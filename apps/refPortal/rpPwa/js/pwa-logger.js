// Universal PWA Console Logger
// This service captures console logs and sends them to your server for monitoring
// Compatible with: iPhone, Android, Desktop, and all PWA-capable devices

export class PWALogger {
    constructor(jwtWebSocket) {
        this.jwtWebSocket = jwtWebSocket;
        this.logBuffer = [];
        this.maxBufferSize = 5; // Smaller buffer size
        this.isEnabled = false; // Disabled by default to prevent crashes
        this.originalConsole = {
            log: console.log,
            error: console.error,
            warn: console.warn,
            info: console.info
        };
        this.sendToServerLogText = 'S2S';

        this.setupConsoleInterception();
        this.setupErrorHandling();
        this.setupVisibilityLogging();
    }

    setupConsoleInterception() {
        if (!this.isEnabled) return;

        // Intercept console.log
        console.log = (...args) => {
            this.originalConsole.log(...args);
            this.captureLog('LOG', args);
        };

        // Intercept console.error
        console.error = (...args) => {
            this.originalConsole.error(...args);
            this.captureLog('ERROR', args);
        };

        // Intercept console.warn
        console.warn = (...args) => {
            this.originalConsole.warn(...args);
            this.captureLog('WARN', args);
        };

        // Intercept console.info
        console.info = (...args) => {
            this.originalConsole.info(...args);
            this.captureLog('INFO', args);
        };
    }

    captureLog(level, args) {
        if (!this.isEnabled) return;

        try {
            const message = args.map(arg => 
                typeof arg === 'object' ? JSON.stringify(arg) : String(arg)
            ).join(' ');

            if (!message.includes(this.sendToServerLogText)) {
                return;
            }

            const logEntry = {
                level,
                message: message,
                timestamp: new Date().toISOString(),
                userAgent: navigator.userAgent,
                url: window.location.href,
                isPWA: window.matchMedia('(display-mode: standalone)').matches,
                isOnline: navigator.onLine
            };

            // Add to buffer
            this.logBuffer.push(logEntry);
            
            // Keep buffer size manageable
            if (this.logBuffer.length > this.maxBufferSize) {
                this.logBuffer.shift();
            }

            // Send critical logs immediately (but safely)
            if (logEntry.message.includes(this.sendToServerLogText) || level === 'ERROR' || logEntry.message.includes('❌') || logEntry.message.includes('🚨')) {
                this.sendLogToServer(logEntry);
            }
        } catch (error) {
            // Use original console to avoid infinite loop
            this.originalConsole.error('Error capturing log:', error);
        } finally {
        }
    }

    setupErrorHandling() {
        // Capture unhandled errors (safely)
        window.addEventListener('error', (event) => {
            this.captureLog('ERROR', [
                `Unhandled Error: ${event.error?.message || event.message}`,
                `File: ${event.filename}`,
                `Line: ${event.lineno}`,
                `Column: ${event.colno}`
            ]);
        });

        // Capture unhandled promise rejections (safely)
        window.addEventListener('unhandledrejection', (event) => {
            this.captureLog('ERROR', [
                `Unhandled Promise Rejection: ${event.reason}`
            ]);
        });
    }

    setupVisibilityLogging() {
        // Log when user switches apps (safely)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.captureLog('INFO', ['📱 User left PWA - switched to another app']);
            } else {
                this.captureLog('INFO', ['📱 User returned to PWA']);
            }
        });

        // Log when PWA is closed (safely)
        window.addEventListener('beforeunload', () => {
            this.captureLog('INFO', ['📱 PWA is being closed']);
            this.flushLogs(); // Send all buffered logs before closing
        });

        // Log network changes (safely)
        window.addEventListener('online', () => {
            this.captureLog('INFO', ['🌐 Network: Online']);
        });

        window.addEventListener('offline', () => {
            this.captureLog('WARN', ['🌐 Network: Offline']);
        });
    }

    sendLogToServer(logEntry) {
        try {
            if (this.jwtWebSocket && this.jwtWebSocket.sendLog) {
                this.jwtWebSocket.sendLog('PWA_LOG', JSON.stringify(logEntry));
            }
        } catch (error) {
            // Use original console to avoid infinite loop
            this.originalConsole.error('Error sending log to server:', error);
        }
    }

    flushLogs() {
        try {
            // Send all buffered logs to server
            this.logBuffer.forEach(logEntry => {
                this.sendLogToServer(logEntry);
            });
            this.logBuffer = [];
        } catch (error) {
            this.originalConsole.error('Error flushing logs:', error);
        }
    }

    // Method to manually send logs
    sendBufferedLogs() {
        if (this.logBuffer.length > 0) {
            this.flushLogs();
            this.originalConsole.log('📤 Sent buffered logs to server');
        }
    }

    // Method to get current log buffer (for debugging)
    getLogBuffer() {
        return [...this.logBuffer];
    }

    // Enable/disable logging safely
    setEnabled(enabled) {
        this.isEnabled = enabled;
        if (enabled) {
            try {
                this.setupConsoleInterception();
                this.setupErrorHandling();
                this.setupVisibilityLogging();
                this.originalConsole.log('✅ PWA Logger enabled safely');
            } catch (error) {
                this.originalConsole.error('❌ Failed to enable PWA Logger:', error);
                this.isEnabled = false;
            }
        } else {
            this.restoreOriginalConsole();
            this.originalConsole.log('🔴 PWA Logger disabled');
        }
    }

    // Safe enable method with error handling
    enableSafely() {
        try {
            this.setEnabled(true);
            return true;
        } catch (error) {
            this.originalConsole.error('❌ PWA Logger enable failed:', error);
            return false;
        }
    }

    restoreOriginalConsole() {
        console.log = this.originalConsole.log;
        console.error = this.originalConsole.error;
        console.warn = this.originalConsole.warn;
        console.info = this.originalConsole.info;
    }

    // Cleanup
    destroy() {
        this.restoreOriginalConsole();
        this.flushLogs();
    }
}
