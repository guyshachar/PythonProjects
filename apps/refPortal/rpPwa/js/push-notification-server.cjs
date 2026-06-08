// Example Node.js server for push notifications
// Save this file and run: npm install web-push

const webpush = require('web-push');

// Configure VAPID keys
webpush.setVapidDetails(
  'mailto:admin@refereex.com',
  'BCrb6Lp792xCx8tOm_BLPrvb6DY9GDhfu9K04DBrhAz4qDL7LqVodnePQ4ZTmZXBUWhWumYlKwEjj4QzHRChhX0',
  'j8XYpDC3_Z56up9IWj-92tZ9J74f0AFzgv0LMafaMpU'
);

// Example function to send push notification
async function sendPushNotification(subscription, payload) {
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
  url: '/refereeX-pwa.html#games',
  action: 'view-game',
  type: 'game-assignment'
};

// Export for use in your server
module.exports = {
  sendPushNotification,
  examplePayload
};
