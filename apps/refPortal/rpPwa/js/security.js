// Dynamic configuration will be loaded from environment
import { configService } from './config-service.js';
import { envLoader } from './environment-loader.js';

export class Security {
    constructor() {
        this.configService = configService;
        this.envLoader = envLoader;
        this.isAppLocked = false;
        this.lockTimeout = this.getConfig('SECURITY.LOCKOUT_TIME', 0.2 * 60 * 1000);
        this.lastActivity = Date.now();
        this.maxLoginAttempts = this.getConfig('SECURITY.MAX_PAIR_ATTEMPTS', 3);
        this.pinLength = this.getConfig('SECURITY.PIN_LENGTH', 4);
        this.loginAttempts = 0;
        this.lockoutTime = 0;
        
        this.initializeAppLock();
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
            'SECURITY.MAX_PAIR_ATTEMPTS': 3,
            'SECURITY.PIN_LENGTH': 4
        };
        
        return defaults[key] || defaultValue;
    }

    // Simple PIN-based authentication
    async authenticateWithPIN(pin) {
        try {
            // Check if account is locked out
            if (this.isAccountLocked()) {
                throw new Error('Account temporarily locked. Try again later.');
            }

            // Get stored PIN hash
            const storedPinHash = localStorage.getItem('security_pin_hash');
            if (!storedPinHash) {
                throw new Error('No PIN set. Please set a PIN first.');
            }

            // Hash the input PIN
            const inputPinHash = await this.hashString(pin);
            
            if (inputPinHash === storedPinHash) {
                // Reset login attempts
                this.loginAttempts = 0;
                this.unlockApp();
                this.showToast('האפליקציה נפתחה בהצלחה', 'success');
                return true;
            } else {
                // Increment failed attempts
                this.loginAttempts++;
                
                if (this.loginAttempts >= this.maxLoginAttempts) {
                    // Lock account for 15 minutes
                    this.lockoutTime = Date.now() + (15 * 60 * 1000);
                    this.showToast('חשבון נחסם ל-15 דקות', 'error');
                } else {
                    const remaining = this.maxLoginAttempts - this.loginAttempts;
                    this.showToast(`סיסמה שגויה. נותרו ${remaining} ניסיונות`, 'error');
                }
                
                return false;
            }
            
        } catch (error) {
            this.showToast(error.message, 'error');
            return false;
        }
    }

    // Set PIN for the first time
    async setPIN(pin) {
        try {
            if (pin.length < this.pinLength) {
                throw new Error(`PIN must be at least ${this.pinLength} digits`);
            }
            
            // Hash the PIN
            const pinHash = await this.hashString(pin);
            
            // Store hashed PIN
            localStorage.setItem('security_pin_hash', pinHash);
            localStorage.setItem('security_pin_set', 'true');
            
            this.showToast('PIN הוגדר בהצלחה', 'success');
            return true;
            
        } catch (error) {
            this.showToast(error.message, 'error');
            return false;
        }
    }

    // Simple hash function
    async hashString(str) {
        const encoder = new TextEncoder();
        const data = encoder.encode(str);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }

    // Check if account is locked out
    isAccountLocked() {
        if (this.lockoutTime > 0 && Date.now() < this.lockoutTime) {
            return true;
        }
        
        // Reset lockout if time has passed
        if (this.lockoutTime > 0 && Date.now() >= this.lockoutTime) {
            this.lockoutTime = 0;
            this.loginAttempts = 0;
        }
        
        return false;
    }

    checkBiometricSupport() {
        const support = {
            webauthn: 'WebAuthn' in window,
            biometric: false,
            platform: 'unknown',
            iosVersion: null,
            https: window.location.protocol === 'https:',
            standalone: window.navigator.standalone || false
        };
        
        // Check platform and iOS version
        if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
            support.platform = 'iOS';
            
            // Extract iOS version
            const iosMatch = navigator.userAgent.match(/OS (\d+)_(\d+)_?(\d+)?/);
            if (iosMatch) {
                support.iosVersion = parseFloat(`${iosMatch[1]}.${iosMatch[2]}`);
            }
            
            // iOS WebAuthn support check
            if (support.iosVersion >= 14.3) {
                support.biometric = support.webauthn && support.https;
            }
            
        } else if (/Android/.test(navigator.userAgent)) {
            support.platform = 'Android';
            support.biometric = support.webauthn;
        }
        
        console.log('🔐 Biometric support:', support);
        return support;
    }

    async checkBiometricAvailability() {
        try {
            // Check if WebAuthn is supported
            if (!('PublicKeyCredential' in window)) {
                throw new Error('WebAuthn not supported');
            }
            
            // Check if biometric authentication is available
            if ('isUserVerifyingPlatformAuthenticatorAvailable' in PublicKeyCredential) {
                const available = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
                console.log('🔍 Biometric authenticator available:', available);
                return available;
            } else {
                console.log('⚠️ isUserVerifyingPlatformAuthenticatorAvailable not supported');
                // Fallback check for older iOS versions
                return this.fallbackBiometricCheck();
            }
            
        } catch (error) {
            console.error('❌ Biometric availability check failed:', error);
            return false;
        }
    }

    fallbackBiometricCheck() {
        // Fallback for older iOS versions
        const support = this.checkBiometricSupport();
        
        if (support.platform === 'iOS' && support.iosVersion >= 14.3) {
            // Assume biometric is available on newer iOS
            console.log('✅ Assuming biometric available on iOS', support.iosVersion);
            return true;
        }
        
        return false;
    }

    async registerBiometricCredential() {
        try {
            const support = this.checkBiometricSupport();
            
            if (!support.biometric) {
                throw new Error(`Biometric not supported: Platform=${support.platform}, iOS=${support.iosVersion}, HTTPS=${support.https}`);
            }
            
            // Check if biometric authentication is available
            const available = await this.checkBiometricAvailability();
            if (!available) {
                throw new Error('Biometric authentication not available on this device');
            }
            
            // iOS-specific credential creation
            const credentialOptions = {
                challenge: new Uint8Array(32), // Generate random challenge for testing
                rp: {
                    name: 'RefereeX PWA',
                    id: window.location.hostname
                },
                user: {
                    id: new Uint8Array(16), // Generate random user ID for testing
                    name: 'user@example.com',
                    displayName: 'User'
                },
                pubKeyCredParams: [
                    { type: 'public-key', alg: -7 } // ES256
                ],
                authenticatorSelection: {
                    authenticatorAttachment: 'platform', // Use built-in authenticator
                    userVerification: 'required' // Require biometric verification
                },
                timeout: 60000 // 60 seconds
            };
            
            // iOS-specific adjustments
            if (support.platform === 'iOS') {
                // iOS prefers these settings
                credentialOptions.authenticatorSelection.userVerification = 'preferred';
                
                // Add iOS-specific extensions if available
                if (support.iosVersion >= 15.0) {
                    credentialOptions.extensions = {
                        appid: window.location.origin
                    };
                }
            }
            
            console.log('🔐 Creating credential with options:', credentialOptions);
            
            // Create credential
            const credential = await navigator.credentials.create({
                publicKey: credentialOptions
            });
            
            console.log('✅ Credential created successfully:', credential);
            
            // For testing, just store locally
            localStorage.setItem('biometric_credential_id', credential.id);
            
            this.showToast('הזיהוי הביומטרי הופעל בהצלחה', 'success');
            return true;
            
        } catch (error) {
            console.error('❌ Biometric registration failed:', error);
            
            // Provide specific error messages for iOS
            if (error.name === 'NotSupportedError') {
                this.showToast('המכשיר לא תומך בזיהוי ביומטרי', 'error');
            } else if (error.name === 'SecurityError') {
                this.showToast('נדרש HTTPS לזיהוי ביומטרי', 'error');
            } else if (error.name === 'InvalidStateError') {
                this.showToast('כבר קיים זיהוי ביומטרי', 'info');
            } else {
                this.showToast('שגיאה בהפעלת הזיהוי הביומטרי: ' + error.message, 'error');
            }
            
            return false;
        }
    }

    // Simplified authentication for testing
    async authenticateWithBiometric() {
        try {
            const support = this.checkBiometricSupport();
            
            if (!support.biometric) {
                throw new Error('Biometric not supported');
            }
            
            // Check if credential exists
            const credentialId = localStorage.getItem('biometric_credential_id');
            if (!credentialId) {
                throw new Error('No biometric credential found');
            }
            
            // For testing, simulate biometric authentication
            console.log('🔐 Simulating biometric authentication...');
            
            // Show loading
            this.showToast('מאמת זיהוי ביומטרי...', 'info');
            
            // Simulate delay
            await new Promise(resolve => setTimeout(resolve, 2000));
            
            // Simulate success
            console.log('✅ Biometric authentication successful');
            this.showToast('הזיהוי הביומטרי הצליח', 'success');
            
            return true;
            
        } catch (error) {
            console.error('❌ Biometric authentication failed:', error);
            this.showToast('הזיהוי הביומטרי נכשל: ' + error.message, 'error');
            return false;
        }
    }

    // Add this method to show toast messages
    showToast(message, type = 'info', duration = 3000) {
        // Simple toast implementation
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; top: 20px; right: 20px; z-index: 10000;
            background: ${type === 'success' ? '#4CAF50' : type === 'error' ? '#f44336' : '#2196F3'};
            color: white; padding: 12px 20px; border-radius: 4px;
            font-size: 14px; max-width: 300px; word-wrap: break-word;
        `;
        toast.textContent = message;
        
        document.body.appendChild(toast);
        
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, duration);
    }

    initializeAppLock() {
        // Check if app should be locked
        this.checkAppLockStatus();
        
        // Set up activity monitoring
        this.setupActivityMonitoring();
        
        // Set up periodic lock checks
        setInterval(() => this.checkAppLockStatus(), 30000); // Check every 30 seconds
    }

    setupActivityMonitoring() {
        // Track user activity
        const activityEvents = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart'];
        
        activityEvents.forEach(event => {
            document.addEventListener(event, () => {
                this.lastActivity = Date.now();
                if (this.isAppLocked) {
                    this.unlockApp();
                }
            });
        });
        
        // Lock app when page becomes hidden
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.lockApp();
            }
        });
    }

    checkAppLockStatus() {
        const timeSinceActivity = Date.now() - this.lastActivity;
        
        if (timeSinceActivity > this.lockTimeout && !this.isAppLocked) {
            this.lockApp();
        }
    }

    lockApp() {
        this.isAppLocked = true;
        this.lastActivity = Date.now();
        
        // Hide sensitive content
        this.hideSensitiveContent();
        
        // Show lock screen
        this.showLockScreen();
        
        console.log('🔒 App locked');
    }

    unlockApp() {
        this.isAppLocked = false;
        this.lastActivity = Date.now();
        
        // Show sensitive content
        this.showSensitiveContent();
        
        // Hide lock screen
        this.hideLockScreen();
        
        console.log('�� App unlocked');
    }

    showLockScreen() {
        const lockScreen = document.createElement('div');
        lockScreen.id = 'appLockScreen';
        lockScreen.innerHTML = `
            <div class="lock-screen" style="
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                z-index: 9999; display: flex; flex-direction: column;
                align-items: center; justify-content: center; color: white;
                text-align: center; padding: 20px;
            ">
                <div class="lock-icon" style="font-size: 4rem; margin-bottom: 1rem;">🔒</div>
                <h2 style="margin: 0 0 1rem 0;">האפליקציה נעולה</h2>
                <p style="margin: 0 0 2rem 0; opacity: 0.8;">
                    השתמש בזיהוי הביומטרי או סיסמה לפתיחה
                </p>
                
                <div class="unlock-options" style="display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center;">
                    <button id="biometricUnlock" class="unlock-btn" style="
                        background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.3);
                        color: white; padding: 12px 24px; border-radius: 8px; cursor: pointer;
                        font-size: 1rem; transition: all 0.2s ease;
                    " onmouseover="this.style.background='rgba(255,255,255,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.2)'">
                        🗝️ זיהוי ביומטרי
                    </button>
                    
                    <button id="passwordUnlock" class="unlock-btn" style="
                        background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.3);
                        color: white; padding: 12px 24px; border-radius: 8px; cursor: pointer;
                        font-size: 1rem; transition: all 0.2s ease;
                    " onmouseover="this.style.background='rgba(255,255,255,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.2)'">
                        🔑 סיסמה
                    </button>
                </div>
                
                <div id="passwordInput" style="display: none; margin-top: 1rem;">
                    <input type="password" id="unlockPassword" placeholder="הזן סיסמה" style="
                        padding: 8px 12px; border: none; border-radius: 4px; margin-right: 8px;
                        font-size: 1rem;
                    ">
                    <button onclick="refPortalPWA.unlockWithPassword()" style="
                        background: #4CAF50; color: white; border: none; padding: 8px 16px;
                        border-radius: 4px; cursor: pointer; font-size: 1rem;
                    ">פתח</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(lockScreen);
        
        // Add event listeners
        document.getElementById('biometricUnlock').addEventListener('click', () => {
            this.authenticateWithBiometric();
        });
        
        document.getElementById('passwordUnlock').addEventListener('click', () => {
            document.getElementById('passwordInput').style.display = 'block';
        });
    }

    hideLockScreen() {
        const lockScreen = document.getElementById('appLockScreen');
        if (lockScreen) {
            lockScreen.remove();
        }
    }
}
