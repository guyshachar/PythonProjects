#!/bin/bash

# Docker Hub Push Script for RefPortal
# This script builds and pushes RefPortal Docker images to Docker Hub
# Usage: ./push2dockerhub.sh [service_name] [options]
# Examples:
#   ./push2dockerhub.sh                    # Deploy all services
#   ./push2dockerhub.sh api                # Deploy only api service
#   ./push2dockerhub.sh pwa                # Deploy only PWA service (auto-increments CACHE_VERSION)
#   ./push2dockerhub.sh gw                 # Deploy only main gw
#   ./push2dockerhub.sh --list             # List available services
# 
# Note: When deploying the PWA service, the CACHE_VERSION in refportal-sw.js
#       is automatically incremented (patch version) before building.

set -e  # Exit on any error

# Directory containing this script (works when run from any cwd)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

env=prod
export DOCKER_HUB_USERNAME=guyshacharacc

# After a successful build/push, SSH to this host and run the prod restart (set SKIP_PROD_SSH_RESTART=1 to skip).
PROD_SSH_HOST="${PROD_SSH_HOST:-ec2-guy}"

# Configuration
DOCKER_HUB_USERNAME="${DOCKER_HUB_USERNAME:-your-dockerhub-username}"
#DOCKER_HUB_REPO_PREFIX="${DOCKER_HUB_REPO_PREFIX:-refportal}"
DOCKER_HUB_REPO_PREFIX="${DOCKER_HUB_REPO_PREFIX}"
VERSION="${VERSION:-latest-$env}"
REGISTRY="docker.io"

# Available services configuration
# Using a more compatible approach for service definitions
SERVICES="api:./rpApi/apiDockerfile:refportalapi
pwa:./rpPwa/pwaDockerfile:refportalpwa
gw:./rpGw/gwDockerfile:refportalgw
cronjob:./rpCronjob/cjDockerfile:refportalcronjob
eventbridge:./eventBridgeDockerfile:refportaleventbridge
monitor:./monitorDockerfile:refportalmonitor"

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

# Function to get service info
get_service_info() {
    local service_name="$1"
    echo "$SERVICES" | grep "^$service_name:" | cut -d':' -f2-
}

# Function to get all service names
get_all_services() {
    echo "$SERVICES" | cut -d':' -f1
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [service_name] [options]"
    echo ""
    echo "Available services:"
    while IFS= read -r line; do
        local service=$(echo "$line" | cut -d':' -f1)
        local dockerfile=$(echo "$line" | cut -d':' -f2)
        local imagename=$(echo "$line" | cut -d':' -f3)
        echo "  $service     - $imagename ($dockerfile)"
    done <<< "$SERVICES"
    echo ""
    echo "Options:"
    echo "  --list, -l     List available services"
    echo "  --help, -h     Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                    # Deploy all services"
    echo "  $0 api                # Deploy only api service"
    echo "  $0 pwa gw        # Deploy PWA and main gw"
    echo "  $0 --list             # List available services"
}

# Function to list available services
list_services() {
    print_status "Available RefPortal services:"
    echo ""
    while IFS= read -r line; do
        local service=$(echo "$line" | cut -d':' -f1)
        local dockerfile=$(echo "$line" | cut -d':' -f2)
        local imagename=$(echo "$line" | cut -d':' -f3)
        echo "  $service     - $imagename"
        echo "              Dockerfile: $dockerfile"
        echo ""
    done <<< "$SERVICES"
}

