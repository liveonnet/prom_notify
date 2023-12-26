import sys
import os
import re
from lxml import etree
import json
import js2py
# #from datetime import datetime
# #from datetime import timedelta
#-#from urllib.parse import quote
from urllib.parse import urljoin
from urllib.parse import urlsplit
from urllib.parse import parse_qs
#from urllib.parse import urlparse
from itertools import repeat
from itertools import count
import importlib
import asyncio
from getpass import getuser
if getuser() != 'pi':  # orangepi 上不检查优惠券信息
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException
else:
    webdriver = None
    NoSuchElementException = None
import nest_asyncio
nest_asyncio.apply()
from IPython import embed
embed
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from applib.orm_lib import SisDB, ClDB
from applib.tools_lib import pcformat
from applib.cache_lib import RedisManager
from applib.conf_lib import getConf
from applib.net_lib import NetManager
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error

cached_js_check = None


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

    async def getPostList(self, loop=None):
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
                        data = await mgr.getPostList(_forum, loop)
                    finally:
                        await mgr.clean()
                else:
                    info('找不到处理类 %s', _forum['mgr'])
        finally:
            await self.clean()

        return data

    async def getPost(self, title, url):
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
                embed()
                m = re.search("updateseccode\('([^']+)'\)", ff.page_source)
                if m:
                    s = m.group(1)
                    ff.find_element_by_id('seccodeverify_' + s).click()
            l_c = ff.get_cookies()
            data = ';'.join('{name}={value}'.format(**c) for c in l_c)
        finally:
            ff.quit()

        return data

    async def getPostList(self, forum, loop):
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
                resp, text, ok = await self.net.getData(_sub['url'], timeout=5, my_fmt='str', my_str_encoding='gb18030', headers={'Cookie': cookie} if cookie else None)
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
                        for _i, (_group, _title, _url, _ctime, _utime) in enumerate(zip(l_group, l_title, l_url, l_ctime, l_utime), 1):
                            info(f'[{_group}] {_i}/{len(l_title)} {_title} {_ctime} {_utime}\n--> {urljoin(forum["post_base_url"], _url)}')
                        break
            if save_cookie:
                open(os.path.abspath(forum['cookie_file']), 'w').write(cookie)
                info('saved cookie to %s', forum['cookie_file'])
#-#            break  # debug only
        info('%s 处理完毕', forum['title'])
        return data

    async def getPost(self, title, url):
        """获得帖子内容, 目前只取开帖内容，不取回帖内容
        """


class SisManager(DiscuzManager):
    """获取sis帖子内容
    """
    def __init__(self, conf_path='config/pn_conf.yaml', event_notify=None):
        super().__init__(conf_path, event_notify)
        self.init()
        self.cookie = None
        self.p_size = re.compile('【影片大小】\s*(?:：|:)\s*([^<]+)')

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
                embed()
                m = re.search("updateseccode\('([^']+)'\)", ff.page_source)
                if m:
                    s = m.group(1)
                    ff.find_element_by_id('seccodeverify_' + s).click()
            l_c = ff.get_cookies()
            data = ';'.join('{name}={value}'.format(**c) for c in l_c)
        finally:
            ff.quit()

        return data

    async def getPostList(self, forum, loop):
        """获得帖子列表
        """
        global cached_js_check
        data = None
        #up = urlparse(forum['login_url'])
        #domain = f'http://{up.hostname}/'
        #debug('domain=%s', domain)
        RedisManager.setCfg(self.conf_path, loop)
        rds = await RedisManager.getConn('sis')
        db = SisDB(self.conf_path)
        p_js = re.compile('<script>(.+?)</script>', re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE)
        resp, aes_js, ok = await self.net.getData('http://23.225.255.99/aes.min.js', my_fmt='str')
        if not ok:
            return data
