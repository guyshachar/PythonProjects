"""
JWT Middleware with Refresh Token Functionality

This module provides JWT authentication middleware with proper refresh token capabilities.

Features:
1. Separate access tokens (short-lived) and refresh tokens (long-lived)
2. Automatic token refresh using refresh tokens
3. Token rotation for security
4. Proactive token refresh for tokens expiring within 5 minutes
5. Response headers indicating when tokens are refreshed
6. Graceful handling of expired tokens with detailed error codes
7. Clean, non-redundant error logging

How it works:
1. Access tokens expire quickly (5 minutes) for security
2. Refresh tokens last longer (30 days) for convenience
3. When access token expires, use refresh token to get new access token
4. Refresh tokens are rotated (new refresh token issued with each refresh)
5. If refresh token expires, user must re-authenticate

Client Usage:
- Store both access token and refresh token
- Check for X-Token-Refreshed header in responses
- Use X-New-Access-Token and X-New-Refresh-Token headers to update stored tokens
- Handle TOKEN_EXPIRED_NO_REFRESH errors by redirecting to login

Error Codes:
- TOKEN_EXPIRED_NO_REFRESH: Token expired and cannot be refreshed
- TOKEN_EXPIRED_REFRESH_FAILED: Token refresh attempt failed
- AUTH_REFRESH_TOKEN_EXPIRED: Refresh token has expired
- AUTH_REFRESH_TOKEN_INVALID: Refresh token is invalid

Error Handling:
- jwt.ExpiredSignatureError: Automatically triggers refresh attempt
- jwt.InvalidTokenError: Immediate failure with 401
- Other exceptions: Fallback to refresh attempt before failing
- Clean logging without duplicate error messages
"""

from fastapi import Request, HTTPException
import jwt
from datetime import datetime, timedelta
import time
import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger
import shared.helpers as helpers
from rpApi.middlewares.customBaseHttpMiddleware import CustomBaseHttpMiddleware
from shared.db.cacheService import CacheService

