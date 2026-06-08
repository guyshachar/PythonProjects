export class JwtService {
    // JWT Token parsing utilities
    // 
    // Usage Examples:
    // 
    // 1. Parse JWT token manually:
    //    const payload = JwtService.parseJwtToken(token);
    //    console.log('User:', payload.refName);
    // 
    // 2. Get current user info from stored token:
    //    const user = JwtService.getCurrentUserFromToken();
    //    if (user) console.log('Logged in as:', user.refName);
    // 
    // 3. Check if token is expired:
    //    if (JwtService.isTokenExpired()) {
    //        console.log('Token expired, need to refresh');
    //    }
    // 
    // 4. Check user role:
    //    if (JwtService.hasRole('admin')) {
    //        console.log('User has admin privileges');
    //    }
    // 
    // 5. Display token info for debugging:
    //    JwtService.displayJwtInfo();
    //
    static parseJwtToken(token) {
        try {
            // JWT tokens have 3 parts separated by dots
            const parts = token.split('.');
            if (parts.length !== 3) {
                throw new Error('Invalid JWT token format');
            }
            
            // Decode the payload (second part)
            const payload = parts[1];
            // Add padding if needed for base64 decoding
            const paddedPayload = payload + '='.repeat((4 - payload.length % 4) % 4);
            const decodedPayload = atob(paddedPayload);
            
            return JSON.parse(decodedPayload);
        } catch (error) {
            console.error('Error parsing JWT token:', error);
            return null;
        }
    }

    static async getJwtPayload() {
        // Get token from refresh token service (primary source)
        let token = null;
        if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
            token = await window.refPortalPwa.refreshTokenService.getAccessToken();
        }

        if (!token) {
            return null;
        }
        return JwtService.parseJwtToken(token);
    }

    static isTokenExpired(token = null) {
        // If refresh token service is available, use its expiration checking
        if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
            return window.refPortalPwa.refreshTokenService.isAccessTokenExpired();
        }

        if (!token) {
            return true;
        }
        
        const payload = JwtService.parseJwtToken(token);
        if (!payload || !payload.exp) {
            return true;
        }
        
        // Check if token is expired (with 5 minute buffer)
        const currentTime = Math.floor(Date.now() / 1000);
        const bufferTime = 5 * 60; // 5 minutes in seconds
        return payload.exp < (currentTime + bufferTime);
    }

    static getTokenExpirationTime(token = null) {
        // If refresh token service is available, get expiration from it
        if (window.refPortalPwa && window.refPortalPwa.refreshTokenService) {
            const tokenExpiry = window.refPortalPwa.refreshTokenService.accessTokenExpiry;
            return tokenExpiry ? new Date(tokenExpiry) : null;
        }
        
        if (!token) {
            return null;
        }
        
        const payload = JwtService.parseJwtToken(token);
        if (!payload || !payload.exp) {
            return null;
        }
        
        return new Date(payload.exp * 1000);
    }

    // Get current user info from JWT token
    static async getCurrentUserFromToken() {
        const payload = await JwtService.getJwtPayload();
        if (!payload) {
            return null;
        }
        
        return {
            clientIdentifier: payload.clientIdentifier,
            refName: payload.refName,
            role: payload.role,
            mobileNo: payload.mobileNo,
            allowedSections: payload.allowedSections,
            tenantRefIds: payload.tenantRefIds,
            issuedAt: payload.iat ? new Date(payload.iat * 1000) : null,
            expiresAt: payload.exp ? new Date(payload.exp * 1000) : null,
            issuer: payload.iss
        };
    }

    // Check if user has specific role
    static async hasRole(role) {
        const payload = await JwtService.getJwtPayload();
        return payload && payload.role === role;
    }

    // Get token age in seconds
    static async getTokenAge() {
        const payload = await JwtService.getJwtPayload();
        if (!payload || !payload.iat) {
            return null;
        }
        
        const currentTime = Math.floor(Date.now() / 1000);
        return currentTime - payload.iat;
    }

    // Display JWT token information for debugging
    static async displayJwtInfo() {
        const payload = await JwtService.getJwtPayload();
        if (!payload) {
            console.log('❌ No JWT token found');
            return;
        }
        
        const tokenAge = await JwtService.getTokenAge();
        const expiresIn = await JwtService.getTokenExpirationTime();
        const isExpired = JwtService.isTokenExpired();
        
        console.log('🔐 JWT Token Information:');
        console.log('  📱 Client ID:', payload.clientIdentifier);
        console.log('  👤 Referee ID:', payload.refId);
        console.log('  🏷️  Referee Name:', payload.refName);
        console.log('  🔑 Role:', payload.role);
        console.log('  📞 Mobile:', payload.mobileNo);
        console.log('  🏢 Issuer:', payload.iss);
        console.log('  📅 Issued At:', new Date(payload.iat * 1000).toLocaleString());
        console.log('  ⏰ Expires At:', expiresIn ? expiresIn.toLocaleString() : 'Unknown');
        console.log('  ⏳ Token Age:', tokenAge ? `${tokenAge}s` : 'Unknown');
        console.log('  ❌ Expired:', isExpired ? 'Yes' : 'No');
        
        // Also display in UI if there's a debug element
        const debugElement = document.getElementById('jwtDebugInfo');
        if (debugElement) {
            debugElement.innerHTML = `
                <h4>JWT Token Info</h4>
                <p><strong>Client ID:</strong> ${payload.clientIdentifier}</p>
                <p><strong>Referee:</strong> ${payload.refName || 'N/A'}</p>
                <p><strong>Role:</strong> ${payload.role || 'N/A'}</p>
                <p><strong>Allowed Sections:</strong> ${payload.allowedSections || 'N/A'}</p>
                <p><strong>Tenant Ref IDs:</strong> ${payload.tenantRefIds || 'N/A'}</p>
                <p><strong>Expires:</strong> ${expiresIn ? expiresIn.toLocaleString() : 'Unknown'}</p>
                <p><strong>Status:</strong> ${isExpired ? '❌ Expired' : '✅ Valid'}</p>
            `;
        }
    }
}