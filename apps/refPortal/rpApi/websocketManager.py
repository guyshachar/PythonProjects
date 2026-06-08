# Create new file: rpApi/websocket/websocketManager.py
import asyncio
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from pathlib import Path
import sys
from contextlib import asynccontextmanager
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger

class WebSocketManager:
    """Manages WebSocket connections for real-time JWT token delivery"""
    
    def __init__(self, logger: Logger):
        self.logger = logger
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_identifiers: Dict[WebSocket, str] = {}
        
    async def connect(self, websocket: WebSocket, client_identifier: str):
        """Accept WebSocket connection and store it"""
        registered = False
        try:
            await websocket.accept()
            self.active_connections[client_identifier] = websocket
            self.client_identifiers[websocket] = client_identifier
            registered = True

            self.logger.info(f"🔌 WebSocket connected on server for client: {client_identifier}")

            # Send connection confirmation (client may disconnect immediately — common, not an error)
            await websocket.send_json({
                "type": "connection_established",
                "client_identifier": client_identifier,
                "message": "WebSocket connection ready for JWT token"
            })

        except WebSocketDisconnect:
            if registered:
                await self.disconnect(websocket)
            self.logger.info(
                f"WebSocket disconnected during handshake for client: {client_identifier}"
            )
            raise
        except Exception as ex:
            if registered:
                await self.disconnect(websocket)
            self.logger.error(f"Error accepting WebSocket connection", ex)
            raise
    
    async def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        try:
            client_identifier = self.client_identifiers.get(websocket)
            if client_identifier:
                if client_identifier in self.active_connections:
                    del self.active_connections[client_identifier]
                if websocket in self.client_identifiers:
                    del self.client_identifiers[websocket]
                self.logger.info(f"🔌 WebSocket disconnected for client: {client_identifier}")
        except Exception as ex:
            self.logger.error(f"Error disconnecting WebSocket", ex)
    
    async def send_jwt_token(self, client_identifier: str, access_token: str, refresh_token: str = None, 
                           access_expires_in: int = 86400, refresh_expires_in: int = 2592000):
        """Send JWT token pair (access + refresh) to specific client"""
        try:
            websocket = self.active_connections.get(client_identifier)
            if websocket:
                message = {
                    "type": "jwt_token_pair",
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "access_expires_in": access_expires_in,
                    "refresh_expires_in": refresh_expires_in,
                    "timestamp": asyncio.get_event_loop().time()
                }
                
                await websocket.send_json(message)
                self.logger.info(f"✅ JWT token pair sent via WebSocket to {client_identifier}")
                self.logger.debug(f"Access token expires in: {access_expires_in}s, Refresh token expires in: {refresh_expires_in}s")
                return True
            else:
                self.logger.warning(f"⚠️ No WebSocket connection for client: {client_identifier}")
                return False
                
        except Exception as ex:
            self.logger.error(f"Error sending JWT token pair via WebSocket", ex)
            return False
    
    async def broadcast_message(self, message: dict, exclude_client: str = None):
        """Broadcast message to all connected clients"""
        disconnected_clients = []
        
        for client_identifier, websocket in self.active_connections.items():
            if client_identifier != exclude_client:
                try:
                    await websocket.send_json(message)
                except Exception as ex:
                    self.logger.error(f"Error broadcasting to {client_identifier}", ex)
                    disconnected_clients.append(client_identifier)
        
        # Clean up disconnected clients
        for client_identifier in disconnected_clients:
            websocket = self.active_connections.get(client_identifier)
            if websocket:
                await self.disconnect(websocket)
    
    def get_connected_clients(self) -> Set[str]:
        """Get list of connected client identifiers"""
        return set(self.active_connections.keys())
    
    def is_client_connected(self, client_identifier: str) -> bool:
        """Check if specific client is connected"""
        self.logger.debug(f"is_client_connected={client_identifier} in {self.active_connections}")
        return client_identifier in self.active_connections