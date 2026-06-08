// Test Push Notification Server for RefereeX PWA
// Run with: node test-push-server.js

const webpush = require('web-push');

// VAPID Keys from pwa-config.js
const VAPID_PUBLIC_KEY = 'BCrb6Lp792xCx8tOm_BLPrvb6DY9GDhfu9K04DBrhAz4qDL7LqVodnePQ4ZTmZXBUWhWumYlKwEjj4QzHRChhX0';
const VAPID_PRIVATE_KEY = 'j8XYpDC3_Z56up9IWj-92tZ9J74f0AFzgv0LMafaMpU';

// Configure web-push with VAPID keys
webpush.setVapidDetails(
  'mailto:admin@refereex.com',
  VAPID_PUBLIC_KEY,
  VAPID_PRIVATE_KEY
);

console.log('🚀 RefereeX PWA Push Notification Test Server');
console.log('==============================================');
console.log(`VAPID Public Key: ${VAPID_PUBLIC_KEY}`);
console.log(`VAPID Private Key: ${VAPID_PRIVATE_KEY}`);
console.log('');

// Example subscription (you'll get this from the PWA)
const exampleSubscription = {
  endpoint: 'https://fcm.googleapis.com/fcm/send/example...',
  keys: {
    p256dh: 'example_p256dh_key',
    auth: 'example_auth_key'
  }
};

// Test notification payloads
const testNotifications = [
  {
    title: 'משחק חדש',
    body: 'שיבוץ חדש זמין עבורך',
    url: '/refereeX-pwa.html#games',
    action: 'view-game',
    type: 'game-assignment'
  },
  {
    title: 'עדכון שופט',
    body: 'התקבל דירוג חדש עבורך',
    url: '/refereeX-pwa.html#reviews',
    action: 'view-review',
    type: 'referee-update'
  },
  {
    title: 'הודעה חדשה',
    body: 'יש לך הודעה חדשה בצ\'אט',
    url: '/refereeX-pwa.html#chat',
    action: 'open-chat',
    type: 'chat-message'
  }
];

// Function to send push notification
async function skipPushNotification(subscription, payload) {
  try {
    const result = await webpush.sendNotification(subscription, JSON.stringify(payload));
    console.log('✅ Push notification sent successfully!');
    console.log('   Response:', result.statusCode);
    return result;
  } catch (error) {
    console.error('❌ Error sending push notification:', error.message);
    if (error.statusCode) {
      console.error('   Status Code:', error.statusCode);
    }
    throw error;
  }
}

// Function to test with a real subscription
async function testWithRealSubscription() {
  console.log('📱 To test with a real subscription:');
  console.log('1. Open the PWA in your browser');
  console.log('2. Allow notifications when prompted');
  console.log('3. Copy the subscription object from browser console');
  console.log('4. Replace the exampleSubscription in this file');
  console.log('5. Run this script again');
  console.log('');
}

// Function to validate VAPID keys
function validateVAPIDKeys() {
  console.log('🔑 Validating VAPID Keys...');
  
  if (!VAPID_PUBLIC_KEY || VAPID_PUBLIC_KEY === '') {
    console.error('❌ VAPID Public Key is missing or empty');
    return false;
  }
  
  if (!VAPID_PRIVATE_KEY || VAPID_PRIVATE_KEY === '') {
    console.error('❌ VAPID Private Key is missing or empty');
    return false;
  }
  
  if (VAPID_PUBLIC_KEY === 'YOUR_VAPID_PUBLIC_KEY_HERE') {
    console.error('❌ VAPID Public Key has not been updated');
    return false;
  }
  
  if (VAPID_PRIVATE_KEY === 'YOUR_VAPID_PRIVATE_KEY_HERE') {
    console.error('❌ VAPID Private Key has not been updated');
    return false;
  }
  
  console.log('✅ VAPID Keys are valid');
  return true;
}

// Function to show test notification examples
function showTestExamples() {
  console.log('📋 Test Notification Examples:');
  testNotifications.forEach((notification, index) => {
    console.log(`\n${index + 1}. ${notification.title}`);
    console.log(`   Body: ${notification.body}`);
    console.log(`   URL: ${notification.url}`);
    console.log(`   Action: ${notification.action}`);
    console.log(`   Type: ${notification.type}`);
  });
  console.log('');
}

// Function to test with example subscription (will fail but shows the process)
async function testExampleSubscription() {
  console.log('🧪 Testing with example subscription (will fail - this is expected)...');
  
  try {
    await skipPushNotification(exampleSubscription, testNotifications[0]);
  } catch (error) {
    console.log('ℹ️  This error is expected since we\'re using a fake subscription');
    console.log('   To test real notifications, use a subscription from your PWA');
  }
  console.log('');
}

// Main function
async function main() {
  try {
    // Validate VAPID keys
    if (!validateVAPIDKeys()) {
      console.log('❌ Please fix VAPID key issues before proceeding');
      return;
    }
    
    // Show test examples
    showTestExamples();
    
    // Test with example subscription
    await testExampleSubscription();
    
    // Show instructions for real testing
    await testWithRealSubscription();
    
    console.log('🎯 Next Steps:');
    console.log('1. Open test-vapid.html in your browser to verify configuration');
    console.log('2. Open refereeX-pwa.html to test the full PWA');
    console.log('3. Use the subscription from the PWA to test real push notifications');
    console.log('');
    console.log('📚 For more information, see:');
    console.log('   - PWA_README.md');
    console.log('   - PWA_SETUP_COMPLETE.md');
    console.log('   - test-vapid.html');
    
  } catch (error) {
    console.error('❌ Fatal error:', error.message);
  }
}

// Run the main function
if (require.main === module) {
  main();
}

// Export functions for use in other modules
module.exports = {
  skipPushNotification,
  testNotifications,
  validateVAPIDKeys,
  VAPID_PUBLIC_KEY,
  VAPID_PRIVATE_KEY
};
