#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from collections import namedtuple
from datetime import datetime
from functools import cmp_to_key
from typing import Dict, List, Optional

from calibre.utils.config import tweaks
from calibre.utils.date import dt_as_local, format_date
from calibre.utils.icu import lower as icu_lower
from qt.core import QAbstractTableModel, QFont, QModelIndex, Qt

from . import DEMO_MODE
from .compat import QColor_fromString, _c
from .config import PREFS, PreferenceKeys
from .libby import LibbyClient
from .libby.client import LibbyFormats, LibbyMediaTypes
from .overdrive import OverDriveClient
from .utils import PluginColors, PluginIcons, obfuscate_date, obfuscate_name

# noinspection PyUnreachableCode
if False:
    load_translations = _ = lambda x=None: x

load_translations()


def get_media_title(
    loan: Dict, for_sorting: bool = False, include_subtitle: bool = False
) -> str:
    """
    Formats the title for a loan

    :param loan:
    :param for_sorting: If True, uses the sort attributes instead
    :param include_subtitle: If True, include subtitle
    :return:
    """
    title: str = (
        loan["sortTitle"] if for_sorting and loan.get("sortTitle") else loan["title"]
    )
    if (
        include_subtitle
        and loan.get("subtitle")
        and not title.endswith(loan["subtitle"])
    ):
        # sortTitle contains subtitle?
        title = f'{title}: {loan["subtitle"]}'
    if loan["type"]["id"] == LibbyMediaTypes.Magazine and loan.get("edition", ""):
        if not for_sorting:
            title = f'{title} - {loan.get("edition", "")}'
        else:
            title = f'{title}|{loan["id"]}'

    return title


def truncate_for_display(text, text_length=30):
    if len(text) <= text_length:
        return text if not DEMO_MODE else obfuscate_name(text)
    return (
        text[:text_length] if not DEMO_MODE else obfuscate_name(text[:text_length])
    ) + "…"


LOAN_TYPE_TRANSLATION = {
    LibbyMediaTypes.EBook: _("Book"),
    LibbyMediaTypes.Magazine: _("Magazine"),
    LibbyMediaTypes.Audiobook: _("Audiobook"),
}
LOAN_FORMAT_TRANSLATION = {
    "ebook-overdrive": _("Libby Book"),
    "audiobook-overdrive": _("Libby Audiobook"),
    "audiobook-mp3": _("MP3 Audiobook"),
    "magazine-overdrive": _("Libby Magazine"),
    "video-overdrive": _("Libby Video"),
    "video-streaming": _("Streaming Video"),
    "ebook-kindle": _("Kindle"),
    "ebook-media-do": _("Media Do"),
    "ebook-epub-open": _("EPUB"),
    "ebook-epub-adobe": _("EPUB (DRM)"),
    "ebook-pdf-open": _("PDF"),
    "ebook-pdf-adobe": _("PDF (DRM)"),
}


class LibbyModel(QAbstractTableModel):
    column_headers: List[str] = []
    DisplaySortRole = Qt.UserRole + 1000

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent)
        self.db = db
        self._cards = []
        self._libraries = []
        self._rows = []
        self.filtered_rows = []

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return section + 1
        if section >= len(self.column_headers):
            return None
        return self.column_headers[section]

    def columnCount(self, parent=None):
        return len(self.column_headers)

    def rowCount(self, parent=None):
        return len(self.filtered_rows)

    def removeRows(self, row, count, _):
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        self.filtered_rows = (
            self.filtered_rows[:row] + self.filtered_rows[row + count :]
        )
        self.endRemoveRows()
        return True

    def sync(self, synced_state: Optional[Dict] = None):
        if not synced_state:
            synced_state = {}
        self._cards = synced_state.get("cards", [])
        self._libraries = synced_state.get("__libraries", [])

    def get_card(self, card_id) -> Dict:
        card = next(
            iter([c for c in self._cards if c["cardId"] == card_id]),
            None,
        )
        if not card:
            raise ValueError("Card is unknown: id=%s" % card_id)
        return card

    def get_website_id(self, card) -> int:
        if not card.get("library"):
            raise ValueError(
                "Card does not have library details: id=%s, advantageKey=%s"
                % (card.get("cardId"), card.get("advantageKey"))
            )
        return int(card.get("library", {}).get("websiteId", "0"))

    def get_library(self, website_id: int) -> Dict:
        library = next(
            iter([lib for lib in self._libraries if lib["websiteId"] == website_id]),
            None,
        )
        if not library:
            raise ValueError("Library is unknown: websiteId=%s" % website_id)
        return library