#-#        embed()
        debug('fetching %s ...', forum['title'])
        cookie, _ = self.cookie, False
        for _sub in forum['subforum']:
            if not _sub['enabled']:
                continue
#-#            debug('fetching sub forum %s\n%s ...', _sub['title'], _sub['url'])
            if cookie is None and os.path.exists(forum['cookie_file']):
                cookie = open(forum['cookie_file']).read()
                info('loaded cookie from %s', forum['cookie_file'])
                self.cookie = cookie
            #if False:
            #if cookie is None:
            #    cookie = json.dumps({'CeRaHigh1': 'e5015f46e9b2ab6a9c77c26c6c624aa8'})
            for _page in count(1):
                for _i in range(2):
                    info(f'fetching {_sub["title"]} page {_page} {"again" if _i == 1 else ""} ...')
                    url = _sub['url'].format(page=_page)
                    resp, text, ok = await self.net.getData(url, timeout=5, my_fmt='str', my_str_encoding='utf8', headers={'Cookie': cookie or cached_js_check} if cookie or cached_js_check else None, my_retry=2)
                    if ok:
                        if len(text) > 2000:
                            break
                        elif _i == 0:
                            debug('need process js ?')
                            m = p_js.search(text)
                            if m:
                                js = m.group(1)
                                idx = js.find('document.cookie')
                                js = js[:idx]
                                js += 'function KKK(a,b,c){s="CeRaHigh1="+toHex(slowAES.decrypt(c,2,a,b));return s}KKK(a,b,c);'
                                #debug('%s', js)
                                x = js2py.eval_js(aes_js + '\n' + js)
                                debug('eval js got: %s', x)
                                #_k, _v = x.split('=', 1)
                                #cookie = json.dumps({_k: _v})
                                cookie = x + '; path=/'
                                cached_js_check = cookie
                                url += '&d=1'
                            continue
                        else:
                            debug(f'try js failed')
                            break
                    else:
                        break
                if ok:
                    #debug('---%s', resp.cookies)
#-#                    info('resp %s', pcformat(resp))
                    #info(f'resp text len {len(text)}')
                    pr = etree.HTMLParser()
                    tree = etree.fromstring(text, pr)
                    l_title = tree.xpath(_sub.get('postlist_title') or forum['postlist_title'])
                    if not l_title:
                        break
                    l_type = tree.xpath(_sub.get('postlist_type') or forum['postlist_type'])
#-#                        info(f'{len(l_title)}\n{l_title}')
                    l_url = tree.xpath(_sub.get('postlist_url') or forum['postlist_url'])
                    l_ctime = tree.xpath(_sub.get('postlist_ctime') or forum['postlist_ctime'])
                    l_utime = tree.xpath(_sub.get('postlist_utime') or forum['postlist_utime'])
#-#                    info(f'{len(l_title)} {len(l_url)} {len(l_ctime)} {len(l_utime)}')
                    for _i, (_group, _title, _type, _url, _ctime, _utime) in enumerate(zip(repeat(_sub['title'], len(l_title)), l_title, l_type, l_url, l_ctime, l_utime), 1):
                        # check cache
                        tid = parse_qs(urlsplit(_url).query).get('tid', [None, ])[0]
                        if await rds.checkCounting(f'tid{tid}', 3600):
#-#                            warn(f'already fetched tid {tid}')
                            continue
                        # check db
                        if db.existsRecord(tid):
#-#                            warn(f'already in db, tid={tid}')
                            continue

                        if _type not in _sub.get('ignore_type', []):
                            _upper_title = _title.upper()
                            for _keyword in _sub.get('ignore_keyword', []):
                                if _upper_title.find(_keyword.upper()) != -1:
#-#                                    warn(f'SKIP keyword {_keyword} for {_title}')
                                    break
                            else:
