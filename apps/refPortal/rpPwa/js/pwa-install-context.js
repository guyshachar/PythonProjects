/**
 * Detect installed PWA vs browser tab and provide Hebrew install steps per client.
 */

const isIOSDevice =
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

export function isRunningAsInstalledPWA() {
    if (typeof window === 'undefined') return false;
    try {
        if (window.navigator.standalone === true) return true;
        const mq = window.matchMedia.bind(window);
        return (
            mq('(display-mode: standalone)').matches ||
            mq('(display-mode: fullscreen)').matches ||
            mq('(display-mode: minimal-ui)').matches
        );
    } catch {
        return false;
    }
}

export function getPWAClientProfile() {
    const ua = navigator.userAgent || '';
    let os = 'other';
    if (/Android/i.test(ua)) os = 'android';
    else if (isIOSDevice) os = 'ios';
    else if (/Win/i.test(navigator.platform || '')) os = 'windows';
    else if (/Mac/i.test(navigator.platform || '')) os = 'mac';
    else if (/Linux/i.test(navigator.platform || '')) os = 'linux';

    let browser = 'other';
    if (/EdgiOS|Edg\/|EdgA/i.test(ua)) browser = /EdgiOS/i.test(ua) ? 'edge_ios' : 'edge';
    else if (/OPR\/|Opera/i.test(ua)) browser = 'opera';
    else if (/SamsungBrowser/i.test(ua)) browser = 'samsung';
    else if (/Firefox\/|FxiOS/i.test(ua)) browser = /FxiOS/i.test(ua) ? 'firefox_ios' : 'firefox';
    else if (/CriOS/i.test(ua)) browser = 'chrome_ios';
    else if (/Chrome\//i.test(ua) && !/Edg/i.test(ua)) browser = 'chrome';
    else if (isIOSDevice && /Safari/i.test(ua) && !/CriOS|FxiOS/i.test(ua)) browser = 'safari_ios';
    else if (/Safari/i.test(ua) && !/Chrome|CriOS|Android/i.test(ua)) browser = 'safari';

    return { os, browser, ua, isIOSDevice };
}

/**
 * @returns {{ title: string, steps: string[] }}
 */
export function getHebrewInstallInstructions(profile) {
    const { os, browser } = profile;

    if (os === 'ios') {
        if (browser === 'chrome_ios' || browser === 'edge_ios' || browser === 'firefox_ios') {
            return {
                title: 'התקנה באייפון/אייפד',
                steps: [
                    'פתחו את התפריט (⋯) בפינה התחתונה או העליונה.',
                    'בחרו בשיתוף / Share (הסמל עם החץ למעלה).',
                    'גללו ובחרו "הוסף למסך הבית" / Add to Home Screen.',
                    'אשרו את השם RefereeX ולחצו "הוסף".'
                ]
            };
        }
        return {
            title: 'התקנה באייפון/אייפד (ספארי)',
            steps: [
                'לחצו על כפתור השיתוף Share (ריבוע עם חץ למעלה) בסרגל התחתון.',
                'גללו ובחרו "הוסף למסך הבית".',
                'אשרו את השם RefereeX ולחצו "הוסף".',
                'האפליקציה תופיע במסך הבית ותיפתח במסך מלא.'
            ]
        };
    }

    if (os === 'android') {
        if (browser === 'samsung') {
            return {
                title: 'התקנה באנדרואיד (Samsung Internet)',
                steps: [
                    'לחצו על תפריט ההמבורגר או על שלוש הנקודות.',
                    'בחרו "הוסף עמוד ל-" או "התקן אפליקציה" אם מופיע.',
                    'אשרו "הוסף" / "התקן" — האייקון יתווסף למסך הבית.'
                ]
            };
        }
        if (browser === 'firefox' || browser === 'firefox_ios') {
            return {
                title: 'התקנה באנדרואיד',
                steps: [
                    'בפיירפוקס תמיכת התקנה מוגבלת. מומלץ לפתוח את האתר בכרום.',
                    'בכרום: תפריט ⋮ → "התקן אפליקציה" או "הוסף למסך הבית".',
                    'אשרו את ההתקנה — יווצר קיצור דרך כמו אפליקציה.'
                ]
            };
        }
        return {
            title: 'התקנה באנדרואיד (כרום ודפדפנים דומים)',
            steps: [
                'לחצו על תפריט שלוש הנקודות ⋮ בפינה העליונה.',
                'בחרו "התקן אפליקציה" או "הוסף למסך הבית" (הניסוח משתנה לפי גרסה).',
                'אשרו — האפליקציה תופיע במסך הבית עם אייקון RefereeX.'
            ]
        };
    }

    if (browser === 'edge') {
        return {
            title: 'התקנה במחשב (Microsoft Edge)',
            steps: [
                'לחצו על ⋯ בתפריט הימני העליון.',
                'בחרו "אפליקציות" → "התקן דף זה כאפליקציה" (או "התקן RefereeX").',
                'אשרו בחלון — תיווצר קיצור באפליקציות ובתפריט התחל.'
            ]
        };
    }

    if (browser === 'chrome' || browser === 'opera') {
        return {
            title: 'התקנה במחשב (כרום / אופרה)',
            steps: [
                'בשורת הכתובת, חפשו אייקון התקנה (⊕ או מחשב עם חץ) ולחצו עליו, או',
                'פתחו את תפריט ⋮ → "התקן RefereeX..." / "Install RefereeX".',
                'אשרו — האפליקציה תיפתח בחלון נפרד ללא סרגל כתובות.'
            ]
        };
    }

    if (browser === 'safari' && os === 'mac') {
        return {
            title: 'התקנה ב-macOS (ספארי)',
            steps: [
                'בתפריט הקובץ: "Add to Dock" אם מוצע (macOS Sonoma ומעלה), או',
                'תפריט File → "Add to Dock" עבור אתרים הנתמכים כאפליקציה.',
                'אם האפשרות לא מופיעה, השתמשו בכרום או ב-Edge להתקנת ה-PWA.'
            ]
        };
    }

    if (browser === 'firefox') {
        return {
            title: 'התקנה בדפדפן',
            steps: [
                'בפיירפוקס התקנת PWA מוגבלת. מומלץ Microsoft Edge או Google Chrome.',
                'פתחו את האתר בדפדפן הנתמך וחפשו באייקון בשורת הכתובת או בתפריט "התקן".'
            ]
        };
    }

    return {
        title: 'התקנת RefereeX',
        steps: [
            'חפשו בשורת הכתובת אייקון "התקן" או בתפריט הדפדפן (⋮ או ⋯) אפשרות להתקין אפליקציה.',
            'אם לא מוצאים, בטלפון: תפריט → הוסף למסך הבית / התקן אפליקציה.',
            'במחשב: מומלץ Chrome או Edge — תפריט → התקן אפליקציה / Install.'
        ]
    };
}
