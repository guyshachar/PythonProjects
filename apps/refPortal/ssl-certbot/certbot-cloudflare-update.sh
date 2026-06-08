#!/bin/bash

# Certbot DNS Challenge and Cloudflare DNS Update Script
# This script runs certbot with manual DNS challenge and updates Cloudflare DNS records

set -e  # Exit on any error

# Configuration - Update these variables
# You can either set them here or create a config.env file
DOMAIN="ha.refereex.com"
CLOUDFLARE_ZONE_ID="68c8427c9e9e3b5474797048d30758b8"  # Get this from Cloudflare dashboard
CLOUDFLARE_API_TOKEN="72dxsrq7nCmk7K0j7HpBYnI5ixE9dOJPGWEzvHOZ"  # Get this from Cloudflare dashboard
CLOUDFLARE_EMAIL="admin@refereex.com"  # Your Cloudflare account email

# Home Assistant SSL configuration
HA_SSL_DIR="/opt/homeassistant/config/ssl"
HA_PRIVKEY_NAME="ha.privkey.pem"
HA_FULLCHAIN_NAME="ha.fullchain.pem"
HA_CONTAINER_NAME="homeassistant"  # Update this if your container name is different

# Source config file if it exists
if [[ -f "config.env" ]]; then
    source config.env
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
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

# Function to check if required tools are installed
check_dependencies() {
    print_status "Checking dependencies..."
    
    if ! command -v certbot &> /dev/null; then
        print_error "certbot is not installed. Please install it first."
        exit 1
    fi
    
    if ! command -v curl &> /dev/null; then
        print_error "curl is not installed. Please install it first."
        exit 1
    fi
    
    if ! command -v jq &> /dev/null; then
        print_error "jq is not installed. Please install it first."
        exit 1
    fi
    
    print_success "All dependencies are installed"
}

# Function to validate configuration
validate_config() {
    print_status "Validating configuration..."
    
    if [[ -z "$CLOUDFLARE_ZONE_ID" ]]; then
        print_error "CLOUDFLARE_ZONE_ID is not set. Please update the script."
        exit 1
    fi
    
    if [[ -z "$CLOUDFLARE_API_TOKEN" ]]; then
        print_error "CLOUDFLARE_API_TOKEN is not set. Please update the script."
        exit 1
    fi
    
    if [[ -z "$CLOUDFLARE_EMAIL" ]]; then
        print_error "CLOUDFLARE_EMAIL is not set. Please update the script."
        exit 1
    fi
    
    print_success "Configuration is valid"
}

# Function to get current DNS records from Cloudflare
get_dns_records() {
    print_status "Fetching current DNS records from Cloudflare..."
    
    local response=$(curl -s -X GET \
        "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json")
    
    if [[ $? -ne 0 ]]; then
        print_error "Failed to fetch DNS records from Cloudflare"
        return 1
    fi
    
    echo "$response"
}

