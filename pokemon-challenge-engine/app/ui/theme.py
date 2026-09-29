"""Identité visuelle commune : contrastes doux et contrôles lisibles."""

STYLESHEET = """
QWidget { color: #e9ecf5; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog, QWidget#page { background: #0d111b; }
QWidget#sidebar { background: #121723; border-right: 1px solid #242c3d; }
QFrame#card { background: #171e2d; border: 1px solid #2a3348; border-radius: 12px; }
QFrame#hero { background: #1c2240; border: 1px solid #3b4266; border-radius: 16px; }
QLabel { background: transparent; border: none; }
QLabel#title { font-size: 28px; font-weight: 650; color: #f6f7fc; }
QLabel#heroTitle { font-size: 32px; font-weight: 650; color: #ffffff; }
QLabel#sectionTitle { font-size: 17px; font-weight: 600; }
QLabel#subtitle, QLabel#muted { color: #a8b3c9; }
QLabel#eyebrow { color: #b2a6ff; font-size: 11px; font-weight: 700; }
QLabel#brand { font-size: 18px; font-weight: 700; }
QLabel#badge { color: #bdcefa; background: #222d48; border-radius: 6px; padding: 5px 9px; }
QLabel#error { color: #ffc1ca; background: #382330; border-radius: 7px; padding: 10px; }
QLabel#success { color: #a9e5cc; background: #20382f; border-radius: 7px; padding: 10px; }
QPushButton { background: #252e43; border: 1px solid #38435e; border-radius: 7px; padding: 9px 15px; font-weight: 600; }
QPushButton:hover { background: #303c56; border-color: #6678a8; }
QPushButton:pressed { background: #3d4a69; }
QPushButton:disabled { color: #727f97; background: #1b2231; border-color: #2a3243; }
QPushButton#primary { background: #8172eb; border-color: #9b8bff; color: #ffffff; }
QPushButton#primary:hover { background: #9383fc; }
QPushButton#primary:disabled { background: #393553; color: #9690af; border-color: #49435e; }
QPushButton#nav { text-align: left; background: transparent; border: 1px solid transparent; padding: 13px 16px; font-weight: 500; color: #b7c1d5; }
QPushButton#nav:hover { background: #20293c; }
QPushButton#nav:checked { background: #2a2a47; color: #d2c9ff; border: 1px solid #443d65; }
QLineEdit, QSpinBox, QComboBox, QTextEdit, QTextBrowser { background: #101724; border: 1px solid #35415a; border-radius: 6px; padding: 7px; selection-background-color: #6759c2; }
QComboBox[state="required"] { color: #b7e0cf; background: #20352e; border-color: #46695c; }
QComboBox[state="possible"] { color: #c3cdf0; background: #202b42; border-color: #445678; }
QComboBox[state="forbidden"] { color: #dfbdc7; background: #352731; border-color: #70515d; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #9d8df6; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: #778299; background: #19202e; }
QComboBox { min-height: 21px; padding-right: 24px; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox QAbstractItemView { background: #20293a; selection-background-color: #4a427d; padding: 4px; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; }
QTableWidget, QListWidget { background: #131b29; alternate-background-color: #182132; border: 1px solid #2b364c; border-radius: 8px; gridline-color: #293247; outline: none; }
QTableWidget::item, QListWidget::item { padding: 8px; border-bottom: 1px solid #252f41; }
QListWidget::item:selected, QTableWidget::item:selected { background: #343453; color: #f2edff; }
QHeaderView::section { background: #20293b; color: #b6c2da; border: none; padding: 9px; font-weight: 600; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #111824; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3a455f; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #111824; height: 10px; }
QScrollBar::handle:horizontal { background: #3a455f; border-radius: 5px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #64718e; border-radius: 4px; background: #151d2c; }
QCheckBox::indicator:checked { background: #8c7bf2; border: 2px solid #cabfff; }
QToolTip { color: #f2f4fc; background: #2a344a; border: 1px solid #536280; padding: 7px; }
QStatusBar { background: #121723; color: #9daac1; border-top: 1px solid #242e41; }
QMessageBox { background: #151d2c; }
"""
