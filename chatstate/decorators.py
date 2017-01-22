import logging
import types

from chatstate import ANY

TAG_ACTIVATE        = '_TELEGRAM_activate'
TAG_DEACTIVATE      = '_TELEGRAM_deactivate'
TAG_EVENT           = '_TELEGRAM_event'
TAG_MESSAGE         = '_TELEGRAM_message'
TAG_COMMAND         = '_TELEGRAM_command'
TAG_NEWCHATMEMBER   = '_TELEGRAM_newchatmember'
TAG_LEFTCHATMEMBER  = '_TELEGRAM_leftchatmember'
TAG_CALLBACKQUERY   = '_TELEGRAM_callbackquery'
TAG_CHATTYPE        = '_TELEGRAM_chattype'

LOG = logging.getLogger('chatstate.reflection')


'''
    Method decorators
'''
class MethodDecorator:
    def __init__(self, chat_type):
        assert isinstance(chat_type, (int, list, tuple, set))
        self._chat_type = chat_type

    def __call__(self, f):
        return self._update_tag(f, TAG_CHATTYPE, self._chat_type)

    @staticmethod
    def _update_tag(f, tag, value):
        assert tag is not None 
        assert isinstance(tag, str)

        curvals = getattr(f, tag) if hasattr(f, tag) else set()
        if isinstance(value, (list, tuple, set)):
            curvals.update(value)
        else:
            curvals.add(value)
        setattr(f, tag, curvals) 
        return f


class message(MethodDecorator):
    def __call__(self, f):
        f = super(message, self).__call__(f)
        return self._update_tag(f, TAG_MESSAGE, self._chat_type)


class callback_query(MethodDecorator):
    def __call__(self, f):
        f = super(callback_query, self).__call__(f)
        return self._update_tag(f, TAG_CALLBACKQUERY, self._chat_type)


class new_chat_member(MethodDecorator):
    def __call__(self, f):
        f = super(callback_query, self).__call__(f)
        return self._update_tag(f, TAG_NEWCHATMEMBER, self._chat_type)


class left_chat_member(MethodDecorator):
    def __call__(self, f):
        f = super(callback_query, self).__call__(f)
        return self._update_tag(f, TAG_LEFTCHATMEMBER, self._chat_type)


class activate(MethodDecorator):
     def __call__(self, f):
        f = super(activate, self).__call__(f)
        return self._update_tag(f, TAG_ACTIVATE, self._chat_type)


class deactivate(MethodDecorator):
     def __call__(self, f):
        f = super(deactivate, self).__call__(f)
        return self._update_tag(f, TAG_DEACTIVATE, self._chat_type)


class command(MethodDecorator):
    def __init__(self, chat_type, name):
        assert isinstance(name, (str, list, tuple, set))
        self._command = name
        super(command, self).__init__(chat_type)

    def __call__(self, f):
        f = super(command, self).__call__(f)
        return self._update_tag(f, TAG_COMMAND, self._command)
      

class event(MethodDecorator):
    def __init__(self, chat_type, name):
        assert name is not None
        assert isinstance(name, str)
        self._name = name
        super(event, self).__init__(chat_type)

    def __call__(self, f):
        f = super(event, self).__call__(f)
        return self._update_tag(f, TAG_EVENT, self._name)


'''
    Class decorators
'''
class chatstate(MethodDecorator):
    pass


'''
    Inspection functions
'''
def has_chattype(cls):
    return hasattr(cls, TAG_CHATTYPE)

def methods(obj):
    return [method
                for method in map(lambda x: getattr(obj, x), dir(obj))
                if isinstance(method, types.MethodType) and hasattr(method, TAG_CHATTYPE)]

def is_suitable(ctype, ctypes):
    return ctype in ctypes or ANY in ctypes

def extract_handlers(chat_type, handler):
    message_handler = None
    command_handlers = dict()
    callback_query_handler = None
    newchatmember_handler = None
    leftchatmember_handler = None
    event_handlers = dict()
    activate_handler = deactivate_handler = None
    LOG.debug('register handlers for {} instance'.format(handler))
    for method in methods(handler):
        mtypes = getattr(method, TAG_CHATTYPE)
        LOG.debug('method %s, chat_types: %s', method, mtypes)
        if chat_type in mtypes or ANY in mtypes:
            if hasattr(method, TAG_MESSAGE):
                LOG.debug('found message handler ' + str(method))
                assert message_handler is None
                message_handler = method
            if hasattr(method, TAG_COMMAND):
                for cmd in getattr(method, TAG_COMMAND):
                    LOG.debug('found command handler ' + str(method))
                    assert cmd not in command_handlers
                    command_handlers[cmd] = method
            if hasattr(method, TAG_CALLBACKQUERY):
                LOG.debug('found callback_query handler ' + str(method))
                assert callback_query_handler is None
                callback_query_handler = method
            if hasattr(method, TAG_EVENT):
                LOG.debug('found event handler %s', str(method))
                events = getattr(method, TAG_EVENT)
                for evt in events:
                    event_handlers.setdefault(evt, []).append(method)
            if hasattr(method, TAG_ACTIVATE):
                LOG.debug('found activate ' + str(method))
                assert activate_handler is None
                activate_handler = method
            if hasattr(method, TAG_DEACTIVATE):
                LOG.debug('found deactivate ' + str(method))
                assert deactivate_handler is None
                deactivate_handler = method
            if hasattr(method, TAG_NEWCHATMEMBER):
                LOG.debug('found newchatmember handler ' + str(method))
                assert newchatmember_handler is None
                newchatmember_handler = method
            if hasattr(method, TAG_LEFTCHATMEMBER):
                LOG.debug('found leftchatmember handler ' + str(method))
                assert leftchatmember_handler is None
                leftchatmember_handler = method

    return message_handler, \
            command_handlers, \
            callback_query_handler, \
            event_handlers, \
            activate_handler, \
            deactivate_handler, \
            newchatmember_handler, \
            leftchatmember_handler

