import sys
import os
import re
from lxml import etree
#-#from urllib.parse import quote
import importlib
import asyncio
from getpass import getuser
if getuser() != 'pi':  # orangepi 上不检查优惠券信息
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException
else:
    webdriver = None
    NoSuchElementException = None
from IPython import embed
embed
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.net_lib import NetManager
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


class DiscuzManager(object):
    """获取discuz!论坛中的帖子内容
    """

    def __init__(self, conf_path='config/pn_conf.yaml', event_notify=None):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='discuz')

        self.loop = None
        self.event_notify = event_notify
        if self.conf['geckodriver'] not in sys.path:
            sys.path.append(self.conf['geckodriver'])
        self.net = None

    def init(self):
        """子类才调用
        """
        if self.net is None:
            self.net = NetManager(self.conf_path, self.loop, self.event_notify)

    async def login(self, login_conf):
        """登录操作
        """

    async def getPostList(self):
        """获得帖子列表
        """
        data = None
        try:
            for _forum in self.conf['forum']:
                if not _forum['enabled']:
                    continue
                module_name, class_name = _forum['mgr'].split('.')
                module = importlib.import_module(module_name)
                mgr_class = getattr(module, class_name)
                mgr = mgr_class(self.conf_path, self.event_notify) if mgr_class else None
                if mgr:
                    try:
                        data = await mgr.getPostList(_forum)
                    finally:
                        await mgr.clean()
                else:
                    info('找不到处理类 %s', _forum['mgr'])
        finally:
            await self.clean()

        return data

    async def getPost(self):
        """获得帖子内容, 目前只取开主内容，不取回帖内容
        """

    async def clean(self):
        """子类才调用
        """
        if self.net:
            await self.net.clean()
            self.net = None


class QiLanManager(DiscuzManager):
    """获取栖兰小筑的帖子内容
    """
    def __init__(self, conf_path='config/pn_conf.yaml', event_notify=None):
        super().__init__(conf_path, event_notify)
        self.init()
        self.cookie = None

    async def login(self, forum):
        """登录操作
        """
        data = None
        ff = webdriver.Firefox()
        try:
            ff.get(forum['login_url'])
            m = re.search('loginhash=([^"]+)"', ff.page_source)
            if m:
                h = m.group(1)
                ff.find_element_by_id('username_' + h).send_keys(forum['user'])
                ff.find_element_by_id('password3_' + h).send_keys(forum['password'])
                m = re.search("updateseccode\('([^']+)'\)", ff.page_source)
                if m:
                    s = m.group(1)
                    ff.find_element_by_id('seccodeverify_' + s).click()
            embed()
            l_c = ff.get_cookies()
            data = ';'.join('{name}={value}'.format(**c) for c in l_c)
        finally:
            ff.quit()

        return data

    async def getPostList(self, forum):
        """获得帖子列表
        """
        data = None
        debug('fetching %s ...', forum['title'])
        for _sub in forum['subforum']:
            if not _sub['enabled']:
                continue
            debug('fetching sub forum %s\n%s ...', _sub['title'], _sub['url'])
            cookie, save_cookie = self.cookie, False
            if cookie is None and os.path.exists(forum['cookie_file']):
                cookie = open(forum['cookie_file']).read()
                info('loaded cookie from %s', forum['cookie_file'])
                self.cookie = cookie
            for _ in range(2):
                resp, text, ok = await self.net.getData(_sub['url'], timeout=5, my_fmt='str', my_str_encoding='gbk', headers={'Cookie': cookie} if cookie else None)
                if ok:
#-#                    info('resp %s', pcformat(resp))
                    if '用户名' in text and '密码' in text and '快捷登录' in text:
                        info('没有登录?')
                        self.cookie = None
                        cookie = await self.login(forum)
                        if cookie:
                            info('got new cookie: %s', cookie)
                            save_cookie = True
                            continue
                        else:
                            info('貌似登录不成功 %s 终止获取帖子', forum['title'])
                            return
                    else:
                        pr = etree.HTMLParser()
                        tree = etree.fromstring(text, pr)
                        l_title = tree.xpath(_sub.get('postlist_title') or forum['postlist_title'])
                        # 最新发表/最新回复 有自己的板块
                        if _sub.get('postlist_group'):
                            l_group = tree.xpath(_sub['postlist_group'])
                        else:
                            l_group = [_sub['title'] for _ in range(len(l_title))]
                        l_url = tree.xpath(_sub.get('postlist_url') or forum['postlist_url'])
                        l_ctime = tree.xpath(_sub.get('postlist_ctime') or forum['postlist_ctime'])
                        l_utime = tree.xpath(_sub.get('postlist_utime') or forum['postlist_utime'])
#-#                        if not l_ctime:
#-#                            info('text %s', text)
#-#                            embed()
                        for _i, (_group, _title, _url, _ctime, _utime) in enumerate(zip(l_group, l_title, l_url, l_ctime, l_utime), 1):
                            info('[%s] %s/%s %s %s %s\n%s', _group, _i, len(l_title), _title, _ctime, _utime, _url)
                        break
            if save_cookie:
                open(os.path.abspath(forum['cookie_file']), 'w').write(cookie)
                info('saved cookie to %s', forum['cookie_file'])
#-#            break  # debug only
        info('%s 处理完毕', forum['title'])
        return data

    async def getPost(self):
        """获得帖子内容, 目前只取开帖内容，不取回帖内容
        """


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    try:
        dz = DiscuzManager()
#-#        task = asyncio.ensure_future(dz.getPostList())
#-#        x = loop.run_until_complete(task)
        x = loop.run_until_complete(dz.getPostList())
        info(pcformat(x))
    except KeyboardInterrupt:
        info('cancel on KeyboardInterrupt..')
#-#        task.cancel()
        loop.run_forever()
#-#        task.exception()
    finally:
        loop.stop()



