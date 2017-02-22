#!/usr/bin/python
#coding=utf8

import sys
import collections
import imp
#-#imp.reload(sys)
#-#sys.setdefaultencoding('utf-8')
#-#import logging
import pickle
from datetime import datetime
from datetime import timedelta
import time
import gzip
import os
from urllib.parse import urlparse
from urllib.parse import urljoin
from urllib.parse import parse_qs
from lxml import etree
import asyncio
import aiohttp
import configparser
import codecs
#-#import requests
from aiohttp.errors import ClientTimeoutError
from aiohttp.errors import ClientConnectionError
#-#from aiohttp.errors import ClientDisconnectedError
from aiohttp.errors import ClientError
from aiohttp.errors import HttpBadRequest
from aiohttp.errors import ClientHttpProcessingError
import html.entities
import subprocess
from IPython import embed
import re
import execjs
import qrcode
from PIL import Image
import pyaudio
import webbrowser
import pyinotify
import fx_conf
from log_lib import app_log

info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error
g_pg, g_db, g_db_file = None, None, None
l_include, l_exclude = None, None
g_changed = None

#-#def _set_trace():
#-#    from IPython.core.debugger import Pdb
#-#    Pdb(color_scheme='Linux').set_trace(sys._getframe().f_back)

premovetag = re.compile('(<.*?>)', re.M | re.S)
#-#exclude_first_div_tag = re.compile(r'\A<div.*?>(.*?)</div>\Z', re.M | re.S)
#-#exclude_first_td_tag = re.compile(r'\A<td.*?>\s*(.*?)\s*</td>\Z', re.M | re.S)
#-#exclude_first_comment_tag = re.compile(r'\A<!-- .*?-->(.*?)<!-- .*?-->\Z', re.M | re.S)
#-#exclude_first_a_tag = re.compile(r'\A<a.*?>\s*(.*?)\s*</a>\Z', re.M | re.S)


def htmlentitydecode(s):
    """http://snipplr.com/view/15261/python-decode-and-strip-html-entites-to-unicode/"""
    # First convert alpha entities (such as &eacute;)
    # (Inspired from http://mail.python.org/pipermail/python-list/2007-June/443813.html)
    def entity2char(m):
        entity = m.group(1)
        if entity in html.entities.name2codepoint:
            return chr(html.entities.name2codepoint[entity])
        return " "  # Unknown entity: We replace with a space.
    t = re.sub('&(%s);' % '|'.join(html.entities.name2codepoint), entity2char, s)

    # Then convert numerical entities (such as &#233;)
    t = re.sub('&#(\d+);', lambda x: chr(int(x.group(1))), t)

    # Then convert hexa entities (such as &#x00E9;)
    return re.sub('&#x(\w+);', lambda x: chr(int(x.group(1), 16)), t)


def _loadDb():
    global g_pg, g_db, g_db_file
    g_pg = aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:35.0) Gecko/20100101 Firefox/35.0'})
    script_dir = os.path.dirname(os.path.abspath(__file__))
    g_db_file = os.path.join(script_dir, 'db.gz')
    g_db = {}
    if os.path.exists(g_db_file):
        g_db = pickle.loads(gzip.open(g_db_file).read())
        info('%d loaded.', len(g_db))


def _loadIncludeExcludeData():
    global l_include, l_exclude
    imp.reload(fx_conf)
    l_include, l_exclude = fx_conf.getConf()
    info('%s include item(s) loaded', len(l_include))
    info('%s exclude item(s) loaded', len(l_exclude))


def _saveDb():
    if len(g_db) > 0:
        info('saving data file (%d)...', len(g_db))
        gzip.open(g_db_file, 'wb').write(pickle.dumps(g_db))


class EventHandler(pyinotify.ProcessEvent):
    def my_init(self, **kwargs):
        self.file2watch = kwargs.get('file2watch')

    def process_default(self, event):
        global g_changed
        if event.pathname not in self.file2watch:
