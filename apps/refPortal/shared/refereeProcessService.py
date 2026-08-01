import logging
from typing import Optional
from collections.abc import Mapping
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo
import os
import uuid
import sys
import re
from pathlib import Path
from playwright.async_api import BrowserContext, Browser, Page
from playwright_stealth import Stealth
import asyncio

from pydantic import AwareDatetime
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.handleUsers import HandleUsers
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from shared.orgRelated import OrgServiceBase
from shared.db import CacheService
from shared.db.repositories import TenantRepository
from shared.messaging import MessagingService
from shared.commonHelper import CommonHelper
from shared.logger import Logger
from shared.orgRelated import OrgServiceFactory, MultiTenantSupport
from shared.configManager import ConfigManager
from shared import playwright_shared_browser
from shared.commute_service import CommuteService
from shared.db.models.enums import NotificationTypeKey

class RefereeProcessService():
    def __init__(self, logger:Logger, commonHelper:CommonHelper, cacheService:CacheService, multiTenantSupport:MultiTenantSupport, messagingService:MessagingService, handleTournaments:HandleTournaments, handleRefereeData:HandleRefereeData, handleUsers:HandleUsers, referees_data:tuple, orgServiceFactory:OrgServiceFactory, commuteService:Optional[CommuteService]=None, config:dict=None, tenantRepository:TenantRepository=None):
        self.logger = logger
        self.commonHelper = commonHelper
        self.cacheService = cacheService
        self.tenantRepository = tenantRepository
        self.multiTenantSupport = multiTenantSupport
        self.messagingService = messagingService
        self.handleTournaments = handleTournaments
        self.handleRefereeData = handleRefereeData
        self.handleUsers = handleUsers
        (self.globalRefereesByMobile, self.refereesByRefId, self.refereesByMobile, self.refereesByGuid, self.globalRefereesByName, self.globalRefereesById, self.refereesById, self.refereesByInternalId) = referees_data
        self.orgServiceFactory = orgServiceFactory
        if config is None:
            import shared.configurationDI as configurationDI
            self.config = configurationDI.configDI
        elif isinstance(config, dict):
            self.config = config
        elif isinstance(config, Mapping):
            self.config = dict(config)
        else:
            self.config = {}
        
        self.logger.sendMessage = self.messagingService.greenApiSendMessage

        self.app = ConfigManager.get_config_value(self.config, 'app', 'APP')

        self.tenantsOrgServices:dict[str, OrgServiceBase] = {}
        for tenantKey in self.tenantRepository.get_tenants().keys():
            orgService = self.orgServiceFactory.get_org_service_by_tenant(tenantKey=tenantKey)
            self.tenantsOrgServices[tenantKey] = orgService
        self.generateReports = ConfigManager.get_config_bool(self.config, 'generateReports', False)
        self.single_playwright_browser = ConfigManager.get_config_bool(
            self.config, 'singlePlaywrightBrowser', True
        )

        self.concurrentPages = ConfigManager.get_config_int(self.config, 'concurrentPages', 4)
        self.checkGames = ConfigManager.get_config_bool(self.config, 'checkGames', True)
        self.checkReviews = ConfigManager.get_config_bool(self.config, 'checkReviews', True)
        self.daysToArchive = ConfigManager.get_config_int(self.config, 'daysToArchive', 1)

        self.apiServiceUrlBase = ConfigManager.get_config_value(self.config, 'apiServiceUrlBase')
        self.approveGames = ConfigManager.get_config_bool(self.config, 'approveGames', False)
        self.avoidChatGroups = ConfigManager.get_config_bool(self.config, 'avoidChatGroups', True)
        self.chatGroups4Singles = ConfigManager.get_config_bool(self.config, 'chatGroups4Singles', False)

        self.swLevel = ConfigManager.get_config_value(self.config, 'swLevel', 'debug') or 'debug'
        #self.season = ConfigManager.get_config_value(self.config, 'season') or (self.config.get('tenant') or {}).get('season')

        _route = str(ConfigManager.get_config_value(self.config, 'commuteRouteProvider', 'waze') or 'waze').strip().lower()
        self._commute_route_provider = 'google' if _route == 'google' else 'waze'
        self._commute_service = commuteService
        
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

        self.logger.info(f'refereeProcessService starts... process time per referee={ConfigManager.get_config_int(self.config, "processTimeout", 30)}')

    async def startProcessByMobileNos(self, mobileNos:list):
        activeTenantKeys = [ tenantKey for tenantKey, tenant in self.tenantRepository.get_tenants().items() if tenant.active ]
        anyChangeResult = False
        for tenantKey in activeTenantKeys:
            referees = { mobileNo: self.handleRefereeData.activeRefereesByMobile[mobileNo] for mobileNo in mobileNos if tenantKey in self.handleRefereeData.activeRefereesByMobile[mobileNo].get('activeTenantKeys', [])}
            portalAllowedReferees = { mobileNo: referee for mobileNo, referee in referees.items() if referee.get('portalAllow', False) == True }
            anyChange = await self.startProcessByReferees(tenantKey=tenantKey, referees=portalAllowedReferees)
            if anyChange:
                anyChangeResult = True
        return anyChangeResult
    
    async def _run_referee_batch_with_browser(
        self,
        tenantKey: str,
        referees: dict,
        p,
        browser: Browser,
        *,
        close_browser_after: bool,
    ):
        any_change = False
        context = None
        try:
            context = await OrgServiceBase.createContext(browser=browser)
            stealth = Stealth()
            await stealth.apply_stealth_async(context)
            if ConfigManager.get_config_bool(self.config, 'tracing', False):
                helpers.initTracing(p)
            mobileNos = list(referees.keys())
            self.logger.info(f'Running referee batch with browser for tenantKey={tenantKey} referees={mobileNos}')
            if self.single_playwright_browser:
                for mobileNo in referees:
                    try:
                        one = await self.startProcessByMobileNo(
                            tenantKey=tenantKey, mobileNo=mobileNo, context=context
                        )
                    except Exception as ex:
                        self.logger.error('Start Process', ex)
                        one = False
                    if isinstance(one, BaseException):
                        self.logger.error('Start Process', one)
                        continue
                    if one:
                        any_change = True
                        break
            else:
                referees_tasks = {
                    asyncio.create_task(
                        self.startProcessByMobileNo(
                            tenantKey=tenantKey, mobileNo=mobileNo, context=context
                        )
                    ): mobileNo
                    for mobileNo in referees
                }
                self.logger.debug('before tasks gather')
                tasks_results = await asyncio.gather(*referees_tasks, return_exceptions=True)
                self.logger.debug('after tasks gather')
                for task_result in tasks_results:
                    if isinstance(task_result, BaseException):
                        self.logger.error('Start Process', task_result)
                        continue
                    if task_result:
                        any_change = True
                        break
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception as close_ex:
                    self.logger.warning('context.close after batch failed: %s', close_ex)
            if close_browser_after and browser is not None:
                try:
                    await browser.close()
                except Exception as close_ex:
                    self.logger.warning('browser.close after batch failed: %s', close_ex)
        return any_change

    async def startProcessByReferees(self, tenantKey:str, referees:dict):
        anyChange = False

        try:
            self.processTimeout = ConfigManager.get_config_int(self.config, 'processTimeout', 30) * len(referees)
            for refId in referees:
                if self.generateReports:
                    await self.handleRefereeData.collectGamesSummary(tenantKey=tenantKey, refId=refId)
                    await self.handleRefereeData.getGamesEvents(tenantKey=tenantKey, refId=refId)

            if referees:
                mobileNos = list(referees.keys())
                helpers.stopwatchStart(f'Process time')
                headless = ConfigManager.get_config_bool(self.config, 'browserHeadless', True)
                use_proxy = tenantKey.startswith('IL#football#') and False
                try:
                    if self.single_playwright_browser:
                        playwright_shared_browser.enter_shared_referee_batch()
                    try:
                        if self.single_playwright_browser:
                            self.logger.debug('Using shared Playwright browser (one per process)...')
                            p, browser = await playwright_shared_browser.get_shared_browser(
                                headless=headless, useProxy=use_proxy
                            )
                            anyChange = await self._run_referee_batch_with_browser(
                                tenantKey,
                                referees,
                                p,
                                browser,
                                close_browser_after=False,
                            )
                        else:
                            async with OrgServiceBase.playwright_driver_context() as p:
                                self.logger.info('Launching browser...')
                                browser = await OrgServiceBase.launchBrowser(
                                    p,
                                    headless=headless,
                                    useProxy=use_proxy,
                                )
                                anyChange = await self._run_referee_batch_with_browser(
                                    tenantKey,
                                    referees,
                                    p,
                                    browser,
                                    close_browser_after=True,
                                )
                        self.logger.info(
                            f'#processed tenantKey={tenantKey} referees={len(referees)}'
                        )
                    finally:
                        if self.single_playwright_browser:
                            playwright_shared_browser.leave_shared_referee_batch()
                finally:
                    try:
                        helpers.stopwatchStop(f'Process time', level=self.swLevel)
                    except KeyError:
                        pass

        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError as ex:
            self.logger.error('Start Process', ex)
        except Exception as ex:
            self.logger.error('Start Process', ex)

        finally:
            pass

        return anyChange

    async def startProcessByMobileNo(self, tenantKey, mobileNo, context:BrowserContext):
        anyChange = False
        refereeTask = None
        try:
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            if tenantRefereeDetail.get('status') != 'active':
                self.logger.warning(f'Referee {mobileNo} not found in active referees')
                return False
            assigner = 'assigner' in tenantRefereeDetail.get('roles', [])
            refereeTask = asyncio.create_task(self.checkRefereeTask(tenantKey=tenantKey, mobileNo=mobileNo, context=context))
            timeout = self.processTimeout if not assigner else None 
            if tenantRefereeDetail.get('refSixEnabled', False) == True:
                timeout += 30
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
            tenant = self.tenantRepository.get_tenant(tenant_key=tenantKey)
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
            mixedRefereeDetail = globalRefereeDetail | tenantRefereeDetail
            self.logger.debug(f'start of CheckRefereeTask#1-{self.app}', refereeDetail=tenantRefereeDetail)
            
            anyChange = False
            self.logger.debug(f'seq={tenantRefereeDetail.get("seq")}', refereeDetail=tenantRefereeDetail)
        
            testResult = helpers.testConnection(self.tenantsOrgServices[tenantKey].baseUrl, 443)
            if testResult:
                self.logger.warning(f'TestConnection: {testResult}')

            windowIsOpen = self.messagingService.checkIf24HoursWindowIsOpen(mobileNo=mobileNo)
            refereeData = { 'mobileNo': mobileNo, 'divertMobileNo': tenantRefereeDetail.get('divertMobileNo'), 'refId': tenantRefereeDetail['refId'], 'refereeId': tenantRefereeDetail.get('refereeId'), 'name': globalRefereeDetail['name'], 'windowIsOpen': windowIsOpen, 'loggedIn': False, 'checkData': False}
            self.tenantsOrgServices[tenantKey].setFetchDates(refereeData=refereeData)
            
            page = await context.new_page()
            loginResult = True
            if not (tenant.assigner_collection if tenant else False) or 'assigner' in tenantRefereeDetail.get('roles', []):
                self.logger.info('before login')
                loginResult, loginMessage = await self.tenantsOrgServices[tenantKey].login(refereeDetail=mixedRefereeDetail, page=page)
                self.logger.debug(f'after login = {loginResult}', refereeDetail=globalRefereeDetail)
                if loginResult == False:
                    message = f'שלום {mobileNo} {globalRefereeDetail["name"]}, {loginMessage}'
                    loginFails = int(self.cacheService.getCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginFails') or '0')
                    self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginFails', value=loginFails + 1)
                    if loginFails >= 5:
                        self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginOnHold', value=helpers.localNow(), ttlSeconds=15*60)
                        self.logger.error(f'Login failed, RefId={tenantRefereeDetail["refId"]}, loginFails={loginFails + 1}', None, refereeDetail=tenantRefereeDetail)

                        if loginMessage == 'Login failed':
                            statusAfterFailedLogin = (tenant.status_after_failed_login if tenant else None) or 'suspended'
                            self.cacheService.setRefereeProperty(tenantKey=tenantKey, refereeId=tenantRefereeDetail.get('refereeId'), propertyName='status', value=statusAfterFailedLogin)
                            self.cacheService.setRefereeProperty(tenantKey=tenantKey, refereeId=tenantRefereeDetail.get('refereeId'), propertyName='statusChangedDate', value=helpers.localNow())
                            if statusAfterFailedLogin != 'active':
                                message += f', יש לעדכן את הסיסמא (לאחר בדיקה בפורטל) ולעדכן באמצעות הקישור הבא:\nhttps://refereex.com/changePassword'
                            toMobileNo = tenantRefereeDetail.get('divertMobileNo') or mobileNo
                            allowMessageSending = self.messagingService.allowMessageSending(to=toMobileNo)
                            if allowMessageSending:
                                msgSid = await self.messagingService.sendMessage(to=list(set([toMobileNo, self.messagingService.adminMobile])), message=message, title='התחברות נכשלה')

                    # Login failed, so there's no session to scrape a fresh list with - but the
                    # referee should still get their pending games/reviews notifications based on
                    # whatever was already cached from the last successful run, rather than missing
                    # a cycle entirely just because this login attempt failed.
                    await self.sendNotificationsWithoutLogin(tenantKey=tenantKey, refereeData=refereeData, tenant=tenant, page=page)
                    return
                else:
                    self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginFails', value=0)                
                    refereeData['loggedIn'] = True
                    refereeData['checkData'] = True
            else:
                refereeData['checkData'] = True

            if False:
                await self.tenantsOrgServices[tenantKey].getPayments(refereeDetail=tenantRefereeDetail, page=page)
            for objType in (tenant.obj_types if tenant else []):
                if objType == 'games' and self.checkGames or objType == 'reviews' and self.checkReviews:
                    changed = await self.checkRefereeData(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                    if changed:
                        anyChange = True
                        if objType == 'games':
                            if self.generateReports:
                                await self.handleRefereeData.collectGamesSummary(tenantKey=tenantKey, refId=mobileNo)
                                await self.handleRefereeData.getGamesEvents(tenantKey=tenantKey, refId=mobileNo)
            
            self.logger.debug(f'end of CheckRefereeTask#1-{self.app}', refereeDetail=tenantRefereeDetail)

        except asyncio.CancelledError as ex:
            self.logger.warning(f"checkRefereeTrask {mobileNo} received cancellation request.")
            raise  # Reraise to propagate cancellation
        except Exception as ex:
            self.logger.error(f'CheckRefereeTask mobileNo={mobileNo}', ex, refereeDetail=tenantRefereeDetail)

        finally:
            if page:
                await page.close()
                page = None

        helpers.stopwatchStop(swName, level=self.swLevel)
        return anyChange

    # Called instead of the normal checkRefereeData path when login fails - there's no session to
    # scrape a fresh currentList with, so getListForReferee/compare/postCompare (and its
    # added/removed abort-run protections) are skipped entirely rather than fed a fake empty
    # currentList. handleNotifications is still driven off whatever prevList is already cached, so
    # a referee doesn't miss a full notification cycle just because this login attempt failed.
    async def sendNotificationsWithoutLogin(self, tenantKey, refereeData, tenant, page):
        for objType in (tenant.obj_types if tenant else []):
            if objType == 'games' and self.checkGames or objType == 'reviews' and self.checkReviews:
                try:
                    await self.handleRefereeData.getRefereeData(tenantKey=tenantKey, objType=objType, refereeData=refereeData)
                    if refereeData[objType].get('prevList') and self.dataDic[objType].get('handleNotifications'):
                        await self.dataDic[objType]['handleNotifications'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, browser=page.context.browser if page else None)
                except Exception as ex:
                    self.logger.error('sendNotificationsWithoutLogin', ex, refereeData=refereeData)

    async def checkRefereeData(self, tenantKey, objType, refereeData, page):
        mobileNo = refereeData['mobileNo']
        tenant = self.tenantRepository.get_tenant(tenant_key=tenantKey)
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeData.get('refereeId'))
        refereeId = refereeData.get('refereeId')

        changed = False
        try:
            self.logger.info(f'Checking {objType}...', refereeDetail=tenantRefereeDetail)
            
            swName = f'checkRefereeData={refereeData["name"]}{objType}'
            helpers.stopwatchStart(swName)
            swLast = 0
            def logSwPhase(phase):
                nonlocal swLast
                elapsed = helpers.stopwatchStop(swName)
                self.logger.info(f'sw {swName} {phase}={elapsed - swLast}ms (total={elapsed}ms)')
                swLast = elapsed

            # get prevList
            await self.handleRefereeData.getRefereeData(tenantKey=tenantKey, objType=objType, refereeData=refereeData)

            found = False
            cnt = 0
            if 'assigner' in tenantRefereeDetail.get('roles', []):
                if not ConfigManager.get_config_bool(self.config, 'skipCollectItemsForAssigner', False):
                    await self.tenantsOrgServices[tenantKey].collectItemsForAssigner(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)

            getListSuccessful = await self.tenantsOrgServices[tenantKey].getListForReferee(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
            if getListSuccessful == False:
                return False
            logSwPhase('getList')

            updatedList = refereeData[objType]['currentList']

            if updatedList and len(updatedList) > 0:
                found = True
                cnt = len(updatedList)
                self.logger.debug(f'parse objType={objType} found={found} updatedList={cnt}', refereeDetail=tenantRefereeDetail)
            else:
                self.logger.info(f"{objType} no results found", refereeDetail=tenantRefereeDetail)

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
                        prevItem['gameDetail'] = self.cacheService.getGameDetail(game=prevItem)
                        pass
            logSwPhase('mergePrevList')
            if updatedList != None:
                if self.dataDic[objType].get('postParse'):
                    await self.dataDic[objType]['postParse'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)

                logSwPhase('postParse')
                if self.dataDic[objType].get('compare'):
                    await self.dataDic[objType]['compare'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                    logSwPhase('compare')

                    now = helpers.localNow()
                    abortRun = False
                    anyRemovals = (
                        len(refereeData[objType]['removed']) > 0 and 
                        (len(refereeData[objType]['removed']) >= (tenant.minimum_removals_to_ignore if tenant else 1) or objType == 'reviews' and cnt == len(refereeData[objType]['removed'])
                    ))
                    if anyRemovals:
                        blockRemovalsStarted = self.cacheService.getCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovalsStarted_{objType}')
                        skipAbortRun = self.cacheService.getCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'skipAbortRun_{objType}')
                        if blockRemovalsStarted and now - blockRemovalsStarted > timedelta(seconds=30*60) or skipAbortRun and skipAbortRun == 'yes':
                            self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovalsStarted_{objType}', value=None, ttlSeconds=1)

                        elif blockRemovalsStarted:
                            abortRun = True
                        
                        else:
                            abortRun = True
                            self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovalsStarted_{objType}', value=now)

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
                            self.messagingService.sendInteractiveMessage(to=self.messagingService.adminMobile, question=f'לשופט {refereeData["name"]} {mobileNo} מזהה {refereeId} יש {len(refereeData[objType]['removed'])} מחיקות {removedText},\nהאם להמשיך במחיקה ?', promptButtons=promptButtons, customData=customData)
                            self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'skipAbortRun_{objType}', value='no', ttlSeconds=30*60)
                            self.logger.warning(f'something happened with {refereeId} {objType} total removals={len(refereeData[objType]['removed'])}')

                    else:
                        self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'blockRemovals_{objType}', value=now, ttlSeconds=1)
                                                
                    if abortRun:
                        return False

                    changed = len(refereeData[objType]['added']) > 0 or len(refereeData[objType]['removed']) > 0 or len(refereeData[objType]['changed']) > 0 or len(refereeData[objType]['archived']) > 0
                    if True or changed:
                        self.logger.info(f"{objType} A:{len(refereeData[objType]['added'])} R:{len(refereeData[objType]['removed'])} C:{len(refereeData[objType]['changed'])} H:{len(refereeData[objType]['archived'])} I:{cnt}", refereeDetail=tenantRefereeDetail)
                        await self.dataDic[objType]['postCompare'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                    logSwPhase('postCompare')
                    if not changed:
                        lastUpdate = self.cacheService.getRefereeProperty(tenantKey=tenantKey, mobileNo=refereeData['mobileNo'], propertyName=f'{objType}_lastUpdate')
                        self.logger.info(f'No {objType} update since {lastUpdate} I:{cnt}', refereeDetail=tenantRefereeDetail)
            
                if (refereeData[objType].get('currentList') or refereeData[objType].get('prevList')) and self.dataDic[objType].get('handleNotifications'):
                    await self.dataDic[objType]['handleNotifications'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, browser=page.context.browser if page else None)
                logSwPhase('handleNotifications')

                helpers.stopwatchStop(f'{swName}', level=self.swLevel)
        except Exception as ex:
            self.logger.error('CheckRefereeData', ex, refereeData=refereeData)
        finally:
            pass
            
        return changed

    async def postProcessTemplate(self, template, tenantRefereeDetail, tournamentGameId, title, message, failureMessage, page=None):
        tenantKey = template['tenantKey']
        templateAction = template['action'].lower()
        msgSid = template['msgSid']
        mobileNo = tenantRefereeDetail['mobileNo']
        targetMobileNo = template['data']['targetMobileNo'] if template.get('data', {}).get('targetMobileNo') else mobileNo
        targetRefereeId = self.globalRefereesByMobile.get(targetMobileNo, {}).get('refereeId') or tenantRefereeDetail.get('refereeId')

        if template['status'] == 'created' and failureMessage:
            template['retries'] = int(template.get('retries', '0')) + 1
            if template['retries'] > 3:
                if page:
                    await helpers.takeScreenshot(page=page, refereeDetail=tenantRefereeDetail, tag=f'{template["action"]}')
                template['status'] = 'deferred'
                template['updated'] = helpers.localNow()
                message = failureMessage
                self.logger.warning(f"{msgSid} ניסיון {template['retries']} של ביצוע הפעולה נכשל", refereeDetail=tenantRefereeDetail)

        self.cacheService.setRefereeTemplate(tenantKey=tenantKey, refereeId=tenantRefereeDetail.get('refereeId'), msgSid=msgSid, value=template)
        if title and message:
            self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=templateAction, target_to=targetRefereeId, contextDate='created', title=title, message=message)

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
            localNow = helpers.localNow()
            mobileNo = refereeData['mobileNo']
            refId = refereeData['refId']
            refereeId = refereeData.get('refereeId')
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeId)

            # filter by status = created
            sortedTemplates = helpers.sortDictByProperty(obj=self.cacheService.getRefereeTemplates(tenantKey=tenantKey, refereeId=refereeId, status='created', forceReload=True), property='created', reverse=True)
            self.logger.debug(f"{len(sortedTemplates)}", refereeDetail=tenantRefereeDetail)
            if sortedTemplates:
                for template in sortedTemplates.values():
                    msgSid = template['msgSid']
                    callPostProcess = True
                    self.logger.debug(f"{msgSid}", refereeDetail=tenantRefereeDetail)
                    self.logger.debug(f"{msgSid} {template.get('repliedButtonId')} {template['action']}", refereeDetail=tenantRefereeDetail)
                    if template['created'] < helpers.localNow() - timedelta(weeks=2):
                        continue
                    if template.get('status') != 'created':
                        continue

                    title = None
                    message = None
                    failureMessage = None
                    gamePk = None
                    tournamentGameId = None
                    targetMobileNo = mobileNo
                    templateAction = template['action'].lower()

                    if objType == 'games':
                        if templateAction == 'approvegame':
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            tournamentGameId = gameDetail.get('id') if gameDetail else None
                            if not gameDetail or not refereeGame:
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                if False and (not refereeGame.get('cells') or not refereeGame['cells'].get('status')):
                                    continue
                                cellSelector = refereeGame.get('cells', {}).get('status')
                                result, message = self._org_service_result(
                                    await self.tenantsOrgServices[tenantKey].approveGame(
                                        refereeData=refereeData, gameId=gameId, statusCell=cellSelector, page=page
                                    ),
                                    default_message='approveGame returned no result',
                                )
                                template['message'] = message
                                self.logger.info(f"processTemplates {templateAction} {msgSid} gameId={gameId} {gameDetail['gameTitle']} result={result}", refereeDetail=tenantRefereeDetail)
                                title = f'משחק {gameDetail["gameTitle"]}'
                                if result:
                                    template['status'] = 'completed'
                                    template['updated'] = localNow
                                    refereeGame['approvedDate'] = localNow
                                    helpers.delProperties(refereeGame, 'cells')
                                    self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=refereeId, gamePk=gamePk, value=refereeGame)
                                    message = f'השיבוץ אושר בפורטל'
                                else:
                                    failureMessage = f'אישור השיבוץ נכשל'

                        elif templateAction == 'declinegame':
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            tournamentGameId = gameDetail.get('id') if gameDetail else None
                            if not gameDetail or not refereeGame:
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                if not refereeGame.get('cells') or not refereeGame['cells'].get('status'):
                                    continue
                                cellSelector = refereeGame.get('cells', {}).get('status')
                                result, message = self._org_service_result(
                                    await self.tenantsOrgServices[tenantKey].declineGame(
                                        refereeData=refereeData, gameId=gameId, statusCell=cellSelector, page=page
                                    ),
                                    default_message='declineGame returned no result',
                                )
                                template['message'] = message
                                self.logger.info(f"processTemplates {templateAction} {msgSid} gameId={gameId} {gameDetail['gameTitle']} result={result}", refereeDetail=tenantRefereeDetail)
                                title = f'משחק {gameDetail["gameTitle"]}'
                                if result:
                                    template['status'] = 'completed'
                                    template['updated'] = localNow
                                    refereeGame['declinedDate'] = localNow
                                    self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=refereeId, gamePk=gamePk, value=refereeGame)
                                    message = f'השיבוץ נדחה בפורטל'
                                else:
                                    failureMessage = f'דחיית השיבוץ נכשלה'

                        elif templateAction in ['postgameupdate', 'gamereport']:
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            tournamentGameId = gameDetail.get('id') if gameDetail else None
                            if not gameDetail:
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                data = template.get('data')
                                if data == None:
                                    continue
                                orgService = self.tenantsOrgServices[tenantKey]
                                if hasattr(orgService, 'submitUnfinishedGameReport'):
                                    # IFA: locate the row in the live 'משחקים אשר דוחות עבורם לא
                                    # נקלטו או לא הושלמו' table (rather than navigating straight
                                    # to gameDetail['internalGameId']) so the click-through path
                                    # matches what a referee sees on the site.
                                    result, message = self._org_service_result(
                                        await orgService.submitUnfinishedGameReport(
                                            refereeDetail=tenantRefereeDetail, page=page, data=data,
                                            date=gameDetail.get('date'), tournamentName=gameDetail.get('tournamentName'),
                                            homeTeamName=gameDetail.get('homeTeamName'), guestTeamName=gameDetail.get('guestTeamName'),
                                            fixture=gameDetail.get('fixture'), field=gameDetail.get('field'),
                                        ),
                                        default_message='submitUnfinishedGameReport returned no result',
                                    )
                                else:
                                    result, message = self._org_service_result(
                                        await orgService.postGameUpdate(
                                            refereeDetail=tenantRefereeDetail, gameId=gameId, data=data, page=page
                                        ),
                                        default_message='postGameUpdate returned no result',
                                    )
                                template['message'] = message
                                self.logger.info(f"processTemplates {templateAction} {msgSid} gameId={gameId} {gameDetail['gameTitle']} result={result}", refereeDetail=tenantRefereeDetail)
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
                                    #self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=gamePk, notificationType=template['action'], target_to=mobileNo, contextDate='created', title=title, message=msg)
                                else:
                                    failureMessage = f'עדכון תוצאת המשחק נכשל' if templateAction == 'postgameupdate' else 'העלאת דו״ח המשחק נכשלה'
                        
                        elif templateAction == 'createrefsixgame':
                            gameId, refereeGame, gameDetail, gamePk = getGameDetail(template)
                            tournamentGameId = gameDetail.get('id') if gameDetail else None
                            if not gameDetail or not refereeGame:
                                template['status'] = 'cancelled'
                                template['updated'] = localNow
                            else:
                                callPostProcess = False
                                await self.createRefSixGame(
                                    template=template,
                                    tenantRefereeDetail=tenantRefereeDetail,
                                    refereeGame=refereeGame,
                                    gameDetail=gameDetail,
                                    browser=page.context.browser if page else None,
                                )
                                '''
                                template['message'] = message
                                if success:
                                    template['status'] = 'completed'
                                    template['updated'] = localNow
                                    self.logger.info(message, refereeDetail=tenantRefereeDetail)
                                else:
                                    failureMessage = message
                                    self.logger.warning(message, refereeDetail=tenantRefereeDetail)
                                '''
                        else:
                            template['status'] = 'deferred'
                            template['updated'] = localNow

                    if templateAction == 'forcesend':
                        if template['objType'] != objType:
                            continue
                        refereeData[objType]['prevList'] = {}
                        template['status'] = 'completed'
                        template['updated'] = helpers.localNow()
                        self.logger.info(f"{template['msgSid']} objType={objType} ישלח מחדש", refereeDetail=tenantRefereeDetail)
                
                    elif templateAction == 'changepassword':
                        targetMobileNo = template['data']['targetMobileNo'] if template.get('data', {}).get('targetMobileNo') else mobileNo
                        targetRefereeId = self.globalRefereesByMobile.get(targetMobileNo, {}).get('refereeId')
                        targetTenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=targetRefereeId)
                        targetGlobalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', refereeId=targetRefereeId)
                        result = False
                        if targetTenantRefereeDetail:
                            title = 'עדכון סיסמא'
                            result, message = await self.tenantsOrgServices[tenantKey].changePassword(refereeDetail=tenantRefereeDetail, targetRefereeDetail=targetTenantRefereeDetail, page=page)
                            template['message'] = message
                            if result:
                                template['status'] = 'completed'
                                template['updated'] = localNow
                                message = f"סיסמת שופט {targetMobileNo} {targetGlobalRefereeDetail['name']} עודכנה"
                                self.logger.info(message, refereeDetail=tenantRefereeDetail)
                            else:
                                message = f"עדכון סיסמא לשופט {targetMobileNo} {targetGlobalRefereeDetail['name']} נכשל"
                                self.logger.warning(message, refereeDetail=tenantRefereeDetail)
                        if result == False:
                            template['status'] = 'deferred'
                            template['updated'] = localNow
                    
                    if callPostProcess:
                        await self.postProcessTemplate(template=template, tenantRefereeDetail=tenantRefereeDetail, tournamentGameId=tournamentGameId, title=title, message=message, failureMessage=failureMessage, page=page)
                    
                    if template['status'] == 'created' and failureMessage:
                        template['retries'] = int(template.get('retries', '0')) + 1
                        if template['retries'] > 3:
                            await helpers.takeScreenshot(page=page, refereeDetail=tenantRefereeDetail, tag=f'{template["action"]}')
                            template['status'] = 'deferred'
                            template['updated'] = localNow
                            message = failureMessage
                            self.logger.warning(f"{msgSid} ניסיון {template['retries']} של ביצוע הפעולה נכשל", refereeDetail=tenantRefereeDetail)
                    
                    self.cacheService.setRefereeTemplate(tenantKey=tenantKey, refereeId=refereeId, msgSid=msgSid, value=template)
                    if title and message:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=gamePk, notificationType=templateAction, target_to=targetMobileNo, contextDate='created', title=title, message=message)
                    
        except Exception as ex:
            self.logger.error(f'processTemplates', ex, refereeDetail=tenantRefereeDetail)

    @staticmethod
    def _org_service_result(value, default_message='operation failed'):
        """Org service methods must return (bool, str); guard against None from incomplete implementations."""
        if isinstance(value, tuple) and len(value) >= 2:
            return bool(value[0]), value[1] if value[1] is not None else default_message
        if value is None:
            return False, default_message
        return False, default_message

    def setNotification(self, tenantKey:str, target:str, target_id:str, notificationType:str, target_to=None, contextDate:str='gameDate', reminderInHrs:float=None, status:str=None, title:str=None, message:str=None, upsert:bool=False, delete:bool=False):
        notifications = self.cacheService.getNotifications(tenantKey=tenantKey, target=target, target_id=target_id, notificationType=notificationType, target_to=target_to, status=status)
        if not notifications and upsert and not delete:
            all_for_item = self.cacheService.getNotifications(tenantKey=tenantKey, target=target, target_id=target_id) or {}
            notifications = {
                k: v for k, v in all_for_item.items()
                if v.get('notificationType') == notificationType and (target_to is None or v.get('target_to') == target_to)
            }
        if delete:
            if notifications:
                for notification in notifications.values():
                    notification['status'] = 'deleted'
                    self.cacheService.setNotification(tenantKey=tenantKey, target=target, target_id=target_id, notificationType=notificationType, target_to=target_to, value=notification)
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
            created_items = [(k, n) for k, n in notifications.items() if n.get('status') == 'created']
            if upsert and len(created_items) > 1:
                created_items.sort(key=lambda x: x[1].get('created') or 0)
                keep_id = created_items[0][1].get('id')
                for _k, extra in created_items[1:]:
                    extra['status'] = 'deleted'
                    self.cacheService.setNotification(
                        tenantKey=tenantKey, target=target, target_id=target_id, notificationType=notificationType,
                        target_to=target_to, value=extra,
                    )
                notifications = {k: v for k, v in notifications.items() if v.get('status') != 'created' or v.get('id') == keep_id}

            createdFound = False
            for notification in notifications.values():
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
            # No 'id' here - this is genuinely new, no row exists yet. postgresClient.setNotifications
            # uses a present value['id'] to update that exact row directly; target_id (the game/item
            # this notification is about) is a different thing entirely and must not be mistaken
            # for the notification's own row id.
            notifications = {0: {'contextDate': contextDate, 'reminderInHrs': reminderInHrs, 'status': 'created', 'title': title, 'message': message, 'target': target, 'notificationType': notificationType, 'tenantKey': tenantKey}}

        for notification in notifications.values():
            self.cacheService.setNotification(tenantKey=tenantKey, target=target, target_id=target_id, notificationType=notificationType, target_to=target_to, value=notification)

        return next(iter(notifications.values()))

    def getEffectiveNotificationSetting(self, tenantKey: str, refereeId: int, typeKey: str, refereeDetail: Optional[dict] = None) -> Optional[dict]:
        """Resolves the effective config for one notification type, cascading:
        notification_types catalog default -> tenants.notification_settings[typeKey] override ->
        referees.notification_overrides[typeKey] override. Consumed by newer features (commute
        reminder actions, time-to-leave push) - the existing hardcoded reminder dispatch
        (gameFirstReminder/gameLastReminder/refereeLastReminder above) does not call this yet.
        Returns None (excluded) whenever the FINAL resolved 'enabled' is false - checked once
        after all three layers merge, not per-layer, so a disable at any layer (catalog global
        kill switch, tenant, or referee) excludes it, and a later layer can still explicitly
        re-enable what an earlier layer disabled (e.g. a referee opting back into a type their
        tenant disabled by default). A dict with enabled=False embedded would be truthy in
        Python, so callers doing `if setting:` need this collapsed to None, not left as a dict.
        refereeDetail: pass the caller's own already-fetched, already-normalized referee row
        (see _normalize_referee_row_from_get) to skip the internal lookup - getReferees hits the
        DB on every call (referee-specific, not cached), so a caller resolving many typeKeys for
        the same referee (e.g. getRefereeNotificationSettings's per-catalog-type loop) should
        fetch it once and pass it through here instead of one DB round trip per type."""
        catalogEntry = self.tenantRepository.get_notification_type(type_key=typeKey)
        effective = {
            'enabled': catalogEntry.enabled if catalogEntry is not None else True,
            'contextTime': catalogEntry.context_time if catalogEntry else 'gameStart',
            'offsetMinutes': catalogEntry.offset_minutes if catalogEntry else 0,
            'channels': catalogEntry.channels if catalogEntry else [],
        }

        tenant = self.tenantRepository.get_tenant(tenant_key=tenantKey)
        tenantOverride = ((tenant.notification_settings or {}).get(typeKey) if tenant else None) or {}
        effective.update({k: v for k, v in tenantOverride.items() if v is not None})

        if refereeDetail is None:
            refereeDetail = self._normalize_referee_row_from_get(
                self.cacheService.getReferees(tenantKey='GLOBAL', refereeId=refereeId)
            ) if refereeId else None
        refereeOverride = ((refereeDetail or {}).get('notificationOverrides', {}).get(typeKey)) or {}
        effective.update({k: v for k, v in refereeOverride.items() if v is not None})

        return effective if effective['enabled'] else None

    def setRefereeNotificationOverride(self, refereeId: int, typeKey: str, enabled: Optional[bool] = None, offsetMinutes: Optional[int] = None) -> None:
        """Merges enabled/offsetMinutes into referees.notification_overrides[typeKey], preserving
        any other field already on that entry and every other type's entry untouched."""
        refereeDetail = self._normalize_referee_row_from_get(
            self.cacheService.getReferees(tenantKey='GLOBAL', refereeId=refereeId)
        )
        if not refereeDetail:
            return
        overrides = dict(refereeDetail.get('notificationOverrides') or {})
        entry = dict(overrides.get(typeKey) or {})
        if enabled is not None:
            entry['enabled'] = enabled
        if offsetMinutes is not None:
            entry['offsetMinutes'] = offsetMinutes
        overrides[typeKey] = entry
        self.cacheService.setRefereeProperty(tenantKey='GLOBAL', refereeId=refereeId, propertyName='notificationOverrides', value=overrides)

    def getRefereeNotificationSettings(self, tenantKeys: list, refereeId: int) -> list:
        """Dynamic, catalog-driven replacement for the old fixed 5-field reminder settings: one
        entry per notification_type in the catalog - regardless of whether any of the referee's
        tenants has it enabled, so the referee can always see and set every type - carrying the
        referee's own effective value (resolved tenant-agnostically, tenantKey='GLOBAL', since
        this is one personal preference shared across all the referee's tenants - mirroring the
        old dedicated-column design, just no longer hardcoded to 3 specific types). hoursInAdvance
        is always a positive "how many hours in this type's natural direction" number - the UI
        doesn't need to know the before/after sign convention, only
        setRefereeNotificationOverride's caller (clientUpdateUserDetails) does, to convert it
        back to offsetMinutes."""
        catalog = self.tenantRepository.get_notification_types()
        # get_notification_types() runs the raw catalog dict through the NotificationType model,
        # and model construction drops any key not declared as a model field - properties JSONB
        # keys (label/hint) get flattened to the top level by _merge_props before that happens,
        # so they never survive into catalogEntry.properties. Read them from the un-modeled
        # cacheService dict instead, where the flattened label/hint are still present.
        rawCatalog = self.cacheService.getNotificationTypes()

        refereeDetail = self._normalize_referee_row_from_get(
            self.cacheService.getReferees(tenantKey='GLOBAL', refereeId=refereeId)
        ) if refereeId else None
        refereeOverrides = (refereeDetail or {}).get('notificationOverrides') or {}

        result = []
        for typeKey, catalogEntry in catalog.items():
            setting = self.getEffectiveNotificationSetting(tenantKey='GLOBAL', refereeId=refereeId, typeKey=typeKey, refereeDetail=refereeDetail)
            contextTime = catalogEntry.context_time
            # Preserve the referee's own configured timing even while disabled (matches the old
            # dedicated-column behavior, where toggling the enabled checkbox off never cleared
            # the hours field) - only fall back to the catalog default if they never set one.
            offsetMinutes = (refereeOverrides.get(typeKey) or {}).get('offsetMinutes')
            if offsetMinutes is None:
                offsetMinutes = setting['offsetMinutes'] if setting else catalogEntry.offset_minutes
            hoursInAdvance = offsetMinutes / 60 if contextTime == 'gameEnd' else -offsetMinutes / 60
            result.append({
                'typeKey': typeKey,
                'label': rawCatalog.get(typeKey, {}).get('label', typeKey),
                'hint': rawCatalog.get(typeKey, {}).get('hint', ''),
                'contextTime': contextTime,
                'enabled': setting is not None,
                'hoursInAdvance': hoursInAdvance,
                'seq': catalogEntry.seq,
            })
        result.sort(key=lambda r: r['seq'])
        return result

    def _normalize_referee_row_from_get(self, data, mobile_no=None):
        """Normalize getReferees / getRefereeProperties result to a single referee row dict."""
        if not data or not isinstance(data, dict):
            return None
        if mobile_no and len(data) == 1 and mobile_no in data and isinstance(data[mobile_no], dict):
            return data[mobile_no]
        if 'refId' in data or 'internalRefereeId' in data:
            return data
        if len(data) == 1:
            inner = next(iter(data.values()))
            if isinstance(inner, dict):
                return inner
        return data

    def _normalize_ref_name_for_match(self, name):
        if not name or not isinstance(name, str):
            return ''
        return ' '.join(name.strip().split()).casefold()

    def _internal_referee_id_from_merged_referee_row(self, detail):
        """IFA/LIGA internal id from a tenant/global merged referee row."""
        if not detail or not isinstance(detail, dict):
            return None
        v = detail.get('internalRefereeId')
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
        return None

    def _mobile_no_for_global_referee_row(self, gr):
        """Global referee row may omit mobileNo; resolve from globalRefereesByMobile identity."""
        if not isinstance(gr, dict):
            return None
        m = gr.get('mobileNo')
        if m:
            return m
        for mob, gref in (self.handleUsers.globalRefereesByMobile or {}).items():
            if gref is gr:
                return mob
        return None

    def _find_internal_referee_id_by_name_for_tenant(self, tenant_key, normalized_name):
        """Resolve IFA internal referee id by display name via globalRefereesByName (tenant-scoped)."""
        if not normalized_name:
            return None
        candidates = []
        for gname, refs in (self.handleUsers.globalRefereesByName or {}).items():
            if self._normalize_ref_name_for_match(gname) != normalized_name:
                continue
            for gr in refs or []:
                if not isinstance(gr, dict):
                    continue
                if tenant_key not in (gr.get('tenantKeys') or []):
                    continue
                mob = self._mobile_no_for_global_referee_row(gr)
                iid = self._internal_referee_id_from_merged_referee_row(
                    {**gr, 'mobileNo': mob} if mob else gr)
                if iid is None and mob:
                    raw_t = self.cacheService.getReferees(
                        tenantKey=tenant_key, mobileNo=mob, forceReload=False)
                    trow = self._normalize_referee_row_from_get(raw_t, mob)
                    if isinstance(trow, dict):
                        iid = self._internal_referee_id_from_merged_referee_row({**gr, **trow, 'mobileNo': mob})
                if iid is not None:
                    candidates.append(iid)
        if not candidates:
            return None
        if len(set(candidates)) > 1:
            self.logger.warning(
                f'multiple internalRefereeId for name match tenant={tenant_key} name={normalized_name!r}: {candidates}')
        return candidates[0]

    def _enrich_ref_detail_internal_id_from_name(self, tenant_key, ref_detail):
        """If crew row has no IFA id yet, copy it from tenant/global tables by * שם match."""
        if ref_detail.get('refereeId') is not None or ref_detail.get('internalRefereeId') is not None:
            return
        nm = ref_detail.get('* name')
        norm = self._normalize_ref_name_for_match(nm)
        if not norm:
            return
        iid = self._find_internal_referee_id_by_name_for_tenant(tenant_key, norm)
        if iid is not None:
            ref_detail['internalRefereeId'] = iid
            ref_detail['refereeId'] = iid

    def _referee_lookup_kwargs(self, phoneIdentifier):
        """'* phone' now holds either a real mobile number (E.164, starts with '+') or, for
        mobile-less referees, the bare referees.id as a string - resolve to the right
        getReferees()/get_referee_game_by_pk() kwarg accordingly."""
        s = str(phoneIdentifier)
        if s.isdigit():
            return {'refereeId': int(s)}
        return {'mobileNo': phoneIdentifier}

    async def postParseGames(self, tenantKey, objType, refereeData, page):
        async def updateGroupName(gameDetail):
            try:
                chatGroupId = gameDetail.get('chatGroupId')
                groupName = f'{gameDetail["tournamentName"]} {gameDetail["gameTitle"]}'
                
                if gameDetail.get('date'):
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
        globalRefereeDetail = self._normalize_referee_row_from_get(
            self.cacheService.getReferees(tenantKey='GLOBAL', refereeId=refereeData.get('refereeId')), mobileNo) or {}
        tenantRefereeDetail = self._normalize_referee_row_from_get(
            self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeData.get('refereeId')), mobileNo) or {}
        tenant = self.tenantRepository.get_tenant(tenant_key=tenantKey)

        try:
            items = refereeData[objType]['currentList']
            sortedItemsByDate = helpers.sortDictByProperty(obj=items, property='date')
            
            for gamePk, refereeGame in sortedItemsByDate.items():
                tournamentName = refereeGame['tournamentName']
                tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName, game=refereeGame)
                if not tournament:
                    tournament = self.handleTournaments.createTournament(tenantKey=tenantKey, tournamentName=tournamentName)
    
                section = self.tenantRepository.get_section(tenant_key=tenantKey, section_name=tournament.get('section'))

                refereeGame['tournamentName'] = tournamentName

                groupName = f'{refereeGame["tournamentName"]} {refereeGame["gameTitle"]}'

                gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName, game=refereeGame)
                gameDetail = self.cacheService.getGameDetail(game=refereeGame, forceReload=True)
                if not gameDetail:
                    gameDetail = { 'gamePk': gamePk, 'tournamentName': tournamentName, 'season': tenant.season, 'groupName': groupName, 'archived': False }
                refereeGame['gameDetail'] = gameDetail
                gameDetail['gameId'] = gameDetail.get('gameId', str(uuid.uuid4())[:8])
                gameDetail['groupMobileNumbers'] = gameDetail.get('groupMobileNumbers', [])
                gameDetail['gameDuration'] = gameDetail.get('gameDuration', gameDuration)

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
                reviewerReferee = None
                isMainReferee = False
                isSecretaryReferee = False
                refereeIds = []
                sortedReferees = sorted(referees, key=lambda refDetail: (lambda r: r.order or '99' if r else '99')(self.tenantRepository.get_role(tenant_key=tenantKey, role_name=refDetail['role'])))
                refereesList = []
                for refDetail in sortedReferees:
                    roleName = refDetail['role']
                    role = self.tenantRepository.get_role(tenant_key=tenantKey, role_name=roleName.replace('*', ''))

                    refPhone = refDetail.get('* phone')
                    if refPhone:
                        refPhoneLookupKwargs = self._referee_lookup_kwargs(refPhone)
                        raw_tenant = self.cacheService.getReferees(tenantKey=tenantKey, **refPhoneLookupKwargs)
                        gameTenantRefereeDetail = self._normalize_referee_row_from_get(raw_tenant, refPhone)
                        if not gameTenantRefereeDetail:
                            self._enrich_ref_detail_internal_id_from_name(tenantKey, refDetail)
                        gameGlobalRefereeId = gameTenantRefereeDetail.get('refereeId') if gameTenantRefereeDetail else None
                        gameRefereeGame = None
                        if gameGlobalRefereeId:
                            refereeIds.append(gameGlobalRefereeId)

                        if refPhone == mobileNo:
                            refereeGame['roleId'] = role.id if role else None
                            refereeGame['role'] = role.role_name if role else None
                            if role and role.role_type == 'main':
                                isMainReferee = True
                            if role and role.role_type == 'secretary':
                                isSecretaryReferee = True
                            if role and role.role_type == 'reviewer' and gameTenantRefereeDetail:
                                refereeGame['reviewer'] = gameTenantRefereeDetail.get('refId') or refPhone

                            refDetail['* status'] = refDetail.get('* status') or refereeGame.get('status')
                            refDetail['* address'] = globalRefereeDetail.get('address') or refDetail.get('* address')
                        else:
                            if gameGlobalRefereeId:
                                gameRefereeGame = self.cacheService.get_referee_game_by_pk(tenantKey=tenantKey, gamePk=gamePk, refereeId=gameGlobalRefereeId)
                            else:
                                gameRefereeGame = self.cacheService.get_referee_game_by_pk(tenantKey=tenantKey, gamePk=gamePk, **refPhoneLookupKwargs)
                            refDetail['* status'] = gameRefereeGame.get('status') if gameRefereeGame else refDetail.get('* status')
                            refDetail['* address'] = refereesDetails.get(refPhone, {}).get('address') or refDetail.get('* address')

                        if role and role.role_type == 'main':
                            if gameTenantRefereeDetail and gameGlobalRefereeId:
                                mainReferees.append(gameGlobalRefereeId)

                        if role and role.role_type == 'secretary':
                            if gameTenantRefereeDetail and gameGlobalRefereeId:
                                secretaryReferee = gameGlobalRefereeId

                        if role and role.role_type == 'reviewer':
                            if gameTenantRefereeDetail and gameGlobalRefereeId:
                                reviewerReferee = gameGlobalRefereeId

                        if not (role and role.role_type == 'reviewer'):
                            # Only real mobile numbers can receive WhatsApp messages - a bare
                            # referee id (mobile-less referee) has nothing to adjust/message.
                            if 'mobileNo' in refPhoneLookupKwargs:
                                refereesMobileNos[MessagingService.adjustMobileNo(refPhone)] = refDetail.get('* name')
                        else:
                            refDetail['reviewer'] = True
                            del sortedReferees[roleName]
                            continue

                    refereesList.append(refDetail)
                
                gameDetail['gameDuration'] = gameDuration
                
                chatGroupId = None

                if jsonHelper.save_to_json(gameDetail.get('referees')) != jsonHelper.save_to_json(refereesList):
                    gameDetail['updateGroupMembers'] = True
                    gameDetail['referees'] = refereesList
                gameDetail['mainReferees'] = mainReferees
                gameDetail['secretaryReferee'] = secretaryReferee
                gameDetail['reviewerReferee'] = reviewerReferee
                gameDetail['removedRefereeIds'] = gameDetail.get('removedRefereeIds', [])
                gameDetail['refereeIds'] = refereeIds
                
                teamNames = refereeGame['gameTitle']       
                teams = teamNames.split(' - ')
                gameDetail['homeTeamName'] = refereeGame.get('homeTeamName', teams[0].strip())
                gameDetail['guestTeamName'] = refereeGame.get('guestTeamName', teams[1].strip())
                gameDetail['date'] = refereeGame['date'] = helpers.ensure_aware(refereeGame['date'])
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
                optionalTags = [ 'homeTeamName', 'guestTeamName', 'internalGameId', 'homeTeamScore', 'guestTeamScore', 'gameResult', 'comment' ]
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

                checkSendGreenApiMessages = self.messagingService.checkSendGreenApiMessages(to=globalRefereeDetail)
                createChatGroup = self.messagingService.checkSendGreenApiMessages(to=globalRefereeDetail) and not self.avoidChatGroups \
                    and (isMainReferee or globalRefereeDetail.get('alwaysCreateChatGroup', False)) \
                    and (len(referees) > 1 or self.chatGroups4Singles and globalRefereeDetail.get('ignoreGroup4Singles', False) == False) \
                    and timedelta(seconds=0) < gameDetail['date'] - helpers.localNow() <= timedelta(days=7)
                    #and (True or not 'אולמות' in tournamentName)
                groupMobileNumbers = refereesMobileNos if gameDetail.get('mainReferees', []) or gameDetail.get('secretaryReferee', []) or globalRefereeDetail.get('alwaysCreateChatGroup', False) else { mobileNo: globalRefereeDetail['name'] }
                activeGroupMobileNumbers = [ mobileNo for mobileNo in refereesMobileNos.keys() if self.refereesByMobile.get(tenantKey, {}).get(mobileNo) ]
                gameDetail['activeGroupMobileNumbers'] = activeGroupMobileNumbers

                result = self.cacheService.setTournamentGame(tournamentGameId=gameDetail.get('id'), tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                if result[1]:
                    gameDetail = result[0]
                tournamentGameId = gameDetail.get('id')
                refereeId = refereeData.get('refereeId')
                gameFirstReminderSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='gameFirstReminder')
                commuteReminderSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='refereeLastReminder')

                #gameFirstReminder
                if gameFirstReminderSetting:
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameFirstReminder, reminderInHrs=-gameFirstReminderSetting['offsetMinutes'] / 60, upsert=True)
                else:
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameFirstReminder, delete=True)

                #refereeLastReminder & gameLastReminder
                if refereeGame.get('state') == 'active':
                    if commuteReminderSetting:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeLastReminder, target_to=refereeId, reminderInHrs=-commuteReminderSetting['offsetMinutes'] / 60, upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeLastReminder, delete=True)
                if len(referees) > 1:
                    if commuteReminderSetting:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameLastReminder, reminderInHrs=-commuteReminderSetting['offsetMinutes'] / 60, upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameLastReminder, delete=True)

                #gameLineupsAnnounced
                if 'אימון' not in tournamentName:
                    gameLineupsSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='gameLineupsAnnounced')
                    if gameLineupsSetting:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameLineupsAnnounced, reminderInHrs=-gameLineupsSetting['offsetMinutes'] / 60, upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameLineupsAnnounced, delete=True)

                #refereeGameReport
                self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameReport, delete=True)
                self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameUpdate, delete=True)
                if isMainReferee or isSecretaryReferee:
                    refereeGameReportSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='refereeGameReport')
                    if refereeGameReportSetting:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameReport, target_to=refereeId, reminderInHrs=-refereeGameReportSetting['offsetMinutes'] / 60, upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameReport, target_to=refereeId, status='created', delete=True)

                    if not (section and section.skip_referee_game_update_reminder):
                        refereeGameUpdateSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='refereeGameUpdate')
                        if refereeGameUpdateSetting:
                            self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameUpdate, target_to=refereeId, reminderInHrs=-refereeGameUpdateSetting['offsetMinutes'] / 60, upsert=True)
                        else:
                            self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameUpdate, target_to=refereeId, status='created', delete=True)

                refereeCommuteGameUpdateSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='refereeCommuteGameUpdate')
                if refereeCommuteGameUpdateSetting:
                    self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeCommuteGameUpdate, target_to=refereeId, reminderInHrs=-refereeCommuteGameUpdateSetting['offsetMinutes'] / 60, upsert=True)
                else:
                    self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeCommuteGameUpdate, target_to=refereeId, status='created', delete=True)
                
                chatGroupId = gameDetail.get('chatGroupId')
                self.logger.debug(f'createChatGroup={createChatGroup} checkSendGreenApiMessages={checkSendGreenApiMessages} avoidChatGroups={self.avoidChatGroups} chatGroupId={chatGroupId} groupName={groupName} groupMobileNumbers={groupMobileNumbers} isMainReferee={isMainReferee}')
                if createChatGroup:
                    # Create chat group, set main referee as admin, set profile, invite participants
                    if not chatGroupId:
                        groupResponse = await self.messagingService.greenApiClient.handleAction('createGroup', {'groupName':groupName, 'tos':list(groupMobileNumbers.keys())})
                        chatGroupId = groupResponse.get('chatId') if groupResponse else None
                        gameDetail['chatGroupId'] = chatGroupId
                        if chatGroupId:
                            changed = self.cacheService.setTournamentGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                            if isMainReferee:
                                await self.messagingService.greenApiClient.handleAction('setGroupAdmin', {'chatGroupId': chatGroupId, 'to': mobileNo})

                            gameDetail['updateGroup'] = True
                    
                    if chatGroupId and gameDetail.get('updateGroup', False):
                        try:
                            #self.logger.info(f'libraqm support: {features.check("raqm")}', refereeDetail)
                            groupJpg = helpers.createHebrewTextImage(gameDetail)
                            if os.path.exists(groupJpg):
                                await self.messagingService.greenApiClient.handleAction('setGroupPicture', {'chatGroupId': chatGroupId, 'pictureFile': groupJpg})
                        except Exception as ex:
                            self.logger.error(f'setGroupPicture gamePk={gameDetail["gamePk"]} cg={chatGroupId}', ex, refereeDetail=globalRefereeDetail)

                if createChatGroup and chatGroupId and len(referees) > 1:
                    chatGroupCreatedSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='chatGroupCreated')
                    if chatGroupCreatedSetting:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.chatGroupCreated, contextDate='created', upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.chatGroupCreated, delete=True)

                    transportationPollSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='transportationPoll')
                    if transportationPollSetting:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.transportationPoll, reminderInHrs=48, upsert=True)
                    else:
                        self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.transportationPoll, delete=True)
                else:
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.chatGroupCreated, delete=True)                    
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.transportationPoll, delete=True)

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

                result = self.cacheService.setTournamentGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                refereeGame['gameDetail'] = result[0]

            for gamePk, refereeGame in refereeData[objType]['prevList'].items():
                gameDetail = refereeGame.get('gameDetail', {}) or self.cacheService.getGameDetail(game=refereeGame)
                if gamePk not in refereeData[objType]['currentList'].keys():
                    await updateGroupName(gameDetail=gameDetail)
                    tournamentName = gameDetail.get('tournamentName')
                    self.cacheService.setTournamentGame(tournamentGameId=gameDetail.get('id'), tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)

            sw1 = helpers.stopwatchStop(swName)
            gamesReportsObjType = 'gamesReports'
            if gamesReportsObjType in (tenant.obj_types if tenant else []):
                getListSuccessful = await self.tenantsOrgServices[tenantKey].getListForReferee(tenantKey=tenantKey, objType=gamesReportsObjType, refereeData=refereeData, page=page)
                if getListSuccessful == True:
                    gamesReports = refereeData[gamesReportsObjType]['currentList']
                    for gamePk, refereeReportGame in gamesReports.items():
                        refereeReportGame['gamePk'] = gamePk
                        gameDetail = self.cacheService.getGameDetail(game=refereeReportGame)
                        if not gameDetail:
                            continue
                        tournamentGameId = gameDetail.get('id')
                        gameDetail['gameReportStatus'] = 'pending'
                        
                        isMainReferee = tenantRefereeDetail.get('refereeId') in gameDetail.get('mainReferees', [])
                        isSecretaryReferee = tenantRefereeDetail.get('refereeId') == gameDetail.get('secretaryReferee')
                        if isMainReferee or isSecretaryReferee:
                            gameReportNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameReport, target_to=refereeData.get('refereeId'))
                            shouldCreateNotification = True
                            now = helpers.localNow()
                            for notification in gameReportNotifications.values():
                                if notification['status'] == 'created':
                                    shouldCreateNotification = False
                                    break
                                if now - notification['updated'] < timedelta(hours=24):
                                    shouldCreateNotification = False
                                    break
                            if shouldCreateNotification:
                                # Effective settings (catalog/tenant.notification_settings/referee override
                                # cascade), not the legacy tenant.notifications dict this duplicate path used
                                # to read directly - see getEffectiveNotificationSetting.
                                refereeGameReportSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeData.get('refereeId'), typeKey='refereeGameReport')
                                if refereeGameReportSetting:
                                    self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeGameReport, target_to=refereeData.get('refereeId'), reminderInHrs=-refereeGameReportSetting['offsetMinutes'] / 60, upsert=True)
                        
                        if refereeReportGame.get('internalGameId'):
                            gameDetail['internalGameId'] = refereeReportGame['internalGameId']
                        if refereeReportGame.get('gameReportUrl'):
                            gameDetail['gameReportUrl'] = refereeReportGame['gameReportUrl']
                        self.cacheService.setTournamentGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, tournamentName=refereeReportGame['tournamentName'], gamePk=gamePk, value=gameDetail)
                        #refereeData[gamesReportsObjType][gameDetail['id']] = refereeReportGame

                    completedGamePks = list(set(gamePk for gamePk, refereeGame in refereeData[objType]['prevList'].items() if refereeGame.get('state', 'active') in ('active', 'archived')) - set(gamesReports.keys()))
                    for gamePk in completedGamePks:
                        refereeGame = refereeData[objType]['prevList'][gamePk]
                        gameDetail = self.cacheService.getGameDetail(game=refereeGame)
                        tournamentGameId = gameDetail.get('id') if gameDetail else None
                        isMainReferee = tenantRefereeDetail.get('refereeId') in gameDetail.get('mainReferees', [])
                        isSecretaryReferee = tenantRefereeDetail.get('refereeId') == gameDetail.get('secretaryReferee')
                        if isMainReferee or isSecretaryReferee:
                            gameDetail['gameReportStatus'] = 'completed'
                            refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, status='created', target_to=refereeData.get('refereeId'))
                            if refereeGamesNotifications:
                                for notification in refereeGamesNotifications.values():
                                    notificationType = notification['notificationType']
                                    if notificationType in [NotificationTypeKey.refereeGameUpdate, NotificationTypeKey.refereeGameReport]:
                                        notification['status'] = 'deleted'
                                        self.cacheService.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=notificationType, target_to=refereeData.get('refereeId'), value=notification)

            sw2 = helpers.stopwatchStop(swName)

            if self.dataDic[objType].get('processTemplates'):
                await self.dataDic[objType]['processTemplates'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
                
            for gamePk, refereeGame in refereeData[objType]['currentList'].items():
                if 'cells' in refereeGame:
                    del refereeGame['cells']
            pass
        except Exception as ex:
            self.logger.error(f'postParseGames', ex, refereeDetail=globalRefereeDetail)
            raise ex

    async def postParseReviews(self, tenantKey, objType, refereeData, page):
        refereeDetail = None
        try:
            mobileNo = refereeData['mobileNo']
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeData.get('refereeId'))
            numOfReviews = len(refereeData[objType]['currentList'])
            i = 0

            for reviewPk, review in refereeData[objType]['currentList'].items():
                prevReview = refereeData[objType]['prevList'].get(reviewPk) 
                if prevReview:
                    review['gameId'] = prevReview['gameId']
                else:
                    review['gameId'] = str(uuid.uuid4())[:8]

                review['no.'] = f'{numOfReviews-i}'
                review['gameTitle'] = review['gameTitle']
                review['date'] = datetime.strptime(review['dateText'], "%d/%m/%y")
                if review.get('cells'):
                    del review['cells']
                i += 1

            if self.dataDic[objType].get('processTemplates'):
                await self.dataDic[objType]['processTemplates'](tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)

        except Exception as ex:
            self.logger.error(f'postParseReviews', ex, refereeDetail=refereeDetail)

    async def compareItems(self, tenantKey, objType, refereeData, page):
        refereeDetail = None
        try:
            mobileNo = refereeData['mobileNo']
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeData.get('refereeId'))

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
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=currentGameDetail['tournamentName'], game=currentItem)
                    if tournament:
                        rule = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament.get('rules'))
                        includeReviewer = rule.include_reviewer if rule else False
                prevItemText = generateDetailsFunc(tenantKey=tenantKey, gameDetail=currentItem | currentGameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
                refereeData[objType]['addedText'] += f'{prevItemText}\n'

            #archive
            candidateToRemoveFromPrevList = {}
            candidateToArchiveFromPrevList = {}
            if 'removeFilter' in self.dataDic[objType]:
                for pk, prevItem in activePrevList.items():
                    # Manual games (see apply_manual_games.py / postgresClient.setTournamentGame)
                    # have no federation page to scrape - they'd otherwise look identical to a
                    # real removal every cycle. Only reconciliation (which archives the manual
                    # stand-in once the scraper finds the real game) or the referee's own explicit
                    # delete may remove one - never this generic scrape-diff path, in any
                    # manual_status.
                    if objType == 'games' and (prevItem.get('gameDetail') or {}).get('isManual'):
                        continue
                    # future game should be removed
                    gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=prevItem['tournamentName'], game=prevItem)
                    # if future game
                    if prevItem.get('date') >= now:
                        if prevItem.get('state', 'active') == 'removed':
                            continue
                        candidateToRemoveFromPrevList[pk] = prevItem
                    # if after game ended + 10 minutes
                    elif now >= prevItem.get('date') + timedelta(minutes=gameDuration + 60):
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

            #Changed/Nonchanged
            changedList = {}
            nonChangedList = {}
            potentialChangePks = sorted(list(set(activePrevList.keys()) & set(currentList.keys())), key=lambda gamePk: currentList[gamePk].get('date'))
            for pk in potentialChangePks:
                prevItem = activePrevList[pk]
                prevGameDetail = prevItem.get('gameDetail') or {}
                currentItem = currentList[pk]
                if objType == 'games' and 'gameDetail' not in currentItem:
                    gameDetail = self.cacheService.getGameDetail(game=currentItem)
                    currentItem['gameDetail'] = gameDetail
                    self.logger.error(f'compareList {objType} pk={pk} missing gameDetail', refereeDetail=refereeDetail)
                currentGameDetail = currentItem['gameDetail'] if objType == 'games' else {}
                includeReferees = True
                includeReviewer = False
                if objType == 'games':
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=currentItem['tournamentName'], game=currentItem)
                    if tournament:
                        rule = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament.get('rules'))
                        includeReviewer = rule.include_reviewer if rule else False
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
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=currentItem['tournamentName'], game=currentItem)
                    if tournament:
                        rule = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament.get('rules'))
                        includeReviewer = rule.include_reviewer if rule else False
                currentItemText = generateDetailsFunc(tenantKey=tenantKey, gameDetail=currentItem | currentGameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
                refereeData[objType]['changedText'] += f'{currentItemText}\n'

        except Exception as ex:
            self.logger.error(f'compareList {objType}', ex, refereeDetail=refereeDetail)

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
        refereeId = refereeData['refereeId']
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeId)
        globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', refereeId=refereeId)

        async def _notifications_work(browser_for_notifications):
            tenant = self.tenantRepository.get_tenant(tenant_key=tenantKey)
            skipAvailabilityNotifications = tenant.skip_availability_notifications if tenant else []
            
            allowMessageSending = self.messagingService.allowMessageSending(to=globalRefereeDetail)

            localTime = datetime.now(ZoneInfo(ConfigManager.get_config_value(self.config, 'TZ', 'UTC')))
            localHour = localTime.hour
            defaultAvailableFromHour = tenant.default_available_from_hour if tenant else 8
            defaultAvailableToHour = tenant.default_available_to_hour if tenant else 21
            allowDefaultAvailability = True
            if defaultAvailableFromHour <= defaultAvailableToHour and (localHour < defaultAvailableFromHour or localHour > defaultAvailableToHour) \
                        or defaultAvailableFromHour > defaultAvailableToHour and (localHour > defaultAvailableFromHour and localHour < defaultAvailableToHour):
                allowDefaultAvailability = False

            if False and not allowMessageSending:
                self.logger.warning(f'handleNotifications, mobileNo={mobileNo}, out of message acceptance limitation', refereeDetail=tenantRefereeDetail)
                return
                        
            items = refereeData[objType]['currentList']
            for itemPk, item in refereeData[objType]['prevList'].items():
                if itemPk not in refereeData[objType]['currentList'].keys():
                    items[itemPk] = item
            sortedItemsByDate = helpers.sortDictByProperty(obj=items, property='date')
            sortedItemsByDate[None] = { 'tenantKey': 'GLOBAL', 'date': helpers.localNow() }
            for itemPk, item in sortedItemsByDate.items():
                gameDetail = self.cacheService.getGameDetail(game=item) or {}
                tournamentGameId = gameDetail.get('id')
                tournamentName = gameDetail.get('tournamentName')
                gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName, game=item)
                self.logger.debug(f"notifications {item.get('date')}", refereeDetail=tenantRefereeDetail)

                refereeGamesNotifications = None
                tournamentGamesNotifications = None
                notifications = None
                if objType == 'games':
                    if item.get('state', 'active') == 'removed':
                        refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, status='created', target_to=refereeId)
                        if refereeGamesNotifications:
                            for notification in refereeGamesNotifications.values():
                                if notification.get('notificationType') != 'removedItem':
                                    notification['status'] = 'deleted'
                                    self.cacheService.setNotification(tenantKey=notification['tenantKey'], target='refereeGames', target_id=tournamentGameId, notificationType=notification['notificationType'], target_to=refereeId, value=notification)

                    refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=item.get('tenantKey', tenantKey), target='refereeGames', target_id=tournamentGameId, status='created', target_to=refereeId)
                    tournamentGamesNotifications = {}
                    if item.get('state', 'active') == 'active':
                        tournamentGamesNotifications = self.cacheService.getNotifications(tenantKey=item.get('tenantKey', tenantKey), target='tournamentGames', target_id=tournamentGameId, status='created') if item.get('state', 'active') != 'removed' else None
                    notifications:dict = helpers.merge_nested_dicts(refereeGamesNotifications, tournamentGamesNotifications)
                elif objType == 'reviews':
                    if item.get('state', 'active') == 'removed':
                        refereeReviewsNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, status='created', target_to=refereeId)
                        if refereeReviewsNotifications:
                            for notification in refereeReviewsNotifications.values():
                                if notification.get('notificationType') != 'removedItem':
                                    notification['status'] = 'deleted'
                                    self.cacheService.setNotification(tenantKey=notification['tenantKey'], target='refereeReviews', target_id=tournamentGameId, notificationType=notification['notificationType'], target_to=refereeId, value=notification)

                    notifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, status='created', target_to=refereeId)
                pass
                seen_notification_keys = set()
                for key, notification in notifications.items():
                    notificationType = notification['notificationType']
                    dedupe_key = (notification.get('target'), notificationType, notification.get('target_to'))
                    if dedupe_key in seen_notification_keys:
                        notification['status'] = 'deleted'
                        self.cacheService.setNotification(
                            tenantKey=notification['tenantKey'],
                            target=notification['target'],
                            target_id=tournamentGameId,
                            notificationType=notificationType,
                            target_to=notification.get('target_to'),
                            value=notification,
                        )
                        continue
                    seen_notification_keys.add(dedupe_key)
                    available = allowMessageSending or notificationType in skipAvailabilityNotifications and allowDefaultAvailability
                    if not available:
                        continue
                    gameDuration = self.handleTournaments.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName, game=item)
                    # Timing now resolved live from the notification_types catalog
                    # (context_time/offset_minutes), cascaded through tenant/referee overrides via
                    # getEffectiveNotificationSetting, instead of the contextDate/reminderInHrs
                    # baked onto the notification record at creation time - so later catalog/tenant/
                    # referee-level changes affect already-created notifications too. context_time
                    # is now 'created' | 'gameStart' | 'gameEnd' (previously 'now'/'gameStart'/'gameEnd'
                    # with 'created' handled only via the notification record's own contextDate).
                    setting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey=notificationType, refereeDetail=globalRefereeDetail)
                    if setting is None:
                        continue
                    contextTime = setting['contextTime']
                    reminderInHrs = -setting['offsetMinutes'] / 60
                    if contextTime == 'created':
                        timePassed = helpers.localNow() - notification['created']
                        if timePassed.total_seconds() > 12 * 60 * 60:
                            notification['status'] = 'deferred'
                            self.cacheService.setNotification(tenantKey=notification['tenantKey'], target=notification['target'], target_id=tournamentGameId, notificationType=notificationType, target_to=notification.get('target_to'), value=notification)
                            continue
                        dueDate = None #notification['created']
                    elif contextTime == 'gameEnd':
                        dueDate = gameDetail.get('date') + timedelta(minutes=gameDuration)
                    else:  # 'gameStart'
                        dueDate = gameDetail.get('date')
                    if reminderInHrs and reminderInHrs == -99:
                        continue
                    processNotification = await self.checkNotificationTime(dueDatetime=dueDate, hoursInAdvance=reminderInHrs, reminderOffsetInMins=15)
                    if processNotification:
                        await self.handleSingleNotification(tenantKey=tenantKey, objType=objType, refereeData=refereeData, notification=notification, itemPk=itemPk, item=item, gameDetail=gameDetail, browser=browser_for_notifications)

        try:
            if browser is not None:
                await _notifications_work(browser)
            elif self.single_playwright_browser:
                headless = ConfigManager.get_config_bool(self.config, 'browserHeadless', True)
                p, launched = await playwright_shared_browser.get_shared_browser(
                    headless=headless, useProxy=False
                )
                if ConfigManager.get_config_bool(self.config, 'tracing', False):
                    helpers.initTracing(p)
                await _notifications_work(launched)
            else:
                async with OrgServiceBase.playwright_driver_context() as p:
                    launched = await OrgServiceBase.launchBrowser(p, headless=ConfigManager.get_config_bool(self.config, 'browserHeadless', True))
                    try:
                        await _notifications_work(launched)
                    finally:
                        try:
                            await launched.close()
                        except Exception:
                            pass

        except Exception as ex:
            self.logger.error(f'handleNotifications {refereeId}', ex, refereeDetail=globalRefereeDetail)

    async def handleSingleNotification(self, tenantKey, objType, refereeData, notification, itemPk, item, gameDetail, browser=None):
        tournamentGameId = (gameDetail.get('id') or itemPk) if gameDetail else itemPk
        mobileNo = refereeData['mobileNo']
        refId = refereeData['refId']
        name = refereeData['name']
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeData.get('refereeId'))
        globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', refereeId=refereeData.get('refereeId'))

        try:
            tenant = self.tenantRepository.get_tenant(tenant_key=tenantKey, game=item)
            localTime = datetime.now(ZoneInfo(ConfigManager.get_config_value(self.config, 'TZ', 'UTC')))
            localHour = localTime.hour
            defaultAvailableFromHour = tenant.default_available_from_hour if tenant else 8
            defaultAvailableToHour = tenant.default_available_to_hour if tenant else 21
            allowDefaultAvailability = True
            if defaultAvailableFromHour <= defaultAvailableToHour and (localHour < defaultAvailableFromHour or localHour > defaultAvailableToHour) \
                        or defaultAvailableFromHour > defaultAvailableToHour and (localHour > defaultAvailableFromHour and localHour < defaultAvailableToHour):
                allowDefaultAvailability = False
            skipAvailabilityNotifications = tenant.skip_availability_notifications if tenant else []
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
            notificationTo = notification.get('target_to')
            internalMsgId = str(notification['id'])

            tournamentName = gameDetail.get('tournamentName') if gameDetail else None
            tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName, game=item)
            rules = None
            if tournament and tournament.get('rules'):
                rules = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament.get('rules').strip())
            referees:list = gameDetail.get('referees', []) if gameDetail else []
            refereeId = tenantRefereeDetail.get('refereeId') if tenantRefereeDetail else None
            isMainReferee = refereeId in gameDetail.get('mainReferees', []) if gameDetail else False
            isSecretaryReferee = refereeId == gameDetail.get('secretaryReferee') if gameDetail else False
            chatGroupId = gameDetail.get('chatGroupId') if gameDetail else None
            field = None
            fieldAddressDetails = None
            fieldTitle = gameDetail.get('fieldName') if gameDetail else None
            if fieldTitle:
                field = self.tenantRepository.get_field(tenant_key=tenantKey, field_name=fieldTitle, game=item)
            if field:
                fieldAddressDetails = field.address

            noticeType = 'regular'
            noticeTitle = None
            noticeDetails = None
            noticeOptions = None

            secondsLeft = round((gameDetail.get('date') - helpers.localNow()).total_seconds()) if gameDetail.get('date') else 0
            minsLeft = round(secondsLeft/60)
            hoursLeft = round(minsLeft/60)

            if notificationType == NotificationTypeKey.addedItem or notificationType == NotificationTypeKey.updatedItem:
                isNewItem = notificationType == NotificationTypeKey.addedItem

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
                        msgSid = await self.messagingService.sendLocation(to=to, latitude=to_coordinates_lat, longitude=to_coordinates_lng, name=field.title, address=fieldAddressDetails['address'])

                    if rules:
                        noticeType = 'regular'
                        noticeTitle = f'*תזכורת אחרונה-חוקים*'
                        noticeDetails = ''
                        for rule in (rules.game or {}):
                            noticeDetails += f"\n{rule}: {rules.game[rule]}"
                        if tournament['tournament'] == 'cup':
                            noticeDetails += '\nחוקים לגביע:'
                            for rule in (rules.cup or {}):
                                noticeDetails += f"\n{rule}: {rules.cup[rule]}"

            elif notificationType.startswith('refereeLastReminder'):
                if tenantRefereeDetail.get('refSixEnabled', False) == True and item.get('refSixCreated', False) == False:
                    template = { 'action': 'createrefsixgame', 'gameId': gameDetail.get('gameId'), 'status': 'created' }
                    self.cacheService.setRefereeTemplate(tenantKey=tenantKey, refereeId=tenantRefereeDetail.get('refereeId'), msgSid=str(uuid.uuid4())[:16], value=template)

                noticeTitle = f'*תזכורת אחרונה*'
                noticeDetails = f'בעוד {hoursLeft} שעות מתחיל המשחק נא להערך בהתאם'
                noticeDetails += await self.getFieldAndCommuteDetails(globalRefereeDetail=globalRefereeDetail, tenantRefereeDetail=tenantRefereeDetail, refereeGame=item, browser=browser)
                if len(referees) == 1 or not (self.messagingService.checkSendGreenApiMessages(to=tenantRefereeDetail) or self.messagingService.useMeta):
                    if rules:
                        noticeDetails += f'\n*חוקים:*'
                        for rule in (rules.game or {}):
                            noticeDetails += f"\n{rule}: {rules.game[rule]}"
                        if tournament['tournament'] == 'cup':
                            for rule in (rules.cup or {}):
                                noticeDetails += f"\n{rule}: {rules.cup[rule]}"

            elif notificationType.startswith('gameLineupsAnnounced'):
                if tournament and gameDetail:
                    if not gameDetail.get('squads'):
                        #helpers.run_async_in_thread(self.tenantsOrgServices[tenantKey].refreshTournamentGamesUrl, tenantKey=tenantKey, tournamentName=tournamentName, round=gameDetail.get('round'), fixture=gameDetail.get('fixture'), fetchGameDetails=True)
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
                noticeDetails = await self.getCommuteDetailsAfterGame(
                    globalRefereeDetail=globalRefereeDetail,
                    tenantRefereeDetail=tenantRefereeDetail,
                    refereeGame=item,
                    browser=browser,
                )
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
                self.cacheService.setCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, value=helpers.localNow(), propertyName='openWindowMessageSent', ttlSeconds=60 * 60 * 12)

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
                    pushSection = None
                    pushCategory = None
                    leaveByTime = None
                    if notificationType.startswith('refereeLastReminder'):
                        # Lets iOS show Waze/Set-Origin/Ignore actions and, if a commute route was
                        # resolved above, schedule a local "time to leave" notification.
                        pushSection = 'games'
                        pushCategory = 'COMMUTE_REMINDER'
                        leaveByTime = item.get('commute', {}).get('departDateTime')
                    msgSid, sentPushMsgIds = await self.messagingService.sendMessage(to=to, message=message, performOpenWindowCheck=True, skipPushNotification=skipPushNotification, returnSentPushMsgIds=True, internalMsgId=internalMsgId, forceUseGreenApi=forceUseGreenApi, gameId=gameDetail['gameId'] if gameDetail else None, pushSection=pushSection, pushCategory=pushCategory, leaveByTime=leaveByTime)
                elif noticeType == 'poll':
                    msgSid = await self.messagingService.sendPoll(to=to, message=message, options=noticeOptions)

                if msgSid or len(sentPushMsgIds) > 0:
                    if msgSid:
                        notification['status'] = 'sent'
                        notification['messageSid'] = msgSid
                        notification['sentDate'] = helpers.localNow()
                    if sentPushMsgIds:
                        notification['sentPushMsgIds'] = sentPushMsgIds
    
                    self.cacheService.setNotification(tenantKey=notification['tenantKey'], target=target, target_id=tournamentGameId, notificationType=notificationType, target_to=notificationTo, value=notification)
            
            elif msgSid or len(sentPushMsgIds) > 0:
                if msgSid:
                    notification['status'] = 'sent'
                    notification['sentDate'] = helpers.localNow()
                    notification['messageSid'] = msgSid
                if sentPushMsgIds:
                    notification['sentPushMsgIds'] = sentPushMsgIds
                self.cacheService.setNotification(tenantKey=notification['tenantKey'], target=target, target_id=tournamentGameId, notificationType=notificationType, target_to=notificationTo, value=notification)
       
        except Exception as ex:
            self.logger.error(f'handleSingleNotification {refId}', ex, refereeDetail=globalRefereeDetail)

    def _google_departure_time_for_arrival(self, arrive_at):
        """Distance Matrix driving uses departure_time; approximate leave time before target arrival."""
        now = helpers.localNow()
        if not arrive_at:
            return now.timestamp()
        leave_guess = arrive_at - timedelta(minutes=90)
        if leave_guess > now:
            return int(leave_guess.timestamp())
        return now.timestamp()

    async def _commute_route_seconds_meters(
        self,
        tenantKey: str,
        from_lat,
        from_lng,
        to_lat,
        to_lng,
        *,
        arrive_at=None,
        browser=None,
    ):
        if self._commute_route_provider == "google":
            dep = self._google_departure_time_for_arrival(arrive_at)
            origin_coords = {"lat": from_lat, "lng": from_lng}
            dest_coords = {"lat": to_lat, "lng": to_lng}
            self._commute_service.has_live_data = False
            duration_secs, distance_meters = await self._commute_service.get_driving_route_seconds_meters(
                origin_coords, dest_coords, departure_time=dep
            )
        else:
            duration_secs, distance_meters = await self.tenantsOrgServices[tenantKey].getBaseWazeRoute(
                from_latitude=from_lat,
                from_longitude=from_lng,
                to_latitude=to_lat,
                to_longitude=to_lng,
                arriveAt=arrive_at,
                browser=browser,
            )
        
        self.logger.info(f'commute_route_seconds_meters {tenantKey} {from_lat} {from_lng} {to_lat} {to_lng} {arrive_at} {duration_secs} {distance_meters}')
        return duration_secs, distance_meters

    async def getFieldAndCommuteDetails(self, globalRefereeDetail, tenantRefereeDetail, refereeGame, browser=None):
        noticeDetails = ''
        try:
            tenantKey = refereeGame['tenantKey']
            gameDetail = self.cacheService.getGameDetail(game=refereeGame)
            tournamentGameId = gameDetail.get('id')
            field = None
            fieldTitle = gameDetail.get('fieldName')
            if fieldTitle:
                field = self.tenantRepository.get_field(tenant_key=tenantKey, field_name=fieldTitle, game=refereeGame)
            if field:
                if not field.address:
                    self.logger.warning(f'getFieldAndCommuteDetails {globalRefereeDetail["mobileNo"]} missing field address details for field {tenantKey}:{fieldTitle}', refereeDetail=globalRefereeDetail)
                    return ''

            originLocation = self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=globalRefereeDetail['mobileNo'], propertyName='originLocation')
            if not originLocation or originLocation.get('expiredBy') < helpers.localNow():
                if not globalRefereeDetail.get('address'):
                    self.logger.warning(f'getFieldAndCommuteDetails {globalRefereeDetail["mobileNo"]} missing address details', refereeDetail=globalRefereeDetail)
                    return ''

                originLocation = {
                    'lng': globalRefereeDetail['addressDetails']['coordinates']['lng'],
                    'lat': globalRefereeDetail['addressDetails']['coordinates']['lat']
                }

            if originLocation and originLocation.get('lng') and originLocation.get('lat') and field and field.lat and field.lng:
                to_coordinates_lat = field.lat
                to_coordinates_lng = field.lng

                if 'commute' not in refereeGame:
                    refereeGame['commute'] = {}

                arriveAt = gameDetail['date'] + timedelta(seconds=-int(globalRefereeDetail["timeArrivalInAdvance"])*60)
                duration_secs, distance_meters = await self._commute_route_seconds_meters(
                    tenantKey,
                    originLocation["lat"],
                    originLocation["lng"],
                    to_coordinates_lat,
                    to_coordinates_lng,
                    arrive_at=arriveAt,
                    browser=browser,
                )
                if duration_secs:
                    refereeGame['commute']['durationToField'] = duration_secs
                    durationStr = helpers.seconds_to_hms(duration_secs)
                    if durationStr[:3] == '00:':
                        durationStr = f'{durationStr[3:]} דקות'
                    else:
                        durationStr = f'{durationStr} שעות'
                    departDateTime = arriveAt + timedelta(seconds=-duration_secs)
                    # Exposed to the push-notification payload (see handleSingleNotification's
                    # refereeLastReminder branch) so iOS can locally schedule a "time to leave"
                    # notification 10 minutes before this, without the server polling/re-computing.
                    refereeGame['commute']['departDateTime'] = departDateTime.isoformat()
                    departTimeStr = departDateTime.strftime("%H:%M")
                    if departTimeStr:
                        noticeDetails += f'\n\n*משך הנסיעה* הוא {durationStr}'
                        noticeDetails += f'\nכדי להגיע {globalRefereeDetail["timeArrivalInAdvance"]} דקות לפני המשחק כדאי לצאת בשעה {departTimeStr}'

                if distance_meters:
                    refereeGame['commute']['distanceToField'] = distance_meters
                    distance = int(distance_meters)/1000
                    noticeDetails += f'\n*המרחק* הוא {distance:.1f} קילומטרים'

                self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=tenantRefereeDetail.get('refereeId'), gamePk=refereeGame['gamePk'], value=refereeGame)
            
            #waze link
            if field and field.waze_link:
                noticeDetails += f'\n\n*קישור:* {field.waze_link}'
            #field address
            if field and field.address:
                noticeDetails += f'\n\n*כתובת:* {field.address}'
        except Exception as ex:
            self.logger.error(f'getFieldDetailsAndCommute {globalRefereeDetail["mobileNo"]}', ex, refereeDetail=globalRefereeDetail)
        
        return noticeDetails

    async def getCommuteDetailsAfterGame(self, globalRefereeDetail, tenantRefereeDetail, refereeGame, browser=None):
        noticeDetails = ''
        try:
            tenantKey = refereeGame['tenantKey']
            gameDetail = self.cacheService.getGameDetail(game=refereeGame)
            tournamentGameId = gameDetail.get('id')
            field = None
            fieldTitle = gameDetail.get('fieldName')
            if fieldTitle:
                field = self.tenantRepository.get_field(tenant_key=tenantKey, field_name=fieldTitle, game=refereeGame)
            destinationLocation = self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=globalRefereeDetail['mobileNo'], propertyName='originLocation')
            #use home address
            if True or not destinationLocation or destinationLocation.get('expiredBy') < helpers.localNow():
                if not globalRefereeDetail.get('addressDetails'):
                    self.logger.warning(f'getCommuteDetailsAfterGame {globalRefereeDetail["mobileNo"]} missing address details', refereeDetail=globalRefereeDetail)
                    return ''

                destinationLocation = {
                    'lng': globalRefereeDetail['addressDetails']['coordinates']['lng'], 
                    'lat': globalRefereeDetail['addressDetails']['coordinates']['lat']
                }

            if destinationLocation and destinationLocation.get('lng') and destinationLocation.get('lat') and field:
                from_coordinates_lat = field.lat
                from_coordinates_lng = field.lng

                if 'commute' not in refereeGame:
                    refereeGame['commute'] = {}

                duration_from_game_secs, distance_from_game_meters = await self._commute_route_seconds_meters(
                    tenantKey,
                    from_coordinates_lat,
                    from_coordinates_lng,
                    destinationLocation["lat"],
                    destinationLocation["lng"],
                    arrive_at=None,
                    browser=browser,
                )
                if duration_from_game_secs:
                    refereeGame['commute']['durationFromField'] = duration_from_game_secs
                if distance_from_game_meters:
                    refereeGame['commute']['distanceFromField'] = distance_from_game_meters

                self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=tenantRefereeDetail.get('refereeId'), gamePk=refereeGame['gamePk'], value=refereeGame)

                if refereeGame['commute'].get('distanceToField') and distance_from_game_meters:
                    totalDistance = int(refereeGame['commute']['distanceToField']) + distance_from_game_meters
                    noticeDetails = f'סה״כ מרחק הנסיעה הוא {totalDistance/1000:.2f} ק״מ'
        except Exception as ex:
            self.logger.error(f'getCommuteDetailsAfterGame {globalRefereeDetail["mobileNo"]}', ex, refereeDetail=globalRefereeDetail)

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

    async def createRefSixGame(
        self,
        template,
        tenantRefereeDetail,
        refereeGame,
        gameDetail,
        browser: Optional[Browser] = None,
    ):
        success = False
        title = f'משחק {gameDetail["gameTitle"]}'
        message = ''
        failureMessage = None
        gamePk = refereeGame['gamePk']
        tournamentGameId = gameDetail.get('id')

        try:
            if tenantRefereeDetail.get('refSixEnabled', False) == False:
                success = True
                message = 'RefSix is not enabled'
            elif refereeGame.get('refSixCreated', False) == True:
                    success = True
                    message = 'RefSix game already created'
            else:
                result = None
                headless = ConfigManager.get_config_bool(self.config, 'browserHeadless', True)
                try:
                    if browser is not None:
                        context = await OrgServiceBase.createContext(browser=browser)
                        stealth = Stealth()
                        await stealth.apply_stealth_async(context)
                        ref_six_page = await context.new_page()
                        try:
                            result = await self.tenantsOrgServices[tenantRefereeDetail['tenantKey']].createGameInRefSix(
                                page=ref_six_page,
                                username=tenantRefereeDetail['refSixUsername'],
                                password=tenantRefereeDetail['refSixPassword'],
                                gameDetail=gameDetail,
                            )
                        finally:
                            try:
                                await context.close()
                            except Exception:
                                pass
                    elif self.single_playwright_browser:
                        p, launched = await playwright_shared_browser.get_shared_browser(
                            headless=headless, useProxy=False
                        )
                        if ConfigManager.get_config_bool(self.config, 'tracing', False):
                            helpers.initTracing(p)
                        context = await OrgServiceBase.createContext(browser=launched)
                        stealth = Stealth()
                        await stealth.apply_stealth_async(context)
                        ref_six_page = await context.new_page()
                        try:
                            result = await self.tenantsOrgServices[tenantRefereeDetail['tenantKey']].createGameInRefSix(
                                page=ref_six_page,
                                username=tenantRefereeDetail['refSixUsername'],
                                password=tenantRefereeDetail['refSixPassword'],
                                gameDetail=gameDetail,
                            )
                        finally:
                            try:
                                await context.close()
                            except Exception:
                                pass
                    else:
                        async with OrgServiceBase.playwright_driver_context() as p:
                            launched = await OrgServiceBase.launchBrowser(p, headless=headless)
                            try:
                                context = await OrgServiceBase.createContext(browser=launched)
                                stealth = Stealth()
                                await stealth.apply_stealth_async(context)
                                ref_six_page = await context.new_page()
                                result = await self.tenantsOrgServices[tenantRefereeDetail['tenantKey']].createGameInRefSix(
                                    page=ref_six_page,
                                    username=tenantRefereeDetail['refSixUsername'],
                                    password=tenantRefereeDetail['refSixPassword'],
                                    gameDetail=gameDetail,
                                )
                            finally:
                                try:
                                    await launched.close()
                                except Exception:
                                    pass
                except Exception as ex:
                    self.logger.error(f'createGameInRefSix', ex)

                if result:
                    refereeGame['refSixCreated'] = result.get('success')
                    self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=refereeGame['tenantKey'], refereeId=tenantRefereeDetail.get('refereeId'), gamePk=refereeGame['gamePk'], value=refereeGame)
                    await self.messagingService.sendMessage(to=tenantRefereeDetail['mobileNo'], title=f'{gameDetail["gameTitle"]} RefSix', message=result.get('message'))
                    success = result.get('success')
                    message = result.get('message') or ''
                else:
                    success = False
                    message = message or 'יצירת משחק RefSix נכשלה'
        except Exception as ex:
            self.logger.error(f'createRefSixGame {tenantRefereeDetail["mobileNo"]}', ex)        
            message = str(ex)

        template['message'] = message
        if success:
            template['status'] = 'completed'
            template['updated'] = helpers.localNow()
            self.logger.info(message, refereeDetail=tenantRefereeDetail)
        else:
            failureMessage = message
            self.logger.warning(message, refereeDetail=tenantRefereeDetail)

        await self.postProcessTemplate(template=template, tenantRefereeDetail=tenantRefereeDetail, tournamentGameId=tournamentGameId, title=title, message=message, failureMessage=failureMessage)

    async def postCompare(self, tenantKey, objType, refereeData, page):
        tenantRefereeDetail = None
        try:
            refereeId = refereeData.get('refereeId')
            mobileNo = refereeData['mobileNo']
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, refereeId=refereeId)
            # Effective settings (catalog/tenant.notification_settings/referee override cascade),
            # not the legacy tenant.notifications dict this used to read directly - see
            # getEffectiveNotificationSetting. Resolved once per type since tenantKey/refereeId are
            # fixed for the whole call.
            addedItemSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='addedItem')
            removedItemSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='removedItem')
            archivedItemSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='archivedItem')
            updatedItemSetting = self.getEffectiveNotificationSetting(tenantKey=tenantKey, refereeId=refereeId, typeKey='updatedItem')
            addedItemNotificationReminderInHrs = -addedItemSetting['offsetMinutes'] / 60 if addedItemSetting else None
            updated = False

            for itemPk in refereeData[objType].get('removed', []):
                prevItem = refereeData[objType]['prevList'][itemPk]
                prevItem['state'] = 'removed'
                gameDetail = self.cacheService.getGameDetail(game=prevItem)
                tournamentGameId = gameDetail.get('id') if gameDetail else None
                addedItemNotification = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.addedItem, target_to=refereeId)

                if addedItemNotification and addedItemNotificationReminderInHrs:
                    timeElapsed = helpers.localNow() - list(addedItemNotification.values())[0].get('created')
                    if timeElapsed.total_seconds() < abs(addedItemNotificationReminderInHrs) * 60 * 60:
                        prevItem['state'] = 'canceled'

                if objType == 'games':
                    refereeGamesNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, status='created', target_to=refereeId)
                    if refereeGamesNotifications:
                        for notification in refereeGamesNotifications.values():
                            notification['status'] = 'deleted'
                            self.cacheService.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=notification['notificationType'], target_to=notification.get('target_to'), value=notification)
                    if gameDetail and mobileNo in gameDetail.get('activeGroupMobileNumbers', []):
                        gameDetail['activeGroupMobileNumbers'].remove(mobileNo)
                        self.cacheService.setTournamentGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'], gamePk=itemPk, value=gameDetail)

                    self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=refereeId, gamePk=itemPk, value=prevItem)

                    addedItemNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.addedItem, target_to=refereeId)
                    addedItemNotificationSent = len(addedItemNotifications) == 0 or any(notification for notification in addedItemNotifications.values() if notification.get('status') == 'sent')
                    if addedItemNotificationSent and removedItemSetting:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.removedItem, target_to=refereeId, contextDate='created', status='created')

                elif objType == 'reviews':
                    refereeReviewsNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, status='created', target_to=refereeId)
                    if refereeReviewsNotifications:
                        for notification in refereeReviewsNotifications.values():
                            notification['status'] = 'deleted'
                            self.cacheService.setNotification(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, notificationType=notification['notificationType'], target_to=notification.get('target_to'), value=notification)

                    self.cacheService.setRefereeReview(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=refereeId, gamePk=itemPk, value=prevItem)

                    addedItemNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, notificationType=NotificationTypeKey.addedItem, target_to=refereeId)
                    addedItemNotificationSent = len(addedItemNotifications) == 0 or any(notification for notification in addedItemNotifications.values() if notification.get('status') == 'sent')
                    if addedItemNotificationSent and removedItemSetting:
                        self.setNotification(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, notificationType=NotificationTypeKey.removedItem, target_to=refereeId, contextDate='created', status='created')

                updated = True

            for itemPk in refereeData[objType].get('archived', []):
                prevItem = refereeData[objType]['prevList'][itemPk]
                if prevItem.get('state', 'active') == 'archived':
                    continue
                if objType == 'games':
                    prevItem['state'] = 'archived'
                    gameDetail = self.cacheService.getGameDetail(game=prevItem)
                    tournamentGameId = gameDetail.get('id') if gameDetail else None
                    self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=refereeId, gamePk=itemPk, value=prevItem)
                    if archivedItemSetting:
                        self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.archivedItem, target_to=refereeId, contextDate='created', status='created')

            objItemPKs = refereeData[objType]['added'] + refereeData[objType]['changed']
            for itemPk in objItemPKs:
                isNewItem = itemPk in refereeData[objType]['added']
                item = refereeData[objType]['currentList'][itemPk]
                prevItem = refereeData[objType]['prevList'].get(itemPk, {})

                if objType == 'games':
                    gameDetail = self.cacheService.getGameDetail(game=item)
                    tournamentGameId = gameDetail.get('id') if gameDetail else None
                    item['state'] = 'active'
                    if item.get('date') >= helpers.localNow():
                        if item.get('status') != 'מאושר':
                            if addedItemSetting:
                                self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.addedItem, target_to=refereeId, contextDate='created', reminderInHrs=addedItemNotificationReminderInHrs, status='created')
                        else:
                            if updatedItemSetting:
                                self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.updatedItem, contextDate='created', status='created')
                    if tenantRefereeDetail.get('refSixEnabled', False) == True and item.get('refSixCreated', False) == False:
                        template = { 'action': 'createrefsixgame', 'gameId': gameDetail.get('gameId'), 'status': 'created' }
                        self.cacheService.setRefereeTemplate(tenantKey=tenantKey, refereeId=tenantRefereeDetail.get('refereeId'), msgSid=str(uuid.uuid4())[:16], value=template)

                    if item.get('status', '') != prevItem.get('status', ''):
                        if item['status'] == 'מאושר':
                            item['approvedDate'] = helpers.localNow()
                        elif item['status'] == 'שיבוץ נדחה':
                            item['declinedDate'] = helpers.localNow()
                    
                    # Reuse the tournament_game_id already resolved above (gameDetail.get('id'))
                    # instead of letting setRefereeGame redundantly re-resolve it from gamePk -
                    # avoids a second lookup that could disagree/fail even though we just proved
                    # the game exists a few lines up. Falls back to gamePk-based resolution inside
                    # setRefereeGame when gameDetail itself couldn't be resolved.
                    self.cacheService.setRefereeGame(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=refereeId, gamePk=itemPk, value=item)

                elif objType == 'reviews':
                    item['state'] = 'active'
                    gameDetail = self.cacheService.getGameDetail(game=item)
                    tournamentGameId = gameDetail.get('id') if gameDetail else None
                    self.cacheService.setRefereeReview(tournamentGameId=tournamentGameId, tenantKey=tenantKey, refereeId=refereeId, gamePk=itemPk, value=item)
                    if isNewItem:
                        if addedItemSetting:
                            self.setNotification(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, notificationType=NotificationTypeKey.addedItem, target_to=refereeId, contextDate='created', status='created')
                    else:
                        if updatedItemSetting:
                            self.setNotification(tenantKey=tenantKey, target='refereeReviews', target_id=tournamentGameId, notificationType=NotificationTypeKey.updatedItem, target_to=refereeId, contextDate='created', status='created')

                updated = True

            if updated:
                self.cacheService.setRefereeProperty(tenantKey=tenantKey, refereeId=refereeId, value=helpers.localNow(), propertyName=f'{objType}_lastUpdate')
            self.cacheService.setRefereeProperty(tenantKey=tenantKey, refereeId=refereeId, value=helpers.localNow(), propertyName=f'{objType}_lastRun')

            self.logger.debug(f'postCompare: {objType}', refereeDetail=tenantRefereeDetail)
        
        except Exception as ex:
            self.logger.error(f'postCompare', ex, refereeDetail=tenantRefereeDetail)

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
        refereeGames = self.cacheService.getRefereeGames(tenantKey=tenantKey, refereeId=refereeDetail.get('refereeId'), from_date=datetime.now() - timedelta(days=2), to_date=datetime.now() + timedelta(days=1), includeArchived=True)
        refereeData = {
            'refId': refereeDetail['refId'],
            'games': {
                'currentList': {
                    next(iter(refereeGames.keys())): next(iter(refereeGames.values()))
                }
            }
        }
        async with OrgServiceBase.playwright_driver_context() as p:
            browser = await OrgServiceBase.launchBrowser(p, headless=ConfigManager.get_config_bool(self.config, 'browserHeadless', True))
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
        async with OrgServiceBase.playwright_driver_context() as p:
            browser = await OrgServiceBase.launchBrowser(p, headless=ConfigManager.get_config_bool(self.config, 'browserHeadless', True))
            context = await OrgServiceBase.createContext(browser=browser)
            page = await context.new_page()
            loginResult, loginMessage = await self.tenantsOrgServices[tenantKey].login(refereeDetail=refereeDetail, page=page)
            print(loginResult, loginMessage)

    async def testSetNotification(self):
        mobileNo = '+972547799979'
        tenantKey = 'IL#football#2025-26'
        referee = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        refereeGames = self.cacheService.getRefereeGames(tenantKey=tenantKey, refereeId=referee.get('refereeId'), from_date=datetime.now() - timedelta(days=0), to_date=datetime.now() + timedelta(days=3), includeArchived=True)
        for gamePk, refereeGame in refereeGames.items():
            gameDetail = self.cacheService.getGameDetail(game=refereeGame)
            tournamentGameId = gameDetail.get('id') if gameDetail else None
            referees = gameDetail.get('referees', [])
            if refereeGame.get('state') == 'active':
                if True:
                    self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeLastReminder, target_to=mobileNo, reminderInHrs=180, upsert=True)
                else:
                    self.setNotification(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.refereeLastReminder, delete=True)
            if len(referees) > 1:
                if True:
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameLastReminder, reminderInHrs=180, upsert=True)
                else:
                    self.setNotification(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, notificationType=NotificationTypeKey.gameLastReminder, delete=True)
            refNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, status='created', target_to=mobileNo)
            gameNotifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='tournamentGames', target_id=tournamentGameId, status='created')
            pass

    def aaa(self):
        refereeDetail = None            
        try:
            refereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo='+972547799979')
            a = int('bb')
        except Exception as ex:
            self.logger.error(f'aaa', ex, refereeDetail=refereeDetail)

    async def testHandleSingleNotification(self):
        tenantKey = 'IL#football#2025-26'
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo='+972547799979')
        refereeData = {
            'mobileNo': refereeDetail['mobileNo'],
            'refId': refereeDetail['refId'],
            'name': refereeDetail['name']
        }
        games = self.cacheService.getRefereeGames(tenantKey=tenantKey, refereeId=refereeDetail.get('refereeId'), from_date=datetime.now() - timedelta(days=0), to_date=datetime.now() + timedelta(days=1), includeArchived=True)
        for game in games.values():
            gameDetail = self.cacheService.getGameDetail(game=game)
            tournamentGameId = (gameDetail.get('id') or game['gamePk']) if gameDetail else game['gamePk']
            notifications = self.cacheService.getNotifications(tenantKey=tenantKey, target='refereeGames', target_id=tournamentGameId, target_to=refereeDetail['mobileNo'])
            for notification in notifications.values():
                if notification.get('notificationType') != 'refereeLastReminder':
                    continue
                await self.handleSingleNotification(tenantKey=tenantKey, objType='games', refereeData=refereeData, notification=notification, itemPk=game['gamePk'], item=gameDetail, gameDetail=gameDetail)
            pass
        pass
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
        asyncio.run(rpc.testHandleSingleNotification())
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