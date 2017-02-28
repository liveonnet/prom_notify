import os
import sys
from datetime import datetime
from peewee import SqliteDatabase
from peewee import Proxy
from playhouse.db_url import connect
from peewee import Model, CharField, DateTimeField
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
#-#from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('peewee')
logger.setLevel(logging.INFO)

db_proxy = Proxy()


class BaseModel(Model):
    class Meta:
        database = db_proxy


class Item(BaseModel):
    source = CharField(index=True)
    sid = CharField(index=True)
    show_title = CharField()
    item_url = CharField(null=True)
    real_url = CharField(null=True)
    pic_url = CharField(null=True)
    get_time = CharField(null=True)
    ctime = DateTimeField(null=True, default=datetime.now)


class HistoryDB(object):
    def __init__(self, conf_path='config/pn_conf.yaml'):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='db')
        assert self.conf['type'] in ('sqlite', 'mysql')
        if self.conf['type'] == 'sqlite':
#-#            self.db = SqliteDatabase(os.path.abspath(self.conf['path']), autocommit=False)
            self.db = SqliteDatabase(os.path.abspath(self.conf['path']))
        elif self.conf['type'] == 'db_url':
            # http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#database-url
            # mysql: mysql://user:passwd@ip:port/my_db
            # mysql with pool: mysql+pool://user:passwd@ip:port/my_db?max_connections=20&stale_timeout=300
            # postgresql: postgresql://postgres:my_password@localhost:5432/my_database will
            # sqlit: sqlite:///my_database.db
            # sqlite in memory: sqlite:///:memory:
            self.db = connect(self.conf['path'])
        db_proxy.initialize(self.db)
        self.db.connect()

    def clean(self):
        self.db.close()

#-#    def __getattr__(self, name):
#-#        """直接访问底层的方法
#-#        """
#-#        obj = getattr(self.conn, name)
#-#        if obj:
#-#            return obj
#-#        raise AttributeError('can\'t find attribute %s in %s', repr(name), self)

