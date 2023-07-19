#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from datetime import datetime, timezone
from typing import Dict

from calibre.gui2 import Dispatcher
from calibre.gui2.dialogs.confirm_delete import confirm
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
    QDialog,
    QLabel,
    QSlider,
    QLayout,
)

from .base import BaseDialogMixin
from ..borrow_book import LibbyBorrowHold
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..hold_actions import LibbyHoldCancel, LibbyHoldUpdate
from ..libby import LibbyClient
from ..magazine_download_utils import parse_datetime
from ..models import get_media_title, LibbyHoldsModel, LibbyModel
from ..utils import PluginIcons

load_translations()

gui_libby_cancel_hold = LibbyHoldCancel()
gui_libby_borrow_hold = LibbyBorrowHold()
gui_libby_update_hold = LibbyHoldUpdate()


class HoldsDialogMixin(BaseDialogMixin):
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
        self.holds_refresh_btn = QPushButton(_c("Refresh"), self)
        self.holds_refresh_btn.setIcon(self.icons[PluginIcons.Refresh])
        self.holds_refresh_btn.setAutoDefault(False)
        self.holds_refresh_btn.setToolTip(_("Get latest holds"))
        self.holds_refresh_btn.clicked.connect(self.holds_refresh_btn_clicked)
        widget.layout.addWidget(self.holds_refresh_btn, widget_row_pos, 0)
        self.refresh_buttons.append(self.holds_refresh_btn)
        widget_row_pos += 1

        self.holds_model = LibbyHoldsModel(None, [], self.db)
        self.holds_search_proxy_model = QSortFilterProxyModel(self)
        self.holds_search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.holds_search_proxy_model.setFilterKeyColumn(-1)
        self.holds_search_proxy_model.setSourceModel(self.holds_model)
        self.holds_search_proxy_model.setSortRole(LibbyModel.DisplaySortRole)
        self.models.append(self.holds_model)

        # The main holds list
        self.holds_view = QTableView(self)
        self.holds_view.setSortingEnabled(True)
        self.holds_view.setAlternatingRowColors(True)
        self.holds_view.setMinimumWidth(self.min_view_width)
        self.holds_view.setModel(self.holds_search_proxy_model)
        horizontal_header = self.holds_view.horizontalHeader()
        for col_index in range(self.holds_model.columnCount()):
            horizontal_header.setSectionResizeMode(
                col_index,
                QHeaderView.ResizeMode.Stretch
                if col_index == 0
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        self.holds_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.holds_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.holds_view.sortByColumn(-1, Qt.AscendingOrder)
        self.holds_view.setTabKeyNavigation(
            False
        )  # prevents tab key being stuck in view
        # add debug trigger
        self.holds_view.doubleClicked.connect(
            lambda mi: self.display_debug("Hold", mi.data(Qt.UserRole))
        )
        # add context menu
        self.holds_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.holds_view.customContextMenuRequested.connect(
            self.holds_view_context_menu_requested
        )
        holds_view_selection_model = self.holds_view.selectionModel()
        holds_view_selection_model.selectionChanged.connect(
            self.holds_view_selection_model_selectionchanged
        )
        widget.layout.addWidget(
            self.holds_view, widget_row_pos, 0, self.view_vspan, self.view_hspan
        )
        widget_row_pos += self.view_vspan

        # Hide unavailable holds
        self.hide_unavailable_holds_checkbox = QCheckBox(
            PreferenceTexts.HIDE_HOLDS_UNAVAILABLE, self
        )
        self.hide_unavailable_holds_checkbox.setChecked(
            PREFS[PreferenceKeys.HIDE_HOLDS_UNAVAILABLE]
        )
        self.hide_unavailable_holds_checkbox.stateChanged.connect(
            self.hide_unavailable_holds_checkbox_state_changed
        )
        self.hide_unavailable_holds_checkbox.clicked.connect(
            self.hide_unavailable_holds_checkbox_clicked
        )
        widget.layout.addWidget(
            self.hide_unavailable_holds_checkbox, widget_row_pos, 0, 1, 2
        )
        # Borrow button
        self.holds_borrow_btn = self.init_borrow_btn(self.do_hold_borrow_action)
        widget.layout.addWidget(
            self.holds_borrow_btn, widget_row_pos, self.view_hspan - 1
        )
        self.refresh_buttons.append(self.holds_borrow_btn)
        widget_row_pos += 1

        self.tab_index = self.tabs.addTab(widget, _("Holds"))

    def rebind_holds_download_button_and_menu(self, borrow_action):
        self.rebind_borrow_btn(
            borrow_action, self.holds_borrow_btn, self.do_hold_borrow_action
        )

    def do_hold_borrow_action(self, do_download=False):
        self.rebind_borrow_buttons(do_download)

        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        for index in reversed(indices):
            hold = index.data(Qt.UserRole)
            self.borrow_hold(hold, do_download=do_download)
            self.holds_model.removeRow(
                self.holds_search_proxy_model.mapToSource(index).row()
            )

    def hide_unavailable_holds_checkbox_state_changed(self, __):
        checked = self.hide_unavailable_holds_checkbox.isChecked()
        self.holds_model.set_filter_hide_unavailable_holds(checked)
        self.holds_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_unavailable_holds_checkbox_clicked(self, checked):
        if PREFS[PreferenceKeys.HIDE_HOLDS_UNAVAILABLE] != checked:
            PREFS[PreferenceKeys.HIDE_HOLDS_UNAVAILABLE] = checked

    def holds_refresh_btn_clicked(self):
        self.sync()

    def holds_view_selection_model_selectionchanged(self, selected, deselected):
        # enables/disables the borrow button
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        for index in indices:
            hold = index.data(Qt.UserRole)
            self.holds_borrow_btn.setEnabled(hold.get("isAvailable", False))

    def holds_view_context_menu_requested(self, pos):
        # displays context menu in the view
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, self.holds_model)
        )
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_overdrive_action.triggered.connect(
            lambda: self.view_in_overdrive_action_triggered(indices, self.holds_model)
        )

        edit_hold_action = menu.addAction(_("Edit hold"))
        edit_hold_action.setIcon(self.icons[PluginIcons.Edit])
        edit_hold_action.triggered.connect(
            lambda: self.edit_hold_action_triggered(indices)
        )

        cancel_action = menu.addAction(_("Cancel hold"))
        cancel_action.setIcon(self.icons[PluginIcons.Delete])
        cancel_action.triggered.connect(lambda: self.cancel_action_triggered(indices))
        menu.exec(QCursor.pos())

    def edit_hold_action_triggered(self, indices):
        for index in reversed(indices):
            hold = index.data(Qt.UserRole)
            # open dialog
            d = SuspendHoldDialog(self, self.gui, self.icons, self.client, hold)
            d.setModal(True)
            d.open()

    def borrow_hold(self, hold, do_download=False):
        # do the actual borrowing
        card = self.holds_model.get_card(hold["cardId"])
        description = _("Borrowing {book}").format(
            book=as_unicode(get_media_title(hold), errors="replace")
        )
        callback = Dispatcher(
            self.borrowed_book_and_download if do_download else self.borrowed_book
        )
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
        # callback after book is borrowed
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to borrow book"))
            return

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def borrowed_book_and_download(self, job):
        # callback after book is borrowed
        self.borrowed_book(job)
        if (not job.failed) and job.result and hasattr(self, "download_loan"):
            # this is actually from the loans tab
            self.download_loan(job.result)

    def cancel_action_triggered(self, indices):
        msg = (
            _("Cancel this hold?")
            + "\n- "
            + "\n- ".join(
                [get_media_title(index.data(Qt.UserRole)) for index in indices]
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
        # actual cancelling of the hold
        description = _("Cancelling hold on {book}").format(
            book=as_unicode(get_media_title(hold), errors="replace")
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
        # callback after hold is cancelled
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to cancel hold"))
            return

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def updated_hold(self, job):
        # callback after hold is updated
        if job.failed:
            self.gui.job_exception(job, dialog_title=_("Failed to update hold"))
            return

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)


class SuspendHoldDialog(QDialog):
    def __init__(
        self,
        parent: HoldsDialogMixin,
        gui,
        icons: Dict,
        client: LibbyClient,
        hold: Dict,
    ):
        super().__init__(parent)
        self.gui = gui
        self.icons = icons
        self.client = client
        self.hold = hold
        self.setWindowFlag(Qt.Sheet)
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout = QGridLayout()
        self.setLayout(layout)
        widget_row_pos = 0

        # Instructions label
        self.instructions_lbl = QLabel(
            ngettext("Deliver after {n} day", "Deliver after {n} days", 0).format(n=0)
            if (
                hold.get("redeliveriesRequestedCount", 0) > 0
                or hold.get("redeliveriesAutomatedCount", 0) > 0
            )
            else ngettext("Suspend for {n} day", "Suspend for {n} days", 0).format(n=0)
        )
        self.instructions_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.instructions_lbl, widget_row_pos, 0, 1, 2)
        widget_row_pos += 1

        self.days_slider = QSlider(Qt.Horizontal, self)
        self.days_slider.setMinimum(0)
        self.days_slider.setMaximum(30)
        self.days_slider.setTickInterval(1)
        self.days_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        layout.addWidget(self.days_slider, widget_row_pos, 0, 1, 2)
        widget_row_pos += 1
        self.days_slider.valueChanged.connect(
            lambda n: self.instructions_lbl.setText(
                ngettext("Deliver after {n} day", "Deliver after {n} days", n).format(
                    n=n
                )
                if (
                    hold.get("redeliveriesRequestedCount", 0) > 0
                    or hold.get("redeliveriesAutomatedCount", 0) > 0
                )
                else ngettext("Suspend for {n} day", "Suspend for {n} days", n).format(
                    n=n
                )
            )
        )
        self.days_slider.setValue(7)
        if hold.get("suspensionEnd"):
            suspend_interval = parse_datetime(hold["suspensionEnd"]) - datetime.now(
                tz=timezone.utc
            )
            if suspend_interval.days >= 0:
                self.days_slider.setValue(suspend_interval.days + 1)

        self.cancel_btn = QPushButton(_c("Cancel"), self)
        self.cancel_btn.setIcon(self.icons[PluginIcons.Cancel])
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.setToolTip(_("Don't save changes"))
        self.cancel_btn.clicked.connect(lambda: self.reject())
        layout.addWidget(self.cancel_btn, widget_row_pos, 0)

        self.update_btn = QPushButton(_c("OK"), self)
        self.update_btn.setIcon(self.icons[PluginIcons.Okay])
        self.update_btn.setAutoDefault(False)
        self.update_btn.setToolTip(_("Save changes"))
        self.update_btn.clicked.connect(self.update_btn_clicked)
        layout.addWidget(self.update_btn, widget_row_pos, 1)
        widget_row_pos += 1

        for r in range(0, 2):
            layout.setColumnMinimumWidth(r, self.parent().min_button_width)
        layout.setSizeConstraint(QLayout.SetFixedSize)

    def update_btn_clicked(self):
        description = _("Updating hold on {book}").format(
            book=as_unicode(get_media_title(self.hold), errors="replace")
        )
        callback = Dispatcher(self.parent().updated_hold)
        job = ThreadedJob(
            "overdrive_libby_update_hold",
            description,
            gui_libby_update_hold,
            (self.gui, self.client, self.hold, self.days_slider.value()),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)
        self.accept()
