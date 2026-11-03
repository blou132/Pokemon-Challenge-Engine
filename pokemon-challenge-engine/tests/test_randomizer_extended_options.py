"""Configuration/provenance tests; synthetic reports are not gameplay evidence."""
from copy import deepcopy
import json

import pytest

from app.core.challenge_engine import ChallengeEngine
from app.services.rom_transformation_service import (
    ADVANCED_DEFAULTS, CATEGORIES, LEGACY_CATEGORIES, RandomizerOptions,
    RomTransformationService, transformation_options,
)
from test_rom_transformation import report, transform, transformation
from test_randomizer_configuration_ui import page, qt_app, widget
from test_run_randomizer_isolation import randomizer, environment, create, tree
from app.services.run_transformation_provider import RunTransformationProvider


def monotype(mode="soft"):
    return {"type_id": "fire", "mode": mode, "prefer_evolutions": True}


def test_legacy_options_serialize_without_implicit_new_settings():
    value = {"kind": "zx", "categories": ["wild"], "balanced": True}
    snapshot = {"seed": 123, "active_rules": ["randomizer"], "settings": {"rom_transformation": value}}
    assert transformation_options(snapshot).to_dict() == {key: item for key, item in value.items() if key != "kind"}


@pytest.mark.parametrize("change", [{"unknown": True}, {"wild_legendaries": 1}, {"trainer_mode": "champions_only"},
                                   {"wild_type_themed": True, "wild_similar_strength": True}])
def test_invalid_advanced_controls_fail_explicitly(change):
    with pytest.raises(ValueError):
        RandomizerOptions(advanced={**ADVANCED_DEFAULTS, **change})


def test_advanced_and_old_global_balance_cannot_conflict():
    with pytest.raises(ValueError):
        RandomizerOptions(balanced=True, advanced=dict(ADVANCED_DEFAULTS))


@pytest.mark.parametrize("mode", ["soft", "strict", "pure"])
def test_monotype_transformation_without_randomizer_rule(catalog, mode):
    challenge = ChallengeEngine(catalog).generate("white", "custom", {"monotype": "required"}, 0, 123)
    challenge.monotype.update(type_id="fire", mode=mode)
    options = RandomizerOptions(("starters",), monotype_starters=monotype(mode))
    challenge.settings["rom_transformation"] = {"kind": "zx", **options.to_dict()}
    assert not ChallengeEngine(catalog).validate(challenge)
    assert transformation_options(challenge.to_dict()) == options
    challenge.monotype["type_id"] = "water"
    with pytest.raises(ValueError, match="Monotype active"):
        transformation_options(challenge.to_dict())


def test_no_monotype_option_is_invented_for_old_snapshots(catalog):
    challenge = ChallengeEngine(catalog).generate("white", "custom", {"monotype": "required"}, 0, 123)
    original = deepcopy(challenge.to_dict())
    assert transformation_options(original) is None
    assert challenge.to_dict() == original


def test_advanced_properties_are_persisted_and_tool_must_confirm_them(transformation):
    options = RandomizerOptions(("shop_items",), advanced=dict(ADVANCED_DEFAULTS))
    data = report(categories=options.categories)
    transformation.changes["report"] = data
    with pytest.raises(ValueError, match="paramètres avancés"):
        transform(transformation, options=options)
    assert not transformation.destination.exists()


def test_applied_advanced_options_are_part_of_manifest(transformation):
    options = RandomizerOptions(("shop_items",), advanced=dict(ADVANCED_DEFAULTS))
    data = report(categories=options.categories)
    data.update(schema_version=2, adapter_options=options.adapter_properties())
    transformation.changes["report"] = data
    result = transform(transformation, options=options)
    assert result.manifest["options"] == options.to_dict()
    assert "wild_legendaries=false" in (result.rom_path.parent / "adapter.properties").read_text()


@pytest.mark.parametrize("mode,types,valid", [
    ("soft", ["water", "fire"], True), ("strict", ["water", "fire"], False),
    ("strict", ["fire", "flying"], True), ("pure", ["fire", "flying"], False), ("pure", ["fire"], True),
])
def test_monotype_report_checks_effective_types_not_original_species(tmp_path, mode, types, valid):
    options = RandomizerOptions(("starters",), monotype_starters=monotype(mode))
    data = report(categories=options.categories)
    data.update(schema_version=2, adapter_options=options.adapter_properties(), starters=[1, 2, 3])
    for row in data["pokemon"][:3]:
        row["types"] = types
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    if valid:
        assert RomTransformationService._validate_report(path, "IRAF", options)["starters"] == [1, 2, 3]
    else:
        with pytest.raises(ValueError, match="trois starters"):
            RomTransformationService._validate_report(path, "IRAF", options)


