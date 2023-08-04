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
from typing import List

from calibre.gui2 import Dispatcher
from calibre.gui2.threaded_jobs import ThreadedJob
from polyglot.builtins import as_unicode
from qt.core import (
    QAbstractItemView,
    QCursor,
    QGridLayout,
    QIcon,
    QLineEdit,
    QMenu,
    QPushButton,
    QSortFilterProxyModel,
    QTableView,
    QThread,
    QWidget,
    Qt,
)

from .base import BaseDialogMixin
from .. import DEMO_MODE, logger
from ..compat import (
    QHeaderView_ResizeMode_ResizeToContents,
    QHeaderView_ResizeMode_Stretch,
    _c,
)
from ..config import BorrowActions, MAX_SEARCH_LIBRARIES, PREFS, PreferenceKeys
from ..hold_actions import LibbyHoldCreate
from ..libby import LibbyClient, LibbyFormats
from ..models import LibbyModel, LibbySearchModel, get_media_title, truncate_for_display
from ..overdrive import OverDriveClient
from ..utils import PluginIcons, obfuscate_name
from ..workers import OverDriveMediaSearchWorker

# noinspection PyUnreachableCode
if False:
    load_translations = _ = ngettext = lambda x=None, y=None: x

load_translations()

gui_create_hold = LibbyHoldCreate()


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
        self.search_btn = QPushButton(_c("Search"), self)
        self.search_btn.setIcon(self.icons[PluginIcons.Search])
        # self.search_btn.setAutoDefault(False)
        self.search_btn.clicked.connect(self.search_btn_clicked)
        search_widget.layout.addWidget(
            self.search_btn, widget_row_pos, self.view_hspan - 1
        )
        widget_row_pos += 1

        self.search_model = LibbySearchModel(None, [], self.db)
        self.search_proxy_model = QSortFilterProxyModel(self)
        self.search_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.search_proxy_model.setFilterKeyColumn(-1)
        self.search_proxy_model.setSourceModel(self.search_model)
        self.search_proxy_model.setSortRole(LibbyModel.DisplaySortRole)
        self.models.append(self.search_model)

        # The main search results list
        self.search_results_view = QTableView(self)
        self.search_results_view.setSortingEnabled(True)
        self.search_results_view.setAlternatingRowColors(True)
        self.search_results_view.setMinimumWidth(self.min_view_width)
        self.search_results_view.setModel(self.search_proxy_model)
        self.search_results_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.search_results_view.setSelectionMode(QAbstractItemView.SingleSelection)
        horizontal_header = self.search_results_view.horizontalHeader()
        for col_index in range(self.search_model.columnCount()):
            horizontal_header.setSectionResizeMode(
                col_index,
                QHeaderView_ResizeMode_Stretch
                if col_index == 0
                else QHeaderView_ResizeMode_ResizeToContents,
            )
        self.search_results_view.sortByColumn(-1, Qt.AscendingOrder)
        self.search_results_view.setContextMenuPolicy(Qt.CustomContextMenu)
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
        )
        search_widget.layout.addWidget(
            self.search_results_view,
            widget_row_pos,
            0,
            self.view_vspan,
            self.view_hspan,
        )
        # set last col's min width (button)
        search_widget.layout.setColumnMinimumWidth(
            search_widget.layout.columnCount() - 1, self.min_button_width
        )
        for col_num in range(0, search_widget.layout.columnCount() - 1):
            search_widget.layout.setColumnStretch(col_num, 1)
        self.search_tab_index = self.add_tab(search_widget, _c("Search"))

    def search_results_view_selection_model_selectionchanged(self):
        selection_model = self.search_results_view.selectionModel()
        if not selection_model.hasSelection():
            return
        indices = selection_model.selectedRows()
        media = indices[-1].data(Qt.UserRole)
        self.status_bar.showMessage(get_media_title(media, include_subtitle=True), 3000)

    def borrow_tooltip(self, media, site_availability):
        available_copies = site_availability.get("availableCopies", 0)
        owned_copies = site_availability.get("ownedCopies", 0)
        texts = [site_availability["__library"]["name"]]
        if available_copies:
            texts.append(
                ngettext(
                    "{n} copy available.", "{n} copies available.", available_copies
                ).format(n=available_copies)
            )
        if owned_copies:
            texts.append(
                ngettext("{n} copy owned.", "{n} copies owned.", owned_copies).format(
                    n=owned_copies
                )
            )
        return "\n".join(texts)

    def hold_tooltip(self, media, site_availability):
        owned_copies = site_availability.get("ownedCopies", 0)
        texts = [
            site_availability["__library"]["name"],
            _("Estimated wait days: {n}.").format(
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
        return "\n".join(texts)

    def search_results_view_context_menu_requested(self, pos):
        selection_model = self.search_results_view.selectionModel()
        if not selection_model.hasSelection():
            return
        mi = self.search_results_view.indexAt(pos)

        borrow_action_default_is_borrow = PREFS[
            PreferenceKeys.LAST_BORROW_ACTION
        ] == BorrowActions.BORROW or not hasattr(self, "download_loan")

        media = mi.data(Qt.UserRole)

        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        available_sites = []
        for k, v in media.get("siteAvailabilities", {}).items():
            v["advantageKey"] = k
            if v.get("ownedCopies") or v.get("isAvailable"):
                available_sites.append(v)
        available_sites = sorted(
            available_sites,
            key=cmp_to_key(OverDriveClient.sort_availabilities),
            reverse=True,
        )
        view_in_libby_menu = QMenu(_("View in Libby"))
        view_in_libby_menu.setIcon(self.icons[PluginIcons.ExternalLink])
        view_in_libby_menu.setToolTipsVisible(True)
        for site in available_sites:
            _card = next(
                iter(self.search_model.get_cards_for_library_key(site["advantageKey"])),
                None,
            )
            site["__card"] = _card
            library = self.search_model.get_library(
                self.search_model.get_website_id(_card)
            )
            site["__library"] = library
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
        view_in_overdrive_menu.setIcon(self.icons[PluginIcons.ExternalLink])
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
            menu.addSection(
                _("Borrow with")
                if borrow_action_default_is_borrow
                else _("Borrow and Download with"),
            )
            for site in borrow_sites:
                cards = self.search_model.get_cards_for_library_key(
                    site["advantageKey"]
                )
                for card in cards:
                    if not LibbyClient.can_borrow(card):
                        logger.debug(
                            f"Card is out of loan limits: {card['cardName']} @ {card['advantageKey']}"
                        )
                        continue
                    if self.search_model.has_loan(media["id"], card["cardId"]):
                        logger.debug(
                            f"Loan already exists for {media['title']} @ {card['advantageKey']}"
                        )
                        continue
                    card_action = menu.addAction(
                        QIcon(self.get_card_pixmap(site["__library"])),
                        truncate_for_display(
                            f'{card["advantageKey"]}: {card["cardName"] or ""}'
                        ),
                    )
                    card_action.setToolTip(self.borrow_tooltip(media, site))
                    media_for_borrow = copy.deepcopy(media)
                    media_for_borrow["cardId"] = card["cardId"]
                    card_action.triggered.connect(
                        # this is from the holds tab
                        lambda checked, m=media_for_borrow: self.borrow_hold(
                            m, do_download=not borrow_action_default_is_borrow
                        )
                    )
        if hold_sites:
            menu.addSection(_("Place Hold with"))
            for site in hold_sites:
                cards = self.search_model.get_cards_for_library_key(
                    site["advantageKey"]
                )
                for card in cards:
                    if not LibbyClient.can_place_hold(card):
                        logger.debug(
                            f"Card is out of hold limits: {card['cardName']} @ {card['advantageKey']}"
                        )
                        continue
                    if self.search_model.has_hold(media["id"], card["cardId"]):
                        logger.debug(
                            f"Hold already exists for {media['title']} @ {card['advantageKey']}"
                        )
                        continue
                    card_action = menu.addAction(
                        QIcon(self.get_card_pixmap(site["__library"])),
                        truncate_for_display(
                            f'{card["advantageKey"]}: {card["cardName"] or ""}'
                        ),
                    )
                    card_action.setToolTip(self.hold_tooltip(media, site))
                    card_action.triggered.connect(
                        lambda checked, m=media, c=card: self.create_hold(m, c)
                    )

        menu.exec(QCursor.pos())

    def create_hold(self, media, card):
        # create the hold
        description = _("Placing hold on {book}").format(
            book=as_unicode(get_media_title(media), errors="replace")
        )
        callback = Dispatcher(self.hold_created)
        job = ThreadedJob(
            "overdrive_libby_create_hold",
            description,
            gui_create_hold,
            (self.gui, self.client, media, card),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def hold_created(self, job):
        # callback after hold is created
        if job.failed:
            return self.unhandled_exception(
                job.exception, msg=_("Failed to create hold")
            )

        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def search_btn_clicked(self):
        self.search_model.sync({"search_results": []})
        self.search_results_view.sortByColumn(-1, Qt.AscendingOrder)
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
        worker.setup(
            overdrive_client,
            query,
            library_keys,
            [
                LibbyFormats.EBookEPubAdobe,
                LibbyFormats.EBookPDFAdobe,
                LibbyFormats.EBookEPubOpen,
                LibbyFormats.EBookPDFOpen,
                LibbyFormats.MagazineOverDrive,
            ],
            max_items=max_items,
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
