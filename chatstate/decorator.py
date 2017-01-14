from .reflection import TAG_ACTIVATE, \
    TAG_DEACTIVATE, \
    TAG_EVENT, \
    TAG_MESSAGE, \
    TAG_COMMAND, \
    TAG_CHATTYPE, \
    TAG_CALLBACKQUERY, \
    TAG_NEWCHATMEMBER, \
    TAG_LEFTCHATMEMBER


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
