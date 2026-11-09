"""Editable keyboard bindings, applied only by the settings Save action."""

from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFormLayout, QKeySequenceEdit, QPushButton, QVBoxLayout, QWidget

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.shortcuts import ACTIONS, defaults, load, validate
from home_finance_cockpit.ui.components import label


class ShortcutSettings(QWidget):
    def __init__(self, settings):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                tr("Kliknij pole i naciśnij wybraną kombinację. Wyczyść pole, aby wyłączyć skrót.")
            )
        )
        form = QFormLayout()
        self.editors = {}
        bindings = load(settings)
        for key, (caption, _) in ACTIONS.items():
            editor = QKeySequenceEdit(QKeySequence(bindings[key]))
            editor.setClearButtonEnabled(True)
            editor.setAccessibleName(tr(caption))
            editor.setToolTip(tr("Domyślnie: {shortcut}", shortcut=ACTIONS[key][1]))
            form.addRow(tr(caption), editor)
            self.editors[key] = editor
        layout.addLayout(form)
        self.reset_button = QPushButton(tr("Przywróć domyślne skróty"))
        self.reset_button.clicked.connect(self.reset)
        layout.addWidget(self.reset_button)
        layout.addStretch()

    def reset(self):
        for key, value in defaults().items():
            self.editors[key].setKeySequence(QKeySequence(value))

    def bindings(self):
        return validate(
            {
                key: editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                for key, editor in self.editors.items()
            }
        )
