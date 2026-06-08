# Client-Side Environment Variables Guide

This guide explains how to inject and use environment variables in your client-side JavaScript files.

## Overview

The client-side environment system provides multiple ways to access environment variables in your PWA:

1. **Static File**: Pre-generated `client-env.js` file
2. **Dynamic API**: Real-time environment via `/api/client-env` endpoint
3. **Environment Loader**: Automatic loading and caching
4. **Environment Utils**: Easy-to-use utility functions

## Quick Start

### 1. Include the Scripts

Add these scripts to your HTML file:

```html
<!DOCTYPE html>
<html>
<head>
    <!-- Other head elements -->
    
    <!-- Environment utilities (load first) -->
    <script src="./js/environment-loader.js"></script>
    <script src="./js/client-env-utils.js"></script>
    
    <!-- Your other scripts -->
    <script src="./js/refportal-pwa.js"></script>
</head>
<body>
    <!-- Your content -->
</body>
</html>
```

### 2. Use Environment Variables

```javascript
// Wait for environment to be ready
await window.clientEnv.waitForReady();

// Get environment variables
const apiUrl = window.clientEnv.getApiBaseUrl();
const isDebug = window.clientEnv.isDebug();
const appName = window.clientEnv.getAppName();

// Use in your code
if (window.clientEnv.isDebug()) {
    console.log('Debug mode enabled');
}

// Make API calls
fetch(`${window.clientEnv.getApiBaseUrl()}/api/data`)
    .then(response => response.json())
    .then(data => console.log(data));
```

## Available Environment Variables

### Server Configuration
- `PWA_HTTP_PORT` - HTTP server port
- `PWA_HTTPS_PORT` - HTTPS server port
- `PWA_BASE_URL` - PWA base URL
- `API_BASE_URL` - API base URL

### Application Configuration
- `NODE_ENV` - Environment (development, production, staging)
- `DEBUG_MODE` - Debug mode flag
- `VERSION` - Application version
- `BUILD_TIME` - Build timestamp

### Feature Flags
- `FEATURES.PUSH_NOTIFICATIONS` - Push notifications enabled
- `FEATURES.OFFLINE_SUPPORT` - Offline support enabled
- `FEATURES.BACKGROUND_SYNC` - Background sync enabled
- `FEATURES.INSTALL_PROMPT` - Install prompt enabled

### App Information
- `APP_NAME` - Application name
- `APP_SHORT_NAME` - Application short name

## Usage Methods

### Method 1: Environment Utils (Recommended)

```javascript
// Check if environment is ready
if (window.clientEnv.isReady()) {
    const apiUrl = window.clientEnv.getApiBaseUrl();
    const isDebug = window.clientEnv.isDebug();
}

// Wait for environment to be ready
await window.clientEnv.waitForReady();
const apiUrl = window.clientEnv.getApiBaseUrl();

// Get specific environment variable
const nodeEnv = window.clientEnv.get('NODE_ENV', 'development');

// Check feature flags
if (window.clientEnv.isFeatureEnabled('PUSH_NOTIFICATIONS')) {
    // Enable push notifications
}

// Get all environment variables
const allEnv = window.clientEnv.getAll();
```

### Method 2: Environment Loader

```javascript
// Load environment
const env = await window.envLoader.load();

// Get environment variable
const apiUrl = env.API_BASE_URL;

// Listen for environment changes
window.envLoader.addListener((env, error) => {
    if (error) {
        console.error('Environment load error:', error);
    } else {
        console.log('Environment loaded:', env);
    }
});

// Reload environment
await window.envLoader.reload();
```

### Method 3: Direct Access

```javascript
// Access pre-loaded environment
if (window.CLIENT_ENV) {
    const apiUrl = window.CLIENT_ENV.API_BASE_URL;
    const isDebug = window.CLIENT_ENV.DEBUG_MODE;
}

// Or use the global instance
if (window.clientEnv && window.clientEnv.isLoaded()) {
    const env = window.clientEnv.getAll();
}
```

### Method 4: Fetch from API

```javascript
// Fetch environment from API
async function loadEnvironment() {
    try {
        const response = await fetch('/api/client-env');
        const env = await response.json();
        
        // Use environment variables
        const apiUrl = env.API_BASE_URL;
        const isDebug = env.DEBUG_MODE;
        
        return env;
    } catch (error) {
        console.error('Failed to load environment:', error);
        return null;
    }
}

// Use it
loadEnvironment().then(env => {
    if (env) {
        console.log('Environment loaded:', env);
    }
});
```

## Practical Examples

### API Service with Environment Variables

```javascript
class ApiService {
    constructor() {
        this.baseUrl = null;
        this.init();
    }

    async init() {
        await window.clientEnv.waitForReady();
        this.baseUrl = window.clientEnv.getApiBaseUrl();
    }

    async get(endpoint) {
        const url = `${this.baseUrl}${endpoint}`;
        const response = await fetch(url);
        return response.json();
    }

    async post(endpoint, data) {
        const url = `${this.baseUrl}${endpoint}`;
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        return response.json();
    }
}

// Usage
const apiService = new ApiService();
apiService.get('/api/users').then(users => {
    console.log('Users:', users);
});
```

### Feature Flag Usage

