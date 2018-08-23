import sys
import json
from datetime import datetime
from datetime import timedelta
import time
import os
import redis
import random
from getpass import getuser
from urllib.parse import urlparse
#-#from urllib.parse import urljoin
from urllib.parse import parse_qs
from lxml import etree
import asyncio
#-#import aiohttp
import configparser
import codecs
from difflib import SequenceMatcher
#-#from aiohttp.errors import ClientTimeoutError
#-#from aiohttp.errors import ClientConnectionError
#-#from aiohttp.errors import ClientDisconnectedError
#-#from aiohttp.errors import ContentEncodingError
#-#from aiohttp.errors import ClientError
#-#from aiohttp.errors import HttpBadRequest
#-#from aiohttp.errors import ClientHttpProcessingError
#-#from aiohttp.resolver import AsyncResolver
from setproctitle import setproctitle
import subprocess
import concurrent
import signal
import re
import multiprocessing
import execjs
import webbrowser
from applib.conf_lib import getConf
from applib.manager import MyManager
from applib.net_lib import NetManager
from applib.audio_lib import PlaySound
from applib.qrcode_lib import QrCode
from applib.watch_lib import startWatchConf, stopWatchConf
from applib.filter_lib import FilterTitle
from applib.coupon_lib import CouponManager
from applib.wx_lib import ItchatManager
#-#from applib.db_lib import HistoryDB
#-#from applib.db_lib import Item
from applib.orm_lib import HistoryDB
from applib.tools_lib import htmlentitydecode
from applib.tools_lib import pcformat
from applib.log_lib import app_log

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('connectionpool')
logger.setLevel(logging.INFO)

info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error
event_notify = multiprocessing.Event()
event_exit = asyncio.Event()

premovetag = re.compile('(<.*?>)', re.M | re.S)
#-#exclude_first_div_tag = re.compile(r'\A<div.*?>(.*?)</div>\Z', re.M | re.S)
#-#exclude_first_td_tag = re.compile(r'\A<td.*?>\s*(.*?)\s*</td>\Z', re.M | re.S)
#-#exclude_first_comment_tag = re.compile(r'\A<!-- .*?-->(.*?)<!-- .*?-->\Z', re.M | re.S)
#-#exclude_first_a_tag = re.compile(r'\A<a.*?>\s*(.*?)\s*</a>\Z', re.M | re.S)


async def signal_handler(sig):
    if sig == signal.SIGINT:
        warn('got Ctrl+C')
        if not event_exit.is_set():
            event_exit.set()


class PromNotify(object):
    """main class
    """
    def __init__(self, conf_file='./config/pn_conf.yaml', loop=None):
        # conf
        self.conf_file_path = os.path.abspath(conf_file)
        conf = getConf(self.conf_file_path)
        self.all_conf = conf
        self.conf = self.all_conf['prom_notify']
        # proc title
        setproctitle(self.all_conf['proc_title'])
        # start remote manager
        self.mm = MyManager(self.conf_file_path)
        # audio module 提前创建是为了使子进程占用内存小一点
        self.ps = PlaySound(self.conf_file_path)
        self.loop = loop
        self.net = NetManager(conf_path=self.conf_file_path, loop=self.loop, event_notify=event_notify)
        # history data
#-#        self.his = HistoryDB(self.conf_file_path)
        # progress data
        self.progress = ProgressData(os.path.abspath(self.conf['progress_file']))
        # filter module
        self.filter = FilterTitle(self.conf_file_path, event_notify)
        # coupon module
        self.coupon = None
        if self.conf['enable_coupon']:
            self.coupon = CouponManager(self.conf_file_path, event_notify)

        self.p_price = re.compile(r'\s*(?:￥|券后)?([0-9\.]+)')
        self.p_chinese = re.compile('[\u4e00-\u9fa5]+')

        # 发送内容到微信
        self.wx = None
        if self.conf['enable_wx']:
            self.wx = ItchatManager(self.conf_file_path)

