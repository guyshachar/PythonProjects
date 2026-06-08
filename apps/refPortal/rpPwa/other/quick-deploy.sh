#!/bin/bash

# Quick Deploy Script for RefereeX PWA
# This is a simplified version for quick deployment

echo "🚀 Quick Deploy - RefereeX PWA"
echo "================================"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Create necessary directories
mkdir -p ssl logs

# Build the image
echo "🔨 Building Docker image..."
docker build -f pwaDockerfile -t refportal-pwa:latest-prod .

# Stop and remove existing container if it exists
if docker ps -a --format "table {{.Names}}" | grep -q "refportal-pwa"; then
    echo "🧹 Cleaning up existing container..."
    docker stop refportal-pwa 2>/dev/null || true
    docker rm refportal-pwa 2>/dev/null || true
fi

# Run the container
echo "🚀 Starting container..."
docker run -d \
    --name refportal-pwa \
    -p 8082:8082 \
    -p 8443:8443 \
    -v $(pwd)/ssl:/app/ssl:ro \
    -v $(pwd)/logs:/app/logs \
    --restart unless-stopped \
    refportal-pwa:latest

echo "✅ PWA deployed successfully!"
echo ""
echo "🌐 Access your PWA at:"
echo "   HTTP:  http://localhost:8082"
echo "   HTTPS: https://localhost:8443"
echo ""
echo "📋 Useful commands:"
echo "   View logs:     docker logs refportal-pwa"
echo "   Stop:          docker stop refportal-pwa"
echo "   Status:        docker ps"
echo "   Shell access:  docker exec -it refportal-pwa sh"
