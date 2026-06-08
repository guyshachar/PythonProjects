# Speed Monitoring Feature Guide

This guide explains the speed monitoring functionality added to the RefPortal PWA service.

## Overview

The speed monitoring feature automatically tracks device speed using GPS/geolocation and triggers alerts when the speed exceeds a configurable threshold (default: 10 km/h).

## Features

### 🚗 **Core Functionality**
- **Real-time speed monitoring** using device GPS
- **Configurable speed threshold** (default: 10 km/h)
- **Multiple alert types**: Toast notifications, modal dialogs, and speed badge
- **Automatic permission handling** for geolocation access
- **Error handling** with user-friendly messages
- **Speed history tracking** for analytics

### 📱 **User Interface**
- **Speed Badge**: Real-time speed display in top-left corner
- **Toast Notifications**: Non-intrusive speed alerts
- **Modal Dialogs**: Important speed violation warnings
- **Visual Indicators**: Color-coded speed display (green/yellow/red)

### 🔧 **Technical Features**
- **High accuracy GPS** positioning
- **Automatic speed calculation** using Haversine formula
- **Battery optimization** with configurable update intervals
- **Error recovery** and fallback mechanisms
- **Event-driven architecture** for easy integration

## File Structure

```
rpPwa/js/
├── speed-monitor-service.js      # Core speed monitoring logic
├── speed-alert-component.js      # UI components for alerts
└── refportal-pwa.js             # Main PWA integration

rpPwa/
├── speed-test.html              # Test page for speed monitoring
└── docs/
    └── SPEED_MONITORING_GUIDE.md # This documentation
```

## Quick Start

### 1. **Automatic Integration**

The speed monitoring is automatically initialized when the PWA starts:

```javascript
// Already integrated in refportal-pwa.js
const pwa = new RefPortalPWA();
await pwa.init(); // Speed monitoring starts automatically
```

### 2. **Manual Control**

```javascript
// Start speed monitoring
await window.refPortalPwa.startSpeedMonitoring();

// Stop speed monitoring
window.refPortalPwa.stopSpeedMonitoring();

// Get current status
const status = window.refPortalPwa.getSpeedMonitoringStatus();

// Update speed threshold
window.refPortalPwa.setSpeedThreshold(15); // 15 km/h
```

### 3. **Testing**

Open the test page in your browser:
```
https://your-domain.com/speed-test.html
```

## Configuration Options

### Speed Monitor Service

```javascript
const speedMonitor = new SpeedMonitorService({
    speedThreshold: 10,        // Speed limit in km/h
    updateInterval: 1000,      // Update frequency in ms
    enableHighAccuracy: true,  // Use high accuracy GPS
    timeout: 10000,           // Geolocation timeout in ms
    maximumAge: 1000          // Cache age in ms
});
```

### Speed Alert Component

```javascript
const speedAlert = new SpeedAlertComponent({
    showToast: true,          // Show toast notifications
    showModal: true,          // Show modal dialogs
    showBadge: true,          // Show speed badge
    autoHideToast: 5000,      // Auto-hide toast after 5s
    maxToastCount: 3          // Maximum concurrent toasts
});
```

## API Reference

### SpeedMonitorService

#### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `startMonitoring()` | Start speed monitoring | None | Promise |
| `stopMonitoring()` | Stop speed monitoring | None | void |
| `getCurrentSpeed()` | Get current speed | None | number (km/h) |
| `getSpeedHistory()` | Get speed history | None | Array |
| `getAverageSpeed()` | Get average speed | None | number |
| `isExceedingThreshold()` | Check if exceeding limit | None | boolean |
| `setSpeedThreshold(threshold)` | Update speed limit | number | void |
| `getStatus()` | Get monitoring status | None | Object |
| `on(event, callback)` | Add event listener | string, function | void |
| `off(event, callback)` | Remove event listener | string, function | void |
| `cleanup()` | Cleanup resources | None | void |

#### Events

| Event | Description | Data |
|-------|-------------|------|
| `onSpeedExceeded` | Speed exceeds threshold | `{speed, threshold, position, timestamp}` |
| `onSpeedChanged` | Speed value changed | `{speed, position, isExceedingThreshold}` |
| `onError` | Error occurred | `{error, message, timestamp}` |

### SpeedAlertComponent

#### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `showSpeedAlert(data)` | Show speed alert | Object | void |
| `updateSpeed(speed)` | Update speed display | number | void |
| `clearAll()` | Clear all alerts | None | void |
| `cleanup()` | Cleanup component | None | void |

## Usage Examples

### Basic Speed Monitoring

```javascript
// Initialize speed monitoring
const speedMonitor = new SpeedMonitorService({
    speedThreshold: 10
});

// Set up event handlers
speedMonitor.on('onSpeedExceeded', (data) => {
    console.log(`Speed exceeded: ${data.speed} km/h`);
    // Handle speed violation
});

speedMonitor.on('onSpeedChanged', (data) => {
    console.log(`Current speed: ${data.speed} km/h`);
    // Update UI
});

// Start monitoring
await speedMonitor.startMonitoring();
```

### Custom Alert Handling

