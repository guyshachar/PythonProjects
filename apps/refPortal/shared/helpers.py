import os
import boto3
from botocore.exceptions import ClientError
import json
import time
import uuid
import inspect
import re
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from difflib import get_close_matches
from thefuzz import fuzz
import logging
import socket
from ics import Calendar, Event
import pytz
from colorama import Fore, Style
from PIL import Image, ImageDraw, ImageFont, features
import pickle
import copy
import types
import asyncio
import threading
from geopy.distance import geodesic

def calculate_distance_between_coordinates(lat1, lng1, lat2, lng2, unit='km'):
    """
    Calculate the distance between two coordinates using the geodesic formula.
    
    Args:
        lat1 (float): Latitude of first point
        lng1 (float): Longitude of first point
        lat2 (float): Latitude of second point
        lng2 (float): Longitude of second point
        unit (str): Unit of measurement ('km' for kilometers, 'miles' for miles)
    
    Returns:
        float: Distance between the two points in the specified unit
    
    Example:
        >>> distance = calculate_distance_between_coordinates(32.0853, 34.7818, 31.7683, 35.2137)
        >>> print(f"Distance: {distance:.2f} km")
        Distance: 67.23 km
    """
    try:
        # Calculate distance using geopy geodesic (most accurate for Earth's surface)
        point1 = (lat1, lng1)
        point2 = (lat2, lng2)
        
        if unit.lower() == 'miles':
            distance_value = geodesic(point1, point2).miles
        else:
            distance_value = geodesic(point1, point2).kilometers
            
        return distance_value
            
    except Exception as ex:
        logging.error(f"Error calculating distance between coordinates", ex)
        return None

def localNow():
    localNow = datetime.now(ZoneInfo(os.getenv('TZ')))
    localNow = localNow.replace(tzinfo=None)
    return localNow

def utcNow():
    utcNow = datetime.now(ZoneInfo('UTC'))
    utcNow = utcNow.replace(tzinfo=None)
    return utcNow

def is_valid_time(s):
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except ValueError:
        return False

def convert_to_datetime(s):
    try:
        return datetime.strptime(s, "%d/%m/%y %H:%M")
    except ValueError:
        try:
            return datetime.strptime(s, "%d/%m/%Y %H:%M")
        except ValueError:
            try:
                return datetime.strptime(s, "%d/%m/%yT%H:%M")
            except ValueError:
                try:
                    return datetime.strptime(s, "%d/%m/%YT%H:%M")
                except ValueError:
                    try:
                        return datetime.strptime(s, "%d/%m/%y")
                    except ValueError:
                        try:
                            return datetime.strptime(s, "%d/%m/%Y")
                        except ValueError:
                            try:
                                return datetime.strptime(s, "%Y-%m-%d")
                            except ValueError:
                                try:
                                    return datetime.strptime(s, "%y-%m-%d")
                                except ValueError:
                                    return None
import base64

def safe_encode_header(value):
    """Encode header values using Base64 to preserve all characters"""
    try:
        if isinstance(value, str):
            # Encode to UTF-8 bytes, then to Base64
            encoded = base64.b64encode(value.encode('utf-8')).decode('ascii')
            return encoded
        else:
            return str(value)
    except Exception:
        return 'unknown'

def safe_decode_header(encoded_value):
    """Decode Base64 encoded header values"""
    try:
        # Decode from Base64 to UTF-8 string
        decoded = base64.b64decode(encoded_value.encode('ascii')).decode('utf-8')
        return decoded
    except Exception:
        return 'unknown'

def split_text(text, size_limit):
    """
    Splits text into chunks by words while retaining newlines.

    :param text: The original text.
    :param size_limit: Maximum size of each chunk.
    :return: A list of text chunks.
    """
    chunks = []
    current_chunk = ""

    for line in text.splitlines(keepends=True):  # Retain newlines in the split
        for word in line.split():
            # Check if adding this word exceeds the size limit
            if len(current_chunk) + len(word) + 1 > size_limit:  # +1 for space/newline
                chunks.append(current_chunk.strip())
                current_chunk = ""
            current_chunk += word + " "
        current_chunk += "\n"
        if False and current_chunk.endswith("\n"):  # Ensure newlines are respected
            chunks.append(current_chunk.strip())
            current_chunk = ""

    if current_chunk:  # Add any remaining text
        chunks.append(current_chunk.strip())

    return chunks

