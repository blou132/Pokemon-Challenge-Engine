"""Client fichier simulé ; ces tests ne prétendent pas lire une ROM réelle."""

import json
from pathlib import Path

import pytest

from app.services.bridge_service import BridgeService


class Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeLuaClient:
    """Reproduit publication atomique et conservation de deux instantanés."""

    def __init__(self, directory: Path, session_id: str) -> None:
        self.directory = directory
        self.session_id = session_id
        self.sequence = 0

    def send(self, **changes: object) -> Path:
        self.sequence += 1
        message = {
            "protocol_version": 1, "session_id": self.session_id, "sequence": self.sequence,
            "event": "heartbeat", "timestamp": 1_790_000_000, "emulator": "desmume",
            "script_version": "0.2.0", "game_id": "black", "game_code": "IRBF",
            "game_region": "FR", "rom_revision": 0, "capabilities": ["heartbeat", "game_identity"],
            "memory_profile": None, "party_size": None, "party": None, "error": None,
        } | changes
        path = self.directory / f"snapshot-{self.sequence}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")
        temporary.rename(path)
        older = self.directory / f"snapshot-{self.sequence - 2}.json"
        older.unlink(missing_ok=True)
        return path

    def party(self, **changes: object) -> Path:
        return self.send(**({
            "event": "party_update", "capabilities": ["game_identity", "party_size", "party_level", "party_hp"],
            "memory_profile": "fixture-only", "party_size": 1,
            "party": [{"slot": 1, "level": 12, "species_id": None, "hp": 20, "max_hp": 31}],
        } | changes))


@pytest.fixture
def connection(tmp_path: Path) -> tuple[BridgeService, FakeLuaClient, Clock]:
    clock = Clock()
    service = BridgeService(tmp_path / "sessions", clock=clock)
    assert service.start("black", "IRBF", 0).status == "waiting"
    return service, FakeLuaClient(service.session_dir, service.session_id), clock


def test_atomic_client_reaches_hello_heartbeat_and_party(connection) -> None:
    service, client, clock = connection
    client.send(event="hello")
    state = service.poll()
    assert state.status == "connected" and state.connected
    assert state.last_event == "hello"
    assert state.received_count == 1 and state.game_region == "FR"
    clock.advance(1)
    client.send()
    assert service.poll().received_count == 2
    clock.advance(1)
    client.party()
    state = service.poll()
    assert state.status == "receiving" and state.party_size == 1
    assert state.last_event == "party_update"
    assert state.party[0]["level"] == 12
    assert state.last_received_at == 12.0
    assert state.last_timestamp == 1_790_000_000
    assert len(list(service.session_dir.glob("snapshot-*.json"))) == 2


def test_lost_hello_is_not_required(connection) -> None:
    service, client, _ = connection
    client.send(event="hello")
    client.send()
    client.party()
    assert service.poll().status == "receiving"
    assert service.state.received_count == 1
    assert service.state.sequence == 3


def test_count_only_zero_is_receiving(connection) -> None:
    service, client, _ = connection
    client.send(party_size=0, memory_profile="fixture-only", capabilities=["game_identity", "party_size"])
    assert service.poll().status == "receiving"
    assert service.state.party_size == 0
    assert service.state.party is None


def test_timeout_clears_live_data_and_same_session_can_reconnect(connection) -> None:
    service, client, clock = connection
    client.party()
    assert service.poll().connected
    clock.advance(3)
    state = service.poll()
    assert state.status == "disconnected" and not state.connected
    assert state.party is None and state.party_size is None
    assert "connexion perdue" in state.last_error
    assert state.received_count == 1
    client.party()
    state = service.poll()
    assert state.status == "receiving" and state.received_count == 2
    assert state.last_error is None


def test_no_message_after_start_times_out(connection) -> None:
    service, _, clock = connection
    clock.advance(3)
    assert service.poll().status == "disconnected"
    assert service.state.last_received_at is None


def test_duplicate_and_older_snapshots_do_not_refresh_timeout(connection) -> None:
    service, client, clock = connection
    client.send()
    client.send()
    service.poll()
    clock.advance(2)
    assert service.poll().last_received_at == 10.0
    (service.session_dir / "snapshot-2.json").unlink()
    clock.advance(1)
    assert service.poll().status == "disconnected"
    assert service.state.received_count == 1
    assert service.state.sequence == 2


def test_stale_message_does_not_reactivate_after_timeout(connection) -> None:
    service, client, clock = connection
    client.party()
    service.poll()
    clock.advance(3)
    service.poll()
    assert service.poll().status == "disconnected"
    assert service.state.party is None


def test_stop_and_restart_isolate_sessions(connection) -> None:
    service, client, _ = connection
    client.party()
    service.poll()
    old_directory = service.session_dir
    old_id = service.session_id
    assert service.stop().status == "stopped"
    assert service.state.party is None and service.session_dir is None and service.session_id is None
    assert (old_directory / "stop").is_file()
    client.party()
    assert service.poll().status == "stopped"
    assert service.start("black").status == "waiting"
    assert service.session_id != old_id and service.session_dir != old_directory
    assert service.poll().status == "waiting"
    assert old_directory.exists()


