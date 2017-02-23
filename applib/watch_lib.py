import os
import sys
import pyinotify
if __name__ == '__main__':
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
from applib.log_lib import app_log
info, debug, warn, error = app_log.info, app_log.debug, app_log.warning, app_log.error


class EventHandler(pyinotify.ProcessEvent):
    def my_init(self, **kwargs):
        self.file2watch = kwargs.get('file2watch')
        self.event_notify = kwargs.get('event_notify')
        info('handler modify for %s', self.file2watch)

    def process_default(self, event):
        if event.pathname not in self.file2watch:
#-#            info("SKIP_FILE %s %s", event.maskname, event.pathname)
            return
        if event.maskname == 'IN_MODIFY':
            if self.event_notify.is_set():
                info('already set changed flag for %s', event.pathname)
            else:
                debug('%s %s%s', event.maskname, event.pathname, '(DIR)' if event.dir else '')
                info('set changed flag for %s', event.pathname)
                self.event_notify.set()


def startWatchConf(path_name, event_notify):
    '''https://github.com/seb-m/pyinotify/wiki/Tutorial
    http://seb.dbzteam.org/pyinotify/
    '''
    wm, wdd = None, None
    path_name = os.path.abspath(path_name)
    assert os.path.isfile(path_name)
    wm = pyinotify.WatchManager()
#-#    mask = pyinotify.IN_CLOSE_WRITE | pyinotify.IN_MODIFY | pyinotify.IN_MOVE_SELF | pyinotify.IN_DELETE_SELF | pyinotify.IN_CREATE
    mask = pyinotify.IN_MODIFY
    info('inotify check start for %s', path_name)
    eh = EventHandler(file2watch=[path_name, ], event_notify=event_notify)
    try:
        notifier = pyinotify.ThreadedNotifier(wm, eh)
        notifier.start()
        wdd = wm.add_watch(os.path.dirname(path_name), mask)
    except:
        error('got except, break ~', exc_info=True)
        pass

    return wm, notifier, wdd


def stopWatchConf(wm, notifier, wdd):
    wm.rm_watch(list(wdd.values()))
    notifier.stop()
#-#    wm.close()
    info('inotify check done for %s', wdd)