LoanMatchCondition = namedtuple(
    "LoanMatchCondition", ["title1", "title2", "isbn", "asin"]
)


class LibbyLoansModel(LibbyModel):
    """
    Underlying data model for the Loans table view
    """

    column_headers = [
        _c("Title"),
        _c("Author"),
        _("Expire Date"),
        _("Library"),
        _c("Format"),
    ]
    filter_hide_books_already_in_library = False

    def __init__(self, parent, synced_state=None, db=None, icons=None):
        super().__init__(parent, synced_state, db)
        self.icons = icons
        self.all_book_ids_titles = self.db.fields["title"].table.book_col_map
        self.all_book_ids_formats = self.db.fields["formats"].table.book_col_map
        self.all_book_ids_identifiers = self.db.fields["identifiers"].table.book_col_map
        self.filter_hide_books_already_in_library = PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ]
        self.sync(synced_state)

    def sync(self, synced_state: Optional[Dict] = None):
        super().sync(synced_state)
        if not synced_state:
            synced_state = {}
        self._rows = sorted(
            synced_state.get("loans", []),
            key=lambda ln: ln["checkoutDate"],
            reverse=True,
        )
        self.filter_rows()

    def filter_rows(self):
        self.beginResetModel()
        self.filtered_rows = []
        for loan in self._rows:
            if not (
                (
                    LibbyClient.is_downloadable_ebook_loan(loan)
                    and not PREFS[PreferenceKeys.HIDE_EBOOKS]
                )
                or (
                    LibbyClient.is_downloadable_magazine_loan(loan)
                    and not PREFS[PreferenceKeys.HIDE_MAGAZINES]
                )
                or (
                    PREFS[PreferenceKeys.INCL_NONDOWNLOADABLE_TITLES]
                    and not (
                        LibbyClient.is_downloadable_magazine_loan(loan)
                        or LibbyClient.is_downloadable_ebook_loan(loan)
                    )
                )
            ):
                continue

            loan_format = LibbyClient.get_loan_format(
                loan,
                PREFS[PreferenceKeys.PREFER_OPEN_FORMATS],
                raise_if_not_downloadable=False,
            )

            if not self.filter_hide_books_already_in_library:
                # hide lib books filter is not enabled
                self.filtered_rows.append(loan)
                continue

            # hide lib books filter is enabled
            book_in_library = False
            loan_title1 = icu_lower(get_media_title(loan).strip())
            loan_title2 = icu_lower(
                get_media_title(loan, include_subtitle=True).strip()
            )
            loan_isbn = OverDriveClient.extract_isbn(
                loan.get("formats", []), [loan_format] if loan_format else []
            )
            loan_asin = OverDriveClient.extract_asin(loan.get("formats", []))
            for book_id, title in iter(self.all_book_ids_titles.items()):
                book_identifiers = self.all_book_ids_identifiers.get(book_id) or {}
                book_in_library = (
                    icu_lower(title) in (loan_title1, loan_title2)
                    or (loan_isbn and loan_isbn == book_identifiers.get("isbn", ""))
                    or (loan_asin and loan_asin == book_identifiers.get("amazon", ""))
                    or (loan_asin and loan_asin == book_identifiers.get("asin", ""))
                )
                if book_in_library:
                    if PREFS[
                        PreferenceKeys.EXCLUDE_EMPTY_BOOKS
                    ] and not self.all_book_ids_formats.get(book_id):
                        book_in_library = False
                    break  # check only first matching book

            if not book_in_library:
                self.filtered_rows.append(loan)

        self.endResetModel()

    def set_filter_hide_books_already_in_library(self, value: bool):
        if value != self.filter_hide_books_already_in_library:
            self.filter_hide_books_already_in_library = value
            self.filter_rows()

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        loan: Dict = self.filtered_rows[row]
        # UserRole
        if role == Qt.UserRole:
            return loan
        # DecorationRole
        if role == Qt.DecorationRole:
            if col == 2 and loan.get("isLuckyDayCheckout"):
                return self.icons[PluginIcons.Clover]
            if (
                col == 4
                and loan.get("type", {}).get("id", "") == LibbyMediaTypes.EBook
                and LibbyClient.has_format(loan, LibbyFormats.EBookKindle)
                and not LibbyClient.get_locked_in_format(loan)
            ):
                return self.icons[PluginIcons.Unlock]
        # TextAlignmentRole
        if role == Qt.TextAlignmentRole and col >= 2:
            return Qt.AlignCenter
        # ForegroundRole
        if role == Qt.ForegroundRole and col == 2 and LibbyClient.is_renewable(loan):
            return QColor_fromString(PluginColors.Red)
        card = self.get_card(loan["cardId"])
        # ToolTipRole
        if role == Qt.ToolTipRole:
            if col == 0:
                return get_media_title(loan, include_subtitle=True)
            if col == 2 and loan.get("isLuckyDayCheckout"):
                return _("A skip-the-line loan")
            if col == 3:
                library = self.get_library(self.get_website_id(card))
                return library["name"]
            if col == 4:
                locked_in_format = LibbyClient.get_locked_in_format(loan)
                tooltip_text = (
                    _("This loan is not format-locked.")
                    if not locked_in_format
                    else _("This loan is format-locked.")
                )
                if LibbyClient.is_downloadable_magazine_loan(loan):
                    is_empty_book = False
                elif LibbyClient.is_downloadable_audiobook_loan(loan):
                    is_empty_book = True
                else:
                    try:
                        LibbyClient.get_loan_format(
                            loan,
                            prefer_open_format=PREFS[
                                PreferenceKeys.PREFER_OPEN_FORMATS
                            ],
                        )
                        is_empty_book = False
                    except ValueError:
                        # kindle
                        is_empty_book = True
                if is_empty_book:
                    tooltip_text += "<br/>"
                    tooltip_text += _("This loan will be downloaded as an empty book.")

                return f"<p>{tooltip_text}</p>"

        # DisplayRole, DisplaySortRole
        if role not in (Qt.DisplayRole, LibbyModel.DisplaySortRole):
            return None
        if col == 0:
            if role == LibbyModel.DisplaySortRole:
                return get_media_title(loan, for_sorting=True)
            return get_media_title(loan)
        if col == 1:
            creator_name = loan.get("firstCreatorName", "")
            if role == LibbyModel.DisplaySortRole:
                return loan.get("firstCreatorSortName", "") or creator_name
            return creator_name
        if col == 2:
            dt_value = dt_as_local(LibbyClient.parse_datetime(loan["expireDate"]))
            if role == LibbyModel.DisplaySortRole:
                return dt_value.isoformat()
            if DEMO_MODE:
                return format_date(
                    obfuscate_date(dt_value, day=31, month=12),
                    tweaks["gui_timestamp_display_format"],
                )
            return format_date(dt_value, tweaks["gui_timestamp_display_format"])
        if col == 3:
            if DEMO_MODE:
                return obfuscate_name(card["advantageKey"])
            return card["advantageKey"]
        if col == 4:
            loan_format = LibbyClient.get_loan_format(
                loan,
                PREFS[PreferenceKeys.PREFER_OPEN_FORMATS],
                raise_if_not_downloadable=False,
            )
            if role == LibbyModel.DisplaySortRole:
                return str(loan_format)
            return _(LOAN_FORMAT_TRANSLATION.get(loan_format, loan_format))
        return None


