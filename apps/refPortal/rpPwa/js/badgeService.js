/**
 * Badge Service for RefereeX PWA
 * Handles app icon badge functionality using the App Badging API
 */

export class BadgeService {
    constructor(sendLog = null) {
        this.sendLog = sendLog;
        this.isSupported = this.checkSupport();
        this.currentBadgeValue = null;
        this.badgeUpdateCallbacks = [];
        
        if (this.isSupported) {
            console.log('✅ App Badge API is supported');
        } else {
            console.log('❌ App Badge API is not supported on this platform');
        }
    }

    /**
     * Check if the App Badging API is supported
     * @returns {boolean} True if supported, false otherwise
     */
    checkSupport() {
        return 'setAppBadge' in navigator && 'clearAppBadge' in navigator;
    }

    /**
     * Set the app badge with a specific number
     * @param {number} value - The number to display on the badge (0-99)
     * @returns {Promise<boolean>} True if successful, false otherwise
     */
    async setBadge(value) {
        await this.sendLog('info', 'Setting badge, value: ' + value + ', isSupported: ' + this.isSupported);
        if (!this.isSupported) {
            console.warn('App Badge API not supported');
            return false;
        }

        // Validate value
        if (typeof value !== 'number' || value < -1 || value > 99) {
            console.error('Badge value must be a number between 0 and 99');
            return false;
        }

        try {
            if (value === -1) {
                await navigator.clearAppBadge();
                console.log('✅ App badge cleared');
            } else {
                await navigator.setAppBadge(value);
                console.log(`✅ App badge set to ${value}`);
            }
            
            this.currentBadgeValue = value;
            this.notifyBadgeUpdate(value);
            return true;
        } catch (error) {
            console.error('❌ Error setting app badge:', error);
            return false;
        }
    }

    /**
    * Zero the app badge
    * @returns {Promise<boolean>} True if successful, false otherwise
    */
    async zeroBadge() {
        if (!!this.currentBadgeValue && this.currentBadgeValue > 0) {
            await this.setBadge(0);
        } else {
            await this.clearBadge();
        }
    }

    /**
     * Clear the app badge
     * @returns {Promise<boolean>} True if successful, false otherwise
     */
    async clearBadge() {
        await this.setBadge(-1);
    }

    /**
     * Set a generic badge (no number, just an indicator)
     * @returns {Promise<boolean>} True if successful, false otherwise
     */
    async setGenericBadge() {
        if (!this.isSupported) {
            console.warn('App Badge API not supported');
            return false;
        }

        try {
            await navigator.setAppBadge();
            console.log('✅ Generic app badge set');
            this.currentBadgeValue = 'generic';
            this.notifyBadgeUpdate('generic');
            return true;
        } catch (error) {
            console.error('❌ Error setting generic app badge:', error);
            return false;
        }
    }

    /**
     * Get the current badge value
     * @returns {number|string|null} Current badge value or null if not set
     */
    getCurrentBadge() {
        return this.currentBadgeValue;
    }

    /**
     * Check if badge is currently set
     * @returns {boolean} True if badge is set, false otherwise
     */
    hasBadge() {
        return this.currentBadgeValue !== null && this.currentBadgeValue >= 0;
    }

    /**
     * Subscribe to badge update events
     * @param {Function} callback - Callback function to call when badge updates
     */
    onBadgeUpdate(callback) {
        if (typeof callback === 'function') {
            this.badgeUpdateCallbacks.push(callback);
        }
    }

    /**
     * Unsubscribe from badge update events
     * @param {Function} callback - Callback function to remove
     */
    offBadgeUpdate(callback) {
        const index = this.badgeUpdateCallbacks.indexOf(callback);
        if (index > -1) {
            this.badgeUpdateCallbacks.splice(index, 1);
        }
    }

    /**
     * Notify all subscribers about badge updates
     * @param {number|string} value - The new badge value
     */
    notifyBadgeUpdate(value) {
        this.badgeUpdateCallbacks.forEach(callback => {
            try {
                callback(value, this.currentBadgeValue);
            } catch (error) {
                console.error('Error in badge update callback:', error);
            }
        });
    }

    /**
     * Update badge based on unread messages count
     * @param {number} unreadCount - Number of unread messages
     */
    async updateFromUnreadCount(unreadCount) {
        if (unreadCount > 0) {
            // Cap at 99 for display purposes
            const badgeValue = Math.min(unreadCount, 99);
            await this.setBadge(badgeValue);
        } else {
            await this.clearBadge();
        }
    }

    /**
     * Update badge based on pending games count
     * @param {number} pendingGames - Number of pending games
     */
    async updateFromPendingGames(pendingGames) {
        await this.sendLog('info', 'Updating badge from pending games, pendingGames: ' + pendingGames);
        if (pendingGames > 0) {
            const badgeValue = Math.min(pendingGames, 99);
            await this.setBadge(badgeValue);
        } else {
            await this.clearBadge();
        }
    }

    /**
     * Update badge based on critical notifications
     * @param {boolean} hasCritical - Whether there are critical notifications
     */
    async updateFromCriticalNotifications(hasCritical) {
        if (hasCritical) {
            await this.setGenericBadge();
        } else {
            await this.clearBadge();
        }
    }

    /**
     * Get platform-specific badge behavior info
     * @returns {Object} Platform information
     */
    getPlatformInfo() {
        const userAgent = navigator.userAgent.toLowerCase();
        const isAndroid = userAgent.includes('android');
        const isIOS = /iphone|ipad|ipod/.test(userAgent);
        const isWindows = userAgent.includes('windows');
        const isMacOS = userAgent.includes('mac');

        return {
            isAndroid,
            isIOS,
            isWindows,
            isMacOS,
            supportsAppBadge: this.isSupported,
            badgeBehavior: this.getBadgeBehavior()
        };
    }

    /**
     * Get expected badge behavior for current platform
     * @returns {string} Description of badge behavior
     */
    getBadgeBehavior() {
        const platform = this.getPlatformInfo();
        
        if (platform.isAndroid) {
            return 'Android: Badge shows automatically with unread notifications';
        } else if (platform.isIOS) {
            return 'iOS: Badge API supported (iOS 16.4+)';
        } else if (platform.isWindows || platform.isMacOS) {
            return 'Desktop: Badge API supported in Chrome/Edge';
        } else {
            return 'Unknown platform behavior';
        }
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = BadgeService;
}