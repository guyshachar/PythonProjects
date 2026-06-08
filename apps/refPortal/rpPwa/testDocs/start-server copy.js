const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');
const { execSync } = require('child_process');
const { PWA_CONFIG } = require('./js/pwa-config.js');

// Configuration
const ROOT_DIR = __dirname;
const PWA_DIR = __dirname;
const HTTP_PORT = process.env.PWA_HTTP_PORT || PWA_CONFIG.HTTP_PORT;
const HTTPS_PORT = process.env.PWA_HTTPS_PORT || PWA_CONFIG.HTTPS_PORT;

// SSL Configuration
const SSL_CONFIG = {
    // Paths to SSL certificates
    certPath: process.env.PWA_CERT_PATH || path.join(__dirname, '../ssl', PWA_CONFIG.SSL_FILES.cert),
    keyPath: process.env.PWA_KEY_PATH || path.join(__dirname, '../ssl', PWA_CONFIG.SSL_FILES.key),
    
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

// MIME types for common file extensions
const mimeTypes = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.eot': 'application/vnd.ms-fontobject'
};

// Check if SSL certificates exist
function checkSSLCertificates() {
    const certExists = fs.existsSync(SSL_CONFIG.certPath);
    const keyExists = fs.existsSync(SSL_CONFIG.keyPath);
    
    if (certExists && keyExists) {
        console.log('✅ SSL certificates found');
        return true;
    } else {
        console.log('⚠️ SSL certificates not found');
        if (!certExists) console.log(`  - Missing: ${SSL_CONFIG.certPath}`);
        if (!keyExists) console.log(`  - Missing: ${SSL_CONFIG.keyPath}`);
        return false;
    }
}

