/**
 * Speed Alert Component for RefPortal PWA
 * Displays alerts and notifications when speed threshold is exceeded
 */

export class SpeedMonitorComponent {
    constructor(options = {}) {
        this.options = {
            showToast: options.showToast !== false,
            showModal: options.showModal !== false,
            showBadge: options.showBadge !== false,
            autoHideToast: options.autoHideToast || 5000, // ms
            maxToastCount: options.maxToastCount || 3,
            ...options
        };
        
        this.toastContainer = null;
        this.modal = null;
        this.badge = null;
        this.activeToasts = [];
        this.isModalVisible = false;
        this.alertCount = 0;
        
        this.init();
    }

    /**
     * Initialize the component
     */
    init() {
        this.createToastContainer();
        this.createModal();
        this.createBadge();
        this.setupStyles();
    }

    /**
     * Create toast notification container
     */
    createToastContainer() {
        if (!this.options.showToast) return;

        this.toastContainer = document.createElement('div');
        this.toastContainer.id = 'speed-alert-toast-container';
        this.toastContainer.className = 'speed-alert-toast-container';
        document.body.appendChild(this.toastContainer);
    }

    /**
     * Create modal dialog
     */
    createModal() {
        if (!this.options.showModal) return;

        this.modal = document.createElement('div');
        this.modal.id = 'speed-alert-modal';
        this.modal.className = 'speed-alert-modal';
        this.modal.innerHTML = `
            <div class="speed-alert-modal-content">
                <div class="speed-alert-modal-header">
                    <h3>⚠️ Speed Alert</h3>
                    <button class="speed-alert-close" onclick="this.closest('.speed-alert-modal').style.display='none'">&times;</button>
                </div>
                <div class="speed-alert-modal-body">
                    <div class="speed-alert-icon">🚗💨</div>
                    <p class="speed-alert-message">You are traveling at <strong id="speed-value">0</strong> קמ״ש</p>
                    <p class="speed-alert-threshold">Speed limit: <strong id="threshold-value">10</strong> קמ״ש</p>
                    <div class="speed-alert-actions">
                        <button class="speed-alert-btn speed-alert-btn-primary" onclick="this.closest('.speed-alert-modal').style.display='none'">I Understand</button>
                        <button class="speed-alert-btn speed-alert-btn-secondary" onclick="this.closest('.speed-alert-modal').style.display='none'">Dismiss</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(this.modal);
    }

    /**
     * Create speed badge
     */
    createBadge() {
        if (!this.options.showBadge) return;

        // Check if badge already exists
        if (this.badge && document.getElementById('speed-alert-badge')) {
            return;
        }

        this.badge = document.createElement('div');
        this.badge.id = 'speed-alert-badge';
        this.badge.className = 'speed-alert-badge';
        this.badge.innerHTML = `
            <div class="speed-badge-content">
                <span class="speed-badge-icon">🚗</span>
                <span class="speed-badge-text" id="speed-badge-text">0 קמ״ש</span>
            </div>
        `;
        
        // Try to append to speed badge container first, fallback to body
        const speedBadgeContainer = document.getElementById('speedBadgeContainer');
        if (speedBadgeContainer) {
            speedBadgeContainer.appendChild(this.badge);
        } else {
            document.body.appendChild(this.badge);
        }
    }

    /**
     * Setup CSS styles
     */
    setupStyles() {
        if (document.getElementById('speed-alert-styles')) return;

        const style = document.createElement('style');
        style.id = 'speed-alert-styles';
        style.textContent = `
            /* Toast Container */
            .speed-alert-toast-container {
                position: fixed;
                top: 5px;
                right: 5px;
                z-index: 10100;
                pointer-events: none;
            }

            /* Toast Notifications */
            .speed-alert-toast {
                background: linear-gradient(135deg, #ff6b6b, #ee5a24);
                color: white;
                padding: 16px 20px;
                margin-bottom: 10px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
                pointer-events: auto;
                animation: slideInRight 0.3s ease-out;
                max-width: 300px;
                position: relative;
                overflow: hidden;
            }

            .speed-alert-toast::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 3px;
                background: linear-gradient(90deg, #ff9ff3, #f368e0);
                animation: pulse 2s infinite;
            }

            .speed-alert-toast-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
            }

            .speed-alert-toast-title {
                font-weight: bold;
                font-size: 16px;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .speed-alert-toast-close {
                background: none;
                border: none;
                color: white;
                font-size: 18px;
                cursor: pointer;
                padding: 0;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                transition: background-color 0.2s;
            }

            .speed-alert-toast-close:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }

            .speed-alert-toast-message {
                font-size: 12px;
                line-height: 1.4;
                margin: 0;
            }

            .speed-alert-toast-speed {
                font-size: 18px;
                font-weight: bold;
                margin: 8px 0;
                text-align: center;
            }

            /* Modal */
            .speed-alert-modal {
                display: none;
                position: fixed;
                z-index: 10001;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0, 0, 0, 0.5);
                backdrop-filter: blur(5px);
            }

