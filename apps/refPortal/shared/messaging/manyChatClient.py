import logging
import requests
import json
import sys
import os
import asyncio
import time
from fastapi import Request
from manychat import ManyChat
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.messaging.messagingClientBase import MessagingClientBase
from shared.db import CacheService

class ManychatClient(MessagingClientBase):
    """
    A Python wrapper for the Manychat API, simplifying common interactions.

    This wrapper uses the unofficial 'manychat' Python package.
    It expects the Manychat API Key to be provided during initialization,
    preferably via an environment variable for security.
    """

    def __init__(self, logger:Logger, cacheService:CacheService, fromMobile:str, useClient:bool=False):
        """
        Initializes the ManychatWrapper.

        Args:
            api_key (str): Your Manychat API Key.
                           It's highly recommended to load this from an environment variable.
        """
        super().__init__(logger=logger, cacheService=cacheService, clientName='manychat', fromMobile=fromMobile, useClient=useClient)
        
        api_key = helpers.get_secret('manychat_auth_token')
        if not api_key:
            raise ValueError("Manychat API Key cannot be empty. Please provide a valid key.")
        
        self.mc = ManyChat(api_key)

        self.logger = logger
        self.cacheService = cacheService

        self.logger.info("Manychat starts...")

    def get_page_info(self) -> dict:
        """
        Retrieves information about the Manychat page associated with the API key.

        Returns:
            dict: A dictionary containing page information, or an error message.
        """
        try:
            self.logger.info("Fetching page information...")
            page_info = self.mc.fb.page.get_info()
            self.logger.info("Page info fetched.")
            return page_info
        except Exception as e:
            self.logger.info(f"Error fetching page info: {e}", file=sys.stderr)
            return {"error": str(e)}

    def send_content_to_subscriber(self, subscriber_id: str, content_data: dict, message_tag: str=None, otn_topic_name: str=None) -> dict:
        """
        Sends dynamic content to a specific Manychat subscriber.

        Args:
            subscriber_id (str): The Manychat Subscriber ID.
            content_data (dict): A dictionary representing the content to send.
                                 This should follow Manychat's sendContent API structure.
                                 Example: {"messages": [{"type": "text", "text": "Hello from Python!"}]}

        Returns:
            dict: The API response, or an error message.
        """
        try:
            self.logger.info(f"Sending content to subscriber {subscriber_id}...")
            response = self.mc.fb.sending.send_content(
                subscriber_id=subscriber_id,
                data=content_data,            # The 'data' parameter expects the full content JSON
                message_tag=message_tag,
                otn_topic_name=otn_topic_name
            )
            self.logger.info(f"Content sent to subscriber {subscriber_id}.")
            return response
        except Exception as e:
            self.logger.info(f"Error sending content to subscriber {subscriber_id}: {e}", file=sys.stderr)
            return {"error": str(e)}

    def send_whatsapp_template_to_subscriber(self, subscriber_id: str, template_name: str, language_code: str, variables: list = None) -> dict:
        """
        Sends a WhatsApp template message with variables to a specific subscriber.

        Args:
            subscriber_id (str): The Manychat Subscriber ID.
            template_name (str): The name of the pre-approved WhatsApp template.
            language_code (str): The language code for the template (e.g., 'en', 'es').
            variables (list, optional): A list of dictionaries for template variables.
                                        Each dictionary should have a 'name' and 'value' key.
                                        Example: [{"name": "1", "value": "John"}, {"name": "2", "value": "order 123"}]
                                        Defaults to None.

        Returns:
            dict: The API response, or an error message.
        """
        if variables is None:
            variables = []

        content_data = {
            "version": "v2",
            "content": {
                "type": "whatsapp",
                "actions": [],
                "messages": [
                    {
                        "buttons": [],
                        "template": {
                            "template_name": template_name,
                            "language_code": language_code,
                            "variables": variables
                        }
                    }
                ]
            }
        }
        
        try:
            self.logger.info(f"Sending WhatsApp template '{template_name}' to subscriber {subscriber_id}...")
            response = self.send_content_to_subscriber(
                subscriber_id=subscriber_id,
                content_data=content_data
            )
            self.logger.info(f"WhatsApp template '{template_name}' sent to subscriber {subscriber_id}.")
            return response
        except Exception as e:
            self.logger.error(f"Error sending WhatsApp template '{template_name}' to subscriber {subscriber_id}:", e)
            return {"error": str(e)}

    def send_flow_to_subscriber(self, subscriber_id: str, flow_ns: str) -> dict:
        """
        Sends a Manychat automation flow to a specific subscriber.

        Args:
            subscriber_id (str): The Manychat Subscriber ID.
            flow_ns (str): The Flow Namespace (Flow ID) of the automation to send.
                           You can find this in the URL of your Manychat flow.

        Returns:
            dict: The API response, or an error message.
        """
        try:
            self.logger.info(f"Sending flow '{flow_ns}' to subscriber {subscriber_id}...")
            response = self.mc.fb.sending.send_flow(
                subscriber_id=subscriber_id,
                flow_ns=flow_ns
            )
            self.logger.info(f"Flow '{flow_ns}' sent to subscriber {subscriber_id}.")
            return response
        except Exception as e:
            self.logger.info(f"Error sending flow to subscriber {subscriber_id}: {e}", file=sys.stderr)
            return {"error": str(e)}

    def add_tag_to_subscriber(self, subscriber_id: str, tag_name: str) -> dict:
        """
        Adds a tag to a Manychat subscriber.

        Args:
            subscriber_id (str): The Manychat Subscriber ID.
            tag_name (str): The name of the tag to add.

        Returns:
            dict: The API response, or an error message.
        """
        try:
            self.logger.info(f"Adding tag '{tag_name}' to subscriber {subscriber_id}...")
            response = self.mc.fb.subscriber.add_tag_by_name(
                subscriber_id=subscriber_id,
                tag_name=tag_name
            )
            self.logger.info(f"Tag '{tag_name}' added to subscriber {subscriber_id}.")
            return response
        except Exception as e:
            self.logger.info(f"Error adding tag '{tag_name}' to subscriber {subscriber_id}: {e}", file=sys.stderr)
            return {"error": str(e)}

    def remove_tag_from_subscriber(self, subscriber_id: str, tag_name: str) -> dict:
        """
        Removes a tag from a Manychat subscriber.

        Args:
            subscriber_id (str): The Manychat Subscriber ID.
            tag_name (str): The name of the tag to remove.

        Returns:
            dict: The API response, or an error message.
        """
        try:
            self.logger.info(f"Removing tag '{tag_name}' from subscriber {subscriber_id}...")
            response = self.mc.fb.subscriber.remove_tag_by_name(
                subscriber_id=subscriber_id,
                tag_name=tag_name
            )
            self.logger.info(f"Tag '{tag_name}' removed from subscriber {subscriber_id}.")
            return response
        except Exception as e:
            self.logger.error(f"Error removing tag '{tag_name}' from subscriber {subscriber_id}:", e)
            return {"error": str(e)}

    def set_custom_field_for_subscriber(self, subscriber_id: str, field_name: str, field_value: str) -> dict:
        """
        Sets the value of a custom field for a Manychat subscriber.

        Args:
            subscriber_id (str): The Manychat Subscriber ID.
            field_name (str): The name of the custom field to set.
            field_value (str): The value to set for the custom field.

        Returns:
            dict: The API response, or an error message.
        """
        try:
            self.logger.info(f"Setting custom field '{field_name}' for subscriber {subscriber_id} to '{field_value}'...")
            response = self.mc.fb.subscriber.set_custom_field_by_name(
                subscriber_id=subscriber_id,
                field_name=field_name,
                field_value=field_value
            )
            self.logger.info(f"Custom field '{field_name}' set for subscriber {subscriber_id}.")
            return response
        except Exception as e:
            self.logger.error(f"Error setting custom field '{field_name}' for subscriber {subscriber_id}:", e)
            return {"error": str(e)}

    def set_custom_fields_for_subscriber(self, subscriber_id: str, fields: list) -> dict:
        """
        Sets the values of custom fields for a Manychat subscriber.

        Args:
            subscriber_id (str): The Manychat Subscriber ID.
            fields (list): The name of the custom field and the value to set.

        Returns:
            dict: The API response, or an error message.
        """
        try:
            self.logger.info(f"Setting custom fields for subscriber {subscriber_id}...")
            response = self.mc.fb.subscriber.set_custom_fields(
                subscriber_id=subscriber_id,
                fields=fields
            )
            return response
        except Exception as e:
            self.logger.error(f"Error setting custom fields for subscriber {subscriber_id}:", e)
            return {"error": str(e)}

    def get_subscriber_id_by_custom_field(self, field_name: str, field_value: str) -> str | None:
        """
        Retrieves a Manychat Subscriber ID using a custom user field and its value.

        Args:
            field_name (str): The name of the custom field to search by.
            field_value (str): The value of the custom field to match.

        Returns:
            str | None: The Subscriber ID if found, otherwise None.
        """
        try:
            self.logger.info(f"Searching for subscriber with custom field '{field_name}' = '{field_value}'...")
            # The find_by_custom_field method typically returns a list of subscribers
            # or an empty list if not found. We assume the first match is sufficient.
            subscribers = self.mc.fb.subscriber.find_by_custom_field(
                field_name=field_name,
                field_value=field_value
            )

            if subscribers and subscribers.get('subscribers'):
                # Manychat API often returns a list of dictionaries under a 'subscribers' key
                # We'll take the first one found
                subscriber_id = subscribers['subscribers'][0].get('id')
                self.logger.info(f"Found subscriber ID: {subscriber_id}")
                return subscriber_id
            else:
                self.logger.info(f"No subscriber found with custom field '{field_name}' = '{field_value}'.")
                return None
        except Exception as e:
            self.logger.info(f"Error searching for subscriber by custom field: {e}", file=sys.stderr)
            return None

    def get_subscriber_id_by_phone(self, phone: str) -> str | None:
        """
        Retrieves a Manychat Subscriber ID using a system user phone.

        Args:
            phone (str): The value of the phone to match.

        Returns:
            str | None: The Subscriber ID if found, otherwise None.
        """
        try:
            self.logger.info(f"Searching for subscriber with phone = '{phone}'...")
            # The find_by_custom_field method typically returns a list of subscribers
            # or an empty list if not found. We assume the first match is sufficient.
            subscriber = self.mc.fb.subscriber.find_by_system_field(
                phone=phone,
                email=None
            )

            if subscriber and subscriber.get('status') == 'success' and subscriber.get('data'):
                # Manychat API often returns a list of dictionaries under a 'subscribers' key
                # We'll take the first one found
                subscriber_id = subscriber['data'].get('id')
                self.logger.info(f"Found subscriber ID: {subscriber_id}")
                return subscriber_id
            else:
                self.logger.info(f"No subscriber found with phone = '{phone}'.")
                return None
        except Exception as e:
            self.logger.error(f"Error searching for subscriber by custom field:", e)
            return None

    async def handleIncomingWebhook(self, incomingWebhookCallback, request:Request):
        data = await request.json()
        self.logger.info(f"in manychat incoming data={data}")
        message_id = "aaa"
        status = "status??"
        fromMobile = data.get("fromMobile")
        to_mobile = data.get("toMobile")
        message = data.get("message")
        repliedFileUrl = data.get("repliedFileUrl")
        repliedFileName = data.get("repliedFileName")
        contact = data.get("contact") or {}
        
        response = None
        statusCode = 200
        mediaType = 'application/json'

        if message:
            manychatApiRequest = {
                "source": "manychat",
                "fromMobile": fromMobile,
                "fromName": contact.get("name"),
                "toMobile": to_mobile,
                "messageBody": message,
                "buttonId": None,
                "messageSid": message_id,
                "latitude": None,
                "longitude": None,
                "mediaFiles": None
            }
        
            if manychatApiRequest:
                manychatResponseEmptyValue = os.getenv("manychatResponseEmptyValue")
                reply = await incomingWebhookCallback(manychatApiRequest, request)
                repliedAnswer = reply.get('repliedAnswer') or ""
                repliedFileUrl = reply.get('repliedFileUrl')
                repliedFileName = reply.get('repliedFileName')
                if repliedFileUrl:
                    repliedAnswer += f'\nמצורף קובץ'
                    if repliedFileName:
                        repliedAnswer += f' {repliedFileName}'
                    repliedAnswer += f': {repliedFileUrl}'
                if repliedAnswer is None or repliedAnswer.strip() == "":
                    repliedAnswer = manychatResponseEmptyValue

                response = {
                    "repliedAnswer": repliedAnswer, 
                    #"repliedFileUrl": repliedFileUrl, 
                    #"repliedFileName": repliedFileName
                }

        elif repliedFileUrl:
            response = {
                "version": "v2",
                "content": {
                    "type": "file",
                    "url": repliedFileUrl,
                    "filename": repliedFileName or "קובץ מצורף"
                }
            }
            mediaType = 'application/json'

        if response:
            self.logger.info(f"✅ Processed message {message_id} with status: {status} response={response} statusCode={statusCode} mediaType={mediaType}")
            return response, statusCode, mediaType

        return "", 400, ""

        # Extract message ID and status
        message_id = data.get("idMessage")
        status = data.get("status")
        greenApiRequest = None
        repliedAnswer = 'ok'

        # Define statuses to ignore
        failed_statuses = {"not_sent", "failed", "error"}

        if status in failed_statuses:
            self.greenApiLogger.warning(f"❌ Ignoring failed message {message_id} with status: {status}")
            return ({"status": "ignored"}), 200

        # Extract sender chatId and received message
        if "messageData" in data and "senderData" in data:
            to_mobile = self.cleanMobileNo(data["instanceData"]["wid"])
            chatId = data["senderData"]["chatId"]
            fromChatGroupId = ''
            from_mobile = ''
            if chatId.endswith("@g.us"):
                fromChatGroupId = chatId
            else:
                from_mobile = self.cleanMobileNo(chatId)
            senderId = data["senderData"]["sender"]
            from_name = data["senderData"].get("senderName")
            from_mobile = self.cleanMobileNo(senderId)
            message_data = data.get("messageData", {})
            type_message = message_data.get("typeMessage", "")

            if from_mobile == self.greenApiSupportWhatsapp or from_mobile == self.adjustMobileNo(self.greenApiFromMobile) or fromChatGroupId:
                self.greenApiLogger.info(f"📩 Ignoring message from {from_mobile} {fromChatGroupId}")
                return ({"status": "ignored"}), 200
            
            elif type_message == "textMessage" or type_message == "extendedTextMessage":
                textMessage = message_data.get("textMessageData", {}).get("textMessage", "") or \
                    message_data.get("extendedTextMessageData", {}).get("text", "")
                self.greenApiLogger.info(f"📩 Received message from {from_mobile}: {textMessage}")
                greenApiRequest = {
                    "source": "greenApi",
                    "fromMobile": from_mobile,
                    "fromChatGroupId": fromChatGroupId,
                    "fromName": from_name,
                    "toMobile": to_mobile,
                    "messageBody": textMessage,
                    "buttonId": None,
                    "messageSid": message_id,
                    "latitude": None,
                    "longitude": None,
                    "mediaFiles": None
                }
            elif type_message == "locationMessage":
                latitude = message_data.get("locationMessageData", {}).get("latitude")
                longitude = message_data.get("locationMessageData", {}).get("longitude")
                self.greenApiLogger.info(f"📩 Received location from {from_mobile}: lat:{latitude} lng:{longitude}")
                greenApiRequest = {
                    "fromMobile": from_mobile,
                    "fromChatGroupId": fromChatGroupId,
                    "toMobile": to_mobile,
                    "messageBody": None,
                    "buttonId": None,
                    "messageSid": message_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "mediaFiles": None
                }

            elif type_message == "interactiveButtonsResponse":
                originalMessageSid = message_data.get("interactiveButtonsResponse", {}).get("stanzaId", "")
                originalMessage = self.cacheService.getMessage(originalMessageSid)
                if not originalMessage:
                    self.greenApiLogger.error(f"📩 Received poll update from {from_mobile}, ❌ Message {originalMessageSid} not found")
                else:
                    button_id = message_data.get("interactiveButtonsResponse", {}).get("selectedButtonId", "")
                    if button_id:
                        greenApiRequest = {
                            "fromMobile": from_mobile,
                            "fromChatGroupId": fromChatGroupId,
                            "toMobile": to_mobile,
                            "messageBody": None,
                            "buttonId": button_id,
                            "messageSid": message_id,
                            "latitude": None,
                            "longitude": None,
                            "mediaFiles": None
                        }

            elif type_message == "pollUpdateMessage":
                originalMessageSid = message_data.get("pollMessageData", {}).get("stanzaId", "")
                originalMessage = self.cacheService.getMessage(originalMessageSid)# or {'type':'sendPoll', 'extra':''}
                if not originalMessage:
                    self.greenApiLogger.error(f"📩 Received poll update from {from_mobile}, ❌ Message {originalMessageSid} not found")
                else:
                    votes = message_data.get("pollMessageData", {}).get("votes", "")
                    selectedVote = self.getPollSelection(votes)
                    self.greenApiLogger.info(f"📩 Received poll update from {from_mobile}: {votes} {selectedVote} {originalMessageSid}:{originalMessage.get('extra')}")
                    if selectedVote and originalMessage and originalMessage.get('type', '') == 'sendPoll':
                        if originalMessage.get('extra', ''):
                            extra = originalMessage['extra']
                            if len(extra.split('_')) == 1:
                                extra = f'approveGame_{extra}'
                            action = extra.split('_')[0]
                            input = extra.split('_')[1]
                            button_id = None
                            if action == 'approveGame':
                                gameId = input
                                gameApproved = selectedVote == 'לאשר בפורטל'
                                if gameApproved:
                                    button_id = f'approvegameid_{gameId}'
                                    self.greenApiLogger.info(f"📩 Game {gameId} approved by {from_mobile}")
                            elif action == 'approveJoin':
                                refereeMobile = input
                                joinApproved = selectedVote == 'כן'
                                if joinApproved:
                                    button_id = f'joinconfirmation_yes'
                                    self.greenApiLogger.info(f"📩 Join approved by {refereeMobile}")
                                else:
                                    button_id = f'joinconfirmation_no'
                                    self.greenApiLogger.info(f"📩 Join declined by {refereeMobile}")
                            elif action == 'activate':
                                refId = input
                                activateApproved = selectedVote == 'מאשר'
                                if activateApproved:
                                    button_id = f'activateref_{refId}'
                                    self.greenApiLogger.info(f"📩 Activate approved for {refId}")
                            if button_id:
                                greenApiRequest = {
                                    "fromMobile": from_mobile,
                                    "fromChatGroupId": fromChatGroupId,
                                    "toMobile": to_mobile,
                                    "messageBody": None,
                                    "buttonId": button_id,
                                    "messageSid": message_id,
                                    "latitude": None,
                                    "longitude": None,
                                    "mediaFiles": None
                                }
                        else:
                            greenApiRequest = {
                                "fromMobile": from_mobile,
                                "fromChatGroupId": fromChatGroupId,
                                "toMobile": to_mobile,
                                "messageBody": selectedVote,
                                "buttonId": None,
                                "messageSid": message_id,
                                "latitude": None,
                                "longitude": None,
                                "mediaFiles": None
                            }
            elif type_message == 'imageMessage':
                media_list = [ message_data["downloadUrl"] ]
                self.greenApiLogger.info(f"📩 Received message with filefrom {from_mobile}: {message_data["downloadUrl"]}")
                greenApiRequest = {
                    "fromMobile": from_mobile,
                    "fromChatGroupId": fromChatGroupId,
                    "fromName": from_name,
                    "toMobile": to_mobile,
                    "messageBody": None,
                    "buttonId": None,
                    "messageSid": message_id,
                    "latitude": None,
                    "longitude": None,
                    "mediaFiles": media_list
                }
            else:
                self.greenApiLogger.warning(f"📩 Received message from {from_mobile}: {message_data}")

            if greenApiRequest:
                reply = await incomingWebhookCallback(greenApiRequest, request)
                repliedAnswer = reply.get('repliedAnswer')
                repliedFileUrl = reply.get('repliedFileUrl')
                if repliedAnswer:
                    await self.handleAction('sendMessage', {'to': chatId, 'message': repliedAnswer})

            self.greenApiLogger.info(f"✅ Processed message {message_id} with status: {status}")
            return ({"response": repliedAnswer}), 200
   
        return ({"status": "processed"}), 200

