from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request
import time
import datetime
import os
import re

# --- New Middleware for Measuring Request Duration ---
class ProcessTimeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger):
        super().__init__(app)
        self.logger = logger

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        if request.method == 'OPTIONS':
            return response
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        self.logger.info(f"Request {request.method} {request.url.path} processed in {process_time:.4f} secs - Status {response.status_code}")
        return response
 
 # --- New Middleware to Fix Proxy Headers in Docker Swarm ---
class SwarmProxyHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger):
        super().__init__(app)
        self.logger = logger

    async def dispatch(self, request: Request, call_next):
        # Check for the X-Forwarded-Proto header set by proxies
        x_forwarded_proto = request.headers.get("x-forwarded-proto")
        if x_forwarded_proto:
            # If the header is present, update the request's scope
            # This is what tells FastAPI the original request was HTTPS
            request.scope["scheme"] = x_forwarded_proto

        response = await call_next(request)
        return response

class LogRequestsAndCorsMiddleware(BaseHTTPMiddleware):
    # Suspicious patterns that indicate exploit attempts or security scans
    SUSPICIOUS_PATTERNS = [
        r'\.php$',  # PHP files
        r'wp-admin',  # WordPress admin
        r'wp-content',  # WordPress content
        r'wp-includes',  # WordPress includes
        r'\.(asp|aspx|jsp|cgi)$',  # Other server-side scripts
        r'/(admin|administrator|phpmyadmin|mysql|sql)',  # Admin panels
        r'/(\.env|\.git|\.svn|\.htaccess)',  # Hidden/config files
        r'/(shell|cmd|exec|eval)',  # Command execution attempts
        r'/(gifclass|nox|xmlrpc)',  # Common exploit paths
    ]
    
    def __init__(self, app, logger, cors_origins_func):
        super().__init__(app)
        self.logger = logger
        self.cors_origins_func = cors_origins_func
        self.suspicious_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.SUSPICIOUS_PATTERNS]

    def _is_suspicious_request(self, path: str) -> bool:
        """Check if the request path matches suspicious patterns"""
        path_lower = path.lower()
        suspicious = any(pattern.search(path_lower) for pattern in self.suspicious_patterns)
        return suspicious

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get('origin', 'no-origin')
        path = request.url.path
        body = await request.body()
        client_ip = request.client.host if request.client else 'unknown'
        user_agent = request.headers.get('user-agent', 'unknown')
        
        # Check for suspicious requests
        is_suspicious = self._is_suspicious_request(path)
        
        if is_suspicious:
            # Log security warning for suspicious requests
            self.logger.warning(
                f"🚨 SECURITY ALERT: Suspicious request detected - "
                f"Method: {request.method}, Path: {path}, "
                f"Origin: {origin}, IP: {client_ip}, "
                f"User-Agent: {user_agent}"
            )
        else:
            pass
        
        try:
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)

            if is_suspicious:
                if response.status_code == 405:
                    self.logger.warning(
                        f"🚨 Blocked suspicious request (405): {request.method} {path} "
                        f"from IP: {client_ip}, User-Agent: {user_agent}"
                    )
            else:
                # Normal request logging
                self.logger.info(f"📡 Request: {request.method} {path} from origin: {origin} processed in {process_time:.4f} secs")

            # Force CORS headers if not already set
            if 'access-control-allow-origin' not in response.headers:
                cors_origins = self.cors_origins_func()
                if origin in cors_origins or "*" in cors_origins:
                    response.headers["Access-Control-Allow-Origin"] = origin if origin != 'no-origin' else "*"
                    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
                    response.headers["Access-Control-Allow-Headers"] = "*"
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                    self.logger.debug(f"🔧 Added CORS headers for origin: {origin}")
            
            return response
            
        except Exception as ex:
            # Log the exception but let FastAPI's global exception handler handle it
            # Re-raise the exception so it can be caught by the global exception handler
            # This prevents conflicts and ensures consistent error handling
            try:
                if is_suspicious:
                    self.logger.warning(
                        f"🚨 Exception in suspicious request: {request.method} {path} "
                        f"from IP: {client_ip}", ex
                    )
                else:
                    self.logger.error(f"❌ Exception in middleware for {request.method} {path} body={body}", ex)
            except Exception:
                # If logging fails, continue anyway
                pass
            # Re-raise to let global exception handler deal with it
            raise


def _get_client_ip(request: Request) -> str:
    """Client IP: first entry of X-Forwarded-For if present (behind proxy), else request.client.host."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip:
            return first_ip
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"

def _parse_ip_blacklist() -> set:
    """Comma-separated IP_BLACKLIST env var, e.g. IP_BLACKLIST=10.0.185.3,192.168.1.1"""
    raw = os.getenv("IP_BLACKLIST", "").strip()
    if not raw:
        return set()
    return {ip.strip() for ip in raw.split(",") if ip.strip()}

# Throttle blacklist block logging to at most once per 60s per IP
_BLACKLIST_LOG_THROTTLE_SEC = 60
_blacklist_log_last = {}

class IpBlacklistMiddleware(BaseHTTPMiddleware):
    """Reject requests from blacklisted IPs with 403. Configure via env IP_BLACKLIST (comma-separated)."""

    def __init__(self, app, logger=None):
        super().__init__(app)
        self.logger = logger
        self._blacklist = _parse_ip_blacklist()
        if self._blacklist and self.logger:
            self.logger.info(f"IP blacklist enabled: {len(self._blacklist)} address(es)")

    def _should_log_block(self, client_ip: str) -> bool:
        now = time.monotonic()
        last = _blacklist_log_last.get(client_ip, 0)
        if now - last >= _BLACKLIST_LOG_THROTTLE_SEC:
            _blacklist_log_last[client_ip] = now
            if len(_blacklist_log_last) > 500:
                _blacklist_log_last.clear()
            return True
        return False

    async def dispatch(self, request: Request, call_next):
        if not self._blacklist:
            return await call_next(request)
        client_ip = _get_client_ip(request)
        if client_ip in self._blacklist:
            if self.logger and self._should_log_block(client_ip):
                self.logger.warning(f"Blocked blacklisted IP: {client_ip} (further blocks logged at most once per {_BLACKLIST_LOG_THROTTLE_SEC}s)")
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden", "error": "Access denied"},
            )
        return await call_next(request)
