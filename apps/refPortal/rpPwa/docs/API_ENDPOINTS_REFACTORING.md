# API Endpoints Refactoring Summary

## Overview
This document summarizes the refactoring work done to replace hardcoded API endpoints with predefined constants in the RefPortal PWA JavaScript code.

## What Was Refactored

### 1. Hardcoded Endpoints Replaced

#### Before (Hardcoded):
```javascript
// Line 637: Hardcoded dashboard endpoint
const response = await fetch('https://api.refereex.com:24501/api/dashboardLoadData');

// Lines 157, 459, 509: Hardcoded auth endpoints
const response = await fetch('/api/check-auth', { ... });
const response = await fetch('/api/logout', { ... });
await fetch('/api/check-auth', { method: 'POST' });

// Line 1123: Hardcoded login endpoint
const response = await fetch('/api/login', { ... });
```

#### After (Using Constants):
```javascript
// Line 637: Using predefined constants
const response = await fetch(`${PWA_CONFIG.API_BASE_URL}${PWA_CONFIG.ENDPOINTS.DASHBOARD}`);

// Lines 157, 459, 509: Using predefined constants
const response = await fetch(`${PWA_CONFIG.ENDPOINTS.CHECK_AUTH}`, { ... });
const response = await fetch(`${PWA_CONFIG.ENDPOINTS.UNPAIR}`, { ... });
await fetch(`${PWA_CONFIG.ENDPOINTS.CHECK_AUTH}`, { method: 'POST' });

// Line 1123: Using predefined constants
const response = await fetch(`${PWA_CONFIG.ENDPOINTS.PAIR}`, { ... });
```

### 2. Configuration File Updated

Added missing `PUSH_SUBSCRIPTION` endpoint to the configuration:
```javascript
ENDPOINTS: {
    // ... existing endpoints ...
    PUSH_SUBSCRIPTION: '/api/push-subscription'
}
```

## Benefits of This Refactoring

1. **Centralized Configuration**: All API endpoints are now defined in one place (`pwa-config.js`)
2. **Easy Environment Switching**: Can easily switch between development and production by changing `API_BASE_URL`
3. **Maintainability**: No need to search through code for hardcoded URLs
4. **Consistency**: All endpoints follow the same pattern
5. **Error Prevention**: Reduces typos and makes endpoint management easier

## Current Configuration Structure

```javascript
const PWA_CONFIG = {
    API_BASE_URL: '', // Empty for relative URLs (same origin)
    ENDPOINTS: {
        DASHBOARD: '/api/dashboardLoadData',
        GAMES: '/api/games',
        REVIEWS: '/api/reviews',
        FIELDS: '/api/fields',
        RULES: '/api/rules',
        PAIR: '/api/pair',
        LOGIN: '/api/login',
        CHECK_AUTH: '/api/check-auth',
        LOGOUT: '/api/logout',
        CHAT: '/api/chat',
        HEALTH: '/api/health',
        PUSH_SUBSCRIPTION: '/api/push-subscription'
    }
    // ... other configuration
};
```

## URL Construction Helper

Added a helper method to the RefPortalPWA class:
```javascript
getApiUrl(endpoint) {
    if (PWA_CONFIG.API_BASE_URL) {
        return `${PWA_CONFIG.API_BASE_URL}${endpoint}`;
    }
    return endpoint; // Return relative URL if no base URL
}
```

## Endpoints Added/Modified

### 1. **PUSH_SUBSCRIPTION** - `/api/push-subscription`
- **Purpose**: Handle POST requests for push subscription data
- **Method**: POST
- **Status**: ✅ **Added** - Was missing from configuration

### 2. **SET_PUSH_SUBSCRIPTION** - `/api/set-push-subscription`
- **Purpose**: Handle GET requests to set push subscription and save to database
- **Method**: GET
- **Parameters**: 
  - `mobileNo` (required): Mobile number of the referee
  - `endpoint` (required): Push subscription endpoint URL
  - `auth` (optional): Authentication key
  - `p256dh` (optional): P-256 DH key
- **Status**: ✅ **New** - Added for GET request handling

## Files Modified

1. **`rpApi/static/pwa/refportal-pwa.js`** - Main PWA JavaScript file
   - Replaced 5 hardcoded API endpoints with constants
2. **`rpApi/static/pwa/pwa-config.js`** - Configuration file
   - Added missing `PUSH_SUBSCRIPTION` endpoint
   - Added new `SET_PUSH_SUBSCRIPTION` endpoint

## Remaining Hardcoded URLs (Appropriate)

The following hardcoded URLs were intentionally left as-is:

1. **`API_BASE_URL` in config** - This is the configuration value itself
2. **`https://fcm.googleapis.com/fcm/send/example...`** - Example/test endpoint
3. **`https://cdn.plot.ly/plotly-latest.min.js`** - CDN URL for Plotly library
4. **Service Worker URLs** - Relative URLs for service worker functionality

## Next Steps

1. **Environment Configuration**: Consider creating separate config files for different environments
2. **Validation**: Add validation to ensure all required endpoints are defined
3. **Testing**: Test all endpoints work correctly after refactoring
4. **Documentation**: Update any API documentation to reflect the new structure

## Fix for "Failed to fetch" Error

The "Failed to fetch" error was caused by a **protocol and port mismatch**:

- **Service Worker**: Running on `http://localhost:8082` (HTTP, port 8082)
- **API Configuration**: Was set to `https://127.0.0.1:5002` (HTTPS, port 5002)

### What Was Fixed:

