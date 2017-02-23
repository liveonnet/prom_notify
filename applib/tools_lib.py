import os
import sys
import json
import collections
from datetime import date
import re
from functools import partial
from itertools import chain
import pprint
from io import StringIO
import html.entities
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from datetime import datetime
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.log_lib import app_log
info, debug, error, warn = app_log.info, app_log.debug, app_log.error, app_log.warning


#升级json中的日期处理
class CJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(obj, date):
            return obj.strftime('%Y-%m-%d')
        else:
            return json.JSONEncoder.default(self, obj)


class Tools(object):

    '''
    classdocs
    '''
    idcard_weight = [pow(2, i, 11) for i in range(17, 0, -1)]
    idcard_bit = '1 0 X 9 8 7 6 5 4 3 2'.split()

    def __init__(self):
        '''
        Constructor
        '''

    @staticmethod
    def ver_cmp(v1, v2, sep='.'):
        '''任何输入都是合法的版本号名称， 所以不会抛出异常
           考虑到的几种case

            *  1.2 == 1.2.0
            *  1.02 == 1.2.0
            *  1.3 > 1.2.9
            *  1.11.0 > 1.2.9
            *  1.2.3 < 1.2.9
        '''
        try:
            arr_v1 = v1.split(sep)
            arr_v2 = v2.split(sep)
            for i in range(max(len(arr_v1), len(arr_v2))):
                if i >= len(arr_v1):
                    if int(arr_v2[i]):
                        return -1
                elif i >= len(arr_v2):
                    if int(arr_v1[i]):
                        return 1
                else:
                    if int(arr_v1[i]) > int(arr_v2[i]):
                        return 1
                    elif int(arr_v1[i]) < int(arr_v2[i]):
                        return -1
            return 0
        except Exception:
            return cmp(v1, v2)

    @staticmethod
    def get_major_version(ver, sep='.'):
        '''
           返回主本版本（即前三位）， 版本号不足的补1（当前的版本策略是从1开始的）
        '''
        arr_ver = [_f for _f in ver.split(sep) if _f]  # '1..1.' == '1.1'
        [arr_ver.append('1') for i in range(3 - len(arr_ver))]
        return sep.join(arr_ver[:3])

    @staticmethod
    def checkIDCard(id_card):
        '''检查身份证号码是否符合规范
        '''
        if not id_card:
            return False, '没有填写身份证号码'

        if len(id_card) != 18 or not id_card[:-1].isdigit() or id_card[-1] not in Tools.idcard_bit:
            return False, '身份证号码位数/格式错误'

        if id_card[0] in ('0', '9'):
            return False, '身份证号码行政区代码错误'

        check_bit = Tools.idcard_bit[sum(int(_c) * Tools.idcard_weight[_i] for _i, _c in enumerate(id_card[:-1])) % 11]
        if check_bit != id_card[-1]:
#-#            info('check_bit %s', check_bit)
            return False, '身份证号码校验位错误'

        try:
            birth_day = datetime.strptime(id_card[6:14], '%Y%m%d')
