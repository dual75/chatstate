import logging
import sched, time
import threading
import re
from queue import Queue, Empty

import telegram

from . import reflection
from . import threadpool

PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY = range(5)
CHAT_TYPE = {'private':PRIVATE, 'group':GROUP, 'channel':CHANNEL, 'supergroup':SUPERGROUP}

class ChatState:
    LOG = logging.getLogger('chatstate.ChatState')

    def __init__(self, dispatcher, chat_id, chat_type, instance):
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.bot = dispatcher.bot
        self.last_active = time.time()
        self._dispatcher = dispatcher
        self._instance = instance
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
        handlers = self._event_handlers.get(event['name']) or list()
        for handler in handlers:
            handler(self, event)

    def handle_message(self, update):
        self.last_active = time.time()
        text = update.message.text
        handlers = list(self._message_handlers)

        entities = update.message.entities
        if entities:
            for ent in [e for e in entities if e.type == 'bot_command']:
                command = update.message.text[ent.offset: ent.offset + ent.length]
                if command == '/stop':
                    self._dispatcher.remove_chat_state(self)
                if self._command_handlers.get(command):
                    handlers.extend(self._command_handlers[command])

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

        for handler in handlers:
            handler(self, update)

    def handle_callback_query(self, update):
        self.last_active = time.time()
        result = None
        if self._callbackquery_handler:
            result = self._callbackquery_handler(self, update)
        self.bot.answerCallbackQuery(callback_query_id=update.callback_query.id, text=result)

    def handle_inline_callback_query(self, update):
        self.last_active = time.time()

    def on_activate(self):
        self.last_active = time.time()
        if self._activate_handler:
            self._activate_handler(self)

    def on_deactivate(self):
        self.last_active = time.time()
        if self._deactivate_handler:
            self._deactivate_handler(self)

    def broadcast_event(self, event):
        self._dispatcher.broadcast_event(event)


class DispatchExecution:

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        pass


class ChatStateDispatcher:
    LOG = logging.getLogger('chatstate.ChatStateDispatcher')
    STATES_LOCK = threading.RLock()

    def __init__(self, bot, dispatch_execution=DispatchExecution(), max_idle_minutes=48):
        self.bot = bot
        self._chat_type_reg = dict(zip(
                                    (PRIVATE, CHANNEL, GROUP, SUPERGROUP, ANY),
                                    (list(), list(), list(), list(), list())
                                    )
                                )
        self._max_idle_minutes = max_idle_minutes
        self._states = {}
        self._pool = threadpool.make_pool()
        self._dispatch_execution = dispatch_execution


    def _clean_idle_states(self):
        self.LOG.debug('_clean_idle_states, {}'.format(len(self._states)))
        with self.STATES_LOCK:
            limit = time.time() - self._max_idle_minutes * 60
            deactivation_list = []
            for state in self._states.values():
                if state.last_active < limit:
                    state.on_deactivate()
                    deactivation_list.append(state.chat_id)
            for state_id in deactivation_list:
                del(self._states[state_id])
                self.LOG.debug('state %d deleted', chat_id)
        self._scheduler.enter(30, 30, self._clean_idle_states)

    def _make_chat_state(self, chat_id, chat_type):
        result = None
        with self.STATES_LOCK:
            hcls = self._chat_type_reg.get(chat_type)
            if not hcls and self._chat_type_reg.get(ANY):
                hcls = self._chat_type_reg[ANY]
            if hcls:
                result = ChatState(self, chat_id, chat_type, hcls())
            if result:
                self._states[chat_id] = result
        if result:
            self._pool.notify((result.on_activate, tuple(), dict()))
        return result

    def register_class(self, class_):
        assert reflection.has_chattype(class_)
        for ctype in class_._TELEGRAM_chattype:
            assert not self._chat_type_reg.get(ctype)
            self._chat_type_reg[ctype] = class_

    def dispatch_update(self, update):
        assert update is not None
        with self._dispatch_execution:
            if update.message:
                self._dispatch_message(update)
            if update.callback_query:
                self._dispatch_callback_query(update)

    def remove_chat_state(self, chat_state):
        del(self._states[chat_state.chat_id])

    def _dispatch_message(self, update):
        chat_id, chat_type = update.message.chat.id, CHAT_TYPE[update.message.chat.type]
        chat_state = self._states.get(chat_id)
        if not chat_state:
            chat_state = self._make_chat_state(chat_id, chat_type)
        if chat_state:
            self._pool.notify((chat_state.handle_message, (update,), dict()))
        else:
            self.LOG.warn('got update.message for unhandled chat_type: %s', update.message.chat.type)

    def _dispatch_callback_query(self, update):
        chat_id, chat_type = update.callback_query.message.chat.id, CHAT_TYPE[update.callback_query.message.chat.type]
        chat_state = self._states.get(chat_id)
        if not chat_state:
            chat_state = self._make_chat_state(chat_id, chat_type)
        if chat_state:
            self._pool.notify((chat_state.handle_callback_query, (update,), dict()))
        else:
            self.LOG.warn('got update.callback_query for unhandled chat_type: %s', update.message.chat.type)

    def broadcast_event(self, event):
        with self.STATES_LOCK:
            for state in self._states.values():
                self._pool.notify((state.handle_event, (event,), dict()))

    def start(self):
        self._pool.start()
        self.LOG.debug('dispatcher started')

    def stop(self):
        self._pool.stop()
        self.LOG.debug('dispatcher stopped')

