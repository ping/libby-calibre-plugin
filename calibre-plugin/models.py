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
from functools import cmp_to_key
from typing import Dict, List, Optional

from calibre.utils.config import tweaks
from calibre.utils.date import dt_as_local, format_date
from calibre.utils.icu import lower as icu_lower
from qt.core import (
    QAbstractTableModel,
    QFont,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)

from . import DEMO_MODE
from .compat import QColor_fromString, _c
from .config import PREFS, PreferenceKeys
from .libby import LibbyClient
from .libby.client import LibbyFormats, LibbyMediaTypes
from .overdrive import OverDriveClient
from .utils import PluginColors, PluginImages, obfuscate_date, obfuscate_name

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


def is_valid_type(media: Dict) -> bool:
    is_downloadable_ebook = LibbyClient.is_downloadable_ebook_loan(media)
    is_downloadable_magazine = (
        False
        if is_downloadable_ebook
        else LibbyClient.is_downloadable_magazine_loan(media)
    )
    if not (
        (is_downloadable_ebook and not PREFS[PreferenceKeys.HIDE_EBOOKS])
        or (is_downloadable_magazine and not PREFS[PreferenceKeys.HIDE_MAGAZINES])
        or (
            PREFS[PreferenceKeys.INCL_NONDOWNLOADABLE_TITLES]
            and not (is_downloadable_ebook or is_downloadable_magazine)
        )
    ):
        return False

    return True


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
CREATOR_ROLE_TRANSLATION = {
    "Cast Member": _("Cast Member"),
    "Contributor": _("Contributor"),
    "Editor": _("Editor"),
    "Illustrator": _("Illustrator"),
    "Narrator": _("Narrator"),
    "Performer": _("Performer"),
    "Photographer": _("Photographer"),
    "Translator": _("Translator"),
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
        return len(self._rows)

    def removeRows(self, row, count, _):
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        self._rows = self._rows[:row] + self._rows[row + count :]
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

    def has_media(self, title_id: str, card_id: str, medias: List[Dict]):
        return bool(
            [m for m in medias if m["id"] == title_id and m["cardId"] == card_id]
        )

    def remove_media(self, title_id: str, card_id: str, medias: List[Dict]):
        return [
            m for m in medias if not (m["id"] == title_id and m["cardId"] == card_id)
        ]


class LibbySortFilterModel(QSortFilterProxyModel):
    filter_text_set = pyqtSignal()

    def __init__(self, parent, model=None, db=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(-1)
        self.setSortRole(LibbyModel.DisplaySortRole)
        self.filter_text = ""
        self.db = db
        if model:
            self.setSourceModel(model)

    def headerData(self, section, orientation, role):
        # if display role of vertical headers (row numbers)
        if orientation == Qt.Vertical and role == Qt.DisplayRole:
            return section + 1
        return super().headerData(section, orientation, role)

    def set_filter_text(self, filter_text_value: str):
        self.filter_text = icu_lower(str(filter_text_value).strip())
        self.invalidateFilter()
        self.filter_text_set.emit()


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

    def __init__(self, parent, synced_state=None, db=None, resources=None):
        super().__init__(parent, synced_state, db)
        self.resources = resources
        self.all_book_ids_titles = self.db.fields["title"].table.book_col_map
        self.all_book_ids_formats = self.db.fields["formats"].table.book_col_map
        self.all_book_ids_identifiers = self.db.fields["identifiers"].table.book_col_map
        self.filter_hide_books_already_in_library = PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ]
        self._holds = []
        self.sync(synced_state)

    def sync(self, synced_state: Optional[Dict] = None):
        super().sync(synced_state)
        if not synced_state:
            synced_state = {}
        self._rows = synced_state.get("loans", [])
        self._holds = synced_state.get("holds", [])
        self.sort_rows()

    def has_hold(self, loan: Dict) -> bool:
        # used to check that we don't offer to create a new hold for
        # an expiring loan when a hold already exists
        return self.has_media(loan["id"], loan["cardId"], self._holds)

    def add_loan(self, loan: Dict):
        self._rows.append(loan)
        self.sort_rows()

    def remove_loan(self, loan: Dict):
        self._rows = self.remove_media(loan["id"], loan["cardId"], self._rows)
        self.sort_rows()

    def add_hold(self, hold: Dict):
        self._holds.append(hold)

    def remove_hold(self, hold: Dict):
        self._holds = self.remove_media(hold["id"], hold["cardId"], self._holds)

    def sort_rows(self):
        self.beginResetModel()
        self._rows = sorted(self._rows, key=lambda ln: ln["checkoutDate"], reverse=True)
        self.endResetModel()

    def set_filter_hide_books_already_in_library(self, value: bool):
        if value != self.filter_hide_books_already_in_library:
            self.filter_hide_books_already_in_library = value
            self.sort_rows()

    def setData(self, index, loan, role=Qt.EditRole):
        if role == Qt.EditRole:
            self._rows[index.row()] = loan
            self.dataChanged.emit(index, index)
            return True

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        loan: Dict = self._rows[row]
        # UserRole
        if role == Qt.UserRole:
            return loan
        # DecorationRole
        if role == Qt.DecorationRole:
            if col == 2 and loan.get("isLuckyDayCheckout"):
                return self.resources[PluginImages.Clover]
            if (
                col == 4
                and loan.get("type", {}).get("id", "") == LibbyMediaTypes.EBook
                and LibbyClient.has_format(loan, LibbyFormats.EBookKindle)
                and not LibbyClient.get_locked_in_format(loan)
            ):
                return self.resources[PluginImages.Unlock]
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


class LibbyLoansSortFilterModel(LibbySortFilterModel):
    def __init__(self, parent, model=None, db=None):
        super().__init__(parent, model, db)
        self.all_book_ids_titles = self.db.fields["title"].table.book_col_map
        self.all_book_ids_formats = self.db.fields["formats"].table.book_col_map
        self.all_book_ids_identifiers = self.db.fields["identifiers"].table.book_col_map
        self.filter_hide_books_already_in_library = PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ]
        self.temporarily_hidden: List[Dict] = []

    def temporarily_hide(self, loan: Dict):
        if not self.is_temporarily_hidden(loan):
            self.temporarily_hidden.append(loan)
            self.invalidateFilter()

    def unhide(self, loan: Dict):
        self.temporarily_hidden = [
            h
            for h in self.temporarily_hidden
            if not (h["id"] == loan["id"] and h["cardId"] == loan["cardId"])
        ]
        self.invalidateFilter()

    def is_temporarily_hidden(self, loan: Dict) -> bool:
        return bool(
            [
                h
                for h in self.temporarily_hidden
                if h["id"] == loan["id"] and h["cardId"] == loan["cardId"]
            ]
        )

    def set_filter_hide_books_already_in_library(self, value: bool):
        if value != self.filter_hide_books_already_in_library:
            self.filter_hide_books_already_in_library = value
            self.invalidateFilter()

    def filterAcceptsRow(self, sourceRow, sourceParent):
        model: LibbyModel = self.sourceModel()
        index = model.index(sourceRow, 0, sourceParent)
        loan = model.data(index, Qt.UserRole)

        if not is_valid_type(loan):
            return False

        try:
            loan_format = LibbyClient.get_loan_format(
                loan,
                PREFS[PreferenceKeys.PREFER_OPEN_FORMATS],
                raise_if_not_downloadable=not PREFS[
                    PreferenceKeys.INCL_NONDOWNLOADABLE_TITLES
                ],
            )
        except ValueError:
            return False

        if not (self.filter_text or self.filter_hide_books_already_in_library):
            # return early if no filters
            return True

        loan_title1 = icu_lower(get_media_title(loan).strip())
        if self.filter_hide_books_already_in_library:
            # hide lib books filter is enabled
            if self.is_temporarily_hidden(loan):
                return False

            book_in_library = False
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

            if book_in_library:
                return False

        if not self.filter_text:
            return True

        card = model.get_card(loan["cardId"])
        creator_name = icu_lower(loan.get("firstCreatorName", ""))
        library = icu_lower(card["advantageKey"])
        return (
            self.filter_text in loan_title1
            or self.filter_text in creator_name
            or self.filter_text in library
        )


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
        self._rows = synced_state.get("holds", [])
        self.sort_rows()

    def add_hold(self, hold: Dict):
        self._rows.append(hold)
        self.sort_rows()

    def remove_hold(self, hold: Dict):
        self._rows = self.remove_media(hold["id"], hold["cardId"], self._rows)
        self.sort_rows()

    def sort_rows(self):
        self.beginResetModel()
        self._rows = sorted(
            self._rows,
            key=lambda h: (
                h["isAvailable"],
                -h.get("estimatedWaitDays", 9999),
                h["placedDate"],
            ),
            reverse=True,
        )
        self.endResetModel()

    def setData(self, index, hold, role=Qt.EditRole):
        if role == Qt.EditRole:
            self._rows[index.row()] = hold
            self.dataChanged.emit(index, index)
            return True

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        hold: Dict = self._rows[row]
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


