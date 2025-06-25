import os
import sys
# #import re
# #from time import sleep
from setproctitle import setproctitle
import multiprocessing
# #from multiprocessing.managers import BaseManager
from multiprocessing.managers import SyncManager
from queue import Queue
# #import concurrent.futures
#-#from ctypes import cdll, CFUNCTYPE, c_char_p, c_int
#-#from contextlib import contextmanager
#-#import shlex
#-#import pyaudio
#-#import subprocess
#-#import asyncio
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
#-#from applib.tools_lib import pcformat
from applib.conf_lib import getConf
#-#from applib.t2s_lib import Text2SpeechXunFei
#-#from applib.t2s_lib import Text2SpeechBaidu
from applib.log_lib import get_lan_ip
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


wx_send_q = Queue()


class MySyncManager(SyncManager):
    pass


MySyncManager.register('get_wx_send_q', callable=lambda: wx_send_q)


def server_manager(address, authkey):
    mgr = MySyncManager(address, authkey)
    setproctitle('process_mgr')
    debug(f'manager server started.')
    server = mgr.get_server()
    server.serve_forever()
    debug(f'manager server stopped.')


class MyManager(object):
    def __init__(self, conf_path='config/pn_conf.yaml'):
        # input param
        self.conf_path = conf_path
        self.conf = getConf(self.conf_path, root_key='remote_manager')
        # create remote manager
        p_mgr = multiprocessing.Process(target=server_manager, args=((get_lan_ip(), self.conf['custom_manager_port']), self.conf['custom_manager_authkey'].encode('utf8')))
        p_mgr.start()


if __name__ == '__main__':
    mm = MyManager()
