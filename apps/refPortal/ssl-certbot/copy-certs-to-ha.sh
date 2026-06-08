#!/bin/bash

# Standalone script to copy existing SSL certificates to Home Assistant
# Useful when you already have certificates and just want to update Home Assistant

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration - Update these if needed
DOMAIN="ha.refereex.com"
HA_SSL_DIR="/opt/homeassistant/config/ssl"
HA_PRIVKEY_NAME="ha.privkey.pem"
HA_FULLCHAIN_NAME="ha.fullchain.pem"
HA_CONTAINER_NAME="homeassistant"

# Source config file if it exists
if [[ -f "config.env" ]]; then
    source config.env
    print_status "Loaded configuration from config.env"
fi

print_status "Starting SSL certificate copy to Home Assistant..."

# Check if source certificates exist
CERT_SOURCE="/etc/letsencrypt/live/$DOMAIN"
if [[ ! -f "$CERT_SOURCE/fullchain.pem" ]] || [[ ! -f "$CERT_SOURCE/privkey.pem" ]]; then
    print_error "SSL certificates not found in $CERT_SOURCE"
    print_error "Please run the main script first to generate certificates"
    exit 1
fi

print_success "Found SSL certificates in $CERT_SOURCE"

# Create SSL directory if it doesn't exist
if [[ ! -d "$HA_SSL_DIR" ]]; then
    print_status "Creating SSL directory: $HA_SSL_DIR"
    sudo mkdir -p "$HA_SSL_DIR"
    if [[ $? -ne 0 ]]; then
        print_error "Failed to create SSL directory"
        exit 1
    fi
fi

# Copy certificates
print_status "Copying private key..."
sudo cp "$CERT_SOURCE/privkey.pem" "$HA_SSL_DIR/$HA_PRIVKEY_NAME"
if [[ $? -ne 0 ]]; then
    print_error "Failed to copy private key"
    exit 1
fi

print_status "Copying full chain certificate..."
sudo cp "$CERT_SOURCE/fullchain.pem" "$HA_SSL_DIR/$HA_FULLCHAIN_NAME"
if [[ $? -ne 0 ]]; then
    print_error "Failed to copy full chain certificate"
    exit 1
fi

# Set proper permissions
print_status "Setting proper permissions..."
sudo chown -R 1000:1000 "$HA_SSL_DIR" 2>/dev/null || true
sudo chmod 600 "$HA_SSL_DIR/$HA_PRIVKEY_NAME"
sudo chmod 644 "$HA_SSL_DIR/$HA_FULLCHAIN_NAME"

print_success "SSL certificates copied to Home Assistant successfully"

# Ask user if they want to restart Home Assistant
read -p "Do you want to restart the Home Assistant container now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_status "Restarting Home Assistant container..."
    
    # Check if Docker is running
    if ! command -v docker &> /dev/null; then
        print_error "Docker not found. Please restart Home Assistant manually."
        exit 1
    fi
    
    # Check if container exists
    if ! docker ps -a --format "table {{.Names}}" | grep -q "^$HA_CONTAINER_NAME$"; then
        print_error "Home Assistant container '$HA_CONTAINER_NAME' not found."
        print_status "Available containers:"
        docker ps -a --format "table {{.Names}}\t{{.Status}}"
        exit 1
    fi
    
    # Restart container
    print_status "Restarting container: $HA_CONTAINER_NAME"
    if docker restart "$HA_CONTAINER_NAME"; then
        print_success "Home Assistant container restarted successfully"
        
        # Wait a moment and check container status
        sleep 5
        if docker ps --format "table {{.Names}}\t{{.Status}}" | grep -q "^$HA_CONTAINER_NAME.*Up"; then
            print_success "Home Assistant container is running"
        else
            print_warning "Home Assistant container may not be running properly"
        fi
    else
        print_error "Failed to restart Home Assistant container"
        exit 1
    fi
else
    print_status "Skipping Home Assistant restart"
    print_status "You can restart it manually with: docker restart $HA_CONTAINER_NAME"
fi

print_success "SSL certificate copy completed!"
print_status "Certificates are now available in: $HA_SSL_DIR"