@pytest.mark.parametrize("starters", [[1, 1, 2], [1, 2], [True, 2, 3], [1, 2, 650]])
def test_monotype_report_requires_three_distinct_base_species(tmp_path, starters):
    options = RandomizerOptions(("starters",), monotype_starters=monotype())
    data = report(categories=options.categories)
    data.update(schema_version=2, adapter_options=options.adapter_properties(), starters=starters)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="trois starters"):
        RomTransformationService._validate_report(path, "IRAF", options)


def test_legacy_reports_without_new_categories_still_load(tmp_path):
    data = report()
    data["categories"] = {key: value for key, value in data["categories"].items() if key in LEGACY_CATEGORIES}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert RomTransformationService._validate_report(path, "IRAF", RandomizerOptions()) == data
    data["schema_version"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Empreinte"):
        RomTransformationService._validate_report(path, "IRAF", RandomizerOptions())


def test_presets_and_each_advanced_control_roundtrip(widget):
    widget.apply_preset("full")
    assert widget.options().categories == CATEGORIES
    widget.apply_preset("classic")
    assert widget.options() == RandomizerOptions()
    widget.apply_preset("custom")
    widget.advanced_checks["starter_legendaries"].setChecked(False)
    widget.advanced_checks["evolution_same_type"].setChecked(True)
    widget.trainer_mode.setCurrentIndex(widget.trainer_mode.findData("type_themed_elite4_gyms"))
    expected = widget.options()
    widget.set_options(expected)
    assert widget.options() == expected
    assert not expected.advanced["starter_legendaries"]
    assert expected.advanced["evolution_same_type"]


def test_monotype_new_editor_generates_patch_but_old_profile_does_not(page, catalog):
    page.state_controls["randomizer"].setCurrentIndex(2)
    page.state_controls["monotype"].setCurrentIndex(0)
    page.generate()
    assert page.challenge is not None
    options = transformation_options(page.challenge.to_dict())
    assert options.categories == ("starters",)
    assert options.monotype_starters["type_id"] == page.challenge.monotype["type_id"]
    old = ChallengeEngine(catalog).generate("white", "custom", {"monotype": "required"}, 0, 42)
    page.load_challenge(old)
    assert not page.monotype_starters_check.isChecked()
    page.generate()
    assert transformation_options(page.challenge.to_dict()) is None


def test_combination_preserves_independent_randomizer_and_monotype_options(page):
    page.state_controls["monotype"].setCurrentIndex(0)
    page.state_controls["shiny_only"].setCurrentIndex(0)
    options = RandomizerOptions(("wild", "types", "evolutions"), advanced=dict(ADVANCED_DEFAULTS, starter_mythicals=False))
    page.randomizer_widget.set_options(options)
    page.generate()
    assert page.challenge is not None
    combined = transformation_options(page.challenge.to_dict())
    assert set(combined.categories) == {*options.categories, "starters"}
    assert combined.advanced == options.advanced
    assert combined.monotype_starters["type_id"] == page.challenge.monotype["type_id"]
    assert "shiny_only" in page.challenge.active_rules
    assert "Taux original conservé" in page.preview.toPlainText()


@pytest.mark.parametrize("rules", [
    ("randomizer", "nuzlocke"),
    ("randomizer", "nuzlocke", "permanent_death", "level_cap", "no_items"),
    ("randomizer", "monotype"), ("randomizer", "shiny_only"),
    ("monotype", "shiny_only"), ("nuzlocke", "monotype"),
    ("randomizer", "monotype", "shiny_only", "unevolved", "no_evolution"),
])
def test_requested_combinations_preserve_each_rule_and_transformation(catalog, rules):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate("white", "custom", {rule: "required" for rule in rules}, 0, 123)
    categories = CATEGORIES if "randomizer" in rules else ("starters",)
    mono = {"type_id": challenge.monotype["type_id"], "mode": challenge.monotype["mode"], "prefer_evolutions": True} if "monotype" in rules else None
    options = RandomizerOptions(categories, advanced=dict(ADVANCED_DEFAULTS) if "randomizer" in rules else None, monotype_starters=mono)
    challenge.settings["rom_transformation"] = {"kind": "zx", **options.to_dict()}
    assert engine.validate(challenge) == []
    assert set(rules) <= set(challenge.active_rules)
    assert transformation_options(challenge.to_dict()) == options


def test_monotype_owned_pipeline_and_melonds_provider_preserve_sources(randomizer, catalog):
    env, tool = randomizer
    original = tree(env.source)
    challenge = ChallengeEngine(catalog).generate("white", "custom", {"monotype": "required"}, 0, 512)
    challenge.monotype["type_id"] = "fire"
    options = RandomizerOptions(("starters",), monotype_starters=monotype())
    challenge.settings["rom_transformation"] = {"kind": "zx", **options.to_dict()}
    data = report(categories=options.categories)
    data.update(schema_version=2, adapter_options=options.adapter_properties(), starters=[1, 2, 3])
    for row in data["pokemon"][:3]:
        row["types"] = ["fire"]
    tool.changes["report"] = data
    isolated = env.service.isolate(create(env, challenge=challenge))
    provider = RunTransformationProvider(env.manager.root)
    assert provider.for_run(isolated)["starters"] == (1, 2, 3)
    old = env.service.directory(isolated)
    new = old.with_name("play-melonds")
    old.rename(new)
    isolated.launch_profile["rom_path"] = str(new / "game" / f"{isolated.game_id}-{isolated.run_id}.nds")
    isolated.launch_profile["emulator_kind"] = "melonds"
    assert provider.for_run(isolated)["starters"] == (1, 2, 3)
    assert tree(env.source) == original


def test_mutated_advanced_dictionary_is_revalidated_before_tool(transformation):
    options = RandomizerOptions(advanced=dict(ADVANCED_DEFAULTS))
    options.advanced["trainer_mode"] = "invalid"
    with pytest.raises(ValueError, match="Mode des dresseurs"):
        transform(transformation, options=options)
    assert not transformation.calls


def test_historical_advanced_schema_roundtrips_without_implicit_options():
    from app.services.rom_transformation_service import LEGACY_ADVANCED_DEFAULTS
    legacy = dict(LEGACY_ADVANCED_DEFAULTS)
    options = RandomizerOptions(advanced=legacy)
    assert options.to_dict()["advanced"] == legacy
    assert options.adapter_properties() == {key: str(value).lower() for key, value in legacy.items()}
    assert "starter_similar_strength" not in options.to_dict()["advanced"]


@pytest.mark.parametrize("key,value", [
    ("wild_mode", "unknown"), ("wild_mode", True), ("evolution_mode", "invalid"),
    ("starter_similar_strength", 1), ("evolution_fix_impossible", "true"),
])
def test_extended_modes_and_flags_reject_invalid_values(key, value):
    with pytest.raises(ValueError):
        RandomizerOptions(advanced={**ADVANCED_DEFAULTS, key: value})


def test_global_mapping_rejects_zone_themes():
    with pytest.raises(ValueError, match="globale"):
        RandomizerOptions(advanced=dict(ADVANCED_DEFAULTS, wild_mode="global_mapping", wild_type_themed=True))


def test_preserved_evolution_targets_require_method_correction_and_no_random_target_constraints():
    with pytest.raises(ValueError, match="impossibles"):
        RandomizerOptions(("evolutions",), advanced=dict(ADVANCED_DEFAULTS, evolution_mode="unchanged"))
    advanced = dict(ADVANCED_DEFAULTS, evolution_mode="unchanged", evolution_fix_impossible=True)
    assert RandomizerOptions(("evolutions",), advanced=advanced).advanced == advanced
    for key in ("evolution_similar_strength", "evolution_same_type", "evolution_three_stages", "evolution_force_change"):
        with pytest.raises(ValueError, match="cibles"):
            RandomizerOptions(("evolutions",), advanced={**advanced, key: True})


@pytest.mark.parametrize("wild_mode", ["random", "area_mapping", "global_mapping"])
@pytest.mark.parametrize("trainer_mode", ["distributed", "main_playthrough"])
def test_new_randomizer_controls_roundtrip(widget, wild_mode, trainer_mode):
    advanced = dict(ADVANCED_DEFAULTS, wild_mode=wild_mode, trainer_mode=trainer_mode,
                    starter_similar_strength=True, evolution_mode="unchanged", evolution_fix_impossible=True)
    options = RandomizerOptions(CATEGORIES, advanced=advanced)
    widget.set_options(options)
    assert widget.options() == options
    assert options.transformation_order() == ["upr-zx-4.6.1", "pce-starters-v1"]
    assert options.adapter_properties()["starter_similar_strength"] == "true"


def test_legacy_advanced_editor_uses_neutral_defaults_for_new_controls(widget):
    from app.services.rom_transformation_service import LEGACY_ADVANCED_DEFAULTS
    widget.set_options(RandomizerOptions(advanced=dict(LEGACY_ADVANCED_DEFAULTS)))
    assert widget.options().advanced == ADVANCED_DEFAULTS


def test_deselected_categories_keep_dormant_options_without_conflicts():
    advanced = dict(ADVANCED_DEFAULTS, wild_mode="global_mapping", wild_type_themed=True,
                    wild_similar_strength=True, evolution_mode="unchanged", evolution_force_change=True)
    options = RandomizerOptions(("starters",), advanced=advanced)
    assert options.advanced == advanced
    assert options.transformation_order() == ["upr-zx-4.6.1"]


def test_historical_advanced_manifest_keeps_its_provenance(transformation):
    from app.services.rom_transformation_service import LEGACY_ADVANCED_DEFAULTS, verified_transformation_report
    options = RandomizerOptions(advanced=dict(LEGACY_ADVANCED_DEFAULTS))
    data = report(categories=options.categories)
    data.update(schema_version=2, adapter_options=options.adapter_properties())
    transformation.changes["report"] = data
    result = transform(transformation, options=options)
    configuration = {"seed": 512, "active_rules": ["randomizer"],
                     "settings": {"rom_transformation": {"kind": "zx", **options.to_dict()}}}
    reread = verified_transformation_report(result.rom_path.parent, result.rom_path, game_id="white",
                                            rom_sha256=result.manifest["output_sha256"], configuration=configuration)
    assert reread == data
    assert result.manifest["options"]["advanced"] == LEGACY_ADVANCED_DEFAULTS


def test_monotype_only_starter_options_roundtrip_without_enabling_randomizer(page):
    page.state_controls["randomizer"].setCurrentIndex(2)
    page.state_controls["monotype"].setCurrentIndex(0)
    page.monotype_starter_checks["starter_legendaries"].setChecked(False)
    page.monotype_starter_checks["starter_mythicals"].setChecked(False)
    page.monotype_starter_checks["starter_similar_strength"].setChecked(True)
    page.monotype_prefer_evolutions_check.setChecked(False)
    page.generate()
    assert page.challenge is not None
    assert "randomizer" not in page.challenge.active_rules
    expected = transformation_options(page.challenge.to_dict())
    assert expected.categories == ("starters",)
    assert not expected.advanced["starter_legendaries"]
    assert not expected.advanced["starter_mythicals"]
    assert expected.advanced["starter_similar_strength"]
    assert not expected.monotype_starters["prefer_evolutions"]
    page.load_challenge(page.challenge)
    page.generate()
    assert transformation_options(page.challenge.to_dict()) == expected


def test_monotype_only_cannot_smuggle_other_randomizer_options(catalog):
    challenge = ChallengeEngine(catalog).generate("white", "custom", {"monotype": "required"}, 0, 123)
    challenge.monotype.update(type_id="fire", mode="soft")
    options = RandomizerOptions(("starters",), advanced=dict(ADVANCED_DEFAULTS, wild_legendaries=True),
                                monotype_starters=monotype())
    challenge.settings["rom_transformation"] = {"kind": "zx", **options.to_dict()}
    with pytest.raises(ValueError, match="Randomizer inactif"):
        transformation_options(challenge.to_dict())


def test_monotype_combination_keeps_randomizer_starter_filters_and_evolution_preference(page):
    page.state_controls["monotype"].setCurrentIndex(0)
    advanced = dict(ADVANCED_DEFAULTS, starter_legendaries=False, starter_mythicals=False)
    page.randomizer_widget.set_options(RandomizerOptions(CATEGORIES, advanced=advanced))
    page.monotype_prefer_evolutions_check.setChecked(False)
    page.generate()
    expected = transformation_options(page.challenge.to_dict())
    assert expected.advanced == advanced
    assert not expected.monotype_starters["prefer_evolutions"]
    page.load_challenge(page.challenge)
    page.generate()
    assert transformation_options(page.challenge.to_dict()) == expected
