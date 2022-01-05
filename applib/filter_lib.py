import os
import sys
import re
from itertools import chain
import jieba
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


class FilterTitle(object):
    def __init__(self, conf_path='config/pn_conf.yaml', event_notify=None):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='filter')

        self.event_notify = event_notify
        self.filter_path = os.path.abspath(self.conf['filter_path'])

        self.l_include_coupon = list()
        self.l_exclude_coupon = list()
        self._loadIncludeExcludeData()

        self.jieba_userdict_path = None
        self.jieba_userdict = None
        self.jieba_strip_word = None
        self._initJieba()

    def _loadIncludeExcludeData(self, force_reload=False):
        """重新从配置文件读取关注/排除词, 作为自定义词组添加到结巴
        """
        conf = getConf(self.filter_path, force_reload=force_reload)
        self.l_concern = conf['l_concern']
        # 将enable=False的关注项去掉
        self.l_concern = [x for x in self.l_concern if x.get('enable', True) is True]
        debug(f'concern item(s) loaded {len(self.l_concern)}')
        self.l_include_coupon = conf['l_include_coupon'] or []
        self.l_exclude_coupon = conf['l_exclude_coupon'] or []
        debug('include/exclude coupon item(s) loaded. %s/%s ', len(self.l_include_coupon), len(self.l_exclude_coupon))

        self.l_include_jr_coupon = conf['l_include_jr_coupon'] or []
        self.l_exclude_jr_coupon = conf['l_exclude_jr_coupon'] or []
        debug('include/exclude jr coupon item(s) loaded. %s/%s ', len(self.l_include_jr_coupon), len(self.l_exclude_jr_coupon))
        if force_reload:
            self._addUserWord()

    def _addUserWord(self):
        """添加自定义词组
        """
# #        l_dynamic_word = sorted(chain((x.get('inc', []) for x in self.l_concern), (x.get('exc', []) for x in self.l_concern)), key=lambda x: len(x) if x else 0, reverse=True)
# #        l_dynamic_word = [m for m in chain(*(x.get('inc', []) for x in self.l_concern), *(x.get('exc', []) for x in self.l_concern)) if len(m) > 0]
        l_dynamic_word = [m for m in chain(*(x.get('inc', []) for x in self.l_concern)) if len(m) > 0]  # 只把inc中的词做自定义分词，exc中的不做
        l_dynamic_word = sorted(set(l_dynamic_word), key=lambda x: len(x) if x else 0, reverse=True)
        debug(pcformat(l_dynamic_word))
        list(map(lambda w: jieba.add_word(w, freq=1500, tag=None) if w else 0, l_dynamic_word))
        debug('added %s include/exclude word(s) to jieba', len(l_dynamic_word))

    def _initJieba(self):
        """初始化结巴分词
        """
        jieba.dt.tmp_dir = self.conf.get('jieba_tmp_dir', '')
        self.jieba_userdict_path = os.path.abspath(self.conf['jieba_userdict_path'])
        if self.jieba_userdict_path and os.path.exists(self.jieba_userdict_path):
            self.jieba_userdict = jieba.load_userdict(self.jieba_userdict_path)
        else:
            self.jieba_userdict = None
        self._addUserWord()
        self.jieba_strip_word = self.conf['jieba_strip_word']

    def cutWordJieba(self, s):
        """分词
        """
        l_word = list(filter(None, map(lambda x: x.strip(self.jieba_strip_word), jieba.cut(s, cut_all=False))))
#-#        warn('%s <= %s', '/'.join(l_word), s)
        return l_word

    def matchConcern(self, **kwargs):
        """根据分词结果给出不同的动作建议(附带关注/排除词匹配结果和额外的分词细节)

        关注优先, 除了关注的外都跳过

        每个关注项包含两个列表：一个是关注关键词列表，一个是排除关键词列表。 另外包含一个inc_all字段，表示是否需要同时匹配上所有的关注关键词(无此字段表示不需要同时匹配所有关注关键词)。一个title中如果包含关注关键词中的任意一个（inc_all=False）或所有的(inc_all=True)并且不包含排除关键词的任何一个，那么这个title就是符合条件的。

        之前的matchFilter是排除优先，需要将要排除的都放到单独的配置文件里面，随着排除项越来越多，这种方式
        变得臃肿低效。其实抓了半天网页就是想得到自己近期有计划要买的商品的优惠信息，所以改成从配置文件里
        读入关心的商品关键字，辅以在匹配了关心的关键字后要排除的关键字，这样就不必维护越来越多的排除项了，
        整个流程变得目的性更强更高效。本函数将代替matchFilter，后者将废止，相关的配置项也将弃用。

        'SKIP', '<SKIP_WORD>', extra_data
        'NOTIFY', '<NOTIFY_WORD>', extra_data
        'NORMAL', '', extra_data
        """
        action, word, extra_data = '', '', {}
        title = kwargs.get('title', '')
        # reload modified filter data
        if self.event_notify is not None and self.event_notify.is_set():
            self._loadIncludeExcludeData(force_reload=True)
            self.event_notify.clear()

        l_word = self.cutWordJieba(title)
        extra_data['cut_word'] = l_word

        action = 'NORMAL'
        # 考虑到同时关注的条目和title都不会太多太长，使用循环查找的笨办法，未使用原matchFilter中的集合方式，因为不确定添加的自定义分词是否都有效，也考虑到添加的关键词可能有重叠部分，优化方向：使用ahocorasick模块
# #        debug(f'=============== 检查目标 {title}')
        for _item in self.l_concern:  # 每个关注排除项依次检查
            _inc_all = _item.get('inc_all', False)
            _inc, _exc = set(_item.get('inc', [])), set(_item.get('exc', []))
