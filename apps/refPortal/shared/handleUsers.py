from cryptography.fernet import Fernet
import json
import os
import logging
import csv
from datetime import datetime, timedelta
import asyncio
from colorama import Fore, Style
import random
import sys
import uuid
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.db import CacheService

class HandleUsers():
    def __init__(self, logger:Logger, cacheService:CacheService):
        self.logger = logger
        self.cacheService = cacheService

        #descopeProjectId = os.getenv('descopeProjectId')
        #self.descopeClient = MyDescopeClient(self.logger, descopeProjectId)

        #(self._globalRefereesByMobile, self._refereesByRefId, self._refereesByMobile, self._refereesByGuid) = self.getAllRefereesByMobileOrGuid()

        self.colors = list(vars(Fore))
        self.newRefStatus = os.getenv('newRefStatus')
        self.logger.info(f'HandleUsers starts...')

    def encrypt(self, referees):
        key = Fernet.generate_key()
        with open("secret/password_key", "wb") as key_file:
            key_file.write(key)

        # Load the key
        with open("secret/password_key", "rb") as key_file:
            key = key_file.read()
        
        fernet = Fernet(key)

        for referee in referees:
            password = referees[referee]
            referees[referee] = self.encryptPassword(password=password, fernet=fernet)

    def encryptPassword(self, password, fernet=None):
        if not fernet:
            key = helpers.get_secret('password_key')
            fernet = Fernet(key)
        encodedPassword = password.encode()
        encryptedPassword = fernet.encrypt(encodedPassword).decode("utf-8")
        return encryptedPassword

    def decryptPassword(self, password, fernet=None):
        if not password:
            return None
        
        if not fernet:
            key = helpers.get_secret('password_key')
            fernet = Fernet(key)
        decryptedPassword = fernet.decrypt(password).decode()
        return decryptedPassword

    def changeRefereePassword(self, tenantKey, mobileNo, refPassword):
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo, forceReload=True)
        if not refereeDetail:
            return False

        encryptedPassword = self.encryptPassword(f'{refPassword}')
        refereeDetail['password'] = encryptedPassword
        refereeDetail['passwordChangedDate'] = helpers.localNow()
        self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=refereeDetail)
        return True

    def updateRefereeArea(self, tenantKey, mobileNo, area):
        self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=area, propertyName='area')
        return True

    def forceSend(self, mobileNo, onOff):
        globalRefereeDetail = self.globalRefereesByMobile.get(mobileNo)
        for tenantKey in globalRefereeDetail['activeTenantKeys']:
            self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=onOff, propertyName='forceSend')

    async def activate(self, tenantKey, mobileNo):
        self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=self.newRefStatus, propertyName='status')
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        return refereeDetail

    async def deactivate(self, tenantKey, mobileNo):
        self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value='inactive', propertyName='status')
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        return refereeDetail

    async def suspend(self, tenantKey, mobileNo):
        self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value='suspended', propertyName='status')
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        return refereeDetail

    @property
    def globalRefereesByMobile(self):
        if not hasattr(self, '_globalRefereesByMobile'):
            (self._globalRefereesByMobile, self._refereesByRefId, 
            self._refereesByMobile, self._refereesByGuid, self._globalRefereesByName) = self.getAllReferees()
        return self._globalRefereesByMobile

    @property
    def refereesByRefId(self):
        if not hasattr(self, '_refereesByRefId'):
            (self._globalRefereesByMobile, self._refereesByRefId, 
            self._refereesByMobile, self._refereesByGuid, self._globalRefereesByName) = self.getAllReferees()
        return self._refereesByRefId

    @property
    def refereesByMobile(self):
        if not hasattr(self, '_refereesByMobile'):
            (self._globalRefereesByMobile, self._refereesByRefId, 
            self._refereesByMobile, self._refereesByGuid, self._globalRefereesByName) = self.getAllReferees()
        return self._refereesByMobile

    @property
    def refereesByGuid(self):
        if not hasattr(self, '_refereesByGuid'):
            (self._globalRefereesByMobile, self._refereesByRefId, 
            self._refereesByMobile, self._refereesByGuid, self._globalRefereesByName) = self.getAllReferees()
        return self._refereesByGuid

    #add property refereesByName
    @property
    def globalRefereesByName(self):
        if not hasattr(self, '_globalRefereesByName'):
            (self._globalRefereesByMobile, self._refereesByRefId, 
            self._refereesByMobile, self._refereesByGuid, self._globalRefereesByName) = self.getAllReferees()
        return self._globalRefereesByName

    #@property
    def getRefereeDetail(self, tenantKey, mobileNo):
        globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo, forceReload=True)
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo, forceReload=True)
        refereeDetail = globalRefereeDetail | tenantRefereeDetail
        return refereeDetail

    def getAllReferees(self):
        tenants = self.cacheService.getTenants()
        activeTenantKeys = [ tenantKey for tenantKey, tenant in tenants.items() if tenant.get('active') == True ]
        
        globalRefereesByMobile = {}
        referees = self.cacheService.getRefereesNoCache()
        globalReferees = referees['GLOBAL']
        refereesByRefId = {}
        refereesByMobile = {}
        refereesByGuid = {}
        globalRefereesByName = {}
        
        for mobileNo, globalReferee in globalReferees.items():
            globalReferee['tenantKeys'] = []
            globalReferee['activeTenantKeys'] = []
            globalRefereesByMobile[mobileNo] = globalReferee
            refName = globalReferee.get('name')
            if not globalRefereesByName.get(refName):
                globalRefereesByName[refName] = []
            globalRefereesByName[refName].append(globalReferee)
        
        for tenantKey in tenants.keys():
            tenantReferees = referees.get(tenantKey)
            refereesByRefId[tenantKey] = {}
            refereesByMobile[tenantKey] = {}
            refereesByGuid[tenantKey] = {}
            #refereesByTenant = self.cacheService.getRefereesNoCache(tenantKey=tenantKey)
            for mobileNo, globalReferee in globalRefereesByMobile.items():
                #tenantReferee = refereesByTenant.get(mobileNo)
                tenantReferee = tenantReferees.get(mobileNo)
                if tenantReferee:
                    refereeDetail = globalReferee | tenantReferee
                    if tenantReferee.get('refId'):
                        refereesByRefId[tenantKey][tenantReferee.get('refId')] = refereeDetail
                    globalReferee['tenantKeys'].append(tenantKey)
                    if tenantKey in activeTenantKeys:
                        globalReferee['activeTenantKeys'].append(tenantKey)

                    refereesByMobile[tenantKey][mobileNo] = refereeDetail
                
                    if globalReferee.get('guid'):
                        refereesByGuid[tenantKey][globalReferee.get('guid')] = refereeDetail
    
        return (globalRefereesByMobile, refereesByRefId, refereesByMobile, refereesByGuid, globalRefereesByName)
    
    async def addPendingReferee(self, tenantKey, mobileNo, refId):
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        if refereeDetail:
            refereeDetail['refId'] = refId
            self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value='pending', propertyName='status')
        else:
            refereeDetail = {
                "refId": refId,
                "status": "pending",
            }
            self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=refereeDetail)

        return None

    async def addReferee(self, tenantKey, mobileNo, **kwargs):
        try:
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            if tenantRefereeDetail:
                return f''
            
            mobileNo = mobileNo.replace('-','')
            mobileNo = mobileNo.replace(' ','')
            
            color = kwargs.get('color')
            if not color:
                color = "LIGHTWHITE_EX"
            
            password = kwargs.get('password')
            encryptedPassword = self.encryptPassword(f'{password}')
            address = kwargs.get('address')
            addressDetails = self.generateRefereeAddress(address)

            globalRefereeDetail = {
                "mobileNo": mobileNo,
                "name": kwargs.get('name'),
                "id": kwargs.get('id'),
                "guid": kwargs.get('guid') or str(uuid.uuid4()),
                "color": color,
                "status": "pending",
                "addressDetails": addressDetails,
                "messageAcceptanceLimitation": False,
                "doNotCreateGroups": False
            }

            tenantRefereeDetail = {
                "refId": kwargs.get('refId'),
                "userName": kwargs.get('userName'),
                "password": encryptedPassword,
                "roles": kwargs.get('roles'),
                "lastNoticeBeforeGameInHours": kwargs.get('lastNoticeBeforeGameInHours'),
                "timeArrivalInMin": kwargs.get('timeArrivalInMin'),
                "objTypes": kwargs.get('objTypes'),
            }

            self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=globalRefereeDetail)
            self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=tenantRefereeDetail)
            return tenantRefereeDetail or globalRefereeDetail
        except Exception as e:
            self.logger.error(f"Error adding referee:", e)
            return None

    async def updateReferee(self, tenantKey, refId, name, id, refPassword, refArea, mobileNo, address, lastNoticeBeforeGameInHours, timeArrivalInMin, color, guid, messageAcceptanceLimitation, createGroups, alwaysCreateChatGroup, ignoreGroup4Singles):
        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        text = None
        if not tenantRefereeDetail:
            text = f"{helpers.localNow()} קוד שופט {refId} נכשל ברישום, אנא פנה למנהל המערכת"
        else:
            status = tenantRefereeDetail['status']
            if not status or status not in ('pending', 'suspended'):
                return f'לא מורשה להצטרף למערכת'
            
            if not color:
                color = "LIGHTWHITE_EX"
            
            encryptedPassword = self.encryptPassword(f'{refPassword}')
            addressDetails = self.generateRefereeAddress(address)

            globalRefereeDetail = {
                "mobileNo": mobileNo,
                "name": name,
                "guid": guid,
                "id": id,
                "reminders": [
                    24,
                    int(lastNoticeBeforeGameInHours)
                ],
                "timeArrivalInAdvance": int(timeArrivalInMin),
                "color": color,
                "addressDetails": addressDetails,
                "gender": "Male",
                "messageAcceptanceLimitation": messageAcceptanceLimitation,
                "createGroups": createGroups,
                "alwaysCreateChatGroup": alwaysCreateChatGroup,
                "ignoreGroup4Singles": ignoreGroup4Singles
            }


            tenantRefereeDetail = {
                "refId": refId,
                "area": refArea,
                "objTypes": [
                    "games",
                    "reviews"
                ],
                "reminders": [
                    24,
                    int(lastNoticeBeforeGameInHours)
                ],
                "timeArrivalInAdvance": int(timeArrivalInMin),
                "status": status,
                "password": encryptedPassword,
            }

            result = self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=globalRefereeDetail)
            result = self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=tenantRefereeDetail)
            self.logger.debug(f"updateReferee result={result}")
        
        return text

    def generateRefereeAddress(self, address):
        coordinates, formattedAddress, error = helpers.get_coordinates_google_maps(f'{address}')
        if not coordinates:
            coordinates = [None, None]

        addressDetails = {
            "address": address,
            "coordinates": {
                "lat": coordinates[0],
                "lng": coordinates[1]
            },
            "formattedAddress": formattedAddress
        }

        return addressDetails

    def getRandomColor(self):
        color = self.colors[random.randint(0, len(self.colors)-1)]
        if color == 'BLACK':
            color = self.colors[random.randint(0, len(self.colors)-1)]
        return color
    
    async def updateAllReferees(self):
        try:
            referees = self.globalRefereesByMobile.items()
            for mobileNo, referee in referees.items():
                if False and referee.get('createGroups'):
                    continue
                prop = False#True if referee['status'] == 'pilot' else False
                self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=prop, propertyName='createGroups')
        except Exception as ex:
            pass
    
    async def setColors(self):
        try:
            referees = self.globalRefereesByMobile.items()
            for mobileNo, referee in referees.items():
                if not referee.get('color'):
                    continue
                color = referee['color']
                newColor = self.getRandomColor()
                self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=newColor, propertyName='color')
        except Exception as ex:
            pass
    
    def checkApproved(self):
        referees = self.refereesByRefId.items()
        with open("./approvedGames.csv", newline="", encoding="utf-8") as file:
            reader = csv.reader(file)
            games = {}
            for row in reader:
                if len(row) == 0:
                    continue
                t = row[0]
                url = row[1][5:]
                urlArr = url.split('/')
                refId = urlArr[3]
                gameId = urlArr[5].split(' ')[0]
                if not games.get(refId):
                    games[refId] = { 'name': referees[refId]['name'], 'games': [] }
                games[refId]['games'].append(gameId)
                print(f'{t} {refId} {gameId}')
        jsonHelper.save_to_file(games, "./approvedGames.json")

    async def getSelectedReferees(self):
        referees = self.refereesByRefId.items()
        selectedRefereeIds = ['43222','43294','42309','43511','43226','41611']
        selectedReferees = { refId: referee for refId, referee in referees.items() if refId in selectedRefereeIds }            
        selectedMobiles = [referee['mobileNo'] for refId, referee in selectedReferees.items()]
        pass
    
    def updateStatuses(self, tenantKey):
        referees = self.refereesByMobile.get(tenantKey, {}).items()
        for mobileNo, referee in referees.items():
            if referee.get('status') == 'suspended':
                self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value='pilot', propertyName='status')

    async def countReferees(self, addRefereeNames = []):
        import searchforreferee

        refereeNames:list = []
        if addRefereeNames:
            refereeNames = addRefereeNames
        else:
            referees = self.refereesByRefId.items()
            refereeNames = [referee['name'] for refId, referee in referees.items() if 'name' in referee]
            refereeNames.append(" ")

        await searchforreferee.searchRefereeCount(refereeNames)
        self.createHtml()
    
    def createHtml(self, page_title='רשימת שופטים'):
        import pandas as pd
        targets = jsonHelper.load_from_file(filename='./refereesTargetsFull.json')          

        # Convert to DataFrame
        df = pd.DataFrame([ \
            {   "href": href, \
                "שם": target.get('שם'), "סה׳כ": str(target.get("countRef")+target.get("countAsRef")+target.get("count4thRef")+target.get("countRev")), \
                "שופט ראשי": str(target.get("countRef")), "עוזר שופט": str(target.get("countAsRef")), "שופט רביעי": str(target.get("count4thRef")), "ביקורות": str(target.get("countRev")), "תמונה": target.get("imgSrc"), "סטטוס": target.get("סטטוס"), "מחוז": target.get("מחוז שיפוט"), \
                "בוגרים": str(target.get("countAdults")), "נוער": str(target.get("countYouth")), "נערים א": str(target.get("countU17")), "נערים ב": str(target.get("countU16")), "נערים ג": str(target.get("countU15")), \
                "ילדים א": str(target.get("countU14")), "ילדים ב": str(target.get("countU13")), "ילדים ג": str(target.get("countU12")), \
                "טרום א": str(target.get("countU11")), "טרום ב": str(target.get("countU10")), "טרום ג": str(target.get("countU09")), \
                "נשים": str(target.get("countWomenAdults")), "נערות": str(target.get("countWomenYouth")), "ילדות": str(target.get("countWomenU15")),  "טרומיות": str(target.get("countWomenU12")) }
            for href, target in targets.items() if target.get('countRef')
        ])

        # Add href-wrapped name
        df["שם"] = df.apply(lambda row: f'<a href="{row["href"]}" target="_blank">{row["שם"]}</a>', axis=1)

        # Drop href column before rendering
        df.drop(columns=["href"], inplace=True)

        # Convert to HTML table
        html_table = df.to_html(
            index=False,
            escape=False,
            classes=["sortable"],
            formatters={
                "תמונה": lambda x: f'<img src="{x}" width="80">'
            }
        )

        page_title += f' {helpers.localNow().strftime("%d/%m/%Y %H:%M")}'
        html_doc = f"""<!DOCTYPE html>
            <html lang="he" dir="rtl">
            <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta name="description" content="{page_title}">
            <title>{page_title}</title>
            <style>
                body {{ font-family: sans-serif; direction: rtl; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ccc; padding: 8px; text-align: right; cursor: pointer; }}
                thead th {{ position: sticky; top: 0; background-color: white; z-index: 1; }}
                img {{ max-height: 100px; }}
                th.asc::after {{ content: " 🔼"; }}
                th:not(.asc)::after {{ content: " 🔽"; }}
            </style>
            <script>
            document.addEventListener('DOMContentLoaded', function () {{
            document.querySelectorAll("th").forEach(header => {{
                header.addEventListener("click", () => {{
                const table = header.closest("table");
                const index = Array.from(header.parentNode.children).indexOf(header);
                const rows = Array.from(table.querySelectorAll("tbody tr"));
                const ascending = header.classList.toggle("asc");

                rows.sort((a, b) => {{
                    const cellA = a.children[index].textContent.trim();
                    const cellB = b.children[index].textContent.trim();

                    return ascending
                    ? cellA.localeCompare(cellB, 'he', {{ numeric: true }})
                    : cellB.localeCompare(cellA, 'he', {{ numeric: true }});
                }});

                rows.forEach(row => table.querySelector("tbody").appendChild(row));
                }});
            }});
            }});
            </script>
            </head>
            <body>
            <h2>{page_title}</h2>
            {html_table}
            </body>
            </html>
            """

        # Save HTML to file
        html_path = "./rpApi/static/refereesCount.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_doc)

        pass
    
    def importReferees(self):
        from shared.messaging import MessagingService
        file = '../HandballStaff/Referees_20260516.csv'
        currentdir = os.path.dirname(os.path.abspath(__file__))
        file = os.path.join(currentdir, file)
        
        json_data = []
        
        with open(file, 'r', encoding='utf-8') as f:
            # Use DictReader to automatically use header row as keys
            reader = csv.DictReader(f)
            
            # Get the fieldnames (headers) from the CSV
            headers = reader.fieldnames
            self.logger.info(f"📋 CSV Headers: {headers}")
            
            for row_num, row in enumerate(reader, start=2):  # Start at 2 because row 1 is headers
                # Convert row to JSON object (dictionary)
                # DictReader already creates a dict with header keys
                # Filter out empty keys (columns with no header)
                json_obj = {k: v for k, v in row.items() if k}  # Remove empty header keys
                if json_obj.get('mobileNo'):
                    json_obj['mobileNo'] = MessagingService.adjustMobileNo(mobileNo=json_obj['mobileNo'])
                # Only add non-empty rows
                if any(json_obj.values()):  # Check if row has any non-empty values
                    json_data.append(json_obj)
                    self.logger.info(f"✅ Row {row_num}: {json.dumps(json_obj, ensure_ascii=False)}")
                else:
                    self.logger.debug(f"⏭️ Skipping empty row {row_num}")
        
        self.logger.info(f"📊 Total records imported: {len(json_data)}")
        # Return list of JSON objects

        for referee in json_data:
            globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=referee['mobileNo'])
            if not globalRefereeDetail:
                globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo='+972547799979')
                globalRefereeDetail['name'] = referee['name']
                globalRefereeDetail['id'] = referee['id']
                globalRefereeDetail['gender'] = 'M' if referee['gender'] == 'ז' else 'F'
                globalRefereeDetail['timeArrivalInAdvance'] = 45
                globalRefereeDetail['commuteReminderTimeInAdvance'] = 3
                globalRefereeDetail['firstGameReminderTimeInAdvance'] = 24
                if referee.get('address'):
                    addressDetails = self.generateRefereeAddress(referee['address'])
                    globalRefereeDetail['addressDetails'] = addressDetails
                self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=referee['mobileNo'], value=globalRefereeDetail)
            
            tenantRefereeDetail = self.cacheService.getReferees(tenantKey='IL#handball#2025-26', mobileNo=referee['mobileNo'])
            if not tenantRefereeDetail:
                tenantRefereeDetail = self.cacheService.getReferees(tenantKey='IL#handball#2025-26', mobileNo='+972547799979')
                tenantRefereeDetail['refId'] = referee['refId']
                tenantRefereeDetail['userName'] = referee['userName']
                self.cacheService.setRefereeProperty(tenantKey='IL#handball#2025-26', mobileNo=referee['mobileNo'], value=tenantRefereeDetail)
        return json_data

    def _normalize_handball_staff_mobile(self, raw) -> str | None:
        """Map staff export phone (טלפון 1) to canonical +972… mobileNo."""
        raw = (raw or '').strip().replace('-', '').replace(' ', '')
        if not raw:
            return None
        p = helpers.extract_phone_number(raw)
        if p:
            return p
        digits = ''.join(c for c in raw if c.isdigit())
        if not digits:
            return None
        if digits.startswith('972') and len(digits) >= 11:
            return f'+{digits}'
        if digits.startswith('0') and len(digits) >= 9:
            return f'+972{digits[1:]}'
        if len(digits) >= 9:
            return f'+972{digits}'
        return None

    def syncHandballStaffPersonsToTenantReferees(
        self,
        tenant_key: str = 'IL#handball#2025-26',
        json_path: str | None = None,
    ) -> dict:
        """
        Read HandballStaff/persons_data.json (array of rows with ID, טלפון 1, שם משתמש).
        For each row, load the tenant referee by normalized mobile and set refId and userName.
        """
        base = Path(__file__).resolve().parent.parent
        path = Path(json_path) if json_path else base / 'HandballStaff' / 'persons_data.json'
        if not path.is_file():
            self.logger.error(f'Handball staff file not found: {path}')
            return {'error': 'file_not_found', 'path': str(path)}
        rows = jsonHelper.load_from_file(filename=str(path))
        if not isinstance(rows, list):
            self.logger.error('persons_data.json must be a JSON array')
            return {'error': 'invalid_json_shape'}
        phone_key = 'טלפון 1'
        ref_id_key = 'id'
        user_key = 'שם משתמש'
        id_key = 'תעודת זהות'
        name_key = 'שם מלא'
        stats = {
            'updated': 0,
            'skipped_no_phone': 0,
            'skipped_no_staff_id': 0,
            'not_found': 0,
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            staff_id = (str(row.get(ref_id_key) or '')).strip()
            if not staff_id:
                stats['skipped_no_staff_id'] += 1
                continue
            user_name = (str(row.get(user_key) or '')).strip()
            id = (str(row.get(id_key) or '')).strip()
            name = (str(row.get(name_key) or '')).strip()
            mobile = self._normalize_handball_staff_mobile(row.get(phone_key))
            if not mobile:
                stats['skipped_no_phone'] += 1
                continue
            global_ref = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobile, forceReload=True)
            if not global_ref:
                global_ref = {}
                global_ref['gender'] = 'M' if row.get('gender') == 'ז' else 'F'
                global_ref['timeArrivalInAdvance'] = 45
                global_ref['commuteReminderTimeInAdvance'] = 3
                global_ref['firstGameReminderTimeInAdvance'] = 24
            global_ref['name'] = name
            global_ref['id'] = id
            self.cacheService.setReferee(tenantKey='GLOBAL', mobileNo=mobile, value=global_ref)
            tenant_ref = self.cacheService.getReferees(tenantKey=tenant_key, mobileNo=mobile, forceReload=True)
            if not tenant_ref:
                stats['not_found'] += 1
                self.logger.warning(
                    f'Handball staff sync: no {tenant_key} referee for mobile={mobile} staffId={staff_id}'
                )
                continue
            if tenant_ref.get('fixedRecordTimestamp'):
                tenant_ref['portalAllow'] = True
                tenant_ref['status'] = 'active'
                tenant_ref['roles'] = ['referee']
            if tenant_ref.get('portalAllowed'):
                del tenant_ref['portalAllowed']
            if tenant_ref.get('value'):
                tenant_ref['fixedRecordTimestamp'] = tenant_ref['value']
                del tenant_ref['value']
            if not tenant_ref.get('refId'):
                tenant_ref['refId'] = staff_id
            if 'userName' not in tenant_ref:
                tenant_ref['userName'] = user_name
            if 'password' not in tenant_ref:
                tenant_ref['password'] = ''
            self.cacheService.setReferee(tenantKey=tenant_key, mobileNo=mobile, value=tenant_ref)
            stats['updated'] += 1
        self.logger.info(f'Handball staff → tenant sync {tenant_key}: {stats}')
        return stats

    def fixReferees(self):
        """Backward-compatible entry point; delegates to syncHandballStaffPersonsToTenantReferees."""
        return self.syncHandballStaffPersonsToTenantReferees()

