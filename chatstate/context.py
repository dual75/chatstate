import logging
from datetime import datetime

from chatstate import decorators, CHAT_TYPE


LOG = logging.getLogger(__name__)


class BaseChatContext(object):

    def __init__(self, dispatcher, chat_id, chat_type):
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.activate(dispatcher)

    def activate(self, dispatcher):
        self.last_active = datetime.now()
        self.me = dispatcher.me
        self.bot = dispatcher.bot
        self.dispatcher = dispatcher

    def __getstate__(self):
        result = dict(self.__dict__)
        del result['me']
        del result['bot']
        del result['last_active']
        del result['dispatcher']
        return result

    def __setstate__(self, data):
        self.__dict__ = data

    def register_handler(self, instance):
        self._instance = instance
        method_handlers = decorators.extract_handlers(self.chat_type, instance)
        self._message_handler = method_handlers[0]
        self._command_handlers = method_handlers[1]
        self._document_handler = method_handlers[2]
        self._photo_handler = method_handlers[3]
        self._video_handler = method_handlers[4]
        self._callbackquery_handler = method_handlers[5]
        self._event_handlers = method_handlers[6]
        self._activate_handler = method_handlers[7]
        self._newchatmember_handler = method_handlers[8]
        self._leftchatmember_handler = method_handlers[9]
        self._idle_handler = method_handlers[10]
        self._stop_handler = method_handlers[11]

    def handle_message(self, update):
            self.last_active = datetime.now()
            handlers = []
            if update.message.entities:
                handlers.extend(self._process_entities(update))

            joined_members = update.message.new_chat_members
            if joined_members:
                for member in joined_members:
                    LOG.debug('User joined, %d %s', member.id, member.username)
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
                    handlers.append(self._leftchatmember_handler)

            document = update.message.document
            if document and self._document_handler:
                handlers.append(self._document_handler)

            photo = update.message.photo
            if photo and self._photo_handler:
                handlers.append(self._photo_handler)

            video = update.message.video
            if video and self._video_handler:
                handlers.append(self._video_handler)

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

                if self.chat_type == CHAT_TYPE.PRIVATE:
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
        if len(chunks) == 2: result = chunks
        return result

    def handle_callback_query(self, update):
        self.last_active = datetime.now()
        self._callbackquery_handler and self._callbackquery_handler(update)

    def handle_inline_callback_query(self, update):
        self.last_active = datetime.now()

    def on_activate(self):
        self.last_active = datetime.now()
        self._activate_handler and self._activate_handler(self)

    def on_idle(self):
        result = True
        if self._idle_handler: result = self._idle_handler()
        return result

    def on_stop(self):
        result = True
        if self._stop_handler: result = self._stop_handler()
        return result

    def on_event(self, evt, data):
        if evt in self._event_handlers:
            self.last_active = datetime.now()
            for handler in self._event_handlers[evt]: handler(data)

    def broadcast_event(self, event, data=dict()):
        self.dispatcher.broadcast_event(event, data)

    def send_message(self, text, **kwargs):
        kwargs.setdefault('text', text)
        kwargs.setdefault('parse_mode', 'Markdown')
        return self.bot.sendMessage(self.chat_id, **kwargs)

    def send_audio(self, audio, **kwargs):
        kwargs.setdefault('audio', audio)
        return self.bot.sendAudio(self.chat_id, **kwargs)

    def send_document(self, document, **kwargs):
        kwargs.setdefault('document', document)
        return self.bot.sendDocument(self.chat_id, **kwargs)

    def send_voice(self, voice, **kwargs):
        kwargs.setdefault('voice', voice)
        return self.bot.sendVoice(self.chat_id, **kwargs)

    def send_location(self, latitude, longitude, **kwargs):
        kwargs.setdefault('latitude', latitude)
        kwargs.setdefault('longitude', longitude)
        return self.bot.sendLocation(self.chat_id, **kwargs)

    def send_venue(self, latitude, longitude, title, address, **kwargs):
        kwargs.setdefault('latitude', latitude)
        kwargs.setdefault('longitude', longitude)
        kwargs.setdefault('title', title)
        kwargs.setdefault('address', address)
        return self.bot.sendLocation(self.chat_id, **kwargs)

    def send_chat_action(self, action, **kwargs):
        kwargs.setdefault('action', action)
        return self.bot.sendChatAction(self.chat_id, **kwargs)

    def send_contact(self, first_name, last_name, phone_number, **kwargs):
        kwargs.setdefault('first_name', first_name)
        kwargs.setdefault('last_name', last_name)
        kwargs.setdefault('phone_number', phone_number)
        return self.bot.sendContact(self.chat_id, **kwargs)

    def send_photo(self, photo, **kwargs):
        kwargs.setdefault('photo', photo)
        return self.bot.sendPhoto(self.chat_id, **kwargs)

    def send_video(self, video, **kwargs):
        kwargs.setdefault('video', video)
        return self.bot.sendVideo(self.chat_id, **kwargs)


