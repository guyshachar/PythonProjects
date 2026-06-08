/**
 * Service Worker for RefereeX Apple Watch PWA
 * Provides offline functionality and caching
 */

const CACHE_NAME = 'refereeX-watch-v1';
const urlsToCache = [
    './refportal-watch.html',
    './css/refportal-watch.css',
    './js/refportal-watch.js',
    './images/RefereeX.png',
    './images/RefereeX_final_192x192.png',
    './images/RefereeX_final_512x512.png'
];

// Install event - cache resources
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache);
            })
    );
});

// Fetch event - serve from cache when offline
self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                // Return cached version or fetch from network
                if (response) {
                    return response;
                }
                return fetch(event.request);
            }
        )
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

