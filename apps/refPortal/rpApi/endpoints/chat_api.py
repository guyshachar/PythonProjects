"""
Chat API for cross-device message synchronization
Handles storing, retrieving, and syncing chat messages across devices
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
import json
import time
from datetime import datetime
import uuid

# In-memory storage for demo purposes
# In production, use a proper database like PostgreSQL or MongoDB
chat_messages_db = {}
client_sessions = {}

# Chat message model
class ChatMessage(BaseModel):
    id: int
    type: str  # 'sent', 'received', 'system'
    text: str
    timestamp: str
    clientIdentifier: Optional[str] = None
    fromMobileNo: Optional[str] = None

# Message sync request model
class MessageSyncRequest(BaseModel):
    message: ChatMessage
    fromMobileNo: Optional[str] = None
    clientIdentifier: str
    timestamp: str

# Message sync response model
class MessageSyncResponse(BaseModel):
    success: bool
    message: str
    messageId: int

# Messages response model
class MessagesResponse(BaseModel):
    messages: List[ChatMessage]
    total: int
    lastMessageId: int

# Create router
chat_router = APIRouter(prefix="/api/pwa/chat", tags=["chat"])

@chat_router.post("/sync-message")
async def sync_message(request: MessageSyncRequest):
    """
    Sync a chat message to the server for cross-device access
    """
    try:
        # Generate unique message ID if not provided
        if not request.message.id:
            request.message.id = int(time.time() * 1000)
        
        # Store message in database
        message_key = f"{request.fromMobileNo}_{request.message.id}"
        chat_messages_db[message_key] = {
            "message": request.message.dict(),
            "fromMobileNo": request.fromMobileNo,
            "clientIdentifier": request.clientIdentifier,
            "timestamp": request.timestamp,
            "synced": True
        }
        
        # Add to client's message list
        if request.fromMobileNo not in client_sessions:
            client_sessions[request.fromMobileNo] = []
        
        client_sessions[request.fromMobileNo].append(message_key)
        
        # Keep only last 100 messages per client
        if len(client_sessions[request.fromMobileNo]) > 100:
            client_sessions[request.fromMobileNo] = client_sessions[request.fromMobileNo][-100:]
        
        print(f"✅ Message synced: {request.clientIdentifier} - {request.message.text[:50]}...")
        
        return MessageSyncResponse(
            success=True,
            message="Message synced successfully",
            messageId=request.message.id
        )
        
    except Exception as e:
        print(f"❌ Error syncing message:", e)
        raise HTTPException(status_code=500, detail=f"Failed to sync message: {str(e)}")

@chat_router.get("/messages")
async def get_messages(
    fromMobileNo: str = Query(..., description="Mobile number"),
    lastMessageId: int = Query(0, description="Last message ID received")
):
    """
    Get chat messages for a specific client, starting from lastMessageId
    """
    try:
        if fromMobileNo not in client_sessions:
            return MessagesResponse(
                messages=[],
                total=0,
                lastMessageId=lastMessageId
            )
        
        # Get all message keys for this client
        message_keys = client_sessions[fromMobileNo]
        
        # Filter messages newer than lastMessageId
        new_messages = []
        for key in message_keys:
            if key in chat_messages_db:
                message_data = chat_messages_db[key]
                message = ChatMessage(**message_data["message"])
                if message.id > lastMessageId:
                    new_messages.append(message)
        
        # Sort by ID to maintain chronological order
        new_messages.sort(key=lambda x: x.id)
        
        print(f"📥 Returning {len(new_messages)} new messages for {fromMobileNo}")
        
        return MessagesResponse(
            messages=new_messages,
            total=len(new_messages),
            lastMessageId=max([msg.id for msg in new_messages]) if new_messages else lastMessageId
        )
        
    except Exception as e:
        print(f"❌ Error getting messages:", e)
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {str(e)}")

@chat_router.get("/events")
async def chat_events(
    fromMobileNo: str = Query(..., description="Mobile number")
):
    """
    Server-Sent Events endpoint for real-time chat updates
    """
    from fastapi.responses import StreamingResponse
    import asyncio
    
    async def event_generator():
        """Generate SSE events for real-time updates"""
        try:
            # Send initial connection event
            yield f"data: {json.dumps({'type': 'connected', 'fromMobileNo': fromMobileNo})}\n\n"
            
            # Keep connection alive and check for new messages
            last_check = time.time()
            while True:
                # Check for new messages every 2 seconds
                if time.time() - last_check >= 2:
                    last_check = time.time()
                    
                    # Get new messages since last check
                    if fromMobileNo in client_sessions:
                        message_keys = client_sessions[fromMobileNo]
                        for key in message_keys[-5:]:  # Check last 5 messages
                            if key in chat_messages_db:
                                message_data = chat_messages_db[key]
                                message = ChatMessage(**message_data["message"])
                                
                                # Send new message event
                                event_data = {
                                    "type": "new_message",
                                    "message": message.dict(),
                                    "timestamp": datetime.now().isoformat()
                                }
                                yield f"data: {json.dumps(event_data)}\n\n"
                
                # Keep connection alive
                await asyncio.sleep(2)
                
        except Exception as e:
            print(f"❌ SSE error for {fromMobileNo}:", e)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )

@chat_router.get("/status/{fromMobileNo}")
async def get_chat_status(fromMobileNo: str):
    """
    Get chat synchronization status for a client
    """
    try:
        if fromMobileNo not in client_sessions:
            return {
                "fromMobileNo": fromMobileNo,
                "status": "not_found",
                "messageCount": 0,
                "lastSync": None
            }
        
        message_keys = client_sessions[fromMobileNo]
        message_count = len(message_keys)
        
        # Get last sync time
        last_sync = None
        if message_keys:
            last_key = message_keys[-1]
            if last_key in chat_messages_db:
                last_sync = chat_messages_db[last_key]["timestamp"]
        
        return {
            "fromMobileNo": fromMobileNo,
            "status": "active",
            "messageCount": message_count,
            "lastSync": last_sync,
            "synced": True
        }
        
    except Exception as e:
        print(f"❌ Error getting chat status:", e)
        raise HTTPException(status_code=500, detail=f"Failed to get chat status: {str(e)}")

@chat_router.delete("/clear/{fromMobileNo}")
async def clear_chat_history(fromMobileNo: str):
    """
    Clear chat history for a specific client
    """
    try:
        if fromMobileNo in client_sessions:
            # Remove all message keys
            message_keys = client_sessions[fromMobileNo]
            for key in message_keys:
                if key in chat_messages_db:
                    del chat_messages_db[key]
            
            # Clear client session
            del client_sessions[fromMobileNo]
            
            print(f"🗑️ Chat history cleared for {fromMobileNo}")
            
            return {
                "success": True,
                "message": "Chat history cleared successfully",
                "fromMobileNo": fromMobileNo
            }
        else:
            return {
                "success": False,
                "message": "Client not found",
                "fromMobileNo": fromMobileNo
            }
            
    except Exception as e:
        print(f"❌ Error clearing chat history:", e)
        raise HTTPException(status_code=500, detail=f"Failed to clear chat history: {str(e)}")

# Health check endpoint
@chat_router.get("/health")
async def chat_health():
    """
    Health check for chat API
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "totalClients": len(client_sessions),
        "totalMessages": len(chat_messages_db),
        "features": {
            "cross_device_sync": True,
            "real_time_updates": True,
            "offline_support": True,
            "message_export": True,
            "conflict_resolution": True
        }
    }

# API info endpoint
@chat_router.get("/info")
async def chat_api_info():
    """
    Get information about the chat API capabilities
    """
    return {
        "name": "RefereeX Chat API",
        "version": "1.0.0",
        "description": "Cross-device chat synchronization API for RefereeX PWA",
        "endpoints": [
            "POST /api/chat/sync-message - Sync message to server",
            "GET /api/chat/messages - Get messages for client",
            "GET /api/chat/events - Real-time updates (SSE)",
            "GET /api/chat/status/{fromMobileNo} - Get sync status",
            "DELETE /api/chat/clear/{fromMobileNo} - Clear chat history",
            "GET /api/chat/health - Health check",
            "GET /api/chat/info - API information"
        ],
        "features": {
            "cross_device_sync": "Messages sync across all devices using same mobile number",
            "real_time_updates": "Server-Sent Events for instant message delivery",
            "offline_support": "Local storage with sync when online",
            "message_export": "Export/import chat history",
            "conflict_resolution": "Automatic duplicate detection and resolution"
        }
    }
