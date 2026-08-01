from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    """Shared base for all DB models.

    alias_generator=to_camel lets model_dump(by_alias=True, mode='json')
    produce camelCase output matching the existing API / PWA convention.
    populate_by_name=True keeps snake_case attribute access working.
    """

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    id: Optional[int] = None
    content_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
