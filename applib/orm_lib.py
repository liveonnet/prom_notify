import sys
import os
from datetime import datetime
from datetime import timedelta
#-#from sqlalchemy.orm import scoped_session
from sqlalchemy import create_engine
from sqlalchemy import and_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
#-#from sqlalchemy.ext.automap import automap_base
from sqlalchemy import Column, Integer, String, DateTime
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


# http://docs.sqlalchemy.org/en/rel_1_1/index.html
Base = declarative_base()
#-#Base = automap_base()


class Item(Base):
    __tablename__ = 'item'

    id = Column(Integer, primary_key=True)
    source = Column(String, index=True)
    sid = Column(String, index=True)
    show_title = Column(String)
    item_url = Column(String, nullable=True)
    real_url = Column(String, nullable=True)
    pic_url = Column(String, nullable=True)
    get_time = Column(String, nullable=True)
    ctime = Column(DateTime, nullable=True, default=datetime.now)

    def __repr__(self):
        return '<%s %s %s>' % (self.source, self.sid, self.show_title)


class Singleton(type):
    _instance = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class SessionMaker():
    _engine = {}
    _sess_factory = {}

    @staticmethod
    def getSessMaker(conn_str, echo):
        sf = SessionMaker._sess_factory.get(conn_str)
        if not sf:
            # get engine
            # TODO 加锁
            engine = SessionMaker._engine.get(conn_str)
            if not engine:
#-#                info('create engine for %s echo %s', conn_str, echo)
                engine = create_engine(conn_str, echo=echo)
                SessionMaker._engine[conn_str] = engine
            else:
                info('using cached engine for %s', conn_str)

#-#            info('create sessionmaker for %s', conn_str)
            sf = sessionmaker(bind=engine)
            SessionMaker._sess_factory[conn_str] = sf
        else:
            info('using cached sessionmaker for %s', conn_str)
        return sf


class HistoryDB(object):
    def __init__(self, conf_path='config/pn_conf.yaml'):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='orm')
        self.sess_factory = SessionMaker.getSessMaker(self.conf['conn_str'], self.conf['echo'])

    def getSess(self):
#-#        return self.sess_factory()
#-#        return scoped_session(self.sess_factory)
        return self.sess_factory()

    def getRecentItems(self, source, seconds_ago, sess=None):
        if not sess:
            sess = self.getSess()
        q = sess.query(Item.source, Item.show_title, Item.ctime).filter(and_(Item.source != source, Item.ctime > seconds_ago))
        ret = q.all()
        sess.close()
#-#        info(pcformat(q.all()))
        return ret

    def existsItem(self, source, sid, sess=None):
        if not sess:
            sess = self.getSess()
        x = sess.query(Item.ctime).filter(and_(Item.source == source, Item.sid == sid)).first()
        sess.close()
        return True if x else False

    def createItem(self, *args, **kwargs):
        source, sid, show_title, item_url, real_url, pic_url, get_time, sess = \
            map(lambda x, d=kwargs: d.get(x, ''), ('source', 'sid', 'show_title', 'item_url', 'real_url', 'pic_url', 'get_time', 'sess'))
        if not sess:
            sess = self.getSess()
        try:
            item = Item(source=source, sid=sid, show_title=show_title, item_url=item_url, real_url=real_url, pic_url=pic_url, get_time=get_time)
            sess.add(item)
            sess.commit()
            sess.close()
        except:
            error('create item error', exc_info=True)

    def clean(self):
        info('closed.')


if __name__ == '__main__':
    h = HistoryDB()
    info(pcformat(h.getRecentItems('mmb', datetime.now() + timedelta(seconds=-240))))
    info(h.existsItem('mmb', 882564))
