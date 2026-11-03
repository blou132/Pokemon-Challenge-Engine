"""Shiny configuration/provenance contracts; synthetic ROMs are not gameplay proof."""

from copy import deepcopy
import json

import pytest

from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.services.rom_transformation_service import (
    ADVANCED_DEFAULTS, RandomizerOptions, RomTransformationService, file_hash,
    transformation_options, verified_transformation_report,
)
from test_rom_transformation import report, transform, transformation


DENOMINATORS = (4096, 1024, 512, 128, 1)


def configured_challenge(catalog, *, denominator=512, rules=("shiny_only",), mode="soft"):
    challenge = ChallengeEngine(catalog).generate(
        "white", "custom", {rule: "required" for rule in rules}, 0, 512,
    )
    mono = None
    categories = ("wild", "starters", "trainers") if "randomizer" in rules else ()
    if "monotype" in rules:
        challenge.monotype.update(type_id="fire", mode=mode)
        mono = {"type_id": "fire", "mode": mode, "prefer_evolutions": False}
        if "starters" not in categories:
            categories += ("starters",)
    options = RandomizerOptions(categories, monotype_starters=mono, shiny_denominator=denominator)
    challenge.settings["rom_transformation"] = {"kind": "zx", **options.to_dict()}
    return challenge, options


@pytest.mark.parametrize("denominator", DENOMINATORS)
def test_white_shiny_patch_can_be_selected_without_randomizer(catalog, denominator):
    challenge, options = configured_challenge(catalog, denominator=denominator)
    assert options.categories == ()
    assert "randomizer" not in challenge.active_rules
    assert ChallengeEngine(catalog).validate(challenge) == []
    assert transformation_options(challenge.to_dict()) == options
    assert options.to_dict() == {"categories": [], "balanced": False, "shiny_denominator": denominator}
    assert options.adapter_properties() == {}
    assert options.transformation_order()[-1] == "pce-shiny-field-v1"


@pytest.mark.parametrize("value", [True, False, 0, -1, 8, 8192, 1.0, "512", [], {}])
def test_patch_denominator_is_strict_and_cannot_mean_original(value):
    with pytest.raises(ValueError):
        RandomizerOptions(shiny_denominator=value)


def test_original_rate_keeps_legacy_serialization_and_pipeline():
    original = {"categories": ["wild", "starters", "trainers"], "balanced": False}
    options = RandomizerOptions(shiny_denominator=None)
    assert options.to_dict() == original
    assert options.transformation_order() == ["upr-zx-4.6.1"]
    with pytest.raises(ValueError):
        RandomizerOptions((), shiny_denominator=None)


def test_old_shiny_profile_is_not_implicitly_patched(catalog, tmp_path):
    challenge = ChallengeEngine(catalog).generate("white", "custom", {"shiny_only": "required"}, 0, 512)
    before = deepcopy(challenge.to_dict())
    profile = ProfileManager(tmp_path / "profiles").create("Ancien shiny", challenge)
    loaded = ProfileManager(tmp_path / "profiles").load(profile.id)
    assert loaded.challenge.to_dict() == before
    assert transformation_options(loaded.challenge.to_dict()) is None
    assert "shiny_denominator" not in json.dumps(loaded.challenge.settings)


@pytest.mark.parametrize("rules,mode", [
    (("shiny_only",), "soft"),
    (("randomizer", "shiny_only"), "soft"),
    (("monotype", "shiny_only"), "soft"),
    (("monotype", "shiny_only"), "strict"),
    (("randomizer", "monotype", "shiny_only"), "pure"),
])
def test_patch_combination_survives_fresh_profile_manager(catalog, tmp_path, rules, mode):
    challenge, options = configured_challenge(catalog, rules=rules, mode=mode)
    before = deepcopy(challenge.to_dict())
    assert ChallengeEngine(catalog).validate(challenge) == []
    profile = ProfileManager(tmp_path / "profiles").create("Terrain shiny", challenge)
    loaded = ProfileManager(tmp_path / "profiles").load(profile.id)
    assert loaded.challenge.to_dict() == before
    assert transformation_options(loaded.challenge.to_dict()) == options
    expected = ["upr-zx-4.6.1"]
    if "monotype" in rules:
        expected.append("pce-starters-v1")
    expected.append("pce-shiny-field-v1")
    assert options.transformation_order() == expected


