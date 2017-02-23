#coding=utf8

import os
import logging
import logging.handlers
import socket
#-#import sys
import struct
import colorlog
#-#from logging import Formatter

if os.name != 'nt':
    import fcntl


def get_lan_ip():
    interfaces = [
        'eth0',
        'eth1',
        'eth2',
        'wlan0',
        'wlan1',
        'wifi0',
        'ath0',
        'ath1',
        'ppp0',
    ]
    ip = socket.gethostbyname(socket.gethostname())
    if os.name != 'nt':
        for ifname in interfaces:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                ip = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s', bytes(ifname.encode('utf8'))))[20:24])
                break
            except IOError:
                pass
    return ip


class MPFormatter(logging.Formatter):
    u'''定制多进程文件日志输出格式
    '''
    server = get_lan_ip()

    def format(self, record):
        record.server = self.__class__.server
        return super(MPFormatter, self).format(record)


class InternalLog(object):
    u'''日志类，实现file和console分开输出
    '''
    _logger = None

    @classmethod
    def getLogger(cls):
        if cls._logger:
            print('use existing logger')
            return cls._logger

        logging.captureWarnings(True)
        cls._logger = logging.getLogger()
        cls._logger.setLevel(logging.DEBUG)
        cls._logger.propagate = 0
        # remove existing handler from root logger
        l_2del = [_h for _h in cls._logger.handlers if isinstance(_h, logging.StreamHandler)]
        for _h in l_2del:
            cls._logger.removeHandler(_h)

        # stream log
        log_sh = colorlog.StreamHandler()
        log_sh.setLevel(logging.DEBUG)
        fmt = colorlog.ColoredFormatter('%(log_color)s%(asctime)s %(levelname)1.1s %(processName)s %(module)s %(funcName)s %(lineno)d |%(message_log_color)s%(message)s',
                                        log_colors={'DEBUG': 'cyan',
                                                    'INFO': 'white',
                                                    'WARNING': 'purple',
                                                    'ERROR': 'red',
                                                    'CRITICAL': 'red',
                                                    },
                                        secondary_log_colors={'message': {'ERROR': 'red,bg_yellow',
                                                                          'CRITICAL': 'red,bg_white',
                                                                          'WARNING': 'yellow,bg_blue',
                                                                          }
                                                              },
                                        datefmt='%H:%M:%S')
        log_sh.setFormatter(fmt)
        print('logger handler StreamHandler init done.', flush=True)

        log_handlers = [log_sh]
        for hdl in log_handlers:
            cls._logger.addHandler(hdl)  # add handler(s) to root logger
            if isinstance(hdl, logging.handlers.RotatingFileHandler) or isinstance(hdl, logging.FileHandler):
                print('log file %s %s' % (hdl.baseFilename, hdl.mode), flush=True)
        cls._logger.info('root logger init done. script dir %s' % (os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)), ))
        return cls._logger


app_log = InternalLog.getLogger()
info, debug, error = app_log.info, app_log.debug, app_log.error

