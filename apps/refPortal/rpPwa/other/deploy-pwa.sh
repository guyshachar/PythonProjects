#!/bin/bash

# RefereeX PWA Manual Docker Deployment Script
# This script provides manual Docker build and deployment commands
# Supports both container and service deployment modes

app=refportalpwa
app_env=$1
action=$2

set -e

# Configuration
IMAGE_NAME="guyshacharacc/${app}"
CONTAINER_NAME="${app}"
SERVICE_NAME="${app}-${app_env}-service"
TAG="latest-${app_env}"
HTTP_PORT="8082"
HTTPS_PORT="8443"
SSL_DIR="./ssl"
LOGS_DIR="./logs"
DEPLOYMENT_MODE="service"  # "container" or "service"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} ${action}"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} ${action}"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} ${action}"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} ${action}"
}

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker first."
        exit 1
    fi
    print_success "Docker is running"
}

# Function to check if Docker Swarm is initialized
check_swarm() {
    if ! docker info --format '{{.Swarm.LocalNodeState}}' | grep -q "active"; then
        print_warning "Docker Swarm is not initialized. Initializing now..."
        docker swarm init --advertise-addr 127.0.0.1
        print_success "Docker Swarm initialized"
    else
        print_success "Docker Swarm is active"
    fi
}

# Function to create necessary directories
create_directories() {
    print_status "Creating necessary directories..."
    mkdir -p "$SSL_DIR"
    mkdir -p "$LOGS_DIR"
    print_success "Directories created"
}

# Function to build the Docker image
pull_image() {
    print_status "Building Docker image: $IMAGE_NAME:$TAG"
    docker image pull $IMAGE_NAME:$TAG
    print_success "Image pulled successfully"
}

# Function to build the Docker image
build_image() {
    print_status "Building Docker image: $IMAGE_NAME:$TAG"
    docker build -f pwaDockerfile -t "$IMAGE_NAME:$TAG" .
    print_success "Image built successfully"
}

# Function to stop and remove existing container
cleanup_container() {
    if docker ps -a --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
        print_status "Stopping existing container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        print_status "Removing existing container: $CONTAINER_NAME"
        docker rm "$CONTAINER_NAME" 2>/dev/null || true
        print_success "Container cleanup completed"
    fi
}

# Function to stop and remove existing service
cleanup_service() {
    if docker service ls --format "table {{.Name}}" | grep -q "$SERVICE_NAME"; then
        print_status "Removing existing service: $SERVICE_NAME"
        docker service rm "$SERVICE_NAME"
        print_success "Service cleanup completed"
    fi
}

# Function to run the container
run_container() {
    print_status "Starting container: $CONTAINER_NAME"
    docker run -d \
        --name "$CONTAINER_NAME" \
        -p "$HTTP_PORT:$HTTP_PORT" \
        -p "$HTTPS_PORT:$HTTPS_PORT" \
        -v "$(pwd)/$SSL_DIR:/app/ssl:ro" \
        -v "$(pwd)/$LOGS_DIR:/app/logs" \
        --restart unless-stopped \
        "$IMAGE_NAME:$TAG"
    
    print_success "Container started successfully"
}

# Function to run the service
run_service() {
    print_status "Starting service: $SERVICE_NAME"
    docker service create \
        --name "$SERVICE_NAME" \
        --publish "$HTTP_PORT:$HTTP_PORT" \
        --publish "$HTTPS_PORT:$HTTPS_PORT" \
        --mount type=bind,source="$(pwd)/$SSL_DIR",target=/app/ssl,readonly=true \
        --mount type=bind,source="$(pwd)/$LOGS_DIR",target=/app/logs \
        --replicas 1 \
        --restart-condition any \
        "$IMAGE_NAME:$TAG"
    
    print_success "Service started successfully"
}

# Function to show container status
show_status() {
    if [ "$DEPLOYMENT_MODE" = "service" ]; then
        print_status "Service status:"
        docker service ls --filter "name=$SERVICE_NAME" --format "table {{.Name}}\t{{.Replicas}}\t{{.Ports}}"
        print_status "Service tasks:"
        docker service ps "$SERVICE_NAME" --format "table {{.Name}}\t{{.Node}}\t{{.CurrentState}}\t{{.Error}}"
    else
        print_status "Container status:"
        docker ps -a --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    fi
}

# Function to show logs
show_logs() {
    if [ "$DEPLOYMENT_MODE" = "service" ]; then
        if docker service ls --format "table {{.Name}}" | grep -q "$SERVICE_NAME"; then
            print_status "Showing service logs (press Ctrl+C to exit):"
            docker service logs -f "$SERVICE_NAME"
        else
            print_warning "Service is not running"
        fi
    else
        if docker ps --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
            print_status "Showing container logs (press Ctrl+C to exit):"
            docker logs -f "$CONTAINER_NAME"
        else
            print_warning "Container is not running"
        fi
    fi
}

# Function to stop the container
stop_container() {
    if docker ps --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
        print_status "Stopping container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME"
        print_success "Container stopped"
    else
        print_warning "Container is not running"
    fi
}

# Function to stop the service
stop_service() {
    if docker service ls --format "table {{.Name}}" | grep -q "$SERVICE_NAME"; then
        print_status "Stopping service: $SERVICE_NAME"
        docker service rm "$SERVICE_NAME"
        print_success "Service stopped"
    else
        print_warning "Service is not running"
    fi
}

# Function to remove the container
remove_container() {
    if docker ps -a --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
        print_status "Removing container: $CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
        print_success "Container removed"
    else
        print_warning "Container does not exist"
    fi
}

