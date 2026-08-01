import requests
import json
import sys
import os
import logging
import asyncio
import time
from pathlib import Path
from fastapi import FastAPI, Request, Response, Header, HTTPException
import hmac
import hashlib
from urllib.parse import urlencode, urlparse, parse_qs
from typing import Optional
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.messaging.messagingClientBase import MessagingClientBase
from shared.db import CacheService

class MetaClient(MessagingClientBase):
    """
    A wrapper class for the Meta Business API (WhatsApp Cloud API)
    to send text and template messages.
    """

    def __init__(self, logger:Logger, cacheService:CacheService, apiVersion:str, fromPhoneNumberId: str, whatsappBusinessAccountId: str, fromMobile:str, metaBaseUrl:str=None, apiServiceUrlBase:str=None, useClient:bool=False, formattedName:str=None):
        """
        Initializes the API wrapper with necessary credentials.

        Args:
            access_token (str): Your permanent access token from Meta for Developers.
            phone_number_id (str): The ID of the phone number you are sending from.
        """
        super().__init__(logger=logger, cacheService=cacheService, clientName='meta', fromMobile=fromMobile, useClient=useClient)
        self.logger:Logger = logger
        self.cacheService = cacheService

        accessToken = helpers.get_secret('meta_access_token')
        if not accessToken or not fromPhoneNumberId:
            raise ValueError("Access token and phone number ID cannot be empty.")
        self.accessToken = accessToken
        self.fromPhoneNumberId = fromPhoneNumberId
        self.whatsappBusinessAccountId = whatsappBusinessAccountId
        self.meta_base_url = metaBaseUrl
        self.metaApiUrl = f"{self.meta_base_url}{apiVersion}"

        self.apiServiceUrlBase = apiServiceUrlBase
        self.formattedName = formattedName

        self.incomingApiGuid = helpers.get_secret('incoming_api_guid')
        # Store your App Secret securely, e.g., as an environment variable
        self.meta_app_secret = helpers.get_secret('meta_app_secret')

        self.logger.info("Meta starts...")
        self._delivery_failure_hook = None

    def register_delivery_failure_hook(self, hook):
        """Async callable: (to_number, wamid, message_record, errors) -> None"""
        self._delivery_failure_hook = hook

    def _sendGetRequestByUrl(self, url: str, params: dict=None, headers: dict=None):
        """
        Sends a GET request to the Meta Business API.

        Args:
            params (dict): The JSON params for the request.

        Returns:
            dict: The JSON response from the API.
        """
        if not headers:
            headers = {}
        headers["Authorization"] = f"Bearer {self.accessToken}"
        
        try:
            response = requests.get(url=url, headers=headers, params=params)
            response.raise_for_status()  # Raise an exception for bad status codes
            try:
                jsonResponse = response.json()
                return jsonResponse
            except Exception as ex:
                return response

        except requests.exceptions.RequestException as ex:
            self.logger.error(f"An error occurred:", ex)
            if ex.response:
                self.logger.error(f"Error details: {ex.response.text}")
            return None

    def _sendGetRequest(self, queryType: str, params: dict=None, headers: dict=None):
        """
        Sends a GET request to the Meta Business API.

        Args:
            params (dict): The JSON params for the request.

        Returns:
            dict: The JSON response from the API.
        """        
        return self._sendGetRequestByUrl(url=f'{self.metaApiUrl}/{self.whatsappBusinessAccountId}/{queryType}', headers=headers, params=params)

    def _sendPostRequest(self, type: str="messages", payload: dict=None, formData: dict=None, files: dict=None, headers: dict=None, replyToMessageId: str=None, returnMsgSid:bool = True):
        """
        Sends a POST request to the Meta Business API.

        Args:
            payload (dict): The JSON payload for the request.

        Returns:
            dict: The JSON response from the API.
        """
        if not headers:
            headers = {}
        headers["Authorization"] = f"Bearer {self.accessToken}"

        try:
            if payload:
                headers["Content-Type"] = "application/json"

                # Add reply context if replying to a message
                if replyToMessageId:
                    payload["context"] = {
                        "message_id": replyToMessageId
                    }

            response = requests.post(url=f'{self.metaApiUrl}/{self.fromPhoneNumberId}/{type}', headers=headers, data=formData, json=payload, files=files)
            
            metaRequest = {
                'formData': formData,
                'payload': payload,
                'statsCode': response.status_code,
                'response': response.text,
            }
            jsonHelper.save_to_file(metaRequest, f'{os.getenv("MY_LOG_FOLDER")}metaRequest-{helpers.localNow().isoformat()}.json')
            
            response.raise_for_status()  # Raise an exception for bad status codes
            jsonResponse = response.json()

            msgSid = jsonResponse.get('messages', [{}])[0].get('id', None)
            self.cacheService.setMessage(msgSid=msgSid, value=payload)

            if returnMsgSid:
                return msgSid
            else:
                return jsonResponse
        except requests.exceptions.RequestException as ex:
            self.logger.error(f"An error occurred, payload={payload}", ex)
            if ex.response:
                self.logger.error(f"Error details: {ex.response.text}")
            return None
        except Exception as ex:
            self.logger.error(f"An error occurred, payload={payload}", ex)
            return None

    def sendMessage(self, to: str, message: str, title: str=None, previewUrl: bool=False, replyToMessageId: str=None, returnMsgSid: bool=True, referee_message_extra: dict=None):
        """
        Sends a free-text message to a recipient.

        Note: You can only send free-text messages to users who have
        messaged you in the last 24 hours.

        Args:
            to (str): The recipient's phone number (with country code).
            message (str): The text message to send.

        Returns:
            dict: The JSON response from the API.
        """
        text = ''
        if title:
            text = f"{title}\n"
        text += message
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": previewUrl, "body": text},
        }

        response = self._sendPostRequest(payload=payload, replyToMessageId=replyToMessageId, returnMsgSid=returnMsgSid)
        self.logger.info(f"Meta sendMessage to: {to}, response: {response}")
        value = dict(payload)
        if referee_message_extra:
            value.update(referee_message_extra)
        self.cacheService.setRefereeMessage(mobileNo=to, direction='TO', msgSid=response, value=value)
        return response

    def sendInteractiveMessage(self, to: str, body: str, header: str=None, footer: str=None, interactiveType: str='button', buttons: list=None, returnMsgSid: bool=True, replyToMessageId: str=None):
        """
        Sends an interactive message to a recipient.

        Note: You can only send free-text messages to users who have
        messaged you in the last 24 hours.

        Args:
            to (str): The recipient's phone number (with country code).
            body (str): The text message body.
            header (str, optional): The header text.
            footer (str, optional): The footer text.
            buttons (list, optional): List of buttons to include.
            returnMsgSid (bool): Whether to return message SID.
            replyToMessageId (str, optional): Message ID to reply to.

        Returns:
            dict: The JSON response from the API.
        """
        maxButtonText = 20
        maxListItemText = 24
        maxListItemDescription = 72

        quickReplyButtonsCount = len([button for button in buttons if button.get('type').lower() == 'quick_reply'])
        maxButtonTextLength = max([len(button['text']) for button in buttons]) if buttons else 0
        #maxButtonDescriptionLength = max([len(button.get('description', '')) for button in buttons])
        if (interactiveType == 'button'):
            interactiveType = 'button' if quickReplyButtonsCount <=3 and maxButtonTextLength <= maxButtonText else 'list'
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": interactiveType,
                "header": {
                    "type": "text",
                    "text": header or ""
                },
                "body": {
                    "text": body
                },
                "footer": {
                    "text": footer or ""
                },
                "action": {
                }
            }
        }

        if interactiveType == 'button':
            payload["interactive"]["action"]["buttons"] = []        
            for button in buttons:
                if button.get('type').lower() == 'quick_reply':
                    payload["interactive"]["action"]["buttons"].append(
                        {
                            "type": "reply",
                            "reply": {
                                "id": button["parameters"][0]['payload'],
                                "title": button["text"][:maxButtonText]
                            }
                        }
                    )
                elif button.get('type').lower() == 'url':
                    text = button["text"][:60-len(button["url"])-2]
                    payload["interactive"]["footer"]["text"] += text + " " + button["url"]
        elif interactiveType == 'list':
            payload["interactive"]["action"]["button"] = "לחץ להצגת האפשרויות"
            section = {
                "title": "בחר אחת האפשרויות הבאות:",
                "rows": []
            }
            payload["interactive"]["action"]["sections"] = [section]
            for button in buttons:
                if button.get('type').lower() == 'quick_reply':
                    description = button.get('description') if button.get('description') else button["text"] if len(button["text"]) > maxListItemText else ''
                    section["rows"].append(
                        {
                            "id": button["parameters"][0]['payload'],
                            "title": button["text"][:maxListItemText],
                            "description": description[:maxListItemDescription]
                        }
                    )
                elif button.get('type').lower() == 'url':
                    text = button["text"][:60-len(button["url"])-2]
                    payload["interactive"]["footer"]["text"] += text + " " + button["url"]

        '''
        "action": {
        "name": "send_location" 
        }  
        '''
        response = self._sendPostRequest(payload=payload, replyToMessageId=replyToMessageId, returnMsgSid=returnMsgSid)
        self.cacheService.setRefereeMessage(mobileNo=to, direction='TO', msgSid=response, value=payload)
        self.logger.info(f"Meta sendInteractiveMessage to: {to}, response: {response}")
        return response

    def sendInteractiveMessageUsingTemplate(self, to: str, templateName: str, bodyParameters: list, header: str=None, footer: str=None, buttons: list=None, languageCode: str = "he", replyToMessageId: str=None, returnMsgSid: bool=True):
        try:
            templatePayload = self.generateTemplatePayload(bodyParameters=bodyParameters, buttons=buttons)
            componentsResult = self.convertTemplateToFreetext(templateName=templateName, languageCode=languageCode, templatePayload=templatePayload)   
            buttons = componentsResult["buttons"]
            quickReplyButtonsCount = len([button for button in buttons if button.get('type').lower() == 'quick_reply'])
            urlButtonsCount = len([button for button in buttons if button.get('type').lower() == 'url'])
            if quickReplyButtonsCount > 0:
                response = self.sendInteractiveMessage(to=to, body=componentsResult["body"], header=header, footer=footer, buttons=componentsResult["buttons"], replyToMessageId=replyToMessageId, returnMsgSid=returnMsgSid)
            else:
                if urlButtonsCount > 0:
                    body = componentsResult["body"]
                    for button in componentsResult["buttons"]:
                        if button.get('type').lower() == 'url':
                            body += f"\n{button.get('text')}: {button.get('url')}"
                response = self.sendMessage(to=to, message=body, title=header, previewUrl=False, replyToMessageId=replyToMessageId, returnMsgSid=returnMsgSid)
            return response
        except Exception as ex:
            self.logger.error(f"Error sending interactive message using template", ex)
            return None
    
    def sendTemplateMessage(self, to: str, templateName: str, languageCode: str = "he", components: list = None, replyToMessageId:str=None, returnMsgSid:bool = True):
        """
        Sends a template message to a recipient.

        Args:
            to (str): The recipient's phone number (with country code).
            template_name (str): The name of the message template.
            language_code (str, optional): The language code of the template. Defaults to "en_US".
            components (list, optional): A list of components for dynamic content in the template.

        Returns:
            dict: The JSON response from the API.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": templateName,
                "language": {"code": languageCode},
            },
        }
        if components:
            payload["template"]["components"] = components

        response = self._sendPostRequest(payload=payload, replyToMessageId=replyToMessageId, returnMsgSid=returnMsgSid)
        self.logger.info(f"Meta sendTemplateMessage to: {to}, response: {response}")
        self.cacheService.setRefereeMessage(mobileNo=to, direction='TO', msgSid=response, value=payload)
        return response

    def sendLocation(self, to: str, latitude:str, longitude:str, name:str, address:str, replyToMessageId:str=None, returnMsgSid:bool = True):
        """
        Sends a free-text location message to a recipient.

        Note: You can only send free-text messages to users who have
        messaged you in the last 24 hours.

        Args:
            to (str): The recipient's phone number (with country code).
            message (str): The text message to send.

        Returns:
            dict: The JSON response from the API.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "location",
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "name": name,
                "address": address
            }
        }
        response = self._sendPostRequest(payload=payload, replyToMessageId=replyToMessageId, returnMsgSid=returnMsgSid)
        self.logger.info(f"Meta sendLocation to: {to}, response: {response}")
        self.cacheService.setRefereeMessage(mobileNo=to, direction='TO', msgSid=response, value=payload)
        return response

    def uploadMedia(self, filePath: str) -> str:
        """
        Uploads a media file to Meta's servers.

        Args:
            file_path (str): The local path to the file.

        Returns:
            str: The media ID if successful, otherwise None.
        """        
        # --- Determine the MIME type ---
        # A more robust solution might use the 'mimetypes' library
        file_extension = os.path.splitext(filePath)[1].lower()
        if file_extension == '.pdf':
            mime_type = 'application/pdf'
        elif file_extension in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif file_extension == '.png':
            mime_type = 'image/png'
        else:
            self.logger.warning("Unsupported file type.")
            return None

        # --- Prepare the request ---
        payload = {
            "messaging_product": "whatsapp"
        }        
        files = {
            'file': (os.path.basename(filePath), open(filePath, 'rb'), mime_type)
        }

        # --- Make the request ---
        response = self._sendPostRequest(type="media", formData=payload, files=files)
        media_id = response.get('id')
        self.logger.info(f"File uploaded successfully. Media ID: {media_id}")
        return media_id
        
    def sendDocumentMessage(self, to: str, filePath: str, message: str = "", filename: str = "document.pdf", replyToMessageId:str=None, returnMsgSid:bool = True):
        """
        Sends a document message using a pre-uploaded media ID.

        Args:
            to (str): The recipient's phone number.
            filePath (str): The ID of the uploaded media.
            caption (str, optional): A caption for the document.
            filename (str, optional): The filename to display to the user.

        Returns:
            dict: The JSON response from the API.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": {
                "caption": message,
                "filename": filename
            }
        }
    
        if filePath.lower().startswith("http"):
            payload["document"]["link"] = filePath
        elif os.path.exists(filePath):
            mediaId = self.uploadMedia(filePath=filePath)
            payload["document"]["id"] = mediaId
        elif filePath.isdigit():
            payload["document"]["id"] = filePath

        # This is a simplified _send_request function
        response = self._sendPostRequest(payload=payload, replyToMessageId=replyToMessageId, returnMsgSid=returnMsgSid)
        self.logger.info(f"Meta sendDocumentMessage to: {to}, response: {response}")
        self.cacheService.setRefereeMessage(mobileNo=to, direction='TO', msgSid=response, value=payload)
        return response
    
    async def getMediaDownloadInfo(self, media_id: str) -> str:
        headers = {
            "User-Agent": "curl/7.64.1"  # Some users report this helps
        }
                
        # Get media information first - correct Meta API endpoint format
        media_url = f"{self.metaApiUrl}/{media_id}"
        self.logger.info(f"Requesting media info from: {media_url}")
        response = self._sendGetRequestByUrl(url=media_url)
        return response

    async def downloadMediaFile(self, media_id: str):
        mediaInfo = await self.getMediaDownloadInfo(media_id=media_id)
        response = self._sendGetRequestByUrl(url=mediaInfo.get('url'))
        
        mediaInfo['content'] = response.content
        mediaInfo['actual_file_size'] = len(response.content)
        mediaInfo['actual_content_type'] = response.headers.get('content-type', mediaInfo.get('mime_type'))
            
        return mediaInfo

    def sendContact(self, to:str, phoneNumber:str, phoneType:str, formattedName:str, company:str=None, emailAddress:str=None, url:str=None, replyToMessageId:str=None):
        """
        Sends a contact card message via the WhatsApp Cloud API.
        """
        
        # Construct the complex 'contacts' object
        # This example includes many possible fields. You only need to include the ones you use.
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "contacts",
            "contacts": [
                {
                    "name": {
                        "formatted_name": formattedName,
                        "first_name": formattedName,
                        #"last_name": "Doe",
                        #"suffix": "Jr."
                    },
                    "org": {
                        "company":company,
                        #"department": "Developer Relations",
                        #"title": "Engineer"
                    },
                    "phones": [
                        {
                            "phone": phoneNumber,
                            "type": phoneType,
                            "wa_id": phoneNumber.strip('+') # Include wa_id if it's a WhatsApp number
                        }
                    ],
                    "emails": [
                        {
                            "email": emailAddress,
                            "type": "WORK"
                        }
                    ],
                    "urls": [
                        {
                            "url": url,
                            "type": "WORK"
                        }
                    ]
                }
            ]
        }

        response = self._sendPostRequest(payload=payload, replyToMessageId=replyToMessageId)
        self.logger.info(f"Meta sendContact to: {to}, response: {response}")
        self.cacheService.setRefereeMessage(mobileNo=to, direction='TO', msgSid=response, value=payload)
        return response

    def getTemplateDetails(self, templateName: str, languageCode: str = "he", ) -> dict:
        """
        Get Template Details by calling the WhatsApp Conversation API.

        Args:
            templateName: template name
            languageCode

        Returns:
            dict
        """

        params = {
            "name": templateName,
            "language": languageCode
        }

        self.logger.info(f"Get template details for {templateName} {languageCode}...")

        # 2. Make the GET request to the API
        response = self._sendGetRequest(queryType='message_templates', params=params)

        # 3. Check if the 'data' array in the response is not empty
        if response and response.get("data"):
            data = response["data"][0]
            components = data.get("components")
            return components

        return None

    def generateTemplatePayload(self, bodyParameters, buttons: list=[]):
        body = {
            "type": "body",
            "parameters": []
        }

        payload = [
            body
        ]

        if isinstance(bodyParameters, dict):
            bodyValues = bodyParameters.values()
        elif isinstance(bodyParameters, list):
            bodyValues = bodyParameters
        else:
            bodyValues = []

        for value in bodyValues:
            if not value:
                pass
            body["parameters"].append({
                "type": "text",
                "text": value.replace('\n', '\r') if value else '...'
            })

        i=0
        for button in buttons:
            buttonPayload = {
                "type": "button",
                "sub_type": button['sub_type'],
                "index": str(i),
                "parameters": []
            }
            if button['sub_type'] == 'quick_reply':
                buttonPayload["parameters"].append({ 
                    "type": "payload",
                    "payload": button['id']
                })
            elif button['sub_type'] == 'url':
                buttonPayload["parameters"].append({ 
                    "type": "text",
                    "text": button.get('id') or button.get('text')
                })
            
            payload.append(buttonPayload)
            i+=1

        return payload

    def convertTemplateToFreetext(self, templateName:str = None, templatePayload:list = None, languageCode: str = "he") -> dict:
        if templateName and languageCode:
            templateComponents:list = self.getTemplateDetails(
                templateName=templateName,
                languageCode=languageCode
            )
        else:
            templateComponents:list = []

        body = {}
        buttons = {}
        for component in templateComponents:
            if component['type'].lower() == 'body':
                body = component['text']
            elif component['type'].lower() == 'buttons':
                buttons = component['buttons']
    
        buttonIdx = 0
        for component in templatePayload:
            if component['type'].lower() == 'body' and body:
                i = 1
                for parameter in component['parameters']:
                    key = '{{' + str(i) + '}}'
                    body = body.replace(key, parameter['text'])
                    i += 1
            elif component['type'].lower() == 'button' and buttons:
                i = 1
                for parameter in component['parameters']:
                    button = buttons[buttonIdx]
                    buttonIdx += 1
                    if 'text' not in parameter:
                        if 'parameters' not in button:
                            button['parameters'] = []
                        button['parameters'].append(parameter)
                    else:
                        key = '{{' + str(i) + '}}'
                        if 'text' in button:
                            button['text'] = button['text'].replace(key, parameter['text'])
                        if 'url' in button:
                            urlPrefix = button['url'].replace(key, '').rstrip('/')
                            button['url'] = f"{urlPrefix}/{parameter['text']}"
                        i += 1
        
        componentsResult = {}
        if body:
            componentsResult['body'] = body
        if buttons:
            componentsResult['buttons'] = buttons
        
        return componentsResult

    #NOT WORKING
    def checkConversations(self, fromMobile: str) -> dict:
        """
        Get Template Details by calling the WhatsApp Conversation API.

        Args:
            template_name: template name

        Returns:
            dict
        """

        params = {
            "user_id": fromMobile
        }

        self.logger.info(f"Get template details for {fromMobile}...")

        # 2. Make the GET request to the API
        response = self._sendGetRequest(queryType='conversations', params=params)

        # 3. Check if the 'data' array in the response is not empty
        if response.get("data"):
            conversation = response["data"][0]
            expiration_timestamp_str = conversation.get("expiration_timestamp")

            if expiration_timestamp_str:
                expiration_timestamp = int(expiration_timestamp_str)
                current_timestamp = int(time.time())

                # 4. Compare current time with the expiration time
                if current_timestamp < expiration_timestamp:
                    # If current time is less than expiration, the window is OPEN
                    self.logger.info(f"-> Result: Window is OPEN. Expires at: {time.ctime(expiration_timestamp)}")
                    return True

        # 5. Default case: If no active conversation is found or an error occurs, the window is CLOSED
        self.logger.info("-> Result: Window is CLOSED.")
        return False

    def checkWhatappNumber(self, to: str) -> dict:
        """
        Sends a free-text message to a recipient.

        Note: You can only send free-text messages to users who have
        messaged you in the last 24 hours.

        Args:
            to (str): The recipient's phone number (with country code).
            message (str): The text message to send.

        Returns:
            dict: The JSON response from the API.
        """
        payload = {
            "blocking": "wait",
            "contacts": [
                to
            ]
        }
        response = self._sendPostRequest(type='v1/contacts', payload=payload)
        if response and response.get('contacts'):
            return response.get('contacts')[0].get('status') == 'valid'
        return False

    async def authenticateMetaRequest(self, request: Request):
        """
        Handles incoming messages and verifies their authenticity using the request signature.
        """
        if ('127.0.0.1' in str(request.url.hostname) 
            or 'api-dev.refereex.com' in str(request.url.hostname)
            or 'api-test.refereex.com' in str(request.url.hostname)
            or 'api-beta.refereex.com' in str(request.url.hostname)):
            return

        x_hub_signature_256 = request.headers.get('X-Hub-Signature-256')
        self.logger.debug(f'x_hub_signature_256={x_hub_signature_256}')
        # 1. Get the raw request body
        raw_body = await request.body()

        # 2. Check if the signature header exists
        if x_hub_signature_256 is None:
            self.logger.error("Signature header not found.")
            raise HTTPException(status_code=403, detail="Signature header missing")

        # 3. Compute your own hash
        hash_algorithm, received_hash = x_hub_signature_256.split('=', 1)
        if hash_algorithm != 'sha256':
            self.logger.error("Unsupported hash algorithm.")
            raise HTTPException(status_code=403, detail="Unsupported hash algorithm")

        expected_signature = hmac.new(
            self.meta_app_secret.encode('utf-8'),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        # 4. Compare the hashes
        if not hmac.compare_digest(expected_signature, received_hash):
            self.logger.error("Request signature did not match.")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # 5. If hashes match, process the data
        data = await request.json() # Now it's safe to parse the JSON
        self.logger.debug("Received a verified request from Meta")

    def sendBotContact(self, to:str, replyToMessageId:str=None):
        from .messagingService import _adjustMobileNo
        adjustedTo = _adjustMobileNo(mobileNo=to)
        formattedName = self.formattedName
        refereeId = self.cacheService.resolveRefereeIdByMobile(adjustedTo)
        msgSid = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', refereeId=refereeId, propertyName=formattedName)

        if msgSid:
            return msgSid
        
        msgSid = self.sendContact(
            to=to,
            phoneNumber=self.fromMobile,
            phoneType='CELL',
            formattedName=formattedName,
            company=os.getenv('company'),
            emailAddress=os.getenv('emailAddress'),
            url=os.getenv('url'),
            replyToMessageId=replyToMessageId
        )
        self.cacheService.setRefereeProperty(tenantKey='GLOBAL', refereeId=refereeId, value=msgSid, propertyName=formattedName)

    def sendNewGameNotification(self, toMobile, bodyParameters, gameDetail, sendTemplate, templateName, sendAt=None):
        gameId = gameDetail.get('id')
        buttons = [
            {
                "sub_type": "quick_reply",
                "id": f"approvegameid"
            },
            {
                "sub_type": "quick_reply",
                "id": f"declinegameid"
            },
            {
                "sub_type": "url",
                "id": f"api/file/{gameId}"
            }
        ]
        customData = {
            "gameId": gameId
        }

        if sendTemplate:
            templatePayload = self.generateTemplatePayload(bodyParameters=bodyParameters, buttons=buttons)
            msgSid = self.sendTemplateMessage(to=toMobile, templateName=templateName, components=templatePayload, languageCode="he")
        else:
            msgSid = self.sendInteractiveMessageUsingTemplate(
                to=toMobile,
                templateName=templateName,
                bodyParameters=bodyParameters,
                buttons=buttons,
            )
        
        if msgSid:
            self.cacheService.setReferenceId(target='msgSid', target_id=msgSid, value=customData)
        return msgSid

    def sendGamePortalCodeMessage(self, toMobile, bodyParameters, sendTemplate, templateName, sendAt=None):
        buttons = []

        if sendTemplate:
            templatePayload = self.generateTemplatePayload(bodyParameters=bodyParameters, buttons=buttons)
            msgSid = self.sendTemplateMessage(to=toMobile, templateName=templateName, components=templatePayload, languageCode="he")
        else:
            msgSid = self.sendInteractiveMessageUsingTemplate(
                to=toMobile,
                templateName=templateName,
                bodyParameters=bodyParameters,
                buttons=buttons,
            )
        
        return msgSid

    def sendInteractiveMessageWrapper(self, toMobile, question: str, promptButtons: dict, interactiveType: str='button', header=None, replyToMessageId:str=None, sendAt=None):
        buttons = []
        for button in promptButtons:
            if button['sub_type'] == 'quick_reply':
                buttons.append(
                {
                    "type": button['sub_type'],
                    "parameters": [
                        {
                            "payload": f"answer_{button['id']}",
                            "type": "payload"
                        }
                    ],
                    "text": button['text'],
                    "description": button.get('description')
                })
            elif button['sub_type'] == 'url':
                buttons.append(
                {
                    "type": button['sub_type'],
                    "url": button['url'],
                    "text": button['text']
                })
        response = self.sendInteractiveMessage(to=toMobile, body=question, header=header, interactiveType=interactiveType, buttons=buttons, replyToMessageId=replyToMessageId)
        return response

    async def isIncomingMessage(self, request:Request):
        data = await request.json()
        value = data['entry'][0]['changes'][0]['value']
        message = value.get('messages')
        if message:
            return True
        return False
    
    async def handleIncomingWebhook(self, incomingWebhookCallback, alwaysSendMessage, request:Request):
        from .messagingService import _adjustMobileNo
        data = await request.json()
        #self.logger.info(f'data={data}')
        now = helpers.localNow()
        value = data['entry'][0]['changes'][0]['value']

        statuses = value.get('statuses', [])
        if statuses and len(statuses) > 0:
            current_message_sid = statuses[0].get('id')
            status = statuses[0].get('status')
            to_number = _adjustMobileNo(mobileNo=statuses[0].get('recipient_id'))
            self.logger.debug(f'handleIncomingWebhook:statuses: to_number={to_number} current_message_sid={current_message_sid} status={status}')
            raw_msg = self.cacheService.getRefereeMessages(mobileNo=to_number, direction='TO', msgSid=current_message_sid)
            message = None
            if isinstance(raw_msg, dict):
                if current_message_sid and current_message_sid in raw_msg:
                    message = raw_msg.get(current_message_sid)
                elif len(raw_msg) == 1:
                    message = next(iter(raw_msg.values()))
                else:
                    message = raw_msg
            if not isinstance(message, dict):
                try:
                    alt = self.cacheService.getMessage(current_message_sid)
                    if isinstance(alt, dict):
                        message = dict(alt)
                except Exception:
                    message = None
            if isinstance(message, dict):
                message['status'] = status
                if status == 'failed':
                    errors = statuses[0].get('errors', [])
                    message['deliveryErrors'] = errors
                    errorCode = errors[0].get('code') if errors else None
                    errorMessage = errors[0].get('message') if errors else None
                    self.logger.error(
                        f'Meta delivery failed to={to_number} wamid={current_message_sid} '
                        f'code={errorCode} detail={errorMessage!r}'
                    )
                    self.cacheService.setRefereeMessage(
                        mobileNo=to_number, direction='TO', msgSid=current_message_sid, value=message
                    )
                    hook = self._delivery_failure_hook
                    if hook:
                        try:
                            if asyncio.iscoroutinefunction(hook):
                                await hook(
                                    to_number=to_number,
                                    wamid=current_message_sid,
                                    message_record=dict(message),
                                    errors=errors,
                                )
                            else:
                                hook(
                                    to_number=to_number,
                                    wamid=current_message_sid,
                                    message_record=dict(message),
                                    errors=errors,
                                )
                        except Exception as ex:
                            self.logger.error('Meta delivery_failure_hook error:', ex)
                    return {"status": "handled"}, 200, 'application/json'
                elif status == 'sent':
                    pricing = statuses[0].get('pricing') or {}
                    billable = pricing.get('billable', False)
                    pricing_model = pricing.get('pricing_model')
                    category = pricing.get('category')
                    message['billable'] = billable
                    message['pricing_model'] = pricing_model
                    message['category'] = category
                    self.cacheService.setCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=to_number, propertyName='failedMessageToMeta', value=None, ttlSeconds=-1)
                    self.logger.info(f'Message sent to {to_number}, billable={billable}, pricing_model={pricing_model}, category={category}')
                self.cacheService.setRefereeMessage(mobileNo=to_number, direction='TO', msgSid=current_message_sid, value=message)
            return {"status": "handled"}, 200, 'application/json'

        message = value.get('messages')
        if not message:
            return {"status": "ignored"}, 200, 'application/json'
    
        raw_message = message[0] if message else None
        if not isinstance(raw_message, dict):
            self.logger.warning(f'handleIncomingWebhook: missing or invalid message payload, raw={raw_message!r}')
            return {"status": "ignored"}, 200, 'application/json'
        message = raw_message
        self.logger.info(f'message={message}')
        current_message_sid = message.get('id')
        # Meta may send JSON null: .get('context', {}) still returns None when key exists.
        original_message_sid = (message.get('context') or {}).get('id')
        from_mobile = message.get('from')
        fromMobileNo = _adjustMobileNo(mobileNo=(from_mobile or '').lstrip('whatsapp:'))
        contacts = value.get('contacts') or []
        from_name = None
        if contacts and isinstance(contacts[0], dict):
            profile = contacts[0].get('profile') or {}
            from_name = profile.get('name')
        globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=fromMobileNo)
        if not globalRefereeDetail:
            self.logger.warning(f'handleIncomingWebhook: unknown referee {fromMobileNo} name={from_name}')
            globalRefereeDetail = {'name': from_name, 'status': 'unknown'}
            self.cacheService.setReferee(tenantKey='GLOBAL', mobileNo=fromMobileNo, value=globalRefereeDetail)
        metadata = value.get('metadata') or {}
        to_number = _adjustMobileNo(mobileNo=metadata.get('display_phone_number'))
        message_type = message.get('type')
        message_body = (message.get('text') or {}).get('body') if message_type == 'text' else None
        button_id = None
        if message_type == 'unsupported':
            self.logger.warning(f'metaRequestIncomingWebhook current_message_sid={current_message_sid} message_type={message_type} message={message}')
            response = { 'message': 'סוג ההודעה לא נתמך' }
            return response, 200, 'application/json'
        elif message_type == 'button':
            button_id = (message.get('button') or {}).get('payload')
        elif message_type == 'interactive':
            interactive = message.get('interactive') or {}
            if interactive.get('button_reply'):
                button_id = (interactive.get('button_reply') or {}).get('id')
            elif interactive.get('list_reply'):
                button_id = (interactive.get('list_reply') or {}).get('id')
        if message_type == 'location':
            loc = message.get('location') or {}
            latitude = loc.get('latitude')
            longitude = loc.get('longitude')
        else:
            latitude = None
            longitude = None
        
        # Extract media files from Meta WhatsApp Business API structure
        media_files = []
        if message_type in ['image', 'document', 'audio', 'video', 'sticker']:
            media_data = message.get(message_type) or {}
            media_id = media_data.get('id')
            mime_type = media_data.get('mime_type')
            sha256 = media_data.get('sha256')
            
            if media_id:
                # Get the download URL from Meta API
                media_files.append({
                    "type": mime_type,
                    "media_id": media_id,
                    "sha256": sha256,
                    "message_type": message_type
                })

        metaRequest = {
            "source": "meta",
            "fromMobile": fromMobileNo,
            "fromName": from_name,
            "toMobile": to_number,
            "messageBody": message_body,
            "buttonId": button_id,
            "messageSid": current_message_sid,
            "originalMessageSid": original_message_sid,  # Original message ID for interactive button replies
            "latitude": latitude,
            "longitude": longitude,
            "mediaFiles": media_files
        }

        self.logger.info(f'metaRequestIncomingWebhook={current_message_sid}')
        reply = await incomingWebhookCallback(metaRequest, request)
        if not isinstance(reply, dict):
            reply = {}

        repliedAnswer = reply.get('repliedAnswer')
        repliedFileUrl = reply.get('repliedFileUrl')
        repliedFileName = reply.get('repliedFileName')
        repliedMediaType = reply.get('repliedMediaType')
        repliedAnswerPreview = reply.get('repliedAnswerPreview')
        repliedLocation = reply.get('repliedLocation')

        response = {}
        returnOnly = request.headers.get('ReturnOnly') is not None
        
        if repliedAnswer:
            if alwaysSendMessage:
                if repliedFileUrl:
                    response['urlFile'] = repliedFileUrl
                    self.logger.info(f'repliedFileUrl={repliedFileUrl} repliedMediaType={repliedMediaType}')
                    if not returnOnly:
                        msgSid = self.sendDocumentMessage(to=fromMobileNo, filePath=repliedFileUrl, message=repliedAnswer, filename=repliedFileName, replyToMessageId=current_message_sid)
                        if msgSid:
                            self.cacheService.setRefereeMessage(mobileNo=fromMobileNo, direction='TO', msgSid=msgSid, value=repliedAnswer)
                else:
                    if not returnOnly:
                        msgSid = self.sendMessage(to=fromMobileNo, message=repliedAnswer, previewUrl=repliedAnswerPreview, replyToMessageId=current_message_sid)
                response['message'] = repliedAnswer[:1600]
        if repliedLocation:
            if not returnOnly:
                msgSid = self.sendLocation(to=fromMobileNo, latitude=repliedLocation['latitude'], longitude=repliedLocation['longitude'], name=repliedLocation['name'], address=repliedLocation['address'], replyToMessageId=current_message_sid)
                if msgSid:
                    self.cacheService.setRefereeMessage(mobileNo=fromMobileNo, direction='TO', msgSid=msgSid, value=repliedLocation)

        if not returnOnly:
            if globalRefereeDetail.get('status') != 'unknown':
                msgSid = self.sendBotContact(to=fromMobileNo, replyToMessageId=current_message_sid)

        return response, 200, repliedMediaType or 'application/json'

if __name__ == '__main__':
    # --- Configuration ---
    # IMPORTANT: Replace these with your actual credentials.
    # It's recommended to use environment variables for security.
    RECIPIENT_PHONE_NUMBER = "972547799979" # e.g., "+15551234567"
    RECIPIENT_PHONE_NUMBER1 = "972546402507" # e.g., "+15551234567"

    meta_access_token = helpers.get_secret('meta_access_token')# '3039282:1951c82a6dea3fc9f33de3d7bee92d84'#os.getenv("MANYCHAT_API_KEY")
    meta_phone_number_id = os.getenv('metaPhoneNumberId', "675571508980894")
    metaFromMobile = os.getenv('metaFromMobile')
    whatsapp_business_account_id = os.getenv('metaWhatsappBusinessAccountId', '1297504508377101')
    apiServiceUrlBase = os.getenv('apiServiceUrlBase')
    templateUrlPrefix = os.getenv('templateUrlPrefix')
    # --- Initialization ---
    if meta_access_token == "YOUR_ACCESS_TOKEN" or meta_phone_number_id == "YOUR_PHONE_NUMBER_ID":
        print("Please replace 'YOUR_ACCESS_TOKEN' and 'YOUR_PHONE_NUMBER_ID' with your actual credentials.")
    else:
        from shared.appContainer import AppContainer
        import shared.configurationDI as configDI
        container = AppContainer()
        container.config.from_dict(configDI.configDI)
        container.init_resources()    

        #service = MessagingService(logger=logging.getLogger(), cacheService=cacheService, refereesByMobile={'+972547799979': {'name': 'Guy', 'mobileNo': '+972547799979'}}, activeClient='meta', metaClient=MetaClient(logger=logging.getLogger(), cacheService=cacheService, fromMobile='+972547799979', useClient=True, apiVersion='v24.0', fromPhoneNumberId='120702945000013', whatsappBusinessAccountId='120702945000013'))
        service = container.meta_client()

        current_message_sid = 'wamid.HBgMOTcyNTQ2NDAyNTA3FQIAEhgUM0E0OTdENTMxODZBQjkzNTQxOTQA'
        msgSid = service.sendBotContact(to='972546402507', replyToMessageId=current_message_sid)
        exit(0)
        r = service.sendMessage(to=RECIPIENT_PHONE_NUMBER, message="This is a reply to a message.")#, replyToMessageId='wamid.HBgMOTcyNTQ3Nzk5OTc5FQIAEhgUM0E4RDUwQjlCMjhFMDREMzM3MUIA')
        #api = MetaClient(logger=logging, dbClient=None, apiVersion=os.getenv('metaApiVersion'), fromPhoneNumberId=meta_phone_number_id, whatsappBusinessAccountId=whatsapp_business_account_id, fromMobile=metaFromMobile)
        #service.getMediaDownloadUrl(media_id='31323615290586389', phone_number_id=meta_phone_number_id)
        pass
        # --- Example: Sending a Free-Text Message ---
        if False:
            print("Get Template")
            text_response = api.getTemplateDetails(
                template_name='new_game'
            )
            if text_response:
                print("getTemplateDetails:", text_response)
            print("-" * 20)

        # --- Example: Sending a Free-Text Message ---
        if False:
            print("Get conversations")
            text_response = service.checkConversations(
                fromMobile=RECIPIENT_PHONE_NUMBER
            )
            if text_response:
                print("conversations:", text_response)
            print("-" * 20)

        # --- Example: Sending a Free-Text Message ---
        if False:
            print("Send Contact")
            text_response = service.sendContact(
                to=RECIPIENT_PHONE_NUMBER,
                phoneNumber=metaFromMobile,
                phoneType='CELL',
                formattedName='RefereeX IFA',
                company='RefereeX',
                emailAddress='contact@refereex.com',
                url='https://refereex.com'
            )
            if text_response:
                print("sendContact:", text_response)
            print("-" * 20)
        
        # --- Example: Sending a Free-Text Message ---
        if False:
            print("Window check")
            text_response = service.isWindowOpen(
                to=RECIPIENT_PHONE_NUMBER
            )
            if text_response:
                print("isWindowCheck:", text_response)
            print("-" * 20)

        # --- Example 1: Sending a Free-Text Message ---
        if False:
            print("Sending a free-text message...")
            text_response = service.sendMessage(
                to=RECIPIENT_PHONE_NUMBER,
                message="Hello! This is a test message from my Python script."
            )
            if text_response:
                print("Text message sent successfully:", text_response)
            print("-" * 20)

        # --- Example 2: Sending a Template Message (Simple) ---
        # This assumes you have a template named 'hello_world' with no variables.
        if True:
            print("Sending a simple template message...")
            template_response_simple = service.sendTemplateMessage(
                to=RECIPIENT_PHONE_NUMBER,
                templateName="hello_world", # Replace with your template name
                languageCode="en_US"
            )
            if template_response_simple:
                print("Simple template message sent successfully:", template_response_simple)
            print("-" * 20)

        # --- Example 3: Sending a Template Message with a Body Variable ---
        # This assumes you have a template with a placeholder like '{{1}}' in the body.
        print("Sending a template message with a body variable...")

        templateComponents:list = service.getTemplateDetails(
            templateName='new_game',
            languageCode='he'
        )

        bodyParameters = [
            "גיא",
            "10/09/2025",
            "נוער",
            "הפועל הרצליה-הוד השרון",
            "ראשי",
            "1",
            "1",
            "הרצליה רן 1",
            "מאושר",
            "שופט ראשי: גיא שחר"
        ]

        buttons = [
            {
                "sub_type": "quick_reply",
                "id": "approvegameid"
            },
            {
                "sub_type": "quick_reply",
                "id": "notapprovegameid"
            },
            {
                "sub_type": "url",
                "id": f"{apiServiceUrlBase}api/file/aa45bb",
                "text": "הוסף ללוח שנה"
            }
        ]

        customData = {
            'test': 'test123',
            'action': 'fieldUpdate', 
            'originalMsgSid': '1234567890',
        }
        templatePayload = service.generateTemplatePayload(bodyParameters=bodyParameters, buttons=buttons)
        if False:
            template_response_body = service.sendTemplateMessage(
                to=RECIPIENT_PHONE_NUMBER,
                templateName="new_game", # Replace with your template name
                components=templatePayload,
                languageCode="he"
            )


        buttons = [
            {
                "sub_type": "quick_reply",
                "id": "yes",
                "text": "כן",
                "description": "מאשר שיבוץ"
            },
            {
                "sub_type": "quick_reply",
                "id": "no",
                "text": "לא",
                "description": "לא מאשר שיבוץ"
            },
            {
                "sub_type": "url",
                "url": f"{apiServiceUrlBase}api/file/aa45bb",
                "text": "הוסף ללוח שנה"
            }
        ]
        msgId = service.sendInteractiveMessageWrapper(toMobile=RECIPIENT_PHONE_NUMBER, question=f'האם אתה רוצה לעדכן את מיקום מגרש {'מגרש בלומםילד'} ?', interactiveType='list', promptButtons=buttons)

        if True:
            customData = {
                'action': 'gameApproval', 
                'gameId': 'aaabbb123'
            }            

            buttons = [
                {
                    "sub_type": "quick_reply",
                    "id": "approvegameid",
                    "text": "מאשר שיבוץ"
                },
                {
                    "sub_type": "quick_reply",
                    "id": "notapprovegameid",
                    "text": "עדיין לא מאשר שיבוץ"
                },
                {
                    "sub_type": "url",
                    "url": f"{apiServiceUrlBase}api/file/aa45bb",
                    "text": "הוסף ללוח שנה"
                }
            ]
            template_response_body = service.sendInteractiveMessageUsingTemplate(
                to=RECIPIENT_PHONE_NUMBER,
                templateName="new_game",
                bodyParameters=bodyParameters,
                buttons=buttons,
                customData=customData
            )

        mediaId = service.uploadMedia(
            filePath="/Users/guyshachar/Documents/RefereeX/RefereeX_English_Brochure.pdf"
        )

        send_file_response_body = service.sendDocumentMessage(
            to=RECIPIENT_PHONE_NUMBER,
            filePath=mediaId,
            message="test attached media id",
            filename="attachedFile"
        )
        if send_file_response_body:
            print("Document message with mediaId sent successfully:", send_file_response_body)
        print("-" * 20)

        send_file_response_body = service.sendDocumentMessage(
            to=RECIPIENT_PHONE_NUMBER,
            filePath="/Users/guyshachar/Documents/RefereeX/RefereeX_English_Brochure.pdf",
            message="test attached local file",
            filename="attachedFile"
        )
        if send_file_response_body:
            print("Document message with local file sent successfully:", send_file_response_body)
        print("-" * 20)

        send_file_response_body = service.sendDocumentMessage(
            to=RECIPIENT_PHONE_NUMBER,
            filePath="https://www.refereex.com/images/RefereeX.png",
            message="test attached url file",
            filename="attachedFile"
        )
        if template_response_body:
            print("Document message with url sent successfully:", send_file_response_body)
        print("-" * 20)
    
        # --- Example 4: Sending a Template Message with a Header Variable (Image) ---
        # This assumes you have a template with an image header.
        print("Sending a template message with an image header...")
        components_with_header = [
            {
                "type": "header",
                "parameters": [
                    {
                        "type": "image",
                        "image": {
                            "link": "https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"
                        }
                    }
                ]
            }
        ]
        template_response_header = service.sendTemplateMessage(
            to=RECIPIENT_PHONE_NUMBER,
            templateName="your_template_with_image_header", # Replace with your template name
            components=components_with_header,
            languageCode="en_US"
        )
        if template_response_header:
            print("Template message with image header sent successfully:", template_response_header)
        print("-" * 20)
