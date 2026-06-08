#!/usr/bin/env node

/**
 * Development Server for RefPortal PWA with Vite Plugin PWA
 * 
 * This server provides:
 * - Vite development server with HMR
 * - PWA auto-refresh functionality
 * - HTTPS support for PWA features
 * - Push notification server integration
 */

import { createServer } from 'vite';
import { resolve } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { readFileSync, existsSync } from 'fs';
import { execSync } from 'child_process';

// Note: PWA_CONFIG is a CommonJS module, so we need to handle it differently
// import { PWA_CONFIG } from './js/pwa-config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const DEFAULT_PORT = 3000;
const DEFAULT_HOST = 'localhost';

// SSL Configuration
const SSL_CONFIG = {
    // Paths to SSL certificates
    certPath: resolve(__dirname, '../ssl/pwa-dev.refereex.com.fullchain.pem'),
    keyPath: resolve(__dirname, '../ssl/pwa-dev.refereex.com.privkey.pem'),
    certPathLocal: resolve(__dirname, './ssl/pwa-dev.refereex.com.fullchain.pem'),
    keyPathLocal: resolve(__dirname, './ssl/pwa-dev.refereex.com.privkey.pem'),
    
    // Auto-generate self-signed certificates if none exist
    autoGenerate: true,
    
    // Certificate details for self-signed generation
    certDetails: {
        country: 'IL',
        state: 'Israel',
        locality: 'Tel Aviv',
        organization: 'RefereeX',
        organizationalUnit: 'Development',
        commonName: 'localhost',
        emailAddress: 'dev@refereex.com'
    }
};

class RefPortalDevServer {
    constructor(options = {}) {
        this.options = {
            port: options.port || DEFAULT_PORT,
            host: options.host || DEFAULT_HOST,
            https: options.https || false,
            open: options.open !== false,
            ...options
        };
        
        this.server = null;
        this.isRunning = false;
        this.sslConfig = null;
    }
    
    async start() {
        try {
            console.log('🚀 Starting RefPortal PWA Development Server...');
            
            // Setup SSL if HTTPS is enabled
            if (this.options.https) {
                await this.setupSSL();
            }
            
            // Create Vite server
            this.server = await createServer({
                configFile: resolve(__dirname, 'vite.config.js'),
                server: {
                    port: this.options.port,
                    host: this.options.host,
                    https: this.sslConfig || this.options.https,
                    open: this.options.open ? `http${this.options.https ? 's' : ''}://${this.options.host}:${this.options.port}` : false,
                    cors: true
                }
            });
            
            // Add middleware for root path redirect
            this.server.middlewares.use('/', (req, res, next) => {
                if (req.url === '/' || req.url === '/index.htmlllll') {
                    res.writeHead(302, { 'Location': '/refportal-pwa.html' });
                    res.end();
                } else {
                    next();
                }
            });
            
            // Start the server
            await this.server.listen();
            
            this.isRunning = true;
            await this.logServerInfo();
            this.setupGracefulShutdown();
            
        } catch (error) {
            console.error('❌ Failed to start development server:', error);
            process.exit(1);
        }
    }
    
    async setupSSL() {
        console.log('🔐 Setting up SSL configuration...');
        
        // Check if SSL certificates exist
        if (this.checkSSLCertificates()) {
            console.log('✅ SSL certificates found');
            this.sslConfig = {
                cert: readFileSync(SSL_CONFIG.certPath),
                key: readFileSync(SSL_CONFIG.keyPath)
            };
        } else if (SSL_CONFIG.autoGenerate) {
            console.log('⚠️ SSL certificates not found, attempting to generate...');
            if (await this.generateSelfSignedCertificates()) {
                this.sslConfig = {
                    cert: readFileSync(SSL_CONFIG.certPath),
                    key: readFileSync(SSL_CONFIG.keyPath)
                };
            } else {
                console.log('⚠️ SSL certificate generation failed, falling back to HTTP');
                this.options.https = false;
            }
        } else {
            console.log('⚠️ SSL certificates not found and auto-generation disabled');
            this.options.https = false;
        }
    }
    
