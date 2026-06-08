/**
 * PWA Auto-Refresh Module
 * Provides automatic refresh functionality for PWA updates
 * 
 * Features:
 * - Hot Module Replacement (HMR) integration
 * - PWA service worker updates
 * - Automatic refresh on file changes
 * - Connection status monitoring
 */

export class VitePWARefresh {
    constructor(options = {}) {
        this.options = {
            enableLogging: options.enableLogging !== false,
            autoConnect: options.autoConnect !== false,
            checkInterval: options.checkInterval || 5000,
            ...options
        };
        
        this.isConnected = false;
        this.checkTimer = null;
        this.lastUpdate = null;
        
        // Bind methods
        this.init = this.init.bind(this);
        this.checkForUpdates = this.checkForUpdates.bind(this);
        this.handleUpdate = this.handleUpdate.bind(this);
    }
    
    async init() {
        this.log('Initializing PWA Auto-Refresh...');
        
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            await new Promise(resolve => {
                document.addEventListener('DOMContentLoaded', resolve);
            });
        }
        
        // Setup refresh if autoConnect is enabled
        if (this.options.autoConnect) {
            await this.setupRefresh();
        }
        
        // Expose global API
        window.VitePWARefresh = this;
    }
    
    async setupRefresh() {
        this.log('Setting up PWA auto-refresh...');
        
        // Check if we're in development mode
        if (this.isDevelopmentMode()) {
            await this.setupDevelopmentRefresh();
        } else {
            await this.setupProductionRefresh();
        }
        
        // Setup debug controls (removed manual header button)
        this.setupDebugControls();
        
        // Start update checking
        this.startUpdateChecking();
    }
    
    isDevelopmentMode() {
        return window.location.hostname === 'localhost' || 
               window.location.hostname === '127.0.0.1' ||
               window.location.port === '3000' ||
               window.location.protocol === 'http:';
    }
    
    async setupDevelopmentRefresh() {
        this.log('Development mode detected - enabling HMR');
        
        // Listen for Vite HMR events
        if (import.meta.hot) {
            import.meta.hot.accept((newModule) => {
                this.log('HMR update received:', newModule);
                this.handleUpdate('hmr', { module: newModule });
            });
            
            import.meta.hot.dispose((data) => {
                this.log('HMR dispose:', data);
            });
        }
        
        // Listen for service worker updates
        await this.setupServiceWorkerUpdates();
    }
    
    async setupProductionRefresh() {
        this.log('Production mode detected - enabling PWA updates');
        
        // Setup service worker updates for production
        await this.setupServiceWorkerUpdates();
        
        // Setup periodic update checks
        this.setupPeriodicChecks();
    }
    
    async setupServiceWorkerUpdates() {
        if (!('serviceWorker' in navigator)) return;

        // Listen for messages from the service worker
        navigator.serviceWorker.addEventListener('message', (event) => {
            if (event.data && event.data.type === 'UPDATE_AVAILABLE') {
                this.log('🔄 Update available from service worker:', event.data);
                this.handleUpdate('sw-update', event.data);
            } else if (event.data && event.data.type === 'SKIP_WAITING') {
                this.log('Service Worker update available');
                this.handleUpdate('sw-update', event.data);
            }
        });

        // Single controllerchange listener (not per-registration)
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            this.log('🔄 Service Worker controller changed - reloading page');
            this.handleUpdate('sw-controller-change', {});
        });

        const attachUpdateFoundListener = (registration) => {
            registration.addEventListener('updatefound', () => {
                this.log('🔄 Service Worker update found');
                const installingWorker = registration.installing;
                if (installingWorker) {
                    installingWorker.addEventListener('statechange', () => {
                        this.log(`🔄 Installing SW state: ${installingWorker.state}`);
                        if (installingWorker.state === 'installed') {
                            if (registration.waiting) {
                                this.log('🔄 New service worker installed and waiting');
                                this.handleUpdate('sw-update', { registration, installingWorker });
                            } else if (registration.active) {
                                this.log('🔄 New service worker activated');
                                this.handleUpdate('sw-update', { registration, installingWorker });
                            }
                        }
                    });
                }
            });
        };

        // Attach to any already-registered SWs and trigger an immediate check
        const registrations = await navigator.serviceWorker.getRegistrations();
        registrations.forEach(registration => {
            attachUpdateFoundListener(registration);
            registration.update().catch(error => {
                this.log('⚠️ Error checking for service worker updates:', error);
            });
        });

        // Also attach to the ready registration — catches the case where the SW
        // registers after this method runs (race condition on first load)
        navigator.serviceWorker.ready.then(registration => {
            if (!registrations.includes(registration)) {
                this.log('🔄 Attaching updatefound listener to late-registered SW');
                attachUpdateFoundListener(registration);
            }
        }).catch(error => {
            this.log('⚠️ Error waiting for service worker ready:', error);
        });

        // Periodic update check (hourly)
        setInterval(async () => {
            try {
                const currentRegistrations = await navigator.serviceWorker.getRegistrations();
                currentRegistrations.forEach(registration => {
                    registration.update().catch(error => {
                        this.log('⚠️ Error checking for service worker updates:', error);
                    });
                });
            } catch (error) {
                this.log('⚠️ Error getting service worker registrations:', error);
            }
        }, 60 * 60 * 1000);
    }
    
    setupPeriodicChecks() {
        // Check for updates every 5 minutes in production
        setInterval(() => {
            this.checkForUpdates();
        }, 5 * 60 * 1000);
    }
    
    // Removed setupManualControls - no header button needed
    
    setupDebugControls() {
        const debugContent = document.querySelector('.debug-content');
        if (debugContent) {
            // Check if Auto-Refresh controls already exist
            if (!document.getElementById('autoRefreshControls')) {
                const autoRefreshSection = document.createElement('div');
                autoRefreshSection.id = 'autoRefreshControls';
                autoRefreshSection.className = 'debug-item';
                autoRefreshSection.innerHTML = `
                    <strong>Auto-Refresh:</strong>
                    <span id="autoRefreshStatus">${this.isConnected ? 'Connected' : 'Disconnected'}</span>
                    <button class="debug-refresh-btn" data-action="autoRefresh">🔄</button>
                    <button class="debug-copy-btn" data-action="autoRefreshStatus">📋</button>
                `;
                
                debugContent.appendChild(autoRefreshSection);
                
                // Add event listeners
                const refreshBtn = autoRefreshSection.querySelector('[data-action="autoRefresh"]');
                const statusBtn = autoRefreshSection.querySelector('[data-action="autoRefreshStatus"]');
                
                refreshBtn.addEventListener('click', () => {
                    this.forceRefresh();
                });
                
                statusBtn.addEventListener('click', () => {
                    this.showStatus();
                });
            }
        }
    }
    
    startUpdateChecking() {
        this.checkTimer = setInterval(() => {
            this.checkForUpdates();
        }, this.options.checkInterval);
    }
    
    async checkForUpdates() {
        try {
            // Check if there are any pending service worker updates
            if ('serviceWorker' in navigator) {
                const registration = await navigator.serviceWorker.getRegistration();
                if (registration && registration.waiting) {
                    this.log('Service Worker update waiting');
                    this.handleUpdate('sw-waiting', { registration });
                }
            }
            
            // Check for manifest updates
            if ('serviceWorker' in navigator && 'SyncManager' in window) {
                const registration = await navigator.serviceWorker.getRegistration();
                if (registration && registration.sync) {
                    const tags = await registration.sync.getTags();
                    if (tags.includes('background-sync')) {
                        this.log('Background sync available');
                        this.handleUpdate('background-sync', { tags });
                    }
                }
            }
            
        } catch (error) {
            this.log('Error checking for updates:', error);
        }
    }
    
    handleUpdate(type, data) {
        this.log(`Handling update: ${type}`, data);
        
        switch (type) {
            case 'hmr':
                // HMR updates are handled automatically by Vite
                this.log('HMR update processed');
                break;
                
            case 'sw-update':
                this.handleServiceWorkerUpdate(data);
                break;
                
            case 'sw-waiting':
                this.promptServiceWorkerUpdate(data);
                break;
                
            case 'background-sync':
                this.handleBackgroundSync(data);
                break;
                
            default:
                this.log('Unknown update type:', type);
        }
        
        this.lastUpdate = new Date();
        this.emit('update', { type, data, timestamp: this.lastUpdate });
    }
    
    handleServiceWorkerUpdate(data) {
        this.log('Service Worker update detected', data);
        
        // Handle UPDATE_AVAILABLE message from refportal-sw.js
        if (data.newVersion) {
            const message = `גרסה חדשה זמינה: ${data.newVersion}`;
            this.showUpdateNotification(message, () => {
                this.updateServiceWorker();
            });
        } else {
            // Generic service worker update
        this.showUpdateNotification('Service Worker update available', () => {
            this.updateServiceWorker();
        });
        }
    }
    
    promptServiceWorkerUpdate(data) {
        const { registration } = data;
        
        if (registration && registration.waiting) {
            this.log('Prompting for Service Worker update');
            
            // Show update prompt
            this.showUpdateNotification('New version available. Click to update.', () => {
                registration.waiting.postMessage({ type: 'SKIP_WAITING' });
                window.location.reload();
            });
        }
    }
    
    handleBackgroundSync(data) {
        this.log('Background sync triggered');
        
        // Trigger background sync
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.ready.then(registration => {
                return registration.sync.register('background-sync');
            }).then(() => {
                this.log('Background sync registered');
            }).catch(error => {
                this.log('Background sync failed:', error);
            });
        }
    }
    
    async updateServiceWorker() {
        if ('serviceWorker' in navigator) {
            try {
                const registrations = await navigator.serviceWorker.getRegistrations();
                
                for (const registration of registrations) {
                    await registration.update();
                    this.log('Service Worker updated');
                }
                
                // Reload to activate new service worker
                window.location.reload();
                
            } catch (error) {
                this.log('Service Worker update failed:', error);
            }
        }
    }
    
    showUpdateNotification(message, action) {
        // Check if notification is already shown
        if (document.getElementById('viteUpdateNotification')) {
            return;
        }
        
        const notification = document.createElement('div');
        notification.id = 'viteUpdateNotification';
        notification.className = 'notification-toast';
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #10b981;
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 10100;
            cursor: pointer;
            max-width: 300px;
        `;
        
        notification.innerHTML = `
            <div style="display: flex; align-items: center; gap: 10px;">
                <span>🔄</span>
                <span>${message}</span>
            </div>
        `;
        
        notification.addEventListener('click', () => {
            if (action) action();
            notification.remove();
        });
        
        document.body.appendChild(notification);
        
        // Auto-remove after 10 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 10000);
    }
    
    forceRefresh() {
        this.log('Force refresh triggered');
        
        if (this.isDevelopmentMode() && import.meta.hot) {
            // In development, trigger HMR reload
            import.meta.hot.send('vite:forceReload');
        } else {
            // In production, reload the page
            window.location.reload();
        }
    }
    
    showStatus() {
        const status = {
            connected: this.isConnected,
            development: this.isDevelopmentMode(),
            lastUpdate: this.lastUpdate,
            serviceWorker: 'serviceWorker' in navigator,
            hmr: !!import.meta.hot
        };
        
        console.log('PWA Auto-Refresh Status:', status);
        
        // Copy to clipboard if supported
        if (navigator.clipboard) {
            navigator.clipboard.writeText(JSON.stringify(status, null, 2));
            this.log('Status copied to clipboard');
        }
    }
    
    // Event system
    emit(event, data) {
        // Dispatch custom event
        const customEvent = new CustomEvent(`vite-pwa-${event}`, { detail: data });
        window.dispatchEvent(customEvent);
        
        this.log(`Event emitted: ${event}`, data);
    }
    
    log(...args) {
        if (this.options.enableLogging) {
            console.log('🔄 PWA Auto-Refresh:', ...args);
        }
    }
    
    // Public API methods
    getStatus() {
        return {
            connected: this.isConnected,
            development: this.isDevelopmentMode(),
            lastUpdate: this.lastUpdate,
            serviceWorker: 'serviceWorker' in navigator,
            hmr: !!import.meta.hot
        };
    }
    
    // Cleanup
    destroy() {
        if (this.checkTimer) {
            clearInterval(this.checkTimer);
            this.checkTimer = null;
        }
        
        this.log('PWA Auto-Refresh destroyed');
    }
}

// Don't auto-initialize here - let refportal-pwa.js handle initialization
// This prevents multiple instances and conflicts

// Export for module usage
export default VitePWARefresh;
