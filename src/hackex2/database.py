"""Small, migration-backed SQLite store for observed HackEx2 target state."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from ipaddress import AddressValueError, IPv4Address
from pathlib import Path

from hackex2.processes import ProcessCard
from hackex2.target_dashboard import TargetDashboard


SCHEMA_VERSION = 1
DEFAULT_DATABASE_PATH = Path("data/hackex2.sqlite3")


class DatabaseError(RuntimeError):
    """Raised when stored data or a schema version cannot be handled safely."""


class TargetEventType(str, Enum):
    TARGET_DISCOVERED = "TARGET_DISCOVERED"
    HACK_ATTEMPTED = "HACK_ATTEMPTED"
    HACK_RETURNED_HOME = "HACK_RETURNED_HOME"
    HACK_VERIFIED = "HACK_VERIFIED"
    WALLET_ACCESSED = "WALLET_ACCESSED"
    WALLET_PASSWORD_REQUIRED = "WALLET_PASSWORD_REQUIRED"
    PASSWORD_CRACK_REQUESTED = "PASSWORD_CRACK_REQUESTED"
    WALLET_PROTECTED = "WALLET_PROTECTED"
    CRYPTO_TRANSFERRED = "CRYPTO_TRANSFERRED"
    LOG_CLEARED = "LOG_CLEARED"
    LOG_PROTECTED = "LOG_PROTECTED"
    DISCONNECTED = "DISCONNECTED"


@dataclass(frozen=True)
class TargetRecord:
    id: int
    identity_key: str
    ip_address: str | None
    ip_pattern: str
    known_ip_octets: int
    username: str | None
    crew_tag: str | None
    level: int | None
    reputation: int | None
    score: int | None
    device: str | None
    network: str | None
    firewall_level: int | None
    encryptor_level: int | None
    first_seen: str
    last_seen: str
    wallet_password_known: bool | None
    wallet_password_last_verified: str | None
    wallet_protected: bool | None
    log_protected: bool | None
    max_crypto_transferred: int
    last_crypto_transferred: int | None
    total_crypto_transferred: int
    crypto_transfer_count: int
    last_hacked_at: str | None
    last_wallet_checked_at: str | None
    game_tags: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True)
class TargetHistoryRecord:
    id: int
    target_id: int
    timestamp: str
    event_type: TargetEventType
    value: str | None
    metadata: Mapping[str, object]


class TargetDatabase:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path or os.getenv("HACKEX2_DB_PATH") or DEFAULT_DATABASE_PATH)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise DatabaseError(
                    f"database schema {version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )
            if version == 0:
                self._migrate_to_v1(connection)

    def status(self) -> tuple[int, int, int]:
        self.initialize()
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            targets = int(connection.execute("SELECT COUNT(*) FROM targets").fetchone()[0])
            events = int(
                connection.execute("SELECT COUNT(*) FROM target_history").fetchone()[0]
            )
        return version, targets, events

    def observe_dashboard(
        self,
        dashboard: TargetDashboard,
        *,
        game_tags: Sequence[str] = (),
    ) -> TargetRecord:
        self.initialize()
        address = _address_identity(
            dashboard.ip_address,
            dashboard.displayed_ip_address,
            dashboard.username,
        )
        tags = _normalize_tags(game_tags)
        now = self._timestamp()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, game_tags_json FROM targets WHERE identity_key = ?",
                (address.identity_key,),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO targets (
                        identity_key, ip_address, ip_pattern, known_ip_octets,
                        username, crew_tag, level, reputation, score,
                        device, network, firewall_level, encryptor_level,
                        first_seen, last_seen, game_tags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        address.identity_key,
                        address.full_ip_address,
                        address.pattern,
                        address.known_octets,
                        dashboard.username,
                        dashboard.crew_tag,
                        dashboard.level,
                        dashboard.reputation,
                        dashboard.score,
                        dashboard.device,
                        dashboard.network,
                        dashboard.firewall_level,
                        dashboard.encryptor_level,
                        now,
                        now,
                        _encode_tags(tags),
                    ),
                )
                target_id = int(cursor.lastrowid)
                self._insert_event(
                    connection,
                    target_id,
                    TargetEventType.TARGET_DISCOVERED,
                    now,
                    metadata={"username": dashboard.username},
                )
            else:
                target_id = int(existing["id"])
                stored_tags = _decode_tags(existing["game_tags_json"])
                merged_tags = _normalize_tags((*stored_tags, *tags))
                connection.execute(
                    """
                    UPDATE targets
                    SET ip_address = ?, ip_pattern = ?, known_ip_octets = ?,
                        username = ?, crew_tag = ?, level = ?, reputation = ?,
                        score = ?, device = ?, network = ?, firewall_level = ?,
                        encryptor_level = ?, last_seen = ?, game_tags_json = ?
                    WHERE id = ?
                    """,
                    (
                        address.full_ip_address,
                        address.pattern,
                        address.known_octets,
                        dashboard.username,
                        dashboard.crew_tag,
                        dashboard.level,
                        dashboard.reputation,
                        dashboard.score,
                        dashboard.device,
                        dashboard.network,
                        dashboard.firewall_level,
                        dashboard.encryptor_level,
                        now,
                        _encode_tags(merged_tags),
                        target_id,
                    ),
                )
        record = self.get_target_by_identity(address.identity_key)
        if record is None:
            raise DatabaseError("target disappeared immediately after dashboard update")
        return record

    def observe_process_target(self, process: ProcessCard) -> TargetRecord:
        """Persist the reliable target fields exposed by one process card."""

        if process.ip_address is None:
            raise DatabaseError(
                f"process {process.process_id} has no observable target IP"
            )
        self.initialize()
        _validate_ip(process.ip_address)
        identity_key = f"ip:{process.ip_address}"
        tags = _normalize_tags(process.game_tags)
        now = self._timestamp()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, game_tags_json FROM targets WHERE identity_key = ?",
                (identity_key,),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO targets (
                        identity_key, ip_address, ip_pattern, known_ip_octets,
                        first_seen, last_seen, game_tags_json
                    ) VALUES (?, ?, ?, 4, ?, ?, ?)
                    """,
                    (
                        identity_key,
                        process.ip_address,
                        process.ip_address,
                        now,
                        now,
                        _encode_tags(tags),
                    ),
                )
                target_id = int(cursor.lastrowid)
                self._insert_event(
                    connection,
                    target_id,
                    TargetEventType.TARGET_DISCOVERED,
                    now,
                    metadata={
                        "process_id": process.process_id,
                        "process_type": process.name,
                    },
                )
            else:
                target_id = int(existing["id"])
                stored_tags = _decode_tags(existing["game_tags_json"])
                merged_tags = _normalize_tags((*stored_tags, *tags))
                connection.execute(
                    """
                    UPDATE targets
                    SET last_seen = ?, game_tags_json = ?
                    WHERE id = ?
                    """,
                    (now, _encode_tags(merged_tags), target_id),
                )
        record = self.get_target(process.ip_address)
        if record is None:
            raise DatabaseError("target disappeared immediately after process update")
        return record

    def get_target(self, ip_address: str) -> TargetRecord | None:
        self.initialize()
        _validate_ip(ip_address)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM targets WHERE ip_address = ?", (ip_address,)
            ).fetchone()
        return _target_from_row(row) if row is not None else None

    def get_target_by_identity(self, identity_key: str) -> TargetRecord | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM targets WHERE identity_key = ?", (identity_key,)
            ).fetchone()
        return _target_from_row(row) if row is not None else None

    def list_history(self, ip_address: str) -> tuple[TargetHistoryRecord, ...]:
        target = self.get_target(ip_address)
        if target is None:
            return ()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM target_history
                WHERE target_id = ?
                ORDER BY id
                """,
                (target.id,),
            ).fetchall()
        return tuple(_history_from_row(row) for row in rows)

    def record_event(
        self,
        ip_address: str,
        event_type: TargetEventType,
        *,
        value: str | int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> TargetHistoryRecord:
        target = self._require_target(ip_address)
        timestamp = self._timestamp()
        with self._connect() as connection:
            event_id = self._insert_event(
                connection,
                target.id,
                event_type,
                timestamp,
                value=value,
                metadata=metadata,
            )
            row = connection.execute(
                "SELECT * FROM target_history WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise DatabaseError("history event disappeared immediately after insert")
        return _history_from_row(row)

    def record_hack_verified(self, ip_address: str) -> None:
        target = self._require_target(ip_address)
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "UPDATE targets SET last_hacked_at = ? WHERE id = ?",
                (now, target.id),
            )
            self._insert_event(
                connection, target.id, TargetEventType.HACK_VERIFIED, now
            )

    def record_wallet_observation(
        self,
        ip_address: str,
        *,
        password_known: bool | None,
        protected: bool | None,
        variant: str,
    ) -> None:
        target = self._require_target(ip_address)
        now = self._timestamp()
        password_verified = now if password_known is True else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE targets
                SET wallet_password_known = ?,
                    wallet_password_last_verified = CASE
                        WHEN ? IS NOT NULL THEN ?
                        ELSE wallet_password_last_verified
                    END,
                    wallet_protected = ?,
                    last_wallet_checked_at = ?
                WHERE id = ?
                """,
                (
                    _optional_bool(password_known),
                    password_verified,
                    password_verified,
                    _optional_bool(protected),
                    now,
                    target.id,
                ),
            )
            self._insert_event(
                connection,
                target.id,
                TargetEventType.WALLET_ACCESSED,
                now,
                metadata={"variant": variant},
            )
            if variant == "PASSWORD_REQUIRED":
                self._insert_event(
                    connection,
                    target.id,
                    TargetEventType.WALLET_PASSWORD_REQUIRED,
                    now,
                )
            if protected is True:
                self._insert_event(
                    connection,
                    target.id,
                    TargetEventType.WALLET_PROTECTED,
                    now,
                )

    def record_crypto_transferred(self, ip_address: str, amount: int) -> None:
        if amount < 0:
            raise DatabaseError("transferred Crypto amount cannot be negative")
        target = self._require_target(ip_address)
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE targets
                SET max_crypto_transferred = MAX(max_crypto_transferred, ?),
                    last_crypto_transferred = ?,
                    total_crypto_transferred = total_crypto_transferred + ?,
                    crypto_transfer_count = crypto_transfer_count + 1,
                    last_wallet_checked_at = ?
                WHERE id = ?
                """,
                (amount, amount, amount, now, target.id),
            )
            self._insert_event(
                connection,
                target.id,
                TargetEventType.CRYPTO_TRANSFERRED,
                now,
                value=amount,
            )

    def record_log_observation(
        self,
        ip_address: str,
        *,
        protected: bool,
        cleared: bool,
    ) -> None:
        target = self._require_target(ip_address)
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "UPDATE targets SET log_protected = ? WHERE id = ?",
                (_optional_bool(protected), target.id),
            )
            if protected:
                event = TargetEventType.LOG_PROTECTED
            elif cleared:
                event = TargetEventType.LOG_CLEARED
            else:
                return
            self._insert_event(connection, target.id, event, now)

    def _require_target(self, ip_address: str) -> TargetRecord:
        target = self.get_target(ip_address)
        if target is None:
            raise DatabaseError(
                f"target {ip_address} must be observed before recording events"
            )
        return target

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _timestamp(self) -> str:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise DatabaseError("database clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _migrate_to_v1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE targets (
                id INTEGER PRIMARY KEY,
                identity_key TEXT NOT NULL UNIQUE,
                ip_address TEXT UNIQUE,
                ip_pattern TEXT NOT NULL,
                known_ip_octets INTEGER NOT NULL CHECK (
                    known_ip_octets BETWEEN 1 AND 4
                ),
                username TEXT,
                crew_tag TEXT,
                level INTEGER,
                reputation INTEGER,
                score INTEGER,
                device TEXT,
                network TEXT,
                firewall_level INTEGER,
                encryptor_level INTEGER,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                wallet_password_known INTEGER CHECK (
                    wallet_password_known IN (0, 1) OR wallet_password_known IS NULL
                ),
                wallet_password_last_verified TEXT,
                wallet_protected INTEGER CHECK (
                    wallet_protected IN (0, 1) OR wallet_protected IS NULL
                ),
                log_protected INTEGER CHECK (
                    log_protected IN (0, 1) OR log_protected IS NULL
                ),
                max_crypto_transferred INTEGER NOT NULL DEFAULT 0,
                last_crypto_transferred INTEGER,
                total_crypto_transferred INTEGER NOT NULL DEFAULT 0,
                crypto_transfer_count INTEGER NOT NULL DEFAULT 0,
                last_hacked_at TEXT,
                last_wallet_checked_at TEXT,
                game_tags_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT
            );

            CREATE TABLE target_history (
                id INTEGER PRIMARY KEY,
                target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                value TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX target_history_target_time
                ON target_history(target_id, timestamp);

            PRAGMA user_version = 1;
            """
        )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        target_id: int,
        event_type: TargetEventType,
        timestamp: str,
        *,
        value: str | int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> int:
        try:
            metadata_json = json.dumps(
                dict(metadata or {}), sort_keys=True, separators=(",", ":")
            )
        except (TypeError, ValueError) as exc:
            raise DatabaseError("event metadata must be JSON serializable") from exc
        cursor = connection.execute(
            """
            INSERT INTO target_history (
                target_id, timestamp, event_type, value, metadata_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                target_id,
                timestamp,
                event_type.value,
                None if value is None else str(value),
                metadata_json,
            ),
        )
        return int(cursor.lastrowid)


def _target_from_row(row: sqlite3.Row) -> TargetRecord:
    return TargetRecord(
        id=int(row["id"]),
        identity_key=str(row["identity_key"]),
        ip_address=row["ip_address"],
        ip_pattern=str(row["ip_pattern"]),
        known_ip_octets=int(row["known_ip_octets"]),
        username=row["username"],
        crew_tag=row["crew_tag"],
        level=row["level"],
        reputation=row["reputation"],
        score=row["score"],
        device=row["device"],
        network=row["network"],
        firewall_level=row["firewall_level"],
        encryptor_level=row["encryptor_level"],
        first_seen=str(row["first_seen"]),
        last_seen=str(row["last_seen"]),
        wallet_password_known=_row_optional_bool(row["wallet_password_known"]),
        wallet_password_last_verified=row["wallet_password_last_verified"],
        wallet_protected=_row_optional_bool(row["wallet_protected"]),
        log_protected=_row_optional_bool(row["log_protected"]),
        max_crypto_transferred=int(row["max_crypto_transferred"]),
        last_crypto_transferred=row["last_crypto_transferred"],
        total_crypto_transferred=int(row["total_crypto_transferred"]),
        crypto_transfer_count=int(row["crypto_transfer_count"]),
        last_hacked_at=row["last_hacked_at"],
        last_wallet_checked_at=row["last_wallet_checked_at"],
        game_tags=_decode_tags(row["game_tags_json"]),
        notes=row["notes"],
    )


def _history_from_row(row: sqlite3.Row) -> TargetHistoryRecord:
    try:
        event_type = TargetEventType(str(row["event_type"]))
        metadata = json.loads(str(row["metadata_json"]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise DatabaseError("stored target history is invalid") from exc
    if not isinstance(metadata, dict):
        raise DatabaseError("stored target history metadata is not an object")
    return TargetHistoryRecord(
        id=int(row["id"]),
        target_id=int(row["target_id"]),
        timestamp=str(row["timestamp"]),
        event_type=event_type,
        value=row["value"],
        metadata=metadata,
    )


def _validate_ip(ip_address: str) -> None:
    try:
        IPv4Address(ip_address)
    except AddressValueError as exc:
        raise DatabaseError(f"invalid target IPv4 address: {ip_address!r}") from exc


@dataclass(frozen=True)
class _AddressIdentity:
    identity_key: str
    full_ip_address: str | None
    pattern: str
    known_octets: int


_MASKED_ADDRESS = re.compile(
    r"(\d{1,3}|xxx)\.(\d{1,3}|xxx)\.(\d{1,3}|xxx)\.(\d{1,3}|xxx)"
)


def _address_identity(
    resolved_or_displayed: str,
    displayed: str | None,
    username: str,
) -> _AddressIdentity:
    try:
        full_ip = str(IPv4Address(resolved_or_displayed))
    except AddressValueError:
        full_ip = None

    visible = displayed or resolved_or_displayed
    match = _MASKED_ADDRESS.fullmatch(visible)
    if match is None:
        raise DatabaseError(f"invalid observed target address: {visible!r}")
    parts = match.groups()
    known_parts: list[str] = []
    masked_started = False
    for part in parts:
        if part == "xxx":
            masked_started = True
            known_parts.append("*")
            continue
        if masked_started:
            raise DatabaseError(
                f"non-contiguous known target address parts: {visible!r}"
            )
        if int(part) > 255:
            raise DatabaseError(f"invalid target address octet: {visible!r}")
        known_parts.append(str(int(part)))
    known_octets = sum(part != "xxx" for part in parts)
    pattern = ".".join(known_parts)
    if full_ip is not None:
        return _AddressIdentity(f"ip:{full_ip}", full_ip, pattern, known_octets)
    normalized_username = username.strip().casefold()
    if not normalized_username:
        raise DatabaseError("masked target address requires a visible username")
    return _AddressIdentity(
        f"masked:{pattern}|username:{normalized_username}",
        None,
        pattern,
        known_octets,
    )


def _normalize_tags(tags: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    if any(len(tag) > 80 for tag in normalized):
        raise DatabaseError("game tag is longer than 80 characters")
    return normalized


def _encode_tags(tags: Sequence[str]) -> str:
    return json.dumps(list(tags), ensure_ascii=False, separators=(",", ":"))


def _decode_tags(value: str) -> tuple[str, ...]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DatabaseError("stored target game tags are invalid JSON") from exc
    if not isinstance(decoded, list) or not all(
        isinstance(tag, str) for tag in decoded
    ):
        raise DatabaseError("stored target game tags are not a string list")
    return tuple(decoded)


def _optional_bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _row_optional_bool(value: object) -> bool | None:
    return None if value is None else bool(value)
