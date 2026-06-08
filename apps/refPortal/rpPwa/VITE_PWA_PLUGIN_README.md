# Vite Plugin PWA Implementation for RefPortal

This document describes the implementation of `vite-plugin-pwa` for automatic PWA refresh and updates in the RefPortal application.

## 🎯 Overview

The `vite-plugin-pwa` provides a comprehensive solution for PWA development with:
- **Automatic Service Worker generation** with Workbox
- **Hot Module Replacement (HMR)** for development
- **Automatic PWA updates** in production
- **Offline support** with intelligent caching strategies
- **Push notification support** integration

## 📦 Installation

The following packages have been installed:

```bash
npm install vite-plugin-pwa workbox-window --save-dev
```

### Dependencies Added:
- `vite-plugin-pwa`: Official Vite plugin for PWA functionality
- `workbox-window`: Workbox library for service worker management
- `vite`: Vite build tool (updated to v5.0.0)

## ⚙️ Configuration

### 1. Vite Configuration (`vite.config.js`)

The Vite configuration has been updated to use the PWA plugin:

```javascript
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['images/**/*', 'css/**/*', 'fonts/**/*'],
      manifest: {
        name: 'RefereeX - ניהול שופטים ומשחקים',
        short_name: 'RefereeX',
        // ... PWA manifest configuration
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,jpg,jpeg,gif}'],
        runtimeCaching: [
          // ... Caching strategies for different asset types
        ],
        cleanupOutdatedCaches: true,
        skipWaiting: true,
        clientsClaim: true
      },
      devOptions: {
        enabled: true,
        type: 'module',
        navigateFallback: 'refportal-pwa.html'
      }
    })
  ]
})
```

### 2. PWA Auto-Refresh Module (`js/vite-pwa-refresh.js`)

A new module has been created to handle PWA updates and refresh functionality:

**Features:**
- Automatic PWA updates when new versions are available
- Service Worker update notifications
- Hot Module Replacement (HMR) support in development
- Manual refresh controls
- Update status monitoring

**Key Methods:**
```javascript
// Global API available in browser console
window.pwaRefresh.getStatus()     // Get PWA status
window.refreshCSS()               // Manual CSS refresh
window.refreshJS()                // Manual JS refresh
window.forceReload()              // Force page reload
```

### 3. Package.json Scripts

New development scripts have been added:

```json
{
  "scripts": {
    "dev": "vite",
    "dev:https": "vite --https",
    "build": "vite build",
    "preview": "vite preview",
    "build:pwa": "vite build --mode pwa",
    "preview:pwa": "vite preview --mode pwa"
  }
}
```

## 🚀 Usage

### Development Mode

Start the development server with PWA auto-refresh:

```bash
# Basic development server
npm run dev

# HTTPS development server (required for PWA features)
npm run dev:https

# Custom development server with advanced options
node dev-server.js --port 8080 --https
```

### Production Build

Build the PWA for production:

```bash
# Standard build
npm run build

# PWA-specific build
npm run build:pwa

# Preview production build
npm run preview
```

## 🔄 Auto-Refresh Features

### Development Mode
- **Hot Module Replacement**: CSS and JS changes update instantly
- **HTML Updates**: Full page reload for HTML changes
- **Service Worker Updates**: Automatic SW updates and refresh
- **Manual Controls**: Console commands for manual refresh

### Production Mode
- **Automatic Updates**: PWA updates when new versions are deployed
- **Update Notifications**: User-friendly update prompts
- **Background Updates**: Updates download in background
- **Graceful Updates**: Updates apply when user is ready

## 📱 PWA Features

