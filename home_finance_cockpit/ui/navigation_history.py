"""Session navigation history, including the active analytics subpage."""

from PyQt6.QtCore import QObject


class NavigationHistory(QObject):
    def __init__(self, host):
        super().__init__(host.workspace)
        self.host = host
        self.entries = [self.location()]
        self.position = 0
        self.restoring = False
        host.tabs.currentChanged.connect(self.record)
        host.analyses.tabs.currentChanged.connect(self.record)
        host.workspace.back_button.clicked.connect(self.back)
        host.workspace.forward_button.clicked.connect(self.forward)
        self.update_buttons()

    def location(self):
        page = self.host.tabs.currentIndex()
        return page, self.host.analyses.tabs.currentIndex() if page == 4 else None

    def record(self, *_):
        if self.restoring:
            return
        target = self.location()
        if target == self.entries[self.position]:
            return
        self.entries = self.entries[: self.position + 1] + [target]
        self.entries = self.entries[-100:]
        self.position = len(self.entries) - 1
        self.update_buttons()

    def update_buttons(self):
        self.host.workspace.back_button.setEnabled(self.position > 0)
        self.host.workspace.forward_button.setEnabled(self.position + 1 < len(self.entries))

    def back(self):
        self.go(-1)

    def forward(self):
        self.go(1)

    def go(self, offset):
        destination = self.position + offset
        if not 0 <= destination < len(self.entries):
            return
        page, group = self.entries[destination]
        if (
            self.host.tabs.currentIndex() == 1
            and page != 1
            and not self.host.transaction_page.inspector.guard_pending()
        ):
            return
        self.restoring = True
        try:
            if group is not None:
                self.host.analyses.tabs.setCurrentIndex(group)
            self.host.tabs.setCurrentIndex(page)
            if self.location() == self.entries[destination]:
                self.position = destination
        finally:
            self.restoring = False
            self.update_buttons()
