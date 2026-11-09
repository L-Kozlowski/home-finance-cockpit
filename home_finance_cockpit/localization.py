"""Application text translation. User data and database identifiers stay unchanged."""

import json
from pathlib import Path

_language = "pl"
_catalog = None


def language():
    return _language


def quote_text(value):
    if not value:
        return ""
    return f"„{value}”" if _language == "pl" else f'"{value}"'


def set_language(value):
    global _language
    if value not in ("pl", "en"):
        raise ValueError("Unsupported language")
    _language = value


def tr(message, **values):
    return translate(message, _language, **values)


def translate(message, language_code, **values):
    """Translate a label in a specific language without changing application state."""
    global _catalog
    if not isinstance(message, str):
        return message
    translated = message
    if language_code == "en":
        if _catalog is None:
            _catalog = json.loads(
                (Path(__file__).parent / "locales" / "en.json").read_text(encoding="utf-8")
            )
        translated = _catalog.get(message) or message
    return translated.format(**values) if values else translated


def install_qt_language(app):
    """Translate native buttons, calendars and file dialogs as well as app labels."""
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

    previous = getattr(app, "_hfc_translator", None)
    if previous is not None:
        app.removeTranslator(previous)
        previous.deleteLater()
    QLocale.setDefault(QLocale("pl_PL" if _language == "pl" else "en_GB"))
    translator = QTranslator(app)
    if _language == "pl" and translator.load(
        "qtbase_pl", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        app.installTranslator(translator)
    app._hfc_translator = translator