### Manifest Configuration
- **App Name**: RefereeX - ניהול שופטים ומשחקים
- **Icons**: Multiple sizes for different devices
- **Shortcuts**: Quick access to Games, Reviews, and Chat
- **RTL Support**: Hebrew language support
- **Theme**: Blue theme color (#2563eb)

### Service Worker Features
- **Caching Strategies**: 
  - CacheFirst for static assets
  - NetworkFirst for API calls
  - StaleWhileRevalidate for images
- **Offline Support**: App works without internet
- **Background Sync**: Sync data when connection restored
- **Push Notifications**: Real-time notifications

### Runtime Caching
- **Plotly.js**: Cached for 1 year
- **Images**: Cached for 30 days
- **Fonts**: Cached for 1 year
- **API Calls**: Network-first with 5-minute cache

## 🛠️ Development Tools

### Console Commands

When the development server is running, these commands are available in the browser console:

```javascript
// PWA Status
window.pwaRefresh.getStatus()

// Manual Refresh
window.refreshCSS()        // Refresh CSS files
window.refreshJS()         // Refresh JS files
window.forceReload()       // Force page reload

// Update Management
window.pwaRefresh.checkForUpdates()  // Check for updates
window.pwaRefresh.applyUpdate()      // Apply pending update
```

### Event System

Listen to PWA events:

```javascript
const pwaRefresh = window.pwaRefresh;

pwaRefresh.on('updateFound', () => {
  console.log('New version available!');
});

pwaRefresh.on('updateReady', () => {
  console.log('Update ready to apply');
});

pwaRefresh.on('hmrUpdate', (payload) => {
  console.log('HMR update:', payload);
});
```

## 🔧 Configuration Options

### PWA Plugin Options

```javascript
VitePWA({
  registerType: 'autoUpdate',           // Auto-update strategy
  includeAssets: [...],                 // Assets to include in SW
  manifest: {...},                      // PWA manifest
  workbox: {
    globPatterns: [...],                // Files to cache
    runtimeCaching: [...],              // Caching strategies
    cleanupOutdatedCaches: true,        // Clean old caches
    skipWaiting: true,                  // Skip waiting for activation
    clientsClaim: true                  // Claim all clients
  },
  devOptions: {
    enabled: true,                      // Enable in development
    type: 'module',                     // SW type
    navigateFallback: 'index.html'      // Fallback page
  }
})
```

### Auto-Refresh Module Options

```javascript
new VitePWARefresh({
  enableLogging: true,                  // Enable console logging
  autoUpdate: true,                     // Auto-apply updates
  showUpdateNotification: true,         // Show update prompts
  updateCheckInterval: 60000            // Update check interval (ms)
})
```

## 🐛 Troubleshooting

### Common Issues

1. **Service Worker Not Updating**
   ```javascript
   // Clear SW cache manually
   navigator.serviceWorker.getRegistrations().then(registrations => {
     registrations.forEach(registration => registration.unregister());
   });
   ```

2. **HMR Not Working**
   ```javascript
   // Check if in development mode
   console.log(window.pwaRefresh.getStatus());
   ```

3. **Update Notifications Not Showing**
   ```javascript
   // Force update check
   window.pwaRefresh.checkForUpdates();
   ```

### Debug Information

Access debug information:

```javascript
// Get comprehensive status
const status = window.pwaRefresh.getStatus();
console.log('PWA Status:', status);

// Check service worker status
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.ready.then(registration => {
    console.log('SW Registration:', registration);
  });
}
```

## 📊 Performance Benefits

### Development
- **Faster Development**: Instant updates without page refresh
- **State Preservation**: JS updates don't lose current state
- **Better Debugging**: Real-time error reporting
- **Efficient Caching**: Smart cache invalidation

### Production
- **Faster Loading**: Aggressive caching strategies
- **Offline Support**: App works without internet
- **Automatic Updates**: Users always have latest version
- **Better UX**: Smooth update experience

## 🔄 Migration from Custom Implementation

The new `vite-plugin-pwa` implementation replaces the custom auto-refresh module with:

### Advantages:
- ✅ **Official Support**: Maintained by Vite team
- ✅ **Better Performance**: Optimized Workbox integration
- ✅ **More Features**: Comprehensive PWA functionality
- ✅ **Better Caching**: Advanced caching strategies
- ✅ **Production Ready**: Battle-tested in production

### Backward Compatibility:
- ✅ **Same API**: Global methods still available
- ✅ **Same Events**: Event system maintained
- ✅ **Same Behavior**: Development experience unchanged

## 📚 Resources

- [Vite Plugin PWA Documentation](https://vite-pwa-org.netlify.app/)
- [Workbox Documentation](https://developers.google.com/web/tools/workbox)
- [PWA Best Practices](https://web.dev/pwa-checklist/)
- [Service Worker API](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API)

## 🎉 Conclusion

The `vite-plugin-pwa` implementation provides a robust, production-ready solution for PWA development with automatic refresh capabilities. It offers better performance, more features, and official support compared to the custom implementation, while maintaining backward compatibility with existing development workflows.
