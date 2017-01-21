import logging
import time
import threading
from datetime import datetime

from chatstate import PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, CHAT_TYPE
from . import reflection
from . import threadpool

class ChatContext:
    LOG = logging.getLogger('chatstate.ChatContext')

    def __init__(self, dispatcher, chat_id, chat_type, user_or_group, handler_class, execution):
        self.me = dispatcher.me
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.user_or_group = user_or_group
        self.bot = dispatcher.bot
        self.execution = None
        self.last_active = datetime.now()
        self._dispatcher = dispatcher
        self._execution = execution
        self._instance = handler_class(self)
        self._register_handlers(self._instance)

    def _register_handlers(self, instance):
        method_handlers = reflection.extract_handlers(self.chat_type, instance)
        self._message_handler = method_handlers[0]
        self._command_handlers = method_handlers[1]
        self._callbackquery_handler = method_handlers[2]
        self._event_handlers = method_handlers[3]
        self._activate_handler = method_handlers[4]
        self._deactivate_handler = method_handlers[5]
        self._newchatmember_handler = method_handlers[6]
        self._leftchatmember_handler = method_handlers[7]

    def handle_event(self, event):
        with self._execution():
            if event['name'] in self._event_handlers:
                self._event_handlers[event['name']](event)

    def handle_message(self, update):
        with self._execution():
            self.last_active = time.time()
            handlers = []

            if update.message.entities:
                handlers.extend(self._process_entities(update))

            joined_member = update.message.new_chat_member
            if joined_member:
                self.LOG.debug('User joined, %d %s', joined_member.id, joined_member.username)
                handlers.extend(self._newchatmember_handlers)

            left_member = update.message.left_chat_member
            if left_member:
                self.LOG.debug('User left, %d %s', left_member.id, left_member.username)
                if left_member.id == self.bot.id:
                    self.LOG.debug('removing myself from dispatcher')
                    self._dispatcher.remove_chat_context(self)
                else:
                    handlers.extend(self._leftchatmember_handlers)

            handlers.append(self._message_handler)
            self.LOG.debug('handlers for update: %s', handlers)
            for handler in handlers:
                handler(update)

    def _process_entities(self, update):
        result = []
        for ent in [e for e in update.message.entities if e.type == 'bot_command']:
            command = update.message.text[ent.offset: ent.offset + ent.length]
            for_me, recipient = False, None
            tokens = self._split_recipient(command)
            if tokens:
                command, recipient = tokens

            if self.chat_type == PRIVATE:
                for_me = True
            elif tokens:
                for_me = recipient == self.me.username

            if for_me:
                self.LOG.debug('command to handle %s', command)
                if command == '/stop':
                    self.LOG.debug('remove chat %s', self.chat_id)
                    self._dispatcher.remove_chat_context(self)
                if command in self._command_handlers:
                    result.append(self._command_handlers[command])
        return result

    @staticmethod
    def _split_recipient(text):
        result = None
        chunks = text.rsplit('@', 1)
        if len(chunks) == 2:
            result = chunks
        return result

    def handle_callback_query(self, update):
        with self._execution():
            self.last_active = time.time()
            result = None
            if self._callbackquery_handler:
                result = self._callbackquery_handler(update)
            self.bot.answerCallbackQuery(callback_query_id=update.callback_query.id, text=result)

    def handle_inline_callback_query(self, update):
        with self._execution():
            self.last_active = datetime.now()

    def on_activate(self):
        with self._execution():
            self.last_active = time.time()
            if self._activate_handler:
                self._activate_handler()

    def on_deactivate(self):
        with self._execution():
            self.last_active = time.time()
            if self._deactivate_handler:
                self._deactivate_handler()

    def broadcast_event(self, event):
        with self._execution():
            self._dispatcher.broadcast_event(event)


class NullDispatchExecution(object):

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass


