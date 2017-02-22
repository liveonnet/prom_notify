#-#import pathlib
import yaml
import os
#-#from applib.tools_lib import pcformat
from log_lib import app_log
info, debug, error, warn = app_log.info, app_log.debug, app_log.error, app_log.warning

_cache_conf = {}


def getConf(conf_path='./pn_conf.yaml', root_key=None, force_reload=False):
    global _cache_conf
    conf_file_path = os.path.abspath(conf_path)
    conf = _cache_conf.get(conf_file_path, None)

    if conf is None or force_reload:
        if force_reload:
            info('force load conf from file %s', conf_file_path)
        assert os.path.exists(conf_file_path)
        conf = yaml.load(open(conf_file_path))
        _cache_conf[conf_file_path] = conf
        info('load %s done. %s key(s)', conf_file_path, len(conf))
    else:
        info('get conf from cache %s', conf_file_path)

    if root_key:
        info('conf has %s %s', root_key, root_key in conf)
        conf = conf.get(root_key)

    return conf
