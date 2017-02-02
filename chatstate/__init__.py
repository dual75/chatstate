PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY, NONE = range(6)
CHAT_TYPE = {
    'private':      PRIVATE,
    'group':        GROUP,
    'channel':      CHANNEL,
    'supergroup':   SUPERGROUP,
}


from . dispatcher import ChatStateDispatcher

