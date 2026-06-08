import logging
from typing import Any, Optional
from collections.abc import Mapping
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo
import os
import uuid
import sys
import re
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext, Browser, Page
from playwright_stealth import Stealth
import asyncio
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.handleUsers import HandleUsers
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from shared.orgRelated import OrgServiceBase
from shared.db import CacheService
from shared.messaging import MessagingService
from shared.commonHelper import CommonHelper
from shared.logger import Logger
from shared.orgRelated import OrgServiceFactory, MultiTenantSupport
from shared.commute_service import CommuteService

class RefereeProcessService():
    def __init__(
        self,
        logger: Logger,
        commonHelper: CommonHelper,
        cacheService: CacheService,
        multiTenantSupport: MultiTenantSupport,
        messagingService: MessagingService,
        handleTournaments: HandleTournaments,
        handleRefereeData: HandleRefereeData,
        handleUsers: HandleUsers,
        referees_data: tuple,
        orgServiceFactory: OrgServiceFactory,
        commuteService: Optional[CommuteService] = None,
        config: Any = None,
    ):
        self.logger = logger
        self.commonHelper = commonHelper
        self.cacheService = cacheService
        self.multiTenantSupport = multiTenantSupport
        self.messagingService = messagingService
        self.handleTournaments = handleTournaments
        self.handleRefereeData = handleRefereeData
        self.handleUsers = handleUsers
        (self.globalRefereesByMobile, self.refereesByRefId, self.refereesByMobile, self.refereesByGuid, self.globalRefereesByName) = referees_data
        self.orgServiceFactory = orgServiceFactory
        self.commuteService = commuteService
        if config is None:
            self.config = {}
        elif isinstance(config, dict):
            self.config = config
        elif isinstance(config, Mapping):
            self.config = dict(config)
        else:
            self.config = {}
        
        self.logger.sendMessage = self.messagingService.greenApiSendMessage

        self.app = os.getenv('app')

        self.tenantsOrgServices:dict[str, OrgServiceBase] = {}
        for tenantKey, tenant in self.cacheService.getTenants().items():
            orgService = self.orgServiceFactory.get_org_service_by_tenant(tenantKey=tenantKey)
            self.tenantsOrgServices[tenantKey] = orgService
        self.generateReports = eval(os.getenv('generateReports', 'False'))
        self.mainInstance = eval(os.getenv('mainInstance', 'False'))

        self.concurrentPages = int(os.getenv('concurrentPages', '4'))
        self.checkGames = eval(os.getenv('checkGames', 'True'))
        self.checkReviews = eval(os.getenv('checkReviews', 'True'))
        self.daysToArchive = int(os.getenv('daysToArchive') or '1')

        self.apiServiceUrlBase = os.getenv('apiServiceUrlBase')
        self.approveGames = eval(os.getenv('approveGames', 'False'))
        self.avoidChatGroups = eval(os.getenv('avoidChatGroups', 'True'))
        self.chatGroups4Singles = eval(os.getenv('chatGroups4Singles', 'False'))

        self.swLevel = os.getenv('swLevel') or 'debug'
        self.season = os.getenv('season')
        
        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            "games" : {
                "url": "https://ref.football.org.il/referee/home",
                "processTemplates": self.processTemplates,
                'postParse': self.postParseGames,
                'compare': self.compareItems,
                'generate': self.commonHelper.generateGameDetails,
                'handleNotifications': self.handleNotifications,
                'postCompare': self.postCompare,
                "tags" : [ 'תאריך', "יום", "מסגרת משחקים", "משחק", "סבב", "מחזור", "מגרש", "סטטוס" ],
                "initTag" : 'תאריך',
                "refereesTags": [ "תפקיד", "* שם", "* סטטוס", "* דרג", "* טלפון", "* כתובת" ],
                "pkrefereesTags": "תפקיד",
                "initrefereesTag" : 'תפקיד',
                "סטטוסTag": { "name": "סטטוס", "dic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")] },
                "* שםTag": { "name": "* סטטוס", "dic": [('class="approved"', "מאשר"), ('class="reject"', "לא מאשר"), ('', "טרם אושר")] },
                'removeFilter': 'תאריך',
            },
            "gamesReports" : {
                "tags" : [ 'תאריך', "מסגרת משחקים", "מח.", "מגרש", "סטטוס", "קבוצה ביתית קבוצה אורחת" ],
                "initTag" : 'תאריך',
                "סטטוסTag": { "name": "סטטוס", "dic": [("new_report.svg", "מחכה לעדכון"), ("new_report2.svg", " בעדכון")] },
            },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                'postParse': self.postParseReviews,
                'processTemplates': self.processTemplates,
                'compare': self.compareItems,
                'generate': self.commonHelper.generateReviewDetails,
                'postCompare': self.postCompare,
                'handleNotifications': self.handleNotifications,
                "tags" : [ "מס.", 'תאריך', "שעה", "מסגרת משחקים", "משחק", "מגרש", "מחזור", "תפקיד במגרש", "מבקר", "ציון" ],
                "initTag" : "מס.",
                "excludeCompareTags" : [ "מס." ],
            }
        }

        self.logger.info(f'refereeProcessService starts... process time per referee={os.getenv("processTimeout", "30")}')

    async def startProcessByMobileNos(self, mobileNos:list):
        activeTenantKeys = [ tenantKey for tenantKey, tenant in self.cacheService.getTenants().items() if tenant.get('active') == True ]
        anyChangeResult = False
        for tenantKey in activeTenantKeys:
            referees = { mobileNo: self.handleRefereeData.activeRefereesByMobile[mobileNo] for mobileNo in mobileNos if tenantKey in self.handleRefereeData.activeRefereesByMobile[mobileNo].get('activeTenantKeys', [])}
            anyChange = await self.startProcessByReferees(tenantKey=tenantKey, referees=referees)
            if anyChange:
                anyChangeResult = True
        return anyChangeResult
    
    async def startProcessByReferees(self, tenantKey:str, referees:dict):
        anyChange = False

        try:
            self.processTimeout = int(os.getenv('processTimeout') or '30') * len(referees)
            for refId in referees:
                if eval(os.getenv('generateReports', 'False')):
                    await self.handleRefereeData.collectGamesSummary(tenantKey=tenantKey, refId=refId)
                    await self.handleRefereeData.getGamesEvents(tenantKey=tenantKey, refId=refId)

            try:
                if referees:
                    helpers.stopwatchStart(f'Process time')
                    async with async_playwright() as p:
                        # Launch the browser with all necessary parameters
                        self.logger.info("Launching browser...") 
                        browser = await OrgServiceBase.launchBrowser(p, headless=eval(os.getenv('browserHeadless') or 'True'))
                        context = await OrgServiceBase.createContext(browser=browser)
                        stealth = Stealth()
                        await stealth.apply_stealth_async(context)
                        if os.getenv('tracing', 'False') == 'True':
                            helpers.initTracing(p)
                        refereesTasks = { asyncio.create_task(self.startProcessByMobileNo(tenantKey=tenantKey, mobileNo=mobileNo, context=context)) : mobileNo for mobileNo in referees }
                        self.logger.debug(f'before tasks gather')
                        tasksResults = await asyncio.gather(*refereesTasks, return_exceptions=True)
                        self.logger.debug(f'after tasks gather')
                        for taskResult in tasksResults:
                            if taskResult:
                                anyChange = True
                                break
                        await browser.close()
                        helpers.stopwatchStop(f'Process time', level=self.swLevel)
                        self.logger.info(f'#processed referees={len(referees)}')

            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError as ex:
                self.logger.error('Start Process', ex)
            except Exception as ex:
                self.logger.error('Start Process', ex)

        except Exception as ex:
            self.logger.error(f'Start Process', ex)

        finally:
            pass

        return anyChange

    async def startProcessByMobileNo(self, tenantKey, mobileNo, context:BrowserContext):
        anyChange = False
        refereeTask = None
        try:
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            if refereeDetail.get('status') != 'active':
                self.logger.warning(f'Referee {mobileNo} not found in active referees')
                return False
            assigner = 'assigner' in refereeDetail.get('roles', [])
            refereeTask = asyncio.create_task(self.checkRefereeTask(tenantKey=tenantKey, mobileNo=mobileNo, context=context))
            timeout = self.processTimeout if not assigner else None 
            done, pending = await asyncio.wait([refereeTask], timeout=timeout)
            for task in pending:
                self.logger.warning(f'Referee process task {mobileNo} is stuck! Cancelling...')
                try:
                    task.cancel()
                except Exception as ex:
                    pass
            tasksResults = await asyncio.gather(*done, return_exceptions=True)
            for taskResult in tasksResults:
                if taskResult:
                    anyChange = True
                    break

            return anyChange

        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError as ex:
            self.logger.error('Start Process', ex)
        except Exception as ex:
            self.logger.error('Start Process', ex)
        finally:
            try:
                await refereeTask
            except asyncio.CancelledError:
                pass

    async def checkRefereeTask(self, tenantKey, mobileNo, context:BrowserContext):
        swName = f'Referee mobileNo={mobileNo} task time'
        helpers.stopwatchStart(swName)
        page:Page = None
        try:
            tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
            self.logger.debug(f'start of CheckRefereeTask#1-{self.app}', **tenantRefereeDetail)
            
            anyChange = False
            self.logger.debug(f'seq={tenantRefereeDetail.get("seq")}', **tenantRefereeDetail)
        
            testResult = helpers.testConnection(self.tenantsOrgServices[tenantKey].baseUrl, 443)
            if testResult:
                self.logger.warning(f'TestConnection: {testResult}')

            windowIsOpen = self.messagingService.checkIf24HoursWindowIsOpen(mobileNo=mobileNo)
            refereeData = { 'mobileNo': mobileNo, 'divertMobileNo': tenantRefereeDetail.get('divertMobileNo'), 'refId': tenantRefereeDetail['refId'], 'name': globalRefereeDetail['name'], 'byGameId': {}, 'windowIsOpen': windowIsOpen, 'loggedIn': False}
            self.tenantsOrgServices[tenantKey].setFetchDates(refereeData=refereeData)
            
            page = await context.new_page()
            if not tenant.get('assignerCollection') or 'assigner' in tenantRefereeDetail.get('roles', []):
                loginResult, loginMessage = await self.tenantsOrgServices[tenantKey].login(refereeDetail=tenantRefereeDetail | globalRefereeDetail, page=page)
                self.logger.debug(f'after login = {loginResult}', **globalRefereeDetail)
                if loginResult == False:
                    message = f'שלום {mobileNo} {globalRefereeDetail["name"]}, {loginMessage}'
                    loginFails = int(self.cacheService.getCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginFails', onlyCache=True) or '0')
                    self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginFails', value=loginFails + 1 ,onlyCache=True)
                    if loginFails >= 5:
                        self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginOnHold', value=helpers.localNow(), onlyCache=True, ttlSeconds=15*60)
                        self.logger.error(f'Login failed, RefId={tenantRefereeDetail["refId"]}, loginFails={loginFails + 1}', None, **tenantRefereeDetail)

                        if loginMessage == 'Login failed':
                            statusAfterFailedLogin = tenant.get('statusAfterFailedLogin', 'suspended')
                            self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='status', value=statusAfterFailedLogin)
                            self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='statusChangedDate', value=helpers.localNow())
                            if statusAfterFailedLogin != 'active':
                                message += f', יש לעדכן את הסיסמא (לאחר בדיקה בפורטל) ולעדכן באמצעות הקישור הבא:\nhttps://refereex.com/changePassword'
                            toMobileNo = tenantRefereeDetail.get('divertMobileNo') or mobileNo
                            allowMessageSending = self.messagingService.allowMessageSending(to=toMobileNo)
                            if allowMessageSending:
                                msgSid = await self.messagingService.sendMessage(to=list(set([toMobileNo, self.messagingService.adminMobile])), message=message, title='התחברות נכשלה')

                    return
                else:
                    self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginFails', value=0 ,onlyCache=True)
                
                refereeData['loggedIn'] = True

            if False:
                await self.tenantsOrgServices[tenantKey].getPayments(refereeDetail=tenantRefereeDetail, page=page)
            for objType in tenant.get('objTypes', []):
                if objType == 'games' and self.checkGames or objType == 'reviews' and self.checkReviews:
                    refereeData['byGameId'][objType] = {}
                    changed = await self.checkRefereeData(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                    if changed:
                        anyChange = True
                        if objType == 'games':
                            if self.generateReports:
                                await self.handleRefereeData.collectGamesSummary(tenantKey=tenantKey, refId=mobileNo)
                                await self.handleRefereeData.getGamesEvents(tenantKey=tenantKey, refId=mobileNo)
            
            self.logger.debug(f'end of CheckRefereeTask#1-{self.app}', **tenantRefereeDetail)

        except asyncio.CancelledError as ex:
            self.logger.warning(f"checkRefereeTrask {mobileNo} received cancellation request.")
            raise  # Reraise to propagate cancellation
        except Exception as ex:
            self.logger.error(f'CheckRefereeTask mobileNo={mobileNo}', ex, **tenantRefereeDetail)

        finally:
            if page:
                await page.close()
                page = None

        helpers.stopwatchStop(swName, level=self.swLevel)
        return anyChange

    async def checkRefereeData(self, tenantKey, objType, refereeData, page):
        mobileNo = refereeData['mobileNo']
        tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        refId = refereeData['refId']
        
        changed = False
        try:
            self.logger.info(f'Checking {objType}...', **tenantRefereeDetail)
            
            swName = f'checkRefereeData={refereeData["name"]}{objType}'
            helpers.stopwatchStart(swName)

            # get prevList
            await self.handleRefereeData.getRefereeData(tenantKey=tenantKey, objType=objType, refereeData=refereeData)

            found = False
            cnt = 0
            if 'assigner' in tenantRefereeDetail.get('roles', []):
                if os.getenv('skipCollectItemsForAssigner', 'False') == 'False':
                    await self.tenantsOrgServices[tenantKey].collectItemsForAssigner(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)

            getListSuccessful = await self.tenantsOrgServices[tenantKey].getListForReferee(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
            if getListSuccessful == False:
                return False
            sw1 = helpers.stopwatchStop(swName)
            
            updatedList = refereeData[objType]['currentList']

            if updatedList and len(updatedList) > 0:
                found = True
                cnt = len(updatedList)
                self.logger.debug(f'parse objType={objType} found={found} updatedList={cnt}', **tenantRefereeDetail)
            else:
                self.logger.info(f"{objType} no results found", **tenantRefereeDetail)

            # copy additional properties from prev to current
            if len(refereeData[objType].get('prevList', {})) > 0:
                for pk, item in (refereeData[objType].get('currentList', {}) or {}).items():
                    prevItem = refereeData[objType]['prevList'].get(pk)
                    if prevItem:
                        for key in prevItem:
                            if key not in item:
                                prevItemJson = jsonHelper.save_to_json(prevItem[key])
                                item[key] = jsonHelper.load_from_json(prevItemJson)
                if objType == 'games':
                    for pk, prevItem in refereeData[objType]['prevList'].items():
                        prevItem['gameDetail'] = self.cacheService.getGameDetail(tenantKey=tenantKey, game=prevItem)
                        pass
            sw2 = helpers.stopwatchStop(swName)
            if updatedList != None:
                if self.dataDic[objType].get('postParse'):
                    await self.dataDic[objType]['postParse'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                
                sw3 = helpers.stopwatchStop(swName)
                if self.dataDic[objType].get('compare'):
                    await self.dataDic[objType]['compare'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                    sw4 = helpers.stopwatchStop(swName)

                    now = helpers.localNow()
                    abortRun = False
                    anyRemovals = len(refereeData[objType]['removed']) >= int(tenant.get('minimumRemovalsToIgnore', '1')) or objType == 'reviews' and cnt == len(refereeData[objType]['removed'])
                    if anyRemovals:
                        blockRemovalsStarted = self.cacheService.getCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovalsStarted_{objType}', onlyCache=True)
                        skipAbortRun = self.cacheService.getCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'skipAbortRun_{objType}', onlyCache=True)
                        if blockRemovalsStarted and now - blockRemovalsStarted > timedelta(seconds=30*60) or skipAbortRun and skipAbortRun == 'yes':
                            self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovalsStarted_{objType}', value=None, onlyCache=True, ttlSeconds=1)

                        elif blockRemovalsStarted:
                            abortRun = True
                        
                        else:
                            abortRun = True
                            self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovalsStarted_{objType}', value=now, onlyCache=True)

                            customData = {
                                'action': 'skipAbortRun',
                                'tenantKey': tenantKey,
                                'mobileNo': refereeData['mobileNo'],
                                'objType': objType
                            }
                            promptButtons = [
                                {
                                    "sub_type": "quick_reply",
                                    "id": "skipAbortRun_yes",
                                    "text": "כן, להמשיך במחיקה"
                                },
                                {
                                    "sub_type": "quick_reply",
                                    "id": "skipAbortRun_no",
                                    "text": "לא, לחכות לבדיקה שלי"
                                },
                            ]
                            removedText = ''
                            for prevItemPk in refereeData[objType]['removed']:
                                prevItem = refereeData[objType]['prevList'][prevItemPk]
                                removedText += f'\n{prevItem.get('gameDate')} {prevItem.get('gameTime')}'
                            self.messagingService.sendInteractiveMessage(to=self.messagingService.adminMobile, question=f'לשופט {refereeData["name"]} {mobileNo} קוד {refId} יש {len(refereeData[objType]['removed'])} מחיקות {removedText},\nהאם להמשיך במחיקה ?', promptButtons=promptButtons, customData=customData)
                            self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'skipAbortRun_{objType}', onlyCache=True, value='no', ttlSeconds=30*60)
                            self.logger.warning(f'something happened with {refId} total removals={len(refereeData[objType]['removed'])}')

                    else:
                        self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovals_{objType}', value=now, onlyCache=True, ttlSeconds=1)
                                                
                    if abortRun:
                        return False

                    changed = len(refereeData[objType]['added']) > 0 or len(refereeData[objType]['removed']) > 0 or len(refereeData[objType]['changed']) > 0 or len(refereeData[objType]['archived']) > 0
                    if True or changed:
                        self.logger.info(f"{objType} A:{len(refereeData[objType]['added'])} R:{len(refereeData[objType]['removed'])} C:{len(refereeData[objType]['changed'])} H:{len(refereeData[objType]['archived'])} I:{cnt}", **tenantRefereeDetail)
                        await self.dataDic[objType]['postCompare'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                    sw5 = helpers.stopwatchStop(swName)
                    if not changed:
                        lastUpdate = self.cacheService.getCachedKeyVal(tenantKey=tenantKey, mobileNo=refereeData['mobileNo'], propertyName=f'{objType}_lastUpdate')
                        self.logger.info(f'No {objType} update since {lastUpdate} I:{cnt}', **tenantRefereeDetail)
            
                if (refereeData[objType].get('currentList') or refereeData[objType].get('prevList')) and self.dataDic[objType].get('handleNotifications'):
                    await self.dataDic[objType]['handleNotifications'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, browser=page.context.browser if page else None)
                sw6 = helpers.stopwatchStop(swName)

                helpers.stopwatchStop(f'{swName}', level=self.swLevel)
        except Exception as ex:
            self.logger.error('CheckRefereeData', ex, **refereeData)
        finally:
            pass
            
        return changed


    async def processTemplates(self, tenantKey, objType, refereeData, page):
        def getGameDetail(template:dict):
            try:
                gameId = template.get('gameId')
                gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
                gamePk = gameDetail.get('gamePk')
                refereeGame = refereeData[objType]['currentList'].get(gamePk)
                return gameId, refereeGame, gameDetail, gamePk
            except Exception as ex:
                self.logger.error(f'getGameDetail', ex, gameId=gameId)
                return None, None, None, None

        try:
            gamesReportsObjType = 'gamesReports'

            localNow = helpers.localNow()
            mobileNo = refereeData['mobileNo']
            refId = refereeData['refId']
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)

            # filter by status = created
            sortedTemplates = helpers.sortDictByProperty(obj=self.cacheService.getRefereeTemplates(tenantKey=tenantKey, mobileNo=mobileNo, status='created'), property='created', reverse=True)
            self.logger.debug(f"{len(sortedTemplates)}", **tenantRefereeDetail)
            if sortedTemplates:
                for msgSid, template in sortedTemplates.items():
                    self.logger.debug(f"{msgSid}", **tenantRefereeDetail)
                    self.logger.debug(f"{msgSid} {template.get('repliedButtonId')} {template['action']}", **tenantRefereeDetail)
                    if template['created'] < helpers.localNow() - timedelta(weeks=2):
                        continue
                    if template.get('status') != 'created':
                        continue

                    title = None
                    message = None
                    failureMessage = None
                    gamePk = 'NONGAME'
                    targetMobileNo = mobileNo
                    templateAction = template['action'].lower()

                    if objType == 'games':
                        if templateAction == 'approvegame':
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            if not gameDetail or not refereeGame:
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                if False and (not refereeGame.get('cells') or not refereeGame['cells'].get('status')):
                                    continue
                                cellSelector = refereeGame.get('cells', {}).get('status')
                                result, message = await self.tenantsOrgServices[tenantKey].approveGame(refereeData=refereeData, gameId=gameId, statusCell=cellSelector, page=page)
                                template['message'] = message
                                self.logger.info(f"processTemplates {templateAction} {msgSid} gameId={gameId} {gameDetail['gameTitle']} result={result}", **tenantRefereeDetail)
                                title = f'משחק {gameDetail["gameTitle"]}'
                                if result:
                                    template['status'] = 'completed'
                                    template['updated'] = localNow
                                    refereeGame['approvedDate'] = localNow
                                    helpers.delProperties(refereeGame, 'cells')
                                    self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=gamePk, value=refereeGame)
                                    message = f'השיבוץ אושר בפורטל'
                                else:
                                    failureMessage = f'אישור השיבוץ נכשל'

                        elif templateAction == 'declinegame':
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            if not gameDetail or not refereeGame:
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                if not refereeGame.get('cells') or not refereeGame['cells'].get('status'):
                                    continue
                                cellSelector = refereeGame.get('cells', {}).get('status')
                                result, message = await self.tenantsOrgServices[tenantKey].declineGame(refereeData=refereeData, gameId=gameId, statusCell=cellSelector, page=page)
                                template['message'] = message
                                self.logger.info(f"processTemplates {templateAction} {msgSid} gameId={gameId} {gameDetail['gameTitle']} result={result}", **tenantRefereeDetail)
                                title = f'משחק {gameDetail["gameTitle"]}'
                                if result:
                                    template['status'] = 'completed'
                                    template['updated'] = localNow
                                    refereeGame['declinedDate'] = localNow
                                    self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=gamePk, value=refereeGame)
                                    message = f'השיבוץ נדחה בפורטל'
                                else:
                                    failureMessage = f'דחיית השיבוץ נכשלה'

                        elif templateAction in ['postgameupdate', 'gamereport']:
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            if not gameDetail or False and gamesReportsObjType in refereeData and gameId not in refereeData.get(gamesReportsObjType, {}):
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                data = template.get('data')
                                if data == None:
                                    continue
                                result, message = await self.tenantsOrgServices[tenantKey].postGameUpdate(refereeDetail=tenantRefereeDetail, gameId=gameId, data=data, page=page)
                                template['message'] = message
                                self.logger.info(f"processTemplates {templateAction} {msgSid} gameId={gameId} {gameDetail['gameTitle']} result={result}", **tenantRefereeDetail)
                                title = f'משחק {gameDetail["gameTitle"]}'
                                if result:
                                    template['status'] = 'completed'
                                    template['updated'] = localNow
                                    gameDetail['reportUpdateDate'] = localNow
                                    self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'], gamePk=gamePk, value=gameDetail)
                                    if templateAction == 'postgameupdate':
                                        title = 'סיכום דו״ח משחק עודכן'
                                        msg = f"סיכום המשחק {gameDetail['gameTitle']} ({gameDetail['guestTeamScore']}-{gameDetail['homeTeamScore']}) עודכן בפורטל,"
                                        msg += f'\nיש לעדכן את שאר פרטי דו״ח השיפוט בהמשך'
                                    elif templateAction == 'gamereport':
                                        title = 'דו״ח בפורטל עודכן'
                                        msg = f"דו״ח השיפוט {gameDetail['gameTitle']} עודכן בפורטל"
                                    message = msg
                                    #self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType=template['action'], to=mobileNo, contextDate='created', title=title, message=msg)
                                else:
                                    failureMessage = f'עדכון תוצאת המשחק נכשל' if templateAction == 'postgameupdate' else 'העלאת דו״ח המשחק נכשלה'
                        
                        elif templateAction == 'createrefsixgame':
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            if not gameDetail or not refereeGame:
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                success, message = await self.createRefSixGame(tenantRefereeDetail=tenantRefereeDetail, refereeGame=refereeGame, gameDetail=gameDetail)
                                template['message'] = message
                                if success:
                                    template['status'] = 'completed'
                                    template['updated'] = localNow
                                    self.logger.info(message, **tenantRefereeDetail)
                                else:
                                    failureMessage = message
                                    self.logger.warning(message, **tenantRefereeDetail)

                        else:
                            template['status'] = 'deferred'
                            template['updated'] = localNow

                    if templateAction == 'forcesend':
                        if template['objType'] != objType:
                            continue
                        refereeData[objType]['prevList'] = {}
                        template['status'] = 'completed'
                        template['updated'] = helpers.localNow()
                        self.logger.info(f"{template['msgSid']} objType={objType} ישלח מחדש", **tenantRefereeDetail)
                
                    elif templateAction == 'changepassword':
                        targetMobileNo = template['data']['targetMobileNo'] if template.get('data', {}).get('targetMobileNo') else mobileNo
                        targetTenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=targetMobileNo)
                        targetGlobalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=targetMobileNo)
                        result = False
                        if targetTenantRefereeDetail:
                            title = 'עדכון סיסמא'
                            result, message = await self.tenantsOrgServices[tenantKey].changePassword(refereeDetail=tenantRefereeDetail, targetRefereeDetail=targetTenantRefereeDetail, page=page)
                            template['message'] = message
                            if result:
                                template['status'] = 'completed'
                                template['updated'] = localNow
                                message = f"סיסמת שופט {targetMobileNo} {targetGlobalRefereeDetail['name']} עודכנה"
                                self.logger.info(message, **tenantRefereeDetail)
                            else:
                                message = f"עדכון סיסמא לשופט {targetMobileNo} {targetGlobalRefereeDetail['name']} נכשל"
                                self.logger.warning(message, **tenantRefereeDetail)
                        if result == False:
                            template['status'] = 'deferred'
                            template['updated'] = localNow
                    
                    if template['status'] == 'created' and failureMessage:
                        template['retries'] = int(template.get('retries', '0')) + 1
                        if template['retries'] > 3:
                            await helpers.takeScreenshot(page=page, refereeDetail=tenantRefereeDetail, tag=f'{template["action"]}')
                            template['status'] = 'deferred'
                            template['updated'] = localNow
                            message = failureMessage
                            self.logger.warning(f"{msgSid} ניסיון {template['retries']} של ביצוע הפעולה נכשל", **tenantRefereeDetail)
                    self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid, value=template)
                    if title and message:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType=templateAction, to=targetMobileNo, contextDate='created', title=title, message=message)

        except Exception as ex:
            self.logger.error(f'processTemplates', ex, **tenantRefereeDetail)

    def setNotification(self, tenantKey:str, target:str, id:str, notificationType:str, to:str=None, contextDate:str='gameDate', reminderInHrs:float=None, status:str=None, title:str=None, message:str=None, upsert:bool=False, delete:bool=False):
        notifications = self.cacheService.getNotifications(tenantKey=tenantKey, target=target, id=id, notificationType=notificationType, to=to, status=status)
        if delete:
            if notifications:
                for timestamp, notification in notifications.items():
                    notification['status'] = 'deleted'
                    self.cacheService.setNotification(tenantKey=tenantKey, target=target, id=id, notificationType=notificationType, to=to, timestamp=timestamp, value=notification)
            return

        #   createNotification = False
        #   if notificationType found
        #       if status == created
        #           then update notification
        #       else      
        #           if upsert
        #               pass
        #           else
        #               createNotification = True
        #   else
        #       createNotification = True
        #
        #   if createNotification is True
        #       create notification
        createNotification = False
        if notifications:
            createdFound = False
            for timestamp, notification in notifications.items():
                if notification['status'] == 'created':
                    createdFound = True
                    notification['contextDate'] = contextDate
                    notification['reminderInHrs'] = reminderInHrs
                    notification['sentDate'] = ''
                    notification['title'] = title
                    notification['message'] = message
            if not createdFound and not upsert:
                createNotification = True
        else:
            createNotification = True

        if createNotification:
            timestamp = int(time.time())
            notifications = {timestamp: {'contextDate': contextDate, 'reminderInHrs': reminderInHrs, 'status': 'created', 'timestamp': timestamp, 'title': title, 'message': message}}
        
        for timestamp, notification in notifications.items():
            self.cacheService.setNotification(tenantKey=tenantKey, target=target, id=id, notificationType=notificationType, to=to, timestamp=timestamp, value=notification)
        
        return next(iter(notifications.values()))
    
    async def postParseGames(self, tenantKey, objType, refereeData, page):
        async def updateGroupName(gameDetail):
            try:
                chatGroupId = gameDetail.get('chatGroupId')
                groupName = f'{gameDetail["tournamentName"]} {gameDetail["gameTitle"]}'

                now = helpers.localNow().date()
                delta_days = (gameDetail['date'].date() - now).days

                if delta_days == 0:
                    groupName = f'היום {datetime.strftime(gameDetail["date"], "%H:%M")} {groupName}'
                elif delta_days == 1:
                    groupName = f'מחר {groupName}'
                elif delta_days == 2:
                    groupName = f'מחרתיים {groupName}'
                elif delta_days < 0:
                    groupName = f'הסתיים {groupName}'

                if groupName != gameDetail.get('groupName'):
                    gameDetail['groupName'] = groupName
                    if chatGroupId and self.messagingService.useGreenApi:
                        groupResponse = await self.messagingService.greenApiClient.handleAction('updateGroupName', {'chatGroupId':chatGroupId, 'groupName':groupName})

            except Exception as ex:
                self.logger.error(f'updateGroupName', ex)
                return None

        mobileNo = refereeData['mobileNo']
        swName = f'postParseGames={mobileNo}'
        helpers.stopwatchStart(swName)
        globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
        tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
        tenantNotifications = tenant.get('notifications', {})

        try:
            items = refereeData[objType]['currentList']
            sortedItemsByDate = helpers.sortDictByProperty(obj=items, property='date')
            
            for gamePk, refereeGame in sortedItemsByDate.items():
                try:
                    tournamentName = refereeGame['tournamentName']
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
                    if not tournament:
                        tournament = self.handleTournaments.createTournament(tenantKey=tenantKey, tournamentName=tournamentName)
    
                    section = self.cacheService.get_section_by_name(tenantKey=tenantKey, sectionName=tournament.get('section')) or {}

                    refereeGame['tournamentName'] = tournamentName

                    groupName = f'{refereeGame["tournamentName"]} {refereeGame["gameTitle"]}'

                    gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName)
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=refereeGame)
                    if not gameDetail:
                        gameDetail = { 'gamePk': gamePk, 'tournamentName': tournamentName, 'season': self.season, 'id': str(uuid.uuid4())[:8], 'groupMobileNumbers': [], 'groupName': groupName, 'archived': False, 'gameDuration': gameDuration }
                
                    refereesDetails = {refDetail['* phone']: { 'address': refDetail.get('* address'), 'status': refDetail.get('* status') } for refDetail in gameDetail.get('referees', [])}
                    referees = []
                    if 'referees' in refereeGame:
                        referees = refereeGame.get('referees', [])
                        del refereeGame['referees']
                        for refDetail in referees:
                            if refDetail.get('* phone'):
                                refDetail['* phone'] = MessagingService.adjustMobileNo(refDetail['* phone'])
                
                    refereesMobileNos = {}
                    mainReferees = []
                    secretaryReferee = None
                    isMainReferee = False
                    isSecretaryReferee = False
                    refereeIds = []
                    sortedReferees = sorted(referees, key=lambda refDetail: self.cacheService.get_role_by_name(tenantKey=tenantKey, roleName=refDetail['role']).get('order', '99'))
                    refereesList = []
                    for refDetail in sortedReferees:
                        roleName = refDetail['role']
                        role = self.cacheService.get_role_by_name(tenantKey=tenantKey, roleName=roleName)
                    
                        refPhone = refDetail['* phone']
                        if refPhone:
                            gameTenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=refPhone)
                            gameRefId = gameTenantRefereeDetail.get('refId') if gameTenantRefereeDetail else None
                            gameRefereeGame = None
                            if gameRefId:
                                refereeIds.append(gameRefId)

                            if refPhone == mobileNo:
                                refereeGame['role'] = roleName
                                if role.get('mainReferee', False):
                                    isMainReferee = True
                                if role.get('secretaryReferee', False):
                                    isSecretaryReferee = True
                                if role.get('reviewer', False) == True and gameTenantRefereeDetail and gameTenantRefereeDetail.get('refId'):
                                    refereeGame['reviewer'] = gameTenantRefereeDetail['refId']

                                refDetail['* status'] = refDetail.get('* status') or refereeGame.get('status')
                                refDetail['* address'] = globalRefereeDetail.get('addressDetails', {}).get('address') or refDetail.get('* address')
                            else:
                                if gameRefId:
                                    gameRefereeGame = self.cacheService.get_referee_game_by_pk(tenantKey=tenantKey, gamePk=gamePk, refId=gameRefId)
                                refDetail['* status'] = gameRefereeGame.get('status') if gameRefereeGame else refDetail.get('* status')
                                refDetail['* address'] = refereesDetails.get(refPhone, {}).get('address') or refDetail.get('* address')

                            if role.get('mainReferee', False):
                                if gameTenantRefereeDetail and gameTenantRefereeDetail.get('refId'):
                                    mainReferees.append(gameTenantRefereeDetail['refId'])

                            if role.get('secretaryReferee', False):
                                if gameTenantRefereeDetail and gameTenantRefereeDetail.get('refId'):
                                    secretaryReferee = gameTenantRefereeDetail['refId']

                        if not role.get('reviewer', False):
                            refereesMobileNos[MessagingService.adjustMobileNo(refPhone)] = refDetail.get('* name') 
                        else:
                            refDetail['reviewer'] = True
                            continue

                        refereesList.append(refDetail)
                
                    gameDetail['gameDuration'] = gameDuration
                
                    chatGroupId = None

                    if jsonHelper.save_to_json(gameDetail.get('referees')) != jsonHelper.save_to_json(refereesList):
                        gameDetail['updateGroupMembers'] = True
                        gameDetail['referees'] = refereesList
                    gameDetail['mainReferees'] = mainReferees
                    gameDetail['secretaryReferee'] = secretaryReferee
                    gameDetail['removedRefereeIds'] = gameDetail.get('removedRefereeIds', [])
                    gameDetail['refereeIds'] = refereeIds
                
                    teamNames = refereeGame['gameTitle']       
                    teams = teamNames.split(' - ')
                    gameDetail['homeTeamName'] = refereeGame.get('homeTeamName', teams[0].strip())
                    gameDetail['guestTeamName'] = refereeGame.get('guestTeamName', teams[1].strip())
                    gameDetail['date'] = refereeGame['date']
                    gameDetail['endTime'] = gameDetail['date'] + timedelta(minutes=gameDuration)
                    gameDetail['dow'] = self.handleRefereeData.dayOfWeekInHebrew(gameDetail.get('date'))
                    mandatoryTags = [ 'dateText', 'dow', 'gameTitle', 'round', 'fixture', 'field' ]
                    for tag in mandatoryTags:
                        if refereeGame.get(tag):
                            gameDetail[tag] = refereeGame[tag]
                            del refereeGame[tag]
                        else:
                            if tag in gameDetail:
                                del gameDetail[tag]
                            self.logger.debug(f'postParseGames game={gamePk} missing mandatory tag={tag}')
                    optionalTags = [ 'homeTeamName', 'guestTeamName', 'internalGameId', 'homeTeamScore', 'guestTeamScore', 'gameResult' ]
                    for tag in optionalTags:
                        if refereeGame.get(tag):
                            gameDetail[tag] = refereeGame[tag]
                            del refereeGame[tag]
                        else:
                            self.logger.debug(f'postParseGames game={gamePk} missing optional tag={tag}')

                    now = helpers.localNow().date()
                    delta_days = (gameDetail['date'].date() - now).days

                    if delta_days == 0:
                        groupName = f'היום {datetime.strftime(gameDetail["date"], "%H:%M")} {groupName}'
                    elif delta_days == 1:
                        groupName = f'מחר {groupName}'
                    elif delta_days == 2:
                        groupName = f'מחרתיים {groupName}'
                    elif delta_days < 0:
                        groupName = f'הסתיים {groupName}'

                    createChatGroup = self.messagingService.checkSendGreenApiMessages(to=globalRefereeDetail) and not self.avoidChatGroups \
                        and (isMainReferee or globalRefereeDetail.get('alwaysCreateChatGroup', False)) \
                        and (len(referees) > 1 or self.chatGroups4Singles and globalRefereeDetail.get('ignoreGroup4Singles', False) == False) \
                        and timedelta(seconds=0) < gameDetail['date'] - helpers.localNow() <= timedelta(days=7)
                        #and (True or not 'אולמות' in tournamentName)
                    groupMobileNumbers = refereesMobileNos if gameDetail.get('mainReferees', []) or gameDetail.get('secretaryReferee', []) or globalRefereeDetail.get('alwaysCreateChatGroup', False) else { mobileNo: globalRefereeDetail['name'] }
                    activeGroupMobileNumbers = [ mobileNo for mobileNo in refereesMobileNos.keys() if self.refereesByMobile.get(tenantKey, {}).get(mobileNo) ]
                    gameDetail['activeGroupMobileNumbers'] = activeGroupMobileNumbers

                    firstGameReminderEnabled = globalRefereeDetail.get('firstGameReminderEnabled', True)
                    commuteReminderEnabled = globalRefereeDetail.get('commuteReminderEnabled', True)
                    firstGameReminderTimeInAdvance = int(globalRefereeDetail.get('firstGameReminderTimeInAdvance', '48'))
                    commuteReminderTimeInAdvance = int(globalRefereeDetail.get('commuteReminderTimeInAdvance', '3'))

                    #gameFirstReminder
                    if firstGameReminderEnabled:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='gameFirstReminder', reminderInHrs=firstGameReminderTimeInAdvance, upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='gameFirstReminder', delete=True)

                    #refereeLastReminder & gameLastReminder
                    if refereeGame.get('state') == 'active':
                        if commuteReminderEnabled:
                            self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeLastReminder', to=mobileNo, reminderInHrs=commuteReminderTimeInAdvance, upsert=True)
                        else:
                            self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeLastReminder', delete=True)
                    if len(referees) > 1:
                        if commuteReminderEnabled:
                            self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='gameLastReminder', reminderInHrs=commuteReminderTimeInAdvance, upsert=True)
                        else:
                            self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='gameLastReminder', delete=True)

                    #gameLineupsAnnounced
                    gameLineupsAnnouncedEnabled = globalRefereeDetail.get('gameLineupsAnnouncedEnabled', True)
                    if gameLineupsAnnouncedEnabled:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='gameLineupsAnnounced', reminderInHrs=float(tenantNotifications['gameLineupsAnnounced']), upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='gameLineupsAnnounced', delete=True)

                    #refereeGameReport
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='refereeGameReport', delete=True)
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='refereeGameUpdate', delete=True)
                    if isMainReferee or isSecretaryReferee:
                        if 'refereeGameReport' in tenantNotifications:
                            self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeGameReport', to=mobileNo, reminderInHrs=float(tenantNotifications['refereeGameReport']), upsert=True)
                        else:
                            self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeGameReport', to=mobileNo, status='created', delete=True)
                    
                        if section.get('skipRefereeGameUpdateReminder', False) == False:
                            if 'refereeGameUpdate' in tenantNotifications:
                                self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeGameUpdate', to=mobileNo, reminderInHrs=float(tenantNotifications['refereeGameUpdate']), upsert=True)
                            else:
                                self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeGameUpdate', to=mobileNo, status='created', delete=True)
                
                    if 'refereeCommuteGameUpdate' in tenantNotifications:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeCommuteGameUpdate', to=mobileNo, reminderInHrs=float(tenantNotifications['refereeCommuteGameUpdate']), upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType='refereeCommuteGameUpdate', to=mobileNo, status='created', delete=True)
                
                    chatGroupId = gameDetail.get('chatGroupId')
                    if createChatGroup:
                        # Create chat group, set main referee as admin, set profile, invite participants
                        if not chatGroupId:
                            groupResponse = await self.messagingService.greenApiClient.handleAction('createGroup', {'groupName':groupName, 'tos':list(groupMobileNumbers.keys())})
                            chatGroupId = groupResponse.get('chatId') if groupResponse else None
                            gameDetail['chatGroupId'] = chatGroupId
                            if chatGroupId:
                                changed = self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                                if isMainReferee:
                                    await self.messagingService.greenApiClient.handleAction('setGroupAdmin', {'chatGroupId': chatGroupId, 'to': mobileNo})

                                try:
                                    #self.logger.info(f'libraqm support: {features.check("raqm")}', **refereeDetail)
                                    groupJpg = helpers.createHebrewTextImage(gameDetail)
                                    if os.path.exists(groupJpg):
                                        await self.messagingService.greenApiClient.handleAction('setGroupPicture', {'chatGroupId': chatGroupId, 'pictureFile': groupJpg})
                                except Exception as ex:
                                    self.logger.error(f'setGroupPicture gamePk={gameDetail["gamePk"]} cg={chatGroupId}', ex, **globalRefereeDetail)

                                gameDetail['updateGroup'] = True
                    
                        if chatGroupId and gameDetail.get('updateGroup', False):
                            try:
                                #self.logger.info(f'libraqm support: {features.check("raqm")}', **refereeDetail)
                                groupJpg = helpers.createHebrewTextImage(gameDetail)
                                if os.path.exists(groupJpg):
                                    await self.messagingService.greenApiClient.handleAction('setGroupPicture', {'chatGroupId': chatGroupId, 'pictureFile': groupJpg})
                            except Exception as ex:
                                self.logger.error(f'setGroupPicture gamePk={gameDetail["gamePk"]} cg={chatGroupId}', ex, **globalRefereeDetail)

                    if createChatGroup and chatGroupId and len(referees) > 1:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='chatGroupCreated', contextDate='created', upsert=True)                    
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='transportationPoll', reminderInHrs=48, upsert=True)
                    
                    else:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='chatGroupCreated', delete=True)                    
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=gamePk, notificationType='transportationPoll', delete=True)

                    if groupName != gameDetail.get('groupName'):
                        gameDetail['groupName'] = groupName
                        if chatGroupId and self.messagingService.useGreenApi:
                            groupResponse = await self.messagingService.greenApiClient.handleAction('updateGroupName', {'chatGroupId':chatGroupId, 'groupName':groupName})

                    if gameDetail.get('updateGroupMembers', False) == True:
                        if chatGroupId and self.messagingService.useGreenApi:
                            await self.messagingService.updateGroupParticipants(gameDetail=gameDetail)
                        gameDetail['groupMobileNumbers'] = list(groupMobileNumbers.keys())
                        gameDetail['updateGroupMembers'] = False
                
                    gameDetail['updateGroup'] = False

                    refereeData['byGameId'][objType][gameDetail['id']] = refereeGame

                    self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                    refereeGame['gameDetail'] = gameDetail
                except Exception as ex:
                    self.logger.error(
                        f'postParseGames failed for gamePk={gamePk} tournamentName={refereeGame.get("tournamentName")!r} gameTitle={refereeGame.get("gameTitle")!r}',
                        ex,
                        **globalRefereeDetail,
                    )

            for gamePk, refereeGame in refereeData[objType]['prevList'].items():
                gameDetail = refereeGame.get('gameDetail', {}) or self.cacheService.getGameDetail(tenantKey=tenantKey, game=refereeGame)
                gameId = gameDetail.get('id')
                if gameId and gameId not in refereeData['byGameId'][objType]:
                    refereeData['byGameId'][objType][gameId] = refereeGame

                if gamePk not in refereeData[objType]['currentList'].keys():
                    await updateGroupName(gameDetail=gameDetail)
                    tournamentName = gameDetail.get('tournamentName')
                    self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)

            sw1 = helpers.stopwatchStop(swName)
            gamesReportsObjType = 'gamesReports'
            if gamesReportsObjType in tenant.get('objTypes', []):
                getListSuccessful = await self.tenantsOrgServices[tenantKey].getListForReferee(tenantKey=tenantKey, objType=gamesReportsObjType, refereeData=refereeData, page=page)
                if getListSuccessful == True:
                    gamesReports = refereeData[gamesReportsObjType]['currentList']
                    for gamePk, refereeReportGame in gamesReports.items():
                        refereeReportGame['gamePk'] = gamePk
                        gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=refereeReportGame)
                        if not gameDetail:
                            continue
                        if refereeReportGame.get('internalGameId'):
                            gameDetail['internalGameId'] = refereeReportGame['internalGameId']
                        if refereeReportGame.get('gameReportUrl'):
                            gameDetail['gameReportUrl'] = refereeReportGame['gameReportUrl']
                        self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=refereeReportGame['tournamentName'], gamePk=gamePk, value=gameDetail)
                        refereeData[gamesReportsObjType][gameDetail['id']] = refereeReportGame

                    completedGamePks = list(set(refereeData[objType]['prevList'].keys()) - set(gamesReports.keys()))
                    for gamePk in completedGamePks:
                        refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', id=gamePk, status='created', to=mobileNo)
                        if refereeGamesNotifications:
                            for notification in refereeGamesNotifications.values():
                                notificationType = notification['notificationType']
                                if notificationType in ['refereeGameUpdate', 'refereeGameReport']:
                                    notification['status'] = 'deleted'
                                    self.cacheService.setNotification(tenantKey=tenantKey, target='refereeGames', id=gamePk, notificationType=notificationType, to=mobileNo, timestamp=notification['timestamp'], value=notification)

            sw2 = helpers.stopwatchStop(swName)

            if self.dataDic[objType].get('processTemplates'):
                await self.dataDic[objType]['processTemplates'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                
            for gamePk, refereeGame in refereeData[objType]['currentList'].items():
                if 'cells' in refereeGame:
                    del refereeGame['cells']
            pass
        except Exception as ex:
            self.logger.error(f'postParseGames', ex, **globalRefereeDetail)
            raise ex

    async def postParseReviews(self, tenantKey, objType, refereeData, page):
        try:
            refId = refereeData['refId']
            mobileNo = refereeData['mobileNo']
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            numOfReviews = len(refereeData[objType]['currentList'])
            i = 0

            for reviewPk, review in refereeData[objType]['currentList'].items():
                prevReview = refereeData[objType]['prevList'].get(reviewPk) 
                if prevReview:
                    review['id'] = prevReview['id']
                else:
                    review['id'] = str(uuid.uuid4())[:8]

                refereeData['byGameId'][objType][review['id']] = review

                review['no.'] = f'{numOfReviews-i}'
                review['gameTitle'] = review['gameTitle']
                review['date'] = datetime.strptime(review['dateText'], "%d/%m/%y")
                if review.get('cells'):
                    del review['cells']
                i += 1

            if self.dataDic[objType].get('processTemplates'):
                await self.dataDic[objType]['processTemplates'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)

        except Exception as ex:
            self.logger.error(f'postParseReviews', ex, **refereeDetail)

    async def compareItems(self, tenantKey, objType, refereeData, page):
        try:
            refId = refereeData['refId']
            mobileNo = refereeData['mobileNo']
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)

            prevList = refereeData[objType]['prevList']
            currentList = refereeData[objType]['currentList']

            activePrevList = { gamePk: prevItem for gamePk, prevItem in prevList.items() if prevItem.get('state', 'active') == 'active' }
            activeCurrentList = { gamePk: currentItem for gamePk, currentItem in currentList.items() if currentItem.get('state', 'active') == 'active' }

            prevItem = None
            currentItem = None
            now = helpers.localNow()
            generateDetailsFunc = self.dataDic[objType]['generate']

            #Added
            futureAddedGamePks = [ gamePk for gamePk in activeCurrentList.keys() if True or activeCurrentList[gamePk].get('date') >= helpers.localNow() ]
            added = sorted(list(set(futureAddedGamePks) - set(activePrevList.keys())), key=lambda gamePk: activeCurrentList[gamePk].get('date'))
            refereeData[objType]['added'] = added
            refereeData[objType]['addedText'] = ''
            for pk in refereeData[objType]['added']:
                currentItem = currentList[pk]
                currentGameDetail = currentItem['gameDetail'] if objType == 'games' else {}
                includeReferees = True
                includeReviewer = False
                if objType == 'games':
                    if currentGameDetail.get('tournamentName') == None:
                        self.logger.error(f'compareList {objType} pk={pk} missing gameDetail={currentItem.get("gameDetail")}')
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=currentGameDetail['tournamentName'])
                    if tournament:
                        rule = self.cacheService.get_rule_by_name(tenantKey=tenantKey, ruleName=tournament.get('rules'))
                        includeReviewer = rule.get('includeReviewer', False)
                prevItemText = generateDetailsFunc(tenantKey=tenantKey, gameDetail=currentItem | currentGameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
                refereeData[objType]['addedText'] += f'{prevItemText}\n'

            #archive
            candidateToRemoveFromPrevList = {}
            candidateToArchiveFromPrevList = {}
            if 'removeFilter' in self.dataDic[objType]:
                for pk, prevItem in activePrevList.items():
                    # future game should be removed
                    gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=prevItem['tournamentName'])
                    # if future game
                    if prevItem.get('date') >= now:
                        if prevItem.get('state', 'active') == 'removed':
                            continue
                        candidateToRemoveFromPrevList[pk] = prevItem
                    # if after game ended + 10 minutes
                    elif now >= prevItem.get('date') + timedelta(minutes=gameDuration+10):
                        if prevItem.get('state', 'active') == 'archived':
                            continue
                        candidateToArchiveFromPrevList[pk] = prevItem
            else:
                candidateToRemoveFromPrevList = activePrevList

            refereeData[objType]['removed'] = sorted(list(set(candidateToRemoveFromPrevList.keys()) - set(currentList.keys())), key=lambda gamePk: candidateToRemoveFromPrevList[gamePk].get('date'))
            refereeData[objType]['removedText'] = ''
            for pk in refereeData[objType]['removed']:
                prevItem = candidateToRemoveFromPrevList[pk]
                prevGameDetail = prevItem.get('gameDetail', {})
                prevItemText = generateDetailsFunc(tenantKey=tenantKey, gameDetail=prevItem | prevGameDetail, includeReferees=False)
                refereeData[objType]['removedText'] += f'{prevItemText}\n'

            refereeData[objType]['archived'] = sorted(candidateToArchiveFromPrevList.keys(), key=lambda gamePk: candidateToArchiveFromPrevList[gamePk].get('date'))
            #refereeData[objType]['archived'] = sorted(list(set(candidateToArchiveFromPrevList.keys()) - set(currentList.keys())), key=lambda gamePk: candidateToArchiveFromPrevList[gamePk].get('date'))

            #Changed/Nonchanged
            changedList = {}
            nonChangedList = {}
            potentialChangePks = sorted(list(set(activePrevList.keys()) & set(currentList.keys())), key=lambda gamePk: currentList[gamePk].get('date'))
            for pk in potentialChangePks:
                prevItem = activePrevList[pk]
                prevGameDetail = prevItem.get('gameDetail') or {}
                currentItem = currentList[pk]
                currentGameDetail = currentItem['gameDetail'] if objType == 'games' else {}
                includeReferees = True
                includeReviewer = False
                if objType == 'games':
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=currentItem['tournamentName'])
                    if tournament:
                        rule = self.cacheService.get_rule_by_name(tenantKey=tenantKey, ruleName=tournament.get('rules'))
                        includeReviewer = rule.get('includeReviewer', False)
                prevItemText = generateDetailsFunc(tenantKey=tenantKey, gameDetail=prevItem | prevGameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
                currentItemText = generateDetailsFunc(tenantKey=tenantKey, gameDetail=currentItem | currentGameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
                if prevItemText != currentItemText:
                    changedList[pk] = currentItem
                else:
                    nonChangedList[pk] = currentItem

            refereeData[objType]['nonChanged'] = sorted(nonChangedList, key=lambda gamePk: currentList[gamePk].get('date'))

            refereeData[objType]['changed'] = sorted(changedList, key=lambda gamePk: currentList[gamePk].get('date'))
            refereeData[objType]['changedText'] = ''
            for pk in refereeData[objType]['changed']:
                currentItem = changedList[pk]
                currentGameDetail = currentItem['gameDetail'] if objType == 'games' else {}
                includeReferees = True
                includeReviewer = False
                if objType == 'games':
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=currentItem['tournamentName'])
                    if tournament:
                        rule = self.cacheService.get_rule_by_name(tenantKey=tenantKey, ruleName=tournament.get('rules'))
                        includeReviewer = rule.get('includeReviewer', False)
                currentItemText = generateDetailsFunc(tenantKey=tenantKey, gameDetail=currentItem | currentGameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
                refereeData[objType]['changedText'] += f'{currentItemText}\n'

        except Exception as ex:
            self.logger.error(f'compareList {objType}', ex, **refereeDetail)

    def teamStatistics(self, teamInTable):
        if teamInTable is None:
            return ''
        text = f"\n*{teamInTable['קבוצה']}*:"
        text += f"\nמיקום: {teamInTable['מיקום']}"
        text += f"\nנקודות: {teamInTable['נקודות']}"
        text += f"\nיחס שערים: {teamInTable['שערים']}"
        return text
        
    async def gameStatistics(self, tenantKey, gameDetail):
        try:
            (tournament, leagueTable, homeTeam, guestTeam) = await self.handleTournaments.findGameTeamsInTable(tenantKey=tenantKey, gameDetail=gameDetail)
            tournamentText = None
            if tournament:
                tournamentText = tournament.get("text")
            self.logger.debug(f'gameStatistics tournament={tournamentText} leagueTable={leagueTable} homeTeam={homeTeam}')
            if tournament and homeTeam and guestTeam:
                homeTeamPosition = int(homeTeam.get('מיקום'))
                guestTeamPosition = int(guestTeam.get('מיקום'))
                homeTeamStatistics = self.teamStatistics(homeTeam)
                aboveHomeTeamStatistics = None
                if homeTeamPosition > 1 and guestTeamPosition != homeTeamPosition - 1:
                    aboveHomeTeam = next((team for team in leagueTable.values() if team.get("מיקום") == str(homeTeamPosition-1)), None)
                    aboveHomeTeamStatistics = self.teamStatistics(aboveHomeTeam)
                guestTeamStatistics = self.teamStatistics(guestTeam)
                aboveGuestTeamStatistics = None
                if guestTeamPosition > 1 and homeTeamPosition != guestTeamPosition - 1:
                    aboveGuestTeam = next((team for team in leagueTable.values() if team.get("מיקום") == str(guestTeamPosition-1)), None)
                    aboveGuestTeamStatistics = self.teamStatistics(aboveGuestTeam)

                text = '*נתונים:*'
                text += f'\n{homeTeamStatistics}'
                text += f'\n{guestTeamStatistics}'
                if aboveHomeTeamStatistics:
                    text += f'\n{aboveHomeTeamStatistics}'
                if aboveGuestTeamStatistics:
                    text += f'\n{aboveGuestTeamStatistics}'
                return text
    
            return None
        except Exception as ex:
            self.logger.error(f'gameStatistics', ex)
            return None

    async def handleNotifications(self, tenantKey, objType, refereeData, browser=None):
        mobileNo = refereeData['mobileNo']
        refId = refereeData['refId']
        name = refereeData['name']
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
        
        try:
            async with async_playwright() as p:
                browser = await OrgServiceBase.launchBrowser(p, headless=eval(os.getenv('browserHeadless') or 'True'))
                tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
                skipAvailabilityNotifications = tenant.get('skipAvailabilityNotifications', [])
                
                allowMessageSending = self.messagingService.allowMessageSending(to=globalRefereeDetail)

                localTime = datetime.now(ZoneInfo(os.getenv('TZ')))
                localHour = localTime.hour
                defaultAvailableFromHour = int(tenant.get('defaultAvailableFromHour', '8'))
                defaultAvailableToHour = int(tenant.get('defaultAvailableToHour', '21'))
                allowDefaultAvailability = True
                if defaultAvailableFromHour <= defaultAvailableToHour and (localHour < defaultAvailableFromHour or localHour > defaultAvailableToHour) \
                            or defaultAvailableFromHour > defaultAvailableToHour and (localHour > defaultAvailableFromHour and localHour < defaultAvailableToHour):
                    allowDefaultAvailability = False
                
                if False and not allowMessageSending:
                    self.logger.warning(f'handleNotifications, mobileNo={mobileNo}, out of message acceptance limitation', **tenantRefereeDetail)
                    return
                            
                items = refereeData[objType]['currentList']
                for itemPk, item in refereeData[objType]['prevList'].items():
                    if itemPk not in refereeData[objType]['currentList'].keys():
                        items[itemPk] = item
                sortedItemsByDate = helpers.sortDictByProperty(obj=items, property='date')
                sortedItemsByDate['NONGAME'] = { 'tenantKey': 'GLOBAL', 'date': helpers.localNow() }
                for itemPk, item in sortedItemsByDate.items():
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=item) or {}
                    tournamentName = gameDetail.get('tournamentName')
                    gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName)
                    self.logger.debug(f"notifications {item.get('date')}", **tenantRefereeDetail)

                    refereeGamesNotifications = None
                    tournamentGamesNotifications = None
                    notifications = None
                    if objType == 'games':
                        if item.get('state', 'active') == 'removed':
                            refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', id=itemPk, status='created', to=mobileNo)
                            if refereeGamesNotifications:
                                for notification in refereeGamesNotifications.values():
                                    if notification.get('notificationType') != 'removedItem':
                                        notification['status'] = 'deleted'
                                        self.cacheService.setNotification(tenantKey=notification['tenantKey'], target='refereeGames', id=itemPk, notificationType=notification['notificationType'], to=mobileNo, timestamp=notification['timestamp'], value=notification)

                        refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=item.get('tenantKey', tenantKey), target='refereeGames', id=itemPk, status='created', to=mobileNo)
                        tournamentGamesNotifications = {}
                        if item.get('state', 'active') == 'active':
                            tournamentGamesNotifications = self.cacheService.getNotifications(tenantKey=item.get('tenantKey', tenantKey), target='tournamentGames', id=itemPk, status='created') if item.get('state', 'active') != 'removed' else None
                        notifications:dict = helpers.merge_nested_dicts(refereeGamesNotifications, tournamentGamesNotifications)
                    elif objType == 'reviews':
                        if item.get('state', 'active') == 'removed':
                            refereeReviewsNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', id=itemPk, status='created', to=mobileNo)
                            if refereeReviewsNotifications:
                                for notification in refereeReviewsNotifications.values():
                                    if notification.get('notificationType') != 'removedItem':
                                        notification['status'] = 'deleted'
                                        self.cacheService.setNotification(tenantKey=notification['tenantKey'], target='refereeReviews', id=itemPk, notificationType=notification['notificationType'], to=mobileNo, timestamp=notification['timestamp'], value=notification)

                        notifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', id=itemPk, status='created', to=mobileNo)
                    pass
                    for key, notification in notifications.items():
                        notificationType = notification['notificationType']
                        available = allowMessageSending or notificationType in skipAvailabilityNotifications and allowDefaultAvailability
                        if not available:
                            continue
                        gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName)
                        contextDate = notification.get('contextDate', 'gameDate')
                        reminderInHrs = float(notification.get('reminderInHrs') or '0')
                        if contextDate == 'created':
                            timePassed = helpers.localNow() - notification['created']
                            if timePassed.total_seconds() > 12 * 60 * 60:
                                notification['status'] = 'deferred'
                                self.cacheService.setNotification(tenantKey=notification['tenantKey'], target=notification['target'], id=notification['id'], notificationType=notificationType, to=notification.get('to'), timestamp=notification['timestamp'], value=notification)
                                continue
                            dueDate = None #notification['created']
                        elif contextDate == 'gameDate':
                            dueDate = gameDetail.get('date') if reminderInHrs >=0 else gameDetail.get('date') + timedelta(minutes=gameDuration) 
                        else:
                            dueDate = helpers.localNow()
                        if reminderInHrs and reminderInHrs == -99:
                            continue
                        processNotification = await self.checkNotificationTime(dueDatetime=dueDate, hoursInAdvance=reminderInHrs, reminderOffsetInMins=15)
                        if processNotification:
                            await self.handleSingleNotification(tenantKey=tenantKey, objType=objType, refereeData=refereeData, notification=notification, itemPk=itemPk, item=item, gameDetail=gameDetail, browser=browser)
       
        except Exception as ex:
            self.logger.error(f'handleNotifications {refId}', ex, **globalRefereeDetail)

    async def handleSingleNotification(self, tenantKey, objType, refereeData, notification, itemPk, item, gameDetail, browser=None):
        mobileNo = refereeData['mobileNo']
        refId = refereeData['refId']
        name = refereeData['name']
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
        
        try:
            tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
            localTime = datetime.now(ZoneInfo(os.getenv('TZ')))
            localHour = localTime.hour
            defaultAvailableFromHour = int(tenant.get('defaultAvailableFromHour', '8'))
            defaultAvailableToHour = int(tenant.get('defaultAvailableToHour', '21'))
            allowDefaultAvailability = True
            if defaultAvailableFromHour <= defaultAvailableToHour and (localHour < defaultAvailableFromHour or localHour > defaultAvailableToHour) \
                        or defaultAvailableFromHour > defaultAvailableToHour and (localHour > defaultAvailableFromHour and localHour < defaultAvailableToHour):
                allowDefaultAvailability = False
            skipAvailabilityNotifications = tenant.get('skipAvailabilityNotifications', [])
            allowMessageSending = self.messagingService.allowMessageSending(to=globalRefereeDetail)
            msgSid = None
            abortNotification = False
            forceUseGreenApi = False
            sentPushMsgIds = []

            target = notification['target']
            notificationType = notification['notificationType']
            available = allowMessageSending or notificationType in skipAvailabilityNotifications and allowDefaultAvailability
            if not available:
                return
            notificationTo = notification.get('to')
            internalMsgId = notification['entityKey']

            tournamentName = gameDetail.get('tournamentName') if gameDetail else None
            tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
            rules = None
            if tournament and tournament.get('rules'):
                rules = self.cacheService.get_rule_by_name(tenantKey=tenantKey, ruleName=tournament.get('rules').strip())
            referees:list = gameDetail.get('referees', []) if gameDetail else []
            isMainReferee = refId in gameDetail.get('mainReferees', []) if gameDetail else False
            isSecretaryReferee = refId == gameDetail.get('secretaryReferee', '' ) if gameDetail else False
            chatGroupId = gameDetail.get('chatGroupId') if gameDetail else None
            field = None
            fieldAddressDetails = None
            fieldTitle = gameDetail.get('field') if gameDetail else None
            if fieldTitle:
                field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldTitle)
            if field:
                fieldAddressDetails = field.get('addressDetails')

            noticeType = 'regular'
            noticeTitle = None
            noticeDetails = None
            noticeOptions = None

            secondsLeft = round((gameDetail.get('date') - helpers.localNow()).total_seconds()) if gameDetail.get('date') else 0
            minsLeft = round(secondsLeft/60)
            hoursLeft = round(minsLeft/60)

            if notificationType == 'addedItem' or notificationType == 'updatedItem':
                isNewItem = notificationType == 'addedItem'

                if objType == 'games':
                    itemStatus = item.get('status')
                    if itemStatus in ('מאושר', 'מאשר'):
                        title = 'שיבוץ חדש (מאושר)' if isNewItem else 'עדכון שיבוץ (מאושר)'
                        msgSid, sentPushMsgIds = await self.messagingService.sendGameUpdateNotification(refereeGames={itemPk:item}, gameRemoval=False, title=title, refId=refId, toMobile=mobileNo, toName=name, internalMsgId=internalMsgId)
                    elif itemStatus != 'שיבוץ נדחה':
                        title = '*שיבוץ חדש לאישור*' if isNewItem else '*עדכון שיבוץ לאישור*'
                        msgSid, sentPushMsgIds = await self.messagingService.sendNewGameNotification(refereeGame=item, title=title, refId=refId, toMobile=mobileNo, toName=name)
                    else:
                        return
                elif objType == 'reviews':
                    if isNewItem:
                        if int(item['no.']) < len(refereeData[objType]['currentList']):
                            title = 'ביקורת "חדשה"'
                        else:
                            title = '*ביקורת חדשה*'
                        msgSid, sentPushMsgIds = await self.messagingService.sendNewReviewNotification(reviews={itemPk:item}, title=title, refId=refId, toMobile=mobileNo, toName=name, internalMsgId=internalMsgId)
                    else:
                        title = 'עדכון ביקורת*'
                        msgSid, sentPushMsgIds = await self.messagingService.sendReviewUpdateNotification(reviews={itemPk:item}, reviewRemoval=False, title=title, refId=refId, toMobile=mobileNo, toName=name, internalMsgId=internalMsgId)

            elif notificationType.startswith('removedItem'):
                if objType == 'games':
                    title = 'שיבוץ נמחק'
                    msgSid, sentPushMsgIds = await self.messagingService.sendGameUpdateNotification(refereeGames={itemPk:item}, gameRemoval=True, title=title, refId=refId, toMobile=mobileNo, toName=name, internalMsgId=internalMsgId)
                elif objType == 'reviews':
                    title = 'ביקורת נמחקה'
                    msgSid, sentPushMsgIds = await self.messagingService.sendReviewUpdateNotification(reviews={itemPk:item}, reviewRemoval=True, title=title, refId=refId, toMobile=mobileNo, toName=name, internalMsgId=internalMsgId)
            
            elif notificationType.startswith('archivedItem'):
                msgSid = str(uuid.uuid4())[:8]

            elif notificationType.startswith('joinChatGroup'):
                noticeTitle = f'*הצטרפת לקבוצה*'
                recentJoinConfirmationReply = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName='joinConfirmationReply') != False
                groupData = await self.messagingService.greenApiClient.handleAction('getGroupData', {'chatGroupId': chatGroupId}) 
                noticeDetails = f'אהלן {name}, שובצת למשחק {gameDetail["gameTitle"]}, לצרכי המשחק נפתחה קבוצת WhatsApp שאליה ניתן להצטרף על ידי הקישור הבא: {groupData["groupInviteLink"]}'
                if False and recentJoinConfirmationReply:
                    noticeDetails += f'\n\nבנוסף, בבקשה לשמור בנייד את איש הקשר הנ״ל לשיבוצים הבאים'
                    await self.sendBotContact(chatId)
                forceUseGreenApi = True

            elif notificationType.startswith('chatGroupCreated'):
                if len(referees) > 1:
                    noticeTitle = f'זוהי קבוצה של צוות השיפוט למשחק {tournamentName}-{gameDetail["gameTitle"]}'
                    noticeDetails = f'הקבוצה תתעדכן לכל שינוי בצוות השיפוט ותקבל הודעות ותזכורות מהמערכת עד לסיום המשחק\nבהצלחה'
                else:
                    noticeTitle = f'זוהי קבוצה ייעודית עבור משחק {tournamentName}-{gameDetail["gameTitle"]}'
                    noticeDetails = f'הקבוצה תקבל הודעות ותזכורות מהמערכת עד לסיום המשחק\nבהצלחה'
            
            elif notificationType.startswith('gameFirstReminder'):
                noticeTitle = f'*תזכורת ראשונה*'
                noticeDetails = f"בעוד {hoursLeft} שעות יש לך משחק"
                if isMainReferee and len(referees) > 1:
                    noticeDetails += f", נא לתאם עם הצוות"
                #statistics
                statistics = await self.gameStatistics(tenantKey=tenantKey, gameDetail=gameDetail)
                if statistics:
                    noticeDetails += f'\n{statistics}'
            
            elif notificationType.startswith('transportationPoll'):
                noticeType = 'poll'
                noticeTitle = f'*בירור הגעה*'
                noticeDetails = 'איך את/ה מגיע למגרש ?'
                noticeOptions = [
                    "ברכב",
                    "צריכ/ה הסעה",
                    "עדיין לא יודע/ת"
                ]

            elif notificationType.startswith('gameLastReminder'):
                if self.messagingService.checkSendGreenApiMessages(to=tenantRefereeDetail) or self.messagingService.useMeta:
                    if fieldAddressDetails:
                        noticeType = 'location'
                        noticeTitle = f'*פרטי המגרש*'
                        noticeDetails = ''

                        to_coordinates_lat = fieldAddressDetails['coordinates']['lat']
                        to_coordinates_lng = fieldAddressDetails['coordinates']['lng']
                    
                        if chatGroupId:
                            to = chatGroupId
                        else:
                            to = mobileNo
                        msgSid = await self.messagingService.sendLocation(to=to, latitude=to_coordinates_lat, longitude=to_coordinates_lng, name=field['title'], address=fieldAddressDetails['address'])

                    if rules:
                        noticeType = 'regular'
                        noticeTitle = f'*תזכורת אחרונה-חוקים*'
                        noticeDetails = ''
                        for rule in rules['game']:
                            noticeDetails += f"\n{rule}: {rules['game'][rule]}"
                        if tournament['tournament'] == 'cup':
                            noticeDetails += '\nחוקים לגביע:'
                            for rule in rules['cup']:
                                noticeDetails += f"\n{rule}: {rules['cup'][rule]}"

            elif notificationType.startswith('refereeLastReminder'):
                if tenantRefereeDetail.get('refSixEnabled', False) == True and item.get('refSixCreated', False) == False:
                    template = { 'action': 'createrefsixgame', 'gameId': gameDetail.get('id'), 'status': 'created' }
                    self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=str(uuid.uuid4())[:16], value=template)

                noticeTitle = f'*תזכורת אחרונה*'
                noticeDetails = f'בעוד {hoursLeft} שעות מתחיל המשחק נא להערך בהתאם'
                noticeDetails += await self.getFieldAndCommuteDetails(globalRefereeDetail=globalRefereeDetail, tenantRefereeDetail=tenantRefereeDetail, refereeGame=item, browser=browser)
                if len(referees) == 1 or not (self.messagingService.checkSendGreenApiMessages(to=tenantRefereeDetail) or self.messagingService.useMeta):
                    if rules:
                        noticeDetails += f'\n*חוקים:*'
                        for rule in rules['game']:
                            noticeDetails += f"\n{rule}: {rules['game'][rule]}"
                        if tournament['tournament'] == 'cup':
                            for rule in rules['cup']:
                                noticeDetails += f"\n{rule}: {rules['cup'][rule]}"

            elif notificationType.startswith('gameLineupsAnnounced'):
                if tournament and gameDetail:
                    if not gameDetail.get('squads'):
                        helpers.run_async_in_thread(self.tenantsOrgServices[tenantKey].refreshTournamentGames, tenantKey=tenantKey, tournamentName=tournamentName, round=gameDetail.get('round'), fixture=gameDetail.get('fixture'), fetchGameDetails=True)
                        return

                    url = gameDetail.get('url')
                    squads = gameDetail.get('squads')
                    noticeTitle = f'*פורסמו ההרכבים*'
                    if secondsLeft:
                        durationStr = helpers.seconds_to_hms(secondsLeft)
                        if durationStr[:3] == '00:':
                            durationStr = f'{durationStr[3:]} דקות'
                        else:
                            durationStr = f'{durationStr} שעות'
                        noticeDetails = f'המשחק יתחיל בעוד {durationStr}'
                    noticeDetails += f"\nלהלן הקישור לפרטי המשחק {url}"

                    noticeDetails += '\n*קבוצה ביתית:*'
                    homeActiveNos = squads['homeActivePlayersNos']
                    noticeDetails += f'\n*הרכב:* {homeActiveNos}'
                    if len(squads['homeReplacementPlayersNos']) > 0:
                        homeBencheNos = squads['homeReplacementPlayersNos']
                        noticeDetails += f'\n*מחליפים:* {homeBencheNos}'
                    noticeDetails += f"\n*מאמן:* {squads['homeCoach']}"

                    noticeDetails += '\n*קבוצה אורחת:*'
                    guestActiveNos = squads['awayActivePlayersNos']
                    noticeDetails += f'\n*הרכב:* {guestActiveNos}'
                    if len(squads['awayReplacementPlayersNos']) > 0:
                        guestBenchNos = squads['awayReplacementPlayersNos']
                        noticeDetails += f'\n*מחליפים:* {guestBenchNos}'
                    noticeDetails += f"\n*מאמן:* {squads['awayCoach']}"

            elif notificationType.startswith('refereeCommuteGameUpdate'):
                noticeTitle = f'*דו״ח נסיעה*'
                noticeDetails = await self.getCommuteDetailsAfterGame(globalRefereeDetail=globalRefereeDetail, tenantRefereeDetail=tenantRefereeDetail, refereeGame=item)
                if not noticeDetails:
                    return

            elif notificationType.startswith('refereeGameUpdate'):
                if not gameDetail.get('internalGameId'):
                    return
                noticeTitle = f'עדכון סיכום משחק בפורטל'
                noticeDetails = 'ניתן לעדכן את סיכום המשחק ביישום RefereeX בנייד על ידי לחיצה על כפתור ״עדכן משחק״,'
                noticeDetails += f'ֿ\nלחילופין ניתן ללחוץ על הקישור הבא, לעדכן את הנתונים בהתאם למבנה ההודעה, ולאחר שליחת ההודעה הנתונים יעודכנו אוטומטית בדו״ח השיפוט בפורטל:'
                postUpdateUrl = f'{self.apiServiceUrlBase}api/getGameUpdateTemplate/{mobileNo}/{gameDetail["id"]}'
                noticeDetails += f'ֿ\n\n{postUpdateUrl}'

            elif notificationType.startswith('refereeGameReport'):
                noticeTitle = f'נא למלא דו״ח בפורטל'
                noticeDetails = f'{self.tenantsOrgServices[tenantKey].loginUrl}'

            elif notificationType.startswith('openWindow'):
                msgSid = await self.messagingService.sendOpenWindowMessage(toMobile=mobileNo, toName=name)
                self.cacheService.setCachedKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, value=helpers.localNow(), propertyName='openWindowMessageSent', onlyCache=True, ttlSeconds=60 * 60 * 12)

            else:
                if notification.get('title'):
                    noticeTitle = notification.get('title')
                if notification.get('message'):
                    noticeDetails = notification.get('message')

            if abortNotification:
                return
            
            if noticeTitle or noticeDetails:
                if item.get('status') == 'מחכה לאישור' and noticeTitle:
                    noticeTitle += f" ({item['status']})"

                to = notification.get('to') or mobileNo
                if gameDetail:
                    if target == 'tournamentGames' or len(referees) == 1:
                        to = gameDetail
                    else:
                        noticeTitle = f'{gameDetail["tournamentName"]} {noticeTitle}'

                message = ''
                if noticeTitle:
                    message += noticeTitle
                if gameDetail and not gameDetail.get('chatGroupId'):
                    if message:
                        message += ' '
                    message += f"*{gameDetail['groupName']}*\n"
                if noticeDetails:
                    if message:
                        message += '\n'
                    message += noticeDetails

                if noticeType == 'regular':
                    skipPushNotification = len(notification['sentPushMsgIds']) > 0 if notification.get('sentPushMsgIds') else False
                    msgSid, sentPushMsgIds = await self.messagingService.sendMessage(to=to, message=message, performOpenWindowCheck=True, skipPushNotification=skipPushNotification, returnSentPushMsgIds=True, internalMsgId=internalMsgId, forceUseGreenApi=forceUseGreenApi, gameId=gameDetail['id'] if gameDetail else None)
                elif noticeType == 'poll':
                    msgSid = await self.messagingService.sendPoll(to=to, message=message, options=noticeOptions)

                if msgSid or len(sentPushMsgIds) > 0:
                    if msgSid:
                        notification['status'] = 'sent'
                        notification['messageSid'] = msgSid
                        notification['sentDate'] = helpers.localNow()
                    if sentPushMsgIds:
                        notification['sentPushMsgIds'] = sentPushMsgIds
    
                    self.cacheService.setNotification(tenantKey=notification['tenantKey'], target=target, id=notification['id'], notificationType=notificationType, to=notificationTo, timestamp=notification['timestamp'], value=notification)
            
            elif msgSid or len(sentPushMsgIds) > 0:
                if msgSid:
                    notification['status'] = 'sent'
                    notification['sentDate'] = helpers.localNow()
                    notification['messageSid'] = msgSid
                if sentPushMsgIds:
                    notification['sentPushMsgIds'] = sentPushMsgIds
                self.cacheService.setNotification(tenantKey=notification['tenantKey'], target=target, id=notification['id'], notificationType=notificationType, to=notificationTo, timestamp=notification['timestamp'], value=notification)
       
        except Exception as ex:
            self.logger.error(f'handleSingleNotification {refId}', ex, **globalRefereeDetail)

    async def getFieldAndCommuteDetails(self, globalRefereeDetail, tenantRefereeDetail, refereeGame, browser=None):
        noticeDetails = ''
        try:
            tenantKey = refereeGame['tenantKey']
            gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=refereeGame)
            fieldAddressDetails = None
            fieldTitle = gameDetail.get('field')
            if fieldTitle:
                field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldTitle)
            if field:
                fieldAddressDetails = field.get('addressDetails')
            originLocation = self.cacheService.getCachedKeyVal(tenantKey='GLOBAL', mobileNo=globalRefereeDetail['mobileNo'], propertyName='originLocation')
            if not originLocation or originLocation.get('expiredBy') < helpers.localNow():
                if not globalRefereeDetail.get('addressDetails'):
                    self.logger.warning(f'getFieldAndCommuteDetails {globalRefereeDetail["mobileNo"]} missing address details', **globalRefereeDetail)
                    return ''

                originLocation = {
                    'lng': globalRefereeDetail['addressDetails']['coordinates']['lng'],
                    'lat': globalRefereeDetail['addressDetails']['coordinates']['lat']
                }

            if originLocation and originLocation.get('lng') and originLocation.get('lat') and fieldAddressDetails:
                to_coordinates_lat = fieldAddressDetails['coordinates']['lat']
                to_coordinates_lng = fieldAddressDetails['coordinates']['lng']

                if 'commute' not in refereeGame:
                    refereeGame['commute'] = {}

                arriveAt = gameDetail['date'] + timedelta(seconds=-int(globalRefereeDetail["timeArrivalInAdvance"])*60)
                duration_secs, distance_meters = await self.tenantsOrgServices[tenantKey].getBaseWazeRoute(from_latitude=originLocation['lat'], from_longitude=originLocation['lng'], to_latitude=to_coordinates_lat, to_longitude=to_coordinates_lng, arriveAt=arriveAt, browser=browser)
                if duration_secs:
                    refereeGame['commute']['durationToField'] = duration_secs
                    durationStr = helpers.seconds_to_hms(duration_secs)
                    if durationStr[:3] == '00:':
                        durationStr = f'{durationStr[3:]} דקות'
                    else:
                        durationStr = f'{durationStr} שעות'
                    departDateTime = arriveAt + timedelta(seconds=-duration_secs)
                    departTimeStr = departDateTime.strftime("%H:%M")
                    if departTimeStr:
                        noticeDetails += f'\n\n*משך הנסיעה* הוא {durationStr}'
                        noticeDetails += f'\nכדי להגיע {globalRefereeDetail["timeArrivalInAdvance"]} דקות לפני המשחק כדאי לצאת בשעה {departTimeStr}'

                if distance_meters:
                    refereeGame['commute']['distanceToField'] = distance_meters
                    distance = int(distance_meters)/1000
                    noticeDetails += f'\n*המרחק* הוא {distance:.1f} קילומטרים'

                self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=tenantRefereeDetail['refId'], gamePk=refereeGame['gamePk'], value=refereeGame)
            
            #waze link
            noticeDetails += f'\n\n*קישור:* {fieldAddressDetails["wazeLink"]}'
            #field address
            noticeDetails += f'\n\n*כתובת:* {fieldAddressDetails["address"]}'
        except Exception as ex:
            self.logger.error(f'getFieldDetailsAndCommute {globalRefereeDetail["mobileNo"]}', ex, **globalRefereeDetail)
        
        return noticeDetails

    async def getCommuteDetailsAfterGame(self, globalRefereeDetail, tenantRefereeDetail, refereeGame, browser=None):
        noticeDetails = ''
        try:
            tenantKey = refereeGame['tenantKey']
            gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=refereeGame)
            fieldAddressDetails = None
            fieldTitle = gameDetail.get('field')
            if fieldTitle:
                field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldTitle)
            if field:
                fieldAddressDetails = field.get('addressDetails')
            destinationLocation = self.cacheService.getCachedKeyVal(tenantKey='GLOBAL', mobileNo=globalRefereeDetail['mobileNo'], propertyName='originLocation')
            #use home address
            if True or not destinationLocation or destinationLocation.get('expiredBy') < helpers.localNow():
                if not globalRefereeDetail.get('addressDetails'):
                    self.logger.warning(f'getCommuteDetailsAfterGame {globalRefereeDetail["mobileNo"]} missing address details', **globalRefereeDetail)
                    return ''

                destinationLocation = {
                    'lng': globalRefereeDetail['addressDetails']['coordinates']['lng'], 
                    'lat': globalRefereeDetail['addressDetails']['coordinates']['lat']
                }

            if destinationLocation and destinationLocation.get('lng') and destinationLocation.get('lat') and fieldAddressDetails:
                from_coordinates_lat = fieldAddressDetails['coordinates']['lat']
                from_coordinates_lng = fieldAddressDetails['coordinates']['lng']

                if 'commute' not in refereeGame:
                    refereeGame['commute'] = {}

                duration_from_game_secs, distance_from_game_meters = await self.tenantsOrgServices[tenantKey].getBaseWazeRoute(from_latitude=from_coordinates_lat, from_longitude=from_coordinates_lng, to_latitude=destinationLocation['lat'], to_longitude=destinationLocation['lng'], browser=browser)
                if duration_from_game_secs:
                    refereeGame['commute']['durationFromField'] = duration_from_game_secs
                if distance_from_game_meters:
                    refereeGame['commute']['distanceFromField'] = distance_from_game_meters

                self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=tenantRefereeDetail['refId'], gamePk=refereeGame['gamePk'], value=refereeGame)

                if refereeGame['commute'].get('distanceToField') and distance_from_game_meters:
                    totalDistance = int(refereeGame['commute']['distanceToField']) + distance_from_game_meters
                    noticeDetails = f'סה״כ מרחק הנסיעה הוא {totalDistance/1000:.2f} ק״מ'
        except Exception as ex:
            self.logger.error(f'getCommuteDetailsAfterGame {globalRefereeDetail["mobileNo"]}', ex, **globalRefereeDetail)

        return noticeDetails

    async def checkNotificationTime(self, dueDatetime, hoursInAdvance:float, reminderOffsetInMins:int):
        reminderInAdvanceInSecs = hoursInAdvance * 60 * 60
        offsetInSecs = reminderOffsetInMins * 60
        timeAfteDueDateInSecs = reminderOffsetInMins * 60
        if hoursInAdvance < 0:
            timeAfteDueDateInSecs = 24 * 60 * 60
        now = helpers.localNow()

        if dueDatetime is None or dueDatetime - timedelta(seconds=reminderInAdvanceInSecs + offsetInSecs) < now < dueDatetime + timedelta(seconds=timeAfteDueDateInSecs):
            return True
        
        return False

    async def createRefSixGame(self, tenantRefereeDetail, refereeGame, gameDetail):
        try:
            if tenantRefereeDetail.get('refSixEnabled', False) == False:
                return True, 'RefSix is not enabled'
            
            if refereeGame.get('refSixCreated', False) == True:
                return True, 'RefSix game already created'

            result = await self.tenantsOrgServices[tenantRefereeDetail['tenantKey']].createGameInRefSix(username=tenantRefereeDetail['refSixUsername'], password=tenantRefereeDetail['refSixPassword'], gameDetail=gameDetail)
            refereeGame['refSixCreated'] = result.get('success')
            self.cacheService.setRefereeGame(tenantKey=refereeGame['tenantKey'], refId=tenantRefereeDetail['refId'], gamePk=refereeGame['gamePk'], value=refereeGame)
            await self.messagingService.sendMessage(to=tenantRefereeDetail['mobileNo'], title=f'{gameDetail["gameTitle"]} RefSix', message=result.get('message'))
            return result.get('success'), result.get('message')
        except Exception as ex:
            self.logger.error(f'createRefSixGame {tenantRefereeDetail["mobileNo"]}', ex)        
            return False, ex.message

    async def postCompare(self, tenantKey, objType, refereeData, page):
        try:
            refId = refereeData['refId']
            mobileNo = refereeData['mobileNo']
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
            tenantNotifications = tenant.get('notifications', {})
            addedItemNotificationReminderInHrs = float(tenantNotifications.get('addedItem')) if tenantNotifications.get('addedItem') else None
            updated = False

            for itemPk in refereeData[objType].get('removed', []):
                addedItemNotification = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', id=itemPk, notificationType='addedItem', to=mobileNo)
                prevItem = refereeData[objType]['prevList'][itemPk]
                prevItem['state'] = 'removed'

                if addedItemNotification and addedItemNotificationReminderInHrs:
                    timeElapsed = helpers.localNow() - list(addedItemNotification.values())[0].get('created')
                    if timeElapsed.total_seconds() < abs(addedItemNotificationReminderInHrs) * 60 * 60:
                        prevItem['state'] = 'canceled'

                if objType == 'games':
                    refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', id=itemPk, status='created', to=mobileNo)
                    if refereeGamesNotifications:
                        for notification in refereeGamesNotifications.values():
                            notification['status'] = 'deleted'
                            self.cacheService.setNotification(tenantKey=tenantKey, target='refereeGames', id=itemPk, notificationType=notification['notificationType'], to=notification.get('to'), timestamp=notification['timestamp'], value=notification)
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=prevItem)
                    if gameDetail and mobileNo in gameDetail.get('activeGroupMobileNumbers', []):
                        gameDetail['activeGroupMobileNumbers'].remove(mobileNo)
                        self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'], gamePk=itemPk, value=gameDetail)

                    self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=itemPk, value=prevItem)
                    
                    addedItemNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', id=itemPk, notificationType='addedItem', to=mobileNo)
                    addedItemNotificationSent = len(addedItemNotifications) == 0 or any(notification for notification in addedItemNotifications.values() if notification.get('status') == 'sent')
                    if addedItemNotificationSent:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', id=itemPk, notificationType='removedItem', to=mobileNo, contextDate='created', status='created')
                    
                elif objType == 'reviews':
                    refereeReviewsNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', id=itemPk, status='created', to=mobileNo)
                    if refereeReviewsNotifications:
                        for notification in refereeReviewsNotifications.values():
                            notification['status'] = 'deleted'
                            self.cacheService.setNotification(tenantKey=tenantKey, target='refereeReviews', id=itemPk, notificationType=notification['notificationType'], to=notification.get('to'), timestamp=notification['timestamp'], value=notification)

                    self.cacheService.setRefereeReview(tenantKey=tenantKey, refId=refId, gamePk=itemPk, value=prevItem)
                    
                    addedItemNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', id=itemPk, notificationType='addedItem', to=mobileNo)
                    addedItemNotificationSent = len(addedItemNotifications) == 0 or any(notification for notification in addedItemNotifications.values() if notification.get('status') == 'sent')
                    if addedItemNotificationSent:
                        self.setNotification(tenantKey=tenantKey, target='refereeReviews', id=itemPk, notificationType='removedItem', to=mobileNo, contextDate='created', status='created')

                updated = True

            for itemPk in refereeData[objType].get('archived', []):
                prevItem = refereeData[objType]['prevList'][itemPk]
                if prevItem.get('state', 'active') == 'archived':
                    continue
                if objType == 'games':
                    prevItem['state'] = 'archived'
                    self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=itemPk, value=prevItem)
                    self.setNotification(tenantKey=tenantKey, target='refereeGames', id=itemPk, notificationType='archivedItem', to=mobileNo, contextDate='created', status='created')
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=prevItem)
                    if gameDetail and gameDetail.get('state', 'active') == 'active':
                        tournamentName = gameDetail['tournamentName']
                        tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
                        helpers.run_async_in_thread(self.tenantsOrgServices[tenantKey].refreshTournamentGames, tenantKey=tenantKey, tournamentName=tournamentName, round=gameDetail.get('round'), fixture=gameDetail.get('fixture'), fetchGamesUrls=True)
                        if tournament and tournament.get('section'):
                            helpers.run_async_in_thread(self.tenantsOrgServices[tenantKey].refreshLeaguesTables, tenantKey=tenantKey, tournamentName=tournamentName)

            objItemPKs = refereeData[objType]['added'] + refereeData[objType]['changed']
            if False:
                objItemPKs = refereeData[objType]['nonChanged']
            for itemPk in objItemPKs:
                if False and 'הכח' not in itemPk:
                    continue
                isNewItem = itemPk in refereeData[objType]['added']
                item = refereeData[objType]['currentList'][itemPk]
                prevItem = refereeData[objType]['prevList'].get(itemPk, {})

                if objType == 'games':
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=item)
                    item['state'] = 'active'
                    if item.get('date') >= helpers.localNow():
                        if False and isNewItem:
                            tournamentName = item['tournamentName']
                            helpers.run_async_in_thread(self.tenantsOrgServices[tenantKey].refreshTournamentGames, tenantKey=tenantKey, tournamentName=tournamentName, round=gameDetail.get('round'), fixture=gameDetail.get('fixture'), fetchSquads=False)
                        if item.get('status') != 'מאושר':
                            self.setNotification(tenantKey=tenantKey, target='refereeGames', id=itemPk, notificationType='addedItem', to=mobileNo, contextDate='created', reminderInHrs=addedItemNotificationReminderInHrs, status='created')
                        else:
                            self.setNotification(tenantKey=tenantKey, target='tournamentGames', id=itemPk, notificationType='updatedItem', contextDate='created', status='created')
                    if tenantRefereeDetail.get('refSixEnabled', False) == True and item.get('refSixCreated', False) == False:
                        template = { 'action': 'createrefsixgame', 'gameId': gameDetail.get('id'), 'status': 'created' }
                        self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=str(uuid.uuid4())[:16], value=template)
                    
                    if item.get('status', '') != prevItem.get('status', ''):
                        if item['status'] == 'מאושר':
                            item['approvedDate'] = helpers.localNow()
                        else:
                            item['declinedDate'] = helpers.localNow()
                    
                    self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=itemPk, value=item)
                
                elif objType == 'reviews':
                    item['state'] = 'active'
                    self.cacheService.setRefereeReview(tenantKey=tenantKey, refId=refId, gamePk=itemPk, value=item)
                    if isNewItem:
                        self.setNotification(tenantKey=tenantKey, target='refereeReviews', id=itemPk, notificationType='addedItem', to=mobileNo, contextDate='created', status='created')
                    else:
                        self.setNotification(tenantKey=tenantKey, target='refereeReviews', id=itemPk, notificationType='updatedItem', to=mobileNo, contextDate='created', status='created')

                updated = True

            if updated:
                self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, value=helpers.localNow(), propertyName=f'{objType}_lastUpdate')
            self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, value=helpers.localNow(), propertyName=f'{objType}_lastRun')

            self.logger.debug(f'postCompare: {objType}', **tenantRefereeDetail)
        
        except Exception as ex:
            self.logger.error(f'postCompare', ex, **tenantRefereeDetail)

    async def testGamesActions(self):
        tenantKey = 'il'
        refereeDetail = {
            "refId": "43679",
            "mobileNo": "+972547799979",
            "name": "יואב שחר"
        }
        gameDetail = {
            "date": "2025-09-09 10:00:00"
        }
        fieldAddressDetails = {
            "coordinates": {"lat": 31.768319, "lng": 35.213711},
            "address": "דרך בין ירושלים לבית שמשון",
            "wazeLink": "https://www.waze.com/ul?ll=31.768319,35.213711&z=17&entry=tt"
        }
        refereeGames = self.cacheService.getRefereeGames(tenantKey=tenantKey, refId=refereeDetail['refId'], fromDate=datetime.now() - timedelta(days=2), toDate=datetime.now() + timedelta(days=1), includeArchived=True)
        refereeData = {
            'refId': refereeDetail['refId'],
            'games': {
                'currentList': {
                    next(iter(refereeGames.keys())): next(iter(refereeGames.values()))
                }
            }
        }
        async with async_playwright() as p:
            browser = await OrgServiceBase.launchBrowser(p, headless=eval(os.getenv('browserHeadless') or 'True'))
            context = await OrgServiceBase.createContext(browser=browser)
            stealth = Stealth()
            await stealth.apply_stealth_async(context)
            page = await context.new_page()
            #noticeDetails = asyncio.run(refereeProcessService.getFieldDetailsAndCommute(refereeDetail=refereeDetail, gameDetail=gameDetail, fieldAddressDetails=fieldAddressDetails, page=page))
            #await refereeProcessService.gamesActions(objType='games', refereeData=refereeData, page=page)

    async def testNotifications(self):
        tenantKey = 'IL#handball#2025-26'
        noticeTitle = f'נא למלא דו״ח בפורטל'
        noticeDetails = f'{self.tenantsOrgServices[tenantKey].loginUrl}'
        await self.messagingService.sendMessage(to='+972547799979', message=noticeDetails, title=noticeTitle)

    async def testLogin(self):
        tenantKey = 'IL#handball#2025-26'
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo='+972527913939')
        async with async_playwright() as p:
            browser = await OrgServiceBase.launchBrowser(p, headless=eval(os.getenv('browserHeadless') or 'True'))
            context = await OrgServiceBase.createContext(browser=browser)
            page = await context.new_page()
            loginResult, loginMessage = await self.tenantsOrgServices[tenantKey].login(refereeDetail=refereeDetail, page=page)
            print(loginResult, loginMessage)

