import os
import json
from datetime import date,datetime
import threading
from decimal import Decimal

def _resolve_db_type() -> str:
    """Mirrors configurationDI's db.type resolution (env var 'db' > config file's env.db >
    default 'redis') without pulling in the full DI container. Checking only the OS env var and
    skipping the config-file fallback (as this used to) silently disagreed with the DI container's
    own resolution whenever an environment set db via config.<env>.json's "env":{"db": ...} and
    never exported it as an actual process env var too (e.g. config.test.json declares
    "db": "postgres" but the test container has no matching env var) - every call site that relies
    on this to skip DynamoDB-string-coercion of bools/numbers (preJsonSetToDynamoDb) then silently
    stringified real Postgres-backed booleans, which strict-typed clients (the iOS app) reject."""
    envVar = os.getenv('db')
    if envVar is not None:
        return envVar
    try:
        from shared.configManager import ConfigManager
        merged = ConfigManager.get_merged_file_config()
        return (merged.get('env') or {}).get('db', 'redis')
    except Exception:
        return 'redis'

# See _resolve_db_type - lets standalone helpers like this one know whether the active backend is
# 'dynamodb' or 'postgres'.
DB_TYPE = _resolve_db_type()

class DbChangeEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, dict) and 'content_hash' in obj:
                return {k: v for k, v in obj.items() if k != "content_hash"}
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)
        except Exception as e:
            pass

class DateTimeDecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            # Handle Locator objects (Playwright/Selenium)
            if hasattr(obj, '__class__') and 'Locator' in str(type(obj)):
                return f"<Locator: {str(obj)}>"
            # Handle other non-serializable objects
            if hasattr(obj, '__dict__'):
                return str(obj)
            return super().default(obj)
        except Exception as e:
            return str(obj)

class DateDecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, date):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)
        except Exception as e:
            pass

class UniversalJSONEncoder(json.JSONEncoder):
    """
    A comprehensive JSON encoder that handles various non-serializable objects
    including Locator objects, datetime, Decimal, and other complex types.
    """
    def default(self, obj):
        try:
            # Handle datetime objects
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, date):
                return obj.isoformat()
            
            # Handle Decimal objects
            if isinstance(obj, Decimal):
                return float(obj)
            
            # Handle Locator objects (Playwright/Selenium)
            if hasattr(obj, '__class__') and 'Locator' in str(type(obj)):
                return f"<Locator: {str(obj)}>"
            
            # Handle WebElement objects (Selenium)
            if hasattr(obj, '__class__') and 'WebElement' in str(type(obj)):
                return f"<WebElement: {str(obj)}>"
            
            # Handle other objects with __dict__ attribute
            if hasattr(obj, '__dict__'):
                return str(obj)
            
            # Handle objects with __str__ method
            if hasattr(obj, '__str__'):
                return str(obj)
            
            # Handle objects with __repr__ method
            if hasattr(obj, '__repr__'):
                return repr(obj)
            
            return super().default(obj)
        except Exception as e:
            return f"<Non-serializable object: {type(obj).__name__}>"

def datetime_decoder(obj):
    for key, value in obj.items():
        try:
            if isinstance(value, str):
                try:
                    # Attempt to parse the string as an ISO 8601 datetime
                    obj[key] = str_to_datetime(value)
                except ValueError:
                    obj[key] = datetime.fromisoformat(value)
        except Exception as e:
            pass
    return obj

def date_decoder(obj):
    for key, value in obj.items():
        try:
            if isinstance(value, str):
                    obj[key] = str_to_date(value)
        except ValueError:
            obj[key] = date.fromisoformat(value)
    return obj

def datetime_to_strfull(dt):
    datetime_str = f'{dt.strftime("%Y%m%d%H%M%S")}{dt.microsecond // 1000:03d}'
    return datetime_str

datetime_format = '%Y-%m-%d%H:%M:%S'
def datetime_to_str(dt):
    return dt.strftime(datetime_format)
