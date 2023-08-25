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

from calibre.constants import DEBUG
from calibre.gui2 import Dispatcher
from calibre.gui2.dialogs.confirm_delete import confirm
from calibre.gui2.threaded_jobs import ThreadedJob
from polyglot.builtins import as_unicode
from qt.core import (
    QAbstractItemView,
    QCheckBox,
    QCursor,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QSlider,
    QWidget,
    Qt,
)

from .base import BaseDialogMixin
from .widgets import DefaultQPushButton, DefaultQTableView
from ..borrow_book import LibbyBorrowMedia
from ..compat import (
    QHeaderView_ResizeMode_ResizeToContents,
    QHeaderView_ResizeMode_Stretch,
    QSlider_TickPosition_TicksBelow,
    _c,
)
from ..config import PREFS, PreferenceKeys, PreferenceTexts
from ..hold_actions import LibbyHoldCancel, LibbyHoldUpdate
from ..libby import LibbyClient
from ..models import (
    LibbyHoldsModel,
    LibbyHoldsSortFilterModel,
    get_media_title,
    is_valid_type,
)
from ..utils import PluginImages

# noinspection PyUnreachableCode
if False:
    load_translations = _ = ngettext = lambda x=None, y=None: x

load_translations()

gui_libby_cancel_hold = LibbyHoldCancel()
gui_libby_borrow_hold = LibbyBorrowMedia()
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
        self.holds_refresh_btn = DefaultQPushButton(
            _c("Refresh"), self.resources[PluginImages.Refresh], self
        )
        self.holds_refresh_btn.setToolTip(_("Get latest holds"))
        self.holds_refresh_btn.clicked.connect(self.holds_refresh_btn_clicked)
        widget.layout.addWidget(self.holds_refresh_btn, widget_row_pos, 0)

        self.holds_filter_txt = QLineEdit(self)
        self.holds_filter_txt.setMinimumWidth(self.min_button_width)
        self.holds_filter_txt.setClearButtonEnabled(True)
        self.holds_filter_txt.setToolTip(_("Filter by Title, Author, Library"))
        self.holds_filter_txt.textChanged.connect(self.holds_filter_txt_textchanged)
        self.holds_filter_lbl = QLabel(_c("Filter"))
        self.holds_filter_lbl.setBuddy(self.holds_filter_txt)
        holds_filter_layout = QHBoxLayout()
        holds_filter_layout.addWidget(self.holds_filter_lbl)
        holds_filter_layout.addWidget(self.holds_filter_txt, 1)
        widget.layout.addLayout(
            holds_filter_layout, widget_row_pos, self.view_hspan - 2, 1, 2
        )
        widget_row_pos += 1

        self.holds_model = LibbyHoldsModel(None, [], self.db)
        self.holds_search_proxy_model = LibbyHoldsSortFilterModel(
            self, model=self.holds_model, db=self.db
        )

        self.holds_model.modelReset.connect(self.holds_model_changed)
        self.holds_model.rowsRemoved.connect(self.holds_model_changed)
        self.holds_model.dataChanged.connect(self.holds_model_changed)

        # The main holds list
        self.holds_view = DefaultQTableView(
            self, model=self.holds_search_proxy_model, min_width=self.min_view_width
        )
        horizontal_header = self.holds_view.horizontalHeader()
        for col_index in range(self.holds_model.columnCount()):
            horizontal_header.setSectionResizeMode(
                col_index,
                QHeaderView_ResizeMode_Stretch
                if col_index == 0
                else QHeaderView_ResizeMode_ResizeToContents,
            )
        self.holds_view.setSelectionMode(QAbstractItemView.SingleSelection)
        # add debug trigger
        self.holds_view.doubleClicked.connect(
            lambda mi: self.display_debug("Hold", mi.data(Qt.UserRole))
            if DEBUG and mi.column() == self.holds_model.columnCount() - 1
            else self.show_book_details(mi.data(Qt.UserRole))
        )
        # add context menu
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
        widget_row_pos += 1

        self.holds_tab_index = self.add_tab(widget, _("Holds"))
        self.last_borrow_action_changed.connect(
            self.rebind_holds_download_button_and_menu
        )
        self.sync_starting.connect(self.base_sync_starting_holds)
        self.sync_ended.connect(self.base_sync_ended_holds)
        self.hold_added.connect(self.hold_added_holds)
        self.hold_removed.connect(self.hold_removed_holds)

    def hold_added_holds(self, hold: Dict):
        self.holds_model.add_hold(hold)

    def hold_removed_holds(self, hold: Dict):
        self.holds_model.remove_hold(hold)

    def base_sync_starting_holds(self):
        self.holds_refresh_btn.setEnabled(False)
        self.holds_borrow_btn.setEnabled(False)
        self.holds_model.sync({})

    def base_sync_ended_holds(self, value):
        self.holds_refresh_btn.setEnabled(True)
        self.holds_borrow_btn.setEnabled(True)
        self.holds_model.sync(value)

    def holds_model_changed(self):
        available_holds_count = 0
        for r in range(self.holds_model.rowCount()):
            hold = self.holds_model.index(r, 0).data(Qt.UserRole)
            if not is_valid_type(hold):
                continue
            if hold.get("isAvailable", False):
                available_holds_count += 1
        if available_holds_count:
            self.tabs.setTabText(
                self.holds_tab_index,
                _("Holds ({n})").format(n=available_holds_count),
            )
        else:
            self.tabs.setTabText(self.holds_tab_index, _("Holds"))

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

    def hide_unavailable_holds_checkbox_state_changed(self, __):
        checked = self.hide_unavailable_holds_checkbox.isChecked()
        self.holds_search_proxy_model.set_filter_hide_unavailable_holds(checked)
        self.holds_view.sortByColumn(-1, Qt.AscendingOrder)

    def hide_unavailable_holds_checkbox_clicked(self, checked):
        if PREFS[PreferenceKeys.HIDE_HOLDS_UNAVAILABLE] != checked:
            PREFS[PreferenceKeys.HIDE_HOLDS_UNAVAILABLE] = checked

    def holds_filter_txt_textchanged(self, text):
        self.holds_search_proxy_model.set_filter_text(text)

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
            card = self.holds_model.get_card(hold["cardId"])
            self.holds_borrow_btn.setEnabled(hold.get("isAvailable", False))
            if hold.get("estimatedWaitDays") and not hold.get("isAvailable", False):
                owned_copies = hold.get("ownedCopies", 0)
                self.status_bar.showMessage(
                    " ".join(
                        [
                            f'{get_media_title(hold)} @{card.get("advantageKey")}:',
                            _("Estimated wait days: {n}.").format(
                                n=hold["estimatedWaitDays"]
                            ),
                            _("You are number {n} in line.").format(
                                n=hold.get("holdListPosition", 0)
                            ),
                            ngettext(
                                "{n} copy ordered.", "{n} copies ordered.", owned_copies
                            ).format(n=owned_copies)
                            if hold.get("isPreReleaseTitle", False)
                            else ngettext(
                                "{n} copy in use.", "{n} copies in use.", owned_copies
                            ).format(n=owned_copies),
                        ]
                    ),
                    3000,
                )
                continue
            elif hold.get("isAvailable"):
                # check card loan limit
                loan_limit = card.get("limits", {}).get("loan", 0)
                used_loan_limit = card.get("counts", {}).get("loan", 0)
                available_loan_limit = loan_limit - used_loan_limit
                if available_loan_limit < 1:
                    self.holds_borrow_btn.setEnabled(False)
                    self.status_bar.showMessage(
                        _(
                            "You have reached your loan limit for this card. To update limits, click on Refresh."
                        ),
                        3000,
                    )
                    continue
            self.status_bar.showMessage(get_media_title(hold), 3000)

    def holds_view_context_menu_requested(self, pos):
        # displays context menu in the view
        selection_model = self.holds_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        # add view in OverDrive/Libby menu actions
        self.add_view_in_menu_actions(menu, indices, self.holds_model)

        selected_hold = self.holds_view.indexAt(pos).data(Qt.UserRole)
        # view book details
        self.add_view_book_details_menu_action(menu, selected_hold)
        # copy share link
        self.add_copy_share_link_menu_action(menu, selected_hold)
        # find calibre matches
        self.add_find_library_match_menu_action(menu, selected_hold)
        # search for title
        self.add_search_for_title_menu_action(menu, selected_hold)

        edit_hold_action = menu.addAction(_("Manage hold"))
        edit_hold_action.setIcon(self.resources[PluginImages.Edit])
        edit_hold_action.triggered.connect(
            lambda: self.edit_hold_action_triggered(indices)
        )

        cancel_action = menu.addAction(_("Cancel hold"))
        cancel_action.setIcon(self.resources[PluginImages.Delete])
        cancel_action.triggered.connect(lambda: self.cancel_action_triggered(indices))
        menu.exec(QCursor.pos())

    def edit_hold_action_triggered(self, indices):
        for index in reversed(indices):
            hold = index.data(Qt.UserRole)
            # open dialog
            d = SuspendHoldDialog(self, self.gui, self.resources, self.client, hold)
            d.setModal(True)
            d.open()

    def borrow_hold(self, hold, availability=None, do_download=False):

        if not availability:
            # this is supplied from the search tab
            availability = {}

        is_lucky_day_loan = bool(
            availability.get("luckyDayAvailableCopies", 0)
            and not availability.get("availableCopies", 0)
        )

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
            (self.gui, self.client, hold, card, is_lucky_day_loan),
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
            return self.unhandled_exception(
                job.exception, msg=_("Failed to borrow book")
            )

        self.loan_added.emit(job.result)
        # the loan dict is returned, but it doesn't matter because only title ID and card ID is required
        # even if the loan was not created from a hold, it shouldn't matter
        self.hold_removed.emit(job.result)
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
            return self.unhandled_exception(
                job.exception, msg=_("Failed to cancel hold")
            )
        self.hold_removed.emit(job.result)
        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def updated_hold(self, job):
        # callback after hold is updated
        if job.failed:
            return self.unhandled_exception(
                job.exception, msg=_("Failed to update hold")
            )

        else:
            updated_hold = job.result
            for r in range(self.holds_model.rowCount()):
                index = self.holds_model.index(r, 0)
                hold = index.data(Qt.UserRole)
                if (
                    hold["id"] == updated_hold["id"]
                    and hold["cardId"] == updated_hold["cardId"]
                ):
                    self.holds_model.setData(index, updated_hold)
                    break
        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)


