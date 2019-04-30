import sys
import os
from datetime import datetime
# #from datetime import timedelta
#-#from sqlalchemy.orm import scoped_session
from sqlalchemy import create_engine
from sqlalchemy import and_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
#-#from sqlalchemy.ext.automap import automap_base
from IPython import embed
embed
from sqlalchemy import Column, BigInteger, Integer, String, DateTime
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
# #from applib.tools_lib import pcformat
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


class SisTorrent(Base):
    __tablename__ = 'sist'

    tid = Column(BigInteger, primary_key=True, autoincrement=False)
    url = Column(String(256))
    title = Column(String(256))
    img_url = Column(String(4096), nullable=True)
    name = Column(String(256))
    size = Column(String(16), nullable=True)
    aid = Column(BigInteger)
    ctime = Column(DateTime, nullable=True, default=datetime.now)


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
                info('create engine for %s echo %s', conn_str, echo)
                engine = create_engine(conn_str, echo=echo)
                SessionMaker._engine[conn_str] = engine
            else:
                info('using cached engine for %s', conn_str)

            info('create sessionmaker for %s', conn_str)
            sf = sessionmaker(bind=engine)
            SessionMaker._sess_factory[conn_str] = sf
#-#        else:
#-#            info('using cached sessionmaker for %s', conn_str)
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
        try:
            x = sess.query(Item.ctime).filter(and_(Item.source == source, Item.sid == sid)).first()
        except Exception:
            error('got error', exc_info=True)
            x = None
        sess.close()
        return True if x else False

    def createItem(self, *args, **kwargs):
        source, sid, show_title, item_url, real_url, pic_url, get_time, sess = \
            map(lambda x, d=kwargs: d.get(x, ''), ('source', 'sid', 'show_title', 'item_url', 'real_url', 'pic_url', 'get_time', 'sess'))
        if not sess:
            sess = self.getSess()
        try:
            item = Item(source=source, sid=sid, show_title=show_title, item_url=item_url, real_url=real_url[:1024], pic_url=pic_url, get_time=get_time)
            sess.add(item)
            sess.commit()
            sess.close()
        except Exception:
            error('create item error', exc_info=True)

    def clean(self):
        pass
#-#        info('closed.')


class SisDB(object):
    def __init__(self, conf_path='config/pn_conf.yaml'):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='orm')
        self.conf = self.conf['sis']
        self.sess_factory = SessionMaker.getSessMaker(self.conf['conn_str'], self.conf['echo'])

    def getSess(self):
        return self.sess_factory()

    def existsRecord(self, tid, sess=None):
        if not sess:
            sess = self.getSess()
        try:
            x = sess.query(SisTorrent.ctime).filter(SisTorrent.tid == tid).first()
        except Exception:
            error('got error', exc_info=True)
            x = None
        sess.close()
        return True if x else False

    def createRecord(self, *args, **kwargs):
        tid, url, title, img_url, name, size, aid, sess = \
            map(lambda x, d=kwargs: d.get(x, ''), ('tid', 'url', 'title', 'img_url', 'name', 'size', 'aid', 'sess'))
        if not sess:
            sess = self.getSess()
        try:
            rcd = SisTorrent(tid=tid, url=url, title=title, img_url=img_url, name=name, size=size, aid=aid)
            sess.add(rcd)
            sess.commit()
            sess.close()
        except Exception:
            error('create record error', exc_info=True)

    def getRecords(self, seconds_ago, page=1, pagesize=10, sess=None):
        ret = None
        if not sess:
            sess = self.getSess()
        try:
            if not page or int(page) < 1:
                page = 1
            start = (int(page) - 1) * pagesize
            ret = sess.query(SisTorrent).filter(SisTorrent.ctime > seconds_ago).order_by(SisTorrent.tid.desc())[start: start + pagesize]
        except Exception:
            error('got error', exc_info=True)
        finally:
            sess.close()
        return ret

    def clean(self):
        pass
#-#        info('closed.')


if __name__ == '__main__':
    def createTable(table_obj):
        conf_path = os.path.abspath('config/pn_conf.yaml')
        conf = getConf(conf_path, root_key='orm')
        conf = conf['sis']
        engine = create_engine(conf['conn_str'], echo=conf['echo'])
#-#        table_obj.__table__.drop(bind=engine)
        table_obj.__table__.create(bind=engine)

#-#    h = HistoryDB()
#-#    info(pcformat(h.getRecentItems('mmb', datetime.now() + timedelta(seconds=-240))))
#-#    info(h.existsItem('mmb', 882564))

# #    createTable(SisTorrent)
    s = SisDB()
#-#    embed()
    info(s.existsRecord(666))