#-#    async def init(self):
#-#        if self.sess is None:
#-#            self.sess = aiohttp.ClientSession(headers={'User-Agent': self.conf['user_agent']})

    async def _getPic(self, pic, raw_data=False):
        '''获取图片数据

        ``raw_data`` True 返回二进制图片数据  False 返回图片文件路径
        '''
        ret = None
        r, picr, ok = await self.net.getData(pic, timeout=5, my_fmt='bytes', my_retry=5)
        if ok:
            if raw_data:
                ret = picr
            else:
                ret = '/tmp/fxx_tmp_icon.jpg'  # 可能被其他协程覆盖，尽量不用这种模式
                open(ret, 'wb').write(await picr.read())
        else:
            warn('pic get status_code %s for %s', picr.status if picr else None, pic)

        return ret

    async def _checkDup(self, from_title, title, his):
        """跨网站查询最近是否有近似的标题内容

        如果有重复返回True, 否则返回False
        """
        ret = False
        seconds_ago = datetime.now() + timedelta(seconds=-180)
        d_tmp = {'慢慢买': 'mmb',
                 '什么值得买': 'smzdm',
                 }
        for _source, _show_title, _ctime in his.getRecentItems(d_tmp[from_title], seconds_ago):
            s = SequenceMatcher(None, _show_title, title)
            if s.ratio() >= 0.8:
                debug('found dup title in %s %s @%s (ratio %s)', _source, _show_title, _ctime, s.ratio())
                ret = True
                break

        return ret

    async def _checkChinese(self, from_title, title):
        """判断标题中是否包含中文

        如果包含则返回True，否则返回False
        """
        ret = False
        if self.p_chinese.search(title):
            ret = True
        else:
            debug('%s no chinese found in title: %s', from_title, title)

        return ret

    async def _notify(self, **kwargs):
        """做根据价格、标题关键字过滤，决定是否做出语音提示
        """
        action, ret_data = 'SKIP', 'IGNORE'
        slience, title, real_url, pic, sbr_time, item_url, from_title, price, his = \
            list(map(lambda x, k=kwargs: k.get(x, ''), ('slience', 'title', 'real_url', 'pic', 'sbr_time', 'item_url', 'from_title', 'price', 'db_his')))

        action, word, extra_data = self.filter.matchFilter(**kwargs)

        # enhance
        if extra_data is None:
            extra_data = {}
        extra_data['from_title'] = from_title
        extra_data['item_url'] = item_url
        extra_data['real_url'] = real_url

        if action != 'SKIP' and await self._checkDup(from_title, title, his):
            action, ret_data = '', ''
            return action, ret_data

        if action == 'NOTIFY':
            action, ret_data = '', word
#-#            if getuser() == 'pi':
#-#                return action, ret_data  # for pi
            # open browser
            cmd = 'notify-send  "%s" "%s at %s"' % (from_title, title.replace('$', '\$').replace('&', '＆'), sbr_time.strftime('%H:%M:%S'))
#-#            debug('EXEC_CMD< %s ...\n%s %s', cmd, item_url, real_url)
            subprocess.Popen(cmd, shell=True).wait()
#-#            # 禁掉open url
            info('ACCEPT open url for word %s in %s', word, title)
#-#            pic_path = await self._getPic(pic)
#-#            webbrowser.get('firefox').open_new_tab('file:///%s' % QrCode.getQrCode(real_url, pic=pic_path))
            pic_data = await self._getPic(pic, raw_data=True)
            if pic_data and getuser() != 'pi':
                webbrowser.get('firefox').open_new_tab('file:///%s' % QrCode.getQrCode(real_url, pic_data=pic_data))
            if not slience:
                self.ps.playTextAsync(title, extra_data)
            else:
                info('[%s] %s (%s) %s --> %s', from_title, title, '/'.join(extra_data['cut_word']), item_url, real_url)
                msg = '[%s] %s (%s) %s --> %s' % (from_title, title, '/'.join(extra_data['cut_word']), item_url, real_url)
                if self.wx:
                    self.wx.q_send.put([msg, ''])
        elif action == 'NORMAL':
            if self.price_check(title, price, extra_data):
                action, ret_data = '', ''
#-#                if getuser() == 'pi':
#-#                    return action, ret_data  # for pi
                if not slience:
                    self.ps.playTextAsync(title, extra_data)
                    if getuser() != 'pi':
                        cmd = 'notify-send  "%s" "%s at %s"' % (from_title, title.replace('$', '\$').replace('&', '＆'), sbr_time.strftime('%H:%M:%S'))
                        subprocess.Popen(cmd, shell=True).wait()
                else:
                    info('[%s] %s (%s) %s --> %s', from_title, title, '/'.join(extra_data['cut_word']), item_url, real_url)
                    msg = '[%s] %s (%s) %s --> %s' % (from_title, title, '/'.join(extra_data['cut_word']), item_url, real_url)
                    if self.wx:
                        self.wx.q_send.put([msg, ''])
        elif action == 'SKIP':
            ret_data = word

        return action, ret_data

    def price_check(self, title, price, extra_data):
        """过滤不关注的价格区间的商品
        """
        m = self.p_price.match(str(price))
        if m:
            v = float(m.group(1))
#-#            info('got price %s from %s', v, price)
            if self.conf['ignore_high_price'] and v >= self.conf['ignore_high_price']:
                debug('ignore high price: %s for %s %s', v, title, price)
                return False
        else:
            warn('price not found: %s|%s', price, title)
        return True

    async def _get_real_url_4mmb(self, url):
        real_url = url
        if url is not None:
            raw_url = url
            nr_redirect = 0
            while url.find('manmanbuy') != -1 and urlparse(url).path:
                r, _, ok = await self.net.getData(url, timeout=7, my_fmt='bytes', my_retry=2)
                nr_redirect += 1
                if ok:
                    if r.status == 200:
                        url = str(r.url)
