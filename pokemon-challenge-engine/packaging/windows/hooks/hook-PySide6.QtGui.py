"""PCE uses Qt Widgets and raster/SVG images, without PDF or virtual keyboard plugins."""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# These optional image/input plugins pull in QtPdf/QtQuick/QtVirtualKeyboard.
# They are unrelated to PCE's UI and would require shipping those extra sources.
binaries = [(source, target) for source, target in binaries
            if Path(source).name.casefold() not in {"qpdf.dll", "qtvirtualkeyboardplugin.dll"}]