if __name__ == "__main__":
    app = None
    try:
        print("Hello RefereeProcessService")
        from shared.appContainer import AppContainer
        import shared.configurationDI as configDI
        appContainer = AppContainer()
        appContainer.config.from_dict(configDI.configDI)
        appContainer.init_resources()
        #handleRefereeData=appContainer.handle_referee_data()
        #handleRefereeData.loadActiveRefereeDetails()
        #refereeProcessService = RefereeProcessService(logger=appContainer.logger(), dbClient=appContainer.db_client(), messagingService=appContainer.messaging_service(), handleTournaments=appContainer.handle_tournaments(), handleRefereeData=appContainer.handle_referee_data(), handleUsers=appContainer.handle_users())
        #asyncio.run(refereeProcessService.testGamesActions())
        from shared.db import DynamodbClient
        rpc:RefereeProcessService = appContainer.referee_process_service()
        asyncio.run(rpc.testLogin())
        exit(0)
        dynamodbClient:DynamodbClient = appContainer.dynamodb_db_client()
        tournaments = dynamodbClient.getTournaments()
        exit(0)
        if True:
            for tournamentName, tournament in tournaments.items():
                games = dynamodbClient.getDict(tableName='tournamentGamesHistory', tournamentName=tournamentName)
                for gamePk, game in games.items():
                    gamePk = gamePk.replace('202526', '')
                    gamePk = gamePk.replace(f'#{tournamentName}','')
                    game['gamePk'] = gamePk
                    entityKey = game['entityKey']
                    game['entityKey'] = game['entityKey'].replace('202526', '')
                    lastCol = ''
                    for col, value in game.items():
                        if col.startswith('2025') and col > lastCol:
                            lastCol = col
                    if lastCol:
                        gameDetail = game[lastCol]
                        gameDetail['gamePk'] = gamePk
                        gameDetail['entityKey'] = entityKey.replace('202526', '')
                        dynamodbClient.setTournamentGame(tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                        pass
            pass
            exit(0)
        games = dynamodbClient.getTournamentGames(tournamentName=None)
        for gamePk, game in games.items():
            tournamentName = game['tournamentName']
            gamePk = gamePk.replace('202526', '')
            gamePk = gamePk.replace(f'#{tournamentName}','')
            game['gamePk'] = gamePk
            entityKey = game['entityKey']
            game['entityKey'] = game['entityKey'].replace('202526', '')
            game['entityKey'] = game['entityKey'].replace(f'{tournamentName}#{tournamentName}#', f'{tournamentName}#')
            dynamodbClient.setTournamentGame(tournamentName=tournamentName, gamePk=gamePk, value=game)
            dynamodbClient.delete(tableName='tournamentGames', entityKey=entityKey)
        pass
    except Exception as ex:
        print(f'Main Error:', ex)
        logging.exception()
        pass