#-#            info('birth_day: %s', birth_day)
        except ValueError:
            return False, '身份证日期无效'
        else:
            if not (1920 <= birth_day.year <= 2010):
                return False, '身份证日期不合理'

        return True, ''

    @staticmethod
    def _get_imei_check_code(imei):
        '''计算imei的校验位

        移植自 ::

            function get_IMEI_check_code($imei)
            {
                $sum1=0;
                $sum2=0;
                for($i=0;$i<14;$i++)
                {
                if($i%2==0)
                {
                    $sum1 = $sum1 +hexdec( $imei[$i]);
                }
                else
                {
                    $temp = hexdec( $imei[$i])*2;
                        if ($temp<10)
                        {
                            $sum2=$sum2+$temp;
                        }
                        else
                        {
                        $sum2 = $sum2 + 1 + $temp - 10;
                        }
                }
                }
                $total = $sum1+$sum2;
                if ($total%10 == 0)
                {
                return '0';
                }
                else
                {
                return (10 - $total%10);
                }
            }
        '''
        sum1, sum2 = 0, 0
        for _i, _c in enumerate(imei[:14]):
            if _i % 2 == 0:
                sum1 += int(_c, 16)
            else:
                tmp = int(_c, 16) * 2
                if tmp < 10:
                    sum2 += tmp
                else:
                    sum2 += (1 + tmp - 10)
        total = sum1 + sum2
        if total % 10 == 0:
            return '0'
        else:
            return chr(0x30 + 10 - total % 10)

    @staticmethod
    def checkDeviceId(device_id):
        ''' 判断device_id(android的device_id，ios的idfa)是否规范

        * 校验长度是否是 14，15，36
        * 如果是14位，判断device_id是否以'a0'或者'a1'或'99'开头
        * 如果是15位，判断device_id校验位是否正确
        * 如果是36位，判断是否按'-'分为5组，各组长度分别为 8,4,4,4,12

        ``return`` True校验通过  False校验不通过

        移植自::

            function is_IMEI_valid($imei)
            {
            if(strlen($imei)!=15)
            {
                return true;//对15位以外的imei目前暂时无法处理
            }
            if(strlen($imei)==15 && (strpos(strtolower($imei),'a0')===0 || strpos(strtolower($imei),'a1')===0))
            {
                return true;
            }
            return $imei[14] == get_IMEI_check_code($imei);
            }
        '''
        if not device_id or not len(device_id) in (15, 14, 36):
            return False
        dev_len = len(device_id)
        if dev_len == 15:
            if not device_id.isdigit():
                return False
            if device_id[14] != Tools._get_imei_check_code(device_id):
                return False
        elif dev_len == 36:
            l_part = device_id.split('-')
            if len(l_part) != 5:
                return False
            if tuple(len(_x) for _x in l_part) != tuple((8, 4, 4, 4, 12)):
                return False
        else:  # 14 位
            if not device_id.lower().startswith(('a0', 'a1', '99')):
                return False

        return True

    @staticmethod
    def getUnit(os_type, app_version):
        if (os_type == 'android' and app_version >= '3.2.1.0' and app_version < '3.3') or (os_type == 'ios' and app_version >= '1.6.0'):
            return '红包币'
        return '元'

    @staticmethod
    def needToChangeUnit(os_type, app_version):
        return (os_type == 'android' and app_version >= '3.2.1.0' and app_version < '3.3') or (os_type == 'ios' and app_version >= '1.6.0')

    @staticmethod
    def replaceUnit(str):
        return str.replace('元', '红包币')


def format(_obj, context, maxlevels, level):
    if isinstance(_obj, bytes):
#-#        return (repr(_obj.encode('utf8')) or "''", False, False)
        return (("'" + _obj.decode('utf8') + "'") or "''", False, False)
    if isinstance(_obj, str):
        if unquote(_obj) == _obj:
            return (repr(_obj) or "''", False, False)
        else:
#-#            return (repr(unquote(_obj).decode('unicode-escape').encode('utf8')) or "''", False, False)
            return (("'" + unquote(_obj).decode('unicode-escape').encode('utf8') + "'") or "''", False, False)
    return pprint._safe_repr(_obj, context, maxlevels, level)
pp = pprint.PrettyPrinter(width=160)
pp.format = format
pcformat = pp.pformat


class Dummy(object):
    '''支持pickle的基类
    '''
    def __getstate__(self):
        d_var = dict((k, v) for k, v in self.__dict__.items() if (not k.startswith('__')) and (not isinstance(v, collections.Callable)))
#-#        print 'd_var = %s'%(d_var, )
        return d_var

    def __setstate(self, state):
        self.__dict__.update(state)


class MyBreak(Exception):
    '''用于从深层逻辑中直接退出
    '''
    pass


def parseXml2Dict(xml_data):
    '''简单实现，不支持多级元素，不支持属性,一般不直接调用
    '''
    j_data = {}
    try:
        root = ET.fromstring(xml_data)
        for _child in root.getchildren():
            j_data[_child.tag] = _child.text
    except:
#-#        error('解析xml失败\nxml=%s', repr(xml_data), exc_info=True)
        info('解析xml失败\nxml=%s', repr(xml_data))
    return j_data


def dict2Xml(d_data):
    '''基于字典对象 ``d_data`` 构造xml，不支持多级元素，不支持属性

    以key的字典序构造元素
    '''
    s = StringIO()
    s.write('<xml>')
    for _k, _v in sorted(d_data.items()):
        if _v:
            s.write('\n    <{NAME}><![CDATA[{VALUE}]]></{NAME}>'.format(NAME=_k.lower(), VALUE=_v))
    s.write('\n</xml>')
    return s.getvalue()


def enum_dict(**named_values):
    '''模拟枚举

    http://pythoncentral.io/how-to-implement-an-enum-in-python/

    >>> Color = enum(RED='red', GREEN='green', BLUE='blue')
    >>> Color.RED
    'red'
    >>> Color.GREEN
    'green'
    '''
    return type('Enum', (), named_values)


