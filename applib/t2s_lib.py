import ctypes
import ctypes.util
import argparse
import os
from io import BytesIO
import sys
import time
import codecs
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
#-#from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error

TTS_FLAG_DATA_END = 2


class Text2Speech(object):

    def __init__(self, conf_path='config/pn_conf.yaml'):
        # input param
        self.conf_path = conf_path
        self.from_text = None  # 保存短小的待转换文字
        self.from_file = None
        self.to_file = None
        self.only_print_result = None
        self.short_mode = None
        self.conf = getConf(self.conf_path, root_key='t2s')
        if __name__ == '__main__':
            self.getArgs()

        # interval use
        self.dl = None  # msc handler

    def getArgs(self):
        '''获取输入的参数
        '''
        parser = argparse.ArgumentParser()
        parser.add_argument('--version', action='version', version='%(prog)s 20170221')
        parser.add_argument('-l', '--print_only', dest='only_print_result', action='store_true', help='don\'t update db, just print stat result')
        parser.add_argument('-f', '--from', dest='from_file', help='input file', default=None)
        parser.add_argument('-t', '--to', dest='to_file', help='output file', default=None)
        parser.add_argument('-s', '--short', dest='short_mode', action='store_true', help='in short text mode')
        options = parser.parse_args()
        if not options.from_file or not options.to_file:
            parser.print_usage()
            sys.exit(-1)

        if not os.path.exists(options.from_file):
            info('input file doesn\'t exists!')
            sys.exit(-2)

        self.from_file = options.from_file
        self.to_file = options.to_file
        self.only_print_result = options.only_print_result
        self.short_mode = options.short_mode

    def _init(self):
        '''载入libmsc.so, 并调用初始化函数
        '''
        if not self.dl:
            self.dl = ctypes.CDLL('libmsc.so')

        ret = self.dl.MSPLogin(self.conf['username'].encode('utf-8'), self.conf['password'].encode('utf-8'), ('appid = %s, work_dir = %s' % (self.conf['appid'], self.conf['workdir'])).encode('utf-8'))
        if ret != 0:
            warn('_init error! %s', ret)
            return

    def _fini(self):
        '''调用结束函数，释放libmsc.so
        '''
        if self.dl:
            self.dl.MSPLogout()
            self.dl = None

    def doWork(self):
        '''工作入口函数
        '''
        try:
            self._init()
            if self.short_mode:
                self.process_short()
            else:
                self.process()
        except KeyboardInterrupt:
            pass
        finally:
            self._fini()

    def short_t2s(self, from_text=None, from_file=None, to_file=None):
        ret = None
        try:
            self._init()
            self.from_file = from_file
            self.from_text = from_text
            self.to_file = to_file
            ret = self.process_short()
        except KeyboardInterrupt:
            pass
        finally:
            self._fini()

        return ret

    def _process_each(self, text_in):
        ok = True
        # create session
        volLen, synthStatus, errorCode, ret = ctypes.c_uint(0), ctypes.c_int(1), ctypes.c_int(0), ctypes.c_int(0)
        sess_param = "voice_name = xiaoyan, text_encoding = utf8, sample_rate = 16000, speed = 60, volume = 100, pitch = 50, rdn = 3".encode('utf8')
        s_vol = BytesIO()
        # sess begin
        sess_id = self.dl.QTTSSessionBegin(ctypes.c_char_p(sess_param), ctypes.byref(ret))
        if ret.value != 0:
            info('QTTSSessionBegin() failed! %d', ret.value)
            return None, False
        # put text
        rslt = self.dl.QTTSTextPut(sess_id, ctypes.c_char_p(b''.join((text_in, '、'.encode('utf-8')))), ctypes.c_int(len(text_in) + len('、'.encode('utf-8'))), None)
        if rslt != 0:
            warn('QTTSTextPut() failed! %s', rslt)
            return None, False
        # get audio in loop
        synthStatus.value = 1  # reset
        func = self.dl.QTTSAudioGet
        func.restype = ctypes.c_void_p
        total_pcm_size = 0
        while TTS_FLAG_DATA_END != synthStatus.value:
            retData = func(sess_id, ctypes.byref(volLen), ctypes.byref(synthStatus), ctypes.byref(errorCode))
            if errorCode.value != 0:
                warn('QTTSAudioGet() failed! %s', errorCode.value)
                s_vol.truncate(0)
                ok = False
                break
            if retData:
                total_pcm_size += volLen.value
                s_vol.write(ctypes.string_at(retData, volLen.value))
            else:
                print('.', end='', file=sys.stderr, flush=True)
                time.sleep(0.8)
        # sess end
        rslt = self.dl.QTTSSessionEnd(sess_id, b"success")
        if rslt != 0:
            warn('QTTSSessionEnd() failed! %s', rslt)

        s = s_vol.getvalue()
        s_vol.close()
        return s, ok

    def process_short(self):
        if not self.from_text:
            assert os.path.exists(self.from_file)
            tmp_text = open(self.from_file).read().encode('utf8')
        else:
            tmp_text = self.from_text
        s, ok = self._process_each(tmp_text)
        if ok and s:
            if self.to_file:
                with open(self.to_file, 'wb') as out_file:
                    out_file.write(s)
                    info('audio file saved %s', self.to_file)
            info('audio data returned. %s bytes', format(len(s), ','))
            return s
        else:
            warn('t2s failed !!!')

    def process(self):
        '''执行具体工作的函数
        '''
        # open output file
        out_file = open(self.to_file, 'wb')

        flag_ok = True  # indicate error in loop
        cnt = 0
        size_per_call = 1000

        # get part text from input content
        p = CParagraphText(self.from_file)
        total_bytes = p.readFile()
        cur_bytes = 0
        tmp_text = p.getPartText('utf-8', size_per_call)
        while flag_ok and tmp_text != '':
            cnt += 1
            cur_bytes += len(tmp_text)
            info('#%d %d byte(s) sent. %d/%d %.2f%%', cnt, len(tmp_text), cur_bytes, total_bytes, 100.0 * cur_bytes / total_bytes)
            tmp_text = p.getPartText('utf-8', size_per_call)
            s, flag_ok = self._process_each(tmp_text)
            if not flag_ok:
                info('break at progress = %d', p.getProgress())
                break
            if s:
                out_file.write(s)
        out_file.close()
        info('done.')


