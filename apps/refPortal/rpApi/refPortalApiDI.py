from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
#from mangum import Mangum
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import logging
import os
import time
from pathlib import Path
import sys
from contextlib import asynccontextmanager
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.appContainer import AppContainer
from rpApi.middlewares.middlewares import LogRequestsAndCorsMiddleware, ProcessTimeMiddleware, SwarmProxyHeadersMiddleware, IpBlacklistMiddleware
from rpApi.middlewares.jwtMiddleware import JWTMiddleware, JwtTokenService
from rpApi.middlewares.authMiddleware import AuthMiddleware
from rpApi.endpoints.chat_api import chat_router
from rpApi.endpoints.auth import auth_router
import shared.helpers as helpers
import shared.configurationDI as configDI

# Throttle slowapi "ratelimit exceeded" logs to avoid endless spam (one per 60s per endpoint+key)
_RATELIMIT_LOG_THROTTLE_SEC = 60
_ratelimit_log_last: dict = {}


def _get_real_client_ip(request):
    """
    Extract the real client IP when running behind reverse proxies/load balancers.
    Falls back to slowapi default behavior when forwarding headers are missing.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return get_remote_address(request)

class _RatelimitLogThrottleFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if "exceeded at endpoint" not in (record.msg or ""):
            return True
        args = getattr(record, "args", None)
        key = (args[2], args[1]) if args and len(args) >= 3 else id(record)  # endpoint_scope, limit_key (e.g. IP)
        now = time.monotonic()
        last = _ratelimit_log_last.get(key, 0)
        if now - last >= _RATELIMIT_LOG_THROTTLE_SEC:
            _ratelimit_log_last[key] = now
            if len(_ratelimit_log_last) > 200:
                _ratelimit_log_last.clear()
            return True
        return False

def _throttle_ratelimit_logs():
    slowapi_logger = logging.getLogger("slowapi")
    slowapi_logger.addFilter(_RatelimitLogThrottleFilter())

class RefPortalApi():
    def __init__(self):
    # Create the container instance globally so it can be used in the lifespan event
        self.container = AppContainer()

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """
        Manages application startup and shutdown events.
        This is the recommended way to handle resource lifecycle.
        """
        try:
            self.logger.info("INFO: Lifespan startup event...")

            # Initialize resources like the referee data cache on startup
            self.container.init_resources()
            yield
        except Exception as ex:
            print(f"ERROR: Lifespan startup failed: {ex}")
            # Fallback: initialize resources directly
            try:
                self.container.init_resources()
            except Exception as fallback_error:
                self.logger.error(f"ERROR: Fallback initialization failed: {fallback_error}")
            yield
        finally:
            # Shutdown resources gracefully on application exit
            try:
                self.logger.info("INFO: Lifespan shutdown event...")
                self.container.shutdown_resources()
            except Exception as ex:
                self.logger.error(f"ERROR: Lifespan shutdown failed: {ex}")
    
    def create_app(self) -> FastAPI:
        """
        Alternative application factory function that doesn't use lifespan protocol.
        Use this if the ASGI server doesn't support lifespan.
        """
        # Load configuration from environment variables
        self.container.config.from_dict(configDI.configDI)

        # Initialize resources directly
        self.container.init_resources()

        # Get the fully constructed implementation instance from the container
        self.impl = self.container.ref_portal_implementation()
        self.logger = self.impl.logger
        self.cacheService = self.impl.cacheService
        self.messageService = self.impl.messagingService
        
        # Create the FastAPI app without lifespan
        self.app = FastAPI(root_path="")

        redisHost = os.getenv('cacheRedisHost', 'localhost')
        redisPort = int(os.getenv('cacheRedisPort', '6379'))

        # IP blacklist: runs first; set env IP_BLACKLIST (comma-separated IPs) to block
        self.app.add_middleware(IpBlacklistMiddleware, logger=self.logger)

        limiter = Limiter(
            key_func=_get_real_client_ip,
            storage_uri=f"redis://{redisHost}:{redisPort}",
            default_limits=["60/minute"]
        )
        self.app.state.limiter = limiter
        self.app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        # Throttle slowapi "ratelimit exceeded" logs to at most once per 60s per endpoint+key (avoids endless log spam)
        _throttle_ratelimit_logs()
        self.app.add_middleware(
            SlowAPIMiddleware
        )

        # Get environment-specific CORS origins
        cors_origins = self._get_cors_origins()
        self.logger.info(f"🌐 CORS Origins configured: {cors_origins}")

        '''
        self.app.add_middleware(
            ProcessTimeMiddleware,
            logger=self.logger
        )
        '''

        # Add request logging and CORS headers middleware FIRST (so it executes last)
        self.app.add_middleware(
            LogRequestsAndCorsMiddleware,
            logger=self.logger,
            cors_origins_func=self._get_cors_origins
        )
        
        # Add CORS middleware SECOND (so it executes second to last)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,        # Allows cookies/authentication headers
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # Explicit methods
            allow_headers=["*"],           # Allows all headers
            expose_headers=["*"])

        # Add global OPTIONS handler for CORS preflight requests
        @self.app.options("/{full_path:path}")
        async def options_handler(request):
            origin = request.headers.get('origin', 'unknown')
            self.logger.info(f"🔄 CORS OPTIONS request: {request.url.path} from {origin}")
            return {"message": "OK"}
        
        # Add CORS test endpoint
        @self.app.get("/api/cors-test")
        async def cors_test(request):
            origin = request.headers.get('origin', 'no-origin')
            self.logger.info(f"🧪 CORS test request from: {origin}")
            return {
                "message": "CORS test successful",
                "origin": origin,
                "timestamp": helpers.localNow().isoformat()
            }
        
        # Add global exception handler
        @self.app.exception_handler(Exception)
        async def global_exception_handler(request, ex):
            # Safely get request info
            try:
                method = getattr(request, 'method', 'UNKNOWN')
                path = getattr(request.url, 'path', 'UNKNOWN') if hasattr(request, 'url') and request.url else 'UNKNOWN'
                origin = request.headers.get('origin', 'no-origin') if hasattr(request, 'headers') else 'no-origin'
            except Exception:
                method = 'UNKNOWN'
                path = 'UNKNOWN'
                origin = 'no-origin'
            
            try:
                self.logger.error(f"❌ Global exception handler: {str(ex)} for {method} {path} from {origin}", ex)
            except Exception:
                # If logging fails, continue anyway
                pass
            
            try:
                from fastapi.responses import JSONResponse
                from fastapi import HTTPException
                
                # Safely get status code
                status_code = 500
                if isinstance(ex, HTTPException):
                    status_code = ex.status_code
                elif hasattr(ex, 'status_code'):
                    try:
                        status_code = ex.status_code
                    except Exception:
                        status_code = 500
                
                # Safely get error message
                error_message = "Internal server error"
                try:
                    if isinstance(ex, HTTPException):
                        error_message = ex.detail
                    elif hasattr(ex, 'detail'):
                        error_message = ex.detail
                    elif hasattr(ex, 'status_text'):
                        error_message = ex.status_text
                    else:
                        error_message = str(ex) if ex else type(ex).__name__
                except Exception:
                    error_message = type(ex).__name__ if ex else "Unknown error"
                
                error_response = JSONResponse(
                    status_code=status_code,
                    content={"error": error_message, "detail": str(ex) if ex else "Unknown error", "type": type(ex).__name__ if ex else "UnknownException"}
                )
                
                # Add CORS headers to error response
                try:
                    cors_origins = self._get_cors_origins()
                    if origin in cors_origins or "*" in cors_origins:
                        error_response.headers["Access-Control-Allow-Origin"] = origin if origin != 'no-origin' else "*"
                        error_response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
                        error_response.headers["Access-Control-Allow-Headers"] = "*"
                        error_response.headers["Access-Control-Allow-Credentials"] = "true"
                except Exception:
                    # If CORS setup fails, add basic CORS headers
                    error_response.headers["Access-Control-Allow-Origin"] = "*"
                    error_response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
                    error_response.headers["Access-Control-Allow-Headers"] = "*"
                
                return error_response
            except Exception as handler_ex:
                # Ultimate fallback - ensure we always return a valid response
                try:
                    from fastapi.responses import JSONResponse
                    fallback_response = JSONResponse(
                        status_code=500,
                        content={"error": "Internal server error", "detail": "Exception handler error", "type": "HandlerException"}
                    )
                    fallback_response.headers["Access-Control-Allow-Origin"] = "*"
                    fallback_response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
                    fallback_response.headers["Access-Control-Allow-Headers"] = "*"
                    return fallback_response
                except Exception:
                    # Last resort - return a basic response
                    from fastapi.responses import Response
                    return Response(
                        status_code=500,
                        content='{"error":"Internal server error"}',
                        media_type="application/json",
                        headers={"Access-Control-Allow-Origin": "*"}
                    )
        
        cur = os.getcwd()
        self.app.mount(path="/static", app=StaticFiles(directory=f"{cur}/rpApi/static/_pages", html=True), name="static")        
        self.configureRoutes()
        return self.app

    def _get_cors_origins(self):
        """Get CORS origins based on environment"""
        env = os.getenv('app_env', 'development')
        self.logger.debug(f"🔧 Environment detected: '{env}'")
        
        if env in ['prod', 'production']:
            return [
                "https://pwa.refereex.com",
                "https://pwa-dev.refereex.com",
                "https://api-dev.refereex.com",
                "https://refportal.refereex.com",
                "https://www.refereex.com",
                "https://refereex.com",
                "https://pwa-dev.refereex.com:8445",  # Your PWA domain
                "https://pwa-dev.refereex.com:8443",  # Your PWA domain
                "https://pwa-dev.refereex.com:24843",  # Your PWA domain
                "https://w.meta.com",
                "https://meta.refereex.com",
                "https://refalert.refereex.com",
                "https://ref.football.org.il",
                "https://www.ref.football.org.il",
            ]
        elif env == 'staging':
            return [
                "https://pwa-staging.refereex.com",
                "https://staging.refereex.com"
            ]
        else:  # development
            return [
                "https://pwa-dev.refereex.com:24843",  # Your PWA domain
                "https://pwa-dev.refereex.com:8445",  # Your PWA domain
                "https://pwa-dev.refereex.com:8443",  # Your PWA domain
                "https://pwa-dev.refereex.com",       # Without port
                "http://localhost:3000",               # Local development
                "http://localhost:8445",               # Local PWA
                "http://127.0.0.1:3000",              # Local development
                "http://127.0.0.1:8445",              # Local PWA
                "*"                                    # Fallback for development
            ]

    def configureRoutes(self):
        # Add other middleware AFTER CORS (so they execute first)
        #self.app.add_middleware(SwarmProxyHeadersMiddleware, logger=self.logger)
        #self.app.add_middleware(ProcessTimeMiddleware, logger=self.logger)

        incomingApiGuid = helpers.get_secret('incoming_api_guid')

        #static
        self.app.add_api_route(
            path="/",
            endpoint=self.impl.root,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/welcome",
            endpoint=self.impl.welcome,
            methods=["GET"]
        )
        
        #self.app.add_url_rule('/admindashboard', 'dashboard', self.refPortalApiImplementation.dashboard, methods=['GET'])
        #self.app.add_url_rule('/dashboard/<guid>', 'dashboardByRef', self.refPortalApiImplementation.dashboard, methods=['GET'])

        #self.app.add_url_rule('/api/dashboardLoadData', 'dashboardLoadData', self.refPortalApiImplementation.dashboardLoadData, methods=['GET'])
        #self.app.add_url_rule('/api/dashboardLoad', 'dashboardLoad', self.dashboardLoad, methods=['GET'])
        #self.app.add_url_rule('/api/dashboardLoadData/<guid>', 'dashboardForReferee', self.refPortalApiImplementation.dashboardLoadDataForReferee, methods=['GET'])
        #self.app.add_url_rule(rule='/api/dashboardLoadData', endpoint='dashboardLoadData', view_func=cross_origin(origins=["https://www.refereex.com"])(self.dashboardLoadData), methods=['GET'])
        
        #self.app.add_url_rule('/calendar/<guid>', 'calendar', self.refPortalApiImplementation.calendar, methods=['GET'])
        #self.app.add_url_rule('/api/calendar/<guid>', 'loadCalendar', self.refPortalApiImplementation.loadCalendar, methods=['GET'])

        self.app.add_api_route(
            path="/registration",
            endpoint=self.impl.registration,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/guy/changePassword",
            endpoint=self.impl.changePassword,
            methods=["GET"]
        )
        '''
        self.app.add_url_rule('/refreshLeaguesTables', 'refreshLeaguesTables', self.refreshLeaguesTables, methods=['GET'])
        self.app.add_url_rule('/getReferee', 'getReferee', self.getReferee, methods=['GET'])
        self.app.add_url_rule('/addPending', 'addPending', self.addPending, methods=['GET'])
        self.app.add_url_rule('/activate', 'activate', self.activate, methods=['GET'])
        self.app.add_url_rule('/deactivate', 'deactivate', self.deactivate, methods=['GET'])
        '''

        #api
        self.app.add_api_route(
            path="/api/health",
            endpoint=self.app.state.limiter.limit("90/minute")(self.impl.getHealth),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/delay",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.delay),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/changePassword",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.changePasswordSubmit),
            methods=["POST"]
        )

        self.app.add_api_route(
            path='/api/reloadIntents',
            endpoint=self.impl.reloadIntents,
            methods=['GET']
        )

        self.app.add_api_route(
            path="/api/refreshLeaguesTables",
            endpoint=self.impl.refreshLeaguesTablesSubmit,
            methods=["POST"]
        )
        self.app.add_api_route(
            path="/api/approveGame/{mobileNo}/{msgSid}/{gameId}",
            endpoint=self.impl.approveGame,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/getGameUpdateTemplate/{mobileNo}/{gameId}",
            endpoint=self.impl.getGameUpdateTemplate,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/file/{fileId}",
            endpoint=self.impl.downloadGameIcsFile,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/downloadIcsFile/{msgSid}",
            endpoint=self.impl.downloadIcsFile,
            methods=["GET"]
        )        
        self.app.add_api_route(
            path="/api/registration",
            endpoint=self.impl.registrationSubmit,
            methods=["POST"]
        )
        
        # Poll preview endpoint - shows poll title and redirects to WhatsApp
        self.app.add_api_route(
            path="/api/pollVote/{pollId}",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pollPreview),
            methods=["GET"],
            tags=["Polls"]
        )

        self.app.add_api_route(
            path="/api/processMobileNo/{mobileNo}",
            endpoint=self.impl.processMobileNo,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/processRefIds",
            endpoint=self.impl.processMobileNo,
            methods=["POST"]
        )
        self.app.add_api_route(
            path="/api/processRefIds",
            endpoint=self.impl.processMobileNosPost,
            methods=["POST"]
        )
        '''
        self.app.add_url_rule('/api/getReferee', 'getRefereeSubmit', self.getRefereeSubmit, methods=['POST'])
        self.app.add_url_rule('/api/addPending', 'addPendingSubmit', self.addPendingSubmit, methods=['POST'])
        self.app.add_url_rule('/api/activate', 'activateSubmit', self.activateSubmit, methods=['POST'])
        self.app.add_url_rule('/api/deactivate', 'deactivateSubmit', self.deactivateSubmit, methods=['POST'])
        '''

        # webhook
        self.app.add_api_route(
            path=f"/api/{incomingApiGuid}/myWebhook",
            endpoint=self.impl.myWebhook,
            methods=["POST"],
            tags=["My Webhook"]
        )

        # twilio
        if self.impl.messagingService.twilioClient.useClient:
            self.app.add_api_route(
                path=f"/twilio/{incomingApiGuid}/incomingWebhook",
                endpoint=self.impl.incomingWebhookFromTwilio,
                methods=["POST"],
                dependencies=[Depends(self.impl.authenticateTwilioRequest)],
                tags=["Twilio WhatsApp"]
            )
            #statusCallBackLimit = self.limiter.exempt()(self.statusCallback)
            self.app.add_api_route(
                path=f"/twilio/{incomingApiGuid}/statusCallback",
                endpoint=self.impl.statusCallback,
                methods=["POST"]
            )

        # greenApi
        if self.impl.messagingService.greenApiClient.useClient:
            self.app.add_api_route(
                path=f"/greenApi/{incomingApiGuid}/incomingWebhook",
                endpoint=self.impl.incomingWebhookFromGreenApi,
                methods=["POST"],
                dependencies=[Depends(self.impl.authenticateGreenApiRequest)],
                tags=["GreenApi WhatsApp"]
            )

        # manychat
        if self.impl.messagingService.manychatClient.useClient:
            self.app.add_api_route(
                path=f"/manychat/{incomingApiGuid}/incomingWebhook",
                endpoint=self.impl.incomingWebhookFromManychat,
                methods=["POST"]
            )

        # meta GET
        if self.impl.messagingService.metaClient.useClient:
            self.app.add_api_route(
                path=f"/meta/incomingWebhook",
                endpoint=self.impl.incomingWebhookFromMeta_GET,
                methods=["GET"]
            )

            # meta POST
            self.app.add_api_route(
                path=f"/meta/incomingWebhook",
                endpoint=self.impl.incomingWebhookFromMeta_POST,
                methods=["POST"],
                dependencies=[Depends(self.impl.authenticateMetaRequest)],
                tags=["Meta WhatsApp"]
            )

            # meta POST
            self.app.add_api_route(
                path=f"/meta/{incomingApiGuid}/incomingWebhook",
                endpoint=self.impl.incomingWebhookFromMeta_POST,
                methods=["POST"],
                dependencies=[Depends(self.impl.authenticateMetaRequest)],
                tags=["Meta WhatsApp"]
            )

        # telegram
        if self.impl.messagingService.telegramClient.useClient:
            self.app.add_api_route(
                path=f"/telegram/incomingWebhook",
                endpoint=self.impl.incomingWebhookFromTelegram,
                methods=["POST"],
                dependencies=[Depends(self.impl.authenticateTelegramRequest)],
                tags=["Telegram"]
            )

        # manychattest
        self.app.add_api_route(
            path="/manychattest/approvegame/{refId}/{waId}/{gameId}",
            endpoint=self.impl.manyChatTest,
            methods=["POST"]
        )
        
        # Chat API routes for cross-device synchronization
        try:
            if chat_router:
                self.app.include_router(chat_router)
                self.logger.info("✅ Chat API router included successfully")
            else:
                self.logger.warning("⚠️ Chat API router not available - chat sync will not work")
        except Exception as ex:
            self.logger.error(f"❌ Error including chat API router: {ex}")
            self.logger.warning("⚠️ Chat synchronization will not be available")

        # Auth API routes for refresh token functionality
        try:
            if auth_router:
                self.app.include_router(auth_router)#, prefix="/api")
                self.logger.info("✅ Auth API router included successfully")
            else:
                self.logger.warning("⚠️ Auth router not available - chat sync will not work")
        except Exception as ex:
            self.logger.error(f"❌ Error including auth API router: {ex}")
            self.logger.warning("⚠️ Refresh token functionality will not be available")

        self.configurePWARoutes()

        websocket_routes = [r for r in self.app.routes if hasattr(r, 'path') and '/pwa/ws/jwt/' in r.path]
        self.logger.info(f"Found {len(websocket_routes)} WebSocket routes: {websocket_routes}")
        
        #statusCallBackLimit = self.limiter.exempt()(self.statusCallback)
        #self.app.add_url_rule(f'/twilio/{incomingApiGuid}/statusCallback', 'statusCallback', statusCallBackLimit, methods=['POST'])

    def configurePWARoutes(self):
        jwtSecretKey = helpers.get_secret('jwt_secret_key')
        
        jwtTokenService = JwtTokenService(secret_key=jwtSecretKey, logger=self.logger, cacheService=self.cacheService)
        self.app.state.jwt_token_service = jwtTokenService
        cacheService = self.container.cache_service()

        self.app.add_middleware(
            middleware_class=JWTMiddleware,
            logger=self.logger,
            cacheService=cacheService,
            jwtTokenService=jwtTokenService,
            protected_paths=[
                '/api/pwa/',
            ],
            skip_paths=[
                '/api/pwa/health',
                '/api/pwa/pair',
                '/api/pwa/chat/',
                '/api/pwa/public/',
                '/api/pwa/log',
                '/api/pwa/fields',
                '/api/pwa/tenants',
                '/api/pwa/broadcastRefreshPush',
                #'/api/pwa/documents',
                #'/api/pwa/rules',
                '/auth/'  # Skip JWT middleware for auth endpoints
            ]
        )
        
        '''
        self.app.add_middleware(
            middleware_class=AuthMiddleware, 
            logger=self.logger,
            cacheService=cacheService,
            protected_paths=[
                '/api/pwa/',
            ],
            skip_paths=[
                '/api/pwa/pair',
            ]
        )
        '''
        
        self.app.add_api_route(
            path="/api/pwa/health",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.getHealth),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/pair",
            endpoint=self.app.state.limiter.limit("5/minute")(self.impl.pwaPair),
            methods=["POST"],
        )

        self.app.add_api_route(
            path="/api/pwa/check-auth",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaCheckAuth),
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/push/set-subscription",
            endpoint=self.impl.pwaSetPushSubscription,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/unpair",
            endpoint=self.impl.pwaUnpair,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/push/position-update",
            endpoint=self.impl.pwaPositionUpdate,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/speed-tracking-data",
            endpoint=self.impl.pwaSpeedTrackingData,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/tenants",
            endpoint=self.impl.pwaGetTenants,
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/roles",
            endpoint=self.impl.pwaGetRoles,
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/referees",
            endpoint=self.impl.pwaGetReferees,
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/dashboardLoadData",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaDashboardLoadData),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/refereeGames",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaGetRefereeGames),
            methods=["GET"]
        )        

        self.app.add_api_route(
            path="/api/pwa/pwaUpdateGameReport",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaUpdateGameReport),
            methods=["POST"]
        )
        
        self.app.add_api_route(
            path="/api/pwa/log",
            endpoint=self.impl.pwaLog,
            methods=["POST"]
        )
        
        self.app.add_api_route(
            path="/api/pwa/refereeReviews",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaGetRefereeReviews),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/messages",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaGetMessages),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/downloadIcsFile/{gameId}",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaDownloadIcsFile),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/approveGame",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaApproveGame),
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/fields",
            endpoint=self.impl.pwaGetFields,
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/availability",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaGetAvailability),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/updateRefereeAvailability",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaUpdateRefereeAvailability),
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/user-details",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaGetUserDetails),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/updateUserDetails",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaUpdateUserDetails),
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/change-password",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaChangePassword),
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/documents",
            endpoint=self.impl.pwaGetDocuments,
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/rules",
            endpoint=self.impl.pwaGetRules,
            methods=["GET"]
        )
        
        self.app.add_api_route(
            path="/api/pwa/websocket/status",
            endpoint=self.app.state.limiter.limit("20/minute")(self.impl.pwaWebsocketStatus),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/test/sendPushNotification",
            endpoint=self.impl.sendTestPushNotification,
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/broadcastRefreshPush",
            endpoint=self.app.state.limiter.limit("5/minute")(self.impl.pwaBroadcastRefreshPush),
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/sendReportEmail",
            endpoint=self.impl.pwaSendReportEmail,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/refereeTemplates",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaGetRefereeTemplates),
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/pwa/templates/update",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaSetRefereeTemplate),
            methods=["POST"]
        )
        self.app.add_api_route(
            path="/api/pwa/notifications",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaGetNotifications),
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/pwa/notifications/update",
            endpoint=self.app.state.limiter.limit("10/minute")(self.impl.pwaSetNotification),
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/pwa/public/leagueTables",
            endpoint=self.app.state.limiter.limit("30/minute")(self.impl.pwaGetPublicLeagueTables),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/public/games",
            endpoint=self.app.state.limiter.limit("30/minute")(self.impl.pwaGetPublicGames),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/public/games/stream",
            endpoint=self.app.state.limiter.limit("30/minute")(self.impl.pwaGetPublicGamesStream),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/public/tablesFilters",
            endpoint=self.app.state.limiter.limit("60/minute")(self.impl.pwaGetPublicTablesFilters),
            methods=["GET"]
        )

        self.app.add_api_route(
            path="/api/pwa/public/gamesFilters",
            endpoint=self.app.state.limiter.limit("60/minute")(self.impl.pwaGetPublicGamesFilters),
            methods=["GET"]
        )

        # Add WebSocket endpoint
        self.app.add_api_websocket_route(
            path="/pwa/ws/jwt/{client_identifier}",
            endpoint=self.impl.pwaWebsocketEndpoint,
            name="Websocket Endpoint"
        )

        self.app.add_api_websocket_route(
            path="/wsTest",
            endpoint=self.impl.wsTestEndpoint,
            name="WebSocket Test Endpoint"
        )

#if __name__ == '__main__':
refPortalApi = RefPortalApi()
#refPortalApiAws.start()
# Use the version without lifespan to avoid ASGI protocol issues
app = refPortalApi.create_app()
#handler = Mangum(app=refPortalApi.app, lifespan="off")
    #asyncio.run(refPortalApi.sendMessageTemplate('43679'))
    #asyncio.run(refPortalApi.approveGame('43679', '26396ab6'))
"""
    flow 
        #1 send askToJoin_+972
        #2 IncomingWebhook - When message received the message
                Create user using MobileNo as LoginId
                Send template message to referee with JoiningConfirmation_+972...  (open 24hrs window)
        #3 IncomngWebhook - When message received send Registration message with link to registration page
        #4 When registration submitted - Create user and delete mobile user
"""
    