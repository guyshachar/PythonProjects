"""
Telegram Bot API client with equivalent interface to MetaClient (WhatsApp Cloud API)
for use with Telegram not integration. Uses sync requests to match Meta client style.
"""
import os
import sys
import json
import logging
import hmac
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import requests
from fastapi import Request, HTTPException

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.messaging.messagingClientBase import MessagingClientBase
from shared.db import CacheService

TELEGRAM_API_BASE = "https://api.telegram.org/bot"

class TelegramClient(MessagingClientBase):
    """
    Telegram Bot API wrapper with MetaClient-equivalent methods.
    'to' is Telegram chat_id (str or int). Use getChatId(mobileNo) or store chat_id per user.
    """

    def __init__(
        self,
        logger: Logger,
        cacheService: CacheService,
        username: str,
        fromMobile: str,
        apiServiceUrlBase: str = None,
        useClient: bool = False,
    ):
        super().__init__(
            logger=logger,
            cacheService=cacheService,
            clientName="telegram",
            fromMobile=fromMobile,
            useClient=useClient,
        )
        self.logger = logger
        self.cacheService = cacheService
        self.apiServiceUrlBase = apiServiceUrlBase

        self.botToken = helpers.get_secret("telegram_bot_token")
        if useClient and (not self.botToken):
            raise ValueError("Telegram bot token is required when useClient=True.")
        self.webhook_secret_token = helpers.get_secret("telegram_webhook_secret_token")
        self._api_base = f"{TELEGRAM_API_BASE}{self.botToken}" if self.botToken else ""
        self.bot = Bot(token=self.botToken)        
        self.logger.info("Telegram client starts...")

    def _request(self, method: str, params: dict = None, data: dict = None, files: dict = None) -> Optional[dict]:
        url = f"{self._api_base}/{method}"
        try:
            if files:
                # Multipart: form fields in data, file in files
                form = {k: (v if v is not None else "") for k, v in (data or params or {}).items()}
                resp = requests.post(url, data=form, files=files, timeout=60)
            elif data or params:
                resp = requests.post(url, json=data or params, timeout=30)
            else:
                resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            out = resp.json()
            if not out.get("ok"):
                self.logger.error(f"Telegram API error: {out}")
                return None
            return out.get("result")
        except requests.exceptions.RequestException as ex:
            self.logger.error(f"Telegram request error: {ex}")
            if getattr(ex, "response", None) and ex.response is not None:
                self.logger.error(f"Response: {ex.response.text}")
            return None

    def read_channel_messages(
        self,
        channel_id: str,
        limit: int = 100,
        after_update_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Read messages (channel posts) from a Telegram channel.
        channel_id: Telegram chat id (e.g. -1001234567890) or channel @username.
        Bot must be in the channel (e.g. as admin) to receive posts.
        Returns list of message dicts with message_id, chat_id, text, date, etc.
        """
        updates = self.get_updates(
            offset=after_update_id,
            limit=limit,
            allowed_updates=["channel_post"],
        )
        if not updates:
            return []
        try:
            channel_id_int = int(channel_id)
        except (TypeError, ValueError):
            channel_id_int = None
        messages: List[Dict[str, Any]] = []
        for u in updates:
            post = u.get("channel_post") or u.get("edited_channel_post")
            if not post:
                continue
            chat = post.get("chat") or {}
            cid = chat.get("id")
            if channel_id_int is not None and cid != channel_id_int:
                continue
            if channel_id_int is None and str(cid) != str(channel_id):
                continue
            messages.append({
                "update_id": u.get("update_id"),
                "message_id": post.get("message_id"),
                "chat_id": cid,
                "chat_title": chat.get("title"),
                "text": post.get("text") or "",
                "date": post.get("date"),
                "sender_chat": post.get("sender_chat"),
            })
        return messages

    def sendMessage(
        self,
        chatId: str,
        mobileNo: str,
        message: str,
        title: Optional[str] = None,
        previewUrl: bool = False,
        replyToMessageId: Optional[str] = None,
        returnMsgSid: bool = True,
    ) -> Optional[str]:
        """Send a text message. to = chat_id."""
        try:
            text = f"{title}\n{message}" if title else message
            payload = {"chat_id": chatId, "text": text, "disable_web_page_preview": not previewUrl}
            if replyToMessageId:
                payload["reply_to_message_id"] = int(replyToMessageId)
            result = self._request("sendMessage", data=payload)
            if not result:
                return None
            msg_id = f'telegram_{str(result.get("message_id"))}'
            self.logger.info(f"Telegram sendMessage to: {chatId}, message_id: {msg_id}")
            self.cacheService.setRefereeMessage(mobileNo=chatId, direction="TO", msgSid=msg_id, value={"text": text})
            return msg_id if returnMsgSid else result
        except Exception as ex:
            self.logger.error(f"Telegram sendMessage error: {ex}")
            return None

    async def sendButton(
        self, 
        chatId: str, 
        message: str,
        url: str,
        returnMsgSid: bool = True,
        replyToMessageId: Optional[str] = None):
        # Creating the buttons
        keyboard = [
            [
                InlineKeyboardButton("פתח WhatsApp", url=url)
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Sending the message
        response =await self.bot.send_message(
            chat_id=chatId,
            text=message,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        pass
        
    def sendButton1(
        self, 
        chatId: str, 
        message: str,
        url: str,
        returnMsgSid: bool = True,
        replyToMessageId: Optional[str] = None

    ) -> Optional[str]:
        # Call Telegram's sendMessage with an inline_keyboard
        payload = {
            "chat_id": chatId,
            "text": message,
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "פתח WhatsApp", "url": url}
                ]]
            }
        }

        result = self._request("sendMessage", data=payload)
        if not result:
            return None
        msg_id = f'telegram_{str(result.get("message_id"))}'
        self.logger.info(f"Telegram sendInteractiveMessage to: {chatId}, message_id: {msg_id}")
        return msg_id if returnMsgSid else result

    def sendInteractiveMessage(
        self,
        chatId: str,
        mobileNo: str,
        body: str,
        header: Optional[str] = None,
        footer: Optional[str] = None,
        buttons: Optional[List[dict]] = None,
        returnMsgSid: bool = True,
        replyToMessageId: Optional[str] = None,
    ) -> Optional[str]:
        """Send text with inline buttons. Buttons: quick_reply -> callback_data, url -> url button."""
        text_parts = []
        if header:
            text_parts.append(header)
        text_parts.append(body)
        if footer:
            text_parts.append(footer)
        text = "\n".join(text_parts)

        payload = {"chat_id": chatId, "text": text}
        if replyToMessageId:
            payload["reply_to_message_id"] = int(replyToMessageId)

        if buttons:
            inline_rows = []
            for btn in (buttons or []):
                btype = (btn.get("type") or "").lower()
                if btype == "quick_reply":
                    payload_id = (btn.get("parameters") or [{}])[0].get("payload") or btn.get("id") or "unknown"
                    inline_rows.append([{"text": (btn.get("text") or "Button")[:64], "callback_data": payload_id}])
                elif btype == "url":
                    url = btn.get("url") or ""
                    inline_rows.append([{"text": (btn.get("text") or "Link")[:64], "url": url}])
            if inline_rows:
                payload["reply_markup"] = json.dumps({"inline_keyboard": inline_rows})

        result = self._request("sendMessage", data=payload)
        if not result:
            return None
        msg_id = f'telegram_{str(result.get("message_id"))}'
        self.logger.info(f"Telegram sendInteractiveMessage to: {chatId}, message_id: {msg_id}")
        return msg_id if returnMsgSid else result

    def sendInteractiveMessageUsingTemplate(
        self,
        chatId: str,
        mobileNo: str,
        templateName: str,
        bodyParameters: list,
        header: Optional[str] = None,
        footer: Optional[str] = None,
        buttons: Optional[list] = None,
        languageCode: str = "he",
        replyToMessageId: Optional[str] = None,
        returnMsgSid: bool = True,
    ) -> Optional[str]:
        """Telegram has no templates; send as interactive (body from template conversion or bodyParameters)."""
        try:
            components = self.convertTemplateToFreetext(
                templateName=templateName, languageCode=languageCode, templatePayload=self.generateTemplatePayload(bodyParameters=bodyParameters, buttons=buttons or [])
            )
            body = components.get("body", "\n".join(str(p) for p in bodyParameters))
            return self.sendInteractiveMessage(
                chatId=chatId,
                mobileNo=mobileNo,
                body=body,
                header=header,
                footer=footer,
                buttons=components.get("buttons") or buttons,
                replyToMessageId=replyToMessageId,
                returnMsgSid=returnMsgSid,
            )
        except Exception as ex:
            self.logger.error("Error sending interactive message using template", ex)
            return None

    def sendLocation(
        self,
        chatId: str,
        mobileNo: str,
        latitude: str,
        longitude: str,
        name: Optional[str] = None,
        address: Optional[str] = None,
        replyToMessageId: Optional[str] = None,
        returnMsgSid: bool = True,
    ) -> Optional[str]:
        """Send location. name/address not in Telegram sendLocation; send as caption in a follow-up if needed."""
        payload = {"chat_id": chatId, "latitude": float(latitude), "longitude": float(longitude)}
        if replyToMessageId:
            payload["reply_to_message_id"] = int(replyToMessageId)
        result = self._request("sendLocation", data=payload)
        if not result:
            return None
        msg_id = f'telegram_{str(result.get("message_id"))}'
        self.logger.info(f"Telegram sendLocation to: {chatId}, message_id: {msg_id}")
        self.cacheService.setRefereeMessage(mobileNo=mobileNo, direction="TO", msgSid=msg_id, value={"location": [latitude, longitude]})
        return msg_id if returnMsgSid else result

    def uploadMedia(self, filePath: str) -> Optional[str]:
        """Upload document to Telegram and return file_id. Telegram does not have a separate media upload; we send to a temp chat or return path. For compatibility we send as document to get file_id - not possible without chat. Return file path or URL for sendDocumentMessage to use."""
        if not os.path.exists(filePath):
            return None
        return filePath

    def sendDocumentMessage(
        self,
        chatId: str,
        mobileNo: str,
        filePath: str,
        message: str = "",
        filename: str = "document.pdf",
        replyToMessageId: Optional[str] = None,
        returnMsgSid: bool = True,
    ) -> Optional[str]:
        """Send document: filePath can be local path, URL, or Telegram file_id."""
        payload = {"chat_id": chatId, "caption": message[:1024] if message else ""}
        if replyToMessageId:
            payload["reply_to_message_id"] = int(replyToMessageId)

        if filePath.lower().startswith("http"):
            payload["document"] = filePath
            result = self._request("sendDocument", data=payload)
        elif os.path.exists(filePath):
            fn = filename or os.path.basename(filePath)
            with open(filePath, "rb") as f:
                result = self._request("sendDocument", data=payload, files={"document": (fn, f)})
        else:
            payload["document"] = filePath
            result = self._request("sendDocument", data=payload)

        if not result:
            return None
        msg_id = f'telegram_{str(result.get("message_id"))}'
        self.logger.info(f"Telegram sendDocumentMessage to: {chatId}, message_id: {msg_id}")
        self.cacheService.setRefereeMessage(mobileNo=chatId, direction="TO", msgSid=msg_id, value={"document": filePath})
        return msg_id if returnMsgSid else result

    async def getMediaDownloadInfo(self, file_id: str) -> Optional[dict]:
        """Get Telegram file info by file_id."""
        result = self._request("getFile", data={"file_id": file_id})
        return result

    async def downloadMediaFile(self, file_id: str) -> Optional[dict]:
        """Download file by file_id. Returns dict with content, file_path, etc."""
        info = await self.getMediaDownloadInfo(file_id)
        if not info or not info.get("file_path"):
            return None
        url = f"https://api.telegram.org/file/bot{self.botToken}/{info['file_path']}"
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            info["content"] = r.content
            info["actual_file_size"] = len(r.content)
            info["actual_content_type"] = r.headers.get("Content-Type", "application/octet-stream")
            return info
        except requests.exceptions.RequestException as ex:
            self.logger.error(f"Telegram download file error: {ex}")
            return None

    def sendContact(
        self,
        chatId: str,
        mobileNo: str,
        phoneNumber: str,
        phoneType: str,
        formattedName: str,
        company: Optional[str] = None,
        emailAddress: Optional[str] = None,
        url: Optional[str] = None,
        replyToMessageId: Optional[str] = None,
    ) -> Optional[str]:
        """Telegram: send contact (phone_number, first_name). Other fields sent as text if needed."""
        payload = {"chat_id": chatId, "phone_number": phoneNumber, "first_name": formattedName}
        if replyToMessageId:
            payload["reply_to_message_id"] = int(replyToMessageId)
        result = self._request("sendContact", data=payload)
        if not result:
            return None
        msg_id = f'telegram_{str(result.get("message_id"))}'
        self.logger.info(f"Telegram sendContact to: {chatId}, message_id: {msg_id}")
        self.cacheService.setRefereeMessage(mobileNo=chatId, direction="TO", msgSid=msg_id, value={"contact": formattedName})
        return msg_id

    def getTemplateDetails(self, templateName: str, languageCode: str = "he") -> Optional[dict]:
        """Telegram has no template API; return minimal structure for convertTemplateToFreetext."""
        return [{"type": "body", "text": "{{1}}"}, {"type": "buttons", "buttons": []}]

    def generateTemplatePayload(self, bodyParameters, buttons: Optional[list] = None) -> list:
        """Meta-style template payload. Telegram uses this only for convertTemplateToFreetext."""
        body = {"type": "body", "parameters": []}
        values = list(bodyParameters.values()) if isinstance(bodyParameters, dict) else list(bodyParameters) if isinstance(bodyParameters, list) else []
        for v in values:
            body["parameters"].append({"type": "text", "text": (v or "").replace("\n", "\r")})
        payload = [body]
        for i, btn in enumerate(buttons or []):
            sub = (btn.get("sub_type") or "quick_reply").lower()
            bp = {"type": "button", "sub_type": sub, "index": str(i), "parameters": []}
            if sub == "quick_reply":
                bp["parameters"].append({"type": "payload", "payload": btn.get("id", "")})
            elif sub == "url":
                bp["parameters"].append({"type": "text", "text": btn.get("id") or btn.get("url") or btn.get("text", "")})
            payload.append(bp)
        return payload

    def convertTemplateToFreetext(
        self,
        templateName: Optional[str] = None,
        templatePayload: Optional[list] = None,
        languageCode: str = "he",
    ) -> dict:
        """Build body and buttons from template payload (no Telegram template API)."""
        body = ""
        buttons = []
        for comp in templatePayload or []:
            if not isinstance(comp, dict):
                continue
            if comp.get("type") == "body":
                body = comp.get("text", "")
                params = comp.get("parameters") or []
                for i, p in enumerate(params):
                    body = body.replace(f"{{{{{i+1}}}}}", p.get("text", ""))
                if not body and params:
                    body = " ".join(p.get("text", "") for p in params)
            elif comp.get("type") == "button":
                sub = comp.get("sub_type", "quick_reply")
                params = comp.get("parameters") or []
                btn = {"type": sub, "parameters": [{"payload": params[0].get("payload") if params else ""}], "text": ""}
                if params and "text" in params[0]:
                    btn["text"] = params[0]["text"]
                buttons.append(btn)
        return {"body": body or "Message", "buttons": buttons}

    def sendBotContact(self, chatId: str, mobileNo: str, replyToMessageId: Optional[str] = None) -> Optional[str]:
        """Send bot contact (phone, name) to user."""
        from .messagingService import _adjustMobileNo
        adjustedMobileNo = _adjustMobileNo(mobileNo=mobileNo)
        formatted_name = os.getenv("formattedName", "Bot")
        globalRefereeDetail = self.cacheService.getReferees(tenantKey="GLOBAL", mobileNo=adjustedMobileNo)
        if globalRefereeDetail.get(formatted_name):
            return globalRefereeDetail.get(formatted_name)
        msg_id = self.sendContact(
            chatId=globalRefereeDetail.get('telegramId'),
            phoneNumber=self.fromMobile,
            phoneType="CELL",
            formattedName=formatted_name,
            company=os.getenv("company"),
            emailAddress=os.getenv("emailAddress"),
            url=os.getenv("url"),
            replyToMessageId=replyToMessageId,
        )
        if msg_id:
            self.cacheService.setRefereeProperty(tenantKey="GLOBAL", mobileNo=adjustedMobileNo, value=msg_id, propertyName=formatted_name)
        return msg_id

    def sendNewGameNotification(
        self,
        chatId,
        mobileNo: str,
        bodyParameters: list,
        gameDetail: dict,
        templateName: str,
        sendAt=None,
    ) -> Optional[str]:
        """Send new game notification with approve/decline/url buttons."""
        game_id = gameDetail.get("id", "")
        buttons = [
            {"sub_type": "quick_reply", "id": "approvegameid"},
            {"sub_type": "quick_reply", "id": "declinegameid"},
            {"sub_type": "url", "id": f"{self.apiServiceUrlBase or ''}api/file/{game_id}", "text": "קישור", "url": f"{self.apiServiceUrlBase or ''}api/file/{game_id}"},
        ]
        msg_sid = self.sendInteractiveMessageUsingTemplate(
            chatId=chatId, mobileNo=mobileNo, templateName=templateName, bodyParameters=bodyParameters, buttons=buttons
        )
        if msg_sid:
            self.cacheService.setReferenceId(target="msgSid", target_id=msg_sid, value={"gameId": game_id})
        return msg_sid

    def sendGamePortalCodeMessage(
        self,
        chatId: str,
        mobileNo: str,
        bodyParameters: list,
        templateName: str,
        sendAt=None,
    ) -> Optional[str]:
        return self.sendInteractiveMessageUsingTemplate(chatId=chatId, mobileNo=mobileNo, templateName=templateName, bodyParameters=bodyParameters, buttons=[])

    def sendInteractiveMessageWrapper(
        self,
        chatId: str,
        mobileNo: str,
        question: str,
        promptButtons: dict,
        header: Optional[str] = None,
        replyToMessageId: Optional[str] = None,
        sendAt=None,
    ) -> Optional[str]:
        """Build buttons from promptButtons and send interactive message."""
        buttons = []
        for btn in promptButtons:
            if (btn.get("sub_type") or "").lower() == "quick_reply":
                buttons.append({
                    "type": "quick_reply",
                    "parameters": [{"payload": f"answer_{btn.get('id', '')}", "type": "payload"}],
                    "text": btn.get("text", ""),
                    "description": btn.get("description"),
                })
            elif (btn.get("sub_type") or "").lower() == "url":
                buttons.append({"type": "url", "url": btn.get("url", ""), "text": btn.get("text", "")})
        return self.sendInteractiveMessage(chatId=chatId, mobileNo=mobileNo, body=question, header=header, buttons=buttons, replyToMessageId=replyToMessageId)

    async def authenticateTelegramRequest(self, request: Request) -> None:
        """Verify Telegram webhook secret_token if configured."""
        if not self.webhook_secret_token:
            return
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not token or not hmac.compare_digest(token, self.webhook_secret_token):
            self.logger.error("Telegram webhook secret token missing or invalid")
            raise HTTPException(status_code=403, detail="Invalid Telegram webhook token")

    async def isIncomingMessage(self, request: Request) -> bool:
        """True if request body contains a message or callback_query."""
        try:
            body = await request.json()
        except Exception:
            return False
        return "message" in body or "callback_query" in body

    async def handleIncomingWebhook(
        self,
        incomingWebhookCallback,
        alwaysSendMessage: bool,
        request: Request,
    ) -> tuple:
        """Parse Telegram Update, build meta-style request dict, call callback, send replies."""
        
        try:
            data = await request.json()
            self.logger.info(f"Telegram webhook data: {data}")
            if not data:
                return {"status": "ignored"}, 200, "application/json"

            #self._request(method="answerCallbackQuery", data={"callback_query_id": callback["id"]})
            message = data.get("message", {})
            chat_id = str(message["chat"]["id"])
            from_user = message.get("from", {})
            from_id = str(from_user.get("id", ""))
            from_username = from_user.get("username") or from_user.get("first_name") or ""
            fromMobileNo = self.cacheService.getKeyVal(key=f'telegramUserId_{from_id}') or from_id
            from_name = (from_user.get("first_name") or "") + " " + (from_user.get("last_name") or "")
            current_message_id = str(message["message_id"])
            original_message_id = str(message.get("reply_to_message", {}).get("message_id", ""))
            button_id = data.get("data", "")
                    
            if message.get('text'):
                message_type = 'text'
                message_body = message.get('text')
            elif message.get('location'):
                message_type = 'location'
                latitude = message.get('location').get('latitude')
                longitude = message.get('location').get('longitude')
            elif message.get('photo'):
                message_type = 'photo'
                photos = message.get('photo')
                media_files = []
                for photo in photos:
                    media_files.append({
                        "type": photo.get('mime_type'),
                        "media_id": photo.get('file_id'),
                        "file_unique_id": photo.get('file_unique_id'),
                        "file_size": photo.get('file_size'),
                        "width": photo.get('width'),
                        "height": photo.get('height'),
                        "message_type": 'photo'
                    })
            else:
                message_type = 'text'
                message_body = message.get('text')

            telegram_request = {
                "source": "telegram",
                "fromId": from_id,
                "fromUsername": from_username,
                "fromMobile": fromMobileNo,
                "fromName": from_name,
                "toMobile": chat_id,
                "messageBody": message_body if message_type == 'text' else None,
                "buttonId": button_id,
                "messageSid": current_message_id,
                "originalMessageSid": original_message_id,
                "latitude": latitude if message_type == 'location' else None,
                "longitude": longitude if message_type == 'location' else None,
                "mediaFiles": media_files if message_type == 'photo' else None,
            }

            if message_type == 'text' and message_body == '/pair':
                telegram_request['skipAuthentication'] = True
            
            self.logger.info(f'metaRequestIncomingWebhook={current_message_id}')
            reply = await incomingWebhookCallback(telegram_request, request)

            repliedAnswer = reply.get('repliedAnswer')
            repliedFileUrl = reply.get('repliedFileUrl')
            repliedFileName = reply.get('repliedFileName')
            repliedMediaType = reply.get('repliedMediaType')
            repliedAnswerPreview = reply.get('repliedAnswerPreview')
            repliedLocation = reply.get('repliedLocation')

            response = {}
            returnOnly = request.headers.get('ReturnOnly') is not None or False
            
            if repliedAnswer:
                if message_type == 'text' and message_body == '/pair':
                    await self.sendButton(chatId=from_id, message=repliedAnswer, url=repliedFileUrl)

                elif alwaysSendMessage:
                    if repliedFileUrl:
                        response['urlFile'] = repliedFileUrl
                        self.logger.info(f'repliedFileUrl={repliedFileUrl} repliedMediaType={repliedMediaType}')
                        if not returnOnly:
                            msgSid = self.sendDocumentMessage(chatId=from_id, mobileNo=fromMobileNo, filePath=repliedFileUrl, message=repliedAnswer, filename=repliedFileName, replyToMessageId=current_message_id)
                            if msgSid:
                                self.cacheService.setRefereeMessage(mobileNo=fromMobileNo, direction='TO', msgSid=msgSid, value=repliedAnswer)
                    else:
                        if not returnOnly:
                            msgSid = self.sendMessage(chatId=from_id, mobileNo=fromMobileNo, message=repliedAnswer, previewUrl=repliedAnswerPreview, replyToMessageId=current_message_id)
                    response['message'] = repliedAnswer[:1600]
            if repliedLocation:
                if not returnOnly:
                    msgSid = self.sendLocation(chatId=from_id, mobileNo=fromMobileNo, latitude=repliedLocation['latitude'], longitude=repliedLocation['longitude'], name=repliedLocation['name'], address=repliedLocation['address'], replyToMessageId=current_message_id)
                    if msgSid:
                        self.cacheService.setRefereeMessage(mobileNo=fromMobileNo, direction='TO', msgSid=msgSid, value=repliedLocation)

            if not returnOnly:
                msgSid = self.sendBotContact(chatId=from_id, mobileNo=fromMobileNo, replyToMessageId=current_message_id)

            return response, 200, repliedMediaType or 'application/json'
        except Exception as ex:
            self.logger.error(f"Telegram webhook body error: {ex}")
            return {"status": "error"}, 500, "application/json"

if __name__ == "__main__":
    telegramClient = TelegramClient(logging.getLogger(__name__), None, None, None, False)
    messages = telegramClient.read_channel_messages(channel_id="-1002381342060")
    print(messages)