/**
 * Unified Geolocation Service
 * Centralized geolocation service to avoid multiple watchPosition calls
 * Shared by speed monitor and distance tracker
 */
export class UnifiedGeolocationService {
    constructor(options = {}) {
        this.options = {
            enableHighAccuracy: true,
            timeout: 15000, // 15 seconds timeout for GPS acquisition (more lenient)
            maximumAge: 1000, // Allow 1 second cache to reduce battery drain while keeping updates frequent
            updateInterval: 1000, // Default update interval
            ...options
        };
        
        this.isActive = false;
        this.watchId = null;
        this.lastPosition = null;
        this.currentPosition = null;
        this.subscribers = new Map(); // Map of subscriber ID to callback functions
        this.subscriberIdCounter = 0;
        
        this.errorCount = 0;
        this.maxErrors = 20; // Increased to 20 for better resilience - GPS can be unreliable
        this.lastError = null;
        this.lastSuccessfulUpdate = null;
        this.healthCheckInterval = null;
        this.recoveryAttempts = 0;
        this.maxRecoveryAttempts = 3;
        
        // Visibility API for handling tab focus/blur
        this.isPageVisible = !document.hidden;
        this.setupVisibilityHandling();
        
        // Bind methods
        this.handlePositionUpdate = this.handlePositionUpdate.bind(this);
        this.handleError = this.handleError.bind(this);
        this.performHealthCheck = this.performHealthCheck.bind(this);
        this.attemptRecovery = this.attemptRecovery.bind(this);
    }
    
    /**
     * Setup visibility change handling to manage geolocation when tab becomes hidden/visible
     */
    setupVisibilityHandling() {
        if (typeof document !== 'undefined') {
            document.addEventListener('visibilitychange', () => {
                const wasVisible = this.isPageVisible;
                this.isPageVisible = !document.hidden;
                
                console.log(`📍 Page visibility changed: ${this.isPageVisible ? 'visible' : 'hidden'}`);
                
                if (wasVisible && !this.isPageVisible) {
                    // Tab became hidden - reduce geolocation frequency
                    this.handleTabHidden();
                } else if (!wasVisible && this.isPageVisible) {
                    // Tab became visible - resume normal geolocation
                    this.handleTabVisible();
                }
            });
        }
    }
    
    /**
     * Handle when tab becomes hidden
     */
    handleTabHidden() {
        if (this.isActive && this.subscribers.size > 0) {
            console.log('📍 Tab hidden - reducing geolocation frequency');
            // Don't stop completely, but reduce frequency
            this.options.maximumAge = 2000; // 2 seconds when hidden (still reasonable for background)
        }
    }
    
    /**
     * Handle when tab becomes visible
     */
    handleTabVisible() {
        if (this.isActive && this.subscribers.size > 0) {
            console.log('📍 Tab visible - resuming normal geolocation');
            // Resume normal frequency
            this.options.maximumAge = 1000; // 1 second cache when visible (good balance)
            
            // Restart geolocation to ensure it's working
            this.restartGeolocation();
        }
    }
    
    /**
     * Restart geolocation service
     */
    restartGeolocation() {
        if (this.isActive && this.subscribers.size > 0) {
            console.log('📍 Restarting geolocation service...');
            const oldWatchId = this.watchId;
            this.stopGeolocation();
            
            // Small delay to ensure clean restart, but keep service active
            setTimeout(() => {
                // Only restart if still needed (has subscribers)
                if (this.subscribers.size > 0) {
                    this.startGeolocation();
                } else {
                    console.log('📍 No subscribers, skipping restart');
                }
            }, 500); // Reduced delay for faster recovery
        }
    }
    