#-#                        info('url=%s', url)
                        if 'url=' in url:  # found 'url=' or 'tourl='
                            up = urlparse(url)
                            d_p = parse_qs(up.query, encoding='gbk')
                            for _k in ('url', 'tourl'):
                                try:
                                    if _k in d_p:
                                        url = d_p[_k][0]
                                        break
                                except UnicodeDecodeError as e:
                                    warn('d_p %s %s', pcformat(d_p))
                                    raise e
                    elif r.status == 400:
                        url = str(r.url)
                        if 'url=' in url:  # found 'url=' or 'tourl='
                            up = urlparse(url)
                            d_p = parse_qs(up.query, encoding='gbk')
                            for _k in ('url', 'tourl'):
                                try:
                                    if _k in d_p:
                                        url = d_p[_k][0]
                                        break
                                except UnicodeDecodeError as e:
                                    warn('d_p %s %s', pcformat(d_p))
                                    raise e
                        elif url.count('http') > 1:
                            for x in ('http://cu.manmanbuy.com/http', ):
                                if url.startswith(x):
                                    url = raw_url[len(x) - 4:]
                                    if url[0] == 's':  # https
                                        url = url[1:]
                                        info('got %s from ', url, r.url)
                        else:
                            info('real url not found: code %s %s %s', r.status, raw_url, r.url)
                    else:
                        x = 'http://cu.manmanbuy.com/http'
                        y = '.manmanbuy.com/redirectUrl.aspx?'
                        if x in str(r.url):
                            url = r.url[len(x) - 4:]
                            if url[0] == 's':  # https
                                url = url[1:]
#-#                                    debug('url from bad url: %s -> %s', raw_url, url)
                        elif r.url.startswith(('http://detail.tmall.com/', 'https://detail.tmall.com/')):
                            url = str(r.url)
                        elif y in str(r.url):
                            up = urlparse(r.url)
                            d_p = parse_qs(up.query, encoding='gbk')
                            for _k in ('tourl', ):
                                try:
                                    if _k in d_p:
                                        url = d_p[_k][0]
#-#                                                info('found url from %s', d_p)
                                        break
                                except UnicodeDecodeError as e:
                                    warn('d_p %s %s', pcformat(d_p))
                                    raise e
                            if url:
                                break
                        else:
                            warn('real url not found: code %s %s %s', r.status, raw_url, r.url)
                        break
                    if nr_redirect > 5:
                        warn('too many redirect %s', real_url)
                        break
                    if url.endswith('404.html'):
                        if r.history:  # 从历史url中找
                            if 'url=' in str(r.history[-1].url):  # found 'url=' or 'tourl='
                                up = urlparse(str(r.history[-1].url))
                                d_p = parse_qs(up.query, encoding='gbk')
                                for _k in ('url', 'tourl'):
                                    try:
                                        if _k in d_p:
                                            url = d_p[_k][0]
                                            break
                                    except UnicodeDecodeError as e:
                                        warn('d_p %s %s', pcformat(d_p))
                                        raise e
                            else:
                                warn('real url not found: %s (history %s)', real_url, r.history[-1].url)
                        else:
                            warn('real url not found: %s (only found %s)', real_url, url)
                        break
                else:
#-#                            info('fetching url not ok %s', url)
                    break

            real_url = url

        return real_url

    async def check_main_page_mmb(self):
        his = HistoryDB(self.conf_file_path)
#-#        r, text, ok = await self.net.getData('http://cu.manmanbuy.com/cx_0_0_wytj_Default_1.aspx', timeout=10, my_str_encoding='gbk')
        r, text, ok = await self.net.getData('http://zhekou.manmanbuy.com/', timeout=10, my_str_encoding='gbk')
#-#        d_arg = {'DA': datetime.now().strftime('%a %b %d %Y %H:%M:%S') + ' GMT+0800 (CST)',
#-#                 'action': 'Pull-downLoad',
#-#                 'siteid': '0',
#-#                 'sjlx': '0',
#-#                 'tag': '',
#-#                 'yfx': '',
#-#                 }
#-#        r, text, ok = await self.net.getData('http://zhekou.manmanbuy.com/defaultsharelist.aspx', params=d_arg, timeout=5, my_str_encoding='gbk', my_retry=2)

        if not ok:
            return

        if r.status != 200:
            info('got code %s for %s', r.status, r.url)
            return
        pr = etree.HTMLParser()
        tree = etree.fromstring(text, pr)
        l_item = tree.xpath('//li[@class="item"]')
#-#        info('got %s item(s)', len(l_item))
        if not l_item:
            open('/tmp/mmb_source.txt', 'w').write(etree.tostring(tree, encoding='unicode'))


        try:
            for x in l_item:
                try:
                    if event_exit.is_set():
                        info('got exit flag, exit~')
                        break
#-#                    _id = x.xpath('./div[@class="action"]/div[@class="popbox"]/dl/dd[1]/a/@data-id')[0][:]
                    s=x.xpath('.//span[@class="gobuy"]/a[1]/@onclick')[0]
                    _id = re.search('(\d+)', s).group(1)
                    if _id.strip() != _id:
                        error('_id contain space char! %s|', _id)
                        _id = _id.strip()

        #-#                if Item.select().where((Item.source == 'mmb') & (Item.sid == _id)).exists():
                    if his.existsItem('mmb', _id):
        #-#                    info('SKIP EXISTING item mmb %s', _id)
        #-#                    continue
                        break
                    title = x.xpath('./div[@class="content"]/h2/a[1]/text()')[0][:].strip()
#-#                    debug('title %s', title)
                    price = x.xpath('./div[@class="content"]/h2/a[2]/text()')[0][:].strip()
