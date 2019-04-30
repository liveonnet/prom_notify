import sys
import os
import re
import json
# #import shlex
from datetime import datetime
from datetime import timedelta
import subprocess
import http.server
#-#import aiohttp
# #import setproctitle
# #import asyncio
#-#import uvloop
#-#asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
#-#import ssl
#-#from aiohttp import web
#-#from lib.conf_lib import conf
#-#from lib.load_handler import setup_routes
#-#from middleware import l_middleware
#-#from urllib.parse import quote
from urllib.parse import urljoin
# #from urllib.parse import unquote
#-#from urllib.parse import urlsplit
from urllib.parse import parse_qs
#-#from itertools import repeat
#-#from itertools import count
# #import importlib
# #import asyncio
#-#from getpass import getuser
from IPython import embed
embed
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.discuz_lib import SisDB
# #from applib.tools_lib import pcformat
# #from applib.cache_lib import RedisManager
from applib.conf_lib import getConf
# #from applib.net_lib import NetManager
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


class MyHandler(http.server.BaseHTTPRequestHandler):
#-#    def __init__(self, *args, **kwargs):
#-#        super().__init__(*args, **kwargs)

    def do_GET(self):
        info(f'{id(self)} {self.path}')
        p = getattr(self, 'p', None)
        if not p:
            self.pageSize = 10
            p = re.compile('^/(\d+)')
            self.p = p
        m = p.match(self.path)
        if m:
            page = m.group(1) or '1'
        else:
            page = '1'
        if self.path == '/' or m:  # 展示
#-#            info(f'{self.requestline}')
#-#            info(f'{self.headers}')
            forum = [x for x in self.discuz_conf['forum'] if x['title'] == 'sis'][0]
            # 查询数据
            db = SisDB(self.conf_path)
            seconds_ago = datetime.now() + timedelta(hours=-24)
#-#            rcds = db.getRecords(seconds_ago, page)
            l_rcd = []
            for _rcd in db.getRecords(seconds_ago, page):
                # 图片转成可访问链接
                _img_url = '<br/>'.join(f'<img src="{_x}" alt="{_x}"></img>' for _x in json.loads(_rcd.img_url))
                # 附件aid转成可访问链接
                _aid = urljoin(forum['post_base_url'], f'attachment.php?aid={_rcd.aid}&clickDownload=1')
                l_rcd.append((_rcd.title, _img_url, _rcd.name, _rcd.size, _aid, _rcd.ctime))
#-#            embed()

            l_content = []
            for _i, (_title, _img_url, _aname, _asize, _aurl, _ctime) in enumerate(l_rcd, 1):
                l_content.append(f'<div>'
                                 f'<h3>{_i}/{len(l_rcd)} {_title}</h3><h5>{_ctime}</h5>'
                                 f'{_img_url}<br/>'
                                 f'<form id="form_{_i}" action="/dl/" method="POST" target="_blank">'
                                 f'<a class="torrent_link" target="_blank" href="{_aurl}">{_aname}&nbsp;&nbsp;{_asize}</a>&nbsp;&nbsp;&nbsp;'
                                 f'<input type="radio" name="as_{_i}" value="start" >start</input>'
                                 f'<input type="radio" name="as_{_i}" value="paused" checked>paused</input>'
                                 f'<input type="hidden" name="aurl" value="{_aurl}" />'
                                 f'&nbsp;&nbsp;<button type="submit" value="Submit">加入下载队列</button>'
                                 f'</form>'
                                 f'</div>')
# #                if  _i > 2:
# #                    break
            # 构造网页
            pre_page = '' if int(page) <= 1 else f'<h2><a href="http://{self.conf["host"]}:{self.conf["port"]}/{int(page) -1}">prev</a></h2>'
            nxt_page = '' if len(l_rcd) < self.pageSize else f'<h2><a href="http://{self.conf["host"]}:{self.conf["port"]}/{int(page) + 1}">next</a></h2>'
            s = '''<html>
<head>
<style>
div
{{
border:15px solid transparent;
width:100%;
padding:10px 10px;
}}

h2
{{
text-align:center;
}}

h3
{{
text-align:center;
color:red;
}}

h5
{{
text-align:center;
color:blue;
}}

form
{{
display:block;
text-align:center;
}}

img
{{
clear:both;
display:block;
max-width: 90%;
margin: auto;
}}

a.torrent_link:link {{text-decoration: none}}
a.torrent_link:hover {{background: #66ff66; text-decoration: underline}}

</style>
<title>sis torrent</title>
</head>
<body>
{content}
<div/>
{pre_page}
{nxt_page}
</body>
</html>'''.format(content='<br/><hr/>'.join(l_content), pre_page=pre_page, nxt_page=nxt_page).encode()

            self.send_response(200)
            self.send_header('Version', 'HTTP/1.0')
            self.send_header('Server', 'sis_server')
            self.send_header('Connection', 'Closed')
            self.send_header('Cache-Control', 'max-age=600')
            self.send_header('Content-Type', 'text/html;charset=utf-8')
            self.send_header('Content-Length', len(s))
            self.end_headers()
            self.wfile.write(s)
        else:
            self.send_error(404)
        return True

    def do_POST(self):
        info(f'{id(self)} {self.path}')
