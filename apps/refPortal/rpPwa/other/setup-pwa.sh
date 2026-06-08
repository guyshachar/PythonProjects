#!/bin/bash

# RefereeX PWA Setup Script
# This script helps set up the PWA with proper configuration

echo "🚀 RefereeX PWA Setup Script"
echo "=============================="

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js first."
    echo "   Visit: https://nodejs.org/"
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install npm first."
    exit 1
fi

echo "✅ Node.js and npm are installed"

# Install web-push globally if not already installed
if ! npm list -g web-push &> /dev/null; then
    echo "📦 Installing web-push globally..."
    npm install -g web-push
else
    echo "✅ web-push is already installed"
fi

# Generate VAPID keys
echo "🔑 Generating VAPID keys..."
VAPID_KEYS=$(web-push generate-vapid-keys)

# Extract public and private keys
VAPID_PUBLIC_KEY=$(echo "$VAPID_KEYS" | grep "Public Key:" | cut -d: -f2 | tr -d ' ')
VAPID_PRIVATE_KEY=$(echo "$VAPID_KEYS" | grep "Private Key:" | cut -d: -f2 | tr -d ' ')

echo "✅ VAPID keys generated successfully!"

# Create configuration file
echo "📝 Creating PWA configuration file..."

cat > pwa-config.js << EOF
// RefereeX PWA Configuration
// Generated automatically by setup script

const PWA_CONFIG = {
    // VAPID Keys for Push Notifications
    VAPID_PUBLIC_KEY: '${VAPID_PUBLIC_KEY}',
    VAPID_PRIVATE_KEY: '${VAPID_PRIVATE_KEY}', // Only needed on server side
    
    // API Endpoints
    API_BASE_URL: 'https://api.refereex.com:24501',
    ENDPOINTS: {
        DASHBOARD: '/api/dashboardLoadData',
        GAMES: '/api/games',
        REVIEWS: '/api/reviews',
        FIELDS: '/api/fields',
        RULES: '/api/rules',
        PUSH_SUBSCRIPTION: '/api/push-subscription',
        SET_PUSH_SUBSCRIPTION: '/api/set-push-subscription',
        CHAT: '/api/chat'
    },
    
    // App Configuration
    APP_NAME: 'RefereeX',
    APP_SHORT_NAME: 'RefereeX',
    APP_DESCRIPTION: 'מערכת ניהול שופטים ומשחקים מתקדמת',
    
    // Notification Settings
    NOTIFICATION_ICON: '../images/RefereeX.png',
    NOTIFICATION_TIMEOUT: 5000, // 5 seconds
    
    // Cache Configuration
    CACHE_VERSION: 'v1.0.0',
    STATIC_CACHE_NAME: 'refportal-static-v1',
    DYNAMIC_CACHE_NAME: 'refportal-dynamic-v1',
    
    // Feature Flags
    FEATURES: {
        PUSH_NOTIFICATIONS: true,
        OFFLINE_SUPPORT: true,
        BACKGROUND_SYNC: true,
        INSTALL_PROMPT: true
    },
    
    // Debug Mode
    DEBUG: false
};

// Export for use in other files
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PWA_CONFIG;
} else {
    // Browser environment
    window.PWA_CONFIG = PWA_CONFIG;
}
EOF

echo "✅ Configuration file created: pwa-config.js"

# Create server-side push notification example
echo "📝 Creating server-side push notification example..."

cat > push-notification-server.js << EOF
// Example Node.js server for push notifications
// Save this file and run: npm install web-push

const webpush = require('web-push');

// Configure VAPID keys
webpush.setVapidDetails(
  'mailto:admin@refereex.com',
  '${VAPID_PUBLIC_KEY}',
  '${VAPID_PRIVATE_KEY}'
);

// Example function to send push notification
async function skipPushNotification(subscription, payload) {
  try {
    const result = await webpush.sendNotification(subscription, JSON.stringify(payload));
    console.log('Push notification sent successfully:', result);
    return result;
  } catch (error) {
    console.error('Error sending push notification:', error);
    throw error;
  }
}

// Example usage
const examplePayload = {
  title: 'משחק חדש',
  body: 'שיבוץ חדש זמין עבורך',
  url: '/refportal-pwa.html#games',
  action: 'view-game',
  type: 'game-assignment'
};

// Export for use in your server
module.exports = {
  skipPushNotification,
  examplePayload
};
EOF

echo "✅ Server example created: push-notification-server.js"

# Create package.json for server dependencies
echo "📝 Creating package.json for server dependencies..."

cat > package.json << EOF
{
      "name": "refereex-push-server",
    "version": "1.0.0",
    "description": "Push notification server for RefereeX PWA",
  "main": "push-notification-server.js",
  "scripts": {
    "start": "node push-notification-server.js",
    "install-deps": "npm install web-push"
  },
  "dependencies": {
    "web-push": "^3.6.6"
  },
  "keywords": ["pwa", "push-notifications", "refereex"],
  "author": "RefereeX Team",
  "license": "MIT"
}
EOF

echo "✅ Package.json created: package.json"

echo ""
echo "🎉 PWA Setup Complete!"
echo "======================"
echo ""
echo "Next steps:"
echo "1. Update your server to handle push notifications using the generated keys"
echo "2. Install server dependencies: npm install"
echo "3. Test the PWA by opening refportal-pwa.html in a browser"
echo "4. Test push notifications using the server example"
echo ""
echo "Files created:"
echo "- pwa-config.js (PWA configuration with VAPID keys)"
echo "- push-notification-server.js (Server example)"
echo "- package.json (Server dependencies)"
echo ""
echo "VAPID Public Key: ${VAPID_PUBLIC_KEY}"
echo "VAPID Private Key: ${VAPID_PRIVATE_KEY}"
echo ""
echo "⚠️  Keep your VAPID private key secure and don't share it publicly!"