def enum_list(*args):
    '''模拟枚举

    >>> Gender = enum('MALE', 'FEMALE', 'N_A')
    >>> Gender.N_A
    2
    >>> Gender.MALE
    0
    '''
    enums = dict(list(zip(args, list(range(len(args))))))
    return type('Enum', (), enums)


class Dictate(object):

    """http://stackoverflow.com/questions/1305532/convert-python-dict-to-object
    Object view of a dict, updating the passed in dict when values are set
    or deleted. "Dictate" the contents of a dict...: """

    def __init__(self, d):
        # since __setattr__ is overridden, self.__dict = d doesn't work
        object.__setattr__(self, '_Dictate__dict', d)

    # Dictionary-like access / updates
    def __getitem__(self, name):
        value = self.__dict[name]
        if isinstance(value, dict):  # recursively view sub-dicts as objects
            value = Dictate(value)
        return value

    def __setitem__(self, name, value):
        self.__dict[name] = value

    def __delitem__(self, name):
        del self.__dict[name]

    # Object-like access / updates
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        del self[name]

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.__dict)

    def __str__(self):
        return str(self.__dict)


def str2_int_list(s, sep=','):
    return list(map(int, [_f for _f in s.split(sep) if _f]))


#-#def str2_int_set(s, sep=','):
#-#    return set(map(int, filter(None, s.split(sep))))


def str2_str_list(s, sep=','):
    '''将字符串 ``s`` 按分隔符 ``sep`` 分隔为列表，不保留空值
    '''
    return [_f for _f in (x.strip() for x in s.split(sep)) if _f]


#-#def str2_str_set(s, sep=','):
#-#    return set(filter(None, s.split(sep)))

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


class ArgValidator(object):
    '''简单的参数获取验证器
    封装参数获取、验证、转换的细节


    schema 例子::

        int(10, 20)&required&default=xxx
        int&required&default=xxx
        required
        required&default=xxx
        default=xxx
        default=xxx&required
        int
        int(10, 12)
        int(10)
        str

    参考实现 https://github.com/guyskk/validater

    '''
    PATTERN_SCHEMA = re.compile(r"^([^ \f\n\r\t\v()&]+)(\(.*\))?(&.*)?$")

    def add_arg_validator(self, arg_name, schema, add=True):
        '''获取一个验证参数 ``arg_name`` 的 ``schema``

        如果 ``add`` 为True（默认）则添加到此参数的默认 schema 列表中，否则只是返回解析后的 ``schema``

        ``schema``
         * ``vt``
         * ``args``
         * ``required``
         * ``default``

        '''
        try:
            l_arg = ArgValidator.PATTERN_SCHEMA.findall(schema)
            assert l_arg
        except:
            raise Exception('schema error %s' % (schema, ))
        else:
            rslt = {'arg_name': arg_name}
            vt_name, args, kwargs = l_arg[0]
#-#            info('schema: %s ', l_arg[0])
            if vt_name not in ArgValidator.BASE_VALIDATOR:  # 修正不指定基本验证器的情况，与kwargs参数拼接
                if args:
                    raise Exception('invalid schema %s' % schema)
                kwargs = vt_name + kwargs
                vt_name = ''
            if vt_name:
                rslt['vt'] = ArgValidator.BASE_VALIDATOR[vt_name]
            if args:
                try:
                    args = eval(args)
                except Exception as e:
                    raise Exception('invalid args: %s %s\n%s' % (schema, args, e))
                if not isinstance(args, tuple):
                    args = (args, )
                rslt['args'] = args
            if kwargs:
                for _x in kwargs[1 if kwargs[0] == '&' else 0:].split('&'):
                    _kv = _x.split('=')
                    if len(_kv) not in (1, 2):
                        raise Exception('invalid kwargs %s %s' % (schema, kwargs))
                    _k, _v = _kv[0], 'True' if len(_kv) == 1 else _kv[1]
                    rslt[_k] = eval(_v)

#-#            info('rslt: %s', rslt)
            if add:
                if not ArgValidator.ARG_VALIDATOR.get(arg_name):
                    ArgValidator.ARG_VALIDATOR[arg_name] = []
                ArgValidator.ARG_VALIDATOR[arg_name].append(rslt)
        return rslt

    @staticmethod
    def int_vt(value, start=None, stop=None):
        try:
            x = int(value or '0')  # 空字符串或None作为'0'看待
            if start is not None and x < start:
                return False, None
            if stop is not None and x > stop:
                return False, None
            return True, x
        except:
            return False, None

