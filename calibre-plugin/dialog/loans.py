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
from polyglot.builtins import as_unicode
from qt.core import (
    QAbstractItemView,
    QCheckBox,
    QCursor,
    QGridLayout,
    QMenu,
    QPushButton,
    QSortFilterProxyModel,
    QTableView,
    QThread,
    QWidget,
    Qt,
)

from .base import BaseDialogMixin
from ..compat import (
    QHeaderView_ResizeMode_ResizeToContents,
    QHeaderView_ResizeMode_Stretch,
    _c,
)
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..ebook_download import CustomEbookDownload
from ..empty_download import EmptyBookDownload
from ..libby import LibbyClient, LibbyFormats
from ..loan_actions import LibbyLoanReturn
from ..magazine_download import CustomMagazineDownload
from ..models import LibbyLoansModel, LibbyModel, get_media_title, truncate_for_display
from ..overdrive import OverDriveClient
from ..utils import OD_IDENTIFIER, PluginIcons, generate_od_identifier
from ..workers import LibbyFulfillLoanWorker

# noinspection PyUnreachableCode
if False:
    load_translations = _ = ngettext = lambda x=None, y=None, z=None: x

load_translations()

gui_ebook_download = CustomEbookDownload()
gui_magazine_download = CustomMagazineDownload()
guid_empty_download = EmptyBookDownload()
gui_libby_return = LibbyLoanReturn()


class LoansDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
        self._readwithkindle_thread = QThread()

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
        widget_row_pos += 1

        self.loans_model = LibbyLoansModel(None, [], self.db, self.icons)
        self.loans_search_proxy_model = QSortFilterProxyModel(self)
        self.loans_search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.loans_search_proxy_model.setFilterKeyColumn(-1)
        self.loans_search_proxy_model.setSourceModel(self.loans_model)
        self.loans_search_proxy_model.setSortRole(LibbyModel.DisplaySortRole)

        # The main loan list
        self.loans_view = QTableView(self)
        self.loans_view.setSortingEnabled(True)
        self.loans_view.setAlternatingRowColors(True)
        self.loans_view.setMinimumWidth(self.min_view_width)
        self.loans_view.setModel(self.loans_search_proxy_model)
        horizontal_header = self.loans_view.horizontalHeader()
        for col_index in range(self.loans_model.columnCount()):
            horizontal_header.setSectionResizeMode(
                col_index,
                QHeaderView_ResizeMode_Stretch
                if col_index == 0
                else QHeaderView_ResizeMode_ResizeToContents,
            )
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
        # selection change
        self.loans_view.selectionModel().selectionChanged.connect(
            self.loans_view_selection_model_selectionchanged
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
        widget_row_pos += 1

        self.loans_tab_index = self.add_tab(widget, _("Loans"))
        self.sync_starting.connect(self.base_sync_starting_loans)
        self.sync_ended.connect(self.base_sync_ended_loans)
        self.hide_title_already_in_lib_pref_changed.connect(
            self.hide_title_already_in_lib_pref_changed_loans
        )

    def base_sync_starting_loans(self):
        self.loans_refresh_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.loans_model.sync({})

    def base_sync_ended_loans(self, value):
        self.loans_refresh_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.loans_model.sync(value)

    def hide_title_already_in_lib_pref_changed_loans(self, checked):
        if self.hide_book_already_in_lib_checkbox.isChecked() != checked:
            self.hide_book_already_in_lib_checkbox.setChecked(checked)

    def hide_book_already_in_lib_checkbox_state_changed(self, __):
        checked = self.hide_book_already_in_lib_checkbox.isChecked()
        self.loans_model.set_filter_hide_books_already_in_library(checked)
        self.loans_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_book_already_in_lib_checkbox_state_clicked(self, checked):
        if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] != checked:
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = checked
            self.hide_title_already_in_lib_pref_changed.emit(checked)

    def loans_refresh_btn_clicked(self):
        self.sync()

    def loans_view_selection_model_selectionchanged(self, selected, deselected):
        selection_model = self.loans_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        loan = indices[-1].data(Qt.UserRole)
        self.status_bar.showMessage(get_media_title(loan), 3000)

    def loans_view_context_menu_requested(self, pos):
        selection_model = self.loans_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, self.loans_model)
        )
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.icons[PluginIcons.ExternalLink])

        selected_loan = self.loans_view.indexAt(pos).data(Qt.UserRole)
        if PREFS[PreferenceKeys.INCL_NONDOWNLOADABLE_TITLES]:
            # Read with Kindle
            locked_in_format = LibbyClient.get_locked_in_format(selected_loan)
            if (locked_in_format == LibbyFormats.EBookKindle) or (
                # not yet locked into any format
                LibbyClient.has_format(selected_loan, LibbyFormats.EBookKindle)
                and not locked_in_format
            ):
                read_with_kindle_action = menu.addAction(
                    _('Read "{book}" with Kindle').format(
                        book=truncate_for_display(get_media_title(selected_loan))
                    )
                )
                read_with_kindle_action.setIcon(self.icons[PluginIcons.Amazon])
                if (
                    LibbyClient.is_downloadable_ebook_loan(selected_loan)
                    and not locked_in_format
                ):
                    read_with_kindle_action.setToolTip(
                        "<p>"
                        + _(
                            "If you choose to Read with Kindle, this loan will be <u>format-locked</u> "
                            "and not downloadable."
                        )
                        + "</p>"
                    )
                read_with_kindle_action.triggered.connect(
                    lambda: self.read_with_kindle_action_triggered(
                        selected_loan, LibbyFormats.EBookKindle
                    )
                )

        if hasattr(self, "search_for"):
            search_action = menu.addAction(
                _('Search for "{book}"').format(
                    book=truncate_for_display(get_media_title(selected_loan))
                )
            )
            search_action.setIcon(self.icons[PluginIcons.Search])
            search_action.triggered.connect(
                lambda: self.search_for(
                    f'{get_media_title(selected_loan)} {selected_loan.get("firstCreatorName", "")}'
                )
            )

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

    def download_loan(self, loan: Dict):
        # do actual downloading of the loan

        try:
            format_id = LibbyClient.get_loan_format(
                loan, prefer_open_format=PREFS[PreferenceKeys.PREFER_OPEN_FORMATS]
            )
        except ValueError:
            # kindle
            tags = [t.strip() for t in PREFS[PreferenceKeys.TAG_EBOOKS].split(",")]
            format_id = LibbyClient.get_locked_in_format(loan)
            if format_id:
                # create empty book
                return self.download_empty_book(loan, format_id, tags)

        if LibbyClient.is_downloadable_audiobook_loan(loan):
            return self.download_empty_book(loan, format_id)

        if LibbyClient.is_downloadable_ebook_loan(loan):
            show_download_info(get_media_title(loan), self)
            tags = [t.strip() for t in PREFS[PreferenceKeys.TAG_EBOOKS].split(",")]

            return self.download_ebook(
                loan,
                format_id,
                filename=f'{loan["id"]}.{LibbyClient.get_file_extension(format_id)}',
                tags=tags,
            )

        if LibbyClient.is_downloadable_magazine_loan(loan):
            show_download_info(get_media_title(loan), self)
            tags = [t.strip() for t in PREFS[PreferenceKeys.TAG_MAGAZINES].split(",")]
            return self.download_magazine(
                loan,
                format_id,
                filename=f'{loan["id"]}.{LibbyClient.get_file_extension(format_id)}',
                tags=tags,
            )

        return self.download_empty_book(loan, format_id)

    def match_existing_book(self, loan, library, format_id):
        book_id = None
        mi = None
        if not PREFS[PreferenceKeys.ALWAYS_DOWNLOAD_AS_NEW]:
            loan_isbn = OverDriveClient.extract_isbn(
                loan.get("formats", []), [format_id] if format_id else []
            )
            if format_id and not loan_isbn:
                # try again without format_id
                loan_isbn = OverDriveClient.extract_isbn(loan.get("formats", []), [])
            loan_asin = OverDriveClient.extract_asin(loan.get("formats", []))
            identifier_conditions: List[str] = []
            if loan_isbn:
                identifier_conditions.append(f'identifiers:"=isbn:{loan_isbn}"')
            if loan_asin:
                identifier_conditions.append(f'identifiers:"=asin:{loan_asin}"')
                identifier_conditions.append(f'identifiers:"=amazon:{loan_asin}"')
            if PREFS[PreferenceKeys.OVERDRIVELINK_INTEGRATION]:
                identifier_conditions.append(
                    f'identifiers:"={OD_IDENTIFIER}:{generate_od_identifier(loan, library)}"'
                )
            if identifier_conditions:
                # search for existing empty book only if there is at least 1 identifier
                search_query = " or ".join(identifier_conditions)
                restriction = "format:False"
                # use restriction because it's apparently cached
                # ref: https://manual.calibre-ebook.com/db_api.html#calibre.db.cache.Cache.search
                self.logger.debug(
                    "Library Search Query (with restriction: %s): %s",
                    restriction,
                    search_query,
                )
                book_ids = list(self.db.search(search_query, restriction=restriction))
                book_id = book_ids[0] if book_ids else 0
                mi = self.db.get_metadata(book_id) if book_id else None
        return book_id, mi

    def download_ebook(self, loan: Dict, format_id: str, filename: str, tags=None):
        if not tags:
            tags = []
        card = self.loans_model.get_card(loan["cardId"])
        library = self.loans_model.get_library(self.loans_model.get_website_id(card))

        # We will handle the downloading of the files ourselves

        book_id, mi = self.match_existing_book(loan, library, format_id)
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
        callback = Dispatcher(self.downloaded_loan)
        job = ThreadedJob(
            "overdrive_libby_download_book",
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
                filename,
                tags,
            ),
            {},
            callback,
            max_concurrent_count=1,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def download_magazine(self, loan: Dict, format_id: str, filename: str, tags=None):
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

        callback = Dispatcher(self.downloaded_loan)
        job = ThreadedJob(
            "overdrive_libby_download_magazine",
            description,
            gui_magazine_download,
            (self.gui, self.client, loan, card, library, format_id, filename, tags),
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
            return self.unhandled_exception(
                job.exception, msg=_("Failed to return loan")
            )

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def downloaded_loan(self, job):
        if job.failed:
            # self.gui.job_exception(job, dialog_title=_c("Failed to download e-book"))
            self.unhandled_exception(job.exception, msg=_c("Failed to download e-book"))

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def download_empty_book(self, loan, format_id, tags=None):
        if not tags:
            tags = []
        card = self.loans_model.get_card(loan["cardId"])
        library = self.loans_model.get_library(self.loans_model.get_website_id(card))

        book_id, mi = self.match_existing_book(loan, library, format_id)
        description = _(
            "Downloading empty book for {book}".format(
                book=as_unicode(get_media_title(loan), errors="replace")
            )
        )
        callback = Dispatcher(self.downloaded_loan)
        job = ThreadedJob(
            "overdrive_libby_download_book",
            description,
            guid_empty_download,
            (
                self.gui,
                self.overdrive_client,
                loan,
                card,
                library,
                format_id,
                book_id,
                mi,
                tags,
            ),
            {},
            callback,
            max_concurrent_count=1,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def read_with_kindle_action_triggered(self, loan: Dict, format_id: str):
        require_confirmation = LibbyClient.is_downloadable_ebook_loan(
            loan
        ) and not LibbyClient.get_locked_in_format(loan)

        if (not require_confirmation) or confirm(
            "<p>"
            + _(
                "If you choose to Read with Kindle, this loan will be <u>format-locked</u> "
                "and not downloadable."
            )
            + "</p></p>"
            + _("Do you wish to continue?")
            + "</p>",
            name=PreferenceKeys.CONFIRM_READ_WITH_KINDLE,
            parent=self,
            title=_("Read with Kindle"),
            config_set=PREFS,
        ):
            if not self._readwithkindle_thread.isRunning():
                self._readwithkindle_thread = self._get_readwithkindle_thread(
                    self.client, loan, format_id
                )
                self.setCursor(Qt.WaitCursor)
                self._readwithkindle_thread.start()

    def _get_readwithkindle_thread(self, libby_client, loan: Dict, format_id: str):
        thread = QThread()
        worker = LibbyFulfillLoanWorker()
        worker.setup(libby_client, loan, format_id)
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(fulfilment_details):
            fulfilment_link = fulfilment_details.get("fulfill", {}).get("href")
            if fulfilment_link:
                self.open_link(fulfilment_link)
            self.unsetCursor()
            thread.quit()

        def errored_out(err: Exception):
            self.unsetCursor()
            thread.quit()
            raise err

        worker.finished.connect(lambda details: loaded(details))
        worker.errored.connect(lambda err: errored_out(err))

        return thread
