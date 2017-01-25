import logging
import time
import threading
from datetime import datetime

from chatstate import PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, CHAT_TYPE
from . import reflection
from . import threadpool

class ChatState:
    LOG = logging.getLogger('chatstate.ChatState')

    def __init__(self, dispatcher, chat_id, chat_type, user_or_group, instance, execution):
        self.me = dispatcher.me
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.user_or_group = user_or_group
        self.bot = dispatcher.bot
        self.execution = None
        self.last_active = datetime.now()
        self._dispatcher = dispatcher
        self._instance = instance
        self._execution = execution
        self._register_handlers(instance)

    def _register_handlers(self, instance):
        method_handlers = reflection.extract_handlers(self.chat_type, instance)
        self._message_handlers = method_handlers[0]
        self._command_handlers = method_handlers[1]
        self._callbackquery_handler = method_handlers[2]
        self._event_handlers = method_handlers[3]
        self._activate_handler = method_handlers[4]
        self._deactivate_handler = method_handlers[5]
        self._newchatmember_handlers = method_handlers[6]
        self._leftchatmember_handlers = method_handlers[7]

    def handle_event(self, event):
        with self._execution():
            handlers = self._event_handlers.get(event['name']) or list()
            for handler in handlers:
                handler(self, event)

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
                    self.LOG.debug('removing myself')
                    self._dispatcher.remove_chat_state(self)
                else:
                    handlers.extend(self._leftchatmember_handlers)

            handlers.extend(list(self._message_handlers))
            self.LOG.debug('handlers for update: %s', handlers)
            for handler in handlers:
                handler(self, update)

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
                    self._dispatcher.remove_chat_state(self)
                if command in self._command_handlers:
                    result.extend(self._command_handlers[command])
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
                result = self._callbackquery_handler(self, update)
            self.bot.answerCallbackQuery(callback_query_id=update.callback_query.id, text=result)

    def handle_inline_callback_query(self, update):
        with self._execution():
            self.last_active = time.time()

    def on_activate(self):
        with self._execution():
            self.last_active = time.time()
            if self._activate_handler:
                self._activate_handler(self)

    def on_deactivate(self):
        with self._execution():
            self.last_active = time.time()
            if self._deactivate_handler:
                self._deactivate_handler(self)

    def broadcast_event(self, event):
        with self._execution():
            self._dispatcher.broadcast_event(event)


class NullDispatchExecution(object):

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass


class ChatStateDispatcher:
    LOG = logging.getLogger('chatstate.ChatStateDispatcher')
    STATES_LOCK = threading.RLock()

    def __init__(self, bot, dispatch_execution=NullDispatchExecution, max_idle_minutes=1440, single_thread=False):
        self.bot = bot
        self._chat_type_reg = dict(zip(
                                    (PRIVATE, CHANNEL, GROUP, SUPERGROUP, ANY),
                                    (list(), list(), list(), list(), list())
                                    )
                                )
        self._max_idle_minutes = max_idle_minutes
        self.contexts = {}
        self._pool = threadpool.make_pool(single_thread)
        self._dispatch_execution = dispatch_execution
        self.me = None

    def _clean_idle_states(self):
        self.LOG.debug('_clean_idle_states, {}'.format(len(self.contexts)))
        with self.STATES_LOCK:
            limit = time.time() - self._max_idle_minutes * 60
            deactivation_list = []
            for state in self.contexts.values():
                if state.last_active < limit:
                    state.on_deactivate()
                    deactivation_list.append(state.chat_id)
            for state_id in deactivation_list:
                del(self.contexts[state_id])
                self.LOG.debug('state %d deleted', state_id)
        self._scheduler.enter(30, 30, self._clean_idle_states)

    def _make_chat_state(self, chat_id, chat_type, user_or_group):
        result = None
        with self.STATES_LOCK:
            hcls = self._chat_type_reg.get(chat_type)
            if not hcls and ANY in self._chat_type_reg:
                hcls = self._chat_type_reg[ANY]
            if hcls:
                result = ChatState(self, chat_id, chat_type, user_or_group, hcls(), self._dispatch_execution)
            if result:
                self.contexts[chat_id] = result
        if result:
            self._pool.notify((result.on_activate, tuple(), dict()))
        return result

    def register_class(self, class_):
        assert reflection.has_chattype(class_)
        for ctype in class_._TELEGRAM_chattype:
            assert not self._chat_type_reg.get(ctype)
            self._chat_type_reg[ctype] = class_

    def dispatch_update(self, update):
        if not self.me:
            self.me = self.bot.getMe()
        self.LOG.debug(update)
        assert update is not None
        if update.message:
            self._dispatch_message(update)
        if update.callback_query:
            self._dispatch_callback_query(update)

    def remove_chat_state(self, chat_state):
        del(self.contexts[chat_state.chat_id])

    @staticmethod
    def _extract_chat_data(message):
        chat = message.chat
        chat_id, chat_type = chat.id, CHAT_TYPE[chat.type]
        user_or_group = chat.username if chat_type == PRIVATE else chat.title
        return chat_id, chat_type, user_or_group

    def _dispatch_message(self, update):
        chat_id, chat_type, uog = self._extract_chat_data(update.message)
        chat_state = self.contexts.get(chat_id)
        if not chat_state:
            chat_state = self._make_chat_state(chat_id, chat_type, uog)
        if chat_state:
            self._pool.notify((chat_state.handle_message, (update,), dict()))
        else:
            self.LOG.warn('got update.message for unhandled chat_type: %s', chat_type)

    def _dispatch_callback_query(self, update):
        chat_id, chat_type, uog = self._extract_chat_data(update.callback_query.message)
        chat_state = self.contexts.get(chat_id)
        if not chat_state:
            chat_state = self._make_chat_state(chat_id, chat_type, uog)
        if chat_state:
            self._pool.notify((chat_state.handle_callback_query, (update,), dict()))
        else:
            self.LOG.warn('got update.callback_query for unhandled chat_type: %s', chat_type)

    def broadcast_event(self, event):
        with self.STATES_LOCK:
            for state in self.contexts.values():
                self._pool.notify((state.handle_event, (event,), dict()))

    def start(self):
        self._pool.start()
        self.LOG.debug('dispatcher started')

    def stop(self):
        self._pool.stop()
        self.LOG.debug('dispatcher stopped')

