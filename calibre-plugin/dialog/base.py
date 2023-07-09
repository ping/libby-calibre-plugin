#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from typing import Dict, List

from calibre.gui2.viewer.overlay import LoadingOverlay

# noinspection PyUnresolvedReferences
from qt.core import (
    Qt,
    QDialog,
    QGridLayout,
    QThread,
    QTabWidget,
    QDesktopServices,
    QUrl,
    QWidget,
    QStatusBar,
)

from .. import logger, __version__
from ..config import PREFS, PreferenceKeys
from ..libby import LibbyClient
from ..model import LibbyModel
from ..overdrive import OverDriveClient
from ..worker import SyncDataWorker

load_translations()


class BaseDialogMixin(QDialog):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.gui = gui
        self.do_user_config = do_user_config
        self.icons = icons
        self.db = gui.current_db.new_api
        self.client = None
        self._sync_thread = QThread()
        self._curr_width = 0
        self._curr_height = 0
        self.logger = logger

        self.setWindowTitle(
            _("OverDrive Libby v{version}").format(
                version=".".join([str(d) for d in __version__])
            )
        )
        self.setWindowIcon(icon)

        libby_token = PREFS[PreferenceKeys.LIBBY_TOKEN]
        if libby_token:
            self.client = LibbyClient(
                identity_token=libby_token, max_retries=1, timeout=30, logger=logger
            )
        self.overdrive_client = OverDriveClient(
            max_retries=1, timeout=30, logger=logger
        )

        self.layout = QGridLayout()
        self.setLayout(self.layout)
        self.tabs = QTabWidget(self)
        self.layout.addWidget(self.tabs, 0, 0)

        self.view_vspan = 8
        self.view_hspan = 4
        self.refresh_buttons: List[QWidget] = []
        self.status_bars: List[QStatusBar] = []
        self.models: List[LibbyModel] = []
        self.loading_overlay = CustomLoadingOverlay(self)

    def resizeEvent(self, e):
        # Because resizeEvent is called *multiple* times during a resize,
        # we will save the new window size only when the differential is
        # greater than min_diff.
        # This does not completely debounce the saves, but it does reduce
        # it reasonably imo.
        new_size = e.size()
        self.loading_overlay.resize(new_size)
        new_width = new_size.width()
        new_height = new_size.height()
        min_diff = 5
        if (
            new_width
            and new_width > 0
            and abs(new_width - self._curr_width) >= min_diff
            and new_width != PREFS[PreferenceKeys.MAIN_UI_WIDTH]
        ):
            PREFS[PreferenceKeys.MAIN_UI_WIDTH] = new_width
            self._curr_width = new_width
            logger.debug("Saved new UI width preference: %d", new_width)
        if (
            new_height
            and new_height > 0
            and abs(new_height - self._curr_height) >= min_diff
            and new_height != PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
        ):
            PREFS[PreferenceKeys.MAIN_UI_HEIGHT] = new_height
            self._curr_height = new_height
            logger.debug("Saved new UI height preference: %d", new_height)

    def view_in_libby_action_triggered(self, indices, model):
        for index in indices:
            data = index.data(Qt.UserRole)
            library_key = model.get_card(data["cardId"])["advantageKey"]
            QDesktopServices.openUrl(
                QUrl(LibbyClient.libby_title_permalink(library_key, data["id"]))
            )

    def view_in_overdrive_action_triggered(self, indices, model: LibbyModel):
        for index in indices:
            data = index.data(Qt.UserRole)
            card = model.get_card(data["cardId"])
            library = model.get_library(model.get_website_id(card))

            QDesktopServices.openUrl(
                QUrl(
                    OverDriveClient.library_title_permalink(
                        library["preferredKey"], data["id"]
                    )
                )
            )

    def sync(self):
        if not self._sync_thread.isRunning():
            for btn in self.refresh_buttons:
                btn.setEnabled(False)
            for bar in self.status_bars:
                bar.showMessage(_("Synchronizing..."))
            for model in self.models:
                model.sync({})
            self.loading_overlay(_("Synchronizing..."))
            self._sync_thread = self._get_sync_thread()
            self._sync_thread.start()

    def _get_sync_thread(self):
        thread = QThread()
        worker = SyncDataWorker()
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(value: Dict):
            self.loading_overlay.hide()
            for btn in self.refresh_buttons:
                btn.setEnabled(True)
            for bar in self.status_bars:
                bar.clearMessage()
            for model in self.models:
                model.sync(value)
            thread.quit()

        def errored_out(err: Exception):
            self.loading_overlay.hide()
            for btn in self.refresh_buttons:
                btn.setEnabled(True)
            for bar in self.status_bars:
                bar.clearMessage()
            thread.quit()
            raise err

        worker.finished.connect(lambda value: loaded(value))
        worker.errored.connect(lambda err: errored_out(err))

        return thread


class CustomLoadingOverlay(LoadingOverlay):
    def hide(self):
        self.pi.stop()
        return QWidget.hide(self)