#-#            info("SKIP_FILE %s %s", event.maskname, event.pathname)
            return
        if event.maskname == 'IN_MODIFY':
            if g_changed:
                info('already set changed flag for %s', event.pathname)
            else:
                debug('%s %s%s', event.maskname, event.pathname, '(DIR)' if event.dir else '')
                info('set changed flag for %s', event.pathname)
                g_changed = 1


def startWatchConf():
    '''https://github.com/seb-m/pyinotify/wiki/Tutorial
    http://seb.dbzteam.org/pyinotify/
    '''
    wm, wdd = None, None
    _file, _pathname, _desc = imp.find_module('fx_conf')
    debug('file %s pathname %s desc %s', _file, _pathname, _desc)
    _file.close()
    assert _pathname
    wm = pyinotify.WatchManager()
#-#    mask = pyinotify.IN_CLOSE_WRITE | pyinotify.IN_MODIFY | pyinotify.IN_MOVE_SELF | pyinotify.IN_DELETE_SELF | pyinotify.IN_CREATE
    mask = pyinotify.IN_MODIFY
    info('inotify check start')
    eh = EventHandler(file2watch=[_pathname, ])
    try:
        notifier = pyinotify.ThreadedNotifier(wm, eh)
        notifier.start()
        wdd = wm.add_watch(os.path.dirname(_pathname), mask)
    except:
        error('got except, break ~', exc_info=True)
        pass

    return wm, notifier, wdd


def stopWatchConf(wm, notifier, wdd):
    wm.rm_watch(list(wdd.values()))
    notifier.stop()
#-#    wm.close()
    info('inotify check done')


class Dummy(object):
    '''支持pickle的基类
    '''
    def __getstate__(self):
        d_var = dict((k, v) for k, v in self.__dict__.items() if (not k.startswith('__')) and (not isinstance(v, collections.Callable)))
#-#        print 'd_var = %s'%(d_var, )
        return d_var

    def __setstate(self, state):
        self.__dict__.update(state)


def utf82unicode(m):
    # change u'\xe6\xa0\xbc\xe5\x85\xb0\xe4\xbb\x95' to '\xe6\xa0\xbc\xe5\x85\xb0\xe4\xbb\x95'
    # decode utf8 string in unicode
    tmp = ''.join([chr(int(x, 16)) for x in re.findall(r'\\x(\w{2})', repr(m.group(0)))])
    tmp_s = tmp[:]
    # remove invalid continuous \xa0
    tmp_s = tmp_s.replace('\xa0\xa0\xa0', '')
    tmp_s = tmp_s.replace('\xa0\xa0', '')

    if tmp_s not in ('\xb0', '\xba', '\xb2', '\xbc', '\xb4', '\xb7', '\xbc', '\xbd', '\xd7', '\xae', '\xe9', '\xe8', '\xd6', '\xf1', '\xa0', '\xa5', '\xf3', '\xa3', '\xdc', '\xfc', '\xb1', '\xb7', '\xe4', '\xed', '\xe0', '\xc9', '\xc8', '\xd4', '\xea', '\xc4', '\xfa', '\xab', '\xf6', '\xf6\xdf', '\xf4', '\xe1', '\xd3', '\xc5', '\xeb'):
        try:
            return tmp_s.decode('utf8')
        except UnicodeError as e:
            print('tmp_s=%s, e=%s' % (repr(tmp_s), e))
            raise e
        except UnicodeDecodeError as e:
            print('tmp_s=%s, e=%s' % (repr(tmp_s), e))
            return ''.join(chr(ord(_c)) for _c in tmp_s)
    else:
        try:
            return chr(ord(tmp_s))
        except (TypeError, UnicodeDecodeError) as e:
            print('tmp_s=%s, e=%s' % (repr(tmp_s), e))
            return ''.join(chr(ord(_c)) for _c in tmp_s)
#-#        return unicode(tmp_s)


class ProgressData(Dummy):
    '''维护处理进度信息
    '''
    def __init__(self, inifile='fx_process.cfg', inifile_encoding='utf8'):
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


