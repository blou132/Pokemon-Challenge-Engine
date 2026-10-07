"""Préparation d'un challenge ; les validations restent dans le moteur."""

import logging
import secrets

from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTextBrowser, QWidget,
)

from app.core.catalog import Catalog
from app.core.challenge_engine import ChallengeEngine
from app.core.monotype import select_type
from app.core.profile_manager import ProfileManager
from app.core.random_selector import RandomSelector
from app.core.rule_engine import RuleEngine
from app.models.challenge import Challenge
from app.ui.monotype_wheel import MonotypeDialog
from app.ui.widgets.common import MODE_LABELS, STATUS_LABELS, card, label, page_layout

LOGGER = logging.getLogger(__name__)
STATES = [("✓ Obligatoire", "required"), ("? Possible", "possible"), ("× Interdite", "forbidden")]


def challenge_summary(challenge: Challenge, catalog: Catalog) -> str:
    """Résumé texte partagé entre aperçu et consultation de profil."""
    game = catalog.games.get(challenge.game_id)
    lines = [game.name if game else challenge.game_id, MODE_LABELS.get(challenge.mode, challenge.mode),
             f"Seed : {challenge.seed}", "", f"{len(challenge.active_rules)} règle(s) active(s)"]
    for rule_id in challenge.active_rules:
        rule = catalog.rules.get(rule_id)
        lines.append("• " + (rule.name if rule else rule_id))
    if challenge.monotype and "monotype" in challenge.active_rules:
        config = challenge.monotype
        type_name = next((t["name"] for t in catalog.types if t["id"] == config["type_id"]), config["type_id"])
        mode = {"soft": "Souple", "strict": "Strict", "pure": "Pur"}[config["mode"]]
        lines.extend(["", f"Monotype : {type_name} · {mode}", f"Tirage n° {config['roll_index'] + 1}"])
    parameters = challenge.settings.get("rule_parameters", {})
    for rule_id, values in parameters.items():
        if rule_id in challenge.active_rules and values:
            rule = catalog.rules.get(rule_id)
            for key, value in values.items():
                name = rule.parameters.get(key, {}).get("label", key) if rule else key
                lines.append(f"{name} : {value}")
    enforcement = challenge.settings.get("enforcement", "soft")
    lines.extend(["", "Mode de suivi : Suivi uniquement" if enforcement == "soft" else
                  "Mode de suivi : Application stricte demandée, non disponible",
                  f"Règles configurées : {len(challenge.active_rules)}",
                  "Règles détectées automatiquement : selon les données disponibles ; détection des captures non disponible",
                  "Règles imposées directement dans le jeu : aucune"])
    return "\n".join(lines)