def str_to_datetime(dt_str):
    return datetime.strptime(dt_str, datetime_format)

date_format = '%Y-%m-%d'
def date_to_str(dt):
    return dt.strftime(date_format)
def str_to_date(dt_str):
    return datetime.strptime(dt_str, date_format)

def save_to_json(data, ensure_ascii=False, indent=4):
    data = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent, sort_keys=True, cls=DateTimeDecimalEncoder)
    return data

def safe_json_dumps(data, ensure_ascii=False, indent=4, sort_keys=True, cls=None):
    """
    Safely serialize data to JSON, handling non-serializable objects.
    Uses UniversalJSONEncoder by default to handle Locator objects and other complex types.
    """
    if cls is None:
        cls = UniversalJSONEncoder
    return json.dumps(data, ensure_ascii=ensure_ascii, indent=indent, sort_keys=sort_keys, cls=cls)

def load_from_json(data, asIs=False):
    if data:
        if asIs:
            objectHook=None
        else:
            objectHook=datetime_decoder
        if isinstance(data, dict):
            return data
        elif isinstance(data, list):
            return data
        obj = json.loads(data, object_hook=objectHook)
        return obj
    else:
        return {}

mainFileLock = threading.Lock()
fileLocks = {}

def save_to_file(obj, filename, ensure_ascii=False):
    data = save_to_json(data=obj, ensure_ascii=ensure_ascii)
    with mainFileLock:
        if not fileLocks.get(filename):
            fileLocks[filename] = threading.Lock()
    with fileLocks[filename]:
        with open(filename, 'w', encoding='utf-8') as file:
            file.write(data.strip())

def append_to_file(obj, filename):
    data = load_from_file(filename)
    for item in obj:
        data[item] = obj[item]
    save_to_file(data, filename)

def load_from_file(filename, asIs=False):
    if not os.path.exists(filename):
        return {}
    with mainFileLock:
        if not fileLocks.get(filename):
            fileLocks[filename] = threading.Lock()
    with fileLocks[filename]:
        with open(filename, 'r') as file:
            data = file.read().strip()
            obj = load_from_json(data, asIs)
            return obj   

def preJsonSetToDynamoDb(obj, excludeProps=[]):
    if isinstance(obj, dict):
        return {k: preJsonSetToDynamoDb(v, excludeProps) for k, v in obj.items() if k not in excludeProps}
    elif isinstance(obj, list):
        return [preJsonSetToDynamoDb(item, excludeProps) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, date):
        obj = datetime.combine(obj, datetime.min.time()).replace(tzinfo=None)
        return obj.isoformat()
    elif isinstance(obj, str):
        try:
            # Try to parse string to datetime
            dt = datetime.fromisoformat(obj)
            return dt.isoformat()
        except ValueError:
            return obj  # Return as is if not a valid datetime
    
    if DB_TYPE == 'postgres':
        return obj

    if isinstance(obj, bool):
        return str(obj)
    elif False and isinstance(obj, int):  # If it's a timestamp
        try:
            return datetime.utcfromtimestamp(obj).isoformat()
        except:
            return obj
    elif isinstance(obj, (int, float)):
        return str(obj)
    return obj

def postJsonGetFromDynamoDb(obj, convert_to_timestamp=False):
    if isinstance(obj, dict):
        return {k: postJsonGetFromDynamoDb(v, convert_to_timestamp) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [postJsonGetFromDynamoDb(item, convert_to_timestamp) for item in obj]

    if DB_TYPE == 'postgres':
        return obj

    if isinstance(obj, str):
        try:
            # Convert ISO format string to datetime object
            dt = datetime.fromisoformat(obj)
            return int(dt.timestamp()) if convert_to_timestamp else dt#.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            if obj == 'True':
                return True
            elif obj == 'False':
                return False
            return obj           
    return obj

if __name__ == "__main__":
    append_to_file({'aaa':'bbb'}, f'{os.getenv("MY_DATA_FOLDER", f"/run/data/")}testFile.json')
