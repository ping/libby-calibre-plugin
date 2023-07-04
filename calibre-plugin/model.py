from typing import Dict

from calibre.ebooks.metadata.book.base import Metadata

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


def get_loan_title(loan: Dict) -> str:
    title = loan["title"]
    if loan["type"]["id"] == LibbyMediaTypes.Magazine:
        title = f'{loan["title"]} - {loan.get("edition", "")}'
    return title


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

    def __init__(self, parent, synced_state=None, db=None):
        super().__init__(parent)
        self.db = db
        self._cards = []
        self._loans = []
        self.filtered_loans = []
        self.filter_hide_books_already_in_library = PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ]
        self.refresh_loans(synced_state)

    def refresh_loans(self, synced_state=None):
        if not synced_state:
            synced_state = {}
        self._cards = synced_state.get("cards", [])
        self._loans = sorted(
            synced_state.get("loans", []),
            key=lambda ln: ln["checkoutDate"],
            reverse=True,
        )
        self.filter_loans()

    def filter_loans(self):
        self.beginResetModel()
        self.filtered_loans = []
        for loan in [
            loan
            for loan in self._loans
            if (
                not PREFS[PreferenceKeys.HIDE_EBOOKS]
                and LibbyClient.is_downloadable_ebook_loan(loan)
            )
            or (
                not PREFS[PreferenceKeys.HIDE_MAGAZINES]
                and LibbyClient.is_downloadable_magazine_loan(loan)
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
        loan = self.filtered_loans[row]
        if role == Qt.UserRole:
            return loan
        if role == Qt.TextAlignmentRole and col in (2, 3, 4):
            return Qt.AlignCenter
        if role != Qt.DisplayRole:
            return None
        if col >= self.column_count:
            return None
        if col == 0:
            return get_loan_title(loan)
        if col == 1:
            return loan.get("firstCreatorName", "")
        if col == 2:
            return parse_datetime(loan["checkoutDate"]).strftime("%Y-%m-%d")
        if col == 3:
            return loan.get("type", {}).get("id", "")
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
