"""Présentation du Mode Jeu : aucune règle ni décision de capture dans l'UI."""

from copy import deepcopy
from datetime import datetime, timezone

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
        hp, maximum = pokemon.get("current_hp", pokemon.get("hp")), pokemon.get("max_hp")
        self.hp_label.setText(f"{hp} / {maximum} PV" if hp is not None and maximum is not None else UNAVAILABLE)
        self.hp_bar.setVisible(hp is not None and maximum is not None and maximum > 0)
        if hp is not None and maximum:
            self.hp_bar.setValue(round(100 * hp / maximum))
        self.status_label.setText("☠ Mort dans cette partie" if pokemon.get("life_status") == "dead" else
                                 "K.O." if hp == 0 else "Statut : " + UNAVAILABLE)


class GameModePage(QWidget):
    launch_requested = Signal(str)
    profile_requested = Signal(object)
    game_changed = Signal(str)
    settings_requested = Signal(str)
    speed_requested = Signal(str)
    backup_requested = Signal()
    fullscreen_requested = Signal()
    arrange_requested = Signal()
    reconnect_requested = Signal()
    stop_session_requested = Signal()
    run_action_requested = Signal(str)

    def __init__(self, catalog: Catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self._profile: Profile | None = None
        self._profiles: dict[str, Profile] = {}
        self._bridge = BridgeState()
        self._run = RunState()
        self._interface = None
        self._persistent_run = None
        self._autosave = {}
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
        self.run_bar = QWidget()
        run_row = QHBoxLayout(self.run_bar)
        run_row.setContentsMargins(0, 0, 0, 0)
        self.active_run_label = label("", "sectionTitle")
        run_row.addWidget(self.active_run_label, 1)
        for text, action in (("+ Capture", "manual_capture"), ("☠ Mort", "manual_death"),
                             ("+ Badge", "badge_increment"), ("− Badge", "badge_decrement"), ("Note", "add_note")):
            button = QPushButton(text)
            button.setToolTip("Saisie manuelle dans la progression PCE")
            button.clicked.connect(lambda checked=False, value=action: self.run_action_requested.emit(value))
            run_row.addWidget(button)
        self.run_bar.hide()
        outer.addWidget(self.run_bar)
        self.recovery_row = QWidget()
        recovery = QHBoxLayout(self.recovery_row)
        recovery.setContentsMargins(0, 0, 0, 0)
        self.session_notice = label("", "muted")
        recovery.addWidget(self.session_notice, 1)
        self.reconnect_button = QPushButton("Reconnecter Lua")
        self.reconnect_button.clicked.connect(self.reconnect_requested)
        recovery.addWidget(self.reconnect_button)
        self.change_game_button = QPushButton("Arrêter et changer de jeu")
        self.change_game_button.clicked.connect(self.stop_session_requested)
        recovery.addWidget(self.change_game_button)
        outer.addWidget(self.recovery_row)

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
        self.launch_button = QPushButton("Jouer  →")
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
        self.installation_button = QPushButton("Installation & diagnostic")
        self.installation_button.clicked.connect(lambda: self.settings_requested.emit("installation"))
        center.addWidget(self.installation_button)
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
        self.autosave_label = label("", "muted")
        self.autosave_label.hide()
        saves.addWidget(self.autosave_label)
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
        if self._persistent_run is not None:
            self._render_persistent()
            return
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
        self._refresh_recovery()
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
        self._render_persistent()

    def set_tracking_state(self, state: TrackingState):
        if self._persistent_run is not None:
            self._render_persistent()
            return
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
        self._refresh_recovery()
        self.speed_label.setText(f"État demandé : {state.requested_speed}\nÉtat réel : {state.confirmed_speed or UNAVAILABLE}")
        for speed, button in self.speed_buttons.items():
            button.setChecked(speed == state.requested_speed)
        seconds = state.elapsed_seconds
        self.time_label.setText(f"Session PCE : {seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
                               if state.game_id else "Session PCE : " + UNAVAILABLE)
        self.time_label.setToolTip("Temps écoulé depuis le lancement suivi par PCE ; distinct du temps de jeu enregistré dans Pokémon.")
        self._render_persistent()

    def set_persistent_run(self, run, autosave=None):
        self._persistent_run = deepcopy(run)
        self._autosave = deepcopy(autosave or {})
        self.run_bar.setVisible(run is not None)
        self.autosave_label.setVisible(run is not None)
        if run is not None:
            with QSignalBlocker(self.game_combo):
                self.game_combo.setCurrentIndex(self.game_combo.findData(run.game_id))
            self._render_persistent()

    def _render_persistent(self):
        run = self._persistent_run
        if run is None:
            return
        game = self.catalog.games.get(run.game_id)
        trackable = run.status in {"preparing", "active"}
        self.active_run_label.setText(("PARTIE ACTIVE · " if trackable else "PARTIE SÉLECTIONNÉE · ") + run.name)
        if not trackable:
            self.launch_button.setEnabled(False)
        self.profile_label.setText(run.name)
        self.game_label.setText(game.name if game else run.game_id)
        self.game_combo.setEnabled(False)
        self.profile_combo.setEnabled(False)
        self.profile_combo.setToolTip("Règles figées de cette partie. Changez de partie dans Mes parties.")
        rules = run.rules_snapshot.get("active_rules", [])
        selection_text = "Classique · aucune règle" if not rules else f"Règles figées de la partie · {len(rules)} actives"
        if self.profile_combo.count() != 1 or self.profile_combo.itemText(0) != selection_text:
            with QSignalBlocker(self.profile_combo):
                self.profile_combo.clear()
                self.profile_combo.addItem(selection_text, None)
        self.mode_label.setText("Classique" if not rules else "Règles de la partie")
        self.rules_label.show()
        self.rules_label.setText("\n".join(self.catalog.rules[key].name if key in self.catalog.rules else key
                                         for key in rules) or "Aucune règle active")
        seconds = int(run.total_play_seconds)
        self.time_label.setText(f"Temps suivi : {seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}")
        self.time_label.setToolTip("Temps confirmé par DeSmuME lancé ici et les messages du jeu associé.")
        self.stat_labels["badges"].setText(f"{run.badges} / 8 · Manuel" if run.badges is not None else "Non renseigné · Manuel")
        self.stat_labels["seed"].setText(str(run.seed) if run.seed is not None else "Non renseigné")
        deaths = [death for death in run.deaths or [] if not death.get("corrected", False)]
        self.stat_labels["deaths"].setText(str(len(deaths)) if run.deaths is not None else "Non renseigné")
        pending = [item for item in run.pending_deaths if not item.get("resolved", False)]
        self.stat_labels["deaths"].setToolTip("")
        if pending:
            self.stat_labels["deaths"].setText(self.stat_labels["deaths"].text() + f" · {len(pending)} à confirmer")
            self.stat_labels["deaths"].setToolTip("Une observation à 0 PV demande confirmation dans Mes parties > Détails > Équipe.")
        self.capture_count_label.setText("Captures · Manuel : " + (str(len(run.captures)) if run.captures is not None else "Non renseigné"))
        self.monotype_label.hide()
        self.randomizer_label.hide()
        self.stat_labels["level_cap"].setText("Non renseigné")
        zone = run.current_zone
        self.zone_label.setText((zone.get("name") or zone.get("id") or "Non renseigné") if isinstance(zone, dict)
                                else zone or "Non renseigné")
        self.zone_map_label.setText("Dernière zone enregistrée dans cette partie")
        party = run.current_party
        matching = self._bridge.connected and self._bridge.game_id == run.game_id
        self.team_note.show()
        self.team_note.setText("Dernière équipe observée · " + ("Lua connecté" if matching else "hors ligne"))
        for index, slot in enumerate(self.team_slots):
            slot.set_pokemon(party[index] if index < len(party) else None, known_empty=bool(party))
        self.nuzlocke_widget.hide()
        self.history_label.setText("\n".join(event["type"].replace("_", " ") for event in run.history[-5:]) or "Aucun événement")
        saved = self._autosave.get("last_saved_at")
        message = "Autosave PCE : en attente"
        if saved:
            try:
                age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(saved)).total_seconds()))
                message = f"Autosave PCE : ✓ il y a {age} s"
            except (ValueError, TypeError):
                message = "Autosave PCE : enregistré"
        if self._autosave.get("dirty"):
            message += " · modifications en attente"
        if self._autosave.get("error"):
            message = "Autosave PCE : erreur · " + self._autosave["error"]
        self.autosave_label.setText(message + "\nSauvegarde Pokémon : gérée dans DeSmuME")

    def _refresh_recovery(self):
        active = self._bridge.status != "stopped"
        self.recovery_row.setVisible(active or self._run.running)
        self.reconnect_button.setVisible(self._bridge.status in {"disconnected", "error"})
        self.change_game_button.setVisible(active)
        self.session_notice.setText("Fermez DeSmuME pour changer de jeu. La session Lua peut être arrêtée séparément."
            if self._run.running else "Session Lua déconnectée : reconnectez-la ou arrêtez-la pour choisir un autre jeu."
            if self._bridge.status == "disconnected" else "Le jeu reste verrouillé tant que la session Lua n'est pas arrêtée.")

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
        self._render_persistent()

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