# Function to remove the image
remove_image() {
    if docker images --format "table {{.Repository}}:{{.Tag}}" | grep -q "$IMAGE_NAME:$TAG"; then
        print_status "Removing image: $IMAGE_NAME:$TAG"
        docker rmi "$IMAGE_NAME:$TAG"
        print_success "Image removed"
    else
        print_warning "Image does not exist"
    fi
}

# Function to execute command in container
exec_container() {
    if docker ps --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
        print_status "Executing command in container: $CONTAINER_NAME"
        docker exec -it "$CONTAINER_NAME" "$@"
    else
        print_warning "Container is not running"
    fi
}

# Function to execute command in service
exec_service() {
    if docker service ls --format "table {{.Name}}" | grep -q "$SERVICE_NAME"; then
        print_status "Executing command in service: $SERVICE_NAME"
        TASK_ID=$(docker service ps "$SERVICE_NAME" --filter "desired-state=running" --format "{{.ID}}" | head -1)
        if [ -n "$TASK_ID" ]; then
            docker exec -it "$TASK_ID" "$@"
        else
            print_warning "No running tasks found for service"
        fi
    else
        print_warning "Service is not running"
    fi
}

# Function to scale service
scale_service() {
    local replicas=${action:-1}
    if docker service ls --format "table {{.Name}}" | grep -q "$SERVICE_NAME"; then
        print_status "Scaling service $SERVICE_NAME to $replicas replicas"
        docker service scale "$SERVICE_NAME=$replicas"
        print_success "Service scaled successfully"
    else
        print_warning "Service is not running"
    fi
}

# Function to show help
show_help() {
    echo "RefereeX PWA Docker Deployment Script"
    echo "====================================="
    echo ""
    echo "Usage: $0 [ENV] [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  build       - Build the Docker image"
    echo "  run         - Build and run (container or service based on mode)"
    echo "  run-container - Build and run as container"
    echo "  run-service   - Build and run as service"
    echo "  start       - Start the container/service (if it exists)"
    echo "  stop        - Stop the container/service"
    echo "  restart     - Restart the container/service"
    echo "  status      - Show container/service status"
    echo "  logs        - Show container/service logs"
    echo "  exec        - Execute command in container/service (e.g., $0 exec sh)"
    echo "  scale       - Scale service replicas (e.g., $0 scale 3)"
    echo "  cleanup     - Stop and remove container/service"
    echo "  remove      - Remove container/service and image"
    echo "  mode        - Set deployment mode (container|service)"
    echo "  help        - Show this help message"
    echo ""
    echo "Deployment Mode: $DEPLOYMENT_MODE"
    echo ""
    echo "Examples:"
    echo "  $0 build        # Build image only"
    echo "  $0 run          # Build and run (based on current mode)"
    echo "  $0 run-service  # Build and run as service"
    echo "  $0 run-container # Build and run as container"
    echo "  $0 scale 3      # Scale service to 3 replicas"
    echo "  $0 logs         # Show logs"
    echo "  $0 exec sh     # Access container/service shell"
    echo "  $0 mode service # Switch to service mode"
}

# Function to set deployment mode
set_deployment_mode() {
    local mode=${action}
    if [ "$mode" = "container" ] || [ "$mode" = "service" ]; then
        DEPLOYMENT_MODE="$mode"
        print_success "Deployment mode set to: $DEPLOYMENT_MODE"
    else
        print_error "Invalid mode. Use 'container' or 'service'"
        exit 1
    fi
}

# Main script logic
case "${action:-help}" in
    "build")
        check_docker
        create_directories
        build_image
        ;;
    "run")
        check_docker
        create_directories
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            check_swarm
            cleanup_service
            build_image
            run_service
        else
            cleanup_container
            build_image
            run_container
        fi
        show_status
        ;;
    "run-container")
        DEPLOYMENT_MODE="container"
        check_docker
        create_directories
        cleanup_container
        build_image
        run_container
        show_status
        ;;
    "run-service")
        DEPLOYMENT_MODE="service"
        check_docker
        check_swarm
        print_status "check swarm"
        create_directories
        cleanup_service
        pull_image
        run_service
        show_status
        ;;
    "start")
        check_docker
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            if docker service ls --format "table {{.Name}}" | grep -q "$SERVICE_NAME"; then
                print_error "Cannot start service directly. Use 'run-service' to recreate."
            else
                print_error "Service does not exist. Run '$0 run-service' first."
            fi
        else
            if docker ps -a --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
                docker start "$CONTAINER_NAME"
                print_success "Container started"
                show_status
            else
                print_error "Container does not exist. Run '$0 run-container' first."
            fi
        fi
        ;;
    "stop")
        check_docker
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            stop_service
        else
            stop_container
        fi
        ;;
    "restart")
        check_docker
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            print_error "Cannot restart service directly. Use 'run-service' to recreate."
        else
            stop_container
            sleep 2
            if docker ps -a --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
                docker start "$CONTAINER_NAME"
                print_success "Container restarted"
                show_status
            else
                print_error "Container does not exist. Run '$0 run-container' first."
            fi
        fi
        ;;
    "status")
        check_docker
        show_status
        ;;
    "logs")
        check_docker
        show_logs
        ;;
    "exec")
        check_docker
        shift
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            exec_service "$@"
        else
            exec_container "$@"
        fi
        ;;
    "scale")
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            check_docker
            check_swarm
            scale_service "$2"
        else
            print_error "Scaling is only available for services. Use 'mode service' first."
        fi
        ;;
    "cleanup")
        check_docker
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            cleanup_service
        else
            cleanup_container
        fi
        ;;
    "remove")
        check_docker
        if [ "$DEPLOYMENT_MODE" = "service" ]; then
            cleanup_service
        else
            cleanup_container
        fi
        remove_image
        ;;
    "mode")
        set_deployment_mode "$2"
        ;;
    "help"|*)
        show_help
        ;;
esac
