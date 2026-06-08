/**
 * Configuration Service for RefPortal PWA
 * Provides dynamic configuration loading from client-env endpoint
 */

class ConfigService {
    constructor() {
        this.config = null;
        this.loading = false;
        this.loaded = false;
        this.error = null;
        this.listeners = [];
    }

    /**
     * Load configuration from various sources
     */
    async load() {
        if (this.loading) {
            return this.waitForLoad();
        }

        if (this.loaded) {
            return this.config;
        }

        this.loading = true;
        this.error = null;

        try {
            // Try to load from API endpoint first (most up-to-date from .env)
            try {
                await this.loadFromAPI();
                this.loaded = true;
                this.loading = false;
                this.notifyListeners();
                return this.config;
            } catch (apiError) {
                console.warn('⚠️ Failed to load from API, trying environment loader:', apiError.message);
            }

            // Fallback: try to get configuration from environment loader
            if (window.envLoader && window.envLoader.isLoaded()) {
                const env = window.envLoader.getAll();
                this.config = this.buildConfigFromEnv(env);
                console.log('🌍 Configuration loaded from environment loader:', this.config);
                this.loaded = true;
                this.loading = false;
                this.notifyListeners();
                return this.config;
            }

            // Fallback: try to load from client-env directly
            if (window.CLIENT_ENV) {
                this.config = this.buildConfigFromEnv(window.CLIENT_ENV);
                console.log('🌍 Configuration loaded from CLIENT_ENV:', this.config);
                this.loaded = true;
                this.loading = false;
                this.notifyListeners();
                return this.config;
            }

        } catch (error) {
            this.error = error;
            this.loading = false;
            console.error('❌ Failed to load configuration:', error);
            
            // Fallback to default configuration
            this.config = this.getDefaultConfig();
            this.loaded = true;
            this.notifyListeners();
            return this.config;
        }
    }

    /**
     * Build configuration object from environment variables
     */
    buildConfigFromEnv(env) {
        const defaultEndpoints = this.getDefaultConfig().ENDPOINTS;
        return {
            // API Configuration
            API_BASE_URL: env.API_BASE_URL || 'https://pwa-dev.refereex.com:24503' ||'https://pwa-dev.refereex.com:5003',
            WSS_BASE_URL: env.API_BASE_URL ? env.API_BASE_URL.replace(/^https?:\/\//, '') : 'pwa-dev.refereex.com:5003',
            
            // VAPID Keys (from environment or default)
            VAPID_PUBLIC_KEY: env.VAPID_PUBLIC_KEY || 'BCrb6Lp792xCx8tOm_BLPrvb6DY9GDhfu9K04DBrhAz4qDL7LqVodnePQ4ZTmZXBUWhWumYlKwEjj4QzHRChhX0',
            
            // Endpoints — merge defaults so new routes work with cached client-env
            ENDPOINTS: {
                ...defaultEndpoints,
                ...(env.ENDPOINTS || {}),
            },
            OPEN_REPORTS_EMAILS: ['openreports@refereex.com'],
            
            // Features
            FEATURES: {
                PUSH_NOTIFICATIONS: env.FEATURES?.PUSH_NOTIFICATIONS !== false,
                PUSH_NOTIFICATIONS_MUST: env.FEATURES?.PUSH_NOTIFICATIONS_MUST === true,
                CHAT_SYNC: env.FEATURES?.CHAT_SYNC !== false,
                OFFLINE_SUPPORT: env.FEATURES?.OFFLINE_SUPPORT !== false,
                BACKGROUND_SYNC: env.FEATURES?.BACKGROUND_SYNC !== false,
                INSTALL_PROMPT: env.FEATURES?.INSTALL_PROMPT !== false,
                MAX_GPS_ACCURACY: env.FEATURES?.MAX_GPS_ACCURACY || 50,
                START_MONITORING_HOURS_BEFORE_GAME: env.FEATURES?.START_MONITORING_HOURS_BEFORE_GAME || 3,
                SPEED_THRESHOLD: env.FEATURES?.SPEED_THRESHOLD || 20,
                MIN_DISTANCE_THRESHOLD: env.FEATURES?.MIN_DISTANCE_THRESHOLD || 2,
            },
            
            // Security
            SECURITY: {
                ENABLE_PIN: env.SECURITY?.ENABLE_PIN === true,
                PIN_LENGTH: env.SECURITY?.PIN_LENGTH || 4,
                MAX_PAIR_ATTEMPTS: env.SECURITY?.MAX_PAIR_ATTEMPTS || 3,
                LOCKOUT_TIME: env.SECURITY?.LOCKOUT_TIME || 0.2 * 60 * 1000
            },
            
            // App Configuration
            APP_NAME: env.APP_NAME || 'RefereeX',
            APP_SHORT_NAME: env.APP_SHORT_NAME || 'RefereeX',
            CACHE_VERSION: env.VERSION || 'v1.0.0',
            DEBUG: env.DEBUG_MODE === true
        };
    }

    /**
     * Load configuration from API endpoint
     */
    async loadFromAPI() {
        const response = await fetch('/api/client-env', {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'Cache-Control': 'no-cache'
            }
        });

        if (!response.ok) {
            throw new Error(`API request failed: ${response.status} ${response.statusText}`);
        }

        const env = await response.json();
        this.config = this.buildConfigFromEnv(env);
        console.log('🌍 Configuration loaded from API endpoint:', this.config);
        return this.config;
    }

