import logging
import time
from datetime import datetime

from chatstate import PRIVATE, GROUP
from . import decorators

class ChatContext:

    LOG = logging.getLogger('chatstate.ChatContext')

    def __init__(self, dispatcher, chat_id, chat_type, user_or_group, handler_class, execution):
        self.me = dispatcher.me
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.user_or_group = user_or_group
        self.bot = dispatcher.bot
        self.last_active = datetime.now()
        self.dispatcher = dispatcher
        self._execution = execution
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
            self.last_active = time.time()
            handlers = []

            if update.message.entities:
                handlers.extend(self._process_entities(update))

            joined_member = update.message.new_chat_member
            if joined_member:
                self.LOG.debug('User joined, %d %s', joined_member.id, joined_member.username)
                self._newchatmember_handler and handlers.append(self._newchatmember_handler)

            left_member = update.message.left_chat_member
            if left_member:
                self.LOG.debug('User left, %d %s', left_member.id, left_member.username)
                if left_member.id == self.bot.id:
                    self.LOG.debug('removing myself from dispatcher')
                    self.dispatcher.remove_chat_context(self)
                else:
                    self._leftchatmember_handler and handlers.extend(self._leftchatmember_handler)

            handlers.append(self._message_handler)
            self.LOG.debug('handlers for update: %s', handlers)
            for handler in handlers:
                handler(update)

    def _process_entities(self, update):
        result = []
        for ent in [e for e in update.message.entities]:
            self.LOG.debug('search entity for %s in %s',
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
                    self.LOG.debug('command to handle %s', command)
                    if command == '/stop':
                        self.LOG.debug('remove chat %s', self.chat_id)
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
            self.last_active = time.time()
            result = None
            if self._callbackquery_handler:
                result = self._callbackquery_handler(update)
            self.bot.answerCallbackQuery(callback_query_id=update.callback_query.id, text=result)

    def handle_inline_callback_query(self, update):
        with self._execution:
            self.last_active = datetime.now()

    def on_activate(self):
        with self._execution:
            self.last_active = time.time()
            if self._activate_handler:
                self._activate_handler()

    def on_deactivate(self):
        with self._execution:
            self.last_active = time.time()
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

