/**
 * ClientIdentifierService - Manages unique client identification for the RefPortal PWA
 * Provides hardware-level stable identifiers and client property management
 */

export class ClientIdentifierService {
    constructor() {
        this.clientIdentifier = null;
        this.sessionIdentifier = null;
        this.isInitialized = false;
    }

    generateUUID() {
        // Check if crypto.randomUUID is available (modern browsers)
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        
        // Fallback for older browsers
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    static getInstance() {
        if (!ClientIdentifierService.instance) {
            ClientIdentifierService.instance = new ClientIdentifierService();
        }
        return ClientIdentifierService.instance;
    }

    getClientIdentifierFromStorage() {
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

    async generateClientIdentifier() {
        if (this.clientIdentifier) return this.clientIdentifier;
        
        let clientIdentifier;
        let clientProperties;
        
        if (false) {
            const identifier = {
                // Only HARDWARE-LEVEL stable identifiers
                hardwareFingerprint: await this.generateHardwareFingerprint(),
                platform: this.detectPlatform(),

                // Network information
                network: await this.getNetworkInfo(),

                // Timestamp for uniqueness (but won't affect the hash)
                timestamp: Date.now(),
                
                // Combined unique hash (only hardware-level stable)
                uniqueId: null
            };

            // Generate hash using ONLY hardware-level stable parameters
            identifier.uniqueId = this.hashIdentifiers(
                identifier.hardwareFingerprint,
                identifier.platform
            );

            clientIdentifier = identifier.uniqueId;
        } else {
            // This works the same on mobile and desktop
            clientIdentifier = this.getClientIdentifierFromStorage();
            if (!clientIdentifier && 'localStorage' in window) {
                clientIdentifier = this.generateUUID();
                clientProperties = {
                    clientIdentifier: clientIdentifier
                };
                // Store referee preferences
                localStorage.setItem('clientProperties', JSON.stringify(clientProperties));
            }
        }

        this.isInitialized = true;
        this.clientIdentifier = clientIdentifier;
        return clientIdentifier;
    }

    getSessionIdentifierFromStorage() {
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

    async generateSessionIdentifier(generateNewId = false) {
        if (this.sessionIdentifier && !generateNewId) return this.sessionIdentifier;
        
        let sessionIdentifier;
        let sessionProperties;
        
        // This works the same on mobile and desktop
        sessionIdentifier = this.getSessionIdentifierFromStorage();
        if ((!sessionIdentifier || generateNewId) && 'localStorage' in window) {
            sessionIdentifier = this.generateUUID();
            sessionProperties = {
                sessionIdentifier: sessionIdentifier
            };
            // Store referee preferences
            localStorage.setItem('sessionProperties', JSON.stringify(sessionProperties));
        }

        this.isInitialized = true;
        this.sessionIdentifier = sessionIdentifier;
        return sessionIdentifier;
    }

    async getNetworkInfo() {
        try {
            const networkInfo = {};
            
            // Get public IP (optional - privacy consideration)
            try {
                const ipResponse = await fetch('https://api.ipify.org?format=json', {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' }
                });
                if (ipResponse.ok) {
                    const { ip } = await ipResponse.json();
                    networkInfo.publicIP = ip;
                }
            } catch (error) {
                console.warn('Could not fetch public IP:', error);
            }

            // Get connection information if available
            if ('connection' in navigator) {
                const connection = navigator.connection;
                networkInfo.connectionType = connection.type;
                networkInfo.effectiveType = connection.effectiveType;
                networkInfo.downlink = connection.downlink;
                networkInfo.rtt = connection.rtt;
                networkInfo.saveData = connection.saveData;
            }

            // Get local IP if possible (WebRTC trick)
            try {
                const localIP = await this.getLocalIP();
                if (localIP) networkInfo.localIP = localIP;
            } catch (error) {
                // Local IP detection failed
            }

            return networkInfo;
        } catch (error) {
            console.warn('Network info collection failed:', error);
            return {};
        }
    }

    async getLocalIP() {
        return new Promise((resolve) => {
            try {
                const RTCPeerConnection = window.RTCPeerConnection || 
                                        window.webkitRTCPeerConnection || 
                                        window.mozRTCPeerConnection;
                
                if (!RTCPeerConnection) {
                    resolve(null);
                    return;
                }

                const pc = new RTCPeerConnection({ iceServers: [] });
                const noop = () => {};
                
                pc.createDataChannel('');
                pc.createOffer(pc.setLocalDescription.bind(pc), noop);
                
                pc.onicecandidate = (ice) => {
                    if (!ice || !ice.candidate) {
                        pc.close();
                        resolve(null);
                        return;
                    }
                    
                    const match = ice.candidate.candidate.match(/([0-9]{1,3}(\.[0-9]{1,3}){3})/);
                    if (match) {
                        pc.close();
                        resolve(match[1]);
                    }
                };
                
                setTimeout(() => {
                    pc.close();
                    resolve(null);
                }, 1000);
            } catch (error) {
                resolve(null);
            }
        });
    }

    async generateHardwareFingerprint() {
        try {
            // Only characteristics that are hardware-level stable
            const hardwareCharacteristics = [
                // Operating system level
                navigator.platform,
                navigator.vendor,
                
                // Hardware capabilities
                navigator.hardwareConcurrency,
                navigator.deviceMemory,
                navigator.maxTouchPoints,
                
                // Physical screen characteristics
                screen.width + 'x' + screen.height,
                screen.colorDepth,
                screen.pixelDepth,
                
                // Graphics capabilities (hardware-level)
                this.getGraphicsFingerprint(),
                
                // Audio capabilities (hardware-level)
                this.getAudioFingerprint()
            ].join('|');
            
            return this.hashString(hardwareCharacteristics);
        } catch (error) {
            console.warn('Hardware fingerprint generation failed:', error);
            // Fallback to basic hardware characteristics
            return this.hashString(
                navigator.platform + 
                navigator.hardwareConcurrency + 
                screen.width + 
                screen.height
            );
        }
    }

    getGraphicsFingerprint() {
        try {
            const canvas = document.createElement('canvas');
            const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
            if (!gl) return 'webgl_not_supported';
            
            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            if (debugInfo) {
                const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
                const vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
                return `${vendor}|${renderer}`;
            }
            return 'webgl_no_debug_info';
        } catch (error) {
            return 'webgl_error';
        }
    }

    getAudioFingerprint() {
        try {
            // Audio context fingerprint (hardware-level)
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const analyser = audioContext.createAnalyser();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(analyser);
            analyser.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            const fingerprint = [
                audioContext.sampleRate,
                audioContext.maxChannelCount,
                audioContext.destination.maxChannelCount
            ].join('|');
            
            // Clean up
            oscillator.disconnect();
            analyser.disconnect();
            gainNode.disconnect();
            
            return fingerprint;
        } catch (error) {
            return 'audio_error';
        }
    }

    detectPlatform() {
        const userAgent = navigator.userAgent.toLowerCase();
        
        if (/android/.test(userAgent)) return 'android';
        if (/iphone|ipad|ipod/.test(userAgent)) return 'ios';
        if (/windows/.test(userAgent)) return 'windows';
        if (/macintosh|mac os x/.test(userAgent)) return 'macos';
        if (/linux/.test(userAgent)) return 'linux';
        
        return 'web';
    }

    hashIdentifiers(...values) {
        const stableValues = values.filter(value => value && value !== '');
        const combined = stableValues.join('|');
        return this.hashString(combined);
    }

    hashString(str) {
        let hash = 0;
        if (str.length === 0) return hash.toString(36);
        
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        
        return Math.abs(hash).toString(36);
    }

    async getClientIdentifier() {
        if (!this.isInitialized) {
            return await this.generateClientIdentifier();
        }
        return this.clientIdentifier;
    }

    reset() {
        this.clientIdentifier = null;
        this.isInitialized = false;
    }
}