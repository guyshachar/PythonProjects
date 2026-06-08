/**
 * RefereeX Apple Watch PWA
 * Simplified version optimized for Apple Watch screen size
 */

class RefPortalWatch {
    constructor() {
        this.currentSection = 'games';
        this.gamesData = [];
        this.reviewsData = [];
        this.isOnline = navigator.onLine;
        
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupNetworkMonitoring();
        this.loadInitialData();
        this.updateLastUpdateTime();
        
        // Update time every minute
        setInterval(() => this.updateLastUpdateTime(), 60000);
    }

    setupEventListeners() {
        // Navigation
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const section = e.target.dataset.section;
                this.switchSection(section);
            });
        });

        // Refresh buttons
        document.getElementById('refreshGames').addEventListener('click', () => {
            this.loadGames();
        });

        document.getElementById('refreshReviews').addEventListener('click', () => {
            this.loadReviews();
        });

        // Filters
        document.getElementById('gamesFilter').addEventListener('change', (e) => {
            this.filterGames(e.target.value);
        });

        document.getElementById('reviewsFilter').addEventListener('change', (e) => {
            this.filterReviews(e.target.value);
        });

        // List item clicks
        document.addEventListener('click', (e) => {
            if (e.target.closest('.watch-item')) {
                this.handleItemClick(e.target.closest('.watch-item'));
            }
        });
    }

    setupNetworkMonitoring() {
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.updateConnectionStatus();
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.updateConnectionStatus();
        });
    }

    switchSection(section) {
        // Update navigation
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelector(`[data-section="${section}"]`).classList.add('active');

        // Update content
        document.querySelectorAll('.content-section').forEach(sec => {
            sec.classList.remove('active');
        });
        document.getElementById(section).classList.add('active');

        this.currentSection = section;

        // Load data if not already loaded
        if (section === 'games' && this.gamesData.length === 0) {
            this.loadGames();
        } else if (section === 'reviews' && this.reviewsData.length === 0) {
            this.loadReviews();
        }
    }

    async loadInitialData() {
        // Load games by default
        await this.loadGames();
    }

    async loadGames() {
        const gamesList = document.getElementById('gamesList');
        gamesList.innerHTML = '<div class="loading">טוען משחקים...</div>';

        try {
            // Simulate API call - replace with actual API endpoint
            const response = await this.fetchData('/api/games');
            this.gamesData = response || this.getMockGames();
            this.renderGames();
        } catch (error) {
            console.error('Error loading games:', error);
            this.gamesData = this.getMockGames();
            this.renderGames();
        }
    }

    async loadReviews() {
        const reviewsList = document.getElementById('reviewsList');
        reviewsList.innerHTML = '<div class="loading">טוען ביקורות...</div>';

        try {
            // Simulate API call - replace with actual API endpoint
            const response = await this.fetchData('/api/reviews');
            this.reviewsData = response || this.getMockReviews();
            this.renderReviews();
        } catch (error) {
            console.error('Error loading reviews:', error);
            this.reviewsData = this.getMockReviews();
            this.renderReviews();
        }
    }

    async fetchData(url) {
        if (!this.isOnline) {
            throw new Error('No internet connection');
        }

        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
            },
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();
    }

    renderGames() {
        const gamesList = document.getElementById('gamesList');
        const filter = document.getElementById('gamesFilter').value;
        
        let filteredGames = this.gamesData;
        if (filter) {
            filteredGames = this.gamesData.filter(game => {
                if (filter === 'active') return game.status === 'active';
                if (filter === 'completed') return game.status === 'completed';
                return true;
            });
        }

        if (filteredGames.length === 0) {
            gamesList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚽</div>
                    <div>אין משחקים זמינים</div>
                </div>
            `;
            return;
        }

        gamesList.innerHTML = filteredGames.map(game => `
            <div class="watch-item" data-id="${game.id}" data-type="game">
                <div class="watch-item-header">
                    <h3 class="watch-item-title">${game.title}</h3>
                    <span class="watch-item-status status-${game.status}">${this.getStatusText(game.status)}</span>
                </div>
                <div class="watch-item-details">
                    ${game.league} • ${game.date}
                </div>
                <div class="watch-item-meta">
                    <span>${game.referee}</span>
                    <span>${game.time}</span>
                </div>
            </div>
        `).join('');
    }

    renderReviews() {
        const reviewsList = document.getElementById('reviewsList');
        const filter = document.getElementById('reviewsFilter').value;
        
        let filteredReviews = this.reviewsData;
        if (filter) {
            filteredReviews = this.reviewsData.filter(review => 
                review.rating.toString() === filter
            );
        }

        if (filteredReviews.length === 0) {
            reviewsList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⭐</div>
                    <div>אין ביקורות זמינות</div>
                </div>
            `;
            return;
        }

        reviewsList.innerHTML = filteredReviews.map(review => `
            <div class="watch-item" data-id="${review.id}" data-type="review">
                <div class="watch-item-header">
                    <h3 class="watch-item-title">${review.game}</h3>
                    <div class="review-rating">
                        ${this.renderStars(review.rating)}
                    </div>
                </div>
                <div class="review-text">${review.comment}</div>
                <div class="watch-item-meta">
                    <span>${review.referee}</span>
                    <span>${review.date}</span>
                </div>
            </div>
        `).join('');
    }

    renderStars(rating) {
        let stars = '';
        for (let i = 1; i <= 5; i++) {
            stars += `<span class="star ${i <= rating ? '' : 'empty'}">★</span>`;
        }
        return stars;
    }

    filterGames(filter) {
        this.renderGames();
    }

    filterReviews(filter) {
        this.renderReviews();
    }

    handleItemClick(item) {
        const id = item.dataset.id;
        const type = item.dataset.type;
        
        // Add visual feedback
        item.style.background = '#2a2a2a';
        setTimeout(() => {
            item.style.background = '';
        }, 200);

        // Handle click based on type
        if (type === 'game') {
            this.showGameDetails(id);
        } else if (type === 'review') {
            this.showReviewDetails(id);
        }
    }

    showGameDetails(gameId) {
        const game = this.gamesData.find(g => g.id === gameId);
        if (game) {
            // Simple alert for now - could be expanded to a modal
            alert(`משחק: ${game.title}\nליגה: ${game.league}\nתאריך: ${game.date}\nשופט: ${game.referee}`);
        }
    }

    showReviewDetails(reviewId) {
        const review = this.reviewsData.find(r => r.id === reviewId);
        if (review) {
            // Simple alert for now - could be expanded to a modal
            alert(`ביקורת על: ${review.game}\nדירוג: ${review.rating} כוכבים\nביקורת: ${review.comment}`);
        }
    }

    updateConnectionStatus() {
        const statusIndicator = document.getElementById('connectionStatus');
        statusIndicator.textContent = this.isOnline ? '🟢' : '🔴';
    }

    updateLastUpdateTime() {
        const lastUpdate = document.getElementById('lastUpdate');
        const now = new Date();
        const timeString = now.toLocaleTimeString('he-IL', {
            hour: '2-digit',
            minute: '2-digit'
        });
        lastUpdate.textContent = `עדכון אחרון: ${timeString}`;
    }

    getStatusText(status) {
        const statusMap = {
            'active': 'פעיל',
            'completed': 'הושלם',
            'pending': 'ממתין',
            'cancelled': 'בוטל'
        };
        return statusMap[status] || status;
    }

    // Mock data for development/testing
    getMockGames() {
        return [
            {
                id: 1,
                title: 'מכבי תל אביב - הפועל באר שבע',
                league: 'ליגת העל',
                date: '15/12/2024',
                time: '20:30',
                referee: 'יוסי כהן',
                status: 'active'
            },
            {
                id: 2,
                title: 'הפועל חיפה - בית"ר ירושלים',
                league: 'ליגת העל',
                date: '16/12/2024',
                time: '18:00',
                referee: 'דני לוי',
                status: 'pending'
            },
            {
                id: 3,
                title: 'מכבי חיפה - הפועל תל אביב',
                league: 'ליגת העל',
                date: '14/12/2024',
                time: '19:30',
                referee: 'אבי כהן',
                status: 'completed'
            }
        ];
    }

    getMockReviews() {
        return [
            {
                id: 1,
                game: 'מכבי תל אביב - הפועל באר שבע',
                rating: 5,
                comment: 'שיפוט מעולה, שליטה טובה במשחק',
                referee: 'יוסי כהן',
                date: '15/12/2024'
            },
            {
                id: 2,
                game: 'הפועל חיפה - בית"ר ירושלים',
                rating: 4,
                comment: 'שיפוט טוב, כמה החלטות שנויות במחלוקת',
                referee: 'דני לוי',
                date: '16/12/2024'
            },
            {
                id: 3,
                game: 'מכבי חיפה - הפועל תל אביב',
                rating: 3,
                comment: 'שיפוט בינוני, צריך שיפור בקבלת החלטות',
                referee: 'אבי כהן',
                date: '14/12/2024'
            }
        ];
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new RefPortalWatch();
});

// Service Worker registration for PWA functionality
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('./sw-watch.js')
            .then(registration => {
                console.log('SW registered: ', registration);
            })
            .catch(registrationError => {
                console.log('SW registration failed: ', registrationError);
            });
    });
}

