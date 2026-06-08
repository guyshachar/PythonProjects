"""
Tenant-Aware Helper Methods for Database Operations
Supporting multiple countries and sports domains
"""

import os
from typing import Optional

class TenantAwareHelpers:
    @staticmethod
    def create_tenant_key(countryCode: str, eventType: str, season: Optional[str] = None) -> str:
        """Create composite tenant key for database operations"""
        if not season:
            season = os.getenv('season', '2024-25')
        return f"{countryCode}#{eventType}#{season}"
    
    @staticmethod
    def create_entity_key(entity_type: str, entity_id: str) -> str:
        """Create sort key for entity"""
        return f"{entity_type}#{entity_id}"
    
    @staticmethod
    def create_redis_key(env: str, countryCode: str, eventType: str, key_prefix: str, pk: Optional[str] = None) -> str:
        """Create Redis key with tenant context"""
        tenant_key = TenantAwareHelpers.create_tenant_key(countryCode, eventType)
        base_key = f"{env}:{tenant_key}:{key_prefix}"
        if pk:
            return f"{base_key}:{pk}"
        return base_key
    
    @staticmethod
    def create_dynamodb_key(countryCode: str, eventType: str, entity_type: str, entity_id: str, season: Optional[str] = None) -> dict:
        """Create DynamoDB key with tenant context"""
        tenant_key = TenantAwareHelpers.create_tenant_key(countryCode, eventType, season)
        entity_key = TenantAwareHelpers.create_entity_key(entity_type, entity_id)
        return {
            "PK": tenant_key,
            "SK": entity_key
        }
    
    @staticmethod
    def add_tenant_metadata(data: dict, countryCode: str, eventType: str, season: Optional[str] = None) -> dict:
        """Add tenant metadata to data objects"""
        if isinstance(data, dict):
            data['countryCode'] = countryCode
            data['eventType'] = eventType
            if season:
                data['season'] = season
            else:
                data['season'] = os.getenv('season', '2024-25')
        return data
    
    @staticmethod
    def validate_tenant_context(countryCode: str, eventType: str) -> bool:
        """Validate tenant context"""
        valid_countries = ["IL", "GR", "US", "UK", "DE", "FR", "ES", "IT"]
        valid_events = ["football", "basketball", "soccer", "baseball", "tennis", "volleyball"]
        
        return countryCode in valid_countries and eventType in valid_events
    
    @staticmethod
    def get_tenant_config(countryCode: str, eventType: str) -> dict:
        """Get tenant configuration"""
        tenant_configs = {
            "IL#football": {
                "country": "IL",
                "sport": "football",
                "name": "Israel Football",
                "timezone": "Asia/Jerusalem",
                "language": "he",
                "domain": "football.il"
            },
            "GR#basketball": {
                "country": "GR",
                "sport": "basketball", 
                "name": "Greece Basketball",
                "timezone": "Europe/Athens",
                "language": "el",
                "domain": "basketball.gr"
            },
            "US#basketball": {
                "country": "US",
                "sport": "basketball",
                "name": "USA Basketball", 
                "timezone": "America/New_York",
                "language": "en",
                "domain": "basketball.us"
            }
        }
        
        tenant_key = f"{countryCode}#{eventType}"
        return tenant_configs.get(tenant_key, {
            "country": countryCode,
            "sport": eventType,
            "name": f"{countryCode} {eventType}",
            "timezone": "UTC",
            "language": "en",
            "domain": f"{eventType}.{countryCode.lower()}"
        })

# Example usage:
"""
# Redis key generation
redis_key = TenantAwareHelpers.create_redis_key(
    env="prod", 
    countryCode="IL", 
    eventType="football", 
    key_prefix="tournaments", 
    pk="premier_league"
)
# Result: "prod:IL#football#2024-25:tournaments:premier_league"

# DynamoDB key generation
dynamodb_key = TenantAwareHelpers.create_dynamodb_key(
    countryCode="GR",
    eventType="basketball", 
    entity_type="tournament",
    entity_id="super_league"
)
# Result: {"PK": "GR#basketball#2024-25", "SK": "tournament#super_league"}

# Add tenant metadata
game_data = {
    "homeTeam": "Maccabi Tel Aviv",
    "guestTeam": "Hapoel Be'er Sheva",
    "date": "2024-12-15"
}
tenant_data = TenantAwareHelpers.add_tenant_metadata(
    game_data, "IL", "football"
)
# Result: game_data now includes countryCode, eventType, and season
""" 