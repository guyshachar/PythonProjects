export class OfflineIntervalManager {
    constructor(callback, interval) {
        this.callback = callback;
        this.interval = interval;
        this.lastRun = localStorage.getItem('lastIntervalRun') || Date.now();
        this.isRunning = false;
        
        this.init();
    }
    
    init() {
        // Run immediately
        this.run();
        
        // Set up interval
        this.startInterval();
        
        // Listen for visibility changes
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.catchUp();
            }
        });
        
        // Listen for online/offline events
        window.addEventListener('online', () => {
            this.catchUp();
        });
    }
    
    startInterval() {
        this.isRunning = true;
        this.intervalId = setInterval(() => {
            this.run();
        }, this.interval);
    }
    
    run() {
        this.callback();
        this.lastRun = Date.now();
        localStorage.setItem('lastIntervalRun', this.lastRun);
    }
    
    catchUp() {
        const now = Date.now();
        const missedRuns = Math.floor((now - this.lastRun) / this.interval);
        
        if (missedRuns > 0) {
            console.log(`Catching up on ${missedRuns} missed intervals`);
            for (let i = 0; i < missedRuns; i++) {
                this.run();
            }
        }
    }
}