#-#    @staticmethod
#-#    def re_vt(p_re):
#-#        def vali(value):
#-#            try:
#-#                if value.match(p_re):
#-#                    return True, value
#-#                else:
#-#                    return False, ''
#-#            except:
#-#                return False, ''
#-#        vali.__doc__ = repr(p_re)
#-#        return vali

    @staticmethod
    def re_vt(value, p_re):
        try:
            if p_re.match(value):
                return True, value
            else:
                return False, ''
        except:
            return False, ''

    @staticmethod
    def type_vt(cls, convert=True, empty=None):
        def vali(value):
            if isinstance(value, cls):
                return True, value
            else:
                if convert:
                    try:
                        c = cls[0](value) if isinstance(cls, tuple) else cls(value)
                    except:
                        return False, empty
                    else:
                        return True, c
                return False, empty
        if isinstance(cls, tuple):
            name = '_'.join([_x.__name__ for _x in cls])
        else:
            name = cls.__name__
        vali.__name__ = str(name + '_validator')
        vali.__doc__ = repr(cls)
        return vali

    @staticmethod
    def date_vt(value, fmt='%Y-%m-%d', only_fmt=False, only_convert=False):
        try:
            if only_fmt:
                return True, value.strftime(fmt)
            elif only_convert:
                if isinstance(value, datetime.datetime):
                    return True, value.date()
                elif isinstance(value, datetime.date):
                    return True, value
                else:
                    return True, datetime.datetime.strptime(value, fmt).date()
            else:
                if isinstance(value, (datetime.date, datetime.datetime)):
                    return True, value.strftime(fmt)
                else:
                    return True, datetime.datetime.strptime(value, fmt).date()
        except:
            return False, None

    @staticmethod
    def str_vt(value, min_len=None, max_len=None, safe=True):
        try:
            if not isinstance(value, str):
                value = str(value)
            if safe:
                # TODO
                value = str(value or '')
            if min_len is not None and len(value) < min_len:
                return False, ''
            if max_len is not None and len(value) > max_len:
                return False, ''
        except:
            return False, ''
        return True, value

    @staticmethod
    def uid_vt(value):
#-#        info('校验 uid %s %s', type(value), value)
        try:
            value = int(value)
            assert 10000000 <= value <= 99999999
        except:
            info('校验 uid %s 失败', value)
            return False, ''
        return True, value

    @staticmethod
    def pnum_vt(value):
        try:
            _tmp = int(value)
            assert 13000000000 < _tmp < 39999999999  # 兼容300+<uid>的假手机号
        except:
            return False, ''
        return True, value

    def get_my_arg(self, *args, **kwargs):
        '''获取参数

        **arg**
         * ``args`` 参数名列表，如果指定了schema，则与参数名以空格分开，比如 'os_type required&default="'android'"'
         * ``kwargs`` 额外的控制参数，目前有
            * ``strict`` 是否严格检查，如果为True（默认）， 则碰到如下情况会终止后续检查并立即返回参数错误
                * ``schema`` 中指定了 ``required`` 但没有此参数且没有提供默认值 ``default``
                * 校验/转换类型出错出错，位数检查出错等情况

        **return**
         * ``l_arg`` 与输入的 ``args`` 顺序相同的校验/转换后的参数值列表
         * ``l_err``  与输入的 ``args`` 顺序相同的校验/转换 错误描述
        '''
        try:
            strict = kwargs.get('strict', True)
#-#            info('%s', ArgValidator.ARG_VALIDATOR)
            l_rslt, l_err = [], []
            for _arg_name in args:
                _arg_name = _arg_name.strip()
#-#                info('get/check %s ...', repr(_arg_name))
                if _arg_name.find(' ') != -1:
                    _arg_name, _arg_schema = _arg_name.split(' ', 1)
                    _arg_vt = self.add_arg_validator(_arg_name, _arg_schema, False)
#-#                    info('\tfound special schema %s', _arg_vt)
                else:
                    _arg_vt = None
                # 优化:
                # 对MY_AUTH为2的接口，因为执行到这里说明已经登陆成功，因此不校验这几个参数
                # 对MY_AUTH为1的接口，self.current_user为非空代表登陆成功，也不校验这几个参数
                if _arg_name in ('device_id', 'uid', 'pnum', 'pw', 'callback') and \
                        (self.__class__.MY_AUTH == 2 or (self.__class__.MY_AUTH == 1 and self.current_user)):
                    _arg_value = getattr(self, 'my_' + _arg_name, None)