def getQrCode(url, **kwargs):
    '''生成二维码
    '''
    pic = kwargs.get('pic')
    f_name = '/tmp/fxx_tmp_qrcode.png'
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_H if pic else qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(url)
    qr.make(True)
    img = qr.make_image()
    img = img.convert('RGBA')
#-#    info('img %s %s', img.format, img.mode)
    if pic:
        icon = Image.open(pic)
        if img.format != 'PNG':
            convert_path = '/tmp/fxx_tmp_icon_convert_png.png'
            icon.save(convert_path)
            icon = Image.open(convert_path)
#-#            info('icon %s %s %s', icon.format, icon.mode, convert_path)
        img_w, img_h = img.size
        factor = 4
        size_w, size_h = int(img_w / factor), int(img_h / factor)
        icon_w, icon_h = icon.size
        if icon_w > size_w:
            icon_w = size_w
        if icon_h > size_h:
            icon_h = size_h
        icon = icon.resize((icon_w, icon_h), Image.ANTIALIAS)
        w = int((img_w - icon_w) / 2)
        h = int((img_h - icon_h) / 2)
#-#        img.paste(icon, (w, h), icon)
        img.paste(icon, (w, h))
    img.save(f_name)
    return f_name


async def getPic(pic):
    '''获取图片数据
    '''
    picfilepath = '/tmp/fxx_tmp_icon.jpg'
    nr_try = 5
    while nr_try:
        pr = urlparse(pic)
        if not pr.scheme:
            new_pic = urljoin('http://', pic)
            warn('pic %s -> %s', pic, new_pic)
            pic = new_pic
        try:
            pr = await g_pg.get(pic, timeout=5)
        except ClientTimeoutError:
            error('ReadTimeout pic get error %s', pic)
            await asyncio.sleep(1)
            nr_try -= 1
        except ClientConnectionError:
            error('ConnectionError pic get error %s', pic)
            await asyncio.sleep(1)
            nr_try -= 1
        except ClientError:
            error('pic get error %s', pic)
            break
        except HttpBadRequest:
            error('InvalidSchema pic get error %s', pic)
            break
        else:
            if pr.status == 200:
                open(picfilepath, 'wb').write(pr.content)
            else:
                warn('pic get status_code %s for %s', pr.status, pic)
            break
        finally:
            if pr:
                await pr.release()

    return picfilepath


async def _notify(**kwargs):
    global g_changed
    ret_msg, ret_data = 'SKIP', 'IGNORE'
    slience, title, real_url, pic, sbr_time, item_url, from_title = \
        list(map(lambda x, k=kwargs: k.get(x, ''), ('slience', 'title', 'real_url', 'pic', 'sbr_time', 'item_url', 'from_title')))

    if not slience:
        if g_changed:
            _loadIncludeExcludeData()
            g_changed = 0
        for _w in l_exclude:
            if _w in title:
                ret_msg, ret_data = 'SKIP', _w
                break
        else:
            # open browser
            for _w in l_include:
                if _w in title:
                    cmd = 'notify-send  "%s" "%s at %s"' % (from_title, title.replace('$', '\$').replace('&', '＆'), sbr_time.strftime('%H:%M:%S'))
#-#                    debug('EXEC_CMD< %s ...\n%s %s', cmd, item_url, real_url)
                    subprocess.Popen(cmd, shell=True).wait()
#-#                    # 禁掉open url
                    info('ACCEPT open url for word %s in %s', _w, title)
                    ret_msg, ret_data = '', _w
                    pic_path = await getPic(pic)
                    webbrowser.get('firefox').open_new_tab('file:///%s' % getQrCode(real_url, pic=pic_path))
                    _play_sound(title)
                    break
            else:
                ret_msg, ret_data = '', ''