# #            debug(f'------------- 检查项 关注{"所有" if _inc_all else "任意"} 关注 {_inc} 排除 {_exc}')
            if _inc:
                if _inc_all:  # 需要匹配上单个关注项中的所有关键词
                    for _inc_one in _inc:
                        if not re.search(_inc_one, title, re.IGNORECASE):
# #                            debug(f'未匹配到所有关键词中的 {_inc_one}')
                            break
                    else:
                        for _exc_one in _exc:
                            if re.search(_exc_one, title, re.IGNORECASE):  # 有匹配
# #                                debug(f'关注 {"&".join(_inc)} 被 {_exc_one} 排除')
                                action, word = 'SKIP', f'{"&".join(_inc)}/{_exc_one}'  # 保留最近一次被排除的信息
                                break
                        else:
# #                            debug(f'关注无排除')
                            action, word = 'NOTIFY', "&".join(_inc)
                            break
                else:  # 只需要匹配单个关注项中的单个关键词
                    for _inc_one in _inc:  # 关注项中的词依次测试是否有匹配
                        if re.search(_inc_one, title, re.IGNORECASE):  # 有匹配
# #                            debug(f'关注匹配到 {_inc_one}')
                            for _exc_one in _exc:  # 排除项中的词依次测试是否有匹配
                                if re.search(_exc_one, title, re.IGNORECASE):  # 有匹配
# #                                    debug(f'关注 {_inc_one} 被 {_exc_one} 排除')
                                    action, word = 'SKIP', f'{_inc_one}/{_exc_one}'
                                    break
                            else:
# #                                debug(f'关注无排除')
                                action, word = 'NOTIFY', _inc_one
                                break
                        if action == 'SKIP':
# #                            debug('提前到下一检查项')
                            break
            else:
                warn(f'关注项为空！ {pcformat(_item)}')

            if action == 'NOTIFY':  # 提前退出
# #                debug(f'提前退出')
                break
# #        else:
# #            pass
# #            debug('不在关注中')

# #        debug(f'check title {title} result: {action} {word}')

        return action, word, extra_data

    def matchFilterCoupon(self, **kwargs):
        """过滤京东优惠券
        根据匹配结果给出不同的动作建议(附带关注/排除词匹配结果和额外的分词细节)

        排除优先

        'SKIP', '<SKIP_WORD>', extra_data
        'NOTIFY', '<NOTIFY_WORD>', extra_data
        'NORMAL', '', extra_data
        """
        action, word, extra_data = '', '', {}
        title = kwargs.get('title', '')
        # reload modified filter data
        if self.event_notify is not None and self.event_notify.is_set():
            self._loadIncludeExcludeData(force_reload=True)
            self.event_notify.clear()

        for _include_word in self.l_include_coupon:
            if _include_word in title:
                action, word = 'NOTIFY', _include_word
                break
        if not action:
            for _ignore_word in self.l_exclude_coupon:
                if _ignore_word in title:
                    action, word = 'SKIP', _ignore_word
                    break
            else:
                action = 'NORMAL'
        if not action:
            action = 'SKIP'

        return action, word, extra_data

    def matchFilterJrCoupon(self, **kwargs):
        """过滤京东金融的优惠券
        根据匹配结果给出不同的动作建议(附带关注/排除词匹配结果和额外的分词细节)

        排除优先

        'SKIP', '<SKIP_WORD>', extra_data
        'NOTIFY', '<NOTIFY_WORD>', extra_data
        'NORMAL', '', extra_data
        """
        action, word, extra_data = '', '', {}
        title = kwargs.get('title', '')
        # reload modified filter data
        if self.event_notify is not None and self.event_notify.is_set():
            self._loadIncludeExcludeData(force_reload=True)
            self.event_notify.clear()

        for _include_word in self.l_include_jr_coupon:
            if _include_word in title:
                action, word = 'NOTIFY', _include_word
                break
        if not action:
            for _ignore_word in self.l_exclude_jr_coupon:
                if _ignore_word in title:
                    action, word = 'SKIP', _ignore_word
                    break
            else:
                action = 'NORMAL'
        if not action:
            action = 'SKIP'

        return action, word, extra_data

    def clean(self):
        info('filter closed.')


if __name__ == '__main__':
#-#    from applib.tools_lib import pcformat
    t = FilterTitle()
#-#    x = t.cutWordJieba('傅雷译·约翰·克利斯朵夫')
#-#    x = t.cutWordJieba('连脚裤袜')
#-#    x = t.cutWordJieba('短毛绒汽车坐垫全包')
# #    x = t.cutWordJieba('世界经典文学名著 全译本')
    x = t.matchConcern(title='闪迪固态硬盘 SATA 500GB')
    info(pcformat(x))
# #    x = t.matchConcern(title='闪迪固态硬盘 SATA 1TB')
# #    info(pcformat(x))
# #    x = t.matchConcern(title='闪迪固态硬盘 SATA 2TB')
# #    info(pcformat(x))

# #    x = t.matchConcern(title='酒精湿巾')
# #    info(pcformat(x))
# #    x = t.matchConcern(title='宠物湿巾')
# #    info(pcformat(x))

    x = t.matchConcern(title='小米 note11')
    info(pcformat(x))
    x = t.matchConcern(title='黄小米500g')
    info(pcformat(x))

    x = t.matchConcern(title='红米 note9')
    info(pcformat(x))
    x = t.matchConcern(title='红米 note9 pro')
    info(pcformat(x))
    x = t.matchConcern(title='红米 note9 pro 6GB')
    info(pcformat(x))
# #    x = t.matchConcern(title='HONOD BEEF 恒都牛肉原切牛腱子肉 2.5kg')
# #    info(pcformat(x))