class LibbyHoldsModel(LibbyModel):
    """
    Underlying data model for the Holds table view
    """

    column_headers = [
        _c("Title"),
        _c("Author"),
        _("Hold/Expire Date"),
        _("Library"),
        _c("Format"),
        _("Available"),
    ]
    filter_hide_unavailable_holds = True

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent, synced_state, db)
        self.filter_hide_unavailable_holds = PREFS[
            PreferenceKeys.HIDE_HOLDS_UNAVAILABLE
        ]
        self.sync(synced_state)

    def sync(self, synced_state: Optional[Dict] = None):
        super().sync(synced_state)
        if not synced_state:
            synced_state = {}
        self._rows = sorted(
            synced_state.get("holds", []),
            key=lambda h: (
                h["isAvailable"],
                -h.get("estimatedWaitDays", 9999),
                h["placedDate"],
            ),
            reverse=True,
        )
        self.filter_rows()

    def filter_rows(self):
        self.beginResetModel()
        self.filtered_rows = []
        for hold in [
            h
            for h in self._rows
            if (
                not PREFS[PreferenceKeys.HIDE_EBOOKS]
                and LibbyClient.is_downloadable_ebook_loan(h)
            )
            or (
                not PREFS[PreferenceKeys.HIDE_MAGAZINES]
                and LibbyClient.is_downloadable_magazine_loan(h)
            )
            or (
                PREFS[PreferenceKeys.INCL_NONDOWNLOADABLE_TITLES]
                and not (
                    LibbyClient.is_downloadable_magazine_loan(h)
                    or LibbyClient.is_downloadable_ebook_loan(h)
                )
            )
        ]:
            if hold.get("isAvailable", False) or not self.filter_hide_unavailable_holds:
                self.filtered_rows.append(hold)
        self.endResetModel()

    def set_filter_hide_unavailable_holds(self, value: bool):
        if value != self.filter_hide_unavailable_holds:
            self.filter_hide_unavailable_holds = value
            self.filter_rows()

    def setData(self, index, hold, role=Qt.EditRole):
        if role == Qt.EditRole:
            self.filtered_rows[index.row()] = hold
            self.dataChanged.emit(index, index)
            return True

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        hold: Dict = self.filtered_rows[row]
        is_suspended = bool(
            hold.get("suspensionFlag") and hold.get("suspensionEnd")
        ) and not hold.get("isAvailable")
        # UserRole
        if role == Qt.UserRole:
            return hold
        # TextAlignmentRole
        if role == Qt.TextAlignmentRole and col >= 2:
            return Qt.AlignCenter
        hold_available = hold.get("isAvailable", False)
        # ForegroundRole
        if role == Qt.ForegroundRole and col == 2 and hold_available:
            return QColor_fromString(PluginColors.Red)
        # FontRole
        if role == Qt.FontRole and col == 5 and hold_available:
            font = QFont()
            font.setBold(True)
            return font
        # ToolTipRole
        card = self.get_card(hold["cardId"])
        placed_or_expire_dt = dt_as_local(
            LibbyClient.parse_datetime(hold.get("expireDate") or hold["placedDate"])
        )
        if role == Qt.ToolTipRole:
            if col == 0:
                return get_media_title(hold, include_subtitle=True)
            if col == 2:
                if hold.get("expireDate"):
                    return _("Expires {dt}").format(
                        dt=format_date(
                            placed_or_expire_dt, tweaks["gui_timestamp_display_format"]
                        )
                    )
                return _("Placed on {dt}").format(
                    dt=format_date(
                        placed_or_expire_dt, tweaks["gui_timestamp_display_format"]
                    )
                )
            if col == 3:
                library = self.get_library(self.get_website_id(card))
                return library["name"]
            if col == 5 and is_suspended:
                suspended_till = dt_as_local(
                    LibbyClient.parse_datetime(hold["suspensionEnd"])
                )
                if (
                    hold.get("redeliveriesRequestedCount", 0) > 0
                    or hold.get("redeliveriesAutomatedCount", 0) > 0
                ):
                    return _("Deliver after {dt}").format(
                        dt=format_date(
                            suspended_till, tweaks["gui_timestamp_display_format"]
                        )
                    )
                else:
                    return _("Suspended till {dt}").format(
                        dt=format_date(
                            suspended_till, tweaks["gui_timestamp_display_format"]
                        )
                    )
        # DisplayRole, DisplaySortRole
        if role not in (Qt.DisplayRole, LibbyModel.DisplaySortRole):
            return None
        if col == 0:
            if role == LibbyModel.DisplaySortRole:
                return get_media_title(hold, for_sorting=True)
            return get_media_title(hold)
        if col == 1:
            creator_name = hold.get("firstCreatorName", "")
            if role == LibbyModel.DisplaySortRole:
                return hold.get("firstCreatorSortName", "") or creator_name
            return creator_name
        if col == 2:
            if role == LibbyModel.DisplaySortRole:
                return placed_or_expire_dt.isoformat()
            if DEMO_MODE:
                return format_date(
                    obfuscate_date(placed_or_expire_dt, month=1, day=1),
                    tweaks["gui_timestamp_display_format"],
                )
            return format_date(
                placed_or_expire_dt, tweaks["gui_timestamp_display_format"]
            )
        if col == 3:
            if DEMO_MODE:
                return obfuscate_name(card["advantageKey"])
            return card["advantageKey"]
        if col == 4:
            hold_format = LibbyClient.get_loan_format(
                hold,
                PREFS[PreferenceKeys.PREFER_OPEN_FORMATS],
                raise_if_not_downloadable=False,
            )
            if role == LibbyModel.DisplaySortRole:
                return str(hold_format)
            return _(LOAN_FORMAT_TRANSLATION.get(hold_format, hold_format))
        if col == 5:
            if is_suspended:
                if (
                    hold.get("redeliveriesRequestedCount", 0) > 0
                    or hold.get("redeliveriesAutomatedCount", 0) > 0
                ):
                    return _("Delivering Later")
                return _("Suspended Hold")
            return _c("Yes") if hold.get("isAvailable", False) else _c("No")

        return None