# Function to parse command line arguments
parse_arguments() {
    local services_to_deploy=()
    local show_help=false
    local show_list=false
    
    # Check for help or list flags first
    for arg in "$@"; do
        case $arg in
            --help|-h)
                show_help=true
                break
                ;;
            --list|-l)
                show_list=true
                break
                ;;
        esac
    done
    
    if [[ "$show_help" == true ]]; then
        show_usage
        exit 0
    fi
    
    if [[ "$show_list" == true ]]; then
        list_services
        exit 0
    fi
    
    # Parse service arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h|--list|-l)
                # Already handled above
                shift
                ;;
            -*)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
            *)
                if get_service_info "$1" >/dev/null 2>&1; then
                    services_to_deploy+=("$1")
                else
                    print_error "Unknown service: $1"
                    print_status "Available services: $(get_all_services | tr '\n' ' ')"
                    exit 1
                fi
                shift
                ;;
        esac
    done
    
    # If no services specified, deploy all
    if [[ ${#services_to_deploy[@]} -eq 0 ]]; then
        services_to_deploy=($(get_all_services))
    fi
    
    echo "${services_to_deploy[@]}"
}

# Function to check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    print_success "Docker is running"
}

# Python for credential scripts: override with REFPORTAL_PUSH_PYTHON, else .venv, else venv, else python3
refportal_push_python() {
    if [ -n "${REFPORTAL_PUSH_PYTHON:-}" ]; then
        echo "$REFPORTAL_PUSH_PYTHON"
    elif [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
        echo "$SCRIPT_DIR/.venv/bin/python3"
    elif [ -x "$SCRIPT_DIR/venv/bin/python3" ]; then
        echo "$SCRIPT_DIR/venv/bin/python3"
    else
        echo "python3"
    fi
}

# Function to get Docker Hub credentials from AWS Secrets Manager
get_dockerhub_credentials() {
    print_status "Retrieving Docker Hub credentials from AWS Secrets Manager..."
    export AWS_LAMBDA_FUNCTION_NAME=aaa
    local PYTHON_CMD
    PYTHON_CMD="$(refportal_push_python)"
    if ! "$PYTHON_CMD" -c "import boto3" 2>/dev/null; then
        print_error "boto3 is not installed for: $PYTHON_CMD"
        print_status "Create a venv and install minimal deps (one-time):"
        print_status "  cd \"$SCRIPT_DIR\" && python3 -m venv .venv && .venv/bin/pip install -r requirements-push2dockerhub.txt"
        print_status "Or use existing venv: \"$SCRIPT_DIR/venv/bin/pip\" install -r requirements-push2dockerhub.txt"
        print_status "Or: pip install boto3"
        print_status "Or set REFPORTAL_PUSH_PYTHON to a Python that has boto3."
        return 1
    fi
    # Check if Python script exists (try simple version first)
    local script_path="$SCRIPT_DIR/get_dockerhub_credentials_simple.py"
    if [ ! -f "$script_path" ]; then
        script_path="$SCRIPT_DIR/get_dockerhub_credentials.py"
        if [ ! -f "$script_path" ]; then
            print_error "Docker Hub credentials script not found under $SCRIPT_DIR (get_dockerhub_credentials_simple.py or get_dockerhub_credentials.py)."
            return 1
        fi
    fi
    
    # Get credentials from AWS Secrets Manager
    local credentials_output
    credentials_output=$("$PYTHON_CMD" "$script_path" 2>&1)
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        print_error "Failed to retrieve Docker Hub credentials from AWS Secrets Manager"
        print_status "Make sure the following secrets exist in AWS Secrets Manager:"
        print_status "  - dockerhub_username"
        print_status "  - dockerhub_password"
        print_status "Error: $credentials_output"
        return 1
    fi
    
    # Parse credentials from output
    DOCKER_HUB_USERNAME=$(echo "$credentials_output" | grep "DOCKER_HUB_USERNAME=" | cut -d'=' -f2)
    DOCKER_HUB_PASSWORD=$(echo "$credentials_output" | grep "DOCKER_HUB_PASSWORD=" | cut -d'=' -f2)
    
    if [ -z "$DOCKER_HUB_USERNAME" ] || [ -z "$DOCKER_HUB_PASSWORD" ]; then
        print_error "Failed to parse Docker Hub credentials from AWS Secrets Manager"
        return 1
    fi
    print_success "Successfully retrieved Docker Hub credentials from AWS Secrets Manager"
    return 0
}

# Function to login to Docker Hub
docker_login() {
    print_status "Logging in to Docker Hub..."
    
    # Try to get credentials from AWS Secrets Manager first
    if get_dockerhub_credentials; then
        # Use credentials from AWS Secrets Manager
        echo "$DOCKER_HUB_PASSWORD" | docker login --username "$DOCKER_HUB_USERNAME" --password-stdin
        local login_exit_code=$?
        
        if [ $login_exit_code -eq 0 ]; then
            print_success "Logged in to Docker Hub as $DOCKER_HUB_USERNAME (using AWS Secrets Manager)"
        else
            print_error "Failed to login to Docker Hub with credentials from AWS Secrets Manager"
            return 1
        fi
    else
        # Fallback to manual login
        print_warning "Falling back to manual Docker Hub login..."
        if [ -z "$DOCKER_HUB_USERNAME" ] || [ "$DOCKER_HUB_USERNAME" = "your-dockerhub-username" ]; then
            print_error "Please set DOCKER_HUB_USERNAME environment variable or ensure AWS Secrets Manager is configured"
            print_status "Example: export DOCKER_HUB_USERNAME=yourusername"
            exit 1
        fi
        
        echo "Please enter your Docker Hub password:"
        docker login --username "$DOCKER_HUB_USERNAME"
        local login_exit_code=$?
        
        if [ $login_exit_code -eq 0 ]; then
            print_success "Logged in to Docker Hub as $DOCKER_HUB_USERNAME (manual login)"
        else
            print_error "Failed to login to Docker Hub"
            return 1
        fi
    fi
}

# Function to update CACHE_VERSION in service worker
update_cache_version() {
    local version_type="${1:-patch}"
    local SW_FILE="$SCRIPT_DIR/rpPwa/js/refportal-sw.js"
    
    if [ ! -f "$SW_FILE" ]; then
        print_warning "Service worker file not found: $SW_FILE. Skipping version update."
        return 0
    fi
    
    print_status "Updating CACHE_VERSION in service worker..."
    
    # Get current version
    local CURRENT_VERSION
    CURRENT_VERSION=$(grep -o "const CACHE_VERSION = '[^']*'" "$SW_FILE" | cut -d"'" -f2 || echo "v1.0.0")
    
    if [ -z "$CURRENT_VERSION" ]; then
        print_warning "Could not detect current version. Starting from v1.0.0"
        CURRENT_VERSION="v1.0.0"
    fi
    
    print_status "Current CACHE_VERSION: $CURRENT_VERSION"
    
    # Extract version numbers (remove 'v' prefix if present)
    local version_str="${CURRENT_VERSION#v}"
    IFS='.' read -ra VERSION_PARTS <<< "$version_str"
    local MAJOR=${VERSION_PARTS[0]:-1}
    local MINOR=${VERSION_PARTS[1]:-0}
    local PATCH=${VERSION_PARTS[2]:-0}
    
    # Increment version based on type
    case $version_type in
        major)
            MAJOR=$((MAJOR + 1))
            MINOR=0
            PATCH=0
            ;;
        minor)
            MINOR=$((MINOR + 1))
            PATCH=0
            ;;
        patch)
            PATCH=$((PATCH + 1))
            ;;
        *)
            print_warning "Invalid version type: $version_type. Using 'patch' instead."
            PATCH=$((PATCH + 1))
            ;;
    esac
    
    local NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"
    print_status "New CACHE_VERSION: $NEW_VERSION"
    
    # Update service worker version (works on both macOS and Linux)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS version
        sed -i.bak "s/const CACHE_VERSION = '[^']*'/const CACHE_VERSION = '$NEW_VERSION'/" "$SW_FILE"
        rm -f "${SW_FILE}.bak" 2>/dev/null || true
    else
        # Linux version
        sed -i "s/const CACHE_VERSION = '[^']*'/const CACHE_VERSION = '$NEW_VERSION'/" "$SW_FILE"
    fi
    
    print_success "CACHE_VERSION updated to $NEW_VERSION"
}