def extract_urls(text):
    # Pattern to match URLs
    url_pattern = r'https?://(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?)?'
    
    # Find all URLs in text
    urls = re.findall(url_pattern, text)
    return urls

def get_secret(secretKey):
    if isRunningInLambda():
        # Create a Secrets Manager client
        client = boto3session.client(
            service_name='secretsmanager',
            region_name=os.getenv('awsRegion')
        )

        try:
            get_secret_value_response = client.get_secret_value(
                SecretId=os.getenv('awsSecretName', 'prod/refPortalSecret')
            )
        except Exception as ex:
            raise ex

        # Decrypts secret using the associated KMS key.
        secret = get_secret_value_response['SecretString']
        secretPairs = json.loads(secret)
        return secretPairs.get(secretKey)
    
    else:
            
        secret_file_path = os.getenv("MY_SECRET_FOLDER", f"/run/secrets/")
        secret_file_path = secret_file_path + secretKey

        try:
            with open(secret_file_path, 'r') as secret_file:
                secret = secret_file.read().strip()
            return secret
        except FileNotFoundError:
            print(f'Error Secret: file not found: {secret_file_path}')
            return None
        except Exception as e:
            print(f'Error secret: {e}')

swDic = {}

def stopwatchStart(name):
    swDic[name] = time.perf_counter()
    return swDic[name]

def stopwatchElapsed(name):
    elapsedTime = int((time.perf_counter() - swDic[name])*1000)
    elapsedTimeHHMMSS = seconds_to_hms(round(elapsedTime/1000))
    return elapsedTimeHHMMSS

def stopwatchStop(name, level=None):
    elapsedTime = int((time.perf_counter() - swDic[name])*1000)
    elapsedTimeHHMMSS = seconds_to_hms(round(elapsedTime/1000))
    if level:
        eval(f'logging.{level}')(f'sw {name}={elapsedTimeHHMMSS} {elapsedTime}ms')
    else:
        logging.debug(f'sw {name}={elapsedTime}')
    return elapsedTime

def get_coordinates_google_maps(address):
    """
    Get precise coordinates for an address using Google Maps API.
    """
    try:
        api_key = get_secret('google_maps_api_key_server')
        geocode_url = 'https://maps.googleapis.com/maps/api/geocode/json'
        params = {
            "address": address,
            "key": api_key,
        }
        response = requests.get(geocode_url, params=params)
        if response.status_code != 200:
            return None, None, 'Error: Failed to connect to Google Maps API.'
        
        results = response.json().get("results", [])
        if not results:
            return None, None, 'Error: No matching location found.'
        
        location = results[0]["geometry"]["location"]
        formatted_address = results[0]["formatted_address"]
        return (location["lat"], location["lng"]), formatted_address, None
    
    except Exception as e:
        return None, None, f'Error: {e}.'
    
def seconds_to_hms(total_seconds):
    # Remove the 's' and commas from the input    
    # Calculate hours, minutes, and seconds
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    # Format as hh:mm:ss
    duration_str = f'{minutes:02}:{seconds:02}'
    if hours >= 0:
        duration_str = f'{hours:02}:{duration_str}'
    return duration_str

def isPartOf(obj, part):
    try:
        return hasattr(obj, part) or part in obj
    except:
        return False

def listToDictionary(list):
    dict = {}
    for item in list:
        key, value = next(iter(item.items()))
        dict[key] = value
    
    return dict

def safe_get(nested_dict, keys, default=None):
    """
    Safely get a value from a nested dictionary.

    Args:
        nested_dict (dict): The dictionary to search.
        keys (list): List of keys to traverse in order.
        default: Value to return if any key is missing.

    Returns:
        The value if found, otherwise the default value.
    """
    current = nested_dict
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current

