#!/bin/bash

# Setup script for Certbot DNS Challenge with Cloudflare API

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

print_status "Setting up Certbot DNS Challenge with Cloudflare API..."

# Detect OS
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
else
    print_error "Could not detect OS"
    exit 1
fi

print_status "Detected OS: $OS $VER"

# Install dependencies based on OS
if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]] || [[ "$OS" == *"Raspberry Pi"* ]]; then
    print_status "Installing dependencies for Ubuntu/Debian/Raspberry Pi..."
    sudo apt update
    sudo apt install -y certbot curl jq dnsutils
elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
    print_status "Installing dependencies for CentOS/RHEL..."
    sudo yum install -y certbot curl jq bind-utils
else
    print_warning "Unsupported OS. Please install dependencies manually:"
    echo "  - certbot"
    echo "  - curl"
    echo "  - jq"
    echo "  - dig (dnsutils or bind-utils)"
fi

# Check if dependencies are installed
print_status "Checking dependencies..."
deps=("certbot" "curl" "jq" "dig")
missing_deps=()

for dep in "${deps[@]}"; do
    if ! command -v "$dep" &> /dev/null; then
        missing_deps+=("$dep")
    fi
done

if [[ ${#missing_deps[@]} -gt 0 ]]; then
    print_error "Missing dependencies: ${missing_deps[*]}"
    print_error "Please install them manually and run this script again."
    exit 1
fi

print_success "All dependencies are installed"

# Create config file if it doesn't exist
if [[ ! -f "config.env" ]]; then
    print_status "Creating config.env from template..."
    if [[ -f "config.env.template" ]]; then
        cp config.env.template config.env
        print_success "config.env created from template"
        print_warning "Please edit config.env with your Cloudflare credentials"
    else
        print_error "config.env.template not found"
        exit 1
    fi
else
    print_status "config.env already exists"
fi

# Make scripts executable
print_status "Making scripts executable..."
chmod +x certbot-cloudflare-update.sh
chmod +x setup.sh

print_success "Setup completed successfully!"
echo
print_status "Next steps:"
echo "1. Edit config.env with your Cloudflare credentials:"
echo "   - CLOUDFLARE_ZONE_ID"
echo "   - CLOUDFLARE_API_TOKEN"
echo "   - CLOUDFLARE_EMAIL"
echo "2. Run the script: ./certbot-cloudflare-update.sh"
echo
print_status "For detailed instructions, see README.md"