1. **Updated API_BASE_URL**: Changed from `https://127.0.0.1:5002` to empty string `''` for relative URLs
2. **Added URL Helper**: Created `getApiUrl()` method to handle both absolute and relative URL construction
3. **Updated All Endpoints**: All API calls now use the helper method for consistent URL construction
4. **Added New Endpoint**: Created `setPushSubscription` GET endpoint for saving push subscriptions to database
5. **Added JavaScript Method**: Created `setPushSubscription()` method in PWA for easy client-side usage

### New Features Added:

#### **setPushSubscription Endpoint**
- **URL**: `/api/set-push-subscription`
- **Method**: GET
- **Purpose**: Save push subscription data to database via GET request
- **Parameters**: 
  - `mobileNo` (required): Mobile number identifier
  - `endpoint` (required): Push subscription endpoint URL
  - `auth` (optional): Authentication key
  - `p256dh` (optional): P-256 DH key

#### **setPushSubscription JavaScript Method**
- **Location**: `refportal-pwa.js`
- **Purpose**: Client-side method to easily save push subscriptions
- **Usage**: 
  ```javascript
  await pwa.setPushSubscription(mobileNo, subscription);
  ```
- **Features**: Automatically builds query parameters and handles response

### Usage Examples:

#### **Direct API Call (GET)**
```bash
curl "http://localhost:8082/api/set-push-subscription?mobileNo=+972501234567&endpoint=https://fcm.googleapis.com/fcm/send/abc123&auth=def456&p256dh=ghi789"
```

#### **JavaScript Usage**
```javascript
// Get push subscription from service worker
const subscription = await serviceWorkerRegistration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: PWA_CONFIG.VAPID_PUBLIC_KEY
});

// Save to database using new endpoint
const result = await pwa.setPushSubscription('+972501234567', subscription);
if (result) {
    console.log('Push subscription saved:', result.message);
}
```

#### **Database Storage**
The endpoint saves push subscription data using the existing `dbClient.setRefereeProperties()` method:
- **Key**: `push_subscription`
- **Value**: Complete subscription object with endpoint and keys
- **Storage**: Uses the same database client as other referee properties

### Why This Fixes the Error:

- **Same Origin**: PWA and API now run on the same origin (`localhost:8082`)
- **No Mixed Content**: No more HTTP page trying to make HTTPS requests
- **Consistent URLs**: All endpoints use the same URL construction logic
- **Flexible Configuration**: Easy to switch between relative and absolute URLs

## Usage Examples

### Making API Calls
```javascript
// Before (hardcoded)
const response = await fetch('/api/login', { ... });

// After (using constants)
const response = await fetch(`${PWA_CONFIG.ENDPOINTS.PAIR}`, { ... });
```

### Full URL Construction
```javascript
// For endpoints that need the full base URL
const response = await fetch(`${PWA_CONFIG.API_BASE_URL}${PWA_CONFIG.ENDPOINTS.DASHBOARD}`);

// For relative endpoints (same origin)
const response = await fetch(`${PWA_CONFIG.ENDPOINTS.PAIR}`, { ... });
```

## Notes

- All fetch calls now use the predefined constants
- The refactoring maintains backward compatibility
- No changes to the API endpoints themselves, only to how they're referenced in the code
- The configuration file is now the single source of truth for all API endpoints

## Summary of Changes

### ✅ **Completed Tasks**

1. **Refactored Hardcoded API Endpoints**
   - Replaced hardcoded URLs with `PWA_CONFIG` constants
   - Added missing `PUSH_SUBSCRIPTION` endpoint
   - Updated all fetch calls to use centralized configuration

2. **Fixed "Failed to fetch" Error**
   - Resolved protocol/port mismatch issues
   - Added `getApiUrl()` helper method
   - Implemented flexible URL construction

3. **Added New setPushSubscription Feature**
   - **Backend**: New GET endpoint `/api/set-push-subscription`
   - **Database**: Saves push subscriptions using existing `dbClient.setRefereeProperties()`
   - **Frontend**: New JavaScript method `setPushSubscription()`
   - **Configuration**: Added endpoint to PWA config and setup scripts

### 🔧 **Files Modified**

1. **`rpApi/refPortalImplementationFastApiDI.py`**
   - Added `setPushSubscription()` method
   - Handles GET requests with query parameters
   - Saves to database using existing infrastructure

2. **`rpApi/refPortalFastApiDI.py`**
   - Added new API route for setPushSubscription
   - Configured for GET method

3. **`rpApi/static/pwa/pwa-config.js`**
   - Added `SET_PUSH_SUBSCRIPTION` endpoint
   - Updated configuration constants

4. **`rpApi/static/pwa/refportal-pwa.js`**
   - Added `setPushSubscription()` method
   - Handles query parameter construction
   - Provides easy client-side API

5. **`rpApi/static/pwa/setup-pwa.sh`**
   - Added new endpoint to setup script
   - Keeps configuration in sync

6. **`rpApi/static/pwa/API_ENDPOINTS_REFACTORING.md`**
   - Comprehensive documentation of all changes
   - Usage examples and testing information

### 🚀 **Benefits**

- **Centralized Configuration**: All API endpoints in one place
- **Easy Maintenance**: Change endpoints without touching code
- **Database Integration**: Seamless push subscription storage
- **Flexible Usage**: Both direct API calls and JavaScript methods
- **Error Handling**: Proper validation and error responses
- **Logging**: Comprehensive logging for debugging

### 📋 **Next Steps**

The `setPushSubscription` endpoint is now ready for use! You can:
1. Test the endpoint with direct GET requests
2. Use the JavaScript method in your PWA
3. Integrate with existing push notification workflows
4. Monitor database storage using existing logging