#-#                                info(f'[{_type}] {_i}/{len(l_title)} {_title} {_ctime} {_utime}\n\t--> {urljoin(forum["post_base_url"], _url)}\n\n')
                                try:
                                    _content, _attach_size, _img_list, _attach_info = await self.getPost(_title, _url, forum, _sub, cookie)
                                    if _attach_info:
                                        _aid = parse_qs(urlsplit(_attach_info[1]).query).get('aid', [None, 0])[0]
                                    if _content and _aid:
                                        info(f'\n[{_type}] {_i}/{len(l_title)} {_title} {_ctime} {_utime}\n\t--> {urljoin(forum["post_base_url"], _url)}\n\t {pcformat(_img_list)}\n\t {_attach_size} {_attach_info}\n\n')
                                        db.createRecord(tid=tid, url=_url, title=_title, img_url=json.dumps(_img_list), name=_attach_info[0], size=_attach_size, aid=_aid)
                                except Exception:
                                    warn('got except title: %s', _title, exc_info=True)
#-#                        else:
#-#                            warn(f'SKIP type {_type} for {_title}')
                else:
                    info(f'no ok')
                    break

#-#        RedisManager.info('sis')
        await RedisManager.releaseConn(rds, 'sis')
#-#        RedisManager.info('sis')
        info('%s 处理完毕', forum['title'])
        return data

    async def getPost(self, title, url, forum_cfg, subforum_cfg, cookie):
        """获得帖子内容, 目前只取开帖内容，不取回帖内容
        """
        resp, text, ok = await self.net.getData(urljoin(forum_cfg['post_base_url'], url), timeout=5, my_fmt='str', my_str_encoding='utf8', headers={'Cookie': cookie} if cookie else None)
        content, attach_size, image_list, attach_info = None, 'Unknown', None, None
        if ok:
            pr = etree.HTMLParser()
            tree = etree.fromstring(text, pr)
#-#            info(f'{etree.tounicode(tree)}')
#-#            info(f'{subforum_cfg.get("post_content")} {forum_cfg["post_content"]}')
            post_content = tree.xpath(subforum_cfg.get('post_content') or forum_cfg['post_content'])
            if post_content:
                post_content = post_content[0]
#-#                info(f'{etree.tounicode(content)}')
                content = etree.tounicode(post_content)
                m = self.p_size.search(content)
                if m:
                    attach_size = m.group(1).strip()
#-#                embed()
                attachlist_title = post_content.xpath(forum_cfg['post_attachlist_title'])[0]
                attachlist_url = post_content.xpath(forum_cfg['post_attachlist_url'])[0]
                attach_info = (attachlist_title, urljoin(forum_cfg["post_base_url"], attachlist_url))
                image_list = post_content.xpath('.//img[starts-with(@src, "http")]/@src')
#-#                info(f'{pcformat(image_list)}\n{attach_info}')
            elif '无权' in etree.tounicode(tree):
                info(f'无权查看 {title} {url}')
        return content, attach_size, image_list, attach_info


class ClManager(DiscuzManager):
    """获取caoliu帖子内容
    """
    def __init__(self, conf_path='config/pn_conf.yaml', event_notify=None):
        super().__init__(conf_path, event_notify)
        self.init()
        self.cookie = None
        self.p_size = re.compile('【影片大小】\s*(?:：|:)\s*([^<]+)')

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
                embed()
                m = re.search("updateseccode\('([^']+)'\)", ff.page_source)
                if m:
                    s = m.group(1)
                    ff.find_element_by_id('seccodeverify_' + s).click()
            l_c = ff.get_cookies()
            data = ';'.join('{name}={value}'.format(**c) for c in l_c)
        finally:
            ff.quit()

        return data

    async def getPostList(self, forum, loop):
        """获得帖子列表
        """
        global cached_js_check
        data = None
        #up = urlparse(forum['login_url'])
        #domain = f'http://{up.hostname}/'
        #debug('domain=%s', domain)
        RedisManager.setCfg(self.conf_path, loop)
        rds = await RedisManager.getConn('cl')
        db = ClDB(self.conf_path)
        debug('fetching %s ...', forum['title'])
        cookie, _ = self.cookie, False
        for _sub in forum['subforum']:
            if not _sub['enabled']:
                continue
