/**
 * SSL Configuration for RefereeX PWA Server
 * 
 * This file contains all SSL-related configuration options.
 * Modify these settings according to your needs.
 */

module.exports = {
    // SSL Certificate Paths
    certificates: {
        // Paths to SSL certificates (relative to this file)
        certPath: '../ssl/refereex.crt',
        keyPath: '../ssl/refereex.key',
        
        // Alternative paths for different environments
        production: {
            certPath: '../ssl/production/cert.pem',
            keyPath: '../ssl/production/key.pem'
        },
        
        development: {
            certPath: '../ssl/development/cert.pem',
            keyPath: '../ssl/development/key.pem'
        }
    },
    
    // Auto-generation settings
    autoGenerate: {
        enabled: true,                    // Enable/disable auto-generation
        forceRegenerate: false,           // Force regeneration even if certificates exist
        validityDays: 365,               // Certificate validity in days
        keySize: 2048,                   // RSA key size (2048 or 4096 recommended)
        
        // Self-signed certificate details
        details: {
            country: 'IL',               // Country code (ISO 3166-1 alpha-2)
            state: 'Israel',             // State/Province
            locality: 'Tel Aviv',        // City/Locality
            organization: 'RefereeX',    // Organization name
            organizationalUnit: 'Development', // Organizational unit
            commonName: 'localhost',     // Common name (domain)
            emailAddress: 'dev@refereex.com', // Email address
            subjectAltNames: [           // Subject Alternative Names
                'localhost',
                '127.0.0.1',
                '*.localhost'
            ]
        }
    },
    
    // Server ports
    ports: {
        http: 8082,                      // HTTP port
        https: 8443                      // HTTPS port
    },
    
    // Security settings
    security: {
        // HSTS (HTTP Strict Transport Security)
        hsts: {
            enabled: true,
            maxAge: 31536000,            // 1 year in seconds
            includeSubDomains: true,
            preload: false
        },
        
        // Security headers
        headers: {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Referrer-Policy': 'strict-origin-when-cross-origin'
        }
    },
    
    // Development settings
    development: {
        // Allow HTTP fallback in development
        allowHttpFallback: true,
        
        // Show detailed SSL information
        verboseSSL: true,
        
        // Auto-reload certificates on change
        autoReload: false
    },
    
    // Production settings
    production: {
        // Require HTTPS in production
        requireHTTPS: true,
        
        // Redirect HTTP to HTTPS
        redirectHTTP: true,
        
        // Strict SSL validation
        strictSSL: true
    }
};
