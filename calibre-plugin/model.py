from typing import Dict, Optional

from calibre.ebooks.metadata.book.base import Metadata
from calibre.utils.config import tweaks
from calibre.utils.date import format_date

# noinspection PyUnresolvedReferences
from qt.core import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
)

from .config import PREFS, PreferenceKeys
from .libby import LibbyClient
from .libby.client import LibbyMediaTypes
from .magazine_download_utils import parse_datetime

load_translations()


def get_loan_title(loan: Dict, for_sorting: bool = False) -> str:
    """
    Formats the title for a loan

    :param loan:
    :param for_sorting: If True, uses the sort attributes instead
    :return:
    """
    title = (
        loan["sortTitle"] if for_sorting and loan.get("sortTitle") else loan["title"]
    )
    if loan["type"]["id"] == LibbyMediaTypes.Magazine and loan.get("edition", ""):
        if not for_sorting:
            title = f'{title} - {loan.get("edition", "")}'
        else:
            title = f'{title}|{loan["id"]}'

    return title


LOAN_TYPE_TRANSLATION = {"ebook": _("ebook"), "magazine": _("magazine")}


class LibbyLoansModel(QAbstractTableModel):
    column_headers = [
        _("Title"),
        _("Author"),
        _("Checkout Date"),
        _("Type"),
        _("Format"),
    ]
    column_count = len(column_headers)
    filter_hide_books_already_in_library = False
    DisplaySortRole = Qt.UserRole + 1000

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent)
        self.db = db
        self._cards = []
        self._loans = []
        self.filtered_loans = []
        self.filter_hide_books_already_in_library = PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ]
        self.sync(synced_state)

    def sync(self, synced_state: Optional[Dict] = None):
        if not synced_state:
            synced_state = {}
        self._cards = synced_state.get("cards", [])
        self._loans = sorted(
            synced_state.get("loans", []),
            key=lambda ln: ln["checkoutDate"],
            reverse=True,
        )
        self.filter_loans()

    def get_card(self, card_id) -> Optional[Dict]:
        return next(
            iter([c for c in self._cards if c["cardId"] == card_id]),
            None,
        )

    def filter_loans(self):
        self.beginResetModel()
        self.filtered_loans = []
        for loan in [
            l
            for l in self._loans
            if (
                not PREFS[PreferenceKeys.HIDE_EBOOKS]
                and LibbyClient.is_downloadable_ebook_loan(l)
            )
            or (
                not PREFS[PreferenceKeys.HIDE_MAGAZINES]
                and LibbyClient.is_downloadable_magazine_loan(l)
            )
        ]:
            if not self.filter_hide_books_already_in_library:
                self.filtered_loans.append(loan)
                continue
            title = get_loan_title(loan)
            authors = []
            if loan.get("firstCreatorName", ""):
                authors = [loan.get("firstCreatorName", "")]
            if not self.db.has_book(Metadata(title=title, authors=authors)):
                self.filtered_loans.append(loan)
        self.endResetModel()

    def set_filter_hide_books_already_in_library(self, value: bool):
        if value != self.filter_hide_books_already_in_library:
            self.filter_hide_books_already_in_library = value
            self.filter_loans()

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return section + 1
        if section >= len(self.column_headers):
            return None
        return self.column_headers[section]

    def rowCount(self, parent):
        return len(self.filtered_loans)

    def columnCount(self, parent):
        return self.column_count

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= len(self.filtered_loans):
            return None
        loan: Dict = self.filtered_loans[row]
        if role == Qt.UserRole:
            return loan
        if role == Qt.TextAlignmentRole and col >= 2:
            return Qt.AlignCenter
        if role not in (Qt.DisplayRole, LibbyLoansModel.DisplaySortRole):
            return None
        if col >= self.column_count:
            return None
        if col == 0:
            if role == LibbyLoansModel.DisplaySortRole:
                return get_loan_title(loan, for_sorting=True)
            return get_loan_title(loan)
        if col == 1:
            creator_name = loan.get("firstCreatorName", "")
            if role == LibbyLoansModel.DisplaySortRole:
                return loan.get("firstCreatorSortName", "") or creator_name
            return creator_name
        if col == 2:
            dt_value = parse_datetime(loan["checkoutDate"])
            if role == LibbyLoansModel.DisplaySortRole:
                return dt_value.isoformat()
            return format_date(dt_value, tweaks["gui_timestamp_display_format"])
        if col == 3:
            type_id = loan.get("type", {}).get("id", "")
            return LOAN_TYPE_TRANSLATION.get(type_id, "") or type_id
        if col == 4:
            return str(
                LibbyClient.get_loan_format(
                    loan, PREFS[PreferenceKeys.PREFER_OPEN_FORMATS]
                )
            )
        return None

    def removeRows(self, row, count, _):
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        self.filtered_loans = (
            self.filtered_loans[:row] + self.filtered_loans[row + count :]
        )
        self.endRemoveRows()
        return True


