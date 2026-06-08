/**
 * Distance Tracker Component
 * UI component for distance tracking with start/pause/end buttons
 */
export class DistanceTrackerComponent {
    constructor(options = {}) {
        this.options = {
            containerId: 'distanceTracker',
            showToast: true,
            showModal: false,
            autoHideToast: 3000,
            position: 'bottom-right',
            ...options
        };
        
        this.distanceTrackerService = null;
        this.container = null;
        this.isVisible = false;
        this.toastContainer = null;
        
        this.callbacks = {
            onDistanceUpdate: null,
            onGameEnd: null
        };
    }
    
    /**
     * Initialize the component
     */
    init(distanceTrackerService) {
        this.distanceTrackerService = distanceTrackerService;
        
        // Set up callbacks
        this.distanceTrackerService.setCallbacks({
            onDistanceUpdate: (data) => this.handleDistanceUpdate(data),
            onStatusChange: (data) => this.handleStatusChange(data),
            onError: (error) => this.handleError(error)
        });
        
        this.createUI();
        this.isVisible = true;
        this.setupEventListeners();
        this.setupIntervals();
    }
    
    /**
     * Create the UI elements
     */
    createUI() {
        // Create main container
        this.container = document.createElement('div');
        this.container.id = this.options.containerId;
        this.container.className = 'distance-tracker-container';
        this.container.innerHTML = `
            <div class="distance-tracker-panel">
                <div class="distance-tracker-header">
                    <h3>🏃‍♂️ מעקב מרחק</h3>
                    <button class="distance-tracker-toggle" id="distanceTrackerToggle">−</button>
                </div>
                <div class="distance-tracker-content">
                    <div class="distance-display">
                        <div class="distance-value" id="distanceValue">0.00 ק״מ</div>
                        <div class="distance-label">סה״כ מרחק</div>
                    </div>
                    <div class="time-display">
                        <div class="time-value" id="timeValue">00:00:00</div>
                        <div class="time-label">זמן פעיל</div>
                    </div>
                    <div class="timestamp-display" style="font-size: 12px; color: #666; margin-top: 4px; display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
                        <span id="positionTimestamp">עדכון: --:--:--</span>
                        <span id="currentSpeed">מהירות: 0.0 קמ״ש</span>
                        <span id="currentAccuracy">דיוק: -- מ׳</span>
                    </div>
                    <div class="tracker-controls">
                        <button class="tracker-btn start-btn" id="startTracking">
                            ▶️ התחלה
                        </button>
                        <button class="tracker-btn pause-btn" id="pauseTracking" disabled>
                            ⏸️ השהה
                        </button>
                        <button class="tracker-btn stop-btn" id="stopTracking" disabled>
                            ⏹️ סיום
                        </button>
                        <button class="tracker-btn reset-btn" id="resetTracking">
                            🔄 איפוס
                        </button>
                    </div>
                    <div class="tracker-status" id="trackerStatus">
                        מוכן להתחיל
                    </div>
                </div>
            </div>
        `;
        
        // Add to page
        document.body.appendChild(this.container);
        
        // Create toast container if enabled
        if (this.options.showToast) {
            this.createToastContainer();
        }
    }
    
