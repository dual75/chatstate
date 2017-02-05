import logging

from datetime import datetime

from chatstate import PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, CHAT_TYPE
from chatstate import decorators

LOG = logging.getLogger(__name__)

class ChatContext:

    def __init__(self, dispatcher, chat_id, chat_type, \
                        user_or_group, handler_class):
        self.me = dispatcher.me
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.user_or_group = user_or_group
        self.bot = dispatcher.bot
        self.last_active = datetime.now()
        self.dispatcher = dispatcher
        self._execution = dispatcher.dispatch_execution()
        self._instance = handler_class(self)
        self._register_handlers(self._instance)

    def _register_handlers(self, instance):
        method_handlers = decorators.extract_handlers(self.chat_type, instance)
        self._message_handler = method_handlers[0]
        self._command_handlers = method_handlers[1]
        self._callbackquery_handler = method_handlers[2]
        self._event_handlers = method_handlers[3]
        self._activate_handler = method_handlers[4]
        self._deactivate_handler = method_handlers[5]
        self._newchatmember_handler = method_handlers[6]
        self._leftchatmember_handler = method_handlers[7]

    def handle_event(self, event):
        with self._execution:
            if event['name'] in self._event_handlers:
                for handler in self._event_handlers[event['name']]:
                    handler(event)

    def handle_message(self, update):
        with self._execution:
            self.last_active = datetime.now()
            handlers = []
            if update.message.entities:
                handlers.extend(self._process_entities(update))

            joined_member = update.message.new_chat_member
            if joined_member:
                LOG.debug('User joined, %d %s',
                                joined_member.id, joined_member.username)
                if self._newchatmember_handler:
                    handlers.append(self._newchatmember_handler)

            left_member = update.message.left_chat_member
            if left_member:
                LOG.debug('User left, %d %s',
                                left_member.id, left_member.username)
                if left_member.id == self.bot.id:
                    LOG.debug('removing myself from dispatcher')
                    self.dispatcher.remove_chat_context(self)
                elif self._leftchatmember_handler:
                    handlers.extend(self._leftchatmember_handler)

            handlers.append(self._message_handler)
            LOG.debug('handlers for update: %s', handlers)
            for handler in handlers:
                handler(update)

    def _process_entities(self, update):
        result = []
        for ent in [e for e in update.message.entities]:
            LOG.debug('search entity for %s in %s',
                            ent, tuple(self._command_handlers.keys()))
            entity = update.message.text[ent.offset: ent.offset + ent.length]
            if ent.type == 'bot_command':
                for_me, recipient = False, None
                tokens = self._split_recipient(entity)
                if tokens: command, recipient = tokens
                else: command = entity

                if self.chat_type == PRIVATE:
                    for_me = True
                elif tokens:
                    for_me = recipient == self.me.username

                if for_me:
                    LOG.debug('command to handle %s', command)
                    if command == '/stop':
                        LOG.debug('remove chat %s', self.chat_id)
                        self.dispatcher.remove_chat_context(self)
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
        with self._execution:
            self.last_active = datetime.now()
            result = None
            if self._callbackquery_handler:
                result = self._callbackquery_handler(update)
            try:
                LOG.debug('now aswer callback query...')
                self.bot.answerCallbackQuery(
                    callback_query_id=update.callback_query.id,
                    text=result)
                LOG.debug('ok')
            except Exception as e:
                LOG.exception(e)

    def handle_inline_callback_query(self, update):
        with self._execution:
            self.last_active = datetime.now()

    def on_activate(self):
        with self._execution:
            self.last_active = datetime.now()
            if self._activate_handler:
                self._activate_handler()

    def on_deactivate(self):
        with self._execution:
            self.last_active = datetime.now()
            if self._deactivate_handler:
                self._deactivate_handler()

    def broadcast_event(self, event):
        with self._execution:
            self.dispatcher.broadcast_event(event)

    def send_message(self, text, **kwargs):
        kwargs.setdefault('text', text)
        kwargs.setdefault('parse_mode', 'Markdown')
        return self.bot.sendMessage(self.chat_id, **kwargs)

    def send_photo(self, photo, **kwargs):
        kwargs.setdefault('photo', photo)
        return self.bot.sendPhoto(self.chat_id, **kwargs)


class ContextClassRegistry:

    def __init__(self):
        self.contexts = dict()
        self._chat_type_reg = dict()

    def register_class(self, class_):
        assert decorators.has_chattype(class_)
        for chat_type in class_._TELEGRAM_chattype:
            print(self._chat_type_reg.get(chat_type))
            assert chat_type in CHAT_TYPE.values()
            assert not self._chat_type_reg.get(chat_type)
            self._chat_type_reg[chat_type] = class_

    def class_for_type(self, chat_type):
        assert chat_type in CHAT_TYPE.values()
        return self._chat_type_reg.get(chat_type)


class ContextFactory:

    def __init__(self, class_registry):
        self._clsreg = class_registry

    def new_chat_context(self, dispatcher, chat_id, chat_type, user_or_group):
        result = None
        handler_class = self._clsreg.class_for_type(chat_type)
        if not handler_class and self._clsreg.class_for_type(ANY):
            handler_class = self._clsreg.class_for_type(ANY)
        if handler_class:
            result = ChatContext(dispatcher, chat_id, chat_type, user_or_group,
                                    handler_class)
        return result


class ContextRegistry(object):

    def __init__(self):
        self.contexts = dict()

    def __getitem__(self, key):
        result = self.contexts.get(key)
        return result

    def __setitem__(self, key, value):
        self.contexts[key] = value


class ChatContextManager:

    def __init__(self):
        self._clsregistry = ContextClassRegistry()
        self._ctxregistry = ContextRegistry()
        self._ctxfactory = ContextFactory(self._clsregistry)

    def __getitem__(self, key):
        return self._ctxregistry[key]

    def new_chat_context(self, dispatcher, chat_id, chat_type, user_or_group):
        result = self._ctxfactory.new_chat_context(dispatcher, chat_id, chat_type, user_or_group)
        self._ctxregistry[chat_id] = result
        return result

    def register_class(self, cls_):
        return self._clsregistry.register_class(cls_)



    '''
    def clean_idle_contexts(self):
        LOG.debug('_clean_idle_contexts, {}'.format(len(self._contexts)))
        with self.CTX_LOCK:
            limit = time.time() - self._max_idle_minutes * 60
            deactivation_list = []
            for state in self.contexts.values():
                if state.last_active < limit:
                    state.on_deactivate()
                    deactivation_list.append(state.chat_id)
            for state_id in deactivation_list:
                del(self.contexts[state_id])
                LOG.debug('state %d deleted', state_id)
        self._scheduler.enter(30, 30, self._clean_idle_contexts)
    '''