class LibbyHoldsModel(QAbstractTableModel):
    column_headers = [
        _("Title"),
        _("Author"),
        _("Hold Date"),
        _("Library"),
        _("Type"),
        _("Available"),
    ]
    column_count = len(column_headers)
    filter_hide_unavailable_holds = True
    DisplaySortRole = Qt.UserRole + 1000

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent)
        self.db = db
        self._cards = []
        self._holds = []
        self.filtered_holds = []
        self.sync(synced_state)

    def sync(self, synced_state: Optional[Dict] = None):
        if not synced_state:
            synced_state = {}
        self._cards = synced_state.get("cards", [])
        self._holds = sorted(
            synced_state.get("holds", []),
            key=lambda h: (
                h["isAvailable"],
                h.get("estimatedWaitDays", 9999),
                h["placedDate"],
            ),
            reverse=True,
        )
        self.filter_holds()

    def get_card(self, card_id) -> Optional[Dict]:
        return next(
            iter([c for c in self._cards if c["cardId"] == card_id]),
            None,
        )

    def filter_holds(self):
        self.beginResetModel()
        self.filtered_holds = []
        for hold in [
            h
            for h in self._holds
            if (
                not PREFS[PreferenceKeys.HIDE_EBOOKS]
                and LibbyClient.is_downloadable_ebook_loan(h)
            )
            or (
                not PREFS[PreferenceKeys.HIDE_MAGAZINES]
                and LibbyClient.is_downloadable_magazine_loan(h)
            )
        ]:
            if hold.get("isAvailable", False) or not self.filter_hide_unavailable_holds:
                self.filtered_holds.append(hold)
        self.endResetModel()

    def set_filter_hide_unavailable_holds(self, value: bool):
        if value != self.filter_hide_unavailable_holds:
            self.filter_hide_unavailable_holds = value
            self.filter_holds()

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return section + 1
        if section >= len(self.column_headers):
            return None
        return self.column_headers[section]

    def rowCount(self, parent):
        return len(self.filtered_holds)

    def columnCount(self, parent):
        return self.column_count

    def data(self, index, role):
        row, col = index.row(), index.column()
        if row >= len(self.filtered_holds):
            return None
        hold: Dict = self.filtered_holds[row]
        if role == Qt.UserRole:
            return hold
        if role == Qt.TextAlignmentRole and col >= 2:
            return Qt.AlignCenter
        if role not in (Qt.DisplayRole, LibbyHoldsModel.DisplaySortRole):
            return None
        if col >= self.column_count:
            return None
        if col == 0:
            if role == LibbyHoldsModel.DisplaySortRole:
                return get_loan_title(hold, for_sorting=True)
            return get_loan_title(hold)
        if col == 1:
            creator_name = hold.get("firstCreatorName", "")
            if role == LibbyHoldsModel.DisplaySortRole:
                return hold.get("firstCreatorSortName", "") or creator_name
            return creator_name
        if col == 2:
            dt_value = parse_datetime(hold["placedDate"])
            if role == LibbyHoldsModel.DisplaySortRole:
                return dt_value.isoformat()
            return format_date(dt_value, tweaks["gui_timestamp_display_format"])
        if col == 3:
            return next(
                iter(
                    [
                        # c["library"]["name"]
                        c["advantageKey"]
                        for c in self._cards
                        if c["cardId"] == hold["cardId"]
                    ]
                ),
                "",
            )
        if col == 4:
            type_id = hold.get("type", {}).get("id", "")
            return LOAN_TYPE_TRANSLATION.get(type_id, "") or type_id
        if col == 5:
            if role == LibbyHoldsModel.DisplaySortRole:
                return str(hold.get("isAvailable", False))
            return _("Yes") if hold.get("isAvailable", False) else _("No")
        return None

    def removeRows(self, row, count, _):
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        self.filtered_holds = (
            self.filtered_holds[:row] + self.filtered_holds[row + count :]
        )
        self.endRemoveRows()
        return True
