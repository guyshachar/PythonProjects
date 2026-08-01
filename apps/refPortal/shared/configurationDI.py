import os
from typing import Optional, Any

from shared.configManager import ConfigManager


def _normalize_eol_bedrock_model_id(model_id: Any, replacements: dict) -> Any:
    if model_id is None:
        return None
    s = str(model_id).strip()
    return replacements.get(s, model_id)


def _normalize_eol_bedrock_model_arn(arn: Any, replacements: dict) -> Any:
    if arn is None:
        return None
    s = str(arn)
    for old, new in replacements.items():
        if old in s:
            s = s.replace(old, new)
    return s


def _llm_source_raw(
    merged_file_config: dict,
    env_flat: dict,
    *,
    nested_key: str,
    env_key: Optional[str],
    default: Any = None,
):
    """
    Resolve one LLM-related value. Precedence: process env (env_key) >
    merged_file_config['LLM'][nested_key] > env JSON flat (env_key) > default.
    """
    if env_key is not None and os.environ.get(env_key) is not None:
        return os.environ.get(env_key)
    llm = merged_file_config.get('LLM')
    if isinstance(llm, dict) and nested_key in llm and llm[nested_key] is not None:
        return llm[nested_key]
    if env_key is not None:
        if env_key in env_flat:
            return env_flat.get(env_key)
        return default
    return default


def _bedrock_region_raw(merged_file_config: dict, env_flat: dict) -> str:
    """Bedrock region: env awsBedrockRegion > LLM.bedrock_region > env flat awsBedrockRegion > default."""
    if os.environ.get('awsBedrockRegion'):
        return os.environ.get('awsBedrockRegion')
    llm = merged_file_config.get('LLM')
    if isinstance(llm, dict) and llm.get('bedrock_region'):
        return str(llm.get('bedrock_region')).strip()
    return ConfigManager.get_env_value('awsBedrockRegion', env_flat, 'eu-central-1')


def _llm_bedrock_eol_model_id_replacements(merged_file_config: dict) -> dict:
    """
    Retired Bedrock foundation-model IDs → replacement (AWS stops accepting EOL modelId / ARN suffix).
    Defined under LLM.bedrockEolModelIdReplacements in config JSON.
    """
    llm = merged_file_config.get('LLM') if isinstance(merged_file_config.get('LLM'), dict) else {}
    raw = llm.get('bedrockEolModelIdReplacements')
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        if k is None or v is None:
            continue
        old = str(k).strip()
        new = str(v).strip()
        if not old or not new:
            continue
        out[old] = new
    return out


def _bedrock_model_candidates_list(
    merged_file_config: dict, env_flat: dict, bedrock_model_id, eol_replacements: dict
) -> list:
    """
    Ordered Bedrock foundation-model IDs for InvokeModel (primary first, then fallbacks).
    Override: env BEDROCK_MODEL_CANDIDATES=comma,separated,ids
    """
    env_csv = os.environ.get('BEDROCK_MODEL_CANDIDATES')
    if env_csv:
        out = [x.strip() for x in env_csv.split(',') if x.strip()]
        if out:
            return [_normalize_eol_bedrock_model_id(x, eol_replacements) for x in out]
        # Env set but empty / whitespace-only → fall through to LLM.bedrockModelCandidates in JSON
    llm = merged_file_config.get('LLM') if isinstance(merged_file_config.get('LLM'), dict) else {}
    raw = llm.get('bedrockModelCandidates')
    if isinstance(raw, list) and len(raw) > 0:
        out = [str(x).strip() for x in raw if x is not None and str(x).strip()]
        return [_normalize_eol_bedrock_model_id(x, eol_replacements) for x in out]
    if bedrock_model_id is not None and str(bedrock_model_id).strip():
        return [_normalize_eol_bedrock_model_id(str(bedrock_model_id).strip(), eol_replacements)]
    return []


