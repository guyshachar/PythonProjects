// RefereeX Service Worker
const CACHE_VERSION = 'v1.2.146'; // Increment this when you make changes
const VERSION_CHECK_INTERVAL = 5 * 60 * 1000; // Check every 5 minutes
const CACHE_NAME = `refereex-${CACHE_VERSION}`;
const STATIC_CACHE = `refereex-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `refereex-dynamic-${CACHE_VERSION}`;

// Files to cache for offline use (excluding JavaScript files - they're always fetched fresh)
const STATIC_FILES = [
    '../refportal-pwa.html',
    '../css/refportal-pwa.css',
    '../refportal-manifest.json',
    './pwa-config.js', // Add config file to static cache
    '../images/RefereeX.png',
    '../images/favicon.png'
    // Note: CDN files like Plotly are not cached during install to avoid CORS issues
];

// Install event - cache static files
self.addEventListener('install', (event) => {
    console.log('Service Worker installing...');
    
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('Caching static files');
                return cache.addAll(STATIC_FILES);
            })
            .then(() => {
                console.log('Static files cached successfully');
                return self.skipWaiting();
            })
            .catch((error) => {
                console.error('Error caching static files:', error);
            })
    );

    event.waitUntil(
        // Create critical notification channel
        self.registration.pushManager.getSubscription().then(function(subscription) {
            if (subscription && 'Notification' in self) {
                // For Android, create a critical channel
                if ('Notification' in self && 'createChannel' in self.Notification) {
                    self.Notification.createChannel('critical', {
                        name: 'Critical Notifications',
                        importance: 'high',
                        sound: 'default',
                        vibration: [500, 200, 500, 200, 500],
                        enableVibration: true,
                        enableLights: true,
                        lightColor: '#FF0000', // Red light for critical
                        lockscreenVisibility: 'public', // Show on lock screen
                        bypassDnd: true // Bypass Do Not Disturb
                    });
                }
            }
        })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('Service Worker activating...');
    
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((cacheName) => {
                        // Delete all old caches that don't match current version
                        if (!cacheName.includes(CACHE_VERSION)) {
                            console.log('🗑️ Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        }
                    })
                );
            })
            .then(() => {
                console.log('✅ Service Worker activated with version:', CACHE_VERSION);
                // Always claim clients immediately so controller is available
                console.log('🔄 Claiming clients...');
                return self.clients.claim();
            })
            .then(() => {
                // Start periodic version checking
                startVersionChecking();
            })
    );
});

// Version checking functionality
function startVersionChecking() {
    // Wait a bit before first check to ensure clients are loaded
    setTimeout(() => {
        checkForUpdates();
    }, 2000);
    
    // Set up periodic checking
    setInterval(checkForUpdates, VERSION_CHECK_INTERVAL);
}

async function checkForUpdates() {
    try {
        console.log('🔍 Checking for updates...');
        console.log(`🔍 Current CACHE_VERSION: ${CACHE_VERSION}`);
        
        // First check if we have any clients
        const currentClients = await self.clients.matchAll({ includeUncontrolled: true });
        console.log(`📱 Current clients count: ${currentClients.length}`);
        
        // Create a completely fresh request with aggressive cache busting
        // Use multiple random parameters to ensure no cache hits
        const cacheBuster = `${Date.now()}_${Math.random().toString(36).substring(7)}`;
        const swUrl = new URL(`/js/refportal-sw.js?t=${cacheBuster}&v=${CACHE_VERSION}`, self.location.origin);
        
        // Create a new Request object with no-cache directives
        const request = new Request(swUrl.toString(), {
            method: 'GET',
            cache: 'no-store',
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate, max-age=0',
                'Pragma': 'no-cache',
                'Expires': '0',
                'X-Requested-With': 'ServiceWorker'
            }
        });
        
        console.log(`🔍 Fetching SW from: ${swUrl.toString()}`);
        
        // Fetch with bypassing all caches
        const response = await fetch(request);
        
        // Check response headers to see if it came from cache
        const cacheControl = response.headers.get('cache-control');
        const age = response.headers.get('age');
        const etag = response.headers.get('etag');
        const lastModified = response.headers.get('last-modified');
        console.log(`🔍 Response headers - Cache-Control: ${cacheControl}, Age: ${age}, ETag: ${etag}, Last-Modified: ${lastModified}`);
        
        if (response.ok) {
            const swContent = await response.text();
            console.log(`🔍 Fetched SW content length: ${swContent.length} chars`);
            
            // Check if content looks like it might be cached (same as current)
            const contentHash = swContent.substring(0, 100) + swContent.substring(swContent.length - 100);
            console.log(`🔍 Content hash (first+last 100 chars): ${contentHash.substring(0, 50)}...`);
            
            const versionMatch = swContent.match(/const CACHE_VERSION = ['"`]([^'"`]+)['"`]/);
            
            if (versionMatch) {
                const serverVersion = versionMatch[1];
                console.log(`🔍 Server version: "${serverVersion}", Current version: "${CACHE_VERSION}"`);
                console.log(`🔍 Versions match: ${serverVersion === CACHE_VERSION}`);
                console.log(`🔍 Version comparison: "${serverVersion}" !== "${CACHE_VERSION}" = ${serverVersion !== CACHE_VERSION}`);
                
                if (serverVersion !== CACHE_VERSION) {
                    console.log('🔄 New version detected:', serverVersion, 'vs current:', CACHE_VERSION);
                    await notifyClientsOfUpdate(serverVersion);
                } else {
                    console.log('⚠️ Version matches - this might indicate cached response');
                    console.log('⚠️ If you updated CACHE_VERSION on server, the cache might be serving old version');
                }
            } else {
                console.log('⚠️ Could not parse version from server response');
                console.log('⚠️ Looking for pattern: const CACHE_VERSION =');
                // Try to find any version-like string
                const anyVersionMatch = swContent.match(/CACHE_VERSION\s*=\s*['"`]([^'"`]+)['"`]/);
                if (anyVersionMatch) {
                    console.log('⚠️ Found alternative pattern:', anyVersionMatch[0]);
                }
            }
        } else {
            console.log('⚠️ Failed to fetch service worker file:', response.status, response.statusText);
        }
    } catch (error) {
        console.log('❌ Version check failed:', error);
        console.error('❌ Error details:', error);
    }
}

async function notifyClientsOfUpdate(newVersion) {
    // Notify all clients about the update
    try {
        const clientList = await self.clients.matchAll({
            includeUncontrolled: true // Include clients not controlled by this SW
        });
        
        console.log(`📢 Notifying ${clientList.length} clients about update:`, newVersion);
        
        clientList.forEach(client => {
            client.postMessage({
                type: 'UPDATE_AVAILABLE',
                newVersion: newVersion,
                currentVersion: CACHE_VERSION
            });
        });
        
        if (clientList.length === 0) {
            console.log('⚠️ No clients found to notify about update');
        }
    } catch (error) {
        console.error('❌ Error notifying clients:', error);
    }
}

// Fetch event - serve from cache when offline
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Bypass service worker for its own file to allow version checking
    // This ensures we always get the latest version from the server
    if (url.pathname.includes('refportal-sw.js')) {
        console.log('🔄 Bypassing SW cache for own file:', url.pathname);
        // Create a completely fresh request that bypasses all caches
        const freshRequest = new Request(request.url, {
            method: request.method,
            headers: request.headers,
            cache: 'no-store',
            credentials: request.credentials,
            redirect: request.redirect
        });
        // Let the request go directly to the network, bypassing all caches
        event.respondWith(fetch(freshRequest));
        return;
    }

    // Debug logging for config files
    if (url.pathname.includes('config') || url.pathname.includes('manifest')) {
        console.log('🔍 Service Worker: Fetching config file:', url.pathname);
        console.log('🔍 Request URL:', request.url);
        console.log('🔍 Request method:', request.method);
    }

    // Handle API requests differently
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(handleApiRequest(request));
        return;
    }

    // Handle static files (only GET requests can be cached)
    if (request.method === 'GET') {
        event.respondWith(handleStaticRequest(request));
        return;
    } else {
        console.log('📝 Skipping non-GET request in service worker:', request.method, request.url);
    }
});

/** True = do not call showNotification (silent / validation / empty title). */
function shouldSuppressPushDisplay(data) {
    if (!data || typeof data !== 'object') {
        return false;
    }
    const silentRaw = data.silent;
    const silent =
        silentRaw === true ||
        silentRaw === 1 ||
        (typeof silentRaw === 'string' &&
            ['true', '1', 'yes', 'on'].includes(silentRaw.trim().toLowerCase()));
    if (silent) {
        return true;
    }
    if (data.tag === 'subscription-validation') {
        return true;
    }
    const title = data.title != null ? String(data.title).trim() : '';
    if (!title) {
        return true;
    }
    return false;
}

// Push notification event listener
self.addEventListener('push', (event) => {
    console.log('📱 Push notification received:', event);
    
    if (event.data) {
        try {
            const data = event.data.json();
            console.log('📱 Push notification data:', data);
            
            if (shouldSuppressPushDisplay(data)) {
                console.log(
                    '🔇 Push suppressed (silent, validation, or no title):',
                    {
                        silent: data.silent,
                        tag: data.tag,
                        title: data.title,
                    }
                );
                sendMessageToClient({
                    type: 'PUSH_NOTIFICATION',
                    data: data
                });
                return;
            }
            
            // Show notification to user
            const notificationPromise = showPushNotification(data);
            event.waitUntil(notificationPromise);
            console.log('📱 Push notification after waitUntil');

            sendMessageToClient({
                type: 'PUSH_NOTIFICATION',
                data: data
            });
            console.log('📱 Push notification after sendMessageToClient');
        } 
        catch (error) {
            console.error('❌ Error parsing push notification data:', error);
            // Fallback to showing basic notification
            const notificationPromise = showBasicNotification('a');
            event.waitUntil(notificationPromise);
        }

    } else {
        console.log('📱 Push notification without data, showing basic notification');
        const notificationPromise = showBasicNotification('b');
        event.waitUntil(notificationPromise);
    }
});

/** Focus existing PWA window or open it; optionally deep-link via NOTIFICATION_NAVIGATE when data.section is set. */
async function focusOrOpenPwaClients(data) {
    const origin = self.location.origin;
    const pwaUrl = origin + '/refportal-pwa.html';
    const clientList = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true
    });

    for (const client of clientList) {
        if (client.url.includes('refportal-pwa.html') && 'focus' in client) {
            await client.focus();
            if (data && data.section && data.section !== 'dashboard') {
                client.postMessage({
                    type: 'NOTIFICATION_NAVIGATE',
                    section: data.section,
                    data: data
                });
                client.postMessage({
                    type: 'UPDATE_HASH',
                    hash: data.section
                });
            }
            return;
        }
    }

    if (self.clients.openWindow) {
        const newWindow = await self.clients.openWindow(pwaUrl);
        setTimeout(() => {
            if (newWindow && data && data.section && data.section !== 'dashboard') {
                newWindow.postMessage({
                    type: 'NOTIFICATION_NAVIGATE',
                    section: data.section,
                    data: data
                });
                newWindow.postMessage({
                    type: 'UPDATE_HASH',
                    hash: data.section
                });
            }
        }, 1000);
    }
}

// Notification click event listener
self.addEventListener('notificationclick', (event) => {
    console.log('🔘 Notification clicked:', event);
    event.notification.close();
    
    // Handle notification click based on action or data
    const notification = event.notification;
    const data = notification.data || {};
    const action = event.action || 'default';
    
    console.log('🔘 Notification clicked with action:', action);
    console.log('🔘 Notification data on click:', data);
    
    // iOS requires event.waitUntil() to keep service worker alive
    let clickPromise;
    
    // Handle different notification actions
    switch (action) {
        case 'view':
            clickPromise = handleNotificationView(data);
            break;
        case 'dismiss':
            clickPromise = handleNotificationDismiss(data);
            break;
        case 'login':
            clickPromise = handleNotificationPair(data);
            break;
        case 'chat':
            clickPromise = handleNotificationChat(data);
            break;
        case 'archive':
            // Perform the archive action
            console.log('Message archived.');
            clickPromise = Promise.resolve();
            break;
        case 'reply':
            // Get the user's typed reply
            const userReply = event.reply;
            console.log(`User replied: ${userReply}`);
            // Send the reply to your server
            clickPromise = Promise.resolve();
            break;
        case 'refresh-pwa':
            clickPromise = handlePwaRefreshNotificationClick(data);
            break;
        default:
            clickPromise = handleDefaultNotificationClick(data);
            break;
    }
    
    // iOS requires waitUntil to process the click
    event.waitUntil(clickPromise);
});

// Handle notification view action
async function handleNotificationView(data) {
    console.log('🔘 Handling notification view action:', data);
    try {
        await focusOrOpenPwaClients(data);
    } catch (error) {
        console.error('❌ Error handling notification view:', error);
    }
}


// Handle notification dismiss action
async function handleNotificationDismiss(data) {
    console.log('🔘 Handling notification dismiss action:', data);
    
    // You can track dismiss events here
    // For example, send analytics data to your server
    
    // Close any existing notifications with the same tag
    const notifications = await self.registration.getNotifications();
    notifications.forEach(notification => {
        if (notification.tag === data.tag) {
            notification.close();
        }
    });
}

// Handle notification login action
async function handleNotificationPair(data) {
    console.log('🔘 Handling notification login action:', data);
    
    // Focus existing window or open new one and navigate to login
    const clientList = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true
    });
    
    for (const client of clientList) {
        if (client.url.includes('/refportal-pwa.html') && 'focus' in client) {
            console.log('🔘 Focusing existing window for login action');
            await client.focus();
            
            client.postMessage({
                type: 'NOTIFICATION_PAIR',
                data: data
            });
            return;
        }
    }
    
    // If no existing window, open a new one
    if (self.clients.openWindow) {
        const origin = self.location.origin;
        const pwaUrl = origin + '/refportal-pwa.html';
        console.log('🔘 Opening new window for login action:', pwaUrl);
        const newWindow = await self.clients.openWindow(pwaUrl);
        
        setTimeout(() => {
            if (newWindow) {
                newWindow.postMessage({
                    type: 'NOTIFICATION_PAIR',
                    data: data
                });
            }
        }, 1000);
    }
}

// Handle notification chat action
async function handleNotificationChat(data) {
    console.log('🔘 Handling notification chat action:', data);
    
    // Focus existing window or open new one and navigate to chat
    const clientList = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true
    });
    
    for (const client of clientList) {
        if (client.url.includes('/refportal-pwa.html') && 'focus' in client) {
            console.log('🔘 Focusing existing window for chat action');
            await client.focus();
            
            client.postMessage({
                type: 'NOTIFICATION_CHAT',
                data: data
            });
            return;
        }
    }
    
    // If no existing window, open a new one
    if (self.clients.openWindow) {
        const origin = self.location.origin;
        const pwaUrl = origin + '/refportal-pwa.html';
        console.log('🔘 Opening new window for chat action:', pwaUrl);
        const newWindow = await self.clients.openWindow(pwaUrl);
        
        setTimeout(() => {
            if (newWindow) {
                newWindow.postMessage({
                    type: 'NOTIFICATION_CHAT',
                    data: data
                });
            }
        }, 1000);
    }
}

// Handle default notification click
async function handleDefaultNotificationClick(data) {
    console.log('🔘 Handling default notification click:', data);
    
    try {
        if (data && data.pwaRefresh === true) {
            console.log('🔘 PWA refresh push (body tap)');
            await handlePwaRefreshNotificationClick(data);
            return;
        }
        if (data && data.section && data.section !== 'dashboard') {
            console.log('🔘 Deep link from notification body:', data.section);
            await focusOrOpenPwaClients(data);
            return;
        }

        // Get the origin for absolute URLs (required for iOS)
        const origin = self.location.origin;
        
        // If there's a URL in the notification data, open it
        if (data && data.url) {
            console.log('🔘 Opening URL from notification:', data.url);
            
            // Convert relative URLs to absolute (iOS requirement)
            let urlToOpen = data.url;
            if (urlToOpen.startsWith('/')) {
                urlToOpen = origin + urlToOpen;
            } else if (!urlToOpen.startsWith('http://') && !urlToOpen.startsWith('https://')) {
                urlToOpen = origin + '/' + urlToOpen;
            }
            
            console.log('🔘 Absolute URL:', urlToOpen);
            
            // Try to open in existing client first
            const clientList = await self.clients.matchAll({
                type: 'window',
                includeUncontrolled: true
            });
            
            for (const client of clientList) {
                if (client.url.includes('refportal-pwa.html') && 'focus' in client) {
                    console.log('🔘 Focusing existing window and navigating to URL');
                    await client.focus();
                    client.postMessage({
                        type: 'NOTIFICATION_CLICK',
                        url: urlToOpen
                    });
                    return;
                }
            }
            
            // If no existing window, open new one with URL
            if (self.clients.openWindow) {
                console.log('🔘 Opening new window with URL:', urlToOpen);
                await self.clients.openWindow(urlToOpen);
                return;
            }
        }
        
        // Default action - focus existing window or open new one
        await focusOrOpenPwaClients({});
    } catch (error) {
        console.error('❌ Error handling notification click:', error);
        // Fallback: try to open the PWA
        try {
            if (self.clients.openWindow) {
                await self.clients.openWindow(self.location.origin + '/refportal-pwa.html');
            }
        } catch (fallbackError) {
            console.error('❌ Fallback error:', fallbackError);
        }
    }
}

/** Deploy broadcast: focus PWA and tell the page to apply waiting SW + reload. */
async function handlePwaRefreshNotificationClick(data) {
    console.log('🔘 Handling PWA refresh notification:', data);
    const origin = self.location.origin;
    const pwaUrl = origin + '/refportal-pwa.html';
    try {
        const clientList = await self.clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        });
        for (const client of clientList) {
            if (client.url.includes('refportal-pwa.html') && 'focus' in client) {
                await client.focus();
                client.postMessage({ type: 'PWA_REFRESH_FROM_PUSH', data: data || {} });
                return;
            }
        }
        if (self.clients.openWindow) {
            const newWindow = await self.clients.openWindow(pwaUrl);
            setTimeout(() => {
                if (newWindow) {
                    newWindow.postMessage({ type: 'PWA_REFRESH_FROM_PUSH', data: data || {} });
                }
            }, 2000);
        }
    } catch (err) {
        console.error('❌ handlePwaRefreshNotificationClick:', err);
    }
}

// Notification close event listener
self.addEventListener('notificationclose', (event) => {
    console.log('📱 Notification closed:', event);
    
    const notification = event.notification;
    const data = notification.data || {};
    
    console.log('📱 Notification data on close:', data);
    
    // You can track notification close events here
    // For example, send analytics data to your server
});

// Show push notification with custom data
async function showPushNotification(data) {
    if (shouldSuppressPushDisplay(data)) {
        console.log('🔇 showPushNotification: suppressed');
        return null;
    }

    let options = {
        body: data.body || 'הודעה1 חדשה מ-RefereeX',
        icon: data.icon || '/images/RefereeX.png',
        badge: data.badge || '/images/RefereeX.png',
        image: data.image,
        tag: data.tag || 'refereex-notification',
        data: data,
        requireInteraction: data.requireInteraction || false,
        silent: data.silent || false,
        vibrate: data.vibrate || [200, 100, 200],
        actions: data.actions || [],
        dir: 'rtl', // Right-to-left for Hebrew
        lang: 'he-IL'
    };

    if (data.pwaRefresh === true && (!data.actions || !data.actions.length)) {
        options.actions = [
            {
                action: 'refresh-pwa',
                title: 'רענון אפליקציה',
                icon: '/images/RefereeX.png'
            },
            {
                action: 'dismiss',
                title: 'סגור',
                icon: '/images/RefereeX.png'
            }
        ];
    } else if (data.section === 'games' && (!data.actions || !data.actions.length)) {
        options.actions = [
            {
                action: 'view',
                title: 'שיבוצים',
                icon: '/images/RefereeX.png'
            },
            {
                action: 'dismiss',
                title: 'סגור',
                icon: '/images/RefereeX.png'
            }
        ];
    } else if (data.section === 'reviews' && (!data.actions || !data.actions.length)) {
        options.actions = [
            {
                action: 'view',
                title: 'ביקורות',
                icon: '/images/RefereeX.png'
            },
            {
                action: 'dismiss',
                title: 'סגור',
                icon: '/images/RefereeX.png'
            }
        ];
    } else if (!options.actions || options.actions.length === 0) {
        options.actions = [
            {
                action: 'view',
                title: 'צפה',
                icon: '/images/RefereeX.png'
            },
            {
                action: 'dismiss',
                title: 'סגור',
                icon: '/images/RefereeX.png'
            },
            {
                action: 'reply',
                type: 'text',
                title: 'הגב',
                placeholder: 'Type your reply here'
            },
            {
                action: 'archive',
                type: 'button',
                title: 'Archive'
            }
        ];
    }

    const isCritical = data.critical || data.priority === 'high' || data.urgency === 'high';

    if (isCritical) {
        // Critical notification options
        Object.assign(options, {
            requireInteraction: true, // Won't auto-dismiss
            silent: false, // Play sound
            vibrate: [500, 200, 500, 200, 500, 200], // Aggressive vibration
            sound: 'default',
            channelId: 'critical', // Use critical channel
            importance: 'high',
            priority: 'high',
            // iOS specific
            subtitle: 'הודעה דחופה', // Add subtitle for critical
        });

        options.actions.push({
            action: 'acknowledge',
            title: 'אישור קבלה',
            icon: '../images/RefereeX.png'
        });
    }
    
    console.log('📱 Showing push notification with options:', options);
    
    try {
        const notification = await self.registration.showNotification(
            isCritical ? 'RefereeX Critical!!!' : String(data.title).trim(),
            options
        );
        console.log('✅ Push notification shown successfully:', notification);
        return notification;
    } catch (error) {
        console.error('❌ Error showing push notification:', error);
        // Fallback to basic notification
        return showBasicNotification('c');
    }
}

// Show basic fallback notification
async function showBasicNotification(from) {
    const options = {
        body: 'הודעה2 חדשה מ-RefereeX ' + from,
        icon: '/images/RefereeX.png',
        badge: '/images/RefereeX.png',
        tag: 'refereex-basic-notification',
        requireInteraction: false,
        silent: false,
        vibrate: [200, 100, 200],
        dir: 'rtl',
        lang: 'he-IL'
    };
    
    try {
        const notification = await self.registration.showNotification(
            'RefereeX',
            options
        );
        console.log('✅ Basic notification shown successfully:', notification);
        return notification;
    } catch (error) {
        console.error('❌ Error showing basic notification:', error);
        return null;
    }
}

// Handle static file requests
async function handleStaticRequest(request) {
    let fileUrl = null;
    let networkResponse = null;
    try {
        const url = new URL(request.url);
        fileUrl = request.url.toString();
        const isJavaScriptFile = url.pathname.endsWith('.js');
        
        // Special handling for config files - always try cache first, then network
        if (url.pathname.includes('config') || url.pathname.includes('manifest')) {
            console.log('🔧 Special handling for config file:', url.pathname);
            
            // First try to serve from cache
            const cachedResponse = await caches.match(request);
            if (cachedResponse) {
                console.log('✅ Serving config file from cache:', url.pathname);
                return cachedResponse;
            }
            
            // If not in cache, fetch from network
            try {
                networkResponse = await fetch(request, {
                    cache: 'no-cache',
                    headers: {
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        'Pragma': 'no-cache',
                        'Expires': '0'
                    }
                });
                
                if (networkResponse.ok) {
                    console.log('✅ Config file fetched from network:', url.pathname);
                    // Cache the response for future use
                    const cache = await caches.open(DYNAMIC_CACHE);
                    cache.put(request, networkResponse.clone());
                    return networkResponse;
                } else {
                    console.warn('⚠️ Network fetch failed for config file:', url.pathname, networkResponse.status);
                    throw new Error('Network fetch failed for config file');
                }
            } catch (networkError) {
                console.error('❌ Error fetching config file from network:', url.pathname, networkError);
                throw networkError;
            }
        }
        
        // For other JavaScript files, NEVER use cache - always fetch fresh from network
        if (isJavaScriptFile) {
            console.log('🔄 ALWAYS fetching JavaScript file from network (no cache):', url.pathname);
            
            // Special handling for CDN files
            const isCDNFile = url.hostname.indexOf('refereex.com') == -1;
            if (isCDNFile) {
                console.log('🌐 CDN file detected:', url.hostname);
            }
            
            try {
                // Add cache-busting timestamp to ensure fresh fetch
                const cacheBustUrl = new URL(request.url);
                //cacheBustUrl.searchParams.delete('_t');
                //cacheBustUrl.searchParams.append('_t', Date.now().toString());
                fileUrl = cacheBustUrl.toString();
                
                const fetchOptions = {
                    cache: 'no-cache',
                    mode: 'cors', // Explicitly set CORS mode for CDN files
                    headers: {
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        'Pragma': 'no-cache',
                        'Expires': '0'
                    }
                };
                
                console.log('🌐 Fetching CDN file with options:', fetchOptions);
                networkResponse = await fetch(cacheBustUrl, fetchOptions);
                
                if (networkResponse.ok) {
                    console.log('✅ Fresh JavaScript file fetched from network:', url.pathname);
                    return networkResponse;
                } else {
                    console.warn('⚠️ Network fetch failed for JS file:', url.pathname, networkResponse.status);
                    // Don't fall back to cache for JS files
                    throw new Error(`Network fetch failed for JS file: ${networkResponse.status} ${networkResponse.statusText}`);
                }
            } catch (networkError) {
                console.error('❌ Critical error fetching JS file from network:', url.pathname, networkError);
                console.error('❌ Error details:', {
                    url: request.url,
                    pathname: url.pathname,
                    method: request.method,
                    hostname: url.hostname,
                    isCDN: isCDNFile,
                    error: networkError.message,
                    stack: networkError.stack
                });
                
                // For JS files, we don't want to serve cached versions
                // But for CDN files, we might want to provide a fallback
                if (isCDNFile) {
                    console.warn('🌐 CDN file failed, providing fallback response');
                    // Return a basic response that won't break the page
                    return new Response('// CDN file failed to load', {
                        status: 200,
                        statusText: 'OK',
                        headers: { 'Content-Type': 'application/javascript' }
                    });
                } else {
                    throw networkError;
                }
            }
        }

        // HTML: network-first when online so the shell (and script ?v=) updates; offline falls back to cache
        if (
            request.method === 'GET' &&
            (url.pathname.endsWith('.html') || url.pathname.endsWith('.htm'))
        ) {
            try {
                const networkResponse = await fetch(request, {
                    cache: 'no-cache',
                    headers: {
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        Pragma: 'no-cache',
                    },
                });
                if (networkResponse.ok) {
                    const cache = await caches.open(DYNAMIC_CACHE);
                    cache.put(request, networkResponse.clone());
                    console.log('🌐 Fresh HTML from network:', url.pathname);
                    return networkResponse;
                }
            } catch (networkError) {
                console.warn(
                    '⚠️ HTML network fetch failed, trying cache:',
                    url.pathname,
                    networkError,
                );
            }
            const htmlCached = await caches.match(request);
            if (htmlCached) {
                console.log('📦 Serving HTML from cache (offline):', url.pathname);
                return htmlCached;
            }
        }
        
        // For non-JS files, use normal caching strategy
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            console.log('📦 Serving from cache:', url.pathname);
            return cachedResponse;
        }

        // If not in cache, fetch from network
        networkResponse = await fetch(request);
        
        // Cache the response for future use (only non-JS files and GET requests)
        if (networkResponse.ok && request.method === 'GET') {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, networkResponse.clone());
            
            // Special handling for config files
            if (url.pathname.includes('config') || url.pathname.includes('manifest')) {
                console.log('💾 Cached config file for future use:', url.pathname);
            }
        } else if (request.method !== 'GET') {
            console.log('📝 Skipping cache for non-GET static request:', request.method, request.url);
        }
        
        return networkResponse;
    } catch (error) {
        console.error('Error handling static request:', error);
        
        // Return offline page if available
        const offlineResponse = await caches.match('/refportal-pwa.html');
        if (offlineResponse) {
            return offlineResponse;
        }
        
        // Return a basic offline response
        return new Response('אין חיבור לאינטרנט', {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
    }
}

// Handle API requests
async function handleApiRequest(request) {
    let response = null;
    try {
        // Try to fetch from network
        response = await fetch(request);
        
        // Cache successful responses (only GET requests can be cached)
        if (response.ok && request.method === 'GET') {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, response.clone());
            console.log('💾 Cached API response:', request.url);
        } else if (request.method !== 'GET') {
            console.log('📝 Skipping cache for non-GET request:', request.method, request.url);
        }
        
        return response;
    } catch (error) {
        console.error('Error handling API request:', error, request.url);
        
        // Try to serve from cache if available (only for GET requests)
        if (request.method === 'GET') {
            const cachedResponse = await caches.match(request);
            if (cachedResponse) {
                console.log('📦 Serving cached API response:', request.url);
                return cachedResponse;
            }
        } else {
            console.log('📝 Skipping cache lookup for non-GET API request:', request.method, request.url);
        }
        
        // Return offline response
        return new Response(JSON.stringify({
            error: 'אין חיבור לאינטרנט',
            offline: true
        }), {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'application/json; charset=utf-8' }
        });
    }
}

// Background sync for offline actions
self.addEventListener('sync', (event) => {
    console.log('Background sync triggered:', event.tag);
    
    if (event.tag === 'background-sync') {
        event.waitUntil(performBackgroundSync());
    } else if (event.tag === 'badge-update-sync') {
        // Trigger API call for badge updates
        event.waitUntil(triggerApiCallForClients().then(() => {
            // Re-register for next sync (if interval is still active)
            if (backgroundSyncInterval) {
                return self.registration.sync.register('badge-update-sync').catch(() => {});
            }
        }));
    }
});

self.addEventListener('backgroundsync', (event) => {
    console.log('Background sync triggered:', event.tag);
    
    if (event.tag === 'background-sync') {
        event.waitUntil(performBackgroundSync());
    }
});

// Perform background sync
async function performBackgroundSync() {
    try {
        // Get pending actions from IndexedDB or cache
        const pendingActions = await getPendingActions();
        
        for (const action of pendingActions) {
            try {
                await performAction(action);
                await removePendingAction(action.id);
            } catch (error) {
                console.error('Error performing background action:', error);
            }
        }
        
        console.log('Background sync completed');
    } catch (error) {
        console.error('Background sync failed:', error);
    }
}

// Get pending actions (implement based on your storage strategy)
async function getPendingActions() {
    // This is a placeholder - implement based on your needs
    return [];
}

// Perform an action (implement based on your needs)
async function performAction(action) {
    // This is a placeholder - implement based on your needs
    console.log('Performing action:', action);
}

// Remove pending action (implement based on your storage strategy)
async function removePendingAction(id) {
    // This is a placeholder - implement based on your needs
    console.log('Removing action:', id);
}

// Send message to client
function sendMessageToClient(message) {
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
        .then((clientList) => {
            clientList.forEach((client) => {
                console.log('📱 Message:', message);
                console.log('📱 Client:', client);
                if (client.url.includes('refportal-pwa.html')) {
                    client.postMessage(message);
                }
            });
        });
}

// Handle messages from clients
self.addEventListener('message', async (event) => {
    console.log('Service Worker received message:', event.data);
    
    if (!event.data || !event.data.type) {
        return;
    }
    
    // Service worker lifecycle messages
    if (event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
        return;
    }
    
    if (event.data.type === 'GET_VERSION') {
        if (event.ports && event.ports[0]) {
            event.ports[0].postMessage({ version: CACHE_NAME });
        }
        return;
    }
    
    if (event.data.type === 'CLEAR_CACHE') {
        console.log('🧹 Clearing all caches...');
        event.waitUntil(
            caches.keys().then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((cacheName) => {
                        console.log('🗑️ Deleting cache:', cacheName);
                        return caches.delete(cacheName);
                    })
                );
            }).then(() => {
                console.log('✅ All caches cleared');
                // Notify clients that cache was cleared
                sendMessageToClient({ type: 'CACHE_CLEARED' });
            })
        );
        return;
    }
    
    if (event.data.type === 'REFRESH_JS_FILES') {
        console.log('🔄 Refreshing JavaScript files...');
        event.waitUntil(
            caches.open(DYNAMIC_CACHE).then((cache) => {
                // Clear only JS files from dynamic cache
                return cache.keys().then((requests) => {
                    const jsRequests = requests.filter((request) => {
                        const url = new URL(request.url);
                        return url.pathname.endsWith('.js');
                    });
                    
                    return Promise.all(
                        jsRequests.map((request) => {
                            console.log('🗑️ Removing JS file from cache:', request.url);
                            return cache.delete(request);
                        })
                    );
                });
            }).then(() => {
                console.log('✅ JavaScript files cache cleared');
                sendMessageToClient({ type: 'JS_CACHE_CLEARED' });
            })
        );
        return;
    }
    
    // Background API sync messages
    if (event.data.type === 'START_BACKGROUND_SYNC') {
        // Start periodic background sync for API calls
        await startBackgroundApiSync(event.data.interval || 30000);
        if (event.ports && event.ports[0]) {
            event.ports[0].postMessage({ success: true });
        }
        return;
    }
    
    if (event.data.type === 'STOP_BACKGROUND_SYNC') {
        // Stop periodic background sync
        await stopBackgroundApiSync();
        if (event.ports && event.ports[0]) {
            event.ports[0].postMessage({ success: true });
        }
        return;
    }
    
    if (event.data.type === 'TRIGGER_API_CALL') {
        // Trigger immediate API call
        await triggerApiCallForClients();
        if (event.ports && event.ports[0]) {
            event.ports[0].postMessage({ success: true });
        }
        return;
    }
    
    if (event.data.type === 'GET_AUTH_TOKEN') {
        // Client is requesting to provide auth token
        // This is handled by the client side, service worker receives response
        if (event.ports && event.ports[0]) {
            // Try to get token from IndexedDB first
            (async () => {
                try {
                    const db = await new Promise((resolve, reject) => {
                        const request = indexedDB.open('refereex-auth', 1);
                        request.onerror = () => reject(request.error);
                        request.onsuccess = () => resolve(request.result);
                    });
                    
                    const transaction = db.transaction(['tokens'], 'readonly');
                    const store = transaction.objectStore('tokens');
                    const tokenRequest = store.get('access_token');
                    const configRequest = store.get('api_config');
                    
                    const token = await new Promise((resolve) => {
                        tokenRequest.onsuccess = () => resolve(tokenRequest.result);
                        tokenRequest.onerror = () => resolve(null);
                    });
                    
                    const config = await new Promise((resolve) => {
                        configRequest.onsuccess = () => resolve(configRequest.result);
                        configRequest.onerror = () => resolve(null);
                    });
                    
                    if (token) {
                        event.ports[0].postMessage({ 
                            token: token,
                            apiBaseUrl: config?.API_BASE_URL || 'https://pwa-dev.refereex.com:5003'
                        });
                    } else {
                        // Request from client
                        const clients = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
                        if (clients.length > 0) {
                            const messageChannel = new MessageChannel();
                            const tokenPromise = new Promise((resolve) => {
                                messageChannel.port1.onmessage = (msgEvent) => {
                                    resolve(msgEvent.data);
                                };
                                setTimeout(() => resolve(null), 2000);
                            });
                            clients[0].postMessage({ type: 'GET_AUTH_TOKEN' }, [messageChannel.port2]);
                            const tokenData = await tokenPromise;
                            if (tokenData && event.ports && event.ports[0]) {
                                event.ports[0].postMessage(tokenData);
                            }
                        }
                    }
                } catch (error) {
                    console.error('Error getting token from IndexedDB:', error);
                }
            })();
        }
        return;
    }
});

// Periodic background sync (if supported)
if ('periodicSync' in self.registration) {
    self.addEventListener('periodicsync', (event) => {
        console.log('Periodic sync triggered:', event.tag);
        
        if (event.tag === 'content-update') {
            event.waitUntil(updateContent());
        } else if (event.tag === 'badge-update') {
            // Trigger API call for badge updates
            event.waitUntil(triggerApiCallForClients());
        }
    });
}

// Update content periodically
async function updateContent() {
    try {
        // Implement content update logic
        console.log('Updating content...');
        
        // Example: Check for new games, reviews, etc.
        // This would typically involve API calls and cache updates
        
    } catch (error) {
        console.error('Error updating content:', error);
    }
}


// Background API sync interval
let testInterval = null;
let backgroundSyncInterval = null;
let periodicSyncRegistered = false;

// Start periodic background API sync
async function startBackgroundApiSync(interval) {
    // Clear any existing interval
    if (testInterval) {
        clearInterval(testInterval);
        testInterval = null;
    }

    if (backgroundSyncInterval) {
        clearInterval(backgroundSyncInterval);
        backgroundSyncInterval = null;
    }
    
    console.log(`🔄 Starting background API sync every ${interval}ms`);
    
    // Try to use Periodic Background Sync API (more reliable than setInterval)
    if ('periodicSync' in self.registration) {
        try {
            // Register periodic sync for badge updates
            await self.registration.periodicSync.register('badge-update', {
                minInterval: Math.max(interval, 60000) // Minimum 60 seconds for periodic sync
            });
            periodicSyncRegistered = true;
            console.log('✅ Registered Periodic Background Sync for badge updates');
        } catch (error) {
            console.warn('⚠️ Periodic Background Sync registration failed:', error);
            // Fall back to setInterval
        }
    } else {
        // Fall back to setInterval if Periodic Background Sync is not supported
        console.log('⚠️ Periodic Background Sync not supported, using setInterval fallback');
    }
    
    await makeLogApiCall('info', '📊 SW: test log message in BG')
    testInterval = setInterval(async () => {
        console.log('⏰ test log message in BG sync interval triggered');
        await makeLogApiCall('info', '📊 SW: test log message in BG sync interval triggered')
    }, 1000 * 60 * 5);

        // Also use setInterval as a fallback/backup (works when SW is active)
    // Trigger immediately
    await triggerApiCallForClients();
    
    // Then set up interval
    backgroundSyncInterval = setInterval(async () => {
        console.log('⏰ Background sync interval triggered');
        await triggerApiCallForClients();
    }, interval);
    
    // Also register Background Sync as a fallback (one-time sync that can wake up SW)
    if ('sync' in self.registration) {
        try {
            // Register a background sync that will trigger periodically
            // Note: This is a one-time sync, so we'll re-register it each time
            await self.registration.sync.register('badge-update-sync');
            console.log('✅ Registered Background Sync as fallback');
        } catch (error) {
            console.warn('⚠️ Background Sync registration failed:', error);
        }
    }
}

// Stop periodic background API sync
async function stopBackgroundApiSync() {
    // Clear interval
    if (testInterval) {
        clearInterval(testInterval);
        testInterval = null;
    }
    
    if (backgroundSyncInterval) {
        clearInterval(backgroundSyncInterval);
        backgroundSyncInterval = null;
    }
    
    // Unregister periodic sync if registered
    if (periodicSyncRegistered && 'periodicSync' in self.registration) {
        try {
            await self.registration.periodicSync.unregister('badge-update');
            periodicSyncRegistered = false;
            console.log('✅ Unregistered Periodic Background Sync');
        } catch (error) {
            console.warn('⚠️ Failed to unregister Periodic Background Sync:', error);
        }
    }
    
    console.log('🛑 Stopped background API sync');
}

// Trigger API call for all clients
async function triggerApiCallForClients() {
    try {
        // On mobile, the page JavaScript is suspended when in background
        // So we need to make the API call directly from the service worker
        // and update the badge directly
        
        console.log('📡 Triggering background API call from service worker');
        
        // Get all clients to check their visibility state
        const clients = await self.clients.matchAll({
            includeUncontrolled: true,
            type: 'window'
        });
        
        // Check if any client is visible/focused
        const hasVisibleClient = clients.some(client => 
            client.visibilityState === 'visible' || client.focused
        );
        
        if (hasVisibleClient) {
            // If page is visible, let the client handle the API call
            // This avoids duplicate API calls
            console.log('📡 Page is visible, notifying client to make API call');
            const messagePromises = clients
                .filter(client => client.visibilityState === 'visible' || client.focused)
                .map(client => {
                    try {
                        return client.postMessage({
                            type: 'MAKE_API_CALL',
                            timestamp: Date.now()
                        });
                    } catch (error) {
                        console.error('Error posting message to client:', error);
                        return Promise.resolve();
                    }
                });
            await Promise.allSettled(messagePromises);
        } else {
            // If page is hidden/background, make API call directly from service worker
            // This works even when page JavaScript is suspended
            console.log('📡 Page is hidden, making API call directly from service worker');
            await makeBadgeUpdateApiCall();
        }
        
        console.log('✅ Background API call completed');
    } catch (error) {
        console.error('Error in triggerApiCallForClients:', error);
        // Fallback: try direct API call if client notification fails
        try {
            await makeBadgeUpdateApiCall();
        } catch (fallbackError) {
            console.error('Fallback API call also failed:', fallbackError);
        }
    }
}

/** Pending games count — must match RefPortalApp.getPendingGames() in refportal-pwa.js */
function countPendingGamesFromApiList(games) {
    const now = new Date();
    return games.filter((game) => {
        const rawDate = game.date || game.gameDate || game.game_date || game.scheduledDate || game.gameDateTime;
        if (!rawDate) return false;
        const gameDateTime = new Date(rawDate);
        if (isNaN(gameDateTime.getTime())) return false;
        const state = game.state || game.gameState;
        return state !== 'archived' && state !== 'removed' && state !== 'canceled' && gameDateTime > now;
    }).length;
}

// Make API call directly from service worker to update badge
async function makeBadgeUpdateApiCall() {
    try {
        // Try to get token from IndexedDB (service workers can access IndexedDB)
        let token = null;
        let apiBaseUrl = 'https://pwa-dev.refereex.com:5003';
        
        try {
            // Open IndexedDB to get token
            const db = await new Promise((resolve, reject) => {
                const request = indexedDB.open('refereex-auth', 1);
                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve(request.result);
                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    if (!db.objectStoreNames.contains('tokens')) {
                        db.createObjectStore('tokens');
                    }
                };
            });
            
            const transaction = db.transaction(['tokens'], 'readonly');
            const store = transaction.objectStore('tokens');
            const tokenRequest = store.get('access_token');
            
            token = await new Promise((resolve, reject) => {
                tokenRequest.onsuccess = () => resolve(tokenRequest.result);
                tokenRequest.onerror = () => reject(tokenRequest.error);
            });
            
            const configRequest = store.get('api_config');
            const config = await new Promise((resolve, reject) => {
                configRequest.onsuccess = () => resolve(configRequest.result);
                configRequest.onerror = () => reject(configRequest.error);
            });
            
            if (config && config.API_BASE_URL) {
                apiBaseUrl = config.API_BASE_URL;
            }
        } catch (dbError) {
            console.warn('⚠️ Could not access IndexedDB, trying to request token from client:', dbError);
            // Try to get token from client via message
            const clients = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
            if (clients.length > 0) {
                // Request token from first client
                const messageChannel = new MessageChannel();
                const tokenPromise = new Promise((resolve) => {
                    messageChannel.port1.onmessage = (event) => {
                        if (event.data && event.data.token) {
                            resolve({
                                token: event.data.token,
                                apiBaseUrl: event.data.apiBaseUrl || 'https://pwa-dev.refereex.com:5003'
                            });
                        } else {
                            resolve(null);
                        }
                    };
                    // Timeout after 2 seconds
                    setTimeout(() => resolve(null), 2000);
                });
                
                clients[0].postMessage({ type: 'GET_AUTH_TOKEN' }, [messageChannel.port2]);
                const tokenData = await tokenPromise;
                if (tokenData) {
                    token = tokenData.token;
                    apiBaseUrl = tokenData.apiBaseUrl;
                }
            }
        }
        
        if (!token) {
            console.warn('⚠️ No auth token available, skipping badge update');
            return;
        }
        
        // Make API call to get referee games
        const gamesUrl = `${apiBaseUrl}/api/pwa/refereeGames`;
        //await makeLogApiCall('info', `📊 SW: Making API call to get referee games: ${gamesUrl}`)
        const response = await fetch(gamesUrl, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            cache: 'no-cache'
        });
        
        //await makeLogApiCall('info', `📊 SW: API call to get referee games response: ${response.ok} ${response.status}`)
        if (!response.ok) {
            if (response.status === 401) {
                console.warn('⚠️ Token expired, badge update skipped');
            } else {
                console.warn(`⚠️ API call failed: ${response.status} ${response.statusText}`);
            }
            return;
        }
        
        const result = await response.json();
        const games = result.data || result.games || [];
        const gamesCount = games.length;
        const pendingCount = countPendingGamesFromApiList(games);
        let msg = `📊 Found ${gamesCount} games, ${pendingCount} pending games`;
        console.log(msg);
        //await makeLogApiCall('info', `📊 SW: ${msg}`)
        
        // Update badge directly from service worker
        if ('setAppBadge' in navigator) {
            //return;
            if (pendingCount > 0) {
                const badgeValue = Math.min(pendingCount, 99);
                await navigator.setAppBadge(badgeValue);
                console.log(`✅ Badge updated to ${badgeValue} from service worker`);
            } else {
                await navigator.clearAppBadge();
                console.log('✅ Badge cleared from service worker');
            }
        } else {
            console.warn('⚠️ Badge API not supported');
        }
        
    } catch (error) {
        console.error('Error making badge update API call:', error);
    }
}

// Make API call to POST log data
async function makeLogApiCall(level = 'info', message = '', type = 'service-worker', data = {}) {
    try {
        // Try to get token from IndexedDB (service workers can access IndexedDB)
        let token = null;
        let apiBaseUrl = 'https://pwa-dev.refereex.com:5003';
        
        try {
            // Open IndexedDB to get token
            const db = await new Promise((resolve, reject) => {
                const request = indexedDB.open('refereex-auth', 1);
                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve(request.result);
                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    if (!db.objectStoreNames.contains('tokens')) {
                        db.createObjectStore('tokens');
                    }
                };
            });
            
            const transaction = db.transaction(['tokens'], 'readonly');
            const store = transaction.objectStore('tokens');
            const tokenRequest = store.get('access_token');
            
            token = await new Promise((resolve, reject) => {
                tokenRequest.onsuccess = () => resolve(tokenRequest.result);
                tokenRequest.onerror = () => reject(tokenRequest.error);
            });
            
            const configRequest = store.get('api_config');
            const config = await new Promise((resolve, reject) => {
                configRequest.onsuccess = () => resolve(configRequest.result);
                configRequest.onerror = () => reject(configRequest.error);
            });
            
            if (config && config.API_BASE_URL) {
                apiBaseUrl = config.API_BASE_URL;
            }
        } catch (dbError) {
            console.warn('⚠️ Could not access IndexedDB, trying to request token from client:', dbError);
            // Try to get token from client via message
            const clients = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
            if (clients.length > 0) {
                // Request token from first client
                const messageChannel = new MessageChannel();
                const tokenPromise = new Promise((resolve) => {
                    messageChannel.port1.onmessage = (event) => {
                        if (event.data && event.data.token) {
                            resolve({
                                token: event.data.token,
                                apiBaseUrl: event.data.apiBaseUrl || 'https://pwa-dev.refereex.com:5003'
                            });
                        } else {
                            resolve(null);
                        }
                    };
                    // Timeout after 2 seconds
                    setTimeout(() => resolve(null), 2000);
                });
                
                clients[0].postMessage({ type: 'GET_AUTH_TOKEN' }, [messageChannel.port2]);
                const tokenData = await tokenPromise;
                if (tokenData) {
                    token = tokenData.token;
                    apiBaseUrl = tokenData.apiBaseUrl;
                }
            }
        }
        
        if (!token) {
            console.warn('⚠️ No auth token available, skipping log API call');
            return;
        }
        
        // Prepare log data
        const logData = {
            level: level.toLowerCase(),
            message: message,
            type: type,
            data: data
        };
        
        // Make API call to POST log
        const logUrl = `${apiBaseUrl}/api/pwa/log`;
        const response = await fetch(logUrl, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(logData),
            cache: 'no-cache'
        });
        
        if (!response.ok) {
            if (response.status === 401) {
                console.warn('⚠️ Token expired, log API call skipped');
            } else {
                console.warn(`⚠️ Log API call failed: ${response.status} ${response.statusText}`);
            }
            return;
        }
        
        console.log('✅ Log sent successfully from service worker');
        
    } catch (error) {
        console.error('Error making log API call:', error);
    }
}

// Handle errors
self.addEventListener('error', (event) => {
    console.error('Service Worker error:', event.error);
});

self.addEventListener('unhandledrejection', (event) => {
    console.error('Service Worker unhandled rejection:', event.reason);
});

console.log('RefereeX Service Worker loaded successfully');
