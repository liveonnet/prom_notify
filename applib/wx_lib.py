"""
参数    l类型   Text 键值
TEXT    文本    文本内容(文字消息)
MAP     地图    位置文本(位置分享)
CARD    名片    推荐人字典(推荐人的名片)
SHARING     分享    分享名称(分享的音乐或者文章等)
PICTURE 下载方法        图片/表情
RECORDING   语音    下载方法
ATTACHMENT  附件    下载方法
VIDEO   小视频  下载方法
FRIENDS     好友邀请    添加好友所需参数
SYSTEM  系统消息    更新内容的用户或群聊的UserName组成的列表
NOTE    通知    通知文本(消息撤回等)
"""
import sys
import os
import time
from datetime import datetime
from datetime import timedelta
import re
from time import sleep
# #import queue
from queue import Empty
#-#import asyncio
from setproctitle import setproctitle
import multiprocessing
from multiprocessing.managers import SyncManager
#-#import concurrent
# #import logging
import _thread
import itchat
from itchat.content import TEXT, FRIENDS, MAP, CARD, NOTE, SHARING, PICTURE, RECORDING, ATTACHMENT, VIDEO
#-#from selenium import webdriver
#-#from selenium.common.exceptions import NoSuchElementException
from IPython import embed
embed
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
# #from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.log_lib import get_lan_ip
from applib.log_lib import app_log
info, debug, warn, excep, error = app_log.info, app_log.debug, app_log.warning, app_log.exception, app_log.error

msg_information = {}
face_bug = None  # 针对表情包的内容
attachment_dir = None


class ItchatManager(object):
    """微信管理类
    """
    def __init__(self, conf_path='config/pn_conf.yaml'):
        global attachment_dir
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='itchat')

        attachment_dir = os.path.abspath(self.conf['attachment_dir'])

        self.thread_id = None

        self.gid = None  # 记录我们群的UserName
        if self.conf['use_custom_manager']:
            # create proxy manager
            class MySyncManager(SyncManager):
                pass
            MySyncManager.register('get_wx_send_q')
            mgr = MySyncManager((get_lan_ip(), self.conf['custom_manager_port']), self.conf['custom_manager_authkey'].encode('utf8'))
#-#            sleep(0.5)  # wait for manager to start
            mgr.connect()

            self.q_send = mgr.get_wx_send_q()
        else:
            mgr = multiprocessing.Manager()
            self.q_send = mgr.Queue()
        self.event_exit = mgr.Event()
        multiprocessing.current_process().authkey = self.conf['custom_manager_authkey'].encode('utf8')  # https://bugs.python.org/issue7503
        self.proc_wx = multiprocessing.Process(target=self.run, args=(self.event_exit, self.q_send))
        self.proc_wx.start()

    def onLogin(self):
        info(f'itchat login ok ~')

    def onExit(self):
        info(f'itchat exit')

    def run(self, event_exit, q_send):
        setproctitle('wx_proc')
        self.start()
        if self.thread_id is None:
            self.thread_id = _thread.start_new_thread(itchat.run, (), {'debug': self.conf['debug'], })
            info(f'instance {itchat.instanceList[-1]}')
            info(f'itchat running')
        else:
            info(f'itchat already running')

        if self.gid is None:  # 有时候登录后第一次查不到“我们”群，尝试多次查找
            try:
                debug(f'finding chatroom ...')
                groups = itchat.get_chatrooms(update=True)
                for _g in groups:
                    if _g['MemberCount'] == 3 and _g.Self.NickName == "刘强":
                        self.gid = _g['UserName']
                        info(f'我们 gid {self.gid}')
                        break
                else:
                    debug(f'chatroom not found')
#-#                            debug('%s\t%s', _g['NickName'], _g['UserName'])
#-#                        g = itchat.search_chatrooms(name="我们")
#-#                        if g:
#-#                            g = g[0]
#-#                            info('g %s %s', g['UserName'], g['MemberCount'])
#-#                            if g['MemberCount'] == 3 and g.Self.NickName == "刘强":
#-#                                self.gid = g['UserName']
#-#                                info('我们 gid %s', self.gid)
#-#                        else:
#-#                            debug('chatroom not found')
            except Exception:
                excep(f'error finding chatroom 我们')

        while 1:
