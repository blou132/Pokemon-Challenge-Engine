"""Valide la configuration locale, ses fallbacks et ses sauvegardes préservées."""

import json
from pathlib import Path

import pytest

from app.services.config_service import AppConfig, ConfigService


def test_missing_config_defaults_without_writing(tmp_path: Path) -> None:
    service = ConfigService(tmp_path / "config.json")
    assert service.load() == AppConfig()
    assert not service.path.exists()
    assert not service.warnings


def test_configuration_roundtrip(tmp_path: Path) -> None:
    service = ConfigService(tmp_path / "settings" / "config.json")
    config = AppConfig(retrobat_path="D:/Mes jeux/RetroBat", desmume_path="D:/Mes jeux/DeSmuME.exe",
                       rom_paths={"black": "D:/ROM/Noir.nds", "black2": "D:/ROM/Noir 2.nds"}, save_path="D:/Saves")
    service.save(config)
    assert service.load() == config
    assert not list(service.path.parent.glob("*.tmp"))


@pytest.mark.parametrize("content", [
    "{", "[]", '{"desmume_path": null}', '{"rom_paths": []}', '{"rom_paths": {"black": 42}}',
    '{"save_path": NaN}', '{"save_path": "a", "save_path": "b"}', '{"unknown_field": true}',
])
def test_invalid_config_is_not_overwritten_on_load(tmp_path: Path, content: str) -> None:
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")
    service = ConfigService(path)
    assert service.load() == AppConfig()
    assert service.warnings
    assert path.read_text(encoding="utf-8") == content
    service.save(AppConfig())
    backups = list(tmp_path.glob("config.json.invalid_*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == content
    assert service.warnings
    assert json.loads(path.read_text(encoding="utf-8")) == AppConfig().to_dict()


def test_invalid_config_save_preserves_valid_existing_file(tmp_path: Path) -> None:
    service = ConfigService(tmp_path / "config.json")
    service.save(AppConfig())
    original = service.path.read_bytes()
    invalid = AppConfig()
    invalid.rom_paths["black"] = None
    with pytest.raises(ValueError):
        service.save(invalid)
    assert service.path.read_bytes() == original
