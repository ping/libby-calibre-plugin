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

from calibre.constants import DEBUG
from qt.core import (
    QAbstractItemView,
    QGridLayout,
    QLineEdit,
    QThread,
    QWidget,
    Qt,
)

from .base_search import SearchBaseDialog
from .widgets import DefaultQPushButton, DefaultQTableView
from ..compat import (
    QHeaderView_ResizeMode_ResizeToContents,
    QHeaderView_ResizeMode_Stretch,
    _c,
)
from ..config import (
    BorrowActions,
    PREFS,
    PreferenceKeys,
    SearchMode,
)
from ..libby import LibbyFormats
from ..models import (
    LibbySearchModel,
    LibbySearchSortFilterModel,
)
from ..utils import PluginImages
from ..workers import OverDriveMediaSearchWorker

# noinspection PyUnreachableCode
if False:
    load_translations = _ = ngettext = lambda x=None, y=None, z=None: x

load_translations()


class SearchDialogMixin(SearchBaseDialog):
    def __init__(self, *args):
        super().__init__(*args)
        self._search_thread = QThread()

        search_widget = QWidget()
        search_widget.layout = QGridLayout()
        search_widget.setLayout(search_widget.layout)
        widget_row_pos = 0

        # Search Query textbox
        self.query_txt = QLineEdit(self)
        self.query_txt.setPlaceholderText(_c("Search for e-books"))
        self.query_txt.setClearButtonEnabled(True)
        search_widget.layout.addWidget(
            self.query_txt, widget_row_pos, 0, 1, self.view_hspan - 1
        )

        # Search button
        self.search_btn = DefaultQPushButton(
            _c("Search"), self.resources[PluginImages.Search], self
        )
        self.search_btn.clicked.connect(self.search_btn_clicked)
        search_widget.layout.addWidget(
            self.search_btn, widget_row_pos, self.view_hspan - 1
        )
        widget_row_pos += 1

        self.search_model = LibbySearchModel(None, [], self.db)
        self.search_proxy_model = LibbySearchSortFilterModel(
            self, model=self.search_model
        )
        self.search_proxy_model.setSourceModel(self.search_model)

        # The main search results list
        self.search_results_view = DefaultQTableView(
            self, model=self.search_proxy_model, min_width=self.min_view_width
        )
        self.search_results_view.setSelectionMode(QAbstractItemView.SingleSelection)
        horizontal_header = self.search_results_view.horizontalHeader()
        for col_index in range(self.search_model.columnCount()):
            horizontal_header.setSectionResizeMode(
                col_index,
                QHeaderView_ResizeMode_Stretch
                if col_index == 0
                else QHeaderView_ResizeMode_ResizeToContents,
            )
        # context menu
        self.search_results_view.customContextMenuRequested.connect(
            self.search_results_view_context_menu_requested
        )
        # selection change
        self.search_results_view.selectionModel().selectionChanged.connect(
            self.search_results_view_selection_model_selectionchanged
        )
        # debug display
        self.search_results_view.doubleClicked.connect(
            lambda mi: self.display_debug("Search Result", mi.data(Qt.UserRole))
            if DEBUG and mi.column() == self.search_model.columnCount() - 1
            else self.show_book_details(mi.data(Qt.UserRole))
        )
        search_widget.layout.addWidget(
            self.search_results_view,
            widget_row_pos,
            0,
            self.view_vspan,
            self.view_hspan,
        )
        widget_row_pos += 1

        self.toggle_search_mode_btn = DefaultQPushButton(
            "", self.resources[PluginImages.SearchToggle], self
        )
        self.toggle_search_mode_btn.setToolTip(_("Advanced Search"))
        self.toggle_search_mode_btn.setMaximumWidth(
            self.toggle_search_mode_btn.height()
        )
        self.toggle_search_mode_btn.clicked.connect(self.toggle_search_mode_btn_clicked)
        search_widget.layout.addWidget(self.toggle_search_mode_btn, widget_row_pos, 0)

        borrow_action_default_is_borrow = PREFS[
            PreferenceKeys.LAST_BORROW_ACTION
        ] == BorrowActions.BORROW or not hasattr(self, "download_loan")

        self.search_borrow_btn = DefaultQPushButton(
            _("Borrow")
            if borrow_action_default_is_borrow
            else _("Borrow and Download"),
            self.resources[PluginImages.Add],
            self,
        )
        search_widget.layout.addWidget(
            self.search_borrow_btn, widget_row_pos, self.view_hspan - 1
        )
        self.search_hold_btn = DefaultQPushButton(_("Place Hold"), None, self)
        search_widget.layout.addWidget(
            self.search_hold_btn, widget_row_pos, self.view_hspan - 2
        )
        # set last 2 col's min width (buttons)
        for i in (1, 2):
            search_widget.layout.setColumnMinimumWidth(
                search_widget.layout.columnCount() - i, self.min_button_width
            )
        for col_num in range(0, search_widget.layout.columnCount() - 2):
            search_widget.layout.setColumnStretch(col_num, 1)
        self.search_tab_index = self.add_tab(search_widget, _c("Search"))
        self.last_borrow_action_changed.connect(self.rebind_search_borrow_btn)
        self.sync_starting.connect(self.base_sync_starting_search)
        self.sync_ended.connect(self.base_sync_ended_search)
        self.loan_added.connect(self.loan_added_search)
        self.loan_removed.connect(self.loan_removed_search)
        self.hold_added.connect(self.hold_added_search)
        self.hold_removed.connect(self.hold_removed_search)

    def toggle_search_mode_btn_clicked(self):
        if hasattr(self, "adv_search_tab_index"):
            PREFS[PreferenceKeys.SEARCH_MODE] = SearchMode.ADVANCED
            self.search_mode_changed.emit(SearchMode.ADVANCED)
            self.tabs.setCurrentIndex(self.adv_search_tab_index)

    def loan_added_search(self, loan: Dict):
        self.search_model.add_loan(loan)
        self.search_results_view.selectionModel().clearSelection()

    def loan_removed_search(self, loan: Dict):
        self.search_model.remove_loan(loan)
        self.search_results_view.selectionModel().clearSelection()

    def hold_added_search(self, hold: Dict):
        self.search_model.add_hold(hold)
        self.search_results_view.selectionModel().clearSelection()

    def hold_removed_search(self, hold: Dict):
        self.search_model.remove_hold(hold)
        self.search_results_view.selectionModel().clearSelection()

    def base_sync_starting_search(self):
        self.search_borrow_btn.setEnabled(False)
        self.search_model.sync({})

    def base_sync_ended_search(self, value):
        self.search_borrow_btn.setEnabled(True)
        self.search_model.sync(value)

    def rebind_search_borrow_btn(self, last_borrow_action: str):
        borrow_action_default_is_borrow = (
            last_borrow_action == BorrowActions.BORROW
            or not hasattr(self, "download_loan")
        )
        self.search_borrow_btn.setText(
            _("Borrow") if borrow_action_default_is_borrow else _("Borrow and Download")
        )
        self.search_borrow_btn.borrow_menu = None
        self.search_borrow_btn.setMenu(None)
        self.search_results_view.selectionModel().clearSelection()

    def search_for(self, text: str):
        self.tabs.setCurrentIndex(self.search_tab_index)
        self.query_txt.setText(text)
        self.search_btn.setFocus(Qt.OtherFocusReason)
        self.search_btn.animateClick()

    def search_results_view_selection_model_selectionchanged(self):
        self.view_selection_model_selectionchanged(
            self.search_borrow_btn,
            self.search_hold_btn,
            self.search_results_view,
            self.search_model,
        )

    def search_results_view_context_menu_requested(self, pos):
        self.view_context_menu_requested(
            pos, self.search_results_view, self.search_model
        )

    def _reset_borrow_hold_buttons(self):
        self.search_borrow_btn.borrow_menu = None
        self.search_borrow_btn.setMenu(None)
        self.search_borrow_btn.setEnabled(True)
        self.search_hold_btn.hold_menu = None
        self.search_hold_btn.setMenu(None)
        self.search_hold_btn.setEnabled(True)

    def search_btn_clicked(self):
        self.search_model.sync({"search_results": []})
        self.search_results_view.sortByColumn(-1, Qt.AscendingOrder)
        self._reset_borrow_hold_buttons()
        search_query = self.query_txt.text().strip()
        if not search_query:
            return
        if not self._search_thread.isRunning():
            self.search_btn.setText(_c("Searching..."))
            self.search_btn.setEnabled(False)
            self.setCursor(Qt.WaitCursor)
            self._search_thread = self._get_search_thread(
                self.overdrive_client,
                search_query,
                self.search_model.limited_library_keys(),
                PREFS[PreferenceKeys.SEARCH_RESULTS_MAX],
            )
            self._search_thread.start()

    def _get_search_thread(
        self, overdrive_client, query: str, library_keys: List[str], max_items: int
    ):
        thread = QThread()
        worker = OverDriveMediaSearchWorker()
        formats = []
        if not PREFS[PreferenceKeys.INCL_NONDOWNLOADABLE_TITLES]:
            formats = [
                LibbyFormats.EBookEPubAdobe,
                LibbyFormats.EBookPDFAdobe,
                LibbyFormats.EBookEPubOpen,
                LibbyFormats.EBookPDFOpen,
                LibbyFormats.MagazineOverDrive,
            ]
        worker.setup(
            overdrive_client, query, library_keys, formats, max_items=max_items
        )
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def done(results):
            thread.quit()
            self.search_btn.setText(_c("Search"))
            self.search_btn.setEnabled(True)
            self.unsetCursor()
            self.search_model.sync({"search_results": results})
            self.status_bar.showMessage(
                ngettext("{n} result found", "{n} results found", len(results)).format(
                    n=len(results)
                ),
                5000,
            )

        def errored_out(err: Exception):
            thread.quit()
            self.search_btn.setText(_c("Search"))
            self.search_btn.setEnabled(True)
            self.unsetCursor()
            raise err

        worker.finished.connect(lambda results: done(results))
        worker.errored.connect(lambda err: errored_out(err))

        return thread