    /**
     * Create toast container
     */
    createToastContainer() {
        this.toastContainer = document.createElement('div');
        this.toastContainer.className = 'distance-toast-container';
        this.toastContainer.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10100;
            pointer-events: none;
        `;
        document.body.appendChild(this.toastContainer);
    }
    
    /**
     * Setup event listeners
     */
    setupEventListeners() {
        // Toggle button
        this.toggleVisibility()
        const toggleBtn = document.getElementById('distanceTrackerToggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => this.toggleVisibility());
        }
        
        // Control buttons
        const startBtn = document.getElementById('startTracking');
        const pauseBtn = document.getElementById('pauseTracking');
        const stopBtn = document.getElementById('stopTracking');
        const resetBtn = document.getElementById('resetTracking');
        
        if (startBtn) {
            startBtn.addEventListener('click', () => this.startTracking());
        }
        
        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => this.togglePause());
        }
        
        if (stopBtn) {
            stopBtn.addEventListener('click', async () => await this.stopTracking());
        }
        
        if (resetBtn) {
            resetBtn.addEventListener('click', async () => await this.resetTracking());
        }
    }
    
    setupIntervals() {
        const active = this.isVisible && this.distanceTrackerService.shouldRefreshDisplay();

        if (active) {
            this.trackingDisplayInterval = setInterval(async () => {
                const data = this.distanceTrackerService.createDisplayData();
                this.updateDisplay(data);
            }, 1000);
        } else {
            clearInterval(this.trackingDisplayInterval);
        }
    }

    /**
     * Toggle visibility
     */
    toggleVisibility() {
        this.isVisible = !this.isVisible;
        const content = this.container.querySelector('.distance-tracker-content');
        const toggle = this.container.querySelector('.distance-tracker-toggle');
        
        if (this.isVisible) {
            content.style.display = 'block';
            toggle.textContent = '−';
            this.setupIntervals();
        } else {
            content.style.display = 'none';
            toggle.textContent = '+';
            this.setupIntervals();
        }
    }
    
    resetDisplay() {
        this.updateDisplay({
            totalDistance: 0,
            currentDistance: 0,
            formattedDistance: '0.00 ק״מ',
            activeTime: 0,
            formattedTime: '00:00:00'
        });
    }

    /**
     * Start tracking
     */
    async startTracking() {
        try {
            await this.distanceTrackerService.startTracking();
            this.setupIntervals();
            this.updateButtonStates('started');
            this.resetDisplay();
            this.showToast('מעקב מרחק התחיל', 'success');
        } catch (error) {
            this.showToast('התחלת מעקב מרחק נכשלה: ' + error.message, 'error');
        }
    }
    
    /**
     * Toggle pause/resume
     */
    async togglePause() {
        if (this.distanceTrackerService.isPaused) {
            await this.distanceTrackerService.resumeTracking();
            this.updateButtonStates('resumed');
            this.showToast('מעקב מרחק המשך', 'info');
        } else {
            this.distanceTrackerService.pauseTracking();
            this.updateButtonStates('paused');
            this.showToast('מעקב מרחק הושהה', 'info');
        }
        this.setupIntervals();
    }
    
    /**
     * Stop tracking
     */
    async stopTracking() {
        const result = await this.distanceTrackerService.stopTracking();
        this.setupIntervals();
        this.updateButtonStates('stopped');
        
        // Show final results
        this.showToast(`מעקב מרחק הסתיים. סה״כ מרחק: ${result.formattedDistance}`, 'success');
        
        // Notify callback if game ended
        if (this.callbacks.onGameEnd) {
            this.callbacks.onGameEnd(result);
        }
    }
    
    /**
     * Reset tracking
     */
    async resetTracking() {
        await this.distanceTrackerService.resetTracking();
        this.setupIntervals();
        this.updateButtonStates('reset');
        this.resetDisplay();
        this.showToast('מעקב מרחק התאפס', 'info');
    }
    
    /**
     * Update button states
     */
    updateButtonStates(status) {
        const startBtn = document.getElementById('startTracking');
        const pauseBtn = document.getElementById('pauseTracking');
        const stopBtn = document.getElementById('stopTracking');
        const resetBtn = document.getElementById('resetTracking');
        
        // Reset all buttons
        [startBtn, pauseBtn, stopBtn, resetBtn].forEach(btn => {
            if (btn) btn.disabled = false;
        });
        
        switch (status) {
            case 'started':
                startBtn.disabled = true;
                pauseBtn.disabled = false;
                stopBtn.disabled = false;
                pauseBtn.textContent = '⏸️ השהה';
                break;
            case 'paused':
                startBtn.disabled = true;
                pauseBtn.disabled = false;
                stopBtn.disabled = false;
                pauseBtn.textContent = '▶️ המשך';
                break;
            case 'resumed':
                startBtn.disabled = true;
                pauseBtn.disabled = false;
                stopBtn.disabled = false;
                pauseBtn.textContent = '⏸️ השהה';
                break;
            case 'stopped':
            case 'reset':
                startBtn.disabled = false;
                pauseBtn.disabled = true;
                stopBtn.disabled = true;
                pauseBtn.textContent = '⏸️ השהה';
                break;
        }
    }
    
    /**
     * Update display
     */
    updateDisplay(data) {
        const distanceValue = document.getElementById('distanceValue');
        const timeValue = document.getElementById('timeValue');
        const tsValue = document.getElementById('positionTimestamp');
        const speedValue = document.getElementById('currentSpeed');
        const accuracyValue = document.getElementById('currentAccuracy');
        
        if (distanceValue) {
            distanceValue.textContent = data.formattedDistance;
        }
        
        if (timeValue) {
            timeValue.textContent = data.formattedTime;
        }
        
        if (tsValue) {
            tsValue.textContent = `עדכון אחרון: ${data.lastPositionTimeFormatted || '--:--:--'}` + (data.errorMessage ? ' ' + data.errorMessage : '');
        }
        
        if (speedValue) {
            speedValue.textContent = `מהירות: ${data.formattedSpeed || '0.0 קמ״ש'}`;
        }
        
        if (accuracyValue) {
            accuracyValue.textContent = `דיוק: ${data.formattedAccuracy || '-- מ׳'}`;
        }
    }
    
    /**
     * Update status
     */
    updateStatus(message) {
        const statusElement = document.getElementById('trackerStatus');
        if (statusElement) {
            statusElement.textContent = message;
        }
    }
    
    /**
     * Handle distance update
     */
    handleDistanceUpdate(data) {
        this.updateDisplay(data);
        
        if (this.callbacks.onDistanceUpdate) {
            this.callbacks.onDistanceUpdate(data);
        }
    }
    
    /**
     * Handle status change
     */
    handleStatusChange(data) {
        let statusMessage = '';
        
        switch (data.status) {
            case 'started':
                statusMessage = 'מעקב מרחק התחיל';
                break;
            case 'paused':
                statusMessage = 'מעקב מרחק הושהה';
                break;
            case 'resumed':
                statusMessage = 'המשך מעקב מרחק';
                break;
            case 'stopped':
                statusMessage = 'מעקב מרחק הסתיים';
                break;
            case 'reset':
                statusMessage = 'מוכן להתחיל';
                break;
        }
        
        this.updateStatus(statusMessage);
    }
    
    /**
     * Handle errors
     */
    handleError(error) {
        this.showToast('שגיאת מעקב מרחק: ' + error, 'error');
        this.updateStatus('Error: ' + error);
    }
    
    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        if (!this.options.showToast || !this.toastContainer) {
            return;
        }
        
        const toast = document.createElement('div');
        toast.className = `distance-toast distance-toast-${type}`;
        toast.textContent = message;
        
        // Add styles
        toast.style.cssText = `
            background: ${this.getToastColor(type)};
            color: white;
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            font-size: 14px;
            max-width: 300px;
            word-wrap: break-word;
            opacity: 0;
            transform: translateX(100%);
            transition: all 0.3s ease;
        `;
        
        this.toastContainer.appendChild(toast);
        
        // Animate in
        setTimeout(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateX(0)';
        }, 10);
        
        // Auto remove
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }, this.options.autoHideToast);
    }
    
    /**
     * Get toast color by type
     */
    getToastColor(type) {
        const colors = {
            success: '#10b981',
            error: '#ef4444',
            warning: '#f59e0b',
            info: '#3b82f6'
        };
        return colors[type] || colors.info;
    }
    
    /**
     * Set callbacks
     */
    setCallbacks(callbacks) {
        this.callbacks = { ...this.callbacks, ...callbacks };
    }
    
    /**
     * Show/hide component
     */
    show() {
        if (this.container) {
            this.container.style.display = 'block';
        }
    }
    
    hide() {
        if (this.container) {
            this.container.style.display = 'none';
        }
    }
    
    /**
     * Destroy component
     */
    destroy() {
        if (this.container && this.container.parentNode) {
            this.container.parentNode.removeChild(this.container);
        }
        
        if (this.toastContainer && this.toastContainer.parentNode) {
            this.toastContainer.parentNode.removeChild(this.toastContainer);
        }
    }
}