#-#            embed()
            try:
                msg, who = q_send.get(timeout=30)
            except KeyboardInterrupt:
                warn(f'got KeyboardInterrupt when waiting for msg to send, exit!')
                break
            except Empty:
                if event_exit.is_set():
                    info(f'got exit flag, exit~')
                    break
            except Exception as e:
                warn(f'got exception when waiting for msg to send, exit! {e}')
                break
            else:
                if not msg and not who:
                    info(f'break !!!')
                    break
                self.sendMsg(msg, toUserName=who)
                if event_exit.is_set():
                    info(f'got exit flag, exit~')
                    break

        self.clean()

    def start(self):
        info(f'itchat starting ..')
        itchat.auto_login(enableCmdQR=2, hotReload=True, picDir='/tmp', statusStorageDir='config/itchat.pkl', loginCallback=self.onLogin, exitCallback=self.onExit)
#-#        groups = itchat.get_chatrooms()
#-#        for _g in groups:
#-#            info('%s\t%s', _g['NickName'], _g['UserName'])
#-#        g = itchat.search_chatrooms(name="我们")
#-#        if g:
#-#            g = g[0]
#-#            info('g %s %s', g['UserName'], g['MemberCount'])
#-#            if g['MemberCount'] == 3 and g.Self.NickName == "刘强":
#-#                self.gid = g['UserName']
#-#                info('我们 gid %s', self.gid)

        info(f'itchat started')

    def stop(self):
        itchat.logout()
        info(f'itchat logout')

    def clean(self):
        self.stop()

    @staticmethod
    @itchat.msg_register([TEXT, PICTURE, FRIENDS, CARD, MAP, SHARING, RECORDING, ATTACHMENT, VIDEO], isFriendChat=True, isGroupChat=True, isMpChat=True)
    def handle_receive_msg(msg):
        global face_bug, attachment_dir
        msg_time_rec = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())  # 接受消息的时间
        user_info = itchat.search_friends(userName=msg['FromUserName'])  # 在好友列表中查询发送信息的好友昵称
        msg_from = msg['FromUserName'] if not user_info else user_info['NickName']  # 在好友列表中查询发送信息的好友昵称
        msg_time = msg['CreateTime']  # 信息发送的时间
        msg_id = msg['MsgId']  # 每条信息的id
        msg_content = None  # 储存信息的内容
        msg_share_url = None  # 储存分享的链接，比如分享的文章和音乐
#-#        info('[%s %s] %s', msg['Type'], msg['MsgId'], msg_from)
        if msg['Type'] in ('Text', 'Friends'):  # 如果发送的消息是文本或者好友推荐
            msg_content = msg['Text']
            info(f'[{msg["Type"]} {msg["MsgId"]}] {msg_from}: {msg_content}')
#-#            info('%s', msg_content)
        elif msg['Type'] in ('Attachment', 'Video', 'Picture', 'Recording'):  # 如果发送的消息是附件、视屏、图片、语音
            msg_content = msg['FileName']  # 内容就是他们的文件名
            msg['Text'](os.path.join(attachment_dir, msg_content))  # 下载文件
            info(f'[{msg["Type"]} {msg["MsgId"]}] {msg_from}')
            # print msg_content
        elif msg['Type'] == 'Card':  # 如果消息是推荐的名片
            msg_content = msg['RecommendInfo']['NickName'] + '的名片'  # 内容就是推荐人的昵称和性别
            if msg['RecommendInfo']['Sex'] == 1:
                msg_content += '性别为男'
            else:
                msg_content += '性别为女'
#-#            info('%s', msg_content)
            info(f'[{msg["Type"]} {msg["MsgId"]}] {msg_from}: {msg_content}')
        elif msg['Type'] == 'Map':  # 如果消息为分享的位置信息
            x, y, location = re.search("<location x=\"(.*?)\" y=\"(.*?)\".*label=\"(.*?)\".*", msg['OriContent']).group(1, 2, 3)
            if location is None:
                msg_content = "纬度->" + x.__str__() + " 经度->" + y.__str__()  # 内容为详细的地址
            else:
                msg_content = location
            info(f'[{msg["Type"]} {msg["MsgId"]}] {msg_from}: {msg_content}')
        elif msg['Type'] == 'Sharing':  # 如果消息为分享的音乐或者文章，详细的内容为文章的标题或者是分享的名字
            msg_content = msg['Text']
            msg_share_url = msg['Url']  # 记录分享的url
