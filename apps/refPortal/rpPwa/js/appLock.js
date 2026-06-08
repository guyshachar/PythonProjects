// Dynamic configuration will be loaded from environment
import { configService } from './config-service.js';
import { envLoader } from './environment-loader.js';

export class AppLock {
    constructor(lockScreen) {
        this.lockScreen = lockScreen;
        this.configService = configService;
        this.envLoader = envLoader;
        this.isLocked = false;
        this.lockTimeout = this.getConfig('SECURITY.LOCKOUT_TIME', 0.2 * 60 * 1000);
        this.pinLength = this.getConfig('SECURITY.PIN_LENGTH', 4);
        this.lastActivity = Date.now();
        this.autoLockEnabled = true;
        
        this.initializeLock();
    }

    /**
     * Get configuration value with fallback
     */
    getConfig(key, defaultValue = null) {
        // Try to get from global config service first
        if (this.configService && this.configService.isLoaded()) {
            return this.configService.get(key, defaultValue);
        }
        
        // Fallback to environment loader
        if (this.envLoader && this.envLoader.isLoaded()) {
            const env = this.envLoader.getAll();
            return this.getNestedValue(env, key, defaultValue);
        }
        
        // Final fallback to default values
        return this.getDefaultConfigValue(key, defaultValue);
    }

    /**
     * Get nested configuration value (e.g., 'FEATURES.PUSH_NOTIFICATIONS')
     */
    getNestedValue(obj, path, defaultValue = null) {
        const keys = path.split('.');
        let current = obj;
        
        for (const key of keys) {
            if (current && typeof current === 'object' && key in current) {
                current = current[key];
            } else {
                return defaultValue;
            }
        }
        
        return current;
    }

    /**
     * Get default configuration value
     */
    getDefaultConfigValue(key, defaultValue = null) {
        const defaults = {
            'SECURITY.LOCKOUT_TIME': 0.2 * 60 * 1000,
            'SECURITY.PIN_LENGTH': 4
        };
        
        return defaults[key] || defaultValue;
    }

    initializeLock() {
        // Check if app should be locked on startup
        this.checkLockStatus();
        
        // Set up activity monitoring
        this.setupActivityMonitoring();
        
        // Set up visibility change detection
        this.setupVisibilityMonitoring();
        
        // Periodic lock checks
        setInterval(() => this.checkLockStatus(), 30000);
    }

    setupActivityMonitoring() {
        const events = ['touchstart', 'touchend', 'mousedown', 'mousemove', 'keypress', 'scroll'];
        
        events.forEach(event => {
            document.addEventListener(event, () => {
                this.lastActivity = Date.now();
                // Don't auto-unlock on activity - only unlock after authentication
                // if (this.isLocked) {
                //     this.unlockApp();
                // }
            });
        });
    }

    setupVisibilityMonitoring() {
        // Lock when app becomes hidden (iOS specific)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.lockApp();
            }
        });
        
        // Lock when page loses focus
        window.addEventListener('blur', () => {
            this.lockApp();
        });
        
        // Lock when switching apps (iOS)
        window.addEventListener('pagehide', () => {
            this.lockApp();
        });
    }

    checkLockStatus() {
        if (!this.autoLockEnabled) return;
        
        const timeSinceActivity = Date.now() - this.lastActivity;
        
        if (timeSinceActivity > this.lockTimeout && !this.isLocked) {
            this.lockApp();
        }
    }

    lockApp() {
        this.isLocked = true;
        this.lastActivity = Date.now();
        
        // Hide sensitive content
        this.hideSensitiveContent();
        
        // Show lock screen if available
        if (this.lockScreen) {
            this.lockScreen.show();
        } else {
            console.warn('⚠️ Lock screen not available');
        }
        
        // Prevent accidental dismissal
        this.preventAccidentalUnlock();
        
        console.log('🔒 App locked');
    }

    preventAccidentalUnlock() {
        // Prevent right-click context menu
        document.addEventListener('contextmenu', (e) => {
            if (this.isLocked) {
                e.preventDefault();
                return false;
            }
        });
        
        // Prevent keyboard shortcuts that might bypass security
        document.addEventListener('keydown', (e) => {
            if (this.isLocked) {
                // Block F12, Ctrl+Shift+I, Ctrl+U, etc.
                if (e.key === 'F12' || 
                    (e.ctrlKey && e.shiftKey && e.key === 'I') ||
                    (e.ctrlKey && e.key === 'u') ||
                    (e.ctrlKey && e.key === 's')) {
                    e.preventDefault();
                    return false;
                }
            }
        });

        // Prevent escape key from dismissing lock screen
        document.addEventListener('keydown', (e) => {
            if (this.isLocked && e.key === 'Escape') {
                e.preventDefault();
                return false;
            }
        });

        // Prevent back button/gesture on mobile
        if ('history' in window) {
            const originalPushState = history.pushState;
            const originalReplaceState = history.replaceState;
            
            history.pushState = function(...args) {
                if (!this.isLocked) {
                    return originalPushState.apply(history, args);
                }
            }.bind(this);
            
            history.replaceState = function(...args) {
                if (!this.isLocked) {
                    return originalReplaceState.apply(history, args);
                }
            }.bind(this);
        }
    }

    unlockApp() {
        this.isLocked = false;
        this.lastActivity = Date.now();
        
        // Show sensitive content
        this.showSensitiveContent();
        
        // Hide lock screen
        this.lockScreen.hide();
        
        console.log('🔓 App unlocked');
    }

    // Method to unlock app after successful authentication
    unlockAfterAuthentication() {
        if (this.isLocked) {
            this.unlockApp();
            return true;
        }
        return false;
    }

    // Method to set PIN
    setPIN(pin) {
        if (pin && pin.length >= this.pinLength) {
            localStorage.setItem('security_pin', pin);
            return true;
        }
        return false;
    }

    // Method to check if app is locked
    isAppLocked() {
        return this.isLocked;
    }

    // Method to manually lock app (for testing)
    manualLock() {
        if (!this.isLocked) {
            this.lockApp();
        }
    }

    // Method to get lock status info
    getLockStatus() {
        return {
            isLocked: this.isLocked,
            lastActivity: this.lastActivity,
            timeSinceActivity: Date.now() - this.lastActivity,
            autoLockEnabled: this.autoLockEnabled,
            lockTimeout: this.lockTimeout
        };
    }

    hideSensitiveContent() {
        // Hide game lists, user info, etc.
        const sensitiveElements = document.querySelectorAll('.sensitive-content, .game-item, .user-info');
        sensitiveElements.forEach(el => {
            el.style.display = 'none';
        });
    }

    showSensitiveContent() {
        // Show all content again
        const sensitiveElements = document.querySelectorAll('.sensitive-content, .game-item, .user-info');
        sensitiveElements.forEach(el => {
            el.style.display = '';
        });
    }
}