#-#                # 获取图片数据
#-#                picfilepath = getPic(pic)
#-#                cmd = 'notify-send -i %s "%s" "%s at %s"' % (picfilepath, from_title, title.replace(u'$', u'\$').replace(u'&', u'＆'), sbr_time.strftime('%H:%M:%S'))
#-##-#                debug('EXEC_CMD< %s ...\n%s %s', cmd, item_url, real_url)
#-#                subprocess.Popen(cmd, shell=True).wait()
#-##-#                webbrowser.get('firefox').open_new_tab('file:///%s' % getQrCode(real_url, pic=picfilepath))
                _play_sound(title)

    return ret_msg, ret_data


def _play_sound(content, tp='pyaudio'):
    new_content = re.sub('(\d+-\d+)', lambda x: x.group(1).replace('-', '减'), content, re.U)
#-#    if new_content != content:
#-#        info('%s -> %s', content, new_content)
    # call tts
    open('/tmp/tmp_in.txt', 'wb').write(new_content.encode('utf8'))
#-#    open('./tmp_in.txt', 'w').write(content)
    cmd = '''%s ./t2s.py -f /tmp/tmp_in.txt -t /tmp/tmp_out.pcm -s''' % (sys.executable, )
    debug('EXEC_CMD< %s ...', cmd)
    subprocess.Popen(cmd, shell=True, stdout=sys.stdout, stderr=sys.stderr).wait()

    if tp == 'mplayer':
#-#        cmd = 'mplayer -demuxer rawaudio -rawaudio channels=1:rate=16000:bitrate=16 -softvol -volume 20 -ao alsa:device=hw=0.0 -novideo ./tmp_out.pcm'
#-#        cmd = 'mplayer -demuxer rawaudio -rawaudio channels=1:rate=16000:bitrate=16  -novideo ./tmp_out.pcm'
        cmd = 'mplayer -demuxer rawaudio -rawaudio channels=1:rate=16000:bitrate=16 -softvol -volume 10 -novideo /tmp/tmp_out.pcm'
        info('EXEC_CMD< %s ...', cmd)
        subprocess.Popen(cmd, shell=True).wait()
    elif tp == 'ao':
        import ao
        ao.AudioDevice('raw', bits=16, rate=16000, channels=1).play(open('/tmp/tmp_out.pcm').read())
    elif tp == 'pcm':
        import alsaaudio
#-#        pcm = alsaaudio.PCM(card='hw:0,0')
        pcm = alsaaudio.PCM(card='Intel')
        pcm.setchannels(2)
        pcm.setrate(16000)
        pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
        # play pcm file from tts
        pcm.write(open('/tmp/tmp_out.pcm').read())
        del pcm
    elif tp == 'pyaudio':
        cmd = 'cmus-remote -u'
        subprocess.Popen(cmd, shell=True).wait()
        p = pyaudio.PyAudio()
        stream = p.open(format=p.get_format_from_width(2), channels=1, rate=16000, output=True)
        stream.write(open('/tmp/tmp_out.pcm', 'rb').read())  # 播放获得到的音频
#-#        stream.stop_stream()
#-#        stream.close()
#-#        p.terminate()
        cmd = 'cmus-remote -u'
        subprocess.Popen(cmd, shell=True).wait()


async def check_main_page_mmb(slience=False):
    global g_db
    try:
        r = await g_pg.get('http://cu.manmanbuy.com/cx_0_0_wytj_Default_1.aspx', timeout=5)
    except ClientConnectionError:
        error('ConnectionError')
        return
    except ClientHttpProcessingError:
        error('ClientHttpProcessingError')
        return
    except asyncio.TimeoutError:
        info('TimeoutError')
        return
    except ClientTimeoutError as e:
        error('timeout %s', e)
        return
    else:
        if r.status != 200:
            info('got code %s for %s', r.status, r.url)
            return
        r.raw_text = await r.text(encoding='gbk')
    finally:
        if r:
            await r.release()
    pr = etree.HTMLParser()
    tree = etree.fromstring(r.raw_text, pr)
    l_item = tree.xpath('//ul[@id="lilist"]/li')
