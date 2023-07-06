#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from pathlib import Path
from typing import Dict

from calibre import browser
from calibre.gui2 import Dispatcher, error_dialog, is_dark_theme
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.dialogs.confirm_delete import confirm
from calibre.gui2.ebook_download import show_download_info
from calibre.gui2.threaded_jobs import ThreadedJob
from polyglot.builtins import as_unicode

# noinspection PyUnresolvedReferences
from qt.core import (
    Qt,
    QToolButton,
    QDialog,
    QGridLayout,
    QPushButton,
    QCheckBox,
    QAbstractItemView,
    QTableView,
    QHeaderView,
    QSortFilterProxyModel,
    QThread,
    QStatusBar,
    QSize,
    QMenu,
    QCursor,
    QUrl,
    QDesktopServices,
    QTabWidget,
    QWidget,
)

from . import logger, PLUGIN_NAME, PLUGIN_ICON, __version__
from .borrow_book import LibbyBorrowHold
from .config import PREFS, PreferenceKeys, PreferenceTexts
from .ebook_download import CustomEbookDownload
from .hold_cancel import LibbyHoldCancel
from .libby import LibbyClient
from .libby.client import LibbyFormats
from .loan_return import LibbyLoanReturn
from .magazine_download import CustomMagazineDownload
from .model import get_loan_title, LibbyLoansModel, LibbyHoldsModel
from .worker import SyncDataWorker

load_translations()

ICON_MAP = {
    "return": "arrow-go-back-fill.png",
    "download": "download-line.png",
    "ext-link": "external-link-line.png",
    "refresh": "refresh-line.png",
    "borrow": "file-add-line.png",
    "cancel_hold": "delete-bin-line.png",
}


class OverdriveLibbyAction(InterfaceAction):
    name = PLUGIN_NAME
    action_spec = (
        "OverDrive Libby",
        None,
        _("Run the OverDrive Libby client UI"),
        None,
    )
    popup_type = QToolButton.MenuButtonPopup
    action_type = "current"
    dont_add_to = frozenset(["context-menu-device"])

    def genesis(self):
        # This method is called once per plugin, do initial setup here

        # extract icons
        theme_folder = Path("images").joinpath(
            "dark-theme" if is_dark_theme() else "light-theme"
        )
        icons_resources = get_icons(
            [str(theme_folder.joinpath(v)) for v in ICON_MAP.values()] + [PLUGIN_ICON]
        )
        self.icons = {}
        for k, v in ICON_MAP.items():
            self.icons[k] = icons_resources.pop(str(theme_folder.joinpath(v)))

        # action icon
        self.qaction.setIcon(icons_resources.pop(PLUGIN_ICON))
        self.qaction.triggered.connect(self.show_dialog)

    def show_dialog(self):
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        d = OverdriveLibbyDialog(
            self.gui, self.qaction.icon(), do_user_config, self.icons
        )
        d.setModal(True)
        d.show()

    def apply_settings(self):
        pass


gui_ebook_download = CustomEbookDownload()
gui_magazine_download = CustomMagazineDownload()
gui_libby_return = LibbyLoanReturn()
gui_libby_cancel_hold = LibbyHoldCancel()
gui_libby_borrow_hold = LibbyBorrowHold()


