import { getUnifiedGeolocationService } from './unified-geolocation-service.js';

/**
 * Distance Tracker Service
 * Tracks referee running distance during games using GPS coordinates
 * Uses unified geolocation service to avoid multiple watchPosition calls
 */
export class DistanceTrackerService {
    constructor(options = {}) {
        this.options = {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0, // 0 = always get fresh position, no caching
            updateInterval: 500, // Update every 500ms for frequent updates
            minDistanceThreshold: 0, // Minimum distance between points (0 = accept all)
            ...options
        };
        
        this.isTracking = false;
        this.isPaused = false;
        this.totalDistance = 0; // in meters
        this.currentDistance = 0; // current session distance
        this.lastPosition = null;
        this.positions = [];
        this.geolocationSubscriberId = null;
        this.startTime = null;
        this.pauseTime = null;
        this.totalPauseTime = 0;
        this.updateTimer = null;
        this.errorMessage = null;
        this.lastApiCallTime = null; // Track last API call time for calculating timeFromLastCall
        this.pendingUpdates = []; // Queue for position updates when offline
        this.maxPendingUpdates = 100; // Maximum pending updates to store
        this.flushThreshold = 80; // Flush when queue reaches this percentage (80%)
        this.isFlushing = false; // Prevent concurrent flush operations
        this.currentSpeed = 0; // km/h
        this.currentAccuracy = null; // meters
        
        // Tracking data for backend submission
        this.trackingData = []; // Store all position data: timestamp, distance, speed, accuracy
        this.trackingStartTime = null;
        this.apiService = options.apiService || null; // API service for sending data
        this.apiEndpoint = options.apiEndpoint || '/api/pwa/speed-tracking-data'; // API endpoint

        this.callbacks = {
            onDistanceUpdate: null,
            onStatusChange: null,
            onError: null
        };
        
        this.errorCount = 0;
        this.maxErrors = 5;
        this.enableApiUpdates = true; // Enable/disable API updates
        
        // Setup online/offline handlers to flush pending updates
        this.setupNetworkHandling();
        
        // Get unified geolocation service
        this.geolocationService = getUnifiedGeolocationService(options);
    }
    
    /**
     * Start distance tracking
     */
    async startTracking() {
        if (this.isTracking) {
            console.log('Distance tracking already started');
            return;
        }
        
        try {
            this.isTracking = true;
            this.isPaused = false;
            this.startTime = new Date();
            this.totalPauseTime = 0;
            this.currentDistance = 0;
            this.positions = [];
            this.lastApiCallTime = null; // Reset API call time when starting tracking
            this.trackingStartTime = Date.now();
            this.trackingData = []; // Reset tracking data
            
            console.log('🏃‍♂️ Starting distance tracking...');
            
            // Subscribe to unified geolocation service
            this.geolocationSubscriberId = this.geolocationService.subscribe({
                onPositionUpdate: (position, lastPosition) => this.handlePositionUpdate(position, lastPosition),
                onError: (error) => this.handleError(error)
            }, {
                maxAccuracy: this.options.maxAccuracy,
                updateInterval: this.options.updateInterval
            });
            
            this.notifyStatusChange('started');
            
            // Start update timer for real-time display updates
            this.startUpdateTimer();
            
        } catch (error) {
            this.handleError(error);
        }
    }
    
    /**
     * Pause distance tracking
     */
    pauseTracking() {
        if (!this.isTracking || this.isPaused) {
            return;
        }
        
        this.isPaused = true;
        this.pauseTime = new Date();
        
        // Unsubscribe from geolocation service
        if (this.geolocationSubscriberId) {
            this.geolocationService.unsubscribe(this.geolocationSubscriberId);
            this.geolocationSubscriberId = null;
        }
        
        console.log('⏸️ Distance tracking paused');
        this.notifyStatusChange('paused');
        
        // Stop update timer when paused
        this.stopUpdateTimer();
    }
    