    /**
     * Perform health check on geolocation service
     */
    performHealthCheck() {
        if (!this.isActive || this.subscribers.size === 0) {
            return;
        }
        
        const now = Date.now();
        const timeSinceLastUpdate = this.lastSuccessfulUpdate ? 
            now - this.lastSuccessfulUpdate : Infinity;
        
        // If no updates for 60 seconds, consider it unhealthy (more lenient for weak GPS)
        if (timeSinceLastUpdate > 60000) {
            console.warn(`📍 Geolocation health check - no updates for ${Math.round(timeSinceLastUpdate/1000)}s, attempting recovery`);
            this.attemptRecovery();
        } else if (timeSinceLastUpdate > 30000) {
            // Just log a warning for 30-60 seconds, don't trigger recovery yet
            console.warn(`📍 Geolocation health check - no updates for ${Math.round(timeSinceLastUpdate/1000)}s`);
        }
    }
    
    /**
     * Attempt to recover from geolocation issues
     */
    attemptRecovery() {
        // Don't give up - keep trying to recover
        this.recoveryAttempts++;
        console.log(`📍 Attempting geolocation recovery (attempt ${this.recoveryAttempts})`);
        
        // Reset error count to allow fresh attempts
        this.errorCount = 0;
        
        // Restart geolocation
        this.restartGeolocation();
        
        // Reset recovery attempts after successful update (with longer timeout for weak GPS)
        setTimeout(() => {
            if (this.lastSuccessfulUpdate && Date.now() - this.lastSuccessfulUpdate < 30000) {
                this.recoveryAttempts = 0;
                console.log('📍 Geolocation recovery successful');
            }
        }, 30000);
    }
    
    /**
     * Subscribe to geolocation updates
     * @param {Object} callbacks - Object containing callback functions
     * @param {Function} callbacks.onPositionUpdate - Called when position updates
     * @param {Function} callbacks.onError - Called when error occurs
     * @param {Object} options - Subscription options
     * @returns {string} - Subscriber ID for unsubscribing
     */
    subscribe(callbacks, options = {}) {
        const subscriberId = `subscriber_${++this.subscriberIdCounter}`;
        
        const subscription = {
            id: subscriberId,
            callbacks: {
                onPositionUpdate: callbacks.onPositionUpdate || null,
                onError: callbacks.onError || null
            },
            options: {
                maxAccuracy: options.maxAccuracy || 100, // meters - relaxed default for frequent updates
                updateInterval: options.updateInterval || this.options.updateInterval,
                lastUpdate: 0,
                ...options
            }
        };
        
        this.subscribers.set(subscriberId, subscription);
        
        // Start geolocation if not already active
        if (!this.isActive) {
            this.startGeolocation();
        }
        
        console.log(`📍 Geolocation subscriber added: ${subscriberId} (Total: ${this.subscribers.size})`);
        return subscriberId;
    }
    
    /**
     * Unsubscribe from geolocation updates
     * @param {string} subscriberId - ID returned from subscribe()
     */
    unsubscribe(subscriberId) {
        if (this.subscribers.has(subscriberId)) {
            this.subscribers.delete(subscriberId);
            console.log(`📍 Geolocation subscriber removed: ${subscriberId} (Total: ${this.subscribers.size})`);
            
            // Stop geolocation if no more subscribers
            if (this.subscribers.size === 0) {
                this.stopGeolocation();
            }
        }
    }
    
    /**
     * Start geolocation watching
     */
    async startGeolocation() {
        if (this.isActive) {
            console.log('📍 Geolocation already active');
            return;
        }
        
        if (!navigator.geolocation) {
            this.handleError(new Error('Geolocation is not supported by this browser'));
            return;
        }
        
        try {
            console.log('📍 Starting unified geolocation service...');
            this.errorCount = 0;
            this.recoveryAttempts = 0;
            
            // Start watching position
            this.watchId = navigator.geolocation.watchPosition(
                (position) => this.handlePositionUpdate(position),
                (error) => this.handleError(error),
                {
                    enableHighAccuracy: this.options.enableHighAccuracy,
                    timeout: this.options.timeout,
                    maximumAge: this.options.maximumAge
                }
            );
            
            this.isActive = true;
            this.lastSuccessfulUpdate = Date.now();
            
        // Start health monitoring
        this.startHealthMonitoring();
        
        // Log watch ID for debugging
        console.log(`✅ Unified geolocation service started (watchId: ${this.watchId})`);
        
        // Debug: Monitor if watchPosition is still active
        this.debugWatchInterval = setInterval(() => {
            if (this.isActive && !this.lastSuccessfulUpdate) {
                console.warn('📍 Geolocation active but no successful updates yet');
            } else if (this.isActive && this.lastSuccessfulUpdate) {
                const timeSinceUpdate = Date.now() - this.lastSuccessfulUpdate;
                if (timeSinceUpdate > 5000) {
                    console.warn(`📍 Geolocation active but last update was ${Math.round(timeSinceUpdate/1000)}s ago`);
                }
            }
        }, 10000); // Check every 10 seconds
            
        } catch (error) {
            this.handleError(error);
        }
    }
    
