#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
import json
from typing import Dict, List

from calibre.constants import is_debugging
from calibre.gui2 import info_dialog, error_dialog
from calibre.gui2.viewer.overlay import LoadingOverlay
from calibre.gui2.widgets2 import CenteredToolButton
from polyglot.io import PolyglotStringIO
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
    QLabel,
)

from .. import logger, __version__, DEMO_MODE
from ..compat import _c, compat_enum
from ..config import PREFS, PreferenceKeys, BorrowActions
from ..libby import LibbyClient
from ..models import LibbyModel
from ..overdrive import OverDriveClient
from ..utils import PluginIcons
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
        self.min_view_width = 740

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
        self.tabs.currentChanged.connect(self.tab_current_changed)
        layout.addWidget(self.tabs, 0, 0)

        # Status bar
        self.status_bar = QStatusBar(self)
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setStyleSheet(
            "background-color: rgba(127, 127, 127, 0.1); border-radius: 4px;"
        )
        help_lbl = QLabel(
            '<a href="https://github.com/ping/libby-calibre-plugin#usage">'
            + _c("Help")
            + '</a> / <a href="https://www.mobileread.com/forums/showthread.php?t=354816">'
            + _("MobileRead")
            + "</a>"
        )
        help_lbl.setStyleSheet("margin: 0 4px")
        help_lbl.setAttribute(Qt.WA_TranslucentBackground)
        help_lbl.setTextFormat(Qt.RichText)
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setTextInteractionFlags(
            Qt.LinksAccessibleByKeyboard | Qt.LinksAccessibleByMouse
        )
        self.status_bar.addPermanentWidget(help_lbl)
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

    def add_tab(self, widget, label) -> int:
        """
        Helper method for adding tabs.
        We temporarily block QTabWidget signals because the `currentChanged` signal is emitted
        even on `addTab()`.

        :param widget:
        :param label:
        :return:
        """
        prev = self.tabs.blockSignals(True)
        new_tab_index = self.tabs.addTab(widget, label)
        self.tabs.blockSignals(prev)
        return new_tab_index

    def tab_current_changed(self, index: int):
        if index > -1:
            PREFS[PreferenceKeys.LAST_SELECTED_TAB] = index

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
            self.status_bar.showMessage(_("Libby is not configured yet."))
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
            try:
                for btn in self.refresh_buttons:
                    btn.setEnabled(True)

                holds = value.get("holds", [])
                holds_count = len(holds)
                holds_unique_count = len(list(set([h["id"] for h in holds])))
                self.status_bar.showMessage(
                    _(
                        "Synced {loans} loans, {holds} holds ({unique_holds} unique), {cards} cards, and {magazines} magazines."
                    ).format(
                        loans=len(value.get("loans", [])),
                        holds=holds_count,
                        unique_holds=holds_unique_count,
                        cards=len(value.get("cards", [])),
                        magazines=len(PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS]),
                    )
                    if not DEMO_MODE
                    else "",
                    5000,
                )
                for model in self.models:
                    model.sync(value)
            except RuntimeError as err:
                # most likely because the UI has been closed before syncing was completed
                logger.warning("Error processing sync results: %s", err)
            finally:
                thread.quit()

        def errored_out(err: Exception):
            try:
                thread.quit()
                self.loading_overlay.hide()
                self.status_bar.showMessage(
                    _("An error occured during sync: {err}").format(err=str(err))
                )
                for btn in self.refresh_buttons:
                    btn.setEnabled(True)
                return self.unhandled_exception(err, msg=_("Error synchronizing data"))
            except RuntimeError as err:
                # most likely because the UI has been closed before syncing was completed
                logger.warning("Error processing sync results: %s", err)

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
            borrow_btn.setPopupMode(
                compat_enum(QToolButton, "ToolButtonPopupMode.DelayedPopup")
            )
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

    def display_debug(self, text, data):
        if is_debugging():
            return info_dialog(
                self,
                _c("Debug"),
                text,
                det_msg=json.dumps(data, indent=2),
                show=True,
            )

    def unhandled_exception(self, err, msg=None):
        """
        Use this to handle unexpected job/sync errors instead of letting calibre's main window do it,
        so that it doesn't go below our modal plugin window in Windows.

        Adapter from
        https://github.com/kovidgoyal/calibre/blob/ffcaf382a277bd980771d36ce915cc451ef30b25/src/calibre/gui2/main_window.py#L216-L243

        :param err:
        :param msg:
        :return:
        """
        if err is KeyboardInterrupt:
            return
        import traceback

        try:
            sio = PolyglotStringIO(errors="replace")
            try:
                from calibre.debug import print_basic_debug_info

                print_basic_debug_info(out=sio)
            except:
                pass
            traceback.print_exception(err.__class__, err, err.__traceback__, file=sio)
            fe = sio.getvalue()
            if msg:
                msg = "<b>%s</b>: %s" % (err.__class__.__name__, msg)
            else:
                msg = "<b>%s</b>" % err.__class__.__name__
            return error_dialog(
                self, _c("Unhandled exception"), msg, det_msg=fe, show=True
            )
        except Exception as err:
            logger.exception(err)


class CustomLoadingOverlay(LoadingOverlay):
    # Custom https://github.com/kovidgoyal/calibre/blob/a562c1f637cf2756fa8336860543a15951f4fbc0/src/calibre/gui2/viewer/overlay.py#L10
    def hide(self):
        try:
            self.pi.stop()
            return QWidget.hide(self)
        except RuntimeError as err:
            # most likely because the UI has been closed before loading was completed
            logger.warning("Error hiding loading overlay: %s", err)