    /**
     * Resume distance tracking
     */
    async resumeTracking() {
        if (!this.isTracking || !this.isPaused) {
            return;
        }
        
        this.isPaused = false;
        this.lastApiCallTime = null; // Reset API call time when resuming
        
        // Add pause time to total
        if (this.pauseTime) {
            this.totalPauseTime += new Date() - this.pauseTime;
            this.pauseTime = null;
        }
        
        // Get current position and resume subscription
        try {
            // Re-subscribe to unified geolocation service
            this.geolocationSubscriberId = this.geolocationService.subscribe({
                onPositionUpdate: (position, lastPosition) => this.handlePositionUpdate(position, lastPosition),
                onError: (error) => this.handleError(error)
            }, {
                maxAccuracy: this.options.maxAccuracy,
                updateInterval: this.options.updateInterval
            });
            
            console.log('▶️ Distance tracking resumed');
            this.notifyStatusChange('resumed');
            
            // Restart update timer when resumed
            this.startUpdateTimer();
            
        } catch (error) {
            this.handleError(error);
        }
    }
    
    /**
     * Stop distance tracking
     */
    async stopTracking() {
        if (!this.isTracking) {
            return;
        }
        
        this.isTracking = false;
        this.isPaused = false;
        this.lastApiCallTime = null; // Reset API call time when stopping
        
        // Unsubscribe from geolocation service
        if (this.geolocationSubscriberId) {
            this.geolocationService.unsubscribe(this.geolocationSubscriberId);
            this.geolocationSubscriberId = null;
        }
        
        // Add final pause time if paused
        if (this.pauseTime) {
            this.totalPauseTime += new Date() - this.pauseTime;
            this.pauseTime = null;
        }
        
        console.log('🛑 Distance tracking stopped');
        console.log(`Total distance: ${this.formatDistance(this.totalDistance)}`);
        console.log(`Active time: ${this.getActiveTime()}`);
        
        this.notifyStatusChange('stopped');
        
        // Stop update timer when stopped
        this.stopUpdateTimer();
        
        // Send tracking data to backend
        await this.sendTrackingDataToBackend();
        
        const data = this.createDisplayData();
        return data;
    }
    
    /**
     * Reset tracking data
     */
    async resetTracking() {
        await this.stopTracking();
        this.totalDistance = 0;
        this.currentDistance = 0;
        this.positions = [];
        this.lastPosition = null;
        this.startTime = null;
        this.pauseTime = null;
        this.totalPauseTime = 0;
        this.errorCount = 0;
        this.currentSpeed = 0; // km/h
        this.currentAccuracy = null; // meters
        this.trackingData = []; // Reset tracking data
        this.trackingStartTime = null;
        
        // Stop update timer when reset
        this.stopUpdateTimer();
        
        console.log('🔄 Distance tracking reset');
        this.notifyStatusChange('reset');
    }
    
    /**
     * Handle position updates from unified geolocation service
     */
    handlePositionUpdate(position, lastPosition) {
        if (!this.isTracking || this.isPaused) {
            return;
        }
        
        const newPosition = {
            lat: position.latitude,
            lng: position.longitude,
            timestamp: new Date(position.timestamp),
            accuracy: position.accuracy
        };
        
        // Update current accuracy
        this.currentAccuracy = position.accuracy;
        
        if (this.lastPosition) {
            const distance = this.calculateDistance(
                this.lastPosition.lat,
                this.lastPosition.lng,
                newPosition.lat,
                newPosition.lng
            );
            
            // Calculate speed from distance and time
            const timeDiff = (newPosition.timestamp - this.lastPosition.timestamp) / 1000; // seconds
            if (timeDiff > 0) {
                const speedMs = distance / timeDiff; // m/s
                this.currentSpeed = speedMs * 3.6; // Convert to km/h
            }
            
            // Only add distance if it's above threshold
            if (distance >= this.options.minDistanceThreshold) {
                this.currentDistance += distance;
                this.totalDistance += distance;
                this.positions.push(newPosition);
                this.lastPosition = newPosition;
                
                console.log(`📍 Distance update: +${this.formatDistance(distance)} (Total: ${this.formatDistance(this.totalDistance)})`);
                
                // Send position update to API
                this.sendPositionUpdateToApi(position, distance);
                
                this.notifyDistanceUpdate();
            } else {
                // Update last position even if distance is below threshold (for speed calculation)
                this.lastPosition = newPosition;
            }
            
            // Store tracking data for backend submission
            this.trackingData.push({
                timestamp: newPosition.timestamp.getTime ? newPosition.timestamp.getTime() : newPosition.timestamp,
                latitude: newPosition.lat,
                longitude: newPosition.lng,
                accuracy: newPosition.accuracy,
                speed: this.currentSpeed, // km/h
                distance: this.totalDistance, // Total accumulated distance in meters
                distanceIncrement: distance // Distance since last position
            });
        } else {
            this.lastPosition = newPosition;
            this.positions.push(newPosition);
            
            // Send initial position to API even if no distance calculated yet
            this.sendPositionUpdateToApi(position, 0);
            
            // Store initial tracking data
            this.trackingData.push({
                timestamp: newPosition.timestamp.getTime ? newPosition.timestamp.getTime() : newPosition.timestamp,
                latitude: newPosition.lat,
                longitude: newPosition.lng,
                accuracy: newPosition.accuracy,
                speed: 0, // km/h
                distance: 0, // Total accumulated distance in meters
                distanceIncrement: 0 // Distance since last position
            });
        }
    }
    
