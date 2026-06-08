from playwright.sync_api import sync_playwright
import csv
import sys
import os
import logging
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db import DynamodbClient, DbClientBase
from shared.db.cacheService import CacheService

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
        fields = {}
        for field in field_elements:
            details = {
                "title": field.query_selector("h2") and field.query_selector("h2").inner_text().strip(),
                "address": field.query_selector(".address") and field.query_selector(".address").inner_text().strip().split(':')[1].strip(),
                "contact": field.query_selector_all("span")[1].inner_text().strip().split(':')[1].strip() if len(field.query_selector_all("span")) == 4 else None,
                "phone": field.query_selector_all("span")[2].inner_text().strip().split(':')[1].strip() if len(field.query_selector_all("span")) == 4 else None,
                "level": field.query_selector_all("span")[3].inner_text().strip().split(':')[1].strip() if len(field.query_selector_all("span")) == 4 else None
            }
            wazeLink, formattedAddress = get_accurate_waze_link(f'{details["address"]}, ישראל')
            details["addressDetails"] = {}
            details["wazeLink"] = wazeLink
            details["addressDetails"]["formattedAddress"] = formattedAddress
            details["wazeLink2"] = get_waze_link(f'{details["address"]}, ישראל')
            details["addressDetails"]["address"] = details["address"]
            del details["address"]
            fields[details['title']] = details

        # Close the browser
        browser.close()

        return fields

def generate_waze_link(lat, lon):
    """
    Generate a Waze link using latitude and longitude.
    """
    base_url = "https://www.waze.com/ul"
    return f"{base_url}?ll={lat},{lon}&navigate=yes"

def update_field_address_details(tenantKey, fieldTitle):
    from shared.appContainer import AppContainer
    import shared.configurationDI as configDI
    appContainer = AppContainer()
    appContainer.config.from_dict(configDI.configDI)
    appContainer.init_resources()
    cacheService:CacheService=appContainer.cache_service()
    field = cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldTitle, forceReload=True)
    if not field:
        return None
    wazeLink, formattedAddress = get_accurate_waze_link(f'{field["addressDetails"]["address"]}, ישראל')
    field["addressDetails"]["wazeLink"] = wazeLink
    field["addressDetails"]["formattedAddress"] = formattedAddress
    cacheService.setField(tenantKey=tenantKey, fieldName=fieldTitle, value=field)
    return field

def get_accurate_waze_link(address):
    """
    Get the most accurate Waze link by geocoding the address with Google Maps.
    """
    coordinates, formatted_address, error = helpers.get_coordinates_google_maps(address)
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
    return f"{base_url}?{urlencode(params)}"

def save_to_csv(data, filename="./config/fields.csv"):
    keys = data[0].keys() if data else []
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)

def convertList2Dic(fields):
    newFields = {}
    for field in fields:
        newFields[field["title"]] = field
    return newFields

def addCoordinates(fields):
    for fieldName, field in fields.items():
        field["wazeLink"] = field["addressDetails"]["wazeLink"]
        wazeLink = field["wazeLink"]
        pos1 = wazeLink.find("=")
        pos2 = wazeLink.find(",")
        pos3 = wazeLink.find("&")
       #https://www.waze.com/ul?ll=31.807275,35.10271&navigate=yes
        lat = float(wazeLink[pos1+1:pos2])
        lng = float(wazeLink[pos2+1:pos3])
        field["addressDetails"]["coordinates"] = {"lat": lat, "lng": lng}
        field["addressDetails"]["wazeLink"] = field['wazeLink']
        del field["wazeLink"]
        if "wazeLink2" in field:
            del field["wazeLink2"]
    return fields

def addNewFields(fields, dbClient:DbClientBase):
    dbFields = dbClient.getFields()
    for fieldName, field in fields.items():
        if fieldName in dbFields:
            continue
        dbClient.setField(fieldName=fieldName, value=field)
        print(fieldName)
        #dbClient.setField(fieldName, field)

# Run the script and print the results
if __name__ == "__main__":
    #field_details = scrape_field_details()
    #save_to_csv(field_details)
    #jsonHelper.save_to_json(field_details)
    #field_details = jsonHelper.load_from_json('./data/fields/fields.json')
    #new_field_details = addCoordinates(field_details)
    #jsonHelper.save_to_file(new_field_details, "./data/fields/newFields.json")
    field = update_field_address_details(tenantKey='IL#handball#2025-26', fieldTitle='מאירי- פ״ת')
    print(field)
    exit(0)


    new_field_details = jsonHelper.load_from_file("./data/fields/newFields.json")
    new_field_details = addCoordinates(new_field_details)
    dbClient:DbClientBase = DynamodbClient(env=os.getenv('app_env'), logger=logging, awsRegion=os.getenv('awsRegion'), endpointUrl=os.getenv('dynamoDbEndpointUrl'))
    addNewFields(new_field_details, dbClient)
    pass
    for field in new_field_details:
        print(field)
