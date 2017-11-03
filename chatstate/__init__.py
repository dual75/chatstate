from collections import namedtuple

EMPTY_DICT    = dict()
EMPTY_TUPLE   = tuple()

PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, NONE = range(6)

ChatType = namedtuple('ChatType', ('PRIVATE', 'GROUP', 'CHANNEL', 'SUPERGROUP', 'ANY', 'NONE'))
CHAT_TYPE = ChatType(PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, NONE)

ChatTypeName = namedtuple('ChatTypeName', ('private', 'group', 'channel', 'supergroup'))
CHAT_TYPE_NAME = ChatTypeName(PRIVATE, GROUP, CHANNEL, SUPERGROUP)