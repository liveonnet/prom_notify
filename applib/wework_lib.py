import asyncio
from datetime import datetime
import sys
import os
from base64 import urlsafe_b64encode
from urllib.parse import urlsplit
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.net_lib import NetManager
from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.cache_lib import RedisManager
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


class WeworkManager(object):
    """利用企业微信的api在手机上获取消息（企业微信里需要启用微信插件）
    """

    def __init__(self, conf_path='./config/pn_conf.yaml', loop=None, event_notify=None, net=None):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='wework')
        self.event_notify = event_notify
        self.loop = loop

        self.corpid = self.conf['corp_id']
        self.agentid = self.conf['agentid']
        self.secret = self.conf['secret']
        self.touser = self.conf['touser']
        self.net = net if net else NetManager(conf_path=self.conf_path, loop=self.loop, event_notify=self.event_notify)
        self.rds = None

        self.httpbin_html = """
        <!DOCTYPE html PUBLIC "-//IETF//DTD HTML 2.0//EN">
        <HTML>
           <HEAD>
           <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
           <meta name="referrer" content="no-referrer" />
           <TITLE>{from_title}</TITLE>
           </HEAD>
           <BODY>
                 <p align="center"><img src="{pic_url}" alt="no img"></p>
                 <h1>{title}</h1>
                 <hr>
                 <p align="center"><a href="{item_url}">发布 {item_url_domain}</a></p>
                 <hr>
                 <p align="center"><a href="{real_url}">直达 {real_url_domain}</a></p>
                 <hr>
           </BODY>
        </HTML>
        """

    async def send_by_wework(self, sbr_time, from_title, title, pic_url, item_url, real_url):
# #        debug(f'{type(from_title)}{from_title} {type(title)}{title} {type(pic_url)}{pic_url} {type(item_url)}{item_url} {type(real_url)}{real_url}')
        access_token = ''

        if not self.rds:
            RedisManager.setCfg(self.conf_path, self.loop)
            self.rds = await RedisManager.getConn()

        if not self.rds:
            error('cache mgr not found!')
            return

        access_token = await self.rds.get('wework_access_token')
#-#        if access_token:
#-#            access_token = access_token.decode()  # bytes -> str

        for _ in range(2):
            if not access_token:
                # https://work.weixin.qq.com/api/doc/10013
                # https://work.weixin.qq.com/api/doc/90000/90003/90556
                # https://work.weixin.qq.com/api/doc/90000/90003/90487
                # get secret
                # 登录企业微信管理端 -> 应用与小程序 -> 应用 -> 自建，点击“创建应用”，设置应用logo、应用名称等信息，创建应用。
                # 创建完成后，在管理端的应用列表里进入该应用，可以看到agentid、secret等信息，这些信息在使用企业微信API时会用到。
                # 由 corpid 和 corpsecret 获取 access_token
                url = f'https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corpid}&corpsecret={self.secret}'
                r, data, ok = await self.net.getData(url, my_fmt='json', my_json_encoding='utf8')
                if not ok:
                    error('get token failed ! %d', r.status)
                    return
                if data['errcode'] == 0:
                    access_token = data['access_token']
# #                    debug(f'got new access_token {access_token}')
                    debug(f'new access_token got.')
                    await self.rds.setex('wework_access_token', 3600, access_token)
                else:
                    error('get token failed ! %d', pcformat(data))
                    return
# #            else:
# #                debug(f'using cached access_token {access_token}')

            if access_token:
                url = f'https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}'
                # markdown 消息只能在企业微信中查看
                payload = {'touser': self.touser,
                           'msgtype': 'markdown',
                           'agentid': self.agentid,
                           'markdown': {'content': f'''`{from_title}`{title}
                                                    **详情**
                                                  <font color='warning'>[发布]({item_url})</font>
                                                  <font color='info'>[链接l({real_url})</font>
                                                  <font color='comment'>{sbr_time.strftime('%H:%M:%S')}</font>
                                                    '''
                                        },
                           'safe': 0,
                           'enable_duplicate_check': 1,
                           'duplicate_check_interval': 600
                           }
                # 图文消息  发3条，第一条发布页链接 第二条直达链接 第三条回显完整标题
                payload = {'touser': self.touser,
                           'msgtype': 'news',
                           'agentid': self.agentid,
                           'news': {'articles': [{'title': f'{title[:30]}',
                                                  'description': f'{title}',
                                                  'url': item_url,
                                                  'picurl': pic_url,
                                                  },
                                                 {'title': f'{title[30:60]}' if len(title) > 30 else real_url,
                                                  'description': f'{from_title}',
                                                  'url': real_url if real_url else item_url,
                                                  'picurl': pic_url,
                                                  },
                                                 {'title': f'{title[60:]}' if len(title) > 60 else title,
                                                  'description': f'{sbr_time.strftime("%H:%M:%S")}',
                                                  #'url': f'https://httpbin.org/base64/{urlsafe_b64encode(title.encode("utf8")).decode()}',  # 利用httpbin显示url后附上的完整标题
                                                  'url': f'https://httpbin.org/base64/{urlsafe_b64encode(self.httpbin_html.format(**locals(), item_url_domain=urlsplit(item_url).netloc, real_url_domain=urlsplit(real_url).netloc).encode("utf8")).decode()}',  # 利用httpbin显示url后附上的完整内容
                                                  'picurl': pic_url,
                                                  },
                                                 ]
                                    },
                           'safe': 0,
                           'enable_duplicate_check': 1,
                           'duplicate_check_interval': 600
                           }
                r, data, ok = await self.net.postData(url, json=payload, my_fmt='json', my_json_encoding='utf8')
                if not ok:
                    error('通过企业微信api发消息失败! %s', r)
                    return
                if data['errcode'] == 40014:
                    debug(f'access_code expired, request new one ...')
                    access_token = None
                    await self.rds.delete('wework_access_token')
                    continue
                elif data['errcode'] != 0:  # 其他提示需要显示
                    debug(f'{pcformat(data)}')
                    break
                else:  # 成功时不必提示
                    break


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    try:
        net = NetManager(loop=loop)
        ww = WeworkManager(loop=loop, net=net)
        task = asyncio.ensure_future(ww.send_by_wework(datetime.now(), 'mmb', '标题就是比较长，还有回车换行符呢。现在要做的基本就是整合起来进行整体测试了，希望能顺利完事\n我就是第二行\n第三行能看到不？', 'https://www.baidu.com/img/PCtm_d9c8750bed0b3c7d089fa7d55720d6cf.png', 'http://www.baidu.com', 'http://bing.com'))
        x = loop.run_until_complete(task)
        info(pcformat(x))

        task = asyncio.ensure_future(net.clean())
        x = loop.run_until_complete(task)
        info(pcformat(x))
    except KeyboardInterrupt:
        info('cancel on KeyboardInterrupt..')
        task.cancel()
        loop.run_forever()
        task.exception()
    finally:
        loop.stop()

