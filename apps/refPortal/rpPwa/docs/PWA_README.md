# RefPortal Progressive Web App (PWA)

A modern Progressive Web App for managing referees and games, built with HTML5, CSS3, and JavaScript.

## Features

### 🎯 Core Functionality
- **Dashboard**: Overview of games, referees, and assignments
- **Games Management**: View and manage game schedules
- **Reviews System**: Referee performance reviews and ratings
- **Fields Information**: Stadium and field details
- **Rules Reference**: Football rules and regulations
- **Chat System**: Real-time communication with action buttons

### 📱 PWA Features
- **Installable**: Add to home screen on mobile devices
- **Push Notifications**: Receive real-time updates and messages
- **Offline Support**: Works without internet connection
- **Responsive Design**: Optimized for all device sizes
- **Hebrew RTL Support**: Full right-to-left language support

### 🔔 Push Notification Features
- Click notifications to open specific URLs
- Interactive notification buttons
- Background message processing
- Chat message notifications

## File Structure

```
rpApi/static/
├── refportal-pwa.html          # Main PWA HTML file
├── refportal-pwa.css           # PWA styles and responsive design
├── refportal-pwa.js            # PWA functionality and logic
├── refportal-manifest.json     # PWA manifest for installation
├── refportal-sw.js             # Service worker for offline/push
└── PWA_README.md               # This documentation
```

## Setup Instructions

### 1. Prerequisites
- Web server with HTTPS (required for PWA features)
- Modern browser supporting Service Workers
- Plotly.js for charts (included via CDN)

### 2. Installation

#### Option A: Direct File Access
1. Place all PWA files in your web server's static directory
2. Ensure HTTPS is enabled
3. Access via `https://yourdomain.com/refportal-pwa.html`

#### Option B: Integration with Existing App
1. Copy PWA files to your existing web application
2. Update API endpoints in `refportal-pwa.js`
3. Customize the manifest file paths
4. Integrate with your existing authentication system

### 3. Service Worker Registration
The service worker is automatically registered when the PWA loads. Ensure:
- Your server supports HTTPS
- The service worker file is accessible at `/refportal-sw.js`
- Proper MIME types are set for JavaScript files

### 4. Push Notifications Setup

#### VAPID Keys
1. Generate VAPID keys for your server:
   ```bash
   npm install -g web-push
   web-push generate-vapid-keys
   ```

2. Update the VAPID public key in `refportal-pwa.js`:
   ```javascript
   applicationServerKey: this.urlBase64ToUint8Array('YOUR_VAPID_PUBLIC_KEY')
   ```

#### Server-Side Implementation
Implement push notification sending on your server:

```javascript
// Example Node.js implementation
const webpush = require('web-push');

webpush.setVapidDetails(
  'mailto:your-email@domain.com',
  'YOUR_VAPID_PUBLIC_KEY',
  'YOUR_VAPID_PRIVATE_KEY'
);

// Send notification
webpush.sendNotification(subscription, JSON.stringify({
  title: 'משחק חדש',
  body: 'שיבוץ חדש זמין עבורך',
  url: '/refportal-pwa.html#games',
  action: 'view-game'
}));
```

## Configuration

### API Endpoints
Update the API endpoints in `refportal-pwa.js`:

```javascript
// Dashboard data
const response = await fetch('https://your-api.com/api/dashboardLoadData');

// Push subscription
await fetch('/api/push-subscription', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(subscription)
});
```

### Customization
- **Colors**: Update CSS variables in `refportal-pwa.css`
- **Icons**: Replace icon files in the `images/` directory
- **Content**: Modify HTML content in `refportal-pwa.html`
- **Functionality**: Extend JavaScript classes in `refportal-pwa.js`

## Usage

### Navigation
- Use the bottom navigation menu to switch between sections
- Each section loads relevant data automatically
- Responsive design adapts to screen size

### Push Notifications
1. Click the notification bell icon to request permissions
2. Grant notification permissions when prompted
3. Receive real-time updates and messages
4. Click notifications to open specific sections or URLs

### Chat System
- Send messages using the chat input
- Receive automated responses and notifications
- Use action buttons for quick actions
- Messages are stored locally and synced when online

### Offline Mode
- App works without internet connection
- Data is cached for offline access
- Actions are queued and synced when online
- Service worker handles all offline functionality

## Browser Support

### Full PWA Support
- Chrome 67+
- Firefox 67+
- Edge 79+
- Safari 11.1+ (iOS 11.3+)

### Partial Support
- Older browsers will work as regular web apps
- PWA features will be gracefully degraded
- Core functionality remains available

## Testing

### Local Development
1. Use a local HTTPS server (e.g., `https-server` npm package)
2. Test PWA installation and offline functionality
3. Verify push notifications work correctly

### Production Testing
1. Deploy to production server with HTTPS
2. Test on various devices and browsers
3. Verify push notification delivery
4. Test offline functionality

## Troubleshooting

### Common Issues

#### Service Worker Not Registering
- Ensure HTTPS is enabled
- Check browser console for errors
- Verify service worker file path

#### Push Notifications Not Working
- Check VAPID key configuration
- Verify notification permissions
- Test with different browsers

#### Offline Functionality Issues
- Clear browser cache and storage
- Check service worker status
- Verify cache strategies

#### Installation Prompt Not Showing
- Ensure manifest file is valid
- Check HTTPS requirement
- Verify app meets installability criteria

### Debug Mode
Enable debug logging in the service worker:

```javascript
// In refportal-sw.js
const DEBUG = true;

if (DEBUG) {
  console.log('Debug info:', data);
}
```

## Security Considerations

### HTTPS Requirement
- PWA features require HTTPS
- Service workers only work over secure connections
- Push notifications require secure context

### Data Privacy
- User data is stored locally
- API calls should use proper authentication
- Implement proper CORS policies

### Push Notification Security
- Use VAPID keys for authentication
- Validate subscription data
- Implement rate limiting

## Performance Optimization

### Caching Strategy
- Static files cached for offline use
- API responses cached when possible
- Dynamic content updated regularly

### Bundle Optimization
- CSS and JavaScript are optimized
- Images are properly sized
- Service worker handles caching efficiently

## Future Enhancements

### Planned Features
- Background sync for offline actions
- Periodic content updates
- Advanced notification actions
- Data synchronization across devices

### Integration Possibilities
- Authentication system integration
- Real-time WebSocket support
- Advanced analytics
- Multi-language support

## Support

For technical support or questions:
1. Check browser console for error messages
2. Verify all files are properly configured
3. Test on different devices and browsers
4. Review browser-specific PWA requirements

## License

This PWA is part of the RefPortal Service application. Please refer to your project's licensing terms.

---

**Note**: This PWA is designed to work with the existing RefPortal Service backend. Ensure all API endpoints and data structures are compatible with your backend implementation.
