/**
 * PDF Report Service for RefereeX PWA
 * Handles PDF generation and email sending for game reports
 */
// Dynamic configuration will be loaded from environment
import { refreshTokenService } from './refreshTokenService.js';
import { configService } from './config-service.js';
import { envLoader } from './environment-loader.js';

export class ReportsService {
    constructor(sendLog) {
        this.configService = configService;
        this.envLoader = envLoader;
        this.recipients = this.getConfig('OPEN_REPORTS_EMAILS') || [
            'openreports@refereex.com'
        ];
        this.sendLog = sendLog;
        this.refreshTokenService = refreshTokenService;
    }

    /**
     * Get configuration value with fallback
     */
    getConfig(key, defaultValue = null) {
        // Try to get from global config service first
        if (this.configService && this.configService.isLoaded()) {
            return this.configService.get(key, defaultValue);
        }
        
        // Fallback to environment loader
        if (this.envLoader && this.envLoader.isLoaded()) {
            const env = this.envLoader.getAll();
            return this.getNestedValue(env, key, defaultValue);
        }
        
        // Final fallback to default values
        return this.getDefaultConfigValue(key, defaultValue);
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

    /**
     * Get default configuration value
     */
    getDefaultConfigValue(key, defaultValue = null) {
        const defaults = {
            'OPEN_REPORTS_EMAILS': ['openreports@refereex.com'],
            'ENDPOINTS.SEND_REPORT_EMAIL': '/api/pwa/sendReportEmail'
        };
        
        return defaults[key] || defaultValue;
    }

    /**
     * Send email through server API
     * @param {Object} reportData - The report data
     * @returns {Promise<Object>} - Email sending result
     */
    async sendEmailViaServer(reportData) {
        try {
            console.log('📧 Sending email via server API...');
            
            // Prepare the API request
            const apiUrl = this.getConfig('ENDPOINTS.SEND_REPORT_EMAIL');
            const requestBody = {
                gameId: reportData.gameId,
                gameTitle: reportData.gameTitle,
                gameDate: reportData.gameDate,
                gameTime: reportData.gameTime,
                league: reportData.league,
                field: reportData.field,
                role: reportData.role,
                status: reportData.status,
                categories: reportData.categories,
                details: reportData.details,
                reporter: reportData.reporter
            };

            this.sendLog('email', `Sending report via server API to ${this.recipients.join(', ')}`);

            // Make the API request
            const response = await this.refreshTokenService.makeApiRequest({
                url: apiUrl,
                options: {
                    method: 'POST',
                    body: JSON.stringify(requestBody)
                }
            });

            const result = await response.json();

            if (response.ok && result.success) {
                console.log('✅ Email sent successfully via server API');
                this.sendLog('email', `Email sent successfully to: ${result.recipients?.join(', ') || 'recipients'}`);
                
                return {
                    success: true,
                    message: 'הדו״ח נשלח בהצלחה בדואר אלקטרוני',
                    recipients: result.recipients || this.recipients,
                    method: 'server_api'
                };
            } else {
                console.error('❌ Server API email failed:', result);
                this.sendLog('email', `Server API email failed: ${result.error || 'Unknown error'}`);
                
                // Fallback to client-side email
                console.log('🔄 Falling back to client-side email...');
                //return await this.sendEmail(reportData, `game-report-${reportData.gameId}.pdf`);
            }
        } catch (error) {
            console.error('❌ Error sending email via server API:', error);
            this.sendLog('email', `Server API error: ${error.message}`);
            
            // Fallback to client-side email
            console.log('🔄 Falling back to client-side email...');
            return await this.sendEmail(reportData, `game-report-${reportData.gameId}.pdf`);
        }
    }

    /**
     * Create email body content
     * @param {Object} reportData - The report data
     * @returns {string} - Email body text
     */
    createEmailBody(reportData) {
        // Get current domain for image URLs
        const currentDomain = window.location?.origin || 'https://refereex.com';
        
        let body = `דו״ח תיקון משחק\n`;
        body += `==================\n\n`;
        
        // Add logos section
        body += `🏆 RefereeX - מערכת ניהול שופטים ומשחקים\n`;
        body += `⚽ ההתאחדות לכדורגל בישראל\n\n`;
        
        body += `משחק: ${reportData.gameTitle}\n`;
        body += `תאריך המשחק: ${reportData.gameDate}\n`;
        body += `ליגה: ${reportData.league}\n`;
        body += `מגרש: ${reportData.field}\n`;
        body += `תפקיד: ${reportData.role}\n`;
        body += `מגיש הדו״ח: ${reportData.reporter}\n`;
        body += `תאריך הדו״ח: ${reportData.reportDatetime}\n\n`;
        
        body += `קטגוריות התיקון:\n`;
        body += `================\n`;
        
        const categoryNames = {
            goals: 'תיקון מבקיעי שערים',
            yellow_cards: 'תיקון רישום כרטיסים צהובים',
            red_cards: 'תיקון רישום כרטיסים אדומים',
            incidents: 'תיקון רישום תקריות',
            result: 'תיקון רישום תוצאה',
            travels: 'תיקון רישום נסיעות',
            players: 'תיקון רישום שחקנים',
            substitutes: 'תיקון מחליפים',
            manual_lists: 'הוספת רשימות ידניות',
            other: 'אחר'
        };
        
        reportData.categories.forEach(category => {
            const categoryName = categoryNames[category] || category;
            const details = reportData.details[category] || '';
            body += `\n${categoryName}:\n`;
            body += `${details}\n`;
            body += `${'='.repeat(categoryName.length + 1)}\n`;
        });
        
        body += `\n\nהדו״ח המלא מצורף כקובץ PDF.\n`;
        body += `תודה,\n${reportData.reporter}\n\n`;
        
        // Add footer with logos
        body += `---\n`;
        body += `🏆 RefereeX - מערכת ניהול שופטים ומשחקים\n`;
        body += `⚽ ההתאחדות לכדורגל בישראל\n`;
        body += `© ${new Date().getFullYear()} RefereeX\n\n`;
        body += `הערה: גרסה מעוצבת של הודעה זו זמינה ב-HTML עם לוגואים מלאים.`;
        
        return body;
    }

    /**
     * Create HTML email body content with logos
     * @param {Object} reportData - The report data
     * @returns {string} - HTML email body content
     */
    createHTMLEmailBody(reportData) {
        // Get current domain for image URLs
        const currentDomain = window.location?.origin || 'https://refereex.com';
        
        let htmlBody = `
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { font-family: Arial, sans-serif; direction: rtl; text-align: right; }
                .header { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .logo-section { display: inline-block; margin: 0 10px; vertical-align: middle; }
                .logo-section img { height: 40px; width: auto; }
                .title { font-size: 18px; font-weight: bold; margin: 10px 0; }
                .game-info { background: #e9ecef; padding: 15px; border-radius: 5px; margin: 15px 0; }
                .categories { margin: 20px 0; }
                .category { margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 5px; }
                .footer { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-top: 20px; text-align: center; }
                .footer-logo { height: 30px; width: auto; margin: 0 10px; }
            </style>
        </head>
        <body>
            <div class="header">
                <div style="text-align: center;">
                    <div class="logo-section">
                        <img src="${currentDomain}/images/RefereeX.png" alt="RefereeX Logo">
                    </div>
                    <div class="logo-section">
                        <img src="${currentDomain}/images/the-israel-football-association-logo.png" alt="Israel Football Association Logo">
                    </div>
                </div>
                <div class="title">דו״ח תיקון משחק</div>
            </div>
            
            <div class="game-info">
                <p><strong>משחק:</strong> ${reportData.gameTitle}</p>
                <p><strong>תאריך המשחק:</strong> ${reportData.gameDate}</p>
                <p><strong>ליגה:</strong> ${reportData.league}</p>
                <p><strong>מגרש:</strong> ${reportData.field}</p>
                <p><strong>תפקיד:</strong> ${reportData.role}</p>
                <p><strong>מגיש הדו״ח:</strong> ${reportData.reporter}</p>
                <p><strong>תאריך הדו״ח:</strong> ${reportData.reportDatetime}</p>
            </div>
            
            <div class="categories">
                <h3>קטגוריות התיקון:</h3>
        `;
        
        const categoryNames = {
            goals: 'תיקון מבקיעי שערים',
            yellow_cards: 'תיקון רישום כרטיסים צהובים',
            red_cards: 'תיקון רישום כרטיסים אדומים',
            incidents: 'תיקון רישום תקריות',
            result: 'תיקון רישום תוצאה',
            travels: 'תיקון רישום נסיעות',
            players: 'תיקון רישום שחקנים',
            substitutes: 'תיקון מחליפים',
            manual_lists: 'הוספת רשימות ידניות',
            other: 'אחר'
        };
        
        reportData.categories.forEach(category => {
            const categoryName = categoryNames[category] || category;
            const details = reportData.details[category] || '';
            htmlBody += `
                <div class="category">
                    <strong>${categoryName}:</strong><br>
                    ${details}
                </div>
            `;
        });
        
        htmlBody += `
            </div>
            
            <p><strong>הדו״ח המלא מצורף כקובץ PDF.</strong></p>
            <p>תודה,<br>${reportData.reporter}</p>
            
            <div class="footer">
                <div class="logo-section">
                    <img src="${currentDomain}/images/RefereeX.png" alt="RefereeX Logo" class="footer-logo">
                </div>
                <div class="logo-section">
                    <img src="${currentDomain}/images/the-israel-football-association-logo.png" alt="Israel Football Association Logo" class="footer-logo">
                </div>
                <p>© ${new Date().getFullYear()} RefereeX - מערכת ניהול שופטים ומשחקים</p>
            </div>
        </body>
        </html>
        `;
        
        return htmlBody;
    }

    /**
     * Create mailto link for email sending
     * @param {string} subject - Email subject
     * @param {string} body - Email body
     * @param {string} filename - PDF filename
     * @returns {string} - Mailto link
     */
    createMailtoLink(subject, body, filename) {
        const recipients = this.recipients.join(',');
        const encodedSubject = encodeURIComponent(subject);
        const encodedBody = encodeURIComponent(body);
        
        // Note: mailto doesn't support file attachments directly
        // The user will need to manually attach the downloaded file
        return `mailto:${recipients}?subject=${encodedSubject}&body=${encodedBody}`;
    }

    /**
     * Generate and send report
     * @param {Object} reportData - The report data
     * @returns {Promise<Object>} - Complete process result
     */
    async generateAndSendReport(reportData) {
        try {
            console.log('📋 Generating and sending report...');
            
            // Try to send email via server API first
            try {
                const emailResult = await this.sendEmailViaServer(reportData);
                
                if (emailResult.success) {
                    console.log('✅ Report sent successfully via server API');
                    return {
                        success: true,
                        message: emailResult.message,
                        recipients: emailResult.recipients,
                        method: 'server_api',
                        instructions: 'הדו״ח נשלח בהצלחה בדואר אלקטרוני'
                    };
                }
            } catch (serverError) {
                console.warn('⚠️ Server API failed, falling back to client-side method:', serverError);
            }
            
            return null;
        } catch (error) {
            console.error('❌ Error in generateAndSendReport:', error);
            throw error;
        }
    }


    /**
     * Add recipient to the list
     * @param {string} email - Email address to add
     */
    addRecipient(email) {
        if (email && !this.recipients.includes(email)) {
            this.recipients.push(email);
        }
    }

    /**
     * Remove recipient from the list
     * @param {string} email - Email address to remove
     */
    removeRecipient(email) {
        const index = this.recipients.indexOf(email);
        if (index > -1) {
            this.recipients.splice(index, 1);
        }
    }

    /**
     * Get current recipients list
     * @returns {Array<string>} - List of recipients
     */
    getRecipients() {
        return [...this.recipients];
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ReportsService;
}