def _llm_bedrock_truncate_model_token_limits(merged_file_config: dict) -> dict:
    """
    Substring keys matched against model_id (lowercased) -> conservative max input tokens for truncate_prompt.
    Defined under LLM.bedrockTruncateModelTokenLimits in config JSON.
    """
    llm = merged_file_config.get('LLM') if isinstance(merged_file_config.get('LLM'), dict) else {}
    raw = llm.get('bedrockTruncateModelTokenLimits')
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        if k is None:
            continue
        try:
            key = str(k).strip()
            if not key:
                continue
            out[key] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def build_config_di(merged_file_config: dict) -> dict:
    _file_env_values = merged_file_config.get('env', {})
    _eol_model_replacements = _llm_bedrock_eol_model_id_replacements(merged_file_config)
    _bedrock_model_id = _normalize_eol_bedrock_model_id(
        _llm_source_raw(
            merged_file_config,
            _file_env_values,
            nested_key='bedrockModelId',
            env_key='BEDROCK_MODEL_ID',
            default=None,
        ),
        _eol_model_replacements,
    )
    _bedrock_model_candidates = _bedrock_model_candidates_list(
        merged_file_config, _file_env_values, _bedrock_model_id, _eol_model_replacements
    )
    _bedrock_truncate_limits = _llm_bedrock_truncate_model_token_limits(merged_file_config)
    return {
        "app_env": ConfigManager.get_env_value('app_env', _file_env_values, 'dev'),
        "env": ConfigManager.get_env_value('app_env', _file_env_values, 'dev'),
        "app": ConfigManager.get_env_value('app', _file_env_values, 'APP'),
        "db": {"type": ConfigManager.get_env_value('db', _file_env_values, 'redis')},
        "APP_REPLICAS": ConfigManager.to_int(ConfigManager.get_env_value('APP_REPLICAS', _file_env_values, 1), 1),
        "REPLICA_SLOT": ConfigManager.to_int(ConfigManager.get_env_value('REPLICA_SLOT', _file_env_values, 1), 1),
        "generateReports": ConfigManager.to_bool(ConfigManager.get_env_value('generateReports', _file_env_values, 'False')),
        "mainInstance": ConfigManager.to_bool(ConfigManager.get_env_value('mainInstance', _file_env_values, 'False')),
        "loadInterval": ConfigManager.to_int(ConfigManager.get_env_value('loadInterval', _file_env_values, 10000), 10000),
        "swLevel": ConfigManager.get_env_value('swLevel', _file_env_values, 'debug'),
        "refereesPerRun": ConfigManager.to_int(ConfigManager.get_env_value('refereesPerRun', _file_env_values, 10), 10),
        "enableCronjobs": ConfigManager.to_bool(ConfigManager.get_env_value('enableCronjobs', _file_env_values, 'False')),
        "cronjobPollIntervalSeconds": ConfigManager.to_int(ConfigManager.get_env_value('cronjobPollIntervalSeconds', _file_env_values, 60), 60),
        "cronjobConfigFile": ConfigManager.get_env_value('cronjobConfigFile', _file_env_values, ''),
        "cronjobConfigFileContent": ConfigManager.get_env_value('cronjobConfigFileContent', _file_env_values, ''),
        "filteredTenantKeys": ConfigManager.get_env_value('filteredTenantKeys', _file_env_values, ''),
        "filteredMobileNos": ConfigManager.get_env_value('filteredMobileNos', _file_env_values, ''),
        "MY_DATA_FOLDER": ConfigManager.get_env_value('MY_DATA_FOLDER', _file_env_values, '/run/data/'),
        "BUILD_DATE": ConfigManager.get_env_value("BUILD_DATE", _file_env_values),
        "tenant": {
            "countryCode": ConfigManager.get_env_value('countryCode', _file_env_values),
            "eventType": ConfigManager.get_env_value('eventType', _file_env_values),
            "season": ConfigManager.get_env_value('season', _file_env_values)
        },
        "redis": {
            "host": ConfigManager.get_env_value('redisHost', _file_env_values, 'localhost'),
            "port": ConfigManager.to_int(ConfigManager.get_env_value('redisPort', _file_env_values, '6379'), '6379'),
            "db": ConfigManager.to_int(ConfigManager.get_env_value('redisDb', _file_env_values, 0), 0),
            "db2": ConfigManager.to_int(ConfigManager.get_env_value('redisDb2', _file_env_values, 1), 1)
        },
        "cache": {
            "host": ConfigManager.get_env_value('cacheRedisHost', _file_env_values, 'localhost'),
            "port": ConfigManager.to_int(ConfigManager.get_env_value('cacheRedisPort', _file_env_values, '6379'), '6379')
        },
        "aws": {
            "region": ConfigManager.get_env_value('awsRegion', _file_env_values, 'il-central-1'),
            "bedrock_region": _bedrock_region_raw(merged_file_config, _file_env_values),
            "dynamodb": {
                "endpointUrl": ConfigManager.get_env_value('dynamoDbEndpointUrl', _file_env_values)
            }
        },
        "postgres": {
            "host":       merged_file_config.get('postgres', {}).get('host',       'localhost'),
            "port":       ConfigManager.to_int(merged_file_config.get('postgres', {}).get('port', '5432'), 5432),
            "db":         merged_file_config.get('postgres', {}).get('db',         'postgres'),
            "user":       merged_file_config.get('postgres', {}).get('user',       'postgres'),
            "schema":     merged_file_config.get('postgres', {}).get('schema',     'public'),
            "sslmode":    merged_file_config.get('postgres', {}).get('sslmode',    'prefer'),
            "use_iam":    ConfigManager.to_bool(merged_file_config.get('postgres', {}).get('use_iam', 'False')),
            "secret_id":  merged_file_config.get('postgres', {}).get('secret_id',  'prod/refPortalSecret'),
            "secret_key": merged_file_config.get('postgres', {}).get('secret_key', 'postgres_password'),
            "ssh_host":   merged_file_config.get('postgres', {}).get('ssh_host',   ''),
            "ssh_user":   merged_file_config.get('postgres', {}).get('ssh_user',   'ec2-user'),
            "ssh_key":    merged_file_config.get('postgres', {}).get('ssh_key',    '~/.ssh/id_rsa'),
        },
        "LLM": {
            "enabled": ConfigManager.to_bool(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='enabled', env_key='LLM_ENABLED', default='False')
            ),
            "confidence_threshold": ConfigManager.to_float(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='confidence_threshold', env_key='LLM_CONFIDENCE_THRESHOLD', default=0.7),
                0.7,
            ),
            "max_tokens": ConfigManager.to_int(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='max_tokens', env_key='LLM_MAX_TOKENS', default='4000'),
                4000,
            ),
            "system_query_agent_max_tokens": ConfigManager.to_int(
                _llm_source_raw(
                    merged_file_config,
                    _file_env_values,
                    nested_key='system_query_agent_max_tokens',
                    env_key='SYSTEM_QUERY_AGENT_MAX_TOKENS',
                    default='1500',
                ),
                1500,
            ),
            "max_content_size": ConfigManager.to_int(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='max_content_size', env_key='LLM_MAX_CONTENT_SIZE', default='50000'),
                50000,
            ),
            "temperature": ConfigManager.to_float(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='temperature', env_key='LLM_TEMPERATURE', default=0.3),
                0.3,
            ),
            "schedule_agent_max_tokens": ConfigManager.to_int(
                _llm_source_raw(
                    merged_file_config,
                    _file_env_values,
                    nested_key='schedule_agent_max_tokens',
                    env_key='SCHEDULE_AGENT_MAX_TOKENS',
                    default='64',
                ),
                64,
            ),
            "schedule_agent_temperature": ConfigManager.to_float(
                _llm_source_raw(
                    merged_file_config,
                    _file_env_values,
                    nested_key='schedule_agent_temperature',
                    env_key='SCHEDULE_AGENT_TEMPERATURE',
                    default=0.0,
                ),
                0.0,
            ),
            "log_interactions": ConfigManager.to_bool(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='log_interactions', env_key='LLM_LOG_INTERACTIONS', default='False')
            ),
            "log_table": (
                f"{_llm_source_raw(merged_file_config, _file_env_values, nested_key='log_table', env_key='LLM_LOG_TABLE', default='llm_interactions')}_"
                f"{ConfigManager.get_env_value('app_env', _file_env_values, 'dev')}"
            ),
            "bedrockModelId": _bedrock_model_id,
            "bedrockModelArn": _normalize_eol_bedrock_model_arn(
                _llm_source_raw(
                    merged_file_config, _file_env_values, nested_key='bedrockModelArn', env_key='BEDROCK_MODEL_ARN', default=None
                ),
                _eol_model_replacements,
            ),
            "bedrockKbId": _llm_source_raw(
                merged_file_config, _file_env_values, nested_key='bedrockKbId', env_key='BEDROCK_KB_ID', default=None
            ),
            "use_cache": ConfigManager.to_bool(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='use_cache', env_key='LLM_USE_CACHE', default='False')
            ),
            "use_redis_cache": ConfigManager.to_bool(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='use_redis_cache', env_key='LLM_USE_REDIS_CACHE', default='False')
            ),
            "cache_ttl_seconds": ConfigManager.to_int(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='cache_ttl_seconds', env_key='LLM_CACHE_TTL_SECONDS', default='3600'),
                3600,
            ),
            "cache_max_size": ConfigManager.to_int(
                _llm_source_raw(merged_file_config, _file_env_values, nested_key='cache_max_size', env_key='LLM_CACHE_MAX_SIZE', default='10000'),
                10000,
            ),
            "bedrockModelCandidates": _bedrock_model_candidates,
            "bedrockEolModelIdReplacements": _eol_model_replacements,
            "bedrockTruncateModelTokenLimits": _bedrock_truncate_limits,
        },
        "adminMobile": ConfigManager.get_env_value('adminMobile', _file_env_values),
        "reviewerPairingSecret": ConfigManager.get_env_value('reviewerPairingSecret', _file_env_values),
        "reviewerDemoMobile": ConfigManager.get_env_value('reviewerDemoMobile', _file_env_values),
        "botMobileNumbers": ConfigManager.get_env_value('botMobileNumbers', _file_env_values),
        "botSignature": ConfigManager.get_env_value('botSignature', _file_env_values),
        "rootServiceUrlBase": ConfigManager.get_env_value('rootServiceUrlBase', _file_env_values),
        "docsServiceUrlBase": ConfigManager.get_env_value('docsServiceUrlBase', _file_env_values),
        "apiServiceUrlBase": ConfigManager.get_env_value('apiServiceUrlBase', _file_env_values),
        "concurrentPages": ConfigManager.to_int(ConfigManager.get_env_value('concurrentPages', _file_env_values, '4'), 4),
        "checkGames": ConfigManager.to_bool(ConfigManager.get_env_value('checkGames', _file_env_values, 'True')),
        "checkReviews": ConfigManager.to_bool(ConfigManager.get_env_value('checkReviews', _file_env_values, 'True')),
        "daysToArchive": ConfigManager.to_int(ConfigManager.get_env_value('daysToArchive', _file_env_values, '1'), 1),
        "approveGames": ConfigManager.to_bool(ConfigManager.get_env_value('approveGames', _file_env_values, 'False')),
        "avoidChatGroups": ConfigManager.to_bool(ConfigManager.get_env_value('avoidChatGroups', _file_env_values, 'True')),
        "chatGroups4Singles": ConfigManager.to_bool(ConfigManager.get_env_value('chatGroups4Singles', _file_env_values, 'False')),
        "addNonActiveRefereesToGroups": ConfigManager.to_bool(ConfigManager.get_env_value('addNonActiveRefereesToGroups', _file_env_values, 'False')),
        "alwaysCreateChatGroup": ConfigManager.to_bool(ConfigManager.get_env_value('alwaysCreateChatGroup', _file_env_values, 'False')),
        "fixChatGroups": ConfigManager.to_bool(ConfigManager.get_env_value('fixChatGroups', _file_env_values, 'False')),
        "mqttPublish": ConfigManager.to_bool(ConfigManager.get_env_value('mqttPublish', _file_env_values, 'False')),
        "fileVersion": ConfigManager.get_env_value('fileVersion', _file_env_values, 'v8'),
        "logLevel": ConfigManager.get_env_value('logLevel', _file_env_values, 'INFO'),
        "log2Console": ConfigManager.to_bool(ConfigManager.get_env_value('log2Console', _file_env_values, 'False')),
        "log2File": ConfigManager.to_bool(ConfigManager.get_env_value('log2File', _file_env_values, 'False')),
        "log2CW": ConfigManager.to_bool(ConfigManager.get_env_value('log2CW', _file_env_values, 'False')),
        "logDynamoDb": ConfigManager.to_bool(ConfigManager.get_env_value('logDynamoDb', _file_env_values, 'False')),
        "awsRegion": ConfigManager.get_env_value('awsRegion', _file_env_values, 'il-central-1'),
        "awsSecretName": ConfigManager.get_env_value('awsSecretName', _file_env_values),
        "awsBucketName": ConfigManager.get_env_value('awsBucketName', _file_env_values),
        "processUsingLambda": ConfigManager.to_bool(ConfigManager.get_env_value('processUsingLambda', _file_env_values, 'False')),
        "AWS_LAMBDA_FUNCTION_NAME": ConfigManager.get_env_value('AWS_LAMBDA_FUNCTION_NAME', _file_env_values, ''),
        "alwaysRenewPages": ConfigManager.to_bool(ConfigManager.get_env_value('alwaysRenewPages', _file_env_values, 'True')),
        "activeStatus": ConfigManager.get_env_value('activeStatus', _file_env_values, 'active'),
        "newRefStatus": ConfigManager.get_env_value('newRefStatus', _file_env_values, 'active'),
        "useGreenApiMessages": ConfigManager.get_env_value('useGreenApiMessages', _file_env_values, 'False'),
        "greenApiSupportWhatsapp": ConfigManager.get_env_value('greenApiSupportWhatsapp', _file_env_values),
        "greenApiUrlBase": ConfigManager.get_env_value('greenApiUrlBase', _file_env_values),
        "templateUrlPrefix": ConfigManager.get_env_value('templateUrlPrefix', _file_env_values),
        "twilioServiceUrlBase": ConfigManager.get_env_value('twilioServiceUrlBase', _file_env_values),
        "twilioApiGuid": ConfigManager.get_env_value('twilioApiGuid', _file_env_values),
        "twilioAddMedia": ConfigManager.to_bool(ConfigManager.get_env_value('twilioAddMedia', _file_env_values, 'False')),
        "twilioEnableStatucCallback": ConfigManager.to_bool(ConfigManager.get_env_value('twilioEnableStatucCallback', _file_env_values, 'False')),
        "twilioMenuContentSid": ConfigManager.get_env_value('twilioMenuContentSid', _file_env_values),
        "twilioOpenWindow": ConfigManager.get_env_value('twilioOpenWindow', _file_env_values),
        "twilioNewGameContentSid": ConfigManager.get_env_value('twilioNewGameContentSid', _file_env_values),
        "twilioGameUpdateContentSid1": ConfigManager.get_env_value('twilioGameUpdateContentSid1', _file_env_values),
        "twilioGameNoticeContentSid": ConfigManager.get_env_value('twilioGameNoticeContentSid', _file_env_values),
        "twilioNewReviewContentSid": ConfigManager.get_env_value('twilioNewReviewContentSid1', _file_env_values),
        "twilioReviewUpdateContentSid": ConfigManager.get_env_value('twilioReviewUpdateContentSid1', _file_env_values),
        "openWindowReminder": ConfigManager.to_int(ConfigManager.get_env_value('openWindowReminder', _file_env_values, '18'), 18),
        "openWindowLastReminder": ConfigManager.to_int(ConfigManager.get_env_value('openWindowLastReminder', _file_env_values, '22'), 22),
        "openWindowMessage": ConfigManager.get_env_value('openWindowMessage', _file_env_values, ''),
        "descopeProjectId": ConfigManager.get_env_value('descopeProjectId', _file_env_values),
        "timeout": ConfigManager.to_int(ConfigManager.get_env_value('timeout', _file_env_values, '5000'), 5000),
        "fontPath": ConfigManager.get_env_value('fontPath', _file_env_values),
        "MY_REFEREE_FOLDER": ConfigManager.get_env_value('MY_REFEREE_FOLDER', _file_env_values, '/tmp/'),
        "MY_CONFIG_FOLDER": ConfigManager.get_env_value('MY_CONFIG_FOLDER', _file_env_values, '/run/config/'),
        "MY_SECRET_FOLDER": ConfigManager.get_env_value('MY_SECRET_FOLDER', _file_env_values, './secret/'),
        "MY_SSL_FOLDER": ConfigManager.get_env_value('MY_SSL_FOLDER', _file_env_values, './ssl/'),
        "MY_LOG_FOLDER": ConfigManager.get_env_value('MY_LOG_FOLDER', _file_env_values, './logs/'),
        "MY_TMP_FOLDER": ConfigManager.get_env_value('MY_TMP_FOLDER', _file_env_values, './tmp/'),
        "MEDIA_STORAGE_PATH": ConfigManager.get_env_value('MEDIA_STORAGE_PATH', _file_env_values),
        "TRACKING_DATA_STORAGE_PATH": ConfigManager.get_env_value('TRACKING_DATA_STORAGE_PATH', _file_env_values),
        "limitPerMin": ConfigManager.to_int(ConfigManager.get_env_value('limitPerMin', _file_env_values, '10'), 10),
        "metaBaseUrl": ConfigManager.get_env_value('metaBaseUrl', _file_env_values),
        "metaVerifyToken": ConfigManager.get_env_value('metaVerifyToken', _file_env_values),
        "whatsappUrlBase": ConfigManager.get_env_value('whatsappUrlBase', _file_env_values),
        "brevoApiUrl": ConfigManager.get_env_value('brevoApiUrl', _file_env_values),
        "brevoSenderName": ConfigManager.get_env_value('brevoSenderName', _file_env_values),
        "brevoSenderEmail": ConfigManager.get_env_value('brevoSenderEmail', _file_env_values),
        "API_BASE_URL": ConfigManager.get_env_value('API_BASE_URL', _file_env_values),
        "PWA_BASE_URL": ConfigManager.get_env_value('PWA_BASE_URL', _file_env_values),
        "WSS_BASE_URL": ConfigManager.get_env_value('WSS_BASE_URL', _file_env_values),
        "IP_BLACKLIST": ConfigManager.get_env_value('IP_BLACKLIST', _file_env_values, ''),
        "chatGroupsToForward": ConfigManager.get_env_value('chatGroupsToForward', _file_env_values, ''),
        "formattedName": ConfigManager.get_env_value('formattedName', _file_env_values),
        "company": ConfigManager.get_env_value('company', _file_env_values),
        "emailAddress": ConfigManager.get_env_value('emailAddress', _file_env_values),
        "url": ConfigManager.get_env_value('url', _file_env_values),
        "eventType1": ConfigManager.get_env_value('eventType1', _file_env_values),
        "season": ConfigManager.get_env_value('season', _file_env_values),
        "processTimeout": ConfigManager.to_int(ConfigManager.get_env_value('processTimeout', _file_env_values, '30'), 30),
        "scheduleAgentEnabled": ConfigManager.to_bool(
            ConfigManager.get_env_value('scheduleAgentEnabled', _file_env_values, 'True')
        ),
        "systemQueryAgentEnabled": ConfigManager.to_bool(
            ConfigManager.get_env_value('systemQueryAgentEnabled', _file_env_values, 'True')
        ),
        "commuteRouteProvider": ConfigManager.get_env_value('commuteRouteProvider', _file_env_values, 'waze'),
        "browserHeadless": ConfigManager.to_bool(ConfigManager.get_env_value('browserHeadless', _file_env_values, 'True')),
        "tracing": ConfigManager.to_bool(ConfigManager.get_env_value('tracing', _file_env_values, 'False')),
        "skipCollectItemsForAssigner": ConfigManager.to_bool(ConfigManager.get_env_value('skipCollectItemsForAssigner', _file_env_values, 'False')),
        "TZ": ConfigManager.get_env_value('TZ', _file_env_values, 'UTC'),
        "domainUrlBase": ConfigManager.get_env_value('domainUrlBase', _file_env_values),
        "twilioQueueUrl": ConfigManager.get_env_value('twilioQueueUrl', _file_env_values),
        "twilioQueueMaxNumberOfMessages": ConfigManager.get_env_value('twilioQueueMaxNumberOfMessages', _file_env_values, '1'),
        "twilioQueueWaitTimeSeconds": ConfigManager.get_env_value('twilioQueueWaitTimeSeconds', _file_env_values, '20'),
        "buildDate": ConfigManager.get_env_value("BUILD_DATE", _file_env_values),
        "messaging": {
            "activeClient": ConfigManager.get_env_value('activeClient', _file_env_values, 'meta'),
            "useMessageTemplates": ConfigManager.to_bool(ConfigManager.get_env_value('useMessageTemplates', _file_env_values, 'True')),
            "twilio": {
                "useClient": ConfigManager.to_bool(ConfigManager.get_env_value('useTwilio', _file_env_values, 'False')),
                "from_mobile": ConfigManager.get_env_value('twilioFromMobile', _file_env_values),
                "service_id": ConfigManager.get_env_value('twilioServiceId', _file_env_values),
                "templates": {
                    "newGameMessageTemplate": ConfigManager.get_env_value('twilioNewGameMessageTemplate', _file_env_values),
                    "gameUpdateMessageTemplate": ConfigManager.get_env_value('twilioGameUpdateMessageTemplate', _file_env_values),
                    "gameNoticeMessageTemplate": ConfigManager.get_env_value('twilioGameNoticeMessageTemplate', _file_env_values),
                    "menuMessageTemplate": ConfigManager.get_env_value('twilioMenuMessageTemplate', _file_env_values),
                    "onBoardingActivateMessageTemplate": ConfigManager.get_env_value('twilioOnBoardingActivateMessageTemplate', _file_env_values),
                    "onBoardingJoinConfirmationMessageTemplate": ConfigManager.get_env_value('twilioOnBoardingJoinConfirmationMessageTemplate', _file_env_values),
                    "onBoardingRegistrationMessageTemplate": ConfigManager.get_env_value('twilioOnBoardingRegistrationMessageTemplate', _file_env_values)
                }
            },
            "green_api": {
                "useClient": ConfigManager.to_bool(ConfigManager.get_env_value('useGreenApi', _file_env_values, 'False')),
                "from_mobile": ConfigManager.get_env_value('greenApiFromMobile', _file_env_values),
                "instance_id": ConfigManager.get_env_value('greenApiInstanceId', _file_env_values),
                "templates": {
                    "newGameMessageTemplate": ConfigManager.get_env_value('greenApiNewGameMessageTemplate', _file_env_values),
                    "gameUpdateMessageTemplate": ConfigManager.get_env_value('greenApiGameUpdateMessageTemplate', _file_env_values),
                    "gameNoticeMessageTemplate": ConfigManager.get_env_value('greenApiGameNoticeMessageTemplate', _file_env_values),
                    "menuMessageTemplate": ConfigManager.get_env_value('greenApiMenuMessageTemplate', _file_env_values),
                    "onBoardingActivateMessageTemplate": ConfigManager.get_env_value('greenApiOnBoardingActivateMessageTemplate', _file_env_values),
                    "onBoardingJoinConfirmationMessageTemplate": ConfigManager.get_env_value('greenApiOnBoardingJoinConfirmationMessageTemplate', _file_env_values),
                    "onBoardingRegistrationMessageTemplate": ConfigManager.get_env_value('greenApiOnBoardingRegistrationMessageTemplate', _file_env_values)
                }
            },
            "meta": {
                "useClient": ConfigManager.to_bool(ConfigManager.get_env_value('useMeta', _file_env_values, 'False')),
                "from_mobile": ConfigManager.get_env_value('metaFromMobile', _file_env_values),
                "base_url": ConfigManager.get_env_value('metaBaseUrl', _file_env_values),
                "api_version": ConfigManager.get_env_value('metaApiVersion', _file_env_values),
                "phone_number_id": ConfigManager.get_env_value('metaPhoneNumberId', _file_env_values),
                "whatsapp_business_account_id": ConfigManager.get_env_value('metaWhatsappBusinessAccountId', _file_env_values),
                "templates": {
                    "newGameMessageTemplate": ConfigManager.get_env_value('metaNewGameMessageTemplate', _file_env_values),
                    "gameUpdateMessageTemplate": ConfigManager.get_env_value('metaGameUpdateMessageTemplate', _file_env_values),
                    "gameNoticeMessageTemplate": ConfigManager.get_env_value('metaGameNoticeMessageTemplate', _file_env_values),
                    "menuMessageTemplate": ConfigManager.get_env_value('metaMenuMessageTemplate', _file_env_values),
                    "onBoardingActivateMessageTemplate": ConfigManager.get_env_value('metaOnBoardingActivateMessageTemplate', _file_env_values),
                    "onBoardingJoinConfirmationMessageTemplate": ConfigManager.get_env_value('metaOnBoardingJoinConfirmationMessageTemplate', _file_env_values),
                    "onBoardingRegistrationMessageTemplate": ConfigManager.get_env_value('metaOnBoardingRegistrationMessageTemplate', _file_env_values),
                    "openWindowMessageTemplate": ConfigManager.get_env_value('metaOpenWindowMessageTemplate', _file_env_values),
                    "gamePortalCodeMessageTemplate": ConfigManager.get_env_value('metaGamePortalCodeMessageTemplate', _file_env_values),
                    "loginOtpMessageTemplate": ConfigManager.get_env_value('metaLoginOtpMessageTemplate', _file_env_values)
                }
            },
            "manychat": {
                "useClient": ConfigManager.to_bool(ConfigManager.get_env_value('useManychat', _file_env_values, 'False')),
                "from_mobile": ConfigManager.get_env_value('manychatFromMobile', _file_env_values),
            },
            "telegram": {
                "username": ConfigManager.get_env_value('telegramUsername', _file_env_values, ''),
                "useClient": ConfigManager.to_bool(ConfigManager.get_env_value('useTelegram', _file_env_values, 'False')),
                "from_mobile": ConfigManager.get_env_value('telegramFromMobile', _file_env_values, ''),
            }
        },
        "mapConfig": {
            'IL': {
                'handball': {
                    'games': {
                        'פרטים נוספים': 'additionalDetails',
                        'תאריך': 'dateText',
                        'יום': 'dow',
                        'משחק': 'gameTitle',
                        'קבוצה מארחת': 'homeTeamName',
                        'קבוצה אורחת': 'guestTeamName',
                        'מסגרת': 'tournamentName',
                        'שעת משחק': 'gameTime',
                        'תאריך משחק': 'gameDate',
                        'מחזור': 'fixture',
                        'אולם': 'field',
                        'סטטוס': 'status',
                        'תפקיד': 'role',
                        '* שם': '* name',
                        '* סטטוס': '* status',
                        '* דרג': '* level',
                        '* טלפון': '* phone',
                        '* כתובת': '* address',
                    },
                },
                'football': {
                    'games': {
                        'תאריך': 'dateText',
                        'יום': 'dow',
                        'מסגרת משחקים': 'tournamentName',
                        'משחק': 'gameTitle',
                        'סבב': 'round',
                        'מחזור': 'fixture',
                        'מגרש': 'field',
                        'סטטוס': 'status',
                        'תפקיד': 'role',
                        'מבקר': 'reviewer',
                        '* שם': '* name',
                        '* סטטוס': '* status',
                        '* דרג': '* level',
                        '* טלפון': '* phone',
                        '* כתובת': '* address',
                        'הערה': 'comment',
                    },
                    'reviews': {
                        'מס.': 'no.',
                        'תאריך': 'dateText',
                        'שעה': 'timeText',
                        'מסגרת משחקים': 'tournamentName',
                        'משחק': 'gameTitle',
                        'מגרש': 'field',
                        'מחזור': 'fixture',
                        'תפקיד במגרש': 'role',
                        'מבקר': 'reviewer',
                        'ציון': 'reviewGrade',
                    },
                    'gamesReports': {
                        'תאריך': 'dateText',
                        'מסגרת משחקים': 'tournamentName',
                        'קבוצה ביתית קבוצה אורחת': 'gameTitle',
                        'מח.': 'fixture',
                        'מגרש': 'field',
                        'סטטוס': 'status',
                    },
                }
            }
        },
        "cronjobs": ConfigManager.get_config_value(merged_file_config, 'cronjobs', {})
    }