    /**
     * Start health monitoring
     */
    startHealthMonitoring() {
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
        }
        
        // Check health every 15 seconds
        this.healthCheckInterval = setInterval(this.performHealthCheck, 15000);
    }
    
    /**
     * Stop health monitoring
     */
    stopHealthMonitoring() {
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
            this.healthCheckInterval = null;
        }
    }
    
    /**
     * Stop geolocation watching
     */
    stopGeolocation() {
        if (!this.isActive) {
            return;
        }
        
        console.log('📍 Stopping unified geolocation service...');
        
        if (this.watchId !== null) {
            navigator.geolocation.clearWatch(this.watchId);
            this.watchId = null;
        }
        
        // Stop health monitoring
        this.stopHealthMonitoring();
        
        // Stop debug interval if exists
        if (this.debugWatchInterval) {
            clearInterval(this.debugWatchInterval);
            this.debugWatchInterval = null;
        }
        
        this.lastPosition = null;
        this.currentPosition = null;
        
        this.isActive = false;
        console.log('✅ Unified geolocation service stopped');
    }
    
    /**
     * Handle position updates from geolocation API
     */
    handlePositionUpdate(position) {
        if (!this.isActive) {
            return;
        }
        
        const newPosition = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy,
            altitude: position.coords.altitude,
            altitudeAccuracy: position.coords.altitudeAccuracy,
            heading: position.coords.heading,
            speed: position.coords.speed,
            timestamp: position.timestamp || Date.now()
        };
        
        this.lastPosition = this.currentPosition;
        this.currentPosition = newPosition;
        
        // Update successful update timestamp
        this.lastSuccessfulUpdate = Date.now();
        
        // Reset error count on successful update
        this.errorCount = 0;
        
        // Notify all subscribers
        this.notifySubscribers(newPosition);
    }
    
    /**
     * Notify all subscribers of position update
     */
    notifySubscribers(position) {
        const now = Date.now();
        
        this.subscribers.forEach((subscription, subscriberId) => {
            try {
                // Check if subscriber wants this update based on interval
                const timeSinceLastUpdate = now - subscription.options.lastUpdate;
                if (timeSinceLastUpdate < subscription.options.updateInterval) {
                    return;
                }
                
                // Check accuracy threshold - only reject extremely poor positions
                // Note: GPS accuracy is in meters, lower = better. For frequent updates like GPS tracking apps,
                // we accept positions even with relatively poor accuracy (up to 100m) to maximize update frequency
                const maxAllowedAccuracy = subscription.options.maxAccuracy || 100; // Default 100m if not set
                if (position.accuracy > maxAllowedAccuracy) {
                    console.warn(`📍 GPS accuracy very poor for subscriber ${subscriberId}: ${position.accuracy}m (max allowed: ${maxAllowedAccuracy}m)`);
                    return;
                }
                
                // Update last update time
                subscription.options.lastUpdate = now;
                
                // Call subscriber's callback
                if (subscription.callbacks.onPositionUpdate) {
                    subscription.callbacks.onPositionUpdate(position, this.lastPosition);
                }
                
            } catch (error) {
                console.error(`📍 Error notifying subscriber ${subscriberId}:`, error);
            }
        });
    }
    
    /**
     * Handle geolocation errors
     */
    handleError(error) {
        this.errorCount++;
        this.lastError = error;
        
        let errorMessage = 'Unknown geolocation error';
        
        switch (error.code) {
            case error.PERMISSION_DENIED:
                errorMessage = 'Location access denied by user';
                break;
            case error.POSITION_UNAVAILABLE:
                errorMessage = 'Location information unavailable';
                break;
            case error.TIMEOUT:
                errorMessage = 'Location request timed out';
                break;
            default:
                errorMessage = error.message || 'Unknown error';
        }
        
        console.error('📍 Geolocation error:', errorMessage);
        
        // Show toast notification if available
        try {
            if (typeof window !== 'undefined' && window.refPortalPwa && typeof window.refPortalPwa.showToast === 'function') {
                window.refPortalPwa.showToast(`Geolocation error: ${errorMessage}`, 'error');
            }
        } catch (toastError) {
            // Ignore toast errors to avoid interfering with geolocation flow
        }
        
        // Notify all subscribers of error
        this.subscribers.forEach((subscription, subscriberId) => {
            try {
                if (subscription.callbacks.onError) {
                    subscription.callbacks.onError(error, errorMessage);
                }
            } catch (callbackError) {
                console.error(`📍 Error in subscriber ${subscriberId} error callback:`, callbackError);
            }
        });
        
        // Attempt recovery if too many errors, but never give up completely
        if (this.errorCount >= this.maxErrors) {
            console.warn(`📍 Multiple geolocation errors (${this.errorCount}), attempting recovery`);
            // Reset error count to prevent immediate re-trigger, but keep trying
            this.errorCount = Math.floor(this.maxErrors / 2); // Reset to half to allow more attempts
            this.attemptRecovery();
        }
    }
    
    /**
     * Get current position (one-time request)
     */
    getCurrentPosition() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error('Geolocation is not supported'));
                return;
            }
            
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const pos = {
                        latitude: position.coords.latitude,
                        longitude: position.coords.longitude,
                        accuracy: position.coords.accuracy,
                        altitude: position.coords.altitude,
                        altitudeAccuracy: position.coords.altitudeAccuracy,
                        heading: position.coords.heading,
                        speed: position.coords.speed,
                        timestamp: position.timestamp || Date.now()
                    };
                    resolve(pos);
                },
                reject,
                {
                    enableHighAccuracy: this.options.enableHighAccuracy,
                    timeout: this.options.timeout,
                    maximumAge: this.options.maximumAge
                }
            );
        });
    }
    
    /**
     * Get service status
     */
    getStatus() {
        return {
            isActive: this.isActive,
            subscriberCount: this.subscribers.size,
            lastPosition: this.currentPosition,
            errorCount: this.errorCount,
            lastError: this.lastError
        };
    }
    
    /**
     * Get list of active subscribers
     */
    getSubscribers() {
        return Array.from(this.subscribers.keys());
    }
    
    /**
     * Update service options
     */
    updateOptions(newOptions) {
        this.options = { ...this.options, ...newOptions };
        console.log('📍 Geolocation service options updated:', this.options);
    }
    
    /**
     * Cleanup service
     */
    cleanup() {
        console.log('📍 Cleaning up unified geolocation service...');
        this.stopGeolocation();
        this.subscribers.clear();
        this.subscriberIdCounter = 0;
        this.errorCount = 0;
        this.lastError = null;
        this.lastSuccessfulUpdate = null;
        this.recoveryAttempts = 0;
        this.isPageVisible = true;
        console.log('✅ Unified geolocation service cleaned up');
    }
}

// Singleton instance
let unifiedGeolocationInstance = null;

/**
 * Get the singleton instance of UnifiedGeolocationService
 */
export function getUnifiedGeolocationService(options = {}) {
    if (!unifiedGeolocationInstance) {
        unifiedGeolocationInstance = new UnifiedGeolocationService(options);
    }
    return unifiedGeolocationInstance;
}

/**
 * Reset the singleton instance (for testing)
 */
export function resetUnifiedGeolocationService() {
    if (unifiedGeolocationInstance) {
        unifiedGeolocationInstance.cleanup();
        unifiedGeolocationInstance = null;
    }
}
