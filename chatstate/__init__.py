PRIVATE, GROUP, CHANNEL, SUPERGROUP, ANY = range(5)
CHAT_TYPE = {
    'private'       : PRIVATE,
    'group'         :GROUP,
    'channel'       :CHANNEL,
    'supergroup'    :SUPERGROUP
}


from . state import ChatStateDispatcher