_merged_file_config = ConfigManager.get_merged_file_config()
configDI = build_config_di(_merged_file_config)

_registered_container = None


def register_config_container(container):
    """DI container whose Configuration provider receives from_dict on merged-config reload."""
    global _registered_container
    _registered_container = container


def apply_merged_to_flat_di(merged_file_config: dict) -> dict:
    """Rebuild module-level flat configDI from merged JSON (no disk read)."""
    global configDI
    new_di = build_config_di(merged_file_config)
    configDI = new_di
    return new_di


def push_flat_config_to_container(flat: dict) -> None:
    if _registered_container is not None:
        _registered_container.config.from_dict(flat)


def subscribe_merged_config_changes(after_reload=None, debounce_seconds=0.75, logger=None):
    """
    Subscribe to ConfigManager config file watcher: reload merged JSON in ConfigManager, then
    rebuild flat configDI, push to registered container, optional after_reload(new_di, file_path, fname).
    """
    def _on_merged(merged, file_path, fname):
        new_di = apply_merged_to_flat_di(merged)
        push_flat_config_to_container(new_di)
        if after_reload is not None:
            after_reload(new_di, file_path, fname)

    ConfigManager.subscribe_config_changes(_on_merged, debounce_seconds=debounce_seconds, logger=logger)


def get_flat_config():
    """Current flat DI dict (same object pushed to the container after reload)."""
    return configDI