#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import PREFS, PreferenceKeys
from .libby import LibbyClient
from .overdrive import OverDriveClient
from .utils import OD_IDENTIFIER, generate_od_identifier


class LibbyDownload:
    """
    Base class for download jobs
    """

    def update_metadata(
        self,
        gui,
        loan: Dict,
        library: Dict,
        format_id: str,
        metadata,
        tags: Optional[List[str]] = None,
        media: Optional[Dict] = None,
    ):
        """
        Update identifiers in book metadata.

        :param gui:
        :param loan:
        :param library:
        :param format_id:
        :param metadata:
        :param tags:
        :param media:
        :return:
        """
        if not tags:
            tags = []
        if not media:
            media = {}
        metadata.tags.extend(tags)

        isbn = OverDriveClient.extract_isbn(
            loan.get("formats", []), [format_id] if format_id else []
        )
        if format_id and not isbn:
            isbn = OverDriveClient.extract_isbn(loan.get("formats", []), [])
        asin = OverDriveClient.extract_asin(loan.get("formats", []))
        odid_identifier = generate_od_identifier(loan, library)

        identifiers = metadata.get_identifiers()
        if isbn and not identifiers.get("isbn"):
            metadata.set_identifier("isbn", isbn)
        if asin and not (identifiers.get("amazon") or identifiers.get("asin")):
            metadata.set_identifier("amazon", asin)
        if (
            PREFS[PreferenceKeys.OVERDRIVELINK_INTEGRATION]
            and "Overdrive Link" in gui.iactions
        ):
            # user has OverdriveLink installed with integration enabled
            try:
                from calibre_plugins.overdrive_link.link import ODLink, ODLinkSet

                new_odlink = ODLink(string=odid_identifier)
                odlinks = ODLinkSet(string=identifiers.get(OD_IDENTIFIER, ""))
                if new_odlink not in odlinks:
                    odlinks.add(ODLink(string=odid_identifier))
                    metadata.set_identifier(OD_IDENTIFIER, str(odlinks))
            except ImportError:
                found_odid_identifiers = (
                    identifiers[OD_IDENTIFIER].split("&")
                    if identifiers.get(OD_IDENTIFIER)
                    else []
                )
                if odid_identifier not in found_odid_identifiers:
                    found_odid_identifiers.append(odid_identifier)
                    metadata.set_identifier(
                        OD_IDENTIFIER, "&".join(found_odid_identifiers)
                    )

        # update more metadata if available and not already set
        pub_date = (
            LibbyClient.parse_datetime(loan["publishDate"])
            if loan.get("publishDate")
            else None
        )
        if pub_date and not metadata.pubdate:
            metadata.pubdate = pub_date
        publisher_name = loan.get("publisher", {}).get("name", "") or loan.get(
            "publisherAccount", {}
        ).get("name", "")
        if publisher_name and not metadata.publisher:
            metadata.publisher = publisher_name
        description = (
            media.get("fullDescription")
            or media.get("description")
            or media.get("shortDescription")
        )
        if description and not metadata.comments:
            metadata.comments = description
        series_info = loan.get("detailedSeries")
        if series_info:
            series_name = series_info.get("seriesName")
            if series_name and not metadata.series:
                metadata.series = series_name
            try:
                series_index = float(series_info.get("readingOrder", 0))
                if series_index and series_index > 0 and not metadata.series_index:
                    metadata.series_index = series_index
            except:  # noqa
                pass

        return metadata

    def update_custom_columns(self, book_id, loan, db, log):
        """
        Update custom columns from loan.

        :param book_id:
        :param loan:
        :param db:
        :param log:
        :return:
        """
        try:
            if PREFS[PreferenceKeys.CUSTCOL_BORROWED_DATE] and loan.get("checkoutDate"):
                borrowed_date = LibbyClient.parse_datetime(loan["checkoutDate"])
                db.set_field(
                    PREFS[PreferenceKeys.CUSTCOL_BORROWED_DATE],
                    {book_id: borrowed_date},
                )
        except Exception as err:
            log.exception("Error updating Borrowed Date: {err}".format(err=err))
        try:
            if PREFS[PreferenceKeys.CUSTCOL_DUE_DATE] and loan.get("expireDate"):
                due_date = LibbyClient.parse_datetime(loan["expireDate"])
                db.set_field(
                    PREFS[PreferenceKeys.CUSTCOL_DUE_DATE],
                    {book_id: due_date},
                )
        except Exception as err:
            log.exception("Error updating Due Date: {err}".format(err=err))

        try:
            if PREFS[PreferenceKeys.CUSTCOL_LOAN_TYPE] and loan.get("type", {}).get(
                "id"
            ):
                db.set_field(
                    PREFS[PreferenceKeys.CUSTCOL_LOAN_TYPE],
                    {book_id: loan["type"]["id"]},
                )
        except Exception as err:
            log.exception("Error updating Loan Type: {err}".format(err=err))

    def add(
        self,
        gui,
        loan: Dict,
        card: Dict,
        library: Dict,
        format_id: str,
        downloaded_file: Path,
        book_id: int = 0,
        tags: Optional[List[str]] = None,
        metadata=None,
        log=None,
    ) -> None:
        """
        Adds the new downloaded book to calibre db

        :param gui:
        :param loan:
        :param card:
        :param library:
        :param format_id:
        :param downloaded_file:
        :param book_id:
        :param tags:
        :param metadata:
        :param log:
        :return:
        """
        db = gui.current_db.new_api
        ext = downloaded_file.suffix[1:]  # remove the "." suffix

        if book_id and metadata:
            log.info(
                "Adding {ext} format to existing book {book}".format(
                    ext=ext.upper(), book=metadata.title
                )
            )
            # if book_id is found, it's an empty book, download and add the epub/pdf as a format
            successfully_added = db.add_format(
                book_id, ext.upper(), str(downloaded_file), replace=False
            )
            if successfully_added:
                metadata = self.update_metadata(
                    gui, loan, library, format_id, metadata, tags
                )
                db.set_metadata(book_id, metadata)
                self.update_custom_columns(book_id, loan, db, log)

                if PREFS[PreferenceKeys.MARK_UPDATED_BOOKS]:
                    gui.current_db.set_marked_ids([book_id])  # mark updated book
                gui.library_view.model().refresh_ids([book_id])
        else:
            # add as a new book
            from calibre.ebooks.metadata.meta import get_metadata
            from calibre.ebooks.metadata.worker import run_import_plugins

            # we have to run_import_plugins first so that we can get
            # the correct metadata for the .acsm
            new_path = run_import_plugins(
                (str(downloaded_file),),
                time.monotonic_ns(),
                str(downloaded_file.parent),
            )[0]
            new_ext = Path(new_path).suffix[1:]

            # Reference: https://github.com/kovidgoyal/calibre/blob/58c609fa7db3a8df59981c3bf73823fa1862c392/src/calibre/gui2/ebook_download.py#L108-L116
            with open(new_path, "rb") as f:
                metadata = get_metadata(f, new_ext, force_read_metadata=True)

            metadata = self.update_metadata(
                gui, loan, library, format_id, metadata, tags
            )
            book_id = gui.library_view.model().db.create_book_entry(metadata)
            gui.library_view.model().db.add_format_with_hooks(
                book_id, new_ext.upper(), new_path, index_is_id=True
            )
            self.update_custom_columns(book_id, loan, db, log)
            gui.library_view.model().books_added(1)
            gui.library_view.model().count_changed()
