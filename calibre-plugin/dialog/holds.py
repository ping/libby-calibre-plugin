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

from calibre.gui2 import Dispatcher
from calibre.gui2.dialogs.confirm_delete import confirm
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
from ..borrow_book import LibbyBorrowHold
from ..config import PREFS, PreferenceKeys
from ..hold_cancel import LibbyHoldCancel
from ..model import get_loan_title, LibbyHoldsModel

load_translations()

gui_libby_cancel_hold = LibbyHoldCancel()
gui_libby_borrow_hold = LibbyBorrowHold()


class HoldsDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
        holds_widget = QWidget()
        holds_widget.layout = QGridLayout()
        holds_widget.setLayout(holds_widget.layout)
        holds_widget_row_pos = 0

        # Refresh button
        self.holds_refresh_btn = QPushButton(_("Refresh"), self)
        self.holds_refresh_btn.setIcon(self.icons["refresh"])
        self.holds_refresh_btn.setAutoDefault(False)
        self.holds_refresh_btn.setToolTip(_("Get latest holds"))
        self.holds_refresh_btn.clicked.connect(self.holds_refresh_btn_clicked)
        holds_widget.layout.addWidget(self.holds_refresh_btn, holds_widget_row_pos, 0)
        self.refresh_buttons.append(self.holds_refresh_btn)
        # Status bar
        self.holds_status_bar = QStatusBar(self)
        self.holds_status_bar.setSizeGripEnabled(False)
        holds_widget.layout.addWidget(
            self.holds_status_bar, holds_widget_row_pos, 1, 1, 3
        )
        self.status_bars.append(self.holds_status_bar)
        holds_widget_row_pos += 1

        self.holds_model = LibbyHoldsModel(None, [], self.db)
        self.holds_search_proxy_model = QSortFilterProxyModel(self)
        self.holds_search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.holds_search_proxy_model.setFilterKeyColumn(-1)
        self.holds_search_proxy_model.setSourceModel(self.holds_model)
        self.holds_search_proxy_model.setSortRole(LibbyHoldsModel.DisplaySortRole)
        self.models.append(self.holds_model)

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
        self.holds_view.customContextMenuRequested.connect(
            self.holds_view_context_menu_requested
        )
        holds_view_selection_model = self.holds_view.selectionModel()
        holds_view_selection_model.selectionChanged.connect(
            self.holds_view_selection_model_selectionchanged
        )
        holds_widget.layout.addWidget(
            self.holds_view, holds_widget_row_pos, 0, self.view_vspan, self.view_hspan
        )
        holds_widget_row_pos += self.view_vspan

        # Hide unavailable holds
        self.hide_unavailable_holds_checkbox = QCheckBox(
            _("Hide unavailable holds"), self
        )
        self.hide_unavailable_holds_checkbox.clicked.connect(
            self.hide_unavailable_holds_checkbox_clicked
        )
        self.hide_unavailable_holds_checkbox.setChecked(True)
        holds_widget.layout.addWidget(
            self.hide_unavailable_holds_checkbox, holds_widget_row_pos, 0
        )
        # Borrow button
        self.borrow_btn = QPushButton(_("Borrow"), self)
        self.borrow_btn.setIcon(self.icons["borrow"])
        self.borrow_btn.setAutoDefault(False)
        self.borrow_btn.setToolTip(_("Borrow selected hold"))
        self.borrow_btn.setStyleSheet("padding: 4px 16px")
        self.borrow_btn.clicked.connect(self.borrow_btn_clicked)
        holds_widget.layout.addWidget(
            self.borrow_btn, holds_widget_row_pos, self.view_hspan - 1
        )
        holds_widget_row_pos += 1

        self.tabs.addTab(holds_widget, _("Holds"))

    def hide_unavailable_holds_checkbox_clicked(self, checked: bool):
        self.holds_model.set_filter_hide_unavailable_holds(checked)
        self.holds_view.sortByColumn(-1, Qt.AscendingOrder)

    def holds_refresh_btn_clicked(self):
        self.sync()

    def holds_view_selection_model_selectionchanged(self, selected, deselected):
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        for index in indices:
            hold = index.data(Qt.UserRole)
            self.borrow_btn.setEnabled(hold.get("isAvailable", False))

    def holds_view_context_menu_requested(self, pos):
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.icons["ext-link"])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, self.holds_model)
        )
        cancel_action = menu.addAction(_("Cancel hold"))
        cancel_action.setIcon(self.icons["cancel_hold"])
        cancel_action.triggered.connect(lambda: self.cancel_action_triggered(indices))
        menu.exec(QCursor.pos())

    def borrow_btn_clicked(self):
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

    def cancel_action_triggered(self, indices):
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