# Function to build and push a Docker image
build_and_push() {
    local dockerfile=$1
    local image_name=$2
    local tag=$3
    local service_name=$4  # Optional service name for special handling
    
    # If building PWA service, update CACHE_VERSION first
    if [ "$service_name" = "pwa" ]; then
        update_cache_version "patch"
    fi
    
    print_status "Building $image_name from $dockerfile..."
    
    # Dockerfile path: resolve relative to SCRIPT_DIR so build works from any cwd
    local df="$dockerfile"
    if [[ "$df" == ./* ]]; then
        df="$SCRIPT_DIR/${df#./}"
    elif [[ "$df" != /* ]]; then
        df="$SCRIPT_DIR/$df"
    fi
    
    # Build the image (context is always refPortal repo root)
    docker build -f "$df" -t "$image_name:$tag" "$SCRIPT_DIR"
    
    if [ $? -eq 0 ]; then
        print_success "Successfully built $image_name:$tag"
    else
        print_error "Failed to build $image_name:$tag"
        return 1
    fi
    
    # Tag for Docker Hub
    local hub_image="$DOCKER_HUB_USERNAME/$DOCKER_HUB_REPO_PREFIX$image_name:$tag"
    docker tag "$image_name:$tag" "$hub_image"
    
    print_status "Pushing $hub_image to Docker Hub..."
    docker push "$hub_image"
    
    if [ $? -eq 0 ]; then
        print_success "Successfully pushed $hub_image"
    else
        print_error "Failed to push $hub_image"
        return 1
    fi

    # Free disk space: remove local tags after a successful push (same image ID)
    print_status "Removing local image tag: $hub_image"
    if docker rmi "$hub_image" 2>/dev/null; then
        print_success "Removed local image for $hub_image"
    else
        print_warning "Could not remove local image (image may be in use by a container); run: docker rmi $hub_image"
    fi
}

# Main execution
main() {
    # Check for help/list flags first
    for arg in "$@"; do
        case $arg in
            --help|-h)
                show_usage
                exit 0
                ;;
            --list|-l)
                list_services
                exit 0
                ;;
        esac
    done
    
    # Parse command line arguments
    local services_to_deploy=($(parse_arguments "$@"))
    
    print_status "Starting RefPortal Docker Hub deployment..."
    print_status "Docker Hub Username: $DOCKER_HUB_USERNAME"
    print_status "Repository Prefix: $DOCKER_HUB_REPO_PREFIX"
    print_status "Version: $VERSION"
    print_status "Services to deploy: ${services_to_deploy[*]}"
    
    # Check prerequisites
    check_docker
    docker_login
    
    # Build and push specified images
    local deployed_services=()
    local failed_services=()
    
    for service in "${services_to_deploy[@]}"; do
        local service_info=$(get_service_info "$service")
        local dockerfile=$(echo "$service_info" | cut -d':' -f1)
        local imagename=$(echo "$service_info" | cut -d':' -f2)
        
        print_status "Building and pushing $service ($imagename)..."

        if build_and_push "$dockerfile" "$imagename" "$VERSION" "$service"; then
            deployed_services+=("$service")
        else
            failed_services+=("$service")
        fi
    done
    
    # Summary
    echo ""
    if [[ ${#deployed_services[@]} -gt 0 ]]; then
        print_success "Successfully deployed services: ${deployed_services[*]}"
        print_status "You can now pull these images using:"
        for service in "${deployed_services[@]}"; do
            local service_info=$(get_service_info "$service")
            local imagename=$(echo "$service_info" | cut -d':' -f2)
            echo "  docker pull $DOCKER_HUB_USERNAME/$DOCKER_HUB_REPO_PREFIX$imagename:$VERSION"
        done
    fi
    
    if [[ ${#failed_services[@]} -gt 0 ]]; then
        print_error "Failed to deploy services: ${failed_services[*]}"
        exit 1
    fi

    if [[ ${#deployed_services[@]} -gt 0 && -z "${SKIP_PROD_SSH_RESTART:-}" ]]; then
        print_status "Running remote production restart: ssh $PROD_SSH_HOST './refPortalService/restart.sh $env'"
        ssh "$PROD_SSH_HOST" "./refPortalService/restart.sh $env"
        print_success "Remote restart on $PROD_SSH_HOST completed"
    elif [[ -n "${SKIP_PROD_SSH_RESTART:-}" ]]; then
        print_warning "Skipped remote restart (SKIP_PROD_SSH_RESTART is set)"
    fi

    print_success "Deployment completed successfully! time: $(date)"
}

# Run main function
main "$@"

#
#
# Minimal Python deps for Docker Hub login (AWS Secrets Manager): see requirements-push2dockerhub.txt