class ChallengePage(QWidget):
    back_requested = Signal()
    saved = Signal(object)
    launch_requested = Signal(object)

    def __init__(self, catalog: Catalog, profiles: ProfileManager | None, parent: QWidget | None = None,
                 *, configuration_only: bool = False) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.profiles = profiles
        self.configuration_only = configuration_only
        self.engine = ChallengeEngine(catalog)
        self.selector = RandomSelector(RuleEngine(catalog.rules.values()))
        self.challenge: Challenge | None = None
        self.monotype_config: dict | None = None
        self._building = True
        self.state_controls: dict[str, QComboBox] = {}
        self.parameter_controls: dict[str, dict[str, QSpinBox]] = {}
        self._generated_parameter_rules = set()
        self._generated_parameter_signature = None
        layout = page_layout(self, "Configurer le challenge" if configuration_only else "Configurer un modèle",
                             "Ces règles seront copiées directement dans votre partie." if configuration_only else
                             "Composez des règles réutilisables. Chaque sauvegarde crée un nouveau modèle pour vos aventures dans Mes parties.")
        self.back_button = QPushButton("← Modèles de challenge")
        self.back_button.clicked.connect(self.back_requested.emit)
        layout.addWidget(self.back_button)
        self.back_button.setVisible(not configuration_only)
        layout.addWidget(self._build_options())
        layout.addWidget(self._build_rules())
        layout.addWidget(self._build_extras())
        layout.addWidget(self._build_result())
        layout.addStretch()
        self.mode_combo.currentIndexChanged.connect(self._constraints_changed)
        self.game_combo.currentIndexChanged.connect(self._constraints_changed)
        self.count_spin.valueChanged.connect(self.invalidate)
        self.enforcement_combo.currentIndexChanged.connect(self.invalidate)
        self.seed_edit.textChanged.connect(self._seed_changed)
        # Un choix utilisateur réapplique aussi le preset déjà affiché.
        self.preset_combo.activated.connect(self.apply_preset)
        self._building = False
        # Commencer sur un preset concret, modifiable immédiatement.
        self.apply_preset()

    def _build_options(self) -> QWidget:
        """Construire les choix de jeu, de mode et de reproductibilité."""
        options, box = card("01  /  Préparer la partie" if self.configuration_only else "01  /  Préparer le modèle")
        grid = QGridLayout()
        self.game_combo = QComboBox()
        for game in self.catalog.games.values():
            if game.status == "supported":
                self.game_combo.addItem(game.name, game.id)
        self.mode_combo = QComboBox()
        for value, text in MODE_LABELS.items():
            self.mode_combo.addItem(text, value)
        self.preset_combo = QComboBox()
        for preset in self.catalog.presets:
            self.preset_combo.addItem(preset["name"], preset["id"])
        self.enforcement_combo = QComboBox()
        self.enforcement_combo.addItem("Suivi uniquement", "soft")
        self.enforcement_combo.addItem("Application stricte prévue · non appliquée", "strict")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, len(self.catalog.rules))
        self.count_spin.setValue(5)
        self.count_spin.setToolTip("Total de règles, obligations et dépendances comprises.")
        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("Aléatoire, ou saisir une seed")
        self.seed_edit.setMaxLength(19)
        self.seed_edit.setToolTip("Entier positif. Même seed et mêmes réglages : même challenge.")
        random_seed = QPushButton("Nouvelle seed")
        random_seed.clicked.connect(self.new_seed)
        seed_row = QHBoxLayout()
        seed_row.addWidget(self.seed_edit, 1)
        seed_row.addWidget(random_seed)
        for row, left, right in [(0, ("Jeu", self.game_combo), ("Preset", self.preset_combo)),
                                 (1, ("Mode de challenge", self.mode_combo), ("Application des règles", self.enforcement_combo))]:
            for col, (text, widget) in enumerate((left, right)):
                grid.addWidget(label(text, "muted"), row * 2, col)
                grid.addWidget(widget, row * 2 + 1, col)
        grid.addWidget(label("Nombre total de règles", "muted"), 4, 0)
        grid.addWidget(label("Reproductibilité", "muted"), 4, 1)
        grid.addWidget(self.count_spin, 5, 0)
        grid.addLayout(seed_row, 5, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(20)
        box.addLayout(grid)
        box.addWidget(label("Les presets sont des propositions de départ ; leurs définitions peuvent varier selon les communautés.", "muted"))
        return options

    def _build_rules(self) -> QWidget:
        """Construire la table des règles et l'indication des totaux possibles."""
        rules_card, rules_box = card("02  /  Composer les règles")
        self.state_summary = label("", "badge")
        rules_box.addWidget(self.state_summary)
        rules_box.addWidget(label("Personnalisé : seules les obligations et leurs dépendances sont retenues. Aléatoire : les règles possibles complètent le total.", "muted"))
        self.rules_table = QTableWidget(len(self.catalog.rules), 3)
        self.rules_table.setHorizontalHeaderLabels(["Règle", "Niveau de support", "Votre choix"])
        self.rules_table.verticalHeader().hide()
        self.rules_table.setShowGrid(False)
        self.rules_table.setAlternatingRowColors(True)
        self.rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rules_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.rules_table.setMinimumHeight(320)
        self.rules_table.setMaximumHeight(450)
        self.rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.rules_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.rules_table.setColumnWidth(2, 178)
        for row, rule in enumerate(self.catalog.rules.values()):
            item = QTableWidgetItem(rule.name)
            required_names = ", ".join(self.catalog.rules[r].name for r in rule.requires)
            conflict_names = ", ".join(self.catalog.rules[r].name for r in rule.conflicts_with)
            item.setToolTip(rule.description + (f"\nNécessite : {required_names}" if required_names else "") + (f"\nIncompatible avec : {conflict_names}" if conflict_names else ""))
            self.rules_table.setItem(row, 0, item)
            self.rules_table.setItem(row, 1, QTableWidgetItem(STATUS_LABELS[rule.implementation_status]))
            combo = QComboBox()
            for text, value in STATES:
                combo.addItem(text, value)
            combo.setCurrentIndex(1)
            combo.setAccessibleName(f"État de la règle {rule.name}")
            combo.currentIndexChanged.connect(self._constraints_changed)
            self.rules_table.setCellWidget(row, 2, combo)
            self.rules_table.setRowHeight(row, 46)
            self.state_controls[rule.id] = combo
        rules_box.addWidget(self.rules_table)
        self.capacity_label = label("", "muted")
        rules_box.addWidget(self.capacity_label)
        return rules_card

    def _build_extras(self) -> QWidget:
        """Construire la roue Monotype et les paramètres décrits par le catalogue."""
        extras, extras_box = card("03  /  Affiner le challenge")
        self.extras_card = extras
        self.monotype_row = QWidget()
        mono_row = QHBoxLayout(self.monotype_row)
        mono_row.setContentsMargins(0, 0, 0, 0)
        self.monotype_label = label("Monotype · 17 types de la génération V", "subtitle")
        self.wheel_button = QPushButton("Ouvrir la roue des types")
        self.wheel_button.clicked.connect(self.open_wheel)
        mono_row.addWidget(self.monotype_label, 1)
        mono_row.addWidget(self.wheel_button)
        extras_box.addWidget(self.monotype_row)
        self.monotype_note = label("La roue configure le type de la règle Monotype active. Sans tirage manuel, le type est déterminé par la seed.", "muted")
        extras_box.addWidget(self.monotype_note)
        form = self.parameter_form = QFormLayout()
        for rule in self.catalog.rules.values():
            if not rule.parameters:
                continue
            self.parameter_controls[rule.id] = {}
            for key, schema in rule.parameters.items():
                spin = QSpinBox()
                spin.setRange(schema["min"], schema["max"])
                spin.setValue(schema["default"])
                spin.valueChanged.connect(self.invalidate)
                # per_zone appartient exclusivement à catch_limit, pas à Nuzlocke.
                spin.setToolTip(f"Paramètre de la règle {rule.name}, utilisé seulement lorsqu'elle est active.")
                form.addRow(f"{rule.name} · {schema['label']}", spin)
                self.parameter_controls[rule.id][key] = spin
        extras_box.addLayout(form)
        return extras

    def _build_result(self) -> QWidget:
        """Construire l'aperçu du challenge et ses actions de sauvegarde/lancement."""
        result, result_box = card("04  /  Votre challenge")
        generate_row = QHBoxLayout()
        self.generate_button = QPushButton("Générer le challenge")
        self.generate_button.setObjectName("primary")
        self.generate_button.clicked.connect(self.generate)
        generate_row.addWidget(self.generate_button)
        generate_row.addWidget(label("Un tirage exact, sans doublon, avec une seed conservée.", "muted"), 1)
        result_box.addLayout(generate_row)
        self.feedback = label("")
        self.feedback.hide()
        result_box.addWidget(self.feedback)
        self.preview = QTextBrowser()
        self.preview.setMinimumHeight(240)
        self.preview.setPlainText("Votre aperçu apparaîtra ici après la génération.")
        result_box.addWidget(self.preview)
        action_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nom du modèle, par exemple Classic Nuzlocke")
        self.name_edit.setMaxLength(100)
        self.save_button = QPushButton("Sauvegarder le modèle")
        self.save_button.clicked.connect(self.save_profile)
        self.launch_button = QPushButton("Lancer directement dans DeSmuME")
        self.launch_button.clicked.connect(self.request_launch)
        action_row.addWidget(self.name_edit, 1)
        action_row.addWidget(self.save_button)
        result_box.addLayout(action_row)
        self.legacy_toggle = QPushButton("▸ Lancement direct historique")
        self.legacy_toggle.setCheckable(True)
        result_box.addWidget(self.legacy_toggle)
        legacy, legacy_box = card()
        legacy_box.addWidget(label("Ce lancement ne crée pas de partie. Pour une aventure avec sa propre progression, utilisez Mes parties.", "muted"))
        legacy_box.addWidget(self.launch_button)
        result_box.addWidget(legacy)
        legacy.hide()
        self.legacy_toggle.toggled.connect(legacy.setVisible)
        self.legacy_toggle.toggled.connect(lambda expanded: self.legacy_toggle.setText(
            ("▾" if expanded else "▸") + " Lancement direct historique"))
        if self.configuration_only:
            for widget in (self.name_edit, self.save_button, self.launch_button, self.legacy_toggle):
                widget.hide()
        result_box.addWidget(label("Les règles sont copiées dans la partie, sans créer de modèle. Aucune règle n'est imposée directement dans Pokémon."
                                  if self.configuration_only else
                                  "Un modèle conserve des règles réutilisables ; chaque partie aura sa propre progression. Aucune règle n'est imposée directement dans Pokémon.", "muted"))
        return result

    def states(self) -> dict[str, str]:
        return {key: combo.currentData() for key, combo in self.state_controls.items()}

    def invalidate(self, *_args: object) -> None:
        if self._building:
            return
        self.challenge = None
        self.save_button.setEnabled(False)
        self.launch_button.setEnabled(False)
        self.feedback.hide()
        self.preview.setPlainText("Réglages modifiés. Générez le challenge pour obtenir un aperçu à jour.")
        self.update_rule_parameter_visibility()

    def _seed_changed(self, *_args: object) -> None:
        """Une nouvelle seed conserve les préférences, mais exige un nouveau type."""
        if self._building:
            return
        self.invalidate()
        if self.monotype_config is not None:
            # État temporaire de l'éditeur : aucun profil incomplet n'est sauvegardé.
            self.monotype_config.pop("type_id", None)
            self.monotype_config["roll_index"] = 0
            self.update_monotype_label()

    def _constraints_changed(self, *_args: object) -> None:
        if self._building:
            return
        self.invalidate()
        game_id = self.game_combo.currentData()
        normal = self.mode_combo.currentData() == "normal"
        self.rules_table.setEnabled(not normal)
        for rule_id, combo in self.state_controls.items():
            games = self.catalog.rules[rule_id].supported_games
            supported = not games or game_id in games
            combo.setEnabled(supported)
            if not supported:
                with QSignalBlocker(combo):
                    combo.setCurrentIndex(2)
            state = combo.currentData()
            if combo.property("state") != state:
                combo.setProperty("state", state)
                combo.style().unpolish(combo)
                combo.style().polish(combo)
                combo.update()
        states = self.states()
        self.state_summary.setText(f"{list(states.values()).count('required')} obligatoires   ·   {list(states.values()).count('possible')} possibles   ·   {list(states.values()).count('forbidden')} interdites")
        self.count_spin.setEnabled(self.mode_combo.currentData() == "random")
        self.update_rule_parameter_visibility()
        if normal:
            self.capacity_label.setText("Partie normale : aucune règle active.")
            return
        try:
            counts = self.selector.feasible_counts(game_id, states)
            self.count_spin.setMaximum(max(counts) if counts else 0)
            self.capacity_label.setText("Totaux compatibles : " + (", ".join(map(str, counts)) if counts else "aucun — modifiez les obligations ou interdictions."))
        except ValueError as exc:
            self.capacity_label.setText(str(exc))

    def apply_preset(self, *_args: object) -> None:
        if self._building:
            return
        preset = next(p for p in self.catalog.presets if p["id"] == self.preset_combo.currentData())
        self._building = True
        for rule_id, combo in self.state_controls.items():
            combo.setCurrentIndex(0 if rule_id in preset["required"] else 1)
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(preset["mode"]))
        self.count_spin.setMaximum(len(self.catalog.rules))
        self.count_spin.setValue(preset["count"])
        self._building = False
        self._constraints_changed()

    def new_seed(self) -> None:
        self.seed_edit.setText(str(secrets.randbelow(2**63)))

    def seed_value(self) -> int:
        if not self.seed_edit.text().strip():
            self.new_seed()
        text = self.seed_edit.text().strip()
        if not text.isascii() or not text.isdecimal() or int(text) >= 2**63:
            raise ValueError("La seed doit être un entier entre 0 et 9223372036854775807.")
        return int(text)

    def show_feedback(self, text: str, success: bool = False) -> None:
        self.feedback.setObjectName("success" if success else "error")
        self.feedback.setText(text)
        self.feedback.style().unpolish(self.feedback)
        self.feedback.style().polish(self.feedback)
        self.feedback.show()

    def open_wheel(self) -> None:
        if "monotype" not in self._editor_active_rules():
            return
        try:
            seed = self.seed_value()
        except ValueError as exc:
            self.show_feedback(str(exc))
            return
        dialog = MonotypeDialog(self.catalog.types, seed, self.monotype_config, self)
        if dialog.exec() == MonotypeDialog.DialogCode.Accepted:
            self.monotype_config = dialog.configuration()
            self.invalidate()
            self.update_monotype_label()

    def update_monotype_label(self) -> None:
        if "monotype" not in self._editor_active_rules():
            self.monotype_label.setText("Monotype non actif")
            return
        if self.monotype_config:
            selected_id = self.monotype_config.get("type_id")
            if selected_id is None:
                self.monotype_label.setText("Monotype · Seed modifiée · nouveau tirage requis")
            else:
                selected = next(t["name"] for t in self.catalog.types if t["id"] == selected_id)
                mode = {"soft": "Souple", "strict": "Strict", "pure": "Pur"}[self.monotype_config["mode"]]
                self.monotype_label.setText(f"Monotype · {selected} · {mode} · tirage {self.monotype_config['roll_index'] + 1}")
        else:
            self.monotype_label.setText("Monotype · 17 types de la génération V")

    def _parameter_signature(self):
        return (self.game_combo.currentData(), self.mode_combo.currentData(), tuple(self.states().items()),
                self.count_spin.value(), self.seed_edit.text())

    def _editor_active_rules(self):
        if self.challenge is not None:
            return set(self.challenge.active_rules)
        if self.mode_combo.currentData() == "normal":
            return set()
        if self._generated_parameter_signature == self._parameter_signature():
            return self._generated_parameter_rules
        return self.engine.rule_engine.dependency_closure(
            rule_id for rule_id, state in self.states().items() if state == "required")

    def update_rule_parameter_visibility(self):
        active = self._editor_active_rules()
        if self.challenge is not None:
            self._generated_parameter_rules = active
            self._generated_parameter_signature = self._parameter_signature()
        monotype_active = "monotype" in active
        self.monotype_row.setVisible(monotype_active)
        self.monotype_note.setVisible(monotype_active)
        self.wheel_button.setEnabled(monotype_active)
        for rule_id, controls in self.parameter_controls.items():
            for control in controls.values():
                self.parameter_form.setRowVisible(control, rule_id in active)
                control.setEnabled(rule_id in active)
        self.extras_card.setVisible(monotype_active or bool(active & self.parameter_controls.keys()))
        self.update_monotype_label()

    def generate(self) -> None:
        try:
            seed = self.seed_value()
            monotype = dict(self.monotype_config) if self.monotype_config else None
            if monotype and not monotype.get("type_id"):
                monotype["type_id"] = select_type(monotype["allowed_types"], seed, monotype["roll_index"])
            parameters = {rule: {key: spin.value() for key, spin in values.items()} for rule, values in self.parameter_controls.items()}
            self.challenge = self.engine.generate(
                self.game_combo.currentData(), self.mode_combo.currentData(), self.states(),
                self.count_spin.value(), seed,
                settings={"enforcement": self.enforcement_combo.currentData(), "rule_parameters": parameters,
                          "preset_id": self._current_preset_id()},
                monotype=monotype,
            )
        except ValueError as exc:
            self.invalidate()
            self.show_feedback(str(exc))
            return
        self.preview.setPlainText(challenge_summary(self.challenge, self.catalog))
        if self.challenge.monotype:
            self.monotype_config = dict(self.challenge.monotype)
            self.update_monotype_label()
        self.update_rule_parameter_visibility()
        self.save_button.setEnabled(True)
        self.launch_button.setEnabled(True)
        self.show_feedback("Configuration prête. Utilisez cette configuration pour revenir à la création de votre partie."
                           if self.configuration_only else
                           "Aperçu non enregistré. Sauvegardez pour créer un modèle avec ces règles ; les modèles existants restent inchangés.", success=True)

    def _current_preset_id(self) -> str:
        """A modified starting preset becomes custom; no preset is reapplied on restore."""
        selected = self.preset_combo.currentData()
        preset = next((item for item in self.catalog.presets if item["id"] == selected), None)
        if preset is None or self.mode_combo.currentData() != preset["mode"]:
            return "custom"
        expected_states = {rule_id: "required" if rule_id in preset["required"] else "possible"
                           for rule_id in self.state_controls}
        if self.states() != expected_states:
            return "custom"
        if preset["mode"] == "random" and self.count_spin.value() != preset["count"]:
            return "custom"
        return selected

    def save_profile(self) -> None:
        if self.challenge is None or self.configuration_only or self.profiles is None:
            return
        name = self.name_edit.text().strip()
        if not name:
            self.show_feedback("Donnez un nom au modèle avant de le sauvegarder.")
            self.name_edit.setFocus()
            return
        try:
            # Serialize the displayed challenge once, then verify exactly that
            # payload after the write. Never regenerate a normal default here.
            expected = self.challenge.to_dict()
            profile = self.profiles.create(name, Challenge.from_dict(expected))
            verified = self.profiles.load(profile.id)
            if verified.challenge.to_dict() != expected:
                raise ValueError("La relecture du modèle ne correspond pas à l'aperçu. Vérifiez le modèle créé avant de continuer.")
        except (ValueError, OSError) as exc:
            LOGGER.warning("Impossible de sauvegarder un profil : %s", type(exc).__name__)
            self.show_feedback(str(exc))
            return
        self.show_feedback(f"Modèle « {verified.name} » sauvegardé et relu : "
                           f"{MODE_LABELS.get(verified.challenge.mode, verified.challenge.mode)}, "
                           f"{len(verified.challenge.active_rules)} règle(s). Chaque sauvegarde crée un modèle distinct.", success=True)
        LOGGER.info("Profil vérifié après sauvegarde : id=%s, jeu=%s, mode=%s, règles=%d",
                    verified.id, verified.challenge.game_id, verified.challenge.mode, len(verified.challenge.active_rules))
        self.saved.emit(verified)

    def request_launch(self) -> None:
        if self.challenge is not None and not self.configuration_only:
            self.launch_requested.emit(self.challenge)

    def load_challenge(self, challenge: Challenge, name: str = "") -> None:
        """Reprendre une configuration crée ensuite une copie, sans écrasement."""
        errors = self.engine.validate(challenge)
        if errors:
            self.show_feedback("\n".join(errors))
            return
        self._building = True
        # Optional provenance in settings keeps the V0.1 challenge schema intact.
        # Older profiles or customized presets keep the Custom label; their exact
        # states remain authoritative, never replaced by a catalog preset.
        saved_preset = challenge.settings.get("preset_id", "custom")
        if not isinstance(saved_preset, str) or self.preset_combo.findData(saved_preset) < 0:
            saved_preset = "custom"
        with QSignalBlocker(self.preset_combo):
            self.preset_combo.setCurrentIndex(self.preset_combo.findData(saved_preset))
        self.game_combo.setCurrentIndex(self.game_combo.findData(challenge.game_id))
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(challenge.mode))
        for rule_id, combo in self.state_controls.items():
            combo.setCurrentIndex(combo.findData(challenge.rule_states.get(rule_id, "possible")))
        self.count_spin.setMaximum(len(self.catalog.rules))
        self.count_spin.setValue(len(challenge.active_rules))
        self.seed_edit.setText(str(challenge.seed))
        self.enforcement_combo.setCurrentIndex(self.enforcement_combo.findData(challenge.settings.get("enforcement", "soft")))
        for rule_id, values in self.parameter_controls.items():
            for key, control in values.items():
                control.setValue(challenge.settings.get("rule_parameters", {}).get(rule_id, {}).get(key, self.catalog.rules[rule_id].parameters[key]["default"]))
        self.monotype_config = dict(challenge.monotype) if challenge.monotype else None
        self.name_edit.setText(name + " · copie" if name else "")
        self._building = False
        self._constraints_changed()
        self.update_monotype_label()
        self.challenge = challenge
        self.update_rule_parameter_visibility()
        self.preview.setPlainText(challenge_summary(challenge, self.catalog))
        self.save_button.setEnabled(True)
        self.launch_button.setEnabled(True)
