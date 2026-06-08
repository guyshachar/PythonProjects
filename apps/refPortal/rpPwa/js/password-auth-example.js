/**
 * Example: Secure Password Authentication from PWA
 * 
 * BEST PRACTICES FOR SENDING PASSWORDS:
 * 
 * 1. ✅ Always use HTTPS (enforced by server)
 * 2. ✅ Use POST request with JSON body (never GET or URL params)
 * 3. ✅ Send password in request body, not headers or URL
 * 4. ✅ Clear password from memory after use
 * 5. ✅ Don't store passwords in localStorage/sessionStorage
 * 6. ✅ Use secure token storage (httpOnly cookies preferred, or secure localStorage)
 * 7. ✅ Implement client-side validation (but don't trust it)
 * 8. ✅ Show generic error messages
 * 9. ✅ Implement rate limiting awareness on client
 */

export class SecurePasswordAuth {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.maxRetries = 3;
    }

    /**
     * Secure login method
     * 
     * @param {string} username - User's username
     * @param {string} password - User's password (will be cleared after use)
     * @returns {Promise<Object>} Login response with tokens
     */
    async login(username, password) {
        // Validate inputs client-side (but server will also validate)
        if (!username || !password) {
            throw new Error('Username and password are required');
        }

        if (password.length < 8) {
            throw new Error('Password must be at least 8 characters');
        }

        try {
            // ✅ Use POST request with JSON body
            const response = await fetch(`${this.apiBaseUrl}/auth/login`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    // Don't add password to headers!
                },
                // ✅ Send password in request body (encrypted by HTTPS)
                body: JSON.stringify({
                    username: username.trim(),
                    password: password  // Will be encrypted by HTTPS/TLS
                }),
                // ✅ Important: Don't include credentials in fetch options
                // credentials: 'include' is only needed if using cookies
            });

            // Clear password from memory as soon as possible
            password = null; // Help GC, though JS strings are immutable

            if (!response.ok) {
                const errorData = await response.json();
                
                // Handle rate limiting
                if (response.status === 429) {
                    throw new Error('Too many login attempts. Please wait before trying again.');
                }
                
                // Generic error message (server should not reveal if username exists)
                throw new Error(errorData.detail || 'Invalid username or password');
            }

            const data = await response.json();
            
            // ✅ Store tokens securely
            this.storeTokensSecurely(data);
            
            return data;
            
        } catch (error) {
            // Clear password on error too
            password = null;
            
            // Don't log passwords in error messages
            console.error('Login error:', error.message);
            throw error;
        }
    }

    /**
     * Store authentication tokens securely
     * 
     * Options (in order of security):
     * 1. httpOnly cookies (most secure, set by server)
     * 2. Secure localStorage with encryption
     * 3. sessionStorage (cleared on tab close)
     */
    storeTokensSecurely(authData) {
        // Option 1: If server sets httpOnly cookies, no client-side storage needed
        // (Most secure - tokens not accessible to JavaScript)
        
        // Option 2: Store in localStorage (less secure, but common for PWAs)
        // Only store tokens, NEVER store passwords
        if (authData.access_token) {
            localStorage.setItem('access_token', authData.access_token);
        }
        if (authData.refresh_token) {
            localStorage.setItem('refresh_token', authData.refresh_token);
        }
        
        // Option 3: For sensitive apps, consider encrypting tokens before storage
        // const encryptedToken = this.encrypt(authData.access_token);
        // localStorage.setItem('access_token_encrypted', encryptedToken);
    }

    /**
     * Clear stored tokens (logout)
     */
    logout() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        // Clear any other auth-related data
    }

    /**
     * Get stored access token
     */
    getAccessToken() {
        return localStorage.getItem('access_token');
    }

    /**
     * Make authenticated API request
     */
    async makeAuthenticatedRequest(url, options = {}) {
        const token = this.getAccessToken();
        
        if (!token) {
            throw new Error('Not authenticated');
        }

        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
            ...options.headers
        };

        const response = await fetch(url, {
            ...options,
            headers
        });

        // Handle token expiration
        if (response.status === 401) {
            // Try to refresh token
            const refreshed = await this.refreshToken();
            if (refreshed) {
                // Retry original request
                return this.makeAuthenticatedRequest(url, options);
            }
            // Refresh failed, redirect to login
            this.logout();
            throw new Error('Session expired. Please login again.');
        }

        return response;
    }

    /**
     * Refresh access token using refresh token
     */
    async refreshToken() {
        const refreshToken = localStorage.getItem('refresh_token');
        
        if (!refreshToken) {
            return false;
        }

        try {
            const response = await fetch(`${this.apiBaseUrl}/auth/refresh`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    refresh_token: refreshToken
                })
            });

            if (response.ok) {
                const data = await response.json();
                this.storeTokensSecurely(data);
                return true;
            }
            
            return false;
        } catch (error) {
            console.error('Token refresh failed:', error);
            return false;
        }
    }
}

// Usage example:
/*
const auth = new SecurePasswordAuth('https://api.example.com');

// Login
try {
    const result = await auth.login('username', 'password');
    console.log('Login successful:', result);
} catch (error) {
    console.error('Login failed:', error.message);
}

// Make authenticated request
try {
    const response = await auth.makeAuthenticatedRequest('/api/user/profile');
    const data = await response.json();
    console.log('User profile:', data);
} catch (error) {
    console.error('Request failed:', error.message);
}
*/

