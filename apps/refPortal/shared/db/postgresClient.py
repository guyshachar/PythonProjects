"""PostgresClient — DbClientBase implementation backed by PostgreSQL.

Manages an optional SSH tunnel + psycopg2 connection.  Reads reconstruct
flat DynamoDB-compatible dicts (dedicated columns merged with properties
JSONB) so callers need no changes when switching from DynamodbClient.

Standalone usage (context manager):
    with PostgresClient() as client:
        games = client.getTournamentGames('IL#football#2025-26', 'ליגת הלאומית')

DI usage (same signature as DynamodbClient):
    client = PostgresClient(env='prod', logger=logger)
    client.connect()
    ...
    client.close()
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time
import uuid
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3
import psycopg2
import psycopg2.extras

from shared.db.dbClientBase import DbClientBase
from shared.logger import Logger
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db.enumTypes import EntityType

# ---------------------------------------------------------------------------
# Module-level env-var fallbacks (used by migration scripts and standalone use
# only; the DI path receives all values via PostgresClient.__init__ pg_config)
# ---------------------------------------------------------------------------

_ENV_PG_HOST    = os.getenv('PG_HOST', 'localhost')
_ENV_PG_PORT    = int(os.getenv('PG_PORT', '5432'))
_ENV_PG_DB      = os.getenv('PG_DB', 'postgres')
_ENV_PG_USER    = os.getenv('PG_USER', 'postgres')
_ENV_PG_SCHEMA  = os.getenv('PG_SCHEMA', 'public')
_ENV_PG_USE_IAM = os.getenv('PG_USE_IAM_AUTH', 'false').lower() in ('1', 'true', 'yes')
_ENV_PG_SSLMODE = os.getenv('PG_SSLMODE', 'prefer')
_ENV_AWS_REGION = os.getenv('AWS_REGION', 'il-central-1')
_ENV_SSH_HOST   = os.getenv('PG_SSH_HOST', '')
_ENV_SSH_USER   = os.getenv('PG_SSH_USER', 'ec2-user')
_ENV_SSH_KEY    = os.path.expanduser(os.getenv('PG_SSH_KEY', '~/.ssh/id_rsa'))

# Application uses 'FROM'/'TO'; DB enum uses 'in'/'out'
_MSG_DIR_TO_DB   = {'FROM': 'in', 'TO': 'out', 'inbound': 'in', 'outbound': 'out', 'in': 'in', 'out': 'out'}
_MSG_DIR_FROM_DB = {'in': 'FROM', 'out': 'TO'}

local_tz = ZoneInfo(os.getenv('TZ'))

# _parse_ts (read side) always converts a stored TIMESTAMPTZ (a real UTC instant) to a naive
# local-Israel datetime. But scraped dates (helpers.convert_to_datetime) and helpers.localNow()
# also produce naive local-Israel datetimes, and psycopg2 has no way to know that - handed a
# naive datetime, it lets Postgres interpret it using the session's own timezone (UTC), silently
# storing e.g. 18:00 Israel as 18:00 UTC (= 21:00 Israel, a +3h shift on every fresh write).
# Registering this adapter makes the write side symmetric with _parse_ts: any naive datetime
# passed as a query parameter anywhere in this process is assumed to already be local-Israel
# time and gets that zone attached (not converted/shifted) before psycopg2 adapts it, so Postgres
# stores the correct UTC instant. Already-aware datetimes pass through untouched.
_original_datetime_adapter = psycopg2.extensions.adapters.get((datetime, psycopg2.extensions.ISQLQuote))


def _adapt_naive_datetime_as_local(dt: datetime):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz)
    return _original_datetime_adapter(dt)


psycopg2.extensions.register_adapter(datetime, _adapt_naive_datetime_as_local)

# ---------------------------------------------------------------------------
# Auth helpers (instance-level; called with resolved config values)
# ---------------------------------------------------------------------------

def _iam_token(host: str, port: int, user: str, region: str) -> str:
    client = boto3.client('rds', region_name=region)
    return client.generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=user, Region=region,
    )


def _secret_password(secret_id: str, secret_key: str, region: str) -> str:
    value = boto3.client('secretsmanager', region_name=region) \
                 .get_secret_value(SecretId=secret_id)['SecretString']
    return json.loads(value)[secret_key]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _merge_props(dedicated: dict, props: dict | None) -> dict:
    """Merge dedicated columns with properties JSONB; dedicated columns win."""
    result = dict(props or {})
    result.update({k: v for k, v in dedicated.items() if v is not None})
    return result


def _jsonb(v: Any) -> str | None:
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False, default=str)


def _hide_zero(v: Any) -> Any:
    """Treat null/empty/zero-ish values (e.g. fixture '0', round 0) as absent."""
    if v is None or v in ('', '0', 0):
        return None
    return v


def _parse_ts(v: Any, skipZeroedTime: bool = False) -> datetime | None:
    """Convert a stored TIMESTAMPTZ (a real UTC instant) to an offset-aware local-Israel
    datetime. Returns tzinfo=local_tz (not stripped) - callers get a genuinely comparable,
    unambiguous instant instead of a naive local-looking value."""
    if not v:
        return None
    if isinstance(v, (int, float)):
        v = datetime.fromtimestamp(v, tz=timezone.utc)
    if skipZeroedTime and v.time() == datetime.min.time():
        localTzV = v.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=local_tz)
    else:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        localTzV = v.astimezone(local_tz)
    return localTzV


def _ensure_aware(v: Any) -> Any:
    """Attach local_tz to a naive datetime (assumed already local-Israel time, matching
    helpers.localNow()/convert_to_datetime() conventions elsewhere in the app); pass through
    anything else (aware datetimes, dates, strings, None) unchanged."""
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=local_tz)
    return v


# ---------------------------------------------------------------------------
# PostgresClient
# ---------------------------------------------------------------------------

class PostgresClient(DbClientBase):
    """DbClientBase implementation backed by PostgreSQL (psycopg2)."""

    def __init__(self, env: str = None, logger: Logger = None,
                 pg_config: dict = None, autocommit: bool = True):
        """
        pg_config: dict with keys matching configurationDI 'postgres' section:
            host, port, db, user, schema, sslmode, use_iam,
            secret_id, secret_key, ssh_host, ssh_user, ssh_key
        When None (standalone/migration use), falls back to PG_* env vars.

        autocommit defaults to True: the app process holds a single long-lived connection (see
        appContainer.py's Singleton), and nothing outside _execute_upsert_id ever calls commit()
        - with autocommit off, every read left its implicit transaction open indefinitely
        ("idle in transaction" for hours, observed blocking DDL from unrelated scripts), and
        several write methods (delete, truncate, deleteTournamentGame, archiveTournamentGame,
        removeRefereeGame, archiveRefereeGame, removeRefereeReview, _ensure_team, _ensure_field)
        never committed at all, relying on a later unrelated _execute_upsert_id call to make them
        durable. No code was found that groups multiple query()/execute() calls into one
        multi-statement transaction expecting atomicity, so autocommit is safe here.
        """
        if logger is None:
            logger = Logger()
        super().__init__(env or os.getenv('app_env', 'prod'), logger)
        self.autocommit = autocommit
        self._lock = threading.RLock()  # psycopg2 single-connection is not thread-safe
        self._tunnel: subprocess.Popen | None = None
        self._conn = None
        self._cur = None

        cfg = pg_config or {}
        self._pg_host    = cfg.get('host',       _ENV_PG_HOST)
        self._pg_port    = int(cfg.get('port',   _ENV_PG_PORT))
        self._pg_db      = cfg.get('db',         _ENV_PG_DB)
        self._pg_user    = cfg.get('user',       _ENV_PG_USER)
        self._pg_schema  = cfg.get('schema',     _ENV_PG_SCHEMA)
        self._pg_sslmode = cfg.get('sslmode',    _ENV_PG_SSLMODE)
        self._pg_use_iam = bool(cfg.get('use_iam', _ENV_PG_USE_IAM))
        self._secret_id  = cfg.get('secret_id',  os.getenv('PG_SECRET_ID',  'prod/refPortalSecret'))
        self._secret_key = cfg.get('secret_key', os.getenv('PG_SECRET_KEY', 'postgres_password'))
        self._aws_region = cfg.get('aws_region', _ENV_AWS_REGION)
        self._ssh_host   = cfg.get('ssh_host',   _ENV_SSH_HOST)
        self._ssh_user   = cfg.get('ssh_user',   _ENV_SSH_USER)
        self._ssh_key    = os.path.expanduser(cfg.get('ssh_key', _ENV_SSH_KEY))

        self.logger.info(f'PostgresClient starts...')

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> 'PostgresClient':
        self.close()  # close any stale connection first (idempotent)
        self._tunnel = self._open_tunnel()
        host, port = self._tunnel_endpoint()
        password = self._resolve_password()
        self._conn = psycopg2.connect(
            host=host, port=port, dbname=self._pg_db, user=self._pg_user, password=password,
            sslmode='require' if self._pg_use_iam else self._pg_sslmode,
            options=f'-c search_path={self._pg_schema}',
        )
        self._conn.autocommit = self.autocommit
        self._cur = self._conn.cursor()
        self.logger.debug(f'PostgresClient connected to {host}:{port}/{self._pg_db}')
        return self

    def _resolve_password(self) -> str:
        if self._pg_use_iam:
            return _iam_token(self._pg_host, self._pg_port, self._pg_user, self._aws_region)
        pw = os.getenv('PG_PASSWORD')
        if pw:
            return pw
        return _secret_password(self._secret_id, self._secret_key, self._aws_region)

    def _ensure_connected(self) -> None:
        """Lazily connect on first use; reconnect if the connection was dropped."""
        if self._conn is None or self._conn.closed:
            self.logger.debug('PostgresClient: (re)connecting')
            self.connect()

    def close(self) -> None:
        if self._cur:
            try:
                self._cur.close()
            except Exception:
                pass
            self._cur = None
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._tunnel:
            self._tunnel.terminate()
            self._tunnel.wait()
            self._tunnel = None
            self.logger.debug('PostgresClient SSH tunnel closed')

    def __enter__(self) -> 'PostgresClient':
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn and not self.autocommit:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        self.close()

    # ------------------------------------------------------------------
    # Convenience query methods
    # ------------------------------------------------------------------

    def _reconnect_if_connection_dead(self, exc) -> bool:
        """psycopg2.OperationalError covers two very different situations: a genuinely dropped
        connection, and a statement that was merely canceled server-side (lock_timeout,
        statement_timeout, pg_cancel_backend) while the connection itself is still fine. Treating
        both as "connection lost" and blindly reconnecting-and-retrying is wrong for the second
        case: it silently drops session-level settings set on the old connection (e.g. a caller's
        own lock_timeout) and can retry straight back into the same contention that caused the
        cancellation in the first place.

        Returns True if the connection was actually dead (now reconnected - caller should retry
        the statement once). Returns False if the connection is still alive (any open transaction
        is rolled back so it's left in a usable state) - the caller should re-raise instead of
        retrying, so the real cancellation error reaches the caller.
        """
        if self._conn is None or self._conn.closed:
            self.logger.warning('PostgresClient: connection lost (%s), reconnecting', exc)
            self.connect()
            return True
        self.logger.warning('PostgresClient: statement canceled (%s)', exc)
        if not self.autocommit:
            self._conn.rollback()
        return False

    def execute(self, sql: str, params=None) -> None:
        with self._lock:
            self._ensure_connected()
            try:
                self._cur.execute(sql, params)
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                if not self._reconnect_if_connection_dead(exc):
                    raise
                self._cur.execute(sql, params)

    def executemany(self, sql: str, rows: list, page_size: int = 200) -> int:
        if not rows:
            return 0
        with self._lock:
            self._ensure_connected()
            try:
                psycopg2.extras.execute_batch(self._cur, sql, rows, page_size=page_size)
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                if not self._reconnect_if_connection_dead(exc):
                    raise
                psycopg2.extras.execute_batch(self._cur, sql, rows, page_size=page_size)
        return len(rows)

    def fetchone(self) -> tuple | None:
        return self._cur.fetchone()

    def fetchall(self) -> list[tuple]:
        return self._cur.fetchall()

    def query(self, sql: str, params=None) -> list[tuple]:
        with self._lock:
            self._ensure_connected()
            finalSql = None
            try:
                finalSql = self._cur.mogrify(sql, params).decode('utf-8') if params else sql
                finalSql = finalSql.replace('\n', '')
                self._cur.execute(sql, params)
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                if not self._reconnect_if_connection_dead(exc):
                    raise
                self._cur.execute(sql, params)
            except Exception as exc:
                self.logger.error(f'PostgresClient: error executing query {finalSql}: {exc}')
                # A failed statement leaves the transaction aborted - every subsequent query on
                # this connection would fail with InFailedSqlTransaction until rolled back, and
                # this is a long-lived shared connection (not one per request), so without this
                # a single bad query (e.g. malformed input) breaks DB access for the rest of the
                # process.
                self.rollback()
                raise exc
            return self._cur.fetchall()

    def queryone(self, sql: str, params=None) -> tuple | None:
        with self._lock:
            self._ensure_connected()
            try:
                self._cur.execute(sql, params)
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                if not self._reconnect_if_connection_dead(exc):
                    raise
                self._cur.execute(sql, params)
            except Exception as exc:
                self.logger.error(f'PostgresClient: error executing query: {exc}')
                self.rollback()
                raise exc
            return self._cur.fetchone()

    def commit(self) -> None:
        with self._lock:
            self._ensure_connected()
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            if self._conn and not self._conn.closed:
                self._conn.rollback()

    def _execute_upsert(self, sql: str, params, label: str = '') -> bool:
        """Execute an INSERT…ON CONFLICT upsert with RETURNING id. Returns True if a row was written."""
        return self._execute_upsert_id(sql, params, label) is not None

    def _execute_upsert_id(self, sql: str, params, label: str = ''):
        """Same as _execute_upsert but returns the RETURNING id itself (or None), for callers
        that need to know which row was written - e.g. a brand-new referee with no mobile_no
        to look the id back up by afterward."""
        self._cur.execute(sql, params)
        row = self._cur.fetchone()
        row_id = row[0] if row else None
        self.logger.debug(f'upsert[{label}]: rowcount={self._cur.rowcount} status={self._cur.statusmessage} id={row_id}')
        self._conn.commit()
        return row_id

    @property
    def cursor(self):
        self._ensure_connected()
        return self._cur

    # ------------------------------------------------------------------
    # DbClientBase: core abstract methods
    # ------------------------------------------------------------------

    def valueChanged(self, value: dict):
        new_value = jsonHelper.preJsonSetToDynamoDb(obj=value, excludeProps=['updated'])
        return new_value, True

    def get(self, tableName, tenantKey='GLOBAL', jsonDumps=False, **entityKeys):
        key = self._build_key(tableName, tenantKey, **entityKeys)
        row = self.queryone(
            'SELECT value FROM key_val kv JOIN tenants t ON t.id = kv.tenant_id WHERE t.tenant_key = %s AND kv.key = %s',
            (tenantKey, key),
        )
        if not row:
            return None
        val = row[0]
        return jsonHelper.load_from_json(val) if jsonDumps and isinstance(val, str) else val

    def set(self, tableName, value, tenantKey='GLOBAL', expiry=None, jsonDumps=False, **entityKeys):
        key = self._build_key(tableName, tenantKey, **entityKeys)
        now = helpers.localNow().isoformat()
        if not isinstance(value, dict):
            value = {'value': value}
        value.setdefault('created', now)
        new_value, _ = self.valueChanged(value)
        new_value['updated'] = now
        new_id = self._execute_upsert_id("""
            INSERT INTO key_val (tenant_id, key, value, updated_at)
            SELECT t.id, %s, %s::jsonb, NOW()
            FROM tenants t WHERE t.tenant_key = %s
            ON CONFLICT (tenant_id, key) DO UPDATE SET
                value = EXCLUDED.value, updated_at = NOW()
            RETURNING id
        """, (key, json.dumps(new_value, default=str), tenantKey), 'set')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getDict(self, entityType: EntityType, tenantKey: str = 'GLOBAL', entityKeys=None,
                queryIterations=None, jsonDumps: bool = False, skipConversion: bool = False,
                recentDays=None, asIsEntityKey: bool = False):
        raise NotImplementedError('Use domain-specific methods (getTournamentGames, etc.) on PostgresClient')

    def setDict(self, tableName, data, entityKeyColumns=None):
        raise NotImplementedError('Use domain-specific methods on PostgresClient')

    def exists(self, tableName, tenantKey, **entityKeys):
        return self.get(tableName=tableName, tenantKey=tenantKey, **entityKeys) is not None

    def rename(self, oldKey, newKey):
        raise NotImplementedError('rename not applicable to relational schema')

    def delete(self, tableName, tenantKey, **entityKeys):
        key = self._build_key(tableName, tenantKey, **entityKeys)
        self._cur.execute("""
            DELETE FROM key_val USING tenants
            WHERE key_val.tenant_id = tenants.id AND tenants.tenant_key = %s AND key_val.key = %s
        """, (tenantKey, key))

    def deleteByFilter(self, tableName, tenantKey, filters, **entityKeys):
        raise NotImplementedError('deleteByFilter not implemented for PostgresClient')

    def truncate(self, tableName):
        safe = {
            'fields': 'fields', 'tournaments': 'tournaments', 'sections': 'sections',
            'roles': 'roles', 'rules': 'rules', 'seasons': 'seasons',
            'refereeGames': 'referee_games', 'tournamentGames': 'tournament_games',
            'refereeTemplates': 'referee_templates', 'refereeMessages': 'referee_messages',
            'notifications': 'notifications', 'keyVal': 'key_val',
        }
        pg_table = safe.get(tableName)
        if pg_table:
            self._cur.execute(f'TRUNCATE TABLE {pg_table} RESTART IDENTITY CASCADE')

    # ------------------------------------------------------------------
    # Domain helpers
    # ------------------------------------------------------------------

    def _tenant_id(self, tenant_key: str) -> int | None:
        row = self.queryone('SELECT id FROM tenants WHERE tenant_key = %s', (tenant_key,))
        return row[0] if row else None

    def _referee_id(self, mobile_no: str) -> int | None:
        row = self.queryone('SELECT id FROM referees WHERE mobile_no = %s', (mobile_no,))
        return row[0] if row else None

    def _tenant_referee_id(self, tenant_id: int, mobile_or_ref: str) -> int | None:
        row = self.queryone(
            'SELECT tr.id FROM tenant_referees tr JOIN referees r ON r.id = tr.referee_id WHERE tr.tenant_id = %s AND r.mobile_no = %s',
            (tenant_id, mobile_or_ref),
        )
        if row:
            return row[0]
        row = self.queryone(
            'SELECT id FROM tenant_referees WHERE tenant_id = %s AND ref_id = %s LIMIT 1',
            (tenant_id, mobile_or_ref),
        )
        return row[0] if row else None

    def _resolve_referee_id(self, mobile_or_ref: str) -> int | None:
        """Resolve referees.id from a mobile number or, as fallback, a legacy tenant_referees.ref_id."""
        if not mobile_or_ref:
            return None
        rid = self._referee_id(mobile_or_ref)
        if rid is not None:
            return rid
        row = self.queryone(
            'SELECT referee_id FROM tenant_referees WHERE ref_id = %s LIMIT 1',
            (mobile_or_ref,),
        )
        return row[0] if row else None

    def _resolve_referee_id_by_internal_id(self, tenant_id: int, internal_referee_id) -> int | None:
        """Resolve referees.id from a tenant-scoped internal_referee_id, for mobile-less
        referees matched by their source-system id rather than a mobile number."""
        if not tenant_id or internal_referee_id is None:
            return None
        row = self.queryone(
            'SELECT referee_id FROM tenant_referees WHERE tenant_id = %s AND internal_referee_id = %s',
            (tenant_id, internal_referee_id),
        )
        return row[0] if row else None

    def resolveRefereeIdByInternalId(self, tenantKey: str, internalRefereeId) -> int | None:
        """Public, tenant-key based counterpart to _resolve_referee_id_by_internal_id, for
        callers (e.g. cacheService) that only have a tenantKey rather than a resolved tenant_id."""
        tid = self._tenant_id(tenantKey)
        return self._resolve_referee_id_by_internal_id(tid, internalRefereeId)

    def _resolve_referee_id_or_id(self, referee_id_or_mobile) -> int | None:
        """Accept an already-resolved referees.id directly (the preferred form for
        target_to), or fall back to resolving a mobile number / legacy ref_id string
        for backward-compat call sites that haven't been updated yet."""
        if isinstance(referee_id_or_mobile, int):
            return referee_id_or_mobile
        s = str(referee_id_or_mobile)
        if s.isdigit():
            return int(s)
        if '@' in s:
            s = s.split('@')[0]
        return self._resolve_referee_id(s)

    def _tournament_id(self, tenant_id: int, tournament_name: str) -> int | None:
        row = self.queryone(
            'SELECT id FROM tournaments WHERE tenant_id = %s AND tournament_name = %s',
            (tenant_id, tournament_name),
        )
        return row[0] if row else None

    def getTournamentId(self, tenantKey: str, tournamentName: str) -> int | None:
        """Public wrapper around _tenant_id/_tournament_id for callers outside this class (e.g.
        the manual-game-creation endpoint) that need the raw id rather than a full dict."""
        tid = self._tenant_id(tenantKey)
        return self._tournament_id(tid, tournamentName) if tid else None

    def _resolve_tournament_game_id(self, tenant_key: str, game_pk: str) -> int | None:
        """Resolve tournament_games.id from a raw game_pk within the given tenant.
        game_pk is informative now (not the real key), and some callers already pass
        the internal tournament_games.id in this slot - detect that case first to
        avoid a text=integer comparison crash, then fall back to the real game_pk lookup."""
        if not game_pk:
            return None
        tid = self._tenant_id(tenant_key)
        if not tid:
            return None
        game_pk_str = str(game_pk)
        if game_pk_str.isdigit():
            row = self.queryone("""
                SELECT tg.id FROM tournament_games tg
                JOIN tournaments t ON t.id = tg.tournament_id
                WHERE t.tenant_id = %s AND tg.id = %s
                LIMIT 1
            """, (tid, int(game_pk_str)))
            if row:
                return row[0]
        row = self.queryone("""
            SELECT tg.id FROM tournament_games tg
            JOIN tournaments t ON t.id = tg.tournament_id
            WHERE t.tenant_id = %s AND tg.game_pk = %s
            LIMIT 1
        """, (tid, game_pk_str))
        return row[0] if row else None

    def _resolve_notification_target_id(self, tenant_key: str, target: str, target_id) -> tuple[int | None, str | None]:
        """Resolve a raw game_pk (or an already-internal tournament_games.id) to
        (target_id, game_pk) for game-scoped notification targets. target_id is
        always an int (or None if unresolvable); game_pk always preserves the
        original identifier so mismatches against tournament_games aren't silently
        lost. NONGAME (non-game notifications, e.g. password changes) and non-game
        targets return (None, None)."""
        if target not in ('tournamentGames', 'refereeGames', 'refereeReviews'):
            return None, None
        if not target_id or target_id == 'NONGAME':
            return None, None
        game_pk = str(target_id)
        if game_pk.isdigit():
            # caller already passed the internal tournament_games.id — not a real game_pk
            return int(game_pk), None
        tg_id = self._resolve_tournament_game_id(tenant_key, game_pk)
        if tg_id is None:
            # source tenant tag may not match the tenant the game actually lives
            # in — fall back to an unambiguous match across all tenants.
            rows = self.query('SELECT tg.id FROM tournament_games tg WHERE tg.game_pk = %s', (game_pk,))
            if len(rows) == 1:
                tg_id = rows[0][0]
        return tg_id, game_pk

    @staticmethod
    def _build_key(tableName: str, tenantKey: str, **entityKeys) -> str:
        parts = [tableName, tenantKey] + [str(v) for v in entityKeys.values() if v is not None]
        return '#'.join(parts)

    # ------------------------------------------------------------------
    # Reference data
    # ------------------------------------------------------------------

    def getTenants(self):
        rows = self.query("""
            SELECT id, tenant_key, name, active, active_status, game_duration_mins, assigner_collection, properties, created_at, updated_at, season, country_code, event_type, notification_settings, allow_manual_games, tournament_types
            FROM tenants WHERE tenant_key != 'GLOBAL'
        """)
        result = {}
        for r in rows:
            d = _merge_props({'id': r[0], 'tenantKey': r[1], 'name': r[2], 'active': r[3],
                               'activeStatus': r[4], 'gameDurationInMins': r[5],
                               'assignerCollection': r[6],
                               'created': _parse_ts(r[8]), 'updated': _parse_ts(r[9]),
                               'season': r[10], 'countryCode': r[11], 'eventType': r[12],
                               'notificationSettings': r[13] or {}, 'allowManualGames': r[14],
                               'tournamentTypes': r[15] or {'league': 'ליגה'}}, r[7])
            result[r[1]] = d
        return result

    def getSeasons(self, season=None, **entityKeys):
        sql = 'SELECT season_name, properties, created_at, updated_at FROM seasons'
        params = []
        if season:
            sql += ' WHERE season_name = %s'
            params.append(season)
        rows = self.query(sql, params or None)
        result = {}
        for r in rows:
            d = _merge_props({'seasonName': r[0], 'created': _parse_ts(r[2]), 'updated': _parse_ts(r[3])}, r[1])
            result[r[0]] = d
        return result

    def setSeason(self, season, value):
        now = helpers.localNow().isoformat()
        value.setdefault('created', now)
        props = {k: v for k, v in value.items() if k not in {'seasonName', 'season', 'content_hash', 'created', 'updated'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO seasons (season_name, properties, created_at, updated_at)
            VALUES (%s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (season_name) DO UPDATE SET properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (season, _jsonb(props)), 'setSeason')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getSections(self, tenantKey, sectionName=None, **entityKeys):
        params = [tenantKey]
        sql = """
            SELECT s.section_name, s.display_order, s.properties, s.created_at, s.updated_at
            FROM sections s JOIN tenants t ON t.id = s.tenant_id
            WHERE t.tenant_key = %s
        """
        if sectionName:
            sql += ' AND s.section_name = %s'
            params.append(sectionName)
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'sectionName': r[0], 'displayOrder': r[1],
                               'created': _parse_ts(r[3]), 'updated': _parse_ts(r[4])}, r[2])
            result[r[0]] = d
        return result

    def setSection(self, tenantKey, sectionName, value):
        tid = self._tenant_id(tenantKey)
        if not tid:
            return value, False
        props = {k: v for k, v in value.items() if k not in {'sectionName', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO sections (tenant_id, section_name, properties, created_at, updated_at)
            VALUES (%s, %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (tenant_id, section_name) DO UPDATE SET
                properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (tid, sectionName, _jsonb(props)), 'setSection')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getRoles(self, tenantKey, roleName=None, **entityKeys):
        params = [tenantKey]
        sql = """
            SELECT r.role_name, r.properties, r.created_at, r.updated_at, r.id, r.display_order, r.role_type
            FROM roles r JOIN tenants t ON t.id = r.tenant_id WHERE t.tenant_key = %s
        """
        if roleName:
            sql += ' AND r.role_name = %s'
            params.append(roleName)
        rows = self.query(sql, params)
        return {r[0]: _merge_props({'id': r[4], 'roleName': r[0], 'displayOrder': r[5], 'roleType': r[6],
                                     'created': _parse_ts(r[2]), 'updated': _parse_ts(r[3])}, r[1]) for r in rows}

    def setRole(self, tenantKey, roleName, value):
        tid = self._tenant_id(tenantKey)
        if not tid:
            return value, False
        props = {k: v for k, v in value.items() if k not in {'roleName', 'displayOrder', 'roleType', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO roles (tenant_id, role_name, display_order, role_type, properties, created_at, updated_at)
            VALUES (%s, %s, %s, %s::role_type, %s::jsonb, NOW(), NOW())
            ON CONFLICT (tenant_id, role_name) DO UPDATE SET
                display_order = EXCLUDED.display_order, role_type = EXCLUDED.role_type,
                properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (tid, roleName, value.get('displayOrder'), value.get('roleType'), _jsonb(props)), 'setRole')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getRules(self, tenantKey, ruleName=None, **entityKeys):
        params = [tenantKey]
        sql = """
            SELECT r.rule_name, r.game_gross_time, r.cup_gross_time, r.match_setup, r.properties, r.created_at, r.updated_at
            FROM rules r JOIN tenants t ON t.id = r.tenant_id WHERE t.tenant_key = %s
        """
        if ruleName:
            sql += ' AND r.rule_name = %s'
            params.append(ruleName)
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'ruleName': r[0], 'gameGrossTime': r[1], 'cupGrossTime': r[2],
                               'matchSetup': r[3], 'created': _parse_ts(r[5]), 'updated': _parse_ts(r[6])}, r[4])
            result[r[0]] = d
        return result

    def setRule(self, tenantKey, ruleName, value):
        tid = self._tenant_id(tenantKey)
        if not tid:
            return value, False
        props = {k: v for k, v in value.items() if k not in {'ruleName', 'gameGrossTime', 'cupGrossTime', 'matchSetup', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO rules (tenant_id, rule_name, game_gross_time, cup_gross_time, match_setup, properties, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW(), NOW())
            ON CONFLICT (tenant_id, rule_name) DO UPDATE SET
                game_gross_time = EXCLUDED.game_gross_time, cup_gross_time = EXCLUDED.cup_gross_time,
                match_setup = EXCLUDED.match_setup, properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (tid, ruleName, value.get('gameGrossTime'), value.get('cupGrossTime'),
              _jsonb(value.get('matchSetup', {})), _jsonb(props)), 'setRule')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getFields(self, tenantKey, fieldName=None, contains_filterText=None):
        params = [tenantKey]
        sql = """
            SELECT f.field_name, f.address, f.lat, f.lng, f.waze_link, f.contact, f.phone, f.level, f.properties, f.created_at, f.updated_at
            FROM fields f JOIN tenants t ON t.id = f.tenant_id WHERE t.tenant_key = %s
        """
        if fieldName:
            sql += ' AND f.field_name = %s'
            params.append(fieldName)
        elif contains_filterText:
            sql += ' AND f.field_name ILIKE %s'
            params.append(f'%{contains_filterText}%')
        sql += ' ORDER BY f.field_name'
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'fieldName': r[0], 'address': r[1], 'lat': float(r[2]) if r[2] else None,
                               'lng': float(r[3]) if r[3] else None, 'wazeLink': r[4],
                               'contact': r[5], 'phone': r[6], 'level': r[7],
                               'created': _parse_ts(r[9]), 'updated': _parse_ts(r[10])}, r[8])
            result[r[0]] = d
        return result

    def setField(self, tenantKey, fieldName, value):
        tid = self._tenant_id(tenantKey)
        if not tid:
            return value, False
        props = {k: v for k, v in value.items() if k not in {'fieldName', 'address', 'addressDetails', 'wazeLink', 'contact', 'phone', 'level', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO fields (tenant_id, field_name, address, lat, lng, waze_link, contact, phone, level, properties, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (tenant_id, field_name) DO UPDATE SET
                address = EXCLUDED.address, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
                waze_link = EXCLUDED.waze_link, contact = EXCLUDED.contact, phone = EXCLUDED.phone,
                level = EXCLUDED.level, properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (tid, fieldName, value.get('address'), value.get('lat'), value.get('lng'),
              value.get('wazeLink'), value.get('contact'), value.get('phone'), value.get('level'),
              _jsonb(props)), 'setField')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getAreas(self, areaName=None, **entityKeys):
        """Global (not tenant-scoped): named regions, each optionally assigned a referee
        (assigner_referee_id) who handles that region's assigner-bot messages."""
        params = []
        sql = """
            SELECT a.id, a.area_name, a.assigner_referee_id, r.mobile_no, r.name,
                   a.properties, a.created_at, a.updated_at
            FROM areas a LEFT JOIN referees r ON r.id = a.assigner_referee_id
            WHERE 1=1
        """
        if areaName:
            sql += ' AND a.area_name = %s'
            params.append(areaName)
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'id': r[0], 'areaName': r[1], 'assignerRefereeId': r[2],
                               'assignerMobileNo': r[3], 'assignerName': r[4],
                               'created': _parse_ts(r[6]), 'updated': _parse_ts(r[7])}, r[5])
            result[r[1]] = d
        return result

    def setArea(self, areaName, value):
        props = {k: v for k, v in (value or {}).items() if k not in {'areaName', 'assignerRefereeId', 'assignerMobileNo', 'assignerName', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO areas (area_name, assigner_referee_id, properties, created_at, updated_at)
            VALUES (%s, %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (area_name) DO UPDATE SET
                assigner_referee_id = EXCLUDED.assigner_referee_id,
                properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (areaName, (value or {}).get('assignerRefereeId'), _jsonb(props)), 'setArea')
        value = value or {}
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getNotificationTypes(self, typeKey=None, **entityKeys):
        """Global (not tenant-scoped) catalog of notification types - see NotificationType model."""
        params = []
        sql = """
            SELECT id, type_key, context_time, offset_minutes, channels, enabled, seq, properties, created_at, updated_at
            FROM notification_types
            WHERE 1=1
        """
        if typeKey:
            sql += ' AND type_key = %s'
            params.append(typeKey)
        sql += ' ORDER BY seq'
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'id': r[0], 'typeKey': r[1], 'contextTime': r[2], 'offsetMinutes': r[3],
                               'channels': r[4], 'enabled': r[5], 'seq': r[6], 'created': _parse_ts(r[8]), 'updated': _parse_ts(r[9])}, r[7])
            result[r[1]] = d
        return result

    def setNotificationType(self, typeKey, value):
        props = {k: v for k, v in (value or {}).items() if k not in {'typeKey', 'contextTime', 'offsetMinutes', 'channels', 'enabled', 'seq', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO notification_types (type_key, context_time, offset_minutes, channels, enabled, seq, properties, created_at, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (type_key) DO UPDATE SET
                context_time = EXCLUDED.context_time, offset_minutes = EXCLUDED.offset_minutes,
                channels = EXCLUDED.channels, enabled = EXCLUDED.enabled, seq = EXCLUDED.seq, properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (typeKey, (value or {}).get('contextTime'), (value or {}).get('offsetMinutes', 0),
              _jsonb((value or {}).get('channels', [])), (value or {}).get('enabled', True), (value or {}).get('seq', 0), _jsonb(props)), 'setNotificationType')
        value = value or {}
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getDocuments(self, tenantKey: str):
        rows = self.query("""
            SELECT d.document_name, d.doc_file, d.properties, d.created_at, d.updated_at
            FROM documents d JOIN tenants t ON t.id = d.tenant_id WHERE t.tenant_key = %s
        """, (tenantKey,))
        return {r[0]: _merge_props({'documentName': r[0], 'docFile': r[1], 'created': _parse_ts(r[3]), 'updated': _parse_ts(r[4])}, r[2]) for r in rows}

    # ------------------------------------------------------------------
    # Tournaments
    # ------------------------------------------------------------------

    def getTournaments(self, tenantKey, tournamentName=None, **entityKeys):
        params = [tenantKey]
        sql = """
            SELECT t.tournament_name, t.tournament_type, t.text, t.href, t.league_id,
                   s.section_name, r.rule_name, t.properties, t.created_at, t.updated_at
            FROM tournaments t
            JOIN tenants ten ON ten.id = t.tenant_id
            LEFT JOIN sections s ON s.id = t.section_id
            LEFT JOIN rules r ON r.id = t.rule_id
            WHERE ten.tenant_key = %s
        """
        if tournamentName:
            sql += ' AND t.tournament_name = %s'
            params.append(tournamentName)
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'tournamentName': r[0], 'tournament': r[1], 'text': r[2], 'href': r[3],
                               'leagueId': r[4], 'section': r[5], 'rules': r[6],
                               'created': _parse_ts(r[8]), 'updated': _parse_ts(r[9])}, r[7])
            result[r[0]] = d
        return result

    def setTournament(self, tenantKey, tournamentName, value):
        tid = self._tenant_id(tenantKey)
        if not tid:
            return value, False
        section_id = None
        if value.get('section'):
            row = self.queryone('SELECT id FROM sections WHERE tenant_id = %s AND section_name = %s', (tid, value['section']))
            section_id = row[0] if row else None
        rule_id = None
        if value.get('rules'):
            row = self.queryone('SELECT id FROM rules WHERE tenant_id = %s AND rule_name = %s', (tid, value['rules']))
            rule_id = row[0] if row else None
        props = {k: v for k, v in value.items() if k not in {'tournamentName', 'tournament', 'text', 'href', 'leagueId', 'section', 'rules', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO tournaments (tenant_id, tournament_name, tournament_type, text, href, league_id, section_id, rule_id, properties, created_at, updated_at)
            VALUES (%s, %s, %s::tournament_type, %s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (tenant_id, tournament_name) DO UPDATE SET
                tournament_type = EXCLUDED.tournament_type, text = EXCLUDED.text, href = EXCLUDED.href,
                league_id = EXCLUDED.league_id, section_id = EXCLUDED.section_id, rule_id = EXCLUDED.rule_id,
                properties = EXCLUDED.properties, updated_at = NOW()
            RETURNING id
        """, (tid, tournamentName, value.get('tournament', 'league'), value.get('text'), value.get('href'),
              value.get('leagueId'), section_id, rule_id, _jsonb(props)), 'setTournament')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def deleteTournament(self, tenantKey, tournamentName):
        """Admin action (see rpApi clientDeleteAdminTournament) - refuses to delete a tournament
        with any non-removed/canceled game still referencing it, rather than cascade-deleting
        games the referee/scraper pipeline still cares about."""
        tid = self._tenant_id(tenantKey)
        tourn_id = self._tournament_id(tid, tournamentName) if tid else None
        if not tourn_id:
            return False, 'לא נמצא'
        row = self.queryone(
            "SELECT COUNT(*) FROM tournament_games WHERE tournament_id = %s AND state NOT IN ('removed', 'canceled')",
            (tourn_id,)
        )
        if row and row[0] > 0:
            return False, f'לא ניתן למחוק - קיימים {row[0]} משחקים פעילים בטורניר זה'
        self._cur.execute("DELETE FROM tournaments WHERE id = %s", (tourn_id,))
        return True, None

    def getTeams(self, tenantKey, tournamentName, **entityKeys):
        """Full team list for a tournament - modest counts per tournament (a division), so the
        client filters/searches locally rather than needing server-side prefix search (matches
        the getTournaments/getRoles precedent)."""
        tid = self._tenant_id(tenantKey)
        tourn_id = self._tournament_id(tid, tournamentName) if tid else None
        if not tourn_id:
            return {}
        rows = self.query("SELECT id, team_name FROM teams WHERE tournament_id = %s ORDER BY team_name", (tourn_id,))
        return {r[0]: {'id': r[0], 'teamName': r[1]} for r in rows}

    def getManualGameTeamOptions(self, tenantKey, tournamentName):
        """Team picker for the manual-game-creation form only (see clientGetGameFormOptions) -
        every team already in this tournament, plus every team from the same section (matched
        by section_name, since sections are separate per-tenant rows each season) in the
        immediately preceding season. A team just hasn't been added to this season's tournament
        yet is a normal state early in a season - the referee still needs to name a real
        opponent, and _ensure_team (see setTournamentGame) will create it under the *current*
        tournament the moment a manual game names it, so this never touches past-season data.
        Unlike getTeams, not reused by the admin team-maintenance views: those manage one
        tournament's exact roster and shouldn't be padded with historical section teams."""
        tid = self._tenant_id(tenantKey)
        tourn_id = self._tournament_id(tid, tournamentName) if tid else None
        if not tourn_id:
            return []
        rows = self.query("SELECT id, team_name FROM teams WHERE tournament_id = %s", (tourn_id,))
        by_name = {name: {'id': team_id, 'teamName': name} for team_id, name in rows}

        prev_tenant_row = self.queryone("""
            SELECT prev_ten.id
            FROM tenants ten
            JOIN tenants prev_ten
              ON prev_ten.country_code = ten.country_code
             AND prev_ten.event_type = ten.event_type
             AND prev_ten.season < ten.season
            WHERE ten.id = %s
            ORDER BY prev_ten.season DESC
            LIMIT 1
        """, (tid,))
        section_row = self.queryone("SELECT section_id FROM tournaments WHERE id = %s", (tourn_id,))
        section_id = section_row[0] if section_row else None
        if prev_tenant_row and section_id:
            section_name_row = self.queryone("SELECT section_name FROM sections WHERE id = %s", (section_id,))
            section_name = section_name_row[0] if section_name_row else None
            if section_name:
                prev_rows = self.query("""
                    SELECT tm.id, tm.team_name
                    FROM teams tm
                    JOIN tournaments trn ON trn.id = tm.tournament_id
                    JOIN sections sec ON sec.id = trn.section_id
                    WHERE trn.tenant_id = %s AND sec.section_name = %s
                """, (prev_tenant_row[0], section_name))
                for team_id, name in prev_rows:
                    by_name.setdefault(name, {'id': team_id, 'teamName': name})

        return sorted(by_name.values(), key=lambda t: t['teamName'])

    def createTeam(self, tenantKey, tournamentName, teamName):
        tid = self._tenant_id(tenantKey)
        tourn_id = self._tournament_id(tid, tournamentName) if tid else None
        if not tourn_id:
            return None, 'לא נמצא טורניר'
        team_id = self._ensure_team(tourn_id, teamName)
        return team_id, None

    def updateTeam(self, teamId, teamName):
        self._cur.execute("UPDATE teams SET team_name = %s, updated_at = NOW() WHERE id = %s", (teamName, teamId))
        return True, None

    def deleteTeam(self, teamId):
        row = self.queryone(
            "SELECT COUNT(*) FROM tournament_games WHERE (home_team_id = %s OR guest_team_id = %s) AND state NOT IN ('removed', 'canceled')",
            (teamId, teamId)
        )
        if row and row[0] > 0:
            return False, f'לא ניתן למחוק - הקבוצה משויכת ל-{row[0]} משחקים פעילים'
        self._cur.execute("DELETE FROM teams WHERE id = %s", (teamId,))
        return True, None

    def getLeagueTables(self, tenantKey, tournamentName, **entityKeys):
        row = self.queryone("""
            SELECT lt.value, lt.created_at, lt.updated_at, t.id
            FROM league_tables lt
            JOIN tournaments t ON t.id = lt.tournament_id
            JOIN tenants ten ON ten.id = t.tenant_id
            WHERE ten.tenant_key = %s AND t.tournament_name = %s
        """, (tenantKey, tournamentName))
        if not row:
            return {}
        # league_tables.value is a scraped standings blob whose embedded team names can drift
        # from the canonical teams table (e.g. missing a playoff-group suffix that the actual
        # game listings use) - the caller resolves display names against this list rather than
        # trusting the blob outright.
        team_rows = self.query("SELECT id, team_name FROM teams WHERE tournament_id = %s", (row[3],))
        teams = [{'id': r[0], 'name': r[1]} for r in team_rows]
        return {tournamentName: {'tournamentName': tournamentName, 'value': row[0],
                                  'created': _parse_ts(row[1]), 'updated': _parse_ts(row[2]),
                                  'teams': teams}}

    def setLeagueTable(self, tenantKey, tournamentName, value):
        tid = self._tenant_id(tenantKey)
        tourn_id = self._tournament_id(tid, tournamentName) if tid else None
        if not tourn_id:
            return value, False
        new_id = self._execute_upsert_id("""
            INSERT INTO league_tables (tournament_id, value, created_at, updated_at)
            VALUES (%s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (tournament_id) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            RETURNING id
        """, (tourn_id, _jsonb(value.get('value', value))), 'setLeagueTable')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    # ------------------------------------------------------------------
    # Tournament games
    # ------------------------------------------------------------------

    # Column order of tournament_games_v as selected below - keep in sync with _tg_row_to_dict.
    _TG_SELECT = """
        SELECT tournament_game_id, tenant_id, tenant_key, event_type, season,
               tournament_name, tournament_type, section_name,
               game_id, game_pk, game_title, game_date, fixture, round, state,
               home_team, guest_team, field_name, field_address, field_lat, field_lng, waze_link,
               group_name, referees, game_result, squads, carpool, url,
               referee_ids, main_referee_ids, reviewer_id, reviewer_name, secretary_id, secretary_name,
               properties, created_at, updated_at,
               tournament_text, tournament_href, tournament_league_id, tournament_properties, rule_name,
               field_formatted_address, field_contact, field_phone, field_level, field_properties,
               tenant_name, tenant_active, tenant_active_status, tenant_game_duration_mins,
               tenant_assigner_collection, tenant_properties,
               group_mobile_numbers,
               is_manual, created_by_referee_id, manual_status
        FROM tournament_games_v
    """

    def _tg_row_to_dict(self, r: tuple) -> dict:
        # tournament_games_v already joins tournaments/teams/fields/tenants, so the tournament,
        # field and tenant details are all embedded - callers can skip separate
        # get_tournament_by_name()/get_field()/getTenants() calls.
        tournament = _merge_props({
            'tournamentName': r[5], 'tournament': r[6], 'text': r[37], 'href': r[38],
            'leagueId': r[39], 'section': r[7], 'rules': r[41],
        }, r[40])
        field = _merge_props({
            'fieldName': r[17], 'address': r[18],
            'lat': float(r[19]) if r[19] is not None else None,
            'lng': float(r[20]) if r[20] is not None else None,
            'wazeLink': r[21], 'formattedAddress': r[42],
            'contact': r[43], 'phone': r[44], 'level': r[45],
        }, r[46])
        tenant = _merge_props({
            'tenantKey': r[2], 'name': r[47], 'active': r[48], 'activeStatus': r[49],
            'gameDurationInMins': r[50], 'assignerCollection': r[51], 'season': r[4],
        }, r[52])
        dedicated = {
            'id': r[0], 'tournamentGameId': r[0], 'gameId': r[8], 'gamePk': r[9], 'gameTitle': r[10],
            'homeTeamName': r[15], 'guestTeamName': r[16],
            'date': _parse_ts(r[11]), 'fieldName': r[17],
            'fieldAddress': r[18], 'fieldLat': float(r[19]) if r[19] is not None else None,
            'fieldLng': float(r[20]) if r[20] is not None else None, 'wazeLink': r[21],
            'fixture': r[12], 'round': r[13], 'url': r[27],
            'groupName': r[22], 'groupMobileNumbers': r[53],
            'state': r[14], 'referees': r[23], 'squads': r[25],
            'gameResult': r[24], 'carpool': r[26],
            'refereeIds': r[28], 'mainReferees': r[29],
            'reviewerReferee': r[30], 'reviewerName': r[31],
            'secretaryReferee': r[32], 'secretaryName': r[33],
            'created': _parse_ts(r[35]), 'updated': _parse_ts(r[36]),
            'tournamentName': r[5], 'tenantKey': r[2], 'season': r[4],
            'tournament': tournament, 'field': field, 'tenant': tenant,
            'isManual': r[54], 'createdByRefereeId': r[55], 'manualStatus': r[56],
        }
        return _merge_props(dedicated, r[34])

    def getTournamentGames(self, tenantKey=None, tournamentName=None, tournamentGameId=None, gamePk=None, gameId=None, nonArchivedOnly=False, filters=None, **entityKeys):
        params = []
        sql = self._TG_SELECT + " WHERE state NOT IN ('removed', 'canceled')"
        if tenantKey:
            params.append(tenantKey)
            sql += " AND tenant_key = %s"
        if tournamentName:
            params.append(tournamentName)
            sql += " AND tournament_name = %s"
        if nonArchivedOnly:
            sql += " AND state != 'archived' AND game_date >= NOW()"
        if tournamentGameId:
            sql += ' AND tournament_game_id = %s'
            params.append(tournamentGameId)
        elif gamePk:
            sql += ' AND game_pk = %s'
            params.append(gamePk)
        elif gameId:
            # gameId is the game's short string identifier - either an org-scraped external id
            # (which can itself be all-digits, e.g. IHA's numeric ids - so digit-vs-string can't
            # distinguish it from a real tournamentGameId passed as a string) or the real
            # tournamentGameId itself (the common case once a game is persisted - see
            # setTournamentGame). Match either column rather than guessing which one it is.
            sql += ' AND game_id = %s'
            params.append(str(gameId))
        rows = self.query(sql, params)
        return {r[0]: self._tg_row_to_dict(r) for r in rows}

    def setTournamentGame(self, tenantKey, tournamentName, value, gamePk=None, tournamentGameId=None):
        tid = self._tenant_id(tenantKey)
        tourn_id = self._tournament_id(tid, tournamentName) if tid else None
        if not tourn_id:
            return value, False

        # game_id (column) / gameId (dict key, matching every other key refereeProcessService.py
        # puts on this dict) is the game's short string identifier - either an org-scraped external
        # id (IHAService) or, absent that, the short placeholder minted for a not-yet-persisted game
        # (see handleTournaments.py/handleRefereeData.py: str(uuid.uuid4())[:8]). Captured only
        # here at INSERT time and preserved via COALESCE below on every later save (once
        # value['id'] is overwritten with the real tournamentGameId), so a WhatsApp button/ICS
        # link minted in the brief pre-persist window keeps resolving via
        # getTournamentGames(gameId=...) - replaces the old reference_ids indirection.
        gameIdForRow = value.get('gameId') or (
            value['id'] if value.get('id') and not str(value['id']).isdigit() else None
        )

        home_id = self._ensure_team(tourn_id, value.get('homeTeamName', ''))
        guest_id = self._ensure_team(tourn_id, value.get('guestTeamName', ''))
        # A blank scraped field must not clobber an already-known field_id on an existing row -
        # _ensure_field('') resolves to the tenant's shared 'Unknown' placeholder field, and a
        # scrape that transiently comes back with no field text (regex miss, site layout quirk,
        # etc.) would otherwise silently reset a previously-correct field back to 'Unknown' on
        # every such sync. field_id is still computed (falls back to 'Unknown') for the INSERT
        # branch, where there's no existing row to preserve; keepExistingFieldOnConflict makes the
        # ON CONFLICT branch below ignore it and keep tournament_games.field_id instead.
        scrapedField = value.get('field')
        field_id = self._ensure_field(tid, scrapedField or '')
        keepExistingFieldOnConflict = not scrapedField
        if keepExistingFieldOnConflict:
            self.logger.warning(f"setTournamentGame: scraped 'field' is blank for gamePk={value.get('gamePk')} tenantKey={tenantKey} - keeping existing field_id on conflict instead of resetting to 'Unknown'")
        if not home_id or not guest_id or not field_id:
            return value, False

        known = {'tenantKey', 'entityKey', 'tournamentGameId', 'id', 'gameId', 'gameTitle', 'homeTeamName', 'guestTeamName',
                 'date', 'field', 'fixture', 'round', 'url', 'groupName', 'groupMobileNumbers',
                 'state', 'referees', 'squads', 'gameResult', 'carpool', 'gamePk',
                 'refereeIds', 'mainReferees', 'secretaryReferee', 'reviewerReferee',
                 'content_hash', 'created', 'updated', 'tournamentName',
                 'isManual', 'createdByRefereeId', 'manualStatus'}
        props = {k: v for k, v in value.items() if k not in known}

        fixtureVal = value.get('fixture') or ''
        roundVal = value.get('round') or ''
        new_id = self._execute_upsert_id("""
            INSERT INTO tournament_games (
                tournament_id, game_id, game_title, game_pk,
                home_team_id, guest_team_id, game_date, field_id,
                fixture, round, url, group_name, group_mobile_numbers,
                state, referees, squads, game_result, carpool,
                referee_ids, main_referee_ids, reviewer_id, secretary_id,
                properties, is_manual, created_by_referee_id, manual_status,
                created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::game_state,
                    %s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,
                    %s::jsonb,%s::jsonb,%s,%s,%s::jsonb,%s,%s,%s,NOW(),NOW())
            ON CONFLICT (tournament_id, fixture, round, home_team_id, guest_team_id) DO UPDATE SET
                game_id=COALESCE(tournament_games.game_id, EXCLUDED.game_id), game_date=EXCLUDED.game_date,
                field_id=CASE WHEN %s THEN tournament_games.field_id ELSE EXCLUDED.field_id END,
                state=EXCLUDED.state, referees=EXCLUDED.referees,
                squads=EXCLUDED.squads, game_result=EXCLUDED.game_result,
                carpool=EXCLUDED.carpool, referee_ids=EXCLUDED.referee_ids,
                main_referee_ids=EXCLUDED.main_referee_ids, reviewer_id=EXCLUDED.reviewer_id,
                secretary_id=EXCLUDED.secretary_id, properties=EXCLUDED.properties,
                is_manual=EXCLUDED.is_manual, created_by_referee_id=EXCLUDED.created_by_referee_id,
                manual_status=EXCLUDED.manual_status, updated_at=NOW()
            RETURNING id
        """, (tourn_id, gameIdForRow, value.get('gameTitle'), value.get('gamePk'),
              home_id, guest_id, _ensure_aware(value.get('date')), field_id,
              fixtureVal, roundVal, value.get('url'),
              value.get('groupName'), value.get('groupMobileNumbers'),
              value.get('state', 'active'),
              _jsonb(value.get('referees', [])), _jsonb(value.get('squads')),
              _jsonb(value.get('gameResult')),
              _jsonb(value.get('carpool')), _jsonb(value.get('refereeIds', [])),
              _jsonb(value.get('mainReferees', [])), value.get('reviewerReferee'), value.get('secretaryReferee'),
              _jsonb(props), bool(value.get('isManual', False)), value.get('createdByRefereeId'),
              value.get('manualStatus'), keepExistingFieldOnConflict), 'setTournamentGame')
        if new_id is not None:
            value['id'] = new_id
            value['tournamentGameId'] = new_id
            # A "real" (non-manual-placeholder) write may supersede an existing manual stand-in
            # for the same real-world game - see _reconcile_manual_stand_in's docstring for why
            # this can't just be ON CONFLICT (the stand-in has a different, synthetic
            # fixture/round so it's never the same row).
            if fixtureVal != '0' and roundVal != '0':
                self._reconcile_manual_stand_in(tourn_id, home_id, guest_id, new_id, value.get('date'))
        return value, new_id is not None

    def _reconcile_manual_stand_in(self, tournament_id, home_id, guest_id, real_row_id, game_date):
        """Called right after a "real" (non-placeholder) setTournamentGame write. A
        manually-created game whose fixture/round were left blank (checkbox ticked) never
        collides with the scraper's own later real write via ON CONFLICT - it has a synthetic
        '0' fixture/round, so it's a different DB row entirely. This looks for such a stand-in
        covering the same real-world game (same tournament, either-order team pair, date within
        a tolerance window - manual games with BOTH fixture and round genuinely known already
        merged for free via ON CONFLICT and never reach this method, since their fixture/round
        aren't the '0' placeholder) and migrates its referee assignments onto the real row before
        archiving it. See the plan's §4 for the full rationale."""
        if not game_date:
            return
        row = self.queryone("""
            SELECT id FROM tournament_games
            WHERE tournament_id = %s AND id != %s AND state = 'active' AND is_manual = true
              AND (manual_status IS NULL OR manual_status != 'reconciled')
              AND ((home_team_id = %s AND guest_team_id = %s) OR (home_team_id = %s AND guest_team_id = %s))
              AND game_date BETWEEN %s - INTERVAL '3 hours' AND %s + INTERVAL '3 hours'
            LIMIT 1
        """, (tournament_id, real_row_id, home_id, guest_id, guest_id, home_id, game_date, game_date))
        if not row:
            return
        stand_in_id = row[0]

        real_referee_ids = {r[0] for r in self.query(
            "SELECT referee_id FROM referee_games WHERE tournament_game_id = %s AND state NOT IN ('removed', 'canceled')",
            (real_row_id,)
        )}
        stand_in_rows = self.query("""
            SELECT referee_id, role_id, status, properties FROM referee_games
            WHERE tournament_game_id = %s AND state NOT IN ('removed', 'canceled')
        """, (stand_in_id,))
        for referee_id, role_id, status, properties in stand_in_rows:
            if referee_id in real_referee_ids:
                continue  # federation's own roster already confirms this referee - nothing to migrate
            props = dict(properties or {})
            props['needsVerification'] = True
            props['migratedFromManualGameId'] = stand_in_id
            self._upsert_referee_game(referee_id, real_row_id, {
                'roleId': role_id, 'status': status, **props,
            })

        self._cur.execute(
            "UPDATE referee_games SET state = 'archived', updated_at = NOW() WHERE tournament_game_id = %s",
            (stand_in_id,)
        )
        self._cur.execute("""
            UPDATE tournament_games
            SET state = 'archived', manual_status = 'reconciled',
                properties = properties || jsonb_build_object('reconciledIntoTournamentGameId', %s),
                updated_at = NOW()
            WHERE id = %s
        """, (real_row_id, stand_in_id))

    def findDuplicateGame(self, tournament_id, home_team_name, guest_team_name, game_date, fixture=None, round_=None):
        """Manual-game-creation dedup check (no precedent elsewhere in the codebase) - a game is
        the same real-world game if the team pair matches in either order AND either the
        fixture/round match exactly (for two genuinely-scraped/known entries) or the date falls
        within a tolerance window (catches a manual entry against a scrape, or two independent
        manual entries for the same game)."""
        row = self.queryone("""
            SELECT tg.id, tg.is_manual, tg.manual_status, tg.state
            FROM tournament_games tg
            JOIN teams ht ON ht.id = tg.home_team_id
            JOIN teams gt ON gt.id = tg.guest_team_id
            WHERE tg.tournament_id = %s
              AND tg.state NOT IN ('removed', 'canceled')
              AND (
                (tg.fixture = %s AND tg.round = %s AND tg.fixture != '0' AND tg.round != '0')
                OR tg.game_date BETWEEN %s - INTERVAL '3 hours' AND %s + INTERVAL '3 hours'
              )
              AND (
                (ht.team_name = %s AND gt.team_name = %s)
                OR (ht.team_name = %s AND gt.team_name = %s)
              )
            LIMIT 1
        """, (tournament_id, fixture or '', round_ or '', game_date, game_date,
              home_team_name, guest_team_name, guest_team_name, home_team_name))
        if not row:
            return None
        return {'tournamentGameId': row[0], 'isManual': row[1], 'manualStatus': row[2], 'state': row[3]}

    def findOverlappingGame(self, referee_id, game_date, duration_mins):
        """Manual-game-creation overlap check (no precedent elsewhere) - any other active game
        this referee is assigned to (any tenant) whose [start, start+duration) range intersects
        the new game's own range."""
        row = self.queryone("""
            SELECT tg.id, tg.game_date, tg.game_title
            FROM referee_games rg
            JOIN tournament_games tg ON tg.id = rg.tournament_game_id
            JOIN tournaments tn ON tn.id = tg.tournament_id
            JOIN tenants t ON t.id = tn.tenant_id
            WHERE rg.referee_id = %s
              AND rg.state NOT IN ('removed', 'archived', 'canceled')
              AND tg.state NOT IN ('removed', 'canceled')
              AND tg.game_date < %s
              AND (tg.game_date + (t.game_duration_mins || ' minutes')::interval) > %s
            LIMIT 1
        """, (referee_id, game_date + timedelta(minutes=duration_mins), game_date))
        if not row:
            return None
        return {'tournamentGameId': row[0], 'gameDate': row[1], 'gameTitle': row[2]}

    def setGameResult(self, tournamentGameId, gameResult):
        """Direct score write for ANY game (manual or scraped) - no existing writer touches
        game_result outside the WhatsApp/browser-automation "report your stats" template flow,
        which is unrelated (refereeProcessService.py's postGameUpdate)."""
        self._cur.execute(
            "UPDATE tournament_games SET game_result = %s::jsonb, updated_at = NOW() WHERE id = %s",
            (_jsonb(gameResult), tournamentGameId)
        )
        return True

    def deleteTournamentGame(self, tenantKey=None, tournamentName=None, gamePk=None, tournamentGameId=None):
        tg_id = tournamentGameId or self._resolve_tournament_game_id(tenantKey, gamePk)
        if tg_id:
            self._cur.execute(
                "UPDATE tournament_games SET state = 'removed' WHERE id = %s",
                (tg_id,),
            )

    def archiveTournamentGame(self, tenantKey=None, tournamentName=None, gamePk=None, tournamentGameId=None):
        tournamentGameId = tournamentGameId or self._resolve_tournament_game_id(tenantKey, gamePk)
        if tournamentGameId:
            self._cur.execute(
                "UPDATE tournament_games SET state = 'archived' WHERE id = %s",
                (tournamentGameId,),
            )

    def getTournamentGamesArchived(self, tenantKey=None, tournamentName=None, tournamentGameId=None, **entityKeys):
        # obsolete: no production callers left (only the smoke test exercises this)
        params = []
        sql = self._TG_SELECT + " WHERE state = 'archived'"
        if tenantKey:
            sql += ' AND tenant_key = %s'
            params.append(tenantKey)
        if tournamentName:
            sql += ' AND tournament_name = %s'
            params.append(tournamentName)
        if tournamentGameId:
            sql += ' AND tournament_game_id = %s'
            params.append(tournamentGameId)
        rows = self.query(sql, params)
        return {r[0]: self._tg_row_to_dict(r) for r in rows}

    def getPublicGames(
        self,
        tenant_keys: list,
        tournament_name: str = None,
        section_filter: str = None,
        from_date=None,
        to_date=None,
        field_filter: str = None,
        referee_id: int = None,
        referee_name: str = None,
    ) -> list:
        """Single-query fetch of public games with all filters pushed to SQL.
        Caller is responsible for referee visibility (name/phone masking) logic.
        """
        params: list = [tenant_keys]

        sql = """
            SELECT
                tg.id,
                tg.game_id,
                tg.game_title,
                ht.team_name,
                gt.team_name,
                tg.game_date,
                f.field_name,
                tg.fixture,
                tg.round,
                tg.url,
                tg.group_name,
                tg.group_mobile_numbers,
                tg.state,
                tg.referees,
                tg.squads,
                tg.game_result,
                tg.carpool,
                tg.referee_ids,
                tg.main_referee_ids,
                tg.properties,
                tg.created_at,
                tg.updated_at,
                t.tournament_name,
                ten.tenant_key,
                COALESCE(s.section_name, '') AS section_name,
                ten.name AS tenant_name,
                ten.properties AS tenant_props,
                f.lat,
                f.lng,
                tg.is_manual,
                tg.created_by_referee_id,
                tg.manual_status
            FROM tournament_games tg
            JOIN tournaments t ON t.id = tg.tournament_id
            JOIN tenants ten ON ten.id = t.tenant_id
            LEFT JOIN sections s ON s.id = t.section_id
            JOIN teams ht ON ht.id = tg.home_team_id
            JOIN teams gt ON gt.id = tg.guest_team_id
            JOIN fields f ON f.id = tg.field_id
            WHERE tg.state NOT IN ('canceled')
              AND ten.tenant_key = ANY(%s)
        """

        if tournament_name:
            sql += ' AND t.tournament_name = %s'; params.append(tournament_name)
        if section_filter:
            sql += ' AND s.section_name = %s'; params.append(section_filter)
        if from_date:
            sql += ' AND tg.game_date >= %s'; params.append(_ensure_aware(from_date))
        if to_date:
            sql += ' AND tg.game_date <= %s'; params.append(_ensure_aware(to_date))
        if field_filter:
            like_val = f'%{field_filter}%'
            sql += (
                " AND (f.field_name ILIKE %s"
                " OR tg.properties->>'fieldName' ILIKE %s"
                " OR tg.properties->'fieldData'->>'name' ILIKE %s)"
            )
            params.extend([like_val, like_val, like_val])
        if referee_id:
            sql += (
                " AND tg.id IN ("
                "   SELECT rg.tournament_game_id FROM referee_games rg"
                "   WHERE rg.referee_id = %s AND rg.state NOT IN ('removed', 'canceled')"
                " )"
            )
            params.append(referee_id)
        if referee_name:
            sql += (
                " AND EXISTS ("
                "   SELECT 1 FROM jsonb_array_elements(tg.referees) ref"
                "   WHERE lower(COALESCE(ref->>'* name', ref->>'name', '')) LIKE lower(%s)"
                " )"
            )
            params.append(f'%{referee_name}%')

        sql += ' ORDER BY tg.game_date DESC'

        rows = self.query(sql, params)

        # tg.referees (the roster scrape used for display below) is a separate sync pipeline from
        # referee_games (the per-referee schedule sync that made the referee_id filter above
        # authoritative) and can lag or omit assignments the latter already has - a game a caller
        # explicitly searched for by referee then renders with an incomplete (or empty) roster
        # even though the match is real. Backfill EVERY referee_games entry missing from tg.referees
        # for exactly these games - not just the one being searched for - since the same scrape gap
        # that dropped the searched referee can just as easily have dropped their co-referees too.
        # NOTE: r.name can be NULL for some referee rows (confirmed via direct query - e.g. ids
        # 2047/2048) - skip those rather than crashing the whole request on a `.strip()` of None,
        # which previously caused this entire query to silently fail and fall back to a much more
        # limited legacy code path (see commit history / session notes for the incident this fixes).
        referee_backfill: dict = {}
        if referee_id and rows:
            game_ids = [r[0] for r in rows]
            rg_rows = self.query(
                """
                SELECT rg.tournament_game_id, r.name, COALESCE(rl.role_name, '')
                FROM referee_games rg
                JOIN referees r ON r.id = rg.referee_id
                LEFT JOIN roles rl ON rl.id = rg.role_id
                WHERE rg.tournament_game_id = ANY(%s)
                  AND rg.state NOT IN ('removed', 'canceled')
                """,
                [game_ids],
            )
            for game_id, ref_name, role_name in rg_rows:
                if not ref_name:
                    continue
                referee_backfill.setdefault(game_id, []).append({'name': ref_name, 'role': role_name})

        result = []
        for r in rows:
            tenant_props = r[26] or {}
            if isinstance(tenant_props, str):
                try:
                    tenant_props = json.loads(tenant_props)
                except Exception:
                    tenant_props = {}
            tenant_icon = tenant_props.get('icon', '') if isinstance(tenant_props, dict) else ''

            referees_list = r[13] if isinstance(r[13], list) else []
            existing_referee_names = {
                str(ref.get('* name') or ref.get('name') or '').strip().lower()
                for ref in referees_list if isinstance(ref, dict)
            }
            for backfill_entry in referee_backfill.get(r[0], []):
                name_key = backfill_entry['name'].strip().lower()
                if name_key not in existing_referee_names:
                    referees_list = referees_list + [backfill_entry]
                    existing_referee_names.add(name_key)

            game = _merge_props({
                'id':                 r[0],
                'tournamentGameId':   r[0],
                'gameId':             r[1],
                'gameTitle':          r[2],
                'homeTeamName':       r[3],
                'guestTeamName':      r[4],
                'date':               _parse_ts(r[5], skipZeroedTime=True),
                'scheduledDate':      _parse_ts(r[5], skipZeroedTime=True),
                'field':              r[6],
                'fixture':            _hide_zero(r[7]),
                'round':              _hide_zero(r[8]),
                'url':                r[9],
                'groupName':          r[10],
                'groupMobileNumbers': r[11],
                'state':              r[12],
                'referees':           referees_list,
                'squads':             r[14],
                'gameResult':         r[15],
                'carpool':            r[16],
                'refereeIds':         r[17],
                'mainReferees':       r[18],
                'properties':         r[19],
                'created':            _parse_ts(r[20]),
                'updated':            _parse_ts(r[21]),
                'tournamentName':     r[22],
                'tenantKey':          r[23],
                'sectionName':        r[24],
                'tenantName':         r[25],
                'tenantProps':        tenant_props,
                'fieldLocation':      {'lat': float(r[27]), 'lng': float(r[28])} if r[27] is not None and r[28] is not None else None,
                'isManual':           r[29],
                'createdByRefereeId': r[30],
                'manualStatus':       r[31],
            }, r[19])
            result.append(game)
        return result

    # ------------------------------------------------------------------
    # Referee domain
    # ------------------------------------------------------------------

    def getRefereeProperties(self, mobileNo=None, refereeId=None, propertyName=None, **entityKeys):
        params: list = []
        sql = """
            SELECT r.mobile_no, r.name, r.gender, r.role, r.color, r.guid,
                   r.address, r.latitude, r.longitude, r.origin_address, r.calendar_name,
                   r.telegram_id, r.telegram_username, r.time_arrival_in_advance,
                   r.avoid_night_messages, r.send_messages_to_telegram,
                   r.blocked_from_meta_templates, r.always_create_chat_group, r.ignore_group4singles,
                   r.id_number, r.active_tenant_keys, r.tenant_keys, r.properties, r.created_at, r.updated_at,
                   r.id, r.create_groups, r.window_is_open, r.force_use_green_api,
                   r.available_from_hour, r.available_to_hour, r.email, r.grade, r.occupation,
                   r.area_id, r.notification_overrides
            FROM referees r
        """
        if refereeId:
            sql += ' WHERE r.id = %s'
            params.append(refereeId)
        elif mobileNo:
            sql += ' WHERE r.mobile_no = %s'
            params.append(mobileNo)
        rows = self.query(sql, params or None)
        result = {}
        for r in rows:
            # Legacy DynamoDB-era shape: most referee-address consumers (commute distance calc,
            # org services, auth, admin panel) still read a nested 'addressDetails' dict rather
            # than the dedicated origin_address/latitude/longitude columns - reconstruct it here
            # so those call sites keep working without each needing its own fallback.
            addressDetails = {
                'address': r[9],
                'coordinates': {
                    'lat': float(r[7]) if r[7] is not None else None,
                    'lng': float(r[8]) if r[8] is not None else None,
                },
                'formattedAddress': r[9],
            } if r[9] else None
            d = _merge_props({
                'mobileNo': r[0], 'name': r[1], 'gender': r[2], 'role': r[3], 'color': r[4],
                'guid': str(r[5]) if r[5] else None, 'address': r[6],
                'latitude': float(r[7]) if r[7] else None, 'longitude': float(r[8]) if r[8] else None,
                'originAddress': r[9], 'addressDetails': addressDetails, 'calendarName': r[10], 'telegramId': r[11],
                'telegramUsername': r[12], 'timeArrivalInAdvance': r[13],
                'avoidNightMessages': r[14],
                'sendMessagesToTelegram': r[15], 'blockedFromMetaTemplates': r[16],
                'alwaysCreateChatGroup': r[17], 'ignoreGroup4Singles': r[18],
                'idNumber': r[19],
                'activeTenantKeys': r[20], 'tenantKeys': r[21],
                'created': _parse_ts(r[23]), 'updated': _parse_ts(r[24]),
                'refereeId': r[25], 'createGroups': r[26],
                'windowIsOpen': r[27], 'forceUseGreenApi': r[28],
                'availableFromHour': r[29], 'availableToHour': r[30],
                'email': r[31], 'grade': r[32], 'occupation': r[33],
                'areaId': r[34], 'notificationOverrides': r[35] or {},
            }, r[22])
            if (mobileNo or refereeId) and propertyName:
                return d.get(propertyName)
            result[r[25]] = d
        return result

    def setRefereeProperties(self, mobileNo=None, refereeId=None, value=None, propertyName=None, **entityKeys):
        if not mobileNo and refereeId:
            # setRefereeProperties upserts by mobile_no when one is known; resolve it once so
            # callers can identify the referee by refereeId alone. mobile_no may legitimately
            # come back None here (a referee created without a mobile number yet) - that's not
            # an error, it just routes below to the update-by-id path instead of ON CONFLICT.
            row = self.queryone('SELECT mobile_no FROM referees WHERE id = %s', (refereeId,))
            if row is None:
                return value, False
            mobileNo = row[0]
        if propertyName:
            existing = self.getRefereeProperties(mobileNo=mobileNo, refereeId=refereeId)
            if not existing:
                return value, False
            value = list(existing.values())[0]
            value[propertyName] = value

        props = {k: v for k, v in value.items() if k not in {
            'mobileNo', 'name', 'gender', 'role', 'color', 'guid', 'address',
            'latitude', 'longitude', 'originAddress', 'calendarName', 'telegramId',
            'telegramUsername', 'timeArrivalInAdvance',
            'avoidNightMessages', 'sendMessagesToTelegram',
            'idNumber', 'activeTenantKeys', 'tenantKeys', 'content_hash', 'created', 'updated',
            'createGroups', 'windowIsOpen', 'forceUseGreenApi',
            'availableFromHour', 'availableToHour', 'email', 'areaId', 'grade', 'occupation',
            'notificationOverrides',
        }}
        common_values = (
            value.get('name'), value.get('gender'), value.get('role'), value.get('color'),
            value.get('address'), value.get('latitude'), value.get('longitude'),
            value.get('originAddress'), value.get('calendarName'), value.get('telegramId'),
            value.get('telegramUsername'), value.get('timeArrivalInAdvance'),
            value.get('avoidNightMessages', False),
            value.get('sendMessagesToTelegram', False),
            value.get('alwaysCreateChatGroup', False), value.get('ignoreGroup4Singles', False),
            value.get('idNumber'),
            value.get('createGroups', False),
            value.get('windowIsOpen', False), value.get('forceUseGreenApi', False),
            value.get('availableFromHour', 7), value.get('availableToHour', 21),
            value.get('email'), value.get('areaId'), value.get('grade'), value.get('occupation'),
            _jsonb(value.get('activeTenantKeys', [])), _jsonb(value.get('tenantKeys', [])),
            _jsonb(value.get('notificationOverrides', {})),
            _jsonb(props),
        )
        if mobileNo:
            new_id = self._execute_upsert_id("""
                INSERT INTO referees (mobile_no, name, gender, role, color, address,
                    latitude, longitude, origin_address, calendar_name, telegram_id, telegram_username,
                    time_arrival_in_advance,
                    avoid_night_messages, send_messages_to_telegram,
                    always_create_chat_group, ignore_group4singles, id_number,
                    create_groups, window_is_open, force_use_green_api,
                    available_from_hour, available_to_hour, email, area_id, grade, occupation,
                    active_tenant_keys, tenant_keys, notification_overrides, properties, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,NOW(),NOW())
                ON CONFLICT (mobile_no) DO UPDATE SET
                    name=EXCLUDED.name, gender=EXCLUDED.gender, role=EXCLUDED.role, color=EXCLUDED.color,
                    address=EXCLUDED.address, latitude=EXCLUDED.latitude, longitude=EXCLUDED.longitude,
                    origin_address=EXCLUDED.origin_address, calendar_name=EXCLUDED.calendar_name,
                    telegram_id=EXCLUDED.telegram_id, telegram_username=EXCLUDED.telegram_username,
                    time_arrival_in_advance=EXCLUDED.time_arrival_in_advance,
                    avoid_night_messages=EXCLUDED.avoid_night_messages,
                    send_messages_to_telegram=EXCLUDED.send_messages_to_telegram,
                    always_create_chat_group=EXCLUDED.always_create_chat_group,
                    ignore_group4singles=EXCLUDED.ignore_group4singles,
                    id_number=EXCLUDED.id_number,
                    create_groups=EXCLUDED.create_groups,
                    window_is_open=EXCLUDED.window_is_open, force_use_green_api=EXCLUDED.force_use_green_api,
                    available_from_hour=EXCLUDED.available_from_hour, available_to_hour=EXCLUDED.available_to_hour,
                    email=EXCLUDED.email, area_id=EXCLUDED.area_id, grade=EXCLUDED.grade, occupation=EXCLUDED.occupation,
                    active_tenant_keys=EXCLUDED.active_tenant_keys, tenant_keys=EXCLUDED.tenant_keys,
                    notification_overrides=EXCLUDED.notification_overrides,
                    properties=EXCLUDED.properties, updated_at=NOW()
                RETURNING id
            """, (mobileNo,) + common_values, 'setRefereeProperties')
        elif refereeId:
            # Mobile-less referee that already exists (resolved above) - update by id directly.
            # ON CONFLICT (mobile_no) can't be used to dedupe here since mobile_no is NULL and
            # Postgres treats every NULL as distinct from every other NULL.
            new_id = self._execute_upsert_id("""
                UPDATE referees SET
                    name=%s, gender=%s, role=%s, color=%s, address=%s,
                    latitude=%s, longitude=%s, origin_address=%s, calendar_name=%s,
                    telegram_id=%s, telegram_username=%s,
                    time_arrival_in_advance=%s,
                    avoid_night_messages=%s,
                    send_messages_to_telegram=%s,
                    always_create_chat_group=%s, ignore_group4singles=%s, id_number=%s,
                    create_groups=%s, window_is_open=%s, force_use_green_api=%s,
                    available_from_hour=%s, available_to_hour=%s, email=%s, area_id=%s, grade=%s, occupation=%s,
                    active_tenant_keys=%s::jsonb, tenant_keys=%s::jsonb, notification_overrides=%s::jsonb,
                    properties=%s::jsonb, updated_at=NOW()
                WHERE id = %s
                RETURNING id
            """, common_values + (refereeId,), 'setRefereeProperties')
        else:
            # Brand new mobile-less referee - plain insert, no natural conflict target exists yet.
            new_id = self._execute_upsert_id("""
                INSERT INTO referees (name, gender, role, color, address,
                    latitude, longitude, origin_address, calendar_name, telegram_id, telegram_username,
                    time_arrival_in_advance,
                    avoid_night_messages, send_messages_to_telegram,
                    always_create_chat_group, ignore_group4singles, id_number,
                    create_groups, window_is_open, force_use_green_api,
                    available_from_hour, available_to_hour, email, area_id, grade, occupation,
                    active_tenant_keys, tenant_keys, notification_overrides, properties, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,NOW(),NOW())
                RETURNING id
            """, common_values, 'setRefereeProperties')
        if new_id is not None:
            value['refereeId'] = new_id
            value['id'] = new_id
        return value, new_id is not None

    def getTenantRefereeProperties(self, tenantKey: str = None, mobileNo=None, refereeId=None, propertyName=None, **entityKeys):
        params: list = []
        sql = """
            SELECT tr.tenant_id, t.tenant_key, r.mobile_no, tr.ref_id, tr.status, tr.role, tr.portal_allow,
                   tr.properties, tr.created_at, tr.updated_at, r.id, tr.internal_referee_id
            FROM tenant_referees tr
            JOIN referees r ON r.id = tr.referee_id
            JOIN tenants t  ON t.id = tr.tenant_id
            WHERE 1 = 1
        """
        if tenantKey:
            sql += ' AND t.tenant_key = %s'
            params.append(tenantKey)
        if refereeId:
            sql += ' AND r.id = %s'
            params.append(refereeId)
        elif mobileNo:
            sql += ' AND r.mobile_no = %s'
            params.append(mobileNo)
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({ 'tenantId': r[0], 'tenantKey': r[1],
                'mobileNo': r[2], 'refId': r[3], 'status': r[4],
                'role': r[5], 'portalAllow': r[6],
                'created': _parse_ts(r[8]), 'updated': _parse_ts(r[9]),
                'refereeId': r[10], 'internalRefereeId': r[11],
            }, r[7])
            if (mobileNo or refereeId) and propertyName:
                return d.get(propertyName)
            # Key by refereeId, not mobile_no - mobile_no is nullable and multiple mobile-less
            # referees would otherwise collapse into a single None-keyed dict entry.
            result[r[10]] = d
        return result

    def setTenantRefereeProperties(self, tenantKey: str, mobileNo=None, refereeId=None, value=None, propertyName=None, **entityKeys):
        if propertyName:
            existing = self.getTenantRefereeProperties(tenantKey=tenantKey, mobileNo=mobileNo, refereeId=refereeId)
            if not existing:
                return value, False
            value = list(existing.values())[0]
            value[propertyName] = value
        props = {k: v for k, v in value.items() if k not in {
            'mobileNo', 'refId', 'status', 'role', 'portalAllow', 'content_hash', 'created', 'updated',
            'internalRefereeId', 'tenantId', 'tenantKey', 'refereeId',
        }}
        resolved_referee_id = refereeId or self._referee_id(mobileNo)
        tid = self._tenant_id(tenantKey)
        if not resolved_referee_id or not tid:
            return value, False
        # Look up any existing row for this (referee_id, tenant_id) pair directly instead of
        # relying on ON CONFLICT (tenant_id, ref_id) - ref_id is nullable and Postgres treats
        # every NULL as distinct, so that target can't dedupe referees without a legacy ref_id
        # (e.g. mobile-less referees, which never have one) and would insert a fresh duplicate
        # row on every call.
        existing_row = self.queryone(
            'SELECT id FROM tenant_referees WHERE referee_id = %s AND tenant_id = %s ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 1',
            (resolved_referee_id, tid),
        )
        if existing_row:
            new_id = self._execute_upsert_id("""
                UPDATE tenant_referees SET
                    ref_id=%s, status=%s::referee_status, role=%s, portal_allow=%s,
                    internal_referee_id=%s, properties=%s::jsonb, updated_at=NOW()
                WHERE id = %s
                RETURNING id
            """, (value.get('refId'), value.get('status', 'inactive'), value.get('role'),
                  value.get('portalAllow', False), value.get('internalRefereeId'), _jsonb(props),
                  existing_row[0]), 'setTenantRefereeProperties')
        else:
            new_id = self._execute_upsert_id("""
                INSERT INTO tenant_referees (referee_id, tenant_id, ref_id, status, role, portal_allow, internal_referee_id, properties, created_at, updated_at)
                VALUES (%s, %s, %s, %s::referee_status, %s, %s, %s, %s::jsonb, NOW(), NOW())
                RETURNING id
            """, (resolved_referee_id, tid, value.get('refId'), value.get('status', 'inactive'), value.get('role'),
                  value.get('portalAllow', False), value.get('internalRefereeId'), _jsonb(props)), 'setTenantRefereeProperties')
        if new_id is not None:
            value['id'] = new_id
            value['refereeId'] = resolved_referee_id
        return value, new_id is not None

    def getRefereeAvailaiblity(self, mobileNo: str = None, refereeId: int = None, from_date: datetime = None, to_date: datetime = None, **entityKeys):
        filter_col = 'r.id' if refereeId is not None else 'r.mobile_no'
        params = [refereeId if refereeId is not None else mobileNo]
        sql = f"""
            SELECT ra.id, ra.availability_date, ra.availability_status, ra.properties, ra.created_at, ra.updated_at, r.mobile_no
            FROM referee_availability ra
            JOIN referees r ON r.id = ra.referee_id
            WHERE {filter_col} = %s
        """
        if from_date:
            sql += ' AND ra.availability_date >= %s'
            # availability_date is a DATE column - localize first so an aware/UTC instant near
            # local midnight extracts the correct local calendar day, not the UTC one.
            params.append(_ensure_aware(from_date).astimezone(local_tz).date() if isinstance(from_date, datetime) else from_date)
        if to_date:
            sql += ' AND ra.availability_date <= %s'
            params.append(_ensure_aware(to_date).astimezone(local_tz).date() if isinstance(to_date, datetime) else to_date)
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            date_str = str(r[1])
            # 'status', not 'availabilityStatus': the DynamoDB path and both clients (iOS/PWA)
            # read/write this field as 'status' - returning 'availabilityStatus' here left every
            # day's status silently missing (nil) for referees on the Postgres backend.
            d = _merge_props({'mobileNo': r[6], 'date': date_str, 'id': r[0], 'status': r[2],
                               'created': _parse_ts(r[4]), 'updated': _parse_ts(r[5])}, r[3])
            result[date_str] = d
        return result

    def setRefereeAvailaiblity(self, mobileNo: str = None, refereeId: int = None, value=None, **entityKeys):
        updated = False
        for date, availability in (value or {}).items():
            referee_id = refereeId if refereeId is not None else self._referee_id(mobileNo)
            if not referee_id:
                continue
            props = {k: v for k, v in availability.items()
                      if k not in {'mobileNo', 'date', 'status', 'availabilityStatus', 'id', 'created', 'updated'}}
            new_id = self._execute_upsert_id("""
                INSERT INTO referee_availability (referee_id, availability_date, availability_status, properties, created_at, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, NOW(), NOW())
                ON CONFLICT (referee_id, availability_date) DO UPDATE SET
                    availability_status = EXCLUDED.availability_status, properties = EXCLUDED.properties, updated_at = NOW()
                RETURNING id
            """, (referee_id, date, availability.get('availabilityStatus') or availability.get('status'), _jsonb(props)), 'setRefereeAvailaiblity')
            if new_id is not None:
                availability['id'] = new_id
                updated = True
        return value, updated

    # ------------------------------------------------------------------
    # Referee games
    # ------------------------------------------------------------------

    # Column order of referee_games_v as selected below - keep in sync with _rg_row_to_dict.
    _RG_SELECT = """
        SELECT referee_game_id, state, role_id, role_name, status, internal_id,
               approved_date, declined_date, referee_game_properties, created_at, updated_at,
               referee_id, mobile_no, ref_id, tenant_key,
               tournament_game_id, game_pk, game_title, game_date, fixture, round, url,
               group_name, group_mobile_numbers, game_state, game_referees, squads,
               game_result, carpool, referee_ids, main_referee_ids,
               reviewer_id, reviewer_name, secretary_id, secretary_name,
               game_properties, game_created_at, game_updated_at, tournament_name,
               home_team, guest_team, field_name, field_address, field_lat, field_lng, waze_link,
               tournament_text, tournament_href, tournament_league_id, tournament_properties,
               section_name, rule_name,
               field_formatted_address, field_contact, field_phone, field_level, field_properties,
               tenant_name, tenant_active, tenant_active_status, tenant_game_duration_mins,
               tenant_assigner_collection, tenant_properties,
               referee_global_role, referee_guid, referee_address, referee_latitude, referee_longitude,
               referee_origin_address, referee_calendar_name, referee_telegram_id, referee_telegram_username,
               referee_time_arrival_in_advance, referee_avoid_night_messages,
               referee_send_messages_to_telegram,
               referee_active_tenant_keys, referee_tenant_keys, referee_properties,
               referee_name, gender, color, referee_status, tenant_role, portal_allow,
               tournament_type, referee_blocked_from_meta_templates,
               referee_always_create_chat_group, referee_ignore_group4singles,
               season, game_short_id,
               is_manual, created_by_referee_id, manual_status
        FROM referee_games_v
    """

    def _rg_row_to_dict(self, r: tuple) -> dict:
        # referee_games_v already joins tournament_games/teams/fields/tenants/referees, so the
        # tournament game, tournament, field, tenant and referee details are all embedded -
        # callers can skip separate getGameDetail()/get_tournament_by_name()/get_field()/
        # getTenants()/getReferees() calls.
        gameDetail = _merge_props({
            'id': r[15], 'tournamentGameId': r[15], 'gameId': r[89], 'gamePk': r[16], 'gameTitle': r[17],
            'date': _parse_ts(r[18]), 'fixture': r[19], 'round': r[20], 'url': r[21],
            'groupName': r[22], 'groupMobileNumbers': r[23], 'state': r[24],
            'referees': r[25], 'squads': r[26], 'gameResult': r[27],
            'carpool': r[28], 'refereeIds': r[29], 'mainReferees': r[30],
            'reviewerReferee': r[31], 'reviewerName': r[32],
            'secretaryReferee': r[33], 'secretaryName': r[34],
            'created': _parse_ts(r[36]), 'updated': _parse_ts(r[37]),
            'tournamentName': r[38], 'tenantKey': r[14], 'season': r[88],
            'homeTeamName': r[39], 'guestTeamName': r[40], 'fieldName': r[41],
            'fieldAddress': r[42], 'fieldLat': float(r[43]) if r[43] is not None else None,
            'fieldLng': float(r[44]) if r[44] is not None else None, 'wazeLink': r[45],
            'isManual': r[90], 'createdByRefereeId': r[91], 'manualStatus': r[92],
        }, r[35])
        tournament = _merge_props({
            'tournamentName': r[38], 'tournament': r[84], 'text': r[46], 'href': r[47],
            'leagueId': r[48], 'section': r[50], 'rules': r[51],
        }, r[49])
        field = _merge_props({
            'fieldName': r[41], 'address': r[42],
            'lat': float(r[43]) if r[43] is not None else None,
            'lng': float(r[44]) if r[44] is not None else None,
            'wazeLink': r[45], 'formattedAddress': r[52],
            'contact': r[53], 'phone': r[54], 'level': r[55],
        }, r[56])
        tenant = _merge_props({
            'tenantKey': r[14], 'name': r[57], 'active': r[58], 'activeStatus': r[59],
            'gameDurationInMins': r[60], 'assignerCollection': r[61], 'season': r[88],
        }, r[62])
        refereeDetail = _merge_props({
            'refereeId': r[11], 'mobileNo': r[12], 'name': r[78], 'gender': r[79],
            'role': r[63], 'color': r[80], 'guid': r[64], 'address': r[65],
            'latitude': float(r[66]) if r[66] is not None else None,
            'longitude': float(r[67]) if r[67] is not None else None,
            'originAddress': r[68], 'calendarName': r[69],
            'telegramId': r[70], 'telegramUsername': r[71],
            'timeArrivalInAdvance': r[72], 'avoidNightMessages': r[73],
            'sendMessagesToTelegram': r[74],
            'activeTenantKeys': r[75], 'tenantKeys': r[76],
            'refId': r[13], 'status': r[81], 'tenantRole': r[82], 'portalAllow': r[83],
            'blockedFromMetaTemplates': r[85], 'alwaysCreateChatGroup': r[86],
            'ignoreGroup4Singles': r[87],
        }, r[77])
        dedicated = {
            'id': r[0], 'state': r[1], 'roleId': r[2], 'role': r[3], 'status': r[4], 'internalId': r[5],
            'tournamentGameId': r[15], 'tournamentName': r[38], 'tenantKey': r[14],
            'mobileNo': r[12], 'refId': r[13], 'season': r[88],
            'approvedDate': _parse_ts(r[6]), 'declinedDate': _parse_ts(r[7]),
            'created': _parse_ts(r[9]), 'updated': _parse_ts(r[10]),
            'refereeId': r[11], 'gameDate': _parse_ts(r[18]), 'date': _parse_ts(r[18]),
            'gameDetail': gameDetail, 'tournament': tournament, 'field': field,
            'tenant': tenant, 'refereeDetail': refereeDetail,
        }
        return _merge_props(dedicated, r[8])

    def getRefereeGames(self, tenantKey=None, mobileNo=None, refereeId=None, tournamentGameId=None, includeArchived=False, includeRemoved=False,
                        includeCanceled=False, from_date=None, to_date=None, from_created=None, to_created=None, **entityKeys):
        params = []
        sql = self._RG_SELECT + ' WHERE 1 = 1'
        if tenantKey:
            sql += ' AND tenant_key = %s'; params.append(tenantKey)
        if refereeId:
            sql += ' AND referee_id = %s'; params.append(refereeId)
        elif mobileNo:
            sql += ' AND mobile_no = %s'; params.append(mobileNo)
        sql, params = self._apply_game_state_filters(sql, params, includeArchived, includeRemoved, includeCanceled)
        if tournamentGameId:
            sql += ' AND tournament_game_id = %s'; params.append(tournamentGameId)
        if from_date:
            sql += ' AND game_date >= %s'; params.append(_ensure_aware(from_date))
        if to_date:
            sql += ' AND game_date <= %s'; params.append(_ensure_aware(to_date))
        if from_created:
            sql += ' AND created_at >= %s'; params.append(_ensure_aware(from_created))
        if to_created:
            sql += ' AND created_at <= %s'; params.append(_ensure_aware(to_created))
        rows = self.query(sql, params)
        return {r[0]: self._rg_row_to_dict(r) for r in rows}

    def _apply_game_state_filters(self, sql, params, include_archived, include_removed, include_canceled, state_column='state'):
        excluded = []
        if not include_archived:
            excluded.append('archived')
        if not include_removed:
            excluded.append('removed')
        if not include_canceled:
            excluded.append('canceled')
        if excluded:
            placeholders = ','.join(['%s'] * len(excluded))
            sql += f' AND {state_column} NOT IN ({placeholders})'
            params.extend(excluded)
        return sql, params

    def setRefereeGame(self, tenantKey, value, mobileNo=None, refereeId=None, tournamentGameId=None, gamePk=None, **entityKeys):
        tid = self._tenant_id(tenantKey)
        referee_id = refereeId or (self._resolve_referee_id(mobileNo) if tid else None)
        tg_id = tournamentGameId or self._resolve_tournament_game_id(tenantKey, gamePk)
        if not referee_id or not tg_id:
            # Silently dropping this is how a referee's new assignment can vanish - e.g. when the
            # per-referee sync discovers an assignment for a game the tournament-level sync hasn't
            # created in tournament_games yet. Log it so a missing referee_games row is traceable
            # instead of just disappearing.
            self.logger.warning(
                f'setRefereeGame: skipping, unresolved referee_id={referee_id} tournament_game_id={tg_id} '
                f'(tenantKey={tenantKey}, mobileNo={mobileNo}, refereeId={refereeId}, tournamentGameId={tournamentGameId}, gamePk={gamePk})'
            )
            return value, False
        return self._upsert_referee_game(referee_id, tg_id, value)

    def _upsert_referee_game(self, referee_id, tg_id, value):
        props = {k: v for k, v in value.items() if k not in {'state', 'roleId', 'status', 'internalId', 'approvedDate', 'declinedDate', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey', 'mobileNo', 'refId', 'tournamentName', 'gameDetail'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO referee_games (referee_id, tournament_game_id, state, role_id, status, internal_id, approved_date, declined_date, properties, created_at, updated_at)
            VALUES (%s,%s,%s::game_state,%s,%s,%s,%s,%s,%s::jsonb,NOW(),NOW())
            ON CONFLICT (referee_id, tournament_game_id) DO UPDATE SET
                state=EXCLUDED.state, role_id=EXCLUDED.role_id, status=EXCLUDED.status,
                internal_id=EXCLUDED.internal_id, approved_date=EXCLUDED.approved_date, declined_date=EXCLUDED.declined_date,
                properties=EXCLUDED.properties, updated_at=NOW()
            RETURNING id
        """, (referee_id, tg_id, value.get('state', 'active'), value.get('roleId'), value.get('status'),
              value.get('internalId'), _ensure_aware(value.get('approvedDate')), _ensure_aware(value.get('declinedDate')), _jsonb(props)), '_upsert_referee_game')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def removeRefereeGame(self, tenantKey, mobileNo=None, refereeId=None, tournamentGameId=None, gamePk=None, **entityKeys):
        tid = self._tenant_id(tenantKey)
        referee_id = refereeId or (self._resolve_referee_id(mobileNo) if tid else None)
        tg_id = tournamentGameId or self._resolve_tournament_game_id(tenantKey, gamePk)
        if referee_id and tg_id:
            self._cur.execute(
                "UPDATE referee_games SET state = 'removed' WHERE referee_id = %s AND tournament_game_id = %s",
                (referee_id, tg_id),
            )

    def archiveRefereeGame(self, tenantKey, mobileNo=None, refereeId=None, tournamentGameId=None, gamePk=None, **entityKeys):
        tid = self._tenant_id(tenantKey)
        referee_id = refereeId or (self._resolve_referee_id(mobileNo) if tid else None)
        tg_id = tournamentGameId or self._resolve_tournament_game_id(tenantKey, gamePk)
        if referee_id and tg_id:
            self._cur.execute(
                "UPDATE referee_games SET state = 'archived' WHERE referee_id = %s AND tournament_game_id = %s",
                (referee_id, tg_id),
            )

    # ------------------------------------------------------------------
    # Referee reviews
    # ------------------------------------------------------------------

    # Column order of referee_reviews_v as selected below - keep in sync with _rr_row_to_dict.
    _RR_SELECT = """
        SELECT review_id, state, review_grade, reviewer, review_detail, review_properties, created_at, updated_at,
               referee_id, mobile_no, ref_id, tenant_key,
               tournament_game_id, game_pk, game_title, game_date, fixture, round, url,
               group_name, group_mobile_numbers, game_state, game_referees, squads,
               game_result, carpool, referee_ids, main_referee_ids,
               reviewer_id, reviewer_name, secretary_id, secretary_name,
               game_properties, game_created_at, game_updated_at, tournament_name,
               home_team, guest_team, field_name, field_address, field_lat, field_lng, waze_link,
               tournament_text, tournament_href, tournament_league_id, tournament_properties,
               section_name, rule_name,
               field_formatted_address, field_contact, field_phone, field_level, field_properties,
               tenant_name, tenant_active, tenant_active_status, tenant_game_duration_mins,
               tenant_assigner_collection, tenant_properties,
               referee_global_role, referee_guid, referee_address, referee_latitude, referee_longitude,
               referee_origin_address, referee_calendar_name, referee_telegram_id, referee_telegram_username,
               referee_time_arrival_in_advance, referee_avoid_night_messages,
               referee_send_messages_to_telegram,
               referee_active_tenant_keys, referee_tenant_keys, referee_properties,
               referee_name, gender, color, referee_status, tenant_role,
               tournament_type, referee_blocked_from_meta_templates,
               referee_always_create_chat_group, referee_ignore_group4singles,
               season, role_id, review_role_name
        FROM referee_reviews_v
    """

    def _rr_row_to_dict(self, r: tuple) -> dict:
        # referee_reviews_v already joins tournament_games/teams/fields/tenants/referees, so the
        # tournament game, tournament, field, tenant and referee details are all embedded -
        # callers can skip separate getGameDetail()/get_tournament_by_name()/get_field()/
        # getTenants()/getReferees() calls.
        gameDetail = _merge_props({
            'id': r[12], 'tournamentGameId': r[12], 'gamePk': r[13], 'gameTitle': r[14],
            'date': _parse_ts(r[15]), 'fixture': r[16], 'round': r[17], 'url': r[18],
            'groupName': r[19], 'groupMobileNumbers': r[20], 'state': r[21],
            'referees': r[22], 'squads': r[23], 'gameResult': r[24],
            'carpool': r[25], 'refereeIds': r[26], 'mainReferees': r[27],
            'reviewerReferee': r[28], 'reviewerName': r[29],
            'secretaryReferee': r[30], 'secretaryName': r[31],
            'created': _parse_ts(r[33]), 'updated': _parse_ts(r[34]),
            'tournamentName': r[35], 'tenantKey': r[11], 'season': r[84],
            'homeTeamName': r[36], 'guestTeamName': r[37], 'fieldName': r[38],
            'fieldAddress': r[39], 'fieldLat': float(r[40]) if r[40] is not None else None,
            'fieldLng': float(r[41]) if r[41] is not None else None, 'wazeLink': r[42],
        }, r[32])
        tournament = _merge_props({
            'tournamentName': r[35], 'tournament': r[80], 'text': r[43], 'href': r[44],
            'leagueId': r[45], 'section': r[47], 'rules': r[48],
        }, r[46])
        field = _merge_props({
            'fieldName': r[38], 'address': r[39],
            'lat': float(r[40]) if r[40] is not None else None,
            'lng': float(r[41]) if r[41] is not None else None,
            'wazeLink': r[42], 'formattedAddress': r[49],
            'contact': r[50], 'phone': r[51], 'level': r[52],
        }, r[53])
        tenant = _merge_props({
            'tenantKey': r[11], 'name': r[54], 'active': r[55], 'activeStatus': r[56],
            'gameDurationInMins': r[57], 'assignerCollection': r[58], 'season': r[84],
        }, r[59])
        refereeDetail = _merge_props({
            'refereeId': r[8], 'mobileNo': r[9], 'name': r[75], 'gender': r[76],
            'role': r[60], 'color': r[77], 'guid': r[61], 'address': r[62],
            'latitude': float(r[63]) if r[63] is not None else None,
            'longitude': float(r[64]) if r[64] is not None else None,
            'originAddress': r[65], 'calendarName': r[66],
            'telegramId': r[67], 'telegramUsername': r[68],
            'timeArrivalInAdvance': r[69], 'avoidNightMessages': r[70],
            'sendMessagesToTelegram': r[71],
            'activeTenantKeys': r[72], 'tenantKeys': r[73],
            'refId': r[10], 'status': r[78], 'tenantRole': r[79],
            'blockedFromMetaTemplates': r[81], 'alwaysCreateChatGroup': r[82],
            'ignoreGroup4Singles': r[83],
        }, r[74])
        dedicated = {
            'id': r[0], 'state': r[1], 'reviewGrade': r[2], 'reviewer': r[3], 'reviewDetail': r[4],
            'tournamentGameId': r[12], 'tournamentName': r[35], 'tenantKey': r[11],
            'refId': r[10], 'mobileNo': r[9], 'season': r[84],
            'roleId': r[85], 'role': r[86],
            'created': _parse_ts(r[6]), 'updated': _parse_ts(r[7]),
            'refereeId': r[8], 'gameDate': _parse_ts(r[15]), 'date': _parse_ts(r[15]),
            'gameDetail': gameDetail, 'tournament': tournament, 'field': field,
            'tenant': tenant, 'refereeDetail': refereeDetail,
        }
        return _merge_props(dedicated, r[5])

    def getRefereeReviews(self, tenantKey=None, mobileNo=None, refereeId=None, tournamentGameId=None, removed=False, from_date=None, to_date=None, **entityKeys):
        params = []
        sql = self._RR_SELECT + ' WHERE 1 = 1'
        if tenantKey:
            sql += ' AND tenant_key = %s'; params.append(tenantKey)
        if refereeId:
            sql += ' AND referee_id = %s'; params.append(refereeId)
        elif mobileNo:
            sql += ' AND mobile_no = %s'; params.append(mobileNo)
        if tournamentGameId:
            sql += ' AND tournament_game_id = %s'; params.append(tournamentGameId)
        if not removed:
            sql += " AND state != 'removed'"
        if from_date:
            sql += ' AND game_date >= %s'; params.append(_ensure_aware(from_date))
        if to_date:
            sql += ' AND game_date <= %s'; params.append(_ensure_aware(to_date))
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = self._rr_row_to_dict(r)
            result[r[0]] = d
        return result

    def setRefereeReview(self, tenantKey, value, mobileNo=None, refereeId=None, tournamentGameId=None, gamePk=None, **entityKeys):
        tid = self._tenant_id(tenantKey)
        referee_id = refereeId or (self._resolve_referee_id(mobileNo) if tid else None)
        tg_id = tournamentGameId or self._resolve_tournament_game_id(tenantKey, gamePk)
        if not referee_id or not tg_id or not tid:
            self.logger.warning(
                f'setRefereeReview: skipping, unresolved referee_id={referee_id} tournament_game_id={tg_id} tenant_id={tid} '
                f'(tenantKey={tenantKey}, mobileNo={mobileNo}, refereeId={refereeId}, tournamentGameId={tournamentGameId}, gamePk={gamePk})'
            )
            return value, False
        return self._upsert_referee_review(referee_id, tg_id, tid, value)

    def _upsert_referee_review(self, referee_id, tg_id, tenant_id, value):
        detail_keys = {'tournamentName', 'gameTitle', 'date', 'dateText', 'timeText', 'fixture', 'field', 'no.', 'title'}
        review_detail = {k: value[k] for k in detail_keys if k in value}
        role_id = self._resolve_role_id(tenant_id, value.get('role'))
        props = {k: v for k, v in value.items() if k not in detail_keys | {'state', 'role', 'reviewGrade', 'reviewer', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey', 'refId', 'mobileNo'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO referee_reviews (referee_id, tournament_game_id, tenant_id, state, role_id, review_grade, reviewer, review_detail, properties, created_at, updated_at)
            VALUES (%s,%s,%s,%s::game_state,%s,%s,%s,%s::jsonb,%s::jsonb,NOW(),NOW())
            ON CONFLICT (referee_id, tournament_game_id) DO UPDATE SET
                state=EXCLUDED.state, role_id=EXCLUDED.role_id, review_grade=EXCLUDED.review_grade, reviewer=EXCLUDED.reviewer,
                review_detail=EXCLUDED.review_detail, properties=EXCLUDED.properties, updated_at=NOW()
            RETURNING id
        """, (referee_id, tg_id, tenant_id, value.get('state', 'active'), role_id, value.get('reviewGrade'),
              value.get('reviewer'), _jsonb(review_detail), _jsonb(props)), '_upsert_referee_review')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def removeRefereeReview(self, tenantKey, mobileNo=None, refereeId=None, tournamentGameId=None, gamePk=None, **entityKeys):
        tid = self._tenant_id(tenantKey)
        referee_id = refereeId or (self._resolve_referee_id(mobileNo) if tid else None)
        tg_id = tournamentGameId or self._resolve_tournament_game_id(tenantKey, gamePk)
        if referee_id and tg_id:
            self._cur.execute(
                "UPDATE referee_reviews SET state = 'removed' WHERE referee_id = %s AND tournament_game_id = %s",
                (referee_id, tg_id),
            )

    # ------------------------------------------------------------------
    # Referee templates & messages
    # ------------------------------------------------------------------

    def getRefereeTemplates(self, tenantKey=None, mobileNo=None, refereeId=None, action=None, msgSid=None, status=None,
                            from_created=None, to_created=None, from_updated=None, to_updated=None, **entityKeys):
        params = []
        sql = """
            SELECT rt.id, rt.action, rt.msg_sid, rt.status, rt.tournament_game_id,
                   rt.template_content, rt.properties, rt.created_at, rt.updated_at,
                   r.id, r.mobile_no
            FROM referee_templates rt
            JOIN referees r ON r.id = rt.referee_id
            LEFT JOIN tenant_referees tr ON tr.referee_id = r.id
            LEFT JOIN tenants ten ON ten.id = tr.tenant_id
            WHERE 1 = 1
        """
        if tenantKey:
            sql += ' AND ten.tenant_key = %s'; params.append(tenantKey)
        if refereeId:
            sql += ' AND r.id = %s'; params.append(refereeId)
        elif mobileNo:
            sql += ' AND r.mobile_no = %s'; params.append(mobileNo)
        if action:
            sql += ' AND rt.action = %s'; params.append(action)
        if msgSid:
            sql += ' AND rt.msg_sid = %s'; params.append(msgSid)
        if status:
            sql += ' AND rt.status = %s::template_status'; params.append(status)
        if from_created:
            sql += ' AND rt.created_at >= %s'; params.append(_ensure_aware(from_created))
        if to_created:
            sql += ' AND rt.created_at <= %s'; params.append(_ensure_aware(to_created))
        if from_updated:
            sql += ' AND rt.updated_at >= %s'; params.append(_ensure_aware(from_updated))
        if to_updated:
            sql += ' AND rt.updated_at <= %s'; params.append(_ensure_aware(to_updated))
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'id': r[0], 'action': r[1], 'msgSid': r[2], 'status': r[3],
                               'tournamentGameId': r[4], 'templateContent': r[5],
                               'refereeId': r[9], 'mobileNo': r[10],
                               'created': _parse_ts(r[7]), 'updated': _parse_ts(r[8])}, r[6])
            result[r[0]] = d
        return result

    def setRefereeTemplate(self, tenantKey, mobileNo=None, msgSid=None, value=None, refereeId=None):
        tid = self._tenant_id(tenantKey)
        referee_id = refereeId if refereeId is not None else (self._resolve_referee_id(mobileNo) if tid else None)
        if not referee_id:
            return value, False
        tg_id = None
        if value.get('tournamentGameId'):
            tg_id = value['tournamentGameId']
        props = {k: v for k, v in value.items() if k not in {'action', 'msgSid', 'status', 'tournamentGameId', 'templateContent', 'content_hash', 'created', 'updated', 'tenantKey', 'entityKey', 'mobileNo'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO referee_templates (referee_id, action, msg_sid, status, tournament_game_id, template_content, properties, created_at, updated_at)
            VALUES (%s,%s,%s,%s::template_status,%s,%s::jsonb,%s::jsonb,NOW(),NOW())
            ON CONFLICT (referee_id, action, msg_sid) DO UPDATE SET
                status=EXCLUDED.status, tournament_game_id=EXCLUDED.tournament_game_id,
                template_content=EXCLUDED.template_content, properties=EXCLUDED.properties, updated_at=NOW()
            RETURNING id
        """, (referee_id, value.get('action', ''), msgSid, value.get('status', 'created'), tg_id,
              _jsonb(value.get('templateContent', {})), _jsonb(props)), 'setRefereeTemplate')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getRefereeMessages(self, mobileNo=None, refereeId=None, direction=None, msgSid=None, recentDays=None, from_created=None, to_created=None, **entityKeys):
        db_dir = _MSG_DIR_TO_DB.get(direction, direction)
        filter_col = 'r.id' if refereeId is not None else 'r.mobile_no'
        params = [refereeId if refereeId is not None else mobileNo, db_dir]
        sql = f"""
            SELECT rm.id, rm.direction, rm.msg_sid, rm.content, rm.sent_at, rm.properties, rm.created_at, rm.updated_at
            FROM referee_messages rm
            JOIN referees r ON r.id = rm.referee_id
            WHERE {filter_col} = %s AND rm.direction = %s::message_direction
        """
        if msgSid:
            sql += ' AND rm.msg_sid = %s'; params.append(msgSid)
        if recentDays:
            sql += ' AND rm.created_at >= NOW() - INTERVAL %s'; params.append(f'{recentDays} days')
        if from_created:
            sql += ' AND rm.created_at >= %s'; params.append(_ensure_aware(from_created))
        if to_created:
            sql += ' AND rm.created_at <= %s'; params.append(_ensure_aware(to_created))
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            d = _merge_props({'id': r[0], 'direction': _MSG_DIR_FROM_DB.get(r[1], r[1]), 'msgSid': r[2], 'content': r[3],
                               'timestamp': _parse_ts(r[4]), 'created': _parse_ts(r[6]), 'updated': _parse_ts(r[7])}, r[5])
            result[r[0]] = d
        return result

    def setRefereeMessage(self, mobileNo=None, direction=None, msgSid=None, value=None, refereeId=None):
        ref_id = refereeId if refereeId is not None else self._referee_id(mobileNo)
        if not ref_id:
            return value, False
        if not msgSid:
            # msg_sid is NOT NULL and part of the unique key - a failed send (provider
            # returned no id) has nothing to key the row on, so there's nothing to log.
            self.logger.warning(f'setRefereeMessage: skipping log, no msgSid for referee_id={ref_id} direction={direction}')
            return value, False
        db_dir = _MSG_DIR_TO_DB.get(direction, direction)
        props = {k: v for k, v in value.items() if k not in {'direction', 'msgSid', 'content', 'body', 'timestamp', 'content_hash', 'created', 'updated'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO referee_messages (referee_id, direction, msg_sid, content, sent_at, properties, created_at, updated_at)
            VALUES (%s,%s::message_direction,%s,%s,%s,%s::jsonb,NOW(),NOW())
            ON CONFLICT (referee_id, direction, msg_sid) DO UPDATE SET
                content=EXCLUDED.content, sent_at=EXCLUDED.sent_at,
                properties=EXCLUDED.properties, updated_at=NOW()
            RETURNING id
        """, (ref_id, db_dir, msgSid, value.get('content') or value.get('body'),
              _ensure_aware(value.get('timestamp')), _jsonb(props)), 'setRefereeMessage')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    # ------------------------------------------------------------------
    # Client identifiers
    # ------------------------------------------------------------------

    def getClientIdentifier(self, clientIdentifier, from_created=None, **entityKeys):
        def _row_to_dict(row):
            return _merge_props({'id': row[0], 'clientIdentifier': row[1], 'sessionIdentifier': row[2],
                                  'pushSubscription': row[3], 'mobileNo': row[4], 'userAgent': row[5],
                                  'platform': row[6], 'whatsappUuid': row[7],
                                  'created': _parse_ts(row[9]), 'updated': _parse_ts(row[10])}, row[8])

        select = """
            SELECT ci.id, ci.client_identifier, ci.session_identifier, ci.push_subscription,
                   r.mobile_no, ci.user_agent, ci.platform, ci.whatsapp_uuid,
                   ci.properties, ci.created_at, ci.updated_at
            FROM client_identifiers ci JOIN referees r ON r.id = ci.referee_id
        """
        if not clientIdentifier:
            sql = select + ' WHERE 1 = 1'
            params = []
            if from_created:
                sql += ' AND ci.created_at >= %s'; params.append(_ensure_aware(from_created))
            rows = self.query(sql, params)
            return {row[1]: _row_to_dict(row) for row in rows}

        sql = select + ' WHERE ci.client_identifier = %s'
        params = [clientIdentifier]
        if from_created:
            sql += ' AND ci.created_at >= %s'; params.append(_ensure_aware(from_created))
        row = self.queryone(sql, params)
        if not row:
            return {}
        return {clientIdentifier: _row_to_dict(row)}

    def setClientIdentifier(self, clientIdentifier, sessionIdentifier=None, pushSubscription=None,
                            mobileNo=None, refereeId=None, userAgent=None, platform=None, status=None):
        existing = self.getClientIdentifier(clientIdentifier)
        if existing and existing.get(clientIdentifier):
            ex = existing[clientIdentifier]
            sessionIdentifier = sessionIdentifier or ex.get('sessionIdentifier')
            pushSubscription = pushSubscription or ex.get('pushSubscription')
            mobileNo = mobileNo or ex.get('mobileNo')
            userAgent = userAgent or ex.get('userAgent')
            platform = platform or ex.get('platform')

        # mobileNo-based lookup remains the default path; refereeId is the fallback for
        # mobile-less referees (no mobile_no to resolve from) whose caller already knows the id.
        refereeId = (self._referee_id(mobileNo) if mobileNo else None) or refereeId
        whatsapp_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, clientIdentifier))
        if not refereeId:
            return None, False

        new_id = self._execute_upsert_id("""
            INSERT INTO client_identifiers (referee_id, client_identifier, session_identifier, push_subscription, user_agent, platform, whatsapp_uuid, properties, created_at, updated_at)
            VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,'{}'::jsonb,NOW(),NOW())
            ON CONFLICT (client_identifier) DO UPDATE SET
                session_identifier=EXCLUDED.session_identifier, push_subscription=EXCLUDED.push_subscription,
                user_agent=EXCLUDED.user_agent, platform=EXCLUDED.platform, whatsapp_uuid=EXCLUDED.whatsapp_uuid,
                updated_at=NOW()
            RETURNING id
        """, (refereeId, clientIdentifier, sessionIdentifier, _jsonb(pushSubscription),
              userAgent, platform, whatsapp_uuid), 'setClientIdentifier')
        return {'id': new_id, 'clientIdentifier': clientIdentifier, 'sessionIdentifier': sessionIdentifier, 'mobileNo': mobileNo}, new_id is not None

    # ------------------------------------------------------------------
    # Game detail / reference IDs
    # ------------------------------------------------------------------

    def getGameDetail(self, game: dict, **entityKeys):
        tenantKey = game.get('tenantKey')
        tournamentName = game.get('tournamentName')
        tournamentGameId = game.get('id') or game.get('tournamentGameId')
        if not tournamentGameId:
            return None
        return self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, tournamentGameId=tournamentGameId)

    def getReferenceId(self, target: str, target_id: str = None, **entityKeys):
        params = [target]
        sql = """
            SELECT ri.target, ri.target_id, ri.value, ri.created_at, ri.updated_at
            FROM reference_ids ri JOIN tenants t ON t.id = ri.tenant_id
            WHERE ri.target = %s
        """
        if target_id:
            sql += ' AND ri.target_id = %s'; params.append(target_id)
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            val = r[2] if isinstance(r[2], dict) else {}
            val.update({'target': r[0], 'id': r[1], 'created': _parse_ts(r[3]), 'updated': _parse_ts(r[4])})
            result[r[1]] = val
        return result

    def setReferenceId(self, target: str, target_id: str, value, **entityKeys):
        new_id = self._execute_upsert_id("""
            INSERT INTO reference_ids (tenant_id, target, target_id, value, created_at, updated_at)
            SELECT t.id, %s, %s, %s::jsonb, NOW(), NOW() FROM tenants t WHERE t.tenant_key = 'GLOBAL'
            ON CONFLICT (tenant_id, target, target_id) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            RETURNING id
        """, (target, target_id, _jsonb(value)), 'setReferenceId')
        if new_id is not None and isinstance(value, dict):
            value['id'] = new_id
        return value, new_id is not None

    # ------------------------------------------------------------------
    # Messages & key-val
    # ------------------------------------------------------------------

    def getMessage(self, msgSid, **entityKeys):
        row = self.queryone("""
            SELECT m.msg_sid, m.content, m.properties, m.created_at, m.updated_at
            FROM messages m JOIN tenants t ON t.id = m.tenant_id WHERE m.msg_sid = %s LIMIT 1
        """, (msgSid,))
        if not row:
            return None
        return _merge_props({'msgSid': row[0], 'content': row[1], 'created': _parse_ts(row[3]), 'updated': _parse_ts(row[4])}, row[2])

    def setMessage(self, msgSid, value, **entityKeys):
        tenantKey = value.get('tenantKey', 'GLOBAL')
        new_id = self._execute_upsert_id("""
            INSERT INTO messages (tenant_id, msg_sid, content, properties, created_at, updated_at)
            SELECT t.id, %s, %s::jsonb, '{}'::jsonb, NOW(), NOW() FROM tenants t WHERE t.tenant_key = %s
            ON CONFLICT (tenant_id, msg_sid) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING id
        """, (msgSid, _jsonb(value.get('content', value)), tenantKey), 'setMessage')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getKeyVal(self, key, tenantKey='GLOBAL', **entityKeys):
        row = self.queryone("""
            SELECT kv.key, kv.value, kv.created_at, kv.updated_at
            FROM key_val kv JOIN tenants t ON t.id = kv.tenant_id
            WHERE t.tenant_key = %s AND kv.key = %s
        """, (tenantKey, key))
        if not row:
            return {}
        return {row[0]: {'key': row[0], 'value': row[1], 'created': _parse_ts(row[2]), 'updated': _parse_ts(row[3])}}

    def setKeyVal(self, key, value, tenantKey='GLOBAL'):
        new_id = self._execute_upsert_id("""
            INSERT INTO key_val (tenant_id, key, value, created_at, updated_at)
            SELECT t.id, %s, %s::jsonb, NOW(), NOW() FROM tenants t WHERE t.tenant_key = %s
            ON CONFLICT (tenant_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            RETURNING id
        """, (key, _jsonb(value), tenantKey), 'setKeyVal')
        if new_id is not None and isinstance(value, dict):
            value['id'] = new_id
        return value, new_id is not None

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def getNotifications(self, tenantKey: str, target: str, target_id: str = ..., notificationType: str = None,
                         target_to=None, status: str = None,
                         from_created=None, to_created=None, from_updated=None, to_updated=None, **entityKeys):
        # target_id: ... (default) means "no filter" (e.g. admin search UI with a
        # blank field); None means "filter for game-independent (NONGAME) notifications".
        # target follows the same "blank means no filter" rule - admin search UI can leave
        # it empty to browse across all target types.
        params = [tenantKey]
        sql = """
            SELECT n.id, n.target, n.target_id, n.notification_type, ref.mobile_no, n.status,
                   n.properties, n.created_at, n.updated_at, n.to_referee_id, n.game_pk
            FROM notifications n
            LEFT JOIN referees ref ON ref.id = n.to_referee_id
            LEFT JOIN tenant_referees tr ON tr.referee_id = n.to_referee_id
            LEFT JOIN tenants ten ON ten.id = tr.tenant_id
            WHERE (n.to_referee_id IS NULL OR ten.tenant_key = %s)
        """
        if target:
            sql += ' AND n.target = %s'; params.append(target)
        if target_id is None:
            sql += ' AND n.target_id IS NULL'
        elif target_id is not ...:
            resolved_id, game_pk = self._resolve_notification_target_id(tenantKey, target, target_id)
            if resolved_id is not None:
                sql += ' AND n.target_id = %s'; params.append(resolved_id)
            elif game_pk is not None:
                # unresolved against tournament_games — fall back to the raw game_pk
                # so historical/mismatched notifications are still found.
                sql += ' AND n.game_pk = %s'; params.append(game_pk)
            else:
                sql += ' AND n.target_id IS NULL'
        if notificationType:
            sql += ' AND n.notification_type = %s'; params.append(notificationType)
        if target_to:
            to_referee_id = self._resolve_referee_id_or_id(target_to)
            sql += ' AND n.to_referee_id = %s'; params.append(to_referee_id)
        if status:
            sql += ' AND n.status = %s'; params.append(status)
        if from_created:
            sql += ' AND n.created_at >= %s'; params.append(_ensure_aware(from_created))
        if to_created:
            sql += ' AND n.created_at <= %s'; params.append(_ensure_aware(to_created))
        if from_updated:
            sql += ' AND n.updated_at >= %s'; params.append(_ensure_aware(from_updated))
        if to_updated:
            sql += ' AND n.updated_at <= %s'; params.append(_ensure_aware(to_updated))
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            key = r[0]  # notification's own row id - the real unique key (no more event_timestamp)
            d = _merge_props({'id': r[0], 'target': r[1], 'targetId': r[2], 'notificationType': r[3], 'to': r[4],
                               'target_to': r[9], 'status': r[5], 'gamePk': r[10],
                               'tenantKey': tenantKey,
                               'created': _parse_ts(r[7]), 'updated': _parse_ts(r[8])}, r[6])
            result[key] = d
        return result

    def setNotifications(self, tenantKey: str, target: str, target_id: str, notificationType: str,
                         target_to, value, **entityKeys):
        tid = self._tenant_id(tenantKey)
        if not tid:
            return value, False
        to_referee_id = self._resolve_referee_id_or_id(target_to) if target_to else None
        if target == 'tournamentGames':
            to_referee_id = None
        elif not to_referee_id:
            return value, False
        target_id, game_pk = self._resolve_notification_target_id(tenantKey, target, target_id)
        props = {k: v for k, v in value.items() if k not in {'target', 'id', 'notificationType', 'status', 'content_hash', 'created', 'updated', 'tenantKey'}}

        # If the caller already has a real row id (fetched moments earlier via getNotifications -
        # e.g. the delete path and the dedup-cleanup path in refereeProcessService.setNotification,
        # which are transitioning an already-fetched row OUT of 'created'), use it directly instead
        # of re-deriving "existing" below. That lookup is hardcoded to status='created', so once a
        # row's real status is anything else (e.g. already 'deleted'), re-searching for it there
        # finds nothing and falls through to INSERT - creating an endless pile of duplicate rows
        # every time the same logical notification is touched again after its first transition.
        existing_id = value.get('id')
        existing = (existing_id,) if existing_id is not None else None

        # No unique constraint to conflict on anymore (event_timestamp removed) - look up an
        # existing 'created'-status row with the same identity that used to be enforced by the
        # unique index, and update it in place; otherwise insert a new row. The three cases
        # mirror idx_notifications_target / idx_notifications_no_target / idx_notifications_no_referee.
        # Only reached when the caller has no known row id yet (genuinely new/first-touch).
        if existing is None and to_referee_id is not None and target_id is not None:
            existing = self.queryone(
                "SELECT id FROM notifications WHERE to_referee_id = %s AND target = %s AND target_id = %s AND notification_type = %s AND status = 'created' LIMIT 1",
                (to_referee_id, target, target_id, notificationType),
            )
        elif existing is None and to_referee_id is not None:
            existing = self.queryone(
                "SELECT id FROM notifications WHERE to_referee_id = %s AND target = %s AND target_id IS NULL AND COALESCE(game_pk, '') = %s AND notification_type = %s AND status = 'created' LIMIT 1",
                (to_referee_id, target, game_pk or '', notificationType),
            )
        elif existing is None:
            existing = self.queryone(
                "SELECT id FROM notifications WHERE to_referee_id IS NULL AND target = %s AND target_id IS NOT DISTINCT FROM %s AND notification_type = %s AND status = 'created' LIMIT 1",
                (target, target_id, notificationType),
            )

        if existing:
            new_id = self._execute_upsert_id(
                "UPDATE notifications SET status = %s, properties = %s::jsonb, updated_at = NOW() WHERE id = %s RETURNING id",
                (value.get('status'), _jsonb(props), existing[0]), 'setNotifications-update',
            )
        else:
            new_id = self._execute_upsert_id("""
                INSERT INTO notifications (to_referee_id, target, target_id, game_pk, notification_type, status, properties, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,NOW(),NOW())
                RETURNING id
            """, (to_referee_id, target, target_id, game_pk, notificationType, value.get('status'),
                  _jsonb(props)), 'setNotifications-insert')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    # ------------------------------------------------------------------
    # Polls
    # ------------------------------------------------------------------

    def getPolls(self, pollId=None, **entityKeys):
        row = self.queryone("""
            SELECT p.poll_name, p.questions, p.options, p.properties, p.created_at, p.updated_at
            FROM polls p JOIN tenants t ON t.id = p.tenant_id WHERE t.tenant_key = 'GLOBAL'
            AND (%s IS NULL OR p.poll_name = %s)
        """, (pollId, pollId))
        if not row:
            return {}
        return {row[0]: _merge_props({'pollId': row[0], 'questions': row[1], 'options': row[2],
                                       'created': _parse_ts(row[4]), 'updated': _parse_ts(row[5])}, row[3])}

    def setPoll(self, pollId, value=None):
        new_id = self._execute_upsert_id("""
            INSERT INTO polls (tenant_id, poll_name, questions, options, properties, created_at, updated_at)
            SELECT t.id, %s, %s::jsonb, %s::jsonb, '{}'::jsonb, NOW(), NOW() FROM tenants t WHERE t.tenant_key = 'GLOBAL'
            ON CONFLICT (tenant_id, poll_name) DO UPDATE SET
                questions=EXCLUDED.questions, options=EXCLUDED.options, updated_at=NOW()
            RETURNING id
        """, (pollId, _jsonb((value or {}).get('questions', [])), _jsonb((value or {}).get('options', {}))), 'setPoll')
        if new_id is not None and isinstance(value, dict):
            value['id'] = new_id
        return value, new_id is not None

    def getPollVotes(self, pollId, mobileNo=None, questionId=None, **entityKeys):
        params: list = [pollId]
        sql = """
            SELECT pv.mobile_no, pv.question_id, pv.answer, pv.properties, pv.created_at
            FROM poll_votes pv
            JOIN polls p ON p.id = pv.poll_id
            WHERE p.poll_name = %s
        """
        if mobileNo:
            sql += ' AND pv.mobile_no = %s'; params.append(mobileNo)
        if questionId:
            sql += ' AND pv.question_id = %s'; params.append(questionId)
        rows = self.query(sql, params)
        return {f'{r[0]}#{r[1]}': {'mobileNo': r[0], 'questionId': r[1], 'answer': r[2]} for r in rows}

    def setPollVote(self, pollId=None, mobileNo=None, questionId=None, value=None):
        new_id = self._execute_upsert_id("""
            INSERT INTO poll_votes (poll_id, mobile_no, question_id, answer, properties, created_at, updated_at)
            SELECT p.id, %s, %s, %s, '{}'::jsonb, NOW(), NOW() FROM polls p
            JOIN tenants t ON t.id = p.tenant_id WHERE t.tenant_key = 'GLOBAL' AND p.poll_name = %s
            ON CONFLICT (poll_id, mobile_no, question_id) DO UPDATE SET answer=EXCLUDED.answer, updated_at=NOW()
            RETURNING id
        """, (mobileNo, questionId, (value or {}).get('answer'), pollId), 'setPollVote')
        if new_id is not None and isinstance(value, dict):
            value['id'] = new_id
        return value, new_id is not None

    # ------------------------------------------------------------------
    # Not yet implemented
    # ------------------------------------------------------------------

    def getPositionUpdates(self, mobileNo, **entityKeys):
        rows = self.query("""
            SELECT pu.recorded_at, pu.coordinates, pu.properties, pu.created_at, pu.updated_at
            FROM position_updates pu
            JOIN referees r ON r.id = pu.referee_id
            WHERE r.mobile_no = %s
            ORDER BY pu.recorded_at DESC
        """, (mobileNo,))
        result = {}
        for r in rows:
            ts = _parse_ts(r[0])
            coords = r[1] if isinstance(r[1], dict) else {}
            d = _merge_props({'timestamp': ts, 'created': _parse_ts(r[3]), 'updated': _parse_ts(r[4])},
                             {**coords, **(r[2] or {})})
            result[ts] = d
        return result

    def setPositionUpdate(self, mobileNo, timestamp, value):
        coords = {k: v for k, v in value.items() if k in {'lat', 'lng', 'latitude', 'longitude', 'accuracy', 'speed', 'heading'}}
        props  = {k: v for k, v in value.items() if k not in {*coords, 'timestamp', 'content_hash', 'created', 'updated'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO position_updates (referee_id, recorded_at, coordinates, properties, created_at, updated_at)
            SELECT r.id, %s::timestamptz, %s::jsonb, %s::jsonb, NOW(), NOW()
            FROM referees r WHERE r.mobile_no = %s
            ON CONFLICT (referee_id, recorded_at) DO UPDATE SET
                coordinates=EXCLUDED.coordinates, properties=EXCLUDED.properties, updated_at=NOW()
            RETURNING id
        """, (_ensure_aware(timestamp), _jsonb(coords), _jsonb(props), mobileNo), 'setPositionUpdate')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def getRefereeLocations(self, mobileNo, timestamp=None, **entityKeys):
        params: list = [mobileNo]
        sql = """
            SELECT rl.recorded_at, rl.latitude, rl.longitude, rl.properties, rl.created_at, rl.updated_at
            FROM referee_locations rl
            JOIN referees r ON r.id = rl.referee_id
            WHERE r.mobile_no = %s
        """
        if timestamp:
            sql += ' AND rl.recorded_at = %s::timestamptz'
            # Pass the datetime through directly (localized if naive) rather than str() - a
            # naive-looking string here would let Postgres reinterpret it in session-UTC time.
            params.append(_ensure_aware(timestamp))
        sql += ' ORDER BY rl.recorded_at DESC'
        rows = self.query(sql, params)
        result = {}
        for r in rows:
            ts = _parse_ts(r[0])
            d = _merge_props({'timestamp': ts,
                              'latitude': float(r[1]) if r[1] else None,
                              'longitude': float(r[2]) if r[2] else None,
                              'created': _parse_ts(r[4]), 'updated': _parse_ts(r[5])}, r[3])
            result[ts] = d
        return result

    def setRefereeLocation(self, mobileNo, timestamp, value):
        props = {k: v for k, v in value.items() if k not in {'latitude', 'longitude', 'timestamp', 'content_hash', 'created', 'updated'}}
        new_id = self._execute_upsert_id("""
            INSERT INTO referee_locations (referee_id, recorded_at, latitude, longitude, properties, created_at, updated_at)
            SELECT r.id, %s::timestamptz, %s, %s, %s::jsonb, NOW(), NOW()
            FROM referees r WHERE r.mobile_no = %s
            ON CONFLICT (referee_id, recorded_at) DO UPDATE SET
                latitude=EXCLUDED.latitude, longitude=EXCLUDED.longitude,
                properties=EXCLUDED.properties, updated_at=NOW()
            RETURNING id
        """, (_ensure_aware(timestamp), value.get('latitude'), value.get('longitude'),
              _jsonb(props), mobileNo), 'setRefereeLocation')
        if new_id is not None:
            value['id'] = new_id
        return value, new_id is not None

    def setInvocation(self, tenantKey, invocationId, value, **entityKeys):
        new_id = self._execute_upsert_id("""
            INSERT INTO invocations (tenant_id, invocation_id, details, created_at, updated_at)
            SELECT t.id, %s, %s::jsonb, NOW(), NOW() FROM tenants t WHERE t.tenant_key = %s
            ON CONFLICT (tenant_id, invocation_id) DO UPDATE SET
                details=EXCLUDED.details, updated_at=NOW()
            RETURNING id
        """, (invocationId, _jsonb(value), tenantKey), 'setInvocation')
        if new_id is not None and isinstance(value, dict):
            value['id'] = new_id
        return value, new_id is not None

    def incrementRateLimit(self, action: str, window: str, limit: int, ttl_seconds: int) -> bool:
        rows = self.query("""
            INSERT INTO rate_limiter (action, time_window, used, expire_at)
            VALUES (%s, %s, 1, NOW() + %s * INTERVAL '1 second')
            ON CONFLICT (action, time_window) DO UPDATE
                SET used      = rate_limiter.used + 1,
                    expire_at = GREATEST(rate_limiter.expire_at, EXCLUDED.expire_at)
                WHERE rate_limiter.used < %s
            RETURNING used
        """, (action, window, ttl_seconds, limit))
        return bool(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_role_id(self, tenant_id: int, role_name: str) -> int | None:
        if not role_name or not tenant_id:
            return None
        row = self.queryone('SELECT id FROM roles WHERE tenant_id = %s AND role_name = %s', (tenant_id, role_name.replace('*', '')))
        return row[0] if row else None

    def _ensure_team(self, tournament_id: int, team_name: str) -> int | None:
        if not team_name:
            return None
        row = self.queryone('SELECT id FROM teams WHERE tournament_id = %s AND team_name = %s', (tournament_id, team_name))
        if row:
            return row[0]
        self._cur.execute(
            'INSERT INTO teams (tournament_id, team_name) VALUES (%s, %s) ON CONFLICT (tournament_id, team_name) DO NOTHING RETURNING id',
            (tournament_id, team_name),
        )
        row = self.fetchone()
        if row:
            return row[0]
        return self.queryone('SELECT id FROM teams WHERE tournament_id = %s AND team_name = %s', (tournament_id, team_name))[0]

    def _ensure_field(self, tenant_id: int, field_name: str) -> int | None:
        name = field_name or 'Unknown'
        row = self.queryone('SELECT id FROM fields WHERE tenant_id = %s AND field_name = %s', (tenant_id, name))
        if row:
            return row[0]
        self._cur.execute(
            "INSERT INTO fields (tenant_id, field_name, properties) VALUES (%s, %s, '{}'::jsonb) ON CONFLICT (tenant_id, field_name) DO NOTHING RETURNING id",
            (tenant_id, name),
        )
        row = self.fetchone()
        if row:
            return row[0]
        return self.queryone('SELECT id FROM fields WHERE tenant_id = %s AND field_name = %s', (tenant_id, name))[0]

    # ------------------------------------------------------------------
    # SSH tunnel
    # ------------------------------------------------------------------

    def _open_tunnel(self) -> subprocess.Popen | None:
        if not self._ssh_host:
            return None
        local_port = self._free_port()
        cmd = [
            'ssh', '-N',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'ExitOnForwardFailure=yes',
            '-i', self._ssh_key,
            '-L', f'{local_port}:{self._pg_host}:{self._pg_port}',
            f'{self._ssh_user}@{self._ssh_host}',
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.5)
            try:
                with socket.create_connection(('127.0.0.1', local_port), timeout=1):
                    break
            except OSError:
                pass
        else:
            proc.terminate()
            raise RuntimeError(f'SSH tunnel to {self._ssh_host} did not open within 10 s')
        proc._local_port = local_port  # type: ignore[attr-defined]
        self.logger.info(f'SSH tunnel opened {self._ssh_host} -> {self._pg_host}:{self._pg_port} (local port {local_port})')
        return proc

    def _tunnel_endpoint(self) -> tuple[str, int]:
        if self._tunnel:
            return '127.0.0.1', self._tunnel._local_port  # type: ignore[attr-defined]
        return self._pg_host, self._pg_port

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]
