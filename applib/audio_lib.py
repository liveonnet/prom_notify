import os
import sys
import re
from time import sleep
from setproctitle import setproctitle
import multiprocessing
from multiprocessing.managers import SyncManager
import concurrent.futures
from ctypes import cdll, CFUNCTYPE, c_char_p, c_int
from contextlib import contextmanager
import shlex
import pyaudio
import subprocess
import asyncio
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
#-#from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.t2s_lib import Text2SpeechXunFei
from applib.t2s_lib import Text2SpeechBaidu
from applib.log_lib import get_lan_ip
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


# http://stackoverflow.com/questions/7088672/pyaudio-working-but-spits-out-error-messages-each-time
ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)


def py_error_handler(filename, line, function, err, fmt):
    pass

c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)


@contextmanager
def noalsaerr():
    asound = cdll.LoadLibrary('libasound.so')
    asound.snd_lib_error_set_handler(c_error_handler)
    yield
    asound.snd_lib_error_set_handler(None)


def server_manager(address, authkey):
    mgr = SyncManager(address, authkey)
    setproctitle('process_mgr')
    debug('manager server started.')
    server = mgr.get_server()
    server.serve_forever()
    debug('manager server stopped.')


def noop_func(x):
#-#    pass
    sleep(1)
    setproctitle('text_2_audio_noop')


class PlaySound(object):
    def __init__(self, conf_path='config/pn_conf.yaml'):
        # input param
        self.conf_path = conf_path
        self.conf = getConf(self.conf_path, root_key='audio')
        if self.conf['target'] == 'pi':
            self.t2s = Text2SpeechBaidu(self.conf_path)  # sync
        else:
            self.t2s = Text2SpeechXunFei(self.conf_path)  # sync
        self.executor_t2s = concurrent.futures.ProcessPoolExecutor(2)  # async
        if self.conf['use_custom_manager']:
            # start remote manager
            p_mgr = multiprocessing.Process(target=server_manager, args=((get_lan_ip(), self.conf['custom_manager_port']), self.conf['custom_manager_authkey'].encode('utf8')))
            p_mgr.start()
            # create proxy manager
            mgr = SyncManager((get_lan_ip(), self.conf['custom_manager_port']), self.conf['custom_manager_authkey'].encode('utf8'))
            sleep(0.5)  # wait for manager to start
            mgr.connect()
        else:
            mgr = multiprocessing.Manager()
        self.q_audio = mgr.Queue()
#-#        debug('audio data queue created. %s', self.q_audio)
        self.event_exit = mgr.Event()
        multiprocessing.current_process().authkey = self.conf['custom_manager_authkey'].encode('utf8')  # https://bugs.python.org/issue7503
        self.proc_play = multiprocessing.Process(target=self.playAudioFromQ, args=(self.q_audio, self.event_exit))
        self.proc_play.start()
#-#        debug('play background proc start. %s', self.proc_play)
        # 触发进程池worker进程创建, 貌似提前创建的占用内存小些
        self.executor_t2s.map(noop_func, (None, None))

    def _text2Audio(self, text):
        """text data => audio data
        """
        new_text = re.sub('(\d+-\d+)', lambda x: x.group(1).replace('-', '减'), text, re.U)
        if new_text != text:
            info('%s -> %s', text, new_text)
        # call tts
        if self.conf['target'] == 'pi':
            loop = asyncio.get_event_loop()
#-#            future = asyncio.Future()
#-#            asyncio.ensure_future(Text2SpeechBaidu(self.conf_path).short_t2s(from_text=new_text.encode('utf8'), fut=future))
#-#            audio_data = loop.run_until_complete(Text2SpeechBaidu(self.conf_path).short_t2s(from_text=new_text.encode('utf8')))
            audio_data = loop.run_until_complete(self.short_t2s(from_text=new_text.encode('utf8')))
#-#            audio_data = future.result()
            loop.close()
        else:
            audio_data = self.t2s.short_t2s(from_text=new_text.encode('utf8'))
        return audio_data

    def playText(self, text, tp='pyaudio'):
        audio_data = self._text2Audio(text)
        self.playAudio(audio_data, tp=tp)

    def playTextFile(self, text_file_path, tp='pyaudio'):
        self.playText(open(text_file_path).read().encode('utf8'))

    def playAudio(self, audio_data, tp='mplayer_mp3'):
        if tp == 'mplayer_mp3':
            cmd = 'mplayer -novideo -nolirc -cache 1024 -really-quiet -'
            cmd = shlex.split(cmd)
#-#            debug('EXEC_CMD< %s ...', cmd)
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            try:
                outs, errs = proc.communicate(audio_data, timeout=30)
                proc.kill()
                outs, errs = proc.communicate()
                proc.terminate()
            except subprocess.TimeoutExpired:
                warn('kill timeout proc %s', proc)
                proc.kill()
                outs, errs = proc.communicate()
        elif tp == 'mplayer':
            cmd = 'mplayer -demuxer rawaudio -rawaudio channels=1:rate=16000:bitrate=16  -novideo -really-quiet -noconsolecontrols -nolirc -'
            cmd = shlex.split(cmd)
            debug('EXEC_CMD< %s ...', cmd)
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            try:
                outs, errs = proc.communicate(audio_data, timeout=30)
            except subprocess.TimeoutExpired:
                warn('kill timeout proc %s', proc)
                proc.kill()
                outs, errs = proc.communicate()
        elif tp == 'ao':
            import ao
            ao.AudioDevice('raw', bits=16, rate=16000, channels=1).play(audio_data)
        elif tp == 'pcm':
            import alsaaudio
            pcm = alsaaudio.PCM(card='Intel')
            pcm.setchannels(2)
            pcm.setrate(16000)
            pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            # play pcm file from tts
            pcm.write(audio_data)
            del pcm
        if tp == 'pyaudio':
            with noalsaerr():
                p = pyaudio.PyAudio()
