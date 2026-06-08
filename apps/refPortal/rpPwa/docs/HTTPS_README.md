# 🔒 HTTPS Server Setup for RefereeX PWA

This guide explains how to set up and use the HTTPS server with SSL certificates for the RefereeX PWA development environment.

## 🚀 Quick Start

### 1. Generate SSL Certificates
```bash
cd rpPwa
node manage-ssl.js generate
```

### 2. Start HTTPS Server
```bash
node start-server.js
```

### 3. Access Your PWA
- **HTTPS**: https://localhost:8443
- **HTTP Fallback**: http://localhost:8082

## 📋 Prerequisites

### Required Software
- **Node.js** (v14 or higher)
- **OpenSSL** (for certificate generation)

### Installing OpenSSL

#### macOS
```bash
brew install openssl
```

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install openssl
```

#### Windows
1. Download from [Win32/Win64 OpenSSL](https://slproweb.com/products/Win32OpenSSL.html)
2. Install and add to PATH
3. Restart terminal/command prompt

## 🔐 SSL Certificate Management

### Available Commands

#### Generate Certificates
```bash
# Generate new self-signed certificates
node manage-ssl.js generate

# Force overwrite existing certificates
node manage-ssl.js generate --force

# Generate with automatic yes to prompts
node manage-ssl.js generate --yes
```

#### Validate Certificates
```bash
# Check if certificates are valid
node manage-ssl.js validate
```

#### View Certificate Information
```bash
# Show detailed certificate info
node manage-ssl.js info
```

#### Clean Up Certificates
```bash
# Remove all generated certificates
node manage-ssl.js clean
```

#### Get Help
```bash
# Show all available commands
node manage-ssl.js help
```

### Certificate Details

The generated certificates include:
- **Country**: IL (Israel)
- **State**: Israel
- **Locality**: Tel Aviv
- **Organization**: RefereeX
- **Common Name**: localhost
- **Validity**: 365 days
- **Key Size**: 2048 bits

## ⚙️ Configuration

### SSL Configuration File (`ssl-config.js`)

You can customize SSL settings by editing `ssl-config.js`:

```javascript
module.exports = {
    certificates: {
        certPath: './ssl/cert.pem',
        keyPath: './ssl/key.pem'
    },
    
    autoGenerate: {
        enabled: true,
        validityDays: 365,
        keySize: 2048,
        details: {
            country: 'IL',
            state: 'Israel',
            // ... more options
        }
    },
    
    ports: {
        http: 8082,
        https: 8443
    }
};
```

### Environment-Specific Settings

#### Development
- Auto-generation enabled
- HTTP fallback allowed
- Self-signed certificates
- Verbose logging

#### Production
- HTTPS required
- HTTP to HTTPS redirect
- Strict SSL validation
- Professional certificates recommended

## 🌐 Server Features

### Dual Protocol Support
- **HTTPS** (port 8443) - Primary, secure
- **HTTP** (port 8082) - Fallback, development

### Automatic Certificate Management
- ✅ Auto-detection of existing certificates
- ✅ Self-signed certificate generation
- ✅ Certificate validation
- ✅ Graceful fallback to HTTP

### Security Headers
- HSTS (HTTP Strict Transport Security)
- X-Content-Type-Options
- X-Frame-Options
- X-XSS-Protection
- Referrer-Policy

### PWA Support
- Service Worker registration
- Push notifications
- Offline functionality
- Install prompts

## 🔧 Troubleshooting

### Common Issues

#### 1. OpenSSL Not Found
```bash
❌ Error: OpenSSL is not installed or not available in PATH
```
**Solution**: Install OpenSSL (see Prerequisites section)

#### 2. Certificate Generation Failed
```bash
❌ Failed to generate certificates: [error message]
```
**Solutions**:
- Check OpenSSL installation
- Verify write permissions in directory
- Try running with `--force` flag

#### 3. Browser Security Warnings
**Expected**: Self-signed certificates show security warnings
**Solution**: 
1. Click "Advanced" in browser warning
2. Click "Proceed to localhost (unsafe)"
3. Accept the certificate

#### 4. Port Already in Use
```bash
❌ Error: listen EADDRINUSE: address already in use :::8443
```
**Solutions**:
- Stop other services using the port
- Change ports in `ssl-config.js`
- Use `lsof -i :8443` to find what's using the port

### Debug Mode

Enable verbose logging by setting environment variable:
```bash
export DEBUG_SSL=true
node start-server.js
```

## 📁 File Structure

```
rpPwa/
├── start-server.js          # Main HTTPS server
├── ssl-config.js           # SSL configuration
├── manage-ssl.js           # Certificate management utility
├── ssl/                    # SSL certificates directory
│   ├── cert.pem           # Certificate file
│   └── key.pem            # Private key file
└── HTTPS_README.md         # This file
```

## 🔄 Development Workflow

### 1. First Time Setup
```bash
# Navigate to PWA directory
cd rpPwa

# Generate SSL certificates
node manage-ssl.js generate

# Start HTTPS server
node start-server.js
```

### 2. Daily Development
```bash
# Start server (certificates auto-detected)
node start-server.js

# Or use npm script if configured
npm run start:https
```

### 3. Certificate Renewal
```bash
# Check certificate validity
node manage-ssl.js validate

# Regenerate if needed
node manage-ssl.js generate --force
```

### 4. Clean Up
```bash
# Remove all certificates
node manage-ssl.js clean
```

## 🚀 Production Deployment

### Professional Certificates
For production, replace self-signed certificates with:
- **Let's Encrypt** (free, automated)
- **Commercial CA** certificates
- **Wildcard certificates** for subdomains

### Let's Encrypt Setup
```bash
# Install certbot
sudo apt-get install certbot

# Generate certificate
sudo certbot certonly --standalone -d yourdomain.com

# Copy certificates to ssl directory
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ssl/cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ssl/key.pem
```

### Environment Variables
```bash
# Production mode
export NODE_ENV=production
export SSL_REQUIRE_HTTPS=true
export SSL_REDIRECT_HTTP=true

# Start server
node start-server.js
```

## 📊 Performance

### HTTPS Overhead
- **Negligible** for development
- **< 5ms** additional latency
- **Minimal** memory usage

### Browser Support
- ✅ Chrome 51+
- ✅ Firefox 50+
- ✅ Safari 10+
- ✅ Edge 79+

## 🔒 Security Considerations

### Development Environment
- Self-signed certificates are **NOT** secure for production
- Use only for local development
- Never commit private keys to version control

### Production Environment
- Use trusted CA certificates
- Enable HSTS
- Implement proper security headers
- Regular certificate renewal

## 📚 Additional Resources

### OpenSSL Documentation
- [OpenSSL Manual](https://www.openssl.org/docs/)
- [Certificate Creation](https://www.openssl.org/docs/man1.1.1/man1/req.html)

### Node.js HTTPS
- [Node.js HTTPS Module](https://nodejs.org/api/https.html)
- [TLS/SSL Documentation](https://nodejs.org/api/tls.html)

### PWA Security
- [PWA Security Best Practices](https://web.dev/pwa-security/)
- [Service Worker Security](https://web.dev/service-worker-security/)

## 🤝 Support

### Getting Help
1. Check this README first
2. Run `node manage-ssl.js help`
3. Check console output for error messages
4. Verify OpenSSL installation

### Reporting Issues
Include in your report:
- Operating system
- Node.js version
- OpenSSL version
- Error messages
- Steps to reproduce

---

**Happy Secure Development! 🔒✨**