#-#            debug('fetching sub forum %s\n%s ...', _sub['title'], _sub['url'])
            if cookie is None and os.path.exists(forum['cookie_file']):
                cookie = open(forum['cookie_file']).read()
                info('loaded cookie from %s', forum['cookie_file'])
                self.cookie = cookie
            for _page in count(1):
                got_new = False
                for _i in range(2):
                    info(f'fetching {_sub["title"]} page {_page} {"again" if _i == 1 else ""} ...')
                    url = _sub['url'].format(page=_page)
                    resp, text, ok = await self.net.getData(url, timeout=5, my_fmt='str', my_str_encoding='utf8', headers={'Cookie': cookie or cached_js_check} if cookie or cached_js_check else None, my_retry=2)
                    if ok:
                        if len(text) > 2000:
                            break
                        elif _i == 0:
                            debug('need process js ?')
                            break
                        else:
                            debug(f'try js failed')
                            break
                    else:
                        break
                if ok:
                    #debug('---%s', resp.cookies)
#-#                    info('resp %s', pcformat(resp))
                    #info(f'resp text len {len(text)}')
                    pr = etree.HTMLParser()
                    tree = etree.fromstring(text, pr)
                    l_title = tree.xpath(_sub.get('postlist_title') or forum['postlist_title'])
                    if not l_title:
                        debug(f'no l_title !!!')
                        break
# #                    debug(f'got {len(l_title)} title')
                    l_url = tree.xpath(_sub.get('postlist_url') or forum['postlist_url'])
# #                    debug(f'got {len(l_url)} url')
                    l_tid = tree.xpath(_sub.get('postlist_tid') or forum['postlist_tid'])
                    l_ctime = tree.xpath(_sub.get('postlist_ctime') or forum['postlist_ctime'])
# #                    debug(f'got {len(l_ctime)} ctime')
                    info(f'{len(l_title)} {len(l_url)} {len(l_ctime)}')
                    for _i, (_group, _title, _url, _tid, _ctime) in enumerate(zip(repeat(_sub['title'], len(l_title)), l_title, l_url, l_tid, l_ctime,), 1):
                        # check cache
                        tid = _tid[1:]
                        _ctime = _ctime[:-1]
# #                        debug(f'got {_title=} {tid=} {_url=} {_ctime=}')
                        if await rds.checkCounting(f'tid{tid}', 3600):
# #                            warn(f'already fetched tid {tid}')
                            continue
                        # check db
                        if db.existsRecord(tid):
#-#                            warn(f'already in db, tid={tid}')
                            continue

                        _upper_title = _title.upper()
                        for _keyword in _sub.get('ignore_keyword', []):
                            if _upper_title.find(_keyword.upper()) != -1:
#-#                                    warn(f'SKIP keyword {_keyword} for {_title}')
                                break
                        else:
                            info(f'{_i}/{len(l_title)} {_title} {_ctime}\n\t--> {urljoin(forum["post_base_url"], _url)}\n\n')
                            got_new = True
                            try:
                                _content, _attach_size, _img_list, _attach_info = await self.getPost(_title, _url, forum, _sub, cookie)
                                if _content and _attach_info and _attach_info[0] and _attach_info[1]:
                                    info(f'\n{_i}/{len(l_title)} {_title} {_ctime}\n\t--> {urljoin(forum["post_base_url"], _url)}\n\t {pcformat(_img_list)}\n\t {_attach_size} {_attach_info}\n\n')
                                    db.createRecord(tid=tid, url=_url, title=_title, img_url=json.dumps(_img_list), name=_attach_info[0], size=_attach_size, download_url=_attach_info[1])
                            except Exception:
                                warn('got except title: %s', _title, exc_info=True)
                else:
                    info(f'no ok')
                    break
                if not got_new:
                    break
                if _page >= 1:
                    debug(f'page number >= {_page}, break')
                    break

