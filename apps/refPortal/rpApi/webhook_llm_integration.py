#!/usr/bin/env python3.12
"""
Webhook LLM Integration

This module integrates the LLM system with your existing webhook infrastructure.
It enhances your current webhook responses with AI-powered responses.
"""

import os
import sys
import asyncio
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

# Add shared modules to path
sys.path.append(str(Path(__file__).resolve().parent))
from llm_webhook_integration import LLMWebhookIntegration, LLMWebhookHandler, LLMResponse
from shared.logger import Logger
from shared.bedrockClient import BedrockClient
from shared.db import DynamodbClient
import shared.helpers as helpers
from shared.db import CacheService

class WebhookLLMEnhancer:
    """Enhances webhook responses with LLM capabilities"""
    
    def __init__(self, 
                 logger: Logger,
                 cacheService: CacheService,
                 llm_integration,
                 webhook_handler,
                 config: Dict[str, Any] = None,
                 response_cache=None):
        
        self.logger = logger
        self.cacheService = cacheService
        self.llm_integration = llm_integration
        self.webhook_handler = webhook_handler
        self.response_cache = response_cache
        self.config = config or {}
        
        self.logger.info("Webhook LLM Enhancer initialized")
    
    async def enhance_incoming_webhook(self, 
                                     incoming_request: Dict,
                                     referee_detail: Optional[Dict] = None,
                                     existing_response: Optional[str] = None) -> str:
        """Enhance incoming webhook with LLM response"""
        
        try:
            # Get enhanced response from LLM
            enhanced_response, is_enhanced = await self.webhook_handler.enhance_webhook_response(
                incoming_request=incoming_request,
                referee_detail=referee_detail,
                existing_response=existing_response
            )
            
            if is_enhanced:
                self.logger.info("Webhook response enhanced with LLM")
            else:
                self.logger.info("Using existing webhook response")
            
            return enhanced_response
            
        except Exception as e:
            self.logger.error(f"Error enhancing webhook:", e)
            return existing_response or ""
    
    async def process_complex_query(self, 
                                  message: str,
                                  referee_detail: Optional[Dict] = None) -> LLMResponse:
        """Process complex queries that need LLM analysis"""
        
        try:
            # Check cache first if available
            if self.response_cache:
                cached_response = self.response_cache.get_cached_response(message, referee_detail)
                if cached_response:
                    self.logger.info(f"Using cached response for message: {message[:50]}...")
                    return LLMResponse(
                        answer=cached_response,
                        confidence=0.9,  # High confidence for cached responses
                        sources=["cached"],
                        action_required=False
                    )
            
            # Get recent messages for context
            recent_messages = []
            if referee_detail:
                recent_messages = self.cacheService.getRefereeMessages(mobileNo=referee_detail['mobileNo'], direction='FROM')
            
            # Process through LLM
            llm_response = await self.llm_integration.process_webhook_message(
                message=message,
                referee_detail=referee_detail,
                recent_messages=recent_messages
            )
            
            # Cache the response if available and confidence is high enough
            if (self.response_cache and 
                llm_response.confidence > 0.7 and 
                llm_response.answer):
                
                self.response_cache.cache_response(
                    message=message,
                    response=llm_response.answer,
                    confidence=llm_response.confidence,
                    referee_detail=referee_detail,
                    metadata={
                        'sources': llm_response.sources,
                        'action_required': llm_response.action_required
                    }
                )
            
            return llm_response
            
        except Exception as e:
            self.logger.error(f"Error processing complex query:", e)
            return LLMResponse(
                answer="מצטער, יש בעיה טכנית. אנא נסה שוב מאוחר יותר.",
                confidence=0.0,
                sources=[],
                action_required=False
            )

# Integration with your existing RefPortalImplementationApi class
def integrate_llm_with_webhook(ref_portal_instance):
    """Integrate LLM with existing RefPortalImplementationApi instance"""
    
    # Create LLM enhancer
    llm_enhancer = WebhookLLMEnhancer(
        logger=ref_portal_instance.logger,
        cacheService=ref_portal_instance.cacheService,
        bedrock_client=ref_portal_instance.bedrockClient,
        config=ref_portal_instance.config
    )
    
    # Store in the instance
    ref_portal_instance.llm_enhancer = llm_enhancer
    
    return llm_enhancer

