"""Présentation du Mode Jeu : aucune règle ni décision de capture dans l'UI."""

from copy import deepcopy

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.bridge.state import BridgeState
from app.core.catalog import Catalog
from app.models.profile import Profile
from app.services.game_mode_service import RunState
from app.services.tracking_service import TrackingState
from app.ui.widgets.common import MODE_LABELS, label
from app.ui.widgets.nuzlocke import NuzlockeWidget, UNAVAILABLE, species_name


BLOCK_LABELS = {
    "controls": "Contrôles", "team": "Équipe", "challenge": "Challenge", "zone": "Zone",
    "capture": "Capture", "deaths": "Morts", "badges": "Badges", "level_cap": "Level cap",
    "seed": "Seed", "speed": "Vitesse", "saves": "Sauvegardes", "logs": "Journal", "debug": "Diagnostic",
}
BUTTON_NAMES = {"Up": "Haut", "Down": "Bas", "Left": "Gauche", "Right": "Droite",
                "A": "A", "B": "B", "X": "X", "Y": "Y", "L": "L", "R": "R",
                "Start": "Start", "Select": "Select"}
_KEEP_SELECTION = object()


def _panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("gameCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(9)
    layout.addWidget(label(title.upper(), "eyebrow"))
    return frame, layout


class TeamSlot(QFrame):
    """Un emplacement connu de la passerelle, jamais rempli par extrapolation."""

    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.setObjectName("teamSlot")
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(4)
        self.name_label = label(f"{number:02} · {UNAVAILABLE}", "teamName")
        self.hp_label = label(UNAVAILABLE, "muted")
        self.hp_bar = QProgressBar()
        self.hp_bar.setTextVisible(False)
        self.hp_bar.setFixedHeight(4)
        self.hp_bar.setRange(0, 100)
        self.hp_bar.setValue(0)
        self.status_label = label("Statut : " + UNAVAILABLE, "teamStatus")
        layout.addWidget(self.name_label)
        layout.addWidget(self.hp_label)
        layout.addWidget(self.hp_bar)
        layout.addWidget(self.status_label)
        self.number = number

    def set_pokemon(self, pokemon: dict | None, *, known_empty=False):
        if pokemon is None:
            self.name_label.setText(f"{self.number:02} · " + ("Emplacement vide" if known_empty else UNAVAILABLE))
            self.hp_label.setText("—" if known_empty else UNAVAILABLE)
            self.status_label.setText("—" if known_empty else "Statut : " + UNAVAILABLE)
            self.hp_bar.setValue(0)
            self.hp_bar.setVisible(False)
            return
        level = pokemon.get("level")
        name = species_name(pokemon.get("species_id"))
        self.name_label.setText(name + (f" · N{level}" if level is not None else " · N?"))
        hp, maximum = pokemon.get("hp"), pokemon.get("max_hp")
        self.hp_label.setText(f"{hp} / {maximum} PV" if hp is not None and maximum is not None else UNAVAILABLE)
        self.hp_bar.setVisible(hp is not None and maximum is not None and maximum > 0)
        if hp is not None and maximum:
            self.hp_bar.setValue(round(100 * hp / maximum))
        self.status_label.setText("K.O." if hp == 0 else "Statut : " + UNAVAILABLE)


class GameModePage(QWidget):
    launch_requested = Signal(str)
    profile_requested = Signal(object)
    game_changed = Signal(str)
    settings_requested = Signal(str)
    speed_requested = Signal(str)
    backup_requested = Signal()
    fullscreen_requested = Signal()
    arrange_requested = Signal()

    def __init__(self, catalog: Catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self._profile: Profile | None = None
        self._profiles: dict[str, Profile] = {}
        self._bridge = BridgeState()
        self._run = RunState()
        self._interface = None
        self._panels_visible = True
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)
        heading = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(label("MODE JEU", "eyebrow"))
        title.addWidget(label("Votre aventure, à portée de main.", "gameTitle"))
        heading.addLayout(title)
        heading.addStretch()
        self.connection_badge = label("Lua · déconnecté", "badge")
        heading.addWidget(self.connection_badge)
        self.customize_button = QPushButton("Personnaliser")
        self.customize_button.clicked.connect(lambda: self.settings_requested.emit("interface"))
        heading.addWidget(self.customize_button)
        self.fullscreen_button = QPushButton("Plein écran")
        self.fullscreen_button.clicked.connect(self.fullscreen_requested)
        heading.addWidget(self.fullscreen_button)
        outer.addLayout(heading)

        selection = QHBoxLayout()
        self.game_combo = QComboBox()
        self.game_combo.setAccessibleName("Jeu du Mode Jeu")
        for game in catalog.games.values():
            if game.status == "supported":
                self.game_combo.addItem(game.name, game.id)
        self.game_combo.currentIndexChanged.connect(self._game_selected)
        selection.addWidget(self.game_combo, 2)
        self.profile_combo = QComboBox()
        self.profile_combo.setAccessibleName("Profil de challenge du Mode Jeu")
        self.profile_combo.addItem("Sans profil · diagnostic uniquement", None)
        self.profile_combo.currentIndexChanged.connect(self._profile_selected)
        selection.addWidget(self.profile_combo, 3)
        self.launch_profile_button = QPushButton("Profil de lancement")
        self.launch_profile_button.clicked.connect(lambda: self.settings_requested.emit("launch"))
        selection.addWidget(self.launch_profile_button)
        outer.addLayout(selection)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        self.left_scroll, self.left_layout = self._column()
        self.right_scroll, self.right_layout = self._column()
        self.left_scroll.setMinimumWidth(220)
        self.right_scroll.setMinimumWidth(300)
        columns.addWidget(self.left_scroll)
        self.center, center = _panel("DeSmuME standalone")
        self.center.setObjectName("gameStage")
        self.center.setMinimumWidth(280)
        self.window_title = label("Fenêtre externe", "sectionTitle")
        center.addWidget(self.window_title)
        center.addWidget(label("Votre jeu s'ouvre dans sa propre fenêtre.\nCe cadre indique la place réservée à DeSmuME.", "muted"))
        center.addStretch(1)
        screen = QFrame()
        screen.setObjectName("dsPlaceholder")
        screen.setMaximumWidth(410)
        screen.setMinimumHeight(240)
        screens = QVBoxLayout(screen)
        screens.setContentsMargins(15, 15, 15, 15)
        screens.setSpacing(12)
        for name in ("ÉCRAN SUPÉRIEUR", "ÉCRAN TACTILE"):
            text = label(name, "dsScreen")
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text.setMinimumHeight(95)
            screens.addWidget(text, 1)
        center.addWidget(screen, 1, Qt.AlignmentFlag.AlignHCenter)
        center.addStretch(1)
        self.launch_button = QPushButton("Lancer DeSmuME  →")
        self.launch_button.setObjectName("primary")
        self.launch_button.clicked.connect(lambda: self.launch_requested.emit(self.game_combo.currentData()))
        center.addWidget(self.launch_button)
        actions = QHBoxLayout()
        self.connect_button = QPushButton("Connexion Lua")
        self.connect_button.clicked.connect(lambda: self.settings_requested.emit("bridge"))
        self.arrange_button = QPushButton("Organiser les fenêtres")
        self.arrange_button.setToolTip("Déplace uniquement la fenêtre DeSmuME lancée ici, sur l'écran choisi.")
        self.arrange_button.clicked.connect(self.arrange_requested)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.arrange_button)
        center.addLayout(actions)
        self.status_label = label("Choisissez un jeu et un profil, puis lancez votre session.", "muted")
        center.addWidget(self.status_label)
        columns.addWidget(self.center, 1)
        columns.addWidget(self.right_scroll)
        outer.addLayout(columns, 1)
        self.blocks: dict[str, QWidget] = {}
        self._build_blocks()
        self.set_profile(None)
        self.set_bridge_state(BridgeState())
        self.set_tracking_state(TrackingState())
        self.set_interface({"density": "standard", "visible": {}, "sides": {}})

    @staticmethod
    def _column():
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(10)
        layout.addStretch()
        scroll.setWidget(content)
        return scroll, layout

    def _block(self, key):
        frame, layout = _panel(BLOCK_LABELS[key])
        self.blocks[key] = frame
        return layout

    def _build_blocks(self):
        controls = self._block("controls")
        self.controls_source = label("Mapping réel : " + UNAVAILABLE, "muted")
        controls.addWidget(self.controls_source)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.control_labels = {}
        for index, (key, text) in enumerate(BUTTON_NAMES.items()):
            grid.addWidget(label(text), index // 2, (index % 2) * 2)
            value = label("—", "keycap")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setMinimumWidth(38)
            value.setToolTip(UNAVAILABLE)
            self.control_labels[key] = value
            grid.addWidget(value, index // 2, (index % 2) * 2 + 1)
        controls.addLayout(grid)
        self.controller_label = label("Manette : " + UNAVAILABLE, "muted")
        controls.addWidget(self.controller_label)
        buttons = QHBoxLayout()
        for text in ("Modifier", "Réinitialiser"):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, action=text: self.settings_requested.emit(
                "controls_reset" if action == "Réinitialiser" else "controls"))
            buttons.addWidget(button)
        controls.addLayout(buttons)

        speed = self._block("speed")
        row = QHBoxLayout()
        self.speed_buttons = {}
        for text in ("x1", "x2", "x4", "MAX"):
            button = QPushButton(text)
            button.setObjectName("speedButton")
            button.setCheckable(True)
            button.setToolTip("État demandé ; aucune vitesse réelle n'est déduite de ce bouton.")
            button.clicked.connect(lambda checked=False, value=text: self.speed_requested.emit(value))
            row.addWidget(button)
            self.speed_buttons[text] = button
        speed.addLayout(row)
        self.speed_label = label("État demandé : x1\nÉtat réel : " + UNAVAILABLE, "muted")
        speed.addWidget(self.speed_label)

        saves = self._block("saves")
        self.save_policy_label = label("Save states : non géré", "muted")
        saves.addWidget(self.save_policy_label)
        self.manual_backup_button = QPushButton("Créer un backup")
        self.manual_backup_button.clicked.connect(self.backup_requested)
        saves.addWidget(self.manual_backup_button)
        self.save_manager_button = QPushButton("Gérer mes sauvegardes")
        self.save_manager_button.clicked.connect(lambda: self.settings_requested.emit("saves"))
        saves.addWidget(self.save_manager_button)

        challenge = self._block("challenge")
        self.profile_label = label("Sans profil", "sectionTitle")
        self.mode_label = label("Diagnostic uniquement", "muted")
        self.game_label = label(UNAVAILABLE, "muted")
        self.time_label = label("Session PCE : " + UNAVAILABLE, "muted")
        self.rules_label = label("Aucune règle sélectionnée", "muted")
        self.monotype_label = label("")
        self.randomizer_label = label("")
        for widget in (self.profile_label, self.game_label, self.mode_label, self.time_label,
                       self.rules_label, self.monotype_label, self.randomizer_label):
            challenge.addWidget(widget)

        team = self._block("team")
        self.team_note = label("Équipe : " + UNAVAILABLE, "muted")
        team.addWidget(self.team_note)
        slots = QGridLayout()
        slots.setSpacing(7)
        self.team_slots = [TeamSlot(index + 1) for index in range(6)]
        for index, slot in enumerate(self.team_slots):
            slots.addWidget(slot, index // 2, index % 2)
        slots.setColumnStretch(0, 1)
        slots.setColumnStretch(1, 1)
        team.addLayout(slots)

        zone = self._block("zone")
        self.zone_label = label(UNAVAILABLE, "sectionTitle")
        self.zone_map_label = label("Carte : " + UNAVAILABLE, "muted")
        zone.addWidget(self.zone_label)
        zone.addWidget(self.zone_map_label)
        self.nuzlocke_widget = NuzlockeWidget()
        self.blocks["capture"] = self.nuzlocke_widget

        self.stat_labels = {}
        for key in ("badges", "deaths", "level_cap", "seed"):
            box = self._block(key)
            value = label(UNAVAILABLE, "sectionTitle")
            box.addWidget(value)
            self.stat_labels[key] = value
        self.capture_count_label = label("Captures consignées : " + UNAVAILABLE, "muted")
        challenge.addWidget(self.capture_count_label)
        logs = self._block("logs")
        self.history_label = label("Aucun événement reçu", "muted")
        logs.addWidget(self.history_label)
        debug = self._block("debug")
        self.debug_label = label(UNAVAILABLE, "muted")
        debug.addWidget(self.debug_label)

    def set_profiles(self, profiles: list[Profile], selected_id=_KEEP_SELECTION):
        self._profiles = {profile.id: profile for profile in profiles}
        selected_id = self.profile_combo.currentData() if selected_id is _KEEP_SELECTION else selected_id
        with QSignalBlocker(self.profile_combo):
            self.profile_combo.clear()
            self.profile_combo.addItem("Sans profil · diagnostic uniquement", None)
            for profile in profiles:
                self.profile_combo.addItem(profile.name, profile.id)
            index = self.profile_combo.findData(selected_id)
            self.profile_combo.setCurrentIndex(max(index, 0))
        self.set_profile(self._profiles.get(self.profile_combo.currentData()))

    def _profile_selected(self, _index):
        profile_id = self.profile_combo.currentData()
        self.set_profile(self._profiles.get(profile_id))
        self.profile_requested.emit(profile_id)

    def _game_selected(self, _index):
        game_id = self.game_combo.currentData()
        if game_id:
            self.game_changed.emit(game_id)

    def set_profile(self, profile: Profile | None):
        self._profile = profile
        self.profile_label.setText(profile.name if profile else "Sans profil")
        challenge = profile.challenge if profile else None
        game = self.catalog.games.get(challenge.game_id) if challenge else None
        self.game_label.setText(game.name if game else UNAVAILABLE)
        self.mode_label.setText(MODE_LABELS.get(challenge.mode, UNAVAILABLE) if challenge else "Diagnostic uniquement")
        self.rules_label.setText("Règles sélectionnées :\n" + " · ".join(
            self.catalog.rules[item].name for item in challenge.active_rules if item in self.catalog.rules)
            if challenge and challenge.active_rules else "Aucune règle sélectionnée")
        if profile:
            with QSignalBlocker(self.game_combo):
                self.game_combo.setCurrentIndex(self.game_combo.findData(challenge.game_id))
        progress = profile.progress if profile else {}
        self.stat_labels["badges"].setText(str(len(progress["badges"])) if "badges" in progress else UNAVAILABLE)
        self.stat_labels["deaths"].setText(str(len(progress["deaths"])) if "deaths" in progress else UNAVAILABLE)
        self.stat_labels["level_cap"].setText(str(progress["current_level_cap"]) if progress.get("current_level_cap") is not None else UNAVAILABLE)
        self.stat_labels["seed"].setText(str(challenge.seed) if challenge else UNAVAILABLE)
        self.capture_count_label.setText("Captures consignées manuellement : " +
                                         (str(len(progress["captures"])) if "captures" in progress else UNAVAILABLE))
        monotype = challenge.monotype if challenge and "monotype" in challenge.active_rules else None
        self.monotype_label.setVisible(monotype is not None)
        if monotype:
            type_name = next((item["name"] for item in self.catalog.types if item["id"] == monotype["type_id"]), monotype["type_id"])
            mode = {"soft": "Souple", "strict": "Strict configuré, non appliqué",
                    "pure": "Pur configuré, non appliqué"}.get(monotype["mode"], UNAVAILABLE)
            self.monotype_label.setText(f"Monotype · {type_name} · {mode}\nValidité de l'équipe : {UNAVAILABLE}\nTypes d'équipe non transmis par Lua.")
        randomizer = challenge is not None and "randomizer" in challenge.active_rules
        self.randomizer_label.setVisible(randomizer)
        if randomizer:
            parameters = challenge.settings.get("rule_parameters", {}).get("randomizer", {})
            details = []
            for key, name in (("wild", "Sauvages"), ("trainers", "Dresseurs"), ("items", "Objets"),
                              ("moves", "Attaques"), ("types", "Types"), ("abilities", "Talents")):
                value = parameters.get(key)
                details.append(f"{name} : " + (str(value) + " (configuré)" if value is not None else "Non disponible"))
            self.randomizer_label.setText("Randomizer · configuré, non appliqué\n" + "\n".join(details))
        self.set_bridge_state(self._bridge)

    def set_bridge_state(self, state: BridgeState):
        self._bridge = state
        self.connection_badge.setText("Lua · connecté" if state.connected else "Lua · déconnecté")
        self.profile_combo.setEnabled(state.status == "stopped" and not self._run.running)
        self.profile_combo.setToolTip("Terminez la session et arrêtez la connexion Lua avant de changer de profil."
                                     if state.status != "stopped" or self._run.running else "Profil suivi lors de la prochaine connexion Lua.")
        self.game_combo.setEnabled(state.status == "stopped" and not self._run.running)
        matching = state.game_id == self.game_combo.currentData() and (
            self._profile is None or state.game_id == self._profile.challenge.game_id)
        party = state.party if state.connected and matching else None
        self.team_note.setText(f"{len(party)} / 6 Pokémon · lecture Lua" if party is not None else
                              "Jeu et profil incompatibles" if state.connected and not matching else "Équipe : " + UNAVAILABLE)
        for index, slot in enumerate(self.team_slots):
            slot.set_pokemon(party[index] if party is not None and index < len(party) else None,
                             known_empty=party is not None and index >= len(party))
        self.debug_label.setText(f"Protocole : {state.protocol_version or UNAVAILABLE}\n"
                                 f"Code : {state.game_code or UNAVAILABLE}\nProfil mémoire : {state.memory_profile or UNAVAILABLE}\n"
                                 f"Séquence : {state.sequence}\nPID : {self._run.pid or UNAVAILABLE}")

    def set_tracking_state(self, state: TrackingState):
        self.nuzlocke_widget.update_state(state)
        self.zone_label.setText(state.zone_name or state.current_zone_id or UNAVAILABLE)
        self.zone_map_label.setText("Carte : " + (str(state.current_map_id) if state.current_map_id is not None else UNAVAILABLE))
        from app.ui.widgets.nuzlocke import RESULT_LABELS
        names = {"zone_entered": "Entrée dans une zone", "wild_encounter_started": "Rencontre sauvage",
                 "capture_success": "Capture enregistrée", "wild_fainted": "Pokémon sauvage K.O."}
        lines = []
        for event in state.history[-5:]:
            kind = event.get("event", "")
            lines.append(names.get(kind, RESULT_LABELS.get(kind, kind or "Événement")))
        self.history_label.setText("\n".join(lines) or "Aucun événement reçu")

    def set_run_state(self, state: RunState):
        self._run = state
        self.window_title.setText(state.window_title or ("DeSmuME démarré · fenêtre recherchée" if state.running else "Fenêtre externe"))
        self.status_label.setText(state.message)
        self.launch_button.setEnabled(not state.running)
        self.arrange_button.setEnabled(state.running)
        self.game_combo.setEnabled(not state.running and self._bridge.status == "stopped")
        self.profile_combo.setEnabled(not state.running and self._bridge.status == "stopped")
        self.speed_label.setText(f"État demandé : {state.requested_speed}\nÉtat réel : {state.confirmed_speed or UNAVAILABLE}")
        for speed, button in self.speed_buttons.items():
            button.setChecked(speed == state.requested_speed)
        seconds = state.elapsed_seconds
        self.time_label.setText(f"Session PCE : {seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
                               if state.game_id else "Session PCE : " + UNAVAILABLE)
        self.time_label.setToolTip("Temps écoulé depuis le lancement suivi par PCE ; distinct du temps de jeu enregistré dans Pokémon.")

    def set_controls(self, mapping: dict[str, str], source: str, *, controller=None):
        for key, widget in self.control_labels.items():
            value = mapping.get(key)
            widget.setText(value or "—")
            widget.setToolTip(value or UNAVAILABLE)
        self.controls_source.setText(source)
        self.controller_label.setText("Manette : " + (controller or UNAVAILABLE))

    def set_interface(self, settings: dict):
        self._interface = deepcopy(settings)
        density = settings.get("density", "standard")
        widths = {"compact": (240, 340), "standard": (260, 370), "large": (290, 410)}
        left, right = widths[density]
        self.left_scroll.setFixedWidth(left)
        self.right_scroll.setFixedWidth(right)
        visible = settings.get("visible", {})
        sides = settings.get("sides", {})
        for key, block in self.blocks.items():
            self.left_layout.removeWidget(block)
            self.right_layout.removeWidget(block)
            side = sides.get(key, "left" if key in {"controls", "speed", "saves"} else "right")
            layout = self.left_layout if side == "left" else self.right_layout
            layout.insertWidget(layout.count() - 1, block)
            block.setVisible(visible.get(key, key not in {"logs", "debug"}))
        self.setProperty("density", density)
        self.rules_label.setVisible(density != "compact")
        self.team_note.setVisible(density != "compact")
        self.toggle_panels(self._panels_visible)

    def toggle_panels(self, visible: bool | None = None):
        self._panels_visible = not self._panels_visible if visible is None else visible
        self.left_scroll.setVisible(self._panels_visible)
        self.right_scroll.setVisible(self._panels_visible)

    def next_panel(self):
        target = self.right_scroll if self.left_scroll.hasFocus() else self.left_scroll
        target.setFocus(Qt.FocusReason.ShortcutFocusReason)


GAME_MODE_STYLE = """
QWidget#page QPushButton {padding:8px 10px;}
QPushButton#speedButton {padding:7px 4px;}
QPushButton#speedButton:checked {background:#605499;border-color:#a998ed;}
QLabel#gameTitle {font-size:22px;font-weight:650;color:#f5f4ff;}
QFrame#gameCard {background:#171e2d;border:1px solid #2a3348;border-radius:12px;}
QFrame#gameStage {background:#111928;border:1px solid #34415a;border-radius:15px;}
QFrame#dsPlaceholder {background:#0b101b;border:1px solid #303b53;border-radius:14px;}
QLabel#dsScreen {background:#141e30;border:1px solid #2b3851;border-radius:7px;color:#65738e;font-size:11px;}
QFrame#teamSlot {background:#111927;border:1px solid #303b50;border-radius:8px;}
QLabel#teamName {font-size:12px;font-weight:600;}
QLabel#teamStatus {font-size:10px;color:#8c9ab5;}
QLabel#keycap {background:#263047;border:1px solid #46516b;border-radius:5px;padding:4px;font-size:11px;}
QProgressBar {border:0px;border-radius:2px;background:#28334a;}
QProgressBar::chunk {background:#74cbb0;border-radius:2px;}
QTabWidget::pane {border:1px solid #303b52;background:#0d111b;}
QTabBar::tab {background:#1a2232;color:#a8b3ca;padding:11px 16px;}
QTabBar::tab:selected {background:#32304f;color:#e4dfff;}
"""