```javascript
class FeatureManager {
    constructor() {
        this.env = null;
        this.init();
    }

    async init() {
        await window.clientEnv.waitForReady();
        this.env = window.clientEnv;
    }

    isPushNotificationsEnabled() {
        return this.env.isFeatureEnabled('PUSH_NOTIFICATIONS');
    }

    isOfflineSupportEnabled() {
        return this.env.isFeatureEnabled('OFFLINE_SUPPORT');
    }

    isDebugMode() {
        return this.env.isDebug();
    }

    async initializeFeatures() {
        if (this.isPushNotificationsEnabled()) {
            await this.initializePushNotifications();
        }

        if (this.isOfflineSupportEnabled()) {
            await this.initializeOfflineSupport();
        }

        if (this.isDebugMode()) {
            this.initializeDebugTools();
        }
    }

    async initializePushNotifications() {
        // Push notification initialization
        console.log('Initializing push notifications...');
    }

    async initializeOfflineSupport() {
        // Offline support initialization
        console.log('Initializing offline support...');
    }

    initializeDebugTools() {
        // Debug tools initialization
        console.log('Initializing debug tools...');
    }
}

// Usage
const featureManager = new FeatureManager();
featureManager.initializeFeatures();
```

### Environment-Specific Configuration

```javascript
class AppConfig {
    constructor() {
        this.config = null;
        this.init();
    }

    async init() {
        await window.clientEnv.waitForReady();
        this.config = this.buildConfig();
    }

    buildConfig() {
        const env = window.clientEnv;
        
        return {
            api: {
                baseUrl: env.getApiBaseUrl(),
                timeout: env.isProduction() ? 30000 : 10000,
                retries: env.isProduction() ? 3 : 1
            },
            logging: {
                level: env.isDebug() ? 'debug' : 'info',
                console: env.isDebug(),
                remote: env.isProduction()
            },
            features: {
                pushNotifications: env.isFeatureEnabled('PUSH_NOTIFICATIONS'),
                offlineSupport: env.isFeatureEnabled('OFFLINE_SUPPORT'),
                backgroundSync: env.isFeatureEnabled('BACKGROUND_SYNC')
            },
            ui: {
                showDebugInfo: env.isDebug(),
                enableAnimations: !env.isProduction(),
                theme: env.get('THEME', 'light')
            }
        };
    }

    get(key, defaultValue = null) {
        return this.config[key] !== undefined ? this.config[key] : defaultValue;
    }
}

// Usage
const appConfig = new AppConfig();
appConfig.init().then(() => {
    const apiConfig = appConfig.get('api');
    console.log('API Config:', apiConfig);
});
```

## Environment-Specific Configurations

### Development Environment
```javascript
// .env file
NODE_ENV=development
DEBUG_MODE=true
API_BASE_URL=http://localhost:8000
PWA_BASE_URL=http://localhost:3000
```

### Production Environment
```javascript
// .env file
NODE_ENV=production
DEBUG_MODE=false
API_BASE_URL=https://api.yourdomain.com
PWA_BASE_URL=https://yourdomain.com
```

### Staging Environment
```javascript
// .env file
NODE_ENV=staging
DEBUG_MODE=true
API_BASE_URL=https://staging-api.yourdomain.com
PWA_BASE_URL=https://staging.yourdomain.com
```

## Best Practices

### 1. Always Wait for Environment
```javascript
// Good
await window.clientEnv.waitForReady();
const apiUrl = window.clientEnv.getApiBaseUrl();

// Bad
const apiUrl = window.clientEnv.getApiBaseUrl(); // May be undefined
```

### 2. Use Feature Flags
```javascript
// Good
if (window.clientEnv.isFeatureEnabled('PUSH_NOTIFICATIONS')) {
    // Initialize push notifications
}

// Bad
if (window.clientEnv.get('NODE_ENV') === 'production') {
    // Initialize push notifications - too specific
}
```

### 3. Provide Default Values
```javascript
// Good
const apiUrl = window.clientEnv.get('API_BASE_URL', 'http://localhost:8000');

// Bad
const apiUrl = window.clientEnv.get('API_BASE_URL'); // May be undefined
```

### 4. Handle Errors Gracefully
```javascript
// Good
try {
    await window.clientEnv.waitForReady();
    const apiUrl = window.clientEnv.getApiBaseUrl();
} catch (error) {
    console.error('Failed to load environment:', error);
    // Use fallback configuration
}

// Bad
const apiUrl = window.clientEnv.getApiBaseUrl(); // May throw error
```

## Troubleshooting

### Environment Not Loading
1. Check if scripts are loaded in correct order
2. Verify server is running and accessible
3. Check browser console for errors
4. Ensure `/api/client-env` endpoint is working

### Environment Variables Not Available
1. Check if environment is ready: `window.clientEnv.isReady()`
2. Wait for environment: `await window.clientEnv.waitForReady()`
3. Check if variable exists: `window.clientEnv.get('VARIABLE_NAME')`

### API Calls Failing
1. Verify API_BASE_URL is correct
2. Check CORS settings
3. Ensure API server is running
4. Check network tab in browser dev tools

## API Endpoints

### GET /api/client-env
Returns current environment configuration as JSON.

**Response:**
```json
{
  "NODE_ENV": "development",
  "DEBUG_MODE": true,
  "API_BASE_URL": "http://localhost:8000",
  "PWA_BASE_URL": "http://localhost:3000",
  "FEATURES": {
    "PUSH_NOTIFICATIONS": true,
    "OFFLINE_SUPPORT": true
  },
  "APP_NAME": "RefereeX",
  "VERSION": "v1.0.0",
  "BUILD_TIME": "2024-01-01T00:00:00.000Z"
}
```

### GET /api/health
Returns server health information including environment details.

## Security Notes

1. **Never expose sensitive data** in client environment variables
2. **Use feature flags** instead of environment-specific logic
3. **Validate environment variables** on the client side
4. **Use HTTPS** in production environments
5. **Sanitize environment variables** before exposing to client
