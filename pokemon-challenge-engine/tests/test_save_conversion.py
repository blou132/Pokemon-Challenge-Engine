import struct

import pytest

from app.services.save_conversion_service import (
    DSV_COOKIE, GEN5_SAVE_BYTES, convert_gen5_battery, gen5_battery_bytes,
)


def dsv(**updates):
    fields = dict(written=GEN5_SAVE_BYTES, padded=GEN5_SAVE_BYTES, kind=6,
                  address_size=3, memory_size=GEN5_SAVE_BYTES, version=0)
    fields.update(updates)
    return bytes(range(256)) * 2048 + b"\0" * 82 + struct.pack("<6I", *fields.values()) + DSV_COOKIE


def test_conversion_preserves_all_bytes_and_source(tmp_path):
    source, target = tmp_path / "original.dsv", tmp_path / "independent.sav"
    content = dsv()
    source.write_bytes(content)
    before = source.stat()
    report = convert_gen5_battery(source, target)
    assert target.read_bytes() == content[:GEN5_SAVE_BYTES]
    assert source.read_bytes() == content
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert report["size"] == GEN5_SAVE_BYTES
    assert report["source_sha256"] != report["output_sha256"]


@pytest.mark.parametrize("updates", [{"padded": 1024}, {"version": 1}, {"address_size": 2},
                                      {"written": 0}, {"written": GEN5_SAVE_BYTES + 1}])
def test_unsupported_footer_refused(updates):
    with pytest.raises(ValueError):
        gen5_battery_bytes(dsv(**updates), ".dsv")


@pytest.mark.parametrize("content", [b"", dsv()[:-1], dsv() + b"x", b"x" + dsv(),
                                      dsv()[:-len(DSV_COOKIE)] + b"x" * len(DSV_COOKIE)],
                         ids=["empty", "truncated", "trailing", "prepended", "cookie"])
def test_malformed_container_refused(content):
    with pytest.raises(ValueError):
        gen5_battery_bytes(content, ".dsv")


def test_no_overwrite_or_inplace_conversion(tmp_path):
    source, target = tmp_path / "source.dsv", tmp_path / "game.sav"
    source.write_bytes(dsv())
    target.write_bytes(b"existing")
    with pytest.raises(ValueError):
        convert_gen5_battery(source, target)
    assert target.read_bytes() == b"existing"
    with pytest.raises(ValueError):
        convert_gen5_battery(source, source)


def test_raw_copy_and_wrong_extensions():
    raw = b"\xff" * GEN5_SAVE_BYTES
    assert gen5_battery_bytes(raw, ".SAV") == raw
    for suffix, content in ((".ds0", raw), (".sav", raw[:-1]), (".sav", dsv())):
        with pytest.raises(ValueError):
            gen5_battery_bytes(content, suffix)
