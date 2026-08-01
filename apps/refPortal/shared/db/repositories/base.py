from __future__ import annotations

import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from shared.db.cacheService import CacheService

M = TypeVar('M', bound=BaseModel)


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a camelCase dict (DynamoDB/cache convention) to snake_case (model convention).

    Also remaps the legacy 'created'/'updated' keys to 'created_at'/'updated_at'.
    Safe to call on dicts already in snake_case — a snake_case key converts to itself.
    """
    result: dict[str, Any] = {}
    for k, v in (raw or {}).items():
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', k).lower()
        if snake == 'created':
            snake = 'created_at'
        elif snake == 'updated':
            snake = 'updated_at'
        result[snake] = v
    return result


def _to_model(cls: Type[M], raw: dict[str, Any] | None) -> M | None:
    """Normalise raw dict and parse into a Pydantic model. Returns None if raw is falsy."""
    if not raw:
        return None
    return cls.model_validate(_normalize(raw))


def _to_model_dict(cls: Type[M], raw: dict[str, Any] | None) -> dict[str, M]:
    """Convert a {key: raw_dict} mapping into {key: Model} — skips empty values."""
    if not raw:
        return {}
    return {k: cls.model_validate(_normalize(v)) for k, v in raw.items() if v}


class BaseRepository:
    """Thin base for all repository classes.

    Subclasses receive a CacheService instance and call `_to_model` /
    `_to_model_dict` to convert raw dicts to typed models.
    """

    def __init__(self, cache_service: CacheService) -> None:
        self._cache = cache_service
