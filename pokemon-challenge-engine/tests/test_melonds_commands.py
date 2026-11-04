"""Command transport regressions. Synthetic files/process, no game or user save."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_run_integration import qt_app

from app.services.config_service import AppConfig
from app.services.game_mode_service import GameModeService, RunState
from app.services.melonds_commands import CAPABILITIES, MelonDSCommands


@pytest.fixture
def commands(tmp_path):
    rom = tmp_path / "test.nds"
    rom.write_bytes(b"synthetic cartridge")
    states = tmp_path / "states"
    states.mkdir()
    client = MelonDSCommands({"PCE_BRIDGE_DIR": str(tmp_path), "PCE_BRIDGE_SESSION": "a" * 32},
                             SimpleNamespace(pid=42, poll=lambda: None), str(rom), str(states), clock=lambda: 100)
    publish(client)
    return client


def publish(client, **changes):
    document = dict(version=1, session_id=client.session, instance_id="b" * 32, pid=42,
                    timestamp_ms=100000, available=True, rom_sha256=client.rom_hash,
                    state_directory=str(client.states), capabilities=sorted(CAPABILITIES), keyboard={"A": 88})
    document.update(changes)
    (client.directory / "melonds-controls.json").write_text(json.dumps(document))


def acknowledge(client, **changes):
    document = dict(version=1, session_id=client.session, instance_id=client.instance, pid=42,
                    timestamp_ms=100001, sequence=client.pending["sequence"], command=client.pending["command"],
                    ok=True, error=None, speed="x2")
    document.update(changes)
    (client.directory / "melonds-command-result.json").write_text(json.dumps(document))


def test_speed_is_pending_until_matching_native_result(commands):
    assert commands.refresh()["keyboard"] == {"A": 88}
    request = commands.request("speed", {"value": "x2"})
    assert commands.poll_result() is None
    assert request["expires_ms"] == 105000 and request["pid"] == 42
    assert json.loads((commands.directory / "melonds-command.json").read_text()) == request
    with pytest.raises(ValueError, match="attente"):
        commands.request("speed", {"value": "x4"})
    acknowledge(commands)
    assert commands.poll_result()["speed"] == "x2"
    assert commands.pending is None
    second = commands.request("speed", {"value": "x4"})
    assert second["sequence"] == 2
    assert commands.poll_result() is None  # Old ACK is not accepted for the next command.


def test_transient_native_replacement_lock_is_read_again(commands, monkeypatch):
    original_open = Path.open
    attempts = []

    def briefly_locked(path, *args, **kwargs):
        if path.name == "melonds-controls.json":
            attempts.append(path)
            if len(attempts) < 3:
                raise PermissionError("native atomic replacement in progress")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", briefly_locked)
    assert commands.refresh()["available"] is True
    assert len(attempts) == 3
    assert commands.sequence == 0


def test_persistent_native_read_lock_remains_bounded(commands, monkeypatch):
    attempts = []

    def locked(path, *args, **kwargs):
        attempts.append(path)
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "open", locked)
    with pytest.raises(PermissionError):
        commands.refresh()
    assert len(attempts) == 3
    assert commands.sequence == 0


def test_retrying_acknowledgement_read_never_resends_action(commands, monkeypatch):
    request = commands.request("speed", {"value": "x2"})
    acknowledge(commands)
    original_open = Path.open
    attempts = []

    def briefly_locked(path, *args, **kwargs):
        if path.name == "melonds-command-result.json":
            attempts.append(path)
            if len(attempts) == 1:
                raise PermissionError("native replacement in progress")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", briefly_locked)
    assert commands.poll_result()["speed"] == "x2"
    assert len(attempts) == 2
    assert commands.pending is None
    assert commands.sequence == request["sequence"] == 1
    assert json.loads((commands.directory / "melonds-command.json").read_text()) == request


def test_transient_command_publish_lock_keeps_one_sequence(commands, monkeypatch):
    original_replace = Path.replace
    attempts = []

    def briefly_locked(path, target):
        attempts.append(json.loads(path.read_text()))
        if len(attempts) < 3:
            raise PermissionError("native reader holds previous command")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", briefly_locked)
    request = commands.request("save_state", {"slot": 1})
    assert attempts == [request] * 3
    assert commands.sequence == 1 and commands.pending == request
    assert json.loads((commands.directory / "melonds-command.json").read_text()) == request
    assert not (commands.directory / "melonds-command.json.tmp").exists()


def test_failed_command_publish_keeps_previous_file_and_allows_later_request(commands, monkeypatch):
    target = commands.directory / "melonds-command.json"
    target.write_text("previous command")
    original_replace = Path.replace
    attempts = []

    def locked(path, destination):
        attempts.append(path)
        raise PermissionError("native reader holds previous command")

    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(PermissionError):
        commands.request("save_state", {"slot": 1})
    assert len(attempts) == 3
    assert target.read_text() == "previous command"
    assert commands.pending is None
    assert not (commands.directory / "melonds-command.json.tmp").exists()
    monkeypatch.setattr(Path, "replace", original_replace)
    request = commands.request("speed", {"value": "x2"})
    assert request["sequence"] == 2
    assert json.loads(target.read_text()) == request


def test_preexisting_command_temporary_is_never_deleted(commands):
    temporary = commands.directory / "melonds-command.json.tmp"
    temporary.write_text("not created by this request")
    with pytest.raises(FileExistsError):
        commands.request("save_state", {"slot": 1})
    assert temporary.read_text() == "not created by this request"
    assert commands.pending is None
    assert not (commands.directory / "melonds-command.json").exists()


@pytest.mark.parametrize("change", [dict(pid=43), dict(session_id="c" * 32), dict(rom_sha256="0" * 64),
                                    dict(state_directory="missing"), dict(version=True), dict(timestamp_ms="bad"),
                                    dict(capabilities=["write_ram"]), dict(instance_id="../other")])
def test_identity_and_capability_mismatch_never_writes_command(commands, change):
    publish(commands, **change)
    with pytest.raises(ValueError):
        commands.request("speed", {"value": "x2"})
    assert not (commands.directory / "melonds-command.json").exists()


@pytest.mark.parametrize("change", [dict(timestamp_ms=90000), dict(available=False)])
def test_stale_or_changed_cart_disables_commands(commands, change):
    publish(commands, **change)
    assert commands.refresh() is None
    with pytest.raises(ValueError, match="indisponibles"):
        commands.request("speed", {"value": "x2"})


def test_instance_nonce_cannot_change_after_attachment(commands):
    commands.refresh()
    publish(commands, instance_id="c" * 32)
    with pytest.raises(ValueError, match="instance"):
        commands.refresh()


@pytest.mark.parametrize("command,args", [("speed", {"value": "x8"}), ("save_state", {"slot": True}),
                                          ("load_state", {"slot": 0}), ("load_state", {"slot": 9}),
                                          ("screen_layout", {"value": 4}), ("input_settings", {"path": "x"}),
                                          ("write_ram", {})])
def test_non_whitelisted_actions_and_parameters_refused(commands, command, args):
    with pytest.raises(ValueError):
        commands.request(command, args)
    assert not (commands.directory / "melonds-command.json").exists()


@pytest.mark.parametrize("change", [dict(speed="x4"), dict(command="save_state"), dict(ok=1),
                                    dict(pid=43), dict(instance_id="c" * 32), dict(timestamp_ms=1)])
def test_acknowledgement_must_match_actual_request(commands, change):
    commands.request("speed", {"value": "x2"})
    acknowledge(commands, **change)
    with pytest.raises(ValueError):
        commands.poll_result()
    assert commands.pending is not None


def test_failed_or_missing_ack_is_never_a_success(commands):
    commands.request("speed", {"value": "x2"})
    acknowledge(commands, ok=False, error="dialog_open")
    with pytest.raises(ValueError, match="dialogue"):
        commands.poll_result()
    assert commands.pending is None
    commands.request("speed", {"value": "x2"})
    commands.clock = lambda: 107
    with pytest.raises(ValueError, match="non confirmé"):
        commands.poll_result()
    assert commands.pending is None


def test_process_exit_and_stop_marker_prevent_commands(commands):
    commands.process.poll = lambda: 0
    with pytest.raises(ValueError, match="terminée"):
        commands.request("speed", {"value": "x2"})
    commands.process.poll = lambda: None
    (commands.directory / "stop").touch()
    with pytest.raises(ValueError, match="terminée"):
        commands.request("speed", {"value": "x2"})


def test_service_confirms_speed_only_after_success(commands, tmp_path):
    service = GameModeService(tmp_path, AppConfig())
    service.native_commands = commands
    service._run_options = {"emulator_kind": "melonds"}
    service.state = RunState(running=True, native_controls=True)
    service.request_speed("x2")
    assert service.state.confirmed_speed is None and service.state.command_pending
    service._poll_native()
    assert service.state.confirmed_speed is None
    acknowledge(commands)
    service._poll_native()
    assert service.state.confirmed_speed == "x2" and not service.state.command_pending


def test_launch_preference_is_sent_once_after_native_handshake(commands, tmp_path):
    service = GameModeService(tmp_path, AppConfig())
    service.native_commands = commands
    service._run_options = {"emulator_kind": "melonds"}
    service._native_launch_speed_pending = True
    service.state = RunState(running=True, requested_speed="x2")
    publish(commands, available=False)
    service._poll_native()
    assert commands.pending is None and service._native_launch_speed_pending
    publish(commands)
    service._poll_native()
    assert commands.pending["parameters"] == {"value": "x2"}
    assert service.state.confirmed_speed is None
    assert not service._native_launch_speed_pending
    acknowledge(commands)
    service._poll_native()
    service._poll_native()
    assert commands.sequence == 1 and commands.pending is None
    assert service.state.confirmed_speed == "x2"


@pytest.mark.parametrize("policy", ["forbidden", "read_only", "outside_battle"])
def test_state_policy_is_enforced_without_inventing_battle_status(commands, tmp_path, policy):
    service = GameModeService(tmp_path, AppConfig())
    service.native_commands = commands
    service._run_options = {"save_state_policy": policy}
    service.state = RunState(running=True)
    with pytest.raises(ValueError):
        service.request_state("save_state", 1)
    assert commands.pending is None


def test_state_load_requires_existing_owned_slot(commands, tmp_path):
    service = GameModeService(tmp_path, AppConfig())
    service.native_commands = commands
    service._run_options = dict(save_state_directory=str(commands.states), save_state_stem="adventure", save_state_policy="allowed")
    service.state = RunState(running=True)
    with pytest.raises(ValueError, match="vide"):
        service.request_state("load_state", 1)
    service.request_state("save_state", 1)
    assert commands.pending["parameters"] == {"slot": 1}


@pytest.mark.parametrize("parameters", [{"mask": 0, "frames": 1}, {"mask": 4096, "frames": 1},
                                       {"mask": 1, "frames": 61}, {"mask": 48, "frames": 1},
                                       {"mask": 192, "frames": 1}, {"mask": True, "frames": 1}])
def test_input_pulse_cannot_hold_unbounded_or_opposite_buttons(commands, parameters):
    with pytest.raises(ValueError):
        commands.request("input_pulse", parameters)


def test_input_pulse_waits_for_completed_native_frames(commands):
    commands.request("input_pulse", {"mask": 1, "frames": 6})
    assert commands.poll_result() is None
    acknowledge(commands, frames=6)
    assert commands.poll_result()["frames"] == 6


def test_native_controls_page_uses_owned_session(qt_app, catalog, tmp_path, monkeypatch):
    from app.ui.main_window import MainWindow
    from test_run_integration import create
    from test_run_ui_edges import select_run
    from unittest.mock import Mock
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    run.launch_profile.update(emulator_kind="melonds", emulator_path="synthetic-melonDS.exe")
    window.runs.save(run)
    try:
        mode = select_run(window, run, qt_app, monkeypatch)
        mode.service.state = RunState(game_id=run.game_id, running=True, native_controls=True)
        mode.page.set_run_state(mode.service.state)
        assert all(button.isEnabled() for button in mode.page.speed_buttons.values())
        mode.open_settings("controls")
        assert mode.settings_tabs.currentWidget() is mode.native_settings
        assert not mode.settings_tabs.isTabEnabled(mode._tab_ids["controls"])
        sent = Mock()
        monkeypatch.setattr(mode.service, "request_native", sent)
        mode.native_settings._request("screen_layout", {"value": 2})
        sent.assert_called_once_with("screen_layout", {"value": 2})
        mode.service.state = RunState(game_id=run.game_id, running=True, command_pending=True)
        mode.native_settings.refresh()
        assert all(not button.isEnabled() for button in mode.native_settings.buttons)
    finally:
        mode.service.state = RunState()
        window.close()
        qt_app.processEvents()
