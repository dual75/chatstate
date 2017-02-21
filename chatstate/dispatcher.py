import logging
import threading

from telegram.error import TelegramError

from chatstate import PRIVATE, CHAT_TYPE
from chatstate import decorators, threadpool
from chatstate.context import ChatContextManager
from chatstate.locking import LOCK

LOG = logging.getLogger(__name__)

EMPTY_DICT = dict()


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
            with LOCK:
                chat_context = self._manager[chat_id]
                if not chat_context:
                    chat_context = self._manager.new_chat_context(
                                self._dispatcher, chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify((chat_context.handle_message, (update,), EMPTY_DICT))
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
            with LOCK:
                chat_context = self._manager[chat_id]
                if not chat_context:
                    chat_context = self._manager.new_chat_context(
                                self._dispatcher, chat_id, chat_type, uog)
        if chat_context:
            self._pool.notify(
                    (chat_context.handle_callback_query, (update,), EMPTY_DICT)
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
        lquery, handler = inline_query.query.lower(), None
        for key in self._dispatcher._inlinequery_reg:
            if key.startswith(lquery.lower()):
                LOG.debug('inlinequery handler %s',
                            self._dispatcher._inlinequery_reg[key])
                handler = self._dispatcher._inlinequery_reg[key]
                break
        if handler:
            self._pool.notify((handler, (self._dispatcher.bot, update), EMPTY_DICT))
        return False


class ChatStateDispatcher:

    LOG = logging.getLogger('chatstate.ChatContextDispatcher')

    def __init__(self, bot, dispatch_execution=NullDispatchExecution,
                                idle_timeout=1800,
                                single_thread=False):
        self.bot = bot
        self.me = None
        self.pool = threadpool.make_pool(single_thread)
        self.manager = ChatContextManager(idle_timeout=idle_timeout)
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
        LOG.debug('begin dispatch_update')
        assert update is not None
        try:
            if not self.me: self.me = self.bot.getMe()
            LOG.debug(update)
            self._processor_chain.process(update)
        except TelegramError as e:
            LOG.exception('errore while dispatch_update', e)

    def idle_check(self):
        removed = []
        LOG.info('Idle check...')
        to_deactivate = self.manager.idle()
        with LOCK:
            for ctx in to_deactivate:
                LOG.info('removing idle chatstate %s', ctx.chat_id)
                self.manager.remove_chat_context(ctx)
                removed.append(ctx)
        return removed

    def broadcast_event(self, event, data=EMPTY_DICT):
        print('all contexts', self.manager.all())
        for ctx in self.manager.all():
            print(event, 'to', ctx.chat_id)
            self.pool.notify((ctx.on_event, (event, data,), EMPTY_DICT))

    def start(self):
        self.pool.start()
        LOG.debug('dispatcher started')

    def stop(self):
        for ctx in self.manager.all():
            self.pool.notify((ctx.on_stop, (), EMPTY_DICT))
        self.pool.stop()
        LOG.debug('dispatcher stopped')