class CParagraphText(object):

    def __init__(self, filename):
        self.encodings = ('utf-8', 'gb2312', 'gbk', 'gb18030')

        self.filename = filename
        self.s = None  # text to be sent to tts
        self.idx_start = None
        self.idx_end = None
        self.idx_cur = None
        # const
        self.paragraph_sep_words = ('\n', '。', '！', '!', '？', '?', '；', ';', '……', '，', ',', '————')
#-#        self.paragraph_sep_words=(u'\n', u'。', u'.', u'！', u'!', u'？', u'?', u'；', u';', u'……', u'，', u',', u'————')

    def readFile(self):
        total_bytes = os.stat(self.filename).st_size
        # read input file content and convert to unicode
        to_code = 'utf-8'
        s = None
        for from_code in self.encodings:
            try:
                s = codecs.EncodedFile(open(self.filename, 'rb'), to_code, from_code).read()
                break
            except UnicodeDecodeError:
                pass
        if not s:
            info('can\'t read content from file %s !', self.filename)
            return
#-#        info('got %d byte(s) from file %s', len(s), self.filename)
        self.s = s.decode(to_code)
        self.idx_start = 0
        self.idx_end = len(self.s)
        self.idx_cur = 0
        info('got %d byte(s), %d char(s) from file %s', total_bytes, self.idx_end, self.filename)
        return total_bytes

    def getPartText(self, to_code='utf-8', byte_limit=None):
        '''从文本中获取以 to_code 编码后长度不超过 byte_limit 的最长的完整文本并做为返回值。
        反复调用直到返回空字符串表示所有文本已经获取完毕。
        '''
        if not self.s:
            info('s is empty!')
            return ''

        limit = 4096 if byte_limit is None or byte_limit > 4096 or byte_limit <= 0 else byte_limit

        # adjust to fit intact paragraph if possible
        tmp_encoded_s = None
        idx = 0
        done = False
        for w in self.paragraph_sep_words:
            i = self.idx_start + limit  # init value indicate the end index
            while not done:
                idx = self.s.rfind(w, self.idx_start, i)
#-#                debug('find %s in [%d, %d] %d', repr(w), self.idx_start, i, idx)
                if idx == -1:
                    break

                # find one sep word
                tmp_encoded_s = self.s[self.idx_start: idx + 1].encode(to_code)  # +1 to include sep word found
                if len(tmp_encoded_s) > limit:
#-#                    debug('len(tmp_encoded_s) = %d', len(tmp_encoded_s))
                    i = idx  # decrease to prepare to find in next loop
                    continue

                done = True

            if done:
                break

        if done:
            self.idx_cur = self.idx_start  # save current index for resume
            self.idx_start = idx + 1  # skip sep word
        else:  # divide by char
            i = self.idx_start + limit  # init value indicate the end index
            tmp_encoded_s = self.s[self.idx_start: i].encode(to_code)
            while len(tmp_encoded_s) > limit:
                tmp_encoded_s = None
                if i == 1:
                    break

                i -= 1
                tmp_encoded_s = self.s[self.idx_start: i].encode(to_code)

            self.idx_cur = self.idx_start  # save current index for resume
            self.idx_start = i

        if not tmp_encoded_s:
            tmp_encoded_s = ''

        info('idx_start/idx_end=%d/%d', self.idx_start, self.idx_end)
        debug('return %d byte(s)', len(tmp_encoded_s))
        return tmp_encoded_s

    def getProgress(self):
        '''获取当前的进度。下一次就可以从这里重新开始。
        '''
        return self.idx_cur


if __name__ == '__main__':

    t2s = Text2Speech()
    t2s.getArgs()
    t2s.doWork()
    sys.exit(0)

    t = CParagraphText('/home/kevin/qqts-5-20.txt')
    t = CParagraphText('/tmp/t2s_input.txt')
    total = t.readFile()
    cur = 0
    while True:
        s = t.getPartText('utf-8', 1024)
        if not s:
            break
        cur += len(s)
        print('s %d/%d = %s\n' % (cur, total, s))
        print('%s\n' % ('*' * 50,))