class PrivateChatContext(BaseChatContext):

    def __init__(self, dispatcher, chat_id, first_name, last_name=None, username=None):
        super().__init__(dispatcher, chat_id, CHAT_TYPE.PRIVATE)
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


class GroupChatContext(BaseChatContext):

    def __init__(self, dispatcher, chat_id, group_name):
        super().__init__(dispatcher, chat_id, CHAT_TYPE.GROUP)
        self.group_name = group_name


class SupergroupChatContext(GroupChatContext):
    pass


class ChannelChatContext(BaseChatContext):

    def __init__(self, dispatcher, chat_id: int, channel_name: str) -> None:
        super().__init__(dispatcher, chat_id, CHAT_TYPE.CHANNEL)
        self.channel_name = channel_name

    def send_message(self, text, **kwargs):
        raise NotImplemented

    def send_audio(self, audio, **kwargs):
        raise NotImplemented

    def send_voice(self, voice, **kwargs):
        raise NotImplemented

    def send_location(self, latitude, longitude, **kwargs):
        raise NotImplemented

    def send_venue(self, latitude, longitude, title, address, **kwargs):
        raise NotImplemented

    def send_chat_action(self, action, **kwargs):
        raise NotImplemented

    def send_contact(self, first_name, last_name, phone_number, **kwargs):
        raise NotImplemented

    def send_photo(self, photo, **kwargs):
        raise NotImplemented

    def send_video(self, video, **kwargs):
        raise NotImplemented


class ChatContextClassRegistry(object):

    def __init__(self):
        self.contexts = dict()
        self._chat_type_reg = dict()

    def register_class(self, class_):
        assert decorators.has_chattype(class_)
        for chat_type in getattr(class_, '_TELEGRAM_chattype'):
            print(self._chat_type_reg.get(chat_type))
            assert not self._chat_type_reg.get(chat_type)
            self._chat_type_reg[chat_type] = class_

    def class_for_type(self, chat_type):
        assert chat_type in CHAT_TYPE
        return self._chat_type_reg.get(chat_type)


class ChatContextFactory(object):

    def __init__(self, class_registry):
        self._clsreg = class_registry

    def new_chat_context(self,
                dispatcher,
                chat_id,
                chat_type,
                username_or_title,
                first_name,
                last_name
                ):
        result = None
        handler_class = self._clsreg.class_for_type(chat_type)
        if not handler_class and self._clsreg.class_for_type(CHAT_TYPE.ANY):
            handler_class = self._clsreg.class_for_type(CHAT_TYPE.ANY)
        if handler_class:
            if chat_type == CHAT_TYPE.PRIVATE:
                result = PrivateChatContext(dispatcher, chat_id, first_name, last_name, username_or_title)
            elif chat_type == CHAT_TYPE.GROUP:
                result = GroupChatContext(dispatcher, chat_id, username_or_title)
            elif chat_type == CHAT_TYPE.SUPERGROUP:
                result = GroupChatContext(dispatcher, chat_id, username_or_title)
            elif chat_type == CHAT_TYPE.CHANNEL:
                result = ChannelChatContext(dispatcher, chat_id, username_or_title)
            result.register_handler(handler_class(result))
        return result


class ChatContextRegistry(object):

    def __init__(self, dispatcher, idle_timeout=1800):
        self.contexts = dict()
        self.idle_timeout = idle_timeout
        self.dispatcher = dispatcher
        self._session = None
        self.post_invocation = None

    def __getitem__(self, key):
        result = self.contexts.get(key)
        return result

    def __setitem__(self, key, value):
        self.contexts[key] = value

    def __delitem__(self, key):
        del self.contexts[key]

    def idle(self):
        now, idle_list = datetime.now(), list()
        for ctx in self.contexts.values():
            LOG.info('ctx %s is being verified, last_active: %s', ctx.chat_id, ctx.last_active)
            if (now - ctx.last_active).seconds > self.idle_timeout:
                active = ctx.on_idle()
                if not active:
                    print('ctx %s is going to be unloaded', ctx.chat_id)
                    idle_list.append(ctx)
        return idle_list


    def all(self):
        return self.contexts.values()


class ChatContextManager(object):

    def __init__(self, dispatcher, ctx_registry):
        self._dispatcher = dispatcher
        self._ctxregistry = ctx_registry
        self._ctxregistry.dispatcher = dispatcher
        self._clsregistry = ChatContextClassRegistry()
        self._ctxfactory = ChatContextFactory(self._clsregistry)

    def __getitem__(self, key):
        return self._ctxregistry[key]

    def new_chat_context(self, chat_id, chat_type, username_or_title, first_name, last_name):
        result = self._ctxfactory.new_chat_context(self._dispatcher, chat_id, chat_type, username_or_title, first_name, last_name)
        self._ctxregistry[chat_id] = result
        return result

    def register_class(self, cls_):
        return self._clsregistry.register_class(cls_)

    def remove_chat_context(self, ctx):
        LOG.debug('delete context chat_id %s', ctx.chat_id)
        del self._ctxregistry[ctx.chat_id]

    def idle(self):
        return self._ctxregistry.idle()

    def all(self):
        return self._ctxregistry.all()