    /**
     * Calculate distance between two coordinates (Haversine formula)
     */
    calculateDistance(lat1, lng1, lat2, lng2) {
        const R = 6371000; // Earth's radius in meters
        const dLat = this.toRadians(lat2 - lat1);
        const dLng = this.toRadians(lng2 - lng1);
        
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(this.toRadians(lat1)) * Math.cos(this.toRadians(lat2)) *
                  Math.sin(dLng / 2) * Math.sin(dLng / 2);
        
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }
    
    /**
     * Convert degrees to radians
     */
    toRadians(degrees) {
        return degrees * (Math.PI / 180);
    }
    
    /**
     * Handle errors
     */
    handleError(error) {
        this.errorCount++;
        
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

        this.errorMessage = errorMessage
        
        console.error('🚨 Distance tracking error:', errorMessage);
        
        if (this.errorCount >= this.maxErrors) {
            console.error('🚨 Too many errors, stopping tracking');
            this.stopTracking().catch(error => {
                console.error('Error stopping tracking after max errors:', error);
            });
        }
        
        if (this.callbacks.onError) {
            this.callbacks.onError(errorMessage);
        }
    }
    
    /**
     * Get active time (excluding pauses)
     */
    getActiveTime() {
        if (!this.startTime) return 0;
        
        const now = new Date();
        const totalTime = now - this.startTime;
        const currentPauseTime = this.isPaused ? (now - this.pauseTime) : 0;
        
        return totalTime - this.totalPauseTime - currentPauseTime;
    }
    
    /**
     * Get total time (including pauses)
     */
    getTotalTime() {
        if (!this.startTime) return 0;
        
        const now = new Date();
        return now - this.startTime;
    }
    
    /**
     * Format distance for display
     */
    formatDistance(meters) {
        if (meters < 1000) {
            return `${Math.round(meters)} מ׳`;
        } else {
            return `${(meters / 1000).toFixed(2)} ק״מ`;
        }
    }
    