class JwtTokenService:
    def __init__(self, logger:Logger, cacheService: CacheService, secret_key: str):
        self.logger = logger
        self.cacheService = cacheService
        self.secret_key = secret_key
        self.algorithm = 'HS256'
        # Token expiration times
        self.access_token_expiry = 24 * 60 * 60  # 24 hours
        self.refresh_token_expiry = 30 * 24 * 60 * 60  # 30 days

    def _get_app_version_from_request(self, request: Request = None) -> str:
        """Get app version from request header (X-App-Version)"""
        if request:
            app_version = request.headers.get('X-App-Version')
            if app_version:
                return app_version
        return None
    
    def create_access_token(self, user_data: dict, app_version: str = None) -> str:
        """Create a short-lived access token"""
        current_time = int(time.time())
        
        payload = {
            **user_data,
            'token_type': 'access',
            'iat': current_time,  # Issued at
            'exp': current_time + self.access_token_expiry,  # Expires in 24 hours
            'iss': 'refereex'
        }
        
        # Add app version to payload if provided
        if app_version:
            payload['app_version'] = app_version
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, user_data: dict, app_version: str = None) -> str:
        """Create a long-lived refresh token"""
        current_time = int(time.time())
        
        payload = {
            **user_data,
            'token_type': 'refresh',
            'iat': current_time,  # Issued at
            'exp': current_time + self.refresh_token_expiry,  # Expires in 30 days
            'iss': 'refereex'
        }
        
        # Add app version to payload if provided
        if app_version:
            payload['app_version'] = app_version
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_token_pair(self, user_data: dict, app_version: str = None) -> dict:
        """Create both access and refresh tokens"""
        return {
            'access_token': self.create_access_token(user_data, app_version=app_version),
            'refresh_token': self.create_refresh_token(user_data, app_version=app_version),
            'access_expires_in': self.access_token_expiry,
            'refresh_expires_in': self.refresh_token_expiry
        }

    def verify_token_by_request(self, request: Request) -> dict:
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            raise HTTPException(status_code=401, detail="Missing Authorization header1")
        
        if not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Invalid Authorization header2 format")

        token = auth_header.split(' ')[1]
        return self.verify_token(token=token, request=request)

    def verify_token(self, token: str, request: Request = None, check_version: bool = True) -> dict:
        payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        
        # Check if token version matches current app version from request header
        # If version mismatch, we'll handle it in middleware to trigger refresh
        if check_version and request:
            current_app_version = self._get_app_version_from_request(request)
            token_app_version = payload.get('app_version')
            
            if current_app_version and (token_app_version is None or token_app_version != current_app_version):
                # Mark payload for version refresh instead of rejecting
                payload['_version_mismatch'] = True
        
        return payload

    def verify_refresh_token(self, refresh_token: str) -> dict:
        """Verify a refresh token specifically"""
        try:
            payload = jwt.decode(refresh_token, self.secret_key, algorithms=[self.algorithm])
            if payload.get('token_type') != 'refresh':
                raise ValueError("Token is not a refresh token")
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "refresh_token_expired",
                    "message": "Refresh token has expired",
                    "code": "AUTH_REFRESH_TOKEN_EXPIRED"
                }
            )
        except Exception as e:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "refresh_token_invalid",
                    "message": "Invalid refresh token",
                    "code": "AUTH_REFRESH_TOKEN_INVALID"
                }
            )

    def refresh_token_pair(self, refresh_token: str, request: Request = None) -> dict:
        """Refresh both access and refresh tokens using a valid refresh token"""
        try:
            # Verify the refresh token
            payload = self.verify_refresh_token(refresh_token)
            
            # Get app version from request header if available
            app_version = self._get_app_version_from_request(request) if request else None
            
            # Create new token pair with same user data
            user_data = {
                'clientIdentifier': payload.get('clientIdentifier'),
                'refName': payload.get('refName'),
                'role': payload.get('role', 'user'),
                'mobileNo': payload.get('mobileNo'),
                'allowedSections': payload.get('allowedSections'),
                'tenantRefIds': payload.get('tenantRefIds')
            }
            
            return self.create_token_pair(user_data, app_version=app_version)
            
        except HTTPException:
            raise
        except Exception as e:
            raise ValueError(f"Failed to refresh token pair: {str(e)}")

    def getUserSectionsAndTenantRefIds(self, globalRefereeDetail: dict):
        mobileNo = globalRefereeDetail.get('mobileNo')
        tenantRefIds = {}
        isGamesAllowed = False
        isReviewsAllowed = False
        roles = []
        if globalRefereeDetail.get('role', '').lower() == 'admin':
            roles.append('admin')
        for tenantKey in globalRefereeDetail.get('tenantKeys', []):
            tenantReferee = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            if tenantReferee:
                tenantRefIds[tenantKey] = tenantReferee.get('refId')
                if 'games' in tenantReferee.get('objTypes', []):
                    isGamesAllowed = True
                if 'reviews' in tenantReferee.get('objTypes', []):
                    isReviewsAllowed = True
                if tenantReferee.get('role') and tenantReferee.get('role') not in roles:
                    roles.append(tenantReferee.get('role'))
        
        userValidSections = ['dashboard', 'games', 'reviews', 'messages', 'fields', 'availability', 'documents', 'rules', 'chat', 'userDetails', 'admin']
        if not 'admin' in roles:
            userValidSections.remove('admin')
        if not ('tenantAdmin' in roles or 'admin' in roles):
            userValidSections.remove('dashboard')
        
        if not isGamesAllowed:
            userValidSections.remove('games')
        if not isReviewsAllowed:
            userValidSections.remove('reviews')
        
        return tenantRefIds, userValidSections

