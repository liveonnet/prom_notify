import sys
import yaml
import os
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
#-#from applib.tools_lib import pcformat
from applib.log_lib import app_log
info, debug, error, warn = app_log.info, app_log.debug, app_log.error, app_log.warning

_cache_conf = {}


def getConf(conf_path='./pn_conf.yaml', root_key=None, force_reload=False):
    global _cache_conf
    conf_file_path = os.path.abspath(conf_path)
    conf = _cache_conf.get(conf_file_path, None)

    if conf is None or force_reload:
        if force_reload:
            debug('force load conf from file %s', conf_file_path)
        assert os.path.exists(conf_file_path)
        conf = yaml.load(open(conf_file_path))
        _cache_conf[conf_file_path] = conf
#-#        debug('load done %s. %s key(s)', conf_file_path, len(conf))
#-#    else:
#-#        debug('get conf from cache %s', conf_file_path)

    if root_key:
        if root_key not in conf:
            error('conf no root_key %s in %s !!!', root_key, conf_file_path)
        conf = conf.get(root_key)

    return conf
