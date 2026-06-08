# Vite Auto-Refresh Module for RefPortal PWA

This module provides automatic refresh functionality for the RefPortal PWA during development, using Vite's Hot Module Replacement (HMR) capabilities and the `vite-plugin-pwa` for enhanced PWA functionality.

## 🚀 Features

- 🔄 **Hot Module Replacement (HMR)** for CSS and JavaScript files
- 📱 **PWA Auto-Refresh** with service worker updates
- ⚡ **Real-time updates** during development
- 🔌 **Connection monitoring** with automatic reconnection
- 🎛️ **Manual refresh controls** for development
- 📊 **Status monitoring** and debugging information
- 🎨 **Integrated PWA manifest** with Vite build system
- 🚀 **Workbox integration** for advanced caching strategies

## 📋 Prerequisites

- Node.js 18+ 
- npm or yarn package manager
- Modern browser with PWA support

## 🛠️ Installation

### 1. Install Dependencies

```bash
cd rpPwa
npm install
```

This will install:
- `vite` - Build tool and development server
- `vite-plugin-pwa` - PWA plugin for Vite
- `workbox-window` - Service worker management

### 2. Verify Installation

```bash
npm list vite vite-plugin-pwa workbox-window
```

## 🚀 Quick Start

### Development Mode

```bash
# Start development server with auto-refresh
npm run dev

# Start with HTTPS (recommended for PWA features)
npm run dev:https

# Start with custom port
node dev-server.js --port 8080 --https
```

### Production Build

```bash
# Build for production
npm run build

# Build with PWA optimizations
npm run build:pwa

# Preview production build
npm run preview:pwa
```

## 🔧 Configuration

### Vite Configuration (`vite.config.js`)

The configuration includes:

- **PWA Plugin**: Automatic service worker generation and manifest management
- **HTTPS Support**: Required for PWA features
- **HMR Configuration**: Hot module replacement setup
- **Asset Optimization**: Automatic asset caching and optimization

### PWA Manifest

The PWA manifest is automatically generated with:

- App icons and splash screens
- Theme colors and display settings
- App shortcuts for quick navigation
- RTL language support (Hebrew)

### Service Worker

Workbox-based service worker with:

- **Cache Strategies**: Network-first for API, cache-first for static assets
- **Background Sync**: Offline capability for data synchronization
- **Update Management**: Automatic service worker updates

## 📱 Auto-Refresh Functionality

### How It Works

1. **Development Mode**: Uses Vite's HMR for instant updates
2. **Production Mode**: Monitors service worker updates and prompts user
3. **Hybrid Mode**: Combines both approaches for optimal experience

### Update Types

- **CSS Updates**: Hot-reloaded without page refresh
- **JavaScript Updates**: Smart module replacement
- **HTML Updates**: Full page reload when necessary
- **Service Worker Updates**: Automatic SW update and refresh
- **Asset Updates**: Intelligent caching and refresh strategies

### Connection Management

- Automatically detects development vs production environment
- Monitors connection status in real-time
- Provides fallback mechanisms for offline scenarios
- Configurable reconnection attempts and delays

## 🎛️ Manual Controls

### Global Methods

When the auto-refresh module is loaded, these methods are available:

```javascript
// Manual refresh methods
window.refreshPWA()           // Force PWA refresh
window.getPWAStatus()         // Get current status
window.showPWAUpdate()        // Show test update notification

// Access the auto-refresh instance
window.VitePWARefresh
```

### Debug Controls

The module automatically adds controls to the debug section:

- **Refresh Button**: Force manual refresh
- **Status Display**: Current connection and update status
- **Copy Status**: Copy status information to clipboard

### Header Controls

A refresh button is automatically added to the header:

- **Green Refresh Button**: Vite auto-refresh functionality
- **Tooltip**: "Vite Auto-Refresh"
- **Click Action**: Triggers immediate refresh

## 🔍 Event System

### Available Events

Listen to auto-refresh events:

```javascript
const autoRefresh = window.VitePWARefresh;

// Update events
autoRefresh.on('update', (data) => {
    console.log('Update received:', data.type);
});

// Service worker events
window.addEventListener('vite-pwa-update', (event) => {
    console.log('PWA update event:', event.detail);
});
```

### Event Types

- `update`: General update event
- `sw-update`: Service worker update
- `sw-waiting`: Service worker waiting for activation
- `background-sync`: Background synchronization
- `hmr`: Hot module replacement updates

## 📊 Status Information

### Get Current Status

```javascript
const status = window.getPWAStatus();
console.log(status);
// {
//     connected: true,
//     development: true,
//     lastUpdate: Date,
//     serviceWorker: true,
//     hmr: true
// }
```

### Status Indicators

- **Connected**: Connection to development server
- **Development**: Running in development mode
- **Last Update**: Timestamp of last update
- **Service Worker**: Service worker support status
- **HMR**: Hot module replacement availability

## 🚀 Development Server

### Server Features

The development server provides:

- **Vite Integration**: Full Vite development server
- **HTTPS Support**: SSL certificates for PWA features
- **HMR**: Hot module replacement
- **PWA Support**: Service worker and manifest management
- **Auto-refresh**: Automatic page updates

### Server Commands

When the development server is running:

