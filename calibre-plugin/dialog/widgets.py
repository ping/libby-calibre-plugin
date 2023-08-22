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
    QLabel,
    QMouseEvent,
    QWidget,
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
