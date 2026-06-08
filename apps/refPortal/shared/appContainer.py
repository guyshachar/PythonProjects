from dependency_injector import containers, providers
from typing import Union, TypeVar
import boto3
import redis
import os
# Add the parent directory to sys.path to allow imports from shared
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
# Import your application's classes
from shared.logger import Logger
from shared.messaging import MessagingService, GreenApiClient, TwilioClient, MetaClient, ManychatClient, TelegramClient
from shared.db import RedisClient, DynamodbClient, DbClientBase, CacheService
from shared.handleUsers import HandleUsers
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from shared.dockerClient import DockerClient
from shared.refereeProcessService import RefereeProcessService
import shared.helpers as helpers
from shared.commonHelper import CommonHelper
from shared.orgRelated import MultiTenantSupport, IFAService, IHAService, OrgServiceFactory
from rpApi.pollService import PollService
from shared.commute_service import CommuteService

# Define a type variable for database clients
DbClientType = TypeVar('DbClientType', bound=DbClientBase)

class AppContainer(containers.DeclarativeContainer):
    """
    The central dependency injection container for the application.
    """
    # Dynamic browser actions factory based on config
    tenantServices = {}
    def create_tenant_services(config, logger, multiTenantSupport, cacheService, handleUsers, messagingService):
        tenantServices = {}
        """Create tenants instance based on config."""
        # Handle both dict and object config formats
        if isinstance(config, dict):
            countryCode = config.get('tenant', {}).get('countryCode')
            eventType = config.get('tenant', {}).get('eventType')
        else:
            countryCode = config.tenant.countryCode
            eventType = config.tenant.eventType

        tenants = cacheService.getTenants()
        for tenantKey, tenant in tenants.items():
            if tenant['countryCode'] == 'IL' and tenant['eventType'] == 'football':
                try:
                    tenantServices[tenantKey] = IFAService(
                        logger=logger,
                        multiTenantSupport=multiTenantSupport,
                        cacheService=cacheService,
                        handleUsers=handleUsers,
                        messagingService=messagingService,
                    )
                except ImportError as e:
                    print(f"Warning: Could not import IFAService:", e)
            elif countryCode == 'IL' and eventType == 'handball':
                try:
                    tenantServices[tenantKey] = IHAService(
                        logger=logger,
                        multiTenantSupport=multiTenantSupport,
                        cacheService=cacheService,
                        handleUsers=handleUsers,
                        messagingService=messagingService,
                    )
                except ImportError as e:
                    print(f"Warning: Could not import IHAService:", e)
        return tenantServices
    
    config = providers.Configuration()

    # --- Core Services ---

    logger = providers.Factory(
        Logger,
        config=config,
    )
    
    # DynamoDB clients
    dynamodb_resource = providers.Singleton(
        lambda region, endpoint_url: boto3.resource(
            "dynamodb",
            region_name=region,
            endpoint_url=endpoint_url
        ),
        region=config.aws.region,
        endpoint_url=config.aws.dynamodb_endpoint_url
    )

    dynamodb_client = providers.Singleton(
        lambda region, endpoint_url: boto3.client(
            "dynamodb",
            region_name=region,
            endpoint_url=endpoint_url
        ),
        region=config.aws.region,
        endpoint_url=config.aws.dynamodb_endpoint_url
    )

    # Redis client
    redis_client = providers.Singleton(
        lambda host, port, db: redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True
        ),
        host=config.redis.host,
        port=config.redis.port,
        db=config.redis.db
    )

    # --- Database Clients (using a Selector) ---

    redis_db_client = providers.Singleton(
        RedisClient,
        env=config.env,
        logger=logger,
        client=redis_client,
    )

    dynamodb_db_client = providers.Singleton(
        DynamodbClient,
        env=config.env,
        logger=logger,
        dynamodbResource=dynamodb_resource,
        dynamodbClient=dynamodb_client,
    )

    # Type-annotated Selector that returns a DbClient
    db_client: providers.Provider[DbClientType] = providers.Selector(
        config.db.type,
        redis=redis_db_client,
        dynamodb=dynamodb_db_client,
    )

    multi_tenant_support = providers.Singleton(
        MultiTenantSupport,
        logger=logger,
        dbClient=db_client,
        mapConfig=config.mapConfig,
    )

    # --- Cache Service ---

    # Redis cache client
    redis_cache_client = providers.Singleton(
        lambda host, port, db: redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True
        ),
        host=config.cache.host,
        port=config.cache.port,
        db=config.redis.db
    )

    cache_service = providers.Singleton(
        CacheService,
        logger=logger,
        dbClient=db_client,
        redisCacheClient=redis_cache_client,
        multiTenantSupport=multi_tenant_support,
    )

    # --- Business Logic / Handlers ---

    handle_users = providers.Singleton(
        HandleUsers,
        logger=logger,
        cacheService=cache_service,
    )

    referees_data = providers.Callable(
        lambda handle_users: (
            handle_users.globalRefereesByMobile,
            handle_users.refereesByRefId,
            handle_users.refereesByMobile,
            handle_users.refereesByGuid,
            handle_users.globalRefereesByName
        ),
        handle_users=handle_users
    )

    # --- Messaging Clients ---
    
    # GreenApi Client
    green_api_client = providers.Singleton(
        GreenApiClient,
        logger=logger,
        cacheService=cache_service,
        greenApiInstanceId=config.messaging.green_api.instance_id,
        fromMobile=config.messaging.green_api.from_mobile,
        useClient=config.messaging.green_api.useClient
    )

    # Twilio Client
    twilio_client = providers.Singleton(
        TwilioClient,
        logger=logger,
        cacheService=cache_service,
        twilioServiceId=config.messaging.twilio.service_id,
        fromMobile=config.messaging.twilio.from_mobile,
        useClient=config.messaging.twilio.useClient
    )

    # Meta Client
    meta_client = providers.Singleton(
        MetaClient,
        logger=logger,
        cacheService=cache_service,
        apiVersion=config.messaging.meta.api_version,
        fromPhoneNumberId=config.messaging.meta.phone_number_id,
        whatsappBusinessAccountId=config.messaging.meta.whatsapp_business_account_id,
        fromMobile=config.messaging.meta.from_mobile,
        useClient=config.messaging.meta.useClient
    )

    # ManyChat Client
    manychat_client = providers.Singleton(
        ManychatClient,
        logger=logger,
        cacheService=cache_service,
        fromMobile=config.messaging.manychat.from_mobile,
        useClient=config.messaging.manychat.useClient
    )

    # Telegram Client (optional; set config.messaging.telegram.useClient and telegram_bot_token for webhook)
    telegram_client = providers.Singleton(
        TelegramClient,
        logger=logger,
        cacheService=cache_service,
        username=config.messaging.telegram.username,
        fromMobile=config.messaging.telegram.from_mobile,
        useClient=config.messaging.telegram.useClient,
    )

    # Message Templates (selected based on active client)
    twilio_templates = providers.Callable(
        lambda newGameMessageTemplate, gameUpdateMessageTemplate, gameNoticeMessageTemplate, menuMessageTemplate, onBoardingActivateMessageTemplate, onBoardingJoinConfirmationMessageTemplate, onBoardingRegistrationMessageTemplate: {
            'newGame': newGameMessageTemplate,  # Meta template name
            'gameUpdate': gameUpdateMessageTemplate,
            'gameNotice': gameNoticeMessageTemplate,
            'menu': menuMessageTemplate,
            'onBoardingActivate': onBoardingActivateMessageTemplate,
            'onBoardingJoinConfirmation': onBoardingJoinConfirmationMessageTemplate,
            'onBoardingRegistration': onBoardingRegistrationMessageTemplate
        },
        newGameMessageTemplate=config.messaging.twilio.templates.newGameMessageTemplate,
        gameUpdateMessageTemplate=config.messaging.twilio.templates.gameUpdateMessageTemplate,
        gameNoticeMessageTemplate=config.messaging.twilio.templates.gameNoticeMessageTemplate,
        menuMessageTemplate=config.messaging.twilio.templates.menuMessageTemplate,
        onBoardingActivateMessageTemplate=config.messaging.twilio.templates.onBoardingActivateMessageTemplate,
        onBoardingJoinConfirmationMessageTemplate=config.messaging.twilio.templates.onBoardingJoinConfirmationMessageTemplate,
        onBoardingRegistrationMessageTemplate=config.messaging.twilio.templates.onBoardingRegistrationMessageTemplate
    )

    meta_templates = providers.Callable(
        lambda newGameMessageTemplate, gameUpdateMessageTemplate, gameNoticeMessageTemplate, menuMessageTemplate, onBoardingActivateMessageTemplate, onBoardingJoinConfirmationMessageTemplate, onBoardingRegistrationMessageTemplate, openWindowMessageTemplate, gamePortalCodeMessageTemplate: {
            'newGame': newGameMessageTemplate,  # Meta template name
            'gameUpdate': gameUpdateMessageTemplate,
            'gameNotice': gameNoticeMessageTemplate,
            'menu': menuMessageTemplate,
            'onBoardingActivate': onBoardingActivateMessageTemplate,
            'onBoardingJoinConfirmation': onBoardingJoinConfirmationMessageTemplate,
            'onBoardingRegistration': onBoardingRegistrationMessageTemplate,
            'openWindow': openWindowMessageTemplate,
            'gamePortalCode': gamePortalCodeMessageTemplate
        },
        newGameMessageTemplate=config.messaging.meta.templates.newGameMessageTemplate,
        gameUpdateMessageTemplate=config.messaging.meta.templates.gameUpdateMessageTemplate,
        gameNoticeMessageTemplate=config.messaging.meta.templates.gameNoticeMessageTemplate,
        menuMessageTemplate=config.messaging.meta.templates.menuMessageTemplate,
        onBoardingActivateMessageTemplate=config.messaging.meta.templates.onBoardingActivateMessageTemplate,
        onBoardingJoinConfirmationMessageTemplate=config.messaging.meta.templates.onBoardingJoinConfirmationMessageTemplate,
        onBoardingRegistrationMessageTemplate=config.messaging.meta.templates.onBoardingRegistrationMessageTemplate,
        openWindowMessageTemplate=config.messaging.meta.templates.openWindowMessageTemplate,
        gamePortalCodeMessageTemplate=config.messaging.meta.templates.gamePortalCodeMessageTemplate
    )

    manychat_templates = providers.Callable(
        lambda config: {
            'newGame': config.messaging.manychat.templates.newGameMessageTemplate,  # ManyChat flow name
            'gameUpdate': config.messaging.manychat.templates.gameUpdateMessageTemplate,
            'gameNotice': config.messaging.manychat.templates.gameNoticeMessageTemplate,
            'menu': config.messaging.manychat.templates.menuMessageTemplate,
            'onBoardingActivate': config.messaging.manychat.templates.onBoardingActivateMessageTemplate,
            'onBoardingJoinConfirmation': config.messaging.manychat.templates.onBoardingJoinConfirmationMessageTemplate,
            'onBoardingRegistration': config.messaging.manychat.templates.onBoardingRegistrationMessageTemplate
        },
        config=config
    )

    # Template selector based on active client
    message_templates = providers.Selector(
        config.messaging.activeClient,
        twilio=twilio_templates,
        #greenapi=None,
        meta=meta_templates,
        manychat=manychat_templates
    )

    common_helper = providers.Singleton(
        CommonHelper,
        logger=logger,
        multiTenantSupport=multi_tenant_support,
        cacheService=cache_service,
    )
    
    messaging_service = providers.Singleton(
        MessagingService,
        logger=logger,
        config=config,
        cacheService=cache_service,
        commonHelper=common_helper,
        referees_data=referees_data,
        activeClient=config.messaging.activeClient,
        twilioClient=twilio_client,
        greenApiClient=green_api_client,
        metaClient=meta_client,
        manychatClient=manychat_client,
        telegramClient=telegram_client,
        useMessageTemplates=config.messaging.useMessageTemplates,
        messageTemplates=message_templates
    )

    orgServiceFactory = providers.Singleton(
        OrgServiceFactory,
        logger=logger,
        multiTenantSupport=multi_tenant_support,
        cacheService=cache_service,
        handleUsers=handle_users,
        messagingService=messaging_service
    )
    
    handle_tournaments = providers.Singleton(
        HandleTournaments,
        logger=logger,
        cacheService=cache_service,
        commonHelper=common_helper,
        orgServiceFactory=orgServiceFactory,
        messagingService=messaging_service,
    )

    handle_referee_data = providers.Singleton(
        HandleRefereeData,
        logger=logger,
        cacheService=cache_service,
        commonHelper=common_helper,
        messagingService=messaging_service,
        handleUsers=handle_users,
        referees_data=referees_data
    )

    docker_client = providers.Singleton(
        DockerClient,
        logger=logger,
    )

    poll_service = providers.Singleton(
        PollService,
        logger=logger,
        cacheService=cache_service,
        messagingService=messaging_service
    )

    commute_service = providers.Singleton(
        lambda _logger: CommuteService(
            logger=_logger,
            google_maps_api_key_server=helpers.get_secret('google_maps_api_key_server'),
        ),
        _logger=logger,
    )

    # Bedrock client - Removed from container, now lazy-loaded in RefPortalImplementationApi

    # LLM Webhook Integration - Removed from container, now lazy-loaded in RefPortalImplementationApi
    # LLM Webhook Handler - Removed from container, now lazy-loaded in RefPortalImplementationApi

    # LLM Response Cache (Redis-based)
    llm_response_cache = providers.Singleton(
        lambda logger, redis_client, config: (
            __import__('rpApi.llm_response_cache', fromlist=['LLMResponseCache']).LLMResponseCache(
                logger=logger,
                redis_client=redis_client,
                ttl_seconds=config.get('LLM', {}).get('cache_ttl_seconds', 3600),
                max_cache_size=config.get('LLM', {}).get('cache_max_size', 10000)
            ) if config.get('LLM', {}).get('use_redis_cache', True) else None
        ),
        logger=logger,
        redis_client=redis_client,
        config=config
    )

    # In-Memory LLM Response Cache
    in_memory_llm_response_cache = providers.Singleton(
        lambda logger, config: (
            __import__('rpApi.llm_response_cache', fromlist=['InMemoryLLMResponseCache']).InMemoryLLMResponseCache(
                logger=logger,
                ttl_seconds=config.get('LLM', {}).get('cache_ttl_seconds', 3600),
                max_cache_size=config.get('LLM', {}).get('cache_max_size', 1000)
            ) if not config.get('LLM', {}).get('use_redis_cache', True) else None
        ),
        logger=logger,
        config=config
    )

    # Active LLM Response Cache (chooses between Redis and In-Memory)
    active_llm_response_cache = providers.Singleton(
        lambda llm_response_cache, in_memory_llm_response_cache, config: (
            llm_response_cache if config.get('LLM', {}).get('use_redis_cache', True) else in_memory_llm_response_cache
        ),
        llm_response_cache=llm_response_cache,
        in_memory_llm_response_cache=in_memory_llm_response_cache,
        config=config
    )

    # LLM Enhancer - Removed from container, now lazy-loaded in RefPortalImplementationApi

    referee_process_service = providers.Singleton(
        RefereeProcessService,
        logger=logger,
        commonHelper=common_helper,
        cacheService=cache_service,
        multiTenantSupport=multi_tenant_support,
        messagingService=messaging_service,
        handleTournaments=handle_tournaments,
        handleRefereeData=handle_referee_data,
        handleUsers=handle_users,
        referees_data=referees_data,
        orgServiceFactory=orgServiceFactory,
        commuteService=commute_service,
        config=config,
    )

    # --- AWS Clients ---
    aws_sqs_client = providers.Singleton(
        lambda region: boto3.client('sqs', region_name=region),
        region=config.aws.region
    )

    aws_s3_client = providers.Singleton(
        lambda: boto3.client('s3')
    )

    # --- Main Application Logic ---
    if eval(os.getenv('useApi', 'False')) == True:
        from rpApi.refPortalImplementationApiDI import RefPortalImplementationApi
        
        ref_portal_implementation = providers.Factory(
            RefPortalImplementationApi,
            logger=logger,
            cacheService=cache_service,
            messagingService=messaging_service,
            handleUsers=handle_users,
            handleTournaments=handle_tournaments,
            handleRefereeData=handle_referee_data,
            dockerClient=providers.Callable(
                lambda is_lambda, docker_client: None if is_lambda else docker_client(),
                is_lambda=providers.Callable(helpers.isRunningInLambda),
                docker_client=docker_client
            ),
            orgServiceFactory=orgServiceFactory,
            pollService=poll_service,
            llm_response_cache=active_llm_response_cache,
            refereeProcessService=referee_process_service,
            commuteService=commute_service,
            awsSqsClient=aws_sqs_client,
            awsS3Client=aws_s3_client,
            referees_data=referees_data,
            config=config,
        )

    def init_resources(self):
        """
        Initialize application resources.
        This method is called during application startup.
        """
        try:
            # Initialize the logger first
            self.logger.info("Initializing application resources...")
            
            # Initialize database connections
            dbClient = self.db_client()
            self.logger.info("Database client initialized")
            
            # Initialize other resources as needed
            self.logger.info("Application resources initialized successfully")
        except Exception as e:
            self.logger.error(f"ERROR: Failed to initialize resources:", e)
            raise

    def shutdown_resources(self):
        """
        Shutdown application resources gracefully.
        This method is called during application shutdown.
        """
        try:
            self.logger.info("Shutting down application resources...")
            
            # Close database connections
            dbClient = self.db_client()
            if hasattr(dbClient, 'close'):
                dbClient.close()
            
            self.logger.info("Application resources shut down successfully")
        except Exception as e:
            self.logger.error(f"ERROR: Failed to shutdown resources:", e)

    def getAppContainer():
        import shared.configurationDI as configDI
        container = AppContainer()
        container.config.from_dict(configDI.configDI)
        container.init_resources()    
        return container     