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

from calibre.constants import DEBUG
from calibre.gui2 import Dispatcher, open_url
from calibre.gui2.dialogs.confirm_delete import confirm
from calibre.gui2.ebook_download import show_download_info
from calibre.gui2.threaded_jobs import ThreadedJob
from polyglot.builtins import as_unicode
from qt.core import (
    QCheckBox,
    QCursor,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QThread,
    QWidget,
    Qt,
)

from .base import BaseDialogMixin
from .widgets import DefaultQPushButton, DefaultQTableView
from ..compat import (
    QHeaderView_ResizeMode_ResizeToContents,
    QHeaderView_ResizeMode_Stretch,
    _c,
)
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..ebook_download import CustomEbookDownload
from ..empty_download import EmptyBookDownload
from ..libby import LibbyClient, LibbyFormats
from ..loan_actions import LibbyLoanRenew, LibbyLoanReturn
from ..magazine_download import CustomMagazineDownload
from ..models import (
    LibbyLoansModel,
    LibbyLoansSortFilterModel,
    get_media_title,
    truncate_for_display,
)
from ..overdrive import OverDriveClient
from ..utils import PluginImages
from ..workers import LibbyFulfillLoanWorker

# noinspection PyUnreachableCode
if False:
    load_translations = _ = ngettext = lambda x=None, y=None, z=None: x

load_translations()

gui_ebook_download = CustomEbookDownload()
gui_magazine_download = CustomMagazineDownload()
guid_empty_download = EmptyBookDownload()
gui_libby_return = LibbyLoanReturn()
gui_renew_loan = LibbyLoanRenew()


