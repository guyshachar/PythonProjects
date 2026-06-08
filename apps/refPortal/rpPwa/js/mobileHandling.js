// Check if Force Touch is supported
function isForceTouchSupported() {
    return 'TouchEvent' in window && 'force' in new TouchEvent('touchstart');
}

// Handle Force Touch events
function handleForceTouch(element, callback) {
    if (!isForceTouchSupported()) return;
    
    let startTime = 0;
    let startForce = 0;
    
    element.addEventListener('touchstart', (e) => {
        startTime = Date.now();
        startForce = e.touches[0].force || 0;
    });
    
    element.addEventListener('touchmove', (e) => {
        const currentForce = e.touches[0].force || 0;
        const forceThreshold = 0.8; // 80% of max force
        
        if (currentForce > forceThreshold) {
            // Hard press detected
            callback(e, currentForce);
        }
    });
    
    element.addEventListener('touchend', (e) => {
        const duration = Date.now() - startTime;
        const forceChange = (e.changedTouches[0].force || 0) - startForce;
        
        // Check if it was a quick hard press
        if (duration < 500 && forceChange > 0.5) {
            callback(e, 'quick-hard-press');
        }
    });
}

// Check if Pressure API is supported
function isPressureSupported() {
    return 'PointerEvent' in window && 'pressure' in new PointerEvent('pointerdown');
}

// Handle Pressure events
function handlePressureTouch(element, callback) {
    if (!isPressureSupported()) return;
    
    let startPressure = 0;
    let startTime = 0;
    
    element.addEventListener('pointerdown', (e) => {
        startPressure = e.pressure;
        startTime = Date.now();
    });
    
    element.addEventListener('pointermove', (e) => {
        const currentPressure = e.pressure;
        const pressureThreshold = 0.8; // 80% of max pressure
        
        if (currentPressure > pressureThreshold) {
            // Hard press detected
            callback(e, currentPressure);
        }
    });
    
    element.addEventListener('pointerup', (e) => {
        const duration = Date.now() - startTime;
        const pressureChange = e.pressure - startPressure;
        
        // Check if it was a quick hard press
        if (duration < 500 && pressureChange > 0.5) {
            callback(e, 'quick-hard-press');
        }
    });
}

// Universal hard click detection for all mobile devices
function implementHardClick(element, callback, options = {}) {
    const {
        forceThreshold = 0.8,
        pressureThreshold = 0.8,
        durationThreshold = 500,
        enableVibration = true
    } = options;
    
    let isHardPressActive = false;
    let startTime = 0;
    let startValue = 0;
    
    // Force Touch (iOS)
    if (isForceTouchSupported()) {
        element.addEventListener('touchstart', (e) => {
            startTime = Date.now();
            startValue = e.touches[0].force || 0;
        });
        
        element.addEventListener('touchmove', (e) => {
            const currentForce = e.touches[0].force || 0;
            
            if (currentForce > forceThreshold && !isHardPressActive) {
                isHardPressActive = true;
                if (enableVibration) navigator.vibrate(50);
                callback(e, { type: 'force-touch', value: currentForce });
            }
        });
        
        element.addEventListener('touchend', () => {
            isHardPressActive = false;
        });
    }
    
    // Pressure API (Android)
    else if (isPressureSupported()) {
        element.addEventListener('pointerdown', (e) => {
            startTime = Date.now();
            startValue = e.pressure;
        });
        
        element.addEventListener('pointermove', (e) => {
            const currentPressure = e.pressure;
            
            if (currentPressure > pressureThreshold && !isHardPressActive) {
                isHardPressActive = true;
                if (enableVibration) navigator.vibrate(50);
                callback(e, { type: 'pressure', value: currentPressure });
            }
        });
        
        element.addEventListener('pointerup', () => {
            isHardPressActive = false;
        });
    }
    
    // Fallback: Long press with haptic feedback
    else {
        let longPressTimer = null;
        
        element.addEventListener('touchstart', () => {
            longPressTimer = setTimeout(() => {
                if (enableVibration) navigator.vibrate(100);
                callback(null, { type: 'long-press', value: 'fallback' });
            }, 800);
        });
        
        element.addEventListener('touchend', () => {
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        });
    }
}

function getDeviceInfo() {
    const userAgent = navigator.userAgent;
    const platform = navigator.platform;
    
    // Device type detection
    let deviceType = 'Unknown';
    let deviceName = 'Unknown Device';
    
    if (/iPhone|iPad|iPod/.test(userAgent)) {
        deviceType = 'iOS';
        if (/iPhone/.test(userAgent)) {
            deviceName = 'iPhone';
        } else if (/iPad/.test(userAgent)) {
            deviceName = 'iPad';
        } else {
            deviceName = 'iPod';
        }
    } else if (/Android/.test(userAgent)) {
        deviceType = 'Android';
        deviceName = 'Android Device';
    } else if (/Windows/.test(userAgent)) {
        deviceType = 'Windows';
        deviceName = 'Windows PC';
    } else if (/Mac/.test(userAgent)) {
        deviceType = 'macOS';
        deviceName = 'Mac';
    } else if (/Linux/.test(userAgent)) {
        deviceType = 'Linux';
        deviceName = 'Linux PC';
    }
    
    // Browser detection
    let browser = 'Unknown';
    if (/Chrome/.test(userAgent)) {
        browser = 'Chrome';
    } else if (/Firefox/.test(userAgent)) {
        browser = 'Firefox';
    } else if (/Safari/.test(userAgent) && !/Chrome/.test(userAgent)) {
        browser = 'Safari';
    } else if (/Edge/.test(userAgent)) {
        browser = 'Edge';
    }
    
    // Screen resolution
    const screenInfo = {
        width: screen.width,
        height: screen.height,
        pixelRatio: window.devicePixelRatio || 1
    };
    
    // Device memory (if available)
    const memory = navigator.deviceMemory ? `${navigator.deviceMemory}GB` : 'Unknown';
    
    // Connection info
    const connection = navigator.connection ? {
        effectiveType: navigator.connection.effectiveType,
        downlink: navigator.connection.downlink,
        rtt: navigator.connection.rtt
    } : null;
    
    return {
        deviceType,
        deviceName,
        browser,
        platform,
        userAgent: userAgent.substring(0, 100) + '...', // Truncate for readability
        screenInfo,
        memory,
        connection,
        language: navigator.language,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        timestamp: new Date().toISOString()
    };
}

export { implementHardClick, getDeviceInfo }