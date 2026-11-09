"""Stable action identifiers, portable bindings and conflict validation."""

import json

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from home_finance_cockpit.localization import tr

# English mnemonics; identifiers and defaults are independent of UI language.
ACTIONS = {
    "navigate_back": ("Wstecz", "Alt+Left"),
    "navigate_forward": ("Dalej", "Alt+Right"),
    "overview": ("Przegląd", "Ctrl+Shift+O"),
    "transactions": ("Transakcje", "Ctrl+Shift+T"),
    "wallets": ("Portfele", "Ctrl+Shift+W"),
    "imports": ("Historia importów", "Ctrl+Shift+I"),
    "analytics": ("Analizy", "Ctrl+Shift+A"),
    "categories": ("Kategorie i reguły", "Ctrl+Shift+C"),
    "reports": ("Generuj raport", "Ctrl+Shift+R"),
    "goals": ("Cele oszczędnościowe", "Ctrl+Shift+G"),
    "add_goal": ("Dodaj cel", "Ctrl+G"),
    "settings": ("Ustawienia", "Ctrl+Shift+S"),
    "currencies": ("Waluty", "Ctrl+Shift+U"),
    "add_transaction": ("Dodaj transakcję", "Ctrl+T"),
    "add_wallet": ("Dodaj portfel", "Ctrl+Alt+W"),
    "import": ("Importuj pliki", "Ctrl+I"),
    "open_database": ("Otwórz bazę danych", "Ctrl+O"),
    "new_database": ("Utwórz nową bazę danych", "Ctrl+N"),
    "backup": ("Kopia zapasowa bazy", "Ctrl+B"),
    "search": ("Wyszukaj transakcje", "Ctrl+F"),
    "refresh": ("Odśwież", "F5"),
    "undo": ("Cofnij usunięcie", "Ctrl+Z"),
}


def defaults():
    return {key: value[1] for key, value in ACTIONS.items()}


def validate(bindings):
    """Empty bindings disable actions; reject duplicates and chord prefixes."""
    result, sequences = {}, []
    for key, (caption, _) in ACTIONS.items():
        value = bindings.get(key, "")
        if not isinstance(value, str):
            raise ValueError(tr("Nieprawidłowy skrót: {action}", action=tr(caption)))
        seq = QKeySequence.fromString(value, QKeySequence.SequenceFormat.PortableText)
        if value and seq.isEmpty():
            raise ValueError(tr("Nieprawidłowy skrót: {action}", action=tr(caption)))
        strokes = []
        for index in range(seq.count()):
            combination = seq[index]
            code = combination.key()
            modifiers = combination.keyboardModifiers()
            if code in (
                Qt.Key.Key_unknown,
                Qt.Key.Key_Control,
                Qt.Key.Key_Shift,
                Qt.Key.Key_Alt,
                Qt.Key.Key_Meta,
            ):
                raise ValueError(tr("Nieprawidłowy skrót: {action}", action=tr(caption)))
            if (
                not (
                    modifiers
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.MetaModifier
                    )
                )
                and not Qt.Key.Key_F1 <= code <= Qt.Key.Key_F35
            ):
                raise ValueError(
                    tr(
                        "Skrót musi zawierać Ctrl, Alt lub klawisz funkcyjny: {action}",
                        action=tr(caption),
                    )
                )
            strokes.append(combination.toCombined())
        strokes = tuple(strokes)
        if strokes:
            for previous, other in sequences:
                if strokes[: len(other)] == other or other[: len(strokes)] == strokes:
                    raise ValueError(
                        tr(
                            "Konflikt skrótów: {first} i {second}.",
                            first=tr(ACTIONS[previous][0]),
                            second=tr(caption),
                        )
                    )
            sequences.append((key, strokes))
        result[key] = seq.toString(QKeySequence.SequenceFormat.PortableText)
    return result


def load(settings):
    try:
        saved = json.loads(settings.value("general/shortcuts", "{}"))
        if not isinstance(saved, dict):
            return defaults()
        result = validate({key: saved.get(key, "") for key in ACTIONS})
        for key, value in defaults().items():
            if key not in saved:
                try:
                    result = validate(dict(result, **{key: value}))
                except ValueError:
                    pass  # A newly introduced default must not replace an existing custom binding.
        return result
    except (ValueError, TypeError):
        return defaults()
