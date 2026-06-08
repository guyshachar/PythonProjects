#!/bin/bash

# Set environment variables
export PWA_HTTP_PORT=${PWA_HTTP_PORT:-3000}
export PWA_HTTPS_PORT=${PWA_HTTPS_PORT:-3443}
export NODE_ENV=${NODE_ENV:-development}

# Optional: Load from .env file if it exists
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "Starting PWA Server with:"
echo "  HTTP_PORT: $PWA_HTTP_PORT"
echo "  HTTPS_PORT: $PWA_HTTPS_PORT"
echo "  NODE_ENV: $NODE_ENV"

# Start the server
node start-server.js
