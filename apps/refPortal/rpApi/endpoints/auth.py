"""
Authentication Endpoints

This module provides authentication-related endpoints including token refresh functionality.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from shared.logger import Logger
import shared.helpers as helpers

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])

# Pydantic models for request/response
class RefreshTokenRequest(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_expires_in: int

class ErrorResponse(BaseModel):
    error: str
    message: str
    code: str

@auth_router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    request: RefreshTokenRequest,
    fastapi_request: Request
):
    # Get JWT service from app state
    jwt_service = fastapi_request.app.state.jwt_token_service
    """
    Refresh access and refresh tokens using a valid refresh token.
    
    This endpoint allows clients to explicitly refresh their tokens when:
    - Access token is about to expire
    - Access token has expired
    - Client wants to rotate tokens for security
    
    Returns:
        - New access token (24 hours validity)
        - New refresh token (30 days validity)
        - Token expiration information
    """
    try:
        # Verify the refresh token and create new token pair (with version from request header)
        new_tokens = jwt_service.refresh_token_pair(request.refresh_token, request=fastapi_request)
        
        # Return the new tokens
        return TokenResponse(
            access_token=new_tokens['access_token'],
            refresh_token=new_tokens['refresh_token'],
            expires_in=jwt_service.access_token_expiry,
            refresh_expires_in=jwt_service.refresh_token_expiry
        )
        
    except HTTPException as e:
        # Re-raise HTTP exceptions as-is
        raise e
    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=500,
            detail={
                "error": "refresh_failed",
                "message": "Failed to refresh tokens",
                "code": "REFRESH_FAILED"
            }
        )

@auth_router.post("/validate", response_model=dict)
async def validate_token(
    request: Request
):
    # Get JWT service from app state
    jwt_service = request.app.state.jwt_token_service
    """
    Validate an access token and return user information.
    
    This endpoint allows clients to check if their access token is still valid
    and get current user information without making a full API call.
    
    Returns:
        - User information if token is valid
        - Error details if token is invalid or expired
    """
    try:
        # Extract and validate the token
        payload = jwt_service.verify_token_by_request(request)
        
        # Return user information
        return {
            "valid": True,
            "user": {
                "clientIdentifier": payload.get('clientIdentifier'),
                "refId": payload.get('refId'),
                "refName": payload.get('refName'),
                "role": payload.get('role', 'user'),
                "mobileNo": payload.get('mobileNo'),
                "expires_at": payload.get('exp'),
                "issued_at": payload.get('iat')
            }
        }
        
    except HTTPException as e:
        # Return structured error response
        return JSONResponse(
            status_code=401,
            content={
                "valid": False,
                "error": "token_invalid",
                "message": str(e.detail),
                "code": "TOKEN_INVALID"
            }
        )
    except Exception as e:
        # Handle unexpected errors
        return JSONResponse(
            status_code=500,
            content={
                "valid": False,
                "error": "validation_failed",
                "message": "Failed to validate token",
                "code": "VALIDATION_FAILED"
            }
        )

@auth_router.post("/logout")
async def logout():
    """
    Logout endpoint for client-side token cleanup.
    
    This endpoint is primarily for client-side use to:
    - Clear stored tokens
    - Update UI state
    - Redirect to login
    
    Note: Server-side token invalidation would require additional infrastructure
    (e.g., token blacklist, Redis, etc.)
    """
    return {
        "message": "Logout successful",
        "code": "LOGOUT_SUCCESS"
    }

# Health check endpoint for authentication service
@auth_router.get("/health")
async def health_check():
    """Health check endpoint for authentication service"""
    return {
        "status": "healthy",
        "service": "authentication",
        "timestamp": helpers.utcNow().isoformat()
    }