// Generate self-signed SSL certificates
function generateSelfSignedCertificates() {
    try {
        console.log('🔐 Generating self-signed SSL certificates...');
        
        // Create ssl directory if it doesn't exist
        const sslDir = path.dirname(SSL_CONFIG.certPath);
        if (!fs.existsSync(sslDir)) {
            fs.mkdirSync(sslDir, { recursive: true });
            console.log(`📁 Created SSL directory: ${sslDir}`);
        }
        
        // Generate private key
        const keyCommand = `openssl genrsa -out "${SSL_CONFIG.keyPath}" 2048`;
        execSync(keyCommand, { stdio: 'inherit' });
        console.log('✅ Private key generated');
        
        // Generate certificate signing request
        const csrPath = path.join(sslDir, 'cert.csr');
        const csrCommand = `openssl req -new -key "${SSL_CONFIG.keyPath}" -out "${csrPath}" -subj "/C=${SSL_CONFIG.certDetails.country}/ST=${SSL_CONFIG.certDetails.state}/L=${SSL_CONFIG.certDetails.locality}/O=${SSL_CONFIG.certDetails.organization}/OU=${SSL_CONFIG.certDetails.organizationalUnit}/CN=${SSL_CONFIG.certDetails.commonName}/emailAddress=${SSL_CONFIG.certDetails.emailAddress}"`;
        execSync(csrCommand, { stdio: 'inherit' });
        console.log('✅ Certificate signing request generated');
        
        // Generate self-signed certificate
        const certCommand = `openssl x509 -req -in "${csrPath}" -signkey "${SSL_CONFIG.keyPath}" -out "${SSL_CONFIG.certPath}" -days 365`;
        execSync(certCommand, { stdio: 'inherit' });
        console.log('✅ Self-signed certificate generated');
        
        // Clean up CSR file
        fs.unlinkSync(csrPath);
        console.log('🧹 Cleaned up temporary files');
        
        // Set proper permissions
        fs.chmodSync(SSL_CONFIG.keyPath, 0o600);
        fs.chmodSync(SSL_CONFIG.certPath, 0o644);
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

// Create HTTPS server
function createHTTPSServer() {
    try {
        const options = {
            cert: fs.readFileSync(SSL_CONFIG.certPath),
            key: fs.readFileSync(SSL_CONFIG.keyPath)
        };
        
        const httpsServer = https.createServer(options, requestHandler);
        
        httpsServer.listen(HTTPS_PORT, () => {
            console.log(`🔒 HTTPS Server running at https://localhost:${HTTPS_PORT}`);
            console.log(`📁 PWA files from: ${ROOT_DIR}`);
            console.log(`📁 Static files from: ${PWA_DIR}`);
            console.log(`🌐 PWA available at: https://localhost:${HTTPS_PORT}/refportal-pwa.html`);
            console.log(`🌐 Root available at: https://localhost:${HTTPS_PORT}/`);
            console.log(`⏹️  Press Ctrl+C to stop the server`);
        });
        
        // Handle server errors
        httpsServer.on('error', (error) => {
            console.error('HTTPS Server error:', error);
        });
    
        return httpsServer;
    } catch (error) {
        console.error('❌ Error creating HTTPS server:', error.message);
        return null;
    }
}

// Create HTTP server (fallback)
function createHTTPServer() {
    const httpServer = http.createServer(requestHandler);
    
    httpServer.listen(HTTP_PORT, () => {
        console.log(`🚀 HTTP Server running at http://localhost:${HTTP_PORT}`);
        console.log(`📁 PWA files from: ${ROOT_DIR}`);
        console.log(`📁 Static files from: ${PWA_DIR}`);
        console.log(`🌐 PWA available at: http://localhost:${HTTP_PORT}/refportal-pwa.html`);
        console.log(`🌐 Root available at: http://localhost:${HTTP_PORT}/`);
        console.log(`⏹️  Press Ctrl+C to stop the server`);
    });
        
    httpServer.on('error', (error) => {
        console.error('HTTP Server error:', error);
    });

    return httpServer;
}

// Request handler for both HTTP and HTTPS
function requestHandler(req, res) {
    const parsedUrl = url.parse(req.url);
    let pathname = parsedUrl.pathname;
    
    if (req.url.startsWith('/api/')) {
        if (req.url === '/api/health' && req.method === 'GET') {
            // Set CORS headers if needed
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.setHeader('Content-Type', 'application/json');
            
            try {
                const healthData = {
                    status: 'healthy',
                    timestamp: new Date().toISOString(),
                    uptime: process.uptime(),
                    memory: process.memoryUsage(),
                    version: process.version,
                    platform: process.platform,
                    nodeEnv: process.env.NODE_ENV || 'development'
                };
                
                res.writeHead(200);
                res.end(JSON.stringify(healthData));
                
            } catch (error) {
                console.error('Health check error:', error);
                res.writeHead(500);
                res.end(JSON.stringify({
                    status: 'unhealthy',
                    error: error.message,
                    timestamp: new Date().toISOString()
                }));
            }
        } else {
            console.log('❌ API not found:', req.url);
            res.writeHead(404);
            res.end( 'API not found');
            return;
        }
    } else {
        // Debug logging for config files
        if (pathname.includes('config') || pathname.includes('manifest')) {
            console.log('🔍 Server: Requesting config file:', pathname);
            console.log('🔍 Full URL:', req.url);
            console.log('🔍 Query params:', parsedUrl.query);
        }
        
        // Default to PWA if root is requested
        if (pathname === '/') {
            pathname = '/refportal-pwa.html';
        }

        // Handle PWA routes
        let filePath = path.join(PWA_DIR, pathname);
        
        // Security check: ensure file is within allowed directories
        if (!filePath.startsWith(ROOT_DIR) && !filePath.startsWith(PWA_DIR)) {
            console.log('❌ Security violation: File path outside allowed directories:', filePath);
            res.writeHead(403);
            res.end('Forbidden');
            return;
        }
        
        // Check if file exists
        fs.access(filePath, fs.constants.F_OK, (err) => {
            if (err) {
                console.log('❌ File not found:', filePath);
                res.writeHead(404);
                res.end('File not found');
                return;
            }
            
            // Get file extension and MIME type
            const ext = path.extname(filePath);
            const mimeType = mimeTypes[ext] || 'application/octet-stream';
            
            // Read and serve file
            fs.readFile(filePath, (err, data) => {
                if (err) {
                    console.log('❌ Error reading file:', filePath, err.message);
                    res.writeHead(500);
                    res.end('Internal server error');
                    return;
                }
                
                // Debug logging for successful config file serves
                if (pathname.includes('config') || pathname.includes('manifest')) {
                    console.log('✅ Successfully serving config file:', pathname);
                    console.log('✅ File size:', data.length, 'bytes');
                }
                
                res.writeHead(200, {
                    'Content-Type': mimeType,
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache, no-store, must-revalidate'
                });
                res.end(data);
            });
        });
    }
}

// Main server startup
function startServer() {
    console.log('🚀 Starting RefereeX PWA Server...');
    console.log('='.repeat(50));
    
    let httpsServer = null;
    let httpServer = null;
    
    // Check for SSL certificates
    if (checkSSLCertificates()) {
        // Certificates exist, start HTTPS server
        httpsServer = createHTTPSServer();
        if (!!httpsServer) {
            console.log('✅ HTTPS server started successfully');
        } else {
            console.log('⚠️ HTTPS server failed, falling back to HTTP');
            httpServer = createHTTPServer();
        }
    } else if (SSL_CONFIG.autoGenerate) {
        // Try to generate self-signed certificates
        console.log('🔐 Attempting to generate self-signed certificates...');
        if (generateSelfSignedCertificates()) {
            httpsServer = createHTTPSServer();
            if (httpsServer) {
                console.log('✅ HTTPS server started with self-signed certificates');
                console.log('⚠️  Note: Self-signed certificates will show browser warnings');
                console.log('💡  Accept the security warning in your browser to proceed');
            } else {
                console.log('⚠️ HTTPS server failed, falling back to HTTP');
                httpServer = createHTTPServer();
            }
        } else {
            console.log('⚠️ Certificate generation failed, starting HTTP server');
            httpServer = createHTTPServer();
        }
    } 
    
    if (!!!httpServer) {
        // No certificates and auto-generation disabled
        console.log('🚀 Starting HTTP server only');
        httpServer = createHTTPServer();
    }
    
    // Graceful shutdown
    const shutdown = (signal) => {
        console.log(`\n🛑 Received ${signal}, shutting down servers...`);
        
        if (!!httpsServer) {
            httpsServer.close(() => {
                console.log('✅ HTTPS server stopped');
                if (!httpServer) process.exit(0);
            });
        }
        
        if (!!httpServer) {
            httpServer.close(() => {
                console.log('✅ HTTP server stopped');
                process.exit(0);
            });
        }
        
        // Force exit if servers don't close gracefully
        setTimeout(() => {
            console.log('⚠️ Force shutting down...');
            process.exit(1);
        }, 5000);
    };
    
    process.on('SIGINT', () => shutdown('SIGINT'));
    process.on('SIGTERM', () => shutdown('SIGTERM'));
    
    // Display server information
    console.log('\n📊 Server Status:');
    if (!!httpsServer) {
        console.log(`  🔒 HTTPS: https://localhost:${HTTPS_PORT} (Active)`);
    }
    if (!!httpServer) {
        console.log(`  🚀 HTTP:  http://localhost:${HTTP_PORT} (Active)`);
    }
    
    console.log('\n💡 Tips:');
    if (!!httpsServer) {
        console.log('  - Use HTTPS for secure connections and PWA features');
        console.log('  - Accept any security warnings for self-signed certificates');
    }
    console.log('  - PWA will work best with HTTPS');
    console.log('  - Check browser console for any errors');
}

// Start the server
const server = startServer();