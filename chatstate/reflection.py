import logging
import types

from . chatstate import ANY

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
    message_handlers = list()
    command_handlers = dict()
    callback_query_handler = None
    newchatmember_handlers = list()
    leftchatmember_handlers = list()
    event_handlers = dict()
    activate_handler = deactivate_handler = None
    LOG.debug('register handlers for {} instance'.format(handler))
    for method in methods(handler):
        mtypes = getattr(method, TAG_CHATTYPE)
        LOG.debug('method %s, chat_types: %s', method, mtypes)
        if chat_type in mtypes or ANY in mtypes:
            if hasattr(method, TAG_COMMAND):
                commands = getattr(method, TAG_COMMAND)
                for cmd in commands:
                    LOG.debug('found command handler ' + str(method))
                    command_handlers.setdefault(cmd, []).append(method)
            if hasattr(method, TAG_MESSAGE):
                LOG.debug('found message handler ' + str(method))
                message_handlers.append(method)
            if hasattr(method, TAG_CALLBACKQUERY):
                LOG.debug('found callback_query handler ' + str(method))
                assert callback_query_handler is None
                callback_query_handler = method
            if hasattr(method, TAG_NEWCHATMEMBER):
                LOG.debug('found newchatmember handler ' + str(method))
                newchatmember_handlers.append(method)
            if hasattr(method, TAG_LEFTCHATMEMBER):
                LOG.debug('found leftchatmember handler ' + str(method))
                leftchatmember_handlers.append(method)
            if hasattr(method, TAG_ACTIVATE):
                LOG.debug('found activate ' + str(method))
                assert activate_handler is None
                activate_handler = method
            if hasattr(method, TAG_DEACTIVATE):
                LOG.debug('found deactivate ' + str(method))
                assert deactivate_handler is None
                deactivate_handler = method
            if hasattr(method, TAG_EVENT):
                LOG.debug('found event handler %s', str(method))
                events = getattr(method, TAG_EVENT)
                for evt in events:
                    event_handlers.setdefault(evt, []).append(method)
    return message_handlers, \
            command_handlers, \
            callback_query_handler, \
            event_handlers, \
            activate_handler, \
            deactivate_handler, \
            newchatmember_handlers, \
            leftchatmember_handlers



