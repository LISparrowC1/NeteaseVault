"""Message boxes without the Windows system ding.

Every box is a Qt widget (never a native dialog), has no icon, and plays two quiet
pips instead of the operating-system notification sound.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox as _QMessageBox

from .sound import soft_beep


class SoftMessageBox(_QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOption(_QMessageBox.Option.DontUseNativeDialog, True)
        self.setIcon(_QMessageBox.Icon.NoIcon)

    def exec(self) -> int:
        self.setIcon(_QMessageBox.Icon.NoIcon)
        soft_beep()
        return super().exec()

    @staticmethod
    def information(parent, title: str, text: str,
                    buttons=_QMessageBox.StandardButton.Ok,
                    defaultButton=_QMessageBox.StandardButton.NoButton):
        box = SoftMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        box.setDefaultButton(defaultButton)
        return box.exec()

    @staticmethod
    def warning(parent, title: str, text: str,
                buttons=_QMessageBox.StandardButton.Ok,
                defaultButton=_QMessageBox.StandardButton.NoButton):
        return SoftMessageBox.information(parent, title, text, buttons, defaultButton)

    @staticmethod
    def critical(parent, title: str, text: str,
                 buttons=_QMessageBox.StandardButton.Ok,
                 defaultButton=_QMessageBox.StandardButton.NoButton):
        return SoftMessageBox.information(parent, title, text, buttons, defaultButton)

    @staticmethod
    def question(parent, title: str, text: str,
                 buttons=_QMessageBox.StandardButton.Yes | _QMessageBox.StandardButton.No,
                 defaultButton=_QMessageBox.StandardButton.No):
        box = SoftMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        box.setDefaultButton(defaultButton)
        return box.exec()


QMessageBox = SoftMessageBox
