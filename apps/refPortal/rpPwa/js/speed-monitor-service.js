import { getUnifiedGeolocationService } from './unified-geolocation-service.js';

/**
 * Speed Monitor Service for RefPortal PWA
 * Monitors device speed and triggers events when speed exceeds threshold
 * Uses unified geolocation service to avoid multiple watchPosition calls
 */

export class SpeedMonitorService {
    constructor(options = {}) {
        this.options = {
            speedThreshold: options.speedThreshold || 10, // km/h
            updateInterval: options.updateInterval || 1000, // ms
            enableHighAccuracy: options.enableHighAccuracy || true,
            timeout: options.timeout || 10000, // ms
            maximumAge: options.maximumAge || 1000, // ms
            startMonitoringHoursBeforeGame: options.startMonitoringHoursBeforeGame || 2,
            detectArrival: options.detectArrival || true,
            showToast: options.showToast || null, // Toast callback function
            ...options
        };
        
        this.isMonitoring = false;
        this.geolocationSubscriberId = null;
        this.lastPosition = null;
        this.currentSpeed = 0;
        this.speedHistory = [];
        this.maxHistoryLength = 10;
        this.callbacks = {
            onSpeedExceeded: [],
            onSpeedChanged: [],
            onError: []
        };
        
        // Game field navigation
        this.nextGameFieldWazeLink = null;
        this.navigationCooldown = 30000; // 30 seconds cooldown between navigations
        this.navigationTriggeredForGame = false; // Track if navigation was triggered for this game
        
        // Game scheduling
        this.nextGameDateTime = null;
        this.gameFieldLocation = null;
        this.arrivalRadius = 100; // meters - consider arrived if within this radius
        this.scheduleCheckInterval = null;
        this.isScheduled = false;
        this.arrivalDetected = false;
        this.serviceStartDateTime = null;
        
        this.logger = console;
        this.permissionStatus = 'unknown';
        
        // Get unified geolocation service
        this.geolocationService = getUnifiedGeolocationService(options);
        
        // Bind methods
        this.startMonitoring = this.startMonitoring.bind(this);
        this.stopMonitoring = this.stopMonitoring.bind(this);
        this.handlePositionUpdate = this.handlePositionUpdate.bind(this);
        this.handleError = this.handleError.bind(this);
    }

    /**
     * Start monitoring device speed
     */
    async startMonitoring() {
        if (this.isMonitoring) {
            this.logger.warn('Speed monitoring is already active');
            return;
        }

        try {
            // Check permission status first
            const permission = await this.requestPermission();
            if (permission === 'denied') {
                this.handleError(new Error('Geolocation permission denied'));
                return;
            }
            // If permission is 'prompt' or 'granted', proceed with monitoring

            this.logger.log('🚀 Starting speed monitoring...');
            this.isMonitoring = true;

            // Subscribe to unified geolocation service
            this.geolocationSubscriberId = this.geolocationService.subscribe({
                onPositionUpdate: (position, lastPosition) => this.handlePositionUpdate(position, lastPosition),
                onError: (error) => this.handleError(error)
            }, {
                maxAccuracy: this.options.maxAccuracy,
                updateInterval: this.options.updateInterval
            });

            this.logger.log(`✅ Speed monitoring started (threshold: ${this.options.speedThreshold} km/h)`);
            
        } catch (error) {
            this.handleError(error);
        }
    }

    /**
     * Stop monitoring device speed
     */
    async stopMonitoring() {
        if (!this.isMonitoring) {
            this.logger.warn('Speed monitoring is not active');
            return;
        }

        // Unsubscribe from unified geolocation service
        if (this.geolocationSubscriberId) {
            this.geolocationService.unsubscribe(this.geolocationSubscriberId);
            this.geolocationSubscriberId = null;
        }

        this.isMonitoring = false;
        this.logger.log('🛑 Speed monitoring stopped');
    }

    /**
     * Request geolocation permission
     */
    async requestPermission() {
        if (!navigator.permissions) {
            // Fallback for browsers without permissions API
            this.logger.log('Permissions API not available, trying direct access...');
            return 'prompt';
        }

        try {
            const permission = await navigator.permissions.query({ name: 'geolocation' });
            this.permissionStatus = permission.state;
            
            this.logger.log(`Permission status: ${permission.state}`);
            
            if (permission.state === 'denied') {
                this.logger.warn('Geolocation permission denied by user');
                return 'denied';
            }
            
            // Listen for permission changes
            permission.onchange = () => {
                this.permissionStatus = permission.state;
                this.logger.log(`Permission changed to: ${permission.state}`);
            };
            
            // Return the state - 'prompt' means we should try to access location
            // which will trigger the browser's permission prompt
            return permission.state;
        } catch (error) {
            this.logger.warn('Could not check geolocation permission:', error);
            return 'prompt'; // Assume we need to prompt if we can't check
        }
    }