class LibbyHoldsSortFilterModel(LibbySortFilterModel):
    def __init__(self, parent, model=None, db=None):
        super().__init__(parent, model, db)
        self.filter_hide_unavailable_holds = PREFS[
            PreferenceKeys.HIDE_HOLDS_UNAVAILABLE
        ]

    def set_filter_hide_unavailable_holds(self, value: bool):
        if value != self.filter_hide_unavailable_holds:
            self.filter_hide_unavailable_holds = value
            self.invalidateFilter()

    def filterAcceptsRow(self, sourceRow, sourceParent):
        model: LibbyModel = self.sourceModel()
        index = model.index(sourceRow, 0, sourceParent)
        hold = model.data(index, Qt.UserRole)

        if not is_valid_type(hold):
            return False

        if not (self.filter_hide_unavailable_holds or self.filter_text):
            # return early if no filters
            return True

        if self.filter_hide_unavailable_holds and not hold.get("isAvailable", False):
            return False

        if not self.filter_text:
            return True

        index = self.sourceModel().index(sourceRow, 0, sourceParent)
        hold = self.sourceModel().data(index, Qt.UserRole)
        card = self.sourceModel().get_card(hold["cardId"])
        title = icu_lower(get_media_title(hold))
        creator_name = icu_lower(hold.get("firstCreatorName", ""))
        library = icu_lower(card["advantageKey"])
        return (
            self.filter_text in title
            or self.filter_text in creator_name
            or self.filter_text in library
        )


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
        self.sort_rows()

    def sort_rows(self):
        self.beginResetModel()
        self._rows = sorted(self._rows, key=lambda c: c["advantageKey"])
        self.endResetModel()

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        card: Dict = self._rows[row]
        if role == Qt.UserRole:
            return card
        if role != Qt.DisplayRole:
            return None
        if col == 0:
            return truncate_for_display(
                f'{card["advantageKey"]}: {card["cardName"] or ""}'
            )
        return None


