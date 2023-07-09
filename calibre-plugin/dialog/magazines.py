#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
import re

from calibre.gui2 import Dispatcher, error_dialog
from calibre.gui2.threaded_jobs import ThreadedJob
from polyglot.builtins import as_unicode

# noinspection PyUnresolvedReferences
from qt.core import (
    Qt,
    QWidget,
    QGridLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QAbstractItemView,
    QTableView,
    QHeaderView,
    QSortFilterProxyModel,
    QCheckBox,
    QMenu,
    QCursor,
    QThread,
)

from .base import BaseDialogMixin
from .. import PluginIcons
from ..borrow_book import LibbyBorrowHold
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..libby import LibbyClient
from ..libby.client import LibbyFormats, LibbyMediaTypes
from ..model import get_media_title, LibbyMagazinesModel, LibbyCardsModel, LibbyModel

LIBBY_SHARE_URL_RE = re.compile(
    r"https://share\.libbyapp\.com/title/(?P<title_id>\d+)\b", re.IGNORECASE
)
LIBBY_URL_RE = re.compile(
    r"https://libbyapp.com/library/.+/(.*/)?page-\d+/(?P<title_id>\d+)\b", re.IGNORECASE
)
OVERDRIVE_URL_RE = re.compile(
    r"https://(.+)?overdrive.com/(.*/)?media/(?P<title_id>\d+)\b", re.IGNORECASE
)

load_translations()

gui_libby_borrow_hold = LibbyBorrowHold()


class MagazinesDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
        self._sync_magazines_thread = QThread()

        magazines_widget = QWidget()
        magazines_widget.layout = QGridLayout()
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
        self.models.append(self.cards_model)
        self.cards_cbbox = QComboBox(self)  # combobox
        self.cards_cbbox.setModel(self.cards_model)
        self.cards_cbbox.setModelColumn(0)
        magazines_widget.layout.addWidget(
            self.cards_cbbox, widget_row_pos, self.view_hspan - 2
        )

        # Add Magazine button
        self.add_magazine_btn = QPushButton(_("Add"), self)
        self.add_magazine_btn.setIcon(self.icons[PluginIcons.AddMagazine])
        self.add_magazine_btn.setAutoDefault(False)
        self.add_magazine_btn.setToolTip(_("Add to monitor for new issues"))
        self.add_magazine_btn.clicked.connect(self.add_magazine_btn_clicked)
        magazines_widget.layout.addWidget(
            self.add_magazine_btn, widget_row_pos, self.view_hspan - 1
        )
        widget_row_pos += 1

        # Refresh button
        self.magazines_refresh_btn = QPushButton(_("Refresh"), self)
        self.magazines_refresh_btn.setIcon(self.icons[PluginIcons.Refresh])
        self.magazines_refresh_btn.setAutoDefault(False)
        self.magazines_refresh_btn.setToolTip(_("Get latest magazines"))
        self.magazines_refresh_btn.clicked.connect(self.magazines_refresh_btn_clicked)
        magazines_widget.layout.addWidget(self.magazines_refresh_btn, widget_row_pos, 0)
        widget_row_pos += 1

        self.magazines_model = LibbyMagazinesModel(None, [], self.db)
        self.magazines_search_proxy_model = QSortFilterProxyModel(self)
        self.magazines_search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.magazines_search_proxy_model.setFilterKeyColumn(-1)
        self.magazines_search_proxy_model.setSourceModel(self.magazines_model)
        self.magazines_search_proxy_model.setSortRole(LibbyModel.DisplaySortRole)
        self.models.append(self.magazines_model)

        # The main magazines list
        self.magazines_view = QTableView(self)
        self.magazines_view.setSortingEnabled(True)
        self.magazines_view.setAlternatingRowColors(True)
        self.magazines_view.setMinimumWidth(720)
        self.magazines_view.setModel(self.magazines_search_proxy_model)
        horizontal_header = self.magazines_view.horizontalHeader()
        for col_index, mode in [
            (0, QHeaderView.ResizeMode.Stretch),
            (1, QHeaderView.ResizeMode.ResizeToContents),
            (2, QHeaderView.ResizeMode.ResizeToContents),
        ]:
            horizontal_header.setSectionResizeMode(col_index, mode)
        self.magazines_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.magazines_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.magazines_view.sortByColumn(-1, Qt.AscendingOrder)
        # add context menu
        self.magazines_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.magazines_view.customContextMenuRequested.connect(
            self.magazines_view_context_menu_requested
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
        self.magazines_borrow_btn = QPushButton(_("Borrow"), self)
        self.magazines_borrow_btn.setIcon(self.icons[PluginIcons.Add])
        self.magazines_borrow_btn.setAutoDefault(False)
        self.magazines_borrow_btn.setToolTip(_("Borrow selected magazine"))
        self.magazines_borrow_btn.setStyleSheet("padding: 4px 16px")
        self.magazines_borrow_btn.clicked.connect(self.magazines_borrow_btn_clicked)
        magazines_widget.layout.addWidget(
            self.magazines_borrow_btn, widget_row_pos, self.view_hspan - 1
        )
        widget_row_pos += 1

        self.tab_index = self.tabs.addTab(magazines_widget, _("Magazines"))

    def hide_mag_already_in_lib_checkbox_state_changed(self, __):
        checked = self.hide_mag_already_in_lib_checkbox.isChecked()
        self.magazines_model.set_filter_hide_magazines_already_in_library(checked)
        self.magazines_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_mag_already_in_lib_checkbox_clicked(self, checked: bool):
        if PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] != checked:
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = checked
        # toggle the other checkbox on the loans tab
        if (
            hasattr(self, "hide_book_already_in_lib_checkbox")
            and self.hide_book_already_in_lib_checkbox.isChecked() != checked
        ):
            self.hide_book_already_in_lib_checkbox.setChecked(checked)

    def magazines_view_selection_model_selectionchanged(self):
        selection_model = self.magazines_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        for index in indices:
            magazine = index.data(Qt.UserRole)
            self.magazines_borrow_btn.setEnabled(
                not magazine.get("__is_borrowed", False)
            )

    def magazines_view_context_menu_requested(self, pos):
        selection_model = self.magazines_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, self.magazines_model)
        )
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_overdrive_action.triggered.connect(
            lambda: self.view_in_overdrive_action_triggered(
                indices, self.magazines_model
            )
        )
        unsub_action = menu.addAction(_("Cancel"))
        unsub_action.setIcon(self.icons[PluginIcons.CancelMagazine])
        unsub_action.triggered.connect(lambda: self.unsub_action_triggered(indices))
        menu.exec(QCursor.pos())

    def magazines_refresh_btn_clicked(self):
        self.sync()

    def magazines_borrow_btn_clicked(self):
        selection_model = self.magazines_view.selectionModel()
        if selection_model.hasSelection():
            rows = selection_model.selectedRows()
            for row in rows:
                self.borrow_magazine(row.data(Qt.UserRole))

    def unsub_action_triggered(self, indices):
        title_ids = []
        for index in reversed(indices):
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

    def borrow_magazine(self, magazine):
        card = self.magazines_model.get_card(magazine["cardId"])
        description = _("Borrowing {book}").format(
            book=as_unicode(get_media_title(magazine), errors="replace")
        )
        callback = Dispatcher(self.borrowed_magazine)
        job = ThreadedJob(
            "overdrive_libby_borrow_book",
            description,
            gui_libby_borrow_hold,
            (self.gui, self.client, magazine, card),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def borrowed_magazine(self, job):
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to borrow magazine"))
            return

        self.gui.status_bar.show_message(job.description + " " + _("finished"), 5000)

    def add_magazine_btn_clicked(self):
        share_url = self.magazine_link_txt.text().strip()
        mobj = (
            LIBBY_SHARE_URL_RE.match(share_url)
            or LIBBY_URL_RE.match(share_url)
            or OVERDRIVE_URL_RE.match(share_url)
        )
        if not mobj:
            return error_dialog(self, _("Add Magazine"), _("Invalid URL"), show=True)

        card = self.cards_model.filtered_rows[self.cards_cbbox.currentIndex()]
        title_id = mobj.group("title_id")
        media = self.overdrive_client.library_media(card["advantageKey"], title_id)
        if not (
            media.get("type", {}).get("id", "") == LibbyMediaTypes.Magazine
            and LibbyClient.has_format(media, LibbyFormats.MagazineOverDrive)
        ):
            return error_dialog(
                self,
                _("Add Magazine"),
                _("Title is not a downloadable magazine"),
                show=True,
            )
        if not (media.get("isOwned") and media.get("parentMagazineTitleId")):
            return error_dialog(
                self, _("Add Magazine"), _("Library does not own this title"), show=True
            )
        card_id = card["cardId"]
        parent_magazine_id = media["parentMagazineTitleId"]
        subscriptions = PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS]
        if [
            sub
            for sub in subscriptions
            if sub["parent_magazine_id"] == parent_magazine_id
        ]:
            return error_dialog(self, _("Add Magazine"), _("Already added"), show=True)
        subscriptions.append(
            {
                "card_id": card_id,
                "parent_magazine_id": parent_magazine_id,
            }
        )
        PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS] = subscriptions
        self.magazine_link_txt.setText("")
        self.sync()
