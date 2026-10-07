"""Atomic acknowledgement publication while a Windows reader holds the file."""

import errno
from pathlib import Path

import pytest

from app.bridge.state import BridgeState
from app.services import bridge_service
from app.services.bridge_service import BridgeService


def acknowledgement(tmp_path):
    bridge = BridgeService(tmp_path)
    bridge.start("white", "IRAF", 0)
    state = BridgeState(status="connected", protocol_version=2,
                        session_id=bridge.session_id, sequence=42)
    target = bridge.session_dir / "ack.txt"
    target.write_text("41", encoding="ascii")
    return bridge, state, target


def windows_error(code):
    error = PermissionError(errno.EACCES, "Acknowledgement is in use")
    error.winerror = code
    return error


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_transient_windows_ack_lock_retries_without_partial_publication(tmp_path, monkeypatch, winerror):
    bridge, state, target = acknowledgement(tmp_path)
    actual_replace = Path.replace
    attempts = []
    delays = []

    def replace(source, destination):
        assert destination == target
        assert source.name == "ack.txt.tmp"
        assert source.read_text(encoding="ascii") == "42"
        assert target.read_text(encoding="ascii") == "41"
        attempts.append(source)
        if len(attempts) < 3:
            raise windows_error(winerror)
        return actual_replace(source, destination)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(bridge_service, "sleep", delays.append)

    bridge.acknowledge_observations(state)

    assert len(attempts) == 3
    assert delays == [0.005, 0.010]
    assert target.read_text(encoding="ascii") == "42"
    assert not target.with_name("ack.txt.tmp").exists()


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_persistent_windows_ack_lock_remains_visible_and_preserves_old_ack(tmp_path, monkeypatch, winerror):
    bridge, state, target = acknowledgement(tmp_path)
    error = windows_error(winerror)
    attempts = []
    delays = []

    def replace(source, destination):
        attempts.append((source, destination))
        raise error

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(bridge_service, "sleep", delays.append)

    with pytest.raises(PermissionError) as caught:
        bridge.acknowledge_observations(state)

    assert caught.value is error
    assert len(attempts) == 3
    assert delays == [0.005, 0.010]
    assert target.read_text(encoding="ascii") == "41"
    assert target.with_name("ack.txt.tmp").read_text(encoding="ascii") == "42"


@pytest.mark.parametrize("error", [PermissionError(errno.EACCES, "Access denied"),
                                  windows_error(19), OSError(errno.ENOSPC, "Disk full")])
def test_other_ack_errors_are_not_retried(tmp_path, monkeypatch, error):
    bridge, state, target = acknowledgement(tmp_path)
    attempts = []
    delays = []

    def replace(source, destination):
        attempts.append((source, destination))
        raise error

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(bridge_service, "sleep", delays.append)

    with pytest.raises(OSError) as caught:
        bridge.acknowledge_observations(state)

    assert caught.value is error
    assert len(attempts) == 1
    assert delays == []
    assert target.read_text(encoding="ascii") == "41"


def test_successful_ack_does_not_wait(tmp_path, monkeypatch):
    bridge, state, target = acknowledgement(tmp_path)
    delays = []
    monkeypatch.setattr(bridge_service, "sleep", delays.append)

    bridge.acknowledge_observations(state)

    assert delays == []
    assert target.read_text(encoding="ascii") == "42"
