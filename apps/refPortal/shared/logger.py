import os
import logging
import inspect
import tempfile
from pathlib import Path
import watchtower
import traceback
import time
import asyncio
import boto3
import socket
from colorama import Fore, Style
from logging.handlers import TimedRotatingFileHandler
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.helpers import validatePath
from shared.helpers import isRunningInLambda
from shared.configManager import ConfigManager
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper

STACK_TRACE_LIMIT = int(os.getenv('stackTraceLimit') or '1')

class Logger():
    def __init__(self, loggerName=None, log2Console=True, log2File=False, log2CW=False, sendMessage=None, config=None):
        self.config = config or {}
        app = ConfigManager.get_config_value(self.config, 'app', os.getenv('app'))
        env = ConfigManager.get_config_value(
            self.config,
            'app_env',
            ConfigManager.get_config_value(self.config, 'env', os.getenv('app_env'))
        )
        self.isRunningInLambda = isRunningInLambda()
        logLevel = eval(
            f"logging.{ConfigManager.get_config_value(self.config, 'logLevel', os.getenv('logLevel') or 'DEBUG')}"
        )
        _loggerName = loggerName or self.findLoggerName()

        logFormat = f'%(asctime)s - {app} - {_loggerName} - %(levelname)s - %(message)s'
        logFormatter = logging.Formatter(logFormat)
        logFormatterJson = LogJsonFormatter(fmt=logFormat, datefmt='%Y-%m-%d %H:%M:%S')
        logging.basicConfig(level=logLevel, format=logFormat, force=True)
        logger = logging.getLogger(_loggerName)
        #logger.setLevel(logging.DEBUG)  # Capture all levels

        logger.handlers.clear()

        if ConfigManager.get_config_bool(self.config, 'log2File', eval(os.getenv('log2File', 'False'))) or log2File:
            log_base = ConfigManager.get_config_value(
                self.config, 'MY_LOG_FOLDER', os.getenv('MY_LOG_FOLDER', '/run/logs/')
            )
            if log_base and not log_base.endswith(('/', os.sep)):
                log_base = log_base + os.sep
            logFile = f'{log_base}logService-{app}-{_loggerName}.log'
            try:
                validatePath(logFile)
            except OSError:
                # Docker/VM use /run/logs; on macOS (and some hosts) /run is not writable — use a temp dir.
                fallback = os.path.join(tempfile.gettempdir(), 'refportal_logs')
                logFile = os.path.join(fallback, f'logService-{app}-{_loggerName}.log')
                validatePath(logFile)
            logHistoryRetention = ConfigManager.get_config_int(self.config, 'logHistoryRetention', os.getenv('logHistoryRetention') or '6')
            file_handler = TimedRotatingFileHandler(
                logFile, when="H", interval=1, backupCount=logHistoryRetention, encoding="utf-8"
            )        
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logFormatter)
            logger.addHandler(file_handler)

        if ConfigManager.get_config_bool(self.config, 'log2Console', eval(os.getenv('log2Console', 'False'))) and log2Console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logLevel)
            if self.isRunningInLambda:
                console_handler.setFormatter(logFormatterJson)
            else:
                console_handler.setFormatter(logFormatter)
            logger.addHandler(console_handler)

        if ConfigManager.get_config_bool(self.config, 'log2CW', eval(os.getenv('log2CW', 'False'))) or log2CW:# and not self.isRunningInLambda:
            cw_logFormat = f'%(asctime)s - {app} - {_loggerName} - %(levelname)s - %(message)s'
            cw_logFormatterJson = LogJsonFormatter(fmt=cw_logFormat, datefmt='%Y-%m-%d %H:%M:%S')
            boto3Client = boto3.client("logs", region_name=ConfigManager.get_config_value(self.config, "awsRegion", os.getenv("awsRegion")))
            cw_handler = watchtower.CloudWatchLogHandler(log_group=f'{_loggerName}-{env}', boto3_client=boto3Client)
            cw_handler.setFormatter(cw_logFormatterJson)
            cw_handler.setLevel(logLevel) 
            logger.addHandler(cw_handler)

        logger.propagate = False

        self.logger = logger
        
        self.sendMessage = sendMessage
        self.errorLogTraces = []

    def findLoggerName(self):
        for step in inspect.stack():
            if step.filename != __file__:
                return os.path.splitext(os.path.basename(step.filename))[0]
        return None
    
    def log(self, level, message, **kwargs):
        extra = kwargs.get('extra') or {}
        refereeDetail = kwargs.get('refereeDetail') or kwargs.get('refereeData')
        if not refereeDetail:
            mobileNo = kwargs.get('mobileNo')
            name = kwargs.get('name')
            refereeDetail = {}
            if mobileNo:
                refereeDetail['mobileNo'] = mobileNo
            if name:
                refereeDetail['name'] = name
            
        if refereeDetail:
            color = Fore.WHITE
            try:
                if refereeDetail:
                    extra['refereeDetail'] = refereeDetail
                    if refereeDetail.get('color'):
                        try:
                            color = eval(f"Fore.{refereeDetail['color']}")
                        except Exception as ex:
                            pass
                if self.isRunningInLambda:
                    message = f'{refereeDetail.get("name")}#{refereeDetail["mobileNo"]}#{message}'
                else:
                    message = f'{color}{refereeDetail.get("name")}#{refereeDetail["mobileNo"]}#{message}{Style.RESET_ALL}'
            except Exception as ex:
                pass
        elif isinstance(message, dict):
            if message.get('value') and isinstance(message['value'], dict) and message['value'].get('mobileNo'):
                extra['mobileNo'] = message['value']['mobileNo']
            #message = json.dumps(message, ensure_ascii=False, default=str)

        else:
            pass

        if isinstance(message, str):
            message = message.rstrip()

        if level == 'debug':
            self.logger.debug(msg=message, extra=extra)
        elif level == 'info':
            self.logger.info(msg=message, extra=extra)
        elif level == 'warning':
            self.logger.warning(msg=message, extra=extra)
        elif level == 'error':
            # Passed from Logger.error(); do not use bare `ex` here — inner `except ... as ex` would make `ex` local and break the try body (UnboundLocalError).
            log_ex = kwargs.get('log_exception')
            log_tb = kwargs.get('log_traceback_str')
            try:
                takeScreenshot = kwargs.get('takeScreenshot') or False
                if self.sendMessage and log_ex is not None and log_tb is not None:
                    msg = (
                        f'MobileNo: {refereeDetail.get("mobileNo")}, Name: {refereeDetail.get("name")}, {message}: '
                        f'Exception Type: {type(log_ex).__name__}, Ex: {log_ex} | Trace: {log_tb}'
                    )
                    if log_tb not in self.errorLogTraces:
                        self.errorLogTraces.append(log_tb)
                        asyncio.create_task(self.sendMessage(to=os.getenv('adminMobile'), message=msg))
                if takeScreenshot:
                    helpers.takeScreenshot(tag='logError')
                #how to get the page variable from the caller function outside Logger class?
                #maybe pass the page object to the logger class?
                #or maybe use the page object from the caller function?

            except Exception as send_err:
                print(f'Error sending message: {send_err} trace: {traceback.format_exc()}')

            self.logger.error(msg=message, extra=extra)

    def debug(self, message, ex=None, **kwargs):
        if ex:
            message += f': {ex}'
        self.log('debug', message, **kwargs)

    def info(self, message, ex=None, **kwargs):
        if ex:
            message += f': {ex}'
        self.log('info', message, **kwargs)

    def warning(self, message, ex=None, **kwargs):
        if ex:
            message += f': {ex}'
        self.log('warning', message, **kwargs)

    def error(self, message, ex=None, **kwargs):
        if not ex:
            self.log('error', message, **kwargs)
            return

        traceback_str = format_exception_full(ex)
        timeoutError = type(ex).__name__ == 'TimeoutError'
        extra_log_kwargs = {**kwargs, 'log_exception': ex, 'log_traceback_str': traceback_str}
        if timeoutError:            
            self.log('error', f'{message}: Exception Type: {type(ex).__name__} | Trace: {traceback_str}', **extra_log_kwargs)
        else:
            self.log('error', f'{message}: Exception Type: {type(ex).__name__}, Message: {ex} | Trace: {traceback_str}', **extra_log_kwargs)
        
        if not timeoutError:
            #logging.exception("An error occurred")
            pass
        if not timeoutError:            
            pass
        if ex:
            #logging.exception(message)
            pass

    async def takeScreenshot(self, page=None, refereeDetail=None, tag=None):
        # Take screenshot before returning False
        try:
            _page = page or self.getObjectFromCaller(objectType='page')
            if not _page:
                self.logger.warning(f'takeScreenshot: No page object found', **(refereeDetail or {}))
                return
            if hasattr(_page, 'is_closed') and _page.is_closed():
                self.logger.debug('takeScreenshot: page is closed, skipping', **(refereeDetail or {}))
                return
            _refereeDetail = refereeDetail or self.getObjectFromCaller(objectType='refereeDetail')

            timestamp = int(time.time())
            refId = (_refereeDetail or {}).get('refId', 'unknown')
            base_storage_path = os.getenv("MEDIA_STORAGE_PATH", "/run/data/media_files")
            screenshot_path = os.path.join(base_storage_path, 'screenshots', refId, tag, f'{timestamp}.png')
            helpers.validatePath(screenshot_path)
            await _page.screenshot(path=str(screenshot_path), full_page=True)
            print(f'WARNING:Screenshot saved: {screenshot_path}')
        except Exception as screenshot_ex:
            print(f'ERROR:Failed to take screenshot {screenshot_ex}')

class LogJsonFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hostname = socket.gethostname() or "unknown"

    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "thread": f'{record.thread}#{record.threadName}',
            "hostname": self.hostname,
        }

        # Add any extra attributes if passed
        if hasattr(record, 'refereeDetail') and isinstance(getattr(record, 'refereeDetail', None), dict):
            rd = record.refereeDetail
            if 'mobileNo' not in rd:
                rd['mobileNo'] = rd.get('mobile', rd.get('mobileNo'))
            log_entry['mobileNo'] = rd['mobileNo']
            log_entry['refName'] = rd.get('name', 'n/a')
        elif hasattr(record, 'mobileNo'):
            log_entry['mobileNo'] = record.mobileNo

        if isinstance(record.msg, dict):
            log_entry = log_entry | record.msg
        else:
            log_entry["message"] = record.getMessage()

        if record.levelname == 'ERROR':
            #log_entry['traceback'] = getMinimalTraceback(ex=record.exc_info[1])
            #log_entry['traceback'] = traceback.format_exc(limit=STACK_TRACE_LIMIT, chain=True)
            #log_entry['stackTrace'] = self.stackTrace()
            pass

        return jsonHelper.safe_json_dumps(data=log_entry)
    
    def stackTrace(self):
        stack = ''
        for frame in traceback.extract_stack():
            if stack:
                stack += '\n'
            stack += f"{frame.filename}:{frame.lineno} in {frame.name}"

class ContextualLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        kwargs['extra'].update(self.extra)
        return msg, kwargs

def format_exception_full(ex: BaseException) -> str:
    """Full traceback text (including chained exceptions when supported)."""
    try:
        return "".join(traceback.format_exception(type(ex), ex, ex.__traceback__, chain=True))
    except TypeError:
        return "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))


def getMinimalTraceback(ex):
    # Get last 2 stack frames (file and line only)
    isDynamo = ex.message.lower().find('dynamodb') != -1 if hasattr(ex, 'message') else False
    isMiddleware = ex.message.lower().find('middleware') != -1 if hasattr(ex, 'message') else False
    callstackLength = 7
    if isDynamo:
        callstackLength = 7
    tb = traceback.extract_tb(ex.__traceback__)
    last_frames = tb
    trace_info = ''
    idx = 0
    for frame in last_frames:
        filename = Path(frame.filename).name
        if filename.startswith('_') or idx >= callstackLength:
            break
        idx += 1
        trace_info += f",{filename}:{frame.lineno}"
    #last_frames = tb[-callstackLength:] if len(tb) >= callstackLength else tb
    #trace_info = ", ".join([f"{Path(frame.filename).name}:{frame.lineno}" for frame in last_frames])
    #self.logger.error(f"Error processing complex query: {ex} | Trace: {trace_info}")
    return trace_info

#logger = logging.getLogger("myapp")
#adapter = ContextualLoggerAdapter(logger, {"refId": 42})
#adapter.info("User logged in")