    /**
     * Handle position updates from unified geolocation service
     */
    handlePositionUpdate(position, lastPosition) {
        try {
            const newPosition = {
                latitude: position.latitude,
                longitude: position.longitude,
                accuracy: position.accuracy,
                timestamp: position.timestamp || Date.now(),
                speed: position.speed || null // m/s
            };

            // Calculate speed if not provided by browser
            if (newPosition.speed === null && this.lastPosition) {
                newPosition.speed = this.calculateSpeed(this.lastPosition, newPosition);
            }

            // Convert speed from m/s to km/h
            const speedKmh = newPosition.speed ? (newPosition.speed * 3.6) : 0;
            this.currentSpeed = speedKmh;

            // Update speed history
            this.updateSpeedHistory(speedKmh);

            // Trigger speed changed callback
            this.triggerCallback('onSpeedChanged', {
                speed: speedKmh,
                position: newPosition,
                isExceedingThreshold: speedKmh > this.options.speedThreshold
            });

            // Check if speed exceeds threshold and trigger navigation
            if (speedKmh > this.options.speedThreshold) {
                // Try to trigger navigation to next game field
                const navigationTriggered = this.triggerNavigation();
                
                // Always trigger callback for speed exceeded
                this.triggerCallback('onSpeedExceeded', {
                    speed: speedKmh,
                    position: newPosition,
                    threshold: this.options.speedThreshold,
                    timestamp: newPosition.timestamp,
                    navigationTriggered: navigationTriggered,
                    fieldWazeLink: this.nextGameFieldWazeLink
                });
            }

            this.lastPosition = newPosition;

        } catch (error) {
            this.handleError(error);
        }
    }

    /** 
     * Calculate speed between two positions
     */
    calculateSpeed(position1, position2) {
        if (!position1 || !position2) return 0;

        const distance = this.calculateDistance(
            position1.latitude, position1.longitude,
            position2.latitude, position2.longitude
        );

        const timeDiff = (position2.timestamp - position1.timestamp) / 1000; // seconds
        if (timeDiff <= 0) return 0;

        return distance / timeDiff; // m/s
    }

