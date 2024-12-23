from playwright.sync_api import sync_playwright
import csv
import json
import urllib.parse
import requests

def scrape_field_details():
    url = "https://www.football.org.il/association/fields/"

    # Initialize Playwright
    with sync_playwright() as p:
        # Launch Chromium
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to the URL
        page.goto(url)

        # Wait for the elements with class 'field-item' to load
        page.wait_for_selector(".field-item")

        # Extract all articles with class 'field-item'
        field_elements = page.query_selector_all("article.field-item")

        # Parse field details
        fields = []
        for field in field_elements:
            details = {
                "title": field.query_selector("h2") and field.query_selector("h2").inner_text().strip(),
                "address": field.query_selector(".address") and field.query_selector(".address").inner_text().strip().split(':')[1].strip(),
                "contact": field.query_selector_all("span")[1].inner_text().strip().split(':')[1].strip() if len(field.query_selector_all("span")) == 4 else None,
                "phone": field.query_selector_all("span")[2].inner_text().strip().split(':')[1].strip() if len(field.query_selector_all("span")) == 4 else None,
                "level": field.query_selector_all("span")[3].inner_text().strip().split(':')[1].strip() if len(field.query_selector_all("span")) == 4 else None
            }
            wazeLink, formattedAddress = get_accurate_waze_link(f'{details["address"]}, ישראל')
            details["wazeLink"] = wazeLink
            details["formattedAddress"] = formattedAddress
            details["wazeLink2"] = get_waze_link(f'{details["address"]}, ישראל')
            fields.append(details)

        # Close the browser
        browser.close()

        return fields

import requests
import urllib.parse

def get_coordinates_google_maps(address):
    """
    Get precise coordinates for an address using Google Maps API.
    """
    try:        
        api_key2 = 'AIzaSyAKA0meXhZOYdSJRPLEfVnuIT_nfYhLG5o'
        api_key = 'AIzaSyAu3Ms3bNsvXbd-EpuUD3yK8mb_KLLV-CY'
        geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": address,
            "key": api_key,
        }
        response = requests.get(geocode_url, params=params)
        if response.status_code != 200:
            return None, None, "Error: Failed to connect to Google Maps API."
        
        results = response.json().get("results", [])
        if not results:
            return None, None, "Error: No matching location found."
        
        location = results[0]["geometry"]["location"]
        formatted_address = results[0]["formatted_address"]
        return (location["lat"], location["lng"]), formatted_address, None
    
    except Exception as e:
        return None, None, f"Error: {e}."
    
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

def get_better_waze_link(address):
    """
    Generate the most accurate Waze link for a given address.
    
    Parameters:
        address (str): The address to navigate to.
        
    Returns:
        str: A Waze link or an error message if no results are found.
    """
    # Waze API endpoint for geocoding
    geocoding_api_url = "https://www.waze.com/SearchServer/mozi"
    params = {
        "q": address,
        "lang": "en",
    }

    # Fetch results from Waze's search server
    response = requests.get(geocoding_api_url, params=params)
    if response.status_code != 200:
        return "Error: Failed to connect to Waze API."

    # Parse the JSON response
    results = response.json().get("suggestions", [])
    if not results:
        return "Error: No matching location found."

    # Use the most accurate (first) result
    top_result = results[0]
    location_name = top_result.get("name")
    lat = top_result.get("location", {}).get("lat")
    lon = top_result.get("location", {}).get("lon")

    if lat is None or lon is None:
        return "Error: No location coordinates found."

    # Generate the Waze navigation link
    base_url = "https://www.waze.com/ul"
    waze_link = f"{base_url}?ll={lat},{lon}&navigate=yes"
    
    return waze_link

def save_to_csv(data, filename="fields.csv"):
    keys = data[0].keys() if data else []
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)

def save_to_json(fields, filename="fields.json"):
    with open(filename, 'w') as fields_file:
        data = json.dumps(fields, ensure_ascii=False)
        fields_file.write(data.strip())

def load_from_json(filename="fields.json"):
    with open(filename, 'r') as fields_file:
        data = fields_file.read().strip()
        fields = json.loads(data)
        return fields

def convertList2Dic(fields):
    newFields = {}
    for field in fields:
        newFields[field["title"]] = field
    return newFields

# Run the script and print the results
if __name__ == "__main__":
    #field_details = scrape_field_details()
    #save_to_csv(field_details)
    #save_to_json(field_details)
    field_details = load_from_json()
    new_field_details = convertList2Dic(field_details)
    save_to_json(new_field_details, "newFields.json")
    for field in field_details:
        print(field)
