"""La détection éventuelle lit uniquement les seize premiers octets."""

import pytest

from app.core.game_detector import GameDetector


@pytest.mark.parametrize("code,expected", [("IRBF", "black"), ("IREF", "black2"), ("IRAO", "white"), ("IRDO", "white2"), ("ABCD", None)])
def test_header_detection_is_read_only(tmp_path, code, expected):
    path = tmp_path / "jeu.nds"
    original = b"POKEMON     " + code.encode("ascii") + b"\x00" * 128
    path.write_bytes(original)
    assert GameDetector.detect(path) == expected
    assert path.read_bytes() == original


def test_missing_or_truncated_rom(tmp_path):
    with pytest.raises(ValueError, match="existe"):
        GameDetector.detect(tmp_path / "missing.nds")
    path = tmp_path / "empty.nds"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="trop court"):
        GameDetector.detect(path)