class LoansDialogMixin(BaseDialogMixin):
    def __init__(self, *args):
        super().__init__(*args)
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
        self.loans_refresh_btn = DefaultQPushButton(
            _c("Refresh"), self.resources[PluginImages.Refresh], self
        )
        self.loans_refresh_btn.setToolTip(_("Get latest loans"))
        self.loans_refresh_btn.clicked.connect(self.loans_refresh_btn_clicked)
        widget.layout.addWidget(self.loans_refresh_btn, widget_row_pos, 0)

        self.loans_filter_txt = QLineEdit(self)
        self.loans_filter_txt.setMinimumWidth(self.min_button_width)
        self.loans_filter_txt.setClearButtonEnabled(True)
        self.loans_filter_txt.setToolTip(_("Filter by Title, Author, Library"))
        self.loans_filter_txt.textChanged.connect(self.loans_filter_txt_textchanged)
        self.loans_filter_lbl = QLabel(_c("Filter"))
        self.loans_filter_lbl.setBuddy(self.loans_filter_txt)
        loan_filter_layout = QHBoxLayout()
        loan_filter_layout.addWidget(self.loans_filter_lbl)
        loan_filter_layout.addWidget(self.loans_filter_txt, 1)
        widget.layout.addLayout(
            loan_filter_layout, widget_row_pos, self.view_hspan - 2, 1, 2
        )
        widget_row_pos += 1

        self.loans_model = LibbyLoansModel(None, [], self.db, self.resources)
        self.loans_search_proxy_model = LibbyLoansSortFilterModel(
            self, model=self.loans_model, db=self.db
        )

        # The main loan list
        self.loans_view = DefaultQTableView(
            self, model=self.loans_search_proxy_model, min_width=self.min_view_width
        )
        horizontal_header = self.loans_view.horizontalHeader()
        for col_index in range(self.loans_model.columnCount()):
            horizontal_header.setSectionResizeMode(
                col_index,
                QHeaderView_ResizeMode_Stretch
                if col_index == 0
                else QHeaderView_ResizeMode_ResizeToContents,
            )
        # add context menu
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
            if DEBUG and mi.column() == self.loans_model.columnCount() - 1
            else self.show_book_details(mi.data(Qt.UserRole))
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
        self.download_btn = DefaultQPushButton(
            _c("Download"), self.resources[PluginImages.Download], self
        )
        self.download_btn.setToolTip(_("Download selected loans"))
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
        self.loan_added.connect(self.loan_added_loans)
        self.hold_added.connect(self.hold_added_loans)
        self.loan_removed.connect(self.loan_removed_loans)
        self.hold_removed.connect(self.hold_removed_loans)
        self.hide_title_already_in_lib_pref_changed.connect(
            self.hide_title_already_in_lib_pref_changed_loans
        )

    def loan_added_loans(self, loan: Dict):
        self.loans_model.add_loan(loan)

    def loan_removed_loans(self, loan: Dict):
        self.loans_model.remove_loan(loan)

    def hold_added_loans(self, hold: Dict):
        self.loans_model.add_hold(hold)

    def hold_removed_loans(self, hold: Dict):
        self.loans_model.remove_hold(hold)

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
        self.loans_search_proxy_model.set_filter_hide_books_already_in_library(checked)
        self.loans_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_book_already_in_lib_checkbox_state_clicked(self, checked):
        if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] != checked:
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = checked
            self.hide_title_already_in_lib_pref_changed.emit(checked)

    def loans_filter_txt_textchanged(self, text):
        self.loans_search_proxy_model.set_filter_text(text)

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

        # add view in OverDrive/Libby menu actions
        self.add_view_in_menu_actions(menu, indices, self.loans_model)

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
                read_with_kindle_action.setIcon(self.resources[PluginImages.Amazon])
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

        # view book details
        self.add_view_book_details_menu_action(menu, selected_loan)
        # copy share link
        self.add_copy_share_link_menu_action(menu, selected_loan)
        # find calibre matches
        self.add_find_library_match_menu_action(menu, selected_loan)
        # search for title
        self.add_search_for_title_menu_action(menu, selected_loan)

        return_action = menu.addAction(
            ngettext("Return {n} loan", "Return {n} loans", len(indices)).format(
                n=len(indices)
            )
        )
        return_action.setIcon(self.resources[PluginImages.Return])
        return_action.triggered.connect(lambda: self.return_action_triggered(indices))

        if LibbyClient.is_renewable(selected_loan):
            if selected_loan.get("availableCopies") or not selected_loan.get(
                "holdsCount"
            ):
                renew_action = menu.addAction(
                    _('Renew "{book}"').format(book=get_media_title(selected_loan))
                )
                renew_action.setIcon(self.resources[PluginImages.Renew])
                renew_action.triggered.connect(
                    lambda: self.renew_action_triggered(selected_loan)
                )

            else:
                hold_action = menu.addAction(
                    _('Place hold on "{book}"').format(
                        book=get_media_title(selected_loan)
                    )
                )
                hold_action.setIcon(self.resources[PluginImages.Add])
                if not self.loans_model.has_hold(selected_loan):
                    hold_action.triggered.connect(
                        lambda: self.hold_action_triggered(selected_loan)
                    )
                else:
                    hold_action.setEnabled(False)
                    hold_action.setToolTip(_("An existing hold already exists."))

        menu.exec(QCursor.pos())

    def renew_action_triggered(self, loan):
        self.renew_loan(loan)

    def hold_action_triggered(self, loan):
        card = self.loans_model.get_card(loan["cardId"])
        self.create_hold(loan, card)

    def download_btn_clicked(self):
        selection_model = self.loans_view.selectionModel()
        if selection_model.hasSelection():
            rows = selection_model.selectedRows()
            for row in reversed(rows):
                self.download_loan(row.data(Qt.UserRole))
                if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB]:
                    self.loans_search_proxy_model.temporarily_hide(
                        row.data(Qt.UserRole)
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

    def match_existing_book(self, loan: Dict, library: Dict, format_id: str):
        book_id = None
        mi = None
        if not PREFS[PreferenceKeys.ALWAYS_DOWNLOAD_AS_NEW]:
            search_conditions = self.generate_search_conditions(
                loan, library, format_id
            )
            if search_conditions:
                # search for existing empty book only if there is at least 1 search condition
                search_query = " or ".join(search_conditions)
                restriction = "format:False"
                # use restriction because it's apparently cached
                # ref: https://manual.calibre-ebook.com/db_api.html#calibre.db.cache.Cache.search
                self.logger.debug(
                    "Library Search Query (with restriction: %s): %s",
                    restriction,
                    search_query,
                )
                book_ids = list(self.db.search(search_query, restriction=restriction))
                # prioritise match by identifiers
                loan_isbn = OverDriveClient.extract_isbn(
                    loan.get("formats", []), [format_id] if format_id else []
                )
                if format_id and not loan_isbn:
                    # try again without format_id
                    loan_isbn = OverDriveClient.extract_isbn(
                        loan.get("formats", []), []
                    )
                loan_asin = OverDriveClient.extract_asin(loan.get("formats", []))
                for bi in book_ids:
                    identifiers = self.db.get_metadata(bi).get_identifiers()
                    if (
                        loan_isbn
                        and identifiers.get("isbn")
                        and loan_isbn == identifiers.get("isbn")
                    ) or (
                        loan_asin
                        and identifiers.get("amazon")
                        and loan_asin == identifiers.get("amazon")
                    ):
                        book_id = bi
                        break
                if not book_id:
                    # we still haven't matched one using identifiers, then just take the first one
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

        book_id, mi = self.match_existing_book(loan, library, format_id)
        if mi and book_id:
            self.logger.debug("Matched existing empty book: %s", mi.title)

        description = _c("Downloading %s") % as_unicode(
            get_media_title(loan), errors="replace"
        )

        callback = Dispatcher(self.downloaded_loan)
        job = ThreadedJob(
            "overdrive_libby_download_magazine",
            description,
            gui_magazine_download,
            (
                self.gui,
                self.client,
                self.overdrive_client,
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

        self.loan_removed.emit(job.result)
        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def downloaded_loan(self, job):
        if job.failed:
            # self.gui.job_exception(job, dialog_title=_c("Failed to download e-book"))
            self.unhandled_exception(job.exception, msg=_c("Failed to download e-book"))

        try:
            if job.result:
                self.loans_search_proxy_model.unhide(job.result)
        except RuntimeError as runtime_err:
            # most likely because the plugin UI was closed before download was completed
            self.logger.warning("Error displaying media results: %s", runtime_err)
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
                self.client,
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
                open_url(fulfilment_link)
            self.unsetCursor()
            thread.quit()

        def errored_out(err: Exception):
            self.unsetCursor()
            thread.quit()
            raise err

        worker.finished.connect(lambda details: loaded(details))
        worker.errored.connect(lambda err: errored_out(err))

        return thread

    def renew_loan(self, loan):
        # create the hold
        description = _("Renewing loan on {book}").format(
            book=as_unicode(get_media_title(loan), errors="replace")
        )
        callback = Dispatcher(self.loan_renewed)
        job = ThreadedJob(
            "overdrive_libby_renew_loan",
            description,
            gui_renew_loan,
            (self.gui, self.client, loan),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def loan_renewed(self, job):
        # callback after loan is renewed
        if job.failed:
            return self.unhandled_exception(
                job.exception, msg=_("Failed to renew loan")
            )

        updated_loan = job.result
        for r in range(self.loans_model.rowCount()):
            index = self.loans_model.index(r, 0)
            loan = index.data(Qt.UserRole)
            if (
                loan["id"] == updated_loan["id"]
                and loan["cardId"] == updated_loan["cardId"]
            ):
                self.loans_model.setData(index, updated_loan)
                break

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)