class LibbyCardsSortFilterModel(LibbySortFilterModel):
    def filterAcceptsRow(self, sourceRow, sourceParent):
        if not self.filter_text:
            return True
        model = self.sourceModel()
        index = model.index(sourceRow, 0, sourceParent)
        card = model.data(index, Qt.UserRole)
        library = model.get_library(model.get_website_id(card))
        accept = (
            self.filter_text in icu_lower(card.get("advantageKey", ""))
            or self.filter_text in icu_lower(card.get("cardName", ""))
            or self.filter_text in icu_lower(library["name"])
        )
        return accept


class LibbyMagazinesModel(LibbyModel):
    """
    Underlying data model for the Magazines table view
    """

    column_headers = [_c("Title"), _("Release Date"), _("Library Card"), _("Borrowed")]
    filter_hide_magazines_already_in_library = False

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent, synced_state, db)
        self._loans: List[Dict] = []
        self.sync(synced_state)

    def sync(self, synced_state: Optional[Dict] = None):
        super().sync(synced_state)
        if not synced_state:
            synced_state = {}
        self._loans = synced_state.get("loans", [])
        self._rows = synced_state.get("__subscriptions", [])
        self.fill_and_sort_rows()

    def sync_subscriptions(self, subscriptions: List[Dict]):
        self._rows = subscriptions
        self.fill_and_sort_rows()

    def add_loan(self, loan: Dict):
        self._loans.append(loan)
        self.fill_and_sort_rows()

    def remove_loan(self, loan: Dict):
        self._loans = self.remove_media(loan["id"], loan["cardId"], self._loans)
        self.fill_and_sort_rows()

    def fill_and_sort_rows(self):
        self.beginResetModel()
        self._rows = sorted(
            self._rows, key=lambda t: t["estimatedReleaseDate"], reverse=True
        )
        for r in self._rows:
            r["__is_borrowed"] = bool(
                [loan for loan in self._loans if loan["id"] == r["id"]]
            )
        self.endResetModel()

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        subscription: Dict = self._rows[row]
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
            dt_value = LibbyClient.parse_datetime(subscription["estimatedReleaseDate"])
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


