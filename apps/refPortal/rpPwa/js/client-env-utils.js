/**
 * Client Environment Utilities
 * Easy access to environment variables in client-side JavaScript
 */

class ClientEnvUtils {
    constructor() {
        this.env = null;
        this.ready = false;
        this.init();
    }

    /**
     * Initialize environment utilities
     */
    async init() {
        try {
            // Wait for environment loader to be available
            if (window.envLoader) {
                this.env = await window.envLoader.load();
            } else if (window.CLIENT_ENV) {
                this.env = window.CLIENT_ENV;
            } else {
                // Fallback to default
                this.env = this.getDefaultEnv();
            }
            this.ready = true;
        } catch (error) {
            console.error('Failed to initialize client environment:', error);
            this.env = this.getDefaultEnv();
            this.ready = true;
        }
    }

    /**
     * Get default environment
     */
    getDefaultEnv() {
        return {
            NODE_ENV: 'development',
            DEBUG_MODE: true,
            API_BASE_URL: 'http://localhost:8000',
            PWA_BASE_URL: window.location.origin,
            PWA_HTTP_PORT: 3000,
            PWA_HTTPS_PORT: 3443,
            CORS_ORIGIN: '*',
            BUILD_TIME: new Date().toISOString(),
            VERSION: 'v1.0.0',
            FEATURES: {
                PUSH_NOTIFICATIONS: true,
                OFFLINE_SUPPORT: true,
                DEBUG_MODE: true
            },
            APP_NAME: 'RefereeX',
            APP_SHORT_NAME: 'RefereeX'
        };
    }

    /**
     * Get environment variable
     */
    get(key, defaultValue = null) {
        if (!this.ready) {
            console.warn('Environment not ready yet. Using default value.');
            return defaultValue;
        }
        return this.env[key] !== undefined ? this.env[key] : defaultValue;
    }

    /**
     * Get all environment variables
     */
    getAll() {
        return this.env;
    }

    /**
     * Check if debug mode is enabled
     */
    isDebug() {
        return this.get('DEBUG_MODE', false);
    }

    /**
     * Check if in development mode
     */
    isDevelopment() {
        return this.get('NODE_ENV', 'development') === 'development';
    }

    /**
     * Check if in production mode
     */
    isProduction() {
        return this.get('NODE_ENV', 'development') === 'production';
    }

    /**
     * Get API base URL
     */
    getApiBaseUrl() {
        return this.get('API_BASE_URL', 'http://localhost:8000');
    }

    /**
     * Get PWA base URL
     */
    getPwaBaseUrl() {
        return this.get('PWA_BASE_URL', window.location.origin);
    }

    /**
     * Get feature flag
     */
    getFeature(featureName, defaultValue = false) {
        const features = this.get('FEATURES', {});
        return features[featureName] !== undefined ? features[featureName] : defaultValue;
    }

    /**
     * Check if feature is enabled
     */
    isFeatureEnabled(featureName) {
        return this.getFeature(featureName, false);
    }

    /**
     * Get app name
     */
    getAppName() {
        return this.get('APP_NAME', 'RefereeX');
    }

    /**
     * Get app short name
     */
    getAppShortName() {
        return this.get('APP_SHORT_NAME', 'RefereeX');
    }

    /**
     * Get version
     */
    getVersion() {
        return this.get('VERSION', 'v1.0.0');
    }

    /**
     * Get build time
     */
    getBuildTime() {
        return this.get('BUILD_TIME', new Date().toISOString());
    }

    /**
     * Log environment info (only in debug mode)
     */
    logInfo() {
        if (this.isDebug()) {
            console.log('🌍 Client Environment Info:');
            console.log(`  App: ${this.getAppName()} (${this.getVersion()})`);
            console.log(`  Environment: ${this.get('NODE_ENV', 'development')}`);
            console.log(`  Debug Mode: ${this.isDebug()}`);
            console.log(`  API Base URL: ${this.getApiBaseUrl()}`);
            console.log(`  PWA Base URL: ${this.getPwaBaseUrl()}`);
            console.log(`  Build Time: ${this.getBuildTime()}`);
            console.log(`  Features:`, this.get('FEATURES', {}));
        }
    }

    /**
     * Wait for environment to be ready
     */
    async waitForReady() {
        while (!this.ready) {
            await new Promise(resolve => setTimeout(resolve, 10));
        }
        return this.env;
    }

    /**
     * Reload environment
     */
    async reload() {
        this.ready = false;
        await this.init();
        return this.env;
    }
}

// Create global instance
window.ClientEnvUtils = ClientEnvUtils;

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.clientEnv = new ClientEnvUtils();
        // Log environment info after a short delay to ensure everything is loaded
        setTimeout(() => {
            window.clientEnv.logInfo();
        }, 100);
    });
} else {
    // DOM already ready
    window.clientEnv = new ClientEnvUtils();
    setTimeout(() => {
        window.clientEnv.logInfo();
    }, 100);
}

// Export for ES6 modules
export default ClientEnvUtils;
export { ClientEnvUtils };