- **`r` + Enter**: Force reload
- **`u` + Enter**: Check for updates
- **`c` + Enter**: Clear cache
- **`q` + Enter**: Quit server
- **Ctrl+C**: Quit server

### Server Options

```bash
# Custom port
node dev-server.js --port 8080

# Custom host
node dev-server.js --host 0.0.0.0

# Enable HTTPS
node dev-server.js --https

# Don't open browser
node dev-server.js --no-open

# Show help
node dev-server.js --help
```

## 🔧 Integration with Existing PWA

### Seamless Integration

The auto-refresh module is designed to work with the existing PWA:

- **Non-intrusive**: Only activates in development mode
- **PWA-compatible**: Works with existing service workers
- **Debug-friendly**: Integrates with existing debug tools
- **Performance-aware**: Minimal impact on production builds

### Existing Features Preserved

- Push notifications
- Offline functionality
- Service worker caching
- Debug information display
- User authentication

## 🌐 Browser Compatibility

### Supported Browsers

- **Chrome/Edge**: Full support
- **Firefox**: Full support
- **Safari**: Full support (iOS 13+)
- **Mobile browsers**: Full support

### PWA Requirements

- HTTPS connection (required for service workers)
- Modern browser with PWA support
- Service worker registration capability

## 🚀 Performance Considerations

### Development Mode

- **Minimal overhead**: Only active during development
- **Efficient updates**: Smart file replacement strategies
- **Connection pooling**: Reuses connections when possible
- **Memory management**: Proper cleanup on disconnect

### Production Mode

- **Optimized builds**: Vite optimizes all assets
- **Service worker caching**: Intelligent caching strategies
- **Background updates**: Non-blocking update checks
- **Offline support**: Full offline functionality

## 🐛 Troubleshooting

### Common Issues

#### Connection Problems

```bash
# Check if server is running
ps aux | grep vite

# Check server logs
npm run dev

# Verify port availability
lsof -i :3000
```

#### Update Issues

```bash
# Clear cache
npm run dev -- --force

# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install

# Reset service worker
# Use browser dev tools to clear SW cache
```

#### PWA Issues

```bash
# Check HTTPS configuration
npm run dev:https

# Verify manifest generation
npm run build:pwa

# Check service worker registration
# Use browser dev tools
```

### Debug Information

Enable detailed logging:

```javascript
// In browser console
window.VitePWARefresh.options.enableLogging = true;
```

### Error Reporting

Common error messages and solutions:

- **"Module not found"**: Check file paths and imports
- **"Service Worker error"**: Verify HTTPS and SW registration
- **"HMR not working"**: Check Vite configuration and file types
- **"PWA not installing"**: Verify manifest and HTTPS setup

## 🔄 Update Process

### Development Updates

1. **File Change**: Edit CSS, JS, or HTML file
2. **HMR Detection**: Vite detects the change
3. **Auto-refresh**: Module automatically refreshes
4. **Instant Update**: Changes appear immediately

### Production Updates

1. **Build Process**: Run `npm run build:pwa`
2. **Service Worker**: New SW is generated
3. **Update Detection**: Module detects new version
4. **User Prompt**: User is prompted to update
5. **Update Application**: Page reloads with new version

## 📚 API Reference

### VitePWARefresh Class

```javascript
class VitePWARefresh {
    constructor(options)
    init()
    setupRefresh()
    forceRefresh()
    showStatus()
    destroy()
}
```

### Options

```javascript
{
    enableLogging: true,        // Enable console logging
    autoConnect: true,          // Auto-connect on init
    checkInterval: 5000         // Update check interval (ms)
}
```

### Methods

- `init()`: Initialize the module
- `setupRefresh()`: Setup refresh functionality
- `forceRefresh()`: Force immediate refresh
- `showStatus()`: Display current status
- `destroy()`: Cleanup and destroy instance

## 🤝 Contributing

### Development Setup

```bash
# Clone repository
git clone <repository-url>
cd rpPwa

# Install dependencies
npm install

# Start development server
npm run dev

# Make changes and test
# Auto-refresh will handle updates
```

### Adding Features

1. **Extend the class**: Add new methods to `VitePWARefresh`
2. **Add event types**: Extend the event system
3. **Update configuration**: Modify Vite config as needed
4. **Test thoroughly**: Verify in both dev and production modes

### Code Style

- Use ES6+ features
- Follow existing naming conventions
- Add JSDoc comments for public methods
- Include error handling for all async operations

## 📄 License

MIT License - See main project license for details.

## 🆘 Support

### Getting Help

1. **Check this README**: Comprehensive documentation
2. **Review console logs**: Enable logging for debugging
3. **Check browser dev tools**: Service worker and network tabs
4. **Verify configuration**: Check Vite and PWA plugin settings

### Known Issues

- **macOS**: Some HTTPS certificate issues (use `--https` flag)
- **Windows**: Path resolution differences (use forward slashes)
- **Linux**: Permission issues with SSL certificates

### Future Enhancements

- **WebSocket fallback**: Alternative to EventSource
- **Custom update strategies**: User-configurable update behavior
- **Advanced caching**: Intelligent cache invalidation
- **Performance metrics**: Update performance monitoring

---

**Happy coding with Vite PWA Auto-Refresh! 🚀**