#-#            info('%s', msg_share_url)
            info(f'[{msg["Type"]} {msg["MsgId"]}] {msg_from}: {msg_share_url}')
        face_bug = msg_content

        # 将信息存储在字典中，每一个msg_id对应一条信息
        msg_information.update(
            {
                msg_id: {
                    "msg_from": msg_from, "msg_time": msg_time, "msg_time_rec": msg_time_rec,
                    "msg_type": msg["Type"],
                    "msg_content": msg_content, "msg_share_url": msg_share_url
                }
            }
        )
        # 去掉5分钟前的消息
        l_msgid_2del = []
        time_5min_early = (datetime.now() + timedelta(minutes=-5)).strftime("%Y-%m-%d %H:%M:%S")
        for _msgid, _v in msg_information.items():
            if _v['msg_time_rec'] <= time_5min_early:
                l_msgid_2del.append(_msgid)
        if l_msgid_2del:
            info(f'del {len(l_msgid_2del)} old msg')
        for _msgid in l_msgid_2del:
            msg_information.pop(_msgid, None)

    # 这个是用于监听是否有消息撤回
    @itchat.msg_register(NOTE, isFriendChat=True, isGroupChat=True, isMpChat=True)
    def information(msg):
        # 这里如果这里的msg['Content']中包含消息撤回和id，就执行下面的语句
        if '撤回了一条消息' in msg['Content']:
            old_msg_id = re.search("\<msgid\>(.*?)\<\/msgid\>", msg['Content']).group(1)  # 在返回的content查找撤回的消息的id
            old_msg = msg_information.get(old_msg_id)  # 得到消息
            info(f'old msg: {old_msg}')
            if not old_msg:  # 找不到消息
                return
            if len(old_msg_id) < 11:  # 如果发送的是表情包
                itchat.send_file(face_bug, toUserName='filehelper')
            else:  # 发送撤回的提示给文件助手
                msg_body = "告诉你一个秘密~" + "\n" \
                           + old_msg.get('msg_from') + " 撤回了 " + old_msg.get("msg_type") + " 消息" + "\n" \
                           + old_msg.get('msg_time_rec') + "\n" \
                           + "撤回了什么 ⇣" + "\n" \
                           + old_msg.get('msg_content')
                #如果是分享的文件被撤回了，那么就将分享的url加在msg_body中发送给文件助手
                if old_msg['msg_type'] == "Sharing":
                    msg_body += "\n就是这个链接➣ " + old_msg.get('msg_share_url')

                # 将撤回消息发送到文件助手
                itchat.send_msg(msg_body, toUserName='filehelper')
                # 有文件的话也要将文件发送过去
                if old_msg['msg_type'] in ('Picture', 'Recording', 'Video', 'Attachment'):
                    f = '@fil@%s' % (old_msg['msg_content'])
                    itchat.send(msg=f, toUserName='filehelper')
                    if os.path.exists(old_msg['msg_content']):
                        os.remove(old_msg['msg_content'])
                # 删除字典旧消息
                msg_information.pop(old_msg_id)

    def sendMsg(self, msg_body, toUserName='filehelper'):
        if not toUserName:
            toUserName = 'filehelper'
        if toUserName != 'filehelper' and toUserName[0] != '@':  # 需要根据用户名找微信id
            users = itchat.search_friends(name=toUserName)
            if users:
# #                debug(f'use {users[0]["UserName"]} from {toUserName}')
                toUserName = users[0]['UserName']
        try:
            itchat.send_msg(msg_body, toUserName)
#-#        debug('send %s %s', msg_body, self.gid if self.gid else toUserName)
        except Exception:
            excep(f'got except')


if __name__ == '__main__':

    it = ItchatManager()
    while 1:
        try:
            sleep(10)
        except KeyboardInterrupt:
            info(f'cancel on KeyboardInterrupt..')
            it.clean()