class OverdriveLibbyDialog(QDialog):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.gui = gui
        self.do_user_config = do_user_config
        self.icons = icons
        self.db = gui.current_db.new_api
        self.client = None
        self.__sync_thread = QThread()
        self.__curr_width = 0
        self.__curr_height = 0

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

        layout = QGridLayout()
        self.setLayout(layout)

        self.tabs = QTabWidget(self)

        # Loans Tab -------------------------
        loans_widget = QWidget()
        loans_widget.layout = QGridLayout()
        loans_widget.setLayout(loans_widget.layout)

        loan_view_hspan = 8
        loan_view_vspan = 3
        loans_widget_row_pos = 0

        # Refresh button
        self.loans_refresh_btn = QPushButton(_("Refresh"), self)
        self.loans_refresh_btn.setIcon(self.icons["refresh"])
        self.loans_refresh_btn.setAutoDefault(False)
        self.loans_refresh_btn.setToolTip(_("Get latest loans"))
        self.loans_refresh_btn.clicked.connect(self.do_refresh)
        loans_widget.layout.addWidget(self.loans_refresh_btn, loans_widget_row_pos, 0)

        # Status bar
        self.loans_status_bar = QStatusBar(self)
        self.loans_status_bar.setSizeGripEnabled(False)
        loans_widget.layout.addWidget(
            self.loans_status_bar, loans_widget_row_pos, 1, 1, 3
        )
        loans_widget_row_pos += 1

        self.loans_model = LibbyLoansModel(None, [], self.db)
        self.loans_search_proxy_model = QSortFilterProxyModel(self)
        self.loans_search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.loans_search_proxy_model.setFilterKeyColumn(-1)
        self.loans_search_proxy_model.setSourceModel(self.loans_model)
        self.loans_search_proxy_model.setSortRole(LibbyLoansModel.DisplaySortRole)

        # The main loan list
        self.loans_view = QTableView(self)
        self.loans_view.setSortingEnabled(True)
        self.loans_view.setAlternatingRowColors(True)
        self.loans_view.setMinimumWidth(720)
        self.loans_view.setModel(self.loans_search_proxy_model)
        horizontal_header = self.loans_view.horizontalHeader()
        for col_index, mode in [
            (0, QHeaderView.ResizeMode.Stretch),
            (1, QHeaderView.ResizeMode.ResizeToContents),
            (2, QHeaderView.ResizeMode.ResizeToContents),
            (3, QHeaderView.ResizeMode.ResizeToContents),
            (4, QHeaderView.ResizeMode.ResizeToContents),
        ]:
            horizontal_header.setSectionResizeMode(col_index, mode)
        self.loans_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.loans_view.sortByColumn(-1, Qt.AscendingOrder)
        # add context menu
        self.loans_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.loans_view.customContextMenuRequested.connect(self.loans_view_context_menu)
        loans_widget.layout.addWidget(
            self.loans_view, loans_widget_row_pos, 0, loan_view_vspan, loan_view_hspan
        )
        loans_widget_row_pos += loan_view_vspan

        # Download button
        self.download_btn = QPushButton(_("Download"), self)
        self.download_btn.setIcon(self.icons["download"])
        self.download_btn.setAutoDefault(False)
        self.download_btn.setToolTip(_("Download selected loans"))
        self.download_btn.setStyleSheet("padding: 4px 16px")
        self.download_btn.clicked.connect(self.download_selected_loans)
        loans_widget.layout.addWidget(
            self.download_btn, loans_widget_row_pos, loan_view_hspan - 1
        )

        # Hide books already in lib checkbox
        self.hide_book_already_in_lib_checkbox = QCheckBox(
            PreferenceTexts.HIDE_BOOKS_ALREADY_IN_LIB, self
        )
        self.hide_book_already_in_lib_checkbox.clicked.connect(
            self.set_hide_books_already_in_library
        )
        self.hide_book_already_in_lib_checkbox.setChecked(
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB]
        )
        loans_widget.layout.addWidget(
            self.hide_book_already_in_lib_checkbox, loans_widget_row_pos, 0, 1, 3
        )
        loans_widget_row_pos += 1

        self.tabs.addTab(loans_widget, _("Loans"))

        # Holds Tab -------------------------
        holds_widget = QWidget()
        holds_widget.layout = QGridLayout()
        holds_widget.setLayout(holds_widget.layout)
        holds_widget_row_pos = 0

        # Refresh button
        self.holds_refresh_btn = QPushButton(_("Refresh"), self)
        self.holds_refresh_btn.setIcon(self.icons["refresh"])
        self.holds_refresh_btn.setAutoDefault(False)
        self.holds_refresh_btn.setToolTip(_("Get latest holds"))
        self.holds_refresh_btn.clicked.connect(self.do_refresh)
        holds_widget.layout.addWidget(self.holds_refresh_btn, holds_widget_row_pos, 0)
        # Status bar
        self.holds_status_bar = QStatusBar(self)
        self.holds_status_bar.setSizeGripEnabled(False)
        holds_widget.layout.addWidget(
            self.holds_status_bar, holds_widget_row_pos, 1, 1, 3
        )
        holds_widget_row_pos += 1

        self.holds_model = LibbyHoldsModel(None, [], self.db)
        self.holds_search_proxy_model = QSortFilterProxyModel(self)
        self.holds_search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.holds_search_proxy_model.setFilterKeyColumn(-1)
        self.holds_search_proxy_model.setSourceModel(self.holds_model)
        self.holds_search_proxy_model.setSortRole(LibbyHoldsModel.DisplaySortRole)

        # The main holds list
        self.holds_view = QTableView(self)
        self.holds_view.setSortingEnabled(True)
        self.holds_view.setAlternatingRowColors(True)
        self.holds_view.setMinimumWidth(720)
        self.holds_view.setModel(self.holds_search_proxy_model)
        horizontal_header = self.holds_view.horizontalHeader()
        for col_index, mode in [
            (0, QHeaderView.ResizeMode.Stretch),
            (1, QHeaderView.ResizeMode.ResizeToContents),
            (2, QHeaderView.ResizeMode.ResizeToContents),
            (3, QHeaderView.ResizeMode.ResizeToContents),
            (4, QHeaderView.ResizeMode.ResizeToContents),
            (5, QHeaderView.ResizeMode.ResizeToContents),
        ]:
            horizontal_header.setSectionResizeMode(col_index, mode)
        self.holds_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.holds_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.holds_view.sortByColumn(-1, Qt.AscendingOrder)
        # add context menu
        self.holds_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.holds_view.customContextMenuRequested.connect(self.holds_view_context_menu)
        holds_view_selection_model = self.holds_view.selectionModel()
        holds_view_selection_model.selectionChanged.connect(
            self.toggle_borrow_btn_state
        )
        holds_widget.layout.addWidget(
            self.holds_view, holds_widget_row_pos, 0, loan_view_vspan, loan_view_hspan
        )
        holds_widget_row_pos += loan_view_vspan

        # Borrow button
        self.borrow_btn = QPushButton(_("Borrow"), self)
        self.borrow_btn.setIcon(self.icons["borrow"])
        self.borrow_btn.setAutoDefault(False)
        self.borrow_btn.setToolTip(_("Borrow selected hold"))
        self.borrow_btn.setStyleSheet("padding: 4px 16px")
        self.borrow_btn.clicked.connect(self.borrow_selected_hold)
        holds_widget.layout.addWidget(
            self.borrow_btn, holds_widget_row_pos, loan_view_hspan - 1
        )

        # Hide unavailable holds
        self.hide_unavailable_holds_checkbox = QCheckBox(
            _("Hide unavailable holds"), self
        )
        self.hide_unavailable_holds_checkbox.clicked.connect(
            self.set_hide_unavailable_holds
        )
        self.hide_unavailable_holds_checkbox.setChecked(True)
        holds_widget.layout.addWidget(
            self.hide_unavailable_holds_checkbox, holds_widget_row_pos, 0, 1, 3
        )
        holds_widget_row_pos += 1

        self.tabs.addTab(holds_widget, _("Holds"))

        layout.addWidget(self.tabs, 0, 0)

        if (
            PREFS[PreferenceKeys.MAIN_UI_WIDTH]
            and PREFS[PreferenceKeys.MAIN_UI_WIDTH] > 0
            and PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
            and PREFS[PreferenceKeys.MAIN_UI_HEIGHT] > 0
        ):
            logger.debug(
                "Resizing window using saved preferences: (%d, %d)",
                PREFS[PreferenceKeys.MAIN_UI_WIDTH],
                PREFS[PreferenceKeys.MAIN_UI_HEIGHT],
            )
            self.resize(
                QSize(
                    PREFS[PreferenceKeys.MAIN_UI_WIDTH],
                    PREFS[PreferenceKeys.MAIN_UI_HEIGHT],
                )
            )
        else:
            self.resize(self.sizeHint())

        # for pseudo-debouncing resizeEvent
        self.__curr_width = self.size().width()
        self.__curr_height = self.size().height()

        self.sync()

    def resizeEvent(self, e):
        # Because resizeEvent is called *multiple* times during a resize,
        # we will save the new window size only when the differential is
        # greater than min_diff.
        # This does not completely debounce the saves, but it does reduce
        # it reasonably imo.
        new_size = e.size()
        new_width = new_size.width()
        new_height = new_size.height()
        min_diff = 5
        if (
            new_width
            and new_width > 0
            and abs(new_width - self.__curr_width) >= min_diff
            and new_width != PREFS[PreferenceKeys.MAIN_UI_WIDTH]
        ):
            PREFS[PreferenceKeys.MAIN_UI_WIDTH] = new_width
            self.__curr_width = new_width
            logger.debug("Saved new UI width preference: %d", new_width)
        if (
            new_height
            and new_height > 0
            and abs(new_height - self.__curr_height) >= min_diff
            and new_height != PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
        ):
            PREFS[PreferenceKeys.MAIN_UI_HEIGHT] = new_height
            self.__curr_height = new_height
            logger.debug("Saved new UI height preference: %d", new_height)

    def do_refresh(self):
        self.loans_model.sync({})
        self.holds_model.sync({})
        self.sync()

    def sync(self):
        if not self.__sync_thread.isRunning():
            self.loans_refresh_btn.setEnabled(False)
            self.holds_refresh_btn.setEnabled(False)
            self.loans_status_bar.showMessage(_("Synchronizing..."))
            self.holds_status_bar.showMessage(_("Synchronizing..."))
            self.__sync_thread = self.__get_sync_thread()
            self.__sync_thread.start()

    def __get_sync_thread(self):
        thread = QThread()
        worker = SyncDataWorker()
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(value: Dict):
            self.loans_model.sync(value)
            self.holds_model.sync(value)
            self.loans_refresh_btn.setEnabled(True)
            self.holds_refresh_btn.setEnabled(True)
            self.loans_status_bar.clearMessage()
            self.holds_status_bar.clearMessage()
            thread.quit()

        worker.finished.connect(lambda value: loaded(value))

        return thread

    def set_hide_books_already_in_library(self, checked: bool):
        PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = checked
        self.loans_model.set_filter_hide_books_already_in_library(checked)
        self.loans_view.sortByColumn(-1, Qt.AscendingOrder)

    def set_hide_unavailable_holds(self, checked: bool):
        self.holds_model.set_filter_hide_unavailable_holds(checked)
        self.holds_view.sortByColumn(-1, Qt.AscendingOrder)

    def loans_view_context_menu(self, pos):
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_action = menu.addAction(_("View in Libby"))
        view_action.setIcon(self.icons["ext-link"])
        view_action.triggered.connect(
            lambda: self.open_selected_in_libby(indices, self.loans_model)
        )
        return_action = menu.addAction(
            ngettext("Return {n} loan", "Return {n} loans", len(indices)).format(
                n=len(indices)
            )
        )
        return_action.setIcon(self.icons["return"])
        return_action.triggered.connect(lambda: self.return_selected_loans(indices))
        menu.exec(QCursor.pos())

    def holds_view_context_menu(self, pos):
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_action = menu.addAction(_("View in Libby"))
        view_action.setIcon(self.icons["ext-link"])
        view_action.triggered.connect(
            lambda: self.open_selected_in_libby(indices, self.holds_model)
        )
        cancel_action = menu.addAction(_("Cancel hold"))
        cancel_action.setIcon(self.icons["cancel_hold"])
        cancel_action.triggered.connect(lambda: self.cancel_selected_hold(indices))
        menu.exec(QCursor.pos())

    def toggle_borrow_btn_state(self, selected, deselected):
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        for index in indices:
            hold = index.data(Qt.UserRole)
            self.borrow_btn.setEnabled(hold.get("isAvailable", False))

    def download_selected_loans(self):
        selection_model = self.loans_view.selectionModel()
        if selection_model.hasSelection():
            rows = selection_model.selectedRows()
            for row in reversed(rows):
                self.download_loan(row.data(Qt.UserRole))
        else:
            return error_dialog(
                self, _("Download"), _("Please select at least 1 loan."), show=True
            )

    def cancel_selected_hold(self, indices):
        msg = (
            _("Cancel this hold?")
            + "\n- "
            + "\n- ".join(
                [get_loan_title(index.data(Qt.UserRole)) for index in indices]
            )
        )
        if confirm(
            msg,
            name=PreferenceKeys.CONFIRM_RETURNS,
            parent=self,
            title=_("Cancel Holds"),
            config_set=PREFS,
        ):
            for index in reversed(indices):
                hold = index.data(Qt.UserRole)
                self.cancel_hold(hold)
                self.holds_model.removeRow(
                    self.holds_search_proxy_model.mapToSource(index).row()
                )

    def download_loan(self, loan: Dict):
        format_id = LibbyClient.get_loan_format(
            loan, prefer_open_format=PREFS[PreferenceKeys.PREFER_OPEN_FORMATS]
        )
        if LibbyClient.is_downloadable_ebook_loan(loan):
            show_download_info(get_loan_title(loan), self)
            tags = [t.strip() for t in PREFS[PreferenceKeys.TAG_EBOOKS].split(",")]
            if format_id in (LibbyFormats.EBookEPubOpen, LibbyFormats.EBookPDFOpen):
                # special handling required for these formats
                self.download_ebook(
                    loan,
                    format_id,
                    filename=f'{loan["id"]}.{LibbyClient.get_file_extension(format_id)}',
                    tags=tags,
                )
            else:
                endpoint_url, headers = self.client.get_loan_fulfilment_details(
                    loan["id"], loan["cardId"], format_id
                )

                def create_custom_browser():
                    br = browser()
                    for k, v in headers.items():
                        br.set_header(k, v)
                    return br

                self.gui.download_ebook(
                    url=endpoint_url,
                    create_browser=create_custom_browser,
                    tags=tags,
                )

        if LibbyClient.is_downloadable_magazine_loan(loan):
            show_download_info(get_loan_title(loan), self)
            tags = [t.strip() for t in PREFS[PreferenceKeys.TAG_MAGAZINES].split(",")]
            self.download_magazine(
                loan,
                format_id,
                filename=f'{loan["id"]}.{LibbyClient.get_file_extension(format_id)}',
                tags=tags,
            )

    def download_ebook(
        self,
        loan: Dict,
        format_id: str,
        url="",
        cookie_file=None,
        filename="",
        save_loc="",
        add_to_lib=True,
        tags=[],
        create_browser=None,
    ):
        # We will handle the downloading of the files ourselves instead of depending
        # on the calibre browser

        # Heavily referenced from
        # https://github.com/kovidgoyal/calibre/blob/58c609fa7db3a8df59981c3bf73823fa1862c392/src/calibre/gui2/ebook_download.py#L127-L152

        description = _("Downloading {book}").format(
            book=as_unicode(get_loan_title(loan), errors="replace")
        )
        callback = Dispatcher(self.gui.downloaded_ebook)
        job = ThreadedJob(
            "overdrive_libby_download",
            description,
            gui_ebook_download,
            (
                self.gui,
                self.client,
                loan,
                format_id,
                cookie_file,
                url,
                filename,
                save_loc,
                add_to_lib,
                tags,
                create_browser,
            ),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def download_magazine(
        self,
        loan: Dict,
        format_id: str,
        url="",
        cookie_file=None,
        filename="",
        save_loc="",
        add_to_lib=True,
        tags=[],
        create_browser=None,
    ):
        # We will handle the downloading of the files ourselves instead of depending
        # on the calibre browser

        # Heavily referenced from
        # https://github.com/kovidgoyal/calibre/blob/58c609fa7db3a8df59981c3bf73823fa1862c392/src/calibre/gui2/ebook_download.py#L127-L152

        description = _("Downloading {book}").format(
            book=as_unicode(get_loan_title(loan), errors="replace")
        )
        callback = Dispatcher(self.gui.downloaded_ebook)
        job = ThreadedJob(
            "overdrive_libby_download",
            description,
            gui_magazine_download,
            (
                self.gui,
                self.client,
                loan,
                format_id,
                cookie_file,
                url,
                filename,
                save_loc,
                add_to_lib,
                tags,
                create_browser,
            ),
            {},
            callback,
            max_concurrent_count=2,
            killable=True,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def open_selected_in_libby(self, indices, model):
        for index in indices:
            loan = index.data(Qt.UserRole)
            library_key = model.get_card(loan["cardId"])["advantageKey"]
            QDesktopServices.openUrl(
                QUrl(LibbyClient.libby_title_permalink(library_key, loan["id"]))
            )

    def return_selected_loans(self, indices):
        msg = (
            ngettext(
                "Return this loan?", "Return these {n} loans?", len(indices)
            ).format(n=len(indices))
            + "\n- "
            + "\n- ".join(
                [get_loan_title(index.data(Qt.UserRole)) for index in indices]
            )
        )

        if confirm(
            msg,
            name=PreferenceKeys.CONFIRM_RETURNS,
            parent=self,
            title=_("Return Loans"),
            config_set=PREFS,
        ):
            for index in reversed(indices):
                loan = index.data(Qt.UserRole)
                self.return_loan(loan)
                self.loans_model.removeRow(
                    self.loans_search_proxy_model.mapToSource(index).row()
                )

    def return_loan(self, loan: Dict):
        description = _("Returning {book}").format(
            book=as_unicode(get_loan_title(loan), errors="replace")
        )
        callback = Dispatcher(self.returned_loan)
        job = ThreadedJob(
            "overdrive_libby_return",
            description,
            gui_libby_return,
            (self.gui, self.client, loan),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def returned_loan(self, job):
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to return loan"))
            return

        self.gui.status_bar.show_message(job.description + " " + _("finished"), 5000)

    def borrow_selected_hold(self):
        selection_model = self.holds_view.selectionModel()
        if selection_model.hasSelection():
            rows = selection_model.selectedRows()
            for row in reversed(rows):
                self.borrow_hold(row.data(Qt.UserRole))

    def borrow_hold(self, hold):
        card = self.holds_model.get_card(hold["cardId"])
        description = _("Borrowing {book}").format(
            book=as_unicode(get_loan_title(hold), errors="replace")
        )
        callback = Dispatcher(self.borrowed_book)
        job = ThreadedJob(
            "overdrive_libby_borrow_book",
            description,
            gui_libby_borrow_hold,
            (self.gui, self.client, hold, card),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def borrowed_book(self, job):
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to borrow book"))
            return

        self.gui.status_bar.show_message(job.description + " " + _("finished"), 5000)

    def cancel_hold(self, hold: Dict):
        description = _("Cancelling hold on {book}").format(
            book=as_unicode(get_loan_title(hold), errors="replace")
        )
        callback = Dispatcher(self.cancelled_hold)
        job = ThreadedJob(
            "overdrive_libby_cancel_hold",
            description,
            gui_libby_cancel_hold,
            (self.gui, self.client, hold),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def cancelled_hold(self, job):
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to cancel hold"))
            return

        self.gui.status_bar.show_message(job.description + " " + _("finished"), 5000)
