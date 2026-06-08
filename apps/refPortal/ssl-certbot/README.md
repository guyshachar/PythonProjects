# Certbot DNS Challenge with Cloudflare API

This script automates the process of obtaining SSL certificates using Let's Encrypt with DNS challenges, specifically designed to work with Cloudflare DNS.

## Features

- Automatically creates/updates DNS challenge records in Cloudflare
- Waits for DNS propagation before proceeding
- Cleans up challenge records after certificate generation
- Automatically copies SSL certificates to Home Assistant
- Restarts Home Assistant container after certificate update
- Colored output for better readability
- Error handling and validation
- Uses Cloudflare API v4 with token authentication

## Prerequisites

1. **Certbot** - SSL certificate tool
2. **curl** - HTTP client for API calls
3. **jq** - JSON processor
4. **dig** - DNS lookup tool
5. **Cloudflare API Token** with Zone:DNS:Edit permissions

## Installation

### 1. Install Dependencies

```bash
# On Ubuntu/Debian/Raspberry Pi OS
sudo apt update
sudo apt install certbot curl jq dnsutils

# On CentOS/RHEL
sudo yum install certbot curl jq bind-utils
```

### 2. Get Cloudflare Credentials

1. **Zone ID**: Go to Cloudflare dashboard → Select your domain → Overview page shows Zone ID
2. **API Token**: Go to Cloudflare dashboard → My Profile → API Tokens → Create Token
   - Use "Custom token" template
   - Permissions: Zone → DNS → Edit
   - Zone Resources: Include → Specific zone → Select your domain

### 3. Configure the Script

```bash
# Copy the template
cp config.env.template config.env

# Edit with your actual values
nano config.env
```

Fill in your actual values:
```bash
CLOUDFLARE_ZONE_ID="abc123def456ghi789"
CLOUDFLARE_API_TOKEN="your_actual_token_here"
CLOUDFLARE_EMAIL="your_email@example.com"
DOMAIN="ha.refereex.com"
```

### 4. Make Script Executable

```bash
chmod +x certbot-cloudflare-update.sh
```

## Usage

### Basic Usage

```bash
# Run the script (it will source config.env automatically)
./certbot-cloudflare-update.sh
```

### Manual Configuration

If you prefer to set variables directly in the script:

```bash
# Edit the script and update these variables at the top
DOMAIN="ha.refereex.com"
CLOUDFLARE_ZONE_ID="your_zone_id"
CLOUDFLARE_API_TOKEN="your_token"
CLOUDFLARE_EMAIL="your_email"
```

## How It Works

1. **Validation**: Checks dependencies and configuration
2. **DNS Challenge Setup**: Creates/updates `_acme-challenge.yourdomain.com` TXT record
3. **DNS Propagation**: Waits for the record to be accessible (up to 5 minutes)
4. **Certificate Generation**: Runs certbot with DNS challenge
5. **Cleanup**: Removes the challenge record from DNS
6. **Home Assistant Integration**: Copies certificates to Home Assistant SSL folder
7. **Container Restart**: Restarts Home Assistant container to use new certificates

## Troubleshooting

### Common Issues

1. **Permission Denied**: Make sure the script is executable (`chmod +x`)
2. **API Token Invalid**: Verify your API token has correct permissions
3. **Zone ID Wrong**: Check the Zone ID in your Cloudflare dashboard
4. **DNS Not Propagating**: The script waits up to 5 minutes, but some DNS providers may take longer

### Debug Mode

To see more detailed output, you can modify the script to add `set -x` at the top:

```bash
#!/bin/bash
set -x  # Add this line for debug output
set -e
```

### Manual DNS Verification

You can manually check if the DNS challenge record is accessible:

```bash
dig TXT _acme-challenge.ha.refereex.com
```

## Security Notes

- Keep your API token secure and don't commit it to version control
- The script uses environment variables for sensitive data
- Consider using a dedicated API token with minimal required permissions
- The script automatically cleans up challenge records after use

## Certificate Renewal

For automatic renewal, add this to your crontab:

```bash
# Edit crontab
crontab -e

# Add this line to run daily at 2 AM
0 2 * * * /path/to/ssl-certbot/certbot-cloudflare-update.sh
```

## File Locations

After successful execution, your certificates will be located at:
- **Certificate**: `/etc/letsencrypt/live/ha.refereex.com/fullchain.pem`
- **Private Key**: `/etc/letsencrypt/live/ha.refereex.com/privkey.pem`
- **Chain**: `/etc/letsencrypt/live/ha.refereex.com/chain.pem`

### Home Assistant Integration

The script automatically copies the certificates to:
- **Private Key**: `/opt/homeassistant/config/ssl/ha.privkey.pem`
- **Full Chain**: `/opt/homeassistant/config/ssl/ha.fullchain.pem`

And restarts the Home Assistant container to use the new certificates.

## Support

If you encounter issues:
1. Check the error messages in the script output
2. Verify your Cloudflare credentials
3. Ensure all dependencies are installed
4. Check that your domain is properly configured in Cloudflare
