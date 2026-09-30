"""Un catalogue corrompu produit une erreur précise, avant d'afficher l'interface."""

import json
from pathlib import Path
import shutil

import pytest

from app.core.catalog import Catalog
from app.models.game import Game


@pytest.fixture
def data_dir(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data"
    target = tmp_path / "data"
    shutil.copytree(source, target)
    return target


def _mutate(data_dir, filename, change):
    path = data_dir / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_catalog_contains_expected_base(catalog):
    assert {game.id for game in catalog.games.values() if game.status == "supported"} == {"black", "white", "black2", "white2"}
    assert len(catalog.rules) == 15
    assert {preset["id"] for preset in catalog.presets} == {"classic_nuzlocke", "hardcore_nuzlocke", "monotype", "chaos", "custom"}


@pytest.mark.parametrize("game_id,name,code", [
    ("black", "Pokémon Noir", "IRBF"), ("white", "Pokémon Blanc", "IRAF"),
    ("black2", "Pokémon Noir 2", "IREF"), ("white2", "Pokémon Blanc 2", "IRDF"),
])
def test_gen5_catalog_has_distinct_french_identity(catalog, game_id, name, code):
    game = catalog.games[game_id]
    assert (game.name, game.generation, game.platform) == (name, 5, "Nintendo DS")
    assert (game.game_code, game.region, game.revision) == (code, "FR", 0)
    assert game.status == "supported" and game.supports_desmume
    assert all(game_id in rule.supported_games for rule in catalog.rules.values())


def test_catalog_and_game_from_v01_remain_compatible(data_dir):
    _mutate(data_dir, "games.json", lambda rows: [row.pop(key, None) for row in rows
                                                for key in ("game_code", "region", "revision")])
    game = Catalog.load(data_dir).games["black"]
    assert (game.game_code, game.region, game.revision) == (None, None, None)
    assert Game("custom", "Ancien jeu", 5, "Nintendo DS", 17, True, True, "supported").game_code is None


@pytest.mark.parametrize("filename,change,match", [
    ("games.json", lambda rows: rows.append(rows[0]), "dupliqué"),
    ("games.json", lambda rows: rows[0].update(generation=True), "entier"),
    ("games.json", lambda rows: rows[0].update(supports_monotype="yes"), "booléens"),
    ("games.json", lambda rows: rows[0].update(status="live"), "statut"),
    ("games.json", lambda rows: rows[0].update(game_code="IR"), "code de jeu"),
    ("games.json", lambda rows: rows[0].update(game_code=[]), "code de jeu"),
    ("games.json", lambda rows: rows[0].update(region="XX"), "région"),
    ("games.json", lambda rows: rows[0].update(revision=True), "entier"),
    ("games.json", lambda rows: rows[0].update(revision=256), "entier"),
    ("games.json", lambda rows: rows[0].pop("revision"), "champs"),
    ("rules.json", lambda rows: rows[0].update(requires=["missing"]), "inconnue"),
    ("rules.json", lambda rows: rows[0].update(supported_games=["missing"]), "inconnu"),
    ("rules.json", lambda rows: rows[0].update(implementation_status="applied"), "statut"),
    ("rules.json", lambda rows: rows[0].update(requires=["nuzlocke"]), "elle-même"),
    ("rules.json", lambda rows: rows[1].update(requires=["nuzlocke"]), "Cycle"),
    ("rules.json", lambda rows: rows[0].update(conflicts_with=["permanent_death"]), "interdite"),
    ("rules.json", lambda rows: rows[0].update(parameters={"x": {"type": "integer"}}), "champs"),
    ("types_gen5.json", lambda rows: rows.append({"id": "fairy", "name": "Fée", "color": "#FFAAFF"}), "inconnu"),
    ("types_gen5.json", lambda rows: rows.pop(), "17 types"),
    ("types_gen5.json", lambda rows: rows[0].update(color="red"), "Couleur"),
    ("presets.json", lambda rows: rows[0].update(required=["missing"]), "inconnue"),
    ("presets.json", lambda rows: rows[0].update(count=1), "inférieur"),
    ("presets.json", lambda rows: rows[0].update(required=["species_clause"], count=1), "dépendances"),
    ("presets.json", lambda rows: rows[0].update(required=["nuzlocke", "solo_run"], count=3), "incompatibles"),
    ("rules.json", lambda rows: rows[1].update(conflicts_with=["species_clause"]), "incohérente"),
])
def test_invalid_catalog_rejected(data_dir, filename, change, match):
    _mutate(data_dir, filename, change)
    with pytest.raises(ValueError, match=match):
        Catalog.load(data_dir)


@pytest.mark.parametrize("content", ["{malformé", "[]", "{}", '[{"id":"x","id":"y"}]', '[{"id":NaN}]'])
def test_malformed_or_empty_json(data_dir, content):
    (data_dir / "games.json").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        Catalog.load(data_dir)


def test_missing_catalog_file(data_dir):
    (data_dir / "rules.json").unlink()
    with pytest.raises(ValueError, match="rules.json"):
        Catalog.load(data_dir)


@pytest.mark.parametrize("content", ['[' * 3000 + '0' + ']' * 3000, '[{"name":"\\ud800"}]'])
def test_deep_or_invalid_unicode_catalog_is_reported(data_dir, content):
    (data_dir / "games.json").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="games.json"):
        Catalog.load(data_dir)
