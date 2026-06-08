#!/usr/bin/env python3
"""
Organization Service Registry - String-based factory to avoid circular imports
"""

from enum import Enum
import sys
from pathlib import Path
from typing import Dict, Type, Any, Optional
sys.path.append(str(Path(__file__).resolve().parent.parent))
from .orgServiceBase import OrgServiceBase, OrgServiceCountryCode, OrgServiceEventType

class OrgServiceRegistry:
    """
    Registry for organization services that avoids circular imports
    by using string-based service creation
    """
    
    def __init__(self, logger, multiTenantSupport, cacheService, handleUsers, messagingService):
        self.logger = logger
        self.multiTenantSupport = multiTenantSupport
        self.cacheService = cacheService
        self.handleUsers = handleUsers
        self.messagingService = messagingService
        
        # Service registry mapping
        self._service_registry = {
            "ifa": "shared.IFAService.IFAService",
            "iha": "shared.IHAService.IHAService",
        }
        
        self._service_cache = {}
    
    def register_service(self, service_key: str, module_path: str):
        """Register a service implementation"""
        self._service_registry[service_key] = module_path
    
    def create_service(self, 
                      countryCode: OrgServiceCountryCode, 
                      eventType: OrgServiceEventType, 
                      **kwargs) -> OrgServiceBase:
        """Create service instance based on country code and event type"""
        
        # Create cache key
        cache_key = f"{countryCode.value}:{eventType.value}"
        
        # Return cached instance if available
        if cache_key in self._service_cache:
            return self._service_cache[cache_key]
        
        # Determine service key
        service_key = self._get_service_key(countryCode, eventType)
        
        if service_key not in self._service_registry:
            raise ValueError(f"No service registered for {countryCode.value}:{eventType.value}")
        
        # Create service instance using dynamic import
        service = self._create_service_from_string(
            module_path=self._service_registry[service_key],
            **kwargs
        )
        
        # Cache the instance
        self._service_cache[cache_key] = service
        
        return service
    
    def _get_service_key(self, countryCode: OrgServiceCountryCode, eventType: OrgServiceEventType) -> str:
        """Get service key based on country code and event type"""
        if countryCode == OrgServiceCountryCode.ISRAEL and eventType == OrgServiceEventType.IFA:
            return "ifa"
        elif countryCode == OrgServiceCountryCode.ISRAEL and eventType == OrgServiceEventType.IHA:
            return "iha"
        else:
            raise ValueError(f"Unsupported combination: {countryCode.value}:{eventType.value}")
    
    def _create_service_from_string(self, module_path: str, **kwargs) -> OrgServiceBase:
        """Create service instance from module path string"""
        try:
            # Split module path into module and class name
            module_name, class_name = module_path.rsplit('.', 1)
            
            # Import the module dynamically
            module = __import__(module_name, fromlist=[class_name])
            service_class = getattr(module, class_name)
            
            # Create instance with required parameters
            return service_class(
                logger=self.logger,
                multiTenantSupport=self.multiTenantSupport,
                cacheService=self.cacheService,
                handleUsers=self.handleUsers,
                messagingService=self.messagingService,
                **kwargs
            )
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Failed to create service from {module_path}:", e)
    
    def get_org_service(self, countryCode: str, eventType: str, **kwargs) -> OrgServiceBase:
        """Convenience method to get organization service"""
        return self.create_service(
            countryCode=OrgServiceCountryCode(countryCode),
            eventType=OrgServiceEventType(eventType),
            **kwargs
        )
    
    def clear_cache(self):
        """Clear service cache"""
        self._service_cache.clear()
    
    def get_registered_services(self) -> Dict[str, str]:
        """Get list of registered services"""
        return self._service_registry.copy()

