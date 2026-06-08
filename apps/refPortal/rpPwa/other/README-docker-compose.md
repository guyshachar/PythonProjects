# PWA Docker Compose Configuration

This directory contains Docker Compose configurations for running the RefPortal PWA service in different environments.

## Files Overview

- `docker-compose.pwa.yml` - Main PWA service configuration (environment configurable)
- `docker-compose.pwa.dev.yml` - Development environment configuration
- `docker-compose.pwa.staging.yml` - Staging environment configuration

## Usage with deploy-pwa.sh

The `deploy-pwa.sh` script has been updated to support both container and service deployment modes. You can use it with Docker Compose for easier management.

### Environment-Specific Deployment

```bash
# Deploy to production
./deploy-pwa.sh prod run-service

# Deploy to staging
./deploy-pwa.sh staging run-service

# Deploy to development
./deploy-pwa.sh dev run-service
```

### Using Docker Compose Directly

#### Production Environment
```bash
cd rpPwa
APP_ENV=prod HTTP_PORT=8082 HTTPS_PORT=8443 docker-compose -f docker-compose.pwa.yml up -d
```

#### Development Environment
```bash
cd rpPwa
docker-compose -f docker-compose.pwa.dev.yml up -d
```

#### Staging Environment
```bash
cd rpPwa
docker-compose -f docker-compose.pwa.staging.yml up -d
```

### Environment Variables

The following environment variables can be customized:

- `APP_ENV` - Environment name (prod, staging, dev)
- `HTTP_PORT` - Host port for HTTP (default: 8082)
- `HTTPS_PORT` - Host port for HTTPS (default: 8443)
- `NODE_ENV` - Node.js environment (production, staging, development)

### Port Mapping

| Environment | HTTP Port | HTTPS Port |
|-------------|-----------|------------|
| Production  | 8082      | 8443       |
| Development | 8083      | 8444       |
| Staging     | 8084      | 8445       |

### Volumes

- `../ssl:/app/ssl:ro` - SSL certificates (read-only)
- `../logs:/app/logs` - Application logs
- `.:/app` - Source code (development only)

### Health Checks

All services include health checks that verify the `/api/health` endpoint is responding correctly.

### Network Configuration

Services use a dedicated `pwa_network` bridge network for isolation.

## Integration with Main docker-compose.yml

The main `docker-compose.yml` file in the root directory also includes PWA services for different environments. You can run all services together:

```bash
# From root directory
docker-compose up -d

# Or run specific services
docker-compose up -d api pwa pwa-dev pwa-staging
```

## Troubleshooting

### Check Service Status
```bash
# Using deploy script
./deploy-pwa.sh prod status

# Using docker-compose
docker-compose -f docker-compose.pwa.yml ps
```

### View Logs
```bash
# Using deploy script
./deploy-pwa.sh prod logs

# Using docker-compose
docker-compose -f docker-compose.pwa.yml logs -f pwa
```

### Restart Service
```bash
# Using deploy script
./deploy-pwa.sh prod run-service

# Using docker-compose
docker-compose -f docker-compose.pwa.yml restart pwa
```

### Clean Up
```bash
# Using deploy script
./deploy-pwa.sh prod cleanup

# Using docker-compose
docker-compose -f docker-compose.pwa.yml down
```

## Security Notes

- SSL certificates are mounted as read-only
- Services run with appropriate environment variables
- Health checks ensure service availability
- Network isolation with dedicated bridge networks