def validatePath(file):
    path = os.path.dirname(file)
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def getGameIcsFilename(tenantKey, gameId):
    fileId = f'{gameId}'
    icsFile = f'{os.getenv("MY_DATA_FOLDER", "/run/data/")}ics/{tenantKey}/{fileId}.ics'
    validatePath(icsFile)
    return (fileId, icsFile)

def createIcs(name, begin, durationInMins, description, location, removal, fileName):
    localTZ = pytz.timezone(os.getenv('TZ'))
    gameCalendar = None
    event = None

    if os.path.exists(fileName):
        with open(fileName, "r") as f:
            gameCalendar = Calendar(f.read())

        # Find the event to update (Example: Updating first event)
        for ev in gameCalendar.events:
            if ev.name == name:
                event = ev
                break

    if not gameCalendar:
        gameCalendar = Calendar()
    
    if not event:
        event = Event()
        event.name = name
        gameCalendar.events.add(event)

    event.begin = localTZ.localize(begin)
    event.duration = timedelta(minutes=durationInMins)
    event.description = description
    event.location = location
    if removal:
        event.status = 'CANCELLED'
    else:
        event.status = 'CONFIRMED'
    
    with open(fileName, "w") as f:
        f.writelines(gameCalendar)

    if isRunningInLambda():
        try:
            bucketName = os.getenv('awsBucketName') + '-' + os.getenv('app_env')
            objectName = fileName.lstrip(os.getenv("MY_DATA_FOLDER", "/run/data/"))
            boto3s3.upload_file(fileName, bucketName, objectName)
        except Exception as ex:
            logging.error(f"Error uploading file", ex)

def testConnection(host="8.8.8.8", port=80):
    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        return None
    except socket.timeout:
        return "Connection timed out"
    except socket.gaierror:
        return "DNS resolution failed"
    except socket.error as ex:
        return f"Network error: {ex}"

def logError(logger, label, ex=None, refereeDetail=None):
    if not ex:
        logger.error(f'{label}')
        return

    timeoutError = type(ex).__name__ == 'TimeoutError'
    if refereeDetail:
        if timeoutError:
            logger.error(colorText(refereeDetail, f'{label}: Exception Type: {type(ex).__name__}'))
        else:
            logger.error(colorText(refereeDetail, f'{label}: Exception Type: {type(ex).__name__}, Message:', ex))
    else:
        if timeoutError:            
            logger.error(f'{label}: Exception Type: {type(ex).__name__}')
        else:
            logger.error(f'{label}: Exception Type: {type(ex).__name__}, Message:', ex)
    if not timeoutError:
        logging.exception("An error occurred")
    if not timeoutError:            
        pass

def colorText(refereeDetail, text):
    color = Fore.WHITE
    try:
        if refereeDetail.get('color'):
            color = eval(f"Fore.{refereeDetail['color']}")
    except Exception as ex:
        pass
    return f'{color}{refereeDetail["name"]}#{refereeDetail["refId"]}:{text}{Style.RESET_ALL}'

def find_intuitive_matches(query:str, choices, cutoff:float=0.5):
    """
    Finds the best matches for a query from a list of choices
    using a token-based comparison. token_set_ratio returns 100 when
    one string's tokens are a subset of the other, so we apply a
    length-similarity factor to prefer the more specific (longer) match.
    """
    results = []

    def _score(query_str: str, choice_str: str) -> float:
        base = fuzz.token_set_ratio(query_str, choice_str) / 100
        if base == 0:
            return 0.0
        # Prefer choice closer in length to query (exact/longer match over subset)
        len_ratio = min(len(query_str), len(choice_str)) / max(len(query_str), len(choice_str)) if (query_str and choice_str) else 1.0
        return base * (0.85 + 0.15 * len_ratio)

    if isinstance(choices, list):
        for choice in choices:
            score = _score(query, choice)
            if score >= cutoff:
                results.append((choice, score))
    elif isinstance(choices, dict):
        for choiceKey, choiceValue in choices.items():
            score1 = _score(query, choiceKey)
            if score1 >= cutoff:
                results.append((choiceKey, score1))
            if choiceValue.get('findText'):
                score2 = _score(query, choiceValue.get('findText'))
                if score2 >= cutoff:
                    results.append((choiceKey, score2))
    
    # Sort by score descending, then by choice length descending (prefer more specific)
    results.sort(key=lambda x: (x[1], len(x[0])), reverse=True)
    
    if len(results) > 0:
        return results[0]
    return None