#-#                    debug('price %s', price)
                    if not await self._checkChinese('慢慢买', title):
                        continue
                    show_title = title + ' ' + price
                    pic = x.xpath('div[@class="cover"]/a/img/@original')[0][:]
                    tim = x.xpath('./div[@class="content"]/div[@class="meta"]/div[@class="flinf"]/span/text()')[0][:].strip()
#-#                    debug('tim %s', tim)
                    tim_part_date, tim_part_time = tim.split(' ', 1)
                    tim_part_date = tim_part_date.split('/')
                    if len(tim_part_date[1]) == 1:
                        tim_part_date[1] = '0' + tim_part_date[1]
                    if len(tim_part_date[2]) == 1:
                        tim_part_date[2] = '0' + tim_part_date[2]
                    tim = '/'.join(tim_part_date) + ' ' + tim_part_time
#-#                    debug('tim %s', tim)
                    tim = datetime.strptime(tim, '%Y/%m/%d %H:%M:%S')
                    url = x.xpath('./div[@class="content"]/div[@class="meta"]/div[2][@class="frinf"]/span[@class="gobuy"]/a/@href')[0][:]

                    url = 'http://cu.manmanbuy.com/%s' % (url, )
                    item_url = 'http://cu.manmanbuy.com/Sharedetailed_%s.aspx' % (_id, )
#-#                    debug('id %s title %s price %s, pic %s tim %s url %s item_url %s', _id, title, price, pic, tim, url, item_url)
                    real_url = await self._get_real_url_4mmb(url)
                    real_url = self.get_from_linkstars(real_url, source='mmb')

                    action, data = await self._notify(slience=self.conf['slience'], title=show_title, real_url=real_url, pic=pic, sbr_time=tim, item_url=item_url, from_title='慢慢买', price=price, db_his=his)
                    if getuser() == 'pi' and action in ('NOTIFY', 'NORMAL', ''):
                        info('%s%sadding [%s] %s %s --> %s\n', ('[' + action + ']') if action else '', (data + ' ') if data else '', tim, show_title, item_url, real_url)
                    else:
                        pass
        #-#                    debug('%s%sadding [%s] %s %s --> %s\n', ('[' + action + ']') if action else '', (data + ' ') if data else '', tim, show_title, item_url, real_url)
        #-#                Item.create(source='mmb', sid=_id, show_title=show_title, item_url=item_url, real_url=real_url, pic_url=pic, get_time=tim)
                    his.createItem(source='mmb', sid=_id, show_title=show_title, item_url=item_url, real_url=real_url, pic_url=pic, get_time=tim)
                except (IndexError, ):
                    debug('IndexError')
                    continue
        except:
            error('error ', exc_info=True)
        finally:
            his.clean()

    def get_from_linkstars(self, url, source=''):
        real_url = url
        if url and url.startswith('https://www.linkstars.com/click.php?'):
#-#            debug('%s%slinkstars url found %s', source, ' ' if source else '', url)
            up = urlparse(url)
            d_p = parse_qs(up.query)
            for _k in ('to', ):
                try:
                    if _k in d_p:
                        real_url = d_p[_k][0]
                        break
                except UnicodeDecodeError as e:
                    warn('d_p %s %s', pcformat(d_p))
                    raise e

#-#        if real_url != url:
#-#            debug('%s%sfound url from linkstars %s', source, ' ' if source else '', real_url)
        return real_url or ''

    async def check_main_page(self):
        nr_new = 0
        max_time, min_time = time.time(), time.time()
        his = HistoryDB(self.conf_file_path)

        base_url = '''https://www.smzdm.com/youhui/'''