#-#    info('got %s item(s)', len(l_item))

    try:
        for x in l_item:
            _id = x.xpath('./div[@class="action"]/div[@class="popbox"]/dl/dd[1]/a/@data-id')[0][:]
            key = 'manmanbuy_%s' % _id
            if key in g_db:
                continue
            title = x.xpath('./div[@class="tit"]/a/text()')[0][:].strip()
            price = x.xpath('./div[@class="price"]/text()')[0][:].strip()
            show_title = ' '.join((title, price))
#-#            pic = x.xpath('./div[@class="pic"]/a/img/@src')[0][:]
            pic = x.xpath('./div[@class="pic"]/a/img/@original')[0][:]
            tim = x.xpath('./div[@class="other"]/span[@class="t"]/text()')[0][:]
            year = datetime.now().year
            tim = datetime.strptime('%s-%s' % (year, tim), '%Y-%m-%d %H:%M')
            url = x.xpath('./div[@class="golink"]/a/@href')[0][:]
            url = 'http://cu.manmanbuy.com/%s' % (url, )
            item_url = 'http://cu.manmanbuy.com/Sharedetailed_%s.aspx' % (_id, )
            # TODO get real url
            real_url = url
            if url is not None:
                raw_url = url
                nr_redirect = 0
                while url.find('manmanbuy') != -1 and urlparse(url).path:
#-#                    debug('getting real_url %s ...', url)
                    try:
                        r = await g_pg.get(url, timeout=5)
                        nr_redirect += 1
                    except asyncio.TimeoutError as e:
#-#                        info('TimeoutError %s', e)
                        await asyncio.sleep(1)
                    except ClientTimeoutError:
                        await asyncio.sleep(1)
                    except ClientConnectionError:
                        await asyncio.sleep(1)
                    except ClientHttpProcessingError:
                        error('got error', exc_info=True)
                        break
                    except ClientError:
                        error('got ClientError for %s', url)
                        break
                    else:
                        if r.status == 200:
                            url = r.url
                            if 'url=' in url:  # found 'url=' or 'tourl='
                                up = urlparse(url)
                                d_p = parse_qs(up.query)
                                for _k in ('url', 'tourl'):
                                    if _k in d_p:
                                        url = d_p[_k][0]
                                        break
                        else:
                            x = 'http://cu.manmanbuy.com/http'
                            if x in raw_url:
                                url = raw_url[len(x) - 4:]
                                debug('url from bad url: %s -> %s', raw_url, url)
                            else:
                                info('real url not found %s %s %s', r.status, raw_url, r.url)
                            break
                        if nr_redirect > 5:
                            break
                    finally:
                        if r:
                            await r.release()

                real_url = url

#-#            print >> sys.stderr, ''  # return line
            pic = pic.replace('////', '//')
            err_msg, data = await _notify(slience=slience, title=show_title, real_url=real_url, pic=pic, sbr_time=tim, item_url=item_url, from_title='慢慢买')
            (info if not err_msg else debug)('%sadding [%s] %s %s --> %s\n', (data + ' ') if data else '', tim, show_title, item_url, real_url)
            g_db[key] = (pic, show_title, item_url, real_url, tim)
    except:
        error('error ', exc_info=True)


async def check_main_page(slience=False):
    global g_db
    nr_new = 0
    max_time, min_time = time.time(), time.time()

    base_url = '''http://www.smzdm.com/youhui/'''
