# -*- coding: utf-8 -*-
#!/usr/bin/python

import random
import math
import requests
import json
import time
import os.path
import logging

class RedAlert():

    def __init__(self):
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

        # initialize locations list
        self.locations = self.get_locations_list()
        # cookies
        self.cookies = ""
        # initialize user agent for web requests
        self.headers = {
           "Host":"www.oref.org.il",
           "Connection":"keep-alive",
           "Content-Type":"application/json",
           "charset":"utf-8",
           "X-Requested-With":"XMLHttpRequest",
           "sec-ch-ua-mobile":"?0",
           "User-Agent":"",
           "sec-ch-ua-platform":"macOS",
           "Accept":"*/*",
           "sec-ch-ua": '".Not/A)Brand"v="99", "Google Chrome";v="103", "Chromium";v="103"',
           "Sec-Fetch-Site":"same-origin",
           "Sec-Fetch-Mode":"cors",
           "Sec-Fetch-Dest":"empty",
           "Referer":"https://www.oref.org.il/12481-he/Pakar.aspx",
           "Accept-Encoding":"gzip, deflate, br",
           "Accept-Language":"en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        }
        # intiiate cokies
        self.get_cookies()

    def get_cookies(self):
        HOST = "https://www.oref.org.il/"
        r = requests.get(HOST,headers=self.headers)
        self.cookies = r.cookies

    def get_coordinates(self, location_name):

        #This function will get city coordinates by given city name
        #so later on it will be possible to visualization the flying rocket to the city
        HOST = "https://maps.google.com/maps/api/geocode/json?address=%s" % location_name
        r = requests.get(HOST, headers=self.headers)
        j = json.loads(r.content)
        return j["results"][0]["geometry"]["location"]

    def random_coordinates(self, latitude, longitude):

        # get random coordinates within the city for random visualization
        # radius of the circle
        circle_r = 1
        # center of the circle (x, y)
        circle_x = latitude
        circle_y = longitude
        # random angle
        alpha = 2 * math.pi * random.random()
        # random radius
        r = circle_r * random.random()
        # calculating coordinates
        x = r * math.cos(alpha) + circle_x
        y = r * math.sin(alpha) + circle_y
        
        return {"latitude":x,"longitude":y}

    def count_alerts(self, alerts_data):
        # this function literally return how many alerts there are currently
        return len(alerts_data)

    def get_locations_list(self):

        '''
        This function is to build a locations list of cities and the time they have
        before the rocket hit the fan. for better parsing later
        '''

        # Get the absolute path of the current script file.
        script_file_path = os.path.abspath(__file__)
        # Get the directory path of the current script file.
        script_dir_path = os.path.dirname(script_file_path)
        # Get the full path to the file you want to open.
        target_file_path = os.path.join(script_dir_path, "targets.json")

        f = open(target_file_path, encoding='utf-8')
        # returns JSON object as 
        j = json.load(f)

        locations = {}
        for i in j:
            val = j[i]
            locations[val["label"]] = val

        return locations

    def get_red_alerts(self):

        # get red alerts
        HOST = "https://www.oref.org.il/WarningMessages/alert/alerts.json"
        r = requests.get(HOST, headers=self.headers, cookies=self.cookies)
        alerts = r.content.decode("UTF-8").replace("\n","").replace("\r","")
        n = len(alerts)
        if(len(alerts) <= 1):
            return None
        # parse the json response
        j = json.loads(r.content)
        # check if there is no alerts - if so, return null.
        if(len(j["data"]) == 0):
            return None
        self.logger.info(f'alerts={alerts}, json={j}')
        # initialize the current timestamp to know when the rocket alert started
        j["timestamp"] = time.time()
        # parse data
        return j

    def run(self):

        # initalize the red alert object
        alert = self
        # check for alerts all the time and do stuff, never stop.
        # set empty alert data dict
        alert_data = {}
        city_data = []
        migun_time = 9999
        # get alerts from pikud ha-oref website
        red_alerts = self.get_red_alerts()
        #red_alerts =  {'id': '133434828810000000', 'cat': '1', 'title': 'ירי רקטות וטילים', 'data': ['סופה'], 'desc': 'היכנסו למרחב המוגן ושהו בו 10 דקות', 'timestamp': 1699009288.333312}
        # if there is red alerts right now, get into action, quickly!
        if (red_alerts != None):
            if (self.logger):
                self.logger.debug(red_alerts)
            # loop through each city there is red alert currently
            for alert_city in red_alerts["data"]:
                # get unique alert id for the current looping alerts
                alert_id = red_alerts["id"]
                # get the data of the current alert code
                cityLocation = self.locations[alert_city]
                if cityLocation["migun_time"] < migun_time:
                    migun_time = cityLocation["migun_time"]
                # set the timestamp of the current alert
                city_data.append(cityLocation)

                # get the coordinates of the city where the rocket is flying to
                '''
                # Google Maps requires API key #
                '''
                #alert_data["coordinates"] = alert.get_coordinates(location_name=alert_city)
                # random coordinates where the rocket should fly to in the visualization map
                #alert_data["random_coordinates"] = alert.random_coordinates(latitude=alert_data["coordinates"]["lat"],longitude=alert_data["coordinates"]["lng"])
                
            red_alerts["cities_labels"] = city_data
            red_alerts["time_to_run"] = migun_time

            '''
            In this block you do what you have to do with your code,
            now when you have all what you could possibly have including:
            alert id, alert city, time to run away, coordinates of city,
            random coordinates where the missle may land and timestamp when the missle started fireup.
            '''

            return red_alerts 
        else:
            return None

if __name__ == "__main__":
    print("Helllllo")
    redAlert = RedAlert()
    #asyncio.run(app.start())
    redAlert.run()