    /**
     * Get default configuration
     */
    getDefaultConfig() {
        return {
            API_BASE_URL: 'https://pwa-dev.refereex.com:5003',
            WSS_BASE_URL: 'pwa-dev.refereex.com:5003',
            VAPID_PUBLIC_KEY: 'BCrb6Lp792xCx8tOm_BLPrvb6DY9GDhfu9K04DBrhAz4qDL7LqVodnePQ4ZTmZXBUWhWumYlKwEjj4QzHRChhX0',
            ENDPOINTS: {
                HEALTH: '/api/pwa/health',
                CHECK_AUTH: '/api/pwa/check-auth',
                UNPAIR: '/api/pwa/unpair',
                DASHBOARD: '/api/pwa/dashboardLoadData',
                TENANTS: '/api/pwa/tenants',
                ROLES: '/api/pwa/roles',
                REFEREES: '/api/pwa/referees',
                REFEREEGAMES: '/api/pwa/refereeGames',
                REFEREEREVIEWS: '/api/pwa/refereeReviews',
                MESSAGES: '/api/pwa/messages',
                DOWNLOADICSFILE: '/api/pwa/downloadIcsFile',
                FIELDS: '/api/pwa/fields',
                AVAILABILITY: '/api/pwa/availability',
                UPDATEREFEREEAVAILABILITY: '/api/pwa/updateRefereeAvailability',
                DOCUMENTS: '/api/pwa/documents',
                CHAT: '/api/pwa/chat',
                SET_PUSH_SUBSCRIPTION: '/api/pwa/push/set-subscription',
                PAIR: '/api/pwa/pair',
                APPROVEGAME: '/api/pwa/approveGame',
                // Auth endpoints for RefreshTokenService
                AUTH_REFRESH_TOKEN: '/auth/refresh',
                AUTH_VALIDATE_TOKEN: '/auth/validate',
                POSITION_UPDATE: '/api/pwa/position-update',
                USER_DETAILS: '/api/pwa/user-details',
                UPDATE_USER_DETAILS: '/api/pwa/updateUserDetails',
                CHANGE_PASSWORD: '/api/pwa/change-password',
                UPDATE_GAME_REPORT: '/api/pwa/pwaUpdateGameReport',
                LOG: '/api/pwa/log',
                REFEREE_TEMPLATES: '/api/pwa/refereeTemplates',
                REFEREE_TEMPLATE_UPDATE: '/api/pwa/templates/update',
                NOTIFICATIONS: '/api/pwa/notifications',
                NOTIFICATION_UPDATE: '/api/pwa/notifications/update',
                PUBLIC_LEAGUE_TABLES: '/api/pwa/public/leagueTables',
                PUBLIC_GAMES: '/api/pwa/public/games',
                PUBLIC_GAMES_STREAM: '/api/pwa/public/games/stream',
                PUBLIC_TABLES_FILTERS: '/api/pwa/public/tablesFilters',
                PUBLIC_GAMES_FILTERS: '/api/pwa/public/gamesFilters',
            },
            FEATURES: {
                PUSH_NOTIFICATIONS: true,
                PUSH_NOTIFICATIONS_MUST: false,
                CHAT_SYNC: true,
                OFFLINE_SUPPORT: true,
                BACKGROUND_SYNC: true,
                INSTALL_PROMPT: true,
                MAX_GPS_ACCURACY: 30,
                START_MONITORING_HOURS_BEFORE_GAME: 3,
                SPEED_THRESHOLD: 20,
                MIN_DISTANCE_THRESHOLD: 2,
            },
            SECURITY: {
                ENABLE_PIN: false,
                PIN_LENGTH: 4,
                MAX_PAIR_ATTEMPTS: 3,
                LOCKOUT_TIME: 0.2 * 60 * 1000
            },
            APP_NAME: 'RefereeX',
            APP_SHORT_NAME: 'RefereeX',
            CACHE_VERSION: 'v1.0.0',
            DEBUG: true
        };
    }

    /**
     * Wait for current loading to complete
     */
    async waitForLoad() {
        return new Promise((resolve, reject) => {
            const checkLoaded = () => {
                if (this.loaded) {
                    resolve(this.config);
                } else if (this.error) {
                    reject(this.error);
                } else {
                    setTimeout(checkLoaded, 10);
                }
            };
            checkLoaded();
        });
    }

    /**
     * Add listener for configuration load events
     */
    addListener(callback) {
        this.listeners.push(callback);
        
        // If already loaded, call immediately
        if (this.loaded) {
            callback(this.config, null);
        }
    }

    /**
     * Remove listener
     */
    removeListener(callback) {
        const index = this.listeners.indexOf(callback);
        if (index > -1) {
            this.listeners.splice(index, 1);
        }
    }

    /**
     * Notify all listeners
     */
    notifyListeners() {
        this.listeners.forEach(callback => {
            try {
                callback(this.config, this.error);
            } catch (error) {
                console.error('Error in configuration listener:', error);
            }
        });
    }

    /**
     * Get configuration value
     */
    get(key, defaultValue = null) {
        if (!this.config) {
            console.warn('Configuration not loaded yet. Call load() first.');
            return defaultValue;
        }
        return this.getNestedValue(this.config, key, defaultValue);
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
     * Check if configuration is loaded
     */
    isLoaded() {
        return this.loaded;
    }

    /**
     * Check if configuration is loading
     */
    isLoading() {
        return this.loading;
    }

    /**
     * Get loading error
     */
    getError() {
        return this.error;
    }

    /**
     * Get all configuration
     */
    getAll() {
        return this.config;
    }

    /**
     * Reload configuration
     */
    async reload() {
        this.loaded = false;
        return this.load();
    }
}

// Create singleton instance
const configService = new ConfigService();

// Auto-load configuration when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        configService.load().catch(error => {
            console.error('Failed to auto-load configuration:', error);
        });
    });
} else {
    // DOM already ready
    configService.load().catch(error => {
        console.error('Failed to auto-load configuration:', error);
    });
}

// Make available globally
//window.configService = configService;

// Export for ES6 modules
export default ConfigService;
export { configService };