#-#        RedisManager.info('cl')
        await RedisManager.releaseConn(rds, 'cl')
#-#        RedisManager.info('cl')
        info('%s 处理完毕', forum['title'])
        return data

    async def getPost(self, title, url, forum_cfg, subforum_cfg, cookie):
        """获得帖子内容, 目前只取开帖内容，不取回帖内容
        """
        resp, text, ok = await self.net.getData(urljoin(forum_cfg['post_base_url'], url), timeout=5, my_fmt='str', my_str_encoding='utf8', headers={'Cookie': cookie} if cookie else None)
        content, attach_size, image_list, attach_info = None, 'Unknown', None, None
        if ok:
            pr = etree.HTMLParser()
            tree = etree.fromstring(text, pr)
#-#            info(f'{etree.tounicode(tree)}')
#-#            info(f'{subforum_cfg.get("post_content")} {forum_cfg["post_content"]}')
            post_content = tree.xpath(subforum_cfg.get('post_content') or forum_cfg['post_content'])
            if post_content:
                post_content = post_content[0]
#-#                info(f'{etree.tounicode(content)}')
                content = etree.tounicode(post_content)
                m = self.p_size.search(content)
                if m:
                    attach_size = m.group(1).strip()
#-#                embed()
                attachlist_title = ''
                attachlist_url = ''
                for _url in reversed(post_content.xpath(forum_cfg['post_attachlist_url'])):
                    attachlist_url = _url
                    if _url.find('link.php') != -1:
                        attachlist_title = _url
                        break
                if not attachlist_url:
                    for _title in reversed(post_content.xpath(forum_cfg['post_attachlist_title'])):
                        if _title.find('email') != -1:
                            continue
                        attachlist_title = _title
                        if _title.find('link.php') != -1:
                            break
                        if _title.find('http') == -1:
                            break
                attach_info = (attachlist_title, attachlist_url)
                image_list = post_content.xpath('//div[@class="t t2"]//tr[@class="tr1 do_not_catch"]//div[@class="tpc_content do_not_catch" and @id="conttpc"]//img/@ess-data')
                image_list = [x for x in image_list if x.find('51688.cc') == -1 and x.find('/ads/') == -1 and x.find('slong') == -1 and x.find('https://gdbco.xyz/wp-content/uploads/2021/06/202307061344259.gif') == -1]
#-#                info(f'{pcformat(image_list)}\n{attach_info}')
            elif '无权' in etree.tounicode(tree):
                info(f'无权查看 {title} {url}')
        else:
            debug(f'fetch failed for {url=}')
        return content, attach_size, image_list, attach_info


async def main():
# #        dz = DiscuzManager()
    #dz = QiLanManager()
# #        dz = SisManager()
    dz = ClManager()
    conf = getConf('config/pn_conf.yaml', root_key='discuz')
    for _forum in conf['forum']:
        #if _forum['title'] == '栖兰小筑':
        #    x = await dz.getPostList(_forum, loop)
        #    info(pcformat(x))
        #    break
# #            if _forum['title'] == 'sis':
# #                x = await dz.getPostList(_forum, loop)
# #                info(pcformat(x))
# #                break
        if _forum['title'] == 'cl':
            x = await dz.getPostList(_forum, loop)
            info(pcformat(x))
            break
    await dz.clean()


async def test():
    dz = ClManager()
    await dz.clean()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
# #        x = loop.run_until_complete(main())
        x = loop.run_until_complete(test())
        info(pcformat(x))
    except KeyboardInterrupt:
        info('cancel on KeyboardInterrupt..')
#-#        task.cancel()
        loop.run_forever()
#-#        task.exception()
    finally:
        loop.stop()

