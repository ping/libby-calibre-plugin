#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

from typing import Dict

from calibre import browser
from calibre.gui2 import Dispatcher, error_dialog
from calibre.gui2.dialogs.confirm_delete import confirm
from calibre.gui2.ebook_download import show_download_info
from calibre.gui2.threaded_jobs import ThreadedJob
from polyglot.builtins import as_unicode

# noinspection PyUnresolvedReferences
from qt.core import (
    Qt,
    QGridLayout,
    QPushButton,
    QCheckBox,
    QAbstractItemView,
    QTableView,
    QHeaderView,
    QSortFilterProxyModel,
    QStatusBar,
    QMenu,
    QCursor,
    QWidget,
)

from .base import BaseDialogMixin
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..ebook_download import CustomEbookDownload
from ..libby import LibbyClient
from ..libby.client import LibbyFormats
from ..loan_return import LibbyLoanReturn
from ..magazine_download import CustomMagazineDownload
from ..model import get_media_title, LibbyLoansModel, LibbyModel

load_translations()

gui_ebook_download = CustomEbookDownload()
gui_magazine_download = CustomMagazineDownload()
gui_libby_return = LibbyLoanReturn()


class LoansDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
        loans_widget = QWidget()
        loans_widget.layout = QGridLayout()
        loans_widget.setLayout(loans_widget.layout)

        widget_row_pos = 0

        # Refresh button
        self.loans_refresh_btn = QPushButton(_("Refresh"), self)
        self.loans_refresh_btn.setIcon(self.icons["refresh"])
        self.loans_refresh_btn.setAutoDefault(False)
        self.loans_refresh_btn.setToolTip(_("Get latest loans"))
        self.loans_refresh_btn.clicked.connect(self.loans_refresh_btn_clicked)
        loans_widget.layout.addWidget(self.loans_refresh_btn, widget_row_pos, 0)
        self.refresh_buttons.append(self.loans_refresh_btn)

        # Status bar
        self.loans_status_bar = QStatusBar(self)
        self.loans_status_bar.setSizeGripEnabled(False)
        loans_widget.layout.addWidget(
            self.loans_status_bar, widget_row_pos, 1, 1, self.view_hspan - 1
        )
        self.status_bars.append(self.loans_status_bar)
        widget_row_pos += 1

        self.loans_model = LibbyLoansModel(None, [], self.db)
        self.loans_search_proxy_model = QSortFilterProxyModel(self)
        self.loans_search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.loans_search_proxy_model.setFilterKeyColumn(-1)
        self.loans_search_proxy_model.setSourceModel(self.loans_model)
        self.loans_search_proxy_model.setSortRole(LibbyModel.DisplaySortRole)
        self.models.append(self.loans_model)

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
        self.loans_view.customContextMenuRequested.connect(
            self.loans_view_context_menu_requested
        )
        loans_widget.layout.addWidget(
            self.loans_view, widget_row_pos, 0, self.view_vspan, self.view_hspan
        )
        widget_row_pos += self.view_vspan

        # Hide books already in lib checkbox
        self.hide_book_already_in_lib_checkbox = QCheckBox(
            PreferenceTexts.HIDE_BOOKS_ALREADY_IN_LIB, self
        )
        self.hide_book_already_in_lib_checkbox.setChecked(
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB]
        )
        self.hide_book_already_in_lib_checkbox.clicked.connect(
            self.hide_book_already_in_lib_checkbox_state_clicked
        )
        self.hide_book_already_in_lib_checkbox.stateChanged.connect(
            self.hide_book_already_in_lib_checkbox_state_changed
        )
        loans_widget.layout.addWidget(
            self.hide_book_already_in_lib_checkbox,
            widget_row_pos,
            0,
            1,
            self.view_hspan - 1,
        )
        # Download button
        self.download_btn = QPushButton(_("Download"), self)
        self.download_btn.setIcon(self.icons["download"])
        self.download_btn.setAutoDefault(False)
        self.download_btn.setToolTip(_("Download selected loans"))
        self.download_btn.setStyleSheet("padding: 4px 16px")
        self.download_btn.clicked.connect(self.download_btn_clicked)
        loans_widget.layout.addWidget(
            self.download_btn,
            widget_row_pos,
            self.view_hspan - 1,
        )
        self.refresh_buttons.append(self.download_btn)
        widget_row_pos += 1

        loans_widget.layout.setColumnMinimumWidth(0, 120)

        self.tab_index = self.tabs.addTab(loans_widget, _("Loans"))

    def hide_book_already_in_lib_checkbox_state_changed(self, __):
        checked = self.hide_book_already_in_lib_checkbox.isChecked()
        self.loans_model.set_filter_hide_books_already_in_library(checked)
        self.loans_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_book_already_in_lib_checkbox_state_clicked(self, checked):
        if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] != checked:
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = checked
        self.loans_model.set_filter_hide_books_already_in_library(checked)
        self.loans_view.sortByColumn(-1, Qt.AscendingOrder)

    def loans_refresh_btn_clicked(self):
        self.sync()

    def loans_view_context_menu_requested(self, pos):
        selection_model = self.loans_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.icons["ext-link"])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, self.loans_model)
        )
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.icons["ext-link"])
        view_in_overdrive_action.triggered.connect(
            lambda: self.view_in_overdrive_action_triggered(indices, self.loans_model)
        )
        return_action = menu.addAction(
            ngettext("Return {n} loan", "Return {n} loans", len(indices)).format(
                n=len(indices)
            )
        )
        return_action.setIcon(self.icons["return"])
        return_action.triggered.connect(lambda: self.return_action_triggered(indices))
        menu.exec(QCursor.pos())

    def download_btn_clicked(self):
        selection_model = self.loans_view.selectionModel()
        if selection_model.hasSelection():
            rows = selection_model.selectedRows()
            for row in reversed(rows):
                self.download_loan(row.data(Qt.UserRole))
                if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB]:
                    self.loans_model.removeRow(
                        self.loans_search_proxy_model.mapToSource(row).row()
                    )
        else:
            return error_dialog(
                self, _("Download"), _("Please select at least 1 loan."), show=True
            )

    def download_loan(self, loan: Dict):
        format_id = LibbyClient.get_loan_format(
            loan, prefer_open_format=PREFS[PreferenceKeys.PREFER_OPEN_FORMATS]
        )
        if LibbyClient.is_downloadable_ebook_loan(loan):
            show_download_info(get_media_title(loan), self)
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
            show_download_info(get_media_title(loan), self)
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
            book=as_unicode(get_media_title(loan), errors="replace")
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
            book=as_unicode(get_media_title(loan), errors="replace")
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

    def return_action_triggered(self, indices):
        msg = (
            ngettext(
                "Return this loan?", "Return these {n} loans?", len(indices)
            ).format(n=len(indices))
            + "\n- "
            + "\n- ".join(
                [get_media_title(index.data(Qt.UserRole)) for index in indices]
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
            book=as_unicode(get_media_title(loan), errors="replace")
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