if __name__ == "__main__":
    from shared.appContainer import AppContainer
    import shared.configurationDI as configDI
    appContainer = AppContainer()
    appContainer.config.from_dict(configDI.configDI)
    appContainer.init_resources()
    handleUsers=appContainer.handle_users()
    cacheService:CacheService=appContainer.cache_service()

    handleUsers.fixReferees()
    exit(0)
    referees = cacheService.getRefereesNoCache()
    referee = cacheService.getReferees(tenantKey='IL#football#2025-26', mobileNo='+972547799979')
    handleUsers.fixReferees()
    eliTenantReferee = cacheService.getReferees(tenantKey='IL#handball#2025-26', mobileNo='+972522899253')
    eliTenantReferee['roles'] = ['assigner']
    eliTenantReferee['password'] = handleUsers.encryptPassword(password='H038329538e')
    cacheService.setReferee(tenantKey='IL#handball#2025-26', mobileNo='+972522899253', value=eliTenantReferee)
    exit(0)
    #handleRefereeData=appContainer.handle_referee_data()
    referees = cacheService.getRefereesNoCache()
    tenantReferee = referees['IL#football#2025-26']['+972547799979']
    globalReferee = referees['GLOBAL']['+972547799979']
    del tenantReferee['+972547799979']
    cacheService.setRefereeProperty(tenantKey='IL#football#2025-26', mobileNo='+972547799979', value=tenantReferee)
    #handleUsers.importReferees()
    #handleUsers.changeRefereePassword(tenantKey='IL#handball#2025-26', mobileNo='+972547799979', refPassword='H038329538e')
    
    from shared.db import DynamodbClient
    dynamoDbService:DynamodbClient=appContainer.dynamodb_db_client()
    footballReferees = referees['IL#football#2025-26']
    handballReferees = referees['IL#handball#2025-26']
    for mobileNo, refereeDetail in handballReferees.items():
        if not refereeDetail.get('roles'):
            refereeDetail['roles'] = ['referee']
            cacheService.setRefereeProperty(tenantKey=refereeDetail.get('tenantKey'), mobileNo=mobileNo, value=refereeDetail)
    globalReferees = referees['GLOBAL']
    for mobileNo, refereeDetail in globalReferees.items():
        tenantKey = refereeDetail.get('tenantKey')
        key = f'{tenantKey}:{mobileNo}'
        refereeDetail['tenantKeys'] = []
        refereeDetail['activeTenantKeys'] = []
        if 'reminders' in refereeDetail:
            del refereeDetail['reminders']
        if 'eventType' in refereeDetail:
            del refereeDetail['eventType']
        if 'objTypes' in refereeDetail:
            del refereeDetail['objTypes']
        if 'status' in refereeDetail:
            del refereeDetail['status']
        if 'timeArrivalInAdvance' not in refereeDetail:
            refereeDetail['timeArrivalInAdvance'] = 45
        if 'commuteReminderTimeInAdvance' not in refereeDetail:
            refereeDetail['commuteReminderTimeInAdvance'] = 3
        if 'firstGameReminderTimeInAdvance' not in refereeDetail:
            refereeDetail['firstGameReminderTimeInAdvance'] = 24
        cacheService.setReferee(tenantKey='GLOBAL', mobileNo=mobileNo, value=refereeDetail)

    tenants = cacheService.getTenants()
    for tenantKey, tenant in tenants.items():
        tenantReferees = referees[tenantKey]
        for mobileNo, tenantRefereeDetail in tenantReferees.items():
            globalRefereeDetail = cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
            if not globalRefereeDetail:
                continue
            if 'name' in tenantRefereeDetail:
                del tenantRefereeDetail['name']
            globalRefereeDetail['tenantKeys'].append(tenantKey)
            if tenant.get('active'):
                globalRefereeDetail['activeTenantKeys'].append(tenantKey)
            tenantRefereeDetail['objTypes'] = tenant.get('objTypes', [])
            cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=globalRefereeDetail)
            cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=tenantRefereeDetail)
            if not tenantKey == 'IL#handball#2025-26':
                continue
            games = handleRefereeData.getRefereeGames(
                    tenantKey=[tenantKey],
                    mobileNo=mobileNo,
                    includeArchived=False,
                    includeRemoved=False,
                    from_date=helpers.localNow() - timedelta(days=120),
                    to_date=helpers.localNow() - timedelta(days=1))
            
            for game in games:
                if game['state'] == 'active':
                    game['state'] = 'archived'
                    cacheService.setRefereeGame(tenantKey=tenantKey, refId=tenantRefereeDetail['refId'], gamePk=game['gamePk'], value=game)
    pass

    clientIdentifiers = cacheService.getClientIdentifier(clientIdentifier=None, from_date=helpers.localNow() - timedelta(days=3))
    mobileNos = list({clientIdentifier.get('mobileNo') for clientIdentifier in clientIdentifiers.values() if clientIdentifier.get('mobileNo') and clientIdentifier.get('mobileNo') != 'XX'})
    for mobileNo in mobileNos:
        print(f'{mobileNo}')
        refereeDetail = cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
        if not refereeDetail or not isinstance(refereeDetail, dict):
            print(f'⚠️ Warning: No referee detail found for {mobileNo}, skipping...')
            continue
        if 'objTypes' not in refereeDetail:
            refereeDetail['objTypes'] = ['games']
        if False and 'name' not in refereeDetail:
            refereeDetail['name'] = 'לוטן וייס'
        if 'timeArrivalInAdvance' not in refereeDetail:
            refereeDetail['timeArrivalInAdvance'] = 45
        if 'commuteReminderTimeInAdvance' not in refereeDetail:
            refereeDetail['commuteReminderTimeInAdvance'] = 3
        if 'firstGameReminderTimeInAdvance' not in refereeDetail:
            refereeDetail['firstGameReminderTimeInAdvance'] = 24
        cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=refereeDetail)
        #handleUsers.activateByMobileNo(mobileNo=mobileNo)
    
    #refereeDetail = cacheService.getReferee(tenantKey='IL#handball#2025-26', mobileNo='+972547799979')
    #cacheService.setReferee(tenantKey='IL#handball#2025-26', mobileNo='+972543183736', value=refereeDetail)

    for mobileNo, refereeDetail in handleUsers.globalRefereesByMobile.items():
        if not refereeDetail.get('name') and refereeDetail.get('eventType') == 'handball':
            tenantReferee = cacheService.getReferees(tenantKey=f'IL#{refereeDetail.get("eventType")}#2024-25', mobileNo=mobileNo)
            if tenantReferee and tenantReferee.get('name'):
                refereeDetail['name'] = tenantReferee['name']
                cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=refereeDetail)
    #asyncio.run(handleUsers.addReferee(tenantKey='IL#handball#2025-26', refId='956', name='חכמון אלי', id='038329538', userName='elisport12@gmail.com', refPassword='H038329538e', mobileNo='+972522899253', address='test', lastNoticeBeforeGameInHours='3', timeArrivalInMin='45', color='red', role='assigner'))
    refereeDetail = cacheService.getReferees(tenantKey='IL#football#2025-26', mobileNo='+972547799979')
    #referees = handleUsers.cacheService.dbClient.getDict(tableName='users')
    #jsonHelper.save_to_file(referees, 'refereesDetails.json')
    import time
    #refsJson = jsonHelper.load_from_file(filename='./HandballStaff/all_handball_referees.json')
    passw = handleUsers.encryptPassword(password='vivna9deFtow')
    refereeDetail['password'] = passw
    cacheService.setRefereeProperty(tenantKey='IL#football#2025-26', mobileNo=refereeDetail['entityKey'], value=refereeDetail)