# Enhanced incomingWebhook method
async def enhanced_incoming_webhook(self, incoming_request, request):
    """Enhanced version of incomingWebhook with LLM integration"""
    
    # Original webhook logic (your existing code)
    source = incoming_request.get('source')
    current_message_sid = incoming_request.get('messageSid')
    if not current_message_sid:
        current_message_sid = str(uuid.uuid4())[:8]
        incoming_request['messageSid'] = current_message_sid
    
    from_mobile = incoming_request.get('fromMobile')
    fromMobileNo = MessagingService.adjustMobileNo((from_mobile or '').lstrip('whatsapp:'))
    message_body = incoming_request.get('messageBody') or ''
    
    # Check if it's a bot message
    if fromMobileNo in self.botMobileNumbers:
        return {}
    
    # Get referee details
    referee_detail = self.refereesByMobile.get(fromMobileNo)
    
    # Save incoming message
    if referee_detail:
        incoming_request['archived'] = False
        self.cacheService.setRefereeMessage(mobileNo=referee_detail['mobileNo'], msgSid=current_message_sid, value=incoming_request)
    
    # Process message with existing logic
    action = ''
    action_value = None
    if message_body:
        (action, action_value) = self.classify_message(message=message_body)
    
    # Get existing response
    existing_response = None
    
    # Handle different actions (your existing logic)
    if action == 'הצטרפות':
        existing_response = await self.askToJoin(fromMobileNo)
    elif action in self.configFiles:
        existing_response = self.configFiles[action]
    elif action == 'מגרש':
        field_to_search = message_body.replace(action, '')
        existing_response, _ = self.generateFieldDetails(field_to_search=field_to_search)
    elif action == 'תמיכה':
        name = referee_detail.get('name') if referee_detail else 'Unknown'
        await self.messagingService.sendMessage(to=self.adminMobile, message=f'{name} פונה לתמיכה {fromMobileNo}')
        existing_response = f'{name}, יחזרו אליך בהקדם'
    
    # Enhance response with LLM if available
    if hasattr(self, 'llm_enhancer'):
        try:
            enhanced_response = await self.llm_enhancer.enhance_incoming_webhook(
                incoming_request=incoming_request,
                referee_detail=referee_detail,
                existing_response=existing_response
            )
            
            # Use enhanced response if it's better
            if enhanced_response and enhanced_response != existing_response:
                existing_response = enhanced_response
                self.logger.info("Using LLM enhanced response")
            
        except Exception as e:
            self.logger.error(f"Error in LLM enhancement:", e)
    
    # Return response
    return {
        'repliedAnswer': existing_response,
        'repliedAnswerPreview': False,
        'repliedLocation': None
    }

# Usage instructions
def setup_llm_integration_instructions():
    """Instructions for setting up LLM integration"""
    
    instructions = """
# LLM Webhook Integration Setup

## 1. Initialize LLM Integration

Add this to your RefPortalImplementationApi.__init__ method:

```python
# After other initializations
if hasattr(self, 'bedrockClient'):
    self.llm_enhancer = integrate_llm_with_webhook(self)
```

## 2. Replace incomingWebhook method

Replace your existing incomingWebhook method with the enhanced version:

```python
async def incomingWebhook(self, incoming_request, request):
    return await enhanced_incoming_webhook(self, incoming_request, request)
```

## 3. Environment Variables

Add these to your environment:

```bash
# Bedrock configuration
AWS_REGION=il-central-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0

# LLM configuration
LLM_ENABLED=true
LLM_MAX_TOKENS=4000
LLM_TEMPERATURE=0.3
```

## 4. Knowledge Base Setup

Ensure your documentation is accessible via the docs service:

- intentPhrases.json
- Documentation files (.txt, .pdf)
- Field data
- Referee data

## 5. Testing

Test the integration:

```python
# Test LLM response
async def test_llm_response(self, message: str):
    if hasattr(self, 'llm_enhancer'):
        response = await self.llm_enhancer.process_complex_query(message)
        return response.answer
    return "LLM not available"
```

## 6. Monitoring

Monitor LLM interactions in the database:

```sql
-- Check LLM interactions
SELECT * FROM llm_interactions_prod 
WHERE timestamp > '2024-01-01' 
ORDER BY timestamp DESC;
```

## 7. Configuration

The LLM will automatically:
- Load your documentation
- Use your existing intent phrases
- Access field and referee data
- Provide context-aware responses
- Log all interactions for analysis
"""
    
    return instructions

def create_llm_webhook_handler(llm_integration) -> Optional['LLMWebhookHandler']:
    """
    Factory function to create LLMWebhookHandler instances for dependency injection.
    
    Args:
        llm_integration: LLMWebhookIntegration instance
        
    Returns:
        LLMWebhookHandler instance or None if creation fails
    """
    try:
        if not llm_integration:
            return None
            
        handler = LLMWebhookHandler(llm_integration)
        return handler
        
    except Exception as e:
        # Since we don't have logger here, we'll just return None
        return None

def create_webhook_llm_enhancer(logger: Logger, cacheService: CacheService, llm_integration, webhook_handler, config: Dict[str, Any] = None, response_cache=None) -> Optional[WebhookLLMEnhancer]:
    """
    Factory function to create WebhookLLMEnhancer instances for dependency injection.
    
    Args:
        logger: Logger instance
        cacheService: CacheService instance
        llm_integration: LLMWebhookIntegration instance to inject (required)
        webhook_handler: LLMWebhookHandler instance to inject (required)
        config: Configuration dictionary
        response_cache: Optional response cache instance (LLMResponseCache or InMemoryLLMResponseCache)
        
    Returns:
        WebhookLLMEnhancer instance or None if creation fails
    """
    try:
        if not llm_integration:
            logger.error("LLMWebhookIntegration is required for WebhookLLMEnhancer")
            return None
            
        if not webhook_handler:
            logger.error("LLMWebhookHandler is required for WebhookLLMEnhancer")
            return None
            
        # Check if LLM is enabled in config
        if config and not config.get('LLM', {}).get('enabled', False):
            logger.info("LLM integration disabled via configuration")
            return None
            
        enhancer = WebhookLLMEnhancer(
            logger=logger,
            cacheService=cacheService,
            llm_integration=llm_integration,
            webhook_handler=webhook_handler,
            response_cache=response_cache,
            config=config,
        )
        logger.info("WebhookLLMEnhancer created successfully")
        return enhancer
        
    except Exception as e:
        logger.error(f"Failed to create WebhookLLMEnhancer:", e)
        return None

def create_llm_webhook_integration(logger: Logger, bedrock_client: BedrockClient, cacheService: CacheService, config: Dict[str, Any], handle_referee_data=None) -> Optional['LLMWebhookIntegration']:
    """
    Factory function to create LLMWebhookIntegration instances for dependency injection.
    
    Args:
        logger: Logger instance
        bedrock_client: Bedrock client instance
        cacheService: CacheService instance
        config: Configuration dictionary
        handle_referee_data: Optional HandleRefereeData for per-referee schedule/statistics in prompts
        
    Returns:
        LLMWebhookIntegration instance or None if creation fails
    """
    try:
        if not bedrock_client:
            logger.warning("BedrockClient not available - LLMWebhookIntegration creation failed")
            return None
            
        if not config.get('LLM', {}).get('enabled', False):
            logger.info("LLM integration disabled via configuration")
            return None
            
        llm_integration = LLMWebhookIntegration(
            logger=logger,
            bedrock_client=bedrock_client,
            cacheService=cacheService,
            docs_service_url=config.get('docsServiceUrlBase'),
            config=config,
            handle_referee_data=handle_referee_data,
        )
        logger.info("LLMWebhookIntegration created successfully")
        return llm_integration
        
    except Exception as e:
        logger.error(f"Failed to create LLMWebhookIntegration:", e)
        return None

if __name__ == "__main__":
    print(setup_llm_integration_instructions())