class ChatStateDispatcher:
    LOG = logging.getLogger('ChatContext.ChatContextDispatcher')
    CTX_LOCK = threading.RLock()

    def __init__(self, bot, dispatch_execution=NullDispatchExecution, max_idle_minutes=1440, single_thread=False):
        self.bot = bot
        self._chat_type_reg = dict(zip(
                                    (PRIVATE, CHANNEL, GROUP, SUPERGROUP, ANY),
                                    (list(), list(), list(), list(), list())
                                    )
                                )
        self._max_idle_minutes = max_idle_minutes
        self._contexts = {}
        self._pool = threadpool.make_pool(single_thread)
        self._dispatch_execution = dispatch_execution
        self.me = None

    def _clean_idle_contexts(self):
        self.LOG.debug('_clean_idle_contexts, {}'.format(len(self._contexts)))
        with self.CTX_LOCK:
            limit = time.time() - self._max_idle_minutes * 60
            deactivation_list = []
            for state in self._contexts.values():
                if state.last_active < limit:
                    state.on_deactivate()
                    deactivation_list.append(state.chat_id)
            for state_id in deactivation_list:
                del(self._contexts[state_id])
                self.LOG.debug('state %d deleted', state_id)
        self._scheduler.enter(30, 30, self._clean_idle_contexts)

    def _make_chat_context(self, chat_id, chat_type, user_or_group):
        result = None
        with self.CTX_LOCK:
            handler_class = self._chat_type_reg.get(chat_type)
            if not handler_class and ANY in self._chat_type_reg:
                handler_class = self._chat_type_reg[ANY]
            if handler_class:
                result = ChatContext(self, chat_id, chat_type, user_or_group, handler_class, self._dispatch_execution)
            if result:
                self._contexts[chat_id] = result
        if result:
            self._pool.notify((result.on_activate, tuple(), dict()))
        return result

    def register_class(self, class_):
        assert reflection.has_chattype(class_)
        print('current types: %s', self._chat_type_reg)
        for chat_type in class_._TELEGRAM_chattype:
            print('analyze type: %d', chat_type)
            assert class_ not in self._chat_type_reg[chat_type]
            self._chat_type_reg[chat_type] = class_

    def dispatch_update(self, update):
        assert update is not None
        if not self.me:
            self.me = self.bot.getMe()
        self.LOG.debug(update)
        if update.message:
            self._dispatch_message(update)
        if update.callback_query:
            self._dispatch_callback_query(update)

    def remove_chat_context(self, chat_context):
        del(self._contexts[chat_context.chat_id])

    @staticmethod
    def _extract_chat_data(message):
        chat = message.chat
        chat_id, chat_type = chat.id, CHAT_TYPE[chat.type]
        user_or_group = chat.username if chat_type == PRIVATE else chat.title
        return chat_id, chat_type, user_or_group

    def _dispatch_message(self, update):
        chat_id, chat_type, uog = self._extract_chat_data(update.message)
        chat_context = self._contexts.get(chat_id)
        if not chat_context:
            chat_context = self._make_chat_context(chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify((chat_context.handle_message, (update,), dict()))
        else:
            self.LOG.warn('got update.message for unhandled chat_type: %s', chat_type)

    def _dispatch_callback_query(self, update):
        chat_id, chat_type, uog = self._extract_chat_data(update.callback_query.message)
        chat_context = self._contexts.get(chat_id)
        if not chat_context:
            chat_context = self._make_chat_context(chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify((chat_context.handle_callback_query, (update,), dict()))
        else:
            self.LOG.warn('got update.callback_query for unhandled chat_type: %s', chat_type)

    def broadcast_event(self, event):
        with self.CTX_LOCK:
            for ctx in self._contexts.values():
                self._pool.notify((ctx.handle_event, (event,), dict()))

    def start(self):
        self._pool.start()
        self.LOG.debug('dispatcher started')

    def stop(self):
        self._pool.stop()
        self.LOG.debug('dispatcher stopped')

