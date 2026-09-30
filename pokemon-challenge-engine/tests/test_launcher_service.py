"""Le launcher démarre le processus sans toucher aux octets des ROM et sauvegardes."""

import os
from pathlib import Path
import subprocess
from unittest.mock import Mock, patch

import pytest

from app.services.config_service import AppConfig
from app.services.launcher_service import LauncherService


@pytest.fixture
def configured(tmp_path: Path) -> tuple[LauncherService, Path, Path, Path]:
    emulator = tmp_path / "DeSmuME standalone.exe"
    emulator.write_bytes(b"emulateur factice")
    rom = tmp_path / "Pokemon Noir 2.nds"
    rom.write_bytes(b"ROM sentinelle non executee\x00\xff")
    saves = tmp_path / "saves"
    saves.mkdir()
    save = saves / "Pokemon Noir 2.dsv"
    save.write_bytes(b"Sauvegarde sentinelle\x00\x01")
    service = LauncherService(AppConfig(desmume_path=str(emulator), rom_paths={"black2": str(rom)}, save_path=str(saves)))
    return service, emulator, rom, save


def test_build_and_launch_preserve_rom_and_save(configured: tuple[LauncherService, Path, Path, Path]) -> None:
    service, emulator, rom, save = configured
    originals = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (rom, save)}
    assert service.validate("black2") == []
    command = service.build_command("black2")
    assert command == [str(emulator.resolve()), str(rom.resolve())]
    process = Mock(pid=1234)
    with patch("app.services.launcher_service.subprocess.Popen", return_value=process) as popen:
        assert service.launch("black2") is process
    popen.assert_called_once_with(command, shell=False, cwd=str(emulator.parent),
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (rom, save)} == originals


def test_launcher_never_opens_rom_or_save(configured: tuple[LauncherService, Path, Path, Path]) -> None:
    service, _, _, _ = configured
    with patch("builtins.open", side_effect=AssertionError("Aucun contenu à ouvrir")), \
         patch("pathlib.Path.open", side_effect=AssertionError("Aucun contenu à ouvrir")), \
         patch("app.services.launcher_service.subprocess.Popen", return_value=Mock(pid=1)):
        assert service.validate("black2") == []
        service.launch("black2")


def test_missing_paths_return_french_errors() -> None:
    service = LauncherService(AppConfig())
    errors = service.validate("black")
    assert len(errors) == 2
    assert "DeSmuME" in errors[0] and "ROM" in errors[1]
    with patch("app.services.launcher_service.subprocess.Popen") as popen:
        with pytest.raises(ValueError):
            service.launch("black")
        popen.assert_not_called()


def test_unsupported_game_is_rejected(configured: tuple[LauncherService, Path, Path, Path]) -> None:
    service, _, _, _ = configured
    assert service.validate("platinum")
    with pytest.raises(ValueError):
        service.build_command("platinum")


@pytest.mark.parametrize("game_id", ["black", "white", "black2", "white2"])
def test_gen5_launch_uses_only_selected_rom(tmp_path, game_id):
    emulator = tmp_path / "DeSmuME.exe"
    emulator.write_bytes(b"emulateur factice")
    paths = {}
    for candidate in ("black", "white", "black2", "white2"):
        rom = tmp_path / f"{candidate}.nds"
        rom.write_bytes(candidate.encode("ascii"))
        paths[candidate] = str(rom)
    service = LauncherService(AppConfig(desmume_path=str(emulator), rom_paths=paths))
    before = {candidate: Path(path).read_bytes() for candidate, path in paths.items()}
    with patch("pathlib.Path.open", side_effect=AssertionError("Le launcher ne lit pas la ROM")), \
         patch("app.services.launcher_service.subprocess.Popen", return_value=Mock(pid=1234)) as popen:
        assert service.validate(game_id) == []
        service.launch(game_id)
    assert popen.call_args.args[0] == [str(emulator.resolve()), str(Path(paths[game_id]).resolve())]
    assert {candidate: Path(path).read_bytes() for candidate, path in paths.items()} == before


def test_directories_cannot_be_executable_or_rom(tmp_path: Path) -> None:
    emulator = tmp_path / "wrong.exe"
    rom = tmp_path / "wrong.nds"
    emulator.mkdir()
    rom.mkdir()
    service = LauncherService(AppConfig(desmume_path=str(emulator), rom_paths={"black": str(rom)}))
    assert len(service.validate("black")) == 2


def test_wrong_extensions_are_rejected(tmp_path: Path) -> None:
    emulator = tmp_path / "command.cmd"
    rom = tmp_path / "rom.zip"
    emulator.write_text("nothing")
    rom.write_bytes(b"nothing")
    service = LauncherService(AppConfig(desmume_path=str(emulator), rom_paths={"black": str(rom)}))
    errors = service.validate("black")
    assert len(errors) == 2 and ".exe" in errors[0] and ".nds" in errors[1]


def test_process_failure_has_readable_error(configured: tuple[LauncherService, Path, Path, Path]) -> None:
    service, _, rom, save = configured
    before = (rom.read_bytes(), save.read_bytes())
    with patch("app.services.launcher_service.subprocess.Popen", side_effect=PermissionError(13, "denied")):
        with pytest.raises(ValueError, match="Impossible de démarrer"):
            service.launch("black2")
    assert (rom.read_bytes(), save.read_bytes()) == before
