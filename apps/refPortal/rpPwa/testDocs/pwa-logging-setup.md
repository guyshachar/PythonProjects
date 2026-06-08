# iPhone PWA Console Logging Setup

## Quick Setup (2 minutes)

### 1. Import the Logger in your main PWA file

Add this to the top of `refportal-pwa.js`:

```javascript
import { IPhoneLogger } from './iphone-logger.js';
```

### 2. Initialize the Logger

In your RefPortalPWA constructor, add:

```javascript
constructor() {
    // ... existing code ...
    
    // Initialize iPhone logger
    this.iphoneLogger = new IPhoneLogger(this.jwtWebSocket);
    
    // ... rest of constructor ...
}
```

### 3. That's it! Your logs are now being sent to your server.

## What Gets Logged

- ✅ All console.log, console.error, console.warn, console.info
- ✅ Unhandled JavaScript errors
- ✅ Unhandled promise rejections
- ✅ App visibility changes (when user switches apps)
- ✅ Network status changes
- ✅ PWA installation events
- ✅ Critical errors (sent immediately)

## Monitoring Methods

### Method 1: Server-Side Logs (Recommended)
Your existing `sendLog` function sends logs to your server. Check your server logs to see iPhone PWA activity.

### Method 2: Safari Web Inspector (For Development)
1. Connect iPhone to Mac via USB
2. Open Safari on Mac
3. Go to Develop menu → [Your iPhone] → [Your PWA]
4. View console logs in real-time

### Method 3: Remote Debugging
1. Enable "Web Inspector" in iPhone Settings → Safari → Advanced
2. Use Safari Web Inspector on Mac
3. Or use remote debugging tools like Weinre or Vorlon.js

### Method 4: Visual Debug Panel
Add a debug panel to your PWA that shows recent logs:

```javascript
// Add this to your PWA for visual debugging
showLogs() {
    const logs = this.iphoneLogger.getLogBuffer();
    console.table(logs);
    // Or display in a modal/panel
}
```

## Advanced Features

### Send Logs Manually
```javascript
// Send all buffered logs immediately
this.iphoneLogger.sendBufferedLogs();
```

### Get Log Buffer
```javascript
// Get current logs without sending
const logs = this.iphoneLogger.getLogBuffer();
console.table(logs);
```

### Enable/Disable Logging
```javascript
// Disable logging
this.iphoneLogger.setEnabled(false);

// Re-enable logging
this.iphoneLogger.setEnabled(true);
```

## Server-Side Log Handling

Your server receives logs with this format:
```json
{
  "type": "log",
  "logType": "PWA_LOG",
  "log": "{\"level\":\"ERROR\",\"message\":\"Something went wrong\",\"timestamp\":\"2024-01-01T12:00:00.000Z\",\"userAgent\":\"...\",\"url\":\"...\",\"isPWA\":true,\"isOnline\":true}",
  "timestamp": 1704110400000
}
```

## Troubleshooting

### Logs not appearing?
1. Check WebSocket connection: `this.jwtWebSocket.connectionState`
2. Check if logger is enabled: `this.iphoneLogger.isEnabled`
3. Check server logs for received messages

### Too many logs?
- Adjust `maxBufferSize` in iphone-logger.js
- Filter logs by level (only send ERROR logs)
- Add rate limiting

### Performance impact?
- Logger is lightweight and only captures console calls
- Buffers logs to avoid excessive server calls
- Can be disabled in production if needed