class JWTMiddleware(CustomBaseHttpMiddleware):
    """JWT-specific middleware that inherits from CustomBaseHttpMiddleware"""
    def __init__(self, app, logger:Logger, cacheService: CacheService, jwtTokenService: JwtTokenService, protected_paths: list = None, skip_paths: list = None):
        super().__init__(app=app, logger=logger, protected_paths=protected_paths, skip_paths=skip_paths)
        
        self.cacheService = cacheService
        self.jwtTokenService = jwtTokenService
            
    async def _handle_protected_path(self, request: Request):
        """Override to implement JWT validation logic"""
        await self._validate_clientSessionIdentifiers(request=request)
        await self._validate_jwt(request=request)
    
    async def _post_process_protected_path(self, request: Request, response):
        self.logger.debug(f"Post-processing protected path: {request.url.path}")
                
        # Check if token was refreshed during validation
        if hasattr(request.state, 'token_refreshed') and request.state.token_refreshed:
            # Add new tokens to response headers
            response.headers['X-New-Access-Token'] = request.state.new_access_token
            response.headers['X-New-Refresh-Token'] = request.state.new_refresh_token
            response.headers['X-Token-Refreshed'] = 'true'
            response.headers['X-Access-Token-Expires-In'] = str(self.jwtTokenService.access_token_expiry)
            response.headers['X-Refresh-Token-Expires-In'] = str(self.jwtTokenService.refresh_token_expiry)
            self.logger.info(f"✅ Adding refreshed tokens to response headers for user: {getattr(request.state, 'ref_name', 'unknown')}")
        else:
            # Check if version mismatch was detected during validation
            if hasattr(request.state, 'version_mismatch') and request.state.version_mismatch:
                # Get token from header to extract user data
                auth_header = request.headers.get('Authorization')
                if auth_header and auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                    try:
                        payload = self._verify_token(token, request, check_version=False)  # Don't check version again
                        tenantRefIds, userValidSections = self.jwtTokenService.getUserSectionsAndTenantRefIds(globalRefereeDetail=self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=payload.get('mobileNo')))
                        # Create new token pair with current version from header
                        new_tokens = self._create_token_pair({
                            'clientIdentifier': payload.get('clientIdentifier'),
                            'refName': payload.get('refName'),
                            'role': payload.get('role'),
                            'mobileNo': payload.get('mobileNo'),
                            'allowedSections': userValidSections,
                            'tenantRefIds': tenantRefIds
                        }, request=request)
                        
                        # Add new tokens to response headers
                        response.headers['X-New-Access-Token'] = new_tokens['access_token']
                        response.headers['X-New-Refresh-Token'] = new_tokens['refresh_token']
                        response.headers['X-Token-Refreshed'] = 'true'
                        response.headers['X-Access-Token-Expires-In'] = str(self.jwtTokenService.access_token_expiry)
                        response.headers['X-Refresh-Token-Expires-In'] = str(self.jwtTokenService.refresh_token_expiry)
                        self.logger.info(f"✅ Token refreshed due to version mismatch for user: {payload.get('refName')}")
                    except Exception as ex:
                        self.logger.debug(f"Could not refresh token for version mismatch:", ex)
            else:
                # Check if proactive refresh is needed (normal expiration-based refresh)
                auth_header = request.headers.get('Authorization')
                if auth_header and auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                    try:
                        payload = self._verify_token(token, request)
                        should_refresh = self._should_refresh_token(payload)
                        self.logger.debug(f"Should refresh token: {should_refresh}")
                        
                        if should_refresh:
                            # Create new token pair (will include current app version from header)
                            new_tokens = self._create_token_pair({
                                'clientIdentifier': payload.get('clientIdentifier'),
                                'refName': payload.get('refName'),
                                'role': payload.get('role'),
                                'mobileNo': payload.get('mobileNo'),
                                'allowedSections': payload.get('allowedSections'),
                                'tenantRefIds': payload.get('tenantRefIds')
                            }, request=request)
                            
                            # Add new tokens to response headers
                            response.headers['X-New-Access-Token'] = new_tokens['access_token']
                            response.headers['X-New-Refresh-Token'] = new_tokens['refresh_token']
                            response.headers['X-Token-Refreshed'] = 'true'
                            response.headers['X-Access-Token-Expires-In'] = str(self.jwtTokenService.access_token_expiry)
                            response.headers['X-Refresh-Token-Expires-In'] = str(self.jwtTokenService.refresh_token_expiry)
                            self.logger.info(f"✅ Proactive token refresh for user: {payload.get('refName')}")
                        else:
                            self.logger.debug(f"Token does not need refresh for user: {payload.get('refName')}")
                    except Exception as ex:
                        # If token verification fails, just continue without refresh
                        self.logger.debug(f"Token verification failed during post-processing:", ex)
                        pass
                else:
                    self.logger.debug("No Authorization header found for proactive refresh check")

        """Override to add JWT-specific headers"""
        response.headers['X-JWT-Validated'] = 'true'
        #response.headers['X-User-ID'] = getattr(request.state, 'ref_id', 'unknown')
        #response.headers['X-User-Name'] = helpers.safe_encode_header(value=getattr(request.state, 'ref_name', 'unknown'))
        #response.headers['X-User-Role'] = helpers.safe_encode_header(value=getattr(request.state, 'role', 'unknown'))
        return response
    
    def _create_token_pair(self, user_data: dict, request: Request = None) -> dict:
        app_version = self.jwtTokenService._get_app_version_from_request(request) if request else None
        return self.jwtTokenService.create_token_pair(user_data=user_data, app_version=app_version)

    async def _validate_clientSessionIdentifiers(self, request: Request):
        # Extract X-Client-Identifier and X-Session-Identifier from headers and add to state
        client_identifier_header = request.headers.get('X-Client-Identifier')
        session_identifier_header = request.headers.get('X-Session-Identifier')

        request.state.client_identifier = None
        request.state.session_identifier = None

        value = self.cacheService.getClientIdentifier(clientIdentifier=client_identifier_header)
        if not value:
            raise HTTPException(status_code=401, detail="Invalid client identifier")

        if session_identifier_header != value.get('sessionIdentifier'):
            raise HTTPException(status_code=401, detail="Invalid session identifier")

        request.state.client_identifier = client_identifier_header
        request.state.session_identifier = session_identifier_header
    
    def _get_admin_apply_selected_referee_from_request(self, request: Request) -> str:
        """Get admin apply selected referee from request header (X-Admin-Apply-Selected-Referee)"""
        if request:
            admin_apply_selected_referee = request.headers.get('X-Admin-Apply-Selected-Referee')
            if admin_apply_selected_referee:
                return admin_apply_selected_referee
        return None

    async def _validate_jwt(self, request: Request):
        """Validate JWT token for protected paths"""
        optional_auth = request.headers.get('X-Optional-Auth') == 'true'

        # Extract Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            if optional_auth:
                return
            raise HTTPException(status_code=401, detail="Missing Authorization header3")

        if not auth_header.startswith('Bearer '):
            if optional_auth:
                return
            startswith = auth_header.split(' ')[0]
            raise HTTPException(status_code=401, detail=f"Missing Authorization header4 x{startswith}z")
        
        # Extract token
        token = auth_header.split(' ')[1]
        if not token:
            raise HTTPException(status_code=401, detail="Missing JWT token")
        
        try:
            payload = self._verify_token(token, request)

            # Check for version mismatch - if present, mark for refresh but still allow request
            request.state.version_mismatch = False
            if payload.get('_version_mismatch'):
                self.logger.info(f"🔄 Version mismatch in token for user {payload.get('refName')}. Token will be refreshed in response headers.")
                # Mark request state to trigger token refresh in post-processing
                request.state.version_mismatch = True

            # Extract user information
            if payload:
                request.state.ref_name = payload.get('refName')
                request.state.role = payload.get('role', 'user')
                request.state.mobile_no = payload.get('mobileNo')
                request.state.allowed_sections = payload.get('allowedSections')
                request.state.tenant_ref_ids = payload.get('tenantRefIds')
                
                request.state.admin_apply_selected_referee = self._get_admin_apply_selected_referee_from_request(request) or ''

                request.state.current_version = self.jwtTokenService._get_app_version_from_request(request)
                request.state.token_version = payload.get('app_version')

                # Validate required fields
                required_fields = ['clientIdentifier']
                missing_fields = [field for field in required_fields if not payload.get(field)]

                if missing_fields:
                    raise HTTPException(
                        status_code=401, 
                        detail=f"Missing required JWT {token[:10]} claims: {', '.join(missing_fields)}"
                    )

                self.logger.debug(f"JWT {token[:10]} validation successful for user: {payload.get('refName')}")
            
        except jwt.ExpiredSignatureError:
            # Token expired - try to refresh it using refresh token
            self.logger.debug(f"JWT token {token[:10]} expired, attempting refresh")
            self._refresh_token_using_refresh_token(request=request, expired_token=token)                
        except jwt.InvalidTokenError as ex:
            raise HTTPException(status_code=401, detail=f"Invalid JWT token {token[:10]}")
        except HTTPException as ex:
            if ex.status_code == 401:
                self.logger.error(f"Jwt authorization error {token[:10]}: {ex.detail}")
            else:
                # Re-raise HTTP exceptions as-is
                raise
        except Exception as ex:
            # Log unexpected errors and try refresh as fallback
            self.logger.error(f"Unexpected JWT {token[:10]} validation error: {type(ex).__name__}: {str(ex)}")
            self._refresh_token_using_refresh_token(request=request, expired_token=token)
    
    def _verify_token(self, token: str, request: Request = None, check_version: bool = True) -> dict:
        """Verify and decode JWT token"""
        try:
            payload = self.jwtTokenService.verify_token(token=token, request=request, check_version=check_version)
            return payload
        except jwt.ExpiredSignatureError:
            # Re-raise to be handled by caller
            raise
        except jwt.InvalidTokenError:
            raise ValueError(f"Invalid token {token[:10]}")
        except HTTPException:
            raise
        except Exception as e:
            raise ValueError(f"Token {token[:10]} verification failed: {str(e)}")

    def _should_refresh_token(self, payload: dict) -> bool:
        """Check if token should be refreshed proactively"""
        exp_timestamp = payload.get('exp')
        if not exp_timestamp:
            self.logger.debug("No expiration timestamp found, should refresh")
            return True
        
        exp_time = datetime.fromtimestamp(exp_timestamp)
        current_time = helpers.utcNow()
        time_until_expiry = exp_time - current_time
        # Refresh if token will expire within the configured refresh window (5% of token lifetime)
        refresh_window_seconds = max(300, int(self.jwtTokenService.access_token_expiry * 0.05))  # At least 5 minutes, or 5% of token lifetime
        refresh_threshold = timedelta(seconds=refresh_window_seconds)
        
        should_refresh = time_until_expiry <= refresh_threshold
        
        self.logger.debug(f"Token refresh check: time_until_expiry={time_until_expiry}, refresh_threshold={refresh_threshold}, should_refresh={should_refresh}")
        
        return should_refresh

    def _refresh_token_using_refresh_token(self, request: Request, expired_token: str):
        """Refresh expired access token using refresh token from request"""
        try:
            # Get refresh token from request headers or cookies
            refresh_token = self._extract_refresh_token(request)
            
            if not refresh_token:
                # No refresh token available
                self.logger.warning(f"JWT token {expired_token[:10]}... expired but no refresh token available")
                raise HTTPException(
                    status_code=401, 
                    detail={
                        "error": "token_expired",
                        "message": f"JWT token {expired_token[:10]}... has expired and no refresh token available",
                        "code": "TOKEN_EXPIRED_NO_AUTH_REFRESH_TOKEN"
                    }
                )
            
            # Try to refresh using the refresh token (with version from request header)
            new_tokens = self.jwtTokenService.refresh_token_pair(refresh_token, request=request)
            
            # Extract user info from the new access token payload
            new_access_payload = jwt.decode(new_tokens['access_token'], self.jwtTokenService.secret_key, algorithms=[self.jwtTokenService.algorithm])
            
            # Set user information from refreshed token
            #request.state.client_identifier = new_access_payload.get('clientIdentifier')
            request.state.ref_name = new_access_payload.get('refName')
            request.state.role = new_access_payload.get('role', 'user')
            request.state.mobile_no = new_access_payload.get('mobileNo')
            request.state.allowed_sections = new_access_payload.get('allowedSections')
            request.state.tenant_ref_ids = new_access_payload.get('tenantRefIds')
            
            request.state.admin_apply_selected_referee = self._get_admin_apply_selected_referee_from_request(request)
            
            # Add refresh headers to request state for later use
            request.state.token_refreshed = True
            request.state.new_access_token = new_tokens['access_token']
            request.state.new_refresh_token = new_tokens['refresh_token']
            
            self.logger.info(f"Token pair automatically refreshed for user: {new_access_payload.get('refName')}")
                
        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as refresh_ex:
            # Log refresh failure and return structured error
            self.logger.error(f"Token refresh failed for {expired_token[:10]}: {type(refresh_ex).__name__}: {str(refresh_ex)}")
            raise HTTPException(
                status_code=401, 
                detail={
                    "error": "token_expired",
                    "message": f"JWT token {expired_token[:10]} has expired and refresh failed",
                    "code": "TOKEN_EXPIRED_REFRESH_FAILED"
                }
            )

    def _extract_refresh_token(self, request: Request) -> str:
        """Extract refresh token from request headers or cookies"""
        # Try to get refresh token from different sources
        refresh_token = None
        
        # 1. Check for X-Refresh-Token header
        refresh_token = request.headers.get('X-Refresh-Token')
        if refresh_token:
            return refresh_token
        
        # 2. Check for Refresh-Token header
        refresh_token = request.headers.get('Refresh-Token')
        if refresh_token:
            return refresh_token
        
        # 3. Check for refresh token in cookies
        refresh_token = request.cookies.get('refresh_token')
        if refresh_token:
            return refresh_token
        
        # 4. Check for refresh token in query parameters (for GET requests)
        if request.method == 'GET':
            refresh_token = request.query_params.get('refresh_token')
            if refresh_token:
                return refresh_token
        
        return None

    def _can_refresh_expired_token(self, payload: dict) -> bool:
        """Check if an expired token can be refreshed (within configured refresh window)"""
        exp_timestamp = payload.get('exp')
        if not exp_timestamp:
            return False
        
        exp_time = datetime.fromtimestamp(exp_timestamp)
        current_time = helpers.utcNow()
        
        # Allow refresh if token expired within configured refresh window (5% of token lifetime)
        refresh_window_seconds = max(300, int(self.jwtTokenService.access_token_expiry * 0.05))  # At least 5 minutes, or 5% of token lifetime
        refresh_window = timedelta(seconds=refresh_window_seconds)
        time_since_expiry = current_time - exp_time
        self.logger.debug(f"Time since expiry: {time_since_expiry}")
        self.logger.debug(f"Refresh window: {refresh_window}")
        return time_since_expiry <= refresh_window

    def _refresh_token(self, request: Request, token: str) -> str:
        """Legacy method - now redirects to refresh token method"""
        return self._refresh_token_using_refresh_token(request, token)
