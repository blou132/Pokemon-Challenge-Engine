"""Catalogues partagés par les tests métier, sans interface graphique."""

from pathlib import Path

import pytest

from app.core.catalog import Catalog
from app.core.rule_engine import RuleEngine


@pytest.fixture(scope="session")
def catalog():
    return Catalog.load(Path(__file__).resolve().parents[1] / "data")


@pytest.fixture(scope="session")
def rule_engine(catalog):
    return RuleEngine(catalog.rules.values())
