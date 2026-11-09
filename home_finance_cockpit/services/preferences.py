"""Application preferences and per-database backup configuration."""

from hashlib import sha256
from pathlib import Path

from PyQt6.QtCore import QSettings

from home_finance_cockpit.localization import tr
from home_finance_cockpit.paths import data_directory, ensure_data_directory

INTERVALS = (
    (3600, "Co godzinę"),
    (21600, "Co 6 godzin"),
    (86400, "Codziennie"),
    (604800, "Co tydzień"),
)
START_PAGES = (
    (0, "Przegląd"),
    (1, "Transakcje"),
    (2, "Portfele"),
    (3, "Importy"),
    (4, "Analizy"),
    (5, "Kategorie i reguły"),
    (6, "Generuj raport"),
    (7, "Cele oszczędnościowe"),
)
FONT_POINTS = (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24)


def application_settings():
    return QSettings(str(ensure_data_directory() / "settings.ini"), QSettings.Format.IniFormat)


class Preferences:
    def __init__(self, database_path, settings=None):
        self.settings = settings if settings is not None else application_settings()
        self.database_path = str(database_path)
        canonical = (
            str(Path(database_path).resolve()) if database_path != ":memory:" else database_path
        )
        self.key = "databases/" + sha256(canonical.encode()).hexdigest()[:24] + "/"
        base = (
            Path(database_path).resolve().parent
            if database_path != ":memory:"
            else data_directory()
        )
        name = Path(database_path).stem if database_path != ":memory:" else "memory"
        self.default_folder = (
            base / "backups" / "automatic" / (name + "_" + self.key.split("/")[1][:8])
        )

    def get(self, name, default=""):
        return self.settings.value(self.key + name, default)

    def backup_config(self):
        enabled = str(self.get("backup_enabled", "false")).lower() in ("true", "1")
        try:
            interval = int(self.get("backup_interval", 86400))
        except (ValueError, TypeError):
            interval = 86400
        if interval not in dict(INTERVALS):
            interval = 86400
        folder = str(self.get("backup_folder", str(self.default_folder))) or str(
            self.default_folder
        )
        return enabled, interval, folder

    def validate_backup(self, enabled, interval, folder):
        if interval not in dict(INTERVALS):
            raise ValueError(tr("Wybierz poprawną częstotliwość kopii."))
        if enabled and self.database_path == ":memory:":
            raise ValueError(tr("Automatyczne kopie wymagają bazy zapisanej w pliku."))
        if not str(folder).strip():
            raise ValueError(tr("Wybierz folder kopii zapasowych."))
        target = Path(folder).expanduser().resolve()
        if target.exists() and not target.is_dir():
            raise ValueError(tr("Ścieżka kopii musi wskazywać folder, a nie plik."))
        return str(target)

    def save(self, enabled, interval, folder, start_page):
        folder = self.validate_backup(enabled, interval, folder)
        if start_page not in dict(START_PAGES):
            raise ValueError(tr("Wybierz poprawny ekran startowy."))
        for name, value in (
            ("backup_enabled", enabled),
            ("backup_interval", interval),
            ("backup_folder", folder),
        ):
            self.settings.setValue(self.key + name, value)
        self.settings.setValue("general/start_page", start_page)
        self.sync()

    def start_page(self):
        try:
            value = int(self.settings.value("general/start_page", 0))
            return value if value in dict(START_PAGES) else 0
        except (ValueError, TypeError):
            return 0

    def date_format(self):
        from home_finance_cockpit.ui.chart_dates import DATE_FORMATS

        value = self.settings.value("general/date_format", DATE_FORMATS[0])
        return value if value in DATE_FORMATS else DATE_FORMATS[0]

    def font_size(self):
        return self.font_points() * 10

    def font_points(self):
        try:
            saved = self.settings.value("general/font_points", None)
            if saved is not None:
                value = int(saved)
                return value if value in FONT_POINTS else 10
            value = int(self.settings.value("general/font_size", 100)) / 10
            return (
                min(FONT_POINTS, key=lambda point: abs(point - value)) if 8 <= value <= 24 else 10
            )
        except (ValueError, TypeError):
            return 10

    def theme(self):
        value = self.settings.value("general/theme", "dark")
        return value if value in ("dark", "light") else "dark"

    def language(self):
        value = self.settings.value("general/language", "pl")
        return value if value in ("pl", "en") else "pl"

    def chart_palette(self):
        from home_finance_cockpit.domain.chart_palettes import PALETTES

        value = self.settings.value("general/chart_palette", "cockpit")
        return value if value in PALETTES else "cockpit"

    def sync(self):
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            raise OSError("Nie udało się zapisać ustawień. Sprawdź uprawnienia do pliku ustawień.")