# Function to create or update TXT record for DNS challenge
update_dns_challenge() {
    local challenge_name="$1"
    local challenge_value="$2"
    
    print_status "Updating DNS challenge record: $challenge_name = $challenge_value"
    
    # Check if record already exists
    local existing_record=$(curl -s -X GET \
        "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records?name=$challenge_name&type=TXT" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json")
    
    local record_id=$(echo "$existing_record" | jq -r '.result[0].id // empty')
    
    if [[ -n "$record_id" && "$record_id" != "null" ]]; then
        # Update existing record
        print_status "Updating existing TXT record (ID: $record_id)"
        local response=$(curl -s -X PUT \
            "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/$record_id" \
            -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{
                \"type\": \"TXT\",
                \"name\": \"$challenge_name\",
                \"content\": \"$challenge_value\",
                \"ttl\": 60
            }")
    else
        # Create new record
        print_status "Creating new TXT record"
        local response=$(curl -s -X POST \
            "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
            -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{
                \"type\": \"TXT\",
                \"name\": \"$challenge_name\",
                \"content\": \"$challenge_value\",
                \"ttl\": 60
            }")
    fi
    
    # Check response
    local success=$(echo "$response" | jq -r '.success // false')
    if [[ "$success" == "true" ]]; then
        print_success "DNS challenge record updated successfully"
        return 0
    else
        local error=$(echo "$response" | jq -r '.errors[0].message // "Unknown error"')
        print_error "Failed to update DNS challenge record: $error"
        return 1
    fi
}

# Function to wait for DNS propagation
wait_for_dns_propagation() {
    local challenge_name="$1"
    local challenge_value="$2"
    local max_attempts=30
    local attempt=1
    
    print_status "Waiting for DNS propagation (max $max_attempts attempts)..."
    
    while [[ $attempt -le $max_attempts ]]; do
        print_status "Attempt $attempt/$max_attempts - Checking DNS propagation..."
        
        # Use dig to check DNS propagation
        local dns_result=$(dig +short TXT "$challenge_name" 2>/dev/null | grep -o "\"$challenge_value\"" || echo "")
        
        if [[ -n "$dns_result" ]]; then
            print_success "DNS challenge record is now accessible"
            return 0
        fi
        
        if [[ $attempt -lt $max_attempts ]]; then
            print_status "DNS not yet propagated, waiting 10 seconds..."
            sleep 10
        fi
        
        ((attempt++))
    done
    
    print_warning "DNS propagation timeout. Proceeding anyway..."
    return 0
}

# Function to run certbot
run_certbot() {
    print_status "Running certbot with DNS challenge..."
    
    # Run certbot in manual mode
    sudo certbot certonly --manual --preferred-challenges=dns -d "$DOMAIN" \
        --manual-public-ip-logging-ok \
        --agree-tos \
        --email "$CLOUDFLARE_EMAIL" \
        --non-interactive \
        --manual-auth-hook "$0" \
        --manual-cleanup-hook "$0"
    
    if [[ $? -eq 0 ]]; then
        print_success "SSL certificate obtained successfully"
    else
        print_error "Failed to obtain SSL certificate"
        exit 1
    fi
}

# Function to cleanup DNS challenge records
cleanup_dns_challenge() {
    print_status "Cleaning up DNS challenge records..."
    
    # Remove the _acme-challenge TXT record
    local challenge_name="_acme-challenge.$DOMAIN"
    
    local existing_record=$(curl -s -X GET \
        "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records?name=$challenge_name&type=TXT" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json")
    
    local record_id=$(echo "$existing_record" | jq -r '.result[0].id // empty')
    
    if [[ -n "$record_id" && "$record_id" != "null" ]]; then
        print_status "Removing DNS challenge record (ID: $record_id)"
        local response=$(curl -s -X DELETE \
            "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/$record_id" \
            -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
            -H "Content-Type: application/json")
        
        local success=$(echo "$response" | jq -r '.success // false')
        if [[ "$success" == "true" ]]; then
            print_success "DNS challenge record removed successfully"
        else
            print_warning "Failed to remove DNS challenge record"
        fi
    fi
}

# Function to copy SSL certificates to Home Assistant
copy_certificates_to_ha() {
    print_status "Copying SSL certificates to Home Assistant..."
    
    # Check if source certificates exist
    local cert_source="/etc/letsencrypt/live/$DOMAIN"
    if [[ ! -f "$cert_source/fullchain.pem" ]] || [[ ! -f "$cert_source/privkey.pem" ]]; then
        print_error "SSL certificates not found in $cert_source"
        return 1
    fi
    
    # Create SSL directory if it doesn't exist
    if [[ ! -d "$HA_SSL_DIR" ]]; then
        print_status "Creating SSL directory: $HA_SSL_DIR"
        sudo mkdir -p "$HA_SSL_DIR"
        if [[ $? -ne 0 ]]; then
            print_error "Failed to create SSL directory"
            return 1
        fi
    fi
    
    # Copy certificates
    print_status "Copying private key..."
    sudo cp "$cert_source/privkey.pem" "$HA_SSL_DIR/$HA_PRIVKEY_NAME"
    if [[ $? -ne 0 ]]; then
        print_error "Failed to copy private key"
        return 1
    fi
    
    print_status "Copying full chain certificate..."
    sudo cp "$cert_source/fullchain.pem" "$HA_SSL_DIR/$HA_FULLCHAIN_NAME"
    if [[ $? -ne 0 ]]; then
        print_error "Failed to copy full chain certificate"
        return 1
    fi
    
    # Set proper permissions
    print_status "Setting proper permissions..."
    sudo chown -R 1000:1000 "$HA_SSL_DIR" 2>/dev/null || true
    sudo chmod 600 "$HA_SSL_DIR/$HA_PRIVKEY_NAME"
    sudo chmod 644 "$HA_SSL_DIR/$HA_FULLCHAIN_NAME"
    
    print_success "SSL certificates copied to Home Assistant successfully"
    return 0
}

# Function to restart Home Assistant container
restart_home_assistant() {
    print_status "Restarting Home Assistant container..."
    
    # Check if Docker is running
    if ! command -v docker &> /dev/null; then
        print_warning "Docker not found. Please restart Home Assistant manually."
        return 1
    fi
    
    # Check if container exists
    if ! docker ps -a --format "table {{.Names}}" | grep -q "^$HA_CONTAINER_NAME$"; then
        print_warning "Home Assistant container '$HA_CONTAINER_NAME' not found. Please restart manually."
        return 1
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
        return 1
    fi
    
    return 0
}

# Main execution
main() {
    print_status "Starting SSL certificate generation with DNS challenge for $DOMAIN"
    
    # Check if this is a hook call from certbot
    if [[ "$CERTBOT_AUTH_OUTPUT" ]]; then
        # This is the cleanup hook
        cleanup_dns_challenge
        exit 0
    fi
    
    # Check dependencies and configuration
    check_dependencies
    validate_config
    
    # Get the DNS challenge details from certbot
    if [[ "$CERTBOT_DOMAIN" && "$CERTBOT_VALIDATION" ]]; then
        local challenge_name="_acme-challenge.$CERTBOT_DOMAIN"
        local challenge_value="$CERTBOT_VALIDATION"
        
        # Update DNS challenge record
        if update_dns_challenge "$challenge_name" "$challenge_value"; then
            # Wait for DNS propagation
            wait_for_dns_propagation "$challenge_name" "$challenge_value"
            print_success "DNS challenge setup complete"
        else
            print_error "Failed to setup DNS challenge"
            exit 1
        fi
        exit 0
    fi
    
    # Run certbot
    run_certbot
    
    print_success "SSL certificate generation completed successfully!"
    print_status "Certificate files are located in /etc/letsencrypt/live/$DOMAIN/"
    
    # Copy certificates to Home Assistant
    if copy_certificates_to_ha; then
        # Restart Home Assistant container
        restart_home_assistant
    else
        print_warning "Failed to copy certificates to Home Assistant"
        print_status "Please copy them manually and restart Home Assistant"
    fi
}

# Run main function
main "$@"