#-#    debug('base_url = %s', base_url)
    real_url = None
    try:
        r = await g_pg.get(base_url, timeout=5)
    except:
        error('error fetching %s', base_url, exc_info=True)
    else:
        if r.status == 200:
            pr = etree.HTMLParser()
            tree = etree.fromstring(await r.text(), pr)
            l_item = tree.xpath('/html/body/section[@class="wrap"]//div[@class="list list_preferential "]')
            for x in l_item:
                url = x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a/@href')[0][:]
                direct_url = None
                try:
                    direct_url = x.xpath('./div[@class="listRight"]/div[@class="lrBot"]/div[@class="botPart"]/div[@class="buy"]/a/@href')[0]
                except IndexError:
                    pass
                title = premovetag.sub('', htmlentitydecode(etree.tostring(x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a')[0]).decode('utf8')))
#-#                title = re.sub('[\x7f-\xff]+', utf82unicode, title)
                title_price = x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a/span[@class="red"]/text()')
                if title_price:
                    title_noprice = premovetag.sub('', x.xpath('./div[@class="listTitle"]//h2[@class="itemName"]/a/text()')[0][:])
#-#                    info('title_noprice: %s', title_noprice)
                    show_title = title_noprice + ' ' + title_price[0][:]
#-#                    show_title = re.sub('[\x7f-\xff]+', utf82unicode, show_title)
                else:
                    show_title = title

                pic = x.xpath('./a[@class="picLeft"]/img/@src')[0][:]
                _id = x.attrib['articleid']
                item_id = 'p' + _id[_id.find('_') + 1:]
                timesort = int(x.attrib['timesort'])
                sbr_time = datetime.fromtimestamp(timesort)
                if min_time is None or timesort < min_time:
                    min_time = timesort
                if max_time is None or timesort > max_time:
                    max_time = timesort
                if item_id not in g_db:
                    nr_new += 1
                    # get real url
                    real_url = None
                    if direct_url is not None:
                        if direct_url.find('/go.smzdm.com/') != -1:
#-#                            debug('getting real_url for %s ...', direct_url)
                            try:
                                rr = await g_pg.get(direct_url, timeout=5)
                            except:
                                error('get real url error %s', exc_info=True)
                            else:
                                if rr.status == 200:
                                    try:
                                        s_js = re.search(r'eval\((.+?)\)\s+\</script\>', await rr.text(), re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE).group(1)
                                    except:
                                        embed()
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
                                        embed()
                            finally:
                                if rr:
                                    await rr.release()
                        else:
                            real_url = direct_url[:]

                    if pic[0] == '/':
                        pic = 'http://www.smzdm.com%s' % pic

#-#                    print >> sys.stderr, ''  # return line
                    err_msg, data = await _notify(slience=slience, title=show_title, real_url=real_url, pic=pic, sbr_time=sbr_time, item_url=url, from_title='什么值得买')
                    (info if not err_msg else debug)('%sadding [%s] %s %s --> %s\n', (data + ' ') if data else '', sbr_time, show_title, url, real_url)
                    g_db[item_id] = (pic, show_title, url, real_url, sbr_time)
                else:
                    pass
        else:
            info('return code = %d !!!', r.status)
    finally:
        if r:
            await r.release()

    return nr_new, max_time, min_time


async def check_main_page_getmore(process_time, slience=False):
    global g_db
    nr_new = 0
    max_time, min_time = None, None
    base_url = '''http://www.smzdm.com/youhui/json_more'''
    debug('base_url = %s', base_url)
    real_url = None
    r = None
    try:
        r = await g_pg.get(base_url, params={'timesort': process_time}, timeout=10)
    except ClientTimeoutError:
        info('timeout', base_url)
        await asyncio.sleep(1)
    except Exception as e:
        error('got error %s timesort: %s %s', base_url, process_time, e)
    else:
        if r.status == 200:
            info('url %s', r.url)
            l_item = await r.json()
            for x in l_item:
                url = x['article_url']
                direct_url = x['article_link']
                show_title = ' '.join((x['article_title'], x['article_price']))
                sbr_time = datetime.fromtimestamp(x['timesort'])
                pic = x['article_pic']
                item_id = 'p' + x['article_id']
                timesort = x['timesort']
                if min_time is None or min_time > timesort:
                    min_time = timesort
                if max_time is None or max_time < timesort:
                    max_time = timesort
                if item_id not in g_db:
                    nr_new += 1
                    # get real url
                    real_url = None
                    if direct_url is not None:
                        real_url = None
                        if direct_url.find('/go.smzdm.com/') != -1:
                            debug('getting real_url for %s ...', direct_url)
                            try:
                                rr = await g_pg.get(direct_url, timeout=5)
                            except:
                                error('get real url error %s', exc_info=True)
                            else:
                                if rr.status == 200:
                                    try:
                                        s_js = re.search(r'eval\((.+?)\)\s+\</script\>', await rr.text(), re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE).group(1)
                                    except:
                                        embed()
                                    s_rs = execjs.eval(s_js)
                                    s_key = re.search(r'location\.href=(.+?)}', s_rs).group(1)
                                    m = re.search(r'''%s='(?P<real_url>.+?)';''' % (s_key,), s_rs, re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE)
                                    if m:
                                        real_url = m.group('real_url')
                                    else:
                                        warn('can\'t find real_url')
                                        embed()
                            finally:
                                rr.release()

                    err_msg, data = await _notify(slience=slience, title=show_title, real_url=real_url, pic=pic, sbr_time=sbr_time, item_url=url, from_title='什么值得买')
                    (info if not err_msg else debug)('%sadding [%s] %s %s --> %s\n', (data + ' ') if data else '', sbr_time, show_title, url, real_url)
                    if len(x['article_link_list']) > 0:
                        (info if not err_msg else debug)('have more url:\n%s', '\n'.join('%s %s %s' % (_url['name'], _url['buy_btn_domain'], _url['link']) for _url in x['article_link_list']))

                    g_db[item_id] = (pic, show_title, url, real_url, sbr_time)
                else:
                    pass
#-#                info('now %d item.', len(g_db))
        else:
            info('return code = %d !!!', r.status)
    finally:
        if r:
            await r.release()

    return nr_new, max_time, min_time


async def do_work(interval, slience=False, first_slience=False):
    global g_changed

    wm, notifier, wdd = startWatchConf()

    _loadDb()
    _loadIncludeExcludeData()

    debug('doing ...')
    pd = ProgressData()

    b_first_time = True
    process_time_sec = time.mktime(pd.process_time.timetuple())
    nr_new = None
    try:
        while True:
            nr_new, max_process_time_sec, min_process_time_sec = await check_main_page(True if b_first_time and first_slience else slience)
#-#            debug('nr_new %d max_sec %d(%s) min_sec %d(%s)', nr_new, max_process_time_sec, datetime.fromtimestamp(max_process_time_sec), min_process_time_sec, datetime.fromtimestamp(min_process_time_sec))

            await check_main_page_mmb(False)

            while min_process_time_sec >= process_time_sec:

                process_time_sec = min_process_time_sec
                nr_new, _, min_process_time_sec = await check_main_page_getmore(process_time_sec, True if b_first_time and first_slience else slience)
                if min_process_time_sec is None:  # got net problem
                    min_process_time_sec = process_time_sec
                    await asyncio.sleep(5)
                    continue
                info('getmore nr_new %d min_sec %d(%s)', nr_new, min_process_time_sec, datetime.fromtimestamp(min_process_time_sec))

            process_time_sec = max_process_time_sec
#-#            check_fx_page( True if b_first_time and first_slience else slience )

            b_first_time = False

#-#            seconds = random.randint(interval, interval+5)
            seconds = interval
#-#            debug('next time range [%s, xxx] after sleep %d seconds ...', datetime.fromtimestamp(process_time_sec), seconds)
            print('.', end='', file=sys.stderr, flush=True)
            await asyncio.sleep(seconds)

    except KeyboardInterrupt:
        error('got KeyboardInterrupt, break ~', exc_info=True)
#-#        _set_trace()
#-#    except StandardError as e:
#-#        error('got StandardError: %s', e)
    except Exception as e:
        error('got Unknown Error: %s', e, exc_info=True)
    finally:
#-#        p.terminate()
        stopWatchConf(wm, notifier, wdd)
        info('now process_time_sec: %.6f(%s)', process_time_sec, datetime.fromtimestamp(process_time_sec))
        pd.process_time = datetime.fromtimestamp(process_time_sec)
        pd.saveCfg()
        if g_pg:
            g_pg.close()

    _saveDb()
    info('done.')


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(do_work(20, False, True))

