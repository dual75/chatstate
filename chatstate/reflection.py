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
    Inspection methods
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



