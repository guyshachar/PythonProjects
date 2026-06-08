#!/bin/bash

# Startup script for RefPortal Cronjob Client on EC2
set -e

echo "Starting RefPortal Cronjob Client..."

# Set timezone
export TZ=Asia/Jerusalem

# Create log directories
mkdir -p /var/log/cronjob
mkdir -p /var/run/supervisor

# Set proper permissions
chmod 755 /var/log/cronjob
chmod 755 /var/run/supervisor

# Initialize cron if needed
if [ ! -f /var/spool/cron/crontabs/root ]; then
    echo "Initializing cron..."
    crontab -l 2>/dev/null || echo "# RefPortal Cronjob Client" | crontab -
fi

# Start supervisor
echo "Starting supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
