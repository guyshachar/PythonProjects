#!/bin/bash

# Deployment script with automatic version increment
# Usage: ./deploy-with-version-update.sh [version_type]
# version_type: patch (default), minor, major

set -e

VERSION_TYPE=${1:-patch}
SW_FILE="rpPwa/js/refportal-sw.js"
CURRENT_VERSION=$(grep -o "const CACHE_VERSION = '[^']*'" "$SW_FILE" | cut -d"'" -f2)

echo "🚀 Starting deployment with version update..."
echo "📦 Current version: $CURRENT_VERSION"
echo "🔄 Version type: $VERSION_TYPE"

# Extract version numbers
IFS='.' read -ra VERSION_PARTS <<< "$CURRENT_VERSION"
MAJOR=${VERSION_PARTS[0]#v}
MINOR=${VERSION_PARTS[1]}
PATCH=${VERSION_PARTS[2]}

# Increment version based on type
case $VERSION_TYPE in
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
        echo "❌ Invalid version type. Use: patch, minor, or major"
        exit 1
        ;;
esac

NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"
echo "✨ New version: $NEW_VERSION"

# Update service worker version
echo "📝 Updating service worker version..."
sed -i.bak "s/const CACHE_VERSION = '[^']*'/const CACHE_VERSION = '$NEW_VERSION'/" "$SW_FILE"
rm "${SW_FILE}.bak"

# Update config service version if it exists
CONFIG_FILE="rpPwa/js/config-service.js"
if [ -f "$CONFIG_FILE" ]; then
    echo "📝 Updating config service version..."
    sed -i.bak "s/CACHE_VERSION: '[^']*'/CACHE_VERSION: '$NEW_VERSION'/" "$CONFIG_FILE"
    rm "${CONFIG_FILE}.bak"
fi

# Update PWA manifest version if it exists
MANIFEST_FILE="rpPwa/refportal-manifest.json"
if [ -f "$MANIFEST_FILE" ]; then
    echo "📝 Updating manifest version..."
    # Update version in manifest (adjust field name as needed)
    if command -v jq &> /dev/null; then
        jq --arg version "$NEW_VERSION" '.version = $version' "$MANIFEST_FILE" > "${MANIFEST_FILE}.tmp" && mv "${MANIFEST_FILE}.tmp" "$MANIFEST_FILE"
    else
        echo "⚠️ jq not found, skipping manifest update"
    fi
fi

echo "✅ Version updated to $NEW_VERSION"

# Run your existing deployment commands here
echo "🚀 Running deployment commands..."

# Example deployment commands (customize based on your setup)
if [ -f "deployService.sh" ]; then
    echo "📦 Running service deployment..."
    ./deployService.sh
fi

if [ -f "deployFastApi.sh" ]; then
    echo "🌐 Running API deployment..."
    ./deployFastApi.sh
fi

if [ -f "deployPwa.sh" ]; then
    echo "📱 Running PWA deployment..."
    ./deployPwa.sh
fi

echo "🎉 Deployment completed successfully!"
echo "📊 Version: $CURRENT_VERSION → $NEW_VERSION"
echo "🔄 Users will be notified of the update automatically"

# Optional: Create a git tag
if command -v git &> /dev/null && [ -d ".git" ]; then
    echo "🏷️ Creating git tag: $NEW_VERSION"
    git add -A
    git commit -m "Deploy version $NEW_VERSION" || true
    git tag "$NEW_VERSION" || true
    echo "✅ Git tag created: $NEW_VERSION"
fi
