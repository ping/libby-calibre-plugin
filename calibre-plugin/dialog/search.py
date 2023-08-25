#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
import copy
from functools import cmp_to_key
from typing import Dict, List

from calibre.constants import DEBUG
from qt.core import (
    QAbstractItemView,
    QCursor,
    QGridLayout,
    QIcon,
    QLineEdit,
    QMenu,
    QThread,
    QWidget,
    Qt,
)

from .base import BaseDialogMixin
from .widgets import DefaultQPushButton, DefaultQTableView
from .. import DEMO_MODE
from ..compat import (
    QHeaderView_ResizeMode_ResizeToContents,
    QHeaderView_ResizeMode_Stretch,
    _c,
)
from ..config import BorrowActions, MAX_SEARCH_LIBRARIES, PREFS, PreferenceKeys
from ..libby import LibbyClient, LibbyFormats
from ..models import (
    LibbySearchModel,
    LibbySearchSortFilterModel,
    get_media_title,
    truncate_for_display,
)
from ..overdrive import OverDriveClient
from ..utils import PluginImages, obfuscate_name
from ..workers import OverDriveMediaSearchWorker

# noinspection PyUnreachableCode
if False:
    load_translations = _ = ngettext = lambda x=None, y=None: x

load_translations()


class SearchDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
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
        self.search_btn.setAutoDefault(True)
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
        self.hold_btn = DefaultQPushButton(_("Place Hold"), None, self)
        search_widget.layout.addWidget(
            self.hold_btn, widget_row_pos, self.view_hspan - 2
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

    def _get_available_sites(self, media):
        available_sites = []
        for k, site in media.get("siteAvailabilities", {}).items():
            site["advantageKey"] = k
            if site.get("ownedCopies") or site.get("isAvailable"):
                _card = next(
                    iter(
                        self.search_model.get_cards_for_library_key(
                            site["advantageKey"]
                        )
                    ),
                    None,
                )
                site["__card"] = _card
                library = self.search_model.get_library(
                    self.search_model.get_website_id(_card)
                )
                site["__library"] = library
                available_sites.append(site)
        return sorted(
            available_sites,
            key=cmp_to_key(OverDriveClient.sort_availabilities),
            reverse=True,
        )

    def _wrap_for_rich_text(self, txt):
        return f"<p>{txt}</p>"

    def _borrow_tooltip(self, media, site_availability):
        available_copies = site_availability.get(
            "luckyDayAvailableCopies", 0
        ) + site_availability.get("availableCopies", 0)
        owned_copies = site_availability.get(
            "luckyDayOwnedCopies", 0
        ) + site_availability.get("ownedCopies", 0)
        texts = [f'<b>{site_availability["__library"]["name"]}</b>']
        if available_copies:
            texts.append(
                ngettext(
                    "<b>{n}</b> copy available.",
                    "<b>{n}</b> copies available.",
                    available_copies,
                ).format(n=available_copies)
            )
        if owned_copies:
            texts.append(
                ngettext("{n} copy owned.", "{n} copies owned.", owned_copies).format(
                    n=owned_copies
                )
            )
        return self._wrap_for_rich_text("<br>".join(texts))

    def _hold_tooltip(self, media, site_availability):
        owned_copies = site_availability.get("ownedCopies", 0)
        texts = [
            f'<b>{site_availability["__library"]["name"]}</b>',
            _("Estimated wait days: <b>{n}</b>.").format(
                n=site_availability.get("estimatedWaitDays", 0) or _c("Unknown")
            ),
            _("You will be number {n} in line.").format(
                n=site_availability.get("holdsCount", 0) + 1
            ),
            ngettext("{n} copy ordered.", "{n} copies ordered.", owned_copies).format(
                n=owned_copies
            )
            if media.get("isPreReleaseTitle", False)
            else ngettext(
                "{n} copy in use.", "{n} copies in use.", owned_copies
            ).format(n=owned_copies),
        ]
        return self._wrap_for_rich_text("<br>".join(texts))

    def search_results_view_selection_model_selectionchanged(self):
        selection_model = self.search_results_view.selectionModel()
        if not selection_model.hasSelection():
            # selection cleared
            self.search_borrow_btn.borrow_menu = None
            self.search_borrow_btn.setMenu(None)
            self.hold_btn.borrow_menu = None
            self.hold_btn.setMenu(None)
            return

        indices = selection_model.selectedRows()
        media = indices[-1].data(Qt.UserRole)
        self.status_bar.showMessage(get_media_title(media, include_subtitle=True), 3000)

        borrow_action_default_is_borrow = PREFS[
            PreferenceKeys.LAST_BORROW_ACTION
        ] == BorrowActions.BORROW or not hasattr(self, "download_loan")

        available_sites = self._get_available_sites(media)

        borrow_sites = [
            s
            for s in available_sites
            if s.get("isAvailable") or s.get("luckyDayAvailableCopies")
        ]
        hold_sites = [
            s
            for s in available_sites
            if not (s.get("isAvailable") or s.get("luckyDayAvailableCopies"))
        ]
        if borrow_sites:
            borrow_menu = QMenu()
            borrow_menu.setToolTipsVisible(True)
            for site in borrow_sites:
                cards = self.search_model.get_cards_for_library_key(
                    site["advantageKey"]
                )
                for card in cards:
                    card_action = borrow_menu.addAction(
                        QIcon(self.get_card_pixmap(site["__library"])),
                        truncate_for_display(
                            f'{card["advantageKey"]}: {card["cardName"] or ""}'
                        ),
                    )
                    if not LibbyClient.can_borrow(card):
                        card_action.setToolTip(
                            self._wrap_for_rich_text(
                                "<br>".join(
                                    [
                                        f'<b>{site["__library"]["name"]}</b>',
                                        _("This card is out of loans."),
                                    ]
                                )
                            )
                        )
                        card_action.setEnabled(False)
                        continue

                    if self.search_model.has_loan(media["id"], card["cardId"]):
                        card_action.setToolTip(
                            self._wrap_for_rich_text(
                                "<br>".join(
                                    [
                                        f'<b>{site["__library"]["name"]}</b>',
                                        _("You already have a loan for this title."),
                                    ]
                                )
                            )
                        )
                        card_action.setEnabled(False)
                        continue

                    card_action.setToolTip(self._borrow_tooltip(media, site))
                    media_for_borrow = copy.deepcopy(media)
                    media_for_borrow["cardId"] = card["cardId"]
                    card_action.triggered.connect(
                        # this is from the holds tab
                        lambda checked, m=media_for_borrow, s=site: self.borrow_hold(
                            m,
                            availability=s,
                            do_download=not borrow_action_default_is_borrow,
                        )
                    )
            self.search_borrow_btn.setEnabled(True)
            self.search_borrow_btn.borrow_menu = borrow_menu
            self.search_borrow_btn.setMenu(borrow_menu)
        else:
            self.search_borrow_btn.borrow_menu = None
            self.search_borrow_btn.setMenu(None)
            self.search_borrow_btn.setEnabled(False)

        if hold_sites:
            hold_menu = QMenu()
            hold_menu.setToolTipsVisible(True)
            for site in hold_sites:
                cards = self.search_model.get_cards_for_library_key(
                    site["advantageKey"]
                )
                for card in cards:
                    card_action = hold_menu.addAction(
                        QIcon(self.get_card_pixmap(site["__library"])),
                        truncate_for_display(
                            f'{card["advantageKey"]}: {card["cardName"] or ""}'
                        ),
                    )
                    if not LibbyClient.can_place_hold(card):
                        card_action.setToolTip(
                            self._wrap_for_rich_text(
                                "<br>".join(
                                    [
                                        f'<b>{site["__library"]["name"]}</b>',
                                        _("This card is out of holds."),
                                    ]
                                )
                            )
                        )
                        card_action.setEnabled(False)
                        continue
                    if self.search_model.has_hold(media["id"], card["cardId"]):
                        card_action.setToolTip(
                            self._wrap_for_rich_text(
                                "<br>".join(
                                    [
                                        f'<b>{site["__library"]["name"]}</b>',
                                        _("You already have a hold for this title."),
                                    ]
                                )
                            )
                        )
                        card_action.setEnabled(False)
                        continue

                    card_action.setToolTip(self._hold_tooltip(media, site))
                    card_action.triggered.connect(
                        lambda checked, m=media, c=card: self.create_hold(m, c)
                    )
            self.hold_btn.setEnabled(True)
            self.hold_btn.hold_menu = hold_menu
            self.hold_btn.setMenu(hold_menu)
        else:
            self.hold_btn.borrow_menu = None
            self.hold_btn.setMenu(None)
            self.hold_btn.setEnabled(False)

    def search_results_view_context_menu_requested(self, pos):
        selection_model = self.search_results_view.selectionModel()
        if not selection_model.hasSelection():
            return
        mi = self.search_results_view.indexAt(pos)
        media = mi.data(Qt.UserRole)

        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        available_sites = self._get_available_sites(media)
        view_in_libby_menu = QMenu(_("View in Libby"))
        view_in_libby_menu.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_libby_menu.setToolTipsVisible(True)
        for site in available_sites:
            _card = site["__card"]
            library = site["__library"]
            libby_action = view_in_libby_menu.addAction(
                QIcon(self.get_card_pixmap(site["__library"])),
                _card["advantageKey"]
                if not DEMO_MODE
                else obfuscate_name(_card["advantageKey"]),
            )
            libby_action.setToolTip(library["name"])
            libby_action.triggered.connect(
                lambda checked, c=_card: self.view_in_libby_action_triggered(
                    [mi], self.search_model, c
                )
            )
        menu.addMenu(view_in_libby_menu)
        view_in_overdrive_menu = QMenu(_("View in OverDrive"))
        view_in_overdrive_menu.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_overdrive_menu.setToolTipsVisible(True)
        for site in available_sites:
            _card = site["__card"]
            library = site["__library"]
            overdrive_action = view_in_overdrive_menu.addAction(
                QIcon(self.get_card_pixmap(site["__library"])),
                _card["advantageKey"]
                if not DEMO_MODE
                else obfuscate_name(_card["advantageKey"]),
            )
            overdrive_action.setToolTip(library["name"])
            overdrive_action.triggered.connect(
                lambda checked, c=_card: self.view_in_overdrive_action_triggered(
                    [mi], self.search_model, c
                )
            )
        menu.addMenu(view_in_overdrive_menu)

        selected_search = self.search_results_view.indexAt(pos).data(Qt.UserRole)
        # view book details
        self.add_view_book_details_menu_action(menu, selected_search)
        # copy share link
        self.add_copy_share_link_menu_action(menu, selected_search)
        # find calibre matches
        self.add_find_library_match_menu_action(menu, selected_search)

        menu.exec(QCursor.pos())

    def _reset_borrow_hold_buttons(self):
        self.search_borrow_btn.borrow_menu = None
        self.search_borrow_btn.setMenu(None)
        self.search_borrow_btn.setEnabled(True)
        self.hold_btn.hold_menu = None
        self.hold_btn.setMenu(None)
        self.hold_btn.setEnabled(True)

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
            all_library_keys = self.search_model.library_keys()
            library_keys = [
                lib
                for lib in all_library_keys
                if lib in PREFS[PreferenceKeys.SEARCH_LIBRARIES]
            ]
            if not library_keys:
                library_keys = all_library_keys

            self._search_thread = self._get_search_thread(
                self.overdrive_client,
                search_query,
                library_keys[:MAX_SEARCH_LIBRARIES],
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
            self.search_btn.setText(_c("Search"))
            self.search_btn.setEnabled(True)
            self.unsetCursor()
            self.search_model.sync({"search_results": results})
            thread.quit()

        def errored_out(err: Exception):
            self.search_btn.setText(_c("Search"))
            self.search_btn.setEnabled(True)
            self.unsetCursor()
            thread.quit()
            raise err

        worker.finished.connect(lambda results: done(results))
        worker.errored.connect(lambda err: errored_out(err))

        return thread
