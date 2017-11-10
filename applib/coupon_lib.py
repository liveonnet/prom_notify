import sys
import os
from urllib.parse import quote
import asyncio
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from IPython import embed
embed
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.tools_lib import pcformat
from applib.conf_lib import getConf
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


class CouponManager(object):
    """优惠券信息的获取和自动领取 目前只支持京东普通优惠券, 不支持验证码
    """

    def __init__(self, conf_path='config/pn_conf.yaml', event_notify=None):
        self.conf_path = os.path.abspath(conf_path)
        self.conf = getConf(self.conf_path, root_key='coupon')

        self.event_notify = event_notify
        self.jd_user = self.conf['jd_user']
        self.jd_password = self.conf['jd_password']

    async def GetJdCoupon(self, title, item):
        """自动领取京东普通优惠券
        """
        rslt, err = '', ''
        if self.conf['geckodriver'] not in sys.path:
            sys.path.append(self.conf['geckodriver'])
        ff = webdriver.Firefox()
        try:
            # 登录京东
            if 'm.jd.com' in item['receiveUrl']:
                ff.get('https://plogin.m.jd.com/user/login.action?appid=100&kpkey=&returnurl=%s' % quote(item['receiveUrl']))
                ff.find_element_by_id('username').send_keys(self.jd_user)
                ff.find_element_by_id('password').send_keys(self.jd_password)
                ff.find_element_by_id('loginBtn').click()
            else:
                ff.get('https://passport.jd.com/new/login.aspx?ReturnUrl=%s' % quote(item['receiveUrl']))
                ff.find_element_by_link_text('账户登录').click()
                await asyncio.sleep(0.5)
                ff.find_element_by_name('loginname').send_keys(self.jd_user)
                ff.find_element_by_name('nloginpwd').send_keys(self.jd_password)
                ff.find_element_by_id('loginsubmit').click()
            await asyncio.sleep(2)
        except:
            info('登录京东时出错', exc_info=True)
        else:
            try:
                info('尝试自动领取 %s ...\n%s', title, pcformat(item))
                try:
                    element = ff.find_element_by_id('btnSubmit')
                except NoSuchElementException:
                    try:
                        element = ff.find_element_by_link_text('立即领取')
                        element.click()
                    except:
                        pass
                    else:
                        try:
                            rslt = ff.find_element_by_xpath('//p[@class="coupon-txt"]').text
                            info('领取结果 %s', rslt)
                        except:
                            error('获取领取结果时出错', exc_info=True)
                else:
                    element.click()
                    try:
                        rslt = ff.find_element_by_xpath('//p[@class="coupon-txt"]').text
                        info('领取结果 %s', rslt)
                    except:
                        error('获取领取结果时出错', exc_info=True)
            except:
                error('自动领取出错', exc_info=True)
            else:
                info('自动领取完成')
                await asyncio.sleep(2)
        finally:
#-#            embed()
            ff.quit()

        return rslt, err

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    item = {'receiveUrl': 'http://coupon.m.jd.com/coupons/show.action?key=df40fa94be1547858be22ac645173891&roleId=8768370&to=https://pro.m.jd.com/mall/active/4Sab8QiDMWw4danTXM8rMAmjMf3d/index.html', }
    try:
        task = asyncio.ensure_future(CouponManager().GetJdCoupon('测试标题', item))
        x = loop.run_until_complete(task)
        info(pcformat(x))
    except KeyboardInterrupt:
        info('cancel on KeyboardInterrupt..')
        task.cancel()
        loop.run_forever()
        task.exception()
    finally:
        loop.stop()


