/**
 * Refresh Token Service for RefereeX PWA
 * 
 * This service handles automatic token refresh, token storage, and token management.
 * It works with the enhanced JWT middleware that supports refresh tokens.
 */
// Dynamic configuration will be loaded from environment
import { configService } from './config-service.js';
import { envLoader } from './environment-loader.js';

class RefreshTokenService {
    constructor() {
        this.configService = configService;
        this.envLoader = envLoader;
        this.accessToken = null;
        this.refreshToken = null;
        this.accessTokenExpiry = null;
        this.refreshTokenExpiry = null;
        this.isRefreshing = false;
        this.refreshPromise = null;

        // Load tokens from storage on initialization (async, but don't await)
        this.loadTokensFromStorage().catch(err => {
            console.error('Error loading tokens on initialization:', err);
        });
        
        // Set up automatic token refresh
        this.setupAutoRefresh();
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
            'API_BASE_URL': 'https://pwa-dev.refereex.com:5003',
            'ENDPOINTS.AUTH_REFRESH_TOKEN': '/auth/refresh',
            'ENDPOINTS.AUTH_VALIDATE_TOKEN': '/auth/validate',
            'ENDPOINTS.DOWNLOADICSFILE': '/api/pwa/downloadIcsFile',
        };
        
        return defaults[key] || defaultValue;
    }

    /**
     * Initialize the refresh token service
     * Called after configuration is loaded to perform any additional setup
     */
    async initialize() {
        try {
            console.log('🔧 Initializing RefreshTokenService...');
            
            // Validate existing tokens if any
            if (this.accessToken && this.refreshToken) {
                console.log('🔍 Validating existing tokens...');
                const validation = await this.validateTokens();
                
                if (!validation.valid) {
                    console.log('⚠️ Existing tokens are invalid, clearing them');
                    this.clearTokens();
                } else {
                    console.log('✅ Existing tokens are valid');
                }
            }
            
            // Set up event listeners for token refresh events
            this._setupEventListeners();
            
            console.log('✅ RefreshTokenService initialized successfully');
        } catch (error) {
            console.error('❌ Failed to initialize RefreshTokenService:', error);
            // Don't throw the error to prevent app startup failure
        }
    }

    /**
     * Set up event listeners for token-related events
     */
    _setupEventListeners() {
        // Listen for token refresh events from other parts of the app
        document.addEventListener('tokensRefreshed', (event) => {
            console.log('🔄 Tokens refreshed event received:', event.detail);
        });

        // Listen for unpair events
        document.addEventListener('userUnpaired', () => {
            console.log('🚪 User unpaired event received, clearing tokens');
            this.clearTokens();
        });
    }

    /**
     * Get current app version from service worker
     */
    async getCurrentVersion() {
        try {
            const swResponse = await fetch('/js/refportal-sw.js?_t=' + Date.now(), { cache: 'no-cache' });
            if (swResponse.ok) {
                const swContent = await swResponse.text();
                const versionMatch = swContent.match(/const CACHE_VERSION = ['"`]([^'"`]+)['"`]/);
                if (versionMatch) {
                    return versionMatch[1];
                }
            }
        } catch (error) {
            console.warn('⚠️ Could not fetch service worker version:', error);
        }
        return null;
    }

    /**
     * Store tokens in localStorage
     */
    async storeTokens(accessToken, refreshToken, accessExpiresIn = 86400, refreshExpiresIn = 2592000) {
        this.accessToken = accessToken;
        this.refreshToken = refreshToken;
        
        // Calculate expiry times
        const now = Date.now();
        this.accessTokenExpiry = now + (accessExpiresIn * 1000);
        this.refreshTokenExpiry = now + (refreshExpiresIn * 1000);
        
        // Get current app version and store it with tokens
        const currentVersion = await this.getCurrentVersion();
        
        // Store in localStorage
        localStorage.setItem('access_token', accessToken);
        localStorage.setItem('refresh_token', refreshToken);
        localStorage.setItem('access_token_expiry', this.accessTokenExpiry.toString());
        localStorage.setItem('refresh_token_expiry', this.refreshTokenExpiry.toString());
        if (currentVersion) {
            localStorage.setItem('token_version', currentVersion);
        }
        
        console.log('🔐 Tokens stored successfully', currentVersion ? `(version: ${currentVersion})` : '');
    }

    /**
     * Load tokens from localStorage
     */
    async loadTokensFromStorage() {
        try {
            this.accessToken = localStorage.getItem('access_token');
            this.refreshToken = localStorage.getItem('refresh_token');
            
            const tokenExpiry = localStorage.getItem('access_token_expiry');
            const refreshExpiry = localStorage.getItem('refresh_token_expiry');
            
            if (tokenExpiry) this.accessTokenExpiry = parseInt(tokenExpiry);
            if (refreshExpiry) this.refreshTokenExpiry = parseInt(refreshExpiry);
            
            console.log('🔐 Tokens loaded from storage');
        } catch (error) {
            console.error('❌ Error loading tokens from storage:', error);
        }
    }

    /**
     * Clear all stored tokens
     */
    clearTokens() {
        this.accessToken = null;
        this.refreshToken = null;
        this.accessTokenExpiry = null;
        this.refreshTokenExpiry = null;
        
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('access_token_expiry');
        localStorage.removeItem('refresh_token_expiry');
        localStorage.removeItem('token_version');
        
        console.log('🔐 Tokens cleared');
    }

    /**
     * Check if access token is expired
     */
    isAccessTokenExpired() {
        if (!this.accessTokenExpiry) return true;
        return Date.now() >= this.accessTokenExpiry;
    }

    /**
     * Check if refresh token is expired
     */
    isRefreshTokenExpired() {
        if (!this.refreshTokenExpiry) return true;
        return Date.now() >= this.refreshTokenExpiry;
    }

    /**
     * Check if access token will expire soon (within 5 minutes)
     */
    isAccessTokenExpiringSoon() {
        if (!this.accessTokenExpiry) return true;
        const fiveMinutes = 5 * 60 * 1000;
        const timeToExpiry = this.accessTokenExpiry - Date.now();
        console.log('🔍 Time to expiry:', timeToExpiry);
        return timeToExpiry <= fiveMinutes;
    }

    /**
     * Check if refresh token will expire soon (within 1 hour)
     */
    isRefreshTokenExpiringSoon() {
        if (!this.refreshTokenExpiry) return true;
        const oneHour = 60 * 60 * 1000;
        return (this.refreshTokenExpiry - Date.now()) <= oneHour;
    }

    /**
     * Get current access token, refreshing if necessary
     */
    async getAccessToken() {
        // If no tokens, return null
        if (!this.accessToken || !this.refreshToken) {
            return null;
        }

        // If access token is expired or expiring soon, refresh it
        if (this.isAccessTokenExpired() || this.isAccessTokenExpiringSoon()) {
            try {
                await this.refreshTokens();
            } catch (error) {
                console.error('❌ Failed to refresh tokens:', error);
                this.clearTokens();
                return null;
            }
        }

        return this.accessToken;
    }

    async getRefreshToken() {
        // If no tokens, return null
        if (!this.accessToken || !this.refreshToken) {
            return null;
        }

        // If refresh token is expired or expiring soon, refresh it
        if (this.isRefreshTokenExpired() || this.isRefreshTokenExpiringSoon()) {
            try {
                await this.refreshTokens();
            } catch (error) {
                console.error('❌ Failed to refresh tokens:', error);
                this.clearTokens();
                return null;
            }
        }

        return this.refreshToken;
    }

    /**
     * Refresh tokens using the refresh token
     */
    async refreshTokens() {
        // Prevent multiple simultaneous refresh attempts
        if (this.isRefreshing) {
            return this.refreshPromise;
        }

        this.isRefreshing = true;
        this.refreshPromise = this._performTokenRefresh();
        
        try {
            const result = await this.refreshPromise;
            return result;
        } finally {
            this.isRefreshing = false;
            this.refreshPromise = null;
        }
    }

    /**
     * Perform the actual token refresh
     */
    async _performTokenRefresh() {
        try {
            if (!this.refreshToken) {
                throw new Error('No refresh token available');
            }

            if (this.isRefreshTokenExpired()) {
                throw new Error('Refresh token has expired');
            }

            console.log('🔄 Refreshing tokens...');

            // Make request to refresh endpoint
            // Validate refresh token before sending request
            if (!this.refreshToken) {
                throw new Error('No refresh token available for refresh request');
            }
            
            const requestBody = {
                refresh_token: this.refreshToken
            };
            
            console.log('🔄 Sending refresh request:', {
                url: '/auth/refresh',
                body: requestBody,
                refreshToken: this.refreshToken ? 'Present' : 'Missing',
                bodyString: JSON.stringify(requestBody),
                refreshTokenLength: this.refreshToken ? this.refreshToken.length : 0
            });
            
            const requestOptions = {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Refresh-Token': this.refreshToken  // Send refresh token in header for middleware
                },
                body: JSON.stringify(requestBody)
            };
            
            console.log('🔄 Request options:', requestOptions);
            
            const response = await this.makeAuthenticatedRequest(this.getConfig('ENDPOINTS.AUTH_REFRESH_TOKEN'), requestOptions);
            
            // Debug response headers
            const headerCount = Array.from(response.headers.keys()).length;
            console.log('🔍 Response headers count:', headerCount);
            
            // Log all headers for debugging
            const allHeaders = {};
            response.headers.forEach((value, key) => {
                allHeaders[key] = value;
            });
            console.log('🔍 All response headers:', allHeaders);
            
            // Check for specific token refresh headers
            const tokenRefreshed = response.headers.get('X-Token-Refreshed');
            const newAccessToken = response.headers.get('X-New-Access-Token');
            const newRefreshToken = response.headers.get('X-New-Refresh-Token');
            
            console.log('🔍 Token refresh headers:', {
                tokenRefreshed,
                newAccessToken: newAccessToken ? 'Present' : 'Missing',
                newRefreshToken: newRefreshToken ? 'Present' : 'Missing'
            });

            if (!response.ok) {
                let errorMessage = 'Token refresh failed';
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorData.message || errorData.error || 'Token refresh failed';
                    console.error('❌ Refresh token error response:', errorData);
                } catch (parseError) {
                    console.error('❌ Could not parse error response:', parseError);
                }
                throw new Error(`HTTP ${response.status}: ${errorMessage}`);
            }

            const tokenData = await response.json();
            
            // Store new tokens (with version)
            await this.storeTokens(
                tokenData.access_token,
                tokenData.refresh_token,
                tokenData.expires_in,
                tokenData.refresh_expires_in
            );

            console.log('✅ Tokens refreshed successfully');
            return tokenData;

        } catch (error) {
            console.error('❌ Token refresh failed:', error);
            this.clearTokens();
            throw error;
        }
    }

    /**
     * Set up automatic token refresh
     */
    setupAutoRefresh() {
        // Check tokens every minute
        setInterval(() => {
            this._checkAndRefreshTokens();
        }, 60000);

        // Also check when the page becomes visible
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this._checkAndRefreshTokens();
            }
        });
    }

    /**
     * Check if tokens need refreshing and refresh if necessary
     */
    async _checkAndRefreshTokens() {
        try {
            if (this.isAccessTokenExpiringSoon() && !this.isRefreshing) {
                console.log('🔄 Access token expiring soon, refreshing...');
                await this.refreshTokens();
            }
        } catch (error) {
            console.error('❌ Auto-refresh failed:', error);
        }
    }

    /**
     * Handle response headers for automatic token refresh
     */
    async handleResponseHeaders(response) {
        const newAccessToken = response.headers.get('X-New-Access-Token');
        const newRefreshToken = response.headers.get('X-New-Refresh-Token');
        const tokenRefreshed = response.headers.get('X-Token-Refreshed');
        const tokenExpiresIn = response.headers.get('X-Access-Token-Expires-In');
        const refreshExpiresIn = response.headers.get('X-Refresh-Token-Expires-In');

        if (tokenRefreshed === 'true' && newAccessToken && newRefreshToken) {
            console.log('🔄 Tokens automatically refreshed by server');
            
            // Store new tokens (with version)
            await this.storeTokens(
                newAccessToken,
                newRefreshToken,
                parseInt(tokenExpiresIn) || 86400,
                parseInt(refreshExpiresIn) || 2592000
            );

            // Trigger event for other parts of the app
            this._triggerTokenRefreshEvent(newAccessToken, newRefreshToken);
        }
    }

    /**
     * Trigger custom event for token refresh
     */
    _triggerTokenRefreshEvent(accessToken, refreshToken) {
        const event = new CustomEvent('tokensRefreshed', {
            detail: {
                accessToken,
                refreshToken,
                timestamp: Date.now()
            }
        });
        document.dispatchEvent(event);
    }

    /**
     * Get authorization header for API requests
     */
    async getAuthorizationHeader() {
        const token = await this.getAccessToken();
        return token ? `Bearer ${token}` : null;
    }

    getClientIdentifier() {
        if ('localStorage' in window) {
            let clientPropertiesString = localStorage.getItem('clientProperties');
            if (clientPropertiesString) {
                const clientProperties = JSON.parse(clientPropertiesString);
                const clientIdentifier = clientProperties.clientIdentifier;
                return clientIdentifier;
            }
        }
        return null;
    }

    getSessionIdentifier() {
        if ('localStorage' in window) {
            let sessionPropertiesString = localStorage.getItem('sessionProperties');
            if (sessionPropertiesString) {
                const sessionProperties = JSON.parse(sessionPropertiesString);
                const sessionIdentifier = sessionProperties.sessionIdentifier;
                return sessionIdentifier;
            }
        }
        return null;
    }

    /** Offline cache: localStorage key prefix, max entries (FIFO eviction), TTL in ms */
    static get OFFLINE_CACHE_PREFIX() { return 'refportal_api_cache_'; }
    static get OFFLINE_CACHE_KEYS_KEY() { return 'refportal_api_cache_keys'; }
    static get OFFLINE_CACHE_MAX_ENTRIES() { return 200; }
    static get OFFLINE_CACHE_TTL_MS() { return 24 * 60 * 60 * 1000; } // 24 hours

    /** Normalize URL to path+search so full URL and path-only yield the same cache key */
    _normalizeUrlForCache(url) {
        if (!url || typeof url !== 'string') return '';
        try {
            if (url.startsWith('http://') || url.startsWith('https://')) {
                const u = new URL(url);
                return u.pathname + u.search;
            }
            return url;
        } catch {
            return url;
        }
    }

    _offlineCacheKey(method, finalUrl, body) {
        const urlForKey = this._normalizeUrlForCache(finalUrl);
        const bodyStr = body === undefined || body === null ? '' : (typeof body === 'string' ? body : JSON.stringify(body));
        const str = `${method || 'GET'}\n${urlForKey}\n${bodyStr}`;
        let h = 0;
        for (let i = 0; i < str.length; i++) {
            h = ((h << 5) - h) + str.charCodeAt(i) | 0;
        }
        return (h >>> 0).toString(36);
    }

    _getCachedResponse(cacheKey, opts = {}) {
        if (!('localStorage' in window)) {
            if (opts.forceOk) return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
            return null;
        }
        try {
            const raw = localStorage.getItem(RefreshTokenService.OFFLINE_CACHE_PREFIX + cacheKey);
            if (!raw) {
                if (opts.forceOk) return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
                return null;
            }
            const cached = JSON.parse(raw);
            const now = Date.now();
            if (cached.expiresAt != null && now > cached.expiresAt) {
                localStorage.removeItem(RefreshTokenService.OFFLINE_CACHE_PREFIX + cacheKey);
                if (opts.forceOk) return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
                return null;
            }
            const headers = new Headers(cached.headers || {});
            const status = opts.forceOk ? 200 : (cached.status ?? 200);
            return new Response(cached.body, { status, headers });
        } catch {
            if (opts.forceOk) return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
            return null;
        }
    }

    async _setCachedResponse(cacheKey, response) {
        if (!('localStorage' in window)) return;
        try {
            const body = await response.clone().text();
            const headers = {};
            response.headers.forEach((v, k) => { headers[k] = v; });
            const expiresAt = Date.now() + RefreshTokenService.OFFLINE_CACHE_TTL_MS;
            const entry = JSON.stringify({ status: response.status, headers, body, expiresAt });
            const key = RefreshTokenService.OFFLINE_CACHE_PREFIX + cacheKey;
            const keysKey = RefreshTokenService.OFFLINE_CACHE_KEYS_KEY;
            localStorage.setItem(key, entry);
            let keys = [];
            try {
                const keysStr = localStorage.getItem(keysKey);
                if (keysStr) keys = JSON.parse(keysStr);
            } catch { keys = []; }
            if (!keys.includes(cacheKey)) keys.push(cacheKey);
            while (keys.length > RefreshTokenService.OFFLINE_CACHE_MAX_ENTRIES) {
                const old = keys.shift();
                localStorage.removeItem(RefreshTokenService.OFFLINE_CACHE_PREFIX + old);
            }
            localStorage.setItem(keysKey, JSON.stringify(keys));
        } catch (e) {
            console.warn('Offline cache write failed:', e);
        }
    }

    _responseFromCache(cached) {
        const headers = new Headers(cached.headers || {});
        return new Response(cached.body, { status: cached.status ?? 200, headers });
    }

    /**
     * Make authenticated API request with automatic token refresh.
     * When offline (or network error), returns the last cached response for this request if available.
     */
    async makeApiRequest({url, options = {}, params = {}}) {
        // Build query string from params
        let finalUrl = url;
        if (Object.keys(params).length > 0) {
            const queryParams = new URLSearchParams();
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null && value !== '') {
                    queryParams.append(key, value);
                }
            });
            const queryString = queryParams.toString();
            if (queryString) {
                finalUrl = `${url}${url.includes('?') ? '&' : '?'}${queryString}`;
            }
        }

        const method = options.method || 'GET';
        const cacheKey = this._offlineCacheKey(method, finalUrl, options.body);

        const tryCache = () => {
            const forceOk = (method || '').toUpperCase() === 'POST';
            const response = this._getCachedResponse(cacheKey, { forceOk });
            if (response) {
                console.log('📦 Serving response from offline cache for', finalUrl);
                return response;
            }
            return null;
        };

        if (!navigator.onLine) {
            const cached = tryCache();
            if (cached) return cached;
            try {
                const keysStr = localStorage.getItem(RefreshTokenService.OFFLINE_CACHE_KEYS_KEY);
                const keyCount = keysStr ? JSON.parse(keysStr).length : 0;
                console.warn('Offline cache miss. Key=', cacheKey, 'normalizedUrl=', this._normalizeUrlForCache(finalUrl), 'cachedRequestsCount=', keyCount);
            } catch (_) {}
            throw new Error('Offline and no cached response for this request');
        }

        try {
            const mergedHeaders = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization',
                ...options.headers
            };
            const response = await this.makeAuthenticatedRequest(
                finalUrl,
                { ...options, headers: mergedHeaders }
            );

            await this._setCachedResponse(cacheKey, response);

            if (response.headers) {
                console.log('🔍 Response headers:', response.headers);
            }

            return response;
        } catch (error) {
            const cached = tryCache();
            if (cached) return cached;
            console.error('API request failed:', error);
            throw error;
        }
    }

    /**
     * Authenticated fetch for SSE/streaming endpoints (not cached as a single JSON body).
     */
    async makeAuthenticatedStreamRequest(url, options = {}) {
        const authHeader = await this.getAuthorizationHeader();
        const appVersion = await this.getCurrentVersion();
        const headers = {
            Accept: 'text/event-stream',
            ...options.headers,
        };
        const clientIdentifier = this.getClientIdentifier();
        const sessionIdentifier = this.getSessionIdentifier();
        if (clientIdentifier) headers['X-Client-Identifier'] = clientIdentifier;
        if (sessionIdentifier) headers['X-Session-Identifier'] = sessionIdentifier;
        if (appVersion) headers['X-App-Version'] = appVersion;
        if (authHeader) headers.Authorization = authHeader;
        const adminApplySelectedReferee = localStorage.getItem('adminApplyReferee');
        if (adminApplySelectedReferee) {
            headers['X-Admin-Apply-Selected-Referee'] = adminApplySelectedReferee;
        }
        return this.makeAuthenticatedRequest(url, {
            ...options,
            headers,
        });
    }

    async makeAuthenticatedRequest(url, options = {}) {
        let requestOptions;
        
        const authHeader = await this.getAuthorizationHeader();
        // Get current app version for header
        const appVersion = await this.getCurrentVersion();

        if (!options.headers) {
            options.headers = {};
        }
        const clientIdentifier = this.getClientIdentifier();
        const sessionIdentifier = this.getSessionIdentifier();
        if (clientIdentifier) {
            options.headers['X-Client-Identifier'] = clientIdentifier;
        }
        if (sessionIdentifier) {
            options.headers['X-Session-Identifier'] = sessionIdentifier;
        }

        // Add X-App-Version header if version is available
        if (appVersion) {
            options.headers['X-App-Version'] = appVersion;
        }

        options.headers['Authorization'] = authHeader;

        const adminApplySelectedReferee = localStorage.getItem('adminApplyReferee');
        if (adminApplySelectedReferee) {
            options.headers['X-Admin-Apply-Selected-Referee'] = adminApplySelectedReferee;
        }

        // Add authorization header and app version header
        requestOptions = {
            ...options,
            headers: {
                ...options.headers,
                'Authorization': authHeader
            }
        };
        
        let fullUrl = null;
        try {
            fullUrl = this.getApiUrl(url);
            // Convert URL object to string if needed
            const urlString = fullUrl instanceof URL ? fullUrl.toString() : fullUrl;
            console.log('🌐 Making request to:', urlString);
            console.log('📋 Request options:', requestOptions);
            const response = await fetch(urlString, requestOptions);
            console.log('✅ Fetch completed, status:', response.status);
            const headerCount = Array.from(response.headers.keys()).length;
            console.log('🔍 Response headers:', headerCount);
            // Handle automatic token refresh from response headers (async, don't await)
            this.handleResponseHeaders(response).catch(err => {
                console.error('Error handling response headers:', err);
            });
            
            return response;
        } catch (error) {
            console.error('❌ API request failed:', error);
            throw error;
        }
    }

    // Helper function to construct API URLs with proper encoding
    getApiUrl(endpoint) {
        // Validate endpoint
        if (!endpoint) {
            throw new Error('Endpoint is required but was null or undefined');
        }
        
        const apiBaseUrl = this.getConfig('API_BASE_URL');
        if (apiBaseUrl) {
            // Ensure the base URL ends with a slash if endpoint doesn't start with one
            const baseUrl = apiBaseUrl.endsWith('/') 
                ? apiBaseUrl 
                : apiBaseUrl + '/';
            
            // Remove leading slash from endpoint if it exists to avoid double slashes
            const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
            
            // Construct full URL; do not pre-encode query values here — URLSearchParams / URL.toString()
            // already percent-encode. Using encodeURIComponent + set() double-encodes (e.g. : → %253A),
            // which breaks ISO datetimes on the API.
            const fullUrl = baseUrl + cleanEndpoint;
            return new URL(fullUrl);
        }
        // Return encoded relative URL if no base URL
        const encodedUrl = this.encodeUrlQuery(endpoint)
        return encodedUrl;
    }

    encodeUrlQuery(invalidUrlString) {
        try {
            // 1. Parse the full URL string into a URL object.
            // This automatically decodes the query parameters.
            const url = new URL(invalidUrlString);
        
            // 2. Create a new URLSearchParams object to build the corrected query string.
            const newSearchParams = new URLSearchParams();
        
            // 3. Iterate over the decoded key-value pairs from the original URL.
            for (const [key, value] of url.searchParams.entries()) {
                // 4. Append each pair to the new search params.
                // The URLSearchParams object handles the encoding automatically.
                newSearchParams.append(key, value);
            }
        
            // 5. Rebuild the final URL.
            // The toString() method creates the correctly encoded query string.
            return `${url.origin}${url.pathname}?${newSearchParams.toString()}${url.hash}`;
        
        } catch (error) {
            console.error("Invalid URL provided:", error);
            return invalidUrlString; // Return the original string if it's not a valid URL
        }
    }    

    /**
     * Validate current tokens
     */
    async validateTokens() {
        try {
            const authHeader = await this.getAuthorizationHeader();
            
            if (!authHeader) {
                return { valid: false, reason: 'No tokens available' };
            }

            const response = await this.makeAuthenticatedRequest(this.getConfig('ENDPOINTS.AUTH_VALIDATE_TOKEN'), {
                method: 'POST',
            });

            if (response.ok) {
                const data = await response.json();
                return { valid: true, user: data.user };
            } else {
                const errorData = await response.json();
                return { valid: false, reason: errorData.message };
            }
        } catch (error) {
            console.error('❌ Token validation failed:', error);
            return { valid: false, reason: 'Validation request failed' };
        }
    }

    /**
     * Unpair and clear all tokens
     */
    async unpair() {
        try {
            // Call unpair endpoint
            const response = await this.makeAuthenticatedRequest(this.getConfig('ENDPOINTS.AUTH_UNPAIR'), { method: 'POST' });
        } catch (error) {
            console.warn('⚠️ Unpair endpoint call failed:', error);
        } finally {
            // Clear tokens regardless of endpoint response
            this.clearTokens();
            
            // Trigger unpair event
            const event = new CustomEvent('userUnpaired', {
                detail: { timestamp: Date.now() }
            });
            document.dispatchEvent(event);
        }
    }
}

// Create singleton instance
export const refreshTokenService = new RefreshTokenService();

// Export for use in other modules
export default refreshTokenService;
