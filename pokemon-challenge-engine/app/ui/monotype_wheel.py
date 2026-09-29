"""Roue Monotype : animation déterministe et configuration locale du défi.

Le moteur choisit le type avant l'animation. La position finale de la roue est
calculée pour placer exactement le centre du secteur choisi sous le pointeur.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.core.monotype import select_type


def pointer_index(rotation: float, count: int) -> int:
    """Indice du secteur sous le pointeur fixe, situé en haut de la roue."""
    if count < 1:
        raise ValueError("La roue doit contenir au moins un type.")
    span = 360.0 / count
    return int(((-rotation + span / 2.0) % 360.0) / span) % count


def target_rotation(rotation: float, index: int, count: int, turns: int = 5) -> float:
    """Rotation horaire qui aligne le centre du secteur après plusieurs tours."""
    if count < 1 or not 0 <= index < count:
        raise ValueError("Le secteur demandé n'existe pas.")
    return rotation + max(0, turns) * 360.0 + ((-index * 360.0 / count - rotation) % 360.0)


class WheelWidget(QWidget):
    """Roue peinte localement ; ``spin_to`` anime un résultat déjà choisi.

    ``pointer_type_id()`` lit la géométrie réelle. ``set_result`` positionne un
    résultat enregistré sans animation. ``spin_finished`` annonce la fin réelle.
    """

    spin_finished = Signal(str)

    def __init__(self, types: list[dict[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self._types = list(types)
        self._rotation = 0.0
        self.selected_type_id: str | None = None
        self._pending_type_id: str | None = None
        self._animation = QPropertyAnimation(self, b"rotation", self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._animation.finished.connect(self._finish_spin)
        self.setMinimumSize(270, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Roue des types Monotype")

    def get_rotation(self) -> float:
        return self._rotation

    def set_rotation(self, value: float) -> None:
        self._rotation = float(value)
        self.update()

    rotation = Property(float, get_rotation, set_rotation)

    @property
    def is_spinning(self) -> bool:
        return self._pending_type_id is not None

    def set_types(self, types: list[dict[str, str]]) -> None:
        """Remplace les secteurs après modification des exclusions."""
        self.stop()
        self._types = list(types)
        self.selected_type_id = None
        self._rotation = 0.0
        self.update()

    def pointer_type_id(self) -> str | None:
        if not self._types:
            return None
        return self._types[pointer_index(self._rotation, len(self._types))]["id"]

    def set_result(self, type_id: str) -> None:
        """Restaure un résultat en alignant son secteur sous le pointeur."""
        index = self._index(type_id)
        self.stop()
        self._rotation = (-index * 360.0 / len(self._types)) % 360.0
        self.selected_type_id = type_id
        self.update()

    def _index(self, type_id: str) -> int:
        for index, type_data in enumerate(self._types):
            if type_data["id"] == type_id:
                return index
        raise ValueError("Le type choisi est absent de la roue.")

    def spin_to(self, type_id: str, duration: int = 3200) -> None:
        """Anime le type fourni ; ne réalise aucun choix aléatoire."""
        if self.is_spinning:
            raise RuntimeError("Un tirage est déjà en cours.")
        index = self._index(type_id)
        self.selected_type_id = None
        self._pending_type_id = type_id
        self._animation.setDuration(max(1, int(duration)))
        self._animation.setStartValue(self._rotation)
        self._animation.setEndValue(target_rotation(self._rotation, index, len(self._types)))
        self._animation.start()

    def stop(self) -> None:
        self._animation.stop()
        self._pending_type_id = None

    def _finish_spin(self) -> None:
        if self._pending_type_id is None:
            return
        expected = self._pending_type_id
        # Normaliser conserve le point d'arrivée exact et évite une dérive.
        self._rotation %= 360.0
        self._pending_type_id = None
        self.selected_type_id = self.pointer_type_id()
        if self.selected_type_id != expected:
            raise RuntimeError("Le pointeur ne correspond pas au résultat du moteur.")
        self.update()
        self.spin_finished.emit(expected)

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2.0, self.height() / 2.0 + 5)
        radius = max(1.0, min(self.width() - 26.0, self.height() - 38.0) / 2.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#080d19"))
        painter.drawEllipse(center, radius + 7, radius + 7)
        if not self._types:
            painter.setPen(QColor("#9aa8c3"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Sélectionnez au moins un type")
            return

        span = 360.0 / len(self._types)
        font = QFont(self.font())
        font.setPixelSize(max(10, min(13, int(radius / 13))))
        font.setBold(True)
        painter.setFont(font)
        for index, type_data in enumerate(self._types):
            middle = -90.0 + index * span + self._rotation
            start = middle - span / 2.0
            path = QPainterPath(center)
            steps = max(6, int(span / 3.0))
            for step in range(steps + 1):
                angle = math.radians(start + span * step / steps)
                path.lineTo(center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle))
            path.closeSubpath()
            color = QColor(type_data.get("color", "#6771c7"))
            if not color.isValid():
                color = QColor("#6771c7")
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#10182a"), 1.5))
            painter.drawPath(path)

            angle = math.radians(middle)
            painter.save()
            painter.translate(center.x() + radius * 0.67 * math.cos(angle), center.y() + radius * 0.67 * math.sin(angle))
            painter.rotate(middle + (180 if math.cos(angle) < -0.0001 else 0))
            lightness = (0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF())
            painter.setPen(QColor("#0b1321") if lightness > 0.55 else QColor("#ffffff"))
            painter.drawText(QRectF(-radius * 0.29, -11, radius * 0.58, 22), Qt.AlignmentFlag.AlignCenter, type_data["name"])
            painter.restore()

        painter.setBrush(QColor("#111a2d"))
        painter.setPen(QPen(QColor("#8998c2"), 2))
        painter.drawEllipse(center, radius * 0.30, radius * 0.30)
        chosen = next((item for item in self._types if item["id"] == self.selected_type_id), None)
        painter.setPen(QColor("#f2f5ff"))
        center_font = QFont(self.font())
        center_font.setPixelSize(max(12, min(20, int(radius / 9))))
        center_font.setBold(True)
        painter.setFont(center_font)
        painter.drawText(QRectF(center.x() - radius * 0.28, center.y() - 24, radius * 0.56, 48), Qt.AlignmentFlag.AlignCenter, chosen["name"] if chosen else "MONOTYPE")
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.setBrush(QColor("#f1f5ff"))
        top = center.y() - radius
        painter.drawPolygon(QPolygonF([QPointF(center.x() - 11, top - 10), QPointF(center.x() + 11, top - 10), QPointF(center.x(), top + 13)]))


class MonotypeDialog(QDialog):
    """Prépare un réglage ; l'appelant ne l'enregistre qu'après ``Accepted``."""

    animation_duration_ms = 3200

    def __init__(self, types: list[dict[str, str]], seed: int, configuration: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        if not types or len({item["id"] for item in types}) != len(types):
            raise ValueError("Les types doivent être présents et posséder des identifiants uniques.")
        self._types = list(types)
        self._seed = seed
        previous = dict(configuration or {})
        known_ids = [item["id"] for item in types]
        allowed = [value for value in previous.get("allowed_types", known_ids) if value in known_ids]
        self._result: str | None = previous.get("type_id") if previous.get("type_id") in allowed else None
        self._has_rolled = self._result is not None
        self._roll_index = int(previous.get("roll_index", 0))
        self._spinning = False
        self.setWindowTitle("Roue Monotype · Pokémon Challenge Engine")
        self.setModal(True)
        self.resize(850, 650)
        self.setMinimumSize(750, 600)
        self.setStyleSheet("""
            QDialog { background: #0c1221; color: #eff3ff; }
            QLabel, QCheckBox, QRadioButton { color: #e4eafa; }
            QLabel#title { font-size: 23px; font-weight: 700; }
            QLabel#subtitle, QLabel#muted { color: #9baac7; }
            QFrame#card { background: #131d31; border: 1px solid #293750; border-radius: 12px; }
            QPushButton { background: #202d46; color: #edf3ff; border: 1px solid #384768; border-radius: 8px; padding: 10px 18px; font-weight: 600; }
            QPushButton:hover { background: #31415f; }
            QPushButton#primary { background: #7557e8; border-color: #967bff; }
            QPushButton#primary:hover { background: #8668f7; }
            QPushButton:disabled { background: #1b2438; color: #63718f; border-color: #29354e; }
            QCheckBox:disabled, QRadioButton:disabled { color: #63718f; }
            QCheckBox, QRadioButton { spacing: 7px; }
        """)
        self._build_ui(allowed, previous)
        if self._result:
            self.wheel.set_result(self._result)
        self._refresh()

    def _build_ui(self, allowed: list[str], previous: dict) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        title = QLabel("Votre run. Un seul type.")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("La seed choisit le résultat ; la roue vous le révèle.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)
        body = QHBoxLayout()
        body.setSpacing(16)
        layout.addLayout(body, 1)
        left = QVBoxLayout()
        self.wheel = WheelWidget([item for item in self._types if item["id"] in allowed])
        self.wheel.spin_finished.connect(self._on_spin_finished)
        left.addWidget(self.wheel, 1)
        self.result_label = QLabel()
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(35)
        left.addWidget(self.result_label)
        self.roll_button = QPushButton("Lancer la roue")
        self.roll_button.setObjectName("primary")
        self.roll_button.clicked.connect(self._roll)
        left.addWidget(self.roll_button)
        body.addLayout(left, 5)
        body.addWidget(self._build_controls(allowed, previous), 4)
        layout.addLayout(self._build_footer())

    def _build_controls(self, allowed: list[str], previous: dict) -> QFrame:
        controls = QFrame()
        controls.setObjectName("card")
        controls.setMinimumWidth(300)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(15, 14, 15, 14)
        controls_layout.setSpacing(8)
        allowed_title = QLabel("TYPES AUTORISÉS · GÉNÉRATION V")
        allowed_title.setStyleSheet("font-weight: 700; font-size: 11px; color: #b6c5e3;")
        controls_layout.addWidget(allowed_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(5)
        self.type_checkboxes: dict[str, QCheckBox] = {}
        for index, type_data in enumerate(self._types):
            checkbox = QCheckBox(type_data["name"])
            checkbox.setChecked(type_data["id"] in allowed)
            checkbox.setToolTip(f"Inclure le type {type_data['name']} dans le tirage")
            checkbox.toggled.connect(self._allowed_changed)
            self.type_checkboxes[type_data["id"]] = checkbox
            grid.addWidget(checkbox, index // 3, index % 3)
        controls_layout.addLayout(grid)
        self.pool_label = QLabel()
        self.pool_label.setObjectName("muted")
        controls_layout.addWidget(self.pool_label)
        self._add_mode_controls(controls_layout, previous.get("mode", "soft"))
        self.reroll_checkbox = QCheckBox("Autoriser les relances")
        self.reroll_checkbox.setChecked(bool(previous.get("allow_reroll", False)))
        self.reroll_checkbox.toggled.connect(self._refresh)
        controls_layout.addWidget(self.reroll_checkbox)
        controls_layout.addStretch(1)
        note = QLabel("Ces règles sont enregistrées dans le profil. Elles ne sont pas appliquées dans le jeu à ce stade.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px;")
        controls_layout.addWidget(note)
        return controls

    def _add_mode_controls(self, controls_layout: QVBoxLayout, initial_mode: str) -> None:
        mode_title = QLabel("RÈGLE DU DÉFI")
        mode_title.setStyleSheet("font-weight: 700; font-size: 11px; color: #b6c5e3; margin-top: 6px;")
        controls_layout.addWidget(mode_title)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        modes = [
            ("soft", "Souple", "Au moins un des types du Pokémon correspond."),
            ("strict", "Strict", "Le type principal du Pokémon doit correspondre."),
            ("pure", "Pur", "Uniquement ce type ; aucun double type."),
        ]
        if initial_mode not in {item[0] for item in modes}:
            initial_mode = "soft"
        for mode, name, description in modes:
            button = QRadioButton(name)
            button.setChecked(mode == initial_mode)
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            controls_layout.addWidget(button)
            help_label = QLabel(description)
            help_label.setObjectName("muted")
            help_label.setWordWrap(True)
            help_label.setStyleSheet("font-size: 11px; margin-left: 23px;")
            controls_layout.addWidget(help_label)

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton("Confirmer ce type")
        self.confirm_button.setObjectName("primary")
        self.confirm_button.setDefault(False)
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self.accept)
        footer.addWidget(self.cancel_button)
        footer.addStretch(1)
        footer.addWidget(self.confirm_button)
        return footer

    def _allowed_types(self) -> list[str]:
        return [item["id"] for item in self._types if self.type_checkboxes[item["id"]].isChecked()]

    def _allowed_changed(self, checked: bool = False) -> None:
        if self._spinning:
            return
        self._result = None
        allowed = self._allowed_types()
        self.wheel.set_types([item for item in self._types if item["id"] in allowed])
        self._refresh()

    def _refresh(self, checked: bool = False) -> None:
        allowed = self._allowed_types()
        self.pool_label.setText(f"{len(allowed)} / {len(self._types)} types dans la roue")
        can_roll = bool(allowed) and (not self._has_rolled or self.reroll_checkbox.isChecked())
        self.roll_button.setEnabled(not self._spinning and can_roll)
        self.roll_button.setText("Relancer la roue" if self._has_rolled else "Lancer la roue")
        self.confirm_button.setEnabled(not self._spinning and self._result in allowed)
        for control in [*self.type_checkboxes.values(), *self.mode_buttons.values(), self.reroll_checkbox]:
            control.setEnabled(not self._spinning)
        if self._spinning:
            self.result_label.setText("La roue tourne…")
        elif self._result:
            name = next(item["name"] for item in self._types if item["id"] == self._result)
            self.result_label.setText(f"Type choisi : {name}")
        elif not allowed:
            self.result_label.setText("Sélectionnez au moins un type pour lancer la roue.")
        elif self._has_rolled and not self.reroll_checkbox.isChecked():
            self.result_label.setText("Sélection modifiée. Autorisez les relances pour effectuer un nouveau tirage.")
        else:
            self.result_label.setText("Choisissez les types autorisés, puis lancez la roue.")

    def _roll(self) -> None:
        allowed = self._allowed_types()
        if self._spinning or not allowed or (self._has_rolled and not self.reroll_checkbox.isChecked()):
            return
        if self._has_rolled:
            self._roll_index += 1
        chosen = select_type(allowed_types=allowed, seed=self._seed, roll_index=self._roll_index)
        self._result = None
        self._spinning = True
        self._refresh()
        self.wheel.spin_to(chosen, duration=self.animation_duration_ms)

    def _on_spin_finished(self, type_id: str) -> None:
        self._spinning = False
        self._has_rolled = True
        self._result = type_id
        self._refresh()

    def configuration(self) -> dict:
        """Retourne une nouvelle valeur ; nécessite un résultat terminé et valide."""
        allowed = self._allowed_types()
        if self._spinning or self._result not in allowed:
            raise ValueError("Terminez un tirage valide avant de confirmer.")
        return {
            "type_id": self._result,
            "mode": next(mode for mode, button in self.mode_buttons.items() if button.isChecked()),
            "allowed_types": allowed,
            "allow_reroll": self.reroll_checkbox.isChecked(),
            "roll_index": self._roll_index,
        }

    def accept(self) -> None:
        if not self._spinning and self._result in self._allowed_types():
            super().accept()

    def reject(self) -> None:
        self.wheel.stop()
        self._spinning = False
        super().reject()
