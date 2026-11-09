"""Shared destination picker for transactions and whole imports."""

from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.components import icon


class WalletDestinationDialog(QDialog):
    def __init__(self, parent, title, wallets, *, count):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Liczba transakcji: {count}", count=count)))
        layout.addWidget(QLabel(tr("Portfel docelowy")))
        self.wallet = QComboBox()
        for row in wallets:
            self.wallet.addItem(
                icon(row["icon_name"]), f"{row['name']} ({row['currency']})", row["id"]
            )
        layout.addWidget(self.wallet)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.wallet.count() > 0)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def wallet_id(self):
        return self.wallet.currentData()
