"""Run with python main.py from any working directory."""

import argparse
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.application import ApplicationController
from home_finance_cockpit.identity import APP_NAME, APP_RELEASE
from home_finance_cockpit.ui.branding import configure_windows_identity
from home_finance_cockpit.ui.theme import configure_application


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--database", type=Path, help="Database offered on the start screen")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_RELEASE}")
    parser.add_argument(
        "--self-test",
        type=Path,
        metavar="RESULT_JSON",
        help="Run an isolated offline release check and write its result",
    )
    args = parser.parse_args()
    if args.self_test:
        from home_finance_cockpit.release_check import run_release_check

        return run_release_check(args.self_test)
    from home_finance_cockpit.diagnostics import install_diagnostics

    install_diagnostics()
    configure_windows_identity()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_RELEASE)
    app.setOrganizationName("HomeFinanceCockpit")
    configure_application(app)
    from home_finance_cockpit.services.preferences import Preferences
    from home_finance_cockpit.ui.theme import apply_font_size, apply_theme

    preferences = Preferences(":memory:")
    apply_font_size(app, preferences.font_size())
    apply_theme(app, preferences.theme())
    controller = ApplicationController(app, initial_path=args.database)
    controller.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
