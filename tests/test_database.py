from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from hackex2.database import (
    DatabaseError,
    SCHEMA_VERSION,
    TargetDatabase,
    TargetEventType,
)
from hackex2.adb.ui import Bounds
from hackex2.processes import ProcessCard, ProcessState
from hackex2.target_dashboard import TargetDashboard


def dashboard(
    *, username: str = "target-one", level: int = 4
) -> TargetDashboard:
    return TargetDashboard(
        username=username,
        crew_tag="TEST",
        level=level,
        reputation=1200,
        score=3400,
        xp_current=200,
        xp_required=500,
        xp_percent=40,
        ip_address="93.140.117.125",
        device="Raider",
        network="Cable",
        firewall_level=2,
        encryptor_level=2,
        available_actions=("DISCONNECT", "WALLET", "LOG"),
    )


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self.values = iter(values)

    def __call__(self) -> datetime:
        return next(self.values)


class TargetDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name, "state.sqlite3")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_initializes_versioned_schema(self) -> None:
        database = TargetDatabase(self.path)

        database.initialize()

        version, targets, events = database.status()
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual((targets, events), (0, 0))

    def test_observes_and_updates_target_without_losing_first_seen_or_tags(self) -> None:
        first = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
        second = datetime(2026, 8, 21, 11, 30, tzinfo=timezone.utc)
        database = TargetDatabase(self.path, clock=SequenceClock(first, second))

        created = database.observe_dashboard(dashboard(), game_tags=("rich",))
        updated = database.observe_dashboard(
            dashboard(username="renamed", level=5), game_tags=("priority", "rich")
        )

        self.assertEqual(updated.id, created.id)
        self.assertEqual(updated.first_seen, created.first_seen)
        self.assertNotEqual(updated.last_seen, created.last_seen)
        self.assertEqual(updated.username, "renamed")
        self.assertEqual(updated.level, 5)
        self.assertEqual(updated.game_tags, ("rich", "priority"))
        history = database.list_history(updated.ip_address)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, TargetEventType.TARGET_DISCOVERED)

    def test_records_wallet_crypto_log_and_hack_history(self) -> None:
        values = tuple(
            datetime(2026, 8, 20, 10, minute, tzinfo=timezone.utc)
            for minute in range(5)
        )
        database = TargetDatabase(self.path, clock=SequenceClock(*values))
        database.observe_dashboard(dashboard())

        database.record_hack_verified("93.140.117.125")
        database.record_wallet_observation(
            "93.140.117.125",
            password_known=True,
            protected=False,
            variant="TRANSFERABLE",
        )
        database.record_crypto_transferred("93.140.117.125", 174)
        database.record_log_observation(
            "93.140.117.125", protected=False, cleared=True
        )

        target = database.get_target("93.140.117.125")
        assert target is not None
        self.assertTrue(target.wallet_password_known)
        self.assertFalse(target.wallet_protected)
        self.assertFalse(target.log_protected)
        self.assertEqual(target.max_crypto_transferred, 174)
        self.assertEqual(target.last_crypto_transferred, 174)
        self.assertEqual(target.total_crypto_transferred, 174)
        self.assertEqual(target.crypto_transfer_count, 1)
        events = tuple(
            event.event_type for event in database.list_history(target.ip_address)
        )
        self.assertEqual(
            events,
            (
                TargetEventType.TARGET_DISCOVERED,
                TargetEventType.HACK_VERIFIED,
                TargetEventType.WALLET_ACCESSED,
                TargetEventType.CRYPTO_TRANSFERRED,
                TargetEventType.LOG_CLEARED,
            ),
        )

    def test_observes_minimal_target_from_process_card(self) -> None:
        database = TargetDatabase(
            self.path,
            clock=lambda: datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
        )
        process = ProcessCard(
            process_id="2055613",
            name="Password Crack",
            level=4,
            state=ProcessState.COMPLETED,
            progress_percent=None,
            completion_text="Completed now",
            ip_address="85.83.90.194",
            success_chance_percent=66,
            game_tags=("rich",),
            system_markers=(),
            available_actions=("OPEN_TARGET", "HACK"),
            bounds=Bounds(45, 452, 1035, 798),
        )

        target = database.observe_process_target(process)

        self.assertEqual(target.ip_address, "85.83.90.194")
        self.assertEqual(target.ip_pattern, "85.83.90.194")
        self.assertEqual(target.known_ip_octets, 4)
        self.assertIsNone(target.username)
        self.assertEqual(target.game_tags, ("rich",))
        self.assertEqual(
            database.list_history(target.ip_address)[0].metadata["process_id"],
            "2055613",
        )

    def test_stores_masked_address_parts_with_distinguishable_identity(self) -> None:
        database = TargetDatabase(
            self.path,
            clock=lambda: datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
        )
        masked = dashboard(username="Subcero99")
        masked = TargetDashboard(
            **{
                **masked.__dict__,
                "ip_address": "255.173.xxx.xxx",
                "displayed_ip_address": "255.173.xxx.xxx",
            }
        )

        target = database.observe_dashboard(masked)

        self.assertIsNone(target.ip_address)
        self.assertEqual(target.ip_pattern, "255.173.*.*")
        self.assertEqual(target.known_ip_octets, 2)
        self.assertEqual(
            target.identity_key,
            "masked:255.173.*.*|username:subcero99",
        )

    def test_rejects_unknown_future_schema(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA user_version = 99")

        with self.assertRaisesRegex(DatabaseError, "newer than supported"):
            TargetDatabase(self.path).initialize()

    def test_requires_observation_before_event(self) -> None:
        with self.assertRaisesRegex(DatabaseError, "must be observed"):
            TargetDatabase(self.path).record_event(
                "93.140.117.125", TargetEventType.DISCONNECTED
            )


if __name__ == "__main__":
    unittest.main()
