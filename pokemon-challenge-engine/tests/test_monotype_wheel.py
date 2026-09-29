"""Vérifie le pointeur réel, les exclusions et la validation Qt sans pytest-qt."""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app.core.monotype import GEN5_TYPE_IDS, select_type
from app.ui.monotype_wheel import MonotypeDialog, WheelWidget, pointer_index, target_rotation


TYPES = [
    {"id": GEN5_TYPE_IDS[index], "name": name, "color": "#9681dd"}
    for index, name in enumerate([
        "Normal", "Feu", "Eau", "Électrik", "Plante", "Glace", "Combat",
        "Poison", "Sol", "Vol", "Psy", "Insecte", "Roche", "Spectre",
        "Dragon", "Ténèbres", "Acier",
    ])
]


class WheelGeometryTests(unittest.TestCase):
    def test_pointer_matches_each_target_across_rotations(self):
        for count in (1, 2, 3, 7, 17):
            for index in range(count):
                for rotation in (0, 12.3, 359.9, 4312.12, -126.5):
                    finish = target_rotation(rotation, index, count)
                    self.assertGreaterEqual(finish, rotation + 1800)
                    self.assertEqual(pointer_index(finish, count), index)

    def test_invalid_geometry_rejected(self):
        with self.assertRaises(ValueError):
            pointer_index(0, 0)
        with self.assertRaises(ValueError):
            target_rotation(0, 17, 17)


class MonotypeQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.qt_app.processEvents()

    def dialog(self, configuration=None):
        dialog = MonotypeDialog(TYPES, seed=4281, configuration=configuration)
        dialog.animation_duration_ms = 25
        self.widgets.append(dialog)
        return dialog

    def finish(self):
        # Attendre une condition réelle évite les échecs liés à une machine chargée.
        deadline = time.monotonic() + 3
        wheels = [widget.wheel if isinstance(widget, MonotypeDialog) else widget for widget in self.widgets]
        QTest.qWait(20)
        while any(wheel.is_spinning for wheel in wheels) and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(all(not wheel.is_spinning for wheel in wheels))

    def test_animated_pointer_and_label_agree_for_every_type(self):
        wheel = WheelWidget(TYPES)
        self.widgets.append(wheel)
        finished = []
        wheel.spin_finished.connect(finished.append)
        for item in TYPES:
            wheel.spin_to(item["id"], duration=1)
            self.finish()
            self.assertEqual(wheel.pointer_type_id(), item["id"])
            self.assertEqual(wheel.selected_type_id, item["id"])
            self.assertEqual(finished[-1], item["id"])

    def test_confirmation_and_controls_locked_while_spinning(self):
        dialog = self.dialog()
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog._roll()
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertFalse(dialog.roll_button.isEnabled())
        self.assertFalse(dialog.reroll_checkbox.isEnabled())
        self.assertTrue(all(not control.isEnabled() for control in dialog.type_checkboxes.values()))
        self.assertTrue(all(not control.isEnabled() for control in dialog.mode_buttons.values()))
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        with self.assertRaises(ValueError):
            dialog.configuration()
        self.finish()
        self.assertTrue(dialog.confirm_button.isEnabled())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_excluded_types_never_reach_wheel_or_engine_result(self):
        dialog = self.dialog()
        for type_id, checkbox in dialog.type_checkboxes.items():
            checkbox.setChecked(type_id == "water")
        dialog._roll()
        self.finish()
        self.assertEqual(dialog.configuration()["type_id"], "water")
        self.assertEqual(dialog.wheel.pointer_type_id(), "water")
        self.assertEqual(dialog.configuration()["allowed_types"], ["water"])

    def test_exclusion_invalidates_result_and_empty_pool_prevents_roll(self):
        dialog = self.dialog()
        dialog._roll()
        self.finish()
        result = dialog.configuration()["type_id"]
        dialog.type_checkboxes[result].setChecked(False)
        self.assertFalse(dialog.confirm_button.isEnabled())
        with self.assertRaises(ValueError):
            dialog.configuration()
        for checkbox in dialog.type_checkboxes.values():
            checkbox.setChecked(False)
        dialog.reroll_checkbox.setChecked(True)
        self.assertFalse(dialog.roll_button.isEnabled())
        dialog._roll()
        self.assertFalse(dialog.wheel.is_spinning)

    def test_reroll_permission_and_deterministic_sequence(self):
        dialog = self.dialog()
        allowed = [item["id"] for item in TYPES]
        dialog._roll()
        self.finish()
        initial = dialog.configuration()
        self.assertEqual(initial["type_id"], select_type(allowed_types=allowed, seed=4281, roll_index=0))
        self.assertFalse(dialog.roll_button.isEnabled())
        dialog._roll()
        self.assertEqual(dialog.configuration(), initial)
        dialog.reroll_checkbox.setChecked(True)
        dialog._roll()
        self.finish()
        reroll = dialog.configuration()
        self.assertEqual(reroll["roll_index"], 1)
        self.assertEqual(reroll["type_id"], select_type(allowed_types=allowed, seed=4281, roll_index=1))
        self.assertEqual(dialog.wheel.pointer_type_id(), reroll["type_id"])

    def test_cancel_preserves_input_and_saved_settings_restore(self):
        original = {"type_id": "grass", "mode": "strict", "allowed_types": ["water", "grass"], "allow_reroll": False, "roll_index": 3}
        dialog = self.dialog(original)
        self.assertEqual(dialog.configuration(), original)
        self.assertEqual(dialog.wheel.pointer_type_id(), "grass")
        dialog.mode_buttons["pure"].setChecked(True)
        dialog.type_checkboxes["water"].setChecked(False)
        dialog.reject()
        self.assertEqual(original, {"type_id": "grass", "mode": "strict", "allowed_types": ["water", "grass"], "allow_reroll": False, "roll_index": 3})
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_cancel_during_spin_emits_no_late_result(self):
        dialog = self.dialog()
        finished = []
        dialog.wheel.spin_finished.connect(finished.append)
        dialog._roll()
        dialog.reject()
        self.finish()
        self.assertFalse(dialog.wheel.is_spinning)
        self.assertEqual(finished, [])
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)


if __name__ == "__main__":
    unittest.main()
