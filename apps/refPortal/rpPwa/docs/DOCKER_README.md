# RefPortal PWA Docker Setup

This document provides comprehensive instructions for running the RefPortal PWA using Docker.

## 🐳 Quick Start

### Prerequisites
- Docker Engine 20.10+
- Docker Compose 2.0+
- At least 512MB RAM available

### 1. Build and Run with Docker Compose (Recommended)

```bash
# Navigate to the rpPwa directory
cd rpPwa

# Build and start the services
docker-compose up --build -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f refportal-pwa
```

### 2. Build and Run with Docker Commands

```bash
# Build the image
docker build -t refportal-pwa .

# Run the container
docker run -d \
  --name refportal-pwa \
  -p 8082:8082 \
  -p 8443:8443 \
  -v $(pwd)/ssl:/app/ssl:ro \
  -v $(pwd)/logs:/app/logs \
  --restart unless-stopped \
  refportal-pwa
```

## 🔧 Configuration

### Environment Variables

The container supports the following environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_ENV` | `production` | Node.js environment |
| `HTTP_PORT` | `8082` | HTTP server port |
| `HTTPS_PORT` | `8443` | HTTPS server port |

### SSL Certificates

The PWA can run in two modes:

#### HTTP Mode (Default)
- Runs on port 8082
- No SSL required
- Good for development/testing

#### HTTPS Mode
- Runs on port 8443
- Requires SSL certificates
- Production-ready

To use HTTPS mode:

1. **Generate self-signed certificates:**
   ```bash
   # Inside the container
   docker exec -it refportal-pwa npm run ssl:generate
   
   # Or from host (if openssl is installed)
   mkdir -p ssl
   openssl req -x509 -newkey rsa:4096 -keyout ssl/key.pem -out ssl/cert.pem -days 365 -nodes
   ```

2. **Mount certificates:**
   ```bash
   docker run -v $(pwd)/ssl:/app/ssl:ro refportal-pwa
   ```

3. **Start HTTPS server:**
   ```bash
   docker exec -it refportal-pwa npm run start:https
   ```

## 🚀 Deployment Options

### Development
```bash
# Start with HTTP only
docker-compose up --build

# Access at: http://localhost:8082
```

### Production
```bash
# Start with HTTPS
docker-compose up --build -d

# Access at: https://localhost:8443
```

### Staging
```bash
# Use environment-specific compose file
docker-compose -f docker-compose.staging.yml up --build -d
```

## 📊 Monitoring and Health Checks

### Health Check
The container includes a built-in health check:
```bash
# Check container health
docker inspect refportal-pwa | grep Health -A 10

# Manual health check
curl http://localhost:8082/api/health
```

### Logs
```bash
# View real-time logs
docker-compose logs -f refportal-pwa

# View specific log levels
docker-compose logs -f refportal-pwa | grep ERROR
```

### Resource Usage
```bash
# Monitor container resources
docker stats refportal-pwa

# Check disk usage
docker exec refportal-pwa du -sh /app
```

## 🔍 Troubleshooting

### Common Issues

#### 1. Port Already in Use
```bash
# Check what's using the port
lsof -i :8082
lsof -i :8443

# Stop conflicting services or change ports in docker-compose.yml
```

#### 2. SSL Certificate Issues
```bash
# Validate certificates
docker exec -it refportal-pwa npm run ssl:validate

# Regenerate certificates
docker exec -it refportal-pwa npm run ssl:generate
```

#### 3. Permission Issues
```bash
# Fix volume permissions
sudo chown -R $USER:$USER ssl/ logs/

# Or run container with proper user mapping
docker run -u $(id -u):$(id -g) refportal-pwa
```

#### 4. Container Won't Start
```bash
# Check container logs
docker logs refportal-pwa

# Check container status
docker ps -a

# Restart container
docker-compose restart refportal-pwa
```

### Debug Mode
```bash
# Run container in interactive mode
docker run -it --rm refportal-pwa sh

# Check Node.js processes
docker exec -it refportal-pwa ps aux

# Check network connectivity
docker exec -it refportal-pwa ping google.com
```

## 🛠️ Advanced Configuration

### Custom Node.js Version
Edit the Dockerfile:
```dockerfile
FROM node:20-alpine AS builder
# ... rest of Dockerfile
```

### Multi-Architecture Build
```bash
# Build for multiple architectures
docker buildx build --platform linux/amd64,linux/arm64 -t refportal-pwa .
```

### Production Optimizations
```bash
# Use production build
docker build --target production -t refportal-pwa:prod .

# Run with resource limits
docker run --memory=512m --cpus=1 refportal-pwa:prod
```

## 📚 Additional Resources

### Useful Commands
```bash
# Stop all services
docker-compose down

# Remove containers and volumes
docker-compose down -v

# Rebuild without cache
docker-compose build --no-cache

# Update dependencies
docker-compose exec refportal-pwa npm update
```

### Integration with Other Services
The PWA can be integrated with:
- **Redis**: For session storage and caching
- **Nginx**: As a reverse proxy
- **Traefik**: For automatic SSL and routing
- **Prometheus**: For metrics collection

### Security Considerations
- Container runs as non-root user (nodejs:1001)
- SSL certificates are mounted as read-only
- Health checks prevent unhealthy containers from receiving traffic
- Resource limits prevent DoS attacks

## 🤝 Contributing

When modifying the Docker setup:
1. Update the Dockerfile version
2. Test with different Node.js versions
3. Verify SSL functionality
4. Update this documentation
5. Test on different architectures

## 📄 License

This Docker setup is part of the RefPortal project and follows the same MIT license.
