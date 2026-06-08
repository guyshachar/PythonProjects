import json
import asyncio
import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db import RedisClient
from shared.db import DynamodbClient

env=os.getenv('app_env')

logFormat = f'%(asctime)s - %(name)s - %(levelname)s - %(message)s'
formatter = logging.Formatter(logFormat)
logging.basicConfig(level=logging.INFO, format=logFormat)
logger = logging

redisClient = RedisClient(env=env, logger=logger, host=os.getenv('redisHost'), port=os.getenv('redisPort'), db=os.getenv('redisDb'))
awsDynamodbClientLocal = DynamodbClient(env='stage', logger=logger, awsRegion=os.getenv('awsRegion'))
awsDynamodbClientStage = DynamodbClient(env='prod', logger=logger, awsRegion=os.getenv('awsRegion'))

def truncateAll(dynamodbClient, env):
    #dynamodbClient.truncate('rules')
    for tableName in dynamodbClient.tables:
        if tableName != 'referees_prod':
            continue
        dynamodbClient.truncate(tableName[:-len(env)-1])

def copy(dynamodbClientFrom, dynamodbClientTo):
    for tableName in dynamodbClientFrom.tables:
        tableName = tableName[:-len(env)-1]
        if tableName != 'referees':
            continue
        items = dynamodbClientFrom.getDict(tableName)
        for key, value in items.items():
            dynamodbClientTo.set(tableName, value)

def convert(dynamodbClient):
    try:
        rules = redisClient.getRules()
        cnt=len(rules)
        for key, value in rules.items():
            dynamodbClient.setRule(key, value)

        fields = redisClient.getFields()
        cnt=len(fields)
        for key, value in fields.items():
            dynamodbClient.setField(key, value)

        sections = redisClient.getSections()
        cnt=len(sections)
        for key, value in sections.items():
            dynamodbClient.setSection(key, value)

        referees = redisClient.getRefereeProperties()
        cnt=len(referees)
        for key, value in referees.items():
            refId = key.split(':')[1]
            prop = key.split(':')[3]
            dynamodbClient.setRefereeProperty(refId, prop, value)

        referees = redisClient.getRefereeGames()
        cnt=len(referees)
        for key, value in referees.items():
            refId = key.split(':')[1]
            gamePk = key.split(':')[3]
            dynamodbClient.setRefereeGame(refId, gamePk, value)

        referees = redisClient.getDict('referees:*:gamesArchived')
        cnt=len(referees)
        for key, value in referees.items():
            refId = key.split(':')[1]
            gamePk = key.split(':')[3]
            dynamodbClient.set('refereeGamesArchived', value, refId, gamePk)

        referees = redisClient.getDict('referees:*:gamesRemoved')
        cnt=len(referees)
        for key, value in referees.items():
            refId = key.split(':')[1]
            gamePk = key.split(':')[3]
            dynamodbClient.set('refereeGamesRemoved', value, refId, gamePk)

        referees = redisClient.getRefereeMessages()
        cnt=len(referees)
        for key, value in referees.items():
            refId = key.split(':')[1]
            msgSid = key.split(':')[3]
            dynamodbClient.setRefereeMessage(refId, msgSid, value)

        referees = redisClient.getRefereeTemplates()
        cnt=len(referees)
        for key, value in referees.items():
            refId = key.split(':')[1]
            msgSid = key.split(':')[3]
            dynamodbClient.setRefereeTemplate(refId, msgSid, value)

        referees = redisClient.getRefereeReviews()
        cnt=len(referees)
        for key, value in referees.items():
            refId = key.split(':')[1]
            gamePk = key.split(':')[3]
            dynamodbClient.setRefereeReview(refId, gamePk, value)

        tournaments = redisClient.getTournaments()
        cnt=len(tournaments)
        for key, value in tournaments.items():
            dynamodbClient.setTournament(key, value)

        for tournamentName in tournaments:
            table = redisClient.getLeagueTable(tournamentName)
            if table is None:
                continue
            cnt=len(table)
            dynamodbClient.setLeagueTable(tournamentName, table)

            games = redisClient.getTournamentGames(tournamentName)
            cnt=len(games)
            for key, value in games.items():
                 dynamodbClient.setTournamentGame(tournamentName, key, value)

            games = redisClient.getDict(f'games:{tournamentName}:archived')
            cnt=len(games)
            for key, value in games.items():
                dynamodbClient.set('tournamentGamesArchived', value, tournamentName, key)

            games = redisClient.getDict(f'games:{tournamentName}:history:*')
            games = {}
            cnt=len(games)
            for key, value in games.items():
                gamePk = key.split(':')[3]
                dynamodbClient.set('tournamentGamesHistory', value, tournamentName, gamePk)

    except Exception as ex:
        logger.error('convert', ex)

if __name__ == '__main__':
    #recreateTablesLocally(awsDynamodbClient.dynamodbClient, '', '_prod')
    truncateAll(awsDynamodbClientStage, 'prod')
    copy(awsDynamodbClientLocal, awsDynamodbClientStage)
    #convert(awsDynamodbClientLocal)
    pass