class LibbyCardsModel(LibbyModel):
    """
    Underlying data model for the Library Cards combobox
    """

    column_headers = ["Card"]

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent, synced_state, db)
        self.sync(synced_state)

    def sync(self, synced_state: Optional[Dict] = None):
        super().sync(synced_state)
        self._rows = self._cards
        self.filter_rows()

    def filter_rows(self):
        self.beginResetModel()
        self.filtered_rows = sorted(self._rows, key=lambda c: c["advantageKey"])
        self.endResetModel()

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        card: Dict = self.filtered_rows[row]
        if role == Qt.UserRole:
            return card
        if role != Qt.DisplayRole:
            return None
        if col == 0:
            return truncate_for_display(
                f'{card["advantageKey"]}: {card["cardName"] or ""}'
            )
        return None


class LibbyMagazinesModel(LibbyModel):
    """
    Underlying data model for the Magazines table view
    """

    column_headers = [_c("Title"), _("Release Date"), _("Library Card"), _("Borrowed")]
    filter_hide_magazines_already_in_library = False

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent, synced_state, db)
        self.all_book_ids_titles = self.db.fields["title"].table.book_col_map
        self.all_book_ids_formats = self.db.fields["formats"].table.book_col_map
        self._loans: List[Dict] = []
        self.filter_hide_magazines_already_in_library = PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ]
        self.sync(synced_state)

    def set_filter_hide_magazines_already_in_library(self, value: bool):
        if value != self.filter_hide_magazines_already_in_library:
            self.filter_hide_magazines_already_in_library = value
            self.filter_rows()

    def sync(self, synced_state: Optional[Dict] = None):
        super().sync(synced_state)
        if not synced_state:
            synced_state = {}
        self._loans = synced_state.get("loans", [])
        self._rows = synced_state.get("__subscriptions", [])
        self.filter_rows()

    def sync_subscriptions(self, subscriptions: List[Dict]):
        self._rows = subscriptions
        self.filter_rows()

    def filter_rows(self):
        self.beginResetModel()
        self.filtered_rows = []
        for r in sorted(
            self._rows, key=lambda t: t["estimatedReleaseDate"], reverse=True
        ):
            r["__is_borrowed"] = bool(
                [loan for loan in self._loans if loan["id"] == r["id"]]
            )
            if not self.filter_hide_magazines_already_in_library:
                self.filtered_rows.append(r)
                continue

            # hide lib books filter is enabled
            book_in_library = False
            q1 = icu_lower(get_media_title(r).strip())
            q2 = icu_lower(get_media_title(r, include_subtitle=True).strip())
            for book_id, title in iter(self.all_book_ids_titles.items()):
                if icu_lower(title) not in (q1, q2):
                    continue
                if (
                    not PREFS[PreferenceKeys.EXCLUDE_EMPTY_BOOKS]
                ) or self.all_book_ids_formats.get(book_id):
                    book_in_library = True
                break  # check only first matching book title
            if not book_in_library:
                self.filtered_rows.append(r)

        self.endResetModel()

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        subscription: Dict = self.filtered_rows[row]
        # UserRole
        if role == Qt.UserRole:
            return subscription
        # TextAlignmentRole
        if role == Qt.TextAlignmentRole and col >= 1:
            return Qt.AlignCenter
        # ToolTipRole
        if role == Qt.ToolTipRole:
            if col == 0:
                return get_media_title(subscription, include_subtitle=True)
            if col == 2:
                card = self.get_card(subscription["cardId"])
                if not card:
                    return "Invalid card setup"
                return f'{card["advantageKey"]}: {card["cardName"] or ""}'
        # DisplayRole, DisplaySortRole
        if role not in (Qt.DisplayRole, LibbyModel.DisplaySortRole):
            return None
        if col == 0:
            return get_media_title(subscription)
        if col == 1:
            dt_value = datetime.strptime(
                subscription["estimatedReleaseDate"], "%Y-%m-%dT%H:%M:%SZ"
            )
            if role == LibbyModel.DisplaySortRole:
                return dt_value.isoformat()
            return format_date(dt_value, tweaks["gui_timestamp_display_format"])
        if col == 2:
            card = self.get_card(subscription["cardId"])
            if not card:
                return "Invalid card setup"
            return truncate_for_display(
                f'{card["advantageKey"]}: {card["cardName"] or ""}'
            )
        if col == 3:
            is_borrowed = subscription.get("__is_borrowed")
            if role == LibbyModel.DisplaySortRole:
                return int(is_borrowed)
            return _c("Yes") if is_borrowed else _c("No")
        return None


