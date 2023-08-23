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
import re
from typing import Dict

from calibre.constants import DEBUG
from calibre.gui2 import Dispatcher, error_dialog, info_dialog
from calibre.gui2.threaded_jobs import ThreadedJob
from polyglot.builtins import as_unicode
from qt.core import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCursor,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QThread,
    QWidget,
    Qt,
)

from .base import BaseDialogMixin
from .widgets import DefaultQTableView
from ..borrow_book import LibbyBorrowMedia
from ..compat import (
    QHeaderView_ResizeMode_ResizeToContents,
    QHeaderView_ResizeMode_Stretch,
    _c,
)
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..libby import LibbyClient
from ..libby.client import LibbyFormats, LibbyMediaTypes
from ..models import (
    LibbyCardsModel,
    LibbyMagazinesModel,
    LibbyMagazinesSortFilterModel,
    get_media_title,
)
from ..overdrive import OverDriveClient
from ..utils import PluginImages
from ..workers import OverDriveLibraryMediaWorker

LIBBY_SHARE_URL_RE = re.compile(
    r"https://share\.libbyapp\.com/title/(?P<title_id>\d+)\b", re.IGNORECASE
)
LIBBY_URL_RE = re.compile(
    r"https://libbyapp.com/library/.+/(.*/)?page-\d+/(?P<title_id>\d+)\b", re.IGNORECASE
)
OVERDRIVE_URL_RE = re.compile(
    r"https://(.+)?overdrive.com/(.*/)?media/(?P<title_id>\d+)\b", re.IGNORECASE
)

# noinspection PyUnreachableCode
if False:
    load_translations = _ = lambda x=None: x


load_translations()

gui_libby_borrow_hold = LibbyBorrowMedia()


class MagazinesDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
        self._fetch_library_media_thread = QThread()

        magazines_widget = QWidget()
        magazines_widget.layout = QGridLayout()
        for col_num in range(1, self.view_hspan - 2):
            magazines_widget.layout.setColumnStretch(col_num, 1)
        for i in (0, self.view_hspan - 1, self.view_hspan - 2):
            magazines_widget.layout.setColumnMinimumWidth(i, self.min_button_width)
        magazines_widget.setLayout(magazines_widget.layout)
        widget_row_pos = 0

        # Share link label
        self.magazine_link_lbl = QLabel(
            _(
                "Paste the share link of the magazine you wish to favorite and select a library card. "
                "\nClick on the Add button to monitor this title for new issues."
            )
        )
        self.magazine_link_lbl.setWordWrap(True)
        magazines_widget.layout.addWidget(
            self.magazine_link_lbl, widget_row_pos, 0, 1, self.view_hspan
        )
        widget_row_pos += 1

        # Share link textbox
        self.magazine_link_txt = QLineEdit(self)
        self.magazine_link_txt.setPlaceholderText(
            "https://share.libbyapp.com/title/123456"
        )
        magazines_widget.layout.addWidget(
            self.magazine_link_txt, widget_row_pos, 0, 1, self.view_hspan - 2
        )
        self.magazine_link_lbl.setBuddy(self.magazine_link_txt)

        # Libraries combobox
        self.cards_model = LibbyCardsModel(None, [], self.db)  # model
        self.cards_cbbox = QComboBox(self)  # combobox
        self.cards_cbbox.setModel(self.cards_model)
        self.cards_cbbox.setModelColumn(0)
        magazines_widget.layout.addWidget(
            self.cards_cbbox, widget_row_pos, self.view_hspan - 2, 1, 1
        )

        # Add Magazine button
        self.add_magazine_btn = QPushButton(_c("Add"), self)
        self.add_magazine_btn.setIcon(self.resources[PluginImages.AddMagazine])
        self.add_magazine_btn.setAutoDefault(False)
        self.add_magazine_btn.setToolTip(_("Add to monitor for new issues"))
        self.add_magazine_btn.clicked.connect(self.add_magazine_btn_clicked)
        magazines_widget.layout.addWidget(
            self.add_magazine_btn, widget_row_pos, self.view_hspan - 1
        )
        widget_row_pos += 1

        # Refresh button
        self.magazines_refresh_btn = QPushButton(_c("Refresh"), self)
        self.magazines_refresh_btn.setIcon(self.resources[PluginImages.Refresh])
        self.magazines_refresh_btn.setAutoDefault(False)
        self.magazines_refresh_btn.setToolTip(_("Get latest magazines"))
        self.magazines_refresh_btn.clicked.connect(self.magazines_refresh_btn_clicked)
        magazines_widget.layout.addWidget(self.magazines_refresh_btn, widget_row_pos, 0)

        self.mags_filter_txt = QLineEdit(self)
        self.mags_filter_txt.setMaximumWidth(self.min_button_width)
        self.mags_filter_txt.setClearButtonEnabled(True)
        self.mags_filter_txt.setToolTip(_("Filter by Title, Library"))
        self.mags_filter_txt.textChanged.connect(self.magazines_filter_txt_textchanged)
        self.mags_filter_lbl = QLabel(_c("Filter"))
        self.mags_filter_lbl.setBuddy(self.mags_filter_txt)
        mags_filter_layout = QHBoxLayout()
        mags_filter_layout.addWidget(self.mags_filter_lbl, alignment=Qt.AlignRight)
        mags_filter_layout.addWidget(self.mags_filter_txt, 1)
        magazines_widget.layout.addLayout(
            mags_filter_layout, widget_row_pos, self.view_hspan - 2, 1, 2
        )
        widget_row_pos += 1

        self.magazines_model = LibbyMagazinesModel(None, [], self.db)
        self.magazines_search_proxy_model = LibbyMagazinesSortFilterModel(self, self.db)
        self.magazines_search_proxy_model.setSourceModel(self.magazines_model)

        # The main magazines list
        self.magazines_view = DefaultQTableView(
            self, model=self.magazines_search_proxy_model, min_width=self.min_view_width
        )
        horizontal_header = self.magazines_view.horizontalHeader()
        for col_index in range(self.magazines_model.columnCount()):
            horizontal_header.setSectionResizeMode(
                col_index,
                QHeaderView_ResizeMode_Stretch
                if col_index == 0
                else QHeaderView_ResizeMode_ResizeToContents,
            )
        self.magazines_view.setSelectionMode(QAbstractItemView.SingleSelection)
        # add context menu
        self.magazines_view.customContextMenuRequested.connect(
            self.magazines_view_context_menu_requested
        )
        # add debug trigger
        self.magazines_view.doubleClicked.connect(
            lambda mi: self.display_debug("Magazine", mi.data(Qt.UserRole))
            if DEBUG and mi.column() == self.magazines_model.columnCount() - 1
            else self.show_book_details(mi.data(Qt.UserRole))
        )
        magazines_view_selection_model = self.magazines_view.selectionModel()
        magazines_view_selection_model.selectionChanged.connect(
            self.magazines_view_selection_model_selectionchanged
        )

        magazines_widget.layout.addWidget(
            self.magazines_view, widget_row_pos, 0, self.view_vspan, self.view_hspan
        )
        widget_row_pos += self.view_vspan

        # Hide books already in lib checkbox
        self.hide_mag_already_in_lib_checkbox = QCheckBox(
            PreferenceTexts.HIDE_BOOKS_ALREADY_IN_LIB, self
        )
        self.hide_mag_already_in_lib_checkbox.setChecked(
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB]
        )
        self.hide_mag_already_in_lib_checkbox.clicked.connect(
            self.hide_mag_already_in_lib_checkbox_clicked
        )
        self.hide_mag_already_in_lib_checkbox.stateChanged.connect(
            self.hide_mag_already_in_lib_checkbox_state_changed
        )
        magazines_widget.layout.addWidget(
            self.hide_mag_already_in_lib_checkbox, widget_row_pos, 0, 1, 2
        )

        # Borrow button
        self.magazines_borrow_btn = self.init_borrow_btn(self.do_magazine_borrow_action)
        magazines_widget.layout.addWidget(
            self.magazines_borrow_btn, widget_row_pos, self.view_hspan - 1
        )
        widget_row_pos += 1

        self.magazines_tab_index = self.add_tab(magazines_widget, _("Magazines"))
        self.last_borrow_action_changed.connect(
            self.rebind_magazines_download_button_and_menu
        )
        self.sync_starting.connect(self.base_sync_starting_magazines)
        self.sync_ended.connect(self.base_sync_ended_magazines)
        self.loan_added.connect(self.loan_added_magazines)
        self.loan_removed.connect(self.loan_removed_magazines)
        self.hide_title_already_in_lib_pref_changed.connect(
            self.hide_title_already_in_lib_pref_changed_magazines
        )

    def loan_added_magazines(self, loan: Dict):
        self.magazines_model.add_loan(loan)

    def loan_removed_magazines(self, loan: Dict):
        self.magazines_model.remove_loan(loan)

    def base_sync_starting_magazines(self):
        self.magazines_refresh_btn.setEnabled(False)
        self.magazines_model.sync({})
        self.cards_model.sync({})

    def base_sync_ended_magazines(self, value):
        self.magazines_refresh_btn.setEnabled(True)
        self.magazines_model.sync(value)
        self.cards_model.sync(value)

    def rebind_magazines_download_button_and_menu(self, borrow_action):
        self.rebind_borrow_btn(
            borrow_action, self.magazines_borrow_btn, self.do_magazine_borrow_action
        )

    def do_magazine_borrow_action(self, do_download=False):
        self.rebind_borrow_buttons(do_download)

        selection_model = self.magazines_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        for index in indices:
            sub = index.data(Qt.UserRole)
            self.borrow_magazine(sub, do_download=do_download)

    def hide_title_already_in_lib_pref_changed_magazines(self, checked):
        if self.hide_mag_already_in_lib_checkbox.isChecked() != checked:
            self.hide_mag_already_in_lib_checkbox.setChecked(checked)

    def hide_mag_already_in_lib_checkbox_state_changed(self, __):
        checked = self.hide_mag_already_in_lib_checkbox.isChecked()
        self.magazines_search_proxy_model.set_filter_hide_magazines_already_in_library(
            checked
        )
        self.magazines_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_mag_already_in_lib_checkbox_clicked(self, checked: bool):
        if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] != checked:
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = checked
            self.hide_title_already_in_lib_pref_changed.emit(checked)

    def magazines_view_selection_model_selectionchanged(self):
        # enables/disables borrow button
        selection_model = self.magazines_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        for index in indices:
            magazine = index.data(Qt.UserRole)
            self.magazines_borrow_btn.setEnabled(
                not magazine.get("__is_borrowed", False)
            )
            self.status_bar.showMessage(get_media_title(magazine), 3000)

    def magazines_view_context_menu_requested(self, pos):
        selection_model = self.magazines_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, self.magazines_model)
        )
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_overdrive_action.triggered.connect(
            lambda: self.view_in_overdrive_action_triggered(
                indices, self.magazines_model
            )
        )

        selected_magazine = self.magazines_view.indexAt(pos).data(Qt.UserRole)
        # view book details
        self.add_view_book_details_menu_action(menu, selected_magazine)
        # find calibre matches
        self.add_find_library_match_menu_action(menu, selected_magazine)

        unsub_action = menu.addAction(_c("Cancel"))
        unsub_action.setIcon(self.resources[PluginImages.CancelMagazine])
        unsub_action.triggered.connect(lambda: self.unsub_action_triggered(indices))
        menu.exec(QCursor.pos())

    def magazines_filter_txt_textchanged(self, text):
        self.magazines_search_proxy_model.set_filter_text(text)

    def magazines_refresh_btn_clicked(self):
        self.sync()

    def unsub_action_triggered(self, indices):
        # remove subscribed magazine
        title_ids = []
        for index in indices:
            sub = index.data(Qt.UserRole)
            title_ids.append(sub["parentMagazineTitleId"])
            self.magazines_model.removeRow(
                self.magazines_search_proxy_model.mapToSource(index).row()
            )
        if title_ids:
            subscriptions = [
                sub
                for sub in PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS]
                if sub["parent_magazine_id"] not in title_ids
            ]
            PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS] = subscriptions

    def borrow_magazine(self, magazine, do_download=False):
        # do actual borrowing
        card = self.magazines_model.get_card(magazine["cardId"])
        description = _("Borrowing {book}").format(
            book=as_unicode(get_media_title(magazine), errors="replace")
        )
        callback = Dispatcher(
            self.borrowed_magazine_and_download
            if do_download
            else self.borrowed_magazine
        )
        job = ThreadedJob(
            "overdrive_libby_borrow_book",
            description,
            gui_libby_borrow_hold,
            (self.gui, self.client, magazine, card, False),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def borrowed_magazine(self, job):
        # callback after magazine is borrowed
        if job.failed:
            return self.unhandled_exception(
                job.exception, msg=_("Failed to borrow magazine")
            )

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def borrowed_magazine_and_download(self, job):
        # callback after magazine is borrowed
        self.borrowed_magazine(job)
        if (not job.failed) and job.result and hasattr(self, "download_loan"):
            # this is actually from the loans tab
            self.download_loan(job.result)

    def add_magazine_btn_clicked(self):
        share_url = self.magazine_link_txt.text().strip()
        mobj = (
            LIBBY_SHARE_URL_RE.match(share_url)
            or LIBBY_URL_RE.match(share_url)
            or OVERDRIVE_URL_RE.match(share_url)
        )
        if not mobj:
            return error_dialog(
                self,
                _("Add Magazine"),
                _("Invalid URL {url}").format(url=share_url),
                show=True,
            )

        card = self.cards_model.data(
            self.cards_model.index(self.cards_cbbox.currentIndex(), 0), Qt.UserRole
        )
        title_id = mobj.group("title_id")
        if not self._fetch_library_media_thread.isRunning():
            self._fetch_library_media_thread = self._get_fetch_library_media_thread(
                self.overdrive_client, card, title_id
            )
            self.add_magazine_btn.setEnabled(False)
            self.setCursor(Qt.WaitCursor)
            self._fetch_library_media_thread.start()

    def found_media(self, media, card):
        # callback after media is found
        if not (
            media.get("type", {}).get("id", "") == LibbyMediaTypes.Magazine
            and LibbyClient.has_format(media, LibbyFormats.MagazineOverDrive)
        ):
            return error_dialog(
                self,
                _("Add Magazine"),
                _(
                    "{media} is not a downloadable magazine".format(
                        media=media["title"]
                    )
                ),
                det_msg=json.dumps(media, indent=2),
                show=True,
            )
        if not (media.get("isOwned") and media.get("parentMagazineTitleId")):
            return error_dialog(
                self,
                _("Add Magazine"),
                _("{library} does not own this title").format(
                    library=self.magazines_model.get_library(
                        self.magazines_model.get_website_id(card)
                    )["name"]
                ),
                det_msg=json.dumps(media, indent=2),
                show=True,
            )
        card_id = card["cardId"]
        parent_magazine_id = media["parentMagazineTitleId"]
        subscriptions = PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS]
        if [
            sub
            for sub in subscriptions
            if sub["parent_magazine_id"] == parent_magazine_id
        ]:
            return error_dialog(
                self,
                _("Add Magazine"),
                _("Already monitoring {magazine}").format(magazine=media["title"]),
                show_copy_button=False,
                show=True,
            )
        subscriptions.append(
            {
                "card_id": card_id,
                "parent_magazine_id": parent_magazine_id,
            }
        )
        PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS] = subscriptions
        self.magazine_link_txt.setText("")
        if info_dialog(
            self,
            _("Add Magazine"),
            _(
                "Added {magazine} for monitoring.\nClick OK to refresh, or the ESC key to continue without.".format(
                    magazine=media["title"]
                )
            ),
            show_copy_button=False,
            show=True,
        ):
            self.sync()

    def _get_fetch_library_media_thread(
        self, overdrive_client: OverDriveClient, card: Dict, title_id: str
    ):
        thread = QThread()
        worker = OverDriveLibraryMediaWorker()
        worker.setup(overdrive_client, card, title_id)
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(media):
            self.found_media(media, card)
            self.unsetCursor()
            self.add_magazine_btn.setEnabled(True)
            thread.quit()

        def errored_out(err: Exception):
            self.unsetCursor()
            self.add_magazine_btn.setEnabled(True)
            thread.quit()
            raise err

        worker.finished.connect(lambda media: loaded(media))
        worker.errored.connect(lambda err: errored_out(err))

        return thread