class LibbyMagazinesSortFilterModel(LibbySortFilterModel):
    def __init__(self, parent, model=None, db=None):
        super().__init__(parent, model, db)
        self.all_book_ids_titles = self.db.fields["title"].table.book_col_map
        self.all_book_ids_formats = self.db.fields["formats"].table.book_col_map
        self.filter_hide_magazines_already_in_library = PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ]

    def set_filter_hide_magazines_already_in_library(self, value: bool):
        if value != self.filter_hide_magazines_already_in_library:
            self.filter_hide_magazines_already_in_library = value
            self.invalidateFilter()

    def filterAcceptsRow(self, sourceRow, sourceParent):

        if not (self.filter_hide_magazines_already_in_library or self.filter_text):
            return True

        model: LibbyModel = self.sourceModel()
        index = model.index(sourceRow, 0, sourceParent)
        subscription = model.data(index, Qt.UserRole)

        if self.filter_hide_magazines_already_in_library:
            # hide lib books filter is enabled
            book_in_library = False
            q1 = icu_lower(get_media_title(subscription).strip())
            q2 = icu_lower(get_media_title(subscription, include_subtitle=True).strip())
            for book_id, title in iter(self.all_book_ids_titles.items()):
                if icu_lower(title) not in (q1, q2):
                    continue
                if (
                    not PREFS[PreferenceKeys.EXCLUDE_EMPTY_BOOKS]
                ) or self.all_book_ids_formats.get(book_id):
                    book_in_library = True
                break  # check only first matching book title
            if book_in_library:
                return False

        if not self.filter_text:
            return True

        card = self.sourceModel().get_card(subscription["cardId"])
        title = icu_lower(get_media_title(subscription))
        library = icu_lower(card["advantageKey"])
        return self.filter_text in title or self.filter_text in library


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

    def has_loan(self, title_id: str, card_id: str):
        return self.has_media(title_id, card_id, self._loans)

    def has_hold(self, title_id: str, card_id: str):
        return self.has_media(title_id, card_id, self._holds)

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
        self._rows = []
        for r in synced_state["search_results"]:
            try:
                if is_valid_type(r):
                    self._rows.append(r)
            except ValueError:
                pass
        self.endResetModel()

    def add_hold(self, hold: Dict):
        self._holds.append(hold)

    def remove_hold(self, hold: Dict):
        self._holds = self.remove_media(hold["id"], hold["cardId"], self._holds)

    def add_loan(self, loan: Dict):
        self._loans.append(loan)

    def remove_loan(self, loan: Dict):
        self._loans = self.remove_media(loan["id"], loan["cardId"], self._loans)

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= self.rowCount() or col >= self.columnCount():
            return None
        media: Dict = self._rows[row]
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
            publish_date = media.get("publishDate") or media.get("estimatedReleaseDate")
            if publish_date:
                dt_value = LibbyClient.parse_datetime(publish_date)
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


class LibbySearchSortFilterModel(LibbySortFilterModel):
    def __init__(self, parent, model=None, db=None):
        super().__init__(parent, model, db)
