import json
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
#from dependency_injector import containers, providers
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import asyncio
import json
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
# Add the rpService directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.handleUsers import HandleUsers
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from shared.dockerClient import DockerClient
from shared.db import RedisClient
from shared.messaging import MessagingService
from shared.logger import Logger
import shared.jsonHelper as jsonHelper

class RefPortalDashboard():
    def __init__(self):
        # Configure logging
        self.logger = Logger()

        self.dbClient = RedisClient(os.getenv('app_env'), self.logger, os.getenv('redisHost'), int(os.getenv('redisPort')), int(os.getenv('redisDb')))
        
        self.messagingService = MessagingService(self.logger, self.dbClient)
        
        self.handleUsers = HandleUsers(self.logger, self.dbClient)
        self.handleTournaments = HandleTournaments(self.logger, self.dbClient)
        self.handleRefereeData = HandleRefereeData(self.logger, self.dbClient)
        self.dockerClient = DockerClient(self.logger)

        self.dataFile = f'{os.getenv("MY_DATA_FOLDER", "/run/data/")}summary/fruits.json'

    async def start(self):
        # Initialize the animation with a 5-second interval
        fig = plt.figure()

        while (True):
            ani = animation.FuncAnimation(fig, self.updateChart, interval=5000)

            # Show the chart
            plt.show()
            await asyncio.sleep(5)
        
    def updateChart(self, i):
        """Updates the bar chart with new JSON data."""
        plt.clf()  # Clear the previous chart
        data = jsonHelper.load_from_file(self.dataFile)

        if data:
            categories = list(data.keys())
            values = list(data.values())

            plt.bar(categories, values, color='skyblue')
            plt.xlabel("Categories")
            plt.ylabel("Values")
            plt.title("Live Updating Bar Chart")
            plt.xticks(rotation=45)
            plt.ylim(0, max(values) + 5)  # Dynamic Y-axis scaling


if __name__ == '__main__':
    refPortalDashboard = RefPortalDashboard()
    asyncio.run(refPortalDashboard.start())