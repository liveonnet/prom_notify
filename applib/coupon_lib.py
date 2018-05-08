import sys
import os
import pickle
from urllib.parse import quote
import asyncio
from getpass import getuser
from logging import WARNING
from selenium.webdriver.remote.remote_connection import LOGGER
LOGGER.setLevel(WARNING)
if getuser() != 'pi':  # orangepi 上不检查优惠券信息
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
else:
    webdriver = None
    NoSuchElementException = None
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

    async def GetJdCouponWithCookie(self, title, item):
        """自动领取京东普通优惠券

        参考 http://selenium-python.readthedocs.io/index.html
        """
        rslt, err = '', ''
        if self.conf['geckodriver'] not in sys.path:
            sys.path.append(self.conf['geckodriver'])
        ff = webdriver.Firefox()
        if 'm.jd.com' in item['receiveUrl']:
            cookie_file = '/tmp/plogin.m.jd.com.cookie.pkl'
        else:
            cookie_file = '/tmp/passport.jd.com.cookie.pkl'
        try:
            if os.path.exists(cookie_file):
                info('读取已有cookie %s', cookie_file)
#-#                ff.get('https://home.m.jd.com' if 'm.jd.com' in item['receiveUrl'] else 'http://help.jd.com/index.html')
#-#                ff.get('https://so.m.jd.com/category/all.html?searchFrom=bysearchbox' if 'm.jd.com' in item['receiveUrl'] else 'http://help.jd.com/index.html')
                url = 'https://p.m.jd.com/cart/cart.action' if 'm.jd.com' in item['receiveUrl'] else 'http://help.jd.com/index.html'
                info('fetching %s', url)
                ff.get(url)

                for _c in pickle.load(open(cookie_file, 'rb')):
#-#                    info('cookie data %s', pcformat(_c))
                    try:
                        ff.add_cookie(_c)
                    except:
                        pass
#-#                        error('ignore except', exc_info=True)
                info('读取完毕cookie %s', cookie_file)
            for _ in range(2):
                try:
                    info('尝试自动领取 %s ...\n%s', title, pcformat(item))
                    info('fetching %s', item['receiveUrl'])
                    ff.get(item['receiveUrl'])
                    no_btn = False
                    try:
                        element = ff.find_element_by_id('btnSubmit')
                    except NoSuchElementException:
                        try:
                            element = ff.find_element_by_link_text('立即领取')
                        except NoSuchElementException:
                            try:
                                element = ff.find_element_by_class_name('btn')
                            except NoSuchElementException:
                                no_btn = True
#-#                    embed()
                    if no_btn:
                        # 没登录？
                        info('没登录? 尝试登录')
                        # 登录京东
                        try:
                            if 'm.jd.com' in item['receiveUrl']:
                                url = 'https://plogin.m.jd.com/user/login.action?appid=100&kpkey=&returnurl=%s' % quote(item['receiveUrl'])
                                info('open login page %s', url)
                                ff.get(url)
                                ff.find_element_by_id('username').send_keys(self.jd_user)
                                ff.find_element_by_id('password').send_keys(self.jd_password)
                                ff.find_element_by_id('loginBtn').click()
                            else:
                                url = 'https://passport.jd.com/new/login.aspx?ReturnUrl=%s' % quote(item['receiveUrl'])
                                info('open login page %s', url)
                                ff.get(url)
                                ff.find_element_by_link_text('账户登录').click()
                                await asyncio.sleep(0.5)
                                ff.find_element_by_name('loginname').send_keys(self.jd_user)
                                await asyncio.sleep(0.5)
                                ff.find_element_by_name('nloginpwd').send_keys(self.jd_password)
                                await asyncio.sleep(0.5)
                                ff.find_element_by_id('loginsubmit').click()
                            await asyncio.sleep(2)
                        except:
                            info('登录京东时出错', exc_info=True)
                            break
                        else:
                            info('登录貌似成功了，保存cookie %s', cookie_file)
                            pickle.dump(ff.get_cookies(), open(cookie_file, 'wb'))
                            continue
                    else:
#-#                        info('element %s', element)
#-#                        embed()
                        if 'btn-unable' in element.get_attribute('class'):
                            info('不能领取：%s', element.text)
                        elif element.text.find('查看') != -1:
                            info('不能领取(已领取过?)：%s', element.text)
                        else:
                            try:
                                element.click()
                                element = WebDriverWait(ff, 3).until(EC.presence_of_element_located((By.XPATH, '//p[@class="coupon-txt"]')))
                                info('领取结果 %s', element.text)
                            except:
                                try:
                                    element = WebDriverWait(ff, 1).until(EC.presence_of_element_located((By.CLASS_NAME, 'btn')))
                                    info('领取结果 %s', element.text)
                                except:
                                    error('获取领取结果时出错', exc_info=True)
#-#                                    embed()
                            finally:
                                info('自动领取完成')
                                await asyncio.sleep(1)
                        break
                except:
                    error('自动领取出错', exc_info=True)
        except:
            error('自动领取出错', exc_info=True)
        finally:
            pass
#-#            embed()
            ff.quit()

        return rslt, err

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    item = {'receiveUrl': 'http://coupon.m.jd.com/coupons/show.action?key=45d6a751fce54aa5be8dd8d40fb2912d&roleId=11653592&to=https://mall.jd.com/index-1000003005.html', }
    try:
        task = asyncio.ensure_future(CouponManager().GetJdCouponWithCookie('测试标题', item))
        x = loop.run_until_complete(task)
        info(pcformat(x))
    except KeyboardInterrupt:
        info('cancel on KeyboardInterrupt..')
        task.cancel()
        loop.run_forever()
        task.exception()
    finally:
        loop.stop()