def flatten_values(data_structure):
    """
    Recursively finds all 'leaf' values in a nested structure
    (dictionaries or lists) and yields them as strings.
    """
    if isinstance(data_structure, dict):
        # If it's a dictionary, recurse on its values
        for value in data_structure.values():
            yield from flatten_values(value)
    elif isinstance(data_structure, list):
        # If it's a list, recurse on its items
        for item in data_structure:
            yield from flatten_values(item)
    else:
        # Base case: If it's not a dict or list, it's a leaf value
        yield str(data_structure)

def initTracing(p):
    p.debug = 'pw:browser,pw:page'

async def startTracing(page):
    await page.context.tracing.start(screenshots=True, snapshots=True)

async def stopTracing(page, fileSuffix=''):
    tracingFile = f'{os.getenv("MY_DATA_FOLDER", f"/run/data/")}tracing/traceFinally_{fileSuffix}{localNow().strftime("%Y%m%d%H%M%S")}.zip'
    await page.context.tracing.stop(path=tracingFile)

def areObjectsIdentical(obj1, obj2, ignoreUpdated=False):
    # Convert objects to dictionaries (if they are class instances)
    if hasattr(obj1, "__dict__"):
        obj1 = obj1.__dict__.copy()
    if hasattr(obj2, "__dict__"):
        obj2 = obj2.__dict__.copy()
    
    # Remove "update" key if ignoreUpdate is True
    if ignoreUpdated:
        obj1.pop("updated", None)
        obj2.pop("updated", None)

    # Compare the JSON-serialized versions (ensures deep comparison)
    return json.dumps(obj1, sort_keys=True) == json.dumps(obj2, sort_keys=True)

boto3session = boto3.session.Session()
boto3s3 = boto3.client('s3')

def sortDictByProperty(obj, property, reverse=False):
    return dict(sorted(obj.items(), key=lambda x: x[1][property], reverse=reverse))

def isRunningInLambda():
    val = os.getenv('AWS_LAMBDA_FUNCTION_NAME')
    logging.debug(f'AWS_LAMBDA_FUNCTION_NAME={val}')
    return val is not None

def getBucketName():
    bucketName = os.getenv('awsBucketName') + '-' + os.getenv('app_env')
    return bucketName

# Wrapper to run the async function in a new thread
def run_async_in_thread(coro_func, **kwargs):
    def runner():
        asyncio.run(coro_func(**kwargs))  # creates its own event loop
    thread = threading.Thread(target=runner)
    thread.start()

def run_sync_in_thread(func, *args):
    def runner():
        func(*args)
    thread = threading.Thread(target=runner)
    thread.start()

def safe_create_task(coro):                                                                                                                                                                      
    task = asyncio.create_task(coro)                                                                                                                                                                    
    task.add_done_callback(handle_task_error)                                                                                                                                                     
                                                                                                                                                                                                        
def handle_task_error(task):                                                                                                                                                                     
    if task.cancelled():                                                                                                                                                                                
        return                                                                                                                                                                                          
    ex = task.exception()                                                                                                                                                                               
    if ex:                                                                                                                                                                                              
        logging.error(f'Background task failed: {type(ex).__name__}: {ex}') 

