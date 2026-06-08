// Dynamic configuration will be loaded from environment
import { configService } from './config-service.js';
import { envLoader } from './environment-loader.js';

// In your PWA, establish WebSocket connection
class JwtWebSocket {
    constructor() {
        this.configService = configService;
        this.envLoader = envLoader;
        this.ws = null;
        this.clientIdentifier = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.isConnecting = false;
        this.autoReconnect = true;
        this.connectionState = 'disconnected';
        this.heartbeatInterval = null;
        this.heartbeatTimeout = null;
        this.isOffline = false; // Track offline state
        
        // Setup online/offline event handlers
        this.setupNetworkHandling();
    }
    
    /**
     * Setup network online/offline event handling
     */
    setupNetworkHandling() {
        window.addEventListener('online', () => {
            console.log('🌐 Network is online - checking WebSocket connection');
            this.isOffline = false; // Mark as online
            
            // If WebSocket is disconnected and we should be connected, try to reconnect
            if (this.connectionState === 'disconnected' && this.clientIdentifier && this.autoReconnect) {
                console.log('🔄 Attempting to reconnect WebSocket after coming online');
                this.reconnectAttempts = 0; // Reset reconnection attempts
                // Small delay to ensure network is stable
                setTimeout(() => {
                    if (navigator.onLine && this.connectionState === 'disconnected') {
                        this.connect(this.clientIdentifier);
                    }
                }, 500);
            } else if (this.connectionState === 'connected') {
                console.log('✅ WebSocket already connected');
            }
        });
        
        window.addEventListener('offline', () => {
            console.log('📴 Network is offline - WebSocket will disconnect');
            // When going offline, proactively mark connection as potentially lost
            // The WebSocket will detect disconnection through heartbeat timeout or error events
            if (this.connectionState === 'connected') {
                console.log('⚠️ Network offline - WebSocket connection will be lost shortly');
                // Optionally: We could close it proactively, but letting heartbeat detect is also fine
                // The browser will close it anyway when network is truly gone
            }
            // Mark that we're aware of offline state - prevents unnecessary reconnection attempts
            this.isOffline = true;
        });
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
            'WSS_BASE_URL': 'pwa-dev.refereex.com:5003'
        };
        