class LibbySearchModel(LibbyModel):
    """
    Underlying data model for the Search table view
    """

    column_headers = [
        _c("Title"),
        _c("Author"),
        _c("Published"),
        _c("Publisher"),
        _c("Format"),
        _("Library"),
    ]
    filter_hide_magazines_already_in_library = False

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent, synced_state, db)
        self._search_results: List[Dict] = []
        self.sync(synced_state)
        self._holds = []
        self._loans = []

    def has_loan(self, title_id, card_id):
        return bool(
            [
                loan
                for loan in self._loans
                if loan["id"] == title_id and loan["cardId"] == card_id
            ]
        )

    def has_hold(self, title_id, card_id):
        return bool(
            [
                hold
                for hold in self._holds
                if hold["id"] == title_id and hold["cardId"] == card_id
            ]
        )

    def library_keys(self) -> List[str]:
        return list(set([c["advantageKey"] for c in self._cards]))

    def get_cards_for_library_key(self, key):
        cards = [c for c in self._cards if c["advantageKey"] == key]
        if not cards:
            # use websiteId
            website_ids = [
                str(s["websiteId"]) for s in self._libraries if s["preferredKey"] == key
            ]
            cards = [c for c in self._cards if c["websiteId"] in website_ids]
        return sorted(cards, key=lambda c: c.get("counts", {}).get("loan", 0))

    def sync(self, synced_state: Optional[Dict] = None):
        if not synced_state:
            synced_state = {}
        if "cards" in synced_state and "__libraries" in synced_state:
            super().sync(synced_state)
            self._holds = synced_state.get("holds", [])
            self._loans = synced_state.get("loans", [])

        if "search_results" not in synced_state:
            return
        self.beginResetModel()
        self.filtered_rows = []
        for r in synced_state["search_results"]:
            try:
                if (
                    LibbyClient.is_downloadable_ebook_loan(r)
                    or LibbyClient.is_downloadable_magazine_loan(r)
                    or (
                        PREFS[PreferenceKeys.INCL_NONDOWNLOADABLE_TITLES]
                        and not (
                            LibbyClient.is_downloadable_magazine_loan(r)
                            or LibbyClient.is_downloadable_ebook_loan(r)
                        )
                    )
                ):
                    self.filtered_rows.append(r)
            except ValueError:
                pass
        self.endResetModel()

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        media: Dict = self.filtered_rows[row]
        # UserRole
        if role == Qt.UserRole:
            return media
        # TextAlignmentRole
        if role == Qt.TextAlignmentRole and col >= 2:
            return Qt.AlignCenter
        # ToolTipRole
        available_sites = []
        for k, v in media.get("siteAvailabilities", {}).items():
            v["advantageKey"] = k
            available_sites.append(v)
        available_sites = sorted(
            available_sites,
            key=cmp_to_key(OverDriveClient.sort_availabilities),
            reverse=True,
        )
        if role == Qt.ToolTipRole:
            if col == 0:
                return get_media_title(media, include_subtitle=True)
            if col == 1:
                return media.get("firstCreatorName", "")
            if col == 3:
                return media.get("publisher", {}).get("name")
            if col == 5:
                return ", ".join([s["advantageKey"] for s in available_sites])
        # DisplayRole, DisplaySortRole
        if role not in (Qt.DisplayRole, LibbyModel.DisplaySortRole):
            return None
        if col == 0:
            if role == LibbyModel.DisplaySortRole:
                return get_media_title(media, for_sorting=True)
            return get_media_title(media)
        if col == 1:
            creator_name = media.get("firstCreatorName", "")
            if role == LibbyModel.DisplaySortRole:
                return media.get("firstCreatorSortName", "") or creator_name
            if DEMO_MODE:
                return creator_name
            return truncate_for_display(creator_name, text_length=20)
        if col == 2:
            if media.get("publishDate"):
                dt_value = datetime.strptime(media["publishDate"], "%Y-%m-%dT%H:%M:%SZ")
                if role == LibbyModel.DisplaySortRole:
                    return dt_value.isoformat()
                return dt_value.year
        if col == 3:
            if DEMO_MODE:
                return media.get("publisher", {}).get("name", "")
            return truncate_for_display(
                media.get("publisher", {}).get("name", ""), text_length=20
            )
        if col == 4:
            try:
                media_format = LibbyClient.get_loan_format(
                    media,
                    PREFS[PreferenceKeys.PREFER_OPEN_FORMATS],
                    raise_if_not_downloadable=False,
                )
                if role == LibbyModel.DisplaySortRole:
                    return str(media_format)
                return _(LOAN_FORMAT_TRANSLATION.get(media_format, str(media_format)))
            except ValueError:
                return ", ".join(
                    [
                        _(
                            LOAN_FORMAT_TRANSLATION.get(
                                media_format["id"], str(media_format["id"])
                            )
                        )
                        for media_format in media.get("formats", [])
                    ]
                )
        if col == 5:
            if role == LibbyModel.DisplaySortRole:
                return len(available_sites)
            return truncate_for_display(
                ", ".join([s["advantageKey"] for s in available_sites]), text_length=15
            )
        return None