async def takeScreenshot(page=None, refereeDetail=None, tag=None):
    # Take screenshot before returning False
    try:
        _page = page or getObjectFromCaller(objectName='page')
        if not _page:
            logging.warning(f'takeScreenshot: No page object found')
            return
        if hasattr(_page, 'is_closed') and _page.is_closed():
            logging.debug('takeScreenshot: page is closed, skipping')
            return
        _refereeDetail = refereeDetail or getObjectFromCaller(objectName='refereeDetail')

        timestamp = int(time.time())
        refId = (_refereeDetail or {}).get('refId', 'unknown')
        base_storage_path = os.getenv("MEDIA_STORAGE_PATH", "/run/data/media_files")
        screenshot_path = os.path.join(base_storage_path, 'screenshots', refId, tag, f'{timestamp}.png')
        validatePath(screenshot_path)
        await _page.screenshot(path=str(screenshot_path), full_page=True)
        print(f'WARNING:Screenshot saved: {screenshot_path}')
    except Exception as screenshot_ex:
        print(f'ERROR:Failed to take screenshot {screenshot_ex}')

async def retryBlock(func, *args, **kwargs): #func
    latencyFactor = float(os.getenv('latencyFactor', '1'))
    retries = kwargs.pop('retries', 3)
    interval = kwargs.pop('interval', 1000)

    for i in range(retries):
        try:
            result = await func(*args, **kwargs)
            if result:
                return True
            await asyncio.sleep(interval * (i+1) * latencyFactor / 1000)
        except Exception as ex:
            logging.error(f'retryBloc: {ex}')
    
    return False

def getObjectFromCaller(objectName='page'):
    """
    Walk back through the call stack and stop at the frame where 'takeScreenshot' is being called.
    Then return the variable from that frame's locals that matches objectType (e.g., 'page' or 'refereeDetail').
    """
    stack = inspect.stack()
    # Frame 0: getObjectFromCaller (this method)
    # Frame 1: takeScreenshot (the method that calls getObjectFromCaller)
    # Frame 2: The caller of takeScreenshot - this is where we want to look
    
    # Start from frame 2 (the caller of takeScreenshot)
    for i, frame_info in enumerate(stack[2:], start=2):
        frame = frame_info.frame
        # Skip frames from this file (logger.py) - we want the caller's frame
        if frame_info.filename == __file__:
            continue
        # This is the frame where takeScreenshot was called from
        # Return the variable from this frame's locals that matches objectType
        if objectName in frame.f_locals:
            return frame.f_locals.get(objectName, None)
    return None

def createHebrewTextImage(gameDetail):
    # Image config
    img_size = (64, 64)
    bg_color = "white"
    text_color = "black"
    lines = [gameDetail['homeTeamName'], gameDetail['guestTeamName'], gameDetail['tournamentName']]  # Hebrew text, 3 lines
    font_size = 8
    '''
    folder_path = "/lambdaFunction"
    path = Path(folder_path)
    print(f'path {path} exists={path.exists()}')
    entries = os.listdir(folder_path)
    entries.sort() 
    for entry in entries:
        full_path = os.path.join(folder_path, entry)
        if os.path.isfile(full_path):
            print(f"File: {entry}")
        elif os.path.isdir(full_path):
            print(f"Directory: {entry}")    
    path = Path(folder_path)
    print(f'path {path} exists={path.exists()}')
    
    font_path = Path(f"{folder_path}/SFHebrew.ttf")
    if not font_path.exists():
        font_path = Path("/var/task/function/fonts/SFHebrew.ttf")
        if not font_path.exists():
            font_path = Path("/var/task/fonts/SFHebrew.ttf")
            if not font_path.exists():
                raise FileNotFoundError("Font file not found")
    '''
    font_path = os.getenv('fontPath')
    print(f'{font_path} FOUND')
    with open(font_path, "rb") as f:
        print(f.read(4)) 
    # Create image
    img = Image.new("RGB", img_size, color=bg_color)
    draw = ImageDraw.Draw(img)

    # Load a font that supports Hebrew
    # Use a TTF font file that supports Hebrew — e.g., DejaVuSans or Arial
    font = ImageFont.truetype(font_path, size=font_size)

    # Draw a circle in the bottom right corner
    circle_radius = img_size[0] / 2 - 2
    circle_center = (img_size[0] - circle_radius - 2, img_size[1] - circle_radius - 2)
    draw.ellipse([
        (circle_center[0] - circle_radius, circle_center[1] - circle_radius),
        (circle_center[0] + circle_radius, circle_center[1] + circle_radius)
    ], outline='red', width=2)

    # Calculate spacing
    line_height = font.getbbox("hg")[3] + 1
    y = (img_size[1] - (line_height * len(lines))) // 2  # Center vertically

    for line in lines:
        # Get text width to center horizontally
        text_width = draw.textlength(line, font=font)
        x = (img_size[0] - text_width) // 2
        draw.text((x, y), line, fill=text_color, font=font, direction="rtl")  # RTL for Hebrew
        y += line_height

    # === Save image ===
    pngFile = f'{os.getenv("MY_TMP_FOLDER", f"/run/data/")}{gameDetail["gamePk"]}_{str(uuid.uuid4())[:8]}.jpg'
    img.save(pngFile)
    return pngFile

