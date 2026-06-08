# Chat API Integration for RefereeX PWA

## Overview

This document describes the cross-device chat synchronization API that has been integrated into the RefereeX PWA system. The chat API enables real-time message synchronization across multiple devices using the same mobile number.

## Architecture

### Frontend (PWA)
- **Real-time sync**: Messages sync automatically across devices
- **Offline support**: Messages stored locally when offline, sync when online
- **Conflict resolution**: Automatic handling of duplicate messages
- **Export/Import**: Backup and restore chat history

### Backend (FastAPI)
- **RESTful endpoints**: Standard HTTP API for message operations
- **Server-Sent Events**: Real-time updates using SSE
- **Client identification**: Unique device IDs for message routing
- **Message storage**: In-memory storage (can be upgraded to database)

## API Endpoints

### 1. Message Synchronization
```
POST /api/chat/sync-message
```
Syncs a message to the server for cross-device access.

**Request Body:**
```json
{
  "message": {
    "id": 1234567890,
    "type": "sent",
    "text": "Hello from device 1",
    "timestamp": "2024-01-15T10:30:00Z"
  },
  "clientIdentifier": "device_123",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### 2. Message Retrieval
```
GET /api/chat/messages?clientIdentifier={id}&lastMessageId={id}
```
Retrieves messages for a specific client, starting from a given message ID.

**Query Parameters:**
- `clientIdentifier`: Unique device identifier
- `lastMessageId`: Last message ID received (for incremental sync)

### 3. Real-time Updates
```
GET /api/chat/events?clientIdentifier={id}
```
Server-Sent Events endpoint for real-time message delivery.

**Response Format:**
```
data: {"type": "new_message", "message": {...}, "timestamp": "..."}

data: {"type": "connected", "clientIdentifier": "..."}
```

### 4. Status Check
```
GET /api/chat/status/{clientIdentifier}
```
Gets synchronization status for a specific client.

### 5. Health Check
```
GET /api/chat/health
```
Returns API health status and statistics.

### 6. API Information
```
GET /api/chat/info
```
Returns detailed information about API capabilities and endpoints.

## Integration Points

### FastAPI Application
The chat API is integrated into the main FastAPI application in `refPortalFastApiDI.py`:

```python
# Chat API routes for cross-device synchronization
try:
    if chat_router:
        self.app.include_router(chat_router)
        self.logger.info("✅ Chat API router included successfully")
    else:
        self.logger.warning("⚠️ Chat API router not available - chat sync will not work")
except Exception as e:
    self.logger.error(f"❌ Error including chat API router:", e)
    self.logger.warning("⚠️ Chat synchronization will not be available")
```

### PWA Frontend
The PWA includes comprehensive chat synchronization features:

- **Automatic sync**: Messages sync every 5 seconds when online
- **Real-time updates**: SSE connection for instant message delivery
- **Offline handling**: Graceful degradation when network unavailable
- **Conflict resolution**: Smart merging of messages from multiple sources

## Usage Examples

### Basic Message Sync
```javascript
// Send message and sync to server
const message = {
    id: Date.now(),
    type: 'sent',
    text: 'Hello from this device',
    timestamp: new Date().toISOString()
};

// Sync to server
await fetch('/api/chat/sync-message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        message: message,
        clientIdentifier: 'device_123',
        timestamp: new Date().toISOString()
    })
});
```

### Real-time Updates
```javascript
// Connect to real-time updates
const eventSource = new EventSource('/api/chat/events?clientIdentifier=device_123');

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'new_message') {
        console.log('New message received:', data.message);
        // Handle new message
    }
};
```

## Testing

### Test Script
Run the integration test script to verify everything works:

```bash
cd rpApi
python test_chat_integration.py
```

### Manual Testing
1. Open the PWA in multiple browsers/devices
2. Login with the same mobile number
3. Send messages in one device
4. Verify they appear in other devices
5. Test offline/online scenarios

## Configuration

### Environment Variables
No additional environment variables are required for basic functionality.

### Production Considerations
- **Database**: Replace in-memory storage with PostgreSQL/MongoDB
- **Authentication**: Add user authentication to chat endpoints
- **Rate limiting**: Implement API rate limiting
- **Monitoring**: Add metrics and logging
- **Scaling**: Consider Redis for message queuing

## Troubleshooting

### Common Issues

1. **Chat router not included**
   - Check import paths in `refPortalFastApiDI.py`
   - Verify `chat_api.py` exists in `rpApi` directory

2. **Messages not syncing**
   - Check network connectivity
   - Verify client identifier is consistent
   - Check browser console for errors

3. **Real-time updates not working**
   - Verify SSE endpoint is accessible
   - Check CORS configuration
   - Test with different browsers

### Debug Information
- Check FastAPI logs for chat API messages
- Use browser developer tools to monitor network requests
- Verify client identifiers are unique per device

## Future Enhancements

- **Message encryption**: End-to-end encryption for privacy
- **File attachments**: Support for images and documents
- **Group chats**: Multi-user conversation support
- **Push notifications**: Native push for new messages
- **Message search**: Full-text search capabilities
- **Read receipts**: Message delivery and read status

## Support

For issues or questions about the chat API integration:
1. Check the logs for error messages
2. Run the test script to verify functionality
3. Review this documentation for configuration details
4. Check browser console for frontend errors
