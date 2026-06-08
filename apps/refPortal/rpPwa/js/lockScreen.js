// Dynamic configuration will be loaded from environment
import { configService } from './config-service.js';
import { envLoader } from './environment-loader.js';

export class LockScreen {
    constructor(appLock) {
        this.appLock = appLock;
        this.configService = configService;
        this.envLoader = envLoader;
        this.pinLength = this.getConfig('SECURITY.PIN_LENGTH', 4);
        
        this.isVisible = false;
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
            'SECURITY.PIN_LENGTH': 4
        };
        
        return defaults[key] || defaultValue;
    }

    show() {
        if (this.isVisible) return;
        
        const lockScreen = document.createElement('div');
        lockScreen.id = 'iosLockScreen';
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
                    הזן PIN לפתיחה
                </p>
                
                <div class="pin-input-container" style="margin-bottom: 2rem;">
                    <input type="password" id="pinInput" placeholder="הזן PIN" 
                           maxlength="6" style="
                        padding: 12px 16px; border: none; border-radius: 8px;
                        font-size: 1.2rem; text-align: center; width: 200px;
                        background: rgba(255,255,255,0.9); color: #333;
                    ">
                </div>
                
                <div class="unlock-options" style="display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center;">
                    <button id="unlockBtn" style="
                        background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.3);
                        color: white; padding: 12px 24px; border-radius: 8px; cursor: pointer;
                        font-size: 1rem; transition: all 0.2s ease;
                    ">
                        🔑 פתח
                    </button>
                    
                    <button id="settingsBtn" style="
                        background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.2);
                        color: white; padding: 12px 24px; border-radius: 8px; cursor: pointer;
                        font-size: 1rem; transition: all 0.2s ease;
                    ">
                        ⚙️ הגדרות
                    </button>
                </div>
                
                <div id="pinError" style="margin-top: 1rem; color: #ff6b6b; display: none;">
                    PIN שגוי
                </div>
            </div>
        `;
        
        document.body.appendChild(lockScreen);
        this.isVisible = true;
        
        // Set up event listeners
        this.setupEventListeners();
        
        // Focus on PIN input
        setTimeout(() => {
            document.getElementById('pinInput').focus();
        }, 100);
    }

    setupEventListeners() {
        const pinInput = document.getElementById('pinInput');
        const unlockBtn = document.getElementById('unlockBtn');
        const settingsBtn = document.getElementById('settingsBtn');
        
        // Handle Enter key on PIN input
        pinInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.authenticate();
            }
        });
        
        // Handle unlock button click
        unlockBtn.addEventListener('click', () => {
            this.authenticate();
        });
        
        // Handle settings button click
        settingsBtn.addEventListener('click', () => {
            this.showSecuritySettings();
        });
        
        // Add hover effects
        unlockBtn.addEventListener('mouseover', () => {
            unlockBtn.style.background = 'rgba(255,255,255,0.3)';
        });
        
        unlockBtn.addEventListener('mouseout', () => {
            unlockBtn.style.background = 'rgba(255,255,255,0.2)';
        });
        
        settingsBtn.addEventListener('mouseover', () => {
            settingsBtn.style.background = 'rgba(255,255,255,0.3)';
        });
        
        settingsBtn.addEventListener('mouseout', () => {
            settingsBtn.style.background = 'rgba(255,255,255,0.2)';
        });
    }

    async authenticate() {
        const pinInput = document.getElementById('pinInput');
        const pin = pinInput.value;
        
        if (!pin || pin.length < this.pinLength) {
            this.showError(`PIN חייב להיות בן ${this.pinLength} ספרות לפחות`);
            return;
        }
        
        try {
            // Verify PIN
            const result = await this.verifyPIN(pin);
            
            if (result.success) {
                // Clear PIN input
                pinInput.value = '';
                
                // Unlock the app
                this.appLock.unlockAfterAuthentication();
                
                // Show success message
                this.showSuccess(result.message);
                
            } else {
                // Show error
                this.showError(result.message);
                
                // Clear PIN input for security
                pinInput.value = '';
                pinInput.focus();
            }
            
        } catch (error) {
            console.error('Authentication error:', error);
            this.showError('שגיאה באימות');
            pinInput.value = '';
            pinInput.focus();
        }
    }

    async verifyPIN(pin) {
        try {
            // Simple PIN verification (you can enhance this)
            const storedPIN = localStorage.getItem('security_pin') || '1234'; // Default PIN for testing
            
            if (pin === storedPIN) {
                return { success: true, message: 'האפליקציה נפתחה בהצלחה' };
            } else {
                return { success: false, message: 'PIN שגוי' };
            }
        } catch (error) {
            console.error('PIN verification error:', error);
            return { success: false, message: 'שגיאה באימות PIN' };
        }
    }

    showSecuritySettings() {
        // Simple PIN change dialog
        const newPIN = prompt('הזן PIN חדש (לפחות 4 ספרות):');
        if (newPIN && newPIN.length >= this.pinLength) {
            localStorage.setItem('security_pin', newPIN);
            this.showSuccess('PIN שונה בהצלחה');
        } else if (newPIN !== null) {
            this.showError('PIN חייב להיות בן 4 ספרות לפחות');
        }
    }

    hide() {
        const lockScreen = document.getElementById('iosLockScreen');
        if (lockScreen) {
            lockScreen.remove();
            this.isVisible = false;
        }
    }

    showError(message) {
        const errorDiv = document.getElementById('pinError');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            
            setTimeout(() => {
                errorDiv.style.display = 'none';
            }, 3000);
        }
    }

    showSuccess(message) {
        // Show success message briefly
        this.showToast(message, 'success');
    }

    showToast(message, type = 'info', duration = 3000) {
        // Simple toast implementation
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; top: 20px; right: 20px; z-index: 10001;
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
}