def delProperties(obj, properties):
    if isinstance(obj, dict):
        if not isinstance(properties, list):
            properties = [properties]
        for property in properties:
            if property in obj:
                del obj[property]
    elif isinstance(obj, list):
        if not isinstance(properties, list):
            properties = [properties]
        for item in obj:
            delProperties(item, properties)
    elif isinstance(obj, tuple):
        for item in obj:
            delProperties(item, properties)
    return obj

def deepDiff(a, b, path=""):
    differences = []

    if type(a) != type(b):
        differences.append(f"Type mismatch at {path}: {type(a)} vs {type(b)}")
        return differences

    if isinstance(a, dict):
        all_keys = set(a.keys()) | set(b.keys())
        for key in all_keys:
            if key not in a:
                differences.append(f"Missing key in first at {path}.{key}")
            elif key not in b:
                differences.append(f"Missing key in second at {path}.{key}")
            else:
                differences += deepDiff(a[key], b[key], f"{path}.{key}")
    elif isinstance(a, (list, tuple)):
        if len(a) != len(b):
            differences.append(f"Length mismatch at {path}: {len(a)} vs {len(b)}")
        else:
            for i in range(len(a)):
                differences += deepDiff(a[i], b[i], f"{path}[{i}]")
    else:
        if a != b:
            differences.append(f"Value mismatch at {path}: {a} vs {b}")

    return differences

def safeClone(obj):
    try:
        return copy.deepcopy(obj)
    except Exception as ex:
        if isinstance(obj, (types.CoroutineType, asyncio.Future)):
            return None  # Or raise an error / log
        return obj  # fallback: return as-is
    
def cleanUnpickleable(obj):
    if isPickleable(obj):
        return obj
    cleanedObj = internalCleanUnpickleable(obj)
    return cleanedObj

def isPickleable(obj):
    try:
        pickle.dumps(obj)
        return True
    except Exception:
        return False

def internalCleanUnpickleable(obj):
    if isinstance(obj, dict):
        return {
            k: internalCleanUnpickleable(v)
            for k, v in obj.items()
            if isPickleable(v)
        }
    elif isinstance(obj, list):
        return [internalCleanUnpickleable(i) for i in obj if isPickleable(i)]
    elif isinstance(obj, tuple):
        return tuple(internalCleanUnpickleable(i) for i in obj if isPickleable(i))
    elif isinstance(obj, set):
        return {internalCleanUnpickleable(i) for i in obj if isPickleable(i)}
    else:
        return obj if isPickleable(obj) else None

