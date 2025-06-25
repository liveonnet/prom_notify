import sys
import json
#-#from datetime import datetime
#-#from datetime import timedelta
#-#import time
import os
#-#import redis
#-#import random
#-#from getpass import getuser
#-#from urllib.parse import urlparse
#-#from urllib.parse import urljoin
#-#from urllib.parse import parse_qs
#-#from lxml import etree
import asyncio
import aiohttp
import aiodns
#-#import configparser
#-#import codecs
#-#from difflib import SequenceMatcher
#-#from aiohttp.errors import ClientTimeoutError
#-#from aiohttp.errors import ClientConnectionError
#-#from aiohttp.errors import ClientDisconnectedError
#-#from aiohttp.errors import ContentEncodingError
from aiohttp import ClientError
#-#from aiohttp.errors import HttpBadRequest
#-#from aiohttp.errors import ClientHttpProcessingError
#from aiohttp.resolver import AsyncResolver
#-#from setproctitle import setproctitle
#-#import subprocess
#-#import concurrent
#-#import signal
#-#import re
#-#import multiprocessing
#-#import execjs
#-#import webbrowser
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.conf_lib import getConf
#-#from applib.audio_lib import PlaySound
#-#from applib.qrcode_lib import QrCode
#-#from applib.watch_lib import startWatchConf, stopWatchConf
#-#from applib.filter_lib import FilterTitle
#-#from applib.coupon_lib import CouponManager
#-#from applib.db_lib import HistoryDB
#-#from applib.db_lib import Item
#-#from applib.orm_lib import HistoryDB
#-#from applib.tools_lib import htmlentitydecode
from applib.tools_lib import pcformat
from applib.log_lib import app_log

info, debug, warn, excep, error = app_log.info, app_log.debug, app_log.warning, app_log.exception, app_log.error


class NetManager(object):
    """网络请求功能简单封装
    """

    def __init__(self, conf_path='./config/pn_conf.yaml', loop=None, event_notify=None):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='net')

        self.loop = None
        self.sess = None
#-#        resolver = AsyncResolver(nameservers=['8.8.8.8', '8.8.4.4', '1.1.1.1'])
#-#        conn = aiohttp.TCPConnector(resolver=resolver, limit=10, ttl_dns_cache=300)
        conn = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
        if self.loop:
            self.sess = aiohttp.ClientSession(connector=conn, headers={'User-Agent': self.conf['user_agent']}, loop=self.loop)
        else:
            self.sess = aiohttp.ClientSession(connector=conn, headers={'User-Agent': self.conf['user_agent']})
        info(f'sess inited.')

    async def postData(self, url, *args, **kwargs):
        """post 方式提交数据，基本照搬getData，自定义参数最好不用
        """
        resp, data, ok = None, None, False
        str_encoding = kwargs.pop('my_str_encoding', None)
        fmt = kwargs.pop('my_fmt', 'str')
        json_encoding = kwargs.pop('my_json_encoding', None)
        json_loads = kwargs.pop('my_json_loads', json.loads)
        streaming_chunk_size = kwargs.pop('my_streaming_chunk_size', 1024)
        streaming_cb = kwargs.pop('my_streaming_cb', None)
        max_try = kwargs.pop('my_retry', 1)
        if 'ssl' not in kwargs:
            kwargs['ssl'] = False

        for nr_try in range(max_try):
            try:
#-#                debug('url %s %s %s', url, pcformat(args), pcformat(kwargs))
                resp = await self.sess.post(url, *args, **kwargs)
                if fmt == 'str':
                    try:
                        data = await resp.text(encoding=str_encoding)
                    except UnicodeDecodeError:
                        txt = await resp.read()
                        data = txt.decode(str_encoding, 'ignore')
                        warn('ignore decode error from %s', url)
#-#                    except ContentEncodingError:
                    except aiohttp.client_exceptions.ContentTypeError:
                        warn('ignore content encoding error from %s', url)
                elif fmt == 'json':
                    data = await resp.json(encoding=json_encoding, loads=json_loads, content_type=None)
#-#                    if not data:
#-#                    if 'json' not in resp.headers.get('content-type', ''):
#-#                        warn('data not in json? %s', resp.headers.get('content-type', ''))
                elif fmt == 'bytes':
                    data = await resp.read()
                elif fmt == 'stream':
                    while 1:
                        chunk = await resp.content.read(streaming_chunk_size)
                        if not chunk:
                            break
                        streaming_cb(url, chunk)
                ok = True
                break
            except asyncio.TimeoutError:
                if nr_try == max_try - 1:  # 日志输出最后一次超时
                    debug(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}TimeoutError {url}')
            except aiohttp.client_exceptions.ClientConnectorError:
                excep('{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""} {url} {pcformat(args)} {pcformat(kwargs)}')
            except ConnectionResetError:
                error(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}ConnectionResetError {url} {pcformat(args)} {pcformat(kwargs)}')
            except aiohttp.client_exceptions.ContentTypeError:
                error(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}ContentTypeError {url} {pcformat(args)} {pcformat(kwargs)}')
                data = await resp.text(encoding=str_encoding)
                info(f'data {data[:50]}')
            except ClientError:
                error(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}ClientError {url} {pcformat(args)} {pcformat(kwargs)}')
            except UnicodeDecodeError:
                _tmp = await resp.read()
                excep(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""} {url} {pcformat(args)} {pcformat(kwargs)} {pcformat(resp.headers)} {_tmp}')
