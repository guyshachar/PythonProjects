#!/bin/bash

# Test script for Cloudflare API connection

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

# Source config file if it exists
if [[ -f "config.env" ]]; then
    source config.env
    print_status "Loaded configuration from config.env"
else
    print_warning "config.env not found. Please create it first."
    exit 1
fi

# Check if required variables are set
if [[ -z "$CLOUDFLARE_ZONE_ID" ]] || [[ -z "$CLOUDFLARE_API_TOKEN" ]] || [[ -z "$CLOUDFLARE_EMAIL" ]]; then
    print_error "Missing required configuration variables. Please check config.env"
    exit 1
fi

print_status "Testing Cloudflare API connection..."

# Test 1: Verify API token and get user info
print_status "Test 1: Verifying API token..."
user_response=$(curl -s -X GET \
    "https://api.cloudflare.com/client/v4/user" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json")

if [[ $? -ne 0 ]]; then
    print_error "Failed to connect to Cloudflare API"
    exit 1
fi

user_success=$(echo "$user_response" | jq -r '.success // false')
if [[ "$user_success" == "true" ]]; then
    user_email=$(echo "$user_response" | jq -r '.result.email // "Unknown"')
    print_success "API token is valid. User: $user_email"
else
    error_msg=$(echo "$user_response" | jq -r '.errors[0].message // "Unknown error"')
    print_error "API token validation failed: $error_msg"
    exit 1
fi

# Test 2: Verify zone access
print_status "Test 2: Verifying zone access..."
zone_response=$(curl -s -X GET \
    "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json")

if [[ $? -ne 0 ]]; then
    print_error "Failed to fetch zone information"
    exit 1
fi

zone_success=$(echo "$zone_response" | jq -r '.success // false')
if [[ "$zone_success" == "true" ]]; then
    zone_name=$(echo "$zone_response" | jq -r '.result.name // "Unknown"')
    zone_status=$(echo "$zone_response" | jq -r '.result.status // "Unknown"')
    print_success "Zone access verified. Domain: $zone_name (Status: $zone_status)"
else
    error_msg=$(echo "$zone_response" | jq -r '.errors[0].message // "Unknown error"')
    print_error "Zone access failed: $error_msg"
    exit 1
fi

# Test 3: Test DNS record creation (create a test record)
print_status "Test 3: Testing DNS record creation..."
test_record_name="test-api-$(date +%s).$zone_name"
test_content="test-content-$(date +%s)"

create_response=$(curl -s -X POST \
    "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"type\": \"TXT\",
        \"name\": \"$test_record_name\",
        \"content\": \"$test_content\",
        \"ttl\": 60
    }")

if [[ $? -ne 0 ]]; then
    print_error "Failed to create test DNS record"
    exit 1
fi

create_success=$(echo "$create_response" | jq -r '.success // false')
if [[ "$create_success" == "true" ]]; then
    record_id=$(echo "$create_response" | jq -r '.result.id // "Unknown"')
    print_success "Test DNS record created successfully (ID: $record_id)"
    
    # Clean up test record
    print_status "Cleaning up test DNS record..."
    delete_response=$(curl -s -X DELETE \
        "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/$record_id" \
        -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
        -H "Content-Type: application/json")
    
    delete_success=$(echo "$delete_response" | jq -r '.success // false')
    if [[ "$delete_success" == "true" ]]; then
        print_success "Test DNS record cleaned up successfully"
    else
        print_warning "Failed to clean up test DNS record (you may need to remove it manually)"
    fi
else
    error_msg=$(echo "$create_response" | jq -r '.errors[0].message // "Unknown error"')
    print_error "DNS record creation failed: $error_msg"
    exit 1
fi

print_success "All Cloudflare API tests passed!"
print_status "Your configuration is working correctly."
print_status "You can now run the main script: ./certbot-cloudflare-update.sh"

