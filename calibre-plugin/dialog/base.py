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
from calibre.gui2.widgets2 import CenteredToolButton
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
    QApplication,
    QFont,
    QToolButton,
    QMenu,
)

from .. import logger, __version__, PluginIcons, DEMO_MODE
from ..config import PREFS, PreferenceKeys, BorrowActions
from ..libby import LibbyClient
from ..models import LibbyModel
from ..overdrive import OverDriveClient
from ..workers import SyncDataWorker

load_translations()


class BorrowAndDownloadButton(CenteredToolButton):
    def __init__(self, text, icon=None, action=None, parent=None):
        super().__init__(icon, text, parent)
        self.setText(text)
        if icon is not None:
            self.setIcon(icon)
        self.setStyleSheet("padding: 2px 16px")
        self.setFont(QFont(QApplication.font()))  # make it bigger
        self.action = None
        self.set_action(action)

    def set_action(self, action):
        try:
            self.clicked.disconnect()
        except TypeError:
            pass
        self.action = action
        if self.action:
            self.clicked.connect(self.action)


class BaseDialogMixin(QDialog):
    """
    Base mixin class for the main QDialog
    """

    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.gui = gui
        self.do_user_config = do_user_config
        self.icons = icons
        self.db = gui.current_db.new_api
        self.client = None
        self._sync_thread = QThread()  # main sync thread
        self._curr_width = 0  # for persisting dialog size
        self._curr_height = 0  # for persisting dialog size
        self.logger = logger

        self.setWindowTitle(
            _("OverDrive Libby v{version}").format(
                version=".".join([str(d) for d in __version__])
            )
            if not DEMO_MODE
            else "OverDrive Libby"
        )
        self.setWindowIcon(icon)
        self.view_vspan = 1
        self.view_hspan = 4
        self.min_button_width = (
            150  # use this to set min col width for cols containing buttons
        )
        self.min_view_width = 720

        libby_token = PREFS[PreferenceKeys.LIBBY_TOKEN]
        if libby_token:
            self.client = LibbyClient(
                identity_token=libby_token, max_retries=1, timeout=30, logger=logger
            )
        self.overdrive_client = OverDriveClient(
            max_retries=1, timeout=30, logger=logger
        )

        layout = QGridLayout()
        self.setLayout(layout)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 0, 0)

        # Status bar
        self.status_bar = QStatusBar(self)
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setStyleSheet(
            "background-color: rgba(127, 127, 127, 0.1); border-radius: 4px;"
        )
        layout.addWidget(self.status_bar, 1, 0)

        self.refresh_buttons: List[QWidget] = []
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
        """
        Open title in Libby

        :param indices:
        :param model:
        :return:
        """
        for index in indices:
            data = index.data(Qt.UserRole)
            library_key = model.get_card(data["cardId"])["advantageKey"]
            QDesktopServices.openUrl(
                QUrl(LibbyClient.libby_title_permalink(library_key, data["id"]))
            )

    def view_in_overdrive_action_triggered(self, indices, model: LibbyModel):
        """
        Open title in library OverDrive site

        :param indices:
        :param model:
        :return:
        """
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
        if not self.client:
            self.status_bar.showMessage("Plugin is not configured!")
            return
        if not self._sync_thread.isRunning():
            for btn in self.refresh_buttons:
                btn.setEnabled(False)
            self.status_bar.showMessage(_("Synchronizing..."))
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

            holds = value.get("holds", [])
            holds_count = len(holds)
            holds_unique_count = len(list(set([h["id"] for h in holds])))
            self.status_bar.showMessage(
                _(
                    "Synced {loans} loans, {holds} holds ({unique_holds} unique), {cards} cards."
                ).format(
                    loans=len(value.get("loans", [])),
                    holds=holds_count,
                    unique_holds=holds_unique_count,
                    cards=len(value.get("cards", [])),
                ),
                3000,
            )
            for model in self.models:
                model.sync(value)
            thread.quit()

        def errored_out(err: Exception):
            self.loading_overlay.hide()
            self.status_bar.showMessage(
                _("An error occured during sync: {err}").format(err=str(err))
            )
            for btn in self.refresh_buttons:
                btn.setEnabled(True)
            thread.quit()
            raise err

        worker.finished.connect(lambda value: loaded(value))
        worker.errored.connect(lambda err: errored_out(err))

        return thread

    def init_borrow_btn(self, borrow_function):
        """
        Build a borrow button for Holds and Magazines tabs

        :param borrow_function:
        :return:
        """
        borrow_action_default_is_borrow = PREFS[
            PreferenceKeys.LAST_BORROW_ACTION
        ] == BorrowActions.BORROW or not hasattr(self, "download_loan")

        borrow_btn = BorrowAndDownloadButton(
            _("Borrow")
            if borrow_action_default_is_borrow
            else _("Borrow and Download"),
            self.icons[PluginIcons.Add],
            lambda: borrow_function(do_download=not borrow_action_default_is_borrow),
            self,
        )
        borrow_btn.setToolTip(
            _("Borrow selected title")
            if borrow_action_default_is_borrow
            else _("Borrow and download selected title")
        )
        if hasattr(self, "download_loan"):
            borrow_btn.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
            borrow_btn_menu = QMenu(borrow_btn)
            borrow_btn_menu_bnd_action = borrow_btn_menu.addAction(
                _("Borrow and Download")
                if borrow_action_default_is_borrow
                else _("Borrow")
            )
            borrow_btn_menu_bnd_action.triggered.connect(
                lambda: borrow_function(do_download=borrow_action_default_is_borrow)
            )
            borrow_btn_menu.borrow_action = borrow_btn_menu_bnd_action
            borrow_btn.borrow_menu = borrow_btn_menu
            borrow_btn.setMenu(borrow_btn_menu)
        return borrow_btn

    def rebind_borrow_btn(self, borrow_action: str, borrow_btn, borrow_function):
        """
        Shared func for rebinding and toggling the borrow button in the Holds and Mgazines tabs.

        :param borrow_action:
        :param borrow_btn:
        :param borrow_function:
        :return:
        """
        borrow_action_default_is_borrow = (
            borrow_action == BorrowActions.BORROW or not hasattr(self, "download_loan")
        )
        borrow_btn.setText(
            _("Borrow") if borrow_action_default_is_borrow else _("Borrow and Download")
        )
        borrow_btn.setToolTip(
            _("Borrow selected title")
            if borrow_action_default_is_borrow
            else _("Borrow and download selected title")
        )
        borrow_btn.set_action(
            lambda: borrow_function(do_download=not borrow_action_default_is_borrow)
        )
        if hasattr(borrow_btn, "borrow_menu") and hasattr(
            borrow_btn.borrow_menu, "borrow_action"
        ):
            borrow_btn.borrow_menu.borrow_action.setText(
                _("Borrow and Download")
                if borrow_action_default_is_borrow
                else _("Borrow")
            )
            try:
                borrow_btn.borrow_menu.borrow_action.triggered.disconnect()
            except TypeError:
                pass
            borrow_btn.borrow_menu.borrow_action.triggered.connect(
                lambda: borrow_function(do_download=borrow_action_default_is_borrow)
            )

    def rebind_borrow_buttons(self, do_download=False):
        """
        Calls the known rebind borrow button functions from tabs

        :param do_download:
        :return:
        """
        borrow_action = (
            BorrowActions.BORROW_AND_DOWNLOAD if do_download else BorrowActions.BORROW
        )
        if PREFS[PreferenceKeys.LAST_BORROW_ACTION] != borrow_action:
            PREFS[PreferenceKeys.LAST_BORROW_ACTION] = borrow_action
            if hasattr(self, "rebind_magazines_download_button_and_menu"):
                self.rebind_magazines_download_button_and_menu(borrow_action)
            if hasattr(self, "rebind_holds_download_button_and_menu"):
                self.rebind_holds_download_button_and_menu(borrow_action)


class CustomLoadingOverlay(LoadingOverlay):
    # Custom https://github.com/kovidgoyal/calibre/blob/a562c1f637cf2756fa8336860543a15951f4fbc0/src/calibre/gui2/viewer/overlay.py#L10
    def hide(self):
        self.pi.stop()
        return QWidget.hide(self)
