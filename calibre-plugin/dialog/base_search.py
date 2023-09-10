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

from qt.core import Qt, QMenu, QIcon, QCursor

from .base import BaseDialogMixin
from .. import DEMO_MODE
from ..compat import _c
from ..config import PREFS, PreferenceKeys, BorrowActions
from ..libby import LibbyClient
from ..models import get_media_title, truncate_for_display
from ..utils import PluginImages, obfuscate_name

# noinspection PyUnreachableCode
if False:
    load_translations = _ = ngettext = lambda x=None, y=None, z=None: x

load_translations()


class SearchBaseDialog(BaseDialogMixin):
    def __init__(self, *args):
        super().__init__(*args)

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

    def view_selection_model_selectionchanged(self, borrow_btn, hold_btn, view, model):
        selection_model = view.selectionModel()
        if not selection_model.hasSelection():
            # selection cleared
            borrow_btn.borrow_menu = None
            borrow_btn.setMenu(None)
            hold_btn.borrow_menu = None
            hold_btn.setMenu(None)
            return

        indices = selection_model.selectedRows()
        media = indices[-1].data(Qt.UserRole)
        self.status_bar.showMessage(get_media_title(media, include_subtitle=True), 3000)

        borrow_action_default_is_borrow = PREFS[
            PreferenceKeys.LAST_BORROW_ACTION
        ] == BorrowActions.BORROW or not hasattr(self, "download_loan")

        available_sites = self.get_available_sites(media, model)

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
                cards = model.get_cards_for_library_key(site["advantageKey"])
                for card in cards:
                    card_action = borrow_menu.addAction(
                        QIcon(self.get_card_pixmap(site["__library"])),
                        truncate_for_display(
                            f'{card["advantageKey"]}: {card["cardName"] or ""}',
                            font=borrow_menu.font(),
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

                    if model.has_loan(media["id"], card["cardId"]):
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
            borrow_btn.setEnabled(True)
            borrow_btn.borrow_menu = borrow_menu
            borrow_btn.setMenu(borrow_menu)
        else:
            borrow_btn.borrow_menu = None
            borrow_btn.setMenu(None)
            borrow_btn.setEnabled(False)

        if hold_sites:
            hold_menu = QMenu()
            hold_menu.setToolTipsVisible(True)
            for site in hold_sites:
                cards = model.get_cards_for_library_key(site["advantageKey"])
                for card in cards:
                    card_action = hold_menu.addAction(
                        QIcon(self.get_card_pixmap(site["__library"])),
                        truncate_for_display(
                            f'{card["advantageKey"]}: {card["cardName"] or ""}',
                            font=hold_menu.font(),
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
                    if model.has_hold(media["id"], card["cardId"]):
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
            hold_btn.setEnabled(True)
            hold_btn.hold_menu = hold_menu
            hold_btn.setMenu(hold_menu)
        else:
            hold_btn.borrow_menu = None
            hold_btn.setMenu(None)
            hold_btn.setEnabled(False)

    def view_context_menu_requested(self, pos, view, model):
        selection_model = view.selectionModel()
        if not selection_model.hasSelection():
            return
        mi = view.indexAt(pos)
        media = mi.data(Qt.UserRole)

        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        available_sites = self.get_available_sites(media, model)
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
                    [mi], model, c
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
                    [mi], model, c
                )
            )
        menu.addMenu(view_in_overdrive_menu)

        selected_search = view.indexAt(pos).data(Qt.UserRole)
        # view book details
        self.add_view_book_details_menu_action(menu, selected_search)
        # copy share link
        self.add_copy_share_link_menu_action(menu, selected_search)
        # find calibre matches
        self.add_find_library_match_menu_action(menu, selected_search)
        # search for author
        self.add_search_for_title_menu_action(
            menu, selected_search, search_for_author=True
        )

        menu.exec(QCursor.pos())
