// RefPortal PWA Configuration
// Generated automatically by setup script

const PWA_CONFIG = {
    // VAPID Keys for Push Notifications
    VAPID_PUBLIC_KEY: 'BCrb6Lp792xCx8tOm_BLPrvb6DY9GDhfu9K04DBrhAz4qDL7LqVodnePQ4ZTmZXBUWhWumYlKwEjj4QzHRChhX0',
    
    SSL_FILES: {
        cert: './pwa-dev.refereex.com.fullchain.pem',
        key: './pwa-dev.refereex.com.privkey.pem',
    },

    HTTP_PORT: 8082,
    HTTPS_PORT: 8443,

    // API Endpoints
    // DEV
    API_BASE_URL: 'https://pwa-dev.refereex.com:5003',
    WSS_BASE_URL: 'pwa-dev.refereex.com:5003',
    // PROD
    API_BASE_URL1: 'https://api.refereex.com',
    WSS_BASE_URL1: 'api.refereex.com',
    
    ENDPOINTS: {
        PUBLIC_LEAGUE_TABLES: '/api/pwa/public/leagueTables',
        PUBLIC_GAMES: '/api/pwa/public/games',
        PUBLIC_GAMES_STREAM: '/api/pwa/public/games/stream',
        PUBLIC_TABLES_FILTERS: '/api/pwa/public/tablesFilters',
        PUBLIC_GAMES_FILTERS: '/api/pwa/public/gamesFilters',
        AUTH_REFRESH_TOKEN: '/api/pwa/auth/refresh',
        DASHBOARD: '/api/pwa/dashboardLoadData',
        REFEREEGAMES: '/api/pwa/refereeGames',
        REFEREEREVIEWS: '/api/pwa/refereeReviews',
        MESSAGES: '/api/pwa/messages',
        DOWNLOADICSFILE: '/api/pwa/downloadIcsFile',
        TENANTS: '/api/pwa/tenants',
        ROLES: '/api/pwa/roles',
        FIELDS: '/api/pwa/fields',
        AVAILABILITY: '/api/pwa/availability',
        UPDATEREFEREEAVAILABILITY: '/api/pwa/updateRefereeAvailability',
        DOCUMENTS: '/api/pwa/documents',
        RULES: '/api/pwa/rules',
        PAIR: '/api/pwa/pair',
        PAIR: '/api/pwa/pair',
        CHECK_AUTH: '/api/pwa/check-auth',
        UNPAIR: '/api/pwa/unpair',
        CHAT: '/api/pwa/chat',
        HEALTH: '/api/pwa/health',
        SET_PUSH_SUBSCRIPTION: '/api/pwa/push/set-subscription',
        APPROVEGAME: '/api/pwa/approveGame',
        SEND_REPORT_EMAIL: '/api/pwa/sendReportEmail',
        AUTH_REFRESH_TOKEN: '/auth/refresh',
        AUTH_VALIDATE_TOKEN: '/auth/validate',
        AUTH_UNPAIR: '/auth/unpair',
        POSITION_UPDATE: '/api/pwa/position-update',
        USER_DETAILS: '/api/pwa/user-details',
        UPDATE_USER_DETAILS: '/api/pwa/updateUserDetails',
        CHANGE_PASSWORD: '/api/pwa/change-password',
        UPDATE_GAME_REPORT: '/api/pwa/pwaUpdateGameReport',
        LOG: '/api/pwa/log',
        REFEREE_TEMPLATES: '/api/pwa/refereeTemplates',
        REFEREE_TEMPLATE_UPDATE: '/api/pwa/templates/update',
        NOTIFICATIONS: '/api/pwa/notifications',
        NOTIFICATION_UPDATE: '/api/pwa/notifications/update',
    },
    
    // App Configuration
    APP_NAME: 'RefereeX',
    APP_SHORT_NAME: 'RefereeX',
    APP_DESCRIPTION: 'מערכת ניהול שופטים ומשחקים מתקדמת',
    
    // Notification Settings
    NOTIFICATION_ICON: '../images/RefereeX.png',
    NOTIFICATION_TIMEOUT: 5000, // 5 seconds
    
    // Cache Configuration
    CACHE_VERSION: 'v1.0.0',
    STATIC_CACHE_NAME: 'refportal-static-v1',
    DYNAMIC_CACHE_NAME: 'refportal-dynamic-v1',
    
    // Feature Flags
    FEATURES: {
        PUSH_NOTIFICATIONS: true,
        PUSH_NOTIFICATIONS_MUST: false,
        OFFLINE_SUPPORT: true,
        BACKGROUND_SYNC: true,
        INSTALL_PROMPT: true,
        CHAT_SYNC: true, // Disabled to prevent frequent refreshes
        MAX_GPS_ACCURACY: 30,
        START_MONITORING_HOURS_BEFORE_GAME: 3,
        SPEED_THRESHOLD: 20,
        MIN_DISTANCE_THRESHOLD: 3,
    },

    // Security
    SECURITY: {
        ENABLE_PIN: false,
        PIN_LENGTH: 4,
        MAX_PAIR_ATTEMPTS: 3,
        LOCKOUT_TIME: 0.2* 60 * 1000, // 5 minutes
    },
    
    // Open Reports Emails
    OPEN_REPORTS_EMAILS: [
        'openreports@refereex.com',
        'guyshachar.acc@gmail.com',
    ],

    // Debug Mode
    DEBUG: true
}

// Export for ES6 modules
export { PWA_CONFIG };