#-#            stream = p.open(format=p.get_format_from_width(2), channels=2, rate=16000, output=True)
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, output=True)
            stream.write(audio_data)
            sleep(0.5)  # wait steam play done
            stream.stop_stream()
            stream.close()
            p.terminate()

    def playAudioFile(self, audio_file, tp='pyaudio'):
        assert os.path.exists(audio_file)
        if tp == 'mplayer':
            audio_size = open.path.getsize(audio_file)
            if audio_size > 1024 * 1024:
                cmd = 'mplayer -demuxer rawaudio -rawaudio channels=1:rate=16000:bitrate=16 -softvol -volume 10 -novideo %s' % audio_file
                info('EXEC_CMD< %s ...', cmd)
                subprocess.Popen(cmd, shell=True).wait()
            else:
                self.playAudio(open(audio_file, 'rb').read(), tp=tp)
        elif tp == 'ao':
            self.playAudio(open(audio_file, 'rb').read(), tp=tp)
        elif tp == 'pcm':
            self.playAudio(open(audio_file, 'rb').read(), tp=tp)
        elif tp == 'pyaudio':
            subprocess.Popen('cmus-remote -u', shell=True).wait()
            self.playAudio(open(audio_file, 'rb').read(), tp=tp)
            subprocess.Popen('cmus-remote -u', shell=True).wait()

    def playTextAsync(self, text, extra_data, tp='mplayer_mp3'):
        """async support
        """
        self.executor_t2s.submit(text2AudioAsync, self.conf['target'], self.conf_path, text, tp, extra_data, self.q_audio)

    def playAudioFromQ(self, q_audio, event_exit):
        """async support
        """
        setproctitle('audio_play')
        debug('audio play process started.')
        while 1:
            try:
                text, audio_data, tp, extra_data = q_audio.get()
            except KeyboardInterrupt:
                warn('got KeyboardInterrupt when playing, exit!')
                break
            except Exception as e:
                warn('got exception when playing, exit! %s', e)
                break
            else:
                if not audio_data:
                    info('(no audio data to play) [%s] %s (%s) %s --> %s', extra_data['from_title'], text, '/'.join(extra_data['cut_word']), extra_data['item_url'], extra_data['real_url'])
                    continue

                if not text and not audio_data:
                    info('break !!!')
                    break
                info('(%s left) [%s] %s (%s) %s --> %s', q_audio.qsize(), extra_data['from_title'], text, '/'.join(extra_data['cut_word']), extra_data['item_url'], extra_data['real_url'])
                try:
                    subprocess.Popen('cmus-remote -u', stderr=subprocess.DEVNULL, shell=True).wait()
                    self.playAudio(audio_data, tp)
                    subprocess.Popen('cmus-remote -u', stderr=subprocess.DEVNULL, shell=True).wait()
                except KeyboardInterrupt:
                    warn('got KeyboardInterrupt when playing, exit!')
                    break
                except Exception as e:
                    warn('got exception when playing, exit! %s', e)
                    break
                if event_exit.is_set():
                    info('got exit flas, exit ~')
                    break

    def clean(self):
        info('audio closing ...')
        if self.executor_t2s:
            self.executor_t2s.shutdown()
        if self.proc_play and self.proc_play.is_alive():
            self.proc_play.join()
        info('audio closed.')


def text2AudioAsync(target, conf_path, text, tp, extra_data, q_audio):
    """text data => audio data
    """
    setproctitle('text_2_audio')
    new_text = text.replace('*', '乘')
    new_text = re.sub('(?:[0-9\.]+-\d+)券', lambda x: x.group(0).replace('-', '减'), new_text, re.U)
    new_text = re.sub('满(?:[0-9\.]+-\d+)元', lambda x: x.group(0).replace('-', '减'), new_text, re.U)
    new_text = re.sub('\d+?(?:个|元|g)?/(?:件|袋|个|包|块)?', lambda x: x.group(0).replace('/', '每'), new_text, re.U)

    if new_text != text:
        debug('%s -> %s', text, new_text)
    # call tts
    if target == 'pi':
        loop = asyncio.get_event_loop()
#-#        future = asyncio.Future()
#-#        asyncio.ensure_future(Text2SpeechBaidu(conf_path).short_t2s(from_text=new_text.encode('utf8'), fut=future))
        audio_data = loop.run_until_complete(Text2SpeechBaidu(conf_path).short_t2s(from_text=new_text.encode('utf8')))
#-#        audio_data = future.result()
#-#        loop.close()
        tp = 'mplayer_mp3'
    else:
        audio_data = Text2SpeechXunFei(conf_path).short_t2s(from_text=new_text.encode('utf8'))
        tp = 'pyaudio'
    # to audio queue
    q_audio.put([text, audio_data, tp, extra_data])


if __name__ == '__main__':
    ps = PlaySound()
    extra_data = {}
    extra_data['from_title'] = '测试标题'
    extra_data['item_url'] = '测试url'
    extra_data['real_url'] = '真实url'
    extra_data['cut_word'] = ['这是', '一个', '测试']
    ps.playTextAsync('测试信息, 开始看的人, 有个', extra_data)
    ps.clean()