def test_restart_requests_old_script_to_stop(connection) -> None:
    service, _, _ = connection
    old_directory = service.session_dir
    service.start("black2")
    assert (old_directory / "stop").is_file()
    assert not (service.session_dir / "stop").exists()


def test_stop_succeeds_when_marker_cannot_be_written(connection, monkeypatch) -> None:
    service, _, _ = connection

    def denied(*args, **kwargs):
        raise PermissionError("fixture verrouillée")

    monkeypatch.setattr(Path, "touch", denied)
    assert service.stop().status == "stopped"
    assert service.session_dir is None


@pytest.mark.parametrize("changes,detail", [
    ({"session_id": "f" * 32}, "autre session"),
    ({"game_id": "black2", "game_code": "IREF"}, "jeu reçu"),
    ({"game_code": "IRBE", "game_region": "EN"}, "code de ROM"),
    ({"rom_revision": 1}, "révision de ROM"),
])
def test_wrong_identity_is_rejected_and_does_not_keep_connection_alive(connection, changes, detail) -> None:
    service, client, clock = connection
    client.send(**changes)
    state = service.poll()
    assert state.status == "error" and detail in state.last_error
    assert state.received_count == 0 and state.last_received_at is None
    clock.advance(3)
    assert service.poll().status == "disconnected"
    client.send()
    assert service.poll().status == "connected"


def test_unknown_identity_connects_without_inventing_party(connection) -> None:
    service, client, _ = connection
    client.send(game_id=None, game_code=None, game_region=None, rom_revision=None)
    state = service.poll()
    assert state.connected and state.game_id is None and state.party_size is None


@pytest.mark.parametrize("event,status", [("emulator_closing", "disconnected"), ("bridge_error", "error")])
def test_closing_or_script_error_clears_party(connection, event, status) -> None:
    service, client, _ = connection
    client.party()
    service.poll()
    client.party(event=event, error="Lecture interrompue")
    state = service.poll()
    assert state.status == status and state.party_size is None and state.party is None
    assert state.last_error == "Lecture interrompue"


@pytest.mark.parametrize("payload", [b"{", b"\xff", b"x" * 65_537], ids=["incomplete", "utf8", "oversized"])
def test_corrupt_or_oversized_files_are_reported_without_crashing(connection, payload) -> None:
    service, client, clock = connection
    (service.session_dir / "snapshot-1.json").write_bytes(payload)
    state = service.poll()
    assert state.status == "error" and state.last_error
    assert state.last_received_at is None
    clock.advance(1)
    client.sequence = 1
    client.send()
    assert service.poll().connected


def test_temporary_file_is_ignored_until_atomic_publication(connection) -> None:
    service, client, _ = connection
    temporary = service.session_dir / "snapshot-1.tmp"
    temporary.write_text("{", encoding="utf-8")
    assert service.poll().status == "waiting"
    client.send()
    assert service.poll().connected


def test_filename_sequence_must_match_message(connection) -> None:
    service, client, _ = connection
    client.send(sequence=2)
    assert "numéro de séquence" in service.poll().last_error
    assert service.state.sequence == 0


def test_numeric_order_uses_newest_snapshot(connection) -> None:
    service, client, _ = connection
    client.sequence = 8
    client.send()
    client.send()
    assert service.poll().sequence == 10


def test_disappearing_directory_is_handled(connection) -> None:
    service, _, clock = connection
    service.session_dir.rmdir()
    assert service.poll().status == "waiting"
    clock.advance(3)
    assert service.poll().status == "disconnected"


def test_directory_enumeration_is_bounded(connection) -> None:
    service, _, _ = connection
    for index in range(513):
        (service.session_dir / f"extra-{index}.tmp").touch()
    assert "Trop de fichiers" in service.poll().last_error


def test_inaccessible_start_returns_useful_error(tmp_path: Path) -> None:
    root = tmp_path / "regular-file"
    root.write_text("fixture", encoding="utf-8")
    service = BridgeService(root)
    assert service.start("black").status == "error"
    assert "créer le dossier" in service.state.last_error
    assert service.session_dir is None and service.session_id is None


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), "3"])
def test_invalid_timeout_is_rejected(tmp_path: Path, timeout: object) -> None:
    with pytest.raises(ValueError):
        BridgeService(tmp_path, timeout_seconds=timeout)


@pytest.mark.parametrize("game,code,revision", [("white", None, None), ([], None, None), ("black", "invalid", None), ("black", "IRBF", True)])
def test_invalid_start_is_rejected(tmp_path: Path, game: object, code: object, revision: object) -> None:
    service = BridgeService(tmp_path)
    with pytest.raises(ValueError):
        service.start(game, code, revision)
    assert service.state.status == "stopped"
