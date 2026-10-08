"""Composants de mise en page et libellés communs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

STATUS_LABELS = {
    "ui_only": "Configuration uniquement",
    "planned": "Application prévue · configuration uniquement",
    "partial": "Configuration et suivi disponible selon le jeu",
    "future_strict": "Application stricte prévue",
}
MODE_LABELS = {"normal": "Partie normale", "custom": "Challenge personnalisé", "random": "Challenge aléatoire"}
INSTALLATION_LABELS = {"ready": "Prêt", "not_found": "Jeu non trouvé",
                       "needs_choice": "Choix nécessaire", "lua_required": "Support Lua requis",
                       "needs_attention": "À vérifier"}


def label(text: str, style: str = "", wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if style:
        widget.setObjectName(style)
    return widget


def card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    if title:
        layout.addWidget(label(title, "sectionTitle"))
    return frame, layout


def page_layout(widget: QWidget, title: str, subtitle: str) -> QVBoxLayout:
    """Toutes les pages restent accessibles avec une fenêtre peu haute."""
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName("page")
    layout = QVBoxLayout(content)
    layout.setContentsMargins(30, 26, 30, 28)
    layout.setSpacing(18)
    layout.addWidget(label(title, "title"))
    layout.addWidget(label(subtitle, "subtitle"))
    scroll.setWidget(content)
    outer.addWidget(scroll)
    return layout