@pytest.mark.parametrize("game_id", ["black", "black2", "white2", "unknown"])
def test_patch_is_rejected_outside_white_before_tool_execution(catalog, game_id):
    challenge, _ = configured_challenge(catalog)
    snapshot = challenge.to_dict()
    snapshot["game_id"] = game_id
    with pytest.raises(ValueError):
        transformation_options(snapshot)
    assert RomTransformationService.shiny_rate_support(game_id)["custom_denominators"] == []


@pytest.mark.parametrize("rules", [("shiny_only",), ("randomizer", "shiny_only"),
                                   ("monotype", "shiny_only")])
def test_patch_requires_shiny_rule_even_with_other_transformation_rules(catalog, rules):
    challenge, _ = configured_challenge(catalog, rules=rules)
    snapshot = challenge.to_dict()
    snapshot["active_rules"].remove("shiny_only")
    with pytest.raises(ValueError):
        transformation_options(snapshot)


@pytest.mark.parametrize("categories", [("wild",), ("starters",), ("trainers",)])
def test_shiny_patch_does_not_authorize_unselected_randomizer_categories(catalog, categories):
    challenge, _ = configured_challenge(catalog)
    challenge.settings["rom_transformation"]["categories"] = list(categories)
    with pytest.raises(ValueError):
        transformation_options(challenge.to_dict())


def test_combined_shiny_patch_keeps_monotype_match_requirement(catalog):
    challenge, _ = configured_challenge(catalog, rules=("monotype", "shiny_only"))
    challenge.monotype["type_id"] = "water"
    with pytest.raises(ValueError):
        transformation_options(challenge.to_dict())


def test_shiny_option_does_not_weaken_unknown_setting_validation(catalog):
    challenge, _ = configured_challenge(catalog)
    challenge.settings["rom_transformation"]["bypass_shiny_locks"] = True
    with pytest.raises(ValueError):
        transformation_options(challenge.to_dict())


def test_randomizer_options_are_kept_separate_from_shiny_parameter():
    advanced = dict(ADVANCED_DEFAULTS, starter_legendaries=False, starter_mythicals=False,
                    starter_similar_strength=True)
    original = RandomizerOptions(advanced=advanced)
    patched = RandomizerOptions(advanced=advanced, shiny_denominator=128)
    assert patched.adapter_properties() == original.adapter_properties()
    assert patched.to_dict() == {**original.to_dict(), "shiny_denominator": 128}
    assert patched.transformation_order() == ["upr-zx-4.6.1", "pce-starters-v1", "pce-shiny-field-v1"]


@pytest.fixture
def patcher(transformation, monkeypatch):
    """Isolate orchestration from bytecode/native validation in the dedicated tests."""
    calls = []

    def apply_patch(output, jar, denominator):
        assert output.parent != transformation.source.parent
        assert jar.parent == output.parent
        assert jar.read_bytes() == transformation.jar.read_bytes()
        contents = bytearray(output.read_bytes())
        assert contents[-1] == 42  # The ZX transformation must have finished first.
        source_hash = file_hash(output)
        contents[-2] = 84
        output.write_bytes(contents)
        evidence = {
            "patch_id": "pce-shiny-field-v1", "selector_denominator": denominator,
            "game_code": "IRAF", "revision": 0, "application": "applied",
            "source_sha256": source_hash, "output_sha256": file_hash(output),
            "source_unchanged": True, "only_declared_spans_changed": True,
            "shiny_lock_preserved": True, "shiny_predicate_changed": False,
        }
        calls.append(evidence)
        return evidence

    monkeypatch.setattr(transformation.service, "_apply_shiny_patch", apply_patch)
    return calls