    checkSSLCertificates() {
        // Check primary paths
        const certExists = existsSync(SSL_CONFIG.certPath);
        const keyExists = existsSync(SSL_CONFIG.keyPath);
        
        if (certExists && keyExists) {
            console.log(`✅ Found SSL certificates at: ${SSL_CONFIG.certPath}`);
            return true;
        }
        
        // Try local paths
        const certExistsLocal = existsSync(SSL_CONFIG.certPathLocal);
        const keyExistsLocal = existsSync(SSL_CONFIG.keyPathLocal);
        
        if (certExistsLocal && keyExistsLocal) {
            console.log(`✅ Found SSL certificates at: ${SSL_CONFIG.certPathLocal}`);
            SSL_CONFIG.certPath = SSL_CONFIG.certPathLocal;
            SSL_CONFIG.keyPath = SSL_CONFIG.keyPathLocal;
            return true;
        }
        
        console.log(`⚠️ SSL certificates not found at:`);
        console.log(`   - ${SSL_CONFIG.certPath}`);
        console.log(`   - ${SSL_CONFIG.certPathLocal}`);
        
        return false;
    }
    
    async generateSelfSignedCertificates() {
        try {
            console.log('🔐 Generating self-signed SSL certificates...');
            
            // Create ssl directory if it doesn't exist
            const sslDir = resolve(__dirname, '../ssl');
            if (!existsSync(sslDir)) {
                execSync(`mkdir -p "${sslDir}"`, { stdio: 'inherit' });
                console.log(`📁 Created SSL directory: ${sslDir}`);
            }
            
            // Generate private key
            const keyCommand = `openssl genrsa -out "${SSL_CONFIG.keyPath}" 2048`;
            execSync(keyCommand, { stdio: 'inherit' });
            console.log('✅ Private key generated');
            
            // Generate certificate signing request
            const csrPath = resolve(sslDir, 'cert.csr');
            const csrCommand = `openssl req -new -key "${SSL_CONFIG.keyPath}" -out "${csrPath}" -subj "/C=${SSL_CONFIG.certDetails.country}/ST=${SSL_CONFIG.certDetails.state}/L=${SSL_CONFIG.certDetails.locality}/O=${SSL_CONFIG.certDetails.organization}/OU=${SSL_CONFIG.certDetails.organizationalUnit}/CN=${SSL_CONFIG.certDetails.commonName}/emailAddress=${SSL_CONFIG.certDetails.emailAddress}"`;
            execSync(csrCommand, { stdio: 'inherit' });
            console.log('✅ Certificate signing request generated');
            
            // Generate self-signed certificate
            const certCommand = `openssl x509 -req -in "${csrPath}" -signkey "${SSL_CONFIG.keyPath}" -out "${SSL_CONFIG.certPath}" -days 365`;
            execSync(certCommand, { stdio: 'inherit' });
            console.log('✅ Self-signed certificate generated');
            
            // Clean up CSR file
            execSync(`rm "${csrPath}"`, { stdio: 'inherit' });
            console.log('🧹 Cleaned up temporary files');
            
            // Set proper permissions
            execSync(`chmod 600 "${SSL_CONFIG.keyPath}"`, { stdio: 'inherit' });
            execSync(`chmod 644 "${SSL_CONFIG.certPath}"`, { stdio: 'inherit' });
            console.log('🔒 Set proper file permissions');
            
            return true;
        } catch (error) {
            console.error('❌ Error generating SSL certificates:', error.message);
            console.log('💡 Make sure OpenSSL is installed on your system');
            console.log('   - macOS: brew install openssl');
            console.log('   - Ubuntu/Debian: sudo apt-get install openssl');
            console.log('   - Windows: Download from https://slproweb.com/products/Win32OpenSSL.html');
            return false;
        }
    }
    
    async logServerInfo() {
        const protocol = this.options.https ? 'https' : 'http';
        const url = `${protocol}://${this.options.host}:${this.options.port}`;
        
        console.log('\n✅ RefPortal PWA Development Server is running!');
        console.log(`📍 Local:   ${url}`);
        console.log(`📍 Network: ${protocol}://${await this.getNetworkIP()}:${this.options.port}`);
        
        if (this.options.https) {
            console.log('\n🔐 SSL Configuration:');
            if (this.sslConfig) {
                console.log('   • HTTPS enabled with SSL certificates');
                console.log('   • PWA features fully supported');
                if (SSL_CONFIG.certPath.includes('self-signed') || SSL_CONFIG.certPath.includes('localhost')) {
                    console.log('   ⚠️  Using self-signed certificates (browser warnings expected)');
                }
            } else {
                console.log('   ⚠️  HTTPS requested but SSL setup failed');
            }
        } else {
            console.log('\n⚠️  HTTP Mode:');
            console.log('   • Some PWA features may not work');
            console.log('   • Use --https flag for full PWA support');
        }
        
        console.log('\n🔧 Features:');
        console.log('   • Hot Module Replacement (HMR)');
        console.log('   • PWA Auto-Refresh');
        console.log('   • Service Worker Updates');
        console.log('   • Push Notifications');
        console.log('\n⌨️  Commands:');
        console.log('   • Press "r" + Enter to force reload');
        console.log('   • Press "u" + Enter to check for updates');
        console.log('   • Press "c" + Enter to clear cache');
        console.log('   • Press "q" + Enter to quit');
        console.log('   • Press Ctrl+C to quit\n');
    }
    