#-#                raise e
            except json.decoder.JSONDecodeError:
                excep(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}JSONDecodeError {url} {pcformat(args)} {pcformat(kwargs)}')
            except aiodns.error.DNSError:
                error(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}DNSError {url} {pcformat(args)} {pcformat(kwargs)}')
            finally:
                if resp:
                    resp.release()

        return resp, data, ok

    async def getData(self, url, *args, **kwargs):
        """封装网络请求

        my_fmt:
            str: 默认项
                my_str_encoding
            json:
                my_json_encoding
                my_json_loads
            bytes:
                None
            streaming:
                my_streaming_chunk_size
                my_streaming_cb
        """
        resp, data, ok = None, None, False
        str_encoding = kwargs.pop('my_str_encoding', None)
        fmt = kwargs.pop('my_fmt', 'str')
        json_encoding = kwargs.pop('my_json_encoding', None)
        json_loads = kwargs.pop('my_json_loads', json.loads)
        streaming_chunk_size = kwargs.pop('my_streaming_chunk_size', 1024)
        streaming_cb = kwargs.pop('my_streaming_cb', None)
        max_try = kwargs.pop('my_retry', 1)
        if 'ssl' not in kwargs:
            kwargs['ssl'] = False

        for nr_try in range(max_try):
            try:
#-#                debug('url %s %s %s', url, pcformat(args), pcformat(kwargs))
                resp = await self.sess.get(url, *args, **kwargs)
                if fmt == 'str':
                    try:
                        data = await resp.text(encoding=str_encoding)
                    except UnicodeDecodeError:
                        txt = await resp.read()
                        data = txt.decode(str_encoding, 'ignore')
                        warn('ignore decode error from %s', url)
#-#                    except ContentEncodingError:
                    except aiohttp.client_exceptions.ContentTypeError:
                        warn('ignore content encoding error from %s', url)
                elif fmt == 'json':
                    try:
                        data = await resp.json(encoding=json_encoding, loads=json_loads, content_type=None)
                    except UnicodeDecodeError as e:
                        debug(f'got except {e}')
                        break
                    except Exception as e:
                        debug(f'got except with {url} {e}')
                        break
#-#                    if not data:
#-#                    if 'json' not in resp.headers.get('content-type', ''):
#-#                        warn('data not in json? %s', resp.headers.get('content-type', ''))
                elif fmt == 'bytes':
                    data = await resp.read()
                elif fmt == 'stream':
                    while 1:
                        chunk = await resp.content.read(streaming_chunk_size)
                        if not chunk:
                            break
                        streaming_cb(url, chunk)
                ok = True
                break
#-#            except aiohttp.errors.ServerDisconnectedError:
#-#                debug('%sServerDisconnectedError %s %s %s', ('%s/%s ' % (nr_try + 1, max_try)) if max_try > 1 else '', url, pcformat(args), pcformat(kwargs))
            except asyncio.TimeoutError:
#-#                debug('%sTimeoutError %s %s %s', ('%s/%s ' % (nr_try + 1, max_try)) if max_try > 1 else '', url, pcformat(args), pcformat(kwargs))
                if nr_try == max_try - 1:  # 日志输出最后一次超时
                    debug(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}TimeoutError {url}')
            except aiohttp.client_exceptions.ClientConnectorError:
                error(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}ClientConnectorError {url} {pcformat(args)} {pcformat(kwargs)}')
            except ConnectionResetError:
                error(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}ConnectionResetError {url} {pcformat(args)} {pcformat(kwargs)}')
#-#            except aiohttp.errors.ClientResponseError:
#-#                debug('%sClientResponseError %s %s %s', ('%s/%s ' % (nr_try + 1, max_try)) if max_try > 1 else '', url, pcformat(args), pcformat(kwargs))
#-#            except ClientHttpProcessingError:
#-#                debug('%sClientHttpProcessingError %s %s %s', ('%s/%s ' % (nr_try + 1, max_try)) if max_try > 1 else '', url, pcformat(args), pcformat(kwargs), exc_info=True)
#-#            except ClientTimeoutError:
#-#                debug('%sClientTimeoutError %s %s %s', ('%s/%s ' % (nr_try + 1, max_try)) if max_try > 1 else '', url, pcformat(args), pcformat(kwargs))
            except aiohttp.client_exceptions.ContentTypeError:
                excep(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""} {url} {pcformat(args)} {pcformat(kwargs)}')
                data = await resp.text(encoding=str_encoding)
                info(f'data {data[:50]}')
            except ClientError:
                excep(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""} {url} {pcformat(args)} {pcformat(kwargs)}')
            except UnicodeDecodeError:
                _tmp = await resp.read()
                excep(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""} {url} {pcformat(args)} {pcformat(kwargs)} {pcformat(resp.headers)} {_tmp}')
#-#                raise e
            except json.decoder.JSONDecodeError:
                excep(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""} {url} {pcformat(args)} {pcformat(kwargs)}')
            except aiodns.error.DNSError:
                error(f'{("%s/%s " % (nr_try + 1, max_try)) if max_try > 1 else ""}DNSError {url} {pcformat(args)} {pcformat(kwargs)}')
            finally:
                if resp:
                    resp.release()

        return resp, data, ok

    async def clean(self):
        if self.sess:
            await self.sess.close()
            info(f'sess closed.')


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    try:
        net = NetManager(loop=loop)
        task = asyncio.ensure_future(net.getData('http://httpbin.org/ip', timeout=1, my_fmt='bytes'))
        x = loop.run_until_complete(task)
        info(pcformat(x))

        task = asyncio.ensure_future(net.clean())
        x = loop.run_until_complete(task)
        info(pcformat(x))
    except KeyboardInterrupt:
        info(f'cancel on KeyboardInterrupt..')
        task.cancel()
        loop.run_forever()
        task.exception()
    finally:
        loop.stop()

