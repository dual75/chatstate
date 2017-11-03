import logging

from telegram.error import TelegramError

from chatstate import CHAT_TYPE, CHAT_TYPE_NAME, EMPTY_DICT, EMPTY_TUPLE, \
                        threadpool, decorators
from chatstate.context import ChatContextManager, ChatContextRegistry
from chatstate.threadpool import LOCK

LOG = logging.getLogger(__name__)


class UpdateProcessor(object):

    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self._manager = dispatcher.manager
        self._pool = dispatcher.pool
        self._bot = dispatcher.bot
        self._me = dispatcher.me

    @staticmethod
    def responsible_for(update):
        raise NotImplementedError

    def process(self, ex, update):
        raise NotImplementedError


class MessageProcessor(UpdateProcessor):

    @staticmethod
    def responsible_for(update):
        return update.message

    def process(self, exc, update):
        chat_id, chat_type, uog, first_name, last_name = _extract_chat_data(update.message)
        chat_context = self._manager[chat_id]
        if not chat_context:
            with LOCK:
                chat_context = self._manager[chat_id]
                if not chat_context:
                    chat_context = self._manager.new_chat_context(chat_id, chat_type, uog, first_name, last_name)
        if chat_context:
            setattr(exc, 'ctx', chat_context)
            self._pool.notify((chat_context.handle_message, (update,), EMPTY_DICT))
        else:
            LOG.warn('got update.message for unknown chat_type: %s', chat_type)
        return True


def _extract_chat_data(message):
    chat = message.chat
    chat_id, chat_type = chat.id, getattr(CHAT_TYPE_NAME, chat.type)
    user_or_group = chat.username if chat_type == CHAT_TYPE.PRIVATE else chat.title
    return chat_id, chat_type, user_or_group, chat.first_name, chat.last_name


class CallbackQueryProcessor(UpdateProcessor):

    @staticmethod
    def responsible_for(update):
        return update.callback_query

    def process(self, exc, update):
        message = update.callback_query.message
        chat_id, chat_type, uog, first_name, last_name = _extract_chat_data(message)
        chat_context = self._manager[chat_id]
        if not chat_context:
            with LOCK:
                chat_context = self._manager[chat_id]
                if not chat_context:
                    chat_context = self._manager.new_chat_context(chat_id, chat_type, uog, first_name, last_name)
        if chat_context:
            setattr(exc, 'ctx', chat_context)
            self._pool.notify((chat_context.handle_callback_query, (update,), EMPTY_DICT))
        else:
            LOG.warn('callback_query for unknow chat_type: %s', chat_type)
        return False


class InlineQueryProcessor(UpdateProcessor):

    @staticmethod
    def responsible_for(update):
        return update.inline_query

    def process(self, exc, update):
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


class ProcessorChain(object):

    def __init__(self, processors):
        self._processors = processors

    def process(self, exc, update):
        assert exc
        assert update
        for proc in self._processors:
            continue_ = True
            if proc.responsible_for(update):
                continue_ = proc.process(exc, update)
            if not continue_: break


class BaseChatContextManager(object):
    def __init__(self):
        self.ctx = None

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        pass


class ChatContextDispatcher(object):
    def __init__(self,
            bot,
            dispatch_execution=BaseChatContextManager,
            dispatch_execution_kwargs=dict(),
            context_registry=ChatContextRegistry,
            context_registry_kwargs=dict(),
            single_thread=False
            ):
        self.bot = bot
        self.me = None
        self.pool = threadpool.make_pool(single_thread)
        self.manager = ChatContextManager(self, ctx_registry=context_registry(self, **context_registry_kwargs))
        self._dispatch_execution = dispatch_execution
        self._dispatch_execution_kwargs = context_registry_kwargs
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
        with self._dispatch_execution(**self._dispatch_execution_kwargs) as exc:
            try:
                if not self.me:
                    self.me = self.bot.getMe()
                LOG.debug(update)
                self._processor_chain.process(exc, update)
            except TelegramError as e:
                LOG.exception('errore while dispatch_update', e)

    def idle_check(self):
        result = []
        LOG.info('Idle check...')
        to_deactivate = self.manager.idle()
        with LOCK:
            for ctx in to_deactivate:
                LOG.info('removing idle chatstate %s', ctx.chat_id)
                self.manager.remove_chat_context(ctx)
                result.append(ctx)
        return result

    def broadcast_event(self, event: str, data: dict=EMPTY_DICT):
        for ctx in self.manager.all():
            self.pool.notify((ctx.on_event, (event, data), EMPTY_DICT))

    def remove_chat_context(self, ctx):
        self.manager.remove_chat_context(ctx)

    def start(self):
        self.pool.start()
        LOG.debug('dispatcher started')

    def stop(self):
        for ctx in self.manager.all():
            self.pool.notify((ctx.on_stop, EMPTY_TUPLE, EMPTY_DICT))
        self.pool.stop()
        LOG.debug('dispatcher stopped')