    /**
     * Calculate distance between two coordinates using Haversine formula
     */
    calculateDistance(lat1, lng1, lat2, lng2) {
        const R = 6371e3; // Earth's radius in meters
        const φ1 = lat1 * Math.PI / 180;
        const φ2 = lat2 * Math.PI / 180;
        const Δφ = (lat2 - lat1) * Math.PI / 180;
        const Δλ = (lng2 - lng1) * Math.PI / 180;

        const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
                Math.cos(φ1) * Math.cos(φ2) *
                Math.sin(Δλ/2) * Math.sin(Δλ/2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

        return R * c; // Distance in meters
    }

    /**
     * Update speed history
     */
    updateSpeedHistory(speed) {
        this.speedHistory.push({
            speed: speed,
            timestamp: Date.now()
        });

        // Keep only recent history
        if (this.speedHistory.length > this.maxHistoryLength) {
            this.speedHistory.shift();
        }
    }

    /**
     * Handle geolocation errors
     */
    handleError(error) {
        this.logger.error('Speed monitoring error:', error);
        
        const errorData = {
            error: error,
            message: this.getErrorMessage(error.code),
            timestamp: Date.now(),
            permissionStatus: this.permissionStatus,
            instructions: this.getPermissionInstructions(error.code)
        };
        
        this.triggerCallback('onError', errorData);
    }

    /**
     * Get user-friendly error message
     */
    getErrorMessage(errorCode) {
        switch (errorCode) {
            case 1:
                return 'Geolocation permission denied';
            case 2:
                return 'Position unavailable';
            case 3:
                return 'Geolocation request timeout';
            default:
                return 'Unknown geolocation error';
        }
    }

    /**
     * Get permission instructions based on error code
     */
    getPermissionInstructions(errorCode) {
        switch (errorCode) {
            case 1: // Permission denied
                return {
                    title: 'Location Permission Required',
                    message: 'To monitor your speed, please grant location permission:',
                    steps: [
                        'Click the lock icon (🔒) in your browser\'s address bar',
                        'Select "Allow" for location access',
                        'Refresh this page',
                        'Or go to your browser settings and enable location for this site'
                    ],
                    browserSpecific: {
                        chrome: 'Chrome: Click lock icon → Allow location access',
                        firefox: 'Firefox: Click shield icon → Allow location access',
                        safari: 'Safari: Safari → Preferences → Websites → Location → Allow',
                        mobile: 'Mobile: Settings → Privacy → Location Services → Allow'
                    }
                };
            case 2: // Position unavailable
                return {
                    title: 'GPS Signal Unavailable',
                    message: 'Unable to get your location. Please check:',
                    steps: [
                        'Ensure GPS/Location Services are enabled on your device',
                        'Try moving to an area with better GPS signal',
                        'Check if you\'re indoors (GPS works better outdoors)',
                        'Restart your browser and try again'
                    ]
                };
            case 3: // Timeout
                return {
                    title: 'Location Request Timeout',
                    message: 'The location request took too long. Please try:',
                    steps: [
                        'Check your internet connection',
                        'Ensure GPS is enabled',
                        'Try again in a few seconds',
                        'Move to an area with better GPS signal'
                    ]
                };
            default:
                return {
                    title: 'Location Error',
                    message: 'An error occurred while accessing your location.',
                    steps: [
                        'Refresh the page and try again',
                        'Check your browser settings',
                        'Ensure location services are enabled'
                    ]
                };
        }
    }

    /**
     * Add event callback
     */
    on(event, callback) {
        if (this.callbacks[event]) {
            this.callbacks[event].push(callback);
        } else {
            this.logger.warn(`Unknown event: ${event}`);
        }
    }

    /**
     * Remove event callback
     */
    off(event, callback) {
        if (this.callbacks[event]) {
            const index = this.callbacks[event].indexOf(callback);
            if (index > -1) {
                this.callbacks[event].splice(index, 1);
            }
        }
    }

    /**
     * Trigger callback for specific event
     */
    triggerCallback(event, data) {
        if (this.callbacks[event]) {
            this.callbacks[event].forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    this.logger.error(`Error in ${event} callback:`, error);
                }
            });
        }
    }

    /**
     * Get current speed
     */
    getCurrentSpeed() {
        return this.currentSpeed;
    }

    /**
     * Get speed history
     */
    getSpeedHistory() {
        return [...this.speedHistory];
    }

    /**
     * Get average speed from history
     */
    getAverageSpeed() {
        if (this.speedHistory.length === 0) return 0;
        
        const sum = this.speedHistory.reduce((acc, entry) => acc + entry.speed, 0);
        return sum / this.speedHistory.length;
    }

    /**
     * Check if currently exceeding speed threshold
     */
    isExceedingThreshold() {
        return this.currentSpeed >= this.options.speedThreshold;
    }

    /**
     * Update speed threshold
     */
    setSpeedThreshold(threshold) {
        this.options.speedThreshold = threshold;
        this.logger.log(`Speed threshold updated to ${threshold} km/h`);
    }

    /**
     * Get monitoring status
     */
    getStatus() {
        return {
            isMonitoring: this.isMonitoring,
            currentSpeed: this.currentSpeed,
            speedThreshold: this.options.speedThreshold,
            isExceedingThreshold: this.isExceedingThreshold(),
            permissionStatus: this.permissionStatus,
            historyLength: this.speedHistory.length,
            isScheduled: this.isScheduled,
            nextGameDateTime: this.nextGameDateTime,
            serviceStartDateTime: this.serviceStartDateTime,
            arrivalDetected: this.arrivalDetected,
            gameFieldLocation: this.gameFieldLocation
        };
    }

    /**
     * Get scheduling status
     */
    getScheduleStatus() {
        const now = new Date();
        const timeUntilStart = this.serviceStartDateTime ? this.serviceStartDateTime.getTime() - now.getTime() : null;
        const timeUntilGame = this.nextGameDateTime ? this.nextGameDateTime.getTime() - now.getTime() : null;
        
        return {
            isScheduled: this.isScheduled,
            nextGameDateTime: this.nextGameDateTime,
            serviceStartDateTime: this.serviceStartDateTime,
            timeUntilStart: timeUntilStart,
            timeUntilGame: timeUntilGame,
            arrivalDetected: this.arrivalDetected,
            gameFieldLocation: this.gameFieldLocation,
            gameTitle: this.gameTitle,
            arrivalRadius: this.arrivalRadius
        };
    }

    /**
     * Set the next game field Waze URL for navigation
     */
    setNextGameFieldUrl(fieldWazeLink) {
        this.nextGameFieldWazeLink = fieldWazeLink;
        this.navigationTriggeredForGame = false; // Reset navigation flag
        this.logger.log(`Next game field URL set: ${fieldWazeLink}`);
    }

    /**
     * Set next game details for scheduling
     */
    async setNextGame(gameDateTime, fieldLocation, fieldWazeLink = null, gameTitle = null) {
        if (this.lastGameDateTime == null || gameDateTime !== this.lastGameDateTime) {
            this.lastGameDateTime = gameDateTime;
            this.nextGameDateTime = new Date(gameDateTime);
            this.gameFieldLocation = fieldLocation; // { latitude, longitude, name }
            this.gameTitle = gameTitle; // e.g., "Team A vs Team B"
            this.arrivalDetected = false;
            this.isScheduled = true;
            
            // Reset navigation flag for new game
            this.navigationTriggeredForGame = false;
            
            if (fieldWazeLink) {
                this.setNextGameFieldUrl(fieldWazeLink);
            }
            
            this.logger.log(`Next game scheduled: ${this.nextGameDateTime.toLocaleString()} - ${gameTitle || 'Game'} at ${fieldLocation.name || 'field'}`);
            await this.startScheduledMonitoring();
        }
    }

    /**
     * Clear next game details
     */
    clearNextGame() {
        this.nextGameDateTime = null;
        this.gameFieldLocation = null;
        this.gameTitle = null;
        this.arrivalDetected = false;
        this.isScheduled = false;
        this.navigationTriggeredForGame = false;
        this.clearNextGameFieldUrl();
        
        if (this.scheduleCheckInterval) {
            clearInterval(this.scheduleCheckInterval);
            this.scheduleCheckInterval = null;
        }
        
        this.logger.log('Next game cleared');
    }

    /**
     * Start scheduled monitoring (n hours before game)
     */
    async startScheduledMonitoring() {
        if (!this.nextGameDateTime || !this.gameFieldLocation) {
            this.logger.warn('Cannot start scheduled monitoring: missing game time or field location');
            return;
        }

        // Calculate start time (n hours before game)
        this.serviceStartDateTime = new Date(this.nextGameDateTime.getTime() - (this.options.startMonitoringHoursBeforeGame * 60 * 60 * 1000));
        
        this.logger.log(`Scheduled monitoring will start at: ${this.serviceStartDateTime.toLocaleString()}`);
        
        // Check every minute if it's time to start
        await this.checkSchedule();
        this.scheduleCheckInterval = setInterval(async () => {
            await this.checkSchedule();
        }, 60000); // Check every minute
    }

    /**
     * Check if speed monitoring should be active (between serviceStartDateTime and either one hour after nextGameDateTime or arrived)
     */
    shouldSpeedMonitoringBeActive() {
        if (!this.serviceStartDateTime || !this.nextGameDateTime) {
            return false;
        }
        
        const now = new Date();
        const oneHourAfterGame = new Date(this.nextGameDateTime.getTime() + (60 * 60 * 1000));
        
        // Stop if arrived
        if (this.arrivalDetected) {
            return false;
        }
        
        // Active between serviceStartDateTime and one hour after nextGameDateTime
        const result =  now >= this.serviceStartDateTime && now < oneHourAfterGame;
        return result;
    }

    /**
     * Check if it's time to start/stop monitoring based on schedule
     */
    async checkSchedule() {
        const shouldBeActive = this.shouldSpeedMonitoringBeActive();
        
        // If we haven't started yet and it's time to start (serviceStartDateTime)
        if (!this.isMonitoring && shouldBeActive) {
            this.logger.log('🚀 Starting scheduled speed monitoring (2 hours before game)');
            await this.startMonitoring();
            return;
        }
        
        // If we're monitoring and it's past game time or at game time, stop
        if (this.isMonitoring && !shouldBeActive) {
            this.logger.log('⏰ Speed monitoring window ended, stopping speed monitoring');
            this.stopMonitoring();
            //this.clearSchedule();
            return;
        }
        
        // If we're monitoring and within the active window, check for arrival
        if (this.isMonitoring && shouldBeActive && this.lastPosition) {
            this.checkArrival();
        }
    }

    /**
     * Check if referee has arrived at the field
     */
    checkArrival() {
        if (!this.gameFieldLocation || !this.lastPosition || !this.options.detectArrival) {
            return;
        }

        const distance = this.calculateDistance(
            this.lastPosition.latitude,
            this.lastPosition.longitude,
            this.gameFieldLocation.latitude,
            this.gameFieldLocation.longitude
        );

        if (distance <= this.arrivalRadius) {
            this.arrivalDetected = true;
            this.logger.log(`🏟️ Arrived at field: ${this.gameFieldLocation.name || 'game field'} (${distance.toFixed(0)}m away)`);
            
            // Stop monitoring
            this.stopMonitoring();
            this.clearSchedule();
            
            // Trigger arrival callback
            this.triggerCallback('onArrival', {
                fieldName: this.gameFieldLocation.name,
                distance: distance,
                arrivalTime: new Date(),
                gameTime: this.nextGameDateTime
            });
        }
    }

    /**
     * Clear schedule and stop monitoring
     */
    clearSchedule() {
        if (this.scheduleCheckInterval) {
            clearInterval(this.scheduleCheckInterval);
            this.scheduleCheckInterval = null;
        }
        this.isScheduled = false;
    }

    /**
     * Clear the next game field URL
     */
    clearNextGameFieldUrl() {
        this.nextGameFieldWazeLink = null;
        this.navigationTriggeredForGame = false;
        this.logger.log('Next game field URL cleared');
    }

    /**
     * Get the current next game field URL
     */
    getNextGameFieldUrl() {
        return this.nextGameFieldWazeLink;
    }

    /**
     * Check if navigation should be triggered based on speed
     */
    shouldTriggerNavigation() {
        // Check if we have a URL and haven't already triggered navigation for this game
        const now = new Date();
        if (!this.nextGameFieldWazeLink || this.navigationTriggeredForGame 
            || !this.serviceStartDateTime || now < this.serviceStartDateTime || now >= this.nextGameDateTime) {
            return false;
        }

        // Check if speed exceeds threshold
        if (this.currentSpeed <= this.options.speedThreshold) {
            return false;
        }

        return true;
    }

    /**
     * Show toast notification
     */
    showToastMessage(message, type = 'info') {
        if (this.options.showToast && typeof this.options.showToast === 'function') {
            this.options.showToast(message, type);
        } else {
            // Fallback to console if no toast callback provided
            this.logger.log(`Toast (${type}): ${message}`);
        }
    }

    /**
     * Trigger navigation to next game field
     */
    triggerNavigation() {
        if (!this.shouldTriggerNavigation()) {
            return false;
        }

        try {
            this.logger.log(`🚗 Speed exceeded ${this.options.speedThreshold} km/h, navigating to next game field...`);
            
            // Show toast message before opening navigation
            this.showToastMessage('פותח Waze לניווט למגרש המשחק... אנא אישר פתיחת חלון חדש', 'info');
            
            // Small delay to ensure toast is visible before browser asks for permission
            setTimeout(() => {
                // Open Waze URL
                window.open(this.nextGameFieldWazeLink, '_blank');
            }, 1000);
            
            // Mark as triggered for this game (once per game)
            this.navigationTriggeredForGame = true;
            this.lastNavigationTime = Date.now();
            
            this.logger.log('Navigation triggered for this game - will not trigger again until next game');
            
            // Trigger callback
            this.triggerCallback('onSpeedExceeded', {
                speed: this.currentSpeed,
                threshold: this.options.speedThreshold,
                action: 'navigation_triggered',
                fieldWazeLink: this.nextGameFieldWazeLink,
                timestamp: Date.now()
            });
            
            return true;
        } catch (error) {
            this.logger.error('Failed to trigger navigation:', error);
            return false;
        }
    }

    /**
     * Cleanup resources
     */
    async cleanup() {
        await this.stopMonitoring();
        this.clearSchedule();
        this.callbacks = {
            onSpeedExceeded: [],
            onSpeedChanged: [],
            onError: []
        };
        this.speedHistory = [];
        this.lastPosition = null;
        this.nextGameFieldWazeLink = null;
        this.navigationTriggeredForGame = false;
        this.nextGameDateTime = null;
        this.gameFieldLocation = null;
        this.gameTitle = null;
        this.arrivalDetected = false;
        this.isScheduled = false;
        this.serviceStartDateTime = null;
    }
}