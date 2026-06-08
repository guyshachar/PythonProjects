# Environment Variables Guide for start-server.js

This guide explains how to inject and use environment variables in your PWA server.

## Supported Environment Variables

### Server Configuration
- `PWA_HTTP_PORT` - HTTP server port (default: from PWA_CONFIG)
- `PWA_HTTPS_PORT` - HTTPS server port (default: from PWA_CONFIG)
- `PWA_CERT_PATH` - Path to SSL certificate file (optional)
- `PWA_KEY_PATH` - Path to SSL private key file (optional)

### Application Configuration
- `NODE_ENV` - Node.js environment (default: 'development')
- `DEBUG_MODE` - Enable debug logging (default: false)
- `API_BASE_URL` - Base URL for API calls (default: 'http://localhost:8000')
- `CORS_ORIGIN` - CORS origin header (default: '*')

## Methods to Set Environment Variables

### Method 1: Command Line (Temporary)
```bash
# Single command with multiple variables
PWA_HTTP_PORT=3000 PWA_HTTPS_PORT=3443 NODE_ENV=production DEBUG_MODE=true node start-server.js

# Or export them first
export PWA_HTTP_PORT=3000
export PWA_HTTPS_PORT=3443
export NODE_ENV=production
export DEBUG_MODE=true
node start-server.js
```

### Method 2: Using .env file (Recommended)
1. Create a `.env` file in the same directory as `start-server.js`:
```bash
# PWA Server Configuration
PWA_HTTP_PORT=3000
PWA_HTTPS_PORT=3443

# SSL Certificate Paths (optional)
# PWA_CERT_PATH=/path/to/your/cert.pem
# PWA_KEY_PATH=/path/to/your/key.pem

# Node Environment
NODE_ENV=development

# Debug and Logging
DEBUG_MODE=false

# API Configuration
API_BASE_URL=http://localhost:8000

# CORS Configuration
CORS_ORIGIN=*
```

2. The server will automatically load these variables when it starts.

### Method 3: Using the startup script
Use the provided `start.sh` script which handles environment variables:
```bash
./start.sh
```

You can also override variables when using the script:
```bash
PWA_HTTP_PORT=8080 ./start.sh
```

## Environment-Specific Configurations

### Development
```bash
NODE_ENV=development
DEBUG_MODE=true
PWA_HTTP_PORT=3000
PWA_HTTPS_PORT=3443
API_BASE_URL=http://localhost:8000
CORS_ORIGIN=*
```

### Production
```bash
NODE_ENV=production
DEBUG_MODE=false
PWA_HTTP_PORT=80
PWA_HTTPS_PORT=443
API_BASE_URL=https://api.yourdomain.com
CORS_ORIGIN=https://yourdomain.com
```

### Staging
```bash
NODE_ENV=staging
DEBUG_MODE=true
PWA_HTTP_PORT=3001
PWA_HTTPS_PORT=3444
API_BASE_URL=https://staging-api.yourdomain.com
CORS_ORIGIN=https://staging.yourdomain.com
```

## Docker Environment Variables

When running in Docker, you can pass environment variables:

```bash
docker run -e PWA_HTTP_PORT=3000 -e NODE_ENV=production your-image
```

Or use a docker-compose.yml file:
```yaml
version: '3.8'
services:
  pwa-server:
    build: .
    ports:
      - "3000:3000"
      - "3443:3443"
    environment:
      - NODE_ENV=production
      - DEBUG_MODE=false
      - API_BASE_URL=https://api.yourdomain.com
      - CORS_ORIGIN=https://yourdomain.com
```

## Health Check Endpoint

The server provides a health check endpoint at `/api/health` that returns current environment configuration:

```bash
curl http://localhost:3000/api/health
```

Response includes:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "uptime": 123.456,
  "memory": {...},
  "version": "v18.17.0",
  "platform": "darwin",
  "nodeEnv": "development",
  "debugMode": false,
  "apiBaseUrl": "http://localhost:8000",
  "corsOrigin": "*",
  "httpPort": 3000,
  "httpsPort": 3443
}
```

## Security Notes

1. **Never commit .env files** to version control
2. **Use .env.example** files to document required variables
3. **Set proper file permissions** on .env files (600)
4. **Use different .env files** for different environments
5. **Validate environment variables** at startup

## Troubleshooting

### Environment variables not loading
1. Check if `.env` file exists in the correct directory
2. Verify `dotenv` package is installed: `npm list dotenv`
3. Check file permissions on `.env` file
4. Look for typos in variable names

### Port conflicts
1. Check if ports are already in use: `lsof -i :3000`
2. Use different ports via environment variables
3. Check firewall settings

### SSL certificate issues
1. Verify certificate paths are correct
2. Check file permissions on certificate files
3. Ensure certificates are valid and not expired