        return defaults[key] || defaultValue;
    }
    
    async connect(clientIdentifier) {
        if (this.isConnecting || this.connectionState === 'connected') {
            console.log('WebSocket already connecting or connected');
            return;
        }
        
        this.clientIdentifier = clientIdentifier;
        this.connectionState = 'connecting';
        this.isConnecting = true;
        
        try {
            // Automatically detect protocol (ws:// for HTTP, wss:// for HTTPS)
            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const wssBaseUrl = this.getConfig('WSS_BASE_URL');
            const wsUrl = `${protocol}://${wssBaseUrl}/pwa/ws/jwt/${clientIdentifier}`;
            
            console.log(`🔌 Attempting to connect to: ${wsUrl}`);
            
            this.ws = new WebSocket(wsUrl);
            this.setupEventHandlers();
        } catch (ex) {
            console.error('Error creating WebSocket:', ex);
            this.handleConnectionError(ex);
        }
    }

    toast(message) {   
        return;                 
        if (window.refPortalPwa) {
            const refPortalPwa = window.refPortalPwa;
            refPortalPwa.showToast(message, 'info');
        }
    }

    setupEventHandlers() {
        this.ws.onopen = () => {
            console.log('🔌 WebSocket connected on client for JWT token');
            this.connectionState = 'connected';
            this.isConnecting = false;
            this.reconnectAttempts = 0;
            this.startHeartbeat();
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'jwt_token_pair') {
                    // Handle new token pair format (access + refresh tokens)
                    this.toast('GUY JWT token pair received via WebSocket ' + data.access_token);
                    this.handleJwtTokenPair(data.access_token, data.refresh_token, data.access_expires_in, data.refresh_expires_in);
                } else if (data.type === 'connection_established') {
                    console.log('WebSocket connection established:', data.message);
                } else if (data.type === 'pong') {
                    console.log('Received pong from server');
                    this.resetHeartbeatTimeout();
                }
            } catch (ex) {
                console.error('Error parsing WebSocket message:', ex);
            }
        };
        
        this.ws.onclose = (event) => {
            console.log('🔌 WebSocket disconnected on client', {
                code: event.code,
                reason: event.reason,
                wasClean: event.wasClean
            });
            
            this.connectionState = 'disconnected';
            this.isConnecting = false;
            this.stopHeartbeat();
            
            // Handle different close codes
            switch (event.code) {
                case 1000: // Normal closure
                    console.log('Normal WebSocket closure');
                    break;
                case 1006: // Abnormal closure (typically network disconnection)
                    console.log('Abnormal WebSocket closure - connection lost unexpectedly');
                    console.log('💡 This usually means network went offline or connection was lost');
                    // Only attempt reconnect if we're online and not marked as offline
                    if (this.autoReconnect && navigator.onLine && !this.isOffline) {
                        this.attemptReconnect();
                    } else {
                        if (!navigator.onLine || this.isOffline) {
                            console.log('📴 Device is offline - will reconnect when back online');
                        }
                    }
                    break;
                case 1015: // TLS handshake failure
                    console.log('TLS handshake failed - protocol mismatch');
                    break;
                default:
                    console.log(`WebSocket closed with code: ${event.code}`);
                    if (event.code !== 1000 && this.autoReconnect) {
                        this.attemptReconnect();
                    }
                    break;
            }
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            // Don't call handleConnectionError here to avoid infinite loops
            // Just log the error and let onclose handle reconnection
        };
    }
    
    startHeartbeat() {
        console.log('🫀 Starting heartbeat mechanism...');
        
        // Clear any existing heartbeat
        this.stopHeartbeat();
        
        // Send initial ping immediately
        this.sendPing();
        
        // Send ping every 15 seconds (reduced from 30 for better reliability)
        this.heartbeatInterval = setInterval(() => {
            console.log('🫀 Heartbeat tick - connection state:', this.connectionState);
            if (this.connectionState === 'connected' && this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.sendPing();
            } else {
                console.warn('⚠️ Cannot send ping - connection not ready:', {
                    connectionState: this.connectionState,
                    wsReadyState: this.ws ? this.ws.readyState : 'no_ws',
                    wsOpen: this.ws ? this.ws.readyState === WebSocket.OPEN : false
                });
            }
        }, 15000);
        
        // Set timeout for pong response
        this.resetHeartbeatTimeout();
        
        console.log('🫀 Heartbeat started successfully');
    }
    
    stopHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
        if (this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
            this.heartbeatTimeout = null;
        }
    }
    
    resetHeartbeatTimeout() {
        if (this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
        }
        
        // If no pong received within 20 seconds, consider connection dead (increased from 10)
        this.heartbeatTimeout = setTimeout(() => {
            console.warn('⏰ Heartbeat timeout - no pong received within 20 seconds');
            console.warn('⏰ Connection state:', this.connectionState);
            console.warn('⏰ WebSocket readyState:', this.ws ? this.ws.readyState : 'no_ws');
            
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                console.log('🔌 Closing WebSocket due to heartbeat timeout');
                this.ws.close(1000, 'Heartbeat timeout');
            } else {
                console.warn('⚠️ WebSocket not available for closing');
            }
        }, 20000); // Increased from 10 seconds to 20 seconds
        
        console.log('🫀 Heartbeat timeout reset - waiting for pong response');
    }
    
    handleJwtTokenPair(accessToken, refreshToken, expiresIn = 86400, refreshExpiresIn = 2592000) {
        this.toast('GUY JWT token pair received via WebSocket');

        console.log('🔐 JWT token pair received via WebSocket');
        console.log('📊 Token info:', { expiresIn, refreshExpiresIn });
        
        // Store both tokens using refresh token service
        if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
            window.refPortalPwa.refreshTokenService.storeTokens(accessToken, refreshToken, expiresIn, refreshExpiresIn);
            console.log('✅ Tokens stored via refresh token service');
        }
        
        if (window.refPortalPwa) {
            const refPortalPwa = window.refPortalPwa;
            const loginWindow = refPortalPwa.windowManager.closeWindow('loginWindow');

            // Try to update authentication state if refPortalPwa is available
            refPortalPwa.handleSuccessfulAuthentication();
            refPortalPwa.refreshSectionsVisibility();
            refPortalPwa.setAuthenticatedState(true);
            refPortalPwa.showToast('התחברת בהצלחה!', 'success');
            refPortalPwa.navigateToSection('dashboard');
        } else {
            console.log('refPortalPwa not available, JWT tokens stored in localStorage');
        }
    }

    sendPing() {
        try {
            if (!this.ws) {
                console.warn('⚠️ Cannot send ping: WebSocket instance is null');
                return false;
            }
            
            if (this.ws.readyState !== WebSocket.OPEN) {
                console.warn('⚠️ Cannot send ping: WebSocket not open (readyState:', this.ws.readyState, ')');
                return false;
            }
            
            if (this.connectionState !== 'connected') {
                console.warn('⚠️ Cannot send ping: Connection state is not connected (', this.connectionState, ')');
                return false;
            }
            
            const pingMessage = { type: 'ping', timestamp: Date.now() };
            console.log('🫀 Sending ping to server:', pingMessage);
            this.ws.send(JSON.stringify(pingMessage));
            
            // Reset heartbeat timeout after sending ping
            this.resetHeartbeatTimeout();
            return true;
            
        } catch (error) {
            console.error('❌ Error sending ping:', error);
            return false;
        }
    }

    sendLog(logType, log) {
        return false;
        try {
            if (!this.ws) {
                console.warn('⚠️ Cannot send log: WebSocket instance is null');
                return false;
            }
            
            if (this.ws.readyState !== WebSocket.OPEN) {
                console.warn('⚠️ Cannot send log: WebSocket not open (readyState:', this.ws.readyState, ')');
                return false;
            }
            
            if (this.connectionState !== 'connected') {
                console.warn('⚠️ Cannot send log: Connection state is not connected (', this.connectionState, ')');
                return false;
            }
            
            const logMessage = { type: 'log', logType: logType,log: log, timestamp: Date.now() };
            console.log('🫀 Sending log to server:', logMessage);
            this.ws.send(JSON.stringify(logMessage));
            
            return true;
            
        } catch (error) {
            console.error('❌ Error sending log:', error);
            return false;
        }
    }

    sendMessage(type, data = {}) {
        try {
            if (this.ws && this.connectionState === 'connected') {
                const message = { type, ...data };
                this.ws.send(JSON.stringify(message));
                return true;
            } else {
                console.warn('Cannot send message: WebSocket not connected');
                return false;
            }
        } catch (error) {
            console.error('Error sending WebSocket message:', error);
            return false;
        }
    }
    
    attemptReconnect() {
        // Don't attempt reconnect if offline or max attempts reached
        if (!this.autoReconnect || this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('Max reconnection attempts reached or auto-reconnect disabled');
            return;
        }
        
        // Don't attempt reconnect if device is offline
        if (!navigator.onLine || this.isOffline) {
            console.log('📴 Device is offline - skipping reconnection attempt');
            return;
        }
        
        this.reconnectAttempts++;
        this.connectionState = 'reconnecting';
        
        // Exponential backoff with max delay
        const delay = Math.min(
            this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxReconnectDelay
        );
        
        console.log(`🔄 Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms`);
        
        setTimeout(async () => {
            // Double-check we're still online and should reconnect
            if (this.autoReconnect && navigator.onLine && !this.isOffline) {
                await this.connect(this.clientIdentifier);
            } else {
                console.log('📴 Cancelled reconnect - device is offline');
                this.connectionState = 'disconnected';
            }
        }, delay);
    }
    
    handleConnectionError(error) {
        this.connectionState = 'disconnected';
        this.isConnecting = false;
        
        if (this.autoReconnect) {
            this.attemptReconnect();
        }
    }
    
    disconnect() {
        this.autoReconnect = false;
        this.connectionState = 'disconnected';
        this.stopHeartbeat();
        
        if (this.ws) {
            this.ws.close(1000, 'User initiated disconnect');
            this.ws = null;
        }
    }
    
    // Utility methods
    getConnectionState() {
        return this.connectionState;
    }
    
    isConnected() {
        return this.connectionState === 'connected';
    }
    
    setAutoReconnect(enabled) {
        this.autoReconnect = enabled;
    }
    
    // Debug method to manually test ping
    testPing() {
        console.log('🧪 Manual ping test initiated');
        console.log('🧪 Connection state:', this.connectionState);
        console.log('🧪 WebSocket readyState:', this.ws ? this.ws.readyState : 'no_ws');
        console.log('🧪 Is connecting:', this.isConnecting);
        
        if (this.connectionState === 'connected' && this.ws && this.ws.readyState === WebSocket.OPEN) {
            const success = this.sendPing();
            console.log('🧪 Ping test result:', success ? 'SUCCESS' : 'FAILED');
            return success;
        } else {
            console.warn('🧪 Cannot test ping - connection not ready');
            return false;
        }
    }
    
    // Get detailed connection status
    getConnectionStatus() {
        return {
            connectionState: this.connectionState,
            isConnecting: this.isConnecting,
            wsReadyState: this.ws ? this.ws.readyState : 'no_ws',
            wsOpen: this.ws ? this.ws.readyState === WebSocket.OPEN : false,
            clientIdentifier: this.clientIdentifier,
            reconnectAttempts: this.reconnectAttempts,
            heartbeatActive: !!this.heartbeatInterval,
            heartbeatTimeoutActive: !!this.heartbeatTimeout
        };
    }
    
    // Force heartbeat restart
    restartHeartbeat() {
        console.log('🔄 Restarting heartbeat mechanism...');
        this.stopHeartbeat();
        this.startHeartbeat();
    }
}

// Initialize WebSocket when client identifier is available
export const jwtWebSocket = new JwtWebSocket();