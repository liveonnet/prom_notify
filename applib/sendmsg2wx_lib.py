import sys
import os
from multiprocessing.managers import SyncManager
from queue import Full
try:
    import readline  # 增加读写历史输入的能力(上下箭头)
except ImportError:
    pass
else:
    readline
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.conf_lib import getConf
from applib.log_lib import get_lan_ip
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


class SendMsg2WeiXin(object):
    """连接 **正在运行** 的pn进程，发送文字到微信
    要求配置中enable_wx 为 true，且itchat中use_custom_manager为 true

    基本过程:
    1 连接到pn进程中的跨进程管理进程，获取itchat使用的发送队列
    2 从标准输入获取内容，分离出目标用户（如果有的话）和文字内容
    3 向itchat发送队列中放要发送的内容和目的用户信息
    """
    def __init__(self, conf_path='config/pn_conf.yaml'):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path)
        self.mgr = None
        self.send_q = None
        if self.conf['prom_notify']['enable_wx']:
            itchat_conf = self.conf['itchat']
            if itchat_conf['use_custom_manager']:
                # create proxy manager
                class MySyncManager(SyncManager):
                    pass
                MySyncManager.register('get_wx_send_q')
                self.mgr = MySyncManager((get_lan_ip(), itchat_conf['custom_manager_port']), itchat_conf['custom_manager_authkey'].encode('utf8'))
                self.mgr.connect()
                self.send_q = self.mgr.get_wx_send_q()  # 获取到了发送队列
            else:
                warn(f'itchat not use custom manager, can\'t send msg via wx !!!')
        else:
            warn(f'wx not enabled, can\'t send msg via wx !!!')

    def run(self):
        """输入格式：
        1 以 -- 开头后面跟用户名，然后空格，后面跟要发送的文字内容
        2 不以 -- 开头，则整个内容为要发送的文字内容，发送给filehelper
        3 如下则发给filehelper，等同于不以 -- 开头直接发送文字内容:
           --filehelper 文字内容
        """
        dft_user = 'filehelper'
        while self.send_q:
            try:
                s = input('<< ')
                s = s.strip()
                if s:
                    if len(s) > 2 and s[0:2] == '--':
                        to, s = s[2:].split(' ', 1)
                    else:
                        to = ''
                    self.send_q.put_nowait([s, to or dft_user])
            except Full:
                warn(f'wx send queue is FULL !!!')
            except (EOFError, KeyboardInterrupt):
                info('break')
                break

        info(f'done')


if __name__ == '__main__':
    sm = SendMsg2WeiXin()
    sm.run()
