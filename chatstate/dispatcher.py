import logging
import time
import threading

from telegram.error import TelegramError

from chatstate import PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, CHAT_TYPE
from . import decorators
from . import threadpool
from . state import ChatContext


class NullDispatchExecution(object):

    def __init__(self):
        self.lock = threading.RLock()

    def __enter__(self):
        self.lock.acquire()
        return self

    def __exit__(self, type, value, traceback):
        self.lock.release()


class ChatStateDispatcher:
    LOG = logging.getLogger('chatstate.ChatContextDispatcher')
    CTX_LOCK = threading.RLock()

    def __init__(self, bot, dispatch_execution=NullDispatchExecution, max_idle_minutes=1440, single_thread=False):
        self.bot = bot
        self._chat_type_reg = dict(zip(
                                    (PRIVATE, CHANNEL, GROUP, SUPERGROUP, ANY),
                                    (list(), list(), list(), list(), list())
                                    )
                                )
        self._inlinequery_reg = dict()
        self._max_idle_minutes = max_idle_minutes
        self.contexts = {}
        self._pool = threadpool.make_pool(single_thread)
        self._dispatch_execution = dispatch_execution
        self.me = None

    def _clean_idle_contexts(self):
        self.LOG.debug('_clean_idle_contexts, {}'.format(len(self._contexts)))
        with self.CTX_LOCK:
            limit = time.time() - self._max_idle_minutes * 60
            deactivation_list = []
            for state in self.contexts.values():
                if state.last_active < limit:
                    state.on_deactivate()
                    deactivation_list.append(state.chat_id)
            for state_id in deactivation_list:
                del(self.contexts[state_id])
                self.LOG.debug('state %d deleted', state_id)
        self._scheduler.enter(30, 30, self._clean_idle_contexts)

    def _make_chat_context(self, chat_id, chat_type, user_or_group):
        result = None
        with self.CTX_LOCK:
            handler_class = self._chat_type_reg.get(chat_type)
            if not handler_class and ANY in self._chat_type_reg:
                handler_class = self._chat_type_reg[ANY]
            if handler_class:
                result = ChatContext(self, chat_id, chat_type, user_or_group, handler_class, self._dispatch_execution())
            if result:
                self.contexts[chat_id] = result
        if result:
            self._pool.notify((result.on_activate, tuple(), dict()))
        return result

    def register_class(self, class_):
        assert decorators.has_chattype(class_)
        for chat_type in class_._TELEGRAM_chattype:
            print('analyze type: %d', chat_type)
            assert class_ not in self._chat_type_reg[chat_type]
            self._chat_type_reg[chat_type] = class_

    def register_function(self, function_):
        assert decorators.has_inlinequery(function_)
        for query in function_._TELEGRAM_inlinequery:
            self._inlinequery_reg[query] = function_

    def dispatch_update(self, update):
        assert update is not None
        try:
            if not self.me:
                self.me = self.bot.getMe()
            self.LOG.debug(update)
            if update.message:
                self._dispatch_message(update)
            if update.callback_query:
                self._dispatch_callback_query(update)
            if update.inline_query:
                self._dispatch_inline_query(update)
        except TelegramError as e:
            self.LOG.exception(e)

    def remove_chat_context(self, chat_context):
        del(self.contexts[chat_context.chat_id])

    @staticmethod
    def _extract_chat_data(message):
        chat = message.chat
        chat_id, chat_type = chat.id, CHAT_TYPE[chat.type]
        user_or_group = chat.username if chat_type == PRIVATE else chat.title
        return chat_id, chat_type, user_or_group

    def _dispatch_message(self, update):
        chat_id, chat_type, uog = self._extract_chat_data(update.message)
        chat_context = self.contexts.get(chat_id)
        if not chat_context:
            chat_context = self._make_chat_context(chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify((chat_context.handle_message, (update,), dict()))
        else:
            self.LOG.warn('got update.message for unhandled chat_type: %s', chat_type)

    def _dispatch_callback_query(self, update):
        chat_id, chat_type, uog = self._extract_chat_data(update.callback_query.message)
        chat_context = self.contexts.get(chat_id)
        if not chat_context:
            chat_context = self._make_chat_context(chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify((chat_context.handle_callback_query, (update,), dict()))
        else:
            self.LOG.warn('got update.callback_query for unhandled chat_type: %s', chat_type)

    def _dispatch_inline_query(self, update):
        inline_query, handler = update.inline_query, None
        lquery = inline_query.query.lower()
        for key in self._inlinequery_reg:
            if lquery.startswith(key.lower()):
                self.LOG.debug('inlinequery handler %s', self._inlinequery_reg[key])
                handler = self._inlinequery_reg[key]
                break
        if handler:
            self._pool.notify((handler, (self.bot, update), dict()))

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
