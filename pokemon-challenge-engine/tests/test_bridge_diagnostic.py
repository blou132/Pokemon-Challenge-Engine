"""Diagnostic CLI avec producteur simulé ; aucune preuve d'exécution DeSmuME."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.bridge_service import BridgeService
from tools import bridge_diagnostic as diagnostic


class Scenario:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.now = 0.0
        self.bridge: BridgeService | None = None
        self.directory: Path | None = None
        self.rom_path = ""
        self.sequence = 0
        self.messages: list[tuple[float, dict]] = []

    def monotonic(self) -> float:
        return self.now

    def create_bridge(self, root: Path) -> BridgeService:
        assert root == self.base_dir / "runtime" / "bridge"
        self.bridge = BridgeService(root, clock=self.monotonic)
        return self.bridge

    def prepare(self, base_dir: Path, bridge: BridgeService, game: str, rom_path: str) -> Path:
        assert base_dir == self.base_dir
        self.rom_path = rom_path
        bridge.start(game)
        self.directory = bridge.session_dir
        return base_dir / "lua" / "script avec espaces.lua"

    def sleep(self, delay: float) -> None:
        self.now += delay
        while self.messages and self.messages[0][0] <= self.now:
            _, changes = self.messages.pop(0)
            self.sequence += 1
            message = {
                "protocol_version": 1, "session_id": self.bridge.session_id, "sequence": self.sequence,
                "event": "heartbeat", "timestamp": 1_790_000_000, "emulator": "desmume",
                "script_version": "0.2.0", "game_id": "black2", "game_code": "IREF", "game_region": "FR",
                "rom_revision": 0, "capabilities": ["heartbeat", "game_identity"], "memory_profile": None,
                "party_size": None, "party": None, "error": None,
            } | changes
            temporary = self.directory / f"snapshot-{self.sequence}.tmp"
            temporary.write_text(json.dumps(message), encoding="utf-8")
            temporary.rename(self.directory / f"snapshot-{self.sequence}.json")

    def args(self, duration: float = 0.8) -> list[str]:
        return ["--game", "black2", "--base-dir", str(self.base_dir), "--duration", str(duration), "--json"]


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch) -> Scenario:
    scenario = Scenario(tmp_path)
    monkeypatch.setattr(diagnostic, "BridgeService", scenario.create_bridge)
    monkeypatch.setattr(diagnostic, "_prepare", scenario.prepare)
    monkeypatch.setattr(diagnostic, "time", SimpleNamespace(monotonic=scenario.monotonic, sleep=scenario.sleep))
    return scenario


def output_events(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_without_producer_cli_fails_and_stops_session(scenario, capsys) -> None:
    assert diagnostic.main(scenario.args()) == 1
    events = output_events(capsys)
    assert events[0]["lua_path"] == str((scenario.base_dir / "lua" / "script avec espaces.lua").resolve())
    assert events[-1]["result"] == "no_heartbeat" and events[-1]["received_messages"] == 0
    assert events[-1]["success"] is False
    assert scenario.bridge.state.status == "stopped"
    assert (scenario.directory / "stop").exists()


def test_cli_reports_received_heartbeats_identity_and_frequency(scenario, capsys) -> None:
    scenario.messages = [(0.2, {"event": "hello"}), (0.4, {}), (0.6, {})]
    rom = str(scenario.base_dir / "ROM personnelle.nds")
    assert diagnostic.main(scenario.args() + ["--rom", rom]) == 0
    assert scenario.rom_path == rom
    summary = output_events(capsys)[-1]
    assert summary["success"] is True and summary["received_messages"] == 3
    assert summary["heartbeat_messages"] == 2 and summary["reception_hz"] == 5.0
    assert summary["state"]["game_code"] == "IREF"
    assert summary["state"]["rom_revision"] == 0
    assert summary["state"]["memory_profile"] is None
    assert summary["state"]["party_size"] is None


def test_hello_or_party_without_heartbeat_cannot_succeed(scenario, capsys) -> None:
    scenario.messages = [(0.2, {"event": "hello"}), (0.4, {"event": "party_update"})]
    assert diagnostic.main(scenario.args()) == 1
    summary = output_events(capsys)[-1]
    assert summary["received_messages"] == 2 and summary["heartbeat_messages"] == 0
    assert summary["result"] == "no_heartbeat"


def test_one_heartbeat_is_insufficient(scenario, capsys) -> None:
    scenario.messages = [(0.2, {})]
    assert diagnostic.main(scenario.args()) == 1
    assert output_events(capsys)[-1]["result"] == "insufficient_messages"


def test_disconnected_at_end_cannot_succeed(scenario, capsys) -> None:
    scenario.messages = [(0.2, {"event": "hello"}), (0.4, {})]
    assert diagnostic.main(scenario.args(4)) == 1
    summary = output_events(capsys)[-1]
    assert summary["result"] == "disconnected" and summary["state"]["status"] == "disconnected"


def test_rejected_heartbeat_does_not_count(scenario, capsys) -> None:
    scenario.messages = [(0.2, {"event": "hello"}), (0.4, {"session_id": "f" * 32})]
    assert diagnostic.main(scenario.args()) == 1
    summary = output_events(capsys)[-1]
    assert summary["heartbeat_messages"] == 0 and summary["received_messages"] == 1
    assert "autre session" in summary["state"]["last_error"]


def test_preparation_failure_has_distinct_exit_code(scenario, monkeypatch, capsys) -> None:
    def failing_prepare(*args, **kwargs):
        scenario.prepare(*args, **kwargs)
        raise ValueError("ROM invalide dans la fixture")

    monkeypatch.setattr(diagnostic, "_prepare", failing_prepare)
    assert diagnostic.main(scenario.args()) == 2
    assert output_events(capsys)[-1]["event"] == "error"
    assert (scenario.directory / "stop").exists()


def test_interruption_stops_the_script(scenario, monkeypatch, capsys) -> None:
    def interrupt(delay: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(diagnostic.time, "sleep", interrupt)
    assert diagnostic.main(scenario.args()) == 130
    assert output_events(capsys)[-1]["event"] == "error"
    assert (scenario.directory / "stop").exists()


def test_human_output_includes_exact_script_and_unknown_values(scenario, capsys) -> None:
    args = scenario.args()
    args.remove("--json")
    assert diagnostic.main(args) == 1
    output = capsys.readouterr().out
    assert str(scenario.base_dir / "lua" / "script avec espaces.lua") in output
    assert "En attente" in output and "équipe : non disponible" in output
    assert "aucun heartbeat" in output


@pytest.mark.parametrize("duration", ["0", "-1", "nan", "inf", "invalide"])
def test_invalid_duration_is_rejected_before_preparation(duration: str) -> None:
    with pytest.raises(SystemExit) as exc:
        diagnostic.main(["--game", "black", "--duration", duration])
    assert exc.value.code == 2


def test_help_does_not_prepare_a_session(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        diagnostic.main(["--help"])
    assert exc.value.code == 0
    assert "--duration" in capsys.readouterr().out
