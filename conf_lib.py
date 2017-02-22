#-#import pathlib
import yaml
import os
#-#from applib.tools_lib import pcformat
from log_lib import app_log
info, debug, error, warn = app_log.info, app_log.debug, app_log.error, app_log.warning

# load config from yaml file in current dir
#-#conf_file_path = str(pathlib.Path('.') / 'server.yaml')
conf_file_path = os.path.join(os.path.abspath('.'), 'pn_conf.yaml')
assert os.path.exists(conf_file_path)
conf = yaml.load(open(conf_file_path))