    /**
     * Format time for display
     */
    formatTime(milliseconds) {
        const seconds = Math.floor(milliseconds / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        
        if (true || hours > 0) {
            return `${hours}:${(minutes % 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
        } else {
            return `${minutes}:${(seconds % 60).toString().padStart(2, '0')}`;
        }
    }
    
    /**
     * Set callback functions
     */
    setCallbacks(callbacks) {
        this.callbacks = { ...this.callbacks, ...callbacks };
    }
    
    createDisplayData() {
        const data = {
            totalDistance: this.totalDistance,
            currentDistance: this.currentDistance,
            formattedDistance: this.formatDistance(this.totalDistance),
            activeTime: this.getActiveTime(),
            formattedTime: this.formatTime(this.getActiveTime()),
            isTracking: this.isTracking,
            isPaused: this.isPaused,
            lastPositionTimestamp: this.lastPosition ? this.lastPosition.timestamp.getTime() : null,
            lastPositionTimeFormatted: (this.lastPosition
                ? this.lastPosition.timestamp.toLocaleTimeString(undefined, {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false
                })
                : null),
            currentSpeed: this.currentSpeed,
            formattedSpeed: this.currentSpeed ? `${this.currentSpeed.toFixed(1)} קמ״ש` : '0.0 קמ״ש',
            currentAccuracy: this.currentAccuracy,
            formattedAccuracy: this.currentAccuracy ? `${Math.round(this.currentAccuracy)} מ׳` : '-- מ׳',
            errorMessage: this.errorMessage
        };
        return data;
    }
    
    /**
     * Send tracking data to backend service
     */
    async sendTrackingDataToBackend() {
        if (!this.trackingData || this.trackingData.length === 0) {
            console.log('📊 No tracking data to send');
            return;
        }

        try {
            const trackingSummary = {
                startTime: this.trackingStartTime,
                endTime: Date.now(),
                duration: this.trackingStartTime ? (Date.now() - this.trackingStartTime) : 0,
                totalDistance: this.totalDistance,
                totalDataPoints: this.trackingData.length,
                data: this.trackingData
            };

            console.log(`📤 Sending ${this.trackingData.length} tracking data points to backend...`);

            if (this.apiService) {
                // Use provided API service
                const response = await this.apiService.makeApiRequest({
                    url: this.apiEndpoint,
                    options: {
                        method: 'POST',
                        body: JSON.stringify(trackingSummary),
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    }
                });

                if (response.ok) {
                    console.log('✅ Tracking data sent successfully to backend');
                } else {
                    const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
                    console.error('❌ Failed to send tracking data:', errorData);
                }
            } else {
                // Fallback: try to use global RefPortalPWA instance
                if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
                    const response = await window.refPortalPwa.refreshTokenService.makeApiRequest({
                        url: this.apiEndpoint,
                        options: {
                            method: 'POST',
                            body: JSON.stringify(trackingSummary),
                            headers: {
                                'Content-Type': 'application/json'
                            }
                        }
                    });

                    if (response.ok) {
                        console.log('✅ Tracking data sent successfully to backend');
                    } else {
                        const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
                        console.error('❌ Failed to send tracking data:', errorData);
                    }
                } else {
                    console.warn('⚠️ No API service available to send tracking data');
                    // Log the data for debugging
                    console.log('📊 Tracking data (not sent):', trackingSummary);
                }
            }
        } catch (error) {
            console.error('❌ Error sending tracking data to backend:', error);
        }
    }

    /**
     * Notify distance update
     */
    notifyDistanceUpdate() {
        if (this.callbacks.onDistanceUpdate) {
            this.callbacks.onDistanceUpdate(this.createDisplayData());
        }
    }
    
    /**
     * Notify status change
     */
    notifyStatusChange(status) {
        if (this.callbacks.onStatusChange) {
            this.callbacks.onStatusChange({
                status,
                isTracking: this.isTracking,
                isPaused: this.isPaused,
                totalDistance: this.totalDistance,
                formattedDistance: this.formatDistance(this.totalDistance)
            });
        }
    }
    
    /**
     * Get current status
     */
    getStatus() {
        return {
            isTracking: this.isTracking,
            isPaused: this.isPaused,
            totalDistance: this.totalDistance,
            currentDistance: this.currentDistance,
            formattedDistance: this.formatDistance(this.totalDistance),
            activeTime: this.getActiveTime(),
            formattedTime: this.formatTime(this.getActiveTime()),
            positions: this.positions.length,
            errorCount: this.errorCount
        };
    }
    
    shouldRefreshDisplay() {
        return this.isTracking && !this.isPaused;
    }

    /**
     * Start update timer for real-time display updates
     */
    startUpdateTimer() {
        // Clear existing timer
        this.stopUpdateTimer();
        
        // Update every second for real-time display
        this.updateTimer = setInterval(() => {
            if (this.shouldRefreshDisplay()) {
                this.notifyDistanceUpdate(this.createDisplayData());
            }
        }, 1000);
    }
    
    /**
     * Stop update timer
     */
    stopUpdateTimer() {
        if (this.updateTimer) {
            clearInterval(this.updateTimer);
            this.updateTimer = null;
        }
    }

    /**
     * Send position update to server (via WebSocket if available, fallback to API)
     */
    async sendPositionUpdateToApi(position, distanceIncrement) {
        if (!this.enableApiUpdates || !this.isTracking || this.isPaused) {
            return;
        }

        // Check if device is online
        if (!navigator.onLine) {
            console.warn('📴 Device is offline - queueing position update for later');
            // Queue update for later when online
            this.queuePositionUpdate(position, distanceIncrement);
            return;
        }
        
        // If we come back online and have pending updates, flush them first
        if (this.pendingUpdates.length > 0) {
            console.log(`📤 Flushing ${this.pendingUpdates.length} pending position updates`);
            await this.attemptFlushQueue();
        }

        try {
            // Calculate time from last call
            const now = Date.now();
            const timeFromLastCall = this.lastApiCallTime ? (now - this.lastApiCallTime) : 0;
            this.lastApiCallTime = now;

            // Prepare position data
            const positionData = {
                position: {
                    latitude: position.latitude,
                    longitude: position.longitude,
                    accuracy: position.accuracy,
                    timestamp: position.timestamp
                },
                distance: this.totalDistance, // Total accumulated distance
                timeFromLastCall: timeFromLastCall // Time in milliseconds since last call
            };

            // Try WebSocket first (more efficient for frequent updates)
            if (this.sendPositionUpdateViaWebSocket(positionData)) {
                // WebSocket send successful (synchronous send, no await needed)
                return;
            }

            // Fallback to HTTP API if WebSocket not available
            await this.sendPositionUpdateViaApi(positionData, timeFromLastCall);

        } catch (error) {
            console.error('❌ Error sending position update:', error);
            // Don't stop tracking on errors, just log them
        }
    }

    /**
     * Send position update via WebSocket (preferred method)
     */
    sendPositionUpdateViaWebSocket(positionData) {
        try {
            // Check if WebSocket is available and connected
            if (window.refPortalPwa && 
                window.refPortalPwa.jwtWebSocket && 
                window.refPortalPwa.jwtWebSocket.connectionState === 'connected') {
                
                // Use sendMessage which creates { type: 'position_update', ...positionData }
                window.refPortalPwa.jwtWebSocket.sendMessage('position_update', positionData);
                return true;
            }
            return false;
        } catch (error) {
            console.error('❌ Error sending position update via WebSocket:', error);
            return false;
        }
    }

    /**
     * Send position update via HTTP API (fallback method)
     */
    async sendPositionUpdateViaApi(positionData, timeFromLastCall) {
        try {
            // Get API base URL from config
            const apiBaseUrl = window.CLIENT_ENV?.API_BASE_URL || 'https://api-dev.refereex.com';
            const endpoint = `${apiBaseUrl}/api/pwa/position-update`;

            // Get JWT token for authentication
            let authHeader = null;
            if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
                authHeader = await window.refPortalPwa.refreshTokenService.getAuthorizationHeader();
            }

            // Make API request
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(authHeader && { 'Authorization': authHeader })
                },
                body: JSON.stringify(positionData)
            });

            if (!response.ok) {
                throw new Error(`API request failed with status ${response.status}`);
            }

            const result = await response.json();
            console.log(`✅ Position update sent to API: distance=${this.totalDistance}m, timeSinceLastCall=${timeFromLastCall}ms`);

        } catch (error) {
            console.error('❌ Error sending position update via API:', error);
            throw error; // Re-throw to let caller handle
        }
    }

    /**
     * Enable or disable API updates
     */
    setApiUpdatesEnabled(enabled) {
        this.enableApiUpdates = enabled;
        console.log(`API updates ${enabled ? 'enabled' : 'disabled'}`);
    }

    /**
     * Setup network online/offline handling
     */
    setupNetworkHandling() {
        window.addEventListener('online', async () => {
            console.log('🌐 Device is back online - flushing pending position updates');
            if (this.pendingUpdates.length > 0) {
                await this.attemptFlushQueue();
            }
        });
        
        window.addEventListener('offline', () => {
            console.log('📴 Device is offline - position updates will be queued');
            // When going offline, try one more flush attempt in case connectivity is intermittent
            if (this.pendingUpdates.length > 0) {
                console.log(`📤 Attempting final flush before going offline (${this.pendingUpdates.length} updates in queue)`);
                setTimeout(() => {
                    this.attemptFlushQueue();
                }, 500);
            }
        });
    }

    /**
     * Queue position update for later when online
     */
    queuePositionUpdate(position, distanceIncrement) {
        const now = Date.now();
        const timeFromLastCall = this.lastApiCallTime ? (now - this.lastApiCallTime) : 0;
        this.lastApiCallTime = now;

        const positionData = {
            position: {
                latitude: position.latitude,
                longitude: position.longitude,
                accuracy: position.accuracy,
                timestamp: position.timestamp
            },
            distance: this.totalDistance,
            timeFromLastCall: timeFromLastCall,
            queuedAt: now
        };

        // Add to queue, remove oldest if over limit
        this.pendingUpdates.push(positionData);
        const queueSize = this.pendingUpdates.length;
        
        // Check if queue is getting full
        const queuePercentage = (queueSize / this.maxPendingUpdates) * 100;
        const shouldFlush = queuePercentage >= (this.flushThreshold / 100) * 100;
        
        if (queueSize > this.maxPendingUpdates) {
            const removed = this.pendingUpdates.shift();
            console.warn(`⚠️ Removed oldest pending update (queue full): ${removed.queuedAt}`);
        }

        console.log(`📦 Queued position update (${queueSize}/${this.maxPendingUpdates} in queue, ${queuePercentage.toFixed(1)}% full)`);

        // Try to flush if queue is getting full, even if we think we're offline
        // This handles intermittent connectivity scenarios
        if (shouldFlush && !this.isFlushing) {
            console.log(`⚠️ Queue is ${queuePercentage.toFixed(1)}% full - attempting to flush to prevent data loss`);
            this.attemptFlushQueue();
        }
    }

    /**
     * Attempt to flush queue (even if offline - handles intermittent connectivity)
     */
    async attemptFlushQueue() {
        if (this.isFlushing) {
            console.log('⏳ Flush already in progress, skipping...');
            return;
        }

        if (this.pendingUpdates.length === 0) {
            return;
        }

        this.isFlushing = true;
        
        try {
            await this.flushPendingUpdates();
        } catch (error) {
            console.error('❌ Error in attemptFlushQueue:', error);
        } finally {
            this.isFlushing = false;
        }
    }

    /**
     * Flush pending position updates (tries even if offline for intermittent connectivity)
     */
    async flushPendingUpdates() {
        if (this.pendingUpdates.length === 0) {
            return;
        }

        // Try to flush even if navigator says offline - sometimes connectivity is intermittent
        // But log a warning so we know
        if (!navigator.onLine) {
            console.warn('📴 navigator.onLine reports offline, but attempting flush anyway (may have intermittent connectivity)');
        }

        const updatesToSend = [...this.pendingUpdates];
        this.pendingUpdates = []; // Clear queue

        console.log(`📤 Attempting to send ${updatesToSend.length} queued position updates`);

        let successCount = 0;
        let failCount = 0;

        for (let i = 0; i < updatesToSend.length; i++) {
            const positionData = updatesToSend[i];
            try {
                let sent = false;
                
                // Try WebSocket first
                if (this.sendPositionUpdateViaWebSocket(positionData)) {
                    sent = true;
                    successCount++;
                } else {
                    // Fallback to API
                    try {
                        await this.sendPositionUpdateViaApi(positionData, positionData.timeFromLastCall);
                        sent = true;
                        successCount++;
                    } catch (apiError) {
                        // API failed, will re-queue below
                        throw apiError;
                    }
                }

                if (sent && (i + 1) % 10 === 0) {
                    console.log(`📊 Progress: ${i + 1}/${updatesToSend.length} updates sent (${successCount} success, ${failCount} failed)`);
                }

                // Small delay between sends to avoid overwhelming the server
                await new Promise(resolve => setTimeout(resolve, 50));
                
            } catch (error) {
                console.error(`❌ Error flushing pending update ${i + 1}/${updatesToSend.length}:`, error);
                failCount++;
                
                // Re-queue failed updates (up to limit) - keep the data
                if (this.pendingUpdates.length < this.maxPendingUpdates) {
                    this.pendingUpdates.push(positionData);
                    console.log(`🔄 Re-queued failed update (${this.pendingUpdates.length}/${this.maxPendingUpdates} in queue)`);
                } else {
                    console.error(`⚠️ Cannot re-queue failed update - queue is full! Data may be lost.`);
                }
            }
        }

        const successRate = updatesToSend.length > 0 
            ? ((successCount / updatesToSend.length) * 100).toFixed(1) 
            : 0;

        console.log(`✅ Finished flushing position updates: ${successCount} sent, ${failCount} failed (${successRate}% success rate). Remaining in queue: ${this.pendingUpdates.length}`);

        // If we still have items in queue and we're now online, schedule another flush
        if (this.pendingUpdates.length > 0 && navigator.onLine) {
            console.log(`🔄 Still have ${this.pendingUpdates.length} updates in queue, will retry shortly...`);
            // Retry after a short delay
            setTimeout(() => {
                if (this.pendingUpdates.length > 0 && !this.isFlushing) {
                    this.attemptFlushQueue();
                }
            }, 2000);
        }
    }
}
