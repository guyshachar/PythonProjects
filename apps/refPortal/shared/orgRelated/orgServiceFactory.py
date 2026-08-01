from enum import Enum
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional
sys.path.append(str(Path(__file__).resolve().parent.parent))
from .orgServiceBase import OrgServiceBase, OrgServiceCountryCode, OrgServiceEventType

if TYPE_CHECKING:
    # Only import for type hints, not at runtime
    from .IFAService import IFAService
    from .IHAService import IHAService
    from shared.db.repositories import TenantRepository

class OrgServiceFactory:
    def __init__(self, logger, multiTenantSupport, cacheService, handleUsers, messagingService, tenantRepository:'Optional[TenantRepository]'=None):
        self.logger = logger
        self.multiTenantSupport = multiTenantSupport
        self.cacheService = cacheService
        self.tenantRepository = tenantRepository
        self.handleUsers = handleUsers
        self.messagingService = messagingService
        
        self._service_cache = {}

    def create_service(self, 
                      countryCode:Enum, 
                      eventType:Enum, 
                      **kwargs) -> OrgServiceBase:
        
        # Create new service instance based on parameters
        service = self._create_service_instance(countryCode=countryCode, eventType=eventType, **kwargs)
                
        return service
    
    def _create_service_instance(self, 
                               countryCode:OrgServiceCountryCode, 
                               eventType:OrgServiceEventType, 
                               **kwargs) -> OrgServiceBase:
        """Create specific service instance based on parameters"""
        
        if countryCode == OrgServiceCountryCode.ISRAEL and eventType == OrgServiceEventType.IFA:
            # Lazy import to avoid circular dependency
            from .IFAService import IFAService
            return IFAService(
                logger=self.logger,
                multiTenantSupport=self.multiTenantSupport,
                cacheService=self.cacheService,
                handleUsers=self.handleUsers,
                messagingService=self.messagingService,
                tenantRepository=self.tenantRepository,
                **kwargs
            )

        elif countryCode == OrgServiceCountryCode.ISRAEL and eventType == OrgServiceEventType.IHA:
            # Lazy import to avoid circular dependency
            from .IHAService import IHAService
            return IHAService(
                logger=self.logger,
                multiTenantSupport=self.multiTenantSupport,
                cacheService=self.cacheService,
                handleUsers=self.handleUsers,
                messagingService=self.messagingService,
                tenantRepository=self.tenantRepository,
                **kwargs
            )
                
        else:
            raise ValueError(f"Unsupported country code: {countryCode} and event type: {eventType}")

    def get_org_service_by_tenant(self, tenantKey: str, **kwargs) -> OrgServiceBase:
            countryCode = tenantKey.split('#')[0]
            eventType = tenantKey.split('#')[1]
            return self.get_org_service(countryCode=countryCode, eventType=eventType, **kwargs)
        
    def get_org_service(self, countryCode: str, eventType: str, **kwargs) -> OrgServiceBase:
        factory = OrgServiceFactory(self.logger, self.multiTenantSupport, self.cacheService, self.handleUsers, self.messagingService, tenantRepository=self.tenantRepository)
        return factory.create_service(
            countryCode=OrgServiceCountryCode(countryCode),
            eventType=OrgServiceEventType(eventType),
            **kwargs
        )