# --- Example Usage ---
if __name__ == "__main__":
    # --- IMPORTANT: Get your Manychat API Key ---
    # 1. Log in to Manychat.
    # 2. Go to Settings -> API.
    # 3. Generate your API Key.
    # 4. For security, set it as an environment variable before running this script:
    #    export MANYCHAT_API_KEY="YOUR_ACTUAL_MANYCHAT_API_KEY_HERE"
    #    (On Windows, use: set MANYCHAT_API_KEY=YOUR_ACTUAL_MANYCHAT_API_KEY_HERE)
    logger = logging

    manychat_api_key = helpers.get_secret('manychat_auth_token')# '3039282:1951c82a6dea3fc9f33de3d7bee92d84'#os.getenv("MANYCHAT_API_KEY")
    incomingApiGuid = helpers.get_secret('incoming_api_guid')

    if not manychat_api_key:
        logger.error("Error: MANYCHAT_API_KEY environment variable is not set.")
        logger.error("Please set it before running the script.")
        sys.exit(1)

    try:
        # Initialize the wrapper
        mc_wrapper = ManychatClient(logger=logger, dbClient=None, api_key=manychat_api_key)

        # --- Test: Get Page Info ---
        page_info_response = mc_wrapper.get_page_info()
        if "error" not in page_info_response:
            logger.info("\n--- Page Info ---")
            logger.info(f"Page Name: {page_info_response.get('page_name')}")
            logger.info(f"Page ID: {page_info_response.get('page_id')}")
            logger.info(f"Subscriber Count: {page_info_response.get('subscriber_count')}")
        else:
            logger.info(f"\nFailed to get page info: {page_info_response['error']}")

        # --- Test: Get Subsriber by Phone ---
        find_subscriber_response = mc_wrapper.get_subscriber_id_by_phone(phone='+972547799979')
        if "error" not in page_info_response:
            logger.info("\n--- Page Info ---")
            logger.info(f"Page Name: {find_subscriber_response}")
        else:
            logger.info(f"\nFailed to get subscriber id: {page_info_response['error']}")

        content_data = {
            "version": "v2",
            "content": {
                "type": "whatsapp",
                "actions": [],
                "messages": [
                    {
                        "buttons": [],
                        "text": f"hello Guy {time.time()}",
                        "type": "text"
                    }
                ]
            }
        }

        wat_response = mc_wrapper.send_content_to_subscriber(
            subscriber_id=find_subscriber_response,
            content_data=content_data)

        botFields = [
            {
                "field_name": "apiServiceBase",
                "field_value": f"{os.getenv('apiServiceUrlBase').lstrip('https://')}"
            },
            {
                "field_name": "incomingApiGuid",
                "field_value": f"{incomingApiGuid}"
            }
        ]
       
        for i in range(1):
            customUserFields = [
                {
                    "field_name": "apiServiceBase1",
                    "field_value": f"{os.getenv('apiServiceUrlBase').lstrip('https://')}"
                },
                {
                    "field_name": "incomingApiGuid1",
                    "field_value": f"{incomingApiGuid}"
                },
                {
                "field_name": "refNick",
                "field_value": "גיא"
                },
                {
                "field_name": "game_Datetime",
                "field_value": "יום שישי 20/05/2025 14:10"
                },
                {
                "field_name": "game_Tournament",
                "field_value": "ילדים ב שרון"
                },
                {
                "field_name": "game_Title",
                "field_value": f"נתניה-נוה יוסף {time.time()}"
                },
                {
                "field_name": "game_RefereePosition",
                "field_value": "ראשי"
                },
                {
                "field_name": "game_Round",
                "field_value": "30"
                },
                {
                "field_name": "game_Fixture",
                "field_value": "2"
                },
                {
                "field_name": "game_Field",
                "field_value": "נתניה שפירא"
                },
                {
                "field_name": "game_RefereeStatus",
                "field_value": "מאושר"
                },
                {
                "field_name": "game_RefereeTeam",
                "field_value": "גיא שופט ראשי"
                },
                {
                "field_name": "game_Id",
                "field_value": "gm-20250604-001"
                }
            ]

            wat_response = mc_wrapper.set_custom_fields_for_subscriber(
                subscriber_id=find_subscriber_response,
                fields=customUserFields)


            wat_response = mc_wrapper.send_flow_to_subscriber(
                subscriber_id=find_subscriber_response,
                flow_ns='content20250609160707_210201')

        # --- Test: Send Whatsapp Template ---
        template_name = 'NewGameAssignment'
        language_code = 'he'
        variables = [
            {"refNick": "גיאא"},
            {"gameDatetime": "יום שישי 20/05/2025 14:10"},
            {"tournament": "ילדים ב שרון"},
            {"gameTitle": f"נתניה-נוה יוסף {time.time()}"},
            {"refereePosition": "ראשי"},
            {"gameRound": "2"},
            {"gameFixture": "30"},
            {"gameField": "נתניה שפירא"},
            {"refereeStatus": "מאושר"},
            {"gameRefereeTeam": "גיא שופט ראשי"},
            {"gameId": "gm-20250604-001"},
        ]

        wat_response = mc_wrapper.send_whatsapp_template_to_subscriber(
            subscriber_id=find_subscriber_response,
            template_name=template_name,
            language_code=language_code,
            variables=variables)
        if "error" not in wat_response:
            logger.info(f"Subscriber Count: {wat_response.get('subscriber_count')}")
        else:
            logger.info(f"\nFailed to get page info: {wat_response['error']}")


        # --- Test: Send a Text Message (requires a valid Subscriber ID) ---
        # Replace 'YOUR_SUBSCRIBER_ID' with an actual Subscriber ID from your Manychat contacts
        # and 'YOUR_FLOW_NAMESPACE' with an actual Flow NS from your Manychat flow URL.
        # You need an active 24-hour messaging window with the subscriber to send content.
        # Also, the 'send_content' API is for dynamic content, not simple broadcast messages outside a flow.
        # For actual messaging to a user, 'send_flow' is often more practical.

        # For demonstration purposes, we'll use placeholder values.
        # DO NOT run these lines in production without valid IDs and a clear understanding of Manychat's rules.
        test_subscriber_id = "YOUR_SUBSCRIBER_ID" # <<< REPLACE THIS
        test_flow_ns = "YOUR_FLOW_NAMESPACE" # <<< REPLACE THIS (e.g., content20230101_12345)
        test_tag_name = "PythonTestTag"
        test_custom_field_name = "my_python_field"
        test_custom_field_value = "hello_world"

        # --- Test: Send a Flow ---
        # send_flow_response = mc_wrapper.send_flow_to_subscriber(test_subscriber_id, test_flow_ns)
        # if "error" not in send_flow_response:
        #     self.logger.info(f"\nSuccessfully sent flow: {send_flow_response}")
        # else:
        #     self.logger.info(f"\nFailed to send flow: {send_flow_response['error']}")

        # --- Test: Add Tag ---
        # add_tag_response = mc_wrapper.add_tag_to_subscriber(test_subscriber_id, test_tag_name)
        # if "error" not in add_tag_response:
        #     self.logger.info(f"\nSuccessfully added tag: {add_tag_response}")
        # else:
        #     self.logger.info(f"\nFailed to add tag: {add_tag_response['error']}")

        # --- Test: Set Custom Field ---
        # set_field_response = mc_wrapper.set_custom_field_for_subscriber(
        #     test_subscriber_id, test_custom_field_name, test_custom_field_value
        # )
        # if "error" not in set_field_response:
        #     self.logger.info(f"\nSuccessfully set custom field: {set_field_response}")
        # else:
        #     self.logger.info(f"\nFailed to set custom field: {set_field_response['error']}")

        # --- Test: Remove Tag ---
        # remove_tag_response = mc_wrapper.remove_tag_from_subscriber(test_subscriber_id, test_tag_name)
        # if "error" not in remove_tag_response:
        #     self.logger.info(f"\nSuccessfully removed tag: {remove_tag_response}")
        # else:
        #     self.logger.info(f"\nFailed to remove tag: {remove_tag_response['error']}")

    except Exception as ex:
        logger.error(f"An unexpected error occurred during execution:", ex)

