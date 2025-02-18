import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta
import os
import uuid
import sys
from pathlib import Path
import socket
import shutil
import asyncio
import shared.helpers as helpers

class HandleRefereeData():
    def __init__(self, logger):
        # Configure logging
        '''
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        '''
        self.logger = logger
        self.fileVersion = os.environ.get('fileVersion') or 'v'

        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            "games" : {
                'title': 'שיבוצים',
                'generate': self.generateGameDetails
           },
            "reviews": {
                'title': 'ביקורות',
                'generate': self.generateReviewDetails,
            }
        }

    def getRefereeFilePath(self, objType, refId):
        try:
            referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/{objType}/'
            referee_file_path = f'{referee_file_path}refId{refId}_{self.fileVersion}'

            return referee_file_path
        except Exception as ex:
            pass

    async def readRefereeDataFile(self, objType, refereeData):
        if objType not in refereeData or 'currentList' not in refereeData[objType] or not refereeData[objType]['currentList']:
            file_datetime = None
            
            try:
                referee_file_path = f'{self.getRefereeFilePath(objType, refereeData["refId"])}.json'
                self.logger.debug(f'file: {referee_file_path}')
                if objType not in refereeData:
                    refereeData[objType] = {}
                t=0
                while not os.path.exists(referee_file_path) and t < 5:
                    await asyncio.sleep(150 * (t + 1) / 1000)
                    t += 1

                if os.path.exists(referee_file_path):
                    file_datetime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
                    refereeData[objType]['currentList'] = helpers.load_from_file(referee_file_path)
                else:
                    file_datetime = datetime.now()
                    refereeData[objType]['currentList'] = {}
                refereeData[objType]['fileDateTime'] = helpers.datetime_to_str(file_datetime)
            except Exception as ex:
                helpers.logError(self.logger, f'readRefereeDataFile', ex)

    async def writeRefereeDataFile(self, objType, refereeData):
        try:
            prevListText = helpers.save_to_json(refereeData[objType]['prevList'])
            currentListText = helpers.save_to_json(refereeData[objType]['currentList'])
            pref_referee_file_path = self.getRefereeFilePath(objType, refereeData['refId'])
            referee_file_path = f'{pref_referee_file_path}.json' 
            dir = os.path.dirname(referee_file_path)
            self.logger.debug(f'file: {dir} {referee_file_path}')
            if dir and not os.path.exists(dir):
                self.logger.debug(f'create dir: {dir}')
                os.makedirs(dir)
            fileExists = os.path.exists(referee_file_path)
            if prevListText != currentListText or not fileExists:
                self.logger.debug(f'prev:{prevListText}')
                self.logger.debug(f'current:{currentListText}')
                if fileExists:
                    fileDateTime = helpers.datetime_to_str(datetime.fromtimestamp(os.path.getmtime(referee_file_path)))
                    shutil.copy(referee_file_path, f'{pref_referee_file_path}_{fileDateTime}.json')
                helpers.save_to_file(refereeData[objType]['currentList'], referee_file_path)
                refereeData[objType]['fileDateTime'] = helpers.datetime_to_str(datetime.now())
        except Exception as ex:
            self.logError(f'writeFileText', ex)

    def generateGameRefereeDetails(self, currentGame, job): 
        currentJobProp = currentGame.get('nested').get(job)

        if currentJobProp:
            details = f'\n{job}'
            details += self.objProperty(currentJobProp, '* שם')
            details += self.objProperty(currentJobProp, '* סטטוס')
            details += self.objProperty(currentJobProp, '* דרג')
            details += self.objProperty(currentJobProp, '* טלפון')
            details += self.objProperty(currentJobProp, '* כתובת')
            return details
        else:
            return ''

    def generateGameReferees(self, game):
        details = ''
        details += self.generateGameRefereeDetails(game, 'שופט ראשי')
        details += self.generateGameRefereeDetails(game, 'שופט ראשי*')
        details += self.generateGameRefereeDetails(game, 'ע. שופט 1')
        details += self.generateGameRefereeDetails(game, 'ע. שופט 2')
        details += self.generateGameRefereeDetails(game, 'שופט רביעי')
        details += self.generateGameRefereeDetails(game, 'שופט מזכירות')
        details += self.generateGameRefereeDetails(game, 'שופט ראשון')
        details += self.generateGameRefereeDetails(game, 'שופט שני')
        details += self.generateGameRefereeDetails(game, 'מבקר')
        return details
        
    def generateGameDetails(self, game, shortResponse=False):
        details = ''
        details += self.objProperty(game, 'תאריך', False)
        details += self.objProperty(game, 'יום')
        details += self.objProperty(game, 'מסגרת משחקים')
        details += self.objProperty(game, 'משחק')
        details += self.objProperty(game, 'סבב')
        details += self.objProperty(game, 'מחזור')
        details += self.objProperty(game, 'מגרש')
        details += self.objProperty(game, 'סטטוס')
        if shortResponse == False:
            details += '\n'
            details += self.generateGameReferees(game)
        return details

    def generateReviewDetails(self, game, shortResponse=False):
        details = ''
        details += self.objProperty(game, 'מס.', False)
        details += self.objProperty(game, 'תאריך')
        details += self.objProperty(game, 'שעה')
        details += self.objProperty(game, 'מסגרת משחקים')
        details += self.objProperty(game, 'משחק')
        details += self.objProperty(game, 'מגרש')
        details += self.objProperty(game, 'מחזור')
        details += self.objProperty(game, 'תפקיד במגרש')
        details += self.objProperty(game, 'מבקר')
        details += self.objProperty(game, 'ציון')
        return details

    def objProperty(self, obj, property, cr=True):
        if obj.get(property):
            text = ''
            if cr:
                text = '\n'
            text = f'{text}{property}: {obj.get(property)}'
            return text
        return ''
    
    async def getDataByRefId(self, refId, objType, shortResponse=False):
        try:
            self.logger.info(f'getDataByRefId refId: {refId} objType: {objType} shortResponse: {shortResponse}')
            refereeData = { 'refId': refId, objType: {} }
            await self.readRefereeDataFile(objType, refereeData)
            data = f"רשימת {self.dataDic[objType]['title']}:"
            if len(refereeData[objType]['currentList']) == 0:
                data = f'{data}\nריקה'
            
            for pk in refereeData[objType]['currentList']:
                self.logger.debug(f'pk={pk}')
                item = refereeData[objType]['currentList'][pk]
                itemDesc = self.dataDic[objType]['generate'](item, shortResponse)
                data = f'{data}\n{itemDesc}'

            return data
        except Exception as ex:
            helpers.logError(self.logger, 'getDataByRefId', ex)
            return 'ארעה שגיאה'
