import logging

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, PickleType,\
                        UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base

from chatstate.context import PrivateChatContext, ChatContextRegistry
from chatstate.dispatcher import BaseChatContextManager


LOG = logging.getLogger(__name__)

Base = declarative_base()

class SqlContext(Base):

    __tablename__ = 'chatstate_sql_context'

    id              = Column(Integer, primary_key=True)
    chat_id         = Column(Integer, nullable=False)
    bot_name        = Column(String(128), nullable=False)
    chat_type       = Column(Integer, nullable=False)
    username        = Column(String(256), nullable=True)
    first_name      = Column(String(128), nullable=True)
    last_name       = Column(String(128), nullable=True)
    time_access     = Column(DateTime, nullable=False)
    context_data    = Column(PickleType, nullable=False)

    __table_args__ = (
        UniqueConstraint("chat_id", "bot_name"),
    )


class SqlChatContextManager(BaseChatContextManager):

    def __init__(self, session_factory, bot_name):
        self._session_factory = session_factory
        self._bot_name = bot_name
        self.ctx = None

    def __enter__(self):
        LOG.info('__enter__ SqlContextExecution')
        self.session = self._session_factory()
        return self

    def __exit__(self, type, value, traceback):
        LOG.info('__exit__ SqlContextExecution')
        try:
            if value:
                LOG.warning('trapped exception %s', value)
                raise value
            if self.ctx:
                self._pre_exit()
            self.session.commit()
        except Exception as e:
            LOG.exception('Error while executing within contextmanager', e)
            self.session.rollback()
            raise
        finally:
            self.session.close()
            self.session = None

    def _pre_exit(self):
        assert self.session
        self.session.query(SqlContext)\
                .filter_by(chat_id=self.ctx.chat_id, bot_name=self._bot_name)\
                .update({'context_data':self.ctx, 'time_access':datetime.now()})


class SqlChatContextRegistry(ChatContextRegistry):

    def __init__(self,
            dispatcher,
            session_factory,
            bot_name
            ):
        assert dispatcher
        assert session_factory
        assert bot_name
        self.dispatcher = dispatcher
        self._session_factory = session_factory
        self._bot_name = bot_name
        self._enter_count = 0

    def __getitem__(self, chat_id):
        LOG.debug('search for context on db')
        sql_ctx = self._session_factory().query(SqlContext)\
                .filter_by(chat_id=chat_id, bot_name=self._bot_name).first()
        if sql_ctx:
            LOG.debug('found, now restoring')
            result = self._reactivate_chat_context(sql_ctx)
            self._current_ctx = result
        else:
            result = None
        return result

    def __setitem__(self, key, value):
        if type(value) is PrivateChatContext:
            username_or_group = value.username
            first_name, last_name = value.first_name, value.last_name
        else:
            username_or_group = value.group_name
            first_name = last_name = None
        sql_ctx = SqlContext(chat_id=key,
            chat_type=value.chat_type,
            username=username_or_group,
            first_name=first_name,
            last_name=last_name,
            context_data=value,
            time_access=datetime.now(),
            bot_name=self._bot_name
            )
        sql_ctx = self._session_factory().merge(sql_ctx)

    def __delitem__(self, key):
        pass

    def idle(self) -> tuple:
        return tuple()

    def all(self):
        session = self._session_factory()
        for dbctx in session.query(SqlContext).filter_by(bot_name=self._bot_name).all():
            yield self._reactivate_chat_context(dbctx)

    def _reactivate_chat_context(self, sql_ctx):
        assert self.dispatcher.bot
        result = sql_ctx.context_data
        result.activate(self.dispatcher)
        result.on_activate()
        return result

