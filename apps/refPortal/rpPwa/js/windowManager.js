export class WindowManager {
    constructor() {
        this.windows = new Map(); // Store windows by ID
    }

    hiddenWindowOptions() {
        const hiddenWindow = [
            'width=1',
            'height=1',
            'left=-10000',
            'top=-10000',
            'scrollbars=no',
            'resizable=no',
            'status=no',
            'toolbar=no',
            'menubar=no',
            'location=no'
        ].join(',');
        return hiddenWindow;
    }

    // Open and store window with ID
    openWindow(id, url, options = {}, hidden = false) {
        if (hidden) {
            options = this.hiddenWindowOptions();
        }
        const windowObj = window.open(url, id, options);
        
        if (windowObj) {
            this.windows.set(id, windowObj);
            console.log(`✅ Window opened and stored with ID: ${id}`);
            return windowObj;
        }
        
        return null;
    }
    
    // Get window by ID
    getWindow(id) {
        const windowObj = this.windows.get(id);
        
        if (windowObj) {//} && !windowObj.closed) {
            return windowObj;
        } else {
            // Remove closed window from storage
            this.windows.delete(id);
            return null;
        }
    }
    
    // Check if window exists
    hasWindow(id) {
        return this.windows.has(id) && !this.windows.get(id).closed;
    }
    
    // Close window by ID
    closeWindow(id) {
        const windowObj = this.getWindow(id);
        if (windowObj) {
            windowObj.close();
            this.windows.delete(id);
            return true;
        }
        return false;
    }
}