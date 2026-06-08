#!/usr/bin/env python3
"""
Handball Games Scraper using Playwright
Extracts referee assignment data from handball management system
"""

import asyncio
from datetime import datetime, timedelta
import re
import traceback
from playwright.async_api import async_playwright, Page, BrowserContext, Browser
from playwright_stealth import Stealth
import sys
import os
import requests
import aiohttp
from dataclasses import dataclass, asdict
from urllib.parse import urlencode
from typing import Dict, Any, Optional
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.handleUsers import HandleUsers
from shared.logger import Logger
# MessagingService imported via TYPE_CHECKING in orgServiceBase to avoid circular import
from shared.db import CacheService
from shared.orgRelated.orgServiceBase import OrgServiceBase, OrgServiceCountryCode, OrgServiceEventType
from shared.orgRelated.multiTenantSupport import MultiTenantSupport
from shared.orgRelated.IHAParser import IHAParser

class IHAService(OrgServiceBase):
    """IFA mgmt lists use ``table.devices``. Wait for the table, not ``tbody tr`` — slow pages
    exceed 10s, and an empty referee assignment list has no data rows."""
    _IHA_DEVICES_TABLE_SEL = 'table.devices tbody tr'
    _IHA_DEVICES_TABLE_TIMEOUT_MS = int(os.getenv('IHA_DEVICES_TABLE_WAIT_MS', '45000'))

    def __init__(self, logger:Logger, multiTenantSupport:MultiTenantSupport, cacheService:CacheService, handleUsers:HandleUsers, messagingService:'MessagingService'):
        super().__init__(logger=logger, multiTenantSupport=multiTenantSupport, cacheService=cacheService, handleUsers=handleUsers, messagingService=messagingService, countryCode=OrgServiceCountryCode.ISRAEL, eventType=OrgServiceEventType.IHA)

        self.translation_table = str.maketrans('', '', "!@#'? \"")

        self.protocol = 'https://'
        self.baseUrl = 'handballisr.co.il'
        self.loginUrl = os.getenv('loginUrl1') or 'https://handballisr.co.il/mgmt/default.asp'
        self.refereeGamesUrl = os.getenv('refereeGamesUrl') or "https://handballisr.co.il/mgmt/Person.asp"
        self.assignerGamesUrl = os.getenv('gamesUrl') or "https://handballisr.co.il/mgmt/assign_list.asp"
        self.reviewsUrl = os.getenv('reviewsUrl1') or ''
        self.gameAnswerUrl = os.getenv('gameAnswerUrl') or f'{self.protocol}{self.baseUrl}/mgmt/assign_answer.asp'
    
        self.dataDic = {
            'games': {
                'pkTags': [ "tournamentName", "gameTitle", "fixture", "internalGameId" ],
            },
            'reviews': {
                'pkTags': [ "tournamentName", "gameTitle", "fixture", "internalGameId" ],
            }
        }

    async def login(self, refereeDetail, page) -> tuple[bool, str]:
        """Login to the system."""
        try:
            page = await self.gotoUrl(page=page, url=self.loginUrl, refereeDetail=refereeDetail)
            await asyncio.sleep(1000 / 1000)
            
            # Check if we're on a login page
            login_form = await self.getLocator(parent=page, selector='form[name="login"]')
            if not login_form:
                self.logger.info("No login form found, assuming already logged in")
                return True, 'Login successful'
            
            # Fill in username
            await page.fill('input[name="UserName"]', refereeDetail["userName"])            
            # Fill in password
            userPass = self.handleUsers.decryptPassword(refereeDetail['password'])
            if not userPass:
                return False, 'Missing password'
            await page.fill('input[name="UserPass"]', userPass)
            
            # Submit the form
            await page.click('input[name="login"]')
            self.logger.info("Submitted login form")
            
            # Wait for navigation after login
            await page.wait_for_timeout(1000)
            
            # Check if login was successful by looking for login form again
            login_form_after = await self.getLocator(parent=page, selector='form[name="login"]')
            if login_form_after:
                passwordInputs = await self.getLocator(parent=page, selector='input[type="password"]', nonSingle=True)
                if await passwordInputs.count() == 1:
                    self.logger.warning("Login form still present, login may have failed")
                    return False, 'Login form still present, login may have failed'
            
            self.logger.info("Login successful")
            return True, 'Login successful'
            
        except Exception as ex:
            self.logger.error(f"Error during login:", ex)
            return False, str(ex)
    
    async def logout(self, refereeDetail, page):
        """Logout from the system."""
        try:
            await page.click('input[name="logout"]')
            self.logger.info("Logged out successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error during logout:", e)
            return False

    async def changePassword(self, refereeDetail, targetRefereeDetail, page) -> tuple[bool, str]:
        """
        Change password for a referee:
        1. Send request to reset password URL
        2. Wait 2 seconds
        3. Navigate to change password URL
        4. Fill in four input text fields with four different values
        5. Click OK button
        """
        try:
            tenants = self.cacheService.getTenants()
            tenant = tenants.get(refereeDetail.get('tenantKey'))
            resetPasswordUrl = tenant.get('urls', {}).get('resetPassword')
            homeUrl = tenant.get('urls', {}).get('home')
            logoutUrl = tenant.get('urls', {}).get('logout')

            # login as Assigner
            result, message = await self.login(refereeDetail=refereeDetail, page=page)
            await asyncio.sleep(200 / 1000)  # Wait for page to load
            if result == False:
                return False, message

            # reset password for referee
            resetPasswordForRefUrl = resetPasswordUrl.replace('{refId}', targetRefereeDetail.get('refId'))
            page = await self.gotoUrl(page=page, url=resetPasswordForRefUrl, refereeDetail=targetRefereeDetail)
            await asyncio.sleep(200 / 1000)  # Wait for page to load
                        
            # login as referee with temporary password
            userPassword = targetRefereeDetail['password']
            targetRefereeDetail['password'] = self.handleUsers.encryptPassword(tenant.get('temporaryPassword'))
            result, message = await self.login(refereeDetail=targetRefereeDetail, page=page)
            await asyncio.sleep(200 / 1000)  # Wait for page to load
            if result == False:
                return False, message
            
            targetRefereeDetail['password'] = userPassword

            # change password for referee
            userInput = await self.getLocator(parent=page, selector='input[name="uName"]')
            if not userInput:
                self.logger.error(f'User input not found', None, refereeDetail=refereeDetail)
                raise Exception(f'User input not found')
            await userInput.fill(targetRefereeDetail.get('userName', ''))
            
            curPasswordInput = await self.getLocator(parent=page, selector='input[name="pwd"]')
            if not curPasswordInput:
                self.logger.error(f'Current password input not found', None, refereeDetail=refereeDetail)
                raise Exception(f'Current password input not found')
            await curPasswordInput.fill(tenant.get('temporaryPassword'))
            
            decryptedPassword = self.handleUsers.decryptPassword(targetRefereeDetail.get('password', ''))
            
            newPasswordInput = await self.getLocator(parent=page, selector='input[name="pass1"]')
            if not newPasswordInput:
                self.logger.error(f'New password input not found', None, refereeDetail=refereeDetail)
                raise Exception(f'New password input not found')
            await newPasswordInput.fill(decryptedPassword)
            
            confirmPasswordInput = await self.getLocator(parent=page, selector='input[name="pass2"]')
            if not confirmPasswordInput:
                self.logger.error(f'Confirm password input not found', None, refereeDetail=refereeDetail)
                raise Exception(f'Confirm password input not found')
            await confirmPasswordInput.fill(decryptedPassword)
                        
            loginButton = await self.getLocator(parent=page, selector='input[name="login"]')
            if not loginButton:
                raise Exception(f'Login button not found')
            
            await loginButton.click()
            
            await asyncio.sleep(200 / 1000)

            url = page.url
            if url != homeUrl:
                self.logger.warning(f'Password not changed as expected', None, refereeDetail=refereeDetail)
                raise Exception(f'Password not changed as expected')

            # logout from referee
            page = await self.gotoUrl(page=page, url=logoutUrl, refereeDetail=targetRefereeDetail)
            await asyncio.sleep(200 / 1000)

            return True, 'success'

        except Exception as ex:
            self.logger.error(f'changePassword', ex, takeScreenshot=True, refereeDetail=refereeDetail)
            #await self.takeScreenshot(page, refereeDetail, 'changePassword')
            return False, str(ex)

    def setFetchDates(self, refereeData):
        now = datetime.now().date()
        if 'games' not in refereeData:
            refereeData['games'] = {}
        pastCollectDays = int(os.getenv('pastCollectDays', '7'))
        refereeData['games']['fromDate'] = now - timedelta(days=pastCollectDays)
        refereeData['games']['toDate'] = now + timedelta(days=365)
        if 'reviews' not in refereeData:
            refereeData['reviews'] = {}
        refereeData['reviews']['fromDate'] = now - timedelta(days=365)
        refereeData['reviews']['toDate'] = now + timedelta(days=365)

    async def parseListForReferee(self, tenantKey, objType, refereeData, page):
        # when no collected items, return None, wait for assigner run
        countCollectedItems = self.cacheService.countCollectedItems(tenantKey=tenantKey, objType=objType)
        if countCollectedItems <= 0:
            return None
        
        mobileNo = refereeData['mobileNo']
        currentPublishedListByReferee = self.cacheService.getCollectedItems(tenantKey=tenantKey, objType=objType, mobileNo=mobileNo)
        return currentPublishedListByReferee

    async def collectItemsForAssigner(self, tenantKey, objType, refereeData, page):
        try:
            tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
            '''
            async with async_playwright() as p:
                browser = await OrgServiceBase.launchBrowser(p=p, headless=eval(os.getenv('browserHeadless') or 'True'))
                context = await OrgServiceBase.createContext(browser=browser)
                stealth = Stealth()
                await stealth.apply_stealth_async(context)
                page1 = await context.new_page()
            '''
            if True:
                page1 = page
                collectType = 'byAssigner' if tenant.get('collectType', 'byAssigner') == 'byAssigner' else 'byReferee'
                if collectType == 'byAssigner':
                    await self.collectItemsByAssigner(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page1)
                elif collectType == 'byReferee':
                    await self.collectItemsByReferees(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page1)
                
            return True
        except Exception as ex:
            self.logger.error(f'collectItemsForAssigner:', ex)
            return False

    def on_page_close(self, page: Page):
        """Handler executed when the page is closed."""
        stack = traceback.extract_stack()
        callstack = ''.join(traceback.format_list(stack))
        self.logger.warning(f"Page closed: {page.url}, callstack={callstack}")

    def on_context_close(self):
        """Handler executed when the browser context is closed."""
        stack = traceback.extract_stack()
        callstack = ''.join(traceback.format_list(stack))
        self.logger.warning(f"Browser Context closed. callstack={callstack}")

    closed_event = asyncio.Event()
    
    def on_browser_disconnect(self, browser: Browser):
        """Handler executed when the browser process disconnects."""
        stack = traceback.extract_stack()
        callstack = ''.join(traceback.format_list(stack))
        self.logger.warning(f"Browser Disconnected (Closed) event triggered. callstack={callstack}")
        self.closed_event.set()

    async def collectItemsByAssigner(self, tenantKey, objType, refereeData, page):
        mobileNo = refereeData.get('mobileNo')

        headless = eval(os.getenv('browserHeadless', 'True'))
        async with IHAParser(logger=self.logger, headless=headless, page=page) as parser:
            try:
                # Parse the URL with pagination
                pastCollectDays = int(os.getenv('pastCollectDays', '0'))

                fromDate = datetime.now().date() - timedelta(days=pastCollectDays)
                toDate = datetime.now().date() + timedelta(days=365)
                url = None
                if objType == 'games':
                    url = self.getGamesUrl(fromDate=fromDate, toDate=toDate)
                elif objType == 'reviews':
                    url = self.getReviewsUrl(fromDate=fromDate, toDate=toDate)

                if not url:
                    return None

                parsedGames = await parser.parse_url_with_pagination(url, max_pages=100)
                
                if not parsedGames:
                    self.logger.warning("No games found. Please check the URL and try again.")
                    return
                
                countPreviousGames = int(self.cacheService.getKeyVal(key=f'handball_assignments_games') or '0')
                if countPreviousGames * 0.70 > len(parsedGames or {}):
                    await helpers.takeScreenshot(refereeDetail=None, tag='collectItemsByAssigner')
                    self.logger.warning(f"Less games found ({len(parsedGames)}) than previous time ({countPreviousGames}), not updating cache")
                    return
                elif countPreviousGames < len(parsedGames):
                    self.logger.info(f"More games found than previous time, updating cache")
                    self.cacheService.setKeyVal(key=f'handball_assignments_games', value=len(parsedGames))
                self.logger.info(f"✅ Successfully parsed {len(parsedGames)} games")
                
                # Print summary
                summary = await parser.get_summary()
                self.logger.info(f"📊 SUMMARY:\n{jsonHelper.save_to_json(summary)}")
                
                # Show page distribution
                if summary['page_distribution']:
                    self.logger.debug(f"📄 PAGE DISTRIBUTION:")
                    for page_num, count in sorted(summary['page_distribution'].items()):
                        self.logger.debug(f"  Page {page_num}: {count} games")
                
                # Export data
                self.logger.debug(f"💾 EXPORTING DATA:")
                self.logger.debug("  Exporting to JSON...")
                await parser.to_json('handball_assignments.json')
                self.logger.debug("  ✅ JSON exported to 'handball_assignments.json'")
                
                self.logger.debug("  Exporting to CSV...")
                await parser.to_csv('handball_assignments.csv')
                self.logger.debug("  ✅ CSV exported to 'handball_assignments.csv'")
                
                # Show sample games
                self.logger.debug(f"🎮 SAMPLE GAMES:")
                for i, game in enumerate(parsedGames[:3], 1):  # Show first 3 games
                    self.logger.debug(f"  Game {i} (Page {game.page_number}):")
                    self.logger.debug(f"    ID: {game.internalGameId}")
                    self.logger.debug(f"    Date/Time: {game.date}")
                    self.logger.debug(f"    Match: {game.homeTeam} vs {game.guestTeam}")
                    self.logger.debug(f"    Venue: {game.field}")
                    assigned_refs = [ref.get('refName') for ref in game.referees if ref.get('refName')]
                    if assigned_refs:
                        self.logger.debug(f"    Referees: {', '.join(assigned_refs)}")
                    else:
                        self.logger.debug(f"    Referees: None assigned")
                
                if len(parsedGames) > 3:
                    self.logger.debug(f"  ... and {len(parsedGames) - 3} more games")
                
                self.logger.debug("="*60)
                self.logger.debug("PARSING COMPLETE!")
                self.logger.debug("="*60)
                
                collectedItems = {}
                for item in parsedGames:
                    refDetails = []
                    for referee in item.referees:
                        mobileNo = referee['refId']
                        refDetail = self.handleUsers.refereesByRefId.get(tenantKey, {}).get(mobileNo)
                        refDetails.append({
                            'role': referee['role'],
                            '* name': refDetail.get('name') if refDetail else referee.get('refName'),
                            '* phone': refDetail.get('mobileNo') if refDetail else '',
                            '* address': refDetail.get('addressDetails').get('address') if refDetail else '',
                        })
                    for referee in item.referees:
                        mobileNo = referee['refId']
                        if mobileNo not in collectedItems:
                            collectedItems[mobileNo] = {}
                        obj = asdict(item)
                        obj['status'] = 'מאושר' if referee['status'] == 'שיבוץ אושר' else referee['status']
                        obj['dateText'] = datetime.strftime(item.date, "%d/%m/%Y %H:%M")
                        obj['date'] = helpers.convert_to_datetime(obj['dateText'])
                        obj['referees'] = refDetails
                        #item = self.multiTenantSupport.mapItem(tenantKey=tenantKey, objType=objType, obj=item)
                        #gameLink = item['links']['game_date']
                        #item['mobileNo'] = refereeDetail.get('mobileNo')
                        #item['refId'] = refereeDetail.get('refId')
                        #await self.scrapGameDetails(page=page, gameLink=gameLink, refereeGame=item)
                        obj['tournamentName'] = item.tournamentName
                        obj['gameTitle'] = item.homeTeam + ' - ' + item.guestTeam
                        pk = self.getPk(objType=objType, obj=obj)
                        obj['gamePk'] = pk
                        collectedItems[mobileNo][pk] = obj
                
                for mobileNo in self.handleUsers.refereesByMobile.get(tenantKey, {}).keys():
                    items = collectedItems.get(mobileNo, {})
                    prevCollectedItems = self.cacheService.getCollectedItems(tenantKey=tenantKey, objType=objType, mobileNo=mobileNo)
                    if len(prevCollectedItems) != len(items):
                        self.logger.info(f"Changed games found for referee {mobileNo}, updating cache")
                    self.cacheService.setCollectedItems(tenantKey=tenantKey, objType=objType, mobileNo=mobileNo, value=items)

            except Exception as ex:
                self.logger.debug(f"❌ collectItemsByAssigner:Error during parsing:", ex)
                import traceback
                traceback.print_exc()

    async def collectItemsByReferees(self, tenantKey, objType, refereeData, page):
        try:
            helpers.stopwatchStart(f'collectItemsByReferees')

            mobileNo = refereeData.get('mobileNo')
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            loginResult, loginMessage = await self.login(refereeDetail=tenantRefereeDetail, page=page)
            if loginResult == False:
                return None

            #refereeItems = refereeItems[:20]
            if True:
                refereeItems = self.handleUsers.refereesByMobile.get(tenantKey, {})
                tenant = self.cacheService.getTenants().get(tenantKey)
                activeStatus = tenant.get('activeStatus')
                activeRefereeItems = { mobileNo: refereeItems[mobileNo] for mobileNo in refereeItems.keys() if refereeItems[mobileNo].get('status') == activeStatus }
                #refereeItems = {'+972545876156': refereeItems['+972545876156']}
                await self.collectItemsByReferee(tenantKey=tenantKey, objType=objType, referees=activeRefereeItems, refereeData=refereeData, page=page)
            else:
                refereeItems = list(self.handleUsers.refereesByMobile.get(tenantKey, {}).items())
                refereeTasks = []
                tasksCount = 1
                refereesPerRun = round(len(refereeItems) / tasksCount + 0.5)
                for i in range(0, len(refereeItems), refereesPerRun):
                    context = page.context
                    batch_referees = dict(refereeItems[i : i + refereesPerRun])
                    task = asyncio.create_task(self.collectItemsByReferee(tenantKey=tenantKey, objType=objType, referees=batch_referees, refereeData=refereeData, context=context))
                    refereeTasks.append(task)
                self.logger.info(f'collectItemsByReferees: before tasks gather={len(refereeTasks)}')
                tasksResults = await asyncio.gather(*refereeTasks, return_exceptions=True)
                self.logger.info(f'collectItemsByReferees: after tasks gather={len(tasksResults)}')
                for taskResult in tasksResults:
                    if taskResult:
                        page2 = taskResult.get('page')
                        if page2:
                            pass
                            #await page.close()
                        pass

            helpers.stopwatchStop(f'collectItemsByReferees')

        except Exception as ex:
            self.logger.error(f'collectItemsByReferees', ex)

    async def collectItemsByReferee(self, tenantKey, objType, referees:dict, refereeData, page=None, context=None):        
        if page is None:
            page = await context.new_page()
        filteredMobileNos = []
        if (os.getenv('filteredMobileNos')):
            filteredMobileNos = os.getenv('filteredMobileNos', '').split(',')
        idx = 0
        for mobileNo, refereeDetail in referees.items():
            try:
                if False and mobileNo != '+972528996023':
                    continue
                if filteredMobileNos and mobileNo not in filteredMobileNos:
                    continue
                idx += 1
                lastScrape = self.cacheService.getCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName=f'{objType}_lastScrape')
                if False and lastScrape is None:
                    refereeData[objType]['fromDate'] = datetime.now() - timedelta(days=365)
                parsedGames = await self.scrapeListByReferee(tenantKey=tenantKey, objType=objType, refereeData=refereeData, refereeDetail=refereeDetail, page=page)
                if parsedGames is None:
                    self.logger.warning(f"collectItemsByReferee, games scraping failed for referee {mobileNo} {idx}/{len(referees)}")
                    continue

                self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, value=helpers.localNow(), propertyName=f'{objType}_lastScrape')
                prevCollectedItems = self.cacheService.getCollectedItems(tenantKey=tenantKey, objType=objType, mobileNo=mobileNo)
                if len(prevCollectedItems) != len(parsedGames):
                    self.logger.info(f"Changed games found for referee {mobileNo}, updating cache")
                self.cacheService.setCollectedItems(tenantKey=tenantKey, objType=objType, mobileNo=mobileNo, value=parsedGames)
                self.logger.info(f"Collected {len(parsedGames)} items for referee {mobileNo} {idx}/{len(referees)}")
            except Exception as ex:
                self.logger.error(f"❌ collectItemsByReferee, mobileNo={mobileNo}", ex)

        if context:
            await page.close()

        return { 'success': True, 'idx': idx, 'page': page }

    async def scrapeListByReferee(self, tenantKey, objType, refereeData, refereeDetail, page):     
        url = None
        mobileNo = refereeDetail.get('mobileNo')
        refId = refereeDetail.get('refId')
        if not mobileNo or not refId:
            return None
        try:
            if objType == 'games':
                url = self.getGamesUrlByReferee(refId=refId, fromDate=refereeData[objType]['fromDate'], toDate=refereeData[objType]['toDate'])
            elif objType == 'reviews':
                url = self.getReviewsUrl(fromDate=refereeData[objType]['fromDate'], toDate=refereeData[objType]['toDate'])

            if not url:
                return None

            self.logger.info(f"scrape games for referee {mobileNo} url={url}")
            parsedList = await self.scrape_games_with_filters(page=page, url=url, filters=None)
            self.logger.debug(f'parsedList: {parsedList}', refereeDetail=refereeDetail)

            if parsedList is None:
                return None
            
            dicObjects = {}
            for item in parsedList:
                obj = item['game_details']
                obj = self.multiTenantSupport.mapItem(tenantKey=tenantKey, objType=objType, obj=obj)
                obj['mobileNo'] = mobileNo
                obj['refId'] = refId
                obj['internalGameId'] = item['game_id']
                await self.scrapGameDetails(refereeDetail=refereeDetail, internalGameId=item['game_id'], obj=obj, page=page)
                obj['dateText'] = obj['gameDate'] + ' ' + obj['gameTime'][:5]
                obj['date'] = helpers.convert_to_datetime(obj['dateText'])
                obj['gameTitle'] = obj['homeTeamName'] + ' - ' + obj['guestTeamName']
                #obj['referees'] = [ { 'role': obj['role'], 'name': refereeDetail['name'], '* phone': refereeDetail['mobileNo'], '* address': refereeDetail['addressDetails']['address']} ]
                pk = self.getPk(objType=objType, obj=obj)
                obj['gamePk'] = pk
                obj['status'] = 'מאושר' if obj['status'] == 'שיבוץ אושר' else obj['status']
                dicObjects[pk] = obj

                if len(obj['referees']) == 0:
                    self.logger.warning(f'scrapeListByReferee mobileNo={mobileNo}, no referees found for game {obj["gamePk"]} {obj["gameTitle"]} {obj["gameDate"]} {obj["gameTime"]}', **obj)
                    return None

            self.logger.debug(f'n={len(dicObjects)} {dicObjects}')
            return dicObjects

        except Exception as ex:
            self.logger.error(f'scrapeListByReferee mobileNo={mobileNo} refId={refId}', ex)
            return None
        
    def getGamesUrl(self, fromDate=None, toDate=None):
        #https://handballisr.co.il/mgmt/assign_list.asp?ArenaId=0&CompId=0&cYear=2026&toDate=01%2F11%2F2025&fromDate=01%2F11%2F2025&sMonth=100
        fromDateStr = fromDate.strftime("%d/%m/%Y")
        toDateStr = toDate.strftime("%d/%m/%Y")        
        year = toDateStr[:4]
        queryParams = {
            'ArenaId': '0',
            'CompId': '0',
            'cYear': year,
            'fromDate': fromDateStr,
            'toDate': toDateStr,
            'sMonth': '100',
        }
        queryString = urlencode(queryParams)
        url = f'{self.assignerGamesUrl}?{queryString}'
        return url

    def getGamesUrlByReferee(self, refId, fromDate=None, toDate=None):
        fromDateStr = fromDate.strftime("%d/%m/%Y")
        toDateStr = toDate.strftime("%d/%m/%Y")        
        year = toDateStr[:4]
        queryParams = {
            'TabId': '3',
            'PersonId': refId,
            'cYear': year,
            'fromDate': fromDateStr,
            'toDate': toDateStr
        }
        queryString = urlencode(queryParams)
        url = f'{self.refereeGamesUrl}?{queryString}'
        return url

    def getReviewsUrl(self, fromDate=None, toDate=None):
        return self.reviewsUrl

    async def createGameInRefSix(self, page, username, password, gameDetail):
        pass
    
    async def approveGame(self, refereeData, gameId, page, statusCell=None) -> tuple[bool, str]:
        try:
            result, message = await self.approveDeclineGameFromAdminPage(refereeData=refereeData, gameId=gameId, page=page)
            return result, message
        except Exception as ex:
            self.logger.error(f'approveGame', ex)
            return False, str(ex)

    async def declineGame(self, refereeData, gameId, page, statusCell=None) -> tuple[bool, str]:
        try:
            result, message = await self.approveDeclineGameFromAdminPage(refereeData=refereeData, gameId=gameId, page=page, declineReasonId=45)
            return result, message
        except Exception as ex:
            self.logger.error(f'declineGame', ex)
            return False, str(ex)

    async def approveDeclineGameFromAdminPage(self, refereeData, gameId, page, declineReasonId=0) -> tuple[bool, str]:
        async def getNewAssignmentsLinkAndCount(page):
            newAssignmentsLink = None
            newAssignmentsCount = 0
            try:
                # Find the anchor tag with text containing "שיבוצים חדשים"
                newAssignmentsLink = page.locator("a").filter(has_text="שיבוצים חדשים")
                if await newAssignmentsLink.count() == 1:
                    # Get the text content
                    linkText = await newAssignmentsLink.nth(0).inner_text()
                    self.logger.debug(f'Found link text: {linkText}')
                    # Parse number from parentheses using regex
                    match = re.search(r'\((\d+)\)', linkText)
                    if match:
                        newAssignmentsCount = int(match.group(1))
                        self.logger.info(f'Found {newAssignmentsCount} new assignments')
                    else:
                        self.logger.debug('No number found in parentheses')
                else:
                    self.logger.debug('Link with text "שיבוצים חדשים" not found')
            except Exception as e:
                self.logger.debug(f'Error parsing new assignments count: {e}')
            return newAssignmentsLink, newAssignmentsCount

        try:
            gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
            tenantKey = gameDetail['tenantKey']
            tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
            internalGameId = gameDetail.get('internalGameId')
            if not internalGameId:
                return False, 'internalGameId not found'
            globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=refereeData['mobileNo'])
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=refereeData['mobileNo'])
            refId = tenantRefereeDetail['refId']
            if refereeData['loggedIn'] == False:
                loginResult, loginMessage = await self.login(refereeDetail=tenantRefereeDetail, page=page)
                if loginResult == False:
                    return False, loginMessage
                refereeData['loggedIn'] = True

            url = self.getGamesUrlByReferee(refId=refId, fromDate=gameDetail['date'], toDate=gameDetail['date'])
            await page.goto(url)
            await asyncio.sleep(500 / 1000)
            self.logger.info(f'approveGame refId={refId} gameId={gameId} title={page.url}')

            # Use XPath instead of CSS selector to avoid escaping issues
            gameTR = await self.getLocator(parent=page, selector=f"//tr[.//td//a[starts-with(@href, 'Game.asp?GameId={internalGameId}&')]]")
            result = False
            if gameTR:
                #find within gameTR href that starts with javascript:AssignReply(
                assignReplyLink = await self.getLocator(parent=gameTR, selector=f"a[href^='javascript:AssignReply(']")
                if assignReplyLink:
                    await assignReplyLink.click()
                    await asyncio.sleep(500 / 1000)

                    reasonLocators = await self.getLocator(parent=page, selector="select[name='assign_reason_id']")
                    if not reasonLocators:
                        return False, 'reason not found'
                    
                    if declineReasonId > 0:
                        reasonOptions = reasonLocators.locator('option')
                        reasonOptionsTexts = [await reasonOptions.nth(i).text_content() for i in range(await reasonOptions.count())]
                        reasonOptionsValues = [await reasonOptions.nth(i).get_attribute("value") for i in range(await reasonOptions.count())]
                        reasonOptionValue = reasonOptionsValues[1]
                        #await reasonLocators.select_option(reasonOptionValue)
                        await reasonLocators.select_option(str(declineReasonId))
                        # Search for the input with value="אשר" (approve)
                        js = f"javascript:ReplyAssignNow(23);"
                        await page.evaluate(js)
                        result = True
                    else:
                        confirmButtonLocator = await self.getLocator(parent=page, selector="input[type='button'].btn[value*='אשר שיבוץ']")                
                        if confirmButtonLocator:
                            await confirmButtonLocator.click()
                            await asyncio.sleep(500 / 1000)
                            result = True
                else:
                    assignedConfirmedLocator = await self.getLocator(parent=gameTR, selector="span:has-text('שיבוץ אושר')")                
                    if assignedConfirmedLocator:
                        result = True
            if result:
                reportTo = tenant.get('assignmentsReplyReportTo')
                if reportTo:
                    title = f'שיבוץ {"אושר" if declineReasonId == 0 else "נדחה"} עבור משחק {gameDetail["gameTitle"]}'
                    message = f'בתאריך {gameDetail["date"]} על ידי {globalRefereeDetail["name"]}'
                    #sentMsgSid = await self.messagingService.sendMessage(to=reportTo, message=message, gameId=gameDetail['id'])
                    self.cacheService.setNotification(tenantKey=tenantKey, target='refereeGames', id='NONGAME', notificationType='assignmentsReplyReport', to=reportTo, contextDate='created', title=title, message=message)
                    
            return result, 'success'

        except Exception as ex:
            self.logger.error(f'approveDeclineGameFromAdminPage', ex)
            return False, str(ex)

    async def approveDeclineGameFromAdminPage1(self, refereeDetail, gameId, page, declineReasonId=0):
        try:
            refId = refereeDetail['refId']
            gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
            internalGameId = gameDetail.get('internalGameId')
            if not internalGameId:
                return False
            url = self.getGamesUrlByReferee(refId=refereeDetail['refId'], fromDate=gameDetail['date'], toDate=gameDetail['date'])
            await page.goto(url)
            self.logger.info(f'approveGame refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')

            #refereeGameId = '123445'

            # Use XPath instead of CSS selector to avoid escaping issues
            gameTR = page.locator(f"//tr[.//td//a[starts-with(@href, 'Game.asp?GameId={internalGameId}&')]]")
            if (await gameTR.count()) > 0:
                # Use CSS selector for the link within the TR
                pgIdAttr = gameTR.first.locator('a[href^="javascript:AssignReply("]')
                if (await pgIdAttr.count()) > 0:
                    pgIdHref = await pgIdAttr.first.get_attribute('href')
                    pgId = pgIdHref.split('(')[1].split(',')[0]
                    refereeGameId = pgId
            #<a href="javascript:AssignReply(51929,'מכבי &quot;הארזים&quot; ר&quot;ג נגד הפועל פ&quot;ת [08/11/2025]','רוקח 118, רמת גן');"><img src="images/icons/SelectObj.png" style="width:24px;height:24px;" alt="מענה לשיבוץ"></a>
            assignAnswerForm = page.locator("form[name='answer_area']")
            if (await assignAnswerForm.count()) > 0:
                assignAnswerForm = assignAnswerForm.first
                txt = await assignAnswerForm.text_content()
                refereeIdField = assignAnswerForm.locator("input[name='PId']")
                if (await refereeIdField.count()) > 0:
                    refereeIdField = refereeIdField.first
                    await refereeIdField.evaluate(f"element => element.value = '{refId}'")
                    #await refereeIdField.fill(refId)
                    gameIdField = assignAnswerForm.locator("input[name='GId']")
                    if (await gameIdField.count()) > 0:
                        gameIdField = gameIdField.first
                        await gameIdField.evaluate(f"element => element.value = '{internalGameId}'")
                        #await gameIdField.fill(internalGameId)
                        refereeGameIdField = assignAnswerForm.locator("input[name='PGId']")
                        if (await refereeGameIdField.count()) > 0:
                            refereeGameIdField = refereeGameIdField.first
                            await refereeGameIdField.evaluate(f"element => element.value = '{refereeGameId}'")
                            #await refereeGameIdField.fill(refereeGameId)
                            declineReasonField = assignAnswerForm.locator("input[name='RId']")
                            if (await declineReasonField.count()) > 0:
                                declineReasonField = declineReasonField.first
                                await declineReasonField.evaluate(f"element => element.value = '{declineReasonId}'")
                                #await declineReasonField.fill(declineReasonId)
                                await assignAnswerForm.evaluate("form => form.submit()")
                                return True
            return False
        except Exception as ex:
            self.logger.error(f'approveDeclineGameFromAdminPage', ex)
            return False

    async def approveGameUsingFormSubmit(self, refereeDetail, gameId, statusCell, page):
        try:
            '''
            <form action="assign_answer.asp" name="answer_area" id="answer_area" method="post">
                <input type="hidden" name="PGId" id="PGId" value="51726">
                <input type="hidden" name="PId" id="PId" value="0">
                <input type="hidden" name="GId" id="GId" value="0">
                <input type="hidden" name="RId" id="RId" value="0">
                <input type="hidden" name="AnsId" id="AnsId" value="0">
            </form>
            '''
            GId = gameId
            submitFieldsApprove = {
                'PGId': gameId,
                'PId': '0',
                'GId': '0',
                'RId': '0',
                'AnsId': '0',
            }

            self.logger.info(f'approveGame refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
            if statusCell:
                await statusCell.click()
                await asyncio.sleep(500/1000)
                inputsLocators = page.locator("input[name='AssignAns']")
                if await inputsLocators.count() == 1:
                    await inputsLocators.nth(0).click()
                    return True

            return False
        except Exception as ex:
            self.logger.error(f'approveGame', ex)

    async def declineGame1(self, refereeDetail, gameId, statusCell, page):
        try:
            reasonOptions = [
                { 'value': '46', 'text': 'אינני יכול להגיע לאולם זה' },
                { 'value': '56', 'text': 'אינני יכול לשפוט את אחת הקבוצות' },
                { 'value': '55', 'text': 'אינני פנוי בשעה זו - מאוחר מדי' },
                { 'value': '54', 'text': 'אינני פנוי בשעה זו - מוקדם מדי' },
                { 'value': '45', 'text': 'אינני פנוי בתאריך זה' }
            ]
            submitFieldsDecline = {
                'PGId': gameId,
                'PId': '0',
                'GId': '0',
                'RId': '0',
                'AnsId': '45',
            }
            self.logger.info(f'declineGame refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
            if statusCell:
                await statusCell.click()
                await asyncio.sleep(500/1000)
                reasonLocators = page.locator("select")
                cnt = await reasonLocators.count()
                if reasonLocators and await reasonLocators.count() == 1:
                    reasonOptions = reasonLocators.locator('option')
                    reasonOptionsTexts = [await reasonOptions.nth(i).text_content() for i in range(await reasonOptions.count())]
                    reasonOptionsValues = [await reasonOptions.nth(i).get_attribute("value") for i in range(await reasonOptions.count())]
                    reasonOptionValue = reasonOptionsValues[1]
                    await reasonLocators.select_option(reasonOptionValue)

                    return True

            return False
        except Exception as ex:
            self.logger.error(f'declineGame', ex)

    def sendGameAnswer(self, gameId, declineReasonId=0):
        try:
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            submitFields = {
                'PGId': gameId,
                'PId': '0',
                'GId': '0',
                'RId': '0',
                'AnsId': declineReasonId,
            }
            #Key	Value
            #fbssls_517931738222367	{"authResponse":null,"status":"unknown","expiresAt":1760628756315}
            response = requests.post(url=f'{self.gameAnswerUrl}', headers=headers, data=submitFields)
            response.raise_for_status()  # Raise an exception for bad status codes
            jsonResponse = response.json()
            return jsonResponse
        except requests.exceptions.RequestException as ex:
            self.logger.error(f"An error occurred:", ex)
            if ex.response:
                self.logger.error(f"Error details: {ex.response.text}")
            return None
        except Exception as ex:
            self.logger.error(f"An error occurred, submitFields={submitFields}", ex)
            return None

    async def generatePostGameUpdateTemplate(self, gameDetail):
        msg = f'*סיכום משחק*'
        msg += f'\nמסגרת משחקים: {gameDetail["tournamentName"]}'
        msg += f'\nקבוצות: {gameDetail["homeTeamName"]}-{gameDetail["guestTeamName"]}'
        msg += f'\nמזהה: {gameDetail["id"]}'
        msg += f'\nביתית סיום:\n0'
        msg += f'\nאורחת סיום:\n0'
        msg += f'\n\nבנוסף, יש לשלוח לבוט את דו״ח המשחק'
        return msg

    async def beforeGameUpdateByOrgService(self, refereeDetail, gameId, data, page, statusCell=None) -> tuple[bool, str]:
        try:
            self.logger.info(f'beforeGameUpdateByOrgService refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')

            loginResult, loginMessage = await self.login(refereeDetail=refereeDetail, page=page)
            if not loginResult:
                return False, loginMessage
            
            gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
            internalGameId = gameDetail.get('internalGameId')
            if not internalGameId:
                return False, 'internalGameId not found'
            url = f"{self.protocol}{self.baseUrl}/mgmt/Game.asp?GameId={internalGameId}&TabId=1"
            await page.goto(url)
            await self.wait_for_load_state(page)
            
            return True, 'success'
        except Exception as ex:
            self.logger.error(f'beforeGameUpdateByOrgService', ex)
            return False, str(ex)

    async def afterGameUpdateByOrgService(self, refereeDetail, gameId, data, page, statusCell=None):
        try:
            self.logger.info(f'afterGameUpdateByOrgService refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
            await page.evaluate(f"javascript:Upd2(3,10,25);")

            modalDivLocator = await self.getLocator(parent=page, selector="div.modal-dialog:has-text('תוצאה עודכנה')")
            if modalDivLocator:
                closeButtonLocator = await self.getLocator(parent=modalDivLocator, selector="button:has-text('סגור')")
                if closeButtonLocator:
                    await closeButtonLocator.click()
                    await asyncio.sleep(250 / 1000)

            return True
        except Exception as ex:
            self.logger.error(f'afterGameUpdateByOrgService', ex)

        return False

    async def postGameReport(self, refereeDetail, gameId, data, page) -> tuple[bool, str]:
        try:
            self.logger.info(f'postGameReport refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
            gameReportFilePath = data.get('storagePath!')
            if gameReportFilePath:
                await page.evaluate("javascript:UploadFile11('game_referee_report');")
                await asyncio.sleep(500/1000)
                print("✅ UploadFile11 called")
                
                # Task 3: Upload file and submit form
                fileExists = os.path.exists(gameReportFilePath)
                iframe = page.frame_locator("iframe")
                await iframe.locator("input[name='my_file']").set_input_files(gameReportFilePath)
                
                await page.locator("input[name='upd']").first.click()
                await page.wait_for_timeout(1000)
                print("✅ File uploaded")

                return True, 'success'

        except Exception as ex:
            self.logger.error(f'postGameReport', ex)
            return False, str(ex)

    async def gamePostUpdate1(self, refereeDetail, gameId, data, page, statusCell=None):
        try:
            homeTeamScore = data.get('homeTeam#1')
            guestTeamScore = data.get('guestTeam#1')
            gameReportFilePath = data.get('storagePath')
            gameNotes = data.get('gameNotes')
            
            # Task 1: Fill score fields
            if homeTeamScore:
                await page.locator("input[name='score_team1']").first.fill(homeTeamScore)
            
            if guestTeamScore:
                await page.locator("input[name='score_team2']").first.fill(guestTeamScore)
            
            # Task 2: Call UploadFile11 JavaScript
            if gameReportFilePath:
                await page.evaluate("javascript:UploadFile11('game_referee_report');")
                await asyncio.sleep(500/1000)
                print("✅ UploadFile11 called")
                
                # Task 3: Upload file and submit form
                fileExists = os.path.exists(gameReportFilePath)
                iframe = page.frame_locator("iframe")
                await iframe.locator("input[name='my_file']").set_input_files(gameReportFilePath)
                
                await page.locator("input[name='upd']").first.click()
                await page.wait_for_timeout(1000)
                print("✅ File uploaded")
            
            # Task 4: Fill game notes
            if gameNotes:
                await page.locator("textarea[name='game_notes']").first.fill(gameNotes)
            print("✅ Game notes filled")
            
            # Task 5: Call Upd2 JavaScript
            if homeTeamScore and guestTeamScore:
                await page.evaluate(f"javascript:Upd2(3,10,25);")
                print("✅ Upd2 called")
            
            return True
        except Exception as ex:
            self.logger.error(f'postGameUpdate', ex)
        
        return False

    async def getCupsList(self):
        pass
    
    async def getLeagueName(self, page, tournamentUrl):
        pass
    
    async def getLeaguesList(self):
        pass
    
    def getPk(self, objType, obj):
        data = self.dataDic[objType]
        pk = ''
        for tag in data['pkTags']:
            if tag not in obj:
                continue
            pk += obj[tag].replace(':', '').replace('-', '')
        return pk

    async def getTournamentGamesUrl(self, page, tournament, round, fixture):
        pass
    
    async def refreshTournamentGame(self, tenantKey, page, tournamentName, gameDetail):
        pass
    
    async def refreshLeaguesTablesByTournament(self, page, tournament, section):
        pass

    async def refreshLeaguesTables(self, tenantKey, tournamentName=None):
        pass
    
    async def set_date_filter(self, page, from_date, to_date):
        """Set date range filter."""
        try:
            # Set from date
            await page.fill('input[name="fromDate"]', from_date)
            self.logger.info(f"Set from date: {from_date}")
            
            # Set to date
            await page.fill('input[name="toDate"]', to_date)
            self.logger.info(f"Set to date: {to_date}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error setting date filter:", e)
            return False
    
    async def set_season_filter(self, page, season_year):
        """Set season filter by year."""
        try:
            # Select season from dropdown
            await page.select_option('select[name="cYear"]', str(season_year))
            self.logger.info(f"Set season: {season_year}")
            return True
        except Exception as e:
            self.logger.error(f"Error setting season filter:", e)
            return False
    
    async def set_month_filter(self, page, month):
        """Set month filter (1-12 or 100 for date range)."""
        try:
            await page.select_option('select[name="sMonth"]', str(month))
            self.logger.info(f"Set month: {month}")
            return True
        except Exception as e:
            self.logger.error(f"Error setting month filter:", e)
            return False
    
    async def apply_filters(self, page):
        """Apply all filters by clicking search button."""
        try:
            # Click search button
            await page.click('input[name="search_branch"]')
            self.logger.info("Applied filters")
            
            # Wait for page to load
            await page.wait_for_timeout(2000)
            return True
        except Exception as e:
            self.logger.error(f"Error applying filters:", e)
            return False
    
    async def read_games(self, page):
        table_index=None

        await page.wait_for_selector(
            self._IHA_DEVICES_TABLE_SEL, timeout=self._IHA_DEVICES_TABLE_TIMEOUT_MS
        )
        tables = await page.query_selector_all('table.devices')
        if not tables:
            self.logger.warning("No tables with class 'devices' found")
            return None
        
        # Select table based on index
        if table_index is None:
            # Use the last table
            selected_table = tables[-1]
            self.logger.debug(f"Using last table (index {len(tables)-1})")
        else:
            # Use specified table index
            if table_index >= len(tables):
                self.logger.warning(f"Table index {table_index} out of range. Available tables: {len(tables)}")
                return None
            selected_table = tables[table_index]
            self.logger.debug(f"Using table at index {table_index}")
        
        # Find rows in the selected table
        rows = await selected_table.query_selector_all('tbody tr')
        self.logger.debug(f"Found {len(rows)-1} rows in the selected table")
        
        games = []
        
        for i, row in enumerate(rows[1:]):
            # Extract all cells in the row
            cells = await row.query_selector_all('td')
            if len(cells) < 10:  # Skip if not enough columns
                continue
            
            # Extract game data
            game_data = {
                'row_number': i + 1,
                'extraction_timestamp': datetime.now().isoformat(),
                'game_details': {},
                'links': {}
            }
            
            imgAlt2text = {
                "מענה לשיבוץ": "טרם אושר",
            }

            # Extract data from each cell based on position
            for j, cell in enumerate(cells):
                cell_text = (await cell.text_content()).strip().replace('\xa0', ' ').replace('  ', ' ')
                cell_a_img = await cell.query_selector_all("a > img")
                cell_a_img_alt = ''
                if len(cell_a_img) == 1:
                    cell_a_img_alt = await cell_a_img[0].get_attribute('alt')
                if cell_text or cell_a_img_alt:
                    # Map cell positions to field names based on the HTML structure
                    field_mapping = {
                        0: 'פרטים נוספים',  # פרטים נוספים
                        1: 'דיווח תוצאה',       # דיווח תוצאה
                        2: 'סטטוס',             # סטטוס
                        3: 'תפקיד',               # תפקיד
                        4: 'אולם',              # אולם
                        5: 'קבוצה אורחת',          # קבוצה אורחת
                        6: 'קבוצה מארחת',          # קבוצה מארחת
                        7: 'מסגרת',        # מסגרת
                        8: 'שעת משחק',          # שעת משחק
                        9: 'תאריך משחק'           # תאריך משחק
                    }
                    
                    if j in field_mapping:
                        if cell_text:
                            text = cell_text
                        elif cell_a_img_alt:
                            text = imgAlt2text.get(cell_a_img_alt)
                        
                        if text:
                            game_data['game_details'][field_mapping[j]] = text
            
            # Extract links from cells
            for j, cell in enumerate(cells):
                links = await cell.query_selector_all('a')
                for link in links:
                    href = await link.get_attribute('href')
                    link_text = await link.text_content()
                    cell_a_img = await link.query_selector_all('img')
                    cell_a_img_alt = ''
                    if cell_a_img and len(cell_a_img) == 1:
                        cell_a_img_alt = await cell_a_img[0].get_attribute('alt')
                    if href and (link_text or cell_a_img_alt):
                        if j == 0:  # Game details link
                            game_data['links']['game_details'] = href
                        elif j == 1:  # Result report link
                            game_data['links']['result_report'] = href
                        elif j == 2:  # Status link
                            game_data['links']['status'] = href
                        elif j == 4:  # Venue link
                            game_data['links']['venue'] = href
                        elif j == 8:  # Game time link
                            game_data['links']['game_time'] = href
                        elif j == 9:  # Game date link
                            game_data['links']['game_date'] = href
            
            # Extract game ID from links if available
            if 'game_details' in game_data['links']:
                href = game_data['links']['game_details']
                if 'GameId=' in href:
                    game_id = href.split('GameId=')[1].split('&')[0]
                    game_data['game_id'] = game_id
            
            if game_data['game_details']:
                games.append(game_data)
                self.logger.debug(f"Extracted game {len(games)}: {game_data.get('game_details', {}).get('תאריך משחק', 'Unknown date')}")
        
        self.logger.debug(f"Successfully extracted {len(games)} games from table")
        return games
            
    async def read_referees(self, page):
        url = page.url if page else None
        try:
            table_index=None
            await page.wait_for_selector(
                self._IHA_DEVICES_TABLE_SEL, timeout=self._IHA_DEVICES_TABLE_TIMEOUT_MS
            )
            tables = await page.query_selector_all('table.devices')
            if not tables:
                self.logger.warning("No tables with class 'devices' found")
                return []
            
            # Select table based on index
            if table_index is None:
                # Use the last table
                selected_table = tables[-1]
                self.logger.debug(f"Using last table (index {len(tables)-1})")
            else:
                # Use specified table index
                if table_index >= len(tables):
                    self.logger.warning(f"Table index {table_index} out of range. Available tables: {len(tables)}")
                    return []
                selected_table = tables[table_index]
                self.logger.debug(f"Using table at index {table_index}")
            
            # Find rows in the selected table
            rows = await selected_table.query_selector_all('tbody tr')
            self.logger.debug(f"Found {len(rows)-1} rows in the selected table")
            
            referees = []
            
            for i, row in enumerate(rows[1:]):
                try:
                    # Extract all cells in the row
                    cells = await row.query_selector_all('td')
                    if len(cells) < 6:  # Skip if not enough columns
                        continue
                    
                    # Extract game data
                    referee_data = {
                        'row_number': i + 1,
                        'extraction_timestamp': datetime.now().isoformat(),
                        'referee_details': {},
                        'links': {}
                    }
                    
                    imgAlt2text = {
                        "מענה לשיבוץ": "טרם אושר",
                    }

                    # Extract data from each cell based on position
                    for j, cell in enumerate(cells):
                        cell_text = (await cell.text_content()).strip().replace('\xa0', ' ').replace('  ', ' ')
                        cell_a_img = await cell.query_selector_all("a > img")
                        cell_a_img_alt = ''
                        if len(cell_a_img) == 1:
                            cell_a_img_alt = await cell_a_img[0].get_attribute('alt')
                        if cell_text or cell_a_img_alt:
                            # Map cell positions to field names based on the HTML structure
                            field_mapping = {
                                5: 'ID',  # קוד שופט
                                4: 'תפקיד',       # תפקיד
                                3: 'שם',             # שם
                                2: 'כרטיס אישי',               # כרטיס אישי
                                1: 'סטטוס',              # סטטוס
                                0: 'הסר רשומה',          # הסר רשומה
                            }
                            
                            if j in field_mapping:
                                if cell_text:
                                    text = cell_text
                                elif cell_a_img_alt:
                                    text = imgAlt2text.get(cell_a_img_alt)
                                
                                if text:
                                    referee_data['referee_details'][field_mapping[j]] = text
                    
                    # Extract links from cells
                    for j, cell in enumerate(cells):
                        links = await cell.query_selector_all('a')
                        for link in links:
                            href = await link.get_attribute('href')
                            link_text = await link.text_content()
                            cell_a_img = await link.query_selector_all('img')
                            cell_a_img_alt = ''
                            if cell_a_img and len(cell_a_img) == 1:
                                cell_a_img_alt = await cell_a_img[0].get_attribute('alt')
                            if href and (link_text or cell_a_img_alt):
                                if j == 0:  # remove record link
                                    referee_data['links']['remove_record'] = href
                                elif j in [2, 3, 5]:  # personal card link
                                    referee_data['links']['personal_card'] = href
                    
                    # Extract game ID from links if available
                    if 'referee_details' in referee_data['links']:
                        href = referee_data['links']['referee_details']
                        if 'GameId=' in href:
                            game_id = href.split('GameId=')[1].split('&')[0]
                            referee_data['game_id'] = game_id
                    
                    if referee_data['referee_details']:
                        referees.append(referee_data)
                        self.logger.debug(f"Extracted referees {len(referees)}: {referee_data.get('referee_details', {}).get('שם', 'Unknown name')}")
                
                except Exception as e:
                    self.logger.warning(f"Error processing row {i+1}:", e)
                    continue
            
            self.logger.debug(f"Successfully extracted {len(referees)} referees from table")
            return referees
            
        except Exception as ex:
            msg = f"Error extracting referees from table"
            if url:
                msg += f" url={url}"
            if ex.__class__.__name__ == 'TimeoutError':
                msg = (
                    f"{msg} (timeout after {self._IHA_DEVICES_TABLE_TIMEOUT_MS}ms waiting for "
                    f"{self._IHA_DEVICES_TABLE_SEL}; page may be slow or table missing)"
                )
            self.logger.error(msg + ":", ex, takeScreenshot=True)
            return None

    async def scrape_games_with_filters(self, page, url, filters=None):
        """Scrape games with specified filters and optional login."""
        page = await self.gotoUrl(page=page, url=url)
                    
        if filters:
            if 'from_date' in filters and 'to_date' in filters:
                await self.set_date_filter(page, filters['from_date'], filters['to_date'])
            
            if 'season_year' in filters:
                await self.set_season_filter(page, filters['season_year'])
            
            if 'month' in filters:
                await self.set_month_filter(page, filters['month'])
            
            await self.apply_filters(page)
        
        welcome_div = await page.query_selector_all('div#welcome')
        if not welcome_div:
            return None
        
        parsed_games = await self.read_games(page)
        
        return parsed_games
    
    async def get_available_seasons(self, page):
        """Get all available seasons from the dropdown."""
        try:
            season_options = await page.query_selector_all('select[name="cYear"] option')
            seasons = []
            
            for option in season_options:
                value = await option.get_attribute('value')
                text = await option.text_content()
                if value and value != '0' and text:
                    seasons.append({
                        'value': value,
                        'text': text.strip()
                    })
            
            self.logger.info(f"Found {len(seasons)} available seasons")
            return seasons
            
        except Exception as e:
            self.logger.error(f"Error getting available seasons:", e)
            return []
    
    async def get_available_months(self, page):
        """Get all available months from the dropdown."""
        try:
            month_options = await page.query_selector_all('select[name="sMonth"] option')
            months = []
            
            for option in month_options:
                value = await option.get_attribute('value')
                text = await option.text_content()
                if value and text:
                    months.append({
                        'value': value,
                        'text': text.strip()
                    })
            
            self.logger.info(f"Found {len(months)} available months")
            return months
            
        except Exception as e:
            self.logger.error(f"Error getting available months:", e)
            return []
    
    async def list_available_tables(self, page):
        """List all available tables with class 'devices' for debugging."""
        try:
            tables = await page.query_selector_all('table.devices')
            table_info = []
            
            for i, table in enumerate(tables):
                # Get table info
                rows = await table.query_selector_all('tbody tr')
                table_info.append({
                    'index': i,
                    'row_count': len(rows),
                    'is_last': i == len(tables) - 1
                })
            
            self.logger.info(f"Found {len(tables)} tables with class 'devices':")
            for info in table_info:
                self.logger.info(f"  Table {info['index']}: {info['row_count']} rows {'(LAST)' if info['is_last'] else ''}")
            
            return table_info
            
        except Exception as e:
            self.logger.error(f"Error listing available tables:", e)
            return []

    async def scrapGameDetails(self, refereeDetail, internalGameId, obj, page):
        self.logger.debug(f'scrapGameDetails refId={refereeDetail["refId"]} internalGameId={internalGameId}')
        if not internalGameId:
            return False

        tenantKey = refereeDetail['tenantKey']

        url = f"{self.protocol}{self.baseUrl}/mgmt/Game.asp?GameId={internalGameId}&TabId=2"
        await page.goto(url)
        await self.wait_for_load_state(page)

        referees = await self.read_referees(page)
        obj['referees'] = []
        if referees:
            for referee in referees:
                refId = referee.get('referee_details', {}).get('ID')
                refDetail = self.handleUsers.refereesByRefId.get(tenantKey, {}).get(refId)
                if refDetail:
                    if not refDetail.get('name'):
                        pass
                    obj['referees'].append({ 'role': referee.get('referee_details', {}).get('תפקיד'), '* name': refDetail['name'], '* phone': refDetail['mobileNo'], '* address': refDetail.get('addressDetails', {}).get('address') })
                else:
                    obj['referees'].append({ 'role': referee.get('referee_details', {}).get('תפקיד'), '* name': referee.get('referee_details', {}).get('שם'), '* phone': '', '* address': '' })
        
        url = f"{self.protocol}{self.baseUrl}/mgmt/Game.asp?GameId={internalGameId}&TabId=0"
        await page.goto(url)
        await self.wait_for_load_state(page)
        
        select = await self._extrace_select_value(page, 'GN')
        obj['fixture'] = select.get('value') if select else ''

        spanResult = await page.query_selector('span.f16Black.fBold')
        if spanResult:
            resultSpanText = (await spanResult.text_content()).strip().replace('\xa0', ' ').replace('  ', ' ')
            resultText = resultSpanText.split('ל:')[0].strip()
            winnerScore = resultText.split('-')[0].strip()
            loserScore = resultText.split('-')[1].strip()
            winnerTeam = resultSpanText.split('ל:')[1].strip()
            if winnerScore != loserScore:
                if winnerTeam == obj['homeTeamName']:
                    obj['homeTeamScore'] = winnerScore
                    obj['guestTeamScore'] = loserScore
                else:
                    obj['homeTeamScore'] = loserScore
                    obj['guestTeamScore'] = winnerScore
            else:
                obj['homeTeamScore'] = winnerScore
                obj['guestTeamScore'] = loserScore
            obj['gameResult'] = { 'full_time_score': [obj["homeTeamScore"], obj["guestTeamScore"]] }

        gameCommentLocator = await page.query_selector('textarea[name="game_notes"]')
        if gameCommentLocator:
            gameComment = await gameCommentLocator.text_content()
            obj['comment'] = gameComment

    async def scrapGameDetails1(self, page, gameLink, refereeGame):
        page = await self.gotoUrl(page, f'{self.protocol}{self.baseUrl}/mgmt/{gameLink}')
        await asyncio.sleep(500 / 1000)
        game_data = await self._extract_game_data(page=page)
        fixture = game_data.get('game_settings', {}).get('round', {}).get('value', '')
        internalGameId = game_data.get('forms', {}).get('hidden_GameId', '')
        refereeGame['fixture'] = fixture
        refereeGame['internalGameId'] = internalGameId
        self.logger.info(f"fixture: {fixture}", **refereeGame)
        return
        select_options = await self.scan_all_select_tags(page=page, refereeDetail=refereeGame)
        jsonHelper.save_to_file(select_options, f'select_options_handball.json')
        pass

    async def _extrace_select_value(self, page, selectName):
        select = await page.query_selector(f'select[name="{selectName}"]')
        if select:
            selected_option = await select.query_selector('option[selected]')
            if selected_option:
                text = await selected_option.text_content()
                value = await selected_option.get_attribute('value')
                return {
                    'text': text,
                    'value': value
                }
        return None

    async def _extract_game_data(self, page) -> Dict[str, Any]:
        """Extract all game data from the current page"""
        game_data = {
            'extraction_timestamp': datetime.now().isoformat(),
            'game_basic_info': {},
            'teams': {},
            'venue_info': {},
            'game_settings': {},
            'breadcrumbs': [],
            'navigation_tabs': [],
            'forms': {},
            'modals': {}
        }

        try:
            # Extract basic game information
            game_data['game_basic_info'] = await self._extract_basic_info(page=page)
            
            # Extract team information
            game_data['teams'] = await self._extract_team_info(page=page)
            
            # Extract venue information
            game_data['venue_info'] = await self._extract_venue_info(page=page)
            
            # Extract game settings from forms
            game_data['game_settings'] = await self._extract_game_settings(page=page)
            
            # Extract breadcrumbs
            game_data['breadcrumbs'] = await self._extract_breadcrumbs(page=page)
            
            # Extract navigation tabs
            game_data['navigation_tabs'] = await self._extract_navigation_tabs(page=page)
            
            # Extract form data
            game_data['forms'] = await self._extract_form_data(page=page)
            
            # Extract modal information
            game_data['modals'] = await self._extract_modal_data(page=page)
            
        except Exception as e:
            self.logger.debug(f"Error during data extraction:", e)
            game_data['extraction_error'] = str(e)

        return game_data

    async def _extract_basic_info(self, page) -> Dict[str, Any]:
        """Extract basic game information"""
        basic_info = {}
        
        try:
            # Extract game title and teams
            title_element = await page.query_selector('div.f16Black.fBold')
            if title_element:
                title_text = await title_element.text_content()
                basic_info['game_title'] = title_text.strip() if title_text else None
                
                # Parse team names and game ID from title
                if title_text:
                    # Extract game ID from title like "[746] מ.כ. חולון 2 נגד [720] א.כ. נס ציונה [03/05/2025]"
                    game_id_match = re.search(r'\[(\d+)\]', title_text)
                    if game_id_match:
                        basic_info['game_id'] = game_id_match.group(1)
                    
                    # Extract date from title
                    date_match = re.search(r'\[(\d{2}/\d{2}/\d{4})\]', title_text)
                    if date_match:
                        basic_info['game_date'] = date_match.group(1)

            # Extract game result
            result_element = await page.query_selector('span.f16Black.fBold')
            if result_element:
                result_text = await result_element.text_content()
                basic_info['game_result'] = result_text.strip() if result_text else None

        except Exception as e:
            self.logger.debug(f"Error extracting basic info:", e)
            basic_info['error'] = str(e)

        return basic_info

    async def _extract_team_info(self, page) -> Dict[str, Any]:
        """Extract team information"""
        teams = {'home_team': {}, 'away_team': {}}
        
        try:
            # Extract home team info
            home_team_select = await page.query_selector('select[name="team1"]')
            if home_team_select:
                selected_option = await home_team_select.query_selector('option[selected]')
                if selected_option:
                    home_team_text = await selected_option.text_content()
                    home_team_value = await selected_option.get_attribute('value')
                    teams['home_team'] = {
                        'name': home_team_text.strip() if home_team_text else None,
                        'value': home_team_value
                    }

            # Extract away team info
            away_team_select = await page.query_selector('select[name="team2"]')
            if away_team_select:
                selected_option = await away_team_select.query_selector('option[selected]')
                if selected_option:
                    away_team_text = await selected_option.text_content()
                    away_team_value = await selected_option.get_attribute('value')
                    teams['away_team'] = {
                        'name': away_team_text.strip() if away_team_text else None,
                        'value': away_team_value
                    }

        except Exception as e:
            self.logger.debug(f"Error extracting team info:", e)
            teams['error'] = str(e)

        return teams

    async def _extract_venue_info(self, page) -> Dict[str, Any]:
        """Extract venue and arena information"""
        venue_info = {}
        
        try:
            # Extract arena
            arena_select = await page.query_selector('select[name="game_arena"]')
            if arena_select:
                selected_arena = await arena_select.query_selector('option[selected]')
                if selected_arena:
                    arena_text = await selected_arena.text_content()
                    arena_value = await selected_arena.get_attribute('value')
                    venue_info['arena'] = {
                        'name': arena_text.strip() if arena_text else None,
                        'value': arena_value
                    }

            # Extract broadcast channel
            broadcast_select = await page.query_selector('select[name="liveOn"]')
            if broadcast_select:
                selected_channel = await broadcast_select.query_selector('option[selected]')
                if selected_channel:
                    channel_text = await selected_channel.text_content()
                    channel_value = await selected_channel.get_attribute('value')
                    venue_info['broadcast_channel'] = {
                        'name': channel_text.strip() if channel_text else None,
                        'value': channel_value
                    }

            # Extract viewers count
            viewers_input = await page.query_selector('input[name="total_viewers"]')
            if viewers_input:
                viewers_value = await viewers_input.get_attribute('value')
                venue_info['viewers_count'] = viewers_value

        except Exception as e:
            self.logger.debug(f"Error extracting venue info:", e)
            venue_info['error'] = str(e)

        return venue_info

    async def _extract_game_settings(self, page) -> Dict[str, Any]:
        """Extract game settings and configuration"""
        settings = {}
        
        try:
            # Extract season
            season_select = await page.query_selector('select[name="cYear"]')
            if season_select:
                selected_season = await season_select.query_selector('option[selected]')
                if selected_season:
                    season_text = await selected_season.text_content()
                    season_value = await selected_season.get_attribute('value')
                    settings['season'] = {
                        'name': season_text.strip() if season_text else None,
                        'value': season_value
                    }

            # Extract competition
            comp_select = await page.query_selector('select[name="CompId"]')
            if comp_select:
                selected_comp = await comp_select.query_selector('option[selected]')
                if selected_comp:
                    comp_text = await selected_comp.text_content()
                    comp_value = await selected_comp.get_attribute('value')
                    settings['competition'] = {
                        'name': comp_text.strip() if comp_text else None,
                        'value': comp_value
                    }

            # Extract game date
            date_input = await page.query_selector('input[name="game_date_txt"]')
            if date_input:
                date_value = await date_input.get_attribute('value')
                settings['game_date'] = date_value

            # Extract game time
            time_input = await page.query_selector('input[name="TimeOfGame"]')
            if time_input:
                time_value = await time_input.get_attribute('value')
                settings['game_time'] = time_value

            # Extract round number
            round_select = await page.query_selector('select[name="GN"]')
            if round_select:
                selected_round = await round_select.query_selector('option[selected]')
                if selected_round:
                    round_text = await selected_round.text_content()
                    round_value = await selected_round.get_attribute('value')
                    settings['round'] = {
                        'name': round_text.strip() if round_text else None,
                        'value': round_value
                    }

            # Extract game notes
            notes_textarea = await page.query_selector('textarea[name="game_notes"]')
            if notes_textarea:
                notes_value = await notes_textarea.text_content()
                settings['game_notes'] = notes_value.strip() if notes_value else None

        except Exception as e:
            self.logger.debug(f"Error extracting game settings:", e)
            settings['error'] = str(e)

        return settings

    async def _extract_breadcrumbs(self, page) -> list:
        """Extract breadcrumb navigation"""
        breadcrumbs = []
        
        try:
            breadcrumb_div = await page.query_selector('div.f13Black')
            if breadcrumb_div:
                breadcrumb_text = await breadcrumb_div.text_content()
                if breadcrumb_text:
                    # Split by ">" and clean up
                    parts = breadcrumb_text.split('>')
                    for part in parts:
                        cleaned = part.strip()
                        if cleaned:
                            breadcrumbs.append(cleaned)

        except Exception as e:
            self.logger.debug(f"Error extracting breadcrumbs:", e)

        return breadcrumbs

    async def _extract_navigation_tabs(self, page) -> list:
        """Extract navigation tabs"""
        tabs = []
        
        try:
            tab_elements = await page.query_selector_all('ul.nav.navbar-nav li')
            for tab in tab_elements:
                link = await tab.query_selector('a')
                if link:
                    tab_text = await link.text_content()
                    tab_href = await link.get_attribute('href')
                    is_active = 'active' in await tab.get_attribute('class')
                    
                    tabs.append({
                        'text': tab_text.strip() if tab_text else None,
                        'href': tab_href,
                        'active': is_active
                    })

        except Exception as e:
            self.logger.debug(f"Error extracting navigation tabs:", e)

        return tabs

    async def _extract_form_data(self, page) -> Dict[str, Any]:
        """Extract all form data"""
        forms = {}
        
        try:
            # Extract hidden form fields
            hidden_inputs = await page.query_selector_all('input[type="hidden"]')
            for input_elem in hidden_inputs:
                name = await input_elem.get_attribute('name')
                value = await input_elem.get_attribute('value')
                if name:
                    forms[f'hidden_{name}'] = value

            # Extract form action URLs
            game_form = await page.query_selector('form[name="game_settings"]')
            if game_form:
                action = await game_form.get_attribute('action')
                method = await game_form.get_attribute('method')
                forms['game_settings_form'] = {
                    'action': action,
                    'method': method
                }

            upd_form = await page.query_selector('form[name="upd_area"]')
            if upd_form:
                action = await upd_form.get_attribute('action')
                method = await upd_form.get_attribute('method')
                forms['update_form'] = {
                    'action': action,
                    'method': method
                }

        except Exception as e:
            self.logger.debug(f"Error extracting form data:", e)
            forms['error'] = str(e)

        return forms

    async def _extract_modal_data(self, page) -> Dict[str, Any]:
        """Extract modal dialog information"""
        modals = {}
        
        try:
            # Extract reply modal
            reply_modal = await page.query_selector('#ReplyModal')
            if reply_modal:
                title = await reply_modal.query_selector('.modal-title')
                if title:
                    title_text = await title.text_content()
                    modals['reply_modal'] = {
                        'title': title_text.strip() if title_text else None,
                        'id': 'ReplyModal'
                    }

            # Extract file upload modal
            file_modal = await page.query_selector('#FileModal11')
            if file_modal:
                title = await file_modal.query_selector('.modal-title')
                if title:
                    title_text = await title.text_content()
                    modals['file_upload_modal'] = {
                        'title': title_text.strip() if title_text else None,
                        'id': 'FileModal11'
                    }

            # Extract new arena modal
            arena_modal = await page.query_selector('#NewArena')
            if arena_modal:
                title = await arena_modal.query_selector('.modal-title')
                if title:
                    title_text = await title.text_content()
                    modals['new_arena_modal'] = {
                        'title': title_text.strip() if title_text else None,
                        'id': 'NewArena'
                    }

        except Exception as e:
            self.logger.debug(f"Error extracting modal data:", e)
            modals['error'] = str(e)

        return modals

    async def scan_all_select_tags(self, page, refereeDetail=None):
        """
        Scan all select tags on the current page and extract all value/text options.
        
        Args:
            page: Playwright page object
            refereeDetail: Optional referee details for logging context
            
        Returns:
            dict: Dictionary containing all select tags and their options
        """
        try:
            self.logger.info("Scanning all select tags on page", refereeDetail=refereeDetail)
            
            select_data = {
                'extraction_timestamp': datetime.now().isoformat(),
                'select_tags': {},
                'total_selects': 0,
                'page_url': page.url
            }
            
            # Find all select elements
            select_elements = await page.query_selector_all('select')
            select_data['total_selects'] = len(select_elements)
            
            self.logger.debug(f"Found {len(select_elements)} select tags", refereeDetail=refereeDetail)
            
            for i, select_elem in enumerate(select_elements):
                try:
                    # Get select element attributes
                    select_name = await select_elem.get_attribute('name')
                    select_id = await select_elem.get_attribute('id')
                    select_class = await select_elem.get_attribute('class')
                    is_disabled = await select_elem.get_attribute('disabled')
                    is_multiple = await select_elem.get_attribute('multiple')
                    
                    # Create unique key for this select
                    select_key = select_name or select_id or f"select_{i}"
                    
                    select_info = {
                        'index': i,
                        'name': select_name,
                        'id': select_id,
                        'class': select_class,
                        'disabled': is_disabled is not None,
                        'multiple': is_multiple is not None,
                        'options': [],
                        'selected_values': [],
                        'selected_texts': []
                    }
                    
                    # Get all option elements within this select
                    option_elements = await select_elem.query_selector_all('option')
                    
                    for j, option_elem in enumerate(option_elements):
                        try:
                            option_value = await option_elem.get_attribute('value')
                            option_text = await option_elem.text_content()
                            is_selected = await option_elem.get_attribute('selected')
                            is_disabled_opt = await option_elem.get_attribute('disabled')
                            
                            option_info = {
                                'index': j,
                                'value': option_value,
                                'text': option_text.strip() if option_text else None,
                                'selected': is_selected is not None,
                                'disabled': is_disabled_opt is not None
                            }
                            
                            select_info['options'].append(option_info)
                            
                            # Track selected options
                            if is_selected is not None:
                                select_info['selected_values'].append(option_value)
                                select_info['selected_texts'].append(option_text.strip() if option_text else None)
                                
                        except Exception as e:
                            self.logger.warning(f"Error processing option {j} in select {select_key}: {e}", refereeDetail=refereeDetail)
                            continue
                    
                    # Store select information
                    select_data['select_tags'][select_key] = select_info
                    
                    self.logger.debug(f"Processed select '{select_key}' with {len(select_info['options'])} options", refereeDetail=refereeDetail)
                    
                except Exception as e:
                    self.logger.warning(f"Error processing select {i}: {e}", refereeDetail=refereeDetail)
                    continue
            
            self.logger.info(f"Successfully scanned {len(select_data['select_tags'])} select tags", refereeDetail=refereeDetail)
            return select_data
            
        except Exception as e:
            self.logger.error(f"Error scanning select tags: {e}", refereeDetail=refereeDetail)
            return {
                'extraction_timestamp': datetime.now().isoformat(),
                'error': str(e),
                'select_tags': {},
                'total_selects': 0,
                'page_url': page.url
            }

    async def get_select_options_by_name(self, page, select_name, refereeDetail=None):
        """
        Get options for a specific select element by name.
        
        Args:
            page: Playwright page object
            select_name: Name attribute of the select element
            refereeDetail: Optional referee details for logging context
            
        Returns:
            dict: Dictionary containing the select element and its options
        """
        try:
            self.logger.info(f"Getting options for select '{select_name}'", refereeDetail=refereeDetail)
            
            select_elem = await page.query_selector(f'select[name="{select_name}"]')
            if not select_elem:
                self.logger.warning(f"Select element with name '{select_name}' not found", refereeDetail=refereeDetail)
                return None
            
            select_data = {
                'select_name': select_name,
                'options': [],
                'selected_values': [],
                'selected_texts': []
            }
            
            # Get all option elements
            option_elements = await select_elem.query_selector_all('option')
            
            for i, option_elem in enumerate(option_elements):
                try:
                    option_value = await option_elem.get_attribute('value')
                    option_text = await option_elem.text_content()
                    is_selected = await option_elem.get_attribute('selected')
                    is_disabled = await option_elem.get_attribute('disabled')
                    
                    option_info = {
                        'index': i,
                        'value': option_value,
                        'text': option_text.strip() if option_text else None,
                        'selected': is_selected is not None,
                        'disabled': is_disabled is not None
                    }
                    
                    select_data['options'].append(option_info)
                    
                    # Track selected options
                    if is_selected is not None:
                        select_data['selected_values'].append(option_value)
                        select_data['selected_texts'].append(option_text.strip() if option_text else None)
                        
                except Exception as e:
                    self.logger.warning(f"Error processing option {i} in select '{select_name}': {e}", refereeDetail=refereeDetail)
                    continue
            
            self.logger.info(f"Found {len(select_data['options'])} options for select '{select_name}'", refereeDetail=refereeDetail)
            return select_data
            
        except Exception as e:
            self.logger.error(f"Error getting options for select '{select_name}': {e}", refereeDetail=refereeDetail)
            return None

    async def get_all_select_names(self, page, refereeDetail=None):
        """
        Get all select element names on the current page.
        
        Args:
            page: Playwright page object
            refereeDetail: Optional referee details for logging context
            
        Returns:
            list: List of select element names
        """
        try:
            self.logger.info("Getting all select element names", refereeDetail=refereeDetail)
            
            select_elements = await page.query_selector_all('select')
            select_names = []
            
            for select_elem in select_elements:
                select_name = await select_elem.get_attribute('name')
                if select_name:
                    select_names.append(select_name)
            
            self.logger.info(f"Found {len(select_names)} select elements with names: {select_names}", refereeDetail=refereeDetail)
            return select_names
            
        except Exception as e:
            self.logger.error(f"Error getting select names: {e}", refereeDetail=refereeDetail)
            return []

    async def load(self):
        pass

    async def testLogin(self):
        tenantKey = 'IL#handball#2025-26'
        referees = self.handleUsers.refereesByMobile.get(tenantKey, {})
        objType='games'
        for mobileNo, referee in referees.items():
            self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, value=helpers.localNow(), propertyName=f'{objType}_lastScrape')

if __name__ == "__main__":
    from shared.appContainer import AppContainer
    container = AppContainer.getAppContainer()
    from shared.orgRelated import OrgServiceFactory
    orgServiceFactory:OrgServiceFactory = container.orgServiceFactory()
    tenantKey = 'IL#handball#2025-26'
    orgService:IHAService = orgServiceFactory.get_org_service_by_tenant(tenantKey=tenantKey)
    asyncio.run(orgService.testLogin())
    exit(0)
    internalGameId='36763'
    gameId='67b3c8f7'
    refereeData = {'mobileNo': '+972522899253'}
    jsonResponse = asyncio.run(orgService.approveDeclineGameFromAdminPage(refereeData=refereeData, gameId=gameId, declineReasonId=45))
    print(jsonResponse)
    exit(0)
    pass

# כתובות מגרשים
# שופט שופט מבקר מזכיר מזכיר
# והעלאה אוטומטית לפורטל העלאת דוח שיפוט
# מסמכים
# רשימת קטגוריות גיל וחוקים לכל קטגוריה
# הודעות לשופטים, שליחת push notification
# 