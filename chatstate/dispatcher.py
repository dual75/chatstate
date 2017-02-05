import logging
import time
import threading

from telegram.error import TelegramError

from chatstate import PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, CHAT_TYPE
from chatstate import decorators, threadpool
from chatstate.context import ChatContextManager

LOG = logging.getLogger(__name__)

class NullDispatchExecution(object):

    def __init__(self):
        self.lock = threading.RLock()

    def __enter__(self):
        self.lock.acquire()
        return self

    def __exit__(self, type, value, traceback):
        self.lock.release()


def _extract_chat_data(message):
    chat = message.chat
    chat_id, chat_type = chat.id, CHAT_TYPE[chat.type]
    user_or_group = chat.username if chat_type == PRIVATE else chat.title
    return chat_id, chat_type, user_or_group


class UpdateProcessor(object):
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self._manager = dispatcher.manager
        self._pool = dispatcher.pool
        self._bot = dispatcher.bot
        self._me = dispatcher.me
        self._dispatch_execution = dispatcher.dispatch_execution

    @staticmethod
    def responsible_for(update):
        raise NotImplementedError

    def process(self, update):
        raise NotImplementedError


class ProcessorChain(object):
    def __init__(self, processors):
        self._processors = processors

    def process(self, update):
        for proc in self._processors:
            continue_ = True
            if proc.responsible_for(update):
                continue_ = proc.process(update)
            if not continue_: break


class MessageProcessor(UpdateProcessor):

    @staticmethod
    def responsible_for(update):
        return update.message

    def process(self, update):
        chat_id, chat_type, uog = _extract_chat_data(update.message)
        chat_context = self._manager[chat_id]
        if not chat_context:
            chat_context = self._manager.new_chat_context(
                                self._dispatcher, chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify((chat_context.handle_message, (update,), dict()))
        else:
            LOG.warn('got update.message for unknown chat_type: %s', chat_type)
        return True


class CallbackQueryProcessor(UpdateProcessor):

    @staticmethod
    def responsible_for(update):
        return update.callback_query

    def process(self, update):
        message = update.callback_query.message
        chat_id, chat_type, uog = _extract_chat_data(message)
        chat_context = self._manager[chat_id]
        if not chat_context:
            chat_context = self._manager.new_chat_context(self._dispatcher,
                                chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify(
                    (chat_context.handle_callback_query, (update,), dict())
                    )
        else:
            LOG.warn('callback_query for unknow chat_type: %s', chat_type)
        return False


class InlineQueryProcessor(UpdateProcessor):

    @staticmethod
    def responsible_for(update):
        return update.inline_query

    def process(self, update):
        inline_query, handler = update.inline_query, None
        lquery = inline_query.query.lower()
        for key in self._inlinequery_reg:
            if lquery.startswith(key.lower()):
                LOG.debug('inlinequery handler %s', self._inlinequery_reg[key])
                handler = self._inlinequery_reg[key]
                break
        if handler:
            self._pool.notify((handler, (self.bot, update), dict()))
        return False


class ChatStateDispatcher:

    LOG = logging.getLogger('chatstate.ChatContextDispatcher')

    def __init__(self, bot, dispatch_execution=NullDispatchExecution,
                                max_idle_minutes=1440, single_thread=False):
        self.bot = bot
        self.me = None
        self.pool = threadpool.make_pool(single_thread)
        self.manager = ChatContextManager()
        self.dispatch_execution = dispatch_execution
        self._inlinequery_reg = dict()
        self._processor_chain = ProcessorChain([
                MessageProcessor(self),
                CallbackQueryProcessor(self),
                InlineQueryProcessor(self)
            ])

    def register_inlinequery_handler(self, function_):
        assert decorators.has_inlinequery(function_)
        for query in function_._TELEGRAM_inlinequery:
            self._inlinequery_reg[query] = function_

    def dispatch_update(self, update):
        assert update is not None
        try:
            if not self.me: self.me = self.bot.getMe()
            LOG.debug(update)
            self._processor_chain.process(update)
        except TelegramError as e:
            LOG.exception(e)

    def broadcast_event(self, event):
        for state in self.register.instances():
            self.pool.notify((state.handle_event, (event,), dict()))

    def start(self):
        self.pool.start()
        LOG.debug('dispatcher started')

    def stop(self):
        self.pool.stop()
        LOG.debug('dispatcher stopped')
