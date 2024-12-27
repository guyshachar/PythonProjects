from playwright.sync_api import sync_playwright
import csv
import json
import urllib.parse
import requests
import helpers

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
            wazeLink, formattedAddress = helpers.get_accurate_waze_link(f'{details["address"]}, ישראל')
            details["wazeLink"] = wazeLink
            details["formattedAddress"] = formattedAddress
            details["wazeLink2"] = helpers.get_waze_link(f'{details["address"]}, ישראל')
            fields.append(details)

        # Close the browser
        browser.close()

        return fields

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
    for fieldName in fields:
        field = fields[fieldName]
        wazeLink = field["wazeLink"]
        pos1 = wazeLink.find("=")
        pos2 = wazeLink.find(",")
        pos3 = wazeLink.find("&")
       #https://www.waze.com/ul?ll=31.807275,35.10271&navigate=yes
        lat = float(wazeLink[pos1+1:pos2])
        lng = float(wazeLink[pos2+1:pos3])
        field["addressDetails"]["wazeLink"] = field['wazeLink']
        del field["wazeLink"]
        del field["wazeLink2"]
    return fields

# Run the script and print the results
if __name__ == "__main__":
    #field_details = scrape_field_details()
    #save_to_csv(field_details)
    #save_to_json(field_details)
    field_details = helpers.load_from_json('./data/fields/fields.json')
    new_field_details = addCoordinates(field_details)
    helpers.save_to_json(new_field_details, "./data/fields/newFields.json")
    for field in field_details:
        print(field)
