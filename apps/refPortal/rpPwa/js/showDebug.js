// Debug information functions for RefPortal PWA
// This file contains all debug-related functionality
import { JwtService } from './jwtService.js';

export class ShowDebug {
    constructor(refPortalPWA) {
        this.refPortalPWA = refPortalPWA;
        this.initializeEventListeners();
    }

    // Initialize all event listeners
    initializeEventListeners() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                this.setupEventListeners();
            });
        } else {
            this.setupEventListeners();
        }
    }

    setupEventListeners() {
        // Debug toggle button
        const debugToggle = document.querySelector('.debug-toggle');
        if (debugToggle) {
            debugToggle.addEventListener('click', async () => await this.toggleDebugInfo());
        }

        // Copy buttons
        const copyButtons = document.querySelectorAll('.debug-copy-btn');
        copyButtons.forEach(button => {
            const elementId = button.getAttribute('data-copy-id');
            if (elementId) {
                button.addEventListener('click', () => this.copyToClipboard(elementId));
            }
        });

        // Refresh buttons
        const refreshButtons = document.querySelectorAll('.debug-refresh-btn');
        refreshButtons.forEach(button => {
            const action = button.getAttribute('data-action');
            if (!!action) {
                if (action === 'refreshDebugInfo') {
                    button.addEventListener('click', async () => await this.refreshDebugInfo());
                } else if (action === 'updateJwtDebugInfo') {
                    button.addEventListener('click', async () => await this.updateJwtDebugInfo());
                }
            }
        });

        // Push notification test button
        const pushNotificationTest = document.querySelector('.push-notification-test');
        if (pushNotificationTest) {
            pushNotificationTest.addEventListener('click', () => this.testPushNotification());
        }

        // JWT action buttons
        const jwtButtons = document.querySelectorAll('[data-jwt-action]');
        jwtButtons.forEach(button => {
            const action = button.getAttribute('data-jwt-action');
            switch (action) {
                case 'displayInConsole':
                    button.addEventListener('click', () => this.displayJwtInConsole());
                    break;
                case 'copyFullToken':
                    button.addEventListener('click', () => this.copyFullJwtToken());
                    break;
                case 'testRefresh':
                    button.addEventListener('click', () => this.testJwtRefresh());
                    break;
            }
        });

        // WebSocket action buttons
        const wsButtons = document.querySelectorAll('[data-ws-action]');
        wsButtons.forEach(button => {
            const action = button.getAttribute('data-ws-action');
            switch (action) {
                case 'testPing':
                    button.addEventListener('click', () => this.testWebSocketPing());
                    break;
                case 'restartHeartbeat':
                    button.addEventListener('click', () => this.restartWebSocketHeartbeat());
                    break;
                case 'showStatus':
                    button.addEventListener('click', () => this.showWebSocketStatus());
                    break;
            }
        });

        // Action buttons
        const actionButtons = document.querySelectorAll('.action-btn');
        actionButtons.forEach(button => {
            const action = button.getAttribute('data-action');
            if (action) {
                button.addEventListener('click', () => this.handleActionButton(action));
            }
        });

        // Chat visibility buttons
        const chatVisibilityBtn = document.querySelector('[data-action="checkChatVisibility"]');
        if (chatVisibilityBtn) {
            chatVisibilityBtn.addEventListener('click', () => this.handleChatVisibilityAction('check'));
        }

        const chatRefreshBtn = document.querySelector('[data-action="refreshChatVisibility"]');
        if (chatRefreshBtn) {
            chatRefreshBtn.addEventListener('click', () => this.handleChatVisibilityAction('refresh'));
        }

        // Chat sync buttons
        const chatSyncButtons = document.querySelectorAll('.sync-btn');
        chatSyncButtons.forEach(button => {
            const action = button.getAttribute('data-sync-action');
            if (action) {
                button.addEventListener('click', () => this.handleChatSyncAction(action));
            }
        });

        // Close notification center button
        const closeNotificationBtn = document.querySelector('.close-notification-center');
        if (closeNotificationBtn) {
            closeNotificationBtn.addEventListener('click', () => this.closeNotificationCenter());
        }

        // File input for chat import
        const chatImportInput = document.getElementById('chatImport');
        if (chatImportInput) {
            chatImportInput.addEventListener('change', (event) => {
                if (event.target.files && event.target.files[0]) {
                    this.handleChatImport(event.target.files[0]);
                }
            });
        }

        console.log('✅ Event listeners initialized in ShowDebug class');
    }


    // Debug information functions
    async toggleDebugInfo() {
        const content = document.querySelector('.debug-content');
        const button = document.querySelector('.debug-toggle');
        if (content.style.display === 'none') {
            content.style.display = 'block';
            button.textContent = 'הסתר';
            await this.refreshDebugInfo();
        } else {
            content.style.display = 'none';
            button.textContent = 'הצג/הסתר';
        }
    }

    copyToClipboard(elementId) {
        const element = document.getElementById(elementId);
        const text = element.textContent;
        
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                this.showCopySuccess(elementId);
            }).catch(err => {
                console.error('Failed to copy: ', err);
                this.fallbackCopyTextToClipboard(text);
            });
        } else {
            this.fallbackCopyTextToClipboard(text);
        }
    }

    fallbackCopyTextToClipboard(text) {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        
        try {
            document.execCommand('copy');
            this.showCopySuccess();
        } catch (err) {
            console.error('Fallback copy failed: ', err);
        }
        
        document.body.removeChild(textArea);
    }

    showCopySuccess(elementId) {
        const element = document.getElementById(elementId);
        const originalText = element.textContent;
        element.textContent = '✅ הועתק!';
        element.style.color = '#10b981';
        
        setTimeout(() => {
            element.textContent = originalText;
            element.style.color = '';
        }, 1000);
    }

    testPushNotification() {
        if (this.refPortalPWA) {
            this.refPortalPWA.testPushNotification();
        } else {
            console.error('RefPortalPWA not available');
        }
    }

    async refreshDebugInfo() {
        // Update client identifier
        if (this.refPortalPWA) {
            this.refPortalPWA.getClientIdentifier().then(id => {
                document.getElementById('debugClientIdentifier').textContent = id || 'לא נמצא';
            }).catch(err => {
                document.getElementById('debugClientIdentifier').textContent = 'שגיאה: ' + err.message;
            });

            // Update push notification endpoint
            this.refPortalPWA.getCurrentPushSubscription().then(subscription => {
                if (subscription && subscription.endpoint) {
                    document.getElementById('debugPushEndpoint').textContent = subscription.endpoint;
                } else {
                    document.getElementById('debugPushEndpoint').textContent = 'לא נמצא';
                }
            }).catch(err => {
                document.getElementById('debugPushEndpoint').textContent = 'שגיאה: ' + err.message;
            });

            // Update service worker status
            this.refPortalPWA.checkServiceWorkerStatus().then(status => {
                const statusText = `${status.supported ? 'נתמך' : 'לא נתמך'}, ${status.registered ? 'רשום' : 'לא רשום'}, ${status.active ? 'פעיל' : 'לא פעיל'}`;
                document.getElementById('debugSWStatus').textContent = statusText;
                
                // Update service worker version
                const versionElement = document.getElementById('debugSWVersion');
                if (versionElement) {
                    versionElement.textContent = status.version || 'לא זמין';
                    versionElement.style.color = status.version && status.version !== 'Unknown' ? '#10b981' : '#f59e0b';
                }
            }).catch(err => {
                document.getElementById('debugSWStatus').textContent = 'שגיאה: ' + err.message;
                const versionElement = document.getElementById('debugSWVersion');
                if (versionElement) {
                    versionElement.textContent = 'שגיאה';
                    versionElement.style.color = '#ef4444';
                }
            });

            // Update PWA status
            const pwaStatus = this.refPortalPWA.getInstallPromptStatus();
            const pwaText = `${pwaStatus.canInstall ? 'ניתן להתקין' : 'לא ניתן להתקין'}, ${pwaStatus.hasPrompt ? 'יש הודעת התקנה' : 'אין הודעת התקנה'}`;
            document.getElementById('debugPWAStatus').textContent = pwaText;
        }

        // Update JWT token information
        await this.updateJwtDebugInfo();
        
        // Update WebSocket status
        this.updateWebSocketDebugInfo();

        // Update user agent
        document.getElementById('debugUserAgent').textContent = navigator.userAgent;

        // Update last updated timestamp
        document.getElementById('debugLastUpdated').textContent = new Date().toLocaleString('he-IL');
    }

    async updateJwtDebugInfo() {
        try {
            // Get JWT token from refresh token service first, fallback to localStorage
            let token = null;
            if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
                token = await window.refPortalPwa.refreshTokenService.getAccessToken();
            }

            if (!token) {
                // No token found
                document.getElementById('debugJwtStatus').textContent = '❌ לא נמצא טוקן';
                document.getElementById('debugJwtStatus').style.color = '#ef4444';
                document.getElementById('debugJwtUserName').textContent = 'לא זמין';
                document.getElementById('debugJwtMobile').textContent = 'לא זמין';
                document.getElementById('debugJwtUserRole').textContent = 'לא זמין';
                document.getElementById('debugJwtTokenAge').textContent = 'לא זמין';
                document.getElementById('debugJwtExpiresAt').textContent = 'לא זמין';
                document.getElementById('debugJwtIssuedAt').textContent = 'לא זמין';
                document.getElementById('debugJwtTokenRaw').textContent = 'לא זמין';
                return;
            }

            // Parse JWT token
            const payload = JwtService.parseJwtToken(token);
            
            if (!payload) {
                // Invalid token
                document.getElementById('debugJwtStatus').textContent = '❌ טוקן לא תקין';
                document.getElementById('debugJwtStatus').style.color = '#ef4444';
                document.getElementById('debugJwtUserName').textContent = 'לא זמין';
                document.getElementById('debugJwtMobile').textContent = 'לא זמין';
                document.getElementById('debugJwtUserRole').textContent = 'לא זמין';
                document.getElementById('debugJwtTokenAge').textContent = 'לא זמין';
                document.getElementById('debugJwtExpiresAt').textContent = 'לא זמין';
                document.getElementById('debugJwtIssuedAt').textContent = 'לא זמין';
                document.getElementById('debugJwtTokenRaw').textContent = token.substring(0, 50) + '...';
                return;
            }

            // Check if token is expired
            const isExpired = JwtService.isTokenExpired(token);
            const tokenAge = await JwtService.getTokenAge();
            const expiresAt = JwtService.getTokenExpirationTime(token);
            const issuedAt = payload.iat ? new Date(payload.iat * 1000) : null;

            // Update status
            if (isExpired) {
                document.getElementById('debugJwtStatus').textContent = '❌ פג תוקף';
                document.getElementById('debugJwtStatus').style.color = '#ef4444';
            } else {
                document.getElementById('debugJwtStatus').textContent = '✅ תקף';
                document.getElementById('debugJwtStatus').style.color = '#10b981';
            }

            // Update user information
            document.getElementById('debugJwtUserName').textContent = payload.refName || 'לא זמין';
            document.getElementById('debugJwtMobile').textContent = payload.mobileNo || 'לא זמין';
            document.getElementById('debugJwtUserRole').textContent = payload.role || 'לא זמין';
            
            // Update token timing information
            document.getElementById('debugJwtTokenAge').textContent = tokenAge ? `${Math.floor(tokenAge / 60)}m ${tokenAge % 60}s` : 'לא זמין';
            document.getElementById('debugJwtExpiresAt').textContent = expiresAt ? expiresAt.toLocaleString('he-IL') : 'לא זמין';
            document.getElementById('debugJwtIssuedAt').textContent = issuedAt ? issuedAt.toLocaleString('he-IL') : 'לא זמין';
            
            // Update raw token (truncated for display)
            document.getElementById('debugJwtTokenRaw').textContent = token.substring(0, 50) + '...';

        } catch (error) {
            console.error('Error updating JWT debug info:', error);
            
            // Set error state for all JWT fields
            document.getElementById('debugJwtStatus').textContent = '❌ שגיאה';
            document.getElementById('debugJwtStatus').style.color = '#ef4444';
            document.getElementById('debugJwtUserName').textContent = 'שגיאה';
            document.getElementById('debugJwtMobile').textContent = 'שגיאה';
            document.getElementById('debugJwtUserRole').textContent = 'שגיאה';
            document.getElementById('debugJwtTokenAge').textContent = 'שגיאה';
            document.getElementById('debugJwtExpiresAt').textContent = 'שגיאה';
            document.getElementById('debugJwtIssuedAt').textContent = 'שגיאה';
            document.getElementById('debugJwtTokenRaw').textContent = 'שגיאה';
        }
    }

    displayJwtInConsole() {
        try {
            // Get JWT token from refresh token service first, fallback to localStorage
            let token = null;
            if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
                token = window.refPortalPwa.refreshTokenService.getAccessToken();
            }

            if (!token) {
                console.log('❌ No JWT token found in localStorage');
                return;
            }

            // Use JwtService to display detailed information
            if (this.refPortalPWA.jwtService ) {
                JwtService.displayJwtInfo();
            } else {
                // Fallback if JwtService is not available
                console.log('🔐 JWT Token (Raw):', token);
                console.log('🔐 JWT Token (Decoded):', JwtService.parseJwtToken(token));
            }
        } catch (error) {
            console.error('Error displaying JWT in console:', error);
        }
    }

    copyFullJwtToken() {
        try {
            // Get JWT token from refresh token service first, fallback to localStorage
            let token = null;
            if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
                token = window.refPortalPwa.refreshTokenService.getAccessToken();
            }

            if (!token) {
                alert('לא נמצא טוקן JWT');
                return;
            }

            if (navigator.clipboard) {
                navigator.clipboard.writeText(token).then(() => {
                    // Show success feedback
                    const button = event.target;
                    const originalText = button.textContent;
                    button.textContent = '✅ הועתק!';
                    button.style.background = '#059669';
                    
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.style.background = '';
                    }, 2000);
                }).catch(err => {
                    console.error('Failed to copy full token:', err);
                    this.fallbackCopyTextToClipboard(token);
                });
            } else {
                this.fallbackCopyTextToClipboard(token);
            }
        } catch (error) {
            console.error('Error copying full JWT token:', error);
            alert('שגיאה בהעתקת הטוקן');
        }
    }

    testJwtRefresh() {
        try {
            // Get JWT token from refresh token service first, fallback to localStorage
            let token = null;
            if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
                token = window.refPortalPwa.refreshTokenService.getAccessToken();
            }

            if (!token) {
                alert('לא נמצא טוקן JWT לבדיקה');
                return;
            }

            // Parse current token
            const payload = JwtService.parseJwtToken(token);
            if (!payload) {
                alert('לא ניתן לפרסר את הטוקן הנוכחי');
                return;
            }

            // Check if token is expired
            const isExpired = JwtService.isTokenExpired(token);
            const expiresAt = JwtService.getTokenExpirationTime(token);
            const tokenAge = JwtService.getTokenAge();

            let message = '🧪 בדיקת טוקן JWT:\n\n';
            message += `📱 Client ID: ${payload.clientIdentifier || 'N/A'}\n`;
            message += `👤 User: ${payload.refName || 'N/A'}\n`;
            message += `🔑 Role: ${payload.role || 'N/A'}\n`;
            message += `⏰ Expires: ${expiresAt ? expiresAt.toLocaleString('he-IL') : 'Unknown'}\n`;
            message += `⏳ Age: ${tokenAge ? `${Math.floor(tokenAge / 60)}m ${tokenAge % 60}s` : 'Unknown'}\n`;
            message += `❌ Expired: ${isExpired ? 'Yes' : 'No'}\n\n`;

            if (isExpired) {
                message += '⚠️ הטוקן פג תוקף! יש צורך ברענון.';
            } else {
                const timeUntilExpiry = expiresAt ? Math.floor((expiresAt - new Date()) / 1000) : null;
                if (timeUntilExpiry && timeUntilExpiry < 300) { // Less than 5 minutes
                    message += '🔄 הטוקן יפוג בקרוב. מומלץ לרענן.';
                } else {
                    message += '✅ הטוקן תקף ועובד כרגיל.';
                }
            }

            alert(message);
            console.log('🧪 JWT Token Test Results:', {
                payload,
                isExpired,
                expiresAt,
                tokenAge,
                timeUntilExpiry: expiresAt ? Math.floor((expiresAt - new Date()) / 1000) : null
            });

        } catch (error) {
            console.error('Error testing JWT refresh:', error);
            alert('שגיאה בבדיקת הטוקן: ' + error.message);
        }
    }

    // WebSocket Debug Functions
    testWebSocketPing() {
        try {
            if (this.refPortalPWA && this.refPortalPWA.jwtWebSocket) {
                const success = this.refPortalPWA.jwtWebSocket.testPing();
                if (success) {
                    alert('✅ Ping נשלח בהצלחה!');
                } else {
                    alert('❌ Ping נכשל - בדוק את הקונסול לפרטים');
                }
            } else {
                alert('⚠️ WebSocket לא זמין לבדיקה');
            }
        } catch (error) {
            console.error('Error testing WebSocket ping:', error);
            alert('שגיאה בבדיקת Ping: ' + error.message);
        }
    }

    restartWebSocketHeartbeat() {
        try {
            if (this.refPortalPWA && this.refPortalPWA.jwtWebSocket) {
                this.refPortalPWA.jwtWebSocket.restartHeartbeat();
                alert('🔄 Heartbeat הופעל מחדש!');
            } else {
                alert('⚠️ WebSocket לא זמין לבדיקה');
            }
        } catch (error) {
            console.error('Error restarting WebSocket heartbeat:', error);
            alert('שגיאה בהפעלת מחדש של Heartbeat: ' + error.message);
        }
    }

    showWebSocketStatus() {
        try {
            if (this.refPortalPWA && this.refPortalPWA.jwtWebSocket) {
                const status = this.refPortalPWA.jwtWebSocket.getConnectionStatus();
                console.log('🔌 WebSocket Status:', status);
                
                let message = '🔌 סטטוס WebSocket:\n\n';
                message += `📡 מצב חיבור: ${status.connectionState}\n`;
                message += `🔄 מתחבר: ${status.isConnecting ? 'כן' : 'לא'}\n`;
                message += `🔌 WebSocket פתוח: ${status.wsOpen ? 'כן' : 'לא'}\n`;
                message += `🆔 מזהה לקוח: ${status.clientIdentifier || 'לא זמין'}\n`;
                message += `🫀 Heartbeat פעיל: ${status.heartbeatActive ? 'כן' : 'לא'}\n`;
                message += `⏰ Timeout פעיל: ${status.heartbeatTimeoutActive ? 'כן' : 'לא'}\n`;
                
                alert(message);
            } else {
                alert('⚠️ WebSocket לא זמין לבדיקה');
            }
        } catch (error) {
            console.error('Error showing WebSocket status:', error);
            alert('שגיאה בהצגת סטטוס WebSocket: ' + error.message);
        }
    }

    updateWebSocketDebugInfo() {
        try {
            if (this.refPortalPWA && this.refPortalPWA.jwtWebSocket) {
                const status = this.refPortalPWA.jwtWebSocket.getConnectionStatus();
                const statusElement = document.getElementById('debugWebSocketStatus');
                
                if (statusElement) {
                    let statusText = '';
                    let statusColor = '';
                    
                    if (status.connectionState === 'connected' && status.wsOpen) {
                        statusText = '✅ מחובר';
                        statusColor = '#10b981';
                    } else if (status.connectionState === 'connecting') {
                        statusText = '🔄 מתחבר...';
                        statusColor = '#f59e0b';
                    } else if (status.connectionState === 'reconnecting') {
                        statusText = '🔄 מתחבר מחדש...';
                        statusColor = '#f59e0b';
                    } else {
                        statusText = '❌ מנותק';
                        statusColor = '#ef4444';
                    }
                    
                    statusElement.textContent = statusText;
                    statusElement.style.color = statusColor;
                }
            } else {
                const statusElement = document.getElementById('debugWebSocketStatus');
                if (statusElement) {
                    statusElement.textContent = '⚠️ לא זמין';
                    statusElement.style.color = '#f59e0b';
                }
            }
        } catch (error) {
            console.error('Error updating WebSocket debug info:', error);
            const statusElement = document.getElementById('debugWebSocketStatus');
            if (statusElement) {
                statusElement.textContent = '❌ שגיאה';
                statusElement.style.color = '#ef4444';
            }
        }
    }

    // Handle action button clicks
    handleActionButton(action) {
        if (this.refPortalPWA) {
            switch (action) {
                case 'testIOSNotification':
                    this.refPortalPWA.testIOSNotification();
                    break;
                case 'showInstallPromptAgain':
                    this.refPortalPWA.showInstallPromptAgain();
                    break;
                case 'checkInstallStatus':
                    console.log('Install Status:', this.refPortalPWA.getInstallPromptStatus());
                    break;
                case 'resetInstallPreferences':
                    this.refPortalPWA.resetInstallPromptPreferences();
                    break;
                case 'testButtonClickability':
                    this.refPortalPWA.testButtonClickability();
                    break;
                case 'testAutoHide':
                    this.refPortalPWA.testAutoHide();
                    break;
                case 'forceAutoHide':
                    this.refPortalPWA.forceAutoHide();
                    break;
                case 'toggleChatSectionVisibility':
                    this.refPortalPWA.toggleChatSectionVisibility();
                    break;
                case 'checkUserStatus':
                    this.refPortalPWA.checkUserStatus();
                    break;
                case 'testCSSApplication':
                    this.refPortalPWA.testCSSApplication();
                    break;
                default:
                    console.warn('Unknown action:', action);
            }
        } else {
            console.error('RefPortalPWA not available');
        }
    }

    // Handle chat visibility actions
    handleChatVisibilityAction(action) {
        if (this.refPortalPWA) {
            if (action === 'check') {
                this.refPortalPWA.checkChatVisibilityStatus();
            } else if (action === 'refresh') {
                this.refPortalPWA.refreshChatVisibility();
            }
        } else {
            console.error('RefPortalPWA not available');
        }
    }

    // Handle chat sync actions
    handleChatSyncAction(action) {
        if (this.refPortalPWA) {
            switch (action) {
                case 'export':
                    this.refPortalPWA.exportChatMessages();
                    break;
                case 'fetch':
                    this.refPortalPWA.fetchChatMessagesFromServer();
                    break;
                case 'start':
                    this.refPortalPWA.startChatSync();
                    break;
                case 'stop':
                    this.refPortalPWA.stopChatSync();
                    break;
                default:
                    console.warn('Unknown sync action:', action);
            }
        } else {
            console.error('RefPortalPWA not available');
        }
    }

    // Close notification center
    closeNotificationCenter() {
        const notificationCenter = document.getElementById('iosNotificationCenter');
        if (notificationCenter) {
            notificationCenter.classList.remove('show');
        }
    }

    // Handle chat import
    handleChatImport(file) {
        if (this.refPortalPWA && this.refPortalPWA.importChatMessages) {
            this.refPortalPWA.importChatMessages(file);
        } else {
            console.error('RefPortalPWA or importChatMessages not available');
        }
    }
}

// Add page reload detection
let pageLoadTime = Date.now();
console.log('📱 Page loaded at:', new Date(pageLoadTime).toLocaleString());

// Check if page is reloading frequently
setInterval(() => {
    const currentTime = Date.now();
    const timeSinceLoad = currentTime - pageLoadTime;
    if (timeSinceLoad < 10000) { // Less than 10 seconds
        console.warn('⚠️ Page may be reloading frequently. Time since load:', timeSinceLoad, 'ms');
    }
}, 5000);