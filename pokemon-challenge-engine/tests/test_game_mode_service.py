"""Frontend session tests; fake processes never launch or alter a game."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.config_service import AppConfig
from app.services.game_mode_config import GameModeConfigStore, validate_config
from app.services.game_mode_service import GameModeService
from app.services.emulator_window_manager import EmulatorWindow, EmulatorWindowManager


class Windows:
    def running_executable(self, path):
        return False

    def find(self, pid, executable=None):
        return SimpleNamespace(title="DeSmuME — fixture synthétique")

    def arrange(self, pid, rect, *, executable):
        return pid, rect, executable


class Launcher:
    def __init__(self, config):
        self.config = config
        self.process = SimpleNamespace(pid=123, code=None)
        self.process.poll = lambda: self.process.code

    def validate(self, game):
        return []

    def launch(self, game):
        return self.process


@pytest.fixture
def service(tmp_path):
    clock = SimpleNamespace(now=100.0)
    value = GameModeService(tmp_path, AppConfig(), clock=lambda: clock.now,
                            launcher_factory=Launcher, window_manager=Windows())
    value.test_clock = clock
    return value


def test_legacy_paths_migrate_in_memory_without_changing_old_config(tmp_path):
    legacy = AppConfig(retrobat_path="retrobat", desmume_path="emulator.exe", rom_paths={"white": "white.nds"})
    store = GameModeConfigStore(tmp_path, legacy)
    value = store.load()
    assert value["launch_profiles"]["white"]["rom_path"] == "white.nds"
    assert all(profile["emulator_path"] == "emulator.exe" for profile in value["launch_profiles"].values())
    assert not list(tmp_path.iterdir())
    store.save(value)
    assert store.load() == value
    assert legacy.save_path == "" and legacy.retrobat_path == "retrobat"


def test_corrupt_preferences_are_preserved_before_explicit_save(tmp_path):
    path = tmp_path / "game-mode.local.json"
    path.write_bytes(b"{bad")
    store = GameModeConfigStore(tmp_path, AppConfig())
    value = store.load()
    assert store.warnings and path.read_bytes() == b"{bad"
    store.save(value)
    backups = list(tmp_path.glob("*.invalid-*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"{bad"


def test_external_changes_are_not_overwritten(service):
    service.save_interface({"density": "compact"})
    service.store.path.write_bytes(b"changed externally")
    with pytest.raises(ValueError, match="autre outil"):
        service.save_interface({"density": "large"})
    assert service.store.path.read_bytes() == b"changed externally"


@pytest.mark.parametrize("changes", [
    {"speed": "x8"}, {"game_id": "black"}, {"backup_retention": 0},
    {"backup_retention": True}, {"backup_interval_minutes": -1},
    {"backup_on_launch": 1}, {"rom_path": "bad\0.nds"}, {"emulator_path": []},
    {"save_state_policy": "enforced"}, {"challenge_profile_id": "../escape"}, {"extra": "unknown"},
])
def test_launch_preferences_validate_before_writing(service, changes):
    original = deepcopy(service.config)
    with pytest.raises(ValueError):
        service.save_launch_profile("white", changes)
    assert service.config == original and not service.store.path.exists()


@pytest.mark.parametrize("updates", [
    {"density": "huge"}, {"visible": {"team": 1}}, {"sides": {"team": "center"}},
    {"auto_arrange": "yes"}, {"monitor_name": 1}, {"visible": {"missing": True}},
])
def test_interface_rejects_unsupported_options(service, updates):
    with pytest.raises(ValueError):
        service.save_interface(updates)


def test_shortcuts_start_unbound_and_conflicts_are_rejected(service):
    assert not any(service.config["shortcuts"].values())
    service.save_shortcuts({"fullscreen": "Ctrl+F11"})
    with pytest.raises(ValueError, match="même combinaison"):
        service.save_shortcuts({"game_mode": "ctrl + f11"})
    assert service.config["shortcuts"]["game_mode"] == ""


def test_failed_atomic_config_replace_keeps_previous_file(service, monkeypatch):
    service.save_interface({"density": "compact"})
    original = service.store.path.read_bytes()
    def denied(*args):
        raise PermissionError("fixture verrouillée")
    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        service.save_interface({"density": "large"})
    assert service.store.path.read_bytes() == original
    assert not list(service.base_dir.glob("*.tmp"))


def test_defaults_never_modify_ini_or_backup_save_at_launch(service, monkeypatch):
    def forbidden(*args):
        raise AssertionError("no implicit mutation")
    monkeypatch.setattr(service, "_backup", forbidden)
    monkeypatch.setattr(service, "_apply_launch_settings", forbidden)
    process = service.launch("white")
    assert process.pid == service.state.pid and service.state.running
    assert service.state.confirmed_speed is None
    assert service.tick().window_title == "DeSmuME — fixture synthétique"
    assert not service.store.path.exists()


def test_opt_in_backups_follow_only_the_launched_session(service, monkeypatch):
    recorded = []
    monkeypatch.setattr(service, "_backup", lambda options, reason: recorded.append((options["game_id"], reason)))
    service.save_launch_profile("white", {"backup_on_launch": True, "backup_on_close": True,
                                          "backup_periodic": True, "backup_interval_minutes": 1})
    process = service.launch("white")
    assert recorded == [("white", "launch")]
    service.test_clock.now += 60
    assert service.tick().elapsed_seconds == 60
    service.tick()
    assert recorded == [("white", "launch"), ("white", "periodic")]
    service.save_launch_profile("black", {"backup_on_close": True})
    process.code = 0
    assert not service.tick().running
    service.tick()
    assert recorded[-1] == ("white", "close") and len(recorded) == 3


def test_backup_failure_does_not_kill_running_game(service, monkeypatch):
    service.save_launch_profile("white", {"backup_periodic": True, "backup_interval_minutes": 1})
    process = service.launch("white")
    def denied(*args):
        raise PermissionError("accès refusé")
    monkeypatch.setattr(service, "_backup", denied)
    service.test_clock.now += 60
    assert service.tick().running and "non créé" in service.state.message
    assert process.poll() is None


def test_relaunch_finalises_previous_games_close_backup_before_replacing_session(service, monkeypatch):
    recorded = []
    monkeypatch.setattr(service, "_backup", lambda options, reason: recorded.append((options["game_id"], reason)))
    service.save_launch_profile("white", {"backup_on_close": True})
    process = service.launch("white")
    process.code = 0
    service.launch("black")
    assert recorded == [("white", "close")]
    assert service.state.game_id == "black"


def test_window_probe_failure_does_not_break_tracking_or_close(service, monkeypatch):
    def denied(*args):
        raise OSError("Windows unavailable")
    process = service.launch("white")
    monkeypatch.setattr(service.windows, "find", denied)
    assert service.tick().running
    assert service.state.window_title is None
    assert not service.stop_tracking().running
    assert process.poll() is None


def test_challenge_mismatch_refuses_launch_before_backups(service, monkeypatch):
    from test_nuzlocke_tracker import make_profile
    profile = service.profiles.create("Noir", make_profile(game="black").challenge)
    with pytest.raises(ValueError, match="incompatibles"):
        service.launch("white", profile.id)
    assert service.process is None


def test_session_time_request_and_window_placement_are_truthful(service):
    service.launch("white")
    service.test_clock.now += 12
    assert service.tick().elapsed_seconds == 12
    result = service.request_speed("x2")
    assert result.requested_speed == "x2" and result.confirmed_speed is None
    assert service.arrange((100, 100, 600, 600))[:2] == (123, (100, 100, 600, 600))
    with pytest.raises(ValueError):
        service.launch("white")
    process = service.process
    service.stop_tracking()
    assert process.poll() is None and not service.state.running


def test_window_matching_never_selects_an_ambiguous_or_foreign_executable(monkeypatch, tmp_path):
    manager = EmulatorWindowManager()
    executable = str((tmp_path / "desmume.exe").resolve())
    one = EmulatorWindow(1, 7, "DeSmuME", executable, (0, 0, 400, 600))
    monkeypatch.setattr(manager, "windows", lambda pid=None: [one])
    assert manager.find(7, executable) == one
    assert manager.find(7, tmp_path / "foreign.exe") is None
    monkeypatch.setattr(manager, "windows", lambda pid=None: [one, one])
    assert manager.find(7, executable) is None
    with pytest.raises(ValueError, match="Dimensions"):
        manager.arrange(7, (0, 0, 0, 100), executable=executable)


def test_running_check_covers_processes_without_windows(monkeypatch, tmp_path):
    manager = EmulatorWindowManager()
    manager.available = True
    executable = str((tmp_path / "DeSmuME.exe").resolve())
    monkeypatch.setattr(manager, "windows", lambda *args: [])
    monkeypatch.setattr(manager, "_processes", lambda: [(8, "unrelated.exe"), (9, "DeSmuME.exe")])
    monkeypatch.setattr(manager, "_executable", lambda pid: executable)
    assert manager.running_executable(executable)
    monkeypatch.setattr(manager, "_executable", lambda pid: str(tmp_path / "other" / "DeSmuME.exe"))
    assert not manager.running_executable(executable)
    monkeypatch.setattr(manager, "_executable", lambda pid: "")
    with pytest.raises(OSError, match="confirmer"):
        manager.running_executable(executable)


def test_running_check_refuses_to_certify_unsupported_platform():
    manager = EmulatorWindowManager()
    manager.available = False
    with pytest.raises(OSError, match="Windows"):
        manager.running_executable("DeSmuME.exe")