            .speed-alert-modal-content {
                background-color: white;
                margin: 10% auto;
                padding: 0;
                border-radius: 12px;
                width: 90%;
                max-width: 400px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
                animation: modalSlideIn 0.3s ease-out;
            }

            .speed-alert-modal-header {
                background: linear-gradient(135deg, #ff6b6b, #ee5a24);
                color: white;
                padding: 20px;
                border-radius: 12px 12px 0 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .speed-alert-modal-header h3 {
                margin: 0;
                font-size: 20px;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .speed-alert-close {
                background: none;
                border: none;
                color: white;
                font-size: 24px;
                cursor: pointer;
                padding: 0;
                width: 32px;
                height: 32px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                transition: background-color 0.2s;
            }

            .speed-alert-close:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }

            .speed-alert-modal-body {
                padding: 30px;
                text-align: center;
            }

            .speed-alert-icon {
                font-size: 48px;
                margin-bottom: 20px;
                animation: bounce 1s infinite;
            }

            .speed-alert-message {
                font-size: 18px;
                margin-bottom: 10px;
                color: #333;
            }

            .speed-alert-threshold {
                font-size: 12px;
                color: #666;
                margin-bottom: 30px;
            }

            .speed-alert-actions {
                display: flex;
                gap: 12px;
                justify-content: center;
            }

            .speed-alert-btn {
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s;
            }

            .speed-alert-btn-primary {
                background: linear-gradient(135deg, #ff6b6b, #ee5a24);
                color: white;
            }

            .speed-alert-btn-primary:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(255, 107, 107, 0.4);
            }

            .speed-alert-btn-secondary {
                background: #f8f9fa;
                color: #666;
                border: 1px solid #dee2e6;
            }

            .speed-alert-btn-secondary:hover {
                background: #e9ecef;
            }

            /* Speed Badge */
            .speed-alert-badge {
                position: relative;
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                padding: 6px 12px;
                border-radius: 16px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
                font-size: 11px;
                font-weight: 500;
                transition: all 0.3s ease;
            }

            .speed-alert-badge.exceeding {
                background: linear-gradient(135deg, #ff6b6b, #ee5a24);
                animation: pulse 1s infinite;
            }

            .speed-badge-content {
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .speed-badge-icon {
                font-size: 16px;
            }

            .speed-badge-text {
                font-family: 'Courier New', monospace;
            }

            /* Animations */
            @keyframes slideInRight {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }

            @keyframes slideOutRight {
                from {
                    transform: translateX(0);
                    opacity: 1;
                }
                to {
                    transform: translateX(100%);
                    opacity: 0;
                }
            }

            @keyframes modalSlideIn {
                from {
                    transform: scale(0.8) translateY(-50px);
                    opacity: 0;
                }
                to {
                    transform: scale(1) translateY(0);
                    opacity: 1;
                }
            }

            @keyframes bounce {
                0%, 20%, 50%, 80%, 100% {
                    transform: translateY(0);
                }
                40% {
                    transform: translateY(-10px);
                }
                60% {
                    transform: translateY(-5px);
                }
            }

            @keyframes pulse {
                0% {
                    transform: scale(1);
                }
                50% {
                    transform: scale(1.05);
                }
                100% {
                    transform: scale(1);
                }
            }

            /* Responsive */
            @media (max-width: 480px) {
                .speed-alert-toast-container {
                    top: 5px;
                    right: 5px;
                    left: 5px;
                }

                .speed-alert-toast {
                    max-width: none;
                }

                .speed-alert-modal-content {
                    margin: 5% auto;
                    width: 95%;
                }

                .speed-alert-actions {
                    flex-direction: column;
                }

                .speed-alert-btn {
                    width: 100%;
                }
            }
        `;
        
        document.head.appendChild(style);
    }

    /**
     * Show speed exceeded alert
     */
    showSpeedAlert(data) {
        this.alertCount++;
        
        // Update badge
        this.updateSpeedBadge(data.speed, true);
        
        // Show toast
        if (this.options.showToast) {
            this.showToast(data);
        }
        
        // Show modal (only first time or if not already visible)
        if (this.options.showModal && !this.isModalVisible) {
            this.showModal(data);
        }
    }

    /**
     * Show permission error alert
     */
    showPermissionError(errorData) {
        const instructions = errorData.instructions;
        
        // Show detailed permission error modal
        this.showPermissionErrorModal(instructions);
        
        // Show toast with quick instructions
        if (this.options.showToast) {
            this.showPermissionErrorToast(instructions);
        }
    }

    /**
     * Show permission error modal
     */
    showPermissionErrorModal(instructions) {
        if (!this.options.showModal) return;

        // Create or update modal for permission error
        let modal = document.getElementById('speed-permission-error-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'speed-permission-error-modal';
            modal.className = 'speed-alert-modal';
            document.body.appendChild(modal);
        }

        modal.innerHTML = `
            <div class="speed-alert-modal-content">
                <div class="speed-alert-modal-header">
                    <h3>🔐 ${instructions.title}</h3>
                    <button class="speed-alert-close" onclick="this.closest('.speed-alert-modal').style.display='none'">&times;</button>
                </div>
                <div class="speed-alert-modal-body">
                    <div class="speed-alert-icon">📍</div>
                    <p class="speed-alert-message">${instructions.message}</p>
                    <div class="permission-steps">
                        <h4>Steps to enable location access:</h4>
                        <ol>
                            ${instructions.steps.map(step => `<li>${step}</li>`).join('')}
                        </ol>
                    </div>
                    <div class="browser-instructions">
                        <h4>Browser-specific instructions:</h4>
                        <ul>
                            <li>${instructions.browserSpecific?.chrome || ''}</li>
                            <li>${instructions.browserSpecific?.firefox || ''}</li>
                            <li>${instructions.browserSpecific?.safari || ''}</li>
                            <li>${instructions.browserSpecific?.mobile || ''}</li>
                        </ul>
                    </div>
                    <div class="speed-alert-actions">
                        <button class="speed-alert-btn speed-alert-btn-primary" onclick="location.reload()">Refresh Page</button>
                        <button class="speed-alert-btn speed-alert-btn-secondary" onclick="this.closest('.speed-alert-modal').style.display='none'">Dismiss</button>
                    </div>
                </div>
            </div>
        `;
        
        modal.style.display = 'block';
        this.isModalVisible = true;
    }

    /**
     * Show permission error toast
     */
    showPermissionErrorToast(instructions) {
        if (!this.options.showToast) return;

        const toast = document.createElement('div');
        toast.className = 'speed-alert-toast permission-error-toast';
        toast.innerHTML = `
            <div class="speed-alert-toast-header">
                <div class="speed-alert-toast-title">
                    🔐 ${instructions.title}
                </div>
                <button class="speed-alert-toast-close" onclick="this.parentElement.parentElement.remove()">&times;</button>
            </div>
            <div class="speed-alert-toast-message">
                ${instructions.message}
            </div>
            <div class="speed-alert-toast-actions">
                <button class="speed-alert-btn-small" onclick="location.reload()">Refresh</button>
            </div>
        `;

        this.toastContainer.appendChild(toast);
        this.activeToasts.push(toast);

        // Auto-hide after 10 seconds
        setTimeout(() => {
            this.removeToast(toast);
        }, 10000);
    }

    /**
     * Show toast notification
     */
    showToast(data) {
        if (this.activeToasts.length >= this.options.maxToastCount) {
            // Remove oldest toast
            const oldestToast = this.activeToasts.shift();
            if (oldestToast) {
                this.removeToast(oldestToast);
            }
        }

        const toast = document.createElement('div');
        toast.className = 'speed-alert-toast';
        toast.innerHTML = `
            <div class="speed-alert-toast-header">
                <div class="speed-alert-toast-title">
                    ⚠️ Speed Alert #${this.alertCount}
                </div>
                <button class="speed-alert-toast-close" onclick="this.parentElement.parentElement.remove()">&times;</button>
            </div>
            <div class="speed-alert-toast-message">
                You are traveling at <strong>${data.speed.toFixed(1)} קמ״ש</strong>
            </div>
            <div class="speed-alert-toast-speed">
                Speed limit: ${data.threshold} קמ״ש
            </div>
        `;

        this.toastContainer.appendChild(toast);
        this.activeToasts.push(toast);

        // Auto-hide toast
        if (this.options.autoHideToast > 0) {
            setTimeout(() => {
                this.removeToast(toast);
            }, this.options.autoHideToast);
        }
    }

    /**
     * Remove toast notification
     */
    removeToast(toast) {
        if (toast && toast.parentNode) {
            toast.style.animation = 'slideOutRight 0.3s ease-in';
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
                const index = this.activeToasts.indexOf(toast);
                if (index > -1) {
                    this.activeToasts.splice(index, 1);
                }
            }, 300);
        }
    }

    /**
     * Show modal dialog
     */
    showModal(data) {
        if (!this.modal) return;

        this.isModalVisible = true;
        this.modal.style.display = 'block';
        
        // Update modal content
        const speedValue = this.modal.querySelector('#speed-value');
        const thresholdValue = this.modal.querySelector('#threshold-value');
        
        if (speedValue) speedValue.textContent = data.speed.toFixed(1);
        if (thresholdValue) thresholdValue.textContent = data.threshold;

        // Auto-hide modal after 10 seconds
        setTimeout(() => {
            this.hideModal();
        }, 10000);
    }

    /**
     * Hide modal dialog
     */
    hideModal() {
        if (this.modal) {
            this.modal.style.display = 'none';
            this.isModalVisible = false;
        }
    }

    /**
     * Update speed badge
     */
    updateSpeedBadge(speed, isExceeding = false) {
        if (!this.badge) return;

        const badgeText = this.badge.querySelector('#speed-badge-text');
        if (badgeText) {
            badgeText.textContent = `${speed.toFixed(1)} קמ״ש`;
        }

        if (isExceeding) {
            this.badge.classList.add('exceeding');
        } else {
            this.badge.classList.remove('exceeding');
        }
    }

    /**
     * Update speed display
     */
    updateSpeed(speed) {
        this.updateSpeedBadge(speed, false && speed > 10); // Assuming 10 קמ״ש threshold
    }

    /**
     * Clear all alerts
     */
    clearAll() {
        // Clear toasts
        this.activeToasts.forEach(toast => this.removeToast(toast));
        this.activeToasts = [];
        
        // Hide modal
        this.hideModal();
        
        // Reset badge
        this.updateSpeedBadge(0, false);
    }

    /**
     * Cleanup component
     */
    cleanup() {
        this.clearAll();
        
        if (this.toastContainer && this.toastContainer.parentNode) {
            this.toastContainer.parentNode.removeChild(this.toastContainer);
        }
        
        if (this.modal && this.modal.parentNode) {
            this.modal.parentNode.removeChild(this.modal);
        }
        
        if (this.badge && this.badge.parentNode) {
            this.badge.parentNode.removeChild(this.badge);
        }
        
        const styles = document.getElementById('speed-alert-styles');
        if (styles && styles.parentNode) {
            styles.parentNode.removeChild(styles);
        }
    }
}

// Export singleton instance
//export const speedAlertComponent = new SpeedMonitorComponent();