"""Hover help is suppressed without intercepting normal widget interaction."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from home_finance_cockpit.ui.theme import disable_tooltips


class TooltipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hover_event_never_reaches_custom_tooltip_handler(self):
        class Button(QPushButton):
            tooltip_events = 0

            def event(self, event):
                if event.type() == QEvent.Type.ToolTip:
                    self.tooltip_events += 1
                return super().event(event)

        disable_tooltips(self.app)
        blocker = self.app._tooltip_blocker
        disable_tooltips(self.app)
        self.assertIs(self.app._tooltip_blocker, blocker)
        button = Button("Action")
        button.setToolTip("Hidden hover help")
        self.addCleanup(button.close)
        button.show()
        self.app.sendEvent(button, QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), QPoint(5, 5)))
        self.assertEqual(button.tooltip_events, 0)
        clicked = []
        button.clicked.connect(lambda: clicked.append(True))
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(clicked, [True])
