/**
 * Environment Loader for Client-Side JavaScript
 * Dynamically loads environment variables from server
 */

class EnvironmentLoader {
    constructor() {
        this.env = null;
        this.loading = false;
        this.loaded = false;
        this.error = null;
        this.listeners = [];
    }

    /**
     * Load environment variables from server
     * @param {boolean} forceReload - Force reload even if already loaded
     * @returns {Promise<Object>} Environment configuration
     */
    async load(forceReload = false) {
        if (this.loading) {
            return this.waitForLoad();
        }

        if (this.loaded && !forceReload) {
            return this.env;
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
                return this.env;
            } catch (apiError) {
                console.warn('⚠️ Failed to load from API, trying static file:', apiError.message);
            }

            // Fallback to static file if API fails
            if (!forceReload) {
                try {
                    await this.loadFromStaticFile();
                    this.loaded = true;
                    this.loading = false;
                    this.notifyListeners();
                    return this.env;
                } catch (staticError) {
                    console.warn('⚠️ Failed to load from static file:', staticError.message);
                }
            }

        } catch (error) {
            this.error = error;
            this.loading = false;
            console.error('❌ Failed to load environment:', error);
            
            // Fallback to default environment
            this.env = this.getDefaultEnvironment();
            this.loaded = true;
            this.notifyListeners();
            return this.env;
        }
    }

    /**
     * Load environment from static client-env.js file
     */
    async loadFromStaticFile() {
        return new Promise((resolve, reject) => {
            // Check if CLIENT_ENV is already available
            if (window.CLIENT_ENV) {
                this.env = window.CLIENT_ENV;
                resolve(this.env);
                return;
            }

            // Try to load the static file
            const script = document.createElement('script');
            script.src = './client-env.js';
            script.onload = () => {
                if (window.CLIENT_ENV) {
                    this.env = window.CLIENT_ENV;
                    resolve(this.env);
                } else {
                    reject(new Error('CLIENT_ENV not found in static file'));
                }
            };
            script.onerror = () => {
                reject(new Error('Failed to load client-env.js'));
            };
            document.head.appendChild(script);
        });
    }

    /**
     * Load environment from API endpoint
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

        this.env = await response.json();
        return this.env;
    }

    /**
     * Wait for current loading to complete
     */
    async waitForLoad() {
        return new Promise((resolve, reject) => {
            const checkLoaded = () => {
                if (this.loaded) {
                    resolve(this.env);
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
     * Get default environment configuration
     */
    getDefaultEnvironment() {
        return {
            NODE_ENV: 'development',
            DEBUG_MODE: true,
            API_BASE_URL: 'http://localhost:8000',
            PWA_BASE_URL: window.location.origin,
            PWA_HTTP_PORT: 3000,
            PWA_HTTPS_PORT: 3443,
            WSS_BASE_URL: 'ws://localhost:8080',
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
     * Add listener for environment load events
     */
    addListener(callback) {
        this.listeners.push(callback);
        
        // If already loaded, call immediately
        if (this.loaded) {
            callback(this.env, null);
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
                callback(this.env, this.error);
            } catch (error) {
                console.error('Error in environment listener:', error);
            }
        });
    }

    /**
     * Get environment variable
     */
    get(key, defaultValue = null) {
        if (!this.env) {
            console.warn('Environment not loaded yet. Call load() first.');
            return defaultValue;
        }
        return this.env[key] !== undefined ? this.env[key] : defaultValue;
    }

    /**
     * Check if environment is loaded
     */
    isLoaded() {
        return this.loaded;
    }

    /**
     * Check if environment is loading
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
     * Get all environment variables
     */
    getAll() {
        return this.env;
    }

    /**
     * Reload environment
     */
    async reload() {
        return this.load(true);
    }
}

// Create singleton instance
const envLoader = new EnvironmentLoader();

// Create global instance
window.EnvironmentLoader = EnvironmentLoader;
window.envLoader = envLoader;

// Auto-load environment when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        envLoader.load().catch(error => {
            console.error('Failed to auto-load environment:', error);
        });
    });
} else {
    // DOM already ready
    envLoader.load().catch(error => {
        console.error('Failed to auto-load environment:', error);
    });
}

// Export for ES6 modules
export default EnvironmentLoader;
export { EnvironmentLoader, envLoader };
