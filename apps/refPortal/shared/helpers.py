import os
import boto3
from botocore.exceptions import ClientError
import json
import time
import urllib
import requests
import asyncio
from datetime import date,datetime
from difflib import get_close_matches
import logging
import socket
import threading
from ics import Calendar, Event
import pytz

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, datetime):
                return obj.isoformat()
            return super().default(obj)
        except Exception as e:
            pass

class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, date):
                return obj.isoformat()
            return super().default(obj)
        except Exception as e:
            pass

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

def get_secret(secretName):
    secret_file_path = os.getenv("MY_SECRET_FILE", f"/run/secrets/")
    secret_file_path = secret_file_path + secretName

    try:
        with open(secret_file_path, 'r') as secret_file:
            secret = secret_file.read().strip()
        return secret
    except FileNotFoundError:
        print(f'Error Secret: file not found: {secret_file_path}')
        return None
    except Exception as e:
        print(f'Error secret: {e}')

def get_secret1(self, secretName):
    self.logger.debug(f'secret: {secretName}')
    region_name = 'il-central-1'
    secret = None

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        self.logger.debug(f'secret: Get Value')
        get_secret_value_response = client.get_secret_value(
            SecretId=secretName
        )
        self.logger.debug(f'secret: Get Value String')
        secretStr = get_secret_value_response['SecretString']
        #self.logger.info(f'secretStr: {secretStr}')
        secret = json.loads(secretStr)
        #self.logger.info(f'secretStr: {secret}')
        return secret

    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        #raise e
        self.logger.error(f'secret clientError: {e}')
        pass
    except Exception as e:
        self.logger.error(f'secret: {e}')
        pass

    return None

swDic = {}

def stopwatchStart(name):
    swDic[name] = time.perf_counter()

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

async def gotoUrl(page, url, timeout = None, level = None):
    stopwatchStart(f'{url}Url')
    for i in range(3):
        try:
            if timeout:
                await page.goto(url, timeout=timeout)
            else:
                await page.goto(url)#, wait_until='networkidle')
            break
        except Exception as ex:
            logging.info(f'{url} {ex}')
    await scroll_to_bottom(page)
    stopwatchStop(f'{url}Url', level=level)

async def getWazeRouteDuration(page, from_lat, from_lng, to_lat, to_lng, arriveAt=None):
    total_seconds = None
    
    try:
        waze_url = f'https://www.waze.com/ul?ll={to_lat},{to_lng}&navigate=yes&from={from_lat},{from_lng}'
        if arriveAt:
            arriveAtTs = int(arriveAt.timestamp()) * 1000
            waze_url = f'{waze_url}&time={arriveAtTs}&reverse=yes'
                    #https://www.waze.com/en-GB/live-map/directions?navigate=yes&to=ll.32.0429027%2C34.7937824&from=ll.32.0771918%2C34.8101153&time=1735084800000&reverse=yes

        # Navigate to the URL
        await gotoUrl(page, waze_url)

        # Wait for the elements with class 'field-item' to load
        await page.wait_for_selector(selector=".is-fastest", timeout=7000)

        # Extract all articles with class 'field-item'
        route_element_div = None
        is_fastest_element_div = await page.query_selector_all("div.wm-routes-item-desktop__header:has(ul li.is-fastest)")
        if is_fastest_element_div and len(is_fastest_element_div) == 1:
            route_element_div = is_fastest_element_div[0]
        else:
            elements = await page.query_selector_all("div.wm-routes-item-desktop__header")
            if elements and len(elements) > 0:
                route_element = elements[0]
        if route_element_div:
            span = await route_element_div.query_selector("span[title]")
            if span:
                title_secs = await span.get_attribute("title")    
                total_seconds = int(title_secs.replace(",", "").replace("s", ""))

    except Exception as e:
        print(f"getWazeRouteDuration: Error extracting route time: {e}")

    return total_seconds

def get_coordinates_google_maps(address):
    """
    Get precise coordinates for an address using Google Maps API.
    """
    try:
        api_key = get_secret('google_cloud_apikey')
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
    
def generate_waze_link(lat, lon):
    """
    Generate a Waze link using latitude and longitude.
    """
    base_url = "https://www.waze.com/ul"
    return f"{base_url}?ll={lat},{lon}&navigate=yes"

def get_accurate_waze_link(address):
    """
    Get the most accurate Waze link by geocoding the address with Google Maps.
    """
    coordinates, formatted_address, error = get_coordinates_google_maps(address)
    if coordinates:
        lat, lon = coordinates
        return generate_waze_link(lat, lon), formatted_address
    else:
        return error, None

def get_waze_link(address):
    """
    Generate a Waze link for a given address.
    
    Parameters:
        address (str): The address to navigate to.
        
    Returns:
        str: A Waze link.
    """
    base_url = "https://www.waze.com/ul"
    params = {
        "q": address,
        "navigate": "yes"
    }
    return f"{base_url}?{urllib.parse.urlencode(params)}"

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

def save_to_json(fields, ensure_ascii=False, indent=4):
    data = json.dumps(fields, ensure_ascii=ensure_ascii, indent=indent, cls=DateTimeEncoder)
    return data

def load_from_json(data):
    if data:
        obj = json.loads(data, object_hook=datetime_decoder)
        return obj
    else:
        return {}

mainFileLock = threading.Lock()
fileLocks = {}

def save_to_file(obj, filename):
    data = save_to_json(obj)
    with mainFileLock:
        if not fileLocks.get(filename):
            fileLocks[filename] = threading.Lock()
    with fileLocks[filename]:
        with open(filename, 'w') as file:
            file.write(data.strip())

def append_to_file(obj, filename):
    data = load_from_file(filename)
    for item in obj:
        data[item] = obj[item]
    save_to_file(data, filename)

def load_from_file(filename):
    if not os.path.exists(filename):
        return {}
    with mainFileLock:
        if not fileLocks.get(filename):
            fileLocks[filename] = threading.Lock()
    with fileLocks[filename]:
        with open(filename, 'r') as file:
            data = file.read().strip()
            obj = load_from_json(data)
            return obj
    
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

def find_best_match(text, candidates):
    matches = get_close_matches(text, candidates, n=1, cutoff=0.4)
    return matches[0] if matches else None

async def scroll_to_bottom(page):
    try:
        for i in range(0, 10):
            await page.evaluate(f"""() => {{window.scrollTo(0, {i*20} );}}""")
            await asyncio.sleep(25/1000)
    except Exception as e:
        pass

def getGameIcsFilename(refId, gameId):
    fileId = f'{refId}_{gameId}'
    icsFile = f'{os.getenv("MY_DATA_FILE", "/run/data/")}ics/{fileId}.ics'
    return (fileId, icsFile)

def createIcs(name, begin, duration, description, location, removal, fileName):
    israel_tz = pytz.timezone(os.environ.get('timezone'))
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

    event.begin = israel_tz.localize(begin)
    event.duration = {"hours": duration}
    event.description = description
    event.location = location
    if removal:
        event.status = 'CANCELLED'
    
    with open(fileName, "w") as f:
        f.writelines(gameCalendar)

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

if __name__ == "__main__":
    append_to_file({'aaa':'bbb'}, f'{os.getenv("MY_DATA_FILE", f"/run/data/")}testFile.json')