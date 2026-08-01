from __future__ import annotations

from shared.db.models.referee import Area, NotificationType
from shared.db.models.tenant import Document, Field, Role, Rule, Season, Section, Tenant
from shared.db.repositories.base import BaseRepository, _to_model, _to_model_dict


class TenantRepository(BaseRepository):
    """Typed access to the tenant-configuration domain.

    Covers: Tenant, Season, Section, Role, Rule, Field, Document, Area, NotificationType.
    All methods delegate to CacheService and convert the raw dicts to
    Pydantic models via _to_model / _to_model_dict.
    """

    # ------------------------------------------------------------------
    # Tenants
    # ------------------------------------------------------------------

    def get_tenants(self) -> dict[str, Tenant]:
        """All tenants keyed by tenant_key."""
        return _to_model_dict(Tenant, self._cache.getTenants())

    def get_tenant(self, tenant_key: str, game: dict = None) -> Tenant | None:
        """game: an item already returned by cacheService.getRefereeGames/getRefereeReviews -
        if it carries an embedded 'tenant', skip the extra lookup."""
        return _to_model(Tenant, self._cache.get_tenant_by_key(tenant_key, game=game))

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------

    def get_seasons(self) -> dict[str, Season]:
        """All seasons keyed by season_name."""
        return _to_model_dict(Season, self._cache.getSeasons())

    def get_season(self, season_name: str) -> Season | None:
        seasons = self._cache.getSeasons()
        return _to_model(Season, seasons.get(season_name))

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def get_sections(self, tenant_key: str) -> dict[str, Section]:
        """All sections for a tenant keyed by section_name."""
        return _to_model_dict(Section, self._cache.getSections(tenantKey=tenant_key))

    def get_section(self, tenant_key: str, section_name: str) -> Section | None:
        return _to_model(Section, self._cache.get_section_by_name(tenantKey=tenant_key, sectionName=section_name))

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------

    def get_roles(self, tenant_key: str) -> dict[str, Role]:
        """All roles for a tenant keyed by role_name."""
        return _to_model_dict(Role, self._cache.getRoles(tenantKey=tenant_key))

    def get_role(self, tenant_key: str, role_name: str) -> Role | None:
        return _to_model(Role, self._cache.get_role_by_name(tenantKey=tenant_key, roleName=role_name))

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def get_rules(self, tenant_key: str) -> dict[str, Rule]:
        """All rules for a tenant keyed by rule_name."""
        return _to_model_dict(Rule, self._cache.getRules(tenantKey=tenant_key))

    def get_rule(self, tenant_key: str, rule_name: str) -> Rule | None:
        return _to_model(Rule, self._cache.get_rule_by_name(tenantKey=tenant_key, ruleName=rule_name))

    # ------------------------------------------------------------------
    # Fields (venues)
    # ------------------------------------------------------------------

    def get_fields(self, tenant_key: str) -> dict[str, Field]:
        """All fields/venues for a tenant keyed by field_name."""
        return _to_model_dict(Field, self._cache.getFields(tenantKey=tenant_key))

    def get_field(self, tenant_key: str, field_name: str, game: dict = None) -> Field | None:
        """game: an item already returned by cacheService.getRefereeGames/getRefereeReviews -
        if it carries an embedded 'field', skip the extra lookup."""
        return _to_model(Field, self._cache.get_field_by_name(tenantKey=tenant_key, fieldName=field_name, game=game))

    def search_fields(self, tenant_key: str, search_term: str) -> list[Field]:
        """Free-text search over field names and attributes."""
        raw_list = self._cache.search_fields(tenantKey=tenant_key, searchTerm=search_term)
        return [f for raw in raw_list if raw and (f := _to_model(Field, raw)) is not None]

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def get_documents(self, tenant_key: str) -> dict[str, Document]:
        """All documents for a tenant keyed by document_name."""
        return _to_model_dict(Document, self._cache.getDocuments(tenantKey=tenant_key))

    def get_document(self, tenant_key: str, document_name: str) -> Document | None:
        documents = self._cache.getDocuments(tenantKey=tenant_key)
        return _to_model(Document, documents.get(document_name))

    # ------------------------------------------------------------------
    # Areas (global, not tenant-scoped - keyed by id, not name)
    # ------------------------------------------------------------------

    def get_areas(self) -> dict[str, Area]:
        """All areas keyed by area_name (like fields/documents/rules)."""
        return _to_model_dict(Area, self._cache.getAreas())

    def get_area(self, area_id: int) -> Area | None:
        return _to_model(Area, self._cache.get_area_by_id(areaId=area_id))

    # ------------------------------------------------------------------
    # Notification types (global, not tenant-scoped)
    # ------------------------------------------------------------------

    def get_notification_types(self) -> dict[str, NotificationType]:
        """All notification-type catalog entries keyed by type_key."""
        return _to_model_dict(NotificationType, self._cache.getNotificationTypes())

    def get_notification_type(self, type_key: str) -> NotificationType | None:
        return _to_model(NotificationType, self._cache.get_notification_type_by_key(typeKey=type_key))