    async getNetworkIP() {
        const { networkInterfaces } = await import('os');
        const nets = networkInterfaces();
        
        for (const name of Object.keys(nets)) {
            for (const net of nets[name]) {
                if (net.family === 'IPv4' && !net.internal) {
                    return net.address;
                }
            }
        }
        
        return 'localhost';
    }
    
    setupGracefulShutdown() {
        // Handle Ctrl+C
        process.on('SIGINT', () => {
            console.log('\n🛑 Shutting down development server...');
            this.stop();
        });
        
        // Handle termination
        process.on('SIGTERM', () => {
            console.log('\n🛑 Shutting down development server...');
            this.stop();
        });
        
        // Handle uncaught exceptions
        process.on('uncaughtException', (error) => {
            console.error('❌ Uncaught Exception:', error);
            this.stop();
        });
        
        // Handle unhandled rejections
        process.on('unhandledRejection', (reason, promise) => {
            console.error('❌ Unhandled Rejection at:', promise, 'reason:', reason);
            this.stop();
        });
    }
    
    async stop() {
        if (this.server && this.isRunning) {
            try {
                await this.server.close();
                this.isRunning = false;
                console.log('✅ Development server stopped');
                process.exit(0);
            } catch (error) {
                console.error('❌ Error stopping server:', error);
                process.exit(1);
            }
        }
    }
}

// CLI Interface
function parseArgs() {
    const args = process.argv.slice(2);
    const options = {};
    
    for (let i = 0; i < args.length; i++) {
        const arg = args[i];
        
        switch (arg) {
            case '--port':
            case '-p':
                options.port = parseInt(args[++i]) || DEFAULT_PORT;
                break;
            case '--host':
            case '-h':
                options.host = args[++i] || DEFAULT_HOST;
                break;
            case '--https':
                options.https = true;
                // Check if next argument is a number (port)
                if (i + 1 < args.length && !isNaN(parseInt(args[i + 1]))) {
                    options.port = parseInt(args[++i]);
                }
                break;
            case '--no-open':
                options.open = false;
                break;
            case '--help':
                showHelp();
                process.exit(0);
                break;
        }
    }
    
    return options;
}

function showHelp() {
    console.log(`
RefPortal PWA Development Server

Usage: node dev-server.js [options]

Options:
  -p, --port <number>    Port to run the server on (default: 3000)
  -h, --host <string>    Host to run the server on (default: localhost)
  --https                Enable HTTPS (required for PWA features)
  --no-open              Don't open browser automatically
  --help                 Show this help message

SSL Configuration:
  The server will automatically:
  • Look for existing SSL certificates in ../ssl/ directory
  • Generate self-signed certificates if none exist
  • Fall back to HTTP if SSL setup fails
  • Use OpenSSL for certificate generation

Examples:
  node dev-server.js                    # Start on localhost:3000 (HTTP)
  node dev-server.js --port 8080        # Start on port 8080 (HTTP)
  node dev-server.js --https            # Start with HTTPS (auto-generate SSL)
  node dev-server.js --host 0.0.0.0     # Start on all interfaces
  node dev-server.js --https --port 8443 # HTTPS on port 8443

SSL Certificate Paths:
  • Certificate: ../ssl/pwa-dev.refereex.com.fullchain.pem
  • Private Key: ../ssl/pwa-dev.refereex.com.privkey.pem
  • Local fallback: ./ssl/ directory

Note: Self-signed certificates will show browser security warnings.
Accept the warnings to proceed with PWA development.
`);
}

// Start the server
async function main() {
    const options = parseArgs();
    const server = new RefPortalDevServer(options);
    
    try {
        await server.start();
    } catch (error) {
        console.error('❌ Failed to start server:', error);
        process.exit(1);
    }
}

// Run if this file is executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
    main();
}

export default RefPortalDevServer;
