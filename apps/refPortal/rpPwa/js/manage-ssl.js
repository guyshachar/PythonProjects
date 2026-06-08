#!/usr/bin/env node
/**
 * SSL Certificate Management Utility for RefereeX PWA
 * 
 * This script helps manage SSL certificates for the development server.
 * 
 * Usage:
 *   node manage-ssl.js [command] [options]
 * 
 * Commands:
 *   generate    - Generate new self-signed certificates
 *   validate    - Validate existing certificates
 *   clean       - Remove all generated certificates
 *   info        - Show certificate information
 *   help        - Show this help message
 * 
 * Examples:
 *   node manage-ssl.js generate
 *   node manage-ssl.js validate
 *   node manage-ssl.js clean
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const sslConfig = require('./ssl-config');

// Colors for console output
const colors = {
    reset: '\x1b[0m',
    bright: '\x1b[1m',
    red: '\x1b[31m',
    green: '\x1b[32m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    magenta: '\x1b[35m',
    cyan: '\x1b[36m'
};

function log(message, color = 'reset') {
    console.log(`${colors[color]}${message}${colors.reset}`);
}

function logError(message) {
    log(`❌ ${message}`, 'red');
}

function logSuccess(message) {
    log(`✅ ${message}`, 'green');
}

function logWarning(message) {
    log(`⚠️ ${message}`, 'yellow');
}

function logInfo(message) {
    log(`ℹ️ ${message}`, 'blue');
}

// Check if OpenSSL is available
function checkOpenSSL() {
    try {
        execSync('openssl version', { stdio: 'pipe' });
        return true;
    } catch (error) {
        return false;
    }
}

// Generate self-signed certificates
function generateCertificates() {
    log('🔐 Generating self-signed SSL certificates...', 'cyan');
    
    if (!checkOpenSSL()) {
        logError('OpenSSL is not installed or not available in PATH');
        log('Please install OpenSSL:', 'yellow');
        log('  - macOS: brew install openssl', 'yellow');
        log('  - Ubuntu/Debian: sudo apt-get install openssl', 'yellow');
        log('  - Windows: Download from https://slproweb.com/products/Win32OpenSSL.html', 'yellow');
        process.exit(1);
    }
    
    try {
        const sslDir = path.resolve(__dirname, 'ssl');
        const certPath = path.join(sslDir, 'cert.pem');
        const keyPath = path.join(sslDir, 'key.pem');
        
        // Create ssl directory if it doesn't exist
        if (!fs.existsSync(sslDir)) {
            fs.mkdirSync(sslDir, { recursive: true });
            logSuccess(`Created SSL directory: ${sslDir}`);
        }
        
        // Check if certificates already exist
        if (fs.existsSync(certPath) && fs.existsSync(keyPath)) {
            logWarning('Certificates already exist');
            const answer = process.argv.includes('--force') ? 'y' : 
                          process.argv.includes('--yes') ? 'y' : 'n';
            
            if (answer !== 'y') {
                log('Use --force to overwrite existing certificates', 'yellow');
                return false;
            }
            
            log('Overwriting existing certificates...', 'yellow');
        }
        
        // Generate private key
        log('Generating private key...', 'blue');
        const keyCommand = `openssl genrsa -out "${keyPath}" ${sslConfig.autoGenerate.keySize}`;
        execSync(keyCommand, { stdio: 'inherit' });
        logSuccess('Private key generated');
        
        // Generate certificate signing request
        log('Generating certificate signing request...', 'blue');
        const csrPath = path.join(sslDir, 'cert.csr');
        const subject = `/C=${sslConfig.autoGenerate.details.country}/ST=${sslConfig.autoGenerate.details.state}/L=${sslConfig.autoGenerate.details.locality}/O=${sslConfig.autoGenerate.details.organization}/OU=${sslConfig.autoGenerate.details.organizationalUnit}/CN=${sslConfig.autoGenerate.details.commonName}/emailAddress=${sslConfig.autoGenerate.details.emailAddress}`;
        
        const csrCommand = `openssl req -new -key "${keyPath}" -out "${csrPath}" -subj "${subject}"`;
        execSync(csrCommand, { stdio: 'inherit' });
        logSuccess('Certificate signing request generated');
        
        // Generate self-signed certificate
        log('Generating self-signed certificate...', 'blue');
        const certCommand = `openssl x509 -req -in "${csrPath}" -signkey "${keyPath}" -out "${certPath}" -days ${sslConfig.autoGenerate.validityDays}`;
        execSync(certCommand, { stdio: 'inherit' });
        logSuccess('Self-signed certificate generated');
        
        // Clean up CSR file
        fs.unlinkSync(csrPath);
        logSuccess('Cleaned up temporary files');
        
        // Set proper permissions
        fs.chmodSync(keyPath, 0o600);
        fs.chmodSync(certPath, 0o644);
        logSuccess('Set proper file permissions');
        
        // Show certificate information
        showCertificateInfo();
        
        return true;
        
    } catch (error) {
        logError(`Failed to generate certificates: ${error.message}`);
        return false;
    }
}

// Validate existing certificates
function validateCertificates() {
    log('🔍 Validating SSL certificates...', 'cyan');
    
    const certPath = path.resolve(__dirname, sslConfig.certificates.certPath);
    const keyPath = path.resolve(__dirname, sslConfig.certificates.keyPath);
    
    if (!fs.existsSync(certPath) || !fs.existsSync(keyPath)) {
        logError('Certificates not found');
        log(`Expected paths:`, 'yellow');
        log(`  Certificate: ${certPath}`, 'yellow');
        log(`  Private Key: ${keyPath}`, 'yellow');
        return false;
    }
    
    try {
        // Check certificate validity
        log('Checking certificate validity...', 'blue');
        const certCheck = execSync(`openssl x509 -in "${certPath}" -text -noout`, { stdio: 'pipe' }).toString();
        
        // Extract expiration date
        const expiryMatch = certCheck.match(/Not After\s*:\s*(.+)/);
        if (expiryMatch) {
            const expiryDate = new Date(expiryMatch[1]);
            const now = new Date();
            const daysLeft = Math.ceil((expiryDate - now) / (1000 * 60 * 60 * 24));
            
            if (daysLeft > 0) {
                logSuccess(`Certificate valid until: ${expiryDate.toLocaleDateString()} (${daysLeft} days left)`);
            } else {
                logError(`Certificate expired on: ${expiryDate.toLocaleDateString()}`);
                return false;
            }
        }
        
        // Check private key
        log('Checking private key...', 'blue');
        const keyCheck = execSync(`openssl rsa -in "${keyPath}" -check -noout`, { stdio: 'pipe' }).toString();
        if (keyCheck.trim() === 'RSA key ok') {
            logSuccess('Private key is valid');
        } else {
            logError('Private key is invalid');
            return false;
        }
        
        // Test certificate and key match
        log('Testing certificate and key match...', 'blue');
        const testCommand = `openssl x509 -noout -modulus -in "${certPath}" | openssl md5`;
        const certModulus = execSync(testCommand, { stdio: 'pipe' }).toString().trim();
        
        const keyModulus = execSync(`openssl rsa -noout -modulus -in "${keyPath}" | openssl md5`, { stdio: 'pipe' }).toString().trim();
        
        if (certModulus === keyModulus) {
            logSuccess('Certificate and private key match');
        } else {
            logError('Certificate and private key do not match');
            return false;
        }
        
        logSuccess('All certificates are valid!');
        return true;
        
    } catch (error) {
        logError(`Failed to validate certificates: ${error.message}`);
        return false;
    }
}

// Show certificate information
function showCertificateInfo() {
    log('📋 Certificate Information:', 'cyan');
    
    const certPath = path.resolve(__dirname, sslConfig.certificates.certPath);
    const keyPath = path.resolve(__dirname, sslConfig.certificates.keyPath);
    
    if (!fs.existsSync(certPath)) {
        logError('Certificate file not found');
        return;
    }
    
    try {
        const certInfo = execSync(`openssl x509 -in "${certPath}" -text -noout`, { stdio: 'pipe' }).toString();
        
        // Extract key information
        const subjectMatch = certInfo.match(/Subject:\s*(.+)/);
        const issuerMatch = certInfo.match(/Issuer:\s*(.+)/);
        const validityMatch = certInfo.match(/Validity\s*Not Before\s*:\s*(.+)\s*Not After\s*:\s*(.+)/s);
        const keyUsageMatch = certInfo.match(/X509v3 Key Usage:\s*(.+)/s);
        
        if (subjectMatch) log(`Subject: ${subjectMatch[1].trim()}`, 'blue');
        if (issuerMatch) log(`Issuer: ${issuerMatch[1].trim()}`, 'blue');
        
        if (validityMatch) {
            const notBefore = new Date(validityMatch[1].trim());
            const notAfter = new Date(validityMatch[2].trim());
            log(`Valid from: ${notBefore.toLocaleDateString()}`, 'blue');
            log(`Valid until: ${notAfter.toLocaleDateString()}`, 'blue');
        }
        
        if (keyUsageMatch) {
            const keyUsage = keyUsageMatch[1].trim().split('\n').map(line => line.trim()).filter(line => line);
            log('Key Usage:', 'blue');
            keyUsage.forEach(usage => log(`  ${usage}`, 'blue'));
        }
        
        // File information
        const certStats = fs.statSync(certPath);
        const keyStats = fs.statSync(keyPath);
        
        log('\nFile Information:', 'cyan');
        log(`Certificate: ${certPath} (${(certStats.size / 1024).toFixed(1)} KB)`, 'blue');
        log(`Private Key: ${keyPath} (${(keyStats.size / 1024).toFixed(1)} KB)`, 'blue');
        
    } catch (error) {
        logError(`Failed to read certificate information: ${error.message}`);
    }
}

// Clean up certificates
function cleanCertificates() {
    log('🧹 Cleaning up SSL certificates...', 'cyan');
    
    const sslDir = path.resolve(__dirname, 'ssl');
    
    if (!fs.existsSync(sslDir)) {
        logInfo('SSL directory does not exist, nothing to clean');
        return;
    }
    
    try {
        const files = fs.readdirSync(sslDir);
        let removedCount = 0;
        
        files.forEach(file => {
            const filePath = path.join(sslDir, file);
            if (file.endsWith('.pem') || file.endsWith('.key') || file.endsWith('.crt')) {
                fs.unlinkSync(filePath);
                logSuccess(`Removed: ${file}`);
                removedCount++;
            }
        });
        
        if (removedCount === 0) {
            logInfo('No certificate files found to remove');
        } else {
            logSuccess(`Removed ${removedCount} certificate files`);
        }
        
        // Remove SSL directory if empty
        const remainingFiles = fs.readdirSync(sslDir);
        if (remainingFiles.length === 0) {
            fs.rmdirSync(sslDir);
            logSuccess('Removed empty SSL directory');
        }
        
    } catch (error) {
        logError(`Failed to clean certificates: ${error.message}`);
    }
}

// Show help
function showHelp() {
    log('🔐 SSL Certificate Management Utility for RefereeX PWA', 'cyan');
    log('=' * 60, 'cyan');
    
    log('\nUsage:', 'bright');
    log('  node manage-ssl.js [command] [options]', 'yellow');
    
    log('\nCommands:', 'bright');
    log('  generate    - Generate new self-signed certificates', 'green');
    log('  validate    - Validate existing certificates', 'green');
    log('  clean       - Remove all generated certificates', 'green');
    log('  info        - Show certificate information', 'green');
    log('  help        - Show this help message', 'green');
    
    log('\nOptions:', 'bright');
    log('  --force     - Force overwrite existing certificates', 'yellow');
    log('  --yes       - Answer yes to all prompts', 'yellow');
    
    log('\nExamples:', 'bright');
    log('  node manage-ssl.js generate', 'yellow');
    log('  node manage-ssl.js validate', 'yellow');
    log('  node manage-ssl.js clean', 'yellow');
    log('  node manage-ssl.js generate --force', 'yellow');
    
    log('\nNote:', 'bright');
    log('  This utility requires OpenSSL to be installed on your system.', 'yellow');
    log('  Generated certificates are for development use only.', 'yellow');
}

// Main function
function main() {
    const command = process.argv[2] || 'help';
    
    switch (command.toLowerCase()) {
        case 'generate':
        case 'gen':
            generateCertificates();
            break;
            
        case 'validate':
        case 'check':
            validateCertificates();
            break;
            
        case 'clean':
        case 'remove':
            cleanCertificates();
            break;
            
        case 'info':
        case 'show':
            showCertificateInfo();
            break;
            
        case 'help':
        default:
            showHelp();
            break;
    }
}

// Run if called directly
if (require.main === module) {
    main();
}

module.exports = {
    generateCertificates,
    validateCertificates,
    showCertificateInfo,
    cleanCertificates,
    checkOpenSSL
};
