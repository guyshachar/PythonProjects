from fastapi import Request, HTTPException
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger
import shared.helpers as helpers
from rpApi.middlewares.customBaseHttpMiddleware import CustomBaseHttpMiddleware
from shared.db.cacheService import CacheService

class AuthMiddleware(CustomBaseHttpMiddleware):
    def __init__(self, app, logger:Logger, cacheService:CacheService, protected_paths: list = None, skip_paths: list = None):
        super().__init__(app=app, logger=logger, protected_paths=protected_paths, skip_paths=skip_paths)
        self.cacheService = cacheService

    async def _handle_protected_path(self, request: Request):
        self.logger.debug(f"Handling protected path: {request.url.path}")
        
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
