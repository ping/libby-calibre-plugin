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

from calibre.gui2 import Dispatcher
from calibre.gui2.dialogs.confirm_delete import confirm
from calibre.gui2.ebook_download import show_download_info
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre.utils.localization import _ as _c
from polyglot.builtins import as_unicode
from qt.core import (
    Qt,
    QGridLayout,
    QPushButton,
    QCheckBox,
    QAbstractItemView,
    QTableView,
    QHeaderView,
    QSortFilterProxyModel,
    QMenu,
    QCursor,
    QWidget,
)

from .base import BaseDialogMixin
from .. import PluginIcons
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..ebook_download import CustomEbookDownload
from ..libby import LibbyClient
from ..loan_actions import LibbyLoanReturn
from ..magazine_download import CustomMagazineDownload
from ..magazine_download_utils import extract_isbn, extract_asin
from ..models import get_media_title, LibbyLoansModel, LibbyModel

load_translations()

gui_ebook_download = CustomEbookDownload()
gui_magazine_download = CustomMagazineDownload()
gui_libby_return = LibbyLoanReturn()


class LoansDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
        widget = QWidget()
        widget.layout = QGridLayout()
        for col_num in range(1, self.view_hspan - 2):
            widget.layout.setColumnStretch(col_num, 1)
        widget.layout.setColumnMinimumWidth(0, self.min_button_width)
        widget.layout.setColumnMinimumWidth(self.view_hspan - 1, self.min_button_width)
        widget.setLayout(widget.layout)
        widget_row_pos = 0

        # Refresh button
        self.loans_refresh_btn = QPushButton(_c("Refresh"), self)
        self.loans_refresh_btn.setIcon(self.icons[PluginIcons.Refresh])
        self.loans_refresh_btn.setAutoDefault(False)
        self.loans_refresh_btn.setToolTip(_("Get latest loans"))
        self.loans_refresh_btn.clicked.connect(self.loans_refresh_btn_clicked)
        widget.layout.addWidget(self.loans_refresh_btn, widget_row_pos, 0)
        self.refresh_buttons.append(self.loans_refresh_btn)
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
        self.loans_view.setMinimumWidth(self.min_view_width)
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
        self.loans_view.setTabKeyNavigation(
            False
        )  # prevents tab key being stuck in view
        # add context menu
        self.loans_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.loans_view.customContextMenuRequested.connect(
            self.loans_view_context_menu_requested
        )
        # add debug trigger
        self.loans_view.doubleClicked.connect(
            lambda mi: self.display_debug("Loan", mi.data(Qt.UserRole))
        )
        widget.layout.addWidget(
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
        widget.layout.addWidget(
            self.hide_book_already_in_lib_checkbox, widget_row_pos, 0, 1, 2
        )
        # Download button
        self.download_btn = QPushButton(_c("Download"), self)
        self.download_btn.setIcon(self.icons[PluginIcons.Download])
        self.download_btn.setAutoDefault(False)
        self.download_btn.setToolTip(_("Download selected loans"))
        self.download_btn.setStyleSheet("padding: 4px 16px")
        self.download_btn.clicked.connect(self.download_btn_clicked)
        widget.layout.addWidget(
            self.download_btn,
            widget_row_pos,
            self.view_hspan - 1,
        )
        self.refresh_buttons.append(self.download_btn)
        widget_row_pos += 1

        self.tab_index = self.tabs.addTab(widget, _("Loans"))

    def hide_book_already_in_lib_checkbox_state_changed(self, __):
        checked = self.hide_book_already_in_lib_checkbox.isChecked()
        self.loans_model.set_filter_hide_books_already_in_library(checked)
        self.loans_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_book_already_in_lib_checkbox_state_clicked(self, checked):
        if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] != checked:
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = checked
        # toggle the other checkbox on the magazines tab
        if (
            hasattr(self, "hide_mag_already_in_lib_checkbox")
            and self.hide_mag_already_in_lib_checkbox.isChecked() != checked
        ):
            self.hide_mag_already_in_lib_checkbox.setChecked(checked)

    def loans_refresh_btn_clicked(self):
        self.sync()

    def loans_view_context_menu_requested(self, pos):
        selection_model = self.loans_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, self.loans_model)
        )
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_overdrive_action.triggered.connect(
            lambda: self.view_in_overdrive_action_triggered(indices, self.loans_model)
        )
        return_action = menu.addAction(
            ngettext("Return {n} loan", "Return {n} loans", len(indices)).format(
                n=len(indices)
            )
        )
        return_action.setIcon(self.icons[PluginIcons.Return])
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
        # else:
        #     return error_dialog(
        #         self, _("Download"), _("Please select at least 1 loan."), show=True
        #     )

    def download_loan(self, loan: Dict):
        # do actual downloading of the loan
        format_id = LibbyClient.get_loan_format(
            loan, prefer_open_format=PREFS[PreferenceKeys.PREFER_OPEN_FORMATS]
        )
        if LibbyClient.is_downloadable_ebook_loan(loan):
            show_download_info(get_media_title(loan), self)
            tags = [t.strip() for t in PREFS[PreferenceKeys.TAG_EBOOKS].split(",")]

            self.download_ebook(
                loan,
                format_id,
                filename=f'{loan["id"]}.{LibbyClient.get_file_extension(format_id)}',
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
        tags=None,
        create_browser=None,
    ):
        if not tags:
            tags = []
        card = self.loans_model.get_card(loan["cardId"])
        library = self.loans_model.get_library(self.loans_model.get_website_id(card))

        # We will handle the downloading of the files ourselves

        # Matching an empty book:
        # If we find a book without formats and matches isbn/asin and odid (if enabled),
        # add the new file as a format to the existing book record
        book_id = None
        mi = None
        enable_overdrivelink_integration = PREFS[
            PreferenceKeys.OVERDRIVELINK_INTEGRATION
        ]
        search_query = "format:False"
        loan_isbn = extract_isbn(loan.get("formats", []), [format_id])
        loan_asin = extract_asin(loan.get("formats", []))
        identifier_conditions: List[str] = []
        if loan_isbn:
            identifier_conditions.append(f"identifiers:=isbn:{loan_isbn}")
        if loan_asin:
            identifier_conditions.append(f"identifiers:=asin:{loan_asin}")
            identifier_conditions.append(f"identifiers:=amazon:{loan_asin}")
        if enable_overdrivelink_integration:
            identifier_conditions.append(
                f'identifiers:"=odid:{loan["id"]}@{library["preferredKey"]}.overdrive.com"'
            )
        if identifier_conditions:
            # search for existing empty book only if there is at least 1 identifier
            search_query += " and (" + " or ".join(identifier_conditions) + ")"
            self.logger.debug("Library Search Query: %s", search_query)
            book_ids = list(self.db.search(search_query))
            book_id = book_ids[0] if book_ids else 0
            mi = self.db.get_metadata(book_id) if book_id else None
        if mi and book_id:
            self.logger.debug("Matched existing empty book: %s", mi.title)

        description = (
            _(
                "Downloading {format} for {book}".format(
                    format=LibbyClient.get_file_extension(format_id).upper(),
                    book=as_unicode(get_media_title(loan), errors="replace"),
                )
            )
            if book_id and mi
            else (
                _c("Downloading %s")
                % as_unicode(get_media_title(loan), errors="replace")
            )
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
                card,
                library,
                format_id,
                book_id,
                mi,
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
        tags=None,
        create_browser=None,
    ):
        if not tags:
            tags = []
        card = self.loans_model.get_card(loan["cardId"])
        library = self.loans_model.get_library(self.loans_model.get_website_id(card))

        # We will handle the downloading of the files ourselves instead of depending
        # on the calibre browser

        # Heavily referenced from
        # https://github.com/kovidgoyal/calibre/blob/58c609fa7db3a8df59981c3bf73823fa1862c392/src/calibre/gui2/ebook_download.py#L127-L152

        description = _c("Downloading %s") % as_unicode(
            get_media_title(loan), errors="replace"
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
                card,
                library,
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
        # callback after returning loan
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to return loan"))
            return

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)