#-#        info(f'{self.headers}')
        if self.path == '/dl/' and self.headers['Content-Type'] == 'application/x-www-form-urlencoded':
            s = self.rfile.read(int(self.headers['Content-Length']))
            info(f'{s}')
            d = parse_qs(s.decode())
            d_cmd = {'add_start': '--start-paused'}
            for _k, _v in d.items():
                if _k.startswith('as_'):
                    if _v and _v[0] == 'start':
                        d_cmd['add_start'] = '--no-start-paused'
                elif _k == 'aurl' and _v:
                    d_cmd['torrent'] = _v[0]
            if 'torrent' in d_cmd:
                tr_conf = self.all_conf['transmission']
                cmd = f'transmission-remote {tr_conf["host"]}:{tr_conf["port"]} -n {tr_conf["user"]}:{tr_conf["auth"]} {d_cmd["add_start"]} -a "{d_cmd["torrent"]}"'
#-#                cmd = shlex.split(cmd)
                debug('EXEC_CMD< %s ...', cmd)

                l_content = []
                try:
                    rs = subprocess.run(cmd, capture_output=True, shell=True, timeout=60)
                    outs = rs.stdout.decode() if rs.stdout else ''
                    errs = rs.stderr.decode() if rs.stderr else ''
                    info(f'{outs}')
                    l_content.append(outs.strip())
                    if errs:
                        info(f'{errs}')
                        l_content.append(errs.strip())
                except subprocess.TimeoutExpired:
                    warn('timeout !!!')
                else:
                    try:
                        cmd = f'transmission-remote {tr_conf["host"]}:{tr_conf["port"]} -n {tr_conf["user"]}:{tr_conf["auth"]} {d_cmd["add_start"]} -l'
                        rs = subprocess.run(cmd, capture_output=True, shell=True, timeout=60)
                        outs = rs.stdout.decode() if rs.stdout else ''
                        errs = rs.stderr.decode() if rs.stderr else ''
                        info(f'\n{outs}')
                        l_content.append(outs.strip())
                        if errs:
                            info(f'\n{errs}')
                            l_content.append(errs.strip())
                    except subprocess.TimeoutExpired:
                        warn('timeout !!!')

                self.send_response(200)
                self.send_header('Version', 'HTTP/1.0')
                self.send_header('Server', 'sis_server')
                self.send_header('Connection', 'Closed')
                self.send_header('Cache-Control', 'max-age=600')
                self.send_header('Content-Type', 'text/html;charset=utf-8')
                s = '''<html>
<head>
<title>result</title>
</head>
<body>
<pre>
{}
</pre>
</body>
</html> '''.format('\n\n'.join(l_content)).encode()
                self.send_header('Content-Length', len(s))
                self.end_headers()
                self.wfile.write(s)
        return True

    @classmethod
    def loadCfg(cls):
        # 加载配置
        cls.conf_path = os.path.abspath('config/pn_conf.yaml')
        cls.all_conf = getConf(cls.conf_path)
        cls.conf = cls.all_conf['sis_server']
        cls.discuz_conf = cls.all_conf['discuz']


def run(server_class=http.server.HTTPServer, handler_class=MyHandler):
    conf_path = os.path.abspath('config/pn_conf.yaml')
    conf = getConf(conf_path, root_key='sis_server')
    server_address = (conf['host'], conf['port'])
    handler_class.loadCfg()
    httpd = server_class(server_address, handler_class)
    info(f'listen on {server_address} ...\nhttp://{conf["host"]}:{conf["port"]}/')
    httpd.serve_forever()
    info('done.')


run()