#-#                    info('跳过检查 %s %s', _arg_name, _arg_value)
                    l_rslt.append(_arg_value)
                    continue
                else:
                    _arg_value = self.post_data.get(_arg_name)
                dft_vt = ArgValidator.ARG_VALIDATOR.get(_arg_name)
                old_len = len(l_rslt)  # 用于判断是否在下面的校验中添加过参数值了
                for _vt in chain(*(vt for vt in ((_arg_vt, ), dft_vt) if vt)):
                    if not _vt:
                        continue
#-#                    info('\tgot vt %s', _vt)
                    if _arg_value is None:  # 参数不存在
                        if 'required' in _vt:  # 缺必须参数
                            if 'default' not in _vt:  # 没有默认值
                                warn('\t[not pass] required arg %s missing and no default value', repr(_arg_name))
                                l_err.append((_arg_name, 'missing required arg %s' % repr(_arg_name)))
                                l_rslt.append(None)
                                if strict:
                                    l_rslt.extend((None for _ in range(len(args) - len(l_rslt))))  # 用None补齐参数
                                    if hasattr(self, 'writeS'):
                                        self.writeS({}, self.err._ERR_INVALID_ARG, '参数不正确')
                                    raise MyBreak()
                                break
                            #  有默认值
#-#                            info('\trequired arg %s missing and return default %s', repr(_arg_name), repr(_vt['default']))
                            l_rslt.append(_vt['default'])
                            break
                        else:  # 缺可选参数
#-#                            info('\toptional arg %s missing, return %s%s', repr(_arg_name), repr(_vt.get('default')), '(default)' if 'default' in _vt else '')
                            l_rslt.append(_vt.get('default'))
                            break

                    if 'vt' in _vt:
#-#                        info('\tcall %s%s', _vt['vt'].__name__ if hasattr(_vt['vt'], '__name__') else _vt['vt'], (' with %s' % _vt['args']) if 'args' in _vt else '')
                        _passed, _value = _vt['vt'](_arg_value, *_vt['args']) if 'args' in _vt else _vt['vt'](_arg_value)
                        if not _passed:
                            warn('\t[not pass] %s %s', repr(_arg_name), repr(_arg_value))
                            l_err.append((_arg_name, 'arg %s validate failed at %s%s' % (repr(_arg_name), _vt['vt'].__name__ if hasattr(_vt['vt'], '__name__') else _vt['vt'], _vt.get('args', ''))))
                            l_rslt.append(_vt['default'] if 'default' in _vt else None)
                            if strict:  # and 'default' not in _vt:
                                l_rslt.extend((None for _ in range(len(args) - len(l_rslt))))  # 用None补齐参数
                                if hasattr(self, 'writeS'):
                                    self.writeS({}, self.err._ERR_INVALID_ARG, '参数不正确')
                                raise MyBreak()
                            break
                        else:
#-#                            info('\t[passed] %s %s%s', repr(_arg_name), repr(_value), ('(origial %s)' % _arg_value) if _arg_value != _value else '')
                            l_rslt.append(_value)
                        break
                if len(l_rslt) == old_len:
                    l_rslt.append(_arg_value)
        except MyBreak:
            pass
        except:
            error('', exc_info=True)
#-#        info('\nargs %s\nrtn  %s %s', pcformat(args), pcformat(l_rslt), pcformat(l_err))
        return l_rslt, l_err


#  默认的校验器
ArgValidator.ARG_VALIDATOR = {'device_id': [{'vt': ArgValidator.str_vt, 'default': ''}, ],
                              'pnum': [{'vt': ArgValidator.pnum_vt, 'default': ''}, ],
                              'pw': [{'default': ''}, ],
                              'uid': [{'vt': ArgValidator.uid_vt, 'default': 0}],
                              'os_type': [{'vt': partial(ArgValidator.re_vt, p_re=re.compile('^(android)|(ios)$')), 'default': ''}, ],
                              'app_version': [{'vt': ArgValidator.str_vt, 'default': ''}, ],
                              'os_version': [{'vt': ArgValidator.str_vt, 'default': ''}, ],
                              'channel:': [{'vt': ArgValidator.str_vt, 'default': ''}, ],
                              'ic': [{'default': ''}, ],
                              'app_id': [{'vt': ArgValidator.str_vt, 'default': '0'}, ],
                              'token': [{'vt': ArgValidator.str_vt, 'default': ''}, ],
                              'imsi': [{'vt': ArgValidator.str_vt, 'default': ''}, ],
                              'callback': [{'vt': ArgValidator.str_vt, 'default': ''}, ],
                              }