def merge_nested_dicts(targetDict, sourceDict):
    """
    Recursively merge two nested dictionaries.
    dict2 values override dict1 values for same keys.
    """
    result = targetDict.copy() if targetDict else {}
    
    for key, value in (sourceDict or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Both values are dictionaries, merge them recursively
            result[key] = merge_nested_dicts(result[key], value)
        else:
            # Override with dict2 value
            result[key] = value
    
    return result

def resolve_notification_item_id(id_value, target=None):
    """
    Return the logical notification item ``id`` (e.g. game pk string).
    DynamoDB may store a composite sort key in ``id`` as target#id#notificationType#...;
    re-saving with that composite as ``id`` nests keys and creates duplicate rows.
    """
    if id_value is None:
        return id_value
    s = str(id_value).strip()
    if not s or '#' not in s:
        return s
    parts = [p for p in s.split('#') if p]
    if not parts:
        return s
    known_targets = ('tournamentGames', 'refereeGames', 'refereeReviews')
    if parts[0] in known_targets and len(parts) >= 2:
        return parts[1]
    if target and str(target) in known_targets and parts[0] == str(target) and len(parts) >= 2:
        return parts[1]
    # Legacy corrupted keys: gameFirstReminder#...#timestamp — cannot recover gamePk
    return s
    
def deep_merge_and_prune(target, updates):
    # Remove keys not in updates
    for key in list(target.keys()):
        if key not in updates:
            del target[key]

    # Update/add keys
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge_and_prune(target[key], value)
        else:
            target[key] = value

def test_pickle(obj, path="root"):
    try:
        pickle.dumps(obj)
        return  # It's safe
    except Exception as e:
        print(f"❌ Not pickleable at {path}: {type(obj).__name__} – {e}")

        # Check inside dicts
        if isinstance(obj, dict):
            for k, v in obj.items():
                test_pickle(v, f"{path}[{repr(k)}]")
        # Check inside lists/tuples/sets
        elif isinstance(obj, (list, tuple, set)):
            for i, item in enumerate(obj):
                test_pickle(item, f"{path}[{i}]")

def split_text_and_url(text):
    if text:
        url_match = re.search(r'https?://\S+', text)
        if url_match:
            url = url_match.group(0)
            text_part = text.replace(url, "").strip().rstrip(":")
            return text_part, url
    return text, None

def extract_phone_number(text):
    # Remove delimiters
    cleaned = re.sub(r"[\s\-]", "", text)

    # Match +<country code> followed by 7-13 digits
    match = re.search(r"\+[\d]{1,4}[\d]{7,13}", cleaned)
    if match:
        return match.group(0)

    # Match 0X... or just digits, fallback to +972
    match = re.search(r"\b0?\d{9,10}\b", cleaned)
    if match:
        raw = match.group(0).lstrip("0")
        return f"+972{raw}"

    return None

def extract_number(text):
    match = re.search(r"\d{2,10}", text)
    return normalize_year(match.group(0)) if match else None

def extract_number2(message):
    # Matches: 24-25, 2024-2025, 2025, 30-31, 2030-31
    pattern = r"(\d{2,9})(?:[-–](\d{2,2}))?"
    matches = re.findall(pattern, message)
    if matches:
        # Return list of all found years
        return [normalize_year(y) for y in matches[0] if y]
    return None

def normalize_year(year_str):
    year = int(year_str)
    if year < 100:  # 2-digit year
        return 2000 + year
    return year

def normalize_text(text):
    return text.replace("#", " ").replace("–", "-").replace("_", " ").lower().strip()

def split_letters_digits(text):
    # Add space between Hebrew/English letters and digits
    return re.sub(r'(?<=[\u0590-\u05FFa-zA-Z])(?=\d)', ' ', text)

def contains_year_format(text):
    """
    Check if text contains a year format like "1987-88" or "2024-25"
    
    Args:
        text (str): The text to check
        
    Returns:
        bool: True if text contains a year format, False otherwise
        
    Examples:
        >>> contains_year_format("Season 1987-88 was great")
        True
        >>> contains_year_format("The year 2024-25")
        True
        >>> contains_year_format("No year format here")
        False
        >>> contains_year_format("1987-88 season")
        True
    """
    if not text:
        return False
    
    # Pattern to match year format: 4 digits - 2 digits
    # Examples: 1987-88, 2024-25, 1999-00
    pattern = r'\b\d{4}-\d{2}\b'
    
    return bool(re.search(pattern, text))

def extract_year_format(text):
    """
    Extract year format from text if it exists
    
    Args:
        text (str): The text to extract from
        
    Returns:
        str or None: The year format if found, None otherwise
        
    Examples:
        >>> extract_year_format("Season 1987-88 was great")
        "1987-88"
        >>> extract_year_format("The year 2024-25")
        "2024-25"
        >>> extract_year_format("No year format here")
        None
    """
    if not text:
        return None
    
    # Pattern to match year format: 4 digits - 2 digits
    pattern = r'\b\d{4}-\d{2}\b'
    
    match = re.search(pattern, text)
    return match.group() if match else None

def is_valid_year_format(year_text):
    """
    Validate if a year format is valid (e.g., "1987-88")
    
    Args:
        year_text (str): The year format to validate
        
    Returns:
        bool: True if valid year format, False otherwise
        
    Examples:
        >>> is_valid_year_format("1987-88")
        True
        >>> is_valid_year_format("2024-25")
        True
        >>> is_valid_year_format("1987-1988")
        False
        >>> is_valid_year_format("87-88")
        False
    """
    if not year_text:
        return False
    
    # Pattern to match exactly: 4 digits - 2 digits
    pattern = r'^\d{4}-\d{2}$'
    
    return bool(re.match(pattern, year_text))

def extract_all_year_formats(text):
    """
    Extract all year formats from text
    
    Args:
        text (str): The text to extract from
        
    Returns:
        list: List of all year formats found
        
    Examples:
        >>> extract_all_year_formats("Seasons 1987-88 and 2024-25 were great")
        ["1987-88", "2024-25"]
        >>> extract_all_year_formats("No year formats")
        []
    """
    if not text:
        return []
    
    # Pattern to match year format: 4 digits - 2 digits
    pattern = r'\b\d{4}-\d{2}\b'
    
    return re.findall(pattern, text)


def dict_diff(a, b, deep=False):
    """
    Compare two dicts and return their differences.

    Args:
        a: First mapping (often the "before" / left side).
        b: Second mapping (often the "after" / right side).
        deep: If True, compare nested dict values recursively. If both values for a
            key are dicts, differences are expressed as another dict_diff-shaped
            structure under that key. Otherwise values are compared with ``!=``.

    Returns:
        dict: May include (omitted when empty):
            - only_in_a: keys only in ``a``, with values from ``a``
            - only_in_b: keys only in ``b``, with values from ``b``
            - changed: keys in both with different values:
                - Shallow mode, or non-dict pair: ``{'old': <a value>, 'new': <b value>}``
                - Deep mode with two dicts: nested result from ``dict_diff`` (same shape)

    Raises:
        TypeError: If ``a`` or ``b`` is not a dict.

    Example:
        >>> dict_diff({"x": 1, "y": 2}, {"x": 1, "y": 3, "z": 0})
        {'only_in_b': {'z': 0}, 'changed': {'y': {'old': 2, 'new': 3}}}
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        raise TypeError("dict_diff expects two dict arguments")

    only_in_a = {k: a[k] for k in a if k not in b}
    only_in_b = {k: b[k] for k in b if k not in a}
    changed = {}

    for k in a:
        if k not in b:
            continue
        va, vb = a[k], b[k]
        if deep and isinstance(va, dict) and isinstance(vb, dict):
            sub = dict_diff(va, vb, deep=True)
            if sub:
                changed[k] = sub
        elif va != vb:
            changed[k] = {"old": va, "new": vb}

    out = {}
    if only_in_a:
        out["only_in_a"] = only_in_a
    if only_in_b:
        out["only_in_b"] = only_in_b
    if changed:
        out["changed"] = changed
    return out


if __name__ == "__main__":
    print("libraqm support:", features.check("raqm"))
    gameDetail = { 
        'gamePk': "ליגה ג' מרכזשיכון ותיקים רג - הפ' חולון צפרירים26", 
        'homeTeamName': "הפ' חולון צפרירים", 
        'guestTeamName': "שיכון ותיקים רג",
        'tournamentName': "ליגה ג' מרכז" ,
        'updated': '123',
        'content_hash': '56e3546465'
    }
    pass
        