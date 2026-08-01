import boto3
import json
from botocore.exceptions import BotoCoreError, ClientError
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger


class BedrockClient():
    def __init__(
        self,
        logger: Logger,
        awsRegion=None,
        bedrockModelId=None,
        bedrockModelArn=None,
        bedrockKbId=None,
        truncate_model_token_limits=None,
    ):
        try:
            self.logger = logger
            # Constants for AWS Bedrock
            self.KB_ID = bedrockKbId
            self.MODEL_ARN = bedrockModelArn
            self.bedrockAwsRegion = awsRegion
            self.truncate_model_token_limits = (
                truncate_model_token_limits if isinstance(truncate_model_token_limits, dict) else {}
            )
            
            # Initialize AWS clients with proper error handling
            try:
                self.bedrockClient = boto3.client("bedrock-agent", region_name=self.bedrockAwsRegion)
                self.logger.info(f"Bedrock agent client initialized for region: {self.bedrockAwsRegion}")
            except Exception as e:
                self.logger.warning(f"Failed to initialize bedrock-agent client:", e)
                self.bedrockClient = None
            
            try:
                self.bedrockRTClient = boto3.client("bedrock-agent-runtime", region_name=self.bedrockAwsRegion)
                self.logger.info(f"Bedrock agent runtime client initialized for region: {self.bedrockAwsRegion}")
            except Exception as e:
                self.logger.warning(f"Failed to initialize bedrock-agent-runtime client:", e)
                self.bedrockRTClient = None
            
            try:
                self.bedrockRuntime = boto3.client("bedrock-runtime", region_name=self.bedrockAwsRegion)
                self.logger.info(f"Bedrock runtime client initialized for region: {self.bedrockAwsRegion}")
            except Exception as e:
                self.logger.error(f"Failed to initialize bedrock-runtime client:", e)
                self.bedrockRuntime = None
                
        except Exception as e:
            self.logger.error(f'BedrockClient/init error={e}')
            self.bedrockClient = None
            self.bedrockRTClient = None
            self.bedrockRuntime = None
    
    def estimate_tokens(self, text: str) -> int:
        """Rough estimation of tokens (4 characters per token)"""
        return len(text) // 4
    
    def truncate_prompt(self, prompt: str, max_tokens: int = 4000, model_id: str = None) -> str:
        """Truncate prompt to fit within model limits"""
        model_limits = self.truncate_model_token_limits

        # Determine the limit based on model
        limit = max_tokens
        mid = (model_id or "").lower()
        for model_key, model_limit in model_limits.items():
            if str(model_key).lower() in mid:
                limit = min(max_tokens, model_limit)
                break
        
        # Estimate tokens in current prompt
        estimated_tokens = self.estimate_tokens(prompt)
        
        if estimated_tokens <= limit:
            return prompt
        
        # Truncate the prompt
        # Keep the beginning and end, remove from middle
        chars_per_token = 4
        max_chars = limit * chars_per_token
        
        if len(prompt) <= max_chars:
            return prompt
        
        # Split into beginning and end
        beginning_chars = max_chars // 3
        end_chars = max_chars // 3
        
        beginning = prompt[:beginning_chars]
        end = prompt[-end_chars:] if end_chars > 0 else ""
        
        # Add truncation indicator
        truncated_prompt = f"{beginning}\n\n[Content truncated due to length...]\n\n{end}"
        
        self.logger.warning(f"Prompt truncated from {estimated_tokens} tokens to ~{limit} tokens for model {model_id}")
        return truncated_prompt

    def _bedrock_requires_inference_profile_first(self, model_id: str) -> bool:
        """
        Some Anthropic IDs only accept InvokeModel via a regional inference profile
        (eu.<modelId> / us.<modelId>), not the bare foundation-model on-demand id.
        """
        m = (model_id or "").lower()
        if not m or m.startswith(("eu.", "us.", "global.")):
            return False
        return (
            "claude-sonnet-4" in m
            or "claude-opus-4" in m
            or "claude-haiku-4" in m
            or "claude-4-5" in m
            or "nova-lite" in m
        )

    def _inference_profile_variants(self, model_id: str) -> list:
        """
        Ordered modelId values to try for InvokeModel.
        Newer Claude 4.x / 4.5 models: inference profile first (eu.* / us.*), then bare id as fallback.
        Older models: bare id first, then profile (previous behavior).
        """
        if not model_id or not str(model_id).strip():
            return []
        mid = str(model_id).strip()
        if mid.startswith(("eu.", "us.", "global.")):
            return [mid]
        region = (self.bedrockAwsRegion or "").lower()
        profile_first = self._bedrock_requires_inference_profile_first(mid)

        def pair(reg_prefix: str):
            prof = f"{reg_prefix}.{mid}"
            return [prof, mid] if profile_first else [mid, prof]

        if region.startswith("eu-"):
            return pair("eu")
        if region.startswith("us-"):
            return pair("us")
        # Unknown bedrock region: still try standard inference profile prefixes, then direct id.
        if profile_first:
            return [f"eu.{mid}", f"us.{mid}", mid]
        return [mid]

    def call_bedrock_agent(self, prompt, session_id="referee-session-1"):
        return ''
        if not self.KB_ID:
            self.logger.warning("Knowledge base ID is not configured.")
            return {"error": "Knowledge base not configured."}

        response = self.bedrockClient.list_knowledge_bases()
        for kb in response.get("knowledgeBaseSummaries", []):
            print(f"Name: {kb['name']}, ID: {kb['knowledgeBaseId']}, Status: {kb['status']}")
        print(self.bedrockClient.meta.service_model.operation_names)
        print(self.bedrockRTClient.meta.service_model.operation_names)

        try:
            response = self.bedrockRTClient.converse(
                agentId=self.KB_ID,
                sessionId=session_id,
                input={"text": prompt}
            )

            return {
                "answer": response["output"]["text"].strip(),
                "sessionState": response.get("sessionState", {})
            }

            response = self.bedrockRTClient.retrieve_and_generate(
                input={"text": prompt},
                retrieveAndGenerateConfiguration={
                    "type": "KNOWLEDGE_BASE",
                    "knowledgeBaseConfiguration": {
                        "knowledgeBaseId": f'{self.KB_ID}',
                        "modelArn": self.MODEL_ARN,
                        "generationConfiguration": {
                            "promptTemplate": {
                                "textPromptTemplate": (
                                    "המשתמש שאל: $query$\n"
                                    "ענה על בסיס המידע הבא:\n"
                                    "$search_results$\n"
                                    "תשובתך:"
                                )
                            }
                        },
                        "orchestrationConfiguration": {
                            "promptTemplate": {
                                "textPromptTemplate": (
                                    "היסטוריית שיחה:\n$conversation_history$\n\n"
                                    "השאלה:\n$query$\n\n"
                                    "$output_format_instructions$"
                                )                            
                            }
                        }
                    }
                }
            )
            return {"answer": response["output"]["text"].strip()}
        except (BotoCoreError, ClientError) as ex:
            self.logger.error(f"Bedrock error: Failed to get response", ex)
        except Exception as ex:
            self.logger.error("Unexpected error during Bedrock call", ex)
    
    def log_token_usage(self, response: dict, model_id: str = None, prompt: str = None) -> dict:
        """
        Extract and log token usage information from Bedrock response
        
        Args:
            response: Response from bedrockRuntime.invoke_model()
            model_id: Optional model ID for context
            prompt: Optional prompt for context
            
        Returns:
            dict: Token usage information
        """
        try:
            # Extract response metadata
            response_metadata = response.get('ResponseMetadata', {})
            http_headers = response_metadata.get('HTTPHeaders', {})
            
            # Get standardized token counts from headers
            input_tokens = http_headers.get('x-amzn-bedrock-input-token-count')
            output_tokens = http_headers.get('x-amzn-bedrock-output-token-count')
            total_tokens = http_headers.get('x-amzn-bedrock-total-token-count')
            
            # Convert to integers (headers are strings)
            token_usage = {}
            if input_tokens:
                token_usage['input_tokens'] = int(input_tokens)
            if output_tokens:
                token_usage['output_tokens'] = int(output_tokens)
            if total_tokens:
                token_usage['total_tokens'] = int(total_tokens)
            
            # Also try to get usage from response body as fallback
            response_body = response.get('body')
            if response_body:
                # Reset body stream position for reading
                response_body#.seek(0)
                try:
                    body_content = json.loads(response_body.read())
                    body_usage = body_content.get('usage', {})
                    if body_usage:
                        # Use body usage if headers are missing
                        if 'input_tokens' not in token_usage and 'input_tokens' in body_usage:
                            token_usage['input_tokens'] = body_usage['input_tokens']
                        if 'output_tokens' not in token_usage and 'output_tokens' in body_usage:
                            token_usage['output_tokens'] = body_usage['output_tokens']
                        if 'total_tokens' not in token_usage and 'total_tokens' in body_usage:
                            token_usage['total_tokens'] = body_usage['total_tokens']
                except Exception as e:
                    self.logger.debug(f"Could not parse response body for usage: {e}")
            
            # Calculate total if we have both input and output
            if 'input_tokens' in token_usage and 'output_tokens' in token_usage:
                calculated_total = token_usage['input_tokens'] + token_usage['output_tokens']
                if 'total_tokens' not in token_usage:
                    token_usage['total_tokens'] = calculated_total
                elif token_usage['total_tokens'] != calculated_total:
                    self.logger.warning(f"Token count mismatch: calculated {calculated_total} vs header {token_usage['total_tokens']}")
            
            # Log the token usage
            if token_usage:
                model_info = f" for model {model_id}" if model_id else ""
                prompt_info = f" (prompt: {len(prompt)} chars)" if prompt else ""
                
                self.logger.info(
                    f"Token usage{model_info}{prompt_info}: "
                    f"{token_usage.get('input_tokens', 'N/A')} input + "
                    f"{token_usage['output_tokens']} output = "
                    f"{token_usage.get('total_tokens', 'N/A')} total tokens"
                )
                
                # Log detailed breakdown
                self.logger.debug(f"Detailed token usage: {token_usage}")
                
                # Log cost estimate if we have total tokens
                if 'total_tokens' in token_usage:
                    # Rough cost estimate (adjust rate as needed)
                    cost_per_1k_tokens = 0.00015  # $0.00015 per 1K tokens (example rate)
                    estimated_cost = (token_usage['total_tokens'] / 1000) * cost_per_1k_tokens
                    self.logger.info(f"Estimated cost: ${estimated_cost:.6f}")
            else:
                self.logger.warning("No token usage information found in response")
            
            return token_usage
            
        except Exception as e:
            self.logger.error(f"Error logging token usage:", e)
            return {}
    
    def invoke_model_async(self, model_id: str, prompt: str, max_tokens: int = 4000, 
                          temperature: float = 0.3, fallback_model_ids: list = None) -> dict:
        """Invoke Bedrock model directly for text generation with fallback support"""
        try:
            # Check if bedrock runtime client is available
            if not self.bedrockRuntime:
                self.logger.error("Bedrock runtime client not initialized")
                return {"error": "Bedrock runtime client not available - check AWS configuration"}
            
            # Expand each logical model: direct ID, then eu.*/us.* inference profile for that region.
            models_to_try = []
            seen = set()
            for mid in [model_id] + list(fallback_model_ids or []):
                for variant in self._inference_profile_variants(mid):
                    if variant not in seen:
                        seen.add(variant)
                        models_to_try.append(variant)

            for current_model_id in models_to_try:
                try:
                    # Truncate prompt if it's too long for the model
                    truncated_prompt = self.truncate_prompt(prompt, max_tokens, current_model_id)
                    
                    request_body = None
                    # Prepare the request body based on model type
                    # For newer Claude models, try different format if needed
                    if "claude-3" in current_model_id.lower():
                        # Alternative format for Claude 3 models
                        request_body = {
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": truncated_prompt
                                }
                            ]
                        }

                    elif "claude" in current_model_id.lower():
                        request_body = {
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": truncated_prompt
                                }
                            ]
                        }
                        
                    elif "titan" in current_model_id.lower():
                        request_body = {
                            "inputText": truncated_prompt,
                            "textGenerationConfig": {
                                "maxTokenCount": max_tokens,
                                "temperature": temperature
                            }
                        }
                    elif "nova" in current_model_id.lower():
                        # Amazon Nova Invoke API: messages + inferenceConfig (no top-level max_tokens / prompt)
                        request_body = {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [{"text": truncated_prompt}],
                                }
                            ],
                            "inferenceConfig": {
                                "maxTokens": max_tokens,
                                "temperature": temperature,
                            },
                        }
                    else:
                        # For other models, use a simpler format
                        request_body = {
                            "prompt": truncated_prompt,
                            "max_tokens": max_tokens,
                            "temperature": temperature
                        }
                    
                    # Invoke the model
                    self.logger.debug(f"Invoking model {current_model_id} with request body {request_body}")
                    response = self.bedrockRuntime.invoke_model(
                        modelId=current_model_id,
                        body=json.dumps(request_body),
                        contentType="application/json"
                    )
                    
                    # Parse the response
                    response_body = json.loads(response['body'].read())

                    # Log token usage from the response
                    token_usage = self.log_token_usage(response, current_model_id, truncated_prompt)
                    
                    if "claude" in current_model_id.lower():
                        # Claude response format
                        content = response_body.get('content', [])
                        if content and len(content) > 0:
                            text = content[0].get('text', '')
                        else:
                            text = ''
                    elif "titan" in current_model_id.lower():
                        # Titan response format
                        text = response_body.get('results', [{}])[0].get('outputText', '')
                    elif "nova" in current_model_id.lower():
                        text = ""
                        content_list = (
                            response_body.get("output", {})
                            .get("message", {})
                            .get("content", [])
                        )
                        if isinstance(content_list, list):
                            for block in content_list:
                                if isinstance(block, dict) and "text" in block:
                                    text = block.get("text") or ""
                                    break
                        if not text.strip():
                            text = response_body.get("outputText", "") or ""
                    else:
                        # Other models response format
                        text = response_body.get('completion', response_body.get('text', ''))
                    
                    return {
                        "text": text.strip(),
                        "model_id": current_model_id,
                        "usage": response_body.get('usage', {}),
                        "token_usage": token_usage
                    }
                    
                except (BotoCoreError, ClientError) as ex:
                    error_msg = str(ex)
                    if "AccessDeniedException" in error_msg:
                        self.logger.warning(f"Access denied for model {current_model_id}, trying next model...")
                        continue
                    elif "ResourceNotFoundException" in error_msg:
                        self.logger.warning(
                            f"Model unavailable or legacy access denied for {current_model_id}, trying next model..."
                        )
                        continue
                    elif "Could not connect to the endpoint URL" in error_msg:
                        self.logger.error(f"Endpoint connection error for {current_model_id}: {error_msg}")
                        if "il-central-1" in error_msg:
                            return {"error": "Bedrock not available in il-central-1 region. Please use eu-central-1, us-east-1, or us-west-2"}
                        return {"error": f"Endpoint connection error: {error_msg}"}
                    elif "Input is too long" in error_msg or "ValidationException" in error_msg:
                        self.logger.warning(
                            f"Validation/input issue for model {current_model_id} ({error_msg[:200]}), trying next..."
                        )
                        continue
                    elif "ModelErrorException" in error_msg or "ThrottlingException" in error_msg or "ServiceUnavailableException" in error_msg or "InternalServerException" in error_msg:
                        # Transient/model-specific hiccups - AWS's own guidance is to just retry, so
                        # fail over to the next candidate instead of erroring out.
                        self.logger.warning(
                            f"Transient error for model {current_model_id} ({error_msg[:200]}), trying next..."
                        )
                        continue
                    else:
                        self.logger.error(f"Bedrock model invocation error for {current_model_id}:", ex)
                        return {"error": f"Bedrock error: {ex}"}
                except Exception as ex:
                    self.logger.error(f"Unexpected error during model invocation for {current_model_id}:", ex)
                    continue
            
            # If we get here, all models failed
            return {"error": "All available models failed - please check AWS Bedrock model access"}
            
        except Exception as ex:
            self.logger.error(f"Unexpected error during model invocation:", ex)
            return {"error": f"Unexpected error: {ex}"}

    def converse_with_tools(self, messages: list, system: str, tools: list,
                             model_id: str, fallback_model_ids: list = None,
                             max_tokens: int = 1500, temperature: float = 0.2) -> dict:
        """Bedrock Converse API call with tool-calling (toolConfig) support - distinct from
        invoke_model_async's raw InvokeModel path, since tool use needs the Converse API's
        structured message/toolUse/toolResult content blocks. Returns the assistant's message
        content blocks + stopReason so the caller can drive a tool-use loop (inspect stopReason
        == 'tool_use' vs 'end_turn')."""
        if not self.bedrockRuntime:
            self.logger.error("Bedrock runtime client not initialized")
            return {"error": "Bedrock runtime client not available - check AWS configuration"}

        models_to_try = []
        seen = set()
        for mid in [model_id] + list(fallback_model_ids or []):
            for variant in self._inference_profile_variants(mid):
                if variant not in seen:
                    seen.add(variant)
                    models_to_try.append(variant)

        tool_config = {"tools": tools} if tools else None

        for current_model_id in models_to_try:
            try:
                kwargs = dict(
                    modelId=current_model_id,
                    messages=messages,
                    inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
                )
                if system:
                    kwargs["system"] = [{"text": system}]
                if tool_config:
                    kwargs["toolConfig"] = tool_config

                response = self.bedrockRuntime.converse(**kwargs)

                usage = response.get('usage') or {}
                token_usage = {}
                if usage:
                    token_usage = {
                        'input_tokens': usage.get('inputTokens'),
                        'output_tokens': usage.get('outputTokens'),
                        'total_tokens': usage.get('totalTokens'),
                    }
                    self.logger.info(f"Token usage for model {current_model_id}: {token_usage}")

                output_message = response.get('output', {}).get('message', {})
                return {
                    "stopReason": response.get('stopReason'),
                    "message": output_message,
                    "model_id": current_model_id,
                    "token_usage": token_usage,
                }

            except (BotoCoreError, ClientError) as ex:
                error_msg = str(ex)
                if "AccessDeniedException" in error_msg:
                    self.logger.warning(f"Access denied for model {current_model_id}, trying next model...")
                    continue
                elif "ResourceNotFoundException" in error_msg:
                    self.logger.warning(f"Model unavailable for {current_model_id}, trying next model...")
                    continue
                elif "ValidationException" in error_msg:
                    self.logger.warning(f"Validation issue for model {current_model_id} ({error_msg[:200]}), trying next...")
                    continue
                elif "ModelErrorException" in error_msg or "ThrottlingException" in error_msg or "ServiceUnavailableException" in error_msg or "InternalServerException" in error_msg:
                    # Transient/model-specific hiccups (e.g. "Model produced invalid sequence as part of
                    # ToolUse") - AWS's own guidance is to just retry, so fail over instead of erroring out.
                    self.logger.warning(f"Transient error for model {current_model_id} ({error_msg[:200]}), trying next...")
                    continue
                else:
                    self.logger.error(f"Bedrock converse error for {current_model_id}:", ex)
                    return {"error": f"Bedrock error: {ex}"}
            except Exception as ex:
                self.logger.error(f"Unexpected error during converse for {current_model_id}:", ex)
                continue

        return {"error": "All available models failed - please check AWS Bedrock model access"}

if __name__ == '__main__':
    # Example usage of the new log_token_usage method
    print("BedrockClient with Token Usage Logging")
    print("=====================================")
    
    # Create a mock response to demonstrate token usage logging
    mock_response = {
        "ResponseMetadata": {
            "HTTPHeaders": {
                "x-amzn-bedrock-input-token-count": "150",
                "x-amzn-bedrock-output-token-count": "75",
                "x-amzn-bedrock-total-token-count": "225"
            }
        }
    }
    
    # Note: This is just a demonstration - in real usage, 
    # log_token_usage is called automatically by invoke_model_async
    print("\nExample response structure:")
    print(f"Input tokens: {mock_response['ResponseMetadata']['HTTPHeaders']['x-amzn-bedrock-input-token-count']}")
    print(f"Output tokens: {mock_response['ResponseMetadata']['HTTPHeaders']['x-amzn-bedrock-output-token-count']}")
    print(f"Total tokens: {mock_response['ResponseMetadata']['HTTPHeaders']['x-amzn-bedrock-total-token-count']}")
    
    print("\nTo test the full functionality, run: python test_token_usage_logging.py")