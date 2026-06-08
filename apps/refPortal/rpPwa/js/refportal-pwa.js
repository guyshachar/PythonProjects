import { ClientIdentifierService } from './client-identifier-service.js';
import { JwtService } from './jwtService.js';
import { jwtWebSocket } from './jwtWebSocket.js';
import { ShowDebug } from './showDebug.js';
import * as mobileHandling from './mobileHandling.js';
// Dynamic configuration will be loaded from environment
import { Security } from './security.js';
import { AppLock } from './appLock.js';
import { LockScreen } from './lockScreen.js';
import { WindowManager } from './windowManager.js';
import { refreshTokenService } from './refreshTokenService.js'; // Add refresh token service
import { VitePWARefresh } from './vite-pwa-refresh.js';
import { BadgeService } from './badgeService.js';
import { ReportsService } from './reportsService.js';
import { OfflineIntervalManager } from './offlineIntervalManager.js';
import { configService } from './config-service.js';
import { envLoader } from './environment-loader.js';
import { PWALogger } from './pwa-logger.js'; // Universal PWA console logging
import { SpeedMonitorService } from './speed-monitor-service.js';
import { SpeedMonitorComponent } from './speed-monitor-component.js';
import { DistanceTrackerService } from './distance-tracker-service.js';
import { DistanceTrackerComponent } from './distance-tracker-component.js';
import {
    isRunningAsInstalledPWA,
    getPWAClientProfile,
    getHebrewInstallInstructions
} from './pwa-install-context.js';

export class RefPortalPWA {
    static instance = null; 
    static getInstance() {
        if (!RefPortalPWA.instance) {
            console.log('🏗️ Creating new RefPortalPWA instance via getInstance...');
            RefPortalPWA.instance = new RefPortalPWA();
        }
        return RefPortalPWA.instance;
    }
    
    static async resetInstance() {
        if (RefPortalPWA.instance) {
            console.log('🔄 Resetting RefPortalPWA instance...');
            await RefPortalPWA.instance.cleanup();
            RefPortalPWA.instance = null;
        }
    }

    constructor() {
        // Prevent multiple instances
        if (RefPortalPWA.instance) {
            console.log('⚠️ RefPortalPWA instance already exists, returning existing instance');
            return RefPortalPWA.instance;
        }
        
        // Store the instance
        RefPortalPWA.instance = this;

        this.refportalSwName = '/js/refportal-sw.js?_t=' + Date.now().toString();

        this.configService = configService;
        this.envLoader = envLoader;
        this.vitePWARefresh = new VitePWARefresh({
            enableLogging: true,
            autoConnect: true,
            showUpdateNotification: true,
            updateCheckInterval: 60000
        });
        this.windowManager = new WindowManager();
        this.jwtWebSocket = jwtWebSocket;
        this.showDebug = new ShowDebug(this);
        this.refreshTokenService = refreshTokenService;  
        this.currentSection = this.defaultValidSection();
        this.chatMessages = [];
        this.pushhNotificationPermission = false;
        this.deferredPrompt = null;
        this.isAuthenticated = false;
        this.authenticationChecked = false; // Track if authentication check has completed (success or failure)
        this.currentUser = null;
        this.pushNotificationsMust = false;
        this.chatSyncEnabled = true;
        this.lastMessageId = null;
        this.chatSyncInterval = null;
        this.isOnline = navigator.onLine;
        this.wasOffline = false; // Track if we were offline to prevent redundant toasts
        this.isInitialized = false;

        /** Monotonic generations for tab async loads — ignore stale responses when user triggers a newer load. */
        this._asyncTabLoadGen = {};

        /** Public games table: default chronological (date then time). */
        this._publicGamesSortColumn = 'date';
        this._publicGamesSortDir = 'asc';

        /** Referee “all games” floating panel table (Games tab). */
        this._refereeGamesPanelSortColumn = 'date';
        this._refereeGamesPanelSortDir = 'asc';
        this._refereeGamesPanelGamesSnapshot = [];

        /** Nestable per-scope flag: programmatic &lt;select&gt;/date updates suppress filter `change` cascades. */
        this._domQuietDepth = {};

        /** Coalesce overlapping section loads: { [kind]: boolean } pending, { [kind]: Promise } in-flight. */
        this._coalescePending = {};
        this._coalesceInFlight = {};

        /** localStorage keys for public section filter persistence */
        this._LS_PUBLIC_GAMES_FILTERS = 'refportal_pwa_v1_publicGamesFilters';
        this._LS_PUBLIC_TABLES_FILTERS = 'refportal_pwa_v1_publicTablesFilters';
        this._scheduleSavePublicGamesFilters = () => {
            clearTimeout(this._savePublicGamesFiltersTimer);
            this._savePublicGamesFiltersTimer = setTimeout(() => this._savePublicGamesFiltersToStorage(), 300);
        };
        
        this.badgeService = new BadgeService(this.sendApiLog);
        this.pdfReportService = new ReportsService(this.jwtWebSocket.sendLog);
        //this.pwaLogger = new PWALogger(this.jwtWebSocket); // Universal PWA console logging (disabled by default)
                
        // Enable logger safely after initialization
        setTimeout(() => {
            if (this.pwaLogger && this.pwaLogger.enableSafely) {
                this.pwaLogger.enableSafely();
            }
        }, 2000); // Enable after 2 seconds to ensure everything is loaded
        this.unreadMessagesCount = 0;
        this.pendingGamesCount = 0;
        this.criticalNotificationsCount = 0;
        this.lastAuthenticationStatus = false;
        
        // Dynamic configuration
        this.config = null;
        this.configLoaded = false;
        
        console.log('🔍 RefPortalPWA constructor called');
    }

    _beginAsyncTabLoad(kind) {
        if (!this._asyncTabLoadGen) this._asyncTabLoadGen = {};
        this._asyncTabLoadGen[kind] = (this._asyncTabLoadGen[kind] || 0) + 1;
        return this._asyncTabLoadGen[kind];
    }

    _staleAsyncTabLoad(kind, myGen) {
        return myGen !== (this._asyncTabLoadGen[kind] || 0);
    }

    /**
     * Coalesce overlapping async work for one logical key (tab data loads, etc.).
     * All callers await the same in-flight promise; bursts collapse to minimal re-runs.
     */
    async _runCoalescedAsync(kind, execFn) {
        this._coalescePending[kind] = true;
        if (this._coalesceInFlight[kind]) {
            return this._coalesceInFlight[kind];
        }
        this._coalesceInFlight[kind] = (async () => {
            try {
                while (true) {
                    this._coalescePending[kind] = false;
                    await execFn();
                    if (!this._coalescePending[kind]) break;
                }
            } finally {
                delete this._coalesceInFlight[kind];
            }
        })();
        return this._coalesceInFlight[kind];
    }

    _isDomQuiet(scope) {
        return (this._domQuietDepth[scope] || 0) > 0;
    }

    /** Nestable: run fn while filter controls for `scope` ignore synthetic change cascades. */
    _runWithDomQuiet(scope, fn) {
        this._domQuietDepth[scope] = (this._domQuietDepth[scope] || 0) + 1;
        try {
            return fn();
        } finally {
            this._domQuietDepth[scope] = Math.max(0, (this._domQuietDepth[scope] || 1) - 1);
        }
    }

    /**
     * Load dynamic configuration from environment
     */
    async loadConfiguration() {
        try {
            console.log('🔧 Loading dynamic configuration...');
            
            // Wait for config service to be available
            if (this.configService) {
                this.config = await this.configService.load();
                this.configLoaded = true;
                console.log('✅ Configuration loaded from configService:', this.config);
            } else {
                // Fallback to environment loader
                if (this.envLoader) {
                    const env = await this.envLoader.load();
                    this.config = this.buildConfigFromEnv(env);
                    this.configLoaded = true;
                    console.log('✅ Configuration loaded from envLoader:', this.config);
                } else {
                    // Final fallback to default configuration
                    this.config = this.getDefaultConfig();
                    this.configLoaded = true;
                    console.log('⚠️ Using default configuration as fallback');
                }
            }
            
            return this.config;
        } catch (error) {
            console.error('❌ Failed to load configuration:', error);
            this.config = this.getDefaultConfig();
            this.configLoaded = true;
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
            API_BASE_URL: env.API_BASE_URL || 'https://pwa-dev.refereex.com:5003',
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
                MIN_DISTANCE_THRESHOLD: env.FEATURES?.MIN_DISTANCE_THRESHOLD || 5,
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
     * Get default configuration
     */
    getDefaultConfig() {
        return {
            API_BASE_URL: 'https://pwa-dev.refereex.com:5003',
            WSS_BASE_URL: 'pwa-dev.refereex.com:5003',
            VAPID_PUBLIC_KEY: 'BCrb6Lp792xCx8tOm_BLPrvb6DY9GDhfu9K04DBrhAz4qDL7LqVodnePQ4ZTmZXBUWhWumYlKwEjj4QzHRChhX0',
            ENDPOINTS: {
                SPEED_TRACKING_DATA: '/api/pwa/speed-tracking-data',
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
                AUTH_REFRESH_TOKEN: '/auth/refresh',
                AUTH_VALIDATE_TOKEN: '/auth/validate',
                SEND_REPORT_EMAIL: '/api/pwa/sendReportEmail',
                POSITION_UPDATE: '/api/pwa/position-update',
                USER_DETAILS: '/api/pwa/user-details',
                UPDATE_USER_DETAILS: '/api/pwa/updateUserDetails',
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
            OPEN_REPORTS_EMAILS: ['openreports@refereex.com'],
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
                MIN_DISTANCE_THRESHOLD: 0,
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
     * Get configuration value with fallback
     */
    getConfig(key, defaultValue = null) {
        if (!this.configLoaded) {
            console.warn('Configuration not loaded yet. Call loadConfiguration() first.');
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

    async init() {
        // Prevent multiple initializations
        if (this.isInitialized) {
            console.log('⚠️ RefPortalPWA already initialized, skipping...');
            return;
        }

        // Load configuration first
        await this.loadConfiguration();

        console.log('🚀 Starting RefPortalPWA initialization...');
        
        console.log('✅ Configuration loaded successfully');

        // Initialize RefreshTokenService after configuration is loaded
        await this.refreshTokenService.initialize();
        
        // Initialize PWA Auto-Refresh
        if (this.vitePWARefresh) {
            try {
                await this.vitePWARefresh.init();
                console.log('✅ PWA Auto-Refresh initialized');
            } catch (error) {
                console.error('❌ Failed to initialize PWA Auto-Refresh:', error);
            }
        }

        this.deviceInfo = mobileHandling.getDeviceInfo();
        this.deviceName = this.deviceInfo.deviceName;

        const geolocationOptions = {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0,
            updateInterval: 1000
        };

        // Speed monitoring services
        this.speedMonitorService = new SpeedMonitorService({
            maxAccuracy: this.getConfig('FEATURES.MAX_GPS_ACCURACY') || 50,
            updateInterval: 1000, // ms
            speedThreshold: this.getConfig('FEATURES.SPEED_THRESHOLD') || 20, // km/h
            startMonitoringHoursBeforeGame: this.getConfig('FEATURES.START_MONITORING_HOURS_BEFORE_GAME') || 3,
            detectArrival: this.getConfig('FEATURES.DETECT_ARRIVAL') || false,
            showToast: (message, type) => this.showToast(message, type), // Pass toast callback
            ...geolocationOptions
        });
        
        this.speedMonitorComponent = new SpeedMonitorComponent({
            showToast: true,
            showModal: true,
            showBadge: true,
            autoHideToast: 5000
        });
        
        // Distance tracking services
        this.distanceTrackerService = new DistanceTrackerService({
            maxAccuracy: this.getConfig('FEATURES.MAX_GPS_ACCURACY') || 50,
            updateInterval: 1000,
            minDistanceThreshold: this.getConfig('FEATURES.MIN_DISTANCE_THRESHOLD') || 3,
            apiService: this.refreshTokenService, // Pass API service for sending tracking data
            apiEndpoint: this.getConfig('ENDPOINTS.SPEED_TRACKING_DATA') || '/api/pwa/speed-tracking-data',
            ...geolocationOptions
        });

        this.distanceTrackerComponent = new DistanceTrackerComponent({
            showToast: true,
            showModal: false,
            autoHideToast: 3000,
            position: 'bottom-left'
        });

        // Initialize current week for availability navigation
        this.currentWeekStart = new Date();
        this.currentWeekStart.setHours(0, 0, 0, 0);
        
        this.setupEventListeners();
        
        //await this.initializeSecurity();
        // Initialize security (iOS-compatible)        
        // Set up security on startup
        if (this.getConfig('SECURITY.ENABLE_PIN')) {
            this.security = new Security();
            this.lockScreen = new LockScreen(this.security);
            this.appLock = new AppLock(this.lockScreen);

            this.setupSecurity();
        }

        await this.checkPushSubscriptionStatus();

        this.pushNotificationsMust = this.getConfig('FEATURES.PUSH_NOTIFICATIONS_MUST');

        // Add this to your PWA for on-device debugging
        if (window.navigator.standalone & false) {
            const debugPanel = document.createElement('div');
            debugPanel.innerHTML = `
                <div id="adminDebugPanel" style="position:fixed;top:0;right:0;background:rgba(0,0,0,0.8);color:white;padding:10px;font-size:12px;z-index:9999;">
                    <div>PWA Debug</div>
                    <div>Standalone: ${window.navigator.standalone}</div>
                    <div>SW: ${'serviceWorker' in navigator}</div>
                    <div>Online: ${navigator.onLine}</div>
                    <button onclick="window.testAppLock()" style="margin-top:5px;padding:2px 8px;background:#4CAF50;border:none;color:white;border-radius:3px;cursor:pointer;">🔒 Test Lock</button>
                    <button onclick="window.securityTest.status()" style="margin-top:5px;margin-left:5px;padding:2px 8px;background:#2196F3;border:none;color:white;border-radius:3px;cursor:pointer;">📊 Status</button>
                </div>
            `;
            document.body.appendChild(debugPanel);
        }

        // Add these to your PWA for quick debugging
        window.debugPWA = {
            status: () => console.log('PWA Status:', {
                standalone: window.navigator.standalone,
                serviceWorker: 'serviceWorker' in navigator,
                pushManager: 'PushManager' in window,
                notifications: 'Notification' in window
            }),
            
            storage: () => console.log('Storage:', {
                localStorage: Object.keys(localStorage),
                sessionStorage: Object.keys(sessionStorage)
            }),
            
            network: () => console.log('Network:', {
                online: navigator.onLine,
                connection: navigator.connection?.effectiveType
            })
        };

        // Wait for service worker to be ready before proceeding
        console.log('🚀 Initializing RefereeX PWA...');
        // Debug current service worker state
        //await this.debugServiceWorkerState();
        
        try {
            const serviceWorkerRegistration = await this.setupServiceWorker();
            
            if (serviceWorkerRegistration) {
                console.log('✅ Service Worker setup complete');
            } else {
                console.warn('⚠️ Service Worker setup failed, some features may not work');
            }
            
            // Check service worker status for debugging
            try {
                const swStatus = await this.checkServiceWorkerStatus();
                console.log('📱 Service Worker Status:', swStatus);
            } catch (swStatusError) {
                console.warn('⚠️ Could not check service worker status:', swStatusError.message);
            }
        } catch (error) {
            console.error('❌ Critical error in service worker setup:', error);
            console.warn('⚠️ Continuing without service worker, some features may not work');
            
            // Try to provide more specific error information
            if (error.message.includes('timeout')) {
                console.warn('⏰ Service worker registration timed out - this may be normal on first load');
            } else if (error.message.includes('not accessible')) {
                console.error('❌ Service worker file is not accessible - check file path and permissions');
            } else if (error.message.includes('not supported')) {
                console.warn('⚠️ Service worker not supported in this browser');
            }
        }
        
        this.currentAuthenticationStatus = null;
        this.authenticationChecked = false; // Reset authentication check status on init
        
        // Initialize splash video for mobile devices
        this.initializeSplashVideo();
        
        // Splash video is already shown by default in CSS, no need to show it here
        // It will be hidden after authentication check completes
        
        await this.checkAuthenticationStatus();
        this.startAuthenticationPolling();
        await this.subscribeToPushNotifications();
        this.startPushSubscriptionPolling();
        this.setupPageVisibilityHandling();
        this.setupInactivityTimeout();
        this.setupInstallPrompt();
        
        // Check PWA status
        this.checkPWAStatus();
        
        // Initialize chat synchronization for cross-device sync
        //this.initializeChatSync();
        
        // Initialize auto-hide functionality for chat sections
        this.initAutoHideSections();

        // Speed / distance before first content load so next-game prefetch can call setNextGame
        await this.initializeSpeedMonitoring();
        await this.initializeDistanceTracking();
        
        await this.loadInitialContent();

        // Debug install prompt status
        setTimeout(() => {
            const status = this.getInstallPromptStatus();
            console.log('🔍 Install Prompt Status:', status);
            
            if (status.canShowPrompt) {
                console.log('✅ Install prompt can be shown');
            } else {
                console.log('❌ Install prompt cannot be shown:', {
                    canInstall: status.canInstall,
                    hasPrompt: status.hasPrompt,
                    dismissedTime: status.dismissedTime
                });
            }
        }, 2000);

        // Update debug panel after initialization
        setTimeout(() => {
            this.updateDebugPanel();
        }, 3000);

        // Initialize badge service
        await this.initializeBadgeService();

        this.mySetInterval(async () => {
            await this.sendApiLog('info', 'test log message');
        }, 1000 * 60 * 5);
        
        // Mark as initialized
        this.isInitialized = true;
        console.log('✅ RefPortalPWA initialization complete');
    }

    mySetInterval(handler, interval) {
        setTimeout(async () => {
            await handler();
        }, 1);
        setInterval(async () => {
            await handler();
        }, interval);
    }
    
    async setupSecurity() {
        // Check if PIN is set
        const pinSet = localStorage.getItem('security_pin_set') === 'true';
        
        if (!pinSet) {
            // Show PIN setup dialog
            this.showPINSetup();
        } else {
            // Check if app should be locked
            this.appLock.checkLockStatus();
        }
    }

    showPINSetup() {
        const pin = prompt('הגדר PIN בן 4 ספרות לפחות:');
        if (pin && pin.length >= 4) {
            this.security.setPIN(pin).then(success => {
                if (success) {
                    this.showToast('PIN הוגדר בהצלחה', 'success');
                }
            });
        }
    }

    // Monitor service worker state changes for debugging
    monitorServiceWorkerState(swRegistration) {
        if (!swRegistration) return;
        
        // Monitor the active service worker
        if (swRegistration.active) {
            console.log('📱 Active service worker state:', swRegistration.active.state);
            
            swRegistration.active.addEventListener('statechange', (event) => {
                console.log('📱 Service worker state changed:', event.target.state);
            });
        }
        
        // Monitor the installing service worker
        if (swRegistration.installing) {
            console.log('📱 Installing service worker state:', swRegistration.installing.state);
            
            swRegistration.installing.addEventListener('statechange', (event) => {
                console.log('📱 Installing service worker state changed:', event.target.state);
            });
        }
        
        // Monitor the waiting service worker
        if (swRegistration.waiting) {
            console.log('📱 Waiting service worker state:', swRegistration.waiting.state);
            
            swRegistration.waiting.addEventListener('statechange', (event) => {
                console.log('📱 Waiting service worker state changed:', event.target.state);
            });
        }
        
        // Monitor registration updates
        swRegistration.addEventListener('updatefound', () => {
            console.log('🔄 Service worker update found');
            this.handleServiceWorkerUpdate(swRegistration);
        });
    }

    checkServiceWorkerSupported() {
        if (!('serviceWorker' in navigator)) {
            console.warn('⚠️ Service Worker not supported');
            return false;
        }
        return true;
    }
    
    checkPushManagerSupported() {
        if (!('PushManager' in window)) {
            console.warn('⚠️ Push Manager not supported');
            return false;
        }
        return true;
    }

    checkPushNotificationSupported() {
        if (!('Notification' in window)) {
            console.warn('⚠️ Push Notification not supported');
            return false;
        }
        return true;
    }

    // Debug function to check current service worker state
    async debugServiceWorkerState() {
        if (!this.checkServiceWorkerSupported()) {
            return;
        }
        
        try {
            const registrations = await navigator.serviceWorker.getRegistrations();
            console.log('🔍 Current service worker registrations:', registrations.length);
            
            registrations.forEach((reg, index) => {
                console.log(`📱 Registration ${index + 1}:`, {
                    scope: reg.scope,
                    active: reg.active ? reg.active.state : 'None',
                    installing: reg.installing ? reg.installing.state : 'None',
                    waiting: reg.waiting ? reg.waiting.state : 'None',
                    updateViaCache: reg.updateViaCache
                });
            });
            
            if (registrations.length === 0) {
                console.log('⚠️ No service worker registrations found');
                
                // Check if there's a pending registration
                try {
                    const readyRegistration = await navigator.serviceWorker.ready;
                    console.log('📱 Pending registration found via ready:', readyRegistration);
                } catch (readyError) {
                    console.log('📱 No pending registration via ready:', readyError.message);
                }
            }
            
            await this.fetchServiceWorker()
        } catch (error) {
            console.error('❌ Error checking service worker state:', error)
        }
    }

    async fetchServiceWorker() {
        // Check if service worker file exists
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.refportalSwName
            });
            if (response.ok) {
                console.log('✅ Service worker file exists and is accessible')
            } else {
                console.warn('⚠️ Service worker file not accessible:', response.status, response.statusText)
            }
        } catch (fetchError) {
            console.warn('⚠️ Cannot check service worker file:', fetchError.message)
        }
    }

    // Handle service worker update
    handleServiceWorkerUpdate(registration) {
        if (registration.waiting) {
            console.log('🔄 New service worker waiting to activate');
            this.showUpdateNotification({
                newVersion: 'New version available',
                currentVersion: 'Current version',
                type: 'SW_UPDATE'
            });
        }
    }
    
    // Show update notification with action buttons
    showUpdateNotification(updateData) {
        // Check if notification already exists
        if (document.getElementById('updateNotification')) {
            return;
        }
        
        const notification = document.createElement('div');
        notification.id = 'updateNotification';
        notification.className = 'update-notification';
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            z-index: 10000;
            max-width: 350px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
        `;
        
        notification.innerHTML = `
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                <div style="font-size: 24px;">🚀</div>
                <div>
                    <div style="font-weight: 600; font-size: 16px;">Update Available</div>
                    <div style="font-size: 14px; opacity: 0.9;">New version: ${updateData.newVersion}</div>
                </div>
            </div>
            <div style="display: flex; gap: 8px;">
                <button id="updateNowBtn" style="
                    background: rgba(255,255,255,0.2);
                    border: 1px solid rgba(255,255,255,0.3);
                    color: white;
                    padding: 8px 16px;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    font-weight: 500;
                    transition: all 0.2s;
                ">עדכן עכשיו</button>
                <button id="updateLaterBtn" style="
                    background: transparent;
                    border: 1px solid rgba(255,255,255,0.3);
                    color: white;
                    padding: 8px 16px;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: all 0.2s;
                ">אח״כ</button>
            </div>
        `;
        
        document.body.appendChild(notification);
        
        // Add hover effects
        const updateBtn = notification.querySelector('#updateNowBtn');
        const laterBtn = notification.querySelector('#updateLaterBtn');
        
        updateBtn.addEventListener('mouseenter', () => {
            updateBtn.style.background = 'rgba(255,255,255,0.3)';
        });
        updateBtn.addEventListener('mouseleave', () => {
            updateBtn.style.background = 'rgba(255,255,255,0.2)';
        });
        
        laterBtn.addEventListener('mouseenter', () => {
            laterBtn.style.background = 'rgba(255,255,255,0.1)';
        });
        laterBtn.addEventListener('mouseleave', () => {
            laterBtn.style.background = 'transparent';
        });
        
        // Handle update now
        updateBtn.addEventListener('click', async () => {
            await this.forceServiceWorkerUpdate();
            notification.remove();
        });
        
        // Handle later
        laterBtn.addEventListener('click', () => {
            notification.remove();
        });
        
        // Auto-remove after 30 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 30000);
    }
    
    // Update debug information panel
    async updateDebugPanel() {
        try {
            console.log('🔍 Updating debug panel...')
            
            // Update client identifier
            try {
                const clientIdentifier = await this.getClientIdentifier();
                const debugElement = document.getElementById('debugClientIdentifier');
                if (debugElement) {
                    debugElement.textContent = clientIdentifier || 'לא נמצא';
                    debugElement.style.color = clientIdentifier ? '#10b981' : '#ef4444';
                }
            } catch (error) {
                console.error('❌ Error updating client identifier:', error);
                const debugElement = document.getElementById('debugClientIdentifier');
                if (debugElement) {
                    debugElement.textContent = 'שגיאה: ' + error.message;
                    debugElement.style.color = '#ef4444';
                }
            }

            // Update push notification endpoint and availability
            try {
                const pushSubscription = await this.getCurrentPushSubscription();
                const pushAvailability = await this.checkPushNotificationAvailability();
                
                const debugElement = document.getElementById('debugPushEndpoint');
                if (debugElement) {
                    if (pushSubscription && pushSubscription.endpoint) {
                        debugElement.textContent = `${pushSubscription.endpoint} (זמין)`;
                        debugElement.style.color = '#10b981';
                    } else if (pushAvailability.available) {
                        debugElement.textContent = 'זמין אך לא נרשם';
                        debugElement.style.color = '#f59e0b';
                    } else {
                        debugElement.textContent = `לא זמין: ${pushAvailability.reason}`;
                        debugElement.style.color = '#ef4444';
                    }
                }
            } catch (error) {
                console.error('❌ Error updating push notification endpoint:', error);
                const debugElement = document.getElementById('debugPushEndpoint');
                if (debugElement) {
                    debugElement.textContent = 'שגיאה: ' + error.message;
                    debugElement.style.color = '#ef4444';
                }
            }

            // Update service worker status
            try {
                const swStatus = await this.checkServiceWorkerStatus();
                const debugElement = document.getElementById('debugSWStatus');
                if (debugElement) {
                    const statusText = `${swStatus.supported ? 'נתמך' : 'לא נתמך'}, ${swStatus.registered ? 'רשום' : 'לא רשום'}, ${swStatus.active ? 'פעיל' : 'לא פעיל'}`;
                    debugElement.textContent = statusText;
                    debugElement.style.color = swStatus.active ? '#10b981' : swStatus.registered ? '#f59e0b' : '#ef4444';
                }
                
                // Update service worker version
                const versionElement = document.getElementById('debugSWVersion');
                if (versionElement) {
                    versionElement.textContent = swStatus.version || 'לא זמין';
                    versionElement.style.color = swStatus.version && swStatus.version !== 'Unknown' ? '#10b981' : '#f59e0b';
                }
            } catch (error) {
                console.error('❌ Error updating service worker status:', error);
                const debugElement = document.getElementById('debugSWStatus');
                if (debugElement) {
                    debugElement.textContent = 'שגיאה: ' + error.message;
                    debugElement.style.color = '#ef4444';
                }
                
                const versionElement = document.getElementById('debugSWVersion');
                if (versionElement) {
                    versionElement.textContent = 'שגיאה';
                    versionElement.style.color = '#ef4444';
                }
            }

            // Update PWA status
            try {
                const pwaStatus = this.getInstallPromptStatus();
                const debugElement = document.getElementById('debugPWAStatus');
                if (debugElement) {
                    const pwaText = `${pwaStatus.canInstall ? 'ניתן להתקין' : 'לא ניתן להתקין'}, ${pwaStatus.hasPrompt ? 'יש הודעת התקנה' : 'אין הודעת התקנה'}`;
                    debugElement.textContent = pwaText;
                    debugElement.style.color = pwaStatus.canInstall ? '#10b981' : '#f59e0b';
                }
            } catch (error) {
                console.error('❌ Error updating PWA status:', error);
                const debugElement = document.getElementById('debugPWAStatus');
                if (debugElement) {
                    debugElement.textContent = 'שגיאה: ' + error.message;
                    debugElement.style.color = '#ef4444';
                }
            }

            // Update last updated timestamp
            try {
                const debugElement = document.getElementById('debugLastUpdated');
                if (debugElement) {
                    debugElement.textContent = new Date().toLocaleString('he-IL');
                    debugElement.style.color = '#10b981';
                }
            } catch (error) {
                console.error('❌ Error updating timestamp:', error);
            }

            console.log('✅ Debug panel updated successfully');
        } catch (error) {
            console.error('❌ Error updating debug panel:', error);
        }
    }

    // Helper function to get service worker registration safely
    async getServiceWorkerRegistration() {
        if (!this.checkServiceWorkerSupported()) {
            throw new Error('Service Worker not supported');
        }
        
        if (!!this.serviceWorkerRegistrion) {
            return this.serviceWorkerRegistrion;
        }
        
        try {
            // First check if we already have a registration
            let existingRegistrations = await navigator.serviceWorker.getRegistrations();
            if (existingRegistrations.length > 0) {
                console.log('✅ Found existing service worker registration');
                this.serviceWorkerRegistrion = existingRegistrations[0];
                return existingRegistrations[0];
            }
            
            // Wait for service worker to be ready (this will wait for the registration from HTML)
            // Add a timeout to prevent waiting indefinitely
            console.log('📱 Waiting for service worker registration to be ready...');
            const registrationPromise = navigator.serviceWorker.ready;
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('Service worker registration timeout')), 10000); // 10 second timeout
            });
            
            const registration = await Promise.race([registrationPromise, timeoutPromise]);
            console.log('✅ Service worker ready');
            return registration;
        } catch (error) {
            console.error('❌ Error getting service worker registration:', error);
            
            // If it's a timeout, the service worker might not be registered yet
            // Try to check if there are any pending registrations
            if (error.message.includes('timeout')) {
                console.log('⏰ Timeout occurred, checking for pending registrations...');
                const pendingRegistrations = await navigator.serviceWorker.getRegistrations();
                if (pendingRegistrations.length > 0) {
                    console.log('✅ Found pending registration after timeout');
                    this.serviceWorkerRegistrion = pendingRegistrations[0];
                    return pendingRegistrations[0];
                }
                
                // If still no registration, try to register manually as a last resort
                console.log('🔄 No registration found, attempting manual registration...');
                try {
                    // Register with root scope so it can control all pages
                    const manualRegistration = await navigator.serviceWorker.register(this.refportalSwName, { scope: '/' });
                    console.log('✅ Manual registration successful');
                    this.serviceWorkerRegistrion = manualRegistration;
                    return manualRegistration;
                } catch (manualError) {
                    console.error('❌ Manual registration failed:', manualError);
                    
                    await this.fetchServiceWorker();
                }
            }
            
            throw new Error(`Failed to get service worker registration: ${error.message}`);
        }
    }

    // Helper function to check if API server is reachable
    async checkApiServerHealth() {
        try {
            console.log('🏥 Checking API server health:', this.getConfig('ENDPOINTS.HEALTH'));
            
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.HEALTH')
            });
            
            if (response.ok) {
                console.log('✅ API server is healthy');
                return true;
            } else {
                console.warn('⚠️ API server returned non-OK status:', response.status);
                return false;
            }
        } catch (error) {
            console.error('❌ API server health check failed:', error);
            return false;
        }
    }

    // Helper function to get client information for API calls
    getClientInfo() {
        return {
            userAgent: navigator.userAgent,
            platform: navigator.platform,
            language: navigator.language,
            cookieEnabled: navigator.cookieEnabled,
            onLine: navigator.onLine,
            timestamp: new Date().toISOString()
        };
    }

    setupEventListeners() {
        console.log('🔧 Setting up event listeners...');

        setTimeout(async () => await this.showDebug.refreshDebugInfo(), 2000);

        // Hash-based routing
        this.setupHashRouting();

        // Navigation
        const navItems = document.querySelectorAll('.nav-item');
        if (navItems.length > 0) {
            navItems.forEach(item => {
                item.addEventListener('click', async (e) => {
                    await this.navigateToSection(e.currentTarget.dataset.section);
                });
            });
            console.log('✅ Navigation event listeners set up');
        } else {
            console.warn('⚠️ No navigation items found');
        }

        // Notification button
        const pushNotificationBtn = document.getElementById('notificationBtn');
        if (pushNotificationBtn) {
            if (!this.checkPushNotificationSupported) {
                pushNotificationBtn.disabled = true;
            }
            else {
                // Long click state variables
                let longClickTimer = null;
                let isLongClick = false;
                let hasMoved = false;
                const longClickDuration = 1000; // 1 second
                const moveThreshold = 5; // pixels
                let startX, startY;

                mobileHandling.implementHardClick(pushNotificationBtn, (event, data) => {
                    console.log('🔴 Hard click detected:', data);
                    this.forceUnsubscribeFromNotifications();
                }, {
                    forceThreshold: 0.7,
                    pressureThreshold: 0.7,
                    enableVibration: true
                });
                
                // Track if this is a touch interaction (to prevent double-firing on iOS)
                let isTouchInteraction = false;
                
                // Unified handler for both mouse and touch events
                const handleStart = (e) => {
                    // Mark as touch if it's a touch event
                    if (e.type.startsWith('touch')) {
                        isTouchInteraction = true;
                        // Prevent default to avoid iOS double-tap zoom
                        e.preventDefault();
                        // Add visual feedback for touch
                        pushNotificationBtn.classList.add('pressed');
                    } else {
                        isTouchInteraction = false;
                        // Add visual feedback for mouse
                        pushNotificationBtn.classList.add('pressed');
                    }
                    
                    // Reset state
                    isLongClick = false;
                    hasMoved = false;
                    
                    // Get coordinates from mouse or touch event
                    const clientX = e.clientX ?? (e.touches && e.touches[0]?.clientX);
                    const clientY = e.clientY ?? (e.touches && e.touches[0]?.clientY);
                    startX = clientX;
                    startY = clientY;
                    
                    // Start long click timer
                    longClickTimer = setTimeout(() => {
                        if (!hasMoved) {
                            isLongClick = true;
                            this.requestPushNotificationPermissionsUnsubscribe(true);
                        }
                        longClickTimer = null;
                    }, longClickDuration);
                };
                
                const handleMove = (e) => {
                    if (e.type.startsWith('touch')) {
                        e.preventDefault(); // Prevent scrolling while touching button
                    }
                    
                    if (longClickTimer && !hasMoved) {
                        const clientX = e.clientX ?? (e.touches && e.touches[0]?.clientX);
                        const clientY = e.clientY ?? (e.touches && e.touches[0]?.clientY);
                        
                        if (clientX !== undefined && clientY !== undefined) {
                            const deltaX = Math.abs(clientX - startX);
                            const deltaY = Math.abs(clientY - startY);
                            
                            if (deltaX > moveThreshold || deltaY > moveThreshold) {
                                hasMoved = true;
                                clearTimeout(longClickTimer);
                                longClickTimer = null;
                            }
                        }
                    }
                };
                
                const handleEnd = (e) => {
                    if (e.type.startsWith('touch')) {
                        e.preventDefault();
                    }
                    
                    // Remove visual feedback
                    pushNotificationBtn.classList.remove('pressed');
                    
                    // Clear long click timer
                    if (longClickTimer) {
                        clearTimeout(longClickTimer);
                        longClickTimer = null;
                    }
                    
                    // For touch events, handle the click action here to avoid double-firing
                    if (isTouchInteraction && !isLongClick && !hasMoved) {
                        // Small delay to ensure state is reset
                        setTimeout(() => {
                            this.requestPushNotificationPermissionsSubscribe(true);
                        }, 10);
                        isTouchInteraction = false;
                    }
                };
                
                const handleCancel = () => {
                    // Remove visual feedback
                    pushNotificationBtn.classList.remove('pressed');
                    
                    // Clear long click timer and mark as moved
                    if (longClickTimer) {
                        clearTimeout(longClickTimer);
                        longClickTimer = null;
                    }
                    hasMoved = true;
                    isTouchInteraction = false;
                };
                
                // Add mouse events (for desktop)
                pushNotificationBtn.addEventListener('mousedown', handleStart);
                pushNotificationBtn.addEventListener('mousemove', handleMove);
                pushNotificationBtn.addEventListener('mouseup', handleEnd);
                pushNotificationBtn.addEventListener('mouseleave', handleCancel);
                
                // Add touch events (for iOS and mobile devices)
                pushNotificationBtn.addEventListener('touchstart', handleStart, { passive: false });
                pushNotificationBtn.addEventListener('touchmove', handleMove, { passive: false });
                pushNotificationBtn.addEventListener('touchend', handleEnd, { passive: false });
                pushNotificationBtn.addEventListener('touchcancel', handleCancel, { passive: false });
                
                // Click handler for mouse events (touch events handled in touchend)
                pushNotificationBtn.addEventListener('click', (e) => {
                    // Only handle if it's NOT a touch interaction (already handled in touchend)
                    if (!isTouchInteraction && !isLongClick && !hasMoved) {
                        this.requestPushNotificationPermissionsSubscribe(true);
                    }
                    
                    // Reset state for next interaction
                    isLongClick = false;
                    hasMoved = false;
                    isTouchInteraction = false;
                });
                
                // Focus handling for showing other buttons after 3 seconds
                let focusTimer = null;
                const focusDuration = 3000; // 3 seconds
                let buttonsShown = false;
                
                // Start timer on notification button focus/hover
                pushNotificationBtn.addEventListener('focus', () => {
                    if (!buttonsShown) {
                        focusTimer = setTimeout(showButtons, focusDuration);
                    }
                });
                
                pushNotificationBtn.addEventListener('mouseenter', () => {
                    if (!buttonsShown) {
                        focusTimer = setTimeout(showButtons, focusDuration);
                    }
                });
                
                // Clear timer on notification button blur/mouseleave (but don't hide buttons yet)
                pushNotificationBtn.addEventListener('blur', () => {
                    if (focusTimer) {
                        clearTimeout(focusTimer);
                        focusTimer = null;
                    }
                });
                
                pushNotificationBtn.addEventListener('mouseleave', () => {
                    if (focusTimer) {
                        clearTimeout(focusTimer);
                        focusTimer = null;
                    }
                });
                
                console.log('✅ Notification button event listener set up');
            }
        } else {
            console.warn('⚠️ Notification button not found');
        }

        // Chat functionality
        const sendMessageBtn = document.getElementById('sendMessage');
        if (sendMessageBtn) {
            sendMessageBtn.addEventListener('click', () => {
                this.sendChatMessage();
            });
            console.log('✅ Send message button event listener set up');
        } else {
            console.warn('⚠️ Send message button not found');
        }

        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.sendChatMessage();
                }
            });
            console.log('✅ Chat input event listener set up');
        } else {
            console.warn('⚠️ Chat input not found');
        }

        // Action buttons
        const actionBtns = document.querySelectorAll('.action-btn');
        if (actionBtns.length > 0) {
            actionBtns.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    this.handleActionButton(e.currentTarget.dataset.action);
                });
            });
            console.log('✅ Action buttons event listeners set up');
        } else {
            console.warn('⚠️ No action buttons found');
        }

        // Toast close
        const toastClose = document.querySelector('.toast-close');
        if (toastClose) {
            toastClose.addEventListener('click', () => {
                this.hideToast();
            });
            console.log('✅ Toast close event listener set up');
        } else {
            console.warn('⚠️ Toast close button not found');
        }

        // Install prompt UI is wired in setupInstallPrompt() (single binding)

        // Pin buttons for chat sections
        const pinChatActions = document.getElementById('pinChatActions');
        if (pinChatActions) {
            pinChatActions.addEventListener('click', () => {
                this.togglePinSection('chatActions');
            });
            console.log('✅ Pin chat actions button event listener set up');
        } else {
            console.warn('⚠️ Pin chat actions button not found');
        }

        const pinChatSyncControls = document.getElementById('pinChatSyncControls');
        if (pinChatSyncControls) {
            pinChatSyncControls.addEventListener('click', () => {
                this.togglePinSection('chatSyncControls');
            });
            console.log('✅ Pin chat sync controls button event listener set up');
        } else {
            console.warn('⚠️ Pin chat sync controls button not found');
        }
        
        // Cache management buttons
        const clearCacheBtn = document.getElementById('clearCacheBtn');
        if (clearCacheBtn) {
            clearCacheBtn.addEventListener('click', async () => {
                await this.clearAllCaches();
            });
            console.log('✅ Clear cache button event listener set up');
        } else {
            console.warn('⚠️ Clear cache button not found');
        }
        
        const refreshJSBtn = document.getElementById('refreshJSBtn');
        if (refreshJSBtn) {
            refreshJSBtn.addEventListener('click', async () => {
                await this.refreshJavaScriptFiles();
            });
            console.log('✅ Refresh JS button event listener set up');
        } else {
            console.warn('⚠️ Refresh JS button not found');
        }
        
        const nuclearRefreshBtn = document.getElementById('nuclearRefreshBtn');
        if (nuclearRefreshBtn) {
            nuclearRefreshBtn.addEventListener('click', async () => {
                await this.nuclearRefresh();
            });
            console.log('✅ Nuclear refresh button event listener set up');
        } else {
            console.warn('⚠️ Nuclear refresh button not found');
        }
        
        const serviceWorkerRefreshBtn = document.getElementById('serviceWorkerRefreshBtn');
        if (serviceWorkerRefreshBtn) {
            serviceWorkerRefreshBtn.addEventListener('click', async () => {
                await this.forceServiceWorkerUpdate();
            });
            console.log('✅ Force update button event listener set up');
        } else {
            console.warn('⚠️ Force update button not found');
        }

        // Rules categories
        const ruleCategories = document.querySelectorAll('.rule-category');
        if (ruleCategories.length > 0) {
            ruleCategories.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    this.loadRulesCategory(e.currentTarget.dataset.category);
                });
            });
            console.log('✅ Rules categories event listeners set up');
        } else {
            console.warn('⚠️ No rules categories found');
        }

        // Refresh buttons
        const refreshGames = document.getElementById('refreshGames');
        if (refreshGames) {
            refreshGames.addEventListener('click', async () => {
                await this.loadRefereeGamesData();
            });
            console.log('✅ Refresh games button event listener set up');
        } else {
            console.warn('⚠️ Refresh games button not found');
        }

        // Games filters
        const gamesTenantFilter = document.getElementById('gamesTenantFilter');
        if (gamesTenantFilter) {
            gamesTenantFilter.addEventListener('change', () => {
                if (this._isDomQuiet('games')) return;
                if (this.allGames) {
                    this.buildSectionFilter(this.allGames);
                    this.buildLeagueFilter(this.allGames);
                }
                this.filterGames();
            });
            console.log('✅ Tenant filter event listener set up');
        } else {
            console.warn('⚠️ Tenant filter not found');
        }

        const gamesSectionFilter = document.getElementById('gamesSectionFilter');
        if (gamesSectionFilter) {
            gamesSectionFilter.addEventListener('change', () => {
                if (this._isDomQuiet('games')) return;
                if (this.allGames) this.buildLeagueFilter(this.allGames);
                this.filterGames();
            });
            console.log('✅ Games section filter event listener set up');
        } else {
            console.warn('⚠️ Games section filter not found');
        }

        const leagueFilter = document.getElementById('gamesLeagueFilter');
        if (leagueFilter) {
            leagueFilter.addEventListener('change', () => {
                if (this._gamesFilterDomQuiet) return;
                this.filterGames();
            });
            console.log('✅ League filter event listener set up');
        } else {
            console.warn('⚠️ League filter not found');
        }

        const gamesRoleFilter = document.getElementById('gamesRoleFilter');
        if (gamesRoleFilter) {
            gamesRoleFilter.addEventListener('change', () => {
                if (this._isDomQuiet('games')) return;
                this.filterGames();
            });
            console.log('✅ Role filter event listener set up');
        } else {
            console.warn('⚠️ Role filter not found');
        }

        const gamesFromDateFilter = document.getElementById('gamesFromDateFilter');
        if (gamesFromDateFilter) {
            gamesFromDateFilter.addEventListener('change', () => {
                if (this._isDomQuiet('games')) return;
                this.filterGames();
            });
            console.log('✅ From date filter event listener set up');
        } else {
            console.warn('⚠️ From date filter not found');
        }

        const gamesToDateFilter = document.getElementById('gamesToDateFilter');
        if (gamesToDateFilter) {
            gamesToDateFilter.addEventListener('change', () => {
                if (this._isDomQuiet('games')) return;
                this.filterGames();
            });
            console.log('✅ To date filter event listener set up');
        } else {
            console.warn('⚠️ To date filter not found');
        }

        const includeArchivedGamesFilter = document.getElementById('includeArchivedGamesFilter');
        if (includeArchivedGamesFilter) {
            includeArchivedGamesFilter.addEventListener('change', () => {
                this.loadRefereeGamesData();
            });
            console.log('✅ Games history filter event listener set up');
        } else {
            console.warn('⚠️ Games history filter not found');
        }

        const includeRemovedGamesFilter = document.getElementById('includeRemovedGamesFilter');
        if (includeRemovedGamesFilter) {
            includeRemovedGamesFilter.addEventListener('change', async () => {
                await this.loadRefereeGamesData();
            });
            console.log('✅ Include removed games filter event listener set up');
        } else {
            console.warn('⚠️ Include removed games filter not found');
        }

        // Messages section event listeners
        const refreshMessages = document.getElementById('refreshMessages');
        if (refreshMessages) {
            refreshMessages.addEventListener('click', async () => {
                await this.loadMessagesData();
            });
            console.log('✅ Refresh messages button event listener set up');
        }

        const clearMessagesFilters = document.getElementById('clearMessagesFilters');
        if (clearMessagesFilters) {
            clearMessagesFilters.addEventListener('click', async () => {
                const directionFilter = document.getElementById('messagesDirectionFilter');
                const providerFilter = document.getElementById('messagesProviderFilter');
                const sourceFilter = document.getElementById('messagesSourceFilter');
                const fromDateFilter = document.getElementById('messagesFromDateFilter');
                const toDateFilter = document.getElementById('messagesToDateFilter');
                if (directionFilter) directionFilter.value = 'both';
                if (providerFilter) providerFilter.value = 'all';
                if (sourceFilter) sourceFilter.value = 'all';
                // Reset to default dates (7 days ago to today)
                if (fromDateFilter) {
                    const sevenDaysAgo = new Date();
                    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
                    fromDateFilter.value = sevenDaysAgo.toISOString().split('T')[0];
                }
                if (toDateFilter) {
                    const today = new Date();
                    toDateFilter.value = today.toISOString().split('T')[0];
                }
                await this.loadMessagesData();
            });
            console.log('✅ Clear messages filters button event listener set up');
        }

        const messagesDirectionFilter = document.getElementById('messagesDirectionFilter');
        if (messagesDirectionFilter) {
            messagesDirectionFilter.addEventListener('change', async () => {
                await this.loadMessagesData();
            });
            console.log('✅ Messages direction filter event listener set up');
        }

        const messagesProviderFilter = document.getElementById('messagesProviderFilter');
        if (messagesProviderFilter) {
            messagesProviderFilter.addEventListener('change', async () => {
                await this.loadMessagesData();
            });
            console.log('✅ Messages provider filter event listener set up');
        }

        const messagesSourceFilter = document.getElementById('messagesSourceFilter');
        if (messagesSourceFilter) {
            messagesSourceFilter.addEventListener('change', async () => {
                await this.loadMessagesData();
            });
            console.log('✅ Messages source filter event listener set up');
        }

        const messagesFromDateFilter = document.getElementById('messagesFromDateFilter');
        if (messagesFromDateFilter) {
            messagesFromDateFilter.addEventListener('change', async () => {
                await this.loadMessagesData();
            });
            console.log('✅ Messages from date filter event listener set up');
        }

        const messagesToDateFilter = document.getElementById('messagesToDateFilter');
        if (messagesToDateFilter) {
            messagesToDateFilter.addEventListener('change', async () => {
                await this.loadMessagesData();
            });
            console.log('✅ Messages to date filter event listener set up');
        }

        const gamesClearFiltersBtn = document.getElementById('gamesClearFilters');
        if (gamesClearFiltersBtn) {
            gamesClearFiltersBtn.addEventListener('click', () => {
                this.gamesClearFilters();
            });
            console.log('✅ Games Clear filters button event listener set up');
        } else {
            console.warn('⚠️ Games Clear filters button not found');
        }
        
        // Tables: sections / leagues come from PUBLIC_TABLES_FILTERS for the selected tenant
        const tablesTenantFilter = document.getElementById('tablesTenantFilter');
        if (tablesTenantFilter) {
            tablesTenantFilter.addEventListener('change', async () => {
                await this.bootstrapPublicTablesFilters();
                this._savePublicTablesFiltersToStorage();
            });
        }
        ['tablesSectionFilter', 'tablesLeagueFilter'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('change', async () => await this.loadTablesData());
        });
        const tablesRefreshBtn = document.getElementById('tablesRefresh');
        if (tablesRefreshBtn) tablesRefreshBtn.addEventListener('click', async () => await this.loadTablesData());
        const tablesClearBtn = document.getElementById('tablesClear');
        if (tablesClearBtn) tablesClearBtn.addEventListener('click', async () => {
            const tablesFieldIds = [
                'tablesTenantFilter',
                'tablesSectionFilter',
                'tablesLeagueFilter',
                'tablesSectionCombo',
                'tablesLeagueCombo',
            ];
            tablesFieldIds.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            await this.bootstrapPublicTablesFilters();
            try {
                localStorage.removeItem(this._LS_PUBLIC_TABLES_FILTERS);
            } catch {
                /* ignore */
            }
        });

        // Public games: sections / leagues / referees / fields come from PUBLIC_GAMES_FILTERS for the selected tenant
        const publicGamesTenantFilter = document.getElementById('publicGamesTenantFilter');
        if (publicGamesTenantFilter) {
            publicGamesTenantFilter.addEventListener('change', async () => {
                await this.bootstrapPublicGamesFilters();
                this._scheduleSavePublicGamesFilters();
            });
        }
        const publicGamesSectionFilter = document.getElementById('publicGamesSectionFilter');
        if (publicGamesSectionFilter) {
            publicGamesSectionFilter.addEventListener('change', () => {
                this.buildPublicGamesLeagueFilterFromMeta();
                this._scheduleSavePublicGamesFilters();
            });
        }
        const publicGamesLeagueFilter = document.getElementById('publicGamesLeagueFilter');
        if (publicGamesLeagueFilter) {
            publicGamesLeagueFilter.addEventListener('change', () => this._scheduleSavePublicGamesFilters());
        }
        const pubFromDate = document.getElementById('publicGamesFromDateFilter');
        if (pubFromDate) {
            pubFromDate.addEventListener('change', () => {
                this._clampPublicGamesToDateToFrom();
                this._scheduleSavePublicGamesFilters();
            });
        }
        const pubToDate = document.getElementById('publicGamesToDateFilter');
        if (pubToDate) {
            pubToDate.addEventListener('change', () => this._scheduleSavePublicGamesFilters());
        }
        ['publicGamesFieldValue', 'publicGamesRefereeValue'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('change', () => this._scheduleSavePublicGamesFilters());
        });
        // Game list loads only when user clicks רענן (publicGamesRefresh), not on other filter change
        this.setupPublicGamesComboboxes();
        this.setupSectionLeagueComboboxes();

        // Radius slider — disabled until geolocation succeeds (no shared location → no radius filter)
        const radiusSlider = document.getElementById('publicGamesRadiusSlider');
        const radiusLabel = document.getElementById('publicGamesRadiusLabel');
        if (radiusSlider) {
            this._disableRadiusSlider('מאמת מיקום...');
            radiusSlider.addEventListener('input', () => {
                if (radiusLabel) radiusLabel.textContent = this._radiusLabel(parseInt(radiusSlider.value, 10));
            });
            radiusSlider.addEventListener('change', () => {
                this.applyPublicGamesRadiusFilter();
                this._scheduleSavePublicGamesFilters();
            });
            this._ensureUserLocation();
        }

        const publicGamesRefreshBtn = document.getElementById('publicGamesRefresh');
        if (publicGamesRefreshBtn) publicGamesRefreshBtn.addEventListener('click', () => this.loadPublicGamesData());
        const publicGamesIncludeNoTime = document.getElementById('publicGamesIncludeNoTime');
        if (publicGamesIncludeNoTime) {
            publicGamesIncludeNoTime.addEventListener('change', () => {
                this._scheduleSavePublicGamesFilters();
                this._refreshPublicGamesTable();
            });
        }
        const publicGamesClearBtn = document.getElementById('publicGamesClear');
        if (publicGamesClearBtn) publicGamesClearBtn.addEventListener('click', () => {
            this._publicGamesSortColumn = 'date';
            this._publicGamesSortDir = 'asc';
            [
                'publicGamesTenantFilter',
                'publicGamesSectionFilter',
                'publicGamesLeagueFilter',
                'publicGamesSectionCombo',
                'publicGamesLeagueCombo',
            ].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            this.applyPublicGamesDefaultDateRange();
            const fieldCombo = document.getElementById('publicGamesFieldCombo');
            const fieldHidden = document.getElementById('publicGamesFieldValue');
            if (fieldCombo) fieldCombo.value = '';
            if (fieldHidden) fieldHidden.value = '';
            const refCombo = document.getElementById('publicGamesRefereeCombo');
            const refHidden = document.getElementById('publicGamesRefereeValue');
            if (refCombo) refCombo.value = '';
            if (refHidden) refHidden.value = '';
            if (radiusSlider && !radiusSlider.disabled) {
                radiusSlider.value = 5;
                if (radiusLabel) radiusLabel.textContent = this._radiusLabel(5);
            }
            const incNoTimeEl = document.getElementById('publicGamesIncludeNoTime');
            if (incNoTimeEl) incNoTimeEl.checked = true;
            this.bootstrapPublicGamesFilters();
            try {
                localStorage.removeItem(this._LS_PUBLIC_GAMES_FILTERS);
            } catch {
                /* ignore */
            }
        });

        const publicGamesList = document.getElementById('publicGamesList');
        if (publicGamesList && !publicGamesList._publicGamesTableBound) {
            publicGamesList._publicGamesTableBound = true;
            const togglePublicGameRow = (tr) => {
                const detail = tr.nextElementSibling;
                if (!detail || !detail.classList.contains('public-games-table__detail-row')) return;
                detail.hidden = !detail.hidden;
                tr.setAttribute('aria-expanded', detail.hidden ? 'false' : 'true');
            };
            publicGamesList.addEventListener('click', (e) => {
                const openLeagueBtn = e.target.closest('[data-action="open-league-tables"]');
                if (openLeagueBtn && publicGamesList.contains(openLeagueBtn)) {
                    e.preventDefault();
                    e.stopPropagation();
                    let tenantKey = '';
                    let section = '';
                    let leagueName = '';
                    try {
                        const at = openLeagueBtn.getAttribute('data-tenant');
                        const asec = openLeagueBtn.getAttribute('data-section');
                        const al = openLeagueBtn.getAttribute('data-league');
                        if (at != null) tenantKey = decodeURIComponent(at);
                        if (asec != null) section = decodeURIComponent(asec);
                        if (al != null) leagueName = decodeURIComponent(al);
                    } catch {
                        /* ignore */
                    }
                    this.openPublicTournamentTableFloatingPanel({ tenantKey, section, leagueName });
                    return;
                }
                if (e.target.closest('a.public-games-table__field-link')) {
                    e.stopPropagation();
                    return;
                }
                const th = e.target.closest('th[data-public-games-sort]');
                if (th && publicGamesList.contains(th)) {
                    e.preventDefault();
                    e.stopPropagation();
                    const col = th.dataset.publicGamesSort;
                    if (this._publicGamesSortColumn === col) {
                        this._publicGamesSortDir = this._publicGamesSortDir === 'asc' ? 'desc' : 'asc';
                    } else {
                        this._publicGamesSortColumn = col;
                        this._publicGamesSortDir = 'asc';
                    }
                    this._refreshPublicGamesTable();
                    this._savePublicGamesFiltersToStorage();
                    return;
                }
                const tr = e.target.closest('tr.public-games-table__main-row');
                if (!tr || !publicGamesList.contains(tr)) return;
                togglePublicGameRow(tr);
            });
            publicGamesList.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                const tr = e.target.closest('tr.public-games-table__main-row');
                if (!tr || !publicGamesList.contains(tr)) return;
                e.preventDefault();
                togglePublicGameRow(tr);
            });
        }

        const refereeGamesList = document.getElementById('refereeGamesList');
        if (refereeGamesList && !refereeGamesList._refereeNameClickBound) {
            refereeGamesList._refereeNameClickBound = true;
            refereeGamesList.addEventListener('click', async (e) => {
                const btn = e.target.closest('.referee-games-tab-name');
                if (!btn || !refereeGamesList.contains(btn)) return;
                e.preventDefault();
                const name = btn.getAttribute('data-referee-name') || '';
                const phone = btn.getAttribute('data-referee-phone') || '';
                let gameTenant = '';
                try {
                    const enc = btn.getAttribute('data-game-tenant');
                    if (enc) gameTenant = decodeURIComponent(enc);
                } catch {
                    gameTenant = btn.getAttribute('data-game-tenant') || '';
                }
                await this.openRefereeGamesFloatingPanel(name, phone, gameTenant);
            });
        }

        const refereePanelRoot = document.getElementById('refereeGamesFloatingPanel');
        const refereePanelBody = document.getElementById('refereeGamesFloatingPanelBody');
        if (refereePanelBody && !refereePanelBody._refereePanelGameTableBound) {
            refereePanelBody._refereePanelGameTableBound = true;
            const toggleRefPanelRow = (tr) => {
                const detail = tr.nextElementSibling;
                if (!detail || !detail.classList.contains('public-games-table__detail-row')) return;
                detail.hidden = !detail.hidden;
                tr.setAttribute('aria-expanded', detail.hidden ? 'false' : 'true');
            };
            refereePanelBody.addEventListener('click', (e) => {
                const openLeagueBtn = e.target.closest('[data-action="open-league-tables"]');
                if (openLeagueBtn && refereePanelBody.contains(openLeagueBtn)) {
                    e.preventDefault();
                    e.stopPropagation();
                    let tenantKey = '';
                    let section = '';
                    let leagueName = '';
                    try {
                        const at = openLeagueBtn.getAttribute('data-tenant');
                        const asec = openLeagueBtn.getAttribute('data-section');
                        const al = openLeagueBtn.getAttribute('data-league');
                        if (at != null) tenantKey = decodeURIComponent(at);
                        if (asec != null) section = decodeURIComponent(asec);
                        if (al != null) leagueName = decodeURIComponent(al);
                    } catch {
                        /* ignore */
                    }
                    this.openPublicTournamentTableFloatingPanel({ tenantKey, section, leagueName });
                    return;
                }
                const th = e.target.closest('th[data-referee-panel-sort]');
                if (th && refereePanelBody.contains(th)) {
                    e.preventDefault();
                    e.stopPropagation();
                    const col = th.dataset.refereePanelSort;
                    if (this._refereeGamesPanelSortColumn === col) {
                        this._refereeGamesPanelSortDir =
                            this._refereeGamesPanelSortDir === 'asc' ? 'desc' : 'asc';
                    } else {
                        this._refereeGamesPanelSortColumn = col;
                        this._refereeGamesPanelSortDir = 'asc';
                    }
                    this._renderRefereeGamesFloatingPanelTable();
                    return;
                }
                const tr = e.target.closest('tr.public-games-table__main-row');
                if (!tr || !refereePanelBody.contains(tr)) return;
                toggleRefPanelRow(tr);
            });
            refereePanelBody.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                const tr = e.target.closest('tr.public-games-table__main-row');
                if (!tr || !refereePanelBody.contains(tr)) return;
                e.preventDefault();
                toggleRefPanelRow(tr);
            });
        }
        if (refereePanelRoot && !refereePanelRoot._refereePanelDismissBound) {
            refereePanelRoot._refereePanelDismissBound = true;
            refereePanelRoot.addEventListener('click', (e) => {
                const dismiss = e.target.closest('[data-referee-panel-dismiss]');
                if (dismiss && refereePanelRoot.contains(dismiss)) {
                    e.preventDefault();
                    this.closeRefereeGamesFloatingPanel();
                }
            });
        }
        if (!this._refereeGamesPanelEscapeBound) {
            this._refereeGamesPanelEscapeBound = true;
            document.addEventListener('keydown', (e) => {
                if (e.key !== 'Escape') return;
                const tPanel = document.getElementById('publicTournamentTableFloatingPanel');
                if (tPanel && !tPanel.hidden) {
                    this.closePublicTournamentTableFloatingPanel();
                    return;
                }
                const p = document.getElementById('refereeGamesFloatingPanel');
                if (p && !p.hidden) this.closeRefereeGamesFloatingPanel();
            });
        }

        const publicTournamentPanelRoot = document.getElementById('publicTournamentTableFloatingPanel');
        if (publicTournamentPanelRoot && !publicTournamentPanelRoot._publicTournamentPanelDismissBound) {
            publicTournamentPanelRoot._publicTournamentPanelDismissBound = true;
            publicTournamentPanelRoot.addEventListener('click', (e) => {
                const dismiss = e.target.closest('[data-public-tournament-panel-dismiss]');
                if (dismiss && publicTournamentPanelRoot.contains(dismiss)) {
                    e.preventDefault();
                    this.closePublicTournamentTableFloatingPanel();
                }
            });
        }

        this.ensurePublicTournamentPanelSortListener();

        // Chat section auto-hide event listeners
        this.setupChatSectionEventListeners();
        
        console.log('🔧 Event listeners setup complete');
        
        // Pair button
        const pairBtn = document.getElementById('pairBtn');
        if (pairBtn) {
            pairBtn.addEventListener('click', async () => {
                console.log('🔐 Pair button clicked!');
                const preOpenedPairWindow = this.windowManager.openWindow('pairWindow', 'about:blank');
                await this.sendPairMessage(preOpenedPairWindow);
            });
            console.log('✅ Pair button event listener set up');
        } else {
            console.warn('⚠️ Pair button not found');
        }

        // Show pair button (from not logged in state)
        const showPairBtn = document.getElementById('showPairBtn');
        if (showPairBtn) {
            showPairBtn.addEventListener('click', () => {
                this.showPairSection();
            });
            console.log('✅ Show pair button event listener set up');
        } else {
            console.warn('⚠️ Show pair button not found');
        }

        // Manual authentication check button
        const manualAuthCheckBtn = document.getElementById('manualAuthCheckBtn');
        if (manualAuthCheckBtn) {
            manualAuthCheckBtn.addEventListener('click', async () => {
                await this.manualAuthCheck();
            });
            console.log('✅ Manual auth check button event listener set up');
        } else {
            console.warn('⚠️ Manual auth check button not found');
        }

        // Unpair button (if exists)
        const unpairBtn = document.getElementById('unpairBtn');
        if (unpairBtn) {
            unpairBtn.addEventListener('click', () => {
                this.manualUnpair();
            });
            console.log('✅ Unpair button event listener set up');
        } else {
            console.warn('⚠️ Unpair button not found');
        }

        // Reviews filters
        const reviewsTenantFilter = document.getElementById('reviewsTenantFilter');
        if (reviewsTenantFilter) {
            reviewsTenantFilter.addEventListener('change', () => {
                if (this._isDomQuiet('reviews')) return;
                this.filterReviews();
            });
            console.log('✅ Review tenant filter event listener set up');
        } else {
            console.warn('⚠️ Review tenant filter not found');
        }

        const refereeFilter = document.getElementById('refereeFilter');
        if (refereeFilter) {
            refereeFilter.addEventListener('change', () => {
                if (this._isDomQuiet('reviews')) return;
                this.filterReviews();
            });
            console.log('✅ Referee filter event listener set up');
        } else {
            console.warn('⚠️ Referee filter not found');
        }

        const reviewsRoleFilter = document.getElementById('reviewsRoleFilter');
        if (reviewsRoleFilter) {
            reviewsRoleFilter.addEventListener('change', () => {
                if (this._isDomQuiet('reviews')) return;
                this.filterReviews();
            });
            console.log('✅ Reviews role filter event listener set up');
        } else {
            console.warn('⚠️ Reviews role filter not found');
        }

        const ratingFilter = document.getElementById('ratingFilter');
        if (ratingFilter) {
            ratingFilter.addEventListener('change', () => {
                if (this._isDomQuiet('reviews')) return;
                this.filterReviews();
            });
            console.log('✅ Rating filter event listener set up');
        } else {
            console.warn('⚠️ Rating filter not found');
        }

        const clearReviewFiltersBtn = document.getElementById('clearReviewFilters');
        if (clearReviewFiltersBtn) {
            clearReviewFiltersBtn.addEventListener('click', () => {
                this.clearReviewFilters();
            });
            console.log('✅ Clear review filters button event listener set up');
        } else {
            console.warn('⚠️ Clear review filters button not found');
        }

        // Fields filters
        const fieldsTextFilter = document.getElementById('fieldsTextFilter');
        if (fieldsTextFilter) {
            // Allow Enter key to trigger search
            fieldsTextFilter.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.searchFields();
                }
            });
            console.log('✅ Fields text filter event listener set up');
        } else {
            console.warn('⚠️ Fields text filter not found');
        }

        const searchFieldsBtn = document.getElementById('searchFieldsBtn');
        if (searchFieldsBtn) {
            searchFieldsBtn.addEventListener('click', () => {
                this.searchFields();
            });
            console.log('✅ Search fields button event listener set up');
        } else {
            console.warn('⚠️ Search fields button not found');
        }

        const clearFieldsFiltersBtn = document.getElementById('clearFieldsFilters');
        if (clearFieldsFiltersBtn) {
            clearFieldsFiltersBtn.addEventListener('click', () => {
                this.clearFieldsFilters();
            });
            console.log('✅ Clear fields filters button event listener set up');
        } else {
            console.warn('⚠️ Clear fields filters button not found');
        }

        const showClosedFieldsFilter = document.getElementById('showClosedFieldsFilter');
        if (showClosedFieldsFilter) {
            showClosedFieldsFilter.addEventListener('change', () => {
                this.filterFieldsAndDisplay();
            });
            console.log('✅ Show closed fields filter event listener set up');
        } else {
            console.warn('⚠️ Show closed fields filter not found');
        }

        // Availability section
        const updateAvailabilityBtn = document.getElementById('updateAvailabilityBtn');
        if (updateAvailabilityBtn) {
            updateAvailabilityBtn.addEventListener('click', async () => {
                await this.updateAvailability();
            });
            console.log('✅ Update availability button event listener set up');
        } else {
            console.warn('⚠️ Update availability button not found');
        }

        const prevWeekBtn = document.getElementById('prevWeekBtn');
        if (prevWeekBtn) {
            prevWeekBtn.addEventListener('click', async () => {
                await this.navigateToPreviousWeek();
            });
            console.log('✅ Previous week button event listener set up');
        } else {
            console.warn('⚠️ Previous week button not found');
        }

        const nextWeekBtn = document.getElementById('nextWeekBtn');
        if (nextWeekBtn) {
            nextWeekBtn.addEventListener('click', async () => {
                await this.navigateToNextWeek();
            });
            console.log('✅ Next week button event listener set up');
        } else {
            console.warn('⚠️ Next week button not found');
        }

        // Setup save button event listener
        const saveBtn = document.getElementById('saveUserDetailsBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', async () => await this.saveUserDetails());
            console.log('✅ Save user details button event listener set up');
        } else {
            console.warn('⚠️ Save user details button not found');
        }

        // Setup save passwords button event listener
        const savePasswordsBtn = document.getElementById('savePasswordsBtn');
        if (savePasswordsBtn) {
            savePasswordsBtn.addEventListener('click', async () => await this.savePasswords());
            console.log('✅ Save passwords button event listener set up');
        } else {
            console.warn('⚠️ Save passwords button not found');
        }

        const adminTenantFilter = document.getElementById('adminTenantFilter');
        if (adminTenantFilter) {
            adminTenantFilter.addEventListener('change', async () => {
                await this.loadReferees();
            });
            console.log('✅ Admin tenant filter event listener set up');
        } else {
            console.warn('⚠️ Admin tenant filter not found');
        }

        const adminApplyBtn = document.getElementById('adminApplyBtn');
        if (adminApplyBtn) {
            adminApplyBtn.addEventListener('click', async () => {
                await this.adminApplyRefereeSelection();
            });
            console.log('✅ Admin apply button event listener set up');
        } else {
            console.warn('⚠️ Admin apply button not found');
        }

        const adminResetBtn = document.getElementById('adminResetBtn');
        if (adminResetBtn) {
            adminResetBtn.addEventListener('click', async () => {
                await this.adminResetRefereeSelection();
            });
            console.log('✅ Admin reset button event listener set up');
        } else {
            console.warn('⚠️ Admin reset button not found');
        }

        // Admin sub-tabs: Templates | Notifications
        document.querySelectorAll('.admin-subtab').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.getAttribute('data-admin-tab');
                document.querySelectorAll('.admin-subtab').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
                btn.classList.add('active');
                btn.setAttribute('aria-selected', 'true');
                document.querySelectorAll('.admin-subsection').forEach(sec => {
                    const contentTab = sec.getAttribute('data-admin-tab-content');
                    if (contentTab === tab) sec.classList.remove('hidden');
                    else sec.classList.add('hidden');
                });
            });
        });

        const refereeTemplatesApplyBtn = document.getElementById('refereeTemplatesApplyBtn');
        if (refereeTemplatesApplyBtn) {
            refereeTemplatesApplyBtn.addEventListener('click', async () => await this.loadRefereeTemplates());
        }
        const refereeTemplatesMobileFilter = document.getElementById('refereeTemplatesMobile');
        if (refereeTemplatesMobileFilter) {
            refereeTemplatesMobileFilter.addEventListener('change', () => {
                if (this._templatesGridData) {
                    this.renderRefereeTemplatesGrid(this.getSortedTemplatesData());
                }
            });
        }
        const notificationsApplyBtn = document.getElementById('notificationsApplyBtn');
        if (notificationsApplyBtn) {
            notificationsApplyBtn.addEventListener('click', async () => await this.loadNotifications());
        }
        const notificationsMobileFilter = document.getElementById('notificationsMobile');
        if (notificationsMobileFilter) {
            notificationsMobileFilter.addEventListener('change', () => {
                if (this._notificationsGridData) {
                    this.renderNotificationsGrid(this.getSortedNotificationsData());
                }
            });
        }

        // iOS Safari viewport fix for header/nav positioning
        this.setupFilterClearButtons();
        this.setupIOSViewportFix();
    }

    _dispatchFilterChange(el) {
        if (!el) return;
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    /** Small × beside each filter to clear only that control. */
    setupFilterClearButtons() {
        if (this._filterClearButtonsBound) return;
        this._filterClearButtonsBound = true;

        const sel = (id) => {
            const el = document.getElementById(id);
            if (!el) return;
            this._attachFilterClearButton(el, {
                isActive: () => !!String(el.value || '').trim(),
                onClear: () => {
                    el.value = '';
                    this._dispatchFilterChange(el);
                },
            });
        };

        sel('gamesTenantFilter');
        sel('gamesSectionFilter');
        sel('gamesLeagueFilter');
        sel('gamesRoleFilter');
        sel('gamesFromDateFilter');
        sel('gamesToDateFilter');

        sel('reviewsTenantFilter');
        sel('refereeFilter');
        sel('reviewsRoleFilter');
        sel('ratingFilter');

        const dirF = document.getElementById('messagesDirectionFilter');
        if (dirF) {
            this._attachFilterClearButton(dirF, {
                isActive: () => dirF.value !== 'both',
                onClear: () => {
                    dirF.value = 'both';
                    this._dispatchFilterChange(dirF);
                },
            });
        }
        const provF = document.getElementById('messagesProviderFilter');
        if (provF) {
            this._attachFilterClearButton(provF, {
                isActive: () => provF.value !== 'all',
                onClear: () => {
                    provF.value = 'all';
                    this._dispatchFilterChange(provF);
                },
            });
        }
        const srcF = document.getElementById('messagesSourceFilter');
        if (srcF) {
            this._attachFilterClearButton(srcF, {
                isActive: () => srcF.value !== 'all',
                onClear: () => {
                    srcF.value = 'all';
                    this._dispatchFilterChange(srcF);
                },
            });
        }

        const fieldsText = document.getElementById('fieldsTextFilter');
        if (fieldsText) {
            this._attachFilterClearButton(fieldsText, {
                isActive: () => !!String(fieldsText.value || '').trim(),
                onClear: () => {
                    fieldsText.value = '';
                    this.filterFieldsAndDisplay();
                },
            });
        }

        sel('adminTenantFilter');
        sel('adminRefereeFilter');

        ['refereeTemplatesTenant', 'refereeTemplatesAction', 'refereeTemplatesStatus', 'refereeTemplatesMobile'].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            this._attachFilterClearButton(el, {
                isActive: () => !!String(el.value || '').trim(),
                onClear: async () => {
                    el.value = '';
                    await this.loadRefereeTemplates();
                },
            });
        });
        const dtTpl = document.getElementById('refereeTemplatesDateType');
        if (dtTpl) {
            this._attachFilterClearButton(dtTpl, {
                isActive: () => dtTpl.value !== 'created',
                onClear: async () => {
                    dtTpl.value = 'created';
                    await this.loadRefereeTemplates();
                },
            });
        }

        [
            'notificationsTenant',
            'notificationsTarget',
            'notificationsId',
            'notificationsType',
            'notificationsStatus',
            'notificationsMobile',
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            this._attachFilterClearButton(el, {
                isActive: () => !!String(el.value || '').trim(),
                onClear: async () => {
                    el.value = '';
                    await this.loadNotifications();
                },
            });
        });
        const dtNotif = document.getElementById('notificationsDateType');
        if (dtNotif) {
            this._attachFilterClearButton(dtNotif, {
                isActive: () => dtNotif.value !== 'created',
                onClear: async () => {
                    dtNotif.value = 'created';
                    await this.loadNotifications();
                },
            });
        }

        sel('tablesTenantFilter');

        this._attachFilterClearForComboboxBlock(
            'tablesSectionCombobox',
            'tablesSectionFilter',
            'tablesSectionCombo',
            'tablesSectionList',
            () => this.buildTablesLeagueFilterFromMeta()
        );
        this._attachFilterClearForComboboxBlock(
            'tablesLeagueCombobox',
            'tablesLeagueFilter',
            'tablesLeagueCombo',
            'tablesLeagueList',
            null
        );

        const pubTenant = document.getElementById('publicGamesTenantFilter');
        if (pubTenant) {
            this._attachFilterClearButton(pubTenant, {
                isActive: () => !!String(pubTenant.value || '').trim(),
                onClear: async () => {
                    pubTenant.value = '';
                    this._dispatchFilterChange(pubTenant);
                },
            });
        }

        this._attachFilterClearForComboboxBlock(
            'publicGamesSectionCombobox',
            'publicGamesSectionFilter',
            'publicGamesSectionCombo',
            'publicGamesSectionList',
            null
        );
        this._attachFilterClearForComboboxBlock(
            'publicGamesLeagueCombobox',
            'publicGamesLeagueFilter',
            'publicGamesLeagueCombo',
            'publicGamesLeagueList',
            null
        );
        this._attachFilterClearForComboboxBlock(
            'publicGamesFieldCombobox',
            'publicGamesFieldValue',
            'publicGamesFieldCombo',
            'publicGamesFieldList',
            null
        );
        this._attachFilterClearForComboboxBlock(
            'publicGamesRefereeCombobox',
            'publicGamesRefereeValue',
            'publicGamesRefereeCombo',
            'publicGamesRefereeList',
            null
        );

        ['publicGamesFromDateFilter', 'publicGamesToDateFilter'].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            this._attachFilterClearButton(el, {
                isActive: () => !!String(el.value || '').trim(),
                onClear: () => {
                    el.value = '';
                    this._dispatchFilterChange(el);
                    this._scheduleSavePublicGamesFilters();
                    this._refreshPublicGamesTable();
                },
            });
        });

        const rad = document.getElementById('publicGamesRadiusSlider');
        if (rad) {
            this._attachFilterClearButton(rad, {
                isActive: () => !rad.disabled && String(rad.value) !== '5',
                onClear: () => {
                    if (rad.disabled) return;
                    rad.value = '5';
                    const lab = document.getElementById('publicGamesRadiusLabel');
                    if (lab) lab.textContent = this._radiusLabel(5);
                    this._dispatchFilterChange(rad);
                },
            });
        }
    }

    _attachFilterClearForComboboxBlock(blockId, hiddenId, comboId, listId, afterClear) {
        const block = document.getElementById(blockId);
        const hidden = document.getElementById(hiddenId);
        const combo = document.getElementById(comboId);
        const list = document.getElementById(listId);
        if (!block || !hidden || !combo || !list) return;

        this._attachFilterClearButton(block, {
            isActive: () =>
                !!String(hidden.value || '').trim() || !!String(combo.value || '').trim(),
            onClear: () => {
                hidden.value = '';
                combo.value = '';
                this._syncComboboxLabelFromHidden(hidden, combo, list);
                this._dispatchFilterChange(hidden);
                if (typeof afterClear === 'function') afterClear();
            },
            syncAlso: [hidden, combo],
        });
    }

    _attachFilterClearButton(el, { isActive, onClear, syncAlso = [] }) {
        if (!el || el.closest('.filter-field-clear-wrap')) return;
        const parent = el.parentNode;
        if (!parent) return;

        const wrap = document.createElement('span');
        wrap.className = 'filter-field-clear-wrap';
        if (el.tagName === 'INPUT' && el.type === 'range') {
            wrap.classList.add('filter-field-clear-wrap--range');
        }
        parent.insertBefore(wrap, el);
        wrap.appendChild(el);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'filter-clear-x';
        btn.setAttribute('aria-label', 'נקה שדה');
        btn.innerHTML = '×';

        const syncBtn = () => {
            const active = typeof isActive === 'function' ? isActive() : !!isActive;
            btn.hidden = !active;
        };

        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            onClear();
            syncBtn();
        });

        wrap.appendChild(btn);

        el.addEventListener('change', syncBtn);
        if (el.tagName === 'INPUT' && (el.type === 'text' || el.type === 'search' || el.type === 'range')) {
            el.addEventListener('input', syncBtn);
        }
        syncAlso.forEach((node) => {
            if (node && node !== el) {
                node.addEventListener('change', syncBtn);
                if (node.tagName === 'INPUT' && (node.type === 'text' || node.type === 'search')) {
                    node.addEventListener('input', syncBtn);
                }
            }
        });
        syncBtn();
    }

    setupIOSViewportFix() {
        // Check if we're on iOS Safari
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
        const isSafari = /Safari/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent);
        
        if (isIOS && isSafari) {
            console.log('🍎 iOS Safari detected, setting up viewport fix');
            
            // Function to update header height
            const updateHeaderHeight = () => {
                const header = document.querySelector('.app-header');
                const nav = document.querySelector('.app-nav');
                
                if (header && nav) {
                    const headerHeight = header.offsetHeight;
                    document.documentElement.style.setProperty('--header-height', `${headerHeight}px`);
                    console.log(`📏 Updated header height to: ${headerHeight}px`);
                }
            };
            
            // Update on load
            updateHeaderHeight();
            
            // Update on resize (handles orientation changes)
            window.addEventListener('resize', () => {
                updateHeaderHeight();
                // Also adjust title font size on resize
                const nextGameTitle = document.getElementById('nextGameTitle');
                if (nextGameTitle) {
                    this.adjustElementFontSize(nextGameTitle);
                }
                const nextGameStatus = document.getElementById('nextGameStatus');
                if (nextGameStatus) {
                    this.adjustElementFontSize(nextGameStatus);
                }
            });
            
            // Update on scroll (handles iOS Safari's dynamic viewport)
            let scrollTimeout;
            window.addEventListener('scroll', () => {
                clearTimeout(scrollTimeout);
                scrollTimeout = setTimeout(updateHeaderHeight, 100);
            });
            
            // Update when viewport changes (iOS Safari specific)
            window.addEventListener('orientationchange', () => {
                setTimeout(() => {
                    updateHeaderHeight();
                    // Also adjust title font size on orientation change
                    const nextGameTitle = document.getElementById('nextGameTitle');
                    if (nextGameTitle) {
                        this.adjustElementFontSize(nextGameTitle);
                    }
                    const nextGameStatus = document.getElementById('nextGameStatus');
                    if (nextGameStatus) {
                        this.adjustElementFontSize(nextGameStatus);
                    }
                    }, 500);
            });
            
            console.log('✅ iOS viewport fix setup complete');
        }
    }

    async checkAuthenticationStatus(manualTrigger=false) {
        console.log('🔍 Checking authentication status...');
        try {
            // First check if API server is reachable
            const apiServerHealthy = await this.checkApiServerHealth();
            if (!apiServerHealthy) {
                console.warn('⚠️ API server is not reachable, skipping authentication check');
                // Show user-friendly message
                this.showToast('שרת לא זמין כרגע, נסה שוב מאוחר יותר', 'warning');
                // Don't unpair if server is just unreachable
                return;
            }
            
            // First validate push subscription
            const hasValidPushSubscription = await this.validatePushSubscription();
            console.log('🔍 Has valid subscription:', hasValidPushSubscription);
            
            if (this.pushNotificationsMust && !hasValidPushSubscription) {
                console.log('❌ No valid push subscription, stopping auth check');
                return;
            }
            
            const pushSubscription = await this.getCurrentPushSubscription();
            console.log('🔍 Current push subscription:', pushSubscription);
            const clientIdentifier = await this.getClientIdentifier();
            console.log('🔍 Current client unique idenitifier:', clientIdentifier);
            const token = await this.getJwtToken()
            console.log('🔍 Current JWT token:', token);

            // Check if we have the minimum requirements for authentication
            const hasMinimumRequirements = !!clientIdentifier && 
                (!this.pushNotificationsMust || !!pushSubscription) &&
                !!token;
            
            console.log('🔍 Authentication requirements check:', {
                hasClientIdentifier: !!clientIdentifier,
                pushNotificationsMust: this.pushNotificationsMust,
                hasPushSubscription: !!pushSubscription,
                hasMinimumRequirements
            });

            if (hasMinimumRequirements) {
                // Check with server if this subscription is authenticated
                console.log('🌐 Checking with server...');

                try {
                    const response = await this.refreshTokenService.makeApiRequest({
                        url: this.getConfig('ENDPOINTS.CHECK_AUTH'), 
                        options: {
                            method: 'POST',
                            body: JSON.stringify({
                                ...this.getClientInfo()
                            })
                        }
                    });

                    console.log('🌐 Server response:', response);
                    if (response.ok) {
                        const data = await response.json();
                        console.log('🔍 Server auth data:', data);
                        if (data.authenticated && !this.isAuthenticated) {
                            console.log('✅ User authenticated, updating state');
                            await this.handleSuccessfulAuthentication(manualTrigger);
                            return;
                        } else if (!data.authenticated && (this.isAuthenticated || this.currentAuthenticationStatus === null)) {
                            console.log('❌ User no longer authenticated, logging out');
                            this.currentUser = null;
                            
                            await this.handleAuthenticationFailure();
                            return;
                        }
                    } else {
                        console.warn('⚠️ Server returned non-OK status:', response.status, response.statusText);
                    }
                } catch (fetchError) {
                    console.error('❌ Network error during authentication check:', fetchError)
                    console.error('❌ Error details:', {
                        url: this.getConfig('ENDPOINTS.CHECK_AUTH'),
                        error: fetchError.message,
                        type: fetchError.name
                    })
                    
                    // Check if it's a mixed content error
                    if (fetchError.message.includes('mixed content') || fetchError.message.includes('blocked')) {
                        console.error('❌ Mixed content error detected - API URL should use HTTPS');
                        this.showToast('שגיאת תצורה - יש להשתמש ב-HTTPS', 'error');
                    }
                    
                    // Check if it's a CORS error
                    if (fetchError.message.includes('CORS') || fetchError.message.includes('cross-origin')) {
                        console.error('❌ CORS error detected - check server CORS configuration');
                        this.showToast('שגיאת CORS - יש לבדוק הגדרות השרת', 'error');
                    }
                    
                    // Check if it's a timeout error
                    if (fetchError.message.includes('timeout') || fetchError.message.includes('Request timeout')) {
                        console.error('❌ Request timeout - server may be slow or unreachable');
                        this.showToast('פג תוקף הבקשה - השרת איטי או לא זמין', 'warning');
                    }
                    
                    // Check if it's a network error
                    if (fetchError.message.includes('Failed to fetch') || fetchError.message.includes('NetworkError')) {
                        console.error('❌ Network error - check internet connection and server status');
                        this.showToast('שגיאת רשת - בדוק חיבור לאינטרנט וסטטוס השרת', 'warning');
                    }
                    
                    throw fetchError; // Re-throw to be handled by outer catch
                }
            } else if (this.isAuthenticated) {
                // No subscription but was authenticated - unpair
                console.log('❌ No subscription but was authenticated, logging out');
                await this.handleAuthenticationFailure();
            } else {
                // Not authenticated and missing requirements - try to resolve
                console.log('🔍 Not authenticated and missing requirements, attempting to resolve...');
                
                if (this.pushhNotificationPermission === true && !pushSubscription) {
                    console.log('📱 Notification permission granted but no push subscription - attempting to create one');
                    try {
                        const newSubscription = await this.subscribeToPushNotifications();
                        if (newSubscription) {
                            console.log('✅ Successfully created new push subscription, retrying authentication');
                            // Retry authentication with new subscription
                            setTimeout(async () => {
                                await this.checkAuthenticationStatus();
                            }, 1000);
                            return;
                        }
                    } catch (subscriptionError) {
                        console.error('❌ Failed to create push subscription:', subscriptionError);
                    }
                }
                
                // If we still can't resolve, show not authenticated state
                console.log('🔍 Setting not authenticated state');
                this.setAuthenticatedState(false);
            }
        } catch (error) {
            console.error('💥 Error checking authentication status:', error);
            // On error, if was authenticated, unpair
            if (this.isAuthenticated) {
                await this.handleAuthenticationFailure();
            }
        } finally {
            this.lastAuthenticationStatus = this.currentAuthenticationStatus;
            // Any early return (API down, push required, etc.) or missed branch must not leave splash playing forever
            if (!this.authenticationChecked) {
                this.authenticationChecked = true;
                this.hideSplashVideo();
            }
        }

    }

    initializeSplashVideo() {
        // Initialize splash video with mobile-friendly autoplay handling
        const splashVideo = document.getElementById('splashVideo');
        if (!splashVideo) return;
        
        // Detect Safari (including iOS Safari)
        const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent) || 
                        /iPad|iPhone|iPod/.test(navigator.userAgent);
        
        console.log('🎬 Initializing splash video, isSafari:', isSafari);
        
        // Set video properties for mobile compatibility (especially Safari)
        splashVideo.muted = true;
        splashVideo.playsInline = true;
        splashVideo.setAttribute('playsinline', '');
        splashVideo.setAttribute('webkit-playsinline', '');
        splashVideo.setAttribute('x-webkit-airplay', 'allow');
        
        // For Safari, set additional properties
        if (isSafari) {
            splashVideo.setAttribute('preload', 'auto');
            // Force muted for Safari
            splashVideo.muted = true;
            splashVideo.volume = 0;
        }
        
        // Try to play immediately
        const tryPlay = () => {
            // Ensure video is still muted (Safari requirement)
            splashVideo.muted = true;
            splashVideo.volume = 0;
            
            const playPromise = splashVideo.play();
            if (playPromise !== undefined) {
                playPromise
                    .then(() => {
                        console.log('✅ Splash video started playing');
                        // For Safari, ensure it keeps playing
                        if (isSafari) {
                            splashVideo.muted = true;
                            splashVideo.volume = 0;
                        }
                    })
                    .catch(error => {
                        console.warn('⚠️ Autoplay prevented, will try on user interaction:', error);
                        // Try again on first user interaction
                        const playOnInteraction = () => {
                            splashVideo.muted = true;
                            splashVideo.volume = 0;
                            splashVideo.play().catch(err => {
                                console.warn('Could not play video on interaction:', err);
                            });
                            // Remove listeners after first interaction
                            document.removeEventListener('touchstart', playOnInteraction);
                            document.removeEventListener('touchend', playOnInteraction);
                            document.removeEventListener('click', playOnInteraction);
                            document.removeEventListener('mousedown', playOnInteraction);
                        };
                        // Add multiple event listeners for better Safari support
                        document.addEventListener('touchstart', playOnInteraction, { once: true, passive: true });
                        document.addEventListener('touchend', playOnInteraction, { once: true, passive: true });
                        document.addEventListener('click', playOnInteraction, { once: true });
                        document.addEventListener('mousedown', playOnInteraction, { once: true });
                    });
            }
        };
        
        // For Safari, try multiple approaches with more aggressive retries
        if (isSafari) {
            // Safari needs the video to be loaded first
            const safariPlay = () => {
                splashVideo.muted = true;
                splashVideo.volume = 0;
                // Don't reload if already loaded
                if (splashVideo.readyState < 1) {
                    splashVideo.load();
                }
                
                // Try multiple times with delays
                const attemptPlay = (attempt = 0) => {
                    if (attempt > 3) return; // Max 3 attempts
                    
                    setTimeout(() => {
                        splashVideo.muted = true;
                        splashVideo.volume = 0;
                        const playPromise = splashVideo.play();
                        if (playPromise !== undefined) {
                            playPromise
                                .then(() => {
                                    console.log('✅ Safari video started playing on attempt', attempt + 1);
                                })
                                .catch(error => {
                                    console.warn(`⚠️ Safari play attempt ${attempt + 1} failed:`, error);
                                    if (attempt < 3) {
                                        attemptPlay(attempt + 1);
                                    } else {
                                        // Last resort: wait for user interaction
                                        const playOnInteraction = () => {
                                            splashVideo.muted = true;
                                            splashVideo.volume = 0;
                                            splashVideo.play().catch(err => {
                                                console.warn('Could not play video on interaction:', err);
                                            });
                                            document.removeEventListener('touchstart', playOnInteraction);
                                            document.removeEventListener('touchend', playOnInteraction);
                                            document.removeEventListener('click', playOnInteraction);
                                        };
                                        document.addEventListener('touchstart', playOnInteraction, { once: true, passive: true });
                                        document.addEventListener('touchend', playOnInteraction, { once: true, passive: true });
                                        document.addEventListener('click', playOnInteraction, { once: true });
                                    }
                                });
                        }
                    }, attempt * 200); // 0ms, 200ms, 400ms, 600ms
                };
                
                attemptPlay();
            };
            
            // Wait for video metadata with multiple event listeners
            const setupSafariListeners = () => {
                if (splashVideo.readyState >= 1) {
                    safariPlay();
                } else {
                    // Try on multiple events
                    const events = ['loadedmetadata', 'loadeddata', 'canplay', 'canplaythrough'];
                    events.forEach(event => {
                        splashVideo.addEventListener(event, safariPlay, { once: true });
                    });
                }
            };
            
            setupSafariListeners();
            
            // Also try on page load with delay
            if (document.readyState === 'complete') {
                setTimeout(safariPlay, 300);
            } else {
                window.addEventListener('load', () => {
                    setTimeout(safariPlay, 300);
                }, { once: true });
            }
            
            // Additional Safari-specific: try on visibility change
            document.addEventListener('visibilitychange', () => {
                if (!document.hidden && splashVideo.paused) {
                    splashVideo.muted = true;
                    splashVideo.volume = 0;
                    splashVideo.play().catch(() => {});
                }
            });
        } else {
            // For other browsers, use standard approach
            if (splashVideo.readyState >= 2) {
                tryPlay();
            } else {
                splashVideo.addEventListener('loadeddata', tryPlay, { once: true });
                splashVideo.addEventListener('canplay', tryPlay, { once: true });
            }
            
            if (document.readyState === 'complete') {
                tryPlay();
            } else {
                window.addEventListener('load', tryPlay, { once: true });
            }
        }
    }

    hideSplashVideo() {
        // Hide splash video screen
        console.log('🔄 Hiding splash video screen...');
        const splashVideoScreen = document.getElementById('splashVideoScreen');
        if (splashVideoScreen) {
            splashVideoScreen.classList.add('hidden');
            // Stop video playback and disconnect audio
            const splashVideo = document.getElementById('splashVideo');
            if (splashVideo) {
                // Pause the video first
                splashVideo.pause();
                splashVideo.currentTime = 0;
                
                // Store the original source for potential restoration (though unlikely after auth)
                if (!splashVideo.dataset.originalSrc) {
                    const sourceElement = splashVideo.querySelector('source');
                    if (sourceElement) {
                        splashVideo.dataset.originalSrc = sourceElement.getAttribute('src');
                        splashVideo.dataset.originalType = sourceElement.getAttribute('type');
                    }
                }
                
                // Disconnect audio by clearing the source
                // This stops the video from sending audio signals
                splashVideo.src = '';
                splashVideo.srcObject = null;
                
                // Remove all source elements to fully disconnect
                const sources = splashVideo.querySelectorAll('source');
                sources.forEach(source => source.remove());
                
                // Reset video element to fully disconnect media stream
                splashVideo.load();
                
                // Ensure muted and volume is 0 as additional safety
                splashVideo.muted = true;
                splashVideo.volume = 0;
                
                // Remove all event listeners from the video element by cloning
                // This is the most reliable way to remove all attached listeners
                const newVideo = splashVideo.cloneNode(false);
                newVideo.id = 'splashVideo';
                newVideo.className = splashVideo.className;
                newVideo.setAttribute('autoplay', '');
                newVideo.setAttribute('muted', '');
                newVideo.setAttribute('loop', '');
                newVideo.setAttribute('playsinline', '');
                newVideo.setAttribute('preload', 'auto');
                newVideo.setAttribute('webkit-playsinline', '');
                newVideo.setAttribute('x-webkit-airplay', 'allow');
                
                // Preserve the stored source data
                if (splashVideo.dataset.originalSrc) {
                    newVideo.dataset.originalSrc = splashVideo.dataset.originalSrc;
                    newVideo.dataset.originalType = splashVideo.dataset.originalType;
                }
                
                // Replace the old video with the new one (this removes all event listeners)
                if (splashVideo.parentNode) {
                    splashVideo.parentNode.replaceChild(newVideo, splashVideo);
                }
                
                console.log('🔇 Splash video audio disconnected and event listeners removed');
            }
            
            // Remove from DOM after transition
            setTimeout(() => {
                splashVideoScreen.style.display = 'none';
            }, 500);
        }
    }

    showSplashVideo() {
        // Show splash video screen
        console.log('🔄 Showing splash video screen...');
        const splashVideoScreen = document.getElementById('splashVideoScreen');
        if (splashVideoScreen) {
            splashVideoScreen.style.display = 'flex';
            splashVideoScreen.classList.remove('hidden');
            // Start video playback
            const splashVideo = document.getElementById('splashVideo');
            if (splashVideo) {
                // Restore source if it was cleared (unlikely after auth, but safe to check)
                if (!splashVideo.src && !splashVideo.querySelector('source') && splashVideo.dataset.originalSrc) {
                    const sourceElement = document.createElement('source');
                    sourceElement.setAttribute('src', splashVideo.dataset.originalSrc);
                    if (splashVideo.dataset.originalType) {
                        sourceElement.setAttribute('type', splashVideo.dataset.originalType);
                    }
                    splashVideo.appendChild(sourceElement);
                    splashVideo.load();
                }
                
                splashVideo.play().catch(err => {
                    console.warn('Could not autoplay splash video:', err);
                });
            }
        }
    }

    setAuthenticatedState(authenticated) {
        console.log('🔄 Setting authentication state:', authenticated);
        this.isAuthenticated = authenticated;
        
        if (authenticated) {
            console.log('✅ User is now authenticated');
            // Add authenticated class to body
            document.body.classList.add('authenticated');

            // Show unpair button
            const unpairBtn = document.getElementById('unpairBtn');
            if (unpairBtn) {
                unpairBtn.style.display = 'block';
                console.log('🔘 Unpair button shown');
            }
                        
            // Show all logged-in content
            document.querySelectorAll('.paired-only').forEach(section => {
                section.classList.add('active');
            });
            console.log('📱 All logged-in content shown');
            
            // Update user info in header (after elements are visible)
            // Add a small delay to ensure CSS changes have taken effect
            setTimeout(() => {
                this.updateUserInfoInHeader();
            }, 100);
            
            // Load dashboard data
            //this.loadDashboardData();
        } else {
            console.log('❌ User is now not authenticated, authenticationChecked:', this.authenticationChecked);
            // Always hide splash video when not authenticated (whether check completed or not)
            // The splash video should only be visible while waiting for authentication check
            this.hideSplashVideo();
            
            // Remove authenticated class from body
            document.body.classList.remove('authenticated');

            // Hide unpair button
            const unpairBtn = document.getElementById('unpairBtn');
            if (unpairBtn) {
                unpairBtn.style.display = 'none';
                console.log('🔘 Unpair button hidden');
            }
                        
            // Hide all logged-in content
            document.querySelectorAll('.paired-only').forEach(section => {
                section.classList.remove('active');
            });
            console.log('📱 All logged-in content hidden');
            
            // Clear user info in header
            this.clearUserInfoInHeader();
            
            // Refresh navigation visibility (will hide all buttons since user is not authenticated)
            this.refreshSectionsVisibility();
        }

        // Show cache management buttons
        const clearCacheBtn = document.getElementById('clearCacheBtn');
        const refreshJSBtn = document.getElementById('refreshJSBtn');
        const nuclearRefreshBtn = document.getElementById('nuclearRefreshBtn');
        const serviceWorkerRefreshBtn = document.getElementById('serviceWorkerRefreshBtn');
        if (clearCacheBtn) {
            clearCacheBtn.style.display = 'block';
            console.log('🔘 Clear cache button shown');
        }
        if (refreshJSBtn) {
            refreshJSBtn.style.display = 'block';
            console.log('🔘 Refresh JS button shown');
        }
        if (nuclearRefreshBtn) {
            nuclearRefreshBtn.style.display = 'block';
            console.log('🔘 Nuclear refresh button shown');
        }
        if (serviceWorkerRefreshBtn) {
            serviceWorkerRefreshBtn.style.display = 'block';
            console.log('🔘 Force update button shown');
        }
    }

    updateUserInfoInHeader() {
        console.log('🔍 updateUserInfoInHeader called, currentUser:', this.currentUser);
        
        if (this.currentUser) {
            const userNameElement = document.getElementById('userName');
            const userMobileElement = document.getElementById('userMobile');
            const userInfoElement = document.querySelector('.user-info');
            
            console.log('🔍 Found elements:', {
                userName: userNameElement,
                userMobile: userMobileElement,
                userInfo: userInfoElement
            });
            
            // Debug CSS state
            if (userInfoElement) {
                console.log('🔍 User info element CSS state:', {
                    classes: userInfoElement.className,
                    display: window.getComputedStyle(userInfoElement).display,
                    visibility: window.getComputedStyle(userInfoElement).visibility,
                    opacity: window.getComputedStyle(userInfoElement).opacity
                });
            }
            
            if (userNameElement && userMobileElement && userInfoElement) {
                // Make sure the user info is visible - use both CSS class and direct style
                userInfoElement.classList.add('active');
                userInfoElement.style.display = 'flex'; // Force display as fallback
                
                // Log the updated CSS state
                console.log('🔍 After adding active class and setting style:', {
                    classes: userInfoElement.className,
                    display: window.getComputedStyle(userInfoElement).display,
                    inlineStyle: userInfoElement.style.display
                });

                const storedRefereeMobileNo = this.getStorageKey('adminApplyReferee');
                const storedRefereeLabel = this.getStorageKey('adminApplyRefereeLabel');
                // Update the content
                if (storedRefereeLabel) {
                    userNameElement.textContent = storedRefereeLabel;
                } else {
                    userNameElement.textContent = this.currentUser?.refereeName || 'שופט';
                }
                if (storedRefereeMobileNo) {
                    userMobileElement.textContent = '#' + storedRefereeMobileNo + '#';
                } else {
                    userMobileElement.textContent = this.currentUser?.mobileNo || '-';
                }
                
                console.log('👤 User info updated in header:', this.currentUser);
            } else {
                console.warn('⚠️ User info elements not found:', {
                    userName: !!userNameElement,
                    userMobile: !!userMobileElement,
                    userInfo: !!userInfoElement
                });
                
                // Only retry once to avoid infinite loops
                if (!this._retryCount) {
                    this._retryCount = 1;
                    console.log('🔄 Retrying once after 500ms...');
                    setTimeout(() => {
                        this._retryCount = 0; // Reset for next time
                        this.updateUserInfoInHeader();
                    }, 500);
                } else {
                    console.error('❌ Elements still not found after retry, giving up');
                    this._retryCount = 0; // Reset for next time
                }
            }
        }
    }

    clearUserInfoInHeader() {
        const userInfoElement = document.querySelector('.user-info');
        if (userInfoElement) {
            userInfoElement.classList.remove('active');
            userInfoElement.style.display = 'none'; // Force hide as fallback
            console.log('👤 User info cleared from header');
        }
                
        this.currentUser = null;
    }

    // Debug method to test auto-hide functionality
    testAutoHide() {
        console.log('🧪 Testing auto-hide functionality...');
        
        // Test chatActions section
        const chatActions = document.getElementById('chatActions');
        if (chatActions) {
            console.log('✅ chatActions found:', chatActions);
            console.log('📌 Pinned state:', this.isSectionPinned('chatActions'));
            console.log('🎭 Auto-hide class:', chatActions.classList.contains('auto-hide'));
        } else {
            console.log('❌ chatActions not found');
        }
        
        // Test chatSyncControls section
        const chatSyncControls = document.getElementById('chatSyncControls');
        if (chatSyncControls) {
            console.log('✅ chatSyncControls found:', chatSyncControls);
            console.log('📌 Pinned state:', this.isSectionPinned('chatSyncControls'));
            console.log('🎭 Auto-hide class:', chatSyncControls.classList.contains('auto-hide'));
        } else {
            console.log('❌ chatSyncControls not found');
        }
        
        // Test pin buttons
        const pinChatActions = document.getElementById('pinChatActions');
        const pinChatSyncControls = document.getElementById('pinChatSyncControls');
        console.log('📌 pinChatActions found:', !!pinChatActions);
        console.log('📌 pinChatSyncControls found:', !!pinChatSyncControls);
        
        // Show current auto-hide timers
        console.log('⏰ Auto-hide timers:', this.autoHideTimers);
        
        // Test overall chat section visibility
        const chatSection = document.getElementById('chat');
        if (chatSection) {
            console.log('🔍 Overall chat section visibility:', {
                display: chatSection.style.display,
                hasHiddenClass: chatSection.classList.contains('hidden'),
                isVisible: chatSection.style.display !== 'none' && !chatSection.classList.contains('hidden')
            });
        }
        
        return {
            chatActions: {
                found: !!chatActions,
                pinned: this.isSectionPinned('chatActions'),
                autoHide: chatActions ? chatActions.classList.contains('auto-hide') : false
            },
            chatSyncControls: {
                found: !!chatSyncControls,
                pinned: this.isSectionPinned('chatSyncControls'),
                autoHide: chatSyncControls ? chatSyncControls.classList.contains('auto-hide') : false
            },
            pinButtons: {
                pinChatActions: !!pinChatActions,
                pinChatSyncControls: !!pinChatSyncControls
            },
            timers: this.autoHideTimers,
            overallChatSection: chatSection ? {
                display: chatSection.style.display,
                hasHiddenClass: chatSection.classList.contains('hidden'),
                isVisible: chatSection.style.display !== 'none' && !chatSection.classList.contains('hidden')
            } : null
        };
    }

    // Method to check if PWA is ready
    isReady() {
        return this.isInitialized;
    }

    // Force auto-hide for testing
    forceAutoHide() {
        console.log('🧪 Force auto-hide for testing...');
        
        const chatActions = document.getElementById('chatActions');
        const chatSyncControls = document.getElementById('chatSyncControls');
        
        if (chatActions) {
            console.log('🎭 Force adding auto-hide to chatActions');
            chatActions.classList.add('auto-hide');
            console.log('🔍 chatActions classes:', chatActions.classList.toString());
        }
        
        if (chatSyncControls) {
            console.log('🎭 Force adding auto-hide to chatSyncControls');
            chatSyncControls.classList.add('auto-hide');
            console.log('🔍 chatSyncControls classes:', chatSyncControls.classList.toString());
        }
        
        return {
            chatActions: chatActions ? chatActions.classList.contains('auto-hide') : false,
            chatSyncControls: chatSyncControls ? chatSyncControls.classList.contains('auto-hide') : false
        };
    }

    // Toggle entire chat section visibility for testing
    toggleChatSectionVisibility() {
        console.log('🔄 Toggling entire chat section visibility...');
        
        const chatSection = document.getElementById('chat');
        if (!chatSection) {
            console.warn('⚠️ Chat section not found');
            return false;
        }
        
        const isCurrentlyVisible = chatSection.style.display !== 'none' && !chatSection.classList.contains('hidden');
        
        if (isCurrentlyVisible) {
            // Hide chat section
            chatSection.style.display = 'none';
            chatSection.classList.add('hidden');
            console.log('🚫 Chat section hidden');
        } else {
            // Show chat section
            chatSection.style.display = 'block';
            chatSection.classList.remove('hidden');
            console.log('✅ Chat section shown');
        }
        
        return !isCurrentlyVisible;
    }

    // Check current user and mobile number status
    checkUserStatus() {
        console.log('👤 Checking current user status...');
        
        const status = {
            isAuthenticated: this.isAuthenticated,
            currentUser: this.currentUser,
            hasMobileNumber: this.currentUser && this.currentUser.mobileNo && this.currentUser.mobileNo.trim() !== '',
            mobileNumber: this.currentUser?.mobileNo || 'Not set',
            chatSectionVisible: false
        };
        
        // Check chat section visibility
        const chatSection = document.getElementById('chat');
        if (chatSection) {
            status.chatSectionVisible = chatSection.style.display !== 'none' && !chatSection.classList.contains('hidden');
        }
        
        console.log('📊 User Status:', status);
        return status;
    }

    // Test CSS application manually
    testCSSApplication() {
        console.log('🎨 Testing CSS application...');
        
        const chatActions = document.getElementById('chatActions');
        const chatSyncControls = document.getElementById('chatSyncControls');
        
        if (chatActions) {
            console.log('🔍 Testing chatActions CSS...');
            
            // Test adding auto-hide class
            chatActions.classList.add('auto-hide');
            console.log('✅ Added auto-hide class to chatActions');
            
            // Check computed styles
            const computedStyle = window.getComputedStyle(chatActions);
            console.log('🎨 Computed styles for chatActions:', {
                opacity: computedStyle.opacity,
                transform: computedStyle.transform,
                filter: computedStyle.filter,
                pointerEvents: computedStyle.pointerEvents
            });
            
            // Force reflow
            chatActions.offsetHeight;
            
            // Check again after reflow
            const computedStyleAfter = window.getComputedStyle(chatActions);
            console.log('🎨 Computed styles after reflow:', {
                opacity: computedStyleAfter.opacity,
                transform: computedStyleAfter.transform,
                filter: computedStyleAfter.filter,
                pointerEvents: computedStyleAfter.pointerEvents
            });
        }
        
        if (chatSyncControls) {
            console.log('🔍 Testing chatSyncControls CSS...');
            
            // Test adding auto-hide class
            chatSyncControls.classList.add('auto-hide');
            console.log('✅ Added auto-hide class to chatSyncControls');
            
            // Check computed styles
            const computedStyle = window.getComputedStyle(chatSyncControls);
            console.log('🎨 Computed styles for chatSyncControls:', {
                opacity: computedStyle.opacity,
                transform: computedStyle.transform,
                filter: computedStyle.filter,
                pointerEvents: computedStyle.pointerEvents
            });
        }
        
        return {
            chatActions: chatActions ? chatActions.classList.contains('auto-hide') : false,
            chatSyncControls: chatSyncControls ? chatSyncControls.classList.contains('auto-hide') : false
        };
    }

    startAuthenticationPolling() {
        // Stop any existing polling first
        this.stopAuthenticationPolling();
        
        // Check authentication status every 30 seconds
        this.authPollingInterval = setInterval(async () => {
            await this.checkAuthenticationStatus();
        }, 10000);
        
        console.log('🔄 Authentication polling started');
    }
    
    stopAuthenticationPolling() {
        if (this.authPollingInterval) {
            clearInterval(this.authPollingInterval);
            this.authPollingInterval = null;
            console.log('⏹️ Authentication polling stopped');
        }
    }

    startPushSubscriptionPolling() {
        // Stop any existing polling first
        this.stopPushSubscriptionPolling();
        
        // Validate immediately on initialization
        if (this.isAuthenticated) {
            (async () => {
                const subscription = await this.getCurrentPushSubscription();
                if (!subscription) {
                    await this.handlePushSubscriptionError();
                } else {
                    // Validate subscription immediately upon initialization
                    await this.checkAndResubscribeIfExpired();
                }
            })();
        }
        
        // Check push subscription validity every 6 hours
        this.pushSubscriptionPollingInterval = setInterval(async () => {
            if (this.isAuthenticated) {
                const subscription = await this.getCurrentPushSubscription();
                if (!subscription) {
                    await this.handlePushSubscriptionError();
                } else {
                    // Periodically validate subscription to catch expiration early
                    // This prevents missing notifications between expiration and detection
                    await this.checkAndResubscribeIfExpired();
                }
            }
        }, 6 * 60 * 60 * 1000); // 6 hours
        
        console.log('🔄 Push subscription polling started (validates immediately and every 6 hours)');
    }
    
    stopPushSubscriptionPolling() {
        if (this.pushSubscriptionPollingInterval) {
            clearInterval(this.pushSubscriptionPollingInterval);
            this.pushSubscriptionPollingInterval = null;
            console.log('⏹️ Push subscription polling stopped');
        }
    }
    
    // Stop all polling and timers
    stopAllPolling() {
        this.stopAuthenticationPolling();
        this.stopPushSubscriptionPolling();
        this.stopChatSync();
        this.stopRealTimeChatUpdates();
        console.log('⏹️ All polling and timers stopped');
    }
    
    // Cleanup method for when PWA is destroyed
    async cleanup() {
        console.log('🧹 Cleaning up RefPortalPWA...');
        this.stopAllPolling();
        
        // Cleanup speed monitoring
        this.stopSpeedMonitoring();
        if (this.speedMonitorComponent) {
            this.speedMonitorComponent.cleanup();
        }
        if (this.speedMonitorService) {
            await this.speedMonitorService.cleanup();
        }
        
        if (this.distanceTrackerComponent) {
            this.distanceTrackerComponent.destroy();
        }
        
        this.isInitialized = false;
        console.log('✅ RefPortalPWA cleanup complete');
    }
    
    // Emergency stop method to break infinite loops
    emergencyStop() {
        console.log('🚨 Emergency stop called - stopping all polling and timers...');
        this.stopAllPolling();
        
        // Clear any remaining intervals that might not be tracked
        for (let i = 1; i < 10000; i++) {
            clearInterval(i);
        }
        
        console.log('🚨 Emergency stop completed');
    }

    setupPageVisibilityHandling() {
        // Handle page visibility changes
        //return;
        document.addEventListener('visibilitychange', async () => {
            if (this.isAuthenticated) {
                if (document.hidden) { // App blurs or is minimized
                    // Page is hidden, could be user switching tabs or closing browser
                    console.log('📱 Page hidden - pausing real-time updates');// + this.pwaLogger.sendToServerLogText);
                    // Pause real-time updates when page is hidden to save resources
                    this.stopRealTimeChatUpdates();
                } else { // App is in focus
                    console.log('📱 Page visible - resuming real-time updates');
                    if (this.pushNotificationsMust || this.pushhNotificationPermission) {
                        await this.checkAndResubscribeIfExpired();
                    }
                    // Resume real-time updates when page becomes visible
                    if (this.isOnline && this.chatSyncEnabled) {
                        this.startRealTimeChatUpdates();
                    }
                }
            }
        });

        // Handle beforeunload event
        window.addEventListener('beforeunload', async (event) => {
            if (this.isAuthenticated) {
                console.log('📱 Page unloading - cleaning up chat connections');
                // Cleanup chat connections when page is unloaded
                this.stopRealTimeChatUpdates();
                this.stopChatSync();
            }
            
            // Always cleanup polling to prevent memory leaks
            this.stopAllPolling();
            
            // Call cleanup to ensure all services are properly cleaned up
            await this.cleanup();
        });
    }

    setupInactivityTimeout() {
        let inactivityTimer;
        const INACTIVITY_TIMEOUT = 30 * 60 * 1000; // 30 minutes

        const resetTimer = () => {
            if (inactivityTimer) {
                clearTimeout(inactivityTimer);
            }
            if (this.isAuthenticated) {
                inactivityTimer = setTimeout(async () => {
                    this.showToast('התנתקת אוטומטית עקב חוסר פעילות', 'info');
                    await this.handleAuthenticationFailure();
                }, INACTIVITY_TIMEOUT);
            }
        };

        // Reset timer on user activity
        const events = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart', 'click'];
        events.forEach(event => {
            document.addEventListener(event, resetTimer, true);
        });

        // Initial timer setup
        resetTimer();
    }

    async getClientIdentifier() {
        const clientIdService = ClientIdentifierService.getInstance();
        const prevClientIdentifier = await clientIdService.clientIdentifier;
        const clientIdentifier = await clientIdService.generateClientIdentifier();
        if ((!prevClientIdentifier || !this.jwtWebSocket.isConnected()) && clientIdentifier) {
            this.jwtWebSocket.connect(clientIdentifier);
        } else if (prevClientIdentifier && this.jwtWebSocket.isConnected() && !clientIdentifier) {
            this.jwtWebSocket.disconnect();
        }
        return clientIdentifier;
    }

    async getSessionIdentifier(generateNewId = false) {
        const clientIdService = ClientIdentifierService.getInstance();
        const sessionIdentifier = await clientIdService.generateSessionIdentifier(generateNewId);
        return sessionIdentifier;
    }

    async validatePushSubscription() {
        try {
            const pushSubscription = await this.getCurrentPushSubscription();

            if (!pushSubscription) {
                if (this.isAuthenticated) {
                    await this.handlePushSubscriptionError();
                }
                return false;
            }
            return true;
        } catch (error) {
            console.error('Error validating push subscription:', error);
            if (this.isAuthenticated) {
                await this.handlePushSubscriptionError();
            }
            return false;
        }
    }

    async handlePushSubscriptionExpired() {
        // Handle case where push subscription has expired
        console.log('⚠️ Push subscription expired, attempting to resubscribe...');
        
        try {
            // Check if we have notification permission
            if (Notification.permission !== 'granted') {
                console.log('⚠️ Notification permission not granted, cannot resubscribe');
                if (this.isAuthenticated) {
                    this.showToast('הרשאות התראות פגו. אנא הפעל מחדש', 'warning');
                }
                return;
            }
            
            // Try to automatically resubscribe
            const newSubscription = await this.subscribeToPushNotifications();
            if (newSubscription) {
                console.log('✅ Successfully resubscribed to push notifications');
                if (this.isAuthenticated) {
                    this.showToast('התראות הופעלו מחדש בהצלחה', 'success');
                }
            } else {
                console.warn('⚠️ Failed to resubscribe to push notifications');
                if (this.isAuthenticated) {
                    this.showToast('הרשאות התראות פגו. אנא הפעל מחדש', 'warning');
                }
            }
        } catch (error) {
            console.error('❌ Error resubscribing to push notifications:', error);
            if (this.isAuthenticated) {
                this.showToast('הרשאות התראות פגו. אנא הפעל מחדש', 'warning');
            }
        }
    }
    
    async checkAndResubscribeIfExpired() {
        /**
         * Check if the push subscription stored on the backend is marked as expired
         * and automatically resubscribe if needed.
         * 
         * This checks:
         * 1. If browser has a valid subscription
         * 2. If backend has marked it as expired (EXPIRED_PUSH_SUBSCRIPTION)
         * 3. Automatically creates a new subscription and sends it to backend
         * 
         * Note: Expiration is controlled by the browser's push service (Chrome/Firefox/etc.),
         * not by the application. When a subscription expires, the push service returns 410,
         * and the backend marks it as 'EXPIRED_PUSH_SUBSCRIPTION'.
         * 
         * Validation Strategy:
         * - Initial subscription: validates immediately
         * - App foreground: validates when app becomes visible
         * - Periodic: validates every 6 hours
         * - Auth check: validates only if 1+ hour has passed (throttled)
         * - Notification send: lazy validation (already implemented)
         * 
         * This balances catching expiration early with avoiding excessive validation.
         */
        try {
            const clientIdentifier = await this.getClientIdentifier();
            if (!clientIdentifier || !this.currentUser?.mobileNo) {
                return; // Need client identifier and mobile number to check
            }
            
            const browserSubscription = await this.getCurrentPushSubscription();
            
            // If we have a browser subscription, validate it with backend
            // Only validate when explicitly checking (not on every save)
            if (browserSubscription) {
                try {
                    await this.sendPushSubscriptionToServer(browserSubscription, true);
                    // If successful, subscription is valid
                    return;
                } catch (error) {
                    // If error, subscription might be expired
                    console.log('⚠️ Error sending subscription to server, might be expired:', error);
                }
            }
            
            // If no browser subscription or sending failed, try to create new one
            if (Notification.permission === 'granted') {
                console.log('📱 Attempting to create new push subscription...');
                const newSubscription = await this.subscribeToPushNotifications();
                if (newSubscription) {
                    console.log('✅ Created new subscription after expiration check');
                    // Don't validate on initial save - validation happens lazily when sending notifications
                    await this.sendPushSubscriptionToServer(newSubscription, false);
                }
            }
        } catch (error) {
            console.error('❌ Error checking for expired subscription:', error);
        }
    }

    async handlePushSubscriptionRevoked() {
        // Handle case where push subscription was revoked by user
        if (this.isAuthenticated) {
            if (this.lastPushSubscriptionRevoked) {
                this.lastPushSubscriptionRevoked = null;
                this.showToast('הרשאות התראות בוטלו', 'warning');
            } 
        }
    }

    async handlePushSubscriptionInvalid() {
        // Handle case where push subscription is invalid for any reason
        if (this.isAuthenticated) {
            if (this.lastPushSubscriptionInvalid) {
                this.lastPushSubscriptionInvalid = null;
                this.showToast('הרשאות התראות לא תקפות', 'error');
            }
        }
    }

    async handlePushSubscriptionNetworkError() {
        // Handle case where there's a network error with push subscription
        if (this.isAuthenticated) {
            if (this.lastPushSubscriptionNetworkError) {
                this.lastPushSubscriptionNetworkError = null;
                this.showToast('שגיאת רשת בהרשאות התראות', 'error');
            }
        }
    }

    async handlePushSubscriptionPermissionDenied() {
        // Handle case where user denied push notification permission
        if (this.isAuthenticated) {
            if (this.lastPushSubscriptionPermissionDenied) {
                this.lastPushSubscriptionPermissionDenied = null;
                this.showToast('הרשאות התראות נדחו', 'warning');
            }
        }
    }

    async handlePushSubscriptionServiceWorkerError() {
        // Handle case where service worker has an error
        if (this.isAuthenticated) {
            if (this.lastPushSubscriptionServiceWorkerError) {
                this.lastPushSubscriptionServiceWorkerError = null;
                this.showToast('שגיאה בשירות התראות', 'error');
            }
        }
    }

    async getJwtToken() {
        // Use refresh token service to get the current access token
        return await this.refreshTokenService.getAccessToken();
    }

    async handleSuccessfulAuthentication(manualTrigger=false) {
        // Get JWT token and parse payload
        const accessToken = await this.getJwtToken()
        if (accessToken) {
            const payload = JwtService.parseJwtToken(accessToken);
            if (payload) {
                console.log('🔐 JWT Token payload:', payload);
                
                // Store user info from JWT payload
                this.currentUser = {
                    clientIdentifier: payload.clientIdentifier,
                    role: payload.role,
                    mobileNo: payload.mobileNo, // if available in payload
                    refereeName: payload.refName, // use refName from JWT
                    allowedSections: payload.allowedSections, // use allowedTabs from JWT
                    tenantRefIds: payload.tenantRefIds, // use tenantRefIds from JWT
                };
                
                // Store additional JWT info
                this.jwtInfo = {
                    issuedAt: new Date(payload.iat * 1000),
                    expiresAt: new Date(payload.exp * 1000),
                    issuer: payload.iss
                };
                
                const adminDebugPanel = document.getElementById('adminDebugPanel');
                if (!!adminDebugPanel) {
                    if (payload.role === 'Admin') {
                        adminDebugPanel.style.display = 'block';
                    } else {
                        adminDebugPanel.style.display = 'none';
                    }
                }

                // Dismiss splash before slow network calls (loadTenants / loadRoles) so UI never hangs on video
                this.authenticationChecked = true;
                this.hideSplashVideo();
                this.setAuthenticatedState(true);

                await this.loadTenants();
                await this.loadRoles();
                console.log('👤 User info from JWT:', this.currentUser);
                console.log('⏰ JWT info:', this.jwtInfo);
                
                // Display JWT information for debugging
                await JwtService.displayJwtInfo();

                this.refreshSectionsVisibility();

                // Show success message
                if (manualTrigger || this.lastAuthenticationStatus == false) {
                    this.showToast('התחברת בהצלחה למערכת!', 'success', 1500);
                }

                // Navigate to dashboard
                const lastSection = this.currentSection;
                await this.navigateToSection(lastSection);

                this.currentAuthenticationStatus = true;
            } else {
                await this.handleAuthenticationFailure();
                return;
            }
        } else {
            await this.handleAuthenticationFailure();
            return;
        }
    }

    async handleAuthenticationFailure() {
        // Clear user info
        this.currentUser = null;
        
        // Mark authentication check as completed (even if failed)
        this.authenticationChecked = true;
        
        // Hide splash video screen since authentication check is complete (failed)
        this.hideSplashVideo();
        
        // Update authentication state
        this.setAuthenticatedState(false);
        
        // Refresh navigation visibility (will hide all buttons since user is null)
        this.refreshSectionsVisibility();
        
        // Clear tokens using refresh token service
        //await this.refreshTokenService.unpair();
        
        // Show message
        this.showToast('התנתקת מהמערכת', 'info');
        
        // Navigate to login section
        await this.navigateToSection('login');

        this.currentAuthenticationStatus = false;
    }

    async manualUnpair() {
        try {
            // Get current push subscription
            const pushSubscription = await this.getCurrentPushSubscription();
            
            // Call unpair endpoint
            const response = await this.refreshTokenService.makeApiRequest({
                url:this.getConfig('ENDPOINTS.UNPAIR'),
                options:{
                    method: 'POST'
                }
            });

            if (response.ok) {
                // Clear tokens using refresh token service
                await this.refreshTokenService.unpair();
                
                // Cleanup services before unpair
                await this.cleanup();
                
                // Clear user info before calling handleAuthenticationFailure
                this.currentUser = null;
                await this.handleAuthenticationFailure();
            } else {
                this.showToast('שגיאה בהתנתקות', 'error');
            }
        } catch (error) {
            console.error('Unpair error:', error);
            // Even if unpair fails, clear local tokens
            await this.refreshTokenService.unpair();
            // Still cleanup services
            await this.cleanup();
            this.showToast('שגיאה בהתנתקות', 'error');
        }
    }

    async manualAuthCheck() {
        this.showToast('בודק מצב התחברות...', 'info');
        await this.checkAuthenticationStatus(true);
        
        if (this.isAuthenticated) {
            this.showToast('התחברת בהצלחה למערכת!', 'success', 1500);
        } else {
            this.showToast('עדיין לא התחברת למערכת', 'error');
        }
    }

    /**
     * Test method to verify refresh token service integration
     */
    async testRefreshTokenService() {
        try {
            console.log('🧪 Testing Refresh Token Service Integration...');
            
            // Test 1: Check if service is available
            if (!this.refreshTokenService) {
                console.error('❌ Refresh token service not available');
                return false;
            }
            console.log('✅ Refresh token service is available');
            
            // Test 2: Check current token status
            const accessToken = await this.refreshTokenService.getAccessToken();
            const refreshToken = await this.refreshTokenService.getRefreshToken();
            const isExpired = this.refreshTokenService.isAccessTokenExpired();
            
            console.log('🔍 Current token status:');
            console.log('  - Access token:', accessToken ? 'Present' : 'Missing');
            console.log('  - Refresh token:', refreshToken ? 'Present' : 'Missing');
            console.log('  - Access token expired:', isExpired);
            
            // Test 3: Test token validation
            const validation = await this.refreshTokenService.validateTokens();
            console.log('🔍 Token validation result:', validation);
            
            // Test 4: Test getJwtToken method
            const jwtToken = await this.getJwtToken();
            console.log('🔍 getJwtToken() result:', jwtToken ? 'Token retrieved' : 'No token');
            
            // Test 5: Test JWT service integration
            const jwtPayload = await JwtService.getJwtPayload();
            console.log('🔍 JWT service integration:', jwtPayload ? 'Working' : 'Not working');
            
            console.log('✅ Refresh Token Service Integration Test Complete');
            this.showToast('בדיקת שירות הטוקנים הושלמה בהצלחה', 'success');
            return true;
            
        } catch (error) {
            console.error('❌ Refresh Token Service Integration Test Failed:', error);
            this.showToast('שגיאה בבדיקת שירות הטוקנים', 'error');
            return false;
        }
    }

    async handlePushSubscriptionError() {
        // If we have a push subscription error and user is authenticated, unpair
        if (this.isAuthenticated) {
            // Try to determine the specific type of error
            try {
                const subscription = await this.getCurrentPushSubscription();
                if (!subscription) {
                    await this.handlePushSubscriptionRevoked();
                } else {
                    // Check if subscription is still valid
                    const serviceWorkerRegistration = await this.getServiceWorkerRegistration()
                    const currentSubscription = await serviceWorkerRegistration.pushManager.getSubscription();
                    if (!currentSubscription) {
                        await this.handlePushSubscriptionExpired()
                    } else {
                        // Check if it's a network error
                        try {
                            await this.checkApiServerHealth()
                            await this.handlePushSubscriptionInvalid()
                        } catch (networkError) {
                            await this.handlePushSubscriptionNetworkError()
                        }
                    }
                }
            } catch (error) {
                console.error('Error determining push subscription status:', error);
                if (error.name === 'NetworkError' || error.message.includes('network')) {
                    await this.handlePushSubscriptionNetworkError();
                } else if (error.name === 'NotAllowedError' || error.message.includes('permission')) {
                    await this.handlePushSubscriptionPermissionDenied();
                } else if (error.name === 'ServiceWorkerError' || error.message.includes('service worker')) {
                    await this.handlePushSubscriptionServiceWorkerError();
                } else {
                    await this.handlePushSubscriptionInvalid();
                }
            }
        }
    }

    async setupServiceWorker() {
        if (this.checkServiceWorkerSupported()) {
            try {
                // Get service worker registration safely
                const serviceWorkerRegistration = await this.getServiceWorkerRegistration();
                console.log('✅ Service Worker ready:', serviceWorkerRegistration);
                this.jwtWebSocket.sendLog('INFO', 'Service Worker ready');
                
                // Set up message listener
                navigator.serviceWorker.addEventListener('message', async (event) => {
                    console.log('📨 Service Worker message received:', event.data);
                    
                    if (false)
                        this.showToast(event.data.type || 'edt', 'info');
                    
                    if (event.data.type === 'PUSH_NOTIFICATION') {
                        await this.handlePushNotification(event.data);
                    } else if (event.data.type === 'CACHE_CLEARED') {
                        console.log('✅ Cache cleared notification received');
                        this.showToast('Cache cleared successfully', 'success');
                    } else if (event.data.type === 'JS_CACHE_CLEARED') {
                        console.log('✅ JavaScript cache cleared notification received');
                        this.showToast('JavaScript files cache cleared', 'success');
                    } else if (event.data.type === 'NOTIFICATION_NAVIGATE') {
                        await this.handleNotificationNavigation(event.data);
                    } else if (event.data.type === 'NOTIFICATION_PAIR') {
                        await this.handleNotificationPair(event.data);
                    } else if (event.data.type === 'NOTIFICATION_CHAT') {
                        await this.handleNotificationChat(event.data);
                    } else if (event.data.type === 'UPDATE_HASH') {
                        this.handleHashUpdate(event.data);
                    } else if (event.data.type === 'NOTIFICATION_CLICK') {
                        // Handle notification click with URL
                        if (event.data.url) {
                            console.log('🔘 Opening URL from notification click:', event.data.url);
                            window.open(event.data.url, '_blank');
                            this.showToast('Opening notification link', 'info');
                        }
                    } else if (event.data.type === 'UPDATE_AVAILABLE') {
                        console.log('🔄 Update available notification received:', event.data);
                        this.showUpdateNotification(event.data);
                    } else if (event.data.type === 'PWA_REFRESH_FROM_PUSH') {
                        console.log('🔄 PWA refresh requested from push notification');
                        await this.forceServiceWorkerUpdate();
                    } else if (event.data.type === 'MAKE_API_CALL') {
                        console.log('📡 Received API call request from service worker');
                        await this.sendApiLog('info', 'MAKE_API_CALL received from service worker');
                        await this.updateBadgeFromData();
                    } else if (event.data.type === 'GET_AUTH_TOKEN') {
                        // Service worker is requesting auth token for background API calls
                        const token = await this.getJwtToken();
                        const apiBaseUrl = this.getConfig('API_BASE_URL');
                        if (event.ports && event.ports[0]) {
                            event.ports[0].postMessage({ 
                                token: token,
                                apiBaseUrl: apiBaseUrl
                            });
                        }
                    }           
                });
                
                // Monitor service worker state changes
                this.monitorServiceWorkerState(serviceWorkerRegistration);
                
                // Check if we already have a push subscription
                const existingSubscription = await serviceWorkerRegistration.pushManager.getSubscription();
                if (existingSubscription) {
                    console.log('📱 Existing push subscription found:', existingSubscription);
                } else {
                    console.log('📱 No existing push subscription found');
                }
                
                return serviceWorkerRegistration;
            } catch (error) {
                console.error('❌ Error setting up service worker:', error);
                
                // If it's a timeout error, try to register manually
                if (error.message.includes('timeout')) {
                    console.log('⏰ Service worker registration timeout, trying manual registration...');
                    try {
                        // Register with root scope so it can control all pages
                        const manualRegistration = await navigator.serviceWorker.register(this.refportalSwName, { scope: '/' });
                        console.log('✅ Manual service worker registration successful:', manualRegistration);
                        return manualRegistration;
                    } catch (manualError) {
                        console.error('❌ Manual service worker registration failed:', manualError);
                    }
                }
                
                return null;
            }
        } else {
            console.warn('⚠️ Service Worker not supported');
            return null;
        }
    }

    setupInstallPrompt() {
        if (this.isPWAInstalled()) {
            console.log('✅ PWA already installed (standalone / display-mode)');
            return;
        }

        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            this.deferredPrompt = e;
            console.log('📱 Native install prompt available');
            if (!this.isInstallBannerDismissedRecently()) {
                this.showInstallPrompt();
            }
        });

        window.addEventListener('appinstalled', () => {
            console.log('🎉 PWA installed successfully!');
            this.hideInstallPrompt();
            this.removeInstallInstructionsModal();
            this.showToast('האפליקציה הותקנה בהצלחה!', 'success');
            this.trackPWAInstallation();
        });

        this.setupInstallButtons();

        if (!this.isInstallBannerDismissedRecently()) {
            this.scheduleInitialInstallBanner();
        }
    }

    isInstallBannerDismissedRecently() {
        const dismissedTime = this.getStorageKey('installPromptDismissed');
        if (!dismissedTime) return false;
        const dismissedDate = new Date(parseInt(dismissedTime, 10));
        if (Number.isNaN(dismissedDate.getTime())) {
            this.removeStorageKey('installPromptDismissed');
            return false;
        }
        const hoursSince = (Date.now() - dismissedDate.getTime()) / (1000 * 60 * 60);
        if (hoursSince >= 24) {
            this.removeStorageKey('installPromptDismissed');
            return false;
        }
        return true;
    }

    scheduleInitialInstallBanner() {
        setTimeout(() => {
            if (this.isPWAInstalled()) return;
            if (this.isInstallBannerDismissedRecently()) return;
            this.showInstallPrompt();
        }, 2800);
    }

    setupInstallButtons() {
        const installBtn = document.getElementById('installBtn');
        const dismissBtn = document.getElementById('dismissInstall');
        const closeBtn = document.getElementById('installPromptClose');

        if (installBtn) {
            installBtn.addEventListener('click', () => this.installPWA());
        }

        if (dismissBtn) {
            dismissBtn.addEventListener('click', () => this.dismissInstallOffer());
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.dismissInstallOffer());
        }
    }

    dismissInstallOffer() {
        this.hideInstallPrompt();
        this.setStorageKey('installPromptDismissed', Date.now().toString());
    }

    isPWAInstalled() {
        return isRunningAsInstalledPWA();
    }

    trackPWAInstallation() {
        // Send analytics or tracking data
        if (typeof gtag !== 'undefined') {
            gtag('event', 'pwa_install', {
                'event_category': 'engagement',
                'event_label': 'RefereeX PWA'
            });
        }
    }

    setupHashRouting() {
        console.log('🔗 Setting up hash-based routing...');
        
        // Listen for hash changes
        window.addEventListener('hashchange', async (e) => {
            await this.handleHashChange();
        });
        
        // Listen for popstate (browser back/forward buttons)
        window.addEventListener('popstate', (e) => {
            console.log('🔙 Popstate event:', e);
            // Hash change will handle the navigation
        });
        
        // Handle initial hash on page load
        if (window.location.hash) {
            // Small delay to ensure DOM is ready
            setTimeout(async () => {
                await this.handleHashChange();
            }, 100);
        }
        
        console.log('✅ Hash routing set up');
    }

    async handleHashChange() {
        const hash = window.location.hash.substring(1); // Remove the # symbol
        console.log('🔗 Hash changed to:', hash);

        if (hash && this.isValidSection(hash)) {
            if (hash === this.currentSection) return; // hash was set by navigateToSection itself, skip
            await this.navigateToSection(hash, false); // false = don't update hash
        } else if (hash) {
            console.warn('⚠️ Invalid hash section:', hash);
            // Redirect to dashboard if invalid hash
            await this.navigateToSection('dashboard', true);
        }
    }

    userValidSections() {
        let userValidSections = [];
        if (this.currentUser && this.currentUser.allowedSections) {
            userValidSections = this.currentUser.allowedSections;
        }
        return userValidSections;
    }

    defaultValidSection() {
        if (!this.isAuthenticated) return 'login';
        const userValidSections = this.userValidSections();
        return userValidSections && userValidSections.length > 0 ? userValidSections[0] : '';
    }

    isValidSection(section) {
        if (['publicTables', 'publicGames', 'fields'].includes(section)) return true;
        if (section === 'login') return !this.isAuthenticated;
        const userValidSections = this.userValidSections();
        return userValidSections.includes(section);
    }

    // Method to handle deep linking from notifications or external sources
    navigateToHash(hash) {
        console.log('🔗 Deep linking to hash:', hash);
        
        if (hash && this.isValidSection(hash)) {
            // Update URL hash and navigate
            window.location.hash = hash;
            // The hashchange event will handle the navigation
        } else {
            console.warn('⚠️ Invalid hash for deep linking:', hash);
        }
    }

    // Method to handle external deep linking (e.g., from email links)
    async handleExternalDeepLink() {
        // Check if there's a hash in the URL
        if (window.location.hash) {
            const hash = window.location.hash.substring(1);
            console.log('🔗 External deep link detected:', hash);
            
            if (this.isValidSection(hash)) {
                // Navigate to the section
                await this.navigateToSection(hash, false);
            }
        }
    }

    // Method to get current section from hash
    getCurrentSectionFromHash() {
        const hash = window.location.hash.substring(1);
        return this.isValidSection(hash) ? hash : this.defaultValidSection();
    }

    // Handle hash updates from service worker
    handleHashUpdate(data) {
        console.log('🔗 Handling hash update from service worker:', data);
        
        if (data.hash && this.isValidSection(data.hash)) {
            // Update URL hash without triggering navigation (to avoid double navigation)
            if (window.location.hash !== `#${data.hash}`) {
                window.location.hash = data.hash;
            }
        }
    }

    refreshSectionsVisibility() {
        // Show/hide nav items based on allowed sections
        document.querySelectorAll('button.nav-item').forEach(item => {
            const sectionId = item.dataset.section;
            if (sectionId) {
                const isAllowed = this.isValidSection(sectionId);
                if (isAllowed) {
                    item.style.display = ''; // Show the button
                } else {
                    item.style.display = 'none'; // Hide the button
                }
            }
        });

        // Hide all sections
        document.querySelectorAll('.content-section').forEach(s => {
            s.classList.remove('active');
        });

        // Remove active from all nav items
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.remove('active');
        });

        // Restore active state for the current section if it is still valid
        if (this.currentSection && this.isValidSection(this.currentSection)) {
            const section = document.getElementById(this.currentSection);
            if (section) section.classList.add('active');
            const navItem = document.querySelector(`[data-section="${this.currentSection}"]`);
            if (navItem) navItem.classList.add('active');
        }
    }

    async navigateToSection(section, updateHash = true) {
        console.log('🧭 Navigating to section:', section, 'updateHash:', updateHash);
        if (!this.isValidSection(section)) {
            section = this.defaultValidSection();
        }

        const targetSection = document.getElementById(section);
        if (targetSection && targetSection.classList.contains('paired-only') && !this.isAuthenticated) {
            return;
        }
        if (!targetSection) {
            console.error('❌ Section not found:', section);
            return;
        }

        // Update currentSection before refreshSectionsVisibility so the restore
        // logic re-activates the correct (new) section, not the old one.
        this.currentSection = section;
        this.refreshSectionsVisibility();

        // Special handling for chat section - activate chat actions
        if (section === 'chat') {
            this.activateChatActions();
        } else {
            this.deactivateChatActions();
        }
        
        // Update URL hash if requested (but avoid infinite loop)
        if (updateHash && window.location.hash !== `#${section}`) {
            window.location.hash = `#${section}`;
        }
        
        await this.loadSectionContent(section);
    }

    async loadSectionContent(section) {
        switch (section) {
            case 'dashboard':
                await this.loadDashboardDataWithNextGameParallel();
                break;
            case 'games':
                await this.loadTenants();
                await this.loadRoles();
                this._runWithDomQuiet('games', () => this.applyGamesTabDateRange());
                await this.loadRefereeGamesData();
                break;
            case 'reviews':
                await this.loadTenants();
                await this.loadRefereeReviewsData();
                break;
            case 'fields':
                await this.loadFieldsData();
                break;
            case 'availability':
                await this.loadAvailabilityData();
                break;
            case 'admin':
                await this.loadReferees();
                await this.loadRefereeTemplates();
                await this.loadNotifications();
                break;
            case 'documents':
                await this.loadDocumentsData();
                break;
            case 'rules':
                await this.loadRulesData();
                break;
            case 'chat':
                this.loadChatData();
                break;
            case 'userDetails':
                await this.loadTenants();
                await this.loadUserDetailsData();
                this.renderPasswordFields();
                break;
            case 'messages':
                await this.loadMessagesData();
                break;
            case 'publicTables': {
                const savedTables = this._readPublicTablesFiltersFromStorage();
                await this.loadTenants();
                if (savedTables?.tenantKey) {
                    const tf = document.getElementById('tablesTenantFilter');
                    if (tf) tf.value = savedTables.tenantKey;
                }
                await this.bootstrapPublicTablesFilters();
                this._applyPublicTablesFiltersFromSaved(savedTables);
                const tKey = document.getElementById('tablesTenantFilter')?.value || '';
                const sec = document.getElementById('tablesSectionFilter')?.value || '';
                const lg = document.getElementById('tablesLeagueFilter')?.value || '';
                if (tKey && (sec || lg)) {
                    await this.loadTablesData();
                } else {
                    this._savePublicTablesFiltersToStorage();
                }
                break;
            }
            case 'publicGames': {
                const savedGames = this._readPublicGamesFiltersFromStorage();
                if (savedGames?.fromDate && savedGames?.toDate) {
                    const fromEl = document.getElementById('publicGamesFromDateFilter');
                    const toEl = document.getElementById('publicGamesToDateFilter');
                    if (fromEl) fromEl.value = savedGames.fromDate;
                    if (toEl) toEl.value = savedGames.toDate;
                } else {
                    this.applyPublicGamesDefaultDateRangeIfEmpty();
                }
                await this.loadTenants();
                await this.loadPublicRefereesList();
                if (savedGames?.tenantKey) {
                    const tf = document.getElementById('publicGamesTenantFilter');
                    if (tf) tf.value = savedGames.tenantKey;
                }
                await this.bootstrapPublicGamesFilters();
                this._applyPublicGamesFiltersFromSaved(savedGames);
                this._clampPublicGamesToDateToFrom();
                const tKeyG = document.getElementById('publicGamesTenantFilter')?.value || '';
                const fromD = document.getElementById('publicGamesFromDateFilter')?.value || '';
                const toD = document.getElementById('publicGamesToDateFilter')?.value || '';
                if (tKeyG && fromD && toD) {
                    await this.loadPublicGamesData();
                } else {
                    this._savePublicGamesFiltersToStorage();
                }
                break;
            }
            case 'login':
                // Clear previous pair status when landing on login tab
                const pairStatus = document.getElementById('pairStatus');
                if (pairStatus) pairStatus.textContent = '';
                break;
        }
    }

    async loadInitialContent() {
        // Handle external deep linking
        await this.handleExternalDeepLink();
        
        // Check if there's a hash in the URL for initial navigation
        if (window.location.hash) {
            const hash = window.location.hash.substring(1);
            if (this.isValidSection(hash)) {
                // Small delay to ensure DOM is ready
                setTimeout(async () => {
                    await this.navigateToSection(hash, false);
                }, 200);
            } else {
                await this.loadDashboardDataWithNextGameParallel();
            }
        } else {
            await this.loadDashboardDataWithNextGameParallel();
        }
        
        // Load rules data
        this.loadRulesData();
        
        // Add welcome message to chat
        if (this.chatMessages.length == 0) {
            this.addChatMessage('system', 'ברוכים הבאים למערכת RefPortal! איך אוכל לעזור לך היום?');
        }
    }

    // ── Public Tables ──────────────────────────────────────────────────────────

    /** Load section/league filter options from PUBLIC_TABLES_FILTERS (not full table rows). */
    async bootstrapPublicTablesFilters() {
        const container = document.getElementById('tablesContent');
        if (!container) return;
        container.innerHTML = '<div class="loading">טוען מסננים...</div>';
        try {
            const tenantKey = document.getElementById('tablesTenantFilter')?.value || '';
            const params = new URLSearchParams();
            if (tenantKey) params.set('tenantKey', tenantKey);
            const url = `${this.getConfig('ENDPOINTS.PUBLIC_TABLES_FILTERS')}?${params}`;
            const response = await this.refreshTokenService.makeApiRequest({ url });
            const data = await response.json();
            if (!data.success) throw new Error(data.error || 'שגיאה בטעינת מסננים');

            const d = data.data || {};
            this._publicTablesSectionsMeta = d.sections || [];
            this._publicTablesLeaguesMeta = d.leagues || [];
            this.applyPublicTablesFiltersFromMetadata();
            this.allTables = [];
            container.innerHTML = tenantKey
                ? '<div class="info-message">בחר קטגוריה או ליגה להצגת משחקים</div>'
                : '<div class="info-message">בחר עונה, או קטגוריה או ליגה להצגת משחקים</div>';
        } catch (err) {
            container.innerHTML = `<div class="error-message">שגיאה: ${err.message}</div>`;
        }
    }

    async loadTablesData() {
        const container = document.getElementById('tablesContent');
        if (!container) return;

        const g = this._beginAsyncTabLoad('tables');

        const tenantKey = document.getElementById('tablesTenantFilter')?.value || '';
        if (!tenantKey) {
            container.innerHTML = '<div class="info-message">יש לבחור עונה להצגת משחקים</div>';
            return;
        }

        const section = document.getElementById('tablesSectionFilter')?.value || '';
        const leagueName = document.getElementById('tablesLeagueFilter')?.value || '';
        const bootstrapOnly = !section && !leagueName;

        if (bootstrapOnly) {
            await this.bootstrapPublicTablesFilters();
            if (this._staleAsyncTabLoad('tables', g)) return;
            this._savePublicTablesFiltersToStorage();
            return;
        }

        container.innerHTML = '<div class="loading">טוען טבלאות...</div>';

        try {
            const params = new URLSearchParams();
            params.set('tenantKey', tenantKey);
            if (section) params.set('section', section);
            if (leagueName) params.set('leagueName', leagueName);

            const url = `${this.getConfig('ENDPOINTS.PUBLIC_LEAGUE_TABLES')}?${params}`;
            const response = await this.refreshTokenService.makeApiRequest({ url });
            if (this._staleAsyncTabLoad('tables', g)) return;
            const data = await response.json();

            if (!data.success) throw new Error(data.error || 'שגיאה בטעינת הטבלאות');

            const rows = data.data || [];
            this.allTables = rows;
            if (this._publicTablesLeaguesMeta?.length) {
                this.buildTablesLeagueFilterFromMeta();
            }
            this.renderTables(this.allTables);
            this._savePublicTablesFiltersToStorage();
        } catch (err) {
            if (this._staleAsyncTabLoad('tables', g)) return;
            container.innerHTML = `<div class="error-message">שגיאה: ${err.message}</div>`;
        }
    }

    applyPublicTablesFiltersFromMetadata() {
        const hidden = document.getElementById('tablesSectionFilter');
        const list = document.getElementById('tablesSectionList');
        const combo = document.getElementById('tablesSectionCombo');
        if (!hidden || !list || !combo) return;
        const sections = this._publicTablesSectionsMeta || [];
        const current = hidden.value;
        this._fillPublicSectionLeagueComboboxList(list, {
            emptyLabel: 'כל הקטגוריות',
            items: sections.map(s => ({ value: s, label: s })),
        });
        if (current && sections.includes(current)) hidden.value = current;
        else hidden.value = '';
        this._syncComboboxLabelFromHidden(hidden, combo, list);
        this.buildTablesLeagueFilterFromMeta();
    }

    buildTablesLeagueFilterFromMeta() {
        const hidden = document.getElementById('tablesLeagueFilter');
        const list = document.getElementById('tablesLeagueList');
        const combo = document.getElementById('tablesLeagueCombo');
        if (!hidden || !list || !combo) return;
        const current = hidden.value;
        const sectionFilter = document.getElementById('tablesSectionFilter')?.value || '';
        const leagueRows = this._publicTablesLeaguesMeta || [];
        const filtered = sectionFilter ? leagueRows.filter(t => t.section === sectionFilter) : leagueRows;
        const displayFor = (row) => row.displayName || row.leagueName;
        const leagues = [...new Set(filtered.map(t => t.leagueName).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'he'));
        const items = leagues.map((ln) => {
            const row = filtered.find((r) => r.leagueName === ln);
            return { value: ln, label: row ? displayFor(row) : ln };
        });
        this._fillPublicSectionLeagueComboboxList(list, { emptyLabel: 'כל הליגות', items });
        if (current && leagues.includes(current)) hidden.value = current;
        else hidden.value = '';
        this._syncComboboxLabelFromHidden(hidden, combo, list);
    }

    _readPublicGamesFiltersFromStorage() {
        try {
            const raw = localStorage.getItem(this._LS_PUBLIC_GAMES_FILTERS);
            if (!raw) return null;
            const o = JSON.parse(raw);
            return o && typeof o === 'object' ? o : null;
        } catch {
            return null;
        }
    }

    _savePublicGamesFiltersToStorage() {
        try {
            const r = document.getElementById('publicGamesRadiusSlider');
            const data = {
                tenantKey: document.getElementById('publicGamesTenantFilter')?.value || '',
                section: document.getElementById('publicGamesSectionFilter')?.value || '',
                leagueName: document.getElementById('publicGamesLeagueFilter')?.value || '',
                fromDate: document.getElementById('publicGamesFromDateFilter')?.value || '',
                toDate: document.getElementById('publicGamesToDateFilter')?.value || '',
                field: document.getElementById('publicGamesFieldValue')?.value || '',
                refereeMobile: document.getElementById('publicGamesRefereeValue')?.value || '',
                radiusIdx: r && !r.disabled && r.value !== '' ? parseInt(r.value, 10) : null,
                sortColumn: this._publicGamesSortColumn,
                sortDir: this._publicGamesSortDir,
                includeGamesWithoutTime: document.getElementById('publicGamesIncludeNoTime')?.checked !== false,
            };
            localStorage.setItem(this._LS_PUBLIC_GAMES_FILTERS, JSON.stringify(data));
        } catch {
            /* ignore */
        }
    }

    _applyPublicGamesFiltersFromSaved(saved) {
        if (!saved) return;
        if (typeof saved.sortColumn === 'string' && saved.sortColumn) {
            this._publicGamesSortColumn = saved.sortColumn;
        }
        if (saved.sortDir === 'asc' || saved.sortDir === 'desc') {
            this._publicGamesSortDir = saved.sortDir;
        }
        const sections = this._publicGamesSectionsMeta || [];
        const sec = saved.section;
        if (sec && typeof sec === 'string' && sections.includes(sec)) {
            const h = document.getElementById('publicGamesSectionFilter');
            if (h) h.value = sec;
        }
        this.buildPublicGamesSectionFilterFromMeta();
        this.buildPublicGamesLeagueFilterFromMeta();
        const leagueRows = this._publicGamesLeaguesMeta || [];
        const sectionFilter = document.getElementById('publicGamesSectionFilter')?.value || '';
        const filtered = sectionFilter
            ? leagueRows.filter((g) => g.section === sectionFilter)
            : leagueRows;
        const leagueSet = new Set(filtered.map((g) => g.leagueName).filter(Boolean));
        const ln = saved.leagueName;
        if (ln && typeof ln === 'string' && leagueSet.has(ln)) {
            const hl = document.getElementById('publicGamesLeagueFilter');
            if (hl) hl.value = ln;
        }
        this.buildPublicGamesLeagueFilterFromMeta();
        if (typeof saved.field === 'string' && saved.field) {
            const fh = document.getElementById('publicGamesFieldValue');
            if (fh) fh.value = saved.field;
        }
        this.buildPublicGamesFieldFilterFromStrings(this._publicGamesFieldsMeta || []);
        {
            const rv =
                (typeof saved.refereeMobile === 'string' && saved.refereeMobile) ||
                (typeof saved.referee === 'string' && saved.referee) ||
                '';
            const rh = document.getElementById('publicGamesRefereeValue');
            if (rv && rh) rh.value = rv;
        }
        this.buildPublicGamesRefereeFilterFromReferees(this._publicGamesRefereesMeta || [], false);
        const r = document.getElementById('publicGamesRadiusSlider');
        if (
            r &&
            !r.disabled &&
            saved.radiusIdx != null &&
            Number.isFinite(saved.radiusIdx) &&
            saved.radiusIdx >= 0 &&
            saved.radiusIdx < this._radiusMilestones.length
        ) {
            r.value = String(saved.radiusIdx);
            const label = document.getElementById('publicGamesRadiusLabel');
            if (label) label.textContent = this._radiusLabel(saved.radiusIdx);
        }
        const incNoTime = document.getElementById('publicGamesIncludeNoTime');
        if (incNoTime) {
            incNoTime.checked = saved.includeGamesWithoutTime !== false;
        }
    }

    _readPublicTablesFiltersFromStorage() {
        try {
            const raw = localStorage.getItem(this._LS_PUBLIC_TABLES_FILTERS);
            if (!raw) return null;
            const o = JSON.parse(raw);
            return o && typeof o === 'object' ? o : null;
        } catch {
            return null;
        }
    }

    _savePublicTablesFiltersToStorage() {
        try {
            const data = {
                tenantKey: document.getElementById('tablesTenantFilter')?.value || '',
                section: document.getElementById('tablesSectionFilter')?.value || '',
                leagueName: document.getElementById('tablesLeagueFilter')?.value || '',
            };
            localStorage.setItem(this._LS_PUBLIC_TABLES_FILTERS, JSON.stringify(data));
        } catch {
            /* ignore */
        }
    }

    _applyPublicTablesFiltersFromSaved(saved) {
        if (!saved) return;
        const sections = this._publicTablesSectionsMeta || [];
        const sec = saved.section;
        if (sec && typeof sec === 'string' && sections.includes(sec)) {
            const h = document.getElementById('tablesSectionFilter');
            if (h) h.value = sec;
        }
        this.applyPublicTablesFiltersFromMetadata();
        const leagueRows = this._publicTablesLeaguesMeta || [];
        const sectionFilter = document.getElementById('tablesSectionFilter')?.value || '';
        const filtered = sectionFilter ? leagueRows.filter((t) => t.section === sectionFilter) : leagueRows;
        const leagueSet = new Set(filtered.map((t) => t.leagueName).filter(Boolean));
        const ln = saved.leagueName;
        if (ln && typeof ln === 'string' && leagueSet.has(ln)) {
            const hl = document.getElementById('tablesLeagueFilter');
            if (hl) hl.value = ln;
        }
        this.buildTablesLeagueFilterFromMeta();
    }

    _renderPublicTournamentTableFloatingPanelBody() {
        const body = document.getElementById('publicTournamentTableFloatingPanelBody');
        if (!body) return;
        const tables = this._publicTournamentPanelTables || [];
        if (!tables.length) {
            body.innerHTML = '<div class="empty-state">לא נמצאה טבלה לליגה זו</div>';
            return;
        }
        const html = tables.map((t, i) => this.renderSingleTable(t, i)).join('');
        body.innerHTML = html || '<div class="empty-state">לא נמצאה טבלה לליגה זו</div>';
    }

    closePublicTournamentTableFloatingPanel() {
        this._publicTournamentPanelFetchGen = (this._publicTournamentPanelFetchGen || 0) + 1;
        const panel = document.getElementById('publicTournamentTableFloatingPanel');
        if (panel) {
            panel.hidden = true;
            panel.setAttribute('aria-hidden', 'true');
        }
        this._publicTournamentPanelTables = null;
        const body = document.getElementById('publicTournamentTableFloatingPanelBody');
        if (body) body.innerHTML = '';
    }

    /** League / tournament cell in public (or referee-panel) games: floating sheet with same table as טבלאות ציבוריות. */
    async openPublicTournamentTableFloatingPanel({ tenantKey, section, leagueName }) {
        const t = (tenantKey || document.getElementById('publicGamesTenantFilter')?.value || '').trim();
        const league = (leagueName || '').trim();
        if (!t || !league) return;

        this.closeRefereeGamesFloatingPanel();

        const titleEl = document.getElementById('publicTournamentTableFloatingPanelTitle');
        const panel = document.getElementById('publicTournamentTableFloatingPanel');
        const body = document.getElementById('publicTournamentTableFloatingPanelBody');
        if (!panel || !body) return;

        this._publicTournamentPanelFetchGen = (this._publicTournamentPanelFetchGen || 0) + 1;
        const gen = this._publicTournamentPanelFetchGen;

        if (titleEl) titleEl.textContent = `${league} — טוען...`;
        body.innerHTML = '<div class="loading">טוען טבלה...</div>';
        panel.hidden = false;
        panel.setAttribute('aria-hidden', 'false');

        const sec = (section || '').trim();

        try {
            const params = new URLSearchParams();
            params.set('tenantKey', t);
            if (sec) params.set('section', sec);
            params.set('leagueName', league);

            const url = `${this.getConfig('ENDPOINTS.PUBLIC_LEAGUE_TABLES')}?${params}`;
            const response = await this.refreshTokenService.makeApiRequest({ url });
            if (gen !== this._publicTournamentPanelFetchGen) return;
            const data = await response.json();
            if (gen !== this._publicTournamentPanelFetchGen) return;

            if (!data.success) throw new Error(data.error || 'שגיאה בטעינת הטבלה');

            let rows = data.data || [];
            if (rows.length > 1) {
                rows = rows.filter((r) => (r.leagueName || '').trim() === league);
            }
            this._publicTournamentPanelTables = rows;

            if (gen !== this._publicTournamentPanelFetchGen) return;

            const first = rows[0];
            if (titleEl) {
                const disp = first?.displayName || first?.leagueName || league;
                titleEl.textContent = disp;
            }
            this._renderPublicTournamentTableFloatingPanelBody();
        } catch (err) {
            if (gen !== this._publicTournamentPanelFetchGen) return;
            if (titleEl) titleEl.textContent = league;
            body.innerHTML = `<div class="error-message">שגיאה: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    renderTables(tables) {
        const container = document.getElementById('tablesContent');
        if (!container) return;
        if (!tables.length) {
            container.innerHTML = '<div class="empty-state">לא נמצאו טבלאות</div>';
            return;
        }
        this.ensurePublicTablesSortListener();
        container.innerHTML = tables.map((t, i) => this.renderSingleTable(t, i)).join('');
    }

    ensurePublicTablesSortListener() {
        if (this._publicTablesSortListenerBound) return;
        const container = document.getElementById('tablesContent');
        if (!container) return;
        this._publicTablesSortListenerBound = true;
        container.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-public-table-sort]');
            if (!btn || !container.contains(btn)) return;
            e.preventDefault();
            const sortKey = btn.dataset.publicTableSort;
            if (sortKey !== 'מיקום' && sortKey !== 'אחוז') return;
            const card = btn.closest('[data-public-table-index]');
            const idx = card ? parseInt(card.dataset.publicTableIndex, 10) : NaN;
            const table = this.allTables?.[idx];
            const leagueName = table?.leagueName;
            if (!leagueName) return;
            this._publicTableSortByLeague = this._publicTableSortByLeague || Object.create(null);
            this._publicTableSortByLeague[leagueName] = sortKey;
            if (this.allTables?.length) this.renderTables(this.allTables);
        });
    }

    ensurePublicTournamentPanelSortListener() {
        if (this._publicTournamentPanelSortListenerBound) return;
        const container = document.getElementById('publicTournamentTableFloatingPanelBody');
        if (!container) return;
        this._publicTournamentPanelSortListenerBound = true;
        container.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-public-table-sort]');
            if (!btn || !container.contains(btn)) return;
            e.preventDefault();
            const sortKey = btn.dataset.publicTableSort;
            if (sortKey !== 'מיקום' && sortKey !== 'אחוז') return;
            const card = btn.closest('[data-public-table-index]');
            const idx = card ? parseInt(card.dataset.publicTableIndex, 10) : NaN;
            const table = this._publicTournamentPanelTables?.[idx];
            const ln = table?.leagueName;
            if (!ln) return;
            this._publicTableSortByLeague = this._publicTableSortByLeague || Object.create(null);
            this._publicTableSortByLeague[ln] = sortKey;
            if (this._publicTournamentPanelTables?.length) this._renderPublicTournamentTableFloatingPanelBody();
        });
    }

    renderSingleTable(tableData, tableIndex = 0) {
        const rows = tableData.table || [];
        if (!rows.length) return '';
        const leagueName = tableData.leagueName || '';
        const sortBy = (this._publicTableSortByLeague && this._publicTableSortByLeague[leagueName]) || 'מיקום';

        const cols = ['מיקום', 'קבוצה', 'משחקים', 'ניצחונות', 'תיקו', 'הפסדים', 'שערים', 'הפרש', 'נקודות', 'אחוז'];
        const statInt = (row, keys) => {
            for (const k of keys) {
                const v = row[k];
                if (v === undefined || v === null) continue;
                const n = parseInt(String(v).replace(/\D/g, ''), 10);
                if (!Number.isNaN(n)) return n;
            }
            return NaN;
        };
        const rankKey = (row) => {
            const r = parseInt(String(row['מיקום'] ?? '').replace(/\D/g, ''), 10);
            return Number.isNaN(r) ? 9999 : r;
        };
        /** Ratio pts/(games*3), or -1 if invalid. */
        const pctRatio = (row) => {
            const games = statInt(row, ['משחקים', 'מש׳']);
            const pts = statInt(row, ['נקודות', 'נק׳']);
            if (!Number.isFinite(games) || games <= 0 || !Number.isFinite(pts)) return -1;
            return pts / (games * 3);
        };
        /** Points ÷ (matches × 3), as % of maximum (3 pts per match). */
        const pointsPctDisplay = (row) => {
            const games = statInt(row, ['משחקים', 'מש׳']);
            const pts = statInt(row, ['נקודות', 'נק׳']);
            if (!Number.isFinite(games) || games <= 0 || !Number.isFinite(pts)) return '—';
            const pct = (pts / (games * 3)) * 100;
            return `${pct.toFixed(1)}%`;
        };

        let rowList = rows.slice();
        if (sortBy === 'מיקום') {
            rowList.sort((a, b) => {
                const d = rankKey(a) - rankKey(b);
                if (d !== 0) return d;
                const ta = String(a.team ?? a['קבוצה'] ?? '');
                const tb = String(b.team ?? b['קבוצה'] ?? '');
                return ta.localeCompare(tb, 'he');
            });
        } else {
            rowList.sort((a, b) => {
                const pa = pctRatio(a);
                const pb = pctRatio(b);
                if (pa < 0 && pb < 0) return rankKey(a) - rankKey(b);
                if (pa < 0) return 1;
                if (pb < 0) return -1;
                if (pb !== pa) return pb - pa;
                return rankKey(a) - rankKey(b);
            });
        }

        const thCell = (c) => {
            if (c === 'מיקום' || c === 'אחוז') {
                const active = sortBy === c ? ' public-league-table__sort--active' : '';
                return `<th scope="col"><button type="button" class="public-league-table__sort${active}" data-public-table-sort="${c}" aria-pressed="${sortBy === c ? 'true' : 'false'}">${c}</button></th>`;
            }
            return `<th scope="col">${c}</th>`;
        };
        const headers = cols.map(thCell).join('');

        const bodyRows = rowList.map((row, sortedIdx) => {
            let rowClass = 'public-league-table__row';
            if (sortBy === 'מיקום') {
                const rk = rankKey(row);
                if (rk === 1) rowClass += ' public-league-table__row--rank1';
                else if (rk === 2) rowClass += ' public-league-table__row--rank2';
                else if (rk === 3) rowClass += ' public-league-table__row--rank3';
            } else {
                if (sortedIdx === 0) rowClass += ' public-league-table__row--rank1';
                else if (sortedIdx === 1) rowClass += ' public-league-table__row--rank2';
                else if (sortedIdx === 2) rowClass += ' public-league-table__row--rank3';
            }
            let goalsDifference = null;
            const cells = cols.map((c, i) => {
                if (c === 'אחוז') {
                    return `<td class="public-league-table__cell public-league-table__cell--num" dir="ltr">${pointsPctDisplay(row)}</td>`;
                } else if (c === 'שערים') {
                    const goals = row[c].split('-');
                    goalsDifference = parseInt(goals[0], 10) - parseInt(goals[1], 10);
                }
                const isTeam = i === 1;
                let inner = isTeam ? (row['קבוצה'] || row.team || '') : (row[c] ?? row['team'] ?? '');
                const cls = isTeam
                    ? 'public-league-table__cell public-league-table__cell--team'
                    : 'public-league-table__cell public-league-table__cell--num';
                let style = '';
                if (c === 'הפרש') {
                    style = 'dir="ltr"';
                    inner = String(goalsDifference);
                }
                return `<td class="${cls}" ${style}>${inner}</td>`;
            });
            return `<tr class="${rowClass}">${cells.join('')}</tr>`;
        }).join('');
        const title = tableData.displayName || tableData.leagueName || '';
        return `
            <div class="public-league-table-card" data-public-table-index="${tableIndex}">
                <h3 class="public-league-table-card__title">${title}</h3>
                <div class="public-league-table-wrap">
                    <table class="public-league-table">
                        <thead>
                            <tr>${headers}</tr>
                        </thead>
                        <tbody>${bodyRows}</tbody>
                    </table>
                </div>
            </div>`;
    }

    // ── Public Games ───────────────────────────────────────────────────────────

    _fillPublicSectionLeagueComboboxList(listEl, { emptyLabel, items }) {
        listEl.innerHTML = '';
        const li0 = document.createElement('li');
        li0.setAttribute('role', 'option');
        li0.setAttribute('data-value', '');
        li0.textContent = emptyLabel;
        listEl.appendChild(li0);
        (items || []).forEach(({ value, label }) => {
            const li = document.createElement('li');
            li.setAttribute('role', 'option');
            li.setAttribute('data-value', value == null ? '' : String(value));
            li.textContent = label == null ? '' : String(label);
            listEl.appendChild(li);
        });
    }

    _syncComboboxLabelFromHidden(hidden, combo, list) {
        if (!hidden || !combo || !list) return;
        const v = hidden.value == null ? '' : String(hidden.value);
        const li = [...list.querySelectorAll('li[role="option"]')].find(
            (el) => (el.getAttribute('data-value') || '') === v
        );
        if (li) combo.value = (li.textContent || '').trim();
        else {
            hidden.value = '';
            const emptyLi = list.querySelector('li[data-value=""]');
            combo.value = emptyLi ? (emptyLi.textContent || '').trim() : '';
        }
    }

    _filterComboboxListByQuery(list, query) {
        if (!list) return;
        const q = (query || '').trim().toLowerCase();
        [...list.querySelectorAll('li[role="option"]')].forEach((li) => {
            const t = (li.textContent || '').toLowerCase();
            li.style.display = !q || t.includes(q) ? '' : 'none';
        });
    }

    _wireOneIncrementalCombobox(hiddenId, comboId, listId, wrapId) {
        const hidden = document.getElementById(hiddenId);
        const combo = document.getElementById(comboId);
        const list = document.getElementById(listId);
        const wrap = document.getElementById(wrapId);
        if (!hidden || !combo || !list || !wrap) return;
        const setOpen = (open) => {
            list.hidden = !open;
            combo.setAttribute('aria-expanded', open ? 'true' : 'false');
        };
        const applyPick = (li) => {
            if (!li) return;
            const raw = li.getAttribute('data-value');
            const v = raw == null ? '' : raw;
            hidden.value = v;
            combo.value = (li.textContent || '').trim();
            setOpen(false);
            hidden.dispatchEvent(new Event('change', { bubbles: true }));
        };
        combo.addEventListener('focus', () => {
            this._filterComboboxListByQuery(list, '');
            setOpen(true);
        });
        combo.addEventListener('input', () => {
            this._filterComboboxListByQuery(list, combo.value);
            setOpen(true);
            if (!combo.value.trim()) {
                if (hidden.value) {
                    hidden.value = '';
                    hidden.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
        });
        list.addEventListener('mousedown', (e) => {
            const li = e.target.closest('li[role="option"]');
            if (!li || !list.contains(li)) return;
            e.preventDefault();
            applyPick(li);
        });
        combo.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            const first = [...list.querySelectorAll('li[role="option"]')].find(
                (li) => li.style.display !== 'none'
            );
            if (first) {
                e.preventDefault();
                applyPick(first);
            }
        });
        combo.addEventListener('blur', () => {
            setTimeout(() => {
                if (wrap.contains(document.activeElement)) return;
                this._syncComboboxLabelFromHidden(hidden, combo, list);
            }, 150);
        });
    }

    setupSectionLeagueComboboxes() {
        if (this._sectionLeagueComboboxesWired) return;
        this._sectionLeagueComboboxesWired = true;
        this._wireOneIncrementalCombobox(
            'tablesSectionFilter',
            'tablesSectionCombo',
            'tablesSectionList',
            'tablesSectionCombobox'
        );
        this._wireOneIncrementalCombobox(
            'tablesLeagueFilter',
            'tablesLeagueCombo',
            'tablesLeagueList',
            'tablesLeagueCombobox'
        );
        this._wireOneIncrementalCombobox(
            'publicGamesSectionFilter',
            'publicGamesSectionCombo',
            'publicGamesSectionList',
            'publicGamesSectionCombobox'
        );
        this._wireOneIncrementalCombobox(
            'publicGamesLeagueFilter',
            'publicGamesLeagueCombo',
            'publicGamesLeagueList',
            'publicGamesLeagueCombobox'
        );
        const closes = [
            'tablesSectionCombobox',
            'tablesLeagueCombobox',
            'publicGamesSectionCombobox',
            'publicGamesLeagueCombobox',
        ];
        document.addEventListener('mousedown', (e) => {
            closes.forEach((id) => {
                const w = document.getElementById(id);
                if (!w || w.contains(e.target)) return;
                const list = w.querySelector('.public-games-combobox-list');
                const combo = w.querySelector('input.filter-select, input[aria-autocomplete="list"]');
                if (list) list.hidden = true;
                if (combo) combo.setAttribute('aria-expanded', 'false');
            });
        });
    }

    setupPublicGamesComboboxes() {
        if (this._publicGamesComboboxesWired) return;
        const fieldCombo = document.getElementById('publicGamesFieldCombo');
        const fieldList = document.getElementById('publicGamesFieldList');
        const fieldHidden = document.getElementById('publicGamesFieldValue');
        const fieldWrap = document.getElementById('publicGamesFieldCombobox');
        const refCombo = document.getElementById('publicGamesRefereeCombo');
        const refList = document.getElementById('publicGamesRefereeList');
        const refHidden = document.getElementById('publicGamesRefereeValue');
        const refWrap = document.getElementById('publicGamesRefereeCombobox');
        if (!fieldCombo || !fieldList || !refCombo || !refList) return;
        this._publicGamesComboboxesWired = true;

        const setFieldOpen = (open) => {
            fieldList.hidden = !open;
            fieldCombo.setAttribute('aria-expanded', open ? 'true' : 'false');
        };
        const setRefOpen = (open) => {
            refList.hidden = !open;
            refCombo.setAttribute('aria-expanded', open ? 'true' : 'false');
        };

        fieldCombo.addEventListener('focus', () => {
            this._filterPublicGamesFieldCombobox(fieldCombo.value);
            setFieldOpen(true);
        });
        fieldCombo.addEventListener('input', () => {
            this._filterPublicGamesFieldCombobox(fieldCombo.value);
            setFieldOpen(true);
        });
        fieldList.addEventListener('mousedown', (e) => {
            const li = e.target.closest('li');
            if (!li || !fieldList.contains(li)) return;
            e.preventDefault();
            const raw = li.dataset.value;
            const v = raw ? decodeURIComponent(raw) : (li.textContent || '').trim();
            if (fieldHidden) fieldHidden.value = v;
            fieldCombo.value = v;
            setFieldOpen(false);
        });
        fieldCombo.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            const first = [...fieldList.querySelectorAll('li')].find(li => li.style.display !== 'none');
            if (first) {
                e.preventDefault();
                first.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
            }
        });

        refCombo.addEventListener('focus', () => {
            this._filterPublicGamesRefereeCombobox(refCombo.value);
            setRefOpen(true);
        });
        refCombo.addEventListener('input', () => {
            if (!refCombo.value.trim() && refHidden) refHidden.value = '';
            this._filterPublicGamesRefereeCombobox(refCombo.value);
            setRefOpen(true);
        });
        refList.addEventListener('mousedown', (e) => {
            const li = e.target.closest('li');
            if (!li || !refList.contains(li)) return;
            e.preventDefault();
            if (refHidden) refHidden.value = li.dataset.value || '';
            refCombo.value = (li.textContent || '').trim();
            setRefOpen(false);
        });
        refCombo.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            const first = [...refList.querySelectorAll('li')].find(li => li.style.display !== 'none');
            if (first) {
                e.preventDefault();
                first.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
            }
        });

        document.addEventListener('mousedown', (e) => {
            if (fieldWrap && !fieldWrap.contains(e.target)) setFieldOpen(false);
            if (refWrap && !refWrap.contains(e.target)) setRefOpen(false);
        });
    }

    _filterPublicGamesFieldCombobox(query) {
        const list = document.getElementById('publicGamesFieldList');
        if (!list) return;
        const q = (query || '').trim().toLowerCase();
        [...list.children].forEach(li => {
            const t = (li.textContent || '').toLowerCase();
            li.style.display = !q || t.includes(q) ? '' : 'none';
        });
    }

    _filterPublicGamesRefereeCombobox(query) {
        const list = document.getElementById('publicGamesRefereeList');
        if (!list) return;
        const qRaw = (query || '').trim();
        const q = qRaw.toLowerCase();
        const qDigits = qRaw.replace(/\D/g, '');
        [...list.children].forEach(li => {
            const t = (li.textContent || '').trim().toLowerCase();
            const dv = li.dataset.value || '';
            const dvDigits = dv.startsWith('n:') ? '' : dv.replace(/\D/g, '');
            let match = !qRaw;
            if (!match && t.includes(q)) match = true;
            // Same phone rules as API: full match or suffix (avoids matching random digit substrings)
            if (!match && qDigits && dvDigits) {
                if (dvDigits === qDigits || dvDigits.endsWith(qDigits)) match = true;
            }
            li.style.display = match ? '' : 'none';
        });
    }

    /** Load filter options from PUBLIC_GAMES_FILTERS (not full games list). */
    async bootstrapPublicGamesFilters() {
        const container = document.getElementById('publicGamesList');
        if (!container) return;
        this._setPublicGamesTotalCountDisplay(null);
        container.innerHTML = '<div class="loading">טוען מסננים...</div>';
        try {
            const tenantKey = document.getElementById('publicGamesTenantFilter')?.value || '';
            const params = new URLSearchParams();
            if (tenantKey) params.set('tenantKey', tenantKey);
            const url = `${this.getConfig('ENDPOINTS.PUBLIC_GAMES_FILTERS')}?${params}`;
            const response = await this.refreshTokenService.makeApiRequest({ url });
            const data = await response.json();
            if (!data.success) throw new Error(data.error || 'שגיאה בטעינת מסננים');

            const d = data.data || {};
            this._publicGamesSectionsMeta = d.sections || [];
            this._publicGamesLeaguesMeta = d.leagues || [];
            this._publicGamesFieldsMeta = d.fields || [];
            this._fieldsDataByTenant = new Map();
            const refs = d.referees || [];
            this._publicGamesRefereesMeta = refs.length ? refs : [];
            this.applyPublicGamesFiltersFromMetadata();
            this.allPublicGames = [];
            container.innerHTML = tenantKey
                ? '<div class="info-message">בחר קטגוריה או ליגה להצגת משחקים</div>'
                : '<div class="info-message">בחר עונה, או קטגוריה או ליגה להצגת משחקים</div>';
        } catch (err) {
            this._setPublicGamesTotalCountDisplay(null);
            container.innerHTML = `<div class="error-message">שגיאה: ${err.message}</div>`;
        }
    }

    async loadPublicGamesData() {
        const container = document.getElementById('publicGamesList');
        if (!container) return;

        const g = this._beginAsyncTabLoad('publicGames');

        const tenantKey = document.getElementById('publicGamesTenantFilter')?.value || '';
        if (!tenantKey) {
            this._setPublicGamesTotalCountDisplay(null);
            container.innerHTML = '<div class="info-message">יש לבחור עונה להצגת משחקים</div>';
            return;
        }

        const fieldComboEl = document.getElementById('publicGamesFieldCombo');
        const fieldHiddenEl = document.getElementById('publicGamesFieldValue');
        if (fieldComboEl && fieldHiddenEl) fieldHiddenEl.value = fieldComboEl.value.trim();

        const section = document.getElementById('publicGamesSectionFilter')?.value || '';
        const leagueName = document.getElementById('publicGamesLeagueFilter')?.value || '';
        const refereeVal = document.getElementById('publicGamesRefereeValue')?.value || '';
        const field = document.getElementById('publicGamesFieldValue')?.value?.trim() || '';
        const fromDate = document.getElementById('publicGamesFromDateFilter')?.value || '';
        const toDate = document.getElementById('publicGamesToDateFilter')?.value || '';
        const bootstrapOnly = !fromDate || !toDate;

        if (bootstrapOnly) {
            await this.bootstrapPublicGamesFilters();
            if (this._staleAsyncTabLoad('publicGames', g)) return;
            this._savePublicGamesFiltersToStorage();
            return;
        }

        this._setPublicGamesTotalCountDisplay(null);
        this._showPublicGamesLoadingProgress();

        try {
            const params = new URLSearchParams();
            params.set('tenantKey', tenantKey);
            if (section) params.set('section', section);
            if (leagueName) params.set('leagueName', leagueName);
            if (refereeVal.startsWith('n:')) {
                const byName = decodeURIComponent(refereeVal.slice(2)).trim();
                if (byName) params.set('referee', byName);
            } else {
                const m = String(refereeVal);//.replace(/\D/g, '');
                if (m) params.set('refereeMobile', m);
            }
            if (fromDate) params.set('fromDate', fromDate);
            if (toDate) {
                let _toDate = new Date(toDate);
                _toDate.setHours(23, 59, 59, 999);
                params.set('toDate', this.toIsoString(_toDate));
            }
            if (field) params.set('field', field);

            const streamPath =
                this.getConfig('ENDPOINTS.PUBLIC_GAMES_STREAM') || '/api/pwa/public/games/stream';
            const streamUrl = `${streamPath}?${params}`;
            const games = await this._fetchPublicGamesStream(streamUrl, (current, total, tournamentName, phase) => {
                if (!this._staleAsyncTabLoad('publicGames', g)) {
                    this._setPublicGamesLoadProgress(current, total, tournamentName, phase);
                }
            });
            if (this._staleAsyncTabLoad('publicGames', g)) return;

            if (this._publicGamesLeaguesMeta?.length) {
                this.buildPublicGamesLeagueFilterFromMeta();
            }
            this.allPublicGames = games;
            await this._ensurePublicGamesFieldsRepository(tenantKey);
            if (this._staleAsyncTabLoad('publicGames', g)) return;
            await this.applyPublicGamesRadiusFilter(() => this._staleAsyncTabLoad('publicGames', g));
            if (this._staleAsyncTabLoad('publicGames', g)) return;
            this._savePublicGamesFiltersToStorage();
        } catch (err) {
            if (this._staleAsyncTabLoad('publicGames', g)) return;
            this._setPublicGamesTotalCountDisplay(null);
            container.innerHTML = `<div class="error-message">שגיאה: ${err.message}</div>`;
        }
    }

    _showPublicGamesLoadingProgress() {
        const container = document.getElementById('publicGamesList');
        if (!container) return;
        container.innerHTML = `
            <div class="loading public-games-loading">
                <div id="publicGamesLoadProgressLabel" class="public-games-load-progress-label">טוען משחקים...</div>
                <div class="chat-sync-progress public-games-load-progress">
                    <div id="publicGamesLoadProgressBar" class="chat-sync-progress-bar" style="width: 0%"></div>
                </div>
            </div>`;
    }

    _setPublicGamesLoadProgress(current, total, tournamentName = '', phase = '') {
        const bar = document.getElementById('publicGamesLoadProgressBar');
        const label = document.getElementById('publicGamesLoadProgressLabel');
        if (!bar || !label) return;
        const safeTotal = Math.max(0, Number(total) || 0);
        const safeCurrent = Math.max(0, Number(current) || 0);
        const pct = safeTotal > 0 ? Math.min(100, Math.round((safeCurrent / safeTotal) * 100)) : 5;
        bar.style.width = `${pct}%`;
        if (safeTotal > 0) {
            const leaguePart = tournamentName ? `: ${tournamentName}` : '';
            const phaseLabel = phase === 'index'
                ? 'מאתר משחקים'
                : phase === 'games'
                    ? 'טוען משחקים'
                    : phase === 'prepare'
                        ? 'מכין'
                        : 'טוען ליגות';
            label.textContent = `${phaseLabel}${leaguePart} (${Math.min(safeCurrent + (phase === 'games' || phase === 'index' ? 1 : 0), safeTotal)}/${safeTotal})`;
        } else {
            label.textContent = phase === 'prepare' ? 'מכין רשימת ליגות...' : 'טוען משחקים...';
        }
    }

    async _fetchPublicGamesStream(url, onProgress) {
        if (!url || String(url).startsWith('null')) {
            throw new Error('Public games stream endpoint is not configured');
        }
        let response;
        try {
            response = await this.refreshTokenService.makeAuthenticatedStreamRequest(url);
        } catch (streamErr) {
            const fallbackPath =
                this.getConfig('ENDPOINTS.PUBLIC_GAMES') || '/api/pwa/public/games';
            const fallbackUrl = url.replace(
                /\/api\/pwa\/public\/games\/stream/,
                fallbackPath
            );
            if (typeof onProgress === 'function') {
                onProgress(0, 0, '', 'prepare');
            }
            response = await this.refreshTokenService.makeApiRequest({ url: fallbackUrl });
            const data = await response.json();
            if (!data.success) throw new Error(data.error || 'שגיאה בטעינת המשחקים');
            return data.data || [];
        }
        if (!response.ok) {
            if (response.status === 404) {
                const fallbackPath =
                    this.getConfig('ENDPOINTS.PUBLIC_GAMES') || '/api/pwa/public/games';
                const fallbackUrl = url.replace(
                    /\/api\/pwa\/public\/games\/stream/,
                    fallbackPath
                );
                const fallbackResponse = await this.refreshTokenService.makeApiRequest({ url: fallbackUrl });
                const data = await fallbackResponse.json();
                if (!data.success) throw new Error(data.error || 'שגיאה בטעינת המשחקים');
                return data.data || [];
            }
            let message = `HTTP ${response.status}`;
            try {
                const errJson = await response.json();
                message = errJson.error || message;
            } catch (_) {}
            throw new Error(message);
        }
        if (!response.body) {
            throw new Error('Streaming not supported');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        const games = [];

        const handleEvent = (event) => {
            if (!event || typeof event !== 'object') return;
            if (event.type === 'progress' && typeof onProgress === 'function') {
                onProgress(
                    event.current || 0,
                    event.total || 0,
                    event.tournamentName || '',
                    event.phase || '',
                );
            } else if (event.type === 'chunk' && Array.isArray(event.games)) {
                games.push(...event.games);
            } else if (event.type === 'error') {
                throw new Error(event.error || 'שגיאה בטעינת המשחקים');
            }
        };

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop() || '';
            for (const part of parts) {
                const line = part.split('\n').find((l) => l.startsWith('data: '));
                if (!line) continue;
                handleEvent(JSON.parse(line.slice(6)));
            }
        }
        if (buffer.trim()) {
            const line = buffer.split('\n').find((l) => l.startsWith('data: '));
            if (line) handleEvent(JSON.parse(line.slice(6)));
        }

        games.sort((a, b) => {
            const ad = String(a.date || a.gameDate || a.scheduledDate || '');
            const bd = String(b.date || b.gameDate || b.scheduledDate || '');
            return bd.localeCompare(ad);
        });
        return games;
    }

    async loadPublicRefereesList() {
        try {
            const url = this.getConfig('ENDPOINTS.PUBLIC_REFEREES');
            const response = await this.refreshTokenService.makeApiRequest({ url });
            const data = await response.json();
            if (!data.success) return;
            this._allRefereeNames = data.data || [];
            this.buildPublicGamesRefereeFilterFromReferees(this._publicGamesRefereesMeta || [], false);
        } catch (_) {}
    }

    applyPublicGamesFiltersFromMetadata() {
        this.buildPublicGamesSectionFilterFromMeta();
        this.buildPublicGamesLeagueFilterFromMeta();
        this.buildPublicGamesRefereeFilterFromReferees(this._publicGamesRefereesMeta || []);
        this.buildPublicGamesFieldFilterFromStrings(this._publicGamesFieldsMeta || []);
    }

    _formatPublicRefereeOptionLabel(r) {
        if (!r || typeof r !== 'object') return '';
        const name = (r.name || '').trim();
        const m = String(r.mobileNo || '');
        const tail = m.length >= 3 ? m.slice(-3) : m;
        return name ? `${name} (${tail})` : m;
    }

    buildPublicGamesSectionFilterFromMeta() {
        const hidden = document.getElementById('publicGamesSectionFilter');
        const list = document.getElementById('publicGamesSectionList');
        const combo = document.getElementById('publicGamesSectionCombo');
        if (!hidden || !list || !combo) return;
        const sections = this._publicGamesSectionsMeta || [];
        const current = hidden.value;
        this._fillPublicSectionLeagueComboboxList(list, {
            emptyLabel: 'כל הקטגוריות',
            items: sections.map((s) => ({ value: s, label: s })),
        });
        if (current && sections.includes(current)) hidden.value = current;
        else hidden.value = '';
        this._syncComboboxLabelFromHidden(hidden, combo, list);
    }

    buildPublicGamesLeagueFilterFromMeta() {
        const hidden = document.getElementById('publicGamesLeagueFilter');
        const list = document.getElementById('publicGamesLeagueList');
        const combo = document.getElementById('publicGamesLeagueCombo');
        if (!hidden || !list || !combo) return;
        const sectionFilter = document.getElementById('publicGamesSectionFilter')?.value || '';
        const leagueRows = this._publicGamesLeaguesMeta || [];
        const filtered = sectionFilter
            ? leagueRows.filter((g) => g.section === sectionFilter)
            : leagueRows;
        const displayFor = (row) => row.displayName || row.leagueName;
        const leagues = [...new Set(filtered.map((g) => g.leagueName).filter(Boolean))].sort((a, b) =>
            a.localeCompare(b, 'he')
        );
        const current = hidden.value;
        const items = leagues.map((ln) => {
            const row = filtered.find((r) => r.leagueName === ln);
            return { value: ln, label: row ? displayFor(row) : ln };
        });
        this._fillPublicSectionLeagueComboboxList(list, { emptyLabel: 'כל הליגות', items });
        if (current && leagues.includes(current)) hidden.value = current;
        else hidden.value = '';
        this._syncComboboxLabelFromHidden(hidden, combo, list);
    }

    buildPublicGamesRefereeFilterFromReferees(referees, updateMeta = true) {
        const listEl = document.getElementById('publicGamesRefereeList');
        const combo = document.getElementById('publicGamesRefereeCombo');
        const hidden = document.getElementById('publicGamesRefereeValue');
        if (!listEl) return;
        const list = Array.isArray(referees) ? referees : [];

        const renderGlobalNames = (names) => {
            listEl.innerHTML = '';
            names.forEach(name => {
                const li = document.createElement('li');
                li.setAttribute('role', 'option');
                li.dataset.value = `n:${encodeURIComponent(name)}`;
                li.textContent = name;
                listEl.appendChild(li);
            });
        };

        if (!list.length && this._allRefereeNames?.length) {
            if (updateMeta) this._publicGamesRefereesMeta = [];
            renderGlobalNames(this._allRefereeNames);
            if (combo && hidden) {
                const hv = hidden.value || '';
                if (hv.startsWith('n:')) {
                    const nm = decodeURIComponent(hv.slice(2));
                    if (!this._allRefereeNames.includes(nm)) {
                        hidden.value = '';
                        combo.value = '';
                    } else {
                        combo.value = nm;
                    }
                } else if (hv && !hv.startsWith('n:')) {
                    hidden.value = '';
                    combo.value = '';
                }
            }
            return;
        }
        if (updateMeta) this._publicGamesRefereesMeta = list;
        const currentHidden = hidden?.value || '';
        listEl.innerHTML = '';
        list.forEach((r) => {
            const li = document.createElement('li');
            li.setAttribute('role', 'option');
            const name = (r.name || '').trim();
            const mobile = String(r.mobileNo || '').trim();
            const digits = mobile.replace(/\D/g, '');
            // Hidden value = referee mobile (query param refereeMobile to pwaGetPublicGames). Name-only: n:…
            li.dataset.value = digits ? mobile : (name ? `n:${encodeURIComponent(name)}` : '');
            if (!li.dataset.value) {
                return;
            }
            li.textContent = this._formatPublicRefereeOptionLabel(r);
            listEl.appendChild(li);
        });
        if (combo && hidden && currentHidden) {
            const ch = currentHidden.replace(/\D/g, '');
            const still = list.some((r) => {
                const m = String(r.mobileNo || '').trim();
                return m && m.replace(/\D/g, '') && m.replace(/\D/g, '') === ch;
            }) || (currentHidden.startsWith('n:') &&
                list.some((r) => `n:${encodeURIComponent((r.name || '').trim())}` === currentHidden));
            if (!still) {
                hidden.value = '';
                combo.value = '';
            } else if (currentHidden.startsWith('n:')) {
                combo.value = decodeURIComponent(currentHidden.slice(2));
            } else {
                const row = list.find(
                    (r) => String(r.mobileNo || '').trim().replace(/\D/g, '') === ch
                );
                if (row) combo.value = this._formatPublicRefereeOptionLabel(row);
            }
        }
    }

    buildPublicGamesFieldFilterFromStrings(fields) {
        const listEl = document.getElementById('publicGamesFieldList');
        if (!listEl) return;
        const sorted = [...(fields || [])].sort((a, b) => a.localeCompare(b, 'he'));
        const hidden = document.getElementById('publicGamesFieldValue');
        const combo = document.getElementById('publicGamesFieldCombo');
        const prev = hidden?.value || '';
        listEl.innerHTML = '';
        sorted.forEach(v => {
            const li = document.createElement('li');
            li.setAttribute('role', 'option');
            li.dataset.value = encodeURIComponent(v);
            li.textContent = v;
            listEl.appendChild(li);
        });
        if (combo && hidden) {
            if (prev && !sorted.includes(prev)) {
                hidden.value = '';
                combo.value = '';
            } else if (prev) {
                combo.value = prev;
            }
        }
    }

    // Slider index → km (index 5 = unlimited)
    _radiusMilestones = [5, 10, 20, 40, 80, Infinity];

    _radiusLabel(index) {
        const km = this._radiusMilestones[index];
        return km === Infinity ? 'ללא הגבלה' : `${km} ק"מ`;
    }

    _haversineKm(lat1, lng1, lat2, lng2) {
        const R = 6371;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLng = (lng2 - lng1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) ** 2 +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
        const distance = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return distance;
    }

    async _ensureUserLocation() {
        if (this.userLocation) {
            this._enableRadiusSlider();
            return this.userLocation;
        }
        if (this._locationDenied) return null;
        return new Promise((resolve) => {
            if (!navigator.geolocation) {
                this._locationDenied = true;
                this._disableRadiusSlider();
                resolve(null);
                return;
            }
            navigator.geolocation.getCurrentPosition(
                pos => {
                    this.userLocation = { lat: pos.coords.latitude, lng: pos.coords.longitude };
                    this._enableRadiusSlider();
                    resolve(this.userLocation);
                },
                () => {
                    this._locationDenied = true;
                    this._disableRadiusSlider();
                    resolve(null);
                },
                { timeout: 8000, maximumAge: 60000 }
            );
        });
    }

    _enableRadiusSlider() {
        const slider = document.getElementById('publicGamesRadiusSlider');
        const label = document.getElementById('publicGamesRadiusLabel');
        if (!slider) return;
        slider.disabled = false;
        slider.removeAttribute('title');
        const idx = parseInt(slider.value, 10);
        if (label) label.textContent = this._radiusLabel(Number.isNaN(idx) ? 5 : idx);
    }

    _disableRadiusSlider(statusLabel = 'מיקום לא זמין') {
        const slider = document.getElementById('publicGamesRadiusSlider');
        const label = document.getElementById('publicGamesRadiusLabel');
        if (!slider) return;
        slider.value = 5;
        slider.disabled = true;
        slider.title = 'נדרש שיתוף מיקום בדפדפן כדי לסנן לפי מרחק';
        if (label) label.textContent = statusLabel;
    }

    _normalizeFieldLookupKey(s) {
        return String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
    }

    _fieldDataHasCoordinates(fd) {
        if (!fd || typeof fd !== 'object') return false;
        const c = fd.addressDetails?.coordinates;
        return c != null && c.lat != null && c.lng != null && c.lat !== '' && c.lng !== '';
    }

    /** One fields-table row -> synthetic fieldData for merge / map (or null if no lat/lng). */
    _syntheticFieldDataFromFieldRow(f) {
        if (!f || typeof f !== 'object') return null;
        const rawAddr = f.addressDetails;
        const addr = rawAddr && typeof rawAddr === 'object' ? { ...rawAddr } : {};
        const c0 = addr.coordinates || f.coordinates || {};
        const lat = c0.lat;
        const lng = c0.lng;
        if (lat == null || lng == null || lat === '' || lng === '') return null;
        return {
            addressDetails: {
                ...addr,
                coordinates: { lat: Number(lat), lng: Number(lng) },
                wazeLink: addr.wazeLink || f.wazeLink || '',
            },
        };
    }

    /** Build Map(normalizedFieldLabel -> synthetic fieldData) from /api/pwa/fields list. */
    _buildPublicGamesFieldDataMap(fields) {
        const m = new Map();
        if (!Array.isArray(fields)) return m;
        for (const f of fields) {
            const synthetic = this._syntheticFieldDataFromFieldRow(f);
            if (!synthetic) continue;
            const names = [f.fieldName, f.name, f.title].filter((x) => x != null && String(x).trim() !== '');
            for (const n of names) {
                const k = this._normalizeFieldLookupKey(n);
                if (k) m.set(k, synthetic);
            }
        }
        return m;
    }

    async _ensurePublicGamesFieldsRepository(tenantKey) {
        if (!tenantKey) return;
        if (!this._fieldsDataByTenant) this._fieldsDataByTenant = new Map();
        if (this._fieldsDataByTenant.has(tenantKey)) return;
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.FIELDS'),
                params: { filterText: '', tenantKey }
            });
            if (!response.ok) {
                this._fieldsDataByTenant.set(tenantKey, new Map());
                return;
            }
            const result = await response.json();
            const rows = result.success && result.data ? result.data : [];
            this._fieldsDataByTenant.set(tenantKey, this._buildPublicGamesFieldDataMap(rows));
        } catch (_) {
            this._fieldsDataByTenant.set(tenantKey, new Map());
        }
    }

    /** Prefetch tenant field maps for a list of games (referee “all tenants” view). */
    async _ensureFieldsRepositoryForGames(games) {
        if (!Array.isArray(games) || !games.length) return;
        const seen = new Set();
        for (const g of games) {
            const tk = g.tenantKey || g.tenant_key || g.tournamentTenant;
            if (!tk || seen.has(tk)) continue;
            seen.add(tk);
            await this._ensurePublicGamesFieldsRepository(tk);
        }
    }

    _findFieldRowInAllFields(tenantKey, normKey) {
        const rows = this.allFields;
        if (!Array.isArray(rows) || !normKey) return null;
        for (const f of rows) {
            if (!f || typeof f !== 'object') continue;
            if (tenantKey && f.tenantKey != null && String(f.tenantKey) !== String(tenantKey)) continue;
            const names = [f.fieldName, f.name, f.title].filter(Boolean);
            if (names.some((n) => this._normalizeFieldLookupKey(n) === normKey)) return f;
        }
        return null;
    }

    /**
     * Resolved fieldData: use game.fieldData when it has coordinates; else fields API cache per tenant;
     * else Fields tab list (allFields).
     */
    _resolveFieldDataForGame(game) {
        const direct = game.fieldData && typeof game.fieldData === 'object' ? game.fieldData : null;
        if (this._fieldDataHasCoordinates(direct)) return direct;

        const tk = game.tenantKey || game.tenant_key || '';
        const label = (game.field || game.fieldName || '').trim();
        if (!label) return direct;

        const norm = this._normalizeFieldLookupKey(label);

        if (tk && this._fieldsDataByTenant) {
            const per = this._fieldsDataByTenant.get(tk);
            if (per) {
                const syn = per.get(norm);
                if (syn && this._fieldDataHasCoordinates(syn)) return syn;
            }
        }

        const raw = this._findFieldRowInAllFields(tk || null, norm);
        const fromAll = this._syntheticFieldDataFromFieldRow(raw);
        if (fromAll && this._fieldDataHasCoordinates(fromAll)) return fromAll;

        return direct;
    }

    _gameFieldCoords(game) {
        const fd = this._resolveFieldDataForGame(game);
        const coords = fd?.addressDetails?.coordinates;
        if (coords != null && coords.lat != null && coords.lng != null && coords.lat !== '' && coords.lng !== '') {
            return { lat: Number(coords.lat), lng: Number(coords.lng) };
        }
        return null;
    }

    _toIsoDateLocal(d) {
        if (!(d instanceof Date) || isNaN(d.getTime())) return '';
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${day}`;
    }

    /** Default public games range: today → today + 7 days (local calendar). */
    applyPublicGamesDefaultDateRange() {
        const fromEl = document.getElementById('publicGamesFromDateFilter');
        const toEl = document.getElementById('publicGamesToDateFilter');
        if (!fromEl || !toEl) return;
        const today = new Date();
        const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        const end = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 6);
        fromEl.value = this._toIsoDateLocal(start);
        toEl.value = this._toIsoDateLocal(end);
    }

    applyPublicGamesDefaultDateRangeIfEmpty() {
        const fromEl = document.getElementById('publicGamesFromDateFilter');
        const toEl = document.getElementById('publicGamesToDateFilter');
        if (!fromEl || !toEl) return;
        if (fromEl.value || toEl.value) return;
        this.applyPublicGamesDefaultDateRange();
    }

    /** If "from" is after "to", move "עד תאריך" up to match (ISO date inputs compare lexicographically). */
    _clampPublicGamesToDateToFrom() {
        const fromEl = document.getElementById('publicGamesFromDateFilter');
        const toEl = document.getElementById('publicGamesToDateFilter');
        if (!fromEl || !toEl) return;
        const fromV = String(fromEl.value || '').trim();
        const toV = String(toEl.value || '').trim();
        if (!fromV || !toV || fromV <= toV) return;
        toEl.value = fromV;
        this._dispatchFilterChange(toEl);
    }

    async applyPublicGamesRadiusFilter(isStale = null) {
        const stale = () => typeof isStale === 'function' && isStale();

        const slider = document.getElementById('publicGamesRadiusSlider');
        const label = document.getElementById('publicGamesRadiusLabel');
        if (!slider) return;

        const idx = parseInt(slider.value, 10);
        const maxKm = this._radiusMilestones[idx];
        if (label) label.textContent = this._radiusLabel(idx);

        if (maxKm === Infinity) {
            if (!stale()) this._refreshPublicGamesTable();
            return;
        }

        const location = await this._ensureUserLocation();
        if (stale()) return;

        if (!location) {
            this.showToast('לא ניתן לקבל מיקום — בדוק הרשאות גישה למיקום', 'warning');
            this._disableRadiusSlider();
            if (!stale()) this._refreshPublicGamesTable();
            return;
        }

        if (!stale()) this._refreshPublicGamesTable();
    }

    _getPublicGamesForTableViewSync() {
        const all = this.allPublicGames || [];
        let list = [...all];
        const slider = document.getElementById('publicGamesRadiusSlider');
        const idx = slider ? parseInt(slider.value, 10) : 5;
        const maxKm = this._radiusMilestones[Number.isNaN(idx) ? 5 : idx];
        if (maxKm !== Infinity && this.userLocation) {
            list = list.filter((game) => {
                const coords = this._gameFieldCoords(game);
                if (!coords) return true;
                const distance = this._haversineKm(this.userLocation.lat, this.userLocation.lng, coords.lat, coords.lng);
                return distance <= maxKm;
            });
        }
        const includeNoTime = document.getElementById('publicGamesIncludeNoTime')?.checked !== false;
        if (!includeNoTime) {
            list = list.filter((g) => !this._publicGameIsMissingKickoffTime(g));
        }
        return list;
    }

    /**
     * True when the game has no scheduled kickoff time (date-only, 00:00 placeholder, or empty time fields).
     */
    _publicGameIsMissingKickoffTime(game) {
        const timeOnly = game.gameTime || game.game_time || game.scheduledTime;
        if (timeOnly != null && String(timeOnly).trim()) return false;
        const raw =
            game.date ||
            game.gameDate ||
            game.game_date ||
            game.scheduledDate ||
            game.dateTime ||
            game.scheduledDateTime;
        if (raw == null || !String(raw).trim()) return true;
        const rawStr = String(raw).trim();
        if (/^\d{4}-\d{2}-\d{2}$/.test(rawStr)) return true;
        if (/T00:00:00(\.000)?Z?$/i.test(rawStr)) return true;
        const d = new Date(raw);
        if (isNaN(d.getTime())) return true;
        return false;
    }

    _getPublicGameDateSortKey(game) {
        const raw = game.date || game.gameDate || game.scheduledDate || game.dateTime || game.scheduledDateTime;
        if (raw) {
            const d = new Date(raw);
            if (!isNaN(d.getTime())) {
                return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
            }
        }
        return 0;
    }

    _getPublicGameTimeSortKey(game) {
        const raw = game.date || game.gameDate || game.scheduledDate || game.dateTime || game.scheduledDateTime;
        if (raw) {
            const d = new Date(raw);
            if (!isNaN(d.getTime())) return d.getTime();
        }
        const t = game.gameTime || game.game_time || game.scheduledTime;
        return t ? String(t) : '';
    }

    _getPublicGameScoreSortKey(game) {
        const ft = game.gameResult?.fullTime || game.fullTimeResult || game.gameResult?.full_time_score;
        if (Array.isArray(ft) && ft.length >= 2) {
            const h = parseInt(ft[0], 10);
            const g = parseInt(ft[1], 10);
            if (!isNaN(h) && !isNaN(g)) return h * 1000 + g;
        }
        return this._formatPublicGameScore(game);
    }

    _publicGameRoundFixtureStrings(game) {
        const round = game.round ?? game.gameRound ?? game.round_number ?? game['סבב'];
        const fixture = game.fixture ?? game.gameFixture ?? game.fixture_number ?? game['מחזור'];
        return {
            roundStr: round != null && round !== '' ? String(round).trim() : '',
            fixtureStr: fixture != null && fixture !== '' ? String(fixture).trim() : '',
        };
    }

    _getPublicGameSortValue(game, column) {
        switch (column) {
            case 'date':
                return this._getPublicGameDateSortKey(game);
            case 'time':
                return this._getPublicGameTimeSortKey(game);
            case 'league':
                return (game.leagueName || game.tournamentName || '').trim();
            case 'round': {
                const { roundStr } = this._publicGameRoundFixtureStrings(game);
                return roundStr;
            }
            case 'fixture': {
                const { fixtureStr } = this._publicGameRoundFixtureStrings(game);
                return fixtureStr;
            }
            case 'home':
                return (game.homeTeamName || game.homeTeam || game.home_team || '').trim();
            case 'guest':
                return (game.guestTeamName || game.guestTeam || game.guest_team || '').trim();
            case 'score':
                return this._getPublicGameScoreSortKey(game);
            case 'field':
                return (game.field || game.fieldName || '').trim();
            default:
                return '';
        }
    }

    _sortPublicGamesArray(games, column, dir) {
        if (!column || !games?.length) return [...games];
        const mult = dir === 'desc' ? -1 : 1;
        const list = [...games];
        list.sort((ga, gb) => {
            const va = this._getPublicGameSortValue(ga, column);
            const vb = this._getPublicGameSortValue(gb, column);
            const numA = typeof va === 'number' && !Number.isNaN(va);
            const numB = typeof vb === 'number' && !Number.isNaN(vb);
            let cmp = 0;
            if (numA && numB) cmp = mult * (va - vb);
            else cmp = mult * String(va ?? '').localeCompare(String(vb ?? ''), 'he', { numeric: true, sensitivity: 'base' });
            if (cmp !== 0) return cmp;
            if (column === 'date') {
                const ta = this._getPublicGameTimeSortKey(ga);
                const tb = this._getPublicGameTimeSortKey(gb);
                const tNumA = typeof ta === 'number' && !Number.isNaN(ta);
                const tNumB = typeof tb === 'number' && !Number.isNaN(tb);
                if (tNumA && tNumB) return mult * (ta - tb);
                return mult * String(ta ?? '').localeCompare(String(tb ?? ''), 'he', { numeric: true, sensitivity: 'base' });
            }
            return 0;
        });
        return list;
    }

    _publicGamesSortThHtml(label, col) {
        const active = this._publicGamesSortColumn === col;
        const arrow = active ? (this._publicGamesSortDir === 'asc' ? ' ▲' : ' ▼') : '';
        const ariaSort = active ? (this._publicGamesSortDir === 'asc' ? 'ascending' : 'descending') : 'none';
        return `<th scope="col" class="public-games-table__th public-games-table__th--sortable" data-public-games-sort="${col}" aria-sort="${ariaSort}">${label}<span class="public-games-table__sort-indicator" aria-hidden="true">${arrow}</span></th>`;
    }

    _setPublicGamesTotalCountDisplay(count) {
        const el = document.getElementById('publicGamesTotalCount');
        if (!el) return;
        if (typeof count !== 'number' || Number.isNaN(count)) {
            el.hidden = true;
            el.textContent = '';
            return;
        }
        el.hidden = false;
        el.textContent =
            count === 1 ? 'נמצא משחק אחד' : `נמצאו ${count} משחקים`;
    }

    _refreshPublicGamesTable() {
        const container = document.getElementById('publicGamesList');
        if (!container) return;
        const games = this._getPublicGamesForTableViewSync();
        this._setPublicGamesTotalCountDisplay(games.length);
        if (!games.length) {
            container.innerHTML = '<div class="empty-state">לא נמצאו משחקים</div>';
            return;
        }
        const sorted = this._publicGamesSortColumn
            ? this._sortPublicGamesArray(games, this._publicGamesSortColumn, this._publicGamesSortDir)
            : games;
        const rows = sorted.map((game, idx) => this.renderPublicGameTableRows(game, idx)).join('');
        container.innerHTML = `
            <div class="public-games-table-wrap">
                <table class="public-games-table" dir="rtl">
                    <thead>
                        <tr>
                            <th class="public-games-table__th public-games-table__th--exp" scope="col"><span class="visually-hidden">פתיחה</span></th>
                            ${this._publicGamesSortThHtml('תאריך', 'date')}
                            ${this._publicGamesSortThHtml('שעה', 'time')}
                            ${this._publicGamesSortThHtml('ליגה', 'league')}
                            ${this._publicGamesSortThHtml('סבב', 'round')}
                            ${this._publicGamesSortThHtml('מחזור', 'fixture')}
                            ${this._publicGamesSortThHtml('קבוצת בית', 'home')}
                            ${this._publicGamesSortThHtml('קבוצת אורח', 'guest')}
                            ${this._publicGamesSortThHtml('תוצאה', 'score')}
                            ${this._publicGamesSortThHtml('מגרש', 'field')}
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    _refereeGamesPanelSortThHtml(label, col) {
        const active = this._refereeGamesPanelSortColumn === col;
        const arrow = active ? (this._refereeGamesPanelSortDir === 'asc' ? ' ▲' : ' ▼') : '';
        const ariaSort = active
            ? this._refereeGamesPanelSortDir === 'asc'
                ? 'ascending'
                : 'descending'
            : 'none';
        return `<th scope="col" class="public-games-table__th public-games-table__th--sortable" data-referee-panel-sort="${col}" aria-sort="${ariaSort}">${label}<span class="public-games-table__sort-indicator" aria-hidden="true">${arrow}</span></th>`;
    }

    _normalizeRefereePanelName(name) {
        return String(name || '')
            .trim()
            .replace(/\s+/g, ' ')
            .toLowerCase();
    }

    _getRefereesArrayFromGame(game) {
        const r = game.referees || game.nested;
        if (!r) return [];
        const arr = Array.isArray(r) ? r : Object.values(r);
        return arr.filter((x) => x && typeof x === 'object');
    }

    _renderRefereeGamesFloatingPanelTable() {
        const container = document.getElementById('refereeGamesFloatingPanelBody');
        if (!container) return;
        const games = this._refereeGamesPanelGamesSnapshot;
        if (!games.length) {
            container.innerHTML = '<div class="empty-state">אין משחקים להצגה</div>';
            return;
        }
        const sorted = this._refereeGamesPanelSortColumn
            ? this._sortPublicGamesArray(
                  games,
                  this._refereeGamesPanelSortColumn,
                  this._refereeGamesPanelSortDir
              )
            : games;
        const rows = sorted
            .map((game, idx) => this.renderPublicGameTableRows(game, idx, 'refereePanelGameDetail_'))
            .join('');
        container.innerHTML = `
            <div class="public-games-table-wrap">
                <table class="public-games-table" dir="rtl">
                    <thead>
                        <tr>
                            <th class="public-games-table__th public-games-table__th--exp" scope="col"><span class="visually-hidden">פתיחה</span></th>
                            ${this._refereeGamesPanelSortThHtml('תאריך', 'date')}
                            ${this._refereeGamesPanelSortThHtml('שעה', 'time')}
                            ${this._refereeGamesPanelSortThHtml('ליגה', 'league')}
                            ${this._refereeGamesPanelSortThHtml('סבב', 'round')}
                            ${this._refereeGamesPanelSortThHtml('מחזור', 'fixture')}
                            ${this._refereeGamesPanelSortThHtml('קבוצת בית', 'home')}
                            ${this._refereeGamesPanelSortThHtml('קבוצת אורח', 'guest')}
                            ${this._refereeGamesPanelSortThHtml('תוצאה', 'score')}
                            ${this._refereeGamesPanelSortThHtml('מגרש', 'field')}
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    /** Date range for referee floating panel: games-tab filters if both set, else wide default. */
    _getRefereeGamesPanelPublicDateRange() {
        const fromEl = document.getElementById('gamesFromDateFilter');
        const toEl = document.getElementById('gamesToDateFilter');
        const fromVal = (fromEl?.value || '').trim();
        const toVal = (toEl?.value || '').trim();
        if (false &&fromVal && toVal) {
            const to = new Date(toVal);
            to.setHours(23, 59, 59, 999);
            return { fromDateStr: fromVal, toDateIso: this.toIsoString(to) };
        }
        const from = new Date();
        from.setFullYear(from.getFullYear() - 2);
        const fromDateStr = from.toISOString().split('T')[0];
        const to = new Date();
        to.setFullYear(to.getFullYear() + 1);
        to.setHours(23, 59, 59, 999);
        return { fromDateStr, toDateIso: this.toIsoString(to) };
    }

    /** Use public-API mobile filter when * phone is a real number (not tmpRefId: / too short). */
    _refereePanelPhoneEligibleForPublicMobileFilter(phoneRaw) {
        const p = String(phoneRaw || '').trim();
        if (!p || p.startsWith('tmpRefId:')) return false;
        const digits = p.replace(/\D/g, '');
        return digits.length >= 8;
    }

    async openRefereeGamesFloatingPanel(displayName, phoneRaw, gameTenantKey) {
        const nameNorm = this._normalizeRefereePanelName(displayName);
        if (!nameNorm) return;

        this.closePublicTournamentTableFloatingPanel();

        const titleEl = document.getElementById('refereeGamesFloatingPanelTitle');
        const panel = document.getElementById('refereeGamesFloatingPanel');
        const body = document.getElementById('refereeGamesFloatingPanelBody');
        if (!panel || !body) return;

        this._refereeGamesPanelFetchGen = (this._refereeGamesPanelFetchGen || 0) + 1;
        const gen = this._refereeGamesPanelFetchGen;

        if (titleEl) titleEl.textContent = `משחקים — ${displayName.trim()} (טוען...)`;
        this._refereeGamesPanelSortColumn = 'date';
        this._refereeGamesPanelSortDir = 'asc';
        this._refereeGamesPanelGamesSnapshot = [];
        body.innerHTML = '<div class="loading">טוען משחקים...</div>';
        panel.hidden = false;
        panel.setAttribute('aria-hidden', 'false');

        const tenantKey =
            (String(gameTenantKey || '').trim()) ||
            (document.getElementById('gamesTenantFilter')?.value || '').trim() ||
            (document.getElementById('publicGamesTenantFilter')?.value || '').trim();
        if (!tenantKey) {
            if (gen !== this._refereeGamesPanelFetchGen) return;
            if (titleEl) titleEl.textContent = `משחקים — ${displayName.trim()}`;
            body.innerHTML =
                '<div class="error-message">יש לבחור עונה במסנני משחקים (או בלוח משחקים ציבורי), או שחסר tenant למשחק הנוכחי.</div>';
            return;
        }

        const { fromDateStr, toDateIso } = this._getRefereeGamesPanelPublicDateRange();
        const params = new URLSearchParams();
        params.set('tenantKey', tenantKey);
        if (this._refereePanelPhoneEligibleForPublicMobileFilter(phoneRaw)) {
            params.set('refereeMobile', String(phoneRaw).trim());
        } else {
            const byName = String(displayName || '').trim();
            if (!byName) {
                if (gen !== this._refereeGamesPanelFetchGen) return;
                if (titleEl) titleEl.textContent = `משחקים — ${displayName.trim()}`;
                body.innerHTML = '<div class="error-message">חסר שם שופט.</div>';
                return;
            }
            params.set('referee', byName);
        }
        if (fromDateStr) params.set('fromDate', fromDateStr);
        if (toDateIso) params.set('toDate', toDateIso);

        try {
            const url = `${this.getConfig('ENDPOINTS.PUBLIC_GAMES')}?${params}`;
            const response = await this.refreshTokenService.makeApiRequest({ url });
            if (gen !== this._refereeGamesPanelFetchGen) return;
            const data = await response.json();
            if (!data.success) throw new Error(data.error || 'שגיאה בטעינת המשחקים');
            const games = data.data || [];
            await this._ensurePublicGamesFieldsRepository(tenantKey);
            if (gen !== this._refereeGamesPanelFetchGen) return;
            this._refereeGamesPanelGamesSnapshot = games;
            const n = games.length;
            if (titleEl) {
                titleEl.textContent = `משחקים — ${displayName.trim()}${n ? ` (${n})` : ''}`;
            }
            this._renderRefereeGamesFloatingPanelTable();
        } catch (err) {
            if (gen !== this._refereeGamesPanelFetchGen) return;
            if (titleEl) titleEl.textContent = `משחקים — ${displayName.trim()}`;
            body.innerHTML = `<div class="error-message">שגיאה: ${err.message}</div>`;
        }
    }

    closeRefereeGamesFloatingPanel() {
        this._refereeGamesPanelFetchGen = (this._refereeGamesPanelFetchGen || 0) + 1;
        const panel = document.getElementById('refereeGamesFloatingPanel');
        if (panel) {
            panel.hidden = true;
            panel.setAttribute('aria-hidden', 'true');
        }
        this._refereeGamesPanelGamesSnapshot = [];
    }

    _formatPublicGameScore(game) {
        const ftResult = game.gameResult?.fullTime || game.fullTimeResult || game.gameResult?.full_time_score;
        const htResult = game.gameResult?.halfTime || game.halfTimeResult || game.gameResult?.half_time_score;
        if (!ftResult && !htResult) return '';
        let s = '';
        if (ftResult) s += Array.isArray(ftResult) ? ftResult[1] + ':' + ftResult[0] : String(ftResult);
        if (htResult) {
            const ht = Array.isArray(htResult) ? htResult[1] + ':' + htResult[0] : String(htResult);
            s = `(${ht}) ${s}`;
        }
        return s;
    }

    /** Split scheduled datetime into display date + time columns (public games table). */
    _getPublicGameDateTimeDisplay(game) {
        const raw = game.date || game.gameDate || game.game_date || game.scheduledDate || game.dateTime || game.scheduledDateTime;
        if (raw) {
            const rawStr = String(raw).trim();
            const d = new Date(raw);
            if (!isNaN(d.getTime())) {
                const dateStr = this.formatDate(d);
                if (/^\d{4}-\d{2}-\d{2}$/.test(rawStr)) {
                    return { dateStr, timeStr: '' };
                }
                if (/T00:00:00(\.000)?Z?$/i.test(rawStr)) {
                    return { dateStr, timeStr: '' };
                }
                return { dateStr, timeStr: this.formatTime(d) };
            }
        }
        const timeOnly = game.gameTime || game.game_time || game.scheduledTime;
        if (timeOnly) return { dateStr: '', timeStr: String(timeOnly) };
        return { dateStr: '', timeStr: '' };
    }

    /** Field name cell / detail line with optional Waze link (public games table). */
    _formatPublicGameFieldHtml(gd, esc) {
        const name = (gd && gd.field) ? String(gd.field).trim() : '';
        if (!name) return '';
        const wazeHref = (gd.fieldWazeUrlLink || gd.fieldWazeLink || '').trim();
        if (!wazeHref) return esc(name);
        const safeHref = esc(wazeHref);
        return `<a class="public-games-table__field-link" href="${safeHref}" target="_blank" rel="noopener noreferrer" title="פתיחה ב-Waze">${esc(name)}</a>`;
    }

    renderPublicGameTableRows(game, idx, _detailIdPrefix = 'publicGameDetail_') {
        const gd = this.getGameDetails(game);
        const { dateStr, timeStr } = this._getPublicGameDateTimeDisplay(game);
        const { roundStr, fixtureStr } = this._publicGameRoundFixtureStrings(game);
        const homeTeam = game.homeTeamName || game.homeTeam || game.home_team || '';
        const guestTeam = game.guestTeamName || game.guestTeam || game.guest_team || '';
        const league = game.leagueName || game.tournamentName || '';
        const sectionForTables =
            game.section ||
            game.leagueSection ||
            (game.tournamentData && game.tournamentData.section) ||
            '';
        const tenantKeyForLink = (
            game.tenantKey ||
            document.getElementById('gamesTenantFilter')?.value ||
            document.getElementById('publicGamesTenantFilter')?.value ||
            ''
        ).trim();
        const esc = (v) => this.escapeHtml(v == null ? '' : String(v));
        const field = gd.field || game.field || game.fieldName || '';
        const fieldHtml = this._formatPublicGameFieldHtml(gd, esc);
        const status = game.status || game.state || '';
        const referees = this._getRefereesArrayFromGame(game);
        const scoreStr = this._formatPublicGameScore(game);
        const detailId = `${_detailIdPrefix}${idx}`;
        const gameUrl = (gd.gameUrl || '').trim();
        const gameLinkLine = gameUrl
            ? `<div class="public-games-table__detail-line"><a class="public-games-table__game-link" href="${esc(gameUrl)}" target="_blank" rel="noopener noreferrer">דף המשחק</a></div>`
            : '';

        const refereesBlock = referees.length
            ? `<div class="public-games-table__detail-line"><strong>שופטים:</strong> ${referees
                  .map((r) => {
                      const nm = r.name || r['* name'] || '';
                      const ro = r.role || r['role'] || '';
                      return esc(`${nm}${ro ? ` (${ro})` : ''}`);
                  })
                  .join(', ')}</div>`
            : '';

        const detailsInner = `
            <div class="public-games-table__detail-inner">
                ${gameLinkLine}
                ${league ? `<div class="public-games-table__detail-line"><strong>ליגה:</strong> ${esc(league)}</div>` : ''}
                ${roundStr ? `<div class="public-games-table__detail-line"><strong>סבב:</strong> ${esc(roundStr)}</div>` : ''}
                ${fixtureStr ? `<div class="public-games-table__detail-line"><strong>מחזור:</strong> ${esc(fixtureStr)}</div>` : ''}
                ${dateStr ? `<div class="public-games-table__detail-line"><strong>תאריך:</strong> ${esc(dateStr)}</div>` : ''}
                ${timeStr ? `<div class="public-games-table__detail-line"><strong>שעה:</strong> ${esc(timeStr)}</div>` : ''}
                ${field ? `<div class="public-games-table__detail-line"><strong>מגרש:</strong> ${fieldHtml || esc(field)}</div>` : ''}
                ${status ? `<div class="public-games-table__detail-line"><strong>סטטוס:</strong> <span class="public-games-table__status-badge" style="background:${this.getStatusColor(status)}">${esc(status)}</span></div>` : ''}
                ${refereesBlock}
            </div>`;

        const dash = (s) => (s ? esc(s) : '—');
        const leagueCell =
            league && tenantKeyForLink
                ? `<td class="public-games-table__cell public-games-table__cell--league"><button type="button" class="public-games-table__league-link" data-action="open-league-tables" data-tenant="${encodeURIComponent(tenantKeyForLink)}" data-section="${encodeURIComponent(sectionForTables)}" data-league="${encodeURIComponent(league)}" title="טבלאות ליגה">${esc(league)}</button></td>`
                : `<td class="public-games-table__cell public-games-table__cell--league">${league ? esc(league) : '—'}</td>`;

        return `
            <tr class="public-games-table__main-row" role="button" tabindex="0" aria-expanded="false" aria-controls="${detailId}">
                <td class="public-games-table__cell public-games-table__cell--exp"><span class="public-games-table__exp" aria-hidden="true">◀</span></td>
                <td class="public-games-table__cell public-games-table__cell--nowrap">${dash(dateStr)}</td>
                <td class="public-games-table__cell public-games-table__cell--time">${dash(timeStr)}</td>
                ${leagueCell}
                <td class="public-games-table__cell public-games-table__cell--round">${dash(roundStr)}</td>
                <td class="public-games-table__cell public-games-table__cell--fixture">${dash(fixtureStr)}</td>
                <td class="public-games-table__cell public-games-table__cell--team">${esc(homeTeam)}</td>
                <td class="public-games-table__cell public-games-table__cell--team">${esc(guestTeam)}</td>
                <td class="public-games-table__cell public-games-table__cell--score" dir="ltr">${esc(scoreStr) || '—'}</td>
                <td class="public-games-table__cell public-games-table__cell--field">${fieldHtml || dash(field)}</td>
            </tr>
            <tr class="public-games-table__detail-row" id="${detailId}" hidden role="region">
                <td colspan="10" class="public-games-table__detail-cell">${detailsInner}</td>
            </tr>`;
    }

    // ── Dashboard ──────────────────────────────────────────────────────────────

    async loadDashboardData() {
        const g = this._beginAsyncTabLoad('dashboard');
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url:this.getConfig('ENDPOINTS.DASHBOARD')
            });
            
            if (this._staleAsyncTabLoad('dashboard', g)) return;

            if (!response.ok) {
                // Check if it's a server down error
                if (this.isServerDownError({ status: response.status })) {
                    this.showDashboardServerDownState(response.status);
                } else {
                    this.showToast(response.message || 'שגיאה בטעינת נתוני הדשבורד', 'error');
                }
                return;
            }
            
            const data = await response.json();
            if (this._staleAsyncTabLoad('dashboard', g)) return;
            this.updateDashboardStats(data.data);
            this.createDashboardChart(data.data);
        } catch (error) {
            if (this._staleAsyncTabLoad('dashboard', g)) return;
            console.error('Error loading dashboard data:', error);
            
            // Check if it's a server down error
            if (this.isServerDownError(error)) {
                this.showDashboardServerDownState(503);
            } else {
                this.showToast('שגיאה בטעינת נתוני הדשבורד', 'error');
            }
        }
    }

    /** Prefetch referee games for next-game header / speed monitor; safe to run in parallel with dashboard. */
    async prefetchNextGameScheduleIfAuthenticated() {
        if (!this.isAuthenticated) return;
        try {
            await this.getPendingGames();
        } catch (e) {
            console.warn('⚠️ Next game prefetch failed:', e);
        }
    }

    /** Load dashboard and next-game schedule together (same wall-clock time as two requests). */
    async loadDashboardDataWithNextGameParallel() {
        await Promise.all([
            this.loadDashboardData(),
            this.prefetchNextGameScheduleIfAuthenticated(),
        ]);
    }

    async loadTenants() {
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.TENANTS')
            });

            if (!response.ok) {
                console.warn('Failed to load tenants, using default options');
                return;
            }

            const result = await response.json();
            if (result.success && result.data) {
                const tenants = result.data;
                this.tenants = tenants;
                await this.populateTenantFilters(tenants);
                console.log(`✅ Loaded ${tenants.length} tenants`);
            }
        } catch (error) {
            console.warn('Error loading tenants:', error);
        }
    }

    async loadRoles() {
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.ROLES'),
            });

            if (!response.ok) {
                console.warn('Failed to load roles, using default options');
                return;
            }

            const result = await response.json();
            if (result.success && result.data) {
                this.roles = result.data;
            }
        } catch (error) {
            console.warn('Error loading roles:', error);
        }
    }

    async populateTenantFilters(tenants) {
        // Populate games tenant filter
        const gamesTenantFilter = document.getElementById('gamesTenantFilter');
        const reviewsTenantFilter = document.getElementById('reviewsTenantFilter');
        const adminTenantFilter = document.getElementById('adminTenantFilter');

        if (gamesTenantFilter) {
            this._runWithDomQuiet('games', () => {
                gamesTenantFilter.innerHTML = '<option value="">הכל</option>';
                Object.values(tenants).forEach(tenant => {
                    const option = document.createElement('option');
                    option.value = tenant.entityKey;
                    option.textContent = tenant.name;
                    gamesTenantFilter.appendChild(option);
                });
            });
        }

        // Populate reviews tenant filter
        if (reviewsTenantFilter) {
            this._runWithDomQuiet('reviews', () => {
                reviewsTenantFilter.innerHTML = '<option value="">הכל</option>';
                Object.values(tenants).forEach(tenant => {
                    const option = document.createElement('option');
                    option.value = tenant.entityKey;
                    option.textContent = tenant.name;
                    reviewsTenantFilter.appendChild(option);
                });
            });
        }

        // Populate reviews tenant filter
        if (adminTenantFilter) {
            adminTenantFilter.innerHTML = '<option value="">הכל</option>';
            Object.values(tenants).forEach(tenant => {
                const option = document.createElement('option');
                option.value = tenant.entityKey;
                option.textContent = tenant.name;
                adminTenantFilter.appendChild(option);
            });
            
            // Pre-select tenant from storage
            const storedTenantKey = this.getStorageKey('adminTenantKey');
            if (storedTenantKey) {
                adminTenantFilter.value = storedTenantKey;
                // Load referees for the pre-selected tenant
                //await this.loadReferees();
            }
        }

        // Populate admin Templates and Notifications tenant filters (same options)
        const refereeTemplatesTenant = document.getElementById('refereeTemplatesTenant');
        const notificationsTenant = document.getElementById('notificationsTenant');
        const tenantOptions = '<option value="">כל העונות</option>' + Object.values(tenants).map(t => `<option value="${t.entityKey}">${t.name}</option>`).join('') + '<option value="GLOBAL">כללי</option>';
        if (refereeTemplatesTenant) refereeTemplatesTenant.innerHTML = tenantOptions;
        if (notificationsTenant) notificationsTenant.innerHTML = tenantOptions;

        // Populate public sections tenant filters
        const publicTenantOptions = '<option value="">כל העונות</option>' +
            Object.values(tenants).map(t => `<option value="${t.entityKey}">${t.name}</option>`).join('');
        ['tablesTenantFilter', 'publicGamesTenantFilter'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = publicTenantOptions;
        });

        console.log(`✅ Populated tenants filters with ${Object.keys(tenants || {}).length} options`);
    }

    async loadReferees() {
        try {
            const tenantKey = document.getElementById('adminTenantFilter').value;
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.REFEREES'),
                params: {
                    tenantKey: tenantKey,
                }
            });

            if (!response.ok) {
                console.warn('Failed to load referees, using default options');
                return;
            }

            const result = await response.json();
            if (result.success && result.data) {
                const referees = result.data;
                this.referees = referees;
                this.populateRefereeFilters(referees);
                const count = Array.isArray(referees) ? referees.length : Object.keys(referees || {}).length;
                console.log(`✅ Loaded ${count} referees`);
            }
        } catch (error) {
            console.warn('Error loading referees:', error);
        }
    }

    populateRefereeFilters(referees) {
        // Populate admin referee filter
        const adminRefereeFilter = document.getElementById('adminRefereeFilter');

        if (adminRefereeFilter) {
            adminRefereeFilter.innerHTML = '<option value="">כל השופטים</option>';
            if (Array.isArray(referees)) {
                referees.forEach(referee => {
                    const option = document.createElement('option');
                    option.value = referee.mobileNo || referee.refId || referee.id;
                    option.textContent = referee.name + ' ' + referee.mobileNo.slice(-3) || referee.refName || `${referee.refId || ''} - ${referee.mobileNo || ''}`;
                    adminRefereeFilter.appendChild(option);
                });
            } else if (typeof referees === 'object') {
                Object.values(referees).forEach(referee => {
                    const option = document.createElement('option');
                    option.value = referee.mobileNo || referee.refId || referee.id;
                    option.textContent = referee.name + ' ' + referee.mobileNo.slice(-3) || referee.refName || `${referee.refId || ''} - ${referee.mobileNo || ''}`;
                    adminRefereeFilter.appendChild(option);
                });
            }
            
            // Pre-select referee from storage
            const storedRefereeMobileNo = this.getStorageKey('adminApplyReferee');
            if (storedRefereeMobileNo) {
                adminRefereeFilter.value = storedRefereeMobileNo;
            }
        }

        const count = Array.isArray(referees) ? referees.length : Object.keys(referees || {}).length;
        console.log(`✅ Populated referee filters with ${count} options`);
    }

    async adminApplyRefereeSelection() {
        const tenantKey = document.getElementById('adminTenantFilter').value;
        const mobileNo = document.getElementById('adminRefereeFilter').value;
        const filter = document.getElementById('adminRefereeFilter');
        const label = filter.options[filter.selectedIndex]?.text || '';

        this.setStorageKey('adminTenantKey', tenantKey);
        this.setStorageKey('adminApplyReferee', mobileNo);
        this.setStorageKey('adminApplyRefereeLabel', label);
        this.showToast('שופט נבחר בהצלחה', 'success');
        this.updateUserInfoInHeader();
        await this.loadDashboardDataWithNextGameParallel();        
    }

    async adminResetRefereeSelection() {
        // Remove from storage
        this.removeStorageKey('adminApplyReferee');      
        this.removeStorageKey('adminApplyRefereeLabel');
        this.showToast('בחירת השופט אופסה בהצלחה', 'success');
        this.updateUserInfoInHeader();
        await this.loadDashboardDataWithNextGameParallel();        
    }

    async loadRefereeTemplates() {
        const tenantKeyFilter = document.getElementById('refereeTemplatesTenant');
        const actionFilter = document.getElementById('refereeTemplatesAction');
        const statusFilter = document.getElementById('refereeTemplatesStatus');
        const fromDateFilter = document.getElementById('refereeTemplatesFromDate');
        const toDateFilter = document.getElementById('refereeTemplatesToDate');

        if (fromDateFilter && !fromDateFilter.value) {
            let fromDate = new Date();
            fromDate.setDate(fromDate.getDate() - 7);
            fromDateFilter.value = fromDate.toISOString().split('T')[0];
        }
        
        if (toDateFilter && !toDateFilter.value) {
            let toDate = new Date();
            toDateFilter.value = toDate.toISOString().split('T')[0];
        }

        const params = new URLSearchParams();
        if (tenantKeyFilter) params.set('tenantKey', tenantKeyFilter?.value);
        if (actionFilter) params.set('action', actionFilter?.value);
        if (statusFilter) params.set('status', statusFilter?.value);
        if (fromDateFilter) params.set('fromDate', this.toIsoString(new Date(fromDateFilter?.value)));
        if (toDateFilter) {
            let toDate = new Date(toDateFilter?.value);
            toDate.setHours(23, 59, 59, 999);
            params.set('toDate', this.toIsoString(toDate));
        }
        const templatesDateTypeSelect = document.getElementById('refereeTemplatesDateType');
        if (templatesDateTypeSelect?.value) params.set('dateType', templatesDateTypeSelect.value);
        
        try {
            const url = this.getConfig('ENDPOINTS.REFEREE_TEMPLATES') + (params.toString() ? '?' + params.toString() : '');
            const response = await this.refreshTokenService.makeApiRequest({ url });
            if (!response.ok) {
                this.showToast('שגיאה בטעינת תבניות', 'error');
                return;
            }
            const result = await response.json();
            if (result.success && Array.isArray(result.data)) {
                this._templatesGridData = result.data;
                this.populateTemplatesMobileFilter(result.data);
                this.renderRefereeTemplatesGrid(this.getSortedTemplatesData());
                this._updateTemplatesApplyButtonLabel(result.data.length);
            } else {
                this._templatesGridData = [];
                this.populateTemplatesMobileFilter([]);
                this.renderRefereeTemplatesGrid([]);
                this._updateTemplatesApplyButtonLabel(0);
            }
        } catch (e) {
            console.warn('loadRefereeTemplates error:', e);
            this.showToast('שגיאה בטעינת תבניות', 'error');
            this._templatesGridData = [];
            this.populateTemplatesMobileFilter([]);
            this.renderRefereeTemplatesGrid([]);
            this._updateTemplatesApplyButtonLabel(0);
        }
    }

    _updateTemplatesApplyButtonLabel(count) {
        const btn = document.getElementById('refereeTemplatesApplyBtn');
        if (btn) btn.textContent = count >= 0 ? `החל תבניות (${count})` : 'החל תבניות';
    }

    _compareGridValues(a, b) {
        const aVal = a == null ? '' : (typeof a === 'string' ? a : String(a));
        const bVal = b == null ? '' : (typeof b === 'string' ? b : String(b));
        if (aVal < bVal) return -1;
        if (aVal > bVal) return 1;
        return 0;
    }

    getSortedTemplatesData() {
        this._templatesSort = this._templatesSort || { column: null, dir: 1 };
        let base = this._templatesGridData ? [...this._templatesGridData] : [];
        const mobileFilterEl = document.getElementById('refereeTemplatesMobile');
        const mobileFilter = mobileFilterEl?.value;
        if (mobileFilter) base = base.filter(row => (row.mobileNo || '') === mobileFilter);
        if (!this._templatesSort.column) return base;
        const col = this._templatesSort.column;
        const dir = this._templatesSort.dir;
        return base.sort((a, b) => this._compareGridValues(a[col], b[col]) * dir);
    }

    populateTemplatesMobileFilter(data) {
        const mobileSelect = document.getElementById('refereeTemplatesMobile');
        if (!mobileSelect) return;
        const currentValue = mobileSelect.value;
        const mobiles = [...new Set((data || []).map(row => row.mobileNo).filter(Boolean))].sort();
        mobileSelect.innerHTML = '<option value="">כל המספרים</option>' + mobiles.map(m => `<option value="${String(m).replace(/"/g, '&quot;')}">${m}</option>`).join('');
        if (mobiles.includes(currentValue)) mobileSelect.value = currentValue;
    }

    getSortedNotificationsData() {
        this._notificationsSort = this._notificationsSort || { column: null, dir: 1 };
        let base = this._notificationsGridData ? [...this._notificationsGridData] : [];
        const mobileFilterEl = document.getElementById('notificationsMobile');
        const mobileFilter = mobileFilterEl?.value;
        if (mobileFilter) base = base.filter(row => (row.to || '') === mobileFilter);
        if (!this._notificationsSort.column) return base;
        const col = this._notificationsSort.column;
        const dir = this._notificationsSort.dir;
        const getVal = (row) => (col === 'notificationType' ? (row.notificationType ?? row.type) : row[col]);
        return [...this._notificationsGridData].sort((a, b) => this._compareGridValues(getVal(a), getVal(b)) * dir);
    }

    renderRefereeTemplatesGrid(data) {
        const container = document.getElementById('refereeTemplatesGrid');
        if (!container) return;
        this._templatesSort = this._templatesSort || { column: null, dir: 1 };
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="admin-grid-placeholder">אין תבניות להצגה</div>';
            return;
        }
        const sort = this._templatesSort;
        const cols = [
            { key: 'tenantKey', label: 'עונה' },
            { key: 'mobileNo', label: 'נייד' },
            { key: 'msgSid', label: 'msgSid' },
            { key: 'gameId', label: 'מזהה' },
            { key: 'action', label: 'פעולה' },
            { key: 'data', label: 'נתונים' },
            { key: 'status', label: 'סטטוס' },
            { key: 'message', label: 'הודעה' },
            { key: 'created', label: 'נוצר' },
            { key: 'updated', label: 'עודכן' },
            { key: 'retries', label: 'ניסיונות' }
        ];
        const thCells = cols.map(({ key, label }) => {
            const arrow = sort.column === key ? (sort.dir === 1 ? ' ↑' : ' ↓') : '';
            return `<th class="sortable" data-sort-key="${key}" title="מיין לפי ${label}">${label}${arrow}</th>`;
        }).join('');
        const statuses = ['created', 'completed', 'onHold', 'deferred', 'cancelled'];
        let html = `<table class="content-grid"><thead><tr>${thCells}<th>עדכון סטטוס</th></tr></thead><tbody>`;
        data.forEach(row => {
            const created = (row.created && row.created.slice) ? row.created.slice(0, 19) : (row.created || '');
            const updated = (row.updated && row.updated.slice) ? row.updated.slice(0, 19) : (row.updated || '');
            html += `<tr data-tenant="${(row.tenantKey || '').replace(/"/g, '&quot;')}" data-mobile="${(row.mobileNo || '').replace(/"/g, '&quot;')}" data-msgsid="${(row.msgSid || '').replace(/"/g, '&quot;')}">
                <td>${(row.tenantKey || '')}</td><td><a href="${this.txt2WhatsappLink(row.mobileNo || '')}" target="_blank">${row.mobileNo || ''}</a></td><td class="of15">${(row.msgSid || '')}</td><td>${(row.gameId || '')}</td><td>${(row.action || '')}</td><td class="of15">${(row.data || '')}</td>
                <td>${(row.status || '')}</td><td class="of15">${this.escapeHtml((row.message || row.msg || row.text || ''))}</td><td>${created}</td><td>${updated}</td><td>${(row.retries || '')}</td>
                <td><select class="compact-status" data-row-tenant="${(row.tenantKey || '').replace(/"/g, '&quot;')}" data-row-mobile="${(row.mobileNo || '').replace(/"/g, '&quot;')}" data-row-msgsid="${(row.msgSid || '').replace(/"/g, '&quot;')}">${statuses.map(s => `<option value="${s}" ${(row.status === s) ? 'selected' : ''}>${s}</option>`).join('')}</select>
                <button type="button" class="btn-update-status btn-primary compact">עדכן</button></td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
        container.querySelectorAll('th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const key = th.getAttribute('data-sort-key');
                if (this._templatesSort.column === key) this._templatesSort.dir *= -1;
                else { this._templatesSort.column = key; this._templatesSort.dir = -1; }
                this.renderRefereeTemplatesGrid(this.getSortedTemplatesData());
            });
        });
        container.querySelectorAll('.btn-update-status').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const tr = e.target.closest('tr');
                const select = tr.querySelector('select.compact-status');
                const tenantKey = select.getAttribute('data-row-tenant');
                const mobileNo = select.getAttribute('data-row-mobile');
                const msgSid = select.getAttribute('data-row-msgsid');
                const status = select.value;
                await this.updateRefereeTemplate(tenantKey, mobileNo, msgSid, status);
            });
        });
    }

    async updateRefereeTemplate(tenantKey, mobileNo, msgSid, status) {
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.REFEREE_TEMPLATE_UPDATE'),
                options: {
                    method: 'POST',
                    body: JSON.stringify({ tenantKey: tenantKey, mobileNo: mobileNo, msgSid: msgSid, status: status }),   
                }
            });
            const result = await response.json();
            if (result.success) {
                this.showToast('סטטוס עודכן', 'success');
                await this.loadRefereeTemplates();
            } else {
                this.showToast(result.error || 'שגיאה בעדכון סטטוס', 'error');
            }
        } catch (e) {
            console.warn('updateRefereeTemplate error:', e);
            this.showToast('שגיאה בעדכון סטטוס', 'error');
        }
    }

    async loadNotifications() {
        const tenantKeyFilter = document.getElementById('notificationsTenant');
        const targetFilter = document.getElementById('notificationsTarget');
        const idFilter = document.getElementById('notificationsId');
        const typeFilter = document.getElementById('notificationsType');
        const statusFilter = document.getElementById('notificationsStatus');
        const fromDateFilter = document.getElementById('notificationsFromDate');
        const toDateFilter = document.getElementById('notificationsToDate');

        if (fromDateFilter && !fromDateFilter.value) {
            let fromDate = new Date();
            fromDate.setDate(fromDate.getDate() - 7);
            fromDateFilter.value = fromDate.toISOString().split('T')[0];
        }
        if (toDateFilter && !toDateFilter.value) {
            let toDate = new Date();
            toDateFilter.value = toDate.toISOString().split('T')[0];
        }

        const params = new URLSearchParams();
        if (tenantKeyFilter?.value) params.set('tenantKey', tenantKeyFilter.value);
        if (targetFilter?.value) params.set('target', targetFilter.value);
        if (idFilter?.value) params.set('id', idFilter.value);
        if (typeFilter) params.set('type', typeFilter?.value);
        if (statusFilter) params.set('status', statusFilter?.value);
        if (fromDateFilter) params.set('fromDate', this.toIsoString(new Date(fromDateFilter?.value)));
        if (toDateFilter) {
            let toDate = new Date(toDateFilter?.value);
            toDate.setHours(23, 59, 59, 999);
            params.set('toDate', this.toIsoString(toDate));
        }
        const dateTypeSelect = document.getElementById('notificationsDateType');
        if (dateTypeSelect?.value) params.set('dateType', dateTypeSelect.value);
        
        try {
            const url = this.getConfig('ENDPOINTS.NOTIFICATIONS') + (params.toString() ? '?' + params.toString() : '');
            const response = await this.refreshTokenService.makeApiRequest({ url });
            if (!response.ok) {
                this.showToast('שגיאה בטעינת התראות', 'error');
                return;
            }
            const result = await response.json();
            if (result.success && Array.isArray(result.data)) {
                this.populateNotificationsIdFilter(result.data);
                this.populateNotificationsMobileFilter(result.data);
                this._notificationsGridData = result.data;
                this.renderNotificationsGrid(this.getSortedNotificationsData());
                this._updateNotificationsApplyButtonLabel(result.data.length);
            } else {
                this.populateNotificationsIdFilter([]);
                this.populateNotificationsMobileFilter([]);
                this._notificationsGridData = [];
                this.renderNotificationsGrid([]);
                this._updateNotificationsApplyButtonLabel(0);
            }
        } catch (e) {
            console.warn('loadNotifications error:', e);
            this.showToast('שגיאה בטעינת התראות', 'error');
            this.populateNotificationsIdFilter([]);
            this.populateNotificationsMobileFilter([]);
            this._notificationsGridData = [];
            this.renderNotificationsGrid([]);
            this._updateNotificationsApplyButtonLabel(0);
        }
    }

    _updateNotificationsApplyButtonLabel(count) {
        const btn = document.getElementById('notificationsApplyBtn');
        if (btn) btn.textContent = count >= 0 ? `החל התראות (${count})` : 'החל התראות';
    }

    populateNotificationsIdFilter(data) {
        const idSelect = document.getElementById('notificationsId');
        if (!idSelect) return;
        const currentValue = idSelect.value;
        const ids = [...new Set((data || []).map(row => row.id).filter(Boolean))].sort();
        idSelect.innerHTML = '<option value="">הכל</option>' + ids.map(id => `<option value="${String(id).replace(/"/g, '&quot;')}">${id}</option>`).join('');
        if (ids.includes(currentValue)) idSelect.value = currentValue;
    }

    populateNotificationsMobileFilter(data) {
        const mobileSelect = document.getElementById('notificationsMobile');
        if (!mobileSelect) return;
        const currentValue = mobileSelect.value;
        const mobiles = [...new Set((data || []).map(row => row.to).filter(Boolean))].sort();
        mobileSelect.innerHTML = '<option value="">הכל</option>' + mobiles.map(m => `<option value="${String(m).replace(/"/g, '&quot;')}">${this.escapeHtml(m)}</option>`).join('');
        if (mobiles.includes(currentValue)) mobileSelect.value = currentValue;
    }

    renderNotificationsGrid(data) {
        const container = document.getElementById('notificationsGrid');
        if (!container) return;
        this._notificationsSort = this._notificationsSort || { column: null, dir: 1 };
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="admin-grid-placeholder">אין התראות להצגה</div>';
            return;
        }
        const sort = this._notificationsSort;
        const cols = [
            { key: 'tenantKey', label: 'עונה' },
            { key: 'target', label: 'יעד' },
            { key: 'id', label: 'מזהה' },
            { key: 'notificationType', label: 'סוג' },
            { key: 'to', label: 'נייד' },
            { key: 'status', label: 'סטטוס' },
            { key: 'created', label: 'נוצר' },
            { key: 'sentDate', label: 'נשלח' },
            { key: 'updated', label: 'עודכן' }
        ];
        const thCells = cols.map(({ key, label }) => {
            const arrow = sort.column === key ? (sort.dir === 1 ? ' ↑' : ' ↓') : '';
            return `<th class="sortable" data-sort-key="${key}" title="מיין לפי ${label}">${label}${arrow}</th>`;
        }).join('');
        const statuses = ['created', 'sent', 'deleted'];
        let html = `<table class="content-grid"><thead><tr>${thCells}<th>עדכון סטטוס</th></tr></thead><tbody>`;
        data.forEach(row => {
            const created = (row.created && row.created.slice) ? row.created.slice(0, 19) : (row.created || '');
            const sentDate = (row.sentDate && row.sentDate.slice) ? row.sentDate.slice(0, 19) : (row.sentDate || '');
            const key = row._key || '';
            const tenantKey = row.tenantKey || '';
            const target = row.target || '';
            const id = row.id || '';
            const notificationType = row.notificationType || row.type || '';
            const to = row.to != null ? row.to : '';
            const timestamp = row.timestamp != null ? row.timestamp : (key && key.split('#').pop());
            const updated = (row.updated && row.updated.slice) ? row.updated.slice(0, 19) : (row.updated || '');
            const mobileDisplay = to ? `<a href="${this.txt2WhatsappLink(to)}" target="_blank">${this.escapeHtml(to)}</a>` : '-';
            html += `<tr>
                <td>${tenantKey}</td><td>${target}</td><td class="of15 rtl">${id}</td><td>${notificationType}</td><td>${mobileDisplay || '-'}</td><td>${(row.status || '')}</td><td>${created}</td><td>${sentDate}</td><td>${updated}</td>
                <td><select class="compact-status" data-tenant="${String(tenantKey).replace(/"/g, '&quot;')}" data-target="${String(target).replace(/"/g, '&quot;')}" data-id="${String(id).replace(/"/g, '&quot;')}" data-type="${String(notificationType).replace(/"/g, '&quot;')}" data-to="${String(to).replace(/"/g, '&quot;')}" data-timestamp="${String(timestamp).replace(/"/g, '&quot;')}">${statuses.map(s => `<option value="${s}" ${(row.status === s) ? 'selected' : ''}>${s}</option>`).join('')}</select>
                <button type="button" class="btn-update-status btn-primary compact">עדכן</button></td></tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
        container.querySelectorAll('th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const key = th.getAttribute('data-sort-key');
                if (this._notificationsSort.column === key) this._notificationsSort.dir *= -1;
                else { this._notificationsSort.column = key; this._notificationsSort.dir = -1; }
                this.renderNotificationsGrid(this.getSortedNotificationsData());
            });
        });
        container.querySelectorAll('.btn-update-status').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const select = e.target.closest('tr').querySelector('select.compact-status');
                const tenantKey = select.getAttribute('data-tenant');
                const target = select.getAttribute('data-target');
                const id = select.getAttribute('data-id');
                const notificationType = select.getAttribute('data-type');
                const to = select.getAttribute('data-to');
                const timestamp = select.getAttribute('data-timestamp');
                const status = select.value;
                await this.updateNotification(tenantKey, target, id, notificationType, to, timestamp, status);
            });
        });
    }

    async updateNotification(tenantKey, target, id, notificationType, to, timestamp, status) {
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.NOTIFICATION_UPDATE'),
                options: {
                    method: 'POST',
                    body: JSON.stringify({ tenantKey: tenantKey, target: target, id: id, notificationType: notificationType, to: to, timestamp: timestamp ? parseInt(timestamp, 10) : null, status: status }),
                }
            });
            const result = await response.json();
            if (result.success) {
                this.showToast('סטטוס עודכן', 'success');
                await this.loadNotifications();
            } else {
                this.showToast(result.error || 'שגיאה בעדכון סטטוס', 'error');
            }
        } catch (e) {
            console.warn('updateNotification error:', e);
            this.showToast('שגיאה בעדכון סטטוס', 'error');
        }
    }

    showDashboardServerDownState(statusCode) {
        const dashboardContent = document.querySelector('.dashboard-content');
        if (!dashboardContent) return;
        
        dashboardContent.innerHTML = this.createServerDownState(
            statusCode,
            'שירות הדשבורד אינו זמין כרגע. השרת מחזיר שגיאה.',
            'loadDashboardData'
        );
    }

    updateDashboardStats(data) {
        document.getElementById('gamesCount').textContent = data.todayGamesCount || 0;
        document.getElementById('activeReferees').textContent = 
            `${Math.round((data.activeRefereesCount || 0) / (data.totalRefereesCount || 1) * 100)}%`;
        document.getElementById('assignmentsCount').textContent = data.gamesCount || 0;
        document.getElementById('assignments24HrsCount').textContent = data.assignments24HrsCount || 0;
        document.getElementById('gameApprovals24HrsCount').textContent = data.gameApprovals24HrsCount || 0;
        document.getElementById('gameResultUpdates24HrsCount').textContent = data.gameResultUpdates24HrsCount || 0;
    }

    createDashboardChart(data) {
        if (data.labels && data.values) {
            const trace = {
                x: data.labels,
                y: data.values,
                type: 'bar',
                marker: {
                    color: '#2563eb'
                }
            };

            const layout = {
                title: 'שיבוצים לפי מסגרת ויום',
                xaxis: { title: 'מסגרת/יום' },
                yaxis: { title: 'שיבוצים' },
                margin: { t: 50, b: 50, l: 50, r: 50 }
            };

            Plotly.newPlot('dashboardChart', [trace], layout, { responsive: true });
        }
    }

    /** Show automation last run / last data update (from refereeProcessService sync props). */
    updateSectionSyncMetaDisplay(elementId, syncMeta) {
        const el = document.getElementById(elementId);
        if (!el) return;
        if (!syncMeta || (!syncMeta.lastRun && !syncMeta.lastUpdate)) {
            el.textContent = '';
            el.hidden = true;
            return;
        }
        el.hidden = false;
        const run = syncMeta.lastRun || '—';
        const upd = syncMeta.lastUpdate || '—';
        el.textContent = `ריצה אחרונה: ${run} · עדכון אחרון: ${upd}`;
    }

    async loadRefereeGamesData() {
        return this._runCoalescedAsync('games', () => this._executeLoadRefereeGamesData());
    }

    async _executeLoadRefereeGamesData() {
        const g = this._beginAsyncTabLoad('games');
        const fromDateFilter = document.getElementById('gamesFromDateFilter').value;
        const toDateFilter = document.getElementById('gamesToDateFilter').value;
        const includeArchived = document.getElementById('includeArchivedGamesFilter').checked;
        const includeRemoved = document.getElementById('includeRemovedGamesFilter').checked;
        const tenant = document.getElementById('gamesTenantFilter').value;
        const refereeGamesList = document.getElementById('refereeGamesList');
        
        try {
            // Show loading state
            refereeGamesList.innerHTML = '<div class="loading">טוען משחקים...</div>';
            
            const startDate = new Date(fromDateFilter);
            const endDate = new Date(toDateFilter);

            const { games, syncMeta } = await this.getRefereeGames(startDate, endDate, includeArchived, includeRemoved, tenant);
            if (this._staleAsyncTabLoad('games', g)) return;

            this._lastGamesSyncMeta = syncMeta || null;

            // Store games for filtering
            this.allGames = games;
            if (tenant) {
                await this._ensurePublicGamesFieldsRepository(tenant);
            } else {
                await this._ensureFieldsRepositoryForGames(games);
            }
            if (this._staleAsyncTabLoad('games', g)) return;
            this._runWithDomQuiet('games', () => {
                this.buildSectionFilter(games);
                this.buildLeagueFilter(games);
                // Build role filter dynamically
                this.buildRoleFilter(games, 'gamesRoleFilter');
                // Display games with current filters (avoids extra filterGames from stray change events after rebuild)
                this.filterGames();
            });
            console.log(`✅ Loaded ${games.length} games`);
            this.updateSectionSyncMetaDisplay('gamesSyncMeta', this._lastGamesSyncMeta);

        } catch (error) {
            if (this._staleAsyncTabLoad('games', g)) return;
            console.error('Error loading games:', error);
            this.updateSectionSyncMetaDisplay('gamesSyncMeta', null);
            
            // Check if it's a server down error
            if (this.isServerDownError(error)) {
                refereeGamesList.innerHTML = this.createServerDownState(
                    503, // Service Unavailable for network errors
                    'שגיאה בחיבור לשרת. ייתכן שהשרת אינו זמין כרגע.',
                    'loadRefereeGamesData'
                );
            } else {
                refereeGamesList.innerHTML = '<div class="empty-state">שגיאה בטעינת משחקים</div>';
            }
        }
    }

    /** Section/category for referee games (from tournament). */
    refereeGameSection(game) {
        const td = game.tournamentData || {};
        const s = td.section ?? game.section ?? game.leagueSection ?? '';
        return typeof s === 'string' ? s.trim() : '';
    }

    _gamesPoolForSectionLeagueDropdowns(games) {
        const tenantEl = document.getElementById('gamesTenantFilter');
        const selectedTenant = tenantEl?.value;
        let pool = games;
        if (selectedTenant) {
            pool = games.filter(
                g => String(g.tenantKey || g.tenant_key || g.tournamentTenant || '') === String(selectedTenant)
            );
        }
        return pool;
    }

    buildSectionFilter(games) {
        const el = document.getElementById('gamesSectionFilter');
        if (!el) return;
        const current = el.value;
        const pool = this._gamesPoolForSectionLeagueDropdowns(games);
        const sections = [...new Set(pool.map(g => this.refereeGameSection(g)).filter(Boolean))].sort((a, b) =>
            a.localeCompare(b, 'he')
        );
        el.innerHTML = '<option value="">כל הקטגוריות</option>';
        sections.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = s;
            el.appendChild(opt);
        });
        if (current && sections.includes(current)) el.value = current;
        console.log(`✅ Built games section filter with ${sections.length} sections`);
    }

    buildLeagueFilter(games) {
        const gamesLeagueFilter = document.getElementById('gamesLeagueFilter');
        const sectionEl = document.getElementById('gamesSectionFilter');
        if (!gamesLeagueFilter) return;

        const selectedSection = sectionEl?.value?.trim() || '';
        let pool = this._gamesPoolForSectionLeagueDropdowns(games);
        if (selectedSection) {
            pool = pool.filter(g => this.refereeGameSection(g) === selectedSection);
        }

        const leagues = [...new Set(pool.map(game => {
            const league = game.league || game.leagueName || game.league_name || game.tournamentName;
            return league && league.trim() ? league.trim() : null;
        }))].filter(league => league && league !== 'מסגרת לא ידועה').sort((a, b) => a.localeCompare(b, 'he'));

        const previousLeague = gamesLeagueFilter.value;

        gamesLeagueFilter.innerHTML = '<option value="">כל הליגות</option>';
        leagues.forEach(league => {
            const option = document.createElement('option');
            option.value = league;
            option.textContent = league;
            gamesLeagueFilter.appendChild(option);
        });

        if (previousLeague && leagues.includes(previousLeague)) {
            gamesLeagueFilter.value = previousLeague;
        } else {
            gamesLeagueFilter.value = '';
        }

        console.log(`✅ Built league filter with ${leagues.length} leagues (section="${selectedSection || 'הכל'}")`, leagues);
    }

    buildRefereeFilter(reviews) {
        const refereeFilter = document.getElementById('refereeFilter');
        if (!refereeFilter) return;

        // Get unique referees from reviews
        const referees = [...new Set(reviews.map(review => {
            const referee = review.referee || review.refereeName || review.referee_name || review['* name'];
            return referee && referee.trim() ? referee.trim() : null;
        }))].filter(referee => referee && referee !== 'שופט לא ידוע').sort();

        // Clear existing options except the first one
        refereeFilter.innerHTML = '<option value="">כל השופטים</option>';

        // Add referee options
        referees.forEach(referee => {
            const option = document.createElement('option');
            option.value = referee;
            option.textContent = referee;
            refereeFilter.appendChild(option);
        });

        console.log(`✅ Built referee filter with ${referees.length} referees:`, referees);
    }

    buildRoleFilter(games, controlId) {
        const roleFilter = document.getElementById(controlId);
        if (!roleFilter) return;

        // Get unique roles from games
        const roles = [...new Set(games.map(game => {
            const role = game.role || game.roleName || game.role_name;
            return role && role.trim() ? role.trim() : null;
        }))].filter(role => role).sort();

        // Clear existing options except the first one
        roleFilter.innerHTML = '<option value="">כל התפקידים</option>';

        // Add league options
        roles.forEach(role => {
            const option = document.createElement('option');
            option.value = role;
            option.textContent = role;
            roleFilter.appendChild(option);
        });

        console.log(`✅ Built role filter with ${roles.length} roles:`, roles);
    }

    filterGames() {
        if (!this.allGames) return;

        const gamesTenantFilter = document.getElementById('gamesTenantFilter');
        const gamesSectionFilter = document.getElementById('gamesSectionFilter');
        const gamesLeagueFilter = document.getElementById('gamesLeagueFilter');
        const gamesRoleFilter = document.getElementById('gamesRoleFilter');
        const gamesFromDateFilter = document.getElementById('gamesFromDateFilter');
        const gamesToDateFilter = document.getElementById('gamesToDateFilter');

        if (!gamesTenantFilter || !gamesLeagueFilter || !gamesRoleFilter || !gamesFromDateFilter || !gamesToDateFilter) return;

        const selectedTenant = gamesTenantFilter.value;
        const selectedSection = gamesSectionFilter?.value?.trim() || '';
        const selectedLeague = gamesLeagueFilter.value;
        const selectedRole = gamesRoleFilter.value;
        const fromDate = gamesFromDateFilter.value;
        const toDate = gamesToDateFilter.value;

        let filteredGames = [...this.allGames];

        // Filter by tenant
        if (selectedTenant) {
            filteredGames = filteredGames.filter(game => {
                const gameTenant = game.tenantKey || game.tenant_key || game.tournamentTenant;
                return gameTenant == selectedTenant; // Use == for type coercion
            });
        }

        // Filter by section (קטגוריה)
        if (selectedSection) {
            filteredGames = filteredGames.filter(game => this.refereeGameSection(game) === selectedSection);
        }

        // Filter by league
        if (selectedLeague) {
            filteredGames = filteredGames.filter(game => {
                const gameLeague = game.league || game.leagueName || game.league_name || game.tournamentName;
                return gameLeague === selectedLeague;
            });
        }

        // Filter by role
        if (selectedRole) {
            filteredGames = filteredGames.filter(game => {
                const gameRole = game.role || game.roleName || game.role_name || game.תפקיד || game['תפקיד במגרש'] || '';
                return gameRole === selectedRole;
            });
        }

        // Filter by date range
        if (fromDate || toDate) {
            filteredGames = filteredGames.filter(game => {
                const gameDate = this.gameDateTime(game);
                if (!gameDate) return true; // Include games without dates

                try {
                    const gameDateObj = new Date(gameDate);
                    if (isNaN(gameDateObj.getTime())) return true; // Invalid date, include the game
                    
                    if (fromDate && toDate) {
                        const fromDateObj = new Date(fromDate);
                        const toDateObj = new Date(toDate);
                        toDateObj.setHours(23, 59, 59, 999); // End of day
                        return gameDateObj >= fromDateObj && gameDateObj <= toDateObj;
                    } else if (fromDate) {
                        const fromDateObj = new Date(fromDate);
                        return gameDateObj >= fromDateObj;
                    } else if (toDate) {
                        const toDateObj = new Date(toDate);
                        toDateObj.setHours(23, 59, 59, 999); // End of day
                        return gameDateObj <= toDateObj;
                    }
                } catch (error) {
                    console.warn('Error parsing game date:', gameDate, error);
                    return true; // Include games with invalid dates
                }
                
                return true;
            });
        }

        // Sort filtered games by date
        filteredGames = this.sortGamesByDate(filteredGames);

        console.log(`✅ Filtered games: ${filteredGames.length} out of ${this.allGames.length}`);
        this.displayRefereeGames(filteredGames);
    }

    gamesClearFilters() {
        const tenantFilter = document.getElementById('gamesTenantFilter');
        const sectionFilter = document.getElementById('gamesSectionFilter');
        const leagueFilter = document.getElementById('gamesLeagueFilter');
        const roleFilter = document.getElementById('gamesRoleFilter');
        const fromDateFilter = document.getElementById('gamesFromDateFilter');
        const toDateFilter = document.getElementById('gamesToDateFilter');
        const includeArchivedFilter = document.getElementById('includeArchivedGamesFilter');
        const includeRemovedFilter = document.getElementById('includeRemovedGamesFilter');

        if (tenantFilter) tenantFilter.value = '';
        if (sectionFilter) sectionFilter.value = '';
        if (leagueFilter) leagueFilter.value = '';
        if (roleFilter) roleFilter.value = '';
        if (fromDateFilter) fromDateFilter.value = '';
        if (toDateFilter) toDateFilter.value = '';
        if (includeArchivedFilter) includeArchivedFilter.checked = false;
        if (includeRemovedFilter) includeRemovedFilter.checked = false;

        if (this.allGames) {
            this.buildSectionFilter(this.allGames);
            this.buildLeagueFilter(this.allGames);
            this.filterGames();
        }
    }

    filterReviews() {
        if (!this.allReviews) return;

        const reviewsTenantFilter = document.getElementById('reviewsTenantFilter');
        const refereeFilter = document.getElementById('refereeFilter');
        const reviewsRoleFilter = document.getElementById('reviewsRoleFilter');
        const ratingFilter = document.getElementById('ratingFilter');

        if (!reviewsTenantFilter || !refereeFilter || !reviewsRoleFilter || !ratingFilter) return;

        const selectedTenant = reviewsTenantFilter.value;
        const selectedReferee = refereeFilter.value;
        const selectedRole = reviewsRoleFilter.value;
        const selectedRating = ratingFilter.value;

        let filteredReviews = [...this.allReviews];

        // Filter by tenant
        if (selectedTenant) {
            filteredReviews = filteredReviews.filter(review => {
                const reviewTenant = review.tenantKey || review.tenant_key || review.tournamentTenant;
                return reviewTenant == selectedTenant; // Use == for type coercion
            });
        }

        // Filter by referee
        if (selectedReferee) {
            filteredReviews = filteredReviews.filter(review => {
                const reviewReferee = review.referee || review.refereeName || review.referee_name || review['* name'];
                return reviewReferee === selectedReferee;
            });
        }

        // Filter by role
        if (selectedRole) {
            filteredReviews = filteredReviews.filter(review => {
                const reviewRole = review.role || review.roleName || review.role_name || review.תפקיד || review['תפקיד במגרש'] || '';
                return reviewRole === selectedRole;
            });
        }

        // Filter by rating
        if (selectedRating) {
            filteredReviews = filteredReviews.filter(review => {
                const reviewRating = review.rating || review.reviewGrade || review['ציון'];
                return reviewRating == selectedRating; // Use == for type coercion
            });
        }

        console.log(`✅ Filtered reviews: ${filteredReviews.length} out of ${this.allReviews.length}`);
        this.displayRefereeReviews(filteredReviews);
    }

    clearReviewFilters() {
        const reviewsTenantFilter = document.getElementById('reviewsTenantFilter');
        const refereeFilter = document.getElementById('refereeFilter');
        const reviewsRoleFilter = document.getElementById('reviewsRoleFilter');
        const ratingFilter = document.getElementById('ratingFilter');

        if (reviewsTenantFilter) reviewsTenantFilter.value = '';
        if (refereeFilter) refereeFilter.value = '';
        if (reviewsRoleFilter) reviewsRoleFilter.value = '';
        if (ratingFilter) ratingFilter.value = '';

        // Show all reviews
        if (this.allReviews) {
            this.displayRefereeReviews(this.allReviews);
        }
    }

    /** Set games tab from/to once: from = today−30, to = max(today, latest tenant season end). Call after loadTenants(). */
    applyGamesTabDateRange() {
        const gamesFromDateFilter = document.getElementById('gamesFromDateFilter');
        const gamesToDateFilter = document.getElementById('gamesToDateFilter');
        if (!gamesFromDateFilter || !gamesToDateFilter) return;
        const fromDate = new Date();
        fromDate.setDate(fromDate.getDate() - 30);
        gamesFromDateFilter.value = fromDate.toISOString().split('T')[0];
        let toDate = new Date();
        if (this.tenants) {
            Object.values(this.tenants).forEach(tenant => {
                if (!tenant || tenant.toDate == null) return;
                const tenantToDate = this.fromIsoString(tenant.toDate);
                if (!Number.isNaN(tenantToDate.getTime()) && tenantToDate > toDate) {
                    toDate = tenantToDate;
                }
            });
        }
        gamesToDateFilter.value = toDate.toISOString().split('T')[0];
    }

    /** @deprecated Use applyGamesTabDateRange after tenants load */
    initGamesDateFiltersPriority() {
        const gamesFromDateFilter = document.getElementById('gamesFromDateFilter');
        const gamesToDateFilter = document.getElementById('gamesToDateFilter');
        if (!gamesFromDateFilter || !gamesToDateFilter) return;
        const fromDate = new Date();
        fromDate.setDate(fromDate.getDate() - 30);
        gamesFromDateFilter.value = fromDate.toISOString().split('T')[0];
        gamesToDateFilter.value = new Date().toISOString().split('T')[0];
    }

    /** Full default range in one shot (e.g. when tenants already in memory). */
    setDefaultDateRange() {
        this._runWithDomQuiet('games', () => this.applyGamesTabDateRange());
    }
    
    displayRefereeGames(games) {
        const refereeGamesList = document.getElementById('refereeGamesList');
        
        if (games.length === 0) {
            refereeGamesList.innerHTML = '<div class="empty-state">אין משחקים זמינים</div>';
            return;
        }

        refereeGamesList.innerHTML = this.generateGamesHtml('games', games);
    }

    displayRefereeReviews(reviews) {
        const refereeReviewsList = document.getElementById('refereeReviewsList');
        
        if (reviews.length === 0) {
            refereeReviewsList.innerHTML = '<div class="empty-state">אין ביקורות זמינות</div>';
            return;
        }

        refereeReviewsList.innerHTML = this.generateGamesHtml('reviews', reviews);
    }

    gameDateTime = (game) => game.date || game.gameDate || game.game_date || game.scheduledDate;

    sortGamesByDate(games) {
        const now = new Date();
        
        return games.sort((gameA, gameB) => {
            // Parse dates
            const dateA = new Date(this.gameDateTime(gameA));
            const dateB = new Date(this.gameDateTime(gameB));
            
            // Check if games are in the future or past
            const isFutureA = dateA > now;
            const isFutureB = dateB > now;
            
            // If both are future games, sort ascending (earliest first)
            if (isFutureA && isFutureB) {
                return dateA > dateB ? 1 : -1;
            }
            
            // If both are past games, sort descending (most recent first)
            if (!isFutureA && !isFutureB) {
                return dateB > dateA ? 1 : -1;
            }
            
            // Future games come before past games
            if (isFutureA && !isFutureB) {
                return -1;
            }
            
            // Past games come after future games
            return 1;
        });
    }
    
    getGameDetails(game) {
        const gameDateTime = this.gameDateTime(game);
        const gameId = game.id || game.gameId || game._id;
        const gameTitle = game.gameTitle || game.game_title;
        const role = game.role || game.roleName || game.role_name;
        let fullTimeResult = Array.isArray(game.gameResult?.full_time_score) ? game.gameResult?.full_time_score : game.gameResult?.full_time_score?.split(':') || null;
        if (!fullTimeResult || fullTimeResult.length !== 2)
            fullTimeResult = game.homeTeamScore && game.guestTeamScore ? [ game.homeTeamScore, game.guestTeamScore ] : null;
        const halfTimeResult = Array.isArray(game.gameResult?.half_time_score) ? game.gameResult?.half_time_score : game.gameResult?.half_time_score?.split(':') || null;
        const fdResolved = this._resolveFieldDataForGame(game);
        const addrRes = fdResolved && fdResolved.addressDetails ? fdResolved.addressDetails : {};
        const coordsRes = addrRes.coordinates || {};
        const fieldLat = coordsRes.lat;
        const fieldLng = coordsRes.lng;
        const state = game.state || game.gameState;

        const gameDetails = {
            tenantKey : game.tenantKey,
            tenantIcon : game.tenantIcon,
            tenantName : game.tenantName,
            countryCode : game.countryCode || game.country_code || game.countryCode || game.country_code,
            eventType : game.eventType || game.event_type || game.eventType || game.event_type,
            season : game.season || game.seasonName || game.season_name || game.tournamentSeason,
            gameId : gameId,
            gameUrl : game.url || game.gameUrl || game.game_url || game.game_url,
            gameTitle : gameTitle,
            homeTeam : game.home || game.homeTeam || game.home_team || game.team1 || game.homeTeamName || gameTitle && gameTitle.split(':')[0].trim() || 'קבוצה לא ידועה',
            guestTeam : game.away || game.guestTeam || game.away_team || game.team2 || game.guestTeamName || gameTitle && gameTitle.split(':')[1].trim() || 'קבוצה לא ידועה',
            league : game.league || game.leagueName || game.league_name || game.tournamentName,
            leagueUrl : game.tournamentData && game.tournamentData.href,
            gameDateTime : gameDateTime,
            gameDate : game.gameDate || game.game_date || game.scheduledDate || this.formatDate(gameDateTime),
            gameTime : game.gameTime || game.game_time || game.scheduledTime || this.formatTime(gameDateTime),
            gameDuration : game.gameDuration || game.game_duration || game.duration,
            round: game.round || game.gameRound || game.round_number,
            fixture: game.fixture || game.gameFixture || game.fixture_number,
            state : state,
            active : state == 'active',
            archived : state == 'archived',
            removed : state == 'removed',
            canceled : state == 'canceled',
            status : game.status || game.gameStatus,
            field : game.field || game.fieldName || game.field_name || 'טרם נקבע',
            fieldWazeUrlLink : addrRes.wazeLink || '',
            fieldLat : fieldLat,
            fieldLng : fieldLng,
            fieldWazeLink: (fieldLat != null && fieldLng != null && fieldLat !== '' && fieldLng !== '')
                ? `waze://?ll=${fieldLat},${fieldLng}&navigate=yes`
                : '',
            referees : game.referees || game.nested,
            role : role,
            mainReferee: this.roles && this.roles[game.tenantKey] && this.roles[game.tenantKey][role] && this.roles[game.tenantKey][role].mainReferee == 'True' || false,
            secretaryReferee: this.roles && this.roles[game.tenantKey] && this.roles[game.tenantKey][role] && this.roles[game.tenantKey][role].secretaryReferee == 'True' || false,
            reviewer : game['reviewer'],
            reviewGrade : game['reviewGrade'],
            icsUrl : `${this.getConfig('API_BASE_URL')}/api/file/${gameId}`,
            fullTimeResult : fullTimeResult && fullTimeResult[1] + ':' + fullTimeResult[0],
            halfTimeResult : halfTimeResult && halfTimeResult[1] + ':' + halfTimeResult[0]
        };

        return gameDetails;
    }
    
    // Usage
    generateGamesHtml(type, games) {
        // Debug: Log the first game to see the structure
        console.log('🔍 First game structure:', games[0]);
        console.log(' All games:', games);
    
        const sortedGames = this.sortGamesByDate(games);

        const gamesHTML = sortedGames.map(game => {
            // Extract game data with fallbacks for missing fields
            const gameDetails = this.getGameDetails(game);

            // Extract referee details
            let refereeSummary = '';
            //if (gameDetails.referees && Object.keys(gameDetails.referees).length > 0) {
            if (gameDetails.referees && gameDetails.referees.length > 0) {
                    // Create referee summary
                refereeSummary = this.createRefereeSummary(gameDetails.referees, {
                    clickableNames: type === 'games',
                    tenantKey: gameDetails.tenantKey,
                });
            }
            let gameHtml = `
                <div class="game-item" style="position: relative; padding: 1rem; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 1rem; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">`;

            if (gameDetails.halfTimeResult || gameDetails.fullTimeResult) {
                gameHtml += `<span style="position: absolute; top: 0.5rem; left: 0.5rem; background: #10b981; color: white; padding: 0.2rem 0.5rem; border-radius: 3px; font-weight: bold; font-size: 0.85rem;">`;
                if (gameDetails.fullTimeResult) {
                    gameHtml += `${gameDetails.fullTimeResult} `;
                }
                if (gameDetails.halfTimeResult) {
                    gameHtml += `(${gameDetails.halfTimeResult})`;
                }
                gameHtml += `</span>`;
            }

            gameHtml += `<div style="display: flex; justify-content: space-between; align-items: flex-start;">
                        <div style="flex: 1;">
                            <h4 style="margin: 0 0 0.5rem 0; color: #1e293b; font-size: 1.1rem;">`
            if (gameDetails.gameUrl) {
                gameHtml += `<a href="${gameDetails.gameUrl}" target="_blank">${gameDetails.homeTeam} נגד ${gameDetails.guestTeam}</a>`;
            } else {
                gameHtml += `${gameDetails.homeTeam} נגד ${gameDetails.guestTeam}`;
            }

            gameHtml += `</h4>`;
            gameHtml += `<div style="color: #64748b; font-size: 0.9rem; line-height: 1.4;">`
            gameHtml += `<p style="margin: 0 0 0.25rem 0;">`
            if (gameDetails.leagueUrl) {
                gameHtml += `<strong>מסגרת:</strong> <a href="https://www.football.org.il${gameDetails.leagueUrl}" target="_blank">${gameDetails.league}</a>`;
            } else {
                gameHtml += `<strong>מסגרת:</strong> ${gameDetails.league}`;
            }
            gameHtml += `</p>`;
            gameHtml += `<p style="margin: 0 0 0.25rem 0;">
                            <strong>עונה:</strong> ${gameDetails.season}
                        </p>`;
            if (gameDetails.round) {
                gameHtml += `<p style="margin: 0 0 0.25rem 0;">
                            <strong>סבב:</strong> ${gameDetails.round}
                        </p>`;
            }
            if (gameDetails.fixture) {
                gameHtml += `<p style="margin: 0 0 0.25rem 0;">
                            <strong>מחזור:</strong> ${gameDetails.fixture}
                        </p>`;
            }
            gameHtml += `<p style="margin: 0 0 0.25rem 0;">`
            if (type == 'games') {
                gameHtml += `<span onclick="refPortalPwa.downloadIcsFile('${gameDetails.gameId}')"><strong>תאריך:</strong>${gameDetails.gameDate} 📅</span>`;
            } else {
                if (false && gameDetails.icsUrl) {
                    gameHtml += `<strong>תאריך:</strong> <a href="${gameDetails.icsUrl}" target="_blank" style="color: #3b82f6; text-decoration: none; border-bottom: 1px dotted #3b82f6; cursor: pointer; transition: all 0.2s ease; padding: 2px 4px; border-radius: 3px;" title="הוסף ליומן" onmouseover="this.style.color='#1d4ed8'; this.style.borderBottomColor='#1d4ed8'; this.style.backgroundColor='#eff6ff'" onmouseout="this.style.color='#3b82f6'; this.style.borderBottomColor='#3b82f6'; this.style.backgroundColor='transparent'">${gameDetails.gameDate} 📅</a>`;
                } else {
                    gameHtml += `<strong>תאריך:</strong> ${gameDetails.gameDate}`;
                }
            }
            gameHtml += `</p>`;
            gameHtml += `<p style="margin: 0 0 0.25rem 0;">
                                    <strong>שעה:</strong> ${gameDetails.gameTime}
                                </p>
                                <p style="margin: 0 0 0.25rem 0;">`
            if (!!gameDetails.fieldWazeUrlLink) {
                gameHtml += `<strong>מגרש:</strong> <a href="${gameDetails.fieldWazeLink}" target="_blank" style="color: #3b82f6; text-decoration: none; border-bottom: 1px dotted #3b82f6; cursor: pointer; transition: all 0.2s ease; padding: 2px 4px; border-radius: 3px;" title="לחץ לפתיחה ב-Waze" onmouseover="this.style.color='#1d4ed8'; this.style.borderBottomColor='#1d4ed8'; this.style.backgroundColor='#eff6ff'" onmouseout="this.style.color='#3b82f6'; this.style.borderBottomColor='#3b82f6'; this.style.backgroundColor='transparent'">${gameDetails.field} 🗺️</a>`;
            } else {
                gameHtml += `<strong>מגרש:</strong> ${gameDetails.field}`;
            }
            gameHtml += `</p>`;
            if (gameDetails.status) {
                gameHtml += `<p style="margin: 0 0 0.25rem 0;">
                                        <strong>סטטוס:</strong> 
                                        <span style="background: ${this.getStatusColor(gameDetails.status)}; color: white; padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.75rem;">
                                            ${gameDetails.status}
                                        </span>
                                    </p>`;
            }
            // Add game results if available
            gameHtml += `</p>
                                <p style="margin: 0 0 0.25rem 0;">
                                    <strong>תפקיד:</strong> ${gameDetails.role}
                                </p>`
            if (type == 'games') {
                gameHtml += refereeSummary !== ''   ? `
                                <p style="margin: 0 0 0.25rem 0;">
                                    <strong>צוות שיפוט:</strong> ${refereeSummary}
                                </p>` : '';
            }
            gameHtml += gameDetails.reviewer ? `
                                <p style="margin: 0 0 0.25rem 0;">
                                    <strong>מבקר:</strong> ${gameDetails.reviewer}
                                </p>` : '';
            gameHtml += gameDetails.reviewGrade ? `
                                <p style="margin: 0 0 0.25rem 0;">
                                    <strong>ציון:</strong> ${gameDetails.reviewGrade}
                                </p>` : '';
            gameHtml += `
                            </div>
                        </div>
                        <div style="margin-left: 1rem; display: flex; flex-direction: column; gap: 0.5rem;">
                            ${this.getGameButtons(type, gameDetails)}
                        </div>
                    </div>
                </div>
            `;
            return gameHtml;
        }).join('');
        
        return gamesHTML;
    }

    // Helper method to create referee summary
    createRefereeSummary(referees, opts = {}) {
        const clickableNames = !!opts.clickableNames;
        const gameTenantKey =
            opts.tenantKey != null && String(opts.tenantKey).trim() !== ''
                ? String(opts.tenantKey).trim()
                : '';
        const gameTenantAttr = gameTenantKey
            ? ` data-game-tenant="${encodeURIComponent(gameTenantKey)}"`
            : '';
        // Convert object to array if it's not already an array
        let refereesArray = referees;
        if (!Array.isArray(referees)) {
            // If it's an object, convert to array
            //refereesArray = Object.values(referees).filter(referee => {
            refereesArray = referees.filter(referee => {
                return referee && typeof referee === 'object' && referee['role'];
            });            
        }    

        if (refereesArray.length === 0) {
            return '<span style="color: #9ca3af; font-style: italic;">טרם הוקצה</span>';
        }

        const refereesHTML = refereesArray.map(referee => {
            const role = referee['role'];
            // Generate Waze link for referee address
            let refereeAddressHTML = '';
            if (referee['* address']) {
                const address = referee['* address'];
                let wazeLink;
                if (referee.address) {
                    wazeLink = `https://www.waze.com/ul?ll=${referee.address['lat']},${referee.address['lng']}&navigate=yes`;
                }                
                refereeAddressHTML = `
                    <a href="${wazeLink}" target="_blank" class="referee-address" style="
                        font-size: 0.75rem; 
                        color: #3b82f6; 
                        font-style: italic;
                        text-decoration: none;
                        cursor: pointer;
                        transition: color 0.2s ease;
                    " onmouseover="this.style.color='#1d4ed8'; this.style.textDecoration='underline'" 
                       onmouseout="this.style.color='#3b82f6'; this.style.textDecoration='none'"
                       title="לחץ לפתיחה ב-Waze">
                        🗺️ ${address}
                    </a>
                `;
            }
                    
            return `
                <div class="referee-card" style="
                    flex: 1; 
                    min-width: 200px; 
                    padding: 0.75rem; 
                    border: 1px solid #e5e7eb; 
                    border-radius: 6px; 
                    background: #f9fafb;
                    margin: 0 0.25rem;
                ">
                    <div class="referee-role" style="
                        font-weight: bold; 
                        color: #374151; 
                        margin-bottom: 0.5rem;
                        font-size: 0.875rem;
                    ">${role}</div>
                    
                    ${referee['* name']
                        ? clickableNames
                            ? `<button type="button" class="referee-games-tab-name referee-name" style="
                            font-size: 1rem;
                            color: #111827;
                            margin-bottom: 0.25rem;
                            display: block;
                            width: 100%;
                            text-align: right;
                        " data-referee-name="${this.escapeHtml(String(referee['* name']))}" data-referee-phone="${this.escapeHtml(referee['* phone'] ? String(referee['* phone']) : '')}"${gameTenantAttr}>${this.escapeHtml(String(referee['* name']))}</button>`
                            : `<div class="referee-name" style="
                            font-size: 1rem; 
                            color: #111827; 
                            margin-bottom: 0.25rem;
                        ">${referee['* name']}</div>`
                        : ''}
                    
                    ${referee['* level'] ? `
                        <div class="referee-level" style="
                            font-size: 0.875rem; 
                            color: #6b7280; 
                            margin-bottom: 0.25rem;
                        ">${referee['* level']}</div>
                    ` : ''}
                    
                    ${referee['* status'] ? `
                        <div class="referee-status" style="
                            font-size: 0.875rem; 
                            color: #059669; 
                            margin-bottom: 0.25rem;
                        ">${referee['* status']}</div>
                    ` : ''}
                    
                    ${referee['* address'] || referee['* phone'] ? `
                        <div style="display: flex; flex-direction: column; gap: 0.25rem;">
                            ${refereeAddressHTML}
                            
                            ${referee['* phone'] ? `
                                <div class="referee-phone" style="
                                    font-size: 0.75rem; 
                                    color: #3b82f6; 
                                    font-style: italic;
                                    direction:ltr;
                                    cursor: pointer;
                                    text-decoration: underline;
                                    transition: color 0.2s ease;
                                    text-align: right;
                                    width: 100%;
                                " onclick="window.open('tel:${referee['* phone'].replace(/[^\d+]/g, '')}', '_self')" 
                                   onmouseover="this.style.color='#1d4ed8'" 
                                   onmouseout="this.style.color='#3b82f6'">
                                    📞 ${referee['* phone']}
                                </div>
                            ` : ''}
                        </div>
                    ` : ''}
                    </div>
            `;        
        }).join('');

        // Return the side-by-side layout
        return `
            <div class="referees-container" style="
                display: flex; 
                flex-wrap: wrap; 
                gap: 0.5rem; 
                justify-content: flex-start;
            ">
                ${refereesHTML}
            </div>
        `;
    }

    // Helper method to get status color
    getStatusColor(status) {
        const statusColors = {
            'scheduled': '#3b82f6',      // Blue for scheduled
            'in_progress': '#f59e0b',    // Orange for in progress
            'completed': '#10b981',      // Green for completed
            'cancelled': '#ef4444',      // Red for cancelled
            'postponed': '#8b5cf6',      // Purple for postponed
            'default': '#6b7280'         // Gray for unknown status
        };
        
        const normalizedStatus = status?.toLowerCase().replace(/\s+/g, '_');
        return statusColors[normalizedStatus] || statusColors.default;
    }
    
    // Helper method to get action button based on game status
    getGameButtons(type, gameDetails) {
        const nowIsoString = this.toIsoString(new Date());
        const tenantKey = gameDetails.tenantKey;
        const tenant = this.tenants[tenantKey];
        const countryCode = gameDetails.countryCode;
        const eventType = gameDetails.eventType;
        const tenantName = gameDetails.tenantName;
        const tenantIcon = gameDetails.tenantIcon;
        const status = gameDetails.status;
        const gameId = gameDetails.gameId;
        const gameActive = gameDetails.active;
        const gameArchived = gameDetails.archived;
        const gameRemoved = gameDetails.removed;
        const gameCanceled = gameDetails.canceled;
        const gameUrl = gameDetails.gameUrl;
        const gameDateTime = gameDetails.gameDateTime;
        const mainReferee = gameDetails.mainReferee;
        const secretaryReferee = gameDetails.secretaryReferee;

        let html = '';
      
        // Add status indicators for archived and removed games
        if (gameArchived) {
            html += `<span style="display: inline-block; margin-right: 0.5rem; color: #10b981; font-size: 1.2rem;" title="משחק שהסתיים">✅</span>`;
        }
        if (gameRemoved) {
            html += `<span style="display: inline-block; margin-right: 0.5rem; color: #ef4444; font-size: 1.2rem;" title="משחק שהוסר">❌</span>`;
        }
        let sportIcon = '';
        if (countryCode == 'IL') {
            sportIcon += '🇮🇱';
        } else if (countryCode == 'US') {
            sportIcon += '🇺🇸'; // usa flag
        } else if (countryCode == 'GB') {
            sportIcon += '🏴󠁧󠁢󠁥󠁮󠁧󠁿';
        }
        if (eventType == 'football') {
            sportIcon += '⚽';
        } else if (eventType == 'basketball') {
            sportIcon += '🏀';
        } else if (eventType == 'handball') {
            sportIcon += '🏐'; // handball icon
        }
        if (tenantIcon) {
            html += `<img src="./images/${tenantIcon}" alt="${tenantName}" style="width: 2rem; height: 2rem; margin-right: 0.5rem;">`;
        }
        if (type == 'games' && gameActive) {
            html += `<span style="display: inline-block; margin-right: 0.5rem; color: #f59e0b; font-size: 1.2rem;" title="משחק שטרם החל">${sportIcon}</span>`;
        }

        if (gameUrl && tenant.buttons.gameDetails == 'True' ) {
            html += `<button class="btn-primary" onclick="refPortalPwa.viewGameDetails('${gameId}', '${gameUrl}')" style="padding: 0.5rem 1rem; font-size: 0.9rem; min-width: 100px;">
                פרטים
            </button>`;
        }
        
        if (type == 'games' && status) {
            if (status !== 'מאושר' && gameActive && tenant.buttons.approveGame == 'True') {
                html += `<button class="btn-secondary" onclick="refPortalPwa.approveGame('${gameId}')" style="padding: 0.5rem 1rem; font-size: 0.9rem; background: #10b981; color: white; border: none; border-radius: 4px;">
                    אשר שיבוץ
                </button>`;
            } else if ((status === 'in_progress' || status === 'במהלך') && tenant.buttons.liveGame == 'True') {
                html += `<button class="btn-secondary" onclick="refPortalPwa.viewGameLive('${gameId}', '${gameUrl}')" style="padding: 0.5rem 1rem; font-size: 0.9rem; background: #f59e0b; color: white; border: none; border-radius: 4px;">
                    צפה במשחק
                </button>`;
            } else if ((status === 'completed' || status === 'הושלם') && tenant.buttons.gameReport == 'True') {
                html += `<button class="btn-secondary" onclick="refPortalPwa.viewGameReport('${gameId}')" style="padding: 0.5rem 1rem; font-size: 0.9rem; background: #3b82f6; color: white; border: none; border-radius: 4px;">
                    דו״ח משחק
                </button>`;
            }
        }

        // Add "פתיחת דו״ח" button for past games (archived games)
        if (type == 'games' && (mainReferee || secretaryReferee) && (gameActive || gameArchived) && gameDateTime < nowIsoString) {
            if (tenant.buttons.updateReport == 'True') {
                html += `<button class="btn-secondary" onclick="refPortalPwa.openGameUpdateReport('${gameId}')" style="padding: 0.5rem 1rem; font-size: 0.9rem; background: #3b82f6; color: white; border: none; border-radius: 4px; margin-left: 0.5rem; min-width: 100px;">
                עדכן דו״ח
                </button>`;
            }
            if (tenant.buttons.openReport == 'True') {
                html += `<button class="btn-report" onclick="refPortalPwa.openGameReport('${gameId}', '${gameUrl || ''}')">
                    פתיחת דו״ח
                </button>`;
            }
        }
        
        return html
    }

    async loadRefereeReviewsData() {
        return this._runCoalescedAsync('reviews', () => this._executeLoadRefereeReviewsData());
    }

    async _executeLoadRefereeReviewsData() {
        const g = this._beginAsyncTabLoad('reviews');
        const tenant = document.getElementById('reviewsTenantFilter').value;
        const refereeReviewsList = document.getElementById('refereeReviewsList');
        
        try {
            // Show loading state
            refereeReviewsList.innerHTML = '<div class="loading">טוען ביקורות...</div>';
    
            // Fetch reviews from REVIEWS endpoint
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.REFEREEREVIEWS'),
                params: {
                    tenantKey: tenant,
                }
            });
    
            if (this._staleAsyncTabLoad('reviews', g)) return;

            if (!response.ok) {
                this.updateSectionSyncMetaDisplay('reviewsSyncMeta', null);
                // Check if it's a server down error
                if (this.isServerDownError({ status: response.status })) {
                    refereeReviewsList.innerHTML = this.createServerDownState(
                        response.status,
                        'שירות RefereeX אינו זמין כרגע. השרת מחזיר שגיאה.',
                        'loadRefereeReviewsData'
                    );
                } else {
                    refereeReviewsList.innerHTML = '<div class="empty-state">שירות RefereeX אינו זמין כרגע</div>';
                }
                return;
            }

            const result = await response.json();
            if (this._staleAsyncTabLoad('reviews', g)) return;

            if (result.success) {
                const raw = result.data;
                const reviews = Array.isArray(raw) ? raw : Object.values(raw || {});
                // Store reviews for filtering
                this.allReviews = reviews;
                this._runWithDomQuiet('reviews', () => {
                    this.buildRefereeFilter(reviews);
                    this.buildRoleFilter(reviews, 'reviewsRoleFilter');
                    this.filterReviews();
                });
                this.updateSectionSyncMetaDisplay('reviewsSyncMeta', result.syncMeta || null);
                console.log(`✅ Loaded ${reviews.length} reviews`);
            } else {
                this.updateSectionSyncMetaDisplay('reviewsSyncMeta', null);
                refereeReviewsList.innerHTML = '<div class="empty-state">שירות הביקורות אינו זמין כרגע</div>';
                return;
            }
        } catch (error) {
            if (this._staleAsyncTabLoad('reviews', g)) return;
            console.error('Error loading reviews:', error);
            this.updateSectionSyncMetaDisplay('reviewsSyncMeta', null);
            
            // Check if it's a server down error
            if (this.isServerDownError(error)) {
                refereeReviewsList.innerHTML = this.createServerDownState(
                    503, // Service Unavailable for network errors
                    'שגיאה בחיבור לשרת. ייתכן שהשרת אינו זמין כרגע.',
                    'loadRefereeReviewsData'
                );
            } else {
                refereeReviewsList.innerHTML = '<div class="empty-state">שגיאה בטעינת ביקורות</div>';
            }
        }
    }

    displayReviews(reviews) {
        const reviewsList = document.getElementById('reviewsList');
        
        if (reviews.length === 0) {
            reviewsList.innerHTML = '<div class="empty-state">אין ביקורות זמינות</div>';
            return;
        }

        const reviewsHTML = reviews.map(review => `
            <div class="review-item" style="padding: 1rem; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 1rem; background: white;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <h4 style="margin: 0 0 0.5rem 0; color: #1e293b;">${review.referee}</h4>
                        <p style="margin: 0 0 0.5rem 0; color: #64748b;">${review.comment}</p>
                        <small style="color: #94a3b8;">${review.date}</small>
                    </div>
                    <div style="color: #fbbf24; font-size: 1.2rem;">
                        ${'★'.repeat(review.rating)}${'☆'.repeat(5-review.rating)}
                    </div>
                </div>
            </div>
        `).join('');

        reviewsList.innerHTML = reviewsHTML;
    }

    async loadFieldsData() {
        const g = this._beginAsyncTabLoad('fields');
        const filterText = document.getElementById('fieldsTextFilter').value;
        const fieldsList = document.getElementById('fieldsList');
        fieldsList.innerHTML = '<div class="loading">טוען מגרשים...</div>';

        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.FIELDS'),
                params: {
                    filterText: filterText
                }
            });
            
            if (this._staleAsyncTabLoad('fields', g)) return;

            if (response.ok) {
                const result = await response.json();
                if (this._staleAsyncTabLoad('fields', g)) return;
                if (result.success && result.data) {
                    const fields = result.data;
                    this.displayFields(fields);
                } else {
                    fieldsList.innerHTML = '<div class="empty-state">שירות המגרשים אינו זמין כרגע</div>';
                    return;
                }
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            if (this._staleAsyncTabLoad('fields', g)) return;
            console.error('Error loading fields:', error);
            fieldsList.innerHTML = '<div class="empty-state">שגיאה בטעינת מגרשים: ' + error.message + '</div>';
        }
    }

    displayFields(fields) {
        const fieldsList = document.getElementById('fieldsList');
        
        // Store fields for filtering
        this.allFields = fields;
        
        // Apply current filter if any
        const filteredFields = this.filterFields(fields);
        
        if (filteredFields.length === 0) {
            fieldsList.innerHTML = '<div class="empty-state">אין מגרשים זמינים</div>';
            return;
        }

        const fieldsHTML = filteredFields.map(field => {
            // Extract field data with fallbacks
            const fieldName = field.fieldName || field.name || 'שם לא ידוע';
            const address = field.addressDetails?.address || field.address || field.location || 'כתובת לא ידועה';
            const coordinates = field.addressDetails?.coordinates || field.coordinates || {};
            const lat = coordinates.lat || '';
            const lng = coordinates.lng || '';
            const wazeLink = field.addressDetails?.wazeLink || '';
            const level = field.level || field.status || 'רמה לא ידועה';
            const contact = field.contact || '';
            const phone = field.phone || '';

            // Create Google Maps link with coordinates
            const googleMapsLink = lat && lng ? 
                `https://www.google.com/maps?q=${lat},${lng}` : 
                `https://www.google.com/maps/search/${encodeURIComponent(address)}`;

            return `
                <div class="field-item" style="padding: 1rem; border: 1px solid #e2e8f0; border-radius: 8px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); width: 100%; box-sizing: border-box; overflow: hidden;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem; gap: 0.5rem;">
                        <h4 style="margin: 0; color: #1e293b; font-size: 1.1rem; word-wrap: break-word; flex: 1; min-width: 0;">${fieldName}</h4>
                        <span style="background: #10b981; color: white; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; white-space: nowrap; flex-shrink: 0;">
                            ${level}
                        </span>
                    </div>
                    
                    <div style="margin-bottom: 0.5rem;">
                        <p style="margin: 0 0 0.25rem 0; color: #64748b; font-size: 0.9rem; word-wrap: break-word;">
                            <strong>כתובת:</strong> 
                            <a href="${googleMapsLink}" target="_blank" style="color: #2563eb; text-decoration: none;">
                                ${address}
                            </a>
                        </p>
                        
                        ${contact ? `
                            <p style="margin: 0 0 0.25rem 0; color: #64748b; font-size: 0.9rem;">
                                <strong>איש קשר:</strong> 
                                <span style="color: #2563eb; text-decoration: none;">${contact}</span>
                            </p>
                        ` : ''}

                        ${phone ? `
                            <p style="margin: 0 0 0.25rem 0; color: #64748b; font-size: 0.9rem;">
                                <strong>טלפון:</strong> 
                                <span style="
                                    color: #3b82f6; 
                                    cursor: pointer;
                                    text-decoration: underline;
                                    transition: color 0.2s ease;
                                    direction: ltr;
                                    display: inline-block;
                                " onclick="window.open('tel:${phone.replace(/[^\d+]/g, '')}', '_self')" 
                                   onmouseover="this.style.color='#1d4ed8'" 
                                   onmouseout="this.style.color='#3b82f6'">
                                    📞 ${phone}
                                </span>
                            </p>
                        ` : ''}

                        ${false && lat && lng ? `
                            <p style="margin: 0 0 0.25rem 0; color: #64748b; font-size: 0.9rem;">
                                <strong>קואורדינטות:</strong> ${lat}, ${lng}
                            </p>
                        ` : ''}
                    </div>
                    
                    <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                        ${wazeLink ? `
                            <a href="${wazeLink}" target="_blank" style="display: inline-flex; align-items: center; gap: 0.25rem; background: #33ccff; color: white; padding: 0.5rem 0.75rem; border-radius: 6px; text-decoration: none; font-size: 0.8rem; font-weight: 500;">
                                <span style="font-size: 1rem;">🗺️</span>
                                Waze
                            </a>
                        ` : ''}
                        
                        <a href="${googleMapsLink}" target="_blank" style="display: inline-flex; align-items: center; gap: 0.25rem; background: #4285f4; color: white; padding: 0.5rem 0.75rem; border-radius: 6px; text-decoration: none; font-size: 0.8rem; font-weight: 500;">
                            <span style="font-size: 1rem;">📍</span>
                            Google Maps
                        </a>
                    </div>
                </div>
            `;
        }).join('');

        fieldsList.innerHTML = `<div class="fields-grid">${fieldsHTML}</div>`;
    }

    filterFields(fields) {
        if (!fields) return [];
        
        const searchText = document.getElementById('fieldsTextFilter')?.value?.toLowerCase() || '';
        const showClosedFields = document.getElementById('showClosedFieldsFilter')?.checked || false;
        
        let filteredFields = fields;
        
        // Filter by closed/active status
        if (!showClosedFields) {
            filteredFields = filteredFields.filter(field => {
                const fieldName = (field.fieldName || field.name || '').toLowerCase();
                const status = (field.status || field.level || '').toLowerCase();
                const isClosed = fieldName.includes('(סגור)') || status.includes('סגור') || status.includes('closed') || 
                               status.includes('לא פעיל') || status.includes('inactive');
                return !isClosed;
            });
        }
        
        // Filter by search text
        if (searchText) {
            filteredFields = filteredFields.filter(field => {
                const fieldName = (field.fieldName || field.name || '').toLowerCase();
                const address = (field.address || field.location || '').toLowerCase();
                const level = (field.level || field.status || '').toLowerCase();
                
                return fieldName.includes(searchText) || 
                       address.includes(searchText) || 
                       level.includes(searchText);
            });
        }
        
        return filteredFields;
    }

    async searchFields() {
        const g = this._beginAsyncTabLoad('fields');
        const filterText = document.getElementById('fieldsTextFilter')?.value || '';
        const fieldsList = document.getElementById('fieldsList');
        fieldsList.innerHTML = '<div class="loading">מחפש מגרשים...</div>';

        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.FIELDS'),
                params: {
                    filterText: filterText
                }
            });
            
            if (this._staleAsyncTabLoad('fields', g)) return;

            if (response.ok) {
                const result = await response.json();
                if (this._staleAsyncTabLoad('fields', g)) return;
                if (result.success && result.data) {
                    const fields = result.data;
                    this.displayFields(fields);
                } else {
                    fieldsList.innerHTML = '<div class="empty-state">שירות המגרשים אינו זמין כרגע</div>';
                    return;
                }
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            if (this._staleAsyncTabLoad('fields', g)) return;
            console.error('Error searching fields:', error);
            fieldsList.innerHTML = '<div class="empty-state">שגיאה בחיפוש מגרשים: ' + error.message + '</div>';
        }
    }

    filterFieldsAndDisplay() {
        if (!this.allFields) return;
        
        const filteredFields = this.filterFields(this.allFields);
        this.displayFields(this.allFields); // This will use the filtered fields internally
    }

    clearFieldsFilters() {
        const fieldsTextFilter = document.getElementById('fieldsTextFilter');
        const showClosedFieldsFilter = document.getElementById('showClosedFieldsFilter');
        
        if (fieldsTextFilter) {
            fieldsTextFilter.value = '';
        }
        
        if (showClosedFieldsFilter) {
            showClosedFieldsFilter.checked = false;
        }
        
        // Reload all fields from server
        this.loadFieldsData();
    }

    async loadAvailabilityData() {
        const g = this._beginAsyncTabLoad('availability');
        const availabilityDataGrid = document.getElementById('availabilityDataGrid');
        try {            
            availabilityDataGrid.innerHTML = '<div class="loading">טוען זמינות ומשחקים...</div>';
            
            // Generate 7 days starting from today
            const days = this.generateNext7Days();
            this.renderAvailabilityGrid(days);

            // Update week display
            this.updateWeekDisplay(days);

            // Load existing availability from server
            await this.loadExistingAvailability();
            if (this._staleAsyncTabLoad('availability', g)) return;
            
            // Load referee games for the 7-day period
            await this.loadRefereeGamesForAvailability(days);
            if (this._staleAsyncTabLoad('availability', g)) return;
            
            // Check and reset elapsed days if not consistent
            this.checkAndResetElapsedDays();

        } catch (error) {
            if (this._staleAsyncTabLoad('availability', g)) return;
            console.error('Error loading availability:', error);
            availabilityDataGrid.innerHTML = '<div class="empty-state">שגיאה בטעינת זמינות</div>';
        }
        finally {
        }
    }

    generateNext7Days() {
        const days = [];
        const dayNames = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'];
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        
        for (let i = 0; i < 7; i++) {
            const date = new Date(this.currentWeekStart);
            date.setDate(this.currentWeekStart.getDate() + i);
            
            days.push({
                dt: date,
                date: this.toIsoString(date),
                dayName: dayNames[date.getDay()],
                dateString: date.toLocaleDateString('he-IL'),
                isToday: date.getTime() === today.getTime()
            });
        }
        
        return days;
    }

    renderAvailabilityGrid(days) {
        const availabilityDataGrid = document.getElementById('availabilityDataGrid');
        
        const gridHTML = days.map(day => `
            <div class="availability-day ${day.isToday ? 'today' : ''}">
                <div class="availability-day-header">${day.dayName}</div>
                <div class="availability-day-date">${day.dateString}</div>
                <select class="availability-select" data-date="${day.date}">
                    <option value="available">זמין</option>
                    <option value="partial">חלקי</option>
                    <option value="not-available">לא זמין</option>
                </select>
                <div class="availability-time-container hidden">
                    <label class="availability-time-label">משעה:</label>
                    <input type="time" class="availability-time-input" data-field="from-time">
                    <label class="availability-time-label">עד שעה:</label>
                    <input type="time" class="availability-time-input" data-field="to-time">
                    <label class="availability-time-label">הערות נוספות:</label>
                    <textarea class="availability-notes" data-field="notes" placeholder="פרטים נוספים על הזמינות החלקית..."></textarea>
                </div>
                <div class="availability-consistency">
                    <label class="consistency-checkbox-label">
                        <input type="checkbox" class="consistency-checkbox" data-date="${day.date}">
                        <span>זמינות קבועה</span>
                    </label>
                </div>
            </div>
        `).join('');

        availabilityDataGrid.innerHTML = gridHTML;

        // Add event listeners for availability changes
        this.setupAvailabilityEventListeners();
    }

    setupAvailabilityEventListeners() {
        const availabilitySelects = document.querySelectorAll('.availability-select');
        availabilitySelects.forEach(select => {
            select.addEventListener('change', (e) => {
                const timeContainer = e.target.parentElement.querySelector('.availability-time-container');
                if (e.target.value === 'partial') {
                    timeContainer.classList.remove('hidden');
                } else {
                    timeContainer.classList.add('hidden');
                }
            });
        });
    }

    toIsoString (date, hourOnly = false, includeMilliseconds = false) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        
        if (hourOnly) {
            return `${year}-${month}-${day}`;
        }
        
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        const milliseconds = String(date.getMilliseconds()).padStart(3, '0');
        
        let isoString = `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`;
        if (includeMilliseconds) {
            isoString += '.' + milliseconds;
        }
        return isoString;
    };

    fromIsoString(isoString) {
        return new Date(isoString);
    }

    async loadExistingAvailability() {
        try {
            // Get the current week's date range
            const days = this.generateNext7Days();
            const startDate = days[0].dt;
            const endDate = days[6].dt;

            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.AVAILABILITY'), // This endpoint needs to be created
                params: {
                    fromDate: this.toIsoString(startDate),
                    toDate: this.toIsoString(endDate)
                }
            });
            
            if (response.ok) {
                const result = await response.json();
                if (result.success && result.data) {
                    const availability = result.data;
                    this.populateAvailabilityFromServer(availability);
                }
            }
        } catch (error) {
            console.log('No existing availability data or server error:', error);
            // Continue with default values
        }
    }

    populateAvailabilityFromServer(dataAvailability) {
        if (!dataAvailability) return;

        Object.entries(dataAvailability).forEach(([date, availability]) => {
            const select = document.querySelector(`[data-date="${date}"]`);
            const timeContainer = select?.parentElement.querySelector('.availability-time-container');
            const consistencyCheckbox = document.querySelector(`.consistency-checkbox[data-date="${date}"]`);
            
            if (select) {
                select.value = availability.status || 'not-available';
                
                if (availability.status === 'partial' && timeContainer) {
                    timeContainer.classList.remove('hidden');
                    const fromTime = timeContainer.querySelector('[data-field="from-time"]');
                    const toTime = timeContainer.querySelector('[data-field="to-time"]');
                    const notes = timeContainer.querySelector('[data-field="notes"]');
                    
                    if (fromTime) fromTime.value = availability.fromTime || '';
                    if (toTime) toTime.value = availability.toTime || '';
                    if (notes) notes.value = availability.notes || '';
                }
            }
            
            if (consistencyCheckbox) {
                consistencyCheckbox.checked = availability.isConsistent == 'True'|| false;
            }
        });
    }

    async updateAvailability() {
        const updateBtn = document.getElementById('updateAvailabilityBtn');
        const originalText = updateBtn.textContent;
        updateBtn.textContent = 'מעדכן...';
        updateBtn.disabled = true;

        try {
            const availabilityData = this.collectAvailabilityData();
            
            // Get the current week's date range
            const days = this.generateNext7Days();
            const startDate = days[0].date;
            const endDate = days[6].date;
            
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.UPDATEREFEREEAVAILABILITY'),
                options: {
                    method: 'POST',
                    body: JSON.stringify({
                        ...availabilityData,
                        fromDate: startDate,
                        toDate: endDate
                    })
                }
            });

            if (response.ok) {
                this.showToast('זמינות עודכנה בהצלחה', 'success');
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            console.error('Error updating availability:', error);
            this.showToast('שגיאה בעדכון זמינות', 'error');
        } finally {
            updateBtn.textContent = originalText;
            updateBtn.disabled = false;
        }
    }

    collectAvailabilityData() {
        const availability = {};
        const selects = document.querySelectorAll('.availability-select');
        
        selects.forEach(select => {
            const date = select.dataset.date;
            const timeContainer = select.parentElement.querySelector('.availability-time-container');
            const consistencyCheckbox = document.querySelector(`.consistency-checkbox[data-date="${date}"]`);
            
            availability[date] = {
                status: select.value,
                isConsistent: consistencyCheckbox ? consistencyCheckbox.checked : false
            };
            
            if (select.value === 'partial' && timeContainer) {
                const fromTime = timeContainer.querySelector('[data-field="from-time"]').value;
                const toTime = timeContainer.querySelector('[data-field="to-time"]').value;
                const notes = timeContainer.querySelector('[data-field="notes"]').value;
                
                availability[date].fromTime = fromTime;
                availability[date].toTime = toTime;
                availability[date].notes = notes;
            }
        });
        
        return { availability };
    }

    formatDateWithoutTimezone(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    checkAndResetElapsedDays() {
        const today = new Date();
        today.setHours(0, 0, 0, 0); // Reset to start of day
        
        const consistencyCheckboxes = document.querySelectorAll('.consistency-checkbox');
        const availabilitySelects = document.querySelectorAll('.availability-select');
        
        consistencyCheckboxes.forEach(checkbox => {
            const dateString = checkbox.dataset.date;
            const dayDate = new Date(dateString);
            dayDate.setHours(0, 0, 0, 0);
            
            // Check if this day has elapsed (is before today)
            if (dayDate < today) {
                // If the day has elapsed and is not marked as consistent, reset it
                if (!checkbox.checked) {
                    const select = document.querySelector(`.availability-select[data-date="${dateString}"]`);
                    const timeContainer = select?.parentElement.querySelector('.availability-time-container');
                    
                    if (select) {
                        select.value = 'not-available';
                        console.log(`Reset availability for elapsed day: ${dateString}`);
                    }
                    
                    if (timeContainer) {
                        timeContainer.classList.add('hidden');
                        // Clear time inputs and notes
                        const fromTime = timeContainer.querySelector('[data-field="from-time"]');
                        const toTime = timeContainer.querySelector('[data-field="to-time"]');
                        const notes = timeContainer.querySelector('[data-field="notes"]');
                        if (fromTime) fromTime.value = '';
                        if (toTime) toTime.value = '';
                        if (notes) notes.value = '';
                    }
                }
            }
        });
    }

    getLastSecondOfDay = (date) => {
        return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59, 999);
    };

    async getRefereeGames(fromDate=null, toDate=null, includeArchived=false, includeRemoved=false, tenantKey=null) {
        if (fromDate) {
            fromDate.setHours(0, 0, 0, 0);
        }
        if (toDate) {
            toDate.setHours(23, 59, 59, 999);
        }
        
        // Fetch games from the referee games endpoint
        const response = await this.refreshTokenService.makeApiRequest({
            url: this.getConfig('ENDPOINTS.REFEREEGAMES'),
            params: {
                fromDate: fromDate ? this.toIsoString(fromDate) : null,
                toDate: toDate ? this.toIsoString(toDate) : null,
                includeArchived: includeArchived,
                includeRemoved: includeRemoved,
                tenantKey: tenantKey
            }
        });

        if (response.ok) {
            const result = await response.json();
            const games = result.data || result.games || [];
            return { games, syncMeta: result.syncMeta || null };
        }

        throw new Error('Failed to load games');
    }

    async getMessages(direction = 'both', provider = 'all', source = 'all', fromDate = null, toDate = null) {
        // Fetch messages from the messages endpoint
        const params = {
            direction: direction !== 'both' ? direction : null,
            provider: provider !== 'all' ? provider : null,
            source: source !== 'all' ? source : null,
        };

        if (fromDate) {
            fromDate.setHours(0, 0, 0, 0);
            params.fromDate = this.toIsoString(fromDate);
        }
        if (toDate) {
            toDate.setHours(23, 59, 59, 999);
            params.toDate = this.toIsoString(toDate);
        }
        
        const response = await this.refreshTokenService.makeApiRequest({
            url: this.getConfig('ENDPOINTS.MESSAGES'),
            params: params
        });

        if (response.ok) {
            const result = await response.json();
            const messages = result.data || result.messages || [];
            return messages;
        }

        throw new Error('Failed to load messages');
    }

    async loadMessagesData() {
        const g = this._beginAsyncTabLoad('messages');
        const directionFilter = document.getElementById('messagesDirectionFilter');
        const providerFilter = document.getElementById('messagesProviderFilter');
        const sourceFilter = document.getElementById('messagesSourceFilter');
        const fromDateFilter = document.getElementById('messagesFromDateFilter');
        const toDateFilter = document.getElementById('messagesToDateFilter');
        const messagesGridBody = document.getElementById('messagesGridBody');
        const messagesColspan = 6;
        
        // Set default date values if empty: 7 days ago to today
        if (fromDateFilter && !fromDateFilter.value) {
            const fromDate = new Date();
            fromDate.setDate(fromDate.getDate() - 7);
            fromDateFilter.value = fromDate.toISOString().split('T')[0];
        }
        
        if (toDateFilter && !toDateFilter.value) {
            const toDate = new Date();
            toDateFilter.value = toDate.toISOString().split('T')[0];
        }
        
        const direction = directionFilter ? directionFilter.value : 'both';
        const provider = providerFilter ? providerFilter.value : 'all';
        const source = sourceFilter ? sourceFilter.value : 'all';
        const fromDate = fromDateFilter && fromDateFilter.value ? new Date(fromDateFilter.value) : null;
        const toDate = toDateFilter && toDateFilter.value ? new Date(toDateFilter.value) : null;
        
        try {
            // Show loading state
            if (messagesGridBody) {
                messagesGridBody.innerHTML = `<tr><td colspan="${messagesColspan}" class="loading-message">טוען הודעות...</td></tr>`;
            }
            
            const messages = await this.getMessages(direction, provider, source, fromDate, toDate);
            
            if (this._staleAsyncTabLoad('messages', g)) return;

            // Store messages for filtering
            this.allMessages = messages;
            
            // Render messages
            this.renderMessagesGrid(messages);
            this._updateMessagesRefreshButtonLabel(messages.length);
            console.log(`✅ Loaded ${messages.length} messages`);

        } catch (error) {
            if (this._staleAsyncTabLoad('messages', g)) return;
            console.error('Error loading messages:', error);
            this._updateMessagesRefreshButtonLabel(0);
            if (messagesGridBody) {
                if (this.isServerDownError(error)) {
                    messagesGridBody.innerHTML = `<tr><td colspan="${messagesColspan}" class="loading-message">שגיאה בחיבור לשרת. ייתכן שהשרת אינו זמין כרגע.</td></tr>`;
                } else {
                    messagesGridBody.innerHTML = `<tr><td colspan="${messagesColspan}" class="loading-message">שגיאה בטעינת הודעות</td></tr>`;
                }
            }
        }
    }

    _formatMessageSourceLabel(source) {
        const s = String(source || '').trim().toLowerCase();
        const labels = {
            meta: 'Meta',
            greenapi: 'Green API',
            twilio: 'Twilio',
            twillio: 'Twilio',
            telegram: 'Telegram',
            manychat: 'ManyChat',
            push: 'Push',
            unknown: '—',
        };
        return labels[s] || (source || '—');
    }

    _formatMessageProviderLabel(provider) {
        const p = String(provider || '').trim().toLowerCase();
        const labels = {
            whatsapp: 'WhatsApp',
            push: 'Push',
            telegram: 'Telegram',
            unknown: '—',
        };
        return labels[p] || (provider || '—');
    }

    _updateMessagesRefreshButtonLabel(count) {
        const btn = document.getElementById('refreshMessages');
        if (btn) btn.textContent = count >= 0 ? `רענן (${count})` : 'רענן';
    }

    txt2WhatsappLink(mobileNo) {
        return `https://wa.me/${mobileNo}`;
    }

    renderMessagesGrid(messages) {
        const messagesGridBody = document.getElementById('messagesGridBody');
        if (!messagesGridBody) return;

        if (!messages || messages.length === 0) {
            messagesGridBody.innerHTML = '<tr><td colspan="6" class="loading-message">אין הודעות</td></tr>';
            return;
        }

        messagesGridBody.innerHTML = messages.map(message => {
            const direction = message.direction;
            const directionText = direction === 'to' ? 'נכנסת' : 'יוצאת';
            const directionClass = direction === 'from' ? 'direction-from' : 'direction-to';
            const source = message.source || 'unknown';
            const sourceClass = `message-source message-source-${String(source).toLowerCase().replace(/[^a-z0-9]/g, '')}`;
            const provider = message.provider || 'unknown';
            const providerClass = `provider-${provider} message-provider-cell`;
            const datetime = message.created || message.datetime || message.createdAt || message.date || '-';
            const mobileNo = message.mobileNo || message.mobile || message.phone || '-';
            const messageText = message.message || message.text || message.content || '-';

            return `
                <tr>
                    <td class="${directionClass}">${directionText}</td>
                    <td>${this.formatDateTime(datetime)}</td>
                    <td><a href="${this.txt2WhatsappLink(mobileNo)}" target="_blank">${mobileNo}</a></td>
                    <td class="${sourceClass}">${this.escapeHtml(this._formatMessageSourceLabel(source))}</td>
                    <td class="${providerClass}">${this.escapeHtml(this._formatMessageProviderLabel(provider))}</td>
                    <td class="message-text-col"><textarea readonly class="message-text-cell" rows="2">${this.escapeHtml(messageText)}</textarea></td>
                </tr>
            `;
        }).join('');

        this._bindMessageTextCellHover(messagesGridBody);
    }

    _bindMessageTextCellHover(container) {
        const table = container && container.closest('table');
        if (!table || this._messageTextCellHoverBound) return;
        this._messageTextCellHoverBound = true;
        let overlay = null;

        table.addEventListener('mouseover', (e) => {
            const cell = e.target.closest('.message-text-cell');
            if (!cell || overlay) return;
            const rect = cell.getBoundingClientRect();
            overlay = document.createElement('textarea');
            overlay.readOnly = true;
            overlay.value = cell.value;
            overlay.className = 'message-text-cell-overlay';
            overlay.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.top}px;min-width:${rect.width}px;min-height:${rect.height}px;z-index:9999;padding:6px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;box-shadow:0 4px 12px rgba(0,0,0,0.15);font:inherit;resize:none;overflow:auto;box-sizing:border-box;`;
            document.body.appendChild(overlay);
            overlay.style.width = (Math.max(rect.width, overlay.scrollWidth + 4) + 12) + 'px';
            overlay.style.height = (Math.min(Math.max(rect.height, overlay.scrollHeight + 4), 320) + 12) + 'px';

            const removeOverlay = () => {
                if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
                overlay = null;
            };
            overlay.addEventListener('mouseleave', removeOverlay);
        });

        table.addEventListener('mouseout', (e) => {
            if (e.relatedTarget && overlay && overlay.contains(e.relatedTarget)) return;
            if (overlay && overlay.parentNode) {
                overlay.parentNode.removeChild(overlay);
                overlay = null;
            }
        });
    }

    filterMessages() {
        if (!this.allMessages) {
            return;
        }

        const directionFilter = document.getElementById('messagesDirectionFilter');
        const providerFilter = document.getElementById('messagesProviderFilter');
        
        const direction = directionFilter ? directionFilter.value : 'both';
        const provider = providerFilter ? providerFilter.value : 'all';

        let filteredMessages = [...this.allMessages];

        // Filter by direction
        if (direction !== 'both') {
            filteredMessages = filteredMessages.filter(msg => {
                const msgDirection = msg.direction || (msg.from ? 'from' : 'to');
                return msgDirection === direction;
            });
        }

        // Filter by provider
        if (provider !== 'all') {
            filteredMessages = filteredMessages.filter(msg => {
                const msgProvider = msg.provider || 'unknown';
                return msgProvider === provider;
            });
        }

        this.renderMessagesGrid(filteredMessages);
    }

    formatDateTime(dateTime) {
        if (!dateTime) return '-';
        try {
            const date = new Date(dateTime);
            if (isNaN(date.getTime())) return dateTime;
            return this.formatDate(date) + ' ' + this.formatTime(date);
        } catch (e) {
            return dateTime;
        }
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async loadRefereeGamesForAvailability(days) {
        try {
            // Get date range for the 7 days
            const startDate = days[0].dt;
            const endDate = this.getLastSecondOfDay(days[6].dt);
            
            const { games } = await this.getRefereeGames(startDate, endDate, true, false, null);
            this.displayGamesInAvailability(days, games);
        } catch (error) {
            console.error('Error loading games for availability:', error);
        }
    }

    displayGamesInAvailability(days, games) {
        // Group games by date
        const gamesByDate = {};
        
        games.forEach(game => {
            const gameDate = game.date || game.gameDate;
            if (gameDate) {
                const dateSOD = new Date(gameDate);
                dateSOD.setHours(0, 0, 0, 0);
                const dateSODStr = this.toIsoString(dateSOD);
                if (!gamesByDate[dateSODStr]) {
                    gamesByDate[dateSODStr] = [];
                }
                gamesByDate[dateSODStr].push(game);
            }
        });

        // Add game highlights to each day
        days.forEach(day => {
            const dateStr = day.date;
            const dayGames = gamesByDate[dateStr] || [];
            
            if (dayGames.length > 0) {
                this.addGameHighlightsToDay(day, dayGames);
            }
        });
    }

    addGameHighlightsToDay(day, games) {
        const dayElement = document.querySelector(`[data-date="${day.date}"]`)?.parentElement;
        if (!dayElement) return;

        // Remove existing games container if it exists
        const existingGamesContainer = dayElement.querySelector('.availability-games');
        if (existingGamesContainer) {
            existingGamesContainer.remove();
        }

        // Create new games container
        const gamesContainer = document.createElement('div');
        gamesContainer.className = 'availability-games';
        
        games.forEach(game => {
            const gameElement = document.createElement('div');
            gameElement.className = 'availability-game-item';
            
            const gameDetails = this.getGameDetails(game);
            const gameTime = gameDetails.gameTime;
            const homeTeam = gameDetails.homeTeam;
            const guestTeam = gameDetails.guestTeam;
            const league = gameDetails.league;
            const field = gameDetails.field;
            const role = gameDetails.role;
            
            gameElement.innerHTML = `
                <div class="game-time">${gameTime}</div>
                <div class="game-teams">${homeTeam} - ${guestTeam}</div>
                <div class="game-details">
                    <span class="game-league">${league}</span>
                </div>
                <div class="game-details">
                    <span class="game-field">${field}</span>
                </div>
                <div class="game-details">
                    <span class="game-role">${role}</span>
                </div>
            `;
            
            gamesContainer.appendChild(gameElement);
        });

        // Insert games container after the date but before the select
        const dayDate = dayElement.querySelector('.availability-day-date');
        if (dayDate) {
            dayDate.insertAdjacentElement('afterend', gamesContainer);
        }
    }

    async navigateToPreviousWeek() {
        this.currentWeekStart.setDate(this.currentWeekStart.getDate() - 7);
        await this.loadAvailabilityData();
    }

    async navigateToNextWeek() {
        this.currentWeekStart.setDate(this.currentWeekStart.getDate() + 7);
        await this.loadAvailabilityData();
    }

    updateWeekDisplay(days) {
        const weekRangeDisplay = document.getElementById('weekRangeDisplay');
        if (!weekRangeDisplay || days.length === 0) return;

        const startDate = days[0].dt;
        const endDate = days[6].dt;
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        
        // Check if this is the current week
        const isCurrentWeek = startDate <= today && endDate >= today;
        
        if (isCurrentWeek) {
            weekRangeDisplay.textContent = 'השבוע הקרוב';
        } else {
            const startStr = startDate.toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit' });
            //const startStr = startDate.substring(5,10);
            const endStr = endDate.toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit' });
            //const endStr = endDate.substring(5,10);
            weekRangeDisplay.textContent = `${startStr} - ${endStr}`;
        }
    }

    async loadDocumentsData() {
        const documentsList = document.getElementById('documentsList');
        documentsList.innerHTML = '<div class="loading">טוען מסמכים...</div>';

        try {
            // TODO: Replace with actual API endpoint
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.DOCUMENTS') // This endpoint needs to be created
            });
            
            if (response.ok) {
                const data = await response.json();
                this.displayDocuments(data.data || data || []);
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            console.error('Error loading documents:', error);
            // Show sample documents for demo
            this.displaySampleDocuments();
        }
    }

    displayDocuments(documents) {
        const documentsList = document.getElementById('documentsList');
        
        if (documents.length === 0) {
            documentsList.innerHTML = '<div class="empty-state">אין מסמכים זמינים</div>';
            return;
        }

        const documentsHTML = documents.map(doc => {
            const docName = doc.name || doc.title || doc.docName || 'מסמך';
            const docDescription = doc.description || doc.description || '';
            const docSize = doc.size || doc.size || '';
            const docUrl = doc.url || doc.downloadUrl || `https://www.refereex.com/docs/${doc.docFile}` || '';
            
            const innerHtml =`
            <div class="document-item">
                <div class="document-info">
                    <div class="document-name">${docName}</div>
                    <div class="document-description">${docDescription}</div>
                    ${docSize ? `<div class="document-size">${docSize}</div>` : ''}
                </div>
                <a href="${encodeURI(docUrl)}" target="_blank" class="document-download" download>
                    <span>📥</span>
                    הורד
                </a>
            </div>
            `;
            return innerHtml;
    }).join('');
        documentsList.innerHTML = documentsHTML;
    }

    displaySampleDocuments() {
        const sampleDocuments = [
            {
                name: 'חוקי המשחק 2024',
                description: 'חוקי המשחק המעודכנים לעונת 2024',
                size: '2.3 MB',
                url: '#'
            },
            {
                name: 'מדריך שופט',
                description: 'מדריך מקיף לשופטים מתחילים ומנוסים',
                size: '1.8 MB',
                url: '#'
            },
            {
                name: 'טופס דיווח משחק',
                description: 'טופס לדיווח תוצאות משחקים',
                size: '245 KB',
                url: '#'
            }
        ];

        this.displayDocuments(sampleDocuments);
    }

    async loadRulesData() {
        const rulesContent = document.getElementById('rulesContent');
        
        const rules = {
            general: {
                title: 'חוקים כלליים',
                content: `
                    <h3>חוקי המשחק הבסיסיים</h3>
                    <ul>
                        <li>משחק נמשך 90 דקות (שני מחציות של 45 דקות)</li>
                        <li>כל קבוצה יכולה להחליף עד 3 שחקנים במהלך המשחק</li>
                        <li>הכדור חייב להיות בתוך המגרש בכל רגע נתון</li>
                        <li>שער נחשב רק כאשר הכדור חוצה את קו השער במלואו</li>
                    </ul>
                `
            },
            fouls: {
                title: 'עבירות',
                content: `
                    <h3>סוגי עבירות</h3>
                    <ul>
                        <li><strong>עבירה ישירה:</strong> בעיטה חופשית ישירה או פנדל</li>
                        <li><strong>עבירה עקיפה:</strong> בעיטה חופשית עקיפה</li>
                        <li><strong>כרטיס צהוב:</strong> אזהרה לשחקן</li>
                        <li><strong>כרטיס אדום:</strong> הרחקה מהמשחק</li>
                    </ul>
                `
            },
            penalties: {
                title: 'עונשין',
                content: `
                    <h3>עונשים במשחק</h3>
                    <ul>
                        <li>בעיטה חופשית ישירה - עבירה בתוך רחבת העונשין</li>
                        <li>בעיטה חופשית עקיפה - עבירה עקיפה</li>
                        <li>פנדל - עבירה ישירה בתוך רחבת העונשין</li>
                        <li>זריקה - כדור יצא מהמגרש</li>
                    </ul>
                `
            },
            offside: {
                title: 'נבדל',
                content: `
                    <h3>חוק הנבדל</h3>
                    <ul>
                        <li>שחקן נמצא בנבדל אם הוא קרוב יותר לשער היריב מהכדורשחקן הלפני אחרון</li>
                        <li>נבדל נקבע רק כאשר השחקן מעורב במשחק</li>
                        <li>נבדל לא נקבע בבעיטה מירי</li>
                        <li>נבדל לא נקבע בבעיטה מירי</li>
                    </ul>
                `
            }
        };

        this.displayRules(rules.general);
    }

    loadRulesCategory(category) {
        const rulesContent = document.getElementById('rulesContent');
        
        const rules = {
            general: {
                title: 'חוקים כלליים',
                content: `
                    <h3>חוקי המשחק הבסיסיים</h3>
                    <ul>
                        <li>משחק נמשך 90 דקות (שני מחציות של 45 דקות)</li>
                        <li>כל קבוצה יכולה להחליף עד 3 שחקנים במהלך המשחק</li>
                        <li>הכדור חייב להיות בתוך המגרש בכל רגע נתון</li>
                        <li>שער נחשב רק כאשר הכדור חוצה את קו השער במלואו</li>
                    </ul>
                `
            },
            fouls: {
                title: 'עבירות',
                content: `
                    <h3>סוגי עבירות</h3>
                    <ul>
                        <li><strong>עבירה ישירה:</strong> בעיטה חופשית ישירה או פנדל</li>
                        <li><strong>עבירה עקיפה:</strong> בעיטה חופשית עקיפה</li>
                        <li><strong>כרטיס צהוב:</strong> אזהרה לשחקן</li>
                        <li><strong>כרטיס אדום:</strong> הרחקה מהמשחק</li>
                    </ul>
                `
            },
            penalties: {
                title: 'עונשין',
                content: `
                    <h3>עונשים במשחק</h3>
                    <ul>
                        <li>בעיטה חופשית ישירה - עבירה בתוך רחבת העונשין</li>
                        <li>בעיטה חופשית עקיפה - עבירה עקיפה</li>
                        <li>פנדל - עבירה ישירה בתוך רחבת העונשין</li>
                        <li>זריקה - כדור יצא מהמגרש</li>
                    </ul>
                `
            },
            offside: {
                title: 'נבדל',
                content: `
                    <h3>חוק הנבדל</h3>
                    <ul>
                        <li>שחקן נמצא בנבדל אם הוא קרוב יותר לשער היריב מהכדורשחקן הלפני אחרון</li>
                        <li>נבדל נקבע רק כאשר השחקן מעורב במשחק</li>
                        <li>נבדל לא נקבע בבעיטה מירי</li>
                        <li>נבדל לא נקבע בבעיטה מירי</li>
                    </ul>
                `
            }
        };

        this.displayRules(rules[category]);
        
        // Update active category button
        document.querySelectorAll('.rule-category').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelector(`[data-category="${category}"]`).classList.add('active');
    }

    displayRules(rulesData) {
        const rulesContent = document.getElementById('rulesContent');
        rulesContent.innerHTML = rulesData.content;
    }

    loadChatData() {
        // Chat data is already loaded in memory
        this.displayChatMessages();
    }

    sendChatMessage() {
        const input = document.getElementById('chatInput');
        const message = input.value.trim();
        
        if (message) {
            this.addChatMessage('sent', message);
            input.value = '';
            
            // Simulate response (replace with actual API call)
            setTimeout(() => {
                this.addChatMessage('received', 'ההודעה שלך התקבלה. נחזור אליך בקרוב.');
            }, 1000);
        }
    }

    addChatMessage(type, text) {
        const message = {
            id: Date.now(),
            type: type,
            text: text,
            timestamp: new Date().toLocaleString('he-IL', { 
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit', 
                minute: '2-digit' 
            })
        };

        this.chatMessages.push(message);
        this.displayChatMessages();
        
        // Sync message to server for cross-device access
        if (this.chatSyncEnabled && this.isOnline) {
            this.syncMessageToServer(message);
        }
        
        // Store message locally for offline access
        this.storeChatMessageLocally(message);
    }

    // Store chat message in storage for offline access
    storeChatMessageLocally(message) {
        try {
            const storedMessages = JSON.parse(this.getStorageKey('refportal_chat_messages') || '[]');
            storedMessages.push(message);
            
            // Keep only last 100 messages to prevent storage overflow
            if (storedMessages.length > 100) {
                storedMessages.splice(0, storedMessages.length - 100);
            }
            
            this.setStorageKey('refportal_chat_messages', JSON.stringify(storedMessages));
        } catch (error) {
            console.error('Error storing chat message locally:', error);
        }
    }

    // Load chat messages from storage
    loadChatMessagesFromLocal() {
        try {
            const storedMessages = JSON.parse(this.getStorageKey('refportal_chat_messages') || '[]');
            this.chatMessages = storedMessages;
            this.displayChatMessages();
            
            // Update last message ID for sync
            if (this.chatMessages.length > 0) {
                this.lastMessageId = Math.max(...this.chatMessages.map(msg => msg.id));
            }
        } catch (error) {
            console.error('Error loading chat messages from local storage:', error);
        }
    }

    // Sync message to server for cross-device access
    async syncMessageToServer(message) {
        if (!this.getConfig('FEATURES.CHAT_SYNC')) {
            return;
        }

        try {
            const clientIdentifier = await this.getClientIdentifier();
            const mobileNo = this.currentUser.mobileNo;
            if (!clientIdentifier) {
                console.warn('No client identifier available for chat sync');
                return;
            }

            const response = await this.refreshTokenService.makeApiRequest({
                url:`${this.getConfig('ENDPOINTS.CHAT')}/sync-message`,
                method: 'POST',
                body: JSON.stringify({
                    message: message,
                    fromMobileNo: mobileNo,
                    timestamp: new Date().toISOString()
                })
            });

            if (response.ok) {
                console.log('✅ Chat message synced to server');
            } else {
                console.warn('⚠️ Failed to sync chat message to server');
            }
        } catch (error) {
            console.error('❌ Error syncing chat message to server:', error);
        }
    }

    // Fetch chat messages from server for cross-device sync
    async fetchChatMessagesFromServer() {
        try {
            const clientIdentifier = await this.getClientIdentifier();
            const mobileNo = this.currentUser?.mobileNo || null;

            if (!clientIdentifier) {
                console.warn('No client identifier available for chat sync');
                return;
            }

            const response = await this.refreshTokenService.makeApiRequest({
                url:`${this.getConfig('ENDPOINTS.CHAT')}/messages?fromMobileNo=${mobileNo}&lastMessageId=${this.lastMessageId || 0}`,
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.messages && data.messages.length > 0) {
                    console.log('📥 Received new chat messages from server:', data.messages.length);
                    
                    // Add new messages to local chat
                    data.messages.forEach(serverMessage => {
                        // Check if message already exists locally
                        const exists = this.chatMessages.some(localMsg => localMsg.id === serverMessage.id);
                        if (!exists) {
                            this.chatMessages.push(serverMessage);
                        }
                    });
                    
                    // Update last message ID
                    if (data.messages.length > 0) {
                        this.lastMessageId = Math.max(...data.messages.map(msg => msg.id));
                    }
                    
                    // Refresh display
                    this.displayChatMessages();
                    
                    // Store updated messages locally
                    this.storeAllChatMessagesLocally();
                }
            }
        } catch (error) {
            console.error('❌ Error fetching chat messages from server:', error);
        }
    }

    // Store all chat messages locally
    storeAllChatMessagesLocally() {
        try {
            this.setStorageKey('refportal_chat_messages', JSON.stringify(this.chatMessages));
        } catch (error) {
            console.error('Error storing all chat messages locally:', error);
        }
    }

    // Start chat synchronization
    startChatSync() {
        if (this.chatSyncInterval) {
            clearInterval(this.chatSyncInterval);
        }
        
        // Sync every 5 seconds when online
        this.chatSyncInterval = setInterval(() => {
            if (this.isOnline && this.chatSyncEnabled) {
                this.fetchChatMessagesFromServer();
            }
        }, 5000);
        
        console.log('🔄 Chat synchronization started');
    }

    // Stop chat synchronization
    stopChatSync() {
        if (this.chatSyncInterval) {
            clearInterval(this.chatSyncInterval);
            this.chatSyncInterval = null;
        }
        console.log('⏹️ Chat synchronization stopped');
    }

    // Initialize chat synchronization
    async initializeChatSync() {
        if (!this.getConfig('FEATURES.CHAT_SYNC')) {
            return;
        }

        try {
            // Load local messages first
            this.loadChatMessagesFromLocal();
            
            // Setup online/offline handling
            this.setupOnlineStatusHandling();
            
            // Start sync if online
            if (this.isOnline && this.chatSyncEnabled) {
                this.startChatSync();
                
                // Initial sync with server
                await this.fetchChatMessagesFromServer();
                
                // Start real-time updates using Server-Sent Events
                this.startRealTimeChatUpdates();
            }
            
            console.log('✅ Chat synchronization initialized');
            
            // Update initial sync status
            this.updateChatSyncStatus(true); // Force show on initialization
        } catch (error) {
            console.error('❌ Error initializing chat sync:', error);
        }
    }

    // Start real-time chat updates using Server-Sent Events
    startRealTimeChatUpdates() {
        try {
            const clientIdentifier = this.getClientIdentifier();
            const mobileNo = this.currentUser?.mobileNo || null;
            if (!clientIdentifier) {
                console.warn('No client identifier available for real-time updates');
                return;
            }

            // Close existing SSE connection if any
            if (this.chatEventSource) {
                this.chatEventSource.close();
            }

            // Create new SSE connection
            const eventSourceUrl = `${this.getConfig('ENDPOINTS.CHAT')}/events?fromMobileNo=${mobileNo}`;
            this.chatEventSource = new EventSource(eventSourceUrl);

            this.chatEventSource.onopen = () => {
                console.log('🔗 Real-time chat connection established');
            };

            this.chatEventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'new_message') {
                        console.log('📥 Real-time message received:', data.message);
                        this.handleRealTimeMessage(data.message);
                    }
                } catch (error) {
                    console.error('Error parsing real-time message:', error);
                }
            };

            this.chatEventSource.onerror = (error) => {
                console.error('❌ Real-time chat connection error:', error);
                // Fallback to polling if SSE fails
                this.startChatSync();
            };

        } catch (error) {
            console.error('❌ Error starting real-time chat updates:', error);
            // Fallback to polling
            this.startChatSync();
        }
    }

    // Handle real-time message from SSE
    handleRealTimeMessage(message) {
        // Check if message already exists locally
        const exists = this.chatMessages.some(localMsg => localMsg.id === message.id);
        if (!exists) {
            // Add new message to chat
            this.chatMessages.push(message);
            
            // Update display
            this.displayChatMessages();
            
            // Store locally
            this.storeChatMessageLocally(message);
            
            // Update last message ID
            if (message.id > this.lastMessageId) {
                this.lastMessageId = message.id;
            }
            
            // Show notification for new message
            this.showNewMessageNotification(message);
        }
    }

    // Show notification for new message
    showNewMessageNotification(message) {
        if (this.pushhNotificationPermission === true) {
            // Show browser notification
            new Notification('RefereeX - הודעה חדשה', {
                body: message.text,
                icon: 'images/RefereeX_transparent_small.png',
                badge: 'images/RefereeX_transparent_small.png'
            });
        }
        
        // Show toast notification
        this.showToast('הודעה חדשה התקבלה', 'info');
    }

    // Stop real-time updates
    stopRealTimeChatUpdates() {
        if (this.chatEventSource) {
            this.chatEventSource.close();
            this.chatEventSource = null;
            console.log('⏹️ Real-time chat updates stopped');
        }
    }

    displayChatMessages() {
        const chatMessages = document.getElementById('chatMessages');
        
        if (this.chatMessages.length === 0) {
            chatMessages.innerHTML = '<div class="empty-state">אין הודעות</div>';
            return;
        }

        const messagesHTML = this.chatMessages.map(msg => `
            <div class="message ${msg.type}">
                <div class="message-text">${msg.text}</div>
                <div class="message-time">${msg.timestamp}</div>
            </div>
        `).join('');

        chatMessages.innerHTML = messagesHTML;
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    handleActionButton(action) {
        switch (action) {
            case 'request-assignment':
                this.addChatMessage('system', 'בקשת שיבוץ נשלחה. נבדוק זמינות ונחזור אליך.');
                break;
            case 'report-issue':
                this.addChatMessage('system', 'דיווח בעיה נשלח. צוות התמיכה יטפל בזה בהקדם.');
                break;
            case 'request-support':
                this.addChatMessage('system', 'בקשת תמיכה נשלחה. נציג יצור איתך קשר בקרוב.');
                break;
        }
    }

    async requestPushNotificationPermissionsSubscribe(manual=false) {
        if (!this.checkPushNotificationSupported()) {
            if (manual) {
                this.showToast('הדפדפן שלך לא תומך בהתראות', 'error');
            }
            return;
        }

        if (!manual) {
            if (this.pushhNotificationPermission) {
                if (manual) {
                    this.showToast('הרשאות התראות כבר ניתנו', 'info');
                }
                return;
            }

            if (Notification.permission === 'denied') {
                if (manual) {
                    this.showToast(`הרשאות התראות נדחו. אנא הפעל מחדש ב${this.deviceName}`, 'error');
                }
                return;
            }
        }

        try {
            const notificationPermission = await Notification.requestPermission();
            if (notificationPermission === 'granted') {
                this.showToast('הרשאות התראות ניתנו בהצלחה!', 'success');
                await this.subscribeToPushNotifications();
            } else {
                this.showToast(`הרשאות התראות נדחו. אנא הפעל מחדש ב${this.deviceName}`, 'error');
            }
            
            // Update button state after permission change
            this.updatePushNotificationButtonState();
        } catch (error) {
            this.showToast('שגיאה בבקשת הרשאות התראות', 'error');
            this.updatePushNotificationButtonState();
        }
    }

    async requestPushNotificationPermissionsUnsubscribe(manual=false) {
        if (!this.checkPushNotificationSupported()) {
            if (manual) {
                this.showToast('הדפדפן שלך לא תומך בהתראות', 'error');
            }
            return;
        }

        if (!manual) {
            if (!this.pushhNotificationPermission) {
                if (manual) {
                    this.showToast('הרשאות התראות לא ניתנו', 'info');
                }
                return;
            }
        }

        try {
            await this.unsubscribeFromPushNotifications();
            if (!this.pushhNotificationPermission) {
                this.showToast('הרשאות התראות הוסרו בהצלחה!', 'warning');
            }
        } catch (error) {
            this.showToast('שגיאה בבקשת הרשאות התראות', 'error');
        }
        finally {
            this.updatePushNotificationButtonState();
        }
    }

    // Update notification button state based on current permission
    updatePushNotificationButtonState() {
        const pushNotificationBtn = document.getElementById('notificationBtn');
        if (!pushNotificationBtn) return;
        
        const currentPermission = Notification.permission;
        
        if (this.pushhNotificationPermission && currentPermission === 'granted') {
            pushNotificationBtn.disabled = false;
            pushNotificationBtn.title = 'הרשאות התראות ניתנו. לחץ ארוך לאיפוס';
            pushNotificationBtn.textContent = '🔔'; // Active notifications
        } else if (!this.pushhNotificationPermission && currentPermission === 'denied' ||
            this.pushhNotificationPermission) {
            pushNotificationBtn.disabled = false;
            pushNotificationBtn.title = 'הרשאות התראות נדחו. לחץ לבקשת הרשאות התראות';
            pushNotificationBtn.textContent = '🔕'; // Notifications muted/denied
        } else if (!this.pushhNotificationPermission) {
            pushNotificationBtn.disabled = false;
            pushNotificationBtn.title = 'לחץ לבקשת הרשאות התראות';
            pushNotificationBtn.textContent = '📢'; // Ready to request notifications
        } else {
            pushNotificationBtn.disabled = true;
            pushNotificationBtn.title = 'התראות לא נתמכות בדפדפן זה';
            pushNotificationBtn.textContent = '❌';
        }
    }

    checkPWAStatus() {
        const isInstalled = this.isPWAInstalled();
        const canInstall = this.checkServiceWorkerSupported() && this.checkPushManagerSupported();
        
        console.log('📱 PWA Status:', {
            isInstalled,
            canInstall,
            userAgent: navigator.userAgent
        });
        
        // Update UI based on PWA status
        this.updatePWAUI(isInstalled, canInstall);
        
        // Check install prompt status
        const promptStatus = this.getInstallPromptStatus();
        console.log('🔍 Install Prompt Status in checkPWAStatus:', promptStatus);
        
        return { isInstalled, canInstall, promptStatus };
    }

    updatePWAUI(isInstalled, _canInstall) {
        const installPrompt = document.getElementById('installPrompt');
        if (!installPrompt) return;

        if (isInstalled) {
            installPrompt.classList.remove('show');
            installPrompt.style.display = 'none';
        }
    }

    showAppModeIndicator() {
        // Add a subtle indicator that the app is running in standalone mode
        const header = document.querySelector('.app-header');
        if (header && !document.querySelector('.app-mode-indicator')) {
            const indicator = document.createElement('div');
            indicator.className = 'app-mode-indicator';
            indicator.innerHTML = `
                <span class="indicator-icon">📱</span>
                <span class="indicator-text">אפליקציה</span>
            `;
            header.appendChild(indicator);
        }
    }

    reEnableInteractiveElements() {
        // Re-enable all buttons and interactive elements
        const buttons = document.querySelectorAll('button, .btn-primary, .btn-secondary, .action-btn, .nav-item');
        buttons.forEach(button => {
            button.style.pointerEvents = 'auto';
            button.style.zIndex = 'auto';
        });
        
        // Re-enable navigation
        const navItems = document.querySelectorAll('.nav-item');
        navItems.forEach(item => {
            item.style.pointerEvents = 'auto';
        });
        
        // Re-enable chat functionality
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.style.pointerEvents = 'auto';
        }
        
        // Re-enable all content sections
        const contentSections = document.querySelectorAll('.content-section');
        contentSections.forEach(section => {
            section.style.pointerEvents = 'auto';
        });
        
        // Re-enable main content
        const mainContent = document.querySelector('main');
        if (mainContent) {
            mainContent.style.pointerEvents = 'auto';
        }
        
        console.log('✅ Interactive elements re-enabled');
    }
    
    testButtonClickability() {
        console.log('🧪 Testing button clickability...');
        
        const buttons = document.querySelectorAll('button, .btn-primary, .btn-secondary, .action-btn, .nav-item');
        let clickableCount = 0;
        let totalCount = 0;
        
        buttons.forEach((button, index) => {
            totalCount++;
            const isClickable = button.style.pointerEvents !== 'none' && 
                               button.style.display !== 'none' && 
                               !button.disabled;
            
            if (isClickable) {
                clickableCount++;
            }
            
            console.log(`Button ${index + 1}: ${isClickable ? '✅ Clickable' : '❌ Not Clickable'}`);
        });
        
        console.log(`📊 Button Status: ${clickableCount}/${totalCount} buttons are clickable`);
        
        return { clickable: clickableCount, total: totalCount };
    }

    // Helper method to check if push notifications are actually available
    async validatePWAServices() {
        console.log('🔍 Checking PWA services availability...');
        
        // Check basic support
        if (!this.checkServiceWorkerSupported()) {
            return { available: false, reason: 'service-worker-not-supported' };
        }
        
        if (!this.checkPushManagerSupported()) {
            return { available: false, reason: 'push-manager-not-supported' };
        }
        
        // Check notification permission
        if (!this.checkPushNotificationSupported()) {
            console.warn('⚠️ Notifications not supported');
            return { available: false, reason: 'notifications-not-supported' };
        }
        
        // Check if service worker is registered and active
        try {
            const serviceWorkerRegistration = await this.getServiceWorkerRegistration();
            if (!serviceWorkerRegistration) {
                console.warn('⚠️ No service worker registration found');
                return { available: false, reason: 'no-service-worker-registration' };
            }
            
            if (!serviceWorkerRegistration.active) {
                console.warn('⚠️ Service worker not yet active');
                return { available: false, reason: 'service-worker-not-active' };
            }

            return { available: true, registration: serviceWorkerRegistration };
        } catch (error) {
            console.error('❌ Error checking push notification availability:', error);
            return { available: false, reason: 'service-worker-error', error: error.message };
        }
    }
    
    // Helper method to check if push notifications are actually available
    async checkPushNotificationAvailability() {
        console.log('🔍 Checking push notification status...');
        
        // Check notification permission
        if (!this.checkPushNotificationSupported()) {
            console.warn('⚠️ Notifications not supported');
            return { available: false, reason: 'notifications-not-supported' };
        }
        
        if (Notification.permission === 'denied') {
            console.warn('⚠️ Notification permission denied');
            return { available: false, reason: 'permission-denied' };
        }
        
        if (Notification.permission === 'default') {
            console.log('📱 Notification permission not yet requested');
            return { available: false, reason: 'permission-not-requested' };
        }
        
        return { available: true };
    }

    async subscribeToPushNotifications() {
        console.log('🔔 Subscribing to push notifications...');
        
        // Check availability first
        const supported = await this.checkPushManagerSupported();
        if (!supported) {
            console.warn(`⚠️ Push notifications not supported`);
            return null;
        }

        try {
            // Check if we already have a subscription
            const serviceWorkerRegistration = await this.getServiceWorkerRegistration();
            const existingSubscription = await serviceWorkerRegistration.pushManager.getSubscription();
            if (false && existingSubscription) {
                console.log('✅ Already subscribed to push notifications:', existingSubscription);
                return existingSubscription;
            }
            
            console.log('📱 Creating new push subscription...');
            console.log('🔑 Using VAPID public key:', this.getConfig('VAPID_PUBLIC_KEY'));
            
            const pushSubscription = await serviceWorkerRegistration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: this.urlBase64ToUint8Array(this.getConfig('VAPID_PUBLIC_KEY'))
            });
            
            console.log('✅ Successfully subscribed to push notifications:', pushSubscription);
            
            // Send subscription to server
            await this.sendPushSubscriptionToServer(pushSubscription, true);
            await this.checkPushSubscriptionStatus();
            return pushSubscription;
        } catch (error) {
            console.error('❌ Error subscribing to push notifications:', error);
            return null;
        }
    }

    async unsubscribeFromPushNotifications() {
        try {
            console.log('�� Unsubscribing from push notifications...');
            
            // Get service worker registration
            const serviceWorkerRegistration = await this.getServiceWorkerRegistration();
            if (!serviceWorkerRegistration) {
                console.log('❌ No service worker registration found');
                return false;
            }
            
            // Get current push subscription
            const pushSubscription = await serviceWorkerRegistration.pushManager.getSubscription();
            if (!pushSubscription) {
                console.log('✅ No active push subscription found');
                return true;
            }
            
            // Unsubscribe from push notifications
            const unsubscribed = await pushSubscription.unsubscribe();
            const per = Notification.permission;
            if (unsubscribed) {
                console.log('✅ Successfully unsubscribed from push notifications');
                
                // Remove subscription from server
                await this.sendPushSubscriptionToServer();
                await this.checkPushSubscriptionStatus();

                // Clear any stored subscription data
                this.removeStorageKey('push_subscription');
                
                // Update UI state
                this.updatePushNotificationButtonState();
                
                return true;
            } else {
                console.log('❌ Failed to unsubscribe from push notifications');
                return false;
            }
            
        } catch (error) {
            console.error('❌ Error unsubscribing from push notifications:', error);
            return false;
        }
    }

    async checkPushSubscriptionStatus() {
        try {            
            const serviceWorkerRegistration = await this.getServiceWorkerRegistration();
            if (!serviceWorkerRegistration) {
                this.pushhNotificationPermission = false;
                return false;
            }
            
            let isSubscribed = false;

            if (this.checkPushManagerSupported() && this.checkPushNotificationSupported()) {
                const pushSubscription = await serviceWorkerRegistration.pushManager.getSubscription();
                isSubscribed = !!pushSubscription;
                this.pushhNotificationPermission = isSubscribed;
                console.log('🔍 Push subscription status:', isSubscribed ? 'Subscribed' : 'Not subscribed');
            } else {
                this.pushhNotificationPermission = false;
            }
            
            // Update UI
            this.updatePushNotificationButtonState();
            
            return isSubscribed;
            
        } catch (error) {
            console.error('❌ Error checking push subscription status:', error);
            return false;
        }
    }

    async sendPushSubscriptionToServer(pushSubscription=null, validate=false) {
        /**
         * Send push subscription to server.
         * 
         * @param {Object|null} pushSubscription - The push subscription object
         * @param {boolean} validate - Whether to validate the subscription (default: false)
         *                              Best practice: Only validate when needed, not on every save
         */
        try {
            // Use configured API endpoint
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.SET_PUSH_SUBSCRIPTION'),
                options: {
                    method: 'POST',
                    body: JSON.stringify({
                        pushSubscription: pushSubscription,
                        validate: validate,  // Only validate when explicitly requested
                        ...this.getClientInfo()
                    })
                }
            });
            
            if (response.ok) {
                const result = await response.json();
                
                // Check if backend detected expiration (only if validation was requested)
                if (validate && result.expired === true) {
                    console.warn('⚠️ Backend detected subscription as expired');
                    // Subscription was expired, try to create a new one
                    if (Notification.permission === 'granted') {
                        console.log('📱 Attempting to create new subscription...');
                        const newSubscription = await this.subscribeToPushNotifications();
                        if (newSubscription) {
                            // Recursively send the new subscription (don't validate again to avoid loop)
                            return await this.sendPushSubscriptionToServer(newSubscription, false);
                        }
                    }
                } else if (validate && result.validated === true) {
                    console.log('✅ Subscription validated successfully by backend');
                }
            }
        } catch (error) {
            console.error('Error sending subscription to server:', error);
        }
    }

    urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, '+')
            .replace(/_/g, '/');

        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }
    
    async refreshToken() {
        try {
            // Use refresh token service to refresh tokens
            const success = await this.refreshTokenService.refreshTokens();
            
            if (success) {
                // Get the new token and update user info
                const newToken = await this.refreshTokenService.getAccessToken();
                
                // Parse and log the new token payload
                const payload = JwtService.parseJwtToken(newToken);
                if (payload) {
                    console.log('🔄 New JWT Token payload after refresh:', payload);
                    
                    // Update user info with new token data
                    if (this.currentUser) {
                        this.currentUser.allowedSections = payload.allowedSections || this.currentUser.allowedSections;
                        this.currentUser.tenantRefIds = payload.tenantRefIds || this.currentUser.tenantRefIds;
                        this.currentUser.role = payload.role || this.currentUser.role;
                        this.currentUser.refereeName = payload.refName || this.currentUser.refereeName;
                    } else {
                        // Create currentUser if it doesn't exist
                        this.currentUser = {
                            clientIdentifier: payload.clientIdentifier,
                            role: payload.role,
                            mobileNo: payload.mobileNo,
                            refereeName: payload.refName,
                            allowedSections: payload.allowedSections || [],
                            tenantRefIds: payload.tenantRefIds || {}
                        };
                    }
                    
                    // Update JWT info
                    this.jwtInfo = {
                        issuedAt: new Date(payload.iat * 1000),
                        expiresAt: new Date(payload.exp * 1000),
                        issuer: payload.iss
                    };
                    
                    // Refresh navigation visibility in case allowed sections changed
                    this.refreshSectionsVisibility();
                }
                
                return true;
            }
        } catch (error) {
            console.error('Token refresh failed:', error);
        }
        return false;
    }

    async sendPairMessage(preOpenedPairWindow = null) {
        console.log('🚀 Starting pair process...');
        let pairUrl = '';
        try {
            this.showPairStatus('שולח הודעת הזדהות...', 'info');
            
            const clientIdentifier = await this.getClientIdentifier();
            console.log('🔍 Current client unique idenitifier:', clientIdentifier);
            const sessionIdentifier = await this.getSessionIdentifier(true);
            console.log('🔍 Current session unique idenitifier:', sessionIdentifier);
            
            // Ensure we have a valid push subscription
            console.log('📱 Ensuring push subscription...');
            const pushSubscription = await this.ensurePushSubscription();
            console.log('📱 Push subscription result:', pushSubscription);

            if (false && !pushSubscription) {
                console.error('❌ Failed to get or create push subscription');
                this.showPairStatus('שגיאה: לא ניתן לקבל הרשאות התראות. אנא בדוק שהדפדפן תומך בהתראות', 'error');
                return;
            }

            if(!clientIdentifier) {
                console.error('❌ Failed to get client unique identifier');
                this.showPairStatus('שגיאה: לא ניתן לקבל הודעת הזדהות', 'error');
                return;
            }

            if(!sessionIdentifier) {
                console.error('❌ Failed to get session unique identifier');
                this.showPairStatus('שגיאה: לא ניתן לקבל הודעת הזדהות', 'error');
                return;
            }

            // Send pair message to FastAPI
            console.log('🌐 Sending pair request to FastAPI...');
            const response = await this.refreshTokenService.makeApiRequest({
                url:this.getConfig('ENDPOINTS.PAIR'),
                options:{
                    method: 'POST',
                    body: JSON.stringify({
                        action: 'הזדהות',
                        pushSubscription: pushSubscription,
                        ...this.getClientInfo()
                    })
                }
            });

            console.log('🌐 FastAPI response:', response);
            console.log('🌐 Response status:', response.status);

            if (response.ok) {
                const responseData = await response.json();
                console.log('✅ Pair successful:', responseData);
                const url = responseData.url;
                pairUrl = url;
                const isWhatsAppUrl = /^(https?:\/\/)?(wa\.me|api\.whatsapp\.com)\//i.test(url);
                // Copy URL to clipboard
                if (navigator.clipboard) {
                    navigator.clipboard.writeText(url).then(() => {
                        console.log('✅ Pair URL copied to clipboard:', url);
                    }).catch(err => {
                        console.error('Failed to copy to clipboard:', err);
                    });
                } else {
                }

                let launchedInPreOpenedWindow = false;
                if (preOpenedPairWindow && !preOpenedPairWindow.closed) {
                    try {
                        preOpenedPairWindow.location.href = url;
                        if (isWhatsAppUrl && preOpenedPairWindow.focus) {
                            preOpenedPairWindow.focus();
                        }
                        launchedInPreOpenedWindow = true;
                        console.log('✅ Pair URL loaded in pre-opened window');
                    } catch (windowError) {
                        console.error('❌ Failed to load pair URL in pre-opened window:', windowError);
                    }
                }

                if (!launchedInPreOpenedWindow) {
                    const fallbackWindow = window.open(url, 'pairWindow');
                    if (fallbackWindow) {
                        launchedInPreOpenedWindow = true;
                        if (isWhatsAppUrl && fallbackWindow.focus) {
                            fallbackWindow.focus();
                        }
                        console.log('✅ Pair URL loaded in fallback window');
                    }
                }

                if (!launchedInPreOpenedWindow && !isWhatsAppUrl) {
                    const existingPairIframe = document.getElementById('pairWindowHiddenIframe');
                    if (existingPairIframe) {
                        existingPairIframe.remove();
                    }

                    const hiddenPairIframe = document.createElement('iframe');
                    hiddenPairIframe.id = 'pairWindowHiddenIframe';
                    hiddenPairIframe.width = '1';
                    hiddenPairIframe.height = '1';
                    hiddenPairIframe.style.position = 'fixed';
                    hiddenPairIframe.style.right = '0';
                    hiddenPairIframe.style.bottom = '0';
                    hiddenPairIframe.style.opacity = '0.01';
                    hiddenPairIframe.style.pointerEvents = 'none';
                    hiddenPairIframe.style.border = '0';
                    hiddenPairIframe.style.zIndex = '-1';
                    hiddenPairIframe.onload = () => console.log('✅ Pair iframe loaded:', url);
                    hiddenPairIframe.onerror = (err) => console.error('❌ Pair iframe failed to load:', err);
                    hiddenPairIframe.src = url;
                    document.body.appendChild(hiddenPairIframe);
                    console.log('ℹ️ Pair URL fallback loaded in iframe');
                }

                if (!launchedInPreOpenedWindow && isWhatsAppUrl) {
                    window.location.href = url;
                    console.log('ℹ️ Pair WhatsApp URL loaded via top-level navigation fallback');
                }

                //this.showPairStatus('הודעת הזדהות נשלחה בהצלחה! בדוק את WhatsApp שלך', 'success');
                // Hide pair section after successful pair
                setTimeout(() => {
                    this.hidePairSection();
                }, 3000);
            } else {
                const errorData = await response.json();
                console.error('❌ Pair failed:', errorData);
                this.showPairStatus(`שגיאה: ${errorData.error || 'לא ניתן לשלוח הודעת הזדהות'}`, 'error');
            }
        } catch (error) {   
            console.error('💥 Pair error:', error);
            this.showPairStatus(`שגיאה: בעיה בחיבור לשרת ${error}ֿֿֿֿֿ\n${pairUrl}`, 'error');
        }
    }

    showPairStatus(message, type) {
        const statusElement = document.getElementById('pairStatus');
        statusElement.textContent = message;
        statusElement.className = `pair-status ${type}`;
    }

    hidePairSection() {
        // Login is now a section tab — nothing to hide
    }

    showPairSection() {
        this.navigateToSection('login');
    }

    async getCurrentPushSubscription() {
        try {
            console.log('🔍 Getting current push subscription...');
            
            if (!this.checkServiceWorkerSupported()) {
                return null;
            }
            
            if (!this.checkPushManagerSupported()) {
                return null;
            }
            
            console.log('📱 Service Worker and Push Manager supported, getting registration...');
            
            try {
                // Get service worker registration safely
                const serviceWorkerRegistration = await this.getServiceWorkerRegistration();
                console.log('📱 Service Worker registration:', serviceWorkerRegistration);
                
                if (!serviceWorkerRegistration) {
                    console.warn('⚠️ No service worker registration found');
                    return null;
                }
                
                console.log('📱 Getting push subscription from registration...');
                const pushSubscription = await serviceWorkerRegistration.pushManager.getSubscription();                
                console.log('📱 Push subscription result:', pushSubscription);
                
                if (pushSubscription) {
                    this.lastPushSubscriptionInvalid = 
                    this.lastPushSubscriptionNetworkError = 
                    this.lastPushSubscriptionPermissionDenied = 
                    this.lastPushSubscriptionServiceWorkerError = 
                    this.lastPushSubscriptionRevoked = pushSubscription;

                    console.log('✅ Push subscription found:', {
                        endpoint: pushSubscription.endpoint,
                        keys: pushSubscription.keys ? 'Present' : 'Missing'
                    });
                } else {
                    console.log('ℹ️ No existing push subscription found');
                }
                
                return pushSubscription;
            } catch (swError) {
                console.error('❌ Service worker error:', swError);
                if (swError.message.includes('timeout')) {
                    console.warn('⏰ Service worker registration timeout, push notifications unavailable');
                } else {
                    console.warn('⚠️ Service worker error, push notifications unavailable');
                }
                return null;
            }
        } catch (error) {
            console.error('❌ Error getting push subscription:', error);
            await this.handlePushSubscriptionError();
            return null;
        }
    }

    async ensurePushSubscription() {
        console.log('🔍 Ensuring push subscription exists...');
        
        // First try to get existing subscription
        let pushSubscription = await this.getCurrentPushSubscription();
        
        if (pushSubscription) {
            console.log('✅ Existing push subscription found');
            return pushSubscription;
        }
        
        console.log('📱 No existing subscription, creating new one...');
        
        // If no subscription exists, create one
        pushSubscription = await this.subscribeToPushNotifications();
        
        if (pushSubscription) {
            console.log('✅ New push subscription created successfully');
            return pushSubscription;
        } else {
            console.error('❌ Failed to create push subscription');
            return null;
        }
    }

    async checkServiceWorkerStatus() {
        console.log('🔍 Checking service worker status...');
        
        if (!this.checkServiceWorkerSupported()) {
            return { supported: false, registered: false, active: false, version: 'N/A' };
        }
        
        try {
            const registration = await this.getServiceWorkerRegistration();
            const isActive = registration.active !== null;
            
            // Get version from service worker
            let version = 'Unknown';
            try {
                // Try to get version from the service worker script
                const swResponse = await fetch('/js/refportal-sw.js?_t=' + Date.now(), { cache: 'no-cache' });
                if (swResponse.ok) {
                    const swContent = await swResponse.text();
                    const versionMatch = swContent.match(/const CACHE_VERSION = ['"`]([^'"`]+)['"`]/);
                    if (versionMatch) {
                        version = versionMatch[1];
                    }
                }
            } catch (versionError) {
                console.warn('⚠️ Could not fetch service worker version:', versionError);
            }
            
            console.log('📱 Service Worker status:', {
                supported: true,
                registered: true,
                active: isActive,
                scope: registration.scope,
                version: version,
                state: registration.active ? 'Active' : 'Installing'
            });
            
            return {
                supported: true,
                registered: true,
                active: isActive,
                scope: registration.scope,
                version: version
            };
        } catch (error) {
            console.error('❌ Error checking service worker status:', error);
            return { supported: true, registered: false, active: false, version: 'Error', error: error.message };
        }
    }
    
    getStorageKey(key) {
        return localStorage.getItem(key=key) || sessionStorage.getItem(key=key) || null;
    }

    setStorageKey(key, value) {
        localStorage.setItem(key=key, value=value);
        sessionStorage.setItem(key=key, value=value);
    }

    removeStorageKey(key) {
        localStorage.removeItem(key=key);
        sessionStorage.removeItem(key=key);
    }

    // Cache management functions
    async clearAllCaches() {
        console.log('🧹 Clearing all caches...');
        
        try {
            // Clear browser caches
            if ('caches' in window) {
                const cacheNames = await caches.keys();
                await Promise.all(
                    cacheNames.map(cacheName => {
                        console.log('🗑️ Deleting cache:', cacheName);
                        return caches.delete(cacheName);
                    })
                );
                console.log('✅ Browser caches cleared');
            }
            
            // Clear service worker caches
            if (navigator.serviceWorker && navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_CACHE' });
                console.log('✅ Service worker cache clear message sent');
            }
            
            // Clear localStorage and sessionStorage
            localStorage.clear();
            sessionStorage.clear();
            console.log('✅ Local storage cleared');
            
            this.showToast('Cache cleared successfully', 'success');
            
        } catch (error) {
            console.error('❌ Error clearing caches:', error);
            this.showToast('Error clearing cache', 'error');
        }
    }
    
    async refreshJavaScriptFiles() {
        console.log('🔄 Refreshing JavaScript files...');
        
        try {
            if (navigator.serviceWorker && navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({ type: 'REFRESH_JS_FILES' });
                console.log('✅ JavaScript refresh message sent to service worker');
                
                // Force reload the page to get fresh JS files
                setTimeout(() => {
                    console.log('🔄 Reloading page to get fresh JavaScript files...');
                    window.location.reload(true);
                }, 1000);
            } else {
                // Fallback: force reload
                console.log('🔄 Service worker not available, forcing page reload...');
                window.location.reload(true);
            }
            
        } catch (error) {
            console.error('❌ Error refreshing JavaScript files:', error);
            this.showToast('Error refreshing JavaScript files', 'error');
        }
    }
    
    // Force reload with cache bypass
    forceReload() {
        console.log('🔄 Force reloading page...');
        
        // Clear caches first
        this.clearAllCaches().then(() => {
            // Force reload bypassing cache
            window.location.reload(true);
        });
    }
    
    // Nuclear option: completely bypass all caching
    async nuclearRefresh() {
        console.log('☢️ Nuclear refresh - bypassing ALL caching...');
        
        try {
            // Clear all caches
            await this.clearAllCaches();
            
            // Unregister service worker to force fresh start
            if (this.checkServiceWorkerSupported()) {
                const registrations = await navigator.serviceWorker.getRegistrations();
                for (let registration of registrations) {
                    await registration.unregister();
                    console.log('🗑️ Service worker unregistered');
                }
            }
            
            // Clear all storage
            localStorage.clear();
            sessionStorage.clear();
            
            // Force reload with cache bypass
            console.log('🔄 Reloading with complete cache bypass...');
            window.location.reload(true);
            
        } catch (error) {
            console.error('❌ Error in nuclear refresh:', error);
            // Fallback to simple reload
            window.location.reload(true);
        }
    }
    
    // Force service worker update
    async forceServiceWorkerUpdate() {
        console.log('🔄 Forcing service worker update...');
        
        try {
            if (this.checkServiceWorkerSupported()) {
                const registration = await this.getServiceWorkerRegistration();
                
                // Send message to service worker to skip waiting
                if (registration.waiting) {
                    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
                    console.log('📤 Skip waiting message sent to service worker');
                }
                
                // Force update check
                await registration.update();
                console.log('✅ Service worker update check completed');
                
                // Reload after a short delay to ensure update is applied
                setTimeout(() => {
                    console.log('🔄 Reloading to apply service worker update...');
                    window.location.reload();
                }, 2000);
                
            } else {
                console.warn('⚠️ Service Worker not supported');
            }
        } catch (error) {
            console.error('❌ Error forcing service worker update:', error);
        }
    }

    async handlePushNotification(data) {
        try {
            const d = data.data || {};
            const silentRaw = d.silent;
            const silent =
                silentRaw === true ||
                silentRaw === 1 ||
                (typeof silentRaw === 'string' &&
                    ['true', '1', 'yes', 'on'].includes(silentRaw.trim().toLowerCase()));
            const titleTrim = d.title != null ? String(d.title).trim() : '';
            if (
                silent ||
                d.tag === 'subscription-validation' ||
                !titleTrim
            ) {
                this.jwtWebSocket.sendLog('INFO', { pushSuppressed: true, ...d });
                return;
            }

            // Show notification
            this.jwtWebSocket.sendLog('INFO', data.data);
            if (this.pushhNotificationPermission) {
                const receivedNotification = new Notification(titleTrim, {
                    body: data.data['body'],
                    icon: '../images/RefereeX.png',
                    data: data.data,
                    requireInteraction: data.data['requireInteraction'] || false,
                    lang: data.data['lang'] || 'he-IL',
                    dir: data.data['dir'] || 'rtl',
                    silent: data.data['silent'] || false,
                    vibrate: data.data['vibrate'] || [200, 100, 200],
                    actions: data.data['actions'] || [],
                    badge: data.data['badge'] || '../images/RefereeX.png',
                    tag: data.data['tag'] || 'refereex-notification',
                });

                receivedNotification.onclick = () => {
                    this.showToast(titleTrim || data.data['url'], 'info');
                    if (data.data['url']) {
                        window.open(data.data['url'], '_blank');
                    }
                    receivedNotification.close();
                };
            }

            // Show toast
            this.showToast(titleTrim || data.data['body'], 'info');

            // Add to chat if it's a chat message
            if (data.data['type'] === 'chat') {
                this.addChatM
                essage('received', data.data['body']);
            }
        } catch (error) {
            console.error('❌ Error handling push notification:', error);
        }
    }

    showToast(message, type = 'info', timeout = 2500) {
        const toast = document.getElementById('notificationToast');
        const toastMessage = document.getElementById('toastMessage');
        
        if (!toast || !toastMessage) {
            console.warn('Toast elements not found, falling back to console log');
            console.log(`Toast (${type}): ${message}`);
            return;
        }
        
        toastMessage.textContent = message;
        
        // Set color based on type
        switch (type) {
            case 'success':
                toast.style.background = '#10b981';
                break;
            case 'error':
                toast.style.background = '#ef4444';
                break;
            case 'warning':
                toast.style.background = '#f59e0b';
                break;
            default:
                toast.style.background = '#3b82f6';
        }
        
        // Ensure toast is visible above modals / install prompt / splash
        toast.style.zIndex = '10100';
        toast.classList.add('show');
        
        // Auto hide after 5 seconds
        setTimeout(() => {
            this.hideToast();
        }, timeout);
    }

    hideToast() {
        const toast = document.getElementById('notificationToast');
        if (toast) {
            toast.classList.remove('show');
        }
    }

    showModalToast(message, type = 'info') {
        // Create a temporary toast notification that works in modal contexts
        const existingToast = document.getElementById('modalToast');
        if (existingToast) {
            existingToast.remove();
        }
        
        const toast = document.createElement('div');
        toast.id = 'modalToast';
        toast.className = 'modal-toast';
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${this.getToastColor(type)};
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            z-index: 10100;
            max-width: 300px;
            font-size: 14px;
            font-weight: 500;
            transform: translateX(100%);
            transition: transform 0.3s ease;
            pointer-events: auto;
        `;
        
        toast.textContent = message;
        document.body.appendChild(toast);
        
        // Trigger animation
        setTimeout(() => {
            toast.style.transform = 'translateX(0)';
        }, 10);
        
        // Auto hide after 5 seconds
        setTimeout(() => {
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }, 5000);
    }

    getToastColor(type) {
        switch (type) {
            case 'success':
                return '#10b981';
            case 'error':
                return '#ef4444';
            case 'warning':
                return '#f59e0b';
            default:
                return '#3b82f6';
        }
    }

    showInstallPrompt() {
        const el = document.getElementById('installPrompt');
        if (!el || this.isPWAInstalled()) return;
        el.style.display = '';
        el.classList.add('show');
    }

    hideInstallPrompt() {
        const el = document.getElementById('installPrompt');
        if (!el) return;
        el.classList.remove('show');
    }

    showInstallInstructionsModal() {
        this.removeInstallInstructionsModal();

        const profile = getPWAClientProfile();
        const { title, steps } = getHebrewInstallInstructions(profile);

        const overlay = document.createElement('div');
        overlay.id = 'installInstructionsOverlay';
        overlay.className = 'install-instructions-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');

        const dialog = document.createElement('div');
        dialog.className = 'install-instructions-dialog';

        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'install-instructions-dismiss';
        close.setAttribute('aria-label', 'סגור');
        close.innerHTML = '×';

        const heading = document.createElement('h3');
        heading.textContent = title;

        const list = document.createElement('ol');
        steps.forEach((text) => {
            const li = document.createElement('li');
            li.textContent = text;
            list.appendChild(li);
        });

        const onClose = () => {
            this.removeInstallInstructionsModal();
        };

        close.addEventListener('click', onClose);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) onClose();
        });

        dialog.appendChild(close);
        dialog.appendChild(heading);
        dialog.appendChild(list);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
    }

    removeInstallInstructionsModal() {
        document.getElementById('installInstructionsOverlay')?.remove();
    }

    async installPWA() {
        if (this.deferredPrompt) {
            this.deferredPrompt.prompt();
            const { outcome } = await this.deferredPrompt.userChoice;

            if (outcome === 'accepted') {
                this.showToast('האפליקציה הותקנה בהצלחה!', 'success');
            }

            this.deferredPrompt = null;
            this.hideInstallPrompt();
            return;
        }

        this.hideInstallPrompt();
        this.showInstallInstructionsModal();
    }

    viewGameDetails(gameId, gameUrl) {
        this.showToast(`פרטי משחק ${gameId} יוצגו בקרוב`, 'info');
        this.windowManager.openWindow(`gameDetails_${gameId}`, gameUrl);
        // Implement game details view
    }

    formatWindowOptions(options = {}) {
        const defaultOptions = {
            width: 800,
            height: 600,
            left: 100,
            top: 100,
            scrollbars: 'yes',
            resizable: 'yes',
            status: 'yes',
            toolbar: 'no',
            menubar: 'no',
            location: 'no'
        };
        
        const mergedOptions = { ...defaultOptions, ...options };
        
        return Object.entries(mergedOptions)
            .map(([key, value]) => `${key}=${value}`)
            .join(',');
    }

    // Utility methods
    formatDate(date) {
        if (!date) return 'תאריך לא ידוע';
        
        try {
            const dateObj = new Date(date);
            
            if (isNaN(dateObj.getTime())) {
                return date;
            }
            
            const day = dateObj.getDate().toString().padStart(2, '0');
            const month = (dateObj.getMonth() + 1).toString().padStart(2, '0');
            const year = dateObj.getFullYear();
            
            return `${day}/${month}/${year}`;
            
        } catch (error) {
            console.warn('Error formatting date:', error);
            return date;
        }
    }

    formatTime(time) {
        if (!time) return 'שעה לא ידועה';
        
        try {
            const timeObj = new Date(time);
            
            if (isNaN(timeObj.getTime())) {
                return time;
            }
            
            return timeObj.toLocaleTimeString('he-IL', { 
                hour: '2-digit', 
                minute: '2-digit',
                hour12: false
            });
            
        } catch (error) {
            console.warn('Error formatting time:', error);
            return time;
        }
    }

    /**
     * Adjust font size of element to fit within its container
     * @param {HTMLElement} element - The element to adjust
     */
    adjustElementFontSize(element) {
        if (!element) return;
        
        try {
            // Reset to default font size
            const defaultFontSize = this.getDefaultFontSize();
            element.style.fontSize = defaultFontSize;
            
            // Get container dimensions
            const container = element.parentElement;
            if (!container) return;
            
            const containerWidth = container.offsetWidth;
            const containerHeight = container.offsetHeight;
            
            // Minimum font sizes for different screen sizes
            const minFontSize = this.getMinFontSize();
            
            // Check if text fits at current size
            if (this.isTextOverflowing(element, containerWidth, containerHeight)) {
                // Binary search for optimal font size
                let fontSize = this.findOptimalFontSize(element, containerWidth, containerHeight, minFontSize);
                element.style.fontSize = fontSize;
            }
            
        } catch (error) {
            console.warn('Error adjusting title font size:', error);
        }
    }

    /**
     * Get default font size based on screen size
     * @returns {string} Default font size
     */
    getDefaultFontSize() {
        const width = window.innerWidth;
        
        if (width <= 480) {
            return '0.75rem'; // Mobile
        } else if (width <= 768) {
            return '0.8rem';  // Tablet
        } else {
            return '0.7rem';  // Desktop
        }
    }

    /**
     * Get minimum font size based on screen size
     * @returns {number} Minimum font size in rem
     */
    getMinFontSize() {
        const width = window.innerWidth;
        
        if (width <= 480) {
            return 0.5; // Mobile
        } else if (width <= 768) {
            return 0.6; // Tablet
        } else {
            return 0.4; // Desktop
        }
    }

    /**
     * Check if text is overflowing the container
     * @param {HTMLElement} element - The element to check
     * @param {number} maxWidth - Maximum allowed width
     * @param {number} maxHeight - Maximum allowed height
     * @returns {boolean} True if overflowing
     */
    isTextOverflowing(element, maxWidth, maxHeight) {
        const rect = element.getBoundingClientRect();
        const computedStyle = window.getComputedStyle(element);
        
        // Account for padding and margins
        const paddingLeft = parseFloat(computedStyle.paddingLeft) || 0;
        const paddingRight = parseFloat(computedStyle.paddingRight) || 0;
        const marginLeft = parseFloat(computedStyle.marginLeft) || 0;
        const marginRight = parseFloat(computedStyle.marginRight) || 0;
        
        const totalWidth = rect.width + paddingLeft + paddingRight + marginLeft + marginRight;
        const totalHeight = rect.height;
        
        return totalWidth > maxWidth || totalHeight > maxHeight;
    }

    /**
     * Find optimal font size using binary search
     * @param {HTMLElement} element - The element to adjust
     * @param {number} maxWidth - Maximum allowed width
     * @param {number} maxHeight - Maximum allowed height
     * @param {number} minFontSize - Minimum font size
     * @returns {string} Optimal font size in rem
     */
    findOptimalFontSize(element, maxWidth, maxHeight, minFontSize) {
        const maxFontSize = parseFloat(this.getDefaultFontSize());
        let low = minFontSize;
        let high = maxFontSize;
        let bestSize = minFontSize;
        
        // Binary search for optimal size
        while (high - low > 0.01) {
            const mid = (low + high) / 2;
            element.style.fontSize = `${mid}rem`;
            
            if (this.isTextOverflowing(element, maxWidth, maxHeight)) {
                high = mid;
            } else {
                bestSize = mid;
                low = mid;
            }
        }
        
        return `${bestSize}rem`;
    }

    // Handle notification navigation action
    async handleNotificationNavigation(data) {
        console.log('🔘 Handling notification navigation:', data);
        
        const { section, data: notificationData } = data;
        
        if (section) {
            if (!this.isAuthenticated && (section === 'games' || section === 'reviews')) {
                console.log('🔘 Navigation requires login:', section);
                await this.navigateToSection('login');
                const hint =
                    section === 'games'
                        ? 'התחבר/י כדי לצפות בשיבוצים'
                        : 'התחבר/י כדי לצפות בביקורות';
                this.showToast(hint, 'info');
                return;
            }
            console.log(`🔘 Navigating to section: ${section}`);
            await this.navigateToSection(section);
            
            // Show toast about the navigation
            this.showToast(`עברתי ל-${this.getSectionDisplayName(section)}`, 'info');
            
            // Handle specific section actions
            if (section === 'chat' && notificationData.messageId) {
                this.scrollToMessage(notificationData.messageId);
            } else if (section === 'dashboard' && notificationData.highlight) {
                this.highlightDashboardElement(notificationData.highlight);
            }
        }
    }

    // Handle notification pair action
    async handleNotificationPair(data) {
        console.log('🔘 Handling notification pair action:', data);
        
        // Navigate to pair section
        await this.navigateToSection('pair');
        
        // Show pair prompt
        this.showToast('התחבר למערכת כדי להמשיך', 'info');
        
        // Pre-fill any data from notification if available
        if (data.mobileNumber) {
            // You could pre-fill a mobile number field if you have one
            console.log('📱 Pre-filling mobile number from notification:', data.mobileNumber);
        }
    }

    // Handle notification chat action
    async handleNotificationChat(data) {
        console.log('🔘 Handling notification chat action:', data);
        
        // Navigate to chat section
        await this.navigateToSection('chat');
        
        // Show chat prompt
        this.showToast('צ\'אט נפתח', 'info');
        
        // Handle specific chat actions
        if (data.messageId) {
            this.scrollToMessage(data.messageId);
        } else if (data.autoMessage) {
            this.addChatMessage('system', data.autoMessage);
        }
    }

    // Helper method to get section display name in Hebrew
    getSectionDisplayName(section) {
        const sectionNames = {
            'dashboard': 'לוח הבקרה',
            'games': 'שיבוצים',
            'reviews': 'ביקורות',
            'publicTables': 'טבלאות',
            'publicGames': 'משחקים',
            'fields': 'מגרשים',
            'availability': 'זמינות',
            'documents': 'מסמכים',
            'rules': 'חוקה',
            'chat': 'צ\'אט',
            'pair': 'התחברות',
            'settings': 'הגדרות',
            'profile': 'פרופיל'
        };
        return sectionNames[section] || section;
    }

    // Helper method to scroll to specific message in chat
    scrollToMessage(messageId) {
        const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
        if (messageElement) {
            messageElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
            messageElement.classList.add('highlight-message');
            setTimeout(() => {
                messageElement.classList.remove('highlight-message');
            }, 3000);
        }
    }

    // Helper method to highlight dashboard element
    highlightDashboardElement(elementId) {
        const element = document.getElementById(elementId);
        if (element) {
            element.classList.add('highlight-dashboard-element');
            setTimeout(() => {
                element.classList.remove('highlight-dashboard-element');
            }, 3000);
        }
    }

    // Method to manually show install prompt again
    showInstallPromptAgain() {
        this.removeStorageKey('installPromptDismissed');
        if (this.isPWAInstalled()) {
            this.showToast('האפליקציה כבר מותקנת', 'info');
            return;
        }
        this.showInstallPrompt();
    }

    // Method to check install prompt status
    getInstallPromptStatus() {
        const isInstalled = this.isPWAInstalled();
        const canInstall = this.checkServiceWorkerSupported() && this.checkPushManagerSupported();
        const hasPrompt = !!this.deferredPrompt;
        const dismissedTime = this.getStorageKey('installPromptDismissed');
        const dismissedRecently = this.isInstallBannerDismissedRecently();

        return {
            isInstalled,
            canInstall,
            hasPrompt,
            dismissedTime: dismissedTime ? new Date(parseInt(dismissedTime, 10)) : null,
            canShowPrompt: !isInstalled && !dismissedRecently
        };
    }

    // Method to reset install prompt preferences
    resetInstallPromptPreferences() {
        this.removeStorageKey('installPromptDismissed');
        this.deferredPrompt = null;
        this.showToast('העדפות ההתקנה אופסו', 'success');
        
        // Check if we can show the prompt again
        setTimeout(() => {
            const status = this.getInstallPromptStatus();
            console.log('🔄 Install Prompt Status after reset:', status);
        }, 1000);
    }

    // Merge and deduplicate chat messages
    mergeChatMessages(newMessages) {
        const existingIds = new Set(this.chatMessages.map(msg => msg.id));
        const messagesToAdd = [];
        
        newMessages.forEach(newMsg => {
            if (!existingIds.has(newMsg.id)) {
                messagesToAdd.push(newMsg);
                existingIds.add(newMsg.id);
            }
        });
        
        if (messagesToAdd.length > 0) {
            // Add new messages
            this.chatMessages.push(...messagesToAdd);
            
            // Sort messages by timestamp to maintain chronological order
            this.chatMessages.sort((a, b) => a.id - b.id);
            
            // Keep only last 100 messages to prevent memory issues
            if (this.chatMessages.length > 100) {
                this.chatMessages = this.chatMessages.slice(-100);
            }
            
            // Update last message ID
            this.lastMessageId = Math.max(...this.chatMessages.map(msg => msg.id));
            
            return true; // Messages were added
        }
        
        return false; // No new messages
    }

    // Resolve chat message conflicts (when same message ID exists with different content)
    resolveMessageConflicts() {
        const messageGroups = new Map();
        
        // Group messages by ID
        this.chatMessages.forEach(msg => {
            if (!messageGroups.has(msg.id)) {
                messageGroups.set(msg.id, []);
            }
            messageGroups.get(msg.id).push(msg);
        });
        
        // Resolve conflicts by keeping the most recent version
        this.chatMessages = Array.from(messageGroups.values()).map(group => {
            if (group.length === 1) {
                return group[0];
            } else {
                // Multiple messages with same ID - keep the one with latest timestamp
                return group.reduce((latest, current) => {
                    return new Date(current.timestamp) > new Date(latest.timestamp) ? current : latest;
                });
            }
        });
        
        // Sort by ID to maintain order
        this.chatMessages.sort((a, b) => a.id - b.id);
    }

    // Export chat messages for backup or transfer
    exportChatMessages() {
        try {
            const exportData = {
                messages: this.chatMessages,
                exportDate: new Date().toISOString(),
                clientIdentifier: this.getClientIdentifier(),
                totalMessages: this.chatMessages.length
            };
            
            const dataStr = JSON.stringify(exportData, null, 2);
            const dataBlob = new Blob([dataStr], { type: 'application/json' });
            
            const link = document.createElement('a');
            link.href = URL.createObjectURL(dataBlob);
            link.download = `refportal_chat_export_${new Date().toISOString().split('T')[0]}.json`;
            link.click();
            
            URL.revokeObjectURL(link.href);
            console.log('✅ Chat messages exported successfully');
        } catch (error) {
            console.error('❌ Error exporting chat messages:', error);
        }
    }

    // Import chat messages from backup
    async importChatMessages(file) {
        try {
            const text = await file.text();
            const importData = JSON.parse(text);
            
            if (importData.messages && Array.isArray(importData.messages)) {
                // Merge imported messages with existing ones
                const wasUpdated = this.mergeChatMessages(importData.messages);
                
                if (wasUpdated) {
                    // Resolve any conflicts
                    this.resolveMessageConflicts();
                    
                    // Update display and storage
                    this.displayChatMessages();
                    this.storeAllChatMessagesLocally();
                    
                    console.log('✅ Chat messages imported successfully');
                    this.showToast('הודעות הצ\'אט יובאו בהצלחה', 'success');
                } else {
                    console.log('ℹ️ No new messages to import');
                    this.showToast('לא היו הודעות חדשות לייבא', 'info');
                }
            } else {
                throw new Error('Invalid import file format');
            }
        } catch (error) {
            console.error('❌ Error importing chat messages:', error);
            this.showToast('שגיאה בייבוא הודעות הצ\'אט', 'error');
        }
    }

    // Show chat sync status
    showChatSyncStatus(message, type = 'info', duration = 3000) {
        const statusElement = document.getElementById('chatSyncStatus');
        const statusText = document.getElementById('chatSyncStatusText');
        
        if (statusElement && statusText) {
            // Remove existing classes
            statusElement.classList.remove('syncing', 'success', 'error');
            
            // Add new class based on type
            if (type === 'syncing') {
                statusElement.classList.add('syncing');
            } else if (type === 'success') {
                statusElement.classList.add('success');
            } else if (type === 'error') {
                statusElement.classList.add('error');
            }
            
            // Update text and show
            statusText.textContent = message;
            statusElement.classList.add('show');
            
            // Auto-hide after duration
            setTimeout(() => {
                statusElement.classList.remove('show');
            }, duration);
        }
    }

    // Update chat sync status based on current state
    updateChatSyncStatus(forceShow = false) {
        if (!this.isOnline) {
            this.showChatSyncStatus('מצב אופליין - סנכרון מושהה', 'error', 5000);
        } else if (this.chatSyncEnabled && this.chatSyncInterval) {
            // Only show "sync active" message if we were offline or if forced
            if (this.wasOffline || forceShow) {
                this.showChatSyncStatus('סנכרון פעיל', 'success', 2000);
            }
        } else if (this.chatSyncEnabled) {
            this.showChatSyncStatus('סנכרון מוכן', 'info', 2000);
        } else {
            this.showChatSyncStatus('סנכרון מושבת', 'error', 2000);
        }
    }

    // Add offline indicator to chat
    addChatOfflineIndicator() {
        const chatContainer = document.querySelector('.chat-container');
        if (chatContainer && !document.getElementById('chatOfflineIndicator')) {
            const offlineIndicator = document.createElement('div');
            offlineIndicator.id = 'chatOfflineIndicator';
            offlineIndicator.className = 'chat-offline-indicator';
            offlineIndicator.innerHTML = '📴 מצב אופליין - הודעות יישמרו מקומית ויסונכרנו כשתחזור לרשת';
            
            // Insert at the top of chat container
            chatContainer.insertBefore(offlineIndicator, chatContainer.firstChild);
        }
    }

    // Remove offline indicator from chat
    removeChatOfflineIndicator() {
        const offlineIndicator = document.getElementById('chatOfflineIndicator');
        if (offlineIndicator) {
            offlineIndicator.remove();
        }
    }

    // Enhanced online/offline handling for chat
    setupOnlineStatusHandling() {
        window.addEventListener('online', () => {
            this.isOnline = true;
            console.log('🌐 Device is online');
            
            // Remove offline indicator
            this.removeChatOfflineIndicator();
            
            // Resume chat sync when coming back online
            if (this.chatSyncEnabled) {
                this.startChatSync();
                // Fetch any missed messages
                this.fetchChatMessagesFromServer();
                // Start real-time updates
                this.startRealTimeChatUpdates();
            }
            
            // Update sync status - only show sync active message if we were offline
            if (this.wasOffline) {
                this.updateChatSyncStatus();
            }
        });

        window.addEventListener('offline', () => {
            // Add offline indicator
            this.addChatOfflineIndicator();
            
            // Stop chat sync when offline
            this.stopChatSync();
            this.stopRealTimeChatUpdates();
            
            // Update sync status
            this.updateChatSyncStatus();
        });
    }



    // Auto-hide functionality for chat sections
    initAutoHideSections() {
        console.log('🚀 Initializing auto-hide sections...');
        
        // Debug: Check if sections exist
        const chatActions = document.getElementById('chatActions');
        const chatSyncControls = document.getElementById('chatSyncControls');
        
        console.log('🔍 chatActions element found:', !!chatActions);
        console.log('🔍 chatSyncControls element found:', !!chatSyncControls);
        
        if (chatActions) {
            console.log('🔍 chatActions current classes:', chatActions.classList.toString());
            console.log('🔍 chatActions HTML:', chatActions.outerHTML.substring(0, 200) + '...');
        }
        if (chatSyncControls) {
            console.log('🔍 chatSyncControls current classes:', chatSyncControls.classList.toString());
            console.log('🔍 chatSyncControls HTML:', chatSyncControls.outerHTML.substring(0, 200) + '...');
        }
        
        // Initialize auto-hide for chat sections
        this.setupAutoHideSection('chatActions');
        this.setupAutoHideSection('chatSyncControls');
        
        // Load saved pin states
        this.loadPinStates();
        
        // Ensure all sections have proper appearance
        this.adjustSectionAppearance('chatActions');
        this.adjustSectionAppearance('chatSyncControls');
        
        console.log('✅ Auto-hide sections initialized');
    }

    setupAutoHideSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (!section) {
            console.warn(`⚠️ Section not found: ${sectionId}`);
            return;
        }

        console.log(`🔧 Setting up auto-hide for section: ${sectionId}`);
        
        // Don't add auto-hide class immediately - wait for timer
        // section.classList.add('auto-hide');
        
        // Don't start auto-hide timer immediately - wait for user interaction
        // this.startAutoHideTimer(sectionId);
        
        console.log(`🔧 Auto-hide setup complete for ${sectionId} - timer will start on mouse leave`);
    }

    startAutoHideTimer(sectionId) {
        const section = document.getElementById(sectionId);
        if (!section) return;

        // Don't start auto-hide timer if chat section is active
        if (sectionId === 'chatActions' || sectionId === 'chatSyncControls') {
            if (this.currentSection !== 'chat') {
                console.log(`📱 Skipping auto-hide timer for ${sectionId} (chat section is active)`);
                return;
            }
        }

        // Clear existing timer
        if (this.autoHideTimers && this.autoHideTimers[sectionId]) {
            clearTimeout(this.autoHideTimers[sectionId]);
        }

        // Initialize timers object if it doesn't exist
        if (!this.autoHideTimers) {
            this.autoHideTimers = {};
        }

        console.log(`⏰ Starting auto-hide timer for ${sectionId} (10 seconds)`);
        console.log(`🔍 Section ${sectionId} current classes:`, section.classList.toString());

        // Start auto-hide timer (10 seconds for better UX)
        this.autoHideTimers[sectionId] = setTimeout(() => {
            console.log(`⏰ Timer fired for ${sectionId}`);
            
            // Double-check that chat section is not active before applying auto-hide
            if (sectionId === 'chatActions' || sectionId === 'chatSyncControls') {
            if (this.currentSection !== 'chat') {
                    console.log(`📱 Timer fired but chat section is active, skipping auto-hide for ${sectionId}`);
                    return;
                }
            }
            
            if (!this.isSectionPinned(sectionId)) {
                console.log(`🎭 Adding auto-hide class to ${sectionId}`);
                section.classList.add('auto-hide');
                
                // Debug: Check if class was added
                console.log(`🔍 Section ${sectionId} classes after auto-hide:`, section.classList.toString());
                console.log(`🔍 Section ${sectionId} has auto-hide class:`, section.classList.contains('auto-hide'));
                
                // Force a reflow to ensure CSS is applied
                section.offsetHeight;
                
                // Check computed styles
                const computedStyle = window.getComputedStyle(section);
                console.log(`🎨 Computed opacity for ${sectionId}:`, computedStyle.opacity);
                console.log(`🎨 Computed transform for ${sectionId}:`, computedStyle.transform);
            } else {
                console.log(`📌 Section ${sectionId} is pinned, skipping auto-hide`);
            }

            this.adjustSectionAppearance(sectionId);
        }, 2000);
        
        console.log(`⏰ Timer set for ${sectionId}, ID:`, this.autoHideTimers[sectionId]);
    }

    resetAutoHideTimer(sectionId) {
        const section = document.getElementById(sectionId);
        if (!section) return;

        // Remove auto-hide class
        section.classList.remove('auto-hide');
        
        // Restart timer
        this.startAutoHideTimer(sectionId);
    }

    togglePinSection(sectionId) {
        const section = document.getElementById(sectionId);
        // Fix pin button ID mapping to match HTML
        let pinBtnId;
        if (sectionId === 'chatActions') {
            pinBtnId = 'pinChatActions';
        } else if (sectionId === 'chatSyncControls') {
            pinBtnId = 'pinChatSyncControls';
        } else {
            pinBtnId = `pin${sectionId.charAt(0).toUpperCase() + sectionId.slice(1)}`;
        }
        
        const pinBtn = document.getElementById(pinBtnId);
        
        if (!section || !pinBtn) {
            console.warn(`⚠️ Section or pin button not found: ${sectionId} -> ${pinBtnId}`);
            return;
        }

        const isPinned = this.isSectionPinned(sectionId);
        
        if (isPinned) {
            // Unpin section
            this.unpinSection(sectionId);
        } else {
            // Pin section
            this.pinSection(sectionId);
        }
    }

    pinSection(sectionId) {
        const section = document.getElementById(sectionId);
        // Fix pin button ID mapping to match HTML
        let pinBtnId;
        if (sectionId === 'chatActions') {
            pinBtnId = 'pinChatActions';
        } else if (sectionId === 'chatSyncControls') {
            pinBtnId = 'pinChatSyncControls';
        } else {
            pinBtnId = `pin${sectionId.charAt(0).toUpperCase() + sectionId.slice(1)}`;
        }
        
        const pinBtn = document.getElementById(pinBtnId);
        
        if (!section || !pinBtn) {
            console.warn(`⚠️ Section or pin button not found: ${sectionId} -> ${pinBtnId}`);
            return;
        }

        // Add pinned class
        section.classList.add('pinned');
        pinBtn.classList.add('pinned');
        
        // Remove auto-hide
        section.classList.remove('auto-hide');
        
        // Save pin state
        this.savePinState(sectionId, true);
        
        // Clear auto-hide timer
        if (this.autoHideTimers && this.autoHideTimers[sectionId]) {
            clearTimeout(this.autoHideTimers[sectionId]);
        }
        
        // Adjust section appearance and chat messages size
        this.adjustSectionAppearance(sectionId);
        if (sectionId === 'chatActions' && this.currentSection === 'chat') {
            this.adjustChatMessagesSize();
        }
    }

    unpinSection(sectionId) {
        const section = document.getElementById(sectionId);
        // Fix pin button ID mapping to match HTML
        let pinBtnId;
        if (sectionId === 'chatActions') {
            pinBtnId = 'pinChatActions';
        } else if (sectionId === 'chatSyncControls') {
            pinBtnId = 'pinChatSyncControls';
        } else {
            pinBtnId = `pin${sectionId.charAt(0).toUpperCase() + sectionId.slice(1)}`;
        }
        
        const pinBtn = document.getElementById(pinBtnId);
        
        if (!section || !pinBtn) {
            console.warn(`⚠️ Section or pin button not found: ${sectionId} -> ${pinBtnId}`);
            return;
        }

        // Remove pinned class
        section.classList.remove('pinned');
        pinBtn.classList.remove('pinned');
        
        // Start auto-hide timer
        this.startAutoHideTimer(sectionId);
        
        // Save pin state
        this.savePinState(sectionId, false);
        
        // Adjust section appearance and chat messages size
        this.adjustSectionAppearance(sectionId);
        if (sectionId === 'chatActions' && this.currentSection === 'chat') {
            this.adjustChatMessagesSize();
        }
    }

    isSectionPinned(sectionId) {
        const section = document.getElementById(sectionId);
        return section && section.classList.contains('pinned');
    }

    savePinState(sectionId, isPinned) {
        try {
            const pinStates = JSON.parse(this.getStorageKey('chatSectionPinStates') || '{}');
            pinStates[sectionId] = isPinned;
            this.setStorageKey('chatSectionPinStates', value=JSON.stringify(pinStates));
        } catch (error) {
            console.error('Error saving pin state:', error);
        }
    }

    loadPinStates() {
        try {
            const pinStates = JSON.parse(this.getStorageKey('chatSectionPinStates') || '{}');
            
                    Object.keys(pinStates).forEach(sectionId => {
                if (pinStates[sectionId]) {
                    this.pinSection(sectionId);
                } else {
                    // Ensure unpinned sections have proper appearance
                    this.adjustSectionAppearance(sectionId);
                }
            });
        } catch (error) {
            console.error('Error loading pin states:', error);
        }
    }

    setupChatSectionEventListeners() {
        // Set up event listeners for chat actions section
        const chatActions = document.getElementById('chatActions');
        if (chatActions) {
            // Listen for mouse enter to show section temporarily
            chatActions.addEventListener('mouseenter', () => {
                console.log('🖱️ Mouse entered chatActions section');
                console.log(`🔍 chatActions pinned: ${this.isSectionPinned('chatActions')}`);
                console.log(`🔍 chatActions has auto-hide: ${chatActions.classList.contains('auto-hide')}`);
                
                if (!this.isSectionPinned('chatActions')) {
                    chatActions.classList.remove('auto-hide');
                    console.log('✅ Removed auto-hide class from chatActions');
                } else {
                    console.log('📌 chatActions is pinned, keeping current state');
                }
            });
            
            // Listen for mouse leave to start auto-hide timer
            chatActions.addEventListener('mouseleave', () => {
                console.log('🖱️ Mouse left chatActions section');
                console.log(`🔍 chatActions pinned: ${this.isSectionPinned('chatActions')}`);
                console.log(`🔍 currentSection: ${this.currentSection}`);
                
                // Don't auto-hide if chat section is active or if pinned
                if (!this.isSectionPinned('chatActions') && this.currentSection === 'chat') {
                    console.log('⏰ Starting auto-hide timer for chatActions');
                    this.startAutoHideTimer('chatActions');
                } else {
                    console.log('📱 Skipping auto-hide for chatActions (section active or pinned)');
                }
            });
            
            console.log('✅ Chat actions auto-hide event listeners set up');
        }

        // Set up event listeners for chat sync controls section
        const chatSyncControls = document.getElementById('chatSyncControls');
        if (chatSyncControls) {
            // Listen for mouse enter to show section temporarily
            chatSyncControls.addEventListener('mouseenter', () => {
                console.log('🖱️ Mouse entered chatSyncControls section');
                console.log(`🔍 chatSyncControls pinned: ${this.isSectionPinned('chatSyncControls')}`);
                console.log(`🔍 chatSyncControls has auto-hide: ${chatSyncControls.classList.contains('auto-hide')}`);
                
                if (!this.isSectionPinned('chatSyncControls')) {
                    chatSyncControls.classList.remove('auto-hide');
                    console.log('✅ Removed auto-hide class from chatSyncControls');
                } else {
                    console.log('📌 chatSyncControls is pinned, keeping current state');
                }
            });
            
            // Listen for mouse leave to start auto-hide timer
            chatSyncControls.addEventListener('mouseleave', () => {
                console.log('🖱️ Mouse left chatSyncControls section');
                console.log(`🔍 chatSyncControls pinned: ${this.isSectionPinned('chatSyncControls')}`);
                console.log(`🔍 currentSection: ${this.currentSection}`);
                
                // Don't auto-hide if chat section is active or if pinned
                if (!this.isSectionPinned('chatSyncControls') && this.currentSection === 'chat') {
                    console.log('⏰ Starting auto-hide timer for chatSyncControls');
                    this.startAutoHideTimer('chatSyncControls');
                } else {
                    console.log('📱 Skipping auto-hide for chatSyncControls (section active or pinned)');
                }
            });
            
            console.log('✅ Chat sync controls auto-hide event listeners set up');
        }
    }

    // Activate chat actions when chat section is active
    activateChatActions() {
        const chatActions = document.getElementById('chatActions');
        const chatSyncControls = document.getElementById('chatSyncControls');
        const chatMessages = document.getElementById('chatMessages');
        
        if (chatActions) {
            chatActions.classList.add('chat-section-active');
            // Remove auto-hide when chat section is active
            chatActions.classList.remove('auto-hide');
            console.log('✅ Chat actions activated, auto-hide removed');
        }
        
        if (chatSyncControls) {
            chatSyncControls.classList.add('chat-section-active');
            // Remove auto-hide when chat section is active
            chatSyncControls.classList.remove('auto-hide');
        }
        
        // Clear any auto-hide timers for chat sections
        if (this.autoHideTimers && this.autoHideTimers['chatActions']) {
            clearTimeout(this.autoHideTimers['chatActions']);
            this.autoHideTimers['chatActions'] = null;
            console.log('⏹️ Cleared auto-hide timer for chatActions');
        }
        
        if (this.autoHideTimers && this.autoHideTimers['chatSyncControls']) {
            clearTimeout(this.autoHideTimers['chatSyncControls']);
            this.autoHideTimers['chatSyncControls'] = null;
            console.log('⏹️ Cleared auto-hide timer for chatSyncControls');
        }
        
        // Adjust chat messages size based on pin status
        this.adjustChatMessagesSize();
    }

    // Deactivate chat actions when leaving chat section
    deactivateChatActions() {
        const chatActions = document.getElementById('chatActions');
        const chatSyncControls = document.getElementById('chatSyncControls');
        const chatMessages = document.getElementById('chatMessages');
        
        if (chatActions) {
            chatActions.classList.remove('chat-section-active');
            console.log('❌ Chat actions deactivated');
        }
        
        if (chatSyncControls) {
            chatSyncControls.classList.remove('chat-section-active');
        }
        
        // Reset chat messages size
        if (chatMessages) {
            chatMessages.classList.remove('chat-messages-expanded');
        }
    }

    // Adjust chat messages size based on pin status
    adjustChatMessagesSize() {
        const chatActions = document.getElementById('chatActions');
        const chatMessages = document.getElementById('chatMessages');
        
        if (!chatActions || !chatMessages) return;
        
        const isPinned = chatActions.classList.contains('pinned');
        
        if (!isPinned) {
            // When not pinned, expand chat messages
            chatMessages.classList.add('chat-messages-expanded');
            console.log('📱 Chat messages expanded (actions not pinned)');
        } else {
            // When pinned, use normal size
            chatMessages.classList.remove('chat-messages-expanded');
            console.log('📱 Chat messages normal size (actions pinned)');
        }
    }

    // Adjust section height and appearance based on pin status
    adjustSectionAppearance(sectionId) {
        const section = document.getElementById(sectionId);
        if (!section) return;
        
        const isPinned = this.isSectionPinned(sectionId);
        
        if (isPinned) {
            // When pinned, ensure full height and remove auto-hide effects
            section.classList.remove('auto-hide');
            section.style.height = 'auto';
            section.style.opacity = '1';
            section.style.transform = 'none';
            section.style.filter = 'none';
            section.style.pointerEvents = 'auto';
            console.log(`📌 Section ${sectionId} appearance adjusted for pinned state`);
        } else {
            // When unpinned, reset to default state
            section.style.height = 5;
            section.style.opacity = '';
            section.style.transform = '';
            section.style.filter = '';
            section.style.pointerEvents = '';
            console.log(`📌 Section ${sectionId} appearance reset for unpinned state`);
        }
    }

    // download ics file
    async downloadIcsFile(gameId) {
        try {
            console.log('🔄 Approving game assignment for game ID:', gameId);
            
            // Show loading state
            this.showToast('מוריד לוח משחקים...', 'info');
            
            const downloadEndpoint = this.getConfig('ENDPOINTS.DOWNLOADICSFILE', '/api/pwa/downloadIcsFile');
            const response = await this.refreshTokenService.makeApiRequest({
                url: `${downloadEndpoint}/${gameId}`,
                options: {
                    headers: {
                        Accept: 'text/calendar, application/json',
                    },
                },
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (!contentType.includes('text/calendar')) {
                throw new Error('Expected calendar file');
            }
            
            const blob = await response.blob();   
            // Create download link
            const downloadUrl = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = downloadUrl;
            const filename = 'calendar.ics'
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(downloadUrl);
            
            console.log('📅 Calendar downloaded successfully');
        } catch (error) {
            console.error('❌ Error download ics file:', error);
            this.showToast(`שגיאה בהורדת לוח משחקים: ${error.message}`, 'error');
        }
    }
    
    // Approve game assignment
    async approveGame(gameId) {
        try {
            console.log('🔄 Approving game assignment for game ID:', gameId);
            
            // Show loading state
            this.showToast('מאשר שיבוץ...', 'info');
            
            // Prepare request data
            const requestData = {
                gameId: gameId,
                action: 'approve',
                timestamp: new Date().toISOString()
            };
            
            // Make API call to approve game
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.APPROVEGAME'),
                options: {
                    method: 'POST',
                    body: JSON.stringify(requestData)
                }
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }
            
            const result = await response.json();
            console.log('✅ Game approval request successful:', result);
            
            // Show success message
            this.showToast('הבקשה לאישור השיבוץ נשלחה', 'success');
            
            // Refresh games data to show updated status
            await this.loadRefereeGamesData();
            
        } catch (error) {
            console.error('❌ Error approving game:', error);
            this.showToast(`שגיאה בשליחת הבקשה לאישור השיבוץ: ${error.message}`, 'error');
        }
    }
    
    // View live game
    async viewGameLive(gameId) {
        try {
            console.log('📺 Viewing live game for game ID:', gameId);
            this.showToast('פותח צפייה במשחק...', 'info');
            
            // TODO: Implement live game viewing logic
            // This could involve opening a live stream, updating UI, etc.
            
            this.showToast('פתיחת צפייה במשחק', 'success');
            
        } catch (error) {
            console.error('❌ Error viewing live game:', error);
            this.showToast(`שגיאה בפתיחת צפייה במשחק: ${error.message}`, 'error');
        }
    }
    
    // View game report
    async viewGameReport(gameId) {
        try {
            console.log('📊 Viewing game report for game ID:', gameId);
            this.showToast('פותח דו״ח משחק...', 'info');
            
            // TODO: Implement game report viewing logic
            // This could involve opening a report modal, navigating to report page, etc.
            
            this.showToast('פתיחת דו״ח משחק', 'success');
            
        } catch (error) {
            console.error('❌ Error viewing game report:', error);
            this.showToast(`שגיאה בפתיחת דו״ח משחק: ${error.message}`, 'error');
        }
    }

    async openGameReport(gameId) {
        try {
            console.log('📋 Opening game report form for past game ID:', gameId);
            
            // Find the game details to display in the form header
            const gameDetails = this.findGameById(gameId);
            if (!gameDetails) {
                this.showToast('לא נמצאו פרטי המשחק', 'error');
                return;
            }
            
            // Show the report form modal
            this.showReportForm(gameDetails);
            
        } catch (error) {
            console.error('❌ Error opening game report:', error);
            this.showToast(`שגיאה בפתיחת דו״ח משחק: ${error.message}`, 'error');
        }
    }

    findGameById(gameId) {
        // Try to find the game in the current games data
        if (this.allGames && Array.isArray(this.allGames)) {
            const game = this.allGames.find(g => 
                g.id == gameId
            );
            
            if (game) {
                const gameDetails = this.getGameDetails(game);
                return gameDetails;
            }
        }

        return null;
    }

    showReportForm(gameDetails) {
        const modal = document.getElementById('reportFormModal');
        const gameTitle = document.getElementById('reportGameTitle');
        
        if (!modal || !gameTitle) {
            console.error('Report form modal elements not found');
            return;
        }
        
        // Set the game title in the header
        gameTitle.textContent = `דו״ח משחק: ${gameDetails.homeTeam} נגד ${gameDetails.guestTeam}`;
        
        // Clear the form
        this.clearReportForm();
        
        // Show the modal
        modal.style.display = 'block';
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
        
        // Add event listener for form submission
        const form = document.getElementById('reportForm');
        if (form) {
            form.onsubmit = (e) => this.handleReportSubmission(e, gameDetails);
        }
        
        // Add event listeners for checkbox changes
        this.setupReportFormListeners();
        
        // Add click-outside-to-close functionality
        modal.onclick = (e) => {
            if (e.target === modal) {
                this.closeReportForm();
            }
        };
    }

    clearReportForm() {
        const form = document.getElementById('reportForm');
        if (form) {
            form.reset();
            
            // Disable all textareas initially
            const textareas = form.querySelectorAll('textarea');
            textareas.forEach(textarea => {
                textarea.disabled = true;
            });
        }
    }

    setupReportFormListeners() {
        const checkboxes = document.querySelectorAll('#reportForm input[type="checkbox"]');
        
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const textarea = document.querySelector(`textarea[name="${e.target.value}_details"]`);
                if (textarea) {
                    textarea.disabled = !e.target.checked;
                    if (e.target.checked) {
                        textarea.focus();
                    }
                }
            });
        });
    }

    closeReportForm() {
        const modal = document.getElementById('reportFormModal');
        if (modal) {
            modal.style.display = 'none';
            document.body.style.overflow = 'auto'; // Restore scrolling
        }
    }

    async openGameUpdateReport(gameId) {
        try {
            console.log('📋 Opening game update report form for game ID:', gameId);
            
            // Find the game details
            const gameDetails = this.findGameById(gameId);
            if (!gameDetails) {
                this.showToast('לא נמצאו פרטי המשחק', 'error');
                return;
            }

            const tenantKey = gameDetails.tenantKey;

            // Get tenant from loaded tenants (tenants is an object keyed by tenantKey)
            let tenant = null;
            if (this.tenants && tenantKey) {
                tenant = this.tenants[tenantKey];
            }

            if (!tenant) {
                this.showToast('לא נמצאו נתוני דייר', 'error');
                return;
            }

            // Get gameUpdateTags from tenant
            const gameUpdateTags = tenant.gameUpdateTags;
            if (!gameUpdateTags || typeof gameUpdateTags !== 'object') {
                this.showToast('לא הוגדרו תגי עדכון למשחק', 'error');
                return;
            }

            // Show the update report form modal
            this.showGameUpdateReportForm(gameDetails, gameUpdateTags);
            
        } catch (error) {
            console.error('❌ Error opening game update report:', error);
            this.showToast(`שגיאה בפתיחת טופס עדכון דו״ח: ${error.message}`, 'error');
        }
    }

    showGameUpdateReportForm(gameDetails, gameUpdateTags) {
        const modal = document.getElementById('gameUpdateReportModal');
        const title = document.getElementById('gameUpdateReportTitle');
        const fieldsContainer = document.getElementById('gameUpdateReportFields');
        
        if (!modal || !title || !fieldsContainer) {
            console.error('Game update report modal elements not found');
            return;
        }
        
        // Set the game title in the header
        title.textContent = `עדכן דו״ח: ${gameDetails.homeTeam} נגד ${gameDetails.guestTeam}`;
        
        // Clear previous fields
        fieldsContainer.innerHTML = '';
        
        // Convert gameUpdateTags to array and sort by order
        const tagsArray = Object.entries(gameUpdateTags).map(([tagName, tagConfig]) => ({
            name: tagName,
            order: tagConfig.order || 0,
            format: tagConfig.format || 'T'
        })).sort((a, b) => a.order - b.order);
        
        // Generate dynamic fields
        tagsArray.forEach(tag => {
            const fieldHtml = this.generateUpdateReportField(tag);
            fieldsContainer.innerHTML += fieldHtml;
        });
        
        // Show the modal
        modal.style.display = 'block';
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
        
        // Add event listener for form submission
        const form = document.getElementById('gameUpdateReportForm');
        if (form) {
            form.onsubmit = (e) => this.handleGameUpdateReportSubmission(e, gameDetails);
        }
        
        // Add click-outside-to-close functionality
        modal.onclick = (e) => {
            if (e.target === modal) {
                this.closeGameUpdateReport();
            }
        };
    }

    generateUpdateReportField(tag) {
        const { name, format } = tag;
        let fieldHtml = '';
        
        // Parse format to determine field type
        if (format.includes('/')) {
            // Single selection dropdown
            const options = format.split('/').map(opt => opt.trim());
            fieldHtml = `
                <div class="category-item" style="margin-bottom: 1rem;">
                    <label style="display: block; margin-bottom: 0.5rem; font-weight: 500;">${name}</label>
                    <select name="${name}" class="form-select" style="width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px;">
                        <option value="">בחר אפשרות</option>
                        ${options.map(opt => `<option value="${opt}">${opt}</option>`).join('')}
                    </select>
                </div>
            `;
        } else if (format === 'hh:mm') {
            // Time input
            fieldHtml = `
                <div class="category-item" style="margin-bottom: 1rem;">
                    <label style="display: block; margin-bottom: 0.5rem; font-weight: 500;">${name}</label>
                    <input type="time" name="${name}" class="form-input" style="width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px;">
                </div>
            `;
        } else if (format === 'N') {
            // Number input
            fieldHtml = `
                <div class="category-item" style="margin-bottom: 1rem;">
                    <label style="display: block; margin-bottom: 0.5rem; font-weight: 500;">${name}</label>
                    <input type="number" name="${name}" class="form-input" style="width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px;">
                </div>
            `;
        } else {
            // Text input (default, format === 'T' or any other)
            fieldHtml = `
                <div class="category-item" style="margin-bottom: 1rem;">
                    <label style="display: block; margin-bottom: 0.5rem; font-weight: 500;">${name}</label>
                    <input type="text" name="${name}" class="form-input" style="width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px;">
                </div>
            `;
        }
        
        return fieldHtml;
    }

    closeGameUpdateReport() {
        const modal = document.getElementById('gameUpdateReportModal');
        if (modal) {
            modal.style.display = 'none';
            document.body.style.overflow = 'auto'; // Restore scrolling
        }
    }

    /**
     * Send log message to API server
     * @param {string} level - Log level: 'info', 'warn', 'error', 'debug'
     * @param {string} message - Log message
     * @param {string} type - Log type/category (optional)
     * @param {object} data - Additional data to include (optional)
     */
    async sendApiLog(level = 'info', message = '', type = 'client', data = {}) {
        try {
            if (false && !this.refreshTokenService) {
                console.warn('⚠️ Cannot send log: refreshTokenService not initialized');
                return;
            }

            const logData = {
                level: level.toLowerCase(),
                message: message,
                type: type,
                data: data
            };

            const response = await this.refreshTokenService.makeApiRequest({
                url:this.getConfig('ENDPOINTS.LOG'),
                options:{
                    method: 'POST',
                    body: JSON.stringify(logData)
                }
            });

            if (!response.ok) {
                console.warn(`⚠️ Failed to send log to server: ${response.status}`);
            }
        } catch (error) {
            // Silently fail - don't log errors about logging to avoid infinite loops
            console.debug('Log send failed:', error);
        }
    }

    async handleGameUpdateReportSubmission(event, gameDetails) {
        event.preventDefault();
        
        try {
            console.log('📋 Processing game update report submission for game:', gameDetails.gameId);
            this.showToast('מעבד עדכון דו״ח משחק...', 'info');
            
            // Collect form data
            const form = document.getElementById('gameUpdateReportForm');
            const formData = new FormData(form);
            const updateData = {};
            
            // Convert FormData to object
            for (const [key, value] of formData.entries()) {
                updateData[key] = value;
            }
            
            // Validate that at least one field has a value
            if (Object.keys(updateData).length === 0) {
                this.showToast('אנא מלא לפחות שדה אחד', 'error');
                return;
            }
            
            // Call API endpoint
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.UPDATE_GAME_REPORT'),
                options: {
                    method: 'POST',
                    body: JSON.stringify({
                        gameId: gameDetails.gameId,
                        data: updateData
                    })
                }
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ message: 'שגיאה בעדכון הדו״ח' }));
                throw new Error(errorData.message || 'שגיאה בעדכון הדו״ח');
            }
            
            const result = await response.json();
            
            // Close the form
            this.closeGameUpdateReport();
            
            // Show success message
            this.showToast('הדו״ח עודכן בהצלחה', 'success');
            
            // Optionally reload game data
            await this.loadDashboardData();
            
        } catch (error) {
            console.error('❌ Error processing game update report submission:', error);
            this.showToast(`שגיאה בעדכון הדו״ח: ${error.message}`, 'error');
        }
    }

    async handleReportSubmission(event, gameDetails) {
        event.preventDefault();
        
        try {
            console.log('📋 Processing report submission for game:', gameDetails.gameId);
            this.showToast('מעבד דו״ח משחק...', 'info');
            
            // Collect form data
            const formData = this.collectReportFormData();
            
            // Validate form data
            if (!this.validateReportForm(formData)) {
                this.showModalToast('אנא בחר לפחות קטגוריה אחת ופרט את התיקון', 'error');
                return;
            }
            
            // Generate PDF and send email
            await this.generateReportPDF(gameDetails, formData);
            
            // Close the form
            this.closeReportForm();
            
            // Show success message with instructions
            this.showModalToast('הבקשה נשלחה למנהלי המשחקים', 'success');
            
        } catch (error) {
            console.error('❌ Error processing report submission:', error);
            this.showModalToast(`שגיאה בשליחת הדו״ח: ${error.message}`, 'error');
        }
    }

    collectReportFormData() {
        const form = document.getElementById('reportForm');
        const formData = {
            selectedCategories: [],
            details: {}
        };
        
        const checkboxes = form.querySelectorAll('input[type="checkbox"]:checked');
        checkboxes.forEach(checkbox => {
            const categoryId = checkbox.value;
            const label = document.querySelector(`span[name="${categoryId}_label"]`);
            const labelText = label.innerText.trim();
            formData.selectedCategories.push(labelText);
            const textarea = document.querySelector(`textarea[name="${categoryId}_details"]`);
            if (textarea) {
                formData.details[labelText] = textarea.value.trim();
            }
        });
        
        return formData;
    }

    validateReportForm(formData) {
        if (formData.selectedCategories.length === 0) {
            return false;
        }
        
        // Check if at least one category has details
        for (const category of formData.selectedCategories) {
            if (formData.details[category] && formData.details[category].length > 0) {
                return true;
            }
        }
        
        return false;
    }

    async generateReportPDF(gameDetails, formData) {
        try {
            console.log('📄 Generating PDF report...');
            
            // Create report data structure
            const now = new Date()
            const reportData = {
                gameId: gameDetails.gameId,
                gameTitle: `${gameDetails.homeTeam} נגד ${gameDetails.guestTeam}`,
                gameUrl: gameDetails.gameUrl,
                gameDate: gameDetails.gameDate,
                gameTime: gameDetails.gameTime,
                league: gameDetails.league,
                field: gameDetails.field,
                status: gameDetails.status,
                role: gameDetails.role,
                reportDatetime: this.formatTime(now) + ' ' + this.formatDate(now),
                categories: formData.selectedCategories,
                details: formData.details,
                reporter: this.currentUser?.refereeName || 'שופט לא ידוע'
            };
            
            // Use PDF service to generate and send report
            const result = await this.pdfReportService.generateAndSendReport(reportData);
            console.log('✅ Report generated and sent successfully:', result);
            return result;
            
        } catch (error) {
            console.error('❌ Error generating PDF report:', error);
            throw error;
        }
    }

    // Create server down state HTML
    createServerDownState(statusCode, message, retryFunction) {
        const statusText = statusCode === 502 ? 'Bad Gateway' : 
                          statusCode === 503 ? 'Service Unavailable' : 
                          statusCode === 504 ? 'Gateway Timeout' : 
                          `HTTP ${statusCode}`;
        
        return `
            <div class="server-down-state">
                <div class="server-down-logo">
                    <img src="./images/RefereeX.png" alt="RefereeX" onerror="this.style.display='none'">
                </div>
                <div class="server-down-title">השרת אינו זמין כרגע</div>
                <div class="server-down-message">${message || 'שירות המשחקים אינו זמין כרגע. אנא נסה שוב מאוחר יותר.'}</div>
                <button class="server-down-refresh-btn" onclick="refPortalPwa.${retryFunction}()">
                    🔄 נסה שוב
                </button>
                <div class="server-down-status">
                    סטטוס: ${statusText}
                </div>
            </div>
        `;
    }

    // Check if error is a server down error
    isServerDownError(error) {
        // Check for specific HTTP status codes
        if (error.status && (error.status === 502 || error.status === 503 || error.status === 504)) {
            return true;
        }
        
        // Check for network errors that might indicate server down
        if (error.name === 'TypeError' && error.message.includes('Failed to fetch')) {
            return true;
        }
        
        // Check for CORS errors that might indicate server down
        if (error.name === 'TypeError' && error.message.includes('CORS')) {
            return true;
        }
        
        return false;
    }

    // Retry connection method for server down state
    async retryConnection() {
        console.log('🔄 Retrying connection...');
        
        try {
            // Show loading state
            const mainContent = document.querySelector('main') || document.body;
            if (mainContent) {
                mainContent.innerHTML = '<div class="loading" style="text-align: center; padding: 3rem; font-size: 1.2rem;">מנסה להתחבר מחדש...</div>';
            }
            
            // Wait a moment before retrying
            await new Promise(resolve => setTimeout(resolve, 2000));
            
            // Try to reload the page
            window.location.reload();
            
        } catch (error) {
            console.error('❌ Retry connection failed:', error);
            
            // Show error state
            const mainContent = document.querySelector('main') || document.body;
            if (mainContent) {
                mainContent.innerHTML = this.createServerDownState(
                    503,
                    'הניסיון להתחבר מחדש נכשל. אנא רענן את הדף או נסה שוב מאוחר יותר.',
                    'retryConnection'
                );
            }
        }
    }

    // ==================== BADGE SERVICE METHODS ====================

    /**
     * Initialize badge service
     */
    async initializeBadgeService() {
        if (!this.badgeService) {
            console.warn('Badge service not available');
            return;
        }

        console.log('🏷️ Initializing badge service...');
        
        // Subscribe to badge updates
        /*
        this.badgeService.onBadgeUpdate((newValue, oldValue) => {
            console.log(`🏷️ Badge updated: ${oldValue} → ${newValue}`);
            this.updateBadgeDisplay(newValue);
        });
        */

        // Set up periodic badge updates
        await this.setupBadgeUpdates();
        
        console.log('✅ Badge service initialized');
    }

    /**
     * Initialize distance tracking service
     */
    async initializeDistanceTracking() {
        if (!this.distanceTrackerService || !this.distanceTrackerComponent) {
            console.warn('Distance tracking services not available');
            return;
        }

        console.log('🏃‍♂️ Initializing distance tracking...');

        // Initialize the distance tracker component
        this.distanceTrackerComponent.init(this.distanceTrackerService);

        // Set up distance tracking event handlers
        this.distanceTrackerService.setCallbacks({
            onDistanceUpdate: (data) => {
                console.log(`🏃‍♂️ Distance update: ${data.formattedDistance} (Active time: ${data.formattedTime})`);
                
                // Log distance update to server
                this.jwtWebSocket.sendLog({
                    type: 'distance_update',
                    totalDistance: data.totalDistance,
                    currentDistance: data.currentDistance,
                    activeTime: data.activeTime,
                    isTracking: data.isTracking,
                    isPaused: data.isPaused,
                    timestamp: new Date().toISOString()
                });
            },
            onStatusChange: (data) => {
                console.log(`🏃‍♂️ Distance tracking status: ${data.status}`);
                
                // Log status change to server
                this.jwtWebSocket.sendLog({
                    type: 'distance_status_change',
                    status: data.status,
                    totalDistance: data.totalDistance,
                    isTracking: data.isTracking,
                    isPaused: data.isPaused,
                    timestamp: new Date().toISOString()
                });
            },
            onError: (error) => {
                console.error('Distance tracking error:', error);
                
                // Log error to server
                this.jwtWebSocket.sendLog({
                    type: 'distance_tracking_error',
                    error: error,
                    timestamp: new Date().toISOString()
                });
            }
        });

        // Set up game end callback to send total distance
        this.distanceTrackerComponent.setCallbacks({
            onGameEnd: (data) => {
                console.log(`🏃‍♂️ Game ended. Total distance: ${data.formattedDistance}`);
                
                // Send final distance data to server
                this.jwtWebSocket.sendLog({
                    type: 'game_distance_complete',
                    totalDistance: data.totalDistance,
                    activeTime: data.activeTime,
                    totalTime: data.totalTime,
                    positions: data.positions?.length,
                    timestamp: new Date().toISOString()
                });
                
                // Show completion toast
                this.showToast(`מדידת מרחק הסתיימה. סה״כ מרחק: ${data.formattedDistance}`, 'success');
            }
        });

        console.log('🏃‍♂️ Distance tracking initialized');
    }

    /**
     * Initialize speed monitoring service
     */
    async initializeSpeedMonitoring() {
        if (!this.speedMonitorService || !this.speedMonitorComponent) {
            console.warn('Speed monitoring services not available');
            return;
        }

        console.log('🚗 Initializing speed monitoring...');

        // Set up speed monitoring event handlers
        this.speedMonitorService.on('onSpeedExceeded', (data) => {
            console.log(`🚗 Speed exceeded: ${data.speed.toFixed(1)} km/h (threshold: ${data.threshold} km/h)`);
            
            if (data.navigationTriggered) {
                console.log(`🚗 Navigation triggered to next game field: ${data.fieldWazeLink}`);
                // Silent navigation - no alerts shown
            } else {
                console.log('⚠️ Speed exceeded but no navigation URL set');
                // Silent - no alerts shown
            }
            
            // Log speed violation with navigation info
            this.jwtWebSocket.sendLog({
                type: 'speed_exceeded',
                speed: data.speed,
                threshold: data.threshold,
                position: data.position,
                timestamp: data.timestamp,
                navigationTriggered: data.navigationTriggered,
                fieldWazeLink: data.fieldWazeLink
            });
        });

        this.speedMonitorService.on('onSpeedChanged', (data) => {
            this.speedMonitorComponent.updateSpeed(data.speed);
            
            // Log speed change (less frequently)
            if (Math.floor(data.speed) !== Math.floor(this.lastLoggedSpeed || 0)) {
                this.lastLoggedSpeed = data.speed;
                console.log(`🚗 Current speed: ${data.speed.toFixed(1)} km/h`);
            }
        });

        this.speedMonitorService.on('onError', (error) => {
            console.error('Speed monitoring error:', error);
            
            // Show detailed permission error if it's a permission issue
            if (error.error && error.error.code === 1) {
                this.speedMonitorComponent.showPermissionError(error);
            } else {
                // Show generic error message
                this.showToast('מעקב מהירות אינו זמין', 'error');
            }
        });

        this.speedMonitorService.on('onArrival', (data) => {
            console.log(`🏟️ Arrived at field: ${data.fieldName}`);
            this.showToast(`הגעתי למגרש ${data.fieldName}! מעקב מהירות עצר.`, 'success');
            
            // Update header display
            this.updateNextGameDisplay();
            
            // Log arrival event
            this.jwtWebSocket.sendLog({
                type: 'field_arrival',
                fieldName: data.fieldName,
                distance: data.distance,
                arrivalTime: data.arrivalTime,
                gameTime: data.gameTime
            });
        });

        // Start speed monitoring
        //await this.startSpeedMonitoring();
        
        // Update header display initially and set up periodic updates
        this.updateNextGameDisplay();
        this.updateSpeedBadgeVisibility();
        setInterval(() => {
            this.updateNextGameDisplay();
            this.updateSpeedBadgeVisibility();
        }, 60000); // Update every minute
        
        console.log('✅ Speed monitoring initialized');
    }

    /**
     * Start speed monitoring
     */
    async startSpeedMonitoring() {
        try {
            await this.speedMonitorService.startMonitoring();
            console.log('🚗 Speed monitoring started');
        } catch (error) {
            console.error('Failed to start speed monitoring:', error);
        }
    }

    /**
     * Stop speed monitoring
     */
    stopSpeedMonitoring() {
        if (this.speedMonitorService) {
            this.speedMonitorService.stopMonitoring();
            console.log('🛑 Speed monitoring stopped');
        }
    }

    /**
     * Get speed monitoring status
     */
    getSpeedMonitoringStatus() {
        if (!this.speedMonitorService) return null;
        
        return this.speedMonitorService.getStatus();
    }

    /**
     * Set next game for scheduled monitoring
     */
    async setNextGame(gameDateTime, fieldLocation, fieldWazeLink = null, gameTitle = null) {
        if (this.speedMonitorService) {
            await this.speedMonitorService.setNextGame(gameDateTime, fieldLocation, fieldWazeLink, gameTitle);
            console.log(`🏟️ Next game scheduled: ${new Date(gameDateTime).toLocaleString()} - ${gameTitle || 'Game'}`);
            
            // Update header display
            this.updateNextGameDisplay();
        }
    }

    /**
     * Clear next game schedule
     */
    clearNextGame() {
        if (this.speedMonitorService) {
            this.speedMonitorService.clearNextGame();
            console.log('🏟️ Next game schedule cleared');
            
            // Update header display
            this.updateNextGameDisplay();
        }
    }

    /**
     * Get scheduling status
     */
    getScheduleStatus() {
        if (this.speedMonitorService) {
            return this.speedMonitorService.getScheduleStatus();
        }
        return null;
    }

    /**
     * Start distance tracking
     */
    async startDistanceTracking() {
        if (this.distanceTrackerService) {
            await this.distanceTrackerService.startTracking();
            console.log('🏃‍♂️ Distance tracking started');
        }
    }

    /**
     * Pause distance tracking
     */
    pauseDistanceTracking() {
        if (this.distanceTrackerService) {
            this.distanceTrackerService.pauseTracking();
            console.log('⏸️ Distance tracking paused');
        }
    }

    /**
     * Resume distance tracking
     */
    async resumeDistanceTracking() {
        if (this.distanceTrackerService) {
            await this.distanceTrackerService.resumeTracking();
            console.log('▶️ Distance tracking resumed');
        }
    }

    /**
     * Stop distance tracking
     */
    async stopDistanceTracking() {
        if (this.distanceTrackerService) {
            const result = await this.distanceTrackerService.stopTracking();
            console.log('🛑 Distance tracking stopped');
            return result;
        }
        return null;
    }

    /**
     * Reset distance tracking
     */
    async resetDistanceTracking() {
        if (this.distanceTrackerService) {
            await this.distanceTrackerService.resetTracking();
            console.log('🔄 Distance tracking reset');
        }
    }

    /**
     * Get distance tracking status
     */
    getDistanceTrackingStatus() {
        if (this.distanceTrackerService) {
            return this.distanceTrackerService.getStatus();
        }
        return null;
    }

    /**
     * Set arrival radius for field detection
     */
    setArrivalRadius(radius) {
        if (this.speedMonitorService) {
            this.speedMonitorService.arrivalRadius = radius;
            console.log(`🏟️ Arrival radius set to ${radius} meters`);
        }
    }

    /**
     * Update speed badge visibility based on monitoring status
     */
    updateSpeedBadgeVisibility() {
        if (!this.speedMonitorService || !this.speedMonitorComponent) {
            return;
        }

        const speedStatus = this.speedMonitorService.getStatus();
        const speedBadgeContainer = document.getElementById('speedBadgeContainer');
        const badge = document.getElementById('speed-alert-badge');
        
        // Show badge whenever speed monitoring is active
        if (speedStatus && speedStatus.isMonitoring && speedStatus.isScheduled) {
            // Show badge container and create badge if needed
            if (speedBadgeContainer) {
                speedBadgeContainer.style.display = 'block';
            }
            if (badge) {
                badge.style.display = 'block';
            } else {
                // Create badge if it doesn't exist
                this.speedMonitorComponent.createBadge();
            }
        } else {
            // Hide badge container when monitoring is not active
            if (speedBadgeContainer) {
                speedBadgeContainer.style.display = 'none';
            }
            if (badge) {
                badge.style.display = 'none';
            }
        }
    }

    /**
     * Update next game display in header
     */
    updateNextGameDisplay() {
        if (!this.isAuthenticated) {
            return;
        }
        
        const nextGameInfo = document.getElementById('nextGameInfo');
        const nextGameTitle = document.getElementById('nextGameTitle');
        const nextGameSchedule = document.getElementById('nextGameSchedule');
        const nextGameDateTime = document.getElementById('nextGameDateTime');;
        const nextGameStatus = document.getElementById('nextGameStatus');
        
        if (!nextGameInfo || !this.speedMonitorService) {
            return;
        }

        const schedule = this.getScheduleStatus();
        
        if (schedule && schedule.isScheduled && schedule.nextGameDateTime) {
            const now = new Date();
            const serviceStartDateTime = schedule.serviceStartDateTime;
            
            // Always show next game info when there's a scheduled game
            nextGameInfo.style.display = 'flex';
            
            // Update title - use game title if available, otherwise field name
            const displayTitle = schedule.gameTitle || schedule.gameFieldLocation?.name || 'משחק';
            nextGameTitle.textContent = displayTitle;
            
            // Adjust font size to fit within container
            this.adjustElementFontSize(nextGameTitle);
            
            // Update date and time
            if (nextGameDateTime) {
                const gameDate = this.formatDate(schedule.nextGameDateTime);
                const gameTime = this.formatTime(schedule.nextGameDateTime);
                nextGameDateTime.textContent = `${gameDate} ${gameTime}`;
            }
            
            // Show speed monitoring status only 2 hours before the game
            const speedDisplayStartTime = serviceStartDateTime ? new Date(serviceStartDateTime.getTime() - (30 * 60 * 1000)) : new Date(schedule.nextGameDateTime.getTime() - (2 * 60 * 60 * 1000));
            const shouldShowSpeedStatus = now >= speedDisplayStartTime;
            
            if (shouldShowSpeedStatus) {
                // Show speed monitoring status
                if (schedule.arrivalDetected) {
                    nextGameStatus.textContent = 'הגעת למגרש';
                    nextGameStatus.className = 'next-game-status arrived';
                } else if (schedule.timeUntilStart > 0) {
                    // Show time until speed monitoring starts
                    const hours = Math.floor(schedule.timeUntilStart / (1000 * 60 * 60));
                    const minutes = Math.floor((schedule.timeUntilStart % (1000 * 60 * 60)) / (1000 * 60));
                    if (hours > 0) {
                        nextGameStatus.textContent = `מעקב מתחיל בעוד ${hours}שע׳ ${minutes}דק׳`;
                    } else {
                        nextGameStatus.textContent = `מעקב מתחיל בעוד ${minutes}דק׳`;
                    }
                    nextGameStatus.className = 'next-game-status scheduled';
                } else if (schedule.timeUntilGame > 0) {
                    // Show time until game starts (when monitoring is active)
                    const hours = Math.floor(schedule.timeUntilGame / (1000 * 60 * 60));
                    const minutes = Math.floor((schedule.timeUntilGame % (1000 * 60 * 60)) / (1000 * 60));
                    nextGameStatus.textContent = `מתחיל בעוד ${hours}שע׳ ${minutes}דק׳`;
                    nextGameStatus.className = 'next-game-status monitoring';
                } else if (now < schedule.nextGameDateTime) {
                    nextGameStatus.textContent = 'במעקב';
                    nextGameStatus.className = 'next-game-status monitoring';
                } else {
                    nextGameStatus.textContent = 'הסתיים';
                    nextGameStatus.className = 'next-game-status expired';
                }
            } else {
                // Show general game status when speed monitoring is not yet active
                const hoursUntilGame = Math.floor((schedule.nextGameDateTime.getTime() - now.getTime()) / (1000 * 60 * 60));
                if (hoursUntilGame > 24) {
                    const days = Math.floor(hoursUntilGame / 24);
                    nextGameStatus.textContent = `בעוד ${days} ימים`;
                } else if (hoursUntilGame > 0) {
                    nextGameStatus.textContent = `בעוד ${hoursUntilGame} שעות`;
                } else {
                    nextGameStatus.textContent = 'היום';
                }
                nextGameStatus.className = 'next-game-status scheduled';
            }

            this.adjustElementFontSize(nextGameStatus);

        } else {
            // Hide next game info
            nextGameInfo.style.display = 'none';
        }
    }

    /**
     * Set up periodic badge updates
     */
    async setupBadgeUpdates() {
        await this.updateBadgeFromData();

        // Track badge update interval
        this.badgeUpdateInterval = null;

        // Update badge every 60 seconds when app is in focus
        const startForegroundUpdates = () => {
            if (this.badgeUpdateInterval) {
                clearInterval(this.badgeUpdateInterval);
            }
            this.badgeUpdateInterval = setInterval(async () => {
                // Only update if app is visible (in focus)
                if (document.visibilityState === 'visible') {
                    await this.updateBadgeFromData();
                }
            }, 60000);
        };

        // Check initial visibility state and set up accordingly
        if (document.visibilityState === 'hidden') {
            // App started in background - use background sync
            console.log('📱 App started in background, starting background badge sync');
            await this.startBackgroundApiSync(60000);
        } else {
            // App started in foreground - use foreground interval
            startForegroundUpdates();
        }
        
        // Listen for messages from service worker for background API calls
        // This works even when the app is in the background
        if ('serviceWorker' in navigator) {
            // Set up message handler function
            const setupMessageHandler = (controller) => {
                if (!controller) return;
                
                controller.addEventListener('message', async (event) => {
                    if (event.data && event.data.type === 'MAKE_API_CALL') {
                        console.log('📡 Received API call request from service worker (controller)');
                        await this.sendApiLog('info', 'MAKE_API_CALL received from service worker controller');
                        await this.updateBadgeFromData();
                    } else if (event.data && event.data.type === 'GET_AUTH_TOKEN') {
                        // Service worker is requesting auth token for background API calls
                        const token = await this.getJwtToken();
                        const apiBaseUrl = this.getConfig('API_BASE_URL');
                        if (event.ports && event.ports[0]) {
                            event.ports[0].postMessage({ 
                                token: token,
                                apiBaseUrl: apiBaseUrl
                            });
                        }
                    }
                });
            };
                        
            // Set up message handler on controller if available
            if (navigator.serviceWorker.controller) {
                console.log('✅ Service worker controller available, setting up message handler');
                setupMessageHandler(navigator.serviceWorker.controller);
            } else {
                console.log('⚠️ Service worker controller not available yet, waiting...');
                // Wait for service worker to be ready
                navigator.serviceWorker.ready.then((registration) => {
                    if (navigator.serviceWorker.controller) {
                        console.log('✅ Service worker controller now available');
                        setupMessageHandler(navigator.serviceWorker.controller);
                    } else {
                        console.warn('⚠️ Service worker ready but controller still null');
                    }
                }).catch((error) => {
                    console.warn('⚠️ Error waiting for service worker ready:', error);
                });
                
                // Also listen for controllerchange event
                navigator.serviceWorker.addEventListener('controllerchange', () => {
                    console.log('✅ Service worker controller changed');
                    if (navigator.serviceWorker.controller) {
                        setupMessageHandler(navigator.serviceWorker.controller);
                    }
                });
            }
            
            // Store token in IndexedDB for service worker access
            this.setupTokenStorageForServiceWorker();
        }

        // Handle page visibility changes (app goes to background/foreground)
        document.addEventListener('visibilitychange', async () => {
            await this.sendApiLog('info', 'visibilitychange: called, document.visibilityState: ' + document.visibilityState);
            if (document.visibilityState === 'hidden') {
                // App went to background - start background sync in service worker
                console.log('📱 App went to background, starting background badge sync');
                await this.startBackgroundApiSync(60000); // Update every 60 seconds in background
            } else {
                // App came to foreground - stop background sync, use foreground interval
                console.log('📱 App came to foreground, stopping background badge sync');
                await this.stopBackgroundApiSync();
                startForegroundUpdates();
                // Immediately update badge when coming back to foreground
                await this.updateBadgeFromData();
            }
        });

        // Update badge when coming back online
        window.addEventListener('online', async () => {
            await this.sendApiLog('info', 'online: called');
            this.offlineIntervalManager = null;
            // Stop background sync in service worker (will be restarted by visibility handler if needed)
            if (document.visibilityState === 'visible') {
                await this.stopBackgroundApiSync();
            }
            await this.updateBadgeFromData();
        });

        window.addEventListener('offline', async () => {
            await this.sendApiLog('info', 'offline: called');
            // Start background sync in service worker (works even when app is not in focus)
            await this.startBackgroundApiSync(30000);
            
            // Also use OfflineIntervalManager as fallback for when app is in focus
            this.offlineIntervalManager = new OfflineIntervalManager(async () => {
                await this.updateBadgeFromDataInOfflineMode();
            }, 30000);
        });

        // Update badge when messages are received
        this.badgeService.onBadgeUpdate((value) => {
            //await this.updateBadgeFromData();
            this.updateBadgeDisplay(value);
        });
    }

    async updateBadgeFromDataInOfflineMode() {
        console.log('Updating badge from data in offline mode...');
        await this.updateBadgeFromData();
    }

    /**
     * Start background API sync in service worker (works even when app is not in focus)
     */
    async startBackgroundApiSync(interval = 30000) {
        try {
            // Get service worker controller or active worker from registration
            let controller = navigator.serviceWorker.controller;
            if (!controller) {
                // Fallback: try to get active worker from registration
                const registration = await this.getServiceWorkerRegistration();
                if (registration && registration.active) {
                    controller = registration.active;
                }
            }
            
            const swExists = Boolean('serviceWorker' in navigator && controller);
            await this.sendApiLog('info', 'startBackgroundApiSync: called, interval: ' + interval + ', swExists: ' + swExists);
            
            if (swExists) {
                try {
                    const messageChannel = new MessageChannel();
                    
                    messageChannel.port1.onmessage = (event) => {
                        if (event.data.success) {
                            console.log('✅ Background API sync started in service worker');
                        }
                    };
                    
                    controller.postMessage(
                        {
                            type: 'START_BACKGROUND_SYNC',
                            interval: interval
                        },
                        [messageChannel.port2]
                    );
                } catch (error) {
                    console.error('Error starting background API sync:', error);
                }
            } else {
                console.warn('⚠️ Service worker not available for background API sync');
            }
        } catch (error) {
            console.error('Error in startBackgroundApiSync:', error);
        }
    }

    /**
     * Set up token storage in IndexedDB for service worker access
     */
    async setupTokenStorageForServiceWorker() {
        try {
            // Store token in IndexedDB whenever it's available
            const storeTokenInIndexedDB = async () => {
                try {
                    const token = await this.getJwtToken();
                    const apiBaseUrl = this.getConfig('API_BASE_URL');
                    
                    if (token) {
                        const db = await new Promise((resolve, reject) => {
                            const request = indexedDB.open('refereex-auth', 1);
                            request.onerror = () => reject(request.error);
                            request.onsuccess = () => resolve(request.result);
                            request.onupgradeneeded = (event) => {
                                const db = event.target.result;
                                if (!db.objectStoreNames.contains('tokens')) {
                                    db.createObjectStore('tokens');
                                }
                            };
                        });
                        
                        const transaction = db.transaction(['tokens'], 'readwrite');
                        const store = transaction.objectStore('tokens');
                        await store.put(token, 'access_token');
                        await store.put({ API_BASE_URL: apiBaseUrl }, 'api_config');
                        console.log('✅ Token stored in IndexedDB for service worker');
                    }
                } catch (error) {
                    console.warn('⚠️ Failed to store token in IndexedDB:', error);
                }
            };
            
            // Store token initially
            await storeTokenInIndexedDB();
            
            // Also store token when it changes (listen to storage events or refresh token service)
            // Check token every 30 seconds and update if changed
            setInterval(async () => {
                await storeTokenInIndexedDB();
            }, 30000);
        } catch (error) {
            console.warn('⚠️ Failed to set up token storage for service worker:', error);
        }
    }

    /**
     * Stop background API sync in service worker
     */
    async stopBackgroundApiSync() {
        try {
            // Get service worker controller or active worker from registration
            let controller = navigator.serviceWorker.controller;
            if (!controller) {
                // Fallback: try to get active worker from registration
                const registration = await this.getServiceWorkerRegistration();
                if (registration && registration.active) {
                    controller = registration.active;
                }
            }
            
            const swExists = Boolean('serviceWorker' in navigator && controller);
            await this.sendApiLog('info', 'stopBackgroundApiSync: called, swExists: ' + swExists);
            
            if (swExists) {
                try {
                    const messageChannel = new MessageChannel();
                    
                    messageChannel.port1.onmessage = (event) => {
                        if (event.data.success) {
                            console.log('✅ Background API sync stopped in service worker');
                        }
                    };
                    
                    controller.postMessage(
                        {
                            type: 'STOP_BACKGROUND_SYNC'
                        },
                        [messageChannel.port2]
                    );
                } catch (error) {
                    console.error('Error stopping background API sync:', error);
                }
            }
        } catch (error) {
            console.error('Error in stopBackgroundApiSync:', error);
        }
    }

    /**
     * Update badge based on current data
     */
    async updateBadgeFromData() {
        await this.sendApiLog('info', 'updateBadgeFromData: called, isAuthenticated: ' + this.isAuthenticated);
        if (!this.badgeService || !this.isAuthenticated) {
            return;
        }

        try {
            // Get unread messages count
            const unreadCount = await this.getUnreadMessagesCount();
            this.unreadMessagesCount = unreadCount;

            // Get pending games count
            const pendingGamesCount = await this.getPendingGamesCount();
            this.pendingGamesCount = pendingGamesCount;
            await this.sendApiLog('info', 'updateBadgeFromData: pendingGamesCount: ' + pendingGamesCount);

            // Get critical notifications count
            const criticalCount = await this.getCriticalNotificationsCount();
            this.criticalNotificationsCount = criticalCount;

            // Update badge based on priority
            if (criticalCount > 0) {
                await this.badgeService.updateFromCriticalNotifications(true);
            } else if (false && unreadCount > 0) {
                await this.badgeService.updateFromUnreadCount(unreadCount);
            } else if (pendingGamesCount > 0) {
                await this.badgeService.updateFromPendingGames(pendingGamesCount);
            } else {
                await this.badgeService.zeroBadge();                
            }

        } catch (error) {
            console.error('Error updating badge:', error);
        }
    }

    /**
     * Get unread messages count
     * @returns {number} Number of unread messages
     */
    async getUnreadMessagesCount() {
        // This should be implemented based on your chat system
        // For now, return a placeholder
        return this.chatMessages ? this.chatMessages.filter(msg => !msg.read).length : 0;
    }

    async getPendingGames() {
        try {
            // Get all games for the referee
            const { games: allGames } = await this.getRefereeGames();
            await this._ensureFieldsRepositoryForGames(allGames);

            // Filter for upcoming games (not archived, not removed, future date)
            const now = new Date();
            const pendingGames = allGames.filter(game => {
                const gameDetails = this.getGameDetails(game);
                const gameDateTime = new Date(gameDetails.gameDateTime);
                
                return !gameDetails.archived &&
                       !gameDetails.removed &&
                       !gameDetails.canceled &&
                       gameDateTime > now;
            });
            
            // Sort by date to get the next game first
            pendingGames.sort((a, b) => {
                const dateA = new Date(this.getGameDetails(a).gameDateTime);
                const dateB = new Date(this.getGameDetails(b).gameDateTime);
                return dateA - dateB;
            });
            
            // If we have pending games, schedule speed monitoring for the first one
            if (pendingGames.length > 0) {
                const nextGame = pendingGames[0];
                const gameDetails = this.getGameDetails(nextGame);
                
                // Create game title
                const gameTitle = `${gameDetails.homeTeam} נגד ${gameDetails.guestTeam}`;
                
                // Create field location (use default coordinates if not available)
                const fieldLocation = {
                    latitude: gameDetails.fieldLat || 32.0853, // Default to Tel Aviv area
                    longitude: gameDetails.fieldLng || 34.7818,
                    name: gameDetails.field || 'מגרש לא ידוע'
                };
                
                // Schedule speed monitoring for the next game
                await this.setNextGame(
                    gameDetails.gameDateTime,
                    fieldLocation,
                    gameDetails.fieldWazeLink || null,
                    gameTitle
                );
                
                console.log(`🚗 Auto-scheduled speed monitoring for next game: ${gameTitle}`);
            } else {
                // No pending games, clear any existing schedule
                this.clearNextGame();
                console.log('📅 No pending games found, cleared speed monitoring schedule');
            }
            
            return pendingGames;
            
        } catch (error) {
            console.error('Error getting pending games:', error);
            return [];
        }
    }

    /**
     * Get pending games count
     * @returns {number} Number of pending games
     */
    async getPendingGamesCount() {
        // Get pending games (this will also auto-schedule speed monitoring)
        const games = await this.getPendingGames();
        return games.length;
    }

    /**
     * Get critical notifications count
     * @returns {number} Number of critical notifications
     */
    async getCriticalNotificationsCount() {
        // This should be implemented based on your notification system
        // For now, return a placeholder
        return 0;
    }

    /**
     * Update badge display in UI
     * @param {number|string} value - Badge value
     */
    updateBadgeDisplay(value) {
        // Update any UI elements that show badge status
        const badgeElements = document.querySelectorAll('.badge-indicator');
        badgeElements.forEach(element => {
            if (value && value !== 0) {
                element.textContent = value;
                element.style.display = 'inline';
            } else {
                element.style.display = 'none';
            }
        });
    }

    /**
     * Get badge service info
     * @returns {Object} Badge service information
     */
    getBadgeInfo() {
        if (!this.badgeService) {
            return { available: false, message: 'Badge service not available' };
        }
        return {
            available: true,
            supported: this.badgeService.isSupported,
            currentBadge: this.badgeService.getCurrentBadge(),
            platformInfo: this.badgeService.getPlatformInfo()
        };
    }

    /**
     * Send position update via HTTP API (fallback method)
     */
    async sendPositionUpdateViaApi(positionData, timeFromLastCall) {
        try {
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.POSITION_UPDATE'),
                options: {
                    method: 'POST',
                    body: JSON.stringify(positionData)
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            // this.showToast('מיקום עודכן בהצלחה', 'success');
            console.log(`✅ Position update sent to API: distance=${this.totalDistance}m, timeSinceLastCall=${timeFromLastCall}ms`);
        } catch (error) {
            console.error('❌ Error sending position update via API:', error);
            // this.showToast('שגיאה בעדכון מיקום', 'error');
        }
    }

    /**
     * Render password fields based on active tenants
     */
    renderPasswordFields() {
        const passwordSection = document.getElementById('passwordFieldsSection');
        const passwordContainer = document.getElementById('passwordFieldsContainer');
        const tenantRefIdsInput = document.getElementById('tenantRefIdsId');
        
        if (!passwordSection || !passwordContainer || !tenantRefIdsInput) {
            console.warn('Password fields section not found');
            return;
        }

        const tenantRefIds = JSON.parse(tenantRefIdsInput.value);
        if (!tenantRefIds || tenantRefIds.length === 0) {
            passwordSection.style.display = 'none';
            return;
        }

        // Show password section
        passwordSection.style.display = 'block';
        
        // Clear existing fields
        passwordContainer.innerHTML = '';

        // Get tenant names for labels
        const tenants = this.tenants || {};

        // Create password field for each active tenant
        Object.keys(tenantRefIds).forEach((tenantKey) => {
            const tenant = tenants[tenantKey] || {};
            if (!tenant.active) {
                return; // Skip inactive tenants (use 'return' instead of 'continue' in forEach)
            }
            const tenantName = tenant.name || tenantKey || tenantKey;
            
            const formGroup = document.createElement('div');
            formGroup.className = 'form-group';
            
            const label = document.createElement('label');
            label.setAttribute('for', `password_${tenantKey}`);
            label.textContent = `סיסמה עבור ${tenantName}:`;
            
            const input = document.createElement('input');
            input.type = 'password';
            input.id = `password_${tenantKey}`;
            input.className = 'form-input';
            input.setAttribute('data-tenant-key', tenantKey);
            input.placeholder = 'הכנס סיסמה חדשה';
            input.minLength = 8;
            
            const hint = document.createElement('small');
            hint.className = 'form-hint';
            hint.textContent = 'מינימום 8 תווים';
            
            formGroup.appendChild(label);
            formGroup.appendChild(input);
            formGroup.appendChild(hint);
            
            passwordContainer.appendChild(formGroup);
        });
    }

    /**
     * Save passwords for all tenants
     */
    async savePasswords() {
        const saveBtn = document.getElementById('savePasswordsBtn');
        const tenantRefIdsInput = document.getElementById('tenantRefIdsId');

        if (!saveBtn) {
            console.error('Save passwords button not found');
            return;
        }

        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="btn-icon">⏳</span><span>שומר...</span>';
        saveBtn.disabled = true;

        try {
            const passwords = {};
            let hasError = false;
            const errors = [];

            const tenants = this.tenants || {};
            const tenantRefIds = JSON.parse(tenantRefIdsInput.value);

            // Collect passwords from all fields
            Object.keys(tenantRefIds).forEach((tenantKey) => {
                const tenant = tenants[tenantKey] || {};
                if (!tenant.active) {
                    return;
                }
                const input = document.getElementById(`password_${tenantKey}`);
                if (input) {
                    const password = input.value.trim();
                    if (password) {
                        if (password.length < 8) {
                            hasError = true;
                            errors.push(`סיסמה עבור ${tenants[tenantKey].name || tenantKey} חייבת להיות לפחות 8 תווים`);
                        } else {
                            passwords[tenantKey] = password;
                        }
                    }
                }
            });

            if (hasError) {
                throw new Error(errors.join('\n'));
            }

            if (Object.keys(passwords).length === 0) {
                throw new Error('לא הוכנסה סיסמא');
            }

            // Send passwords to API
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.CHANGE_PASSWORD'),
                options: {
                    method: 'POST',
                    body: JSON.stringify({
                        passwords: passwords
                    })
                }
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    this.showToast('סיסמאות עודכנו בהצלחה', 'success');
                    // Clear password fields
                    const tenantRefIdsToClear = this.currentUser?.tenantRefIds || {};
                    Object.keys(tenantRefIdsToClear).forEach((tenantKey) => {
                        const input = document.getElementById(`password_${tenantKey}`);
                        if (input) {
                            input.value = '';
                        }
                    });
                } else {
                    throw new Error(result.error || 'שגיאה בשמירת הסיסמאות');
                }
            } else {
                const errorData = await response.json().catch(() => ({ error: 'שגיאה בשרת' }));
                throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            console.error('Error saving passwords:', error);
            this.showToast(`שגיאה בשמירת סיסמאות: ${error.message}`, 'error');
        } finally {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;
        }
    }

    /**
     * Load user details data
     */
    async loadUserDetailsData() {
        const addressInput = document.getElementById('userHomeAddress');
        const arrivalTimeInput = document.getElementById('userArrivalTime');
        const messageAcceptanceLimitationInput = document.getElementById('messageAcceptanceLimitation');
        const availableFromHourInput = document.getElementById('userAvailableFromHour');
        const availableToHourInput = document.getElementById('userAvailableToHour');
        const firstGameReminderEnabledInput = document.getElementById('userFirstGameReminderEnabled');
        const commuteReminderEnabledInput = document.getElementById('userCommuteReminderEnabled');
        const gameLineupsAnnouncedEnabledInput = document.getElementById('userGameLineupsAnnouncedEnabled');
        const commuteReminderTimeInput = document.getElementById('userCommuteReminderTime');
        const firstGameReminderTimeInput = document.getElementById('userFirstGameReminderTime');
        const calendarNameInput = document.getElementById('userCalendarName');
        const telegramUsernameInput = document.getElementById('userTelegramUsername');
        const tenantRefIdsInput = document.getElementById('tenantRefIdsId');

        if (!addressInput || !arrivalTimeInput || !commuteReminderTimeInput || !firstGameReminderTimeInput) {
            console.error('User details form elements not found');
            return;
        }

        try {
            // Load existing user properties from server
            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.USER_DETAILS'),
                params: {}
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success && result.data) {
                    const data = result.data;
                    
                    // Populate form fields
                    if (data.originAddress) {
                        addressInput.value = data.originAddress;
                    }
                    else {
                        addressInput.value = '';
                    }
                    if (data.messageAcceptanceLimitation !== undefined && data.messageAcceptanceLimitation !== null) {
                        messageAcceptanceLimitationInput.checked = data.messageAcceptanceLimitation;
                    } else {
                        messageAcceptanceLimitationInput.checked = true;
                    }
                    if (data.availableFromHour !== undefined && data.availableFromHour !== null) {
                        availableFromHourInput.value = data.availableFromHour;
                    }
                    if (data.availableToHour !== undefined && data.availableToHour !== null) {
                        availableToHourInput.value = data.availableToHour;
                    }
                    if (data.firstGameReminderEnabled !== undefined && data.firstGameReminderEnabled !== null) {
                        firstGameReminderEnabledInput.checked = data.firstGameReminderEnabled;
                    }
                    if (data.commuteReminderEnabled !== undefined && data.commuteReminderEnabled !== null) {
                        commuteReminderEnabledInput.checked = data.commuteReminderEnabled;
                    }
                    if (data.gameLineupsAnnouncedEnabled !== undefined && data.gameLineupsAnnouncedEnabled !== null) {
                        gameLineupsAnnouncedEnabledInput.checked = data.gameLineupsAnnouncedEnabled;
                    }
                    if (data.timeArrivalInAdvance !== undefined && data.timeArrivalInAdvance !== null) {
                        arrivalTimeInput.value = data.timeArrivalInAdvance;
                    } else {
                        // Default to 45 minutes if not set
                        arrivalTimeInput.value = 45;
                    }
                    if (data.commuteReminderTimeInAdvance !== undefined && data.commuteReminderTimeInAdvance !== null) {
                        commuteReminderTimeInput.value = data.commuteReminderTimeInAdvance;
                    } else {
                        // Default to 3 hours if not set
                        commuteReminderTimeInput.value = 3;
                    }
                    if (data.firstGameReminderTimeInAdvance !== undefined && data.firstGameReminderTimeInAdvance !== null) {
                        firstGameReminderTimeInput.value = data.firstGameReminderTimeInAdvance;
                    } else {
                        // Default to 24 hours if not set
                        firstGameReminderTimeInput.value = 24;
                    }
                    if (calendarNameInput && data.calendarName) {
                        calendarNameInput.value = data.calendarName;
                    }
                    if (telegramUsernameInput) {
                        telegramUsernameInput.value = data.telegramUsername != null && data.telegramUsername !== undefined ? data.telegramUsername : '';
                    }
                    const sendMessagesToTelegramInput = document.getElementById('userSendMessagesToTelegram');
                    if (sendMessagesToTelegramInput && data.sendMessagesToTelegram !== undefined) {
                        sendMessagesToTelegramInput.checked = !!data.sendMessagesToTelegram;
                    }
                    if (sendMessagesToTelegramInput && telegramUsernameInput) {
                        sendMessagesToTelegramInput.disabled = !telegramUsernameInput.value.trim();
                    }
                    if (tenantRefIdsInput) {
                        tenantRefIdsInput.value = JSON.stringify(data.tenantRefIds);
                    }
                }
            } else {
                // If endpoint doesn't exist yet or returns error, just load defaults
                console.log('User details endpoint not available yet, using defaults');
                messageAcceptanceLimitationInput.checked = true;
                availableFromHourInput.value = 7;
                availableToHourInput.value = 21;
                firstGameReminderEnabledInput.checked = true;
                commuteReminderEnabledInput.checked = true;
                gameLineupsAnnouncedEnabledInput.checked = true;
                arrivalTimeInput.value = 45;
                commuteReminderTimeInput.value = 3;
                firstGameReminderTimeInput.value = 24;
                tenantRefIdsInput.value = JSON.stringify({});
                const sendToTelDef = document.getElementById('userSendMessagesToTelegram');
                if (sendToTelDef) { sendToTelDef.checked = false; sendToTelDef.disabled = true; }
            }

        } catch (error) {
            console.log('Error loading user details (using defaults):', error);
            // Set default values if loading fails
            messageAcceptanceLimitationInput.checked = true;
            if (!availableFromHourInput.value || availableFromHourInput.value === '') {
                availableFromHourInput.value = 7;
            }
            if (!availableToHourInput.value || availableToHourInput.value === '') {
                availableToHourInput.value = 21;
            }
            firstGameReminderEnabledInput.checked = true;
            commuteReminderEnabledInput.checked = true;
            gameLineupsAnnouncedEnabledInput.checked = true;
            if (!arrivalTimeInput.value || arrivalTimeInput.value === '') {
                arrivalTimeInput.value = 45;
            }
            if (!commuteReminderTimeInput.value || commuteReminderTimeInput.value === '') {
                commuteReminderTimeInput.value = 3;
            }
            if (!firstGameReminderTimeInput.value || firstGameReminderTimeInput.value === '') {
                firstGameReminderTimeInput.value = 24;
            }
            if (!tenantRefIdsInput.value) {
                tenantRefIdsInput.value = JSON.stringify({});
            }
            const sendToTelErr = document.getElementById('userSendMessagesToTelegram');
            if (sendToTelErr) { sendToTelErr.checked = false; sendToTelErr.disabled = true; }
        }
    }

    /**
     * Save user details
     */
    async saveUserDetails() {
        const saveBtn = document.getElementById('saveUserDetailsBtn');
        const addressInput = document.getElementById('userHomeAddress');
        const messageAcceptanceLimitationInput = document.getElementById('messageAcceptanceLimitation');
        const availableFromHourInput = document.getElementById('userAvailableFromHour');
        const availableToHourInput = document.getElementById('userAvailableToHour');
        const firstGameReminderEnabledInput = document.getElementById('userFirstGameReminderEnabled');
        const commuteReminderEnabledInput = document.getElementById('userCommuteReminderEnabled');
        const gameLineupsAnnouncedEnabledInput = document.getElementById('userGameLineupsAnnouncedEnabled');
        const arrivalTimeInput = document.getElementById('userArrivalTime');
        const commuteReminderTimeInput = document.getElementById('userCommuteReminderTime');
        const firstGameReminderTimeInput = document.getElementById('userFirstGameReminderTime');
        const calendarNameInput = document.getElementById('userCalendarName');
        const telegramUsernameInput = document.getElementById('userTelegramUsername');
        const sendMessagesToTelegramInput = document.getElementById('userSendMessagesToTelegram');

        if (!saveBtn || !addressInput || !arrivalTimeInput || !commuteReminderTimeInput || !firstGameReminderTimeInput) {
            console.error('User details form elements not found');
            return;
        }

        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="btn-icon">⏳</span><span>שומר...</span>';
        saveBtn.disabled = true;

        try {
            const originAddress = addressInput.value.trim();
            const messageAcceptanceLimitation = messageAcceptanceLimitationInput.checked;
            const availableFromHour = availableFromHourInput.valueAsNumber;
            const availableToHour = availableToHourInput.valueAsNumber;
            const firstGameReminderEnabled = firstGameReminderEnabledInput.checked;
            const commuteReminderEnabled = commuteReminderEnabledInput.checked;
            const gameLineupsAnnouncedEnabled = gameLineupsAnnouncedEnabledInput.checked;
            const firstGameReminderTimeInAdvance = firstGameReminderTimeInput.valueAsNumber;
            const commuteReminderTimeInAdvance = commuteReminderTimeInput.valueAsNumber;
            const timeArrivalInAdvance = arrivalTimeInput.valueAsNumber;

            if (messageAcceptanceLimitation && (isNaN(availableFromHour) || availableFromHour < 0 || availableFromHour > 24 || isNaN(availableToHour) || availableToHour < 0 || availableToHour > 24)) {
                throw new Error('שעת התחלה והסיום חייבות להיות מספרים בין 0 ל-24 שעות');
            }

            // Validate first game reminder time
            if (firstGameReminderEnabled && (isNaN(firstGameReminderTimeInAdvance) || firstGameReminderTimeInAdvance < 0 || firstGameReminderTimeInAdvance > 96)) {
                throw new Error('זמן מראש לתזכורת משחק ראשון חייב להיות מספר בין 0 ל-96 שעות');
            }

            // Validate commute reminder time
            if (commuteReminderEnabled && (isNaN(commuteReminderTimeInAdvance) || commuteReminderTimeInAdvance < 0 || commuteReminderTimeInAdvance > 48)) {
                throw new Error('זמן מראש לתזכורת נסיעה חייב להיות מספר בין 0 ל-48 שעות');
            }

            // Validate arrival time
            if (isNaN(timeArrivalInAdvance) || timeArrivalInAdvance < 0 || timeArrivalInAdvance > 180) {
                throw new Error('זמן הגעה חייב להיות מספר בין 0 ל-180 דקות');
            }

            const calendarName = calendarNameInput ? calendarNameInput.value.trim() : '';
            const telegramUsername = telegramUsernameInput ? telegramUsernameInput.value.trim() : '';
            const sendMessagesToTelegram = telegramUsername && sendMessagesToTelegramInput && !sendMessagesToTelegramInput.disabled && sendMessagesToTelegramInput.checked;

            const response = await this.refreshTokenService.makeApiRequest({
                url: this.getConfig('ENDPOINTS.UPDATE_USER_DETAILS'),
                options: {
                    method: 'POST',
                    body: JSON.stringify({
                        originAddress: originAddress,
                        telegramUsername: telegramUsername,
                        sendMessagesToTelegram: sendMessagesToTelegram,
                        messageAcceptanceLimitation: messageAcceptanceLimitation,
                        availableFromHour: availableFromHour,
                        availableToHour: availableToHour,
                        firstGameReminderEnabled: firstGameReminderEnabled,
                        commuteReminderEnabled: commuteReminderEnabled,
                        gameLineupsAnnouncedEnabled: gameLineupsAnnouncedEnabled,
                        firstGameReminderTimeInAdvance: firstGameReminderTimeInAdvance,
                        commuteReminderTimeInAdvance: commuteReminderTimeInAdvance,
                        timeArrivalInAdvance: timeArrivalInAdvance,
                        calendarName: calendarName,
                    })
                }
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    this.showToast('פרטי משתמש עודכנו בהצלחה', 'success');
                } else {
                    throw new Error(result.error || 'שגיאה בשמירת הפרטים');
                }
            } else {
                const errorData = await response.json().catch(() => ({ error: 'שגיאה בשרת' }));
                throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            console.error('Error saving user details:', error);
            this.showToast(`שגיאה בשמירת פרטי משתמש: ${error.message}`, 'error');
        } finally {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;
        }
    }
}

// Handle offline/online status
window.addEventListener('online', () => {
    console.log('📴 Device is online ' + this.pwaLogger.sendToServerLogText);    
    
    if (window.refPortalPwa) {
        const refPortalPwa = window.refPortalPwa;
        // Only show toast if we were actually offline
        if (refPortalPwa.wasOffline) {
            refPortalPwa.showToast('החיבור לאינטרנט חודש', 'success');
            refPortalPwa.wasOffline = false; // Reset the flag
            refPortalPwa.hideToast();
            const section = refPortalPwa.currentSection;
            refPortalPwa.navigateToSection(section);
        }
    }
});

window.addEventListener('offline', () => {
    console.log('📴 Device is offline ' + this.pwaLogger.sendToServerLogText);    

    if (window.refPortalPwa) {
        const refPortalPwa = window.refPortalPwa;
        refPortalPwa.isOnline = false;
        refPortalPwa.wasOffline = true; // Mark that we were offline
        refPortalPwa.showToast('אין חיבור לאינטרנט', 'error');
    }
});

// Global error handler for module loading issues
window.addEventListener('error', (event) => {
    console.error('❌ Global error: ' + this.pwaLogger.sendToServerLogText, event.error);
    if (event.error && event.error.message && event.error.message.includes('import')) {
        console.error('🚨 Module import error detected. Check browser console for details.');
    }
    
    // Check if it's a server down error
    if (window.refPortalPwa && window.refPortalPwa.isServerDownError(event.error)) {
        // Show server down state in the main content area
        const mainContent = document.querySelector('main') || document.body;
        if (mainContent) {
            mainContent.innerHTML = window.refPortalPwa.createServerDownState(
                503,
                'השרת אינו זמין כרגע. ייתכן שיש בעיה בחיבור או שהשרת לא פועל.',
                'retryConnection'
            );
        }
    }
});

// Handle unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
    console.error('❌ Unhandled promise rejection:', event.reason);
});

async function bootstrapRefPortalPwa() {
    try {
        const pwa = new RefPortalPWA();
        window.refPortalPwa = pwa;
        await pwa.init();
        console.log('✅ PWA initialized and set as global variable');
        console.log('Available methods:', Object.getOwnPropertyNames(pwa));
    } catch (error) {
        console.error('❌ Failed to initialize PWA:', error);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => bootstrapRefPortalPwa());
} else {
    bootstrapRefPortalPwa();
}