```javascript
// Create custom alert component
const customAlert = new SpeedAlertComponent({
    showToast: true,
    showModal: false,
    showBadge: true
});

// Handle speed exceeded
speedMonitor.on('onSpeedExceeded', (data) => {
    customAlert.showSpeedAlert(data);
    
    // Custom logic
    if (data.speed > 20) {
        // Critical speed violation
        sendEmergencyAlert(data);
    }
});
```

### Integration with Existing PWA

```javascript
// Access through main PWA instance
const pwa = window.refPortalPwa;

// Start/stop monitoring
await pwa.startSpeedMonitoring();
pwa.stopSpeedMonitoring();

// Get status
const status = pwa.getSpeedMonitoringStatus();
console.log('Monitoring:', status.isMonitoring);
console.log('Current speed:', status.currentSpeed);

// Update threshold
pwa.setSpeedThreshold(15);
```

## Browser Compatibility

### Supported Browsers
- ✅ Chrome 50+
- ✅ Firefox 45+
- ✅ Safari 10+
- ✅ Edge 79+
- ✅ Mobile browsers (iOS Safari, Chrome Mobile)

### Required Permissions
- **Geolocation**: Required for GPS access
- **HTTPS**: Required for geolocation in production

### Fallback Behavior
- Graceful degradation if geolocation unavailable
- Error messages for permission denied
- Automatic retry on temporary failures

## Security & Privacy

### Data Handling
- **No data storage**: Speed data not persisted locally
- **No tracking**: No user location tracking
- **Local processing**: All calculations done client-side
- **Optional logging**: Speed violations can be logged to server

### Permission Management
- **Explicit consent**: User must grant location permission
- **Clear messaging**: Explains why location access needed
- **Easy disable**: Can be turned off anytime

## Performance Considerations

### Battery Usage
- **Optimized intervals**: Configurable update frequency
- **High accuracy mode**: Can be disabled for battery saving
- **Automatic cleanup**: Resources released when not needed

### Memory Usage
- **Limited history**: Only recent speed data kept
- **Efficient calculations**: Optimized distance/speed algorithms
- **Event-driven**: No polling when not monitoring

## Troubleshooting

### Common Issues

#### 1. **Permission Denied**
```
Error: Geolocation permission denied
```
**Solution**: User must grant location permission in browser settings

#### 2. **No GPS Signal**
```
Error: Position unavailable
```
**Solution**: Ensure device has GPS enabled and clear sky view

#### 3. **Inaccurate Speed Readings**
```
Issue: Speed readings seem incorrect
```
**Solution**: Enable high accuracy mode and check GPS signal strength

#### 4. **Battery Drain**
```
Issue: High battery usage
```
**Solution**: Increase update interval or disable high accuracy mode

### Debug Mode

Enable debug logging:
```javascript
// Set debug mode
speedMonitor.options.debug = true;

// Check status
const status = speedMonitor.getStatus();
console.log('Speed monitor status:', status);
```

### Testing

Use the test page for debugging:
1. Open `speed-test.html` in browser
2. Grant location permission
3. Start monitoring
4. Check console for logs
5. Test with different speeds

## Configuration Examples

### Conservative Settings (Battery Saving)
```javascript
const speedMonitor = new SpeedMonitorService({
    speedThreshold: 10,
    updateInterval: 5000,      // 5 seconds
    enableHighAccuracy: false, // Lower accuracy
    timeout: 15000,           // Longer timeout
    maximumAge: 5000          // 5 second cache
});
```

### High Accuracy Settings
```javascript
const speedMonitor = new SpeedMonitorService({
    speedThreshold: 10,
    updateInterval: 500,       // 0.5 seconds
    enableHighAccuracy: true,  // High accuracy
    timeout: 5000,            // Quick timeout
    maximumAge: 100           // Fresh data only
});
```

### Custom Alert Settings
```javascript
const speedAlert = new SpeedAlertComponent({
    showToast: true,
    showModal: false,         // No modal dialogs
    showBadge: true,
    autoHideToast: 3000,      // 3 second toasts
    maxToastCount: 1          // Only one toast at a time
});
```

## Integration with Backend

### Logging Speed Violations

```javascript
// Log to server
speedMonitor.on('onSpeedExceeded', (data) => {
    fetch('/api/log-speed-violation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            speed: data.speed,
            threshold: data.threshold,
            timestamp: data.timestamp,
            position: data.position
        })
    });
});
```

### Real-time Notifications

```javascript
// Send push notification
speedMonitor.on('onSpeedExceeded', (data) => {
    if (navigator.serviceWorker) {
        navigator.serviceWorker.ready.then(registration => {
            registration.showNotification('Speed Alert', {
                body: `You are traveling at ${data.speed.toFixed(1)} km/h`,
                icon: '/icons/speed-alert.png',
                badge: '/icons/badge.png'
            });
        });
    }
});
```

## Future Enhancements

### Planned Features
- **Speed zones**: Different limits for different areas
- **Historical analytics**: Speed trend analysis
- **Custom thresholds**: User-configurable limits
- **Integration with maps**: Visual speed display
- **Voice alerts**: Audio speed warnings

### API Extensions
- **Speed zones API**: Define area-specific limits
- **Analytics API**: Speed data aggregation
- **Settings API**: User preference management
- **Notification API**: Custom alert configurations

This speed monitoring feature provides a comprehensive solution for tracking device speed in the RefPortal PWA, with robust error handling, user-friendly interfaces, and flexible configuration options.