def read_verified(result, challenge):
    return verified_transformation_report(
        result.rom_path.parent, result.rom_path, game_id="white",
        rom_sha256=result.manifest["output_sha256"], configuration=challenge.to_dict(),
    )


@pytest.mark.parametrize("denominator", DENOMINATORS)
def test_patch_only_publishes_provenance_and_preserves_original(catalog, transformation, patcher, denominator):
    challenge, options = configured_challenge(catalog, denominator=denominator)
    transformation.changes["report"] = report(categories=())
    before, modified = transformation.source.read_bytes(), transformation.source.stat().st_mtime_ns
    result = transform(transformation, options=options)
    assert transformation.source.read_bytes() == before
    assert transformation.source.stat().st_mtime_ns == modified
    assert len(patcher) == 1
    assert result.manifest["options"] == options.to_dict()
    assert result.manifest["output_sha256"] == file_hash(result.rom_path)
    assert result.manifest["transformation_order"][-1] == "pce-shiny-field-v1"
    assert result.manifest["validation"]["shiny_rate"] == "field_generator_experimental"
    assert result.manifest["validation"]["shiny_denominator"] == denominator
    assert result.manifest["validation"]["shiny_scope"]
    patch_path = result.rom_path.parent / "shiny-patch.json"
    assert json.loads(patch_path.read_text(encoding="utf-8")) == patcher[0]
    assert result.manifest["shiny_patch_sha256"] == file_hash(patch_path)
    assert read_verified(result, challenge) == transformation.changes["report"]


def test_combined_pipeline_checks_starters_before_shiny_and_retains_effective_report(catalog, transformation, patcher):
    challenge, options = configured_challenge(catalog, rules=("randomizer", "monotype", "shiny_only"))
    data = report(categories=options.categories)
    data.update(schema_version=2, adapter_options=options.adapter_properties(), starters=[1, 2, 3])
    for row in data["pokemon"][:3]:
        row["types"] = ["fire"]
    transformation.changes["report"] = data
    result = transform(transformation, options=options)
    assert len(patcher) == 1
    assert result.manifest["transformation_order"] == ["upr-zx-4.6.1", "pce-starters-v1", "pce-shiny-field-v1"]
    assert read_verified(result, challenge) == data


def test_invalid_zx_report_never_reaches_shiny_patch(catalog, transformation, patcher):
    _, options = configured_challenge(catalog)
    # The fake tool claims wild encounters changed, though only shiny was requested.
    transformation.changes["report"] = report(categories=("wild",))
    with pytest.raises(ValueError):
        transform(transformation, options=options)
    assert patcher == []
    assert not transformation.destination.exists()


def test_patch_signature_failure_never_publishes_or_changes_original(catalog, transformation, monkeypatch):
    _, options = configured_challenge(catalog)
    transformation.changes["report"] = report(categories=())
    before = transformation.source.read_bytes()

    def refuse(*args):
        raise ValueError("Unrecognized field signature")

    monkeypatch.setattr(transformation.service, "_apply_shiny_patch", refuse)
    with pytest.raises(ValueError, match="signature"):
        transform(transformation, options=options)
    assert not transformation.destination.exists()
    assert transformation.source.read_bytes() == before
    failures = list(transformation.destination.parent.glob(".pce-transform-*/failed.json"))
    assert len(failures) == 1
    assert json.loads(failures[0].read_text(encoding="utf-8"))["status"] == "not_published"


@pytest.mark.parametrize("filename", ["shiny-patch.json", "report.json", "derived.nds"])
def test_modified_patch_report_or_rom_cannot_be_resumed(catalog, transformation, patcher, filename):
    challenge, options = configured_challenge(catalog)
    transformation.changes["report"] = report(categories=())
    result = transform(transformation, options=options)
    path = result.rom_path.parent / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        read_verified(result, challenge)