class SuspendHoldDialog(QDialog):
    def __init__(
        self,
        parent: HoldsDialogMixin,
        gui,
        resources: Dict,
        client: LibbyClient,
        hold: Dict,
    ):
        super().__init__(parent)
        self.gui = gui
        self.resources = resources
        self.client = client
        self.hold = hold
        self.setWindowFlag(Qt.Sheet)
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout = QGridLayout()
        self.setLayout(layout)
        widget_row_pos = 0

        self.title_lbl = QLabel(get_media_title(hold))
        self.title_lbl.setAlignment(Qt.AlignCenter)
        curr_font = self.title_lbl.font()
        curr_font.setPointSizeF(curr_font.pointSizeF() * 1.1)
        self.title_lbl.setFont(curr_font)
        self.title_lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.title_lbl, widget_row_pos, 0, 1, 2)
        widget_row_pos += 1

        # Instructions label
        self.instructions_lbl = QLabel(
            ngettext("Deliver after {n} day", "Deliver after {n} days", 0).format(n=0)
            if self._is_delivery_delay(hold)
            else ngettext("Suspend for {n} day", "Suspend for {n} days", 0).format(n=0)
        )
        self.instructions_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.instructions_lbl, widget_row_pos, 0, 1, 2)
        widget_row_pos += 1

        self.days_slider = QSlider(Qt.Horizontal, self)
        self.days_slider.setMinimum(0)
        self.days_slider.setMaximum(30)
        self.days_slider.setTickInterval(1)
        self.days_slider.setTickPosition(QSlider_TickPosition_TicksBelow)
        layout.addWidget(self.days_slider, widget_row_pos, 0, 1, 2)
        widget_row_pos += 1
        self.days_slider.valueChanged.connect(
            lambda n: self.instructions_lbl.setText(
                ngettext("Deliver after {n} day", "Deliver after {n} days", n).format(
                    n=n
                )
                if self._is_delivery_delay(hold)
                else ngettext("Suspend for {n} day", "Suspend for {n} days", n).format(
                    n=n
                )
            )
        )
        self.days_slider.setValue(7)
        if hold.get("suspensionEnd"):
            suspension_end = LibbyClient.parse_datetime(hold["suspensionEnd"])
            if suspension_end:
                suspend_interval = suspension_end - datetime.now(tz=timezone.utc)
                if suspend_interval.days >= 0:
                    self.days_slider.setValue(suspend_interval.days + 1)

        self.cancel_btn = DefaultQPushButton(
            _c("Cancel"), self.resources[PluginImages.Cancel], self
        )
        self.cancel_btn.clicked.connect(lambda: self.reject())
        layout.addWidget(self.cancel_btn, widget_row_pos, 0)

        self.update_btn = DefaultQPushButton(
            _c("OK"), self.resources[PluginImages.Okay], self
        )
        self.update_btn.clicked.connect(self.update_btn_clicked)
        layout.addWidget(self.update_btn, widget_row_pos, 1)
        widget_row_pos += 1

        for r in range(0, 2):
            layout.setColumnMinimumWidth(r, self.parent().min_button_width)
        layout.setSizeConstraint(QLayout.SetFixedSize)

    def _is_delivery_delay(self, hold):
        if hold.get("isAvailable"):
            return True
        is_suspended = bool(hold.get("suspensionFlag") and hold.get("suspensionEnd"))
        if is_suspended and (
            hold.get("redeliveriesRequestedCount", 0) > 0
            or hold.get("redeliveriesAutomatedCount", 0) > 0
        ):
            return True
        return False

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
