from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import Response, JSONResponse
from abc import abstractmethod
import jwt
import os
import re
from typing import List, Union, Callable
import sys
from pathlib import Path
from anyio.streams.memory import EndOfStream
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger

class CustomBaseHttpMiddleware(BaseHTTPMiddleware):
    """Base middleware class that handles path-based logic"""
    
    def __init__(self, app, logger:Logger, protected_paths: list = None, skip_paths: list = None):
        super().__init__(app)
        self.logger = logger
        self.protected_paths = self._compile_patterns(protected_paths or [])
        self.skip_paths = self._compile_patterns(skip_paths or [])
        pass
            
    def _get_origin_from_scope(self, scope) -> str:
        """Extract Origin header value from ASGI scope headers."""
        for name, value in scope.get("headers", []):
            if name.lower() == b"origin":
                return value.decode("utf-8", errors="replace")
        return ""

    def _apply_cors_headers(self, response, origin: str):
        """Add CORS headers to a response if an origin is present."""
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
            response.headers["Access-Control-Allow-Headers"] = "*"

    async def __call__(self, scope, receive, send):
        """Override to catch ExceptionGroup and handle HTTPExceptions without traceback"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await super().__call__(scope, receive, send)
        except BaseExceptionGroup as ex:
            first_exception = ex.exceptions[0] if ex.exceptions else None
            if first_exception and isinstance(first_exception, HTTPException):
                try:
                    detail = first_exception.detail if isinstance(first_exception.detail, str) else str(first_exception.detail)
                    self.logger.error(f"HTTPException {first_exception.status_code} on {scope.get('method','?')} {scope.get('path','?')}: {detail}")
                except Exception:
                    pass
                response = JSONResponse(status_code=first_exception.status_code, content={"detail": first_exception.detail})
                self._apply_cors_headers(response, self._get_origin_from_scope(scope))
                await response(scope, receive, send)
            else:
                raise
        except HTTPException as ex:
            try:
                detail = ex.detail if isinstance(ex.detail, str) else str(ex.detail)
                self.logger.error(f"HTTPException {ex.status_code} on {scope.get('method','?')} {scope.get('path','?')}: {detail}")
            except Exception:
                pass
            response = JSONResponse(status_code=ex.status_code, content={"detail": ex.detail})
            self._apply_cors_headers(response, self._get_origin_from_scope(scope))
            await response(scope, receive, send)
            
    def _compile_patterns(self, patterns: List[Union[str, re.Pattern]]) -> List[re.Pattern]:
        """Convert string patterns to compiled regex patterns"""
        compiled_patterns = []
        
        for pattern in patterns:
            if isinstance(pattern, str):
                # Convert string to regex pattern
                if pattern.endswith('/'):
                    # Match any path that starts with this prefix (for directory paths)
                    escaped_pattern = re.escape(pattern.rstrip('/'))
                    compiled_patterns.append(re.compile(f"^{escaped_pattern}/"))
                else:
                    # Exact match for specific paths
                    compiled_patterns.append(re.compile(f"^{re.escape(pattern)}$"))
            elif isinstance(pattern, re.Pattern):
                compiled_patterns.append(pattern)
        
        return compiled_patterns
    
    def _should_skip_path(self, path: str) -> bool:
        """Check if path should skip middleware processing"""
        try:
            shouldSkip = any(pattern.match(path) for pattern in self.skip_paths)
            return shouldSkip
        except Exception as ex:
            pass

    def _is_protected_path(self, path: str) -> bool:
        """Check if path requires middleware processing"""
        try:
            isProtected = any(pattern.match(path) for pattern in self.protected_paths)
            return isProtected
        except Exception as ex:
            pass
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Base dispatch method with path-based logic"""     
        current_path = request.url.path
        current_method = request.method

        # Defensive check: ensure call_next is callable
        if call_next is None:
            self.logger.error(f"call_next is None for {current_path}")
            raise HTTPException(status_code=500, detail="Middleware chain error: call_next is None")

        try:
            if current_method == "OPTIONS":
                self.logger.debug(f"🔄 Skipping middleware for OPTIONS request to {current_path}")
                return await call_next(request)
            
            # Check if path should skip middleware processing
            if self._should_skip_path(current_path):
                self.logger.debug(f"Skipping middleware processing for: {current_path}")
                response = await call_next(request)
                return response

            # Check if path requires middleware processing
            if self._is_protected_path(current_path):
                self.logger.debug(f"Applying middleware processing for: {current_path}")
                # Call the protected path handler (to be implemented by subclasses)
                await self._handle_protected_path(request=request)
            else:
                self.logger.debug(f"Path not protected, continuing: {current_path}")
            
            # Continue with the request
            response = await call_next(request)
            
            # Post-processing for protected paths
            if self._is_protected_path(current_path):
                response = await self._post_process_protected_path(request, response)# or response
            
            return response
            
        except (EndOfStream, ConnectionError, OSError) as ex:
            # These exceptions occur when client disconnects - let them propagate naturally
            # They are not errors that should be converted to HTTP 500
            self.logger.debug(f"Client disconnected during request to {current_path}: {type(ex).__name__}")
            raise
        except HTTPException as ex:
            response = JSONResponse(status_code=ex.status_code, content={"detail": ex.detail})
            self._apply_cors_headers(response, request.headers.get('origin', ''))
            return response
        except Exception as ex:
            self.logger.error(f"CustomBaseMiddleware error for {current_path}: {str(ex)}")
            raise HTTPException(status_code=500, detail=f"Middleware error: {str(ex)}")
    
    async def _handle_protected_path(self, request: Request):
        """Handle protected path processing - to be overridden by subclasses"""
        # This method should be overridden by subclasses
        pass
    
    async def _post_process_protected_path(self, request: Request, response):
        """Post-process protected path responses - to be overridden by subclasses"""
        # This method should be overridden by subclasses
        return response