# 可用的基础校验器
ArgValidator.BASE_VALIDATOR = {'int': ArgValidator.int_vt,
                               'bool': ArgValidator.type_vt(bool),
                               '+int': partial(ArgValidator.int_vt, start=1),
                               're': ArgValidator.re_vt,
                               'str': ArgValidator.str_vt,
                               }


if __name__ == '__main__':
#-#    ArgValidator.add_arg_validator('uid', 'int(10000000,99999999)&required&default=None')
#-#    ArgValidator.add_arg_validator('device_id', 'default=None')
#-#    ArgValidator.add_arg_validator('some', 'bool')

    class X(ArgValidator):
        MY_AUTH = 0
        pass

    x = X()
#-#    x.post_data = {'uid': 10}
#-#    x.post_data = {'os_type': 'android'}
#-#    x.post_data = {"token": "246158926f12e26a2430ef4f33db9670", "channel": "", "app_version": "3.0.0", "device_id": "866445025879258", "os_version": "4.4.2", "os_type": "android", "app_package_name": "com.happy.lock", "imsi": ""}
    x.post_data = {"screen_width": "720", "app_version": "3.0.0.0", "login_way": "", "device_id": "866445025879156", "net": "WIFI", "country_code": "CN", "os_version": "4.4.4", "os_type": "android", "appvc": "3000000", "bssid": "70:f9:6d:61:75:70", "device_name": "HM+NOTE+1LTE", "token": "c0596df7e45f73b6441d6e746793c0ee", "pnum": "", "screen_layout_size": "2", "app_package_name": "com.happy.lock", "ssid": "dianjoy", "screen_density": "320", "pw": "", "language": "zh", "imsi": "", "channel": "share", "re_time": "1457325389013", "screen_height": "1280"}
#-#    a, b = ArgValidator.get_my_arg(x, 'device_id', 'uid', 'some default=False')
#-#    a, b = ArgValidator.get_my_arg(x, 'os_type')
#-#    (pnum, password, device_id, device_imsi, os_type, channel, app_version, os_version, app_package_name, invite_code, token, ticket), l_err = \
#-#    l_rslt, l_err = ArgValidator.get_my_arg(x, 'pnum default=0', 'pw', 'device_id required', 'imsi', 'os_type required', 'channel required', 'app_version required', 'os_version required', 'app_package_name required', 'ic', 'token', 'ticket', 'callback')

    x.post_data = {'item_type': 'xx'}
#-#    l_rslt, l_err = x.get_my_arg('uid int&default=0')
    l_rslt, l_err = x.get_my_arg('item_type re(re.compile(r"^(news)|(img)|(ad)$"))&default=""')
    info('rslt: %s  err %s', l_rslt, l_err)
    l_rslt, l_err = x.get_my_arg('duration int&default=0')
    info('rslt: %s  err %s', l_rslt, l_err)
    sys.exit(0)
#-#    print Tools.checkIDCard('440524188001010014')
#-#    print Tools.checkIDCard('11010519491231002X')
#-#    print Tools.checkIDCard('110105194913310021')
#-#    print Tools.checkIDCard('110105184912310020')
    print(Tools.checkDeviceId('860505026891330'))
    print(Tools.checkDeviceId('860505026891331'))
    print(Tools.checkDeviceId('866445025879156'))
    import gzip
    from IPython import embed
    nr_succ, nr_fail = 0, 0
#-#    with gzip.open('/tmp/device_id_exchange_201508.txt.gz') as fi:
    l_fail = []
    with gzip.open('/tmp/device_id_201508.txt.gz') as fi:
        for _l in fi:
            _device_id = _l.strip()
#-#            info('%s', _device_id)
            r = Tools.checkDeviceId(_device_id)
            if r:
                nr_succ += 1
            else:
                nr_fail += 1
                l_fail.append(_device_id)
#-#            if nr_fail > 100:
#-#                info('break')
#-#                break
    total = nr_succ + nr_fail
    info('%d(succ) %.2f%% + %d(fail) %.2f%% = %d', nr_succ, float(nr_succ) / total * 100, nr_fail, float(nr_fail) / total * 100, total)
    embed()
