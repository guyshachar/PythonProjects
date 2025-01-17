import appdaemon.plugins.hass.hassapi as hass
from Shared.logger import Logger

class LogRedirectApp(hass.Hass):
    def initialize(self):
        Logger(self)
        self.listen_log(self.cb)
    
    def cb(self, name, ts, level, message, param1, param2):
        #self.logger.info(f'{name} {ts} {level} {message} {param1} {param2}')
        msg = "{}: {}: {}: {}".format(ts, level, name, message)
        self.call_service("python_script/log",   message = msg)