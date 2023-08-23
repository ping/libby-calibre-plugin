#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

from calibre.gui2.viewer.overlay import LoadingOverlay
from qt.core import (
    QAbstractItemView,
    QApplication,
    QFont,
    QLabel,
    QMouseEvent,
    QPushButton,
    QTableView,
    QWidget,
    Qt,
    pyqtSignal,
)

from .. import logger


class CustomLoadingOverlay(LoadingOverlay):
    # Custom https://github.com/kovidgoyal/calibre/blob/a562c1f637cf2756fa8336860543a15951f4fbc0/src/calibre/gui2/viewer/overlay.py#L10
    def hide(self):
        try:
            self.pi.stop()
            return QWidget.hide(self)
        except RuntimeError as err:
            # most likely because the UI has been closed before loading was completed
            logger.warning("Error hiding loading overlay: %s", err)


class ClickableQLabel(QLabel):
    clicked = pyqtSignal(QMouseEvent)
    doubleClicked = pyqtSignal(QMouseEvent)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def mousePressEvent(self, ev):
        self.clicked.emit(ev)

    def mouseDoubleClickEvent(self, ev):
        self.doubleClicked.emit(ev)


class DefaultQTableView(QTableView):
    def __init__(self, parent, model=None, min_width=0):
        super().__init__(parent)
        if min_width:
            self.setMinimumWidth(min_width)
        if model:
            self.setModel(model)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.sortByColumn(-1, Qt.AscendingOrder)
        self.setTabKeyNavigation(False)  # prevents tab key being stuck in view
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setContextMenuPolicy(Qt.CustomContextMenu)


class DefaultQPushButton(QPushButton):
    def __init__(self, text, icon=None, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("padding: 3px 16px")
        self.setFont(QFont(QApplication.font()))
        self.setAutoDefault(False)
        if icon:
            self.setIcon(icon)