@pytest.mark.parametrize("key,value", [
    ("selector_denominator", 1), ("output_sha256", "0" * 64),
    ("game_code", "IREF"), ("patch_id", "other-patch"),
    ("shiny_lock_preserved", False), ("shiny_predicate_changed", True),
    ("source_unchanged", False), ("only_declared_spans_changed", False),
])
def test_rehashed_patch_evidence_must_still_confirm_requested_operation(catalog, transformation, patcher, key, value):
    challenge, options = configured_challenge(catalog)
    transformation.changes["report"] = report(categories=())
    result = transform(transformation, options=options)
    path = result.rom_path.parent / "shiny-patch.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence[key] = value
    path.write_text(json.dumps(evidence), encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["shiny_patch_sha256"] = file_hash(path)
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        read_verified(result, challenge)


def test_resuming_with_different_shiny_rate_is_rejected(catalog, transformation, patcher):
    challenge, options = configured_challenge(catalog)
    transformation.changes["report"] = report(categories=())
    result = transform(transformation, options=options)
    challenge.settings["rom_transformation"]["shiny_denominator"] = 128
    with pytest.raises(ValueError):
        read_verified(result, challenge)


@pytest.mark.parametrize("field,value", [
    ("shiny_rate", "original"), ("shiny_denominator", 128), ("shiny_denominator", True),
])
def test_manifest_must_confirm_the_experimental_rate(catalog, transformation, patcher, field, value):
    challenge, options = configured_challenge(catalog, denominator=1)
    transformation.changes["report"] = report(categories=())
    result = transform(transformation, options=options)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["validation"][field] = value
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        read_verified(result, challenge)


def test_boolean_patch_denominator_cannot_impersonate_one(catalog, transformation, patcher):
    challenge, options = configured_challenge(catalog, denominator=1)
    transformation.changes["report"] = report(categories=())
    result = transform(transformation, options=options)
    path = result.rom_path.parent / "shiny-patch.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["selector_denominator"] = True
    path.write_text(json.dumps(evidence), encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["shiny_patch_sha256"] = file_hash(path)
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        read_verified(result, challenge)


def test_native_patch_signature_refusal_preserves_staging_and_original(catalog, transformation, monkeypatch):
    from tools import shiny_field_trial

    _, options = configured_challenge(catalog)
    transformation.changes["report"] = report(categories=())
    original = transformation.source.read_bytes()
    inspected = []

    def unrecognized(source, output, java, jar, denominator):
        inspected.append((source, source.read_bytes()))
        assert source != transformation.source
        assert output != source
        assert denominator == 512
        raise ValueError("Unrecognized field signature")

    monkeypatch.setattr(shiny_field_trial, "create_trial", unrecognized)
    with pytest.raises(ValueError, match="Patch shiny"):
        transform(transformation, options=options)
    assert len(inspected) == 1
    assert inspected[0][0].read_bytes() == inspected[0][1]
    assert transformation.source.read_bytes() == original
    assert not transformation.destination.exists()


@pytest.mark.parametrize("wrong_hash", ["source_sha256", "output_sha256"])
def test_native_patch_hash_mismatch_does_not_replace_staging_output(catalog, transformation, monkeypatch, wrong_hash):
    from tools import shiny_field_trial

    _, options = configured_challenge(catalog)
    transformation.changes["report"] = report(categories=())
    original = transformation.source.read_bytes()
    inspected = []

    def mismatched(source, output, java, jar, denominator):
        contents = source.read_bytes()
        inspected.append((source, contents))
        output.write_bytes(contents[:-2] + b"XY")
        evidence = {"source_sha256": file_hash(source), "output_sha256": file_hash(output)}
        evidence[wrong_hash] = "0" * 64
        return evidence

    monkeypatch.setattr(shiny_field_trial, "create_trial", mismatched)
    with pytest.raises(ValueError, match="empreintes"):
        transform(transformation, options=options)
    assert len(inspected) == 1
    assert inspected[0][0].read_bytes() == inspected[0][1]
    assert transformation.source.read_bytes() == original
    assert not transformation.destination.exists()
