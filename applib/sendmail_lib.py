import argparse
import os
import sys
# import time
# import json
# from datetime import date
# from datetime import datetime
# from datetime import timedelta
# from collections import defaultdict
from pprint import pformat
from itertools import chain
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.utils import COMMASPACE
import mimetypes
from applib.log_lib import app_log
info, debug, error = app_log.info, app_log.debug, app_log.error


MAIL_CONFIG = {'smtp_server': '',
               'smtp_port': 0,
               'user': '',
               'pwd': '',
               }


def flat_list(x):
    for _x in x:
        if isinstance(_x, (list, tuple)):
            for _f in _x:
                yield _f
        else:
            yield _x


def get_args():
    def _cfg_wrapper():
        pass
    cfg = _cfg_wrapper
    parser = argparse.ArgumentParser(description='This app is used to send mail', epilog='Please always execute this app in its directory !')
#    parser.add_argument('-t', '--test_mode', dest='test_mode', action='store_true', help='in test mode, default is not in test mode', default=False)
    parser.add_argument('-f', '--from', dest='from_address', help='', type=str, default=MAIL_CONFIG['user'])
    parser.add_argument('-t', '--to', dest='to_address', help='', action='append', nargs='*', default=[])
    parser.add_argument('-c', '--cc', dest='cc_address', help='', action='append', nargs='*', default=[])
    parser.add_argument('-s', '--subject', dest='subject', help='', type=str, default='no subject')
    parser.add_argument('-b', '--body', dest='body', help='', type=str, default='<html><body>no body</body></html>')
    parser.add_argument('-a', '--attachment_file', dest='attachment_file', help='', action='append', nargs='*', default=[])
    args = parser.parse_args()
    cfg._from = args.from_address
    cfg._to = list(flat_list(args.to_address))
    if not cfg._to:
        cfg._to = [MAIL_CONFIG['user'], ]
    cfg._cc = list(flat_list(args.cc_address))
    cfg._subject = args.subject
    cfg._body = args.body
    l_file = []
    for _f in flat_list(args.attachment_file):
        if not os.path.exists(_f):
            info(f'attachment file not exists {_f}')
            continue
        l_file.append(_f)
    cfg._attached_file = l_file
    info(f'\ncmd: {sys.argv}\nargs: \n{pformat(cfg.__dict__)}')
    return cfg


def send_mail(smtp_server, smtp_port, smtp_user, smtp_password, from_address, to_addresses, cc_addresses, subject, body_file, attachment_files):
    rtn = False
    msgroot = MIMEMultipart('related')
#    msgroot['Subject'] = Header("%s(%s)"%(subject, datetime.date.today()), 'gbk')
    msgroot['Subject'] = Header("%s" % (subject, ), 'utf8')
    if not from_address:
        from_address = smtp_user
    msgroot['From'] = from_address
    msgroot['To'] = COMMASPACE.join(to_addresses)
    msgroot['Cc'] = COMMASPACE.join(cc_addresses)
    msgroot.preamble = 'This is a multi-part message in MIME format.'
    msgroot.epilogue = ''

    msgAlternative = MIMEMultipart('alternative')
    msgroot.attach(msgAlternative)
    textbody = MIMEText('This is the alternative plain text message.')
    msgAlternative.attach(textbody)

    htmlbody = MIMEText(body_file, 'html', 'utf8')
    msgAlternative.attach(htmlbody)

    for _file_name in attachment_files:
        ftype, fsubtype = 'application', 'octet-stream'
        guesstype, _ = mimetypes.guess_type(_file_name)
        _file_content = open(_file_name).read()
        if guesstype:
            ftype, fsubtype = guesstype.split('/')

        if any(_ext in _file_name for _ext in ('.jpg', '.bmp', '.jpeg', '.png', '.gif')):
            info(f'detect image file (guesstype {guesstype}): {_file_name}, len(_file_content)={len(_file_content)}')
            part = MIMEImage(_file_content, fsubtype)
            part.add_header("Content-ID", "<%s>" % os.path.basename(_file_name))
        else:
            part = MIMEBase(ftype, fsubtype)
            part.set_payload(_file_content, 'utf8')
            part.add_header('Content-Disposition', 'inline', filename=os.path.basename(_file_name))
        msgroot.attach(part)

#    _stderr = sys.stderr
#    _f_name = os.path.join('/data/api-log/' if os.path.exists('/data/api-log/') else '/tmp', 'sendmail_dbg-%s.txt' % date.today())
#    _f = open(_f_name, 'a')
#    _f.write('\n\n\n%s %s %s\n\n' % ('-*' * 20, datetime.today(), '-*' * 20))
#    info('smtp debug output to %s', _f_name)
#    smtplib.stderr = _f
#    smtp = smtplib.SMTP()
    smtp = smtplib.SMTP(smtp_server)
#    smtp.set_debuglevel(1)
    while True:
        info(f'connecting mail server {smtp_server}:{smtp_port} ...')
        try:
            smtp.connect(smtp_server, smtp_port)
            break
        except smtplib.SMTPConnectError:
            info('got SMTPConnectError when trying to connect mail server ! while try after 30 seconds.')
        except Exception as e:
            info(f'got Error: {e}')
            return rtn

    try:
        try:
            smtp.starttls()
        except (smtplib.SMTPHeloError, smtplib.SMTPException, RuntimeError):
            pass
        smtp.login(smtp_user, smtp_password)
        info('login ok.')
        to = list(chain(to_addresses, cc_addresses))
        info(f'send to: {to} ...')
        smtp.sendmail(msgroot['From'], to, msgroot.as_string())
        info('send ok.')
        rtn = True
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPHeloError, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
        info(f'got {e}')
    finally:
        smtp.close()

#    _f.close()
#    smtplib.stderr = _stderr
    return rtn


if __name__ == '__main__':
    cfg = get_args()
    send_mail(MAIL_CONFIG['smtp_server'], MAIL_CONFIG['smtp_port'], MAIL_CONFIG['user'], MAIL_CONFIG['pwd'], cfg._from, cfg._to, cfg._cc, cfg._subject, cfg._body, cfg._attached_file)