#-#        debug('base_url = %s', base_url)
        real_url = None
        r, text, ok = await self.net.getData(base_url, timeout=5, my_retry=2)
        if ok:
            if ok and r.status == 200:
                pr = etree.HTMLParser()
                tree = etree.fromstring(text, pr)
                l_item = tree.xpath('/html/body/section[@class="wrap"]//div[@class="list list_preferential "]')
                for x in l_item:
                    if event_exit.is_set():
                        info('got exit flag, exit~')
                        break
                    url = x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a/@href')[0][:]
                    direct_url = None
                    try:
                        direct_url = x.xpath('./div[@class="listRight"]/div[@class="lrBot"]/div[@class="botPart"]/div[@class="buy"]/a/@href')[0]
                    except IndexError:
                        pass
                    title = premovetag.sub('', htmlentitydecode(etree.tostring(x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a')[0]).decode('utf8')))
                    if not await self._checkChinese('什么值得买', title):
                        continue
                    title_price = x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a/span[@class="red"]/text()')
                    if title_price:
                        title_price = title_price[0][:]
                        try:
                            title_noprice = premovetag.sub('', x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a/text()')[0][:])
                        except:
                            error('got except, %s', etree.tostring(x), exc_info=True)
                            continue
#-#                        info('title_noprice: %s', title_noprice)
                        show_title = title_noprice + ' ' + title_price
                    else:
                        show_title = title

                    pic = x.xpath('./a[@class="picLeft"]/img/@src')[0][:]
                    _id = x.attrib['articleid']
                    if _id.strip() != _id:
                        error('_id contain space char! %s|', _id)
                        _id = _id.strip()
                    _id = _id[_id.find('_') + 1:]
                    timesort = int(x.attrib['timesort'])
                    sbr_time = datetime.fromtimestamp(timesort)
                    if min_time is None or timesort < min_time:
                        min_time = timesort
                    if max_time is None or timesort > max_time:
                        max_time = timesort
#-#                    if not Item.select().where((Item.source == 'smzdm') & (Item.sid == _id)).exists():
                    if not his.existsItem('smzdm', _id):
                        nr_new += 1
                        # get real url
                        real_url = None
                        if direct_url is not None:
                            if direct_url.find('/go.smzdm.com/') != -1:
#-#                                debug('getting real_url for %s ...', direct_url)
                                rr, rr_text, ok = await self.net.getData(direct_url, timeout=5)
                                if ok and rr.status == 200:
                                    s_js = re.search(r'eval\((.+?)\)\s+\</script\>', rr_text, re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE).group(1)
                                    s_rs = execjs.eval(s_js)
#-#                                    debug('s_rs: %s', repr(s_rs))
                                    s_key = re.search(r'location\.href=(.+?)}', s_rs).group(1)
#-#                                    debug('s_key: %s', repr(s_key))
                                    m = re.search(r'''%s='(?P<real_url>.+?)';''' % (s_key,), s_rs, re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE)
                                    if m:
                                        real_url = m.group('real_url')
#-#                                        debug('real_url: %s', real_url)
                                    else:
                                        info('can\'t find real_url')
                            else:
                                real_url = direct_url[:]
                        real_url = self.get_from_linkstars(real_url, source='smzdm')

                        if pic[0] == '/':
                            pic = 'http://www.smzdm.com%s' % pic

                        action, data = await self._notify(slience=self.conf['slience'], title=show_title, real_url=real_url, pic=pic, sbr_time=sbr_time, item_url=url, from_title='什么值得买', price=title_price, db_his=his)

                        if getuser() == 'pi' and action in ('NOTIFY', 'NORMAL', ''):
                            info('%s%sadding [%s] %s %s --> %s\n', ('[' + action + ']') if action else '', (data + ' ') if data else '', sbr_time, show_title, url, real_url)
                        else:
                            pass
#-#                            debug('%s%sadding [%s] %s %s --> %s\n', ('[' + action + ']') if action else '', (data + ' ') if data else '', sbr_time, show_title, url, real_url)
#-#                        Item.create(source='smzdm', sid=_id, show_title=show_title, item_url=url, real_url=real_url, pic_url=pic, get_time=sbr_time)
                        his.createItem(source='smzdm', sid=_id, show_title=show_title, item_url=url, real_url=real_url, pic_url=pic, get_time=sbr_time)
                    else:
                        break
#-#                        info('SKIP EXISTING item smzdm %s', _id)
            else:
                info('return code = %d !!!', r.status)

        his.clean()
        return nr_new, max_time, min_time

    async def check_main_page_getmore(self, process_time):
        nr_new = 0
        max_time, min_time = None, None
#-#        base_url = '''https://www.smzdm.com/youhui/json_more'''
        base_url = '''https://faxian.smzdm.com/json_more'''
#-#        debug('base_url = %s', base_url)
        real_url = None
        his = HistoryDB(self.conf_file_path)
        r, text, ok = await self.net.getData(base_url, params={'type': 'a', 'timesort': str(int(process_time))}, timeout=5, my_fmt='json', my_json_encoding='utf8')
        if ok:
            if r.status == 200:
#-#                debug('url %s', r.url)
                l_item = text
                for x in l_item:
                    if event_exit.is_set():
                        info('got exit flag, exit~')
                        break
                    url = x['article_url']
                    direct_url = x['article_link']
                    price = x['article_price']
                    if not await self._checkChinese('什么值得买', x['article_title']):
                        continue
                    show_title = ' '.join((x['article_title'], price))
                    sbr_time = datetime.fromtimestamp(x['timesort'])
                    pic = x['article_pic_url']
                    _id = str(x['article_id'])
                    if _id.strip() != _id:
                        error('_id contain space char! %s|', _id)
                        _id = _id.strip()
                    timesort = x['timesort']
                    if min_time is None or min_time > timesort:
                        min_time = timesort
                    if max_time is None or max_time < timesort:
                        max_time = timesort
#-#                    if not Item.select().where((Item.source == 'smzdm') & (Item.sid == _id)).exists():
                    if not his.existsItem('smzdm', _id):
                        nr_new += 1
                        # get real url
                        real_url = None
                        if direct_url is not None:
                            real_url = None
                            if direct_url.find('/go.smzdm.com/') != -1:
#-#                                debug('getting real_url for %s ...', direct_url)
                                rr, rr_text, ok = await self.net.getData(direct_url, timeout=5)
                                if ok and rr.status == 200:
                                    s_js = re.search(r'eval\((.+?)\)\s+\</script\>', rr_text, re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE).group(1)
                                    s_rs = execjs.eval(s_js)
                                    s_key = re.search(r'location\.href=(.+?)}', s_rs).group(1)
                                    m = re.search(r'''%s='(?P<real_url>.+?)';''' % (s_key,), s_rs, re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE)
                                    if m:
                                        real_url = m.group('real_url')
#-#                                        debug('%s -> %s', direct_url, real_url)
                                    else:
                                        warn('can\'t find real_url')
                            else:
                                real_url = direct_url[:]
                            real_url = self.get_from_linkstars(real_url, source='smzdm')

                        action, data = await self._notify(slience=self.conf['slience'], title=show_title, real_url=real_url, pic=pic, sbr_time=sbr_time, item_url=url, from_title='什么值得买', price=price, db_his=his)
                        if getuser() == 'pi' and action in ('NOTIFY', 'NORMAL', ''):
                            info('%s%sadding [%s] %s %s --> %s\n', ('[' + action + ']') if action else '', (data + ' ') if data else '', sbr_time, show_title, url, real_url)
                        else:
                            pass
#-#                            debug('%s%sadding [%s] %s %s --> %s\n', ('[' + action + ']') if action else '', (data + ' ') if data else '', sbr_time, show_title, url, real_url)
#-#                        if len(x['article_link_list']) > 0:
#-#                            (info if not action else debug)('have more url:\n%s', '\n'.join('%s %s %s' % (_url['name'], _url['buy_btn_domain'], _url['link']) for _url in x['article_link_list']))

#-#                        Item.create(source='smzdm', sid=_id, show_title=show_title, item_url=url, real_url=real_url, pic_url=pic, get_time=sbr_time)
                        his.createItem(source='smzdm', sid=_id, show_title=show_title, item_url=url, real_url=real_url, pic_url=pic, get_time=sbr_time)
                    else:
                        break
#-#                        info('SKIP EXISTING item smzdm %s', _id)
            else:
                info('return code = %d !!!', r.status)

        his.clean()
        return nr_new, max_time, min_time

    async def check_jd_coupon(self):
        nr_total, nr_ignore = 0, 0
        num = None
        rds, k_jd_coupon = redis.Redis(host=self.all_conf['redis']['host'], port=self.all_conf['redis']['port'], db=self.all_conf['redis']['db'], password=self.all_conf['redis']['password']), 'jd_coupon'
        for _idx in range(1, 20):
            cb, page, t = 'jQuery%s' % random.randint(1000000, 9999999), _idx, int(time.time() * 1000)
            headers = {'Accept': 'text/javascript, application/javascript, application/ecmascript, application/x-ecmascript, */*; q=0.01',
                       'Referer': 'https://a.jd.com/?cateId=0',
                       'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:54.0) Gecko/20100101 Firefox/54.0',
                       'X-Requested-With': 'XMLHttpRequest',
                       }
            url = 'https://a.jd.com/indexAjax/getCouponListByCatalogId.html?callback=%s&catalogId=0&page=%s&pageSize=9&_=%s' % (cb, page, t)
            r, text, ok = await self.net.getData(url, timeout=10, my_str_encoding='utf8', headers=headers, my_fmt='str')
            if not ok:
                return
            if r.status != 200:
                info('got code %s for %s', r.status, r.url)
                return
#-#            info('url %s', url)

            text = text[len(cb) + 1: -1]
#-#            info('text %s %s', text[:5], text[-10:])
            try:
                j_data = json.loads(text)
            except:
#-#                error('got except loading json data', exc_info=True)
                error('got except loading json data')
            else:
                if j_data.get('resultCode') != '200' or j_data.get('success') is not True:
                    error('error result')
                else:
                    if num is None:
                        num = j_data['totalNum']
                    if 'couponList' not in j_data:
#-#                        info('no couponList\n%s', pcformat(j_data))
                        break
                    for _item in j_data['couponList']:
                        nr_total += 1
                        if _item['receiveFlag'] == 1:  # 已经领取
                            continue
                        if _item['rate'] == 100:  # 已经抢光
                            continue
                        if rds.hexists(k_jd_coupon, str(_item['roleId'])):
                            nr_ignore += 1
                            continue
                        else:
                            rds.hset(k_jd_coupon, str(_item['roleId']), _item['receiveUrl'])
                        action, word, _ = self.filter.matchFilterCoupon(title=_item['limitStr'])
                        if action == 'SKIP':
                            debug('跳过 %s keyword: %s %s', _item['limitStr'], word, _item['receiveUrl'])
                            nr_ignore += 1
                            continue

                        if _item['receiveUrl'] is None:
                            debug('empty url? skip %s', _item)
                            nr_ignore += 1
                            continue

                        # url补全
                        if not _item['receiveUrl'].startswith('http'):
                            if _item['receiveUrl'].startswith('//'):
                                _item['receiveUrl'] = 'http:' + _item['receiveUrl']
                            else:
                                warn('bad url %s', _item['receiveUrl'])

                        if action == 'NORMAL' or action == 'NOTIFY':
#-#                            info('券 %s %s %s[%s-%s][%s, %s] %s', _item['successLabel'], _item['limitStr'] or'', 'Plus' if _item['ynPlus'] else '', _item['quota'], _item['denomination'], _item['startTime'], _item['endTime'], _item['receiveUrl'])
                            extra_data = {'from_title': 'jd',
                                          'cut_word': '',
                                          'item_url': '',
                                          'real_url': _item['receiveUrl']}
                            title = '优惠券 %s %s %s%s%s%s' % (_item['successLabel'] or '', _item['limitStr'] or '', '满' if _item['quota'].isdigit() else '', _item['quota'], '减' if _item['denomination'].isdigit() else '', _item['denomination'])
                            if _item['quota'] is not None and _item['quota'].isdigit():
                                if int(_item['quota']) > 1500:
                                    debug('%s 面额太高 %s，略过 [%s, %s]', title, _item['quota'], _item['startTime'], _item['endTime'])
                                    continue
                                if _item['denomination'] is not None and _item['denomination'].isdigit():
                                    if '全品类' not in _item['limitStr'] and int(_item['denomination']) and int(_item['quota']) and int(_item['denomination']) / float(_item['quota']) < 0.15:
                                        info('跳过低比例非全品类优惠券 %s', title)
                                        continue

                            if _item['leftTime'] is not None and int(_item['leftTime']) > 0:
#-#                                debug('%s 没到领取时间? %s [%s, %s]', title, _item['leftTime'], _item['startTime'], _item['endTime'])
                                rds.hdel(k_jd_coupon, str(_item['roleId']))
                                continue
                            # 对全品类　按面值过滤
                            if '全品类' in _item['limitStr'] and _item['quota'].isdigit() and int(_item['quota']) >= 2500:
                                info('跳过大面额 %s', title)
                                continue

#-#                            info('FAKE 自动领取 %s', title)
#-#                            continue

                            if not self.conf['slience']:
                                self.ps.playTextAsync(title, extra_data)
                            else:
                                info(title)

                            # 自动领取尝试
#-#                            info('page %s', _idx)
                            await self.coupon.GetJdCouponWithCookie(title, _item)
#-#        info('nr_total %s(%s) nr_ignore %s', nr_total, num, nr_ignore)

        return

    async def clean(self):
        info('cleaning ...')
#-#        if self.sess:
#-#            self.sess.close()
        if self.coupon:
            self.coupon.clean()
        if self.net:
            await self.net.clean()
        if self.filter:
            self.filter.clean()
        if self.ps:
            self.ps.clean()
#-#        if self.his:
#-#            self.his.clean()
        if self.wx:
            self.wx.clean()

    async def do_work_smzdm(self):
        global event_exit
        process_time_sec = time.mktime(self.progress.process_time.timetuple())
        nr_new = None
        interval = self.conf['interval']
        while True:
            nr_new, max_process_time_sec, min_process_time_sec = await self.check_main_page()

            while min_process_time_sec >= process_time_sec:
                process_time_sec = min_process_time_sec
                try:
                    nr_new, _, min_process_time_sec = await self.check_main_page_getmore(process_time_sec)
                except:
                    error('error when chek main page getmore', exc_info=True)

                if event_exit.is_set():
                    info('got exit flag, exit~')
                    break

                if min_process_time_sec is None:  # got net problem
                    min_process_time_sec = process_time_sec
                    await asyncio.sleep(5)
                    continue

                if not nr_new:
                    debug('got %s new item', nr_new)
                    break
                info('getmore nr_new %d min_sec %d(%s)', nr_new, min_process_time_sec, datetime.fromtimestamp(min_process_time_sec))

            process_time_sec = max_process_time_sec
            self.progress.process_time = datetime.fromtimestamp(process_time_sec)

            print('.', end='', file=sys.stderr, flush=True)
            if event_exit.is_set():
                info('got exit flag, exit~')
                break
#-#            await asyncio.sleep(interval)
            try:
                await asyncio.wait_for(event_exit.wait(), interval)
            except concurrent.futures._base.TimeoutError:
                pass
            else:
                info('what\' wrong ?')
            if event_exit.is_set():
                info('got exit flag, exit~')
                break

    async def do_work_mmb(self):
        global event_exit
        interval = self.conf['interval']
        while True:
            await self.check_main_page_mmb()
            print('*', end='', file=sys.stderr, flush=True)
            if event_exit.is_set():
                info('got exit flag, exit~')
                break
#-#            await asyncio.sleep(interval)
            try:
                await asyncio.wait_for(event_exit.wait(), interval)
            except concurrent.futures._base.TimeoutError:
                pass
            else:
                info('what\' wrong ?')
            if event_exit.is_set():
                info('got exit flag, exit~')
                break

    async def do_work_coupon(self):
        global event_exit
        if getuser() == 'pi':  # orangepi 上不检查优惠券信息
            return
        interval = self.conf['interval'] * 3  # 检查时间放长
        while True:
#-#            info('check %s ...', datetime.now())
            await self.check_jd_coupon()
            print('+', end='', file=sys.stderr, flush=True)
            if event_exit.is_set():
                info('got exit flag, exit~')
                break
            try:
                await asyncio.wait_for(event_exit.wait(), min(interval, 60 - float(datetime.now().strftime('%S.%f'))))  # 检查时长=min(指定时长, 距下一整分钟秒数), 保证整分钟时检查
            except concurrent.futures._base.TimeoutError:
                pass
            else:
                info('what\' wrong ?')
            if event_exit.is_set():
                info('got exit flag, exit~')
                break

    async def do_work_jr_coupon(self):
        global event_exit
        if getuser() == 'pi':  # orangepi 上不检查优惠券信息
            return
        interval = 1800  # 最低半小时检查一次
        while True:
#-#            info('check %s ...', datetime.now())
            await self.coupon.GetJdJrCouponWithCookie(self.filter)
            print('$', end='', file=sys.stderr, flush=True)
            if event_exit.is_set():
                info('got exit flag, exit~')
                break
            try:
                x = datetime.now().strftime('%M%S')
                s = 60 * (60 - int(x[:2])) - int(x[2:])
                await asyncio.wait_for(event_exit.wait(), min(interval, s))  # 检查时长=min(指定时长, 距下一整点秒数), 保证整点时检查
            except concurrent.futures._base.TimeoutError:
                pass
            else:
                info('what\' wrong ?')
            if event_exit.is_set():
                info('got exit flag, exit~')
                break

    async def do_work_test_conn(self):
        """网络连通性测试
        """
        global event_exit
        interval = self.conf['interval']
        while True:
            r, text, ok = await self.net.getData('http://www.baidu.com', timeout=5, my_str_encoding='utf8', my_retry=2)
            if ok:
                if r.status != 200:
                    info('got code %s for %s', r.status, r.url)

            print('?', end='', file=sys.stderr, flush=True)
            if event_exit.is_set():
                info('got exit flag, exit~')
                break
#-#            await asyncio.sleep(interval)
            try:
                await asyncio.wait_for(event_exit.wait(), interval)
            except concurrent.futures._base.TimeoutError:
                pass
            else:
                info('what\' wrong ?')
            if event_exit.is_set():
                info('got exit flag, exit~')
                break


    async def do_work_async(self):
        self.loop.add_signal_handler(signal.SIGINT, lambda: asyncio.ensure_future(signal_handler(signal.SIGINT)))

#-#        await self.init()
        wm, notifier, wdd = startWatchConf(self.all_conf['filter']['filter_path'], event_notify)

        debug('doing ...')
        if self.all_conf['only_check_connection']:
            info('只检查网络连通性')
            fut = [self.do_work_test_conn(), ]
        else:
#-#            fut = [self.do_work_smzdm(), self.do_work_mmb(), self.do_work_coupon(), self.do_work_jr_coupon(), self.do_work_test_conn()]
            fut = [self.do_work_smzdm(), self.do_work_mmb(), self.do_work_test_conn()]
            if self.coupon:
                fut.append(self.do_work_coupon())
                fut.append(self.do_work_jr_coupon())
        try:
            await asyncio.gather(*fut)
        except concurrent.futures._base.CancelledError:
            info('Cancel after KeyboardInterrupt ? exit!')

        stopWatchConf(wm, notifier, wdd)
        await self.clean()
        self.progress.saveCfg()

        info('done.')


class ProgressData():
    '''维护处理进度信息
    '''
    def __init__(self, inifile='./config/fx_process.cfg', inifile_encoding='utf8'):
        super(ProgressData, self).__init__()

        self.__inifile_encoding = inifile_encoding
        self.__curdir = os.path.abspath(os.path.dirname(__file__))
        if os.path.abspath(os.curdir) != self.__curdir:
            os.chdir(self.__curdir)
        if not os.path.isabs(inifile):
            self.__inifile = os.path.join(self.__curdir, inifile)
        else:
            self.__inifile = inifile
        self.__cfg = None

        # cfg data
        self.process_time = None  # the time next  process begin with

        self.loadCfg()

    def loadCfg(self):
        self.__cfg = configparser.SafeConfigParser({'youhui_last_process_time': None, })
        if os.path.exists(self.__inifile):
            self.__cfg.readfp(codecs.open(self.__inifile, 'r', self.__inifile_encoding))
            debug('progress data loaded %s', self.__inifile)
        else:
            warn('progress data file not found ! %s', self.__inifile)

        self.process_time = self.__cfg.get('DEFAULT', 'youhui_last_process_time')
        if self.process_time in (None, 'None'):
            _tmp = (datetime.now() + timedelta(minutes=-10)).strftime('%Y%m%d_%H:%M:%S')
            self.process_time = datetime.strptime(_tmp, '%Y%m%d_%H:%M:%S')
        else:
            self.process_time = datetime.strptime(self.process_time, '%Y%m%d_%H:%M:%S')

    def saveCfg(self):
        self.__cfg.set('DEFAULT', 'youhui_last_process_time', self.process_time.strftime('%Y%m%d_%H:%M:%S'))
        with codecs.open(self.__inifile, 'w', self.__inifile_encoding) as _fo:
            self.__cfg.write(_fo)
        info('progress file saved. %s', self.__inifile)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    try:
        task = asyncio.ensure_future(PromNotify(loop=loop).do_work_async())
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        info('cancel on KeyboardInterrupt..')
        task.cancel()
        loop.run_forever()
        task.exception()
    finally:
        try:
            loop.stop()
        except:
            error('got except when stop loop', exc_info=True)
            pass


