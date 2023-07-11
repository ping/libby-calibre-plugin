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
from typing import List, Dict

from .config import PREFS, PreferenceKeys
from .magazine_download_utils import extract_isbn, extract_asin


class LibbyDownload:
    def add(
        self,
        gui,
        loan: Dict,
        card: Dict,
        library: Dict,
        format_id: str,
        downloaded_file: Path,
        book_id: int = None,
        tags: List[str] = [],
        metadata=None,
        log=None,
    ) -> None:
        db = gui.current_db.new_api
        ext = downloaded_file.suffix[1:]  # remove the "." suffix

        if book_id and metadata:
            log.info(
                "Adding {ext} format to existing book {book}".format(
                    ext=ext.upper(), book=metadata.title
                )
            )
            # if book_id is found, it's an OverDriveLink book, download and add the book as a format
            successfully_added = db.add_format(
                book_id, ext.upper(), str(downloaded_file), replace=False
            )
            if successfully_added:
                metadata.tags.extend(tags)
                db.set_metadata(book_id, metadata)
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
                mi = get_metadata(f, new_ext, force_read_metadata=True)
            mi.tags.extend(tags)

            # set identifiers
            isbn = extract_isbn(loan.get("formats", []), [format_id])
            asin = extract_asin(loan.get("formats", []))
            identifiers = mi.get_identifiers()
            if isbn and not identifiers.get("isbn"):
                mi.set_identifier("isbn", isbn)
            if asin and not (identifiers.get("amazon") or identifiers.get("asin")):
                mi.set_identifier("amazon", asin)
            if (
                PREFS[PreferenceKeys.OVERDRIVELINK_INTEGRATION]
                and "Overdrive Link" in gui.iactions
                and not identifiers.get("odid")
            ):
                # user has OverdriveLink installed with integration enabled and no odid
                mi.set_identifier(
                    "odid", f'{loan["id"]}@{library["preferredKey"]}.overdrive.com'
                )

            book_id = gui.library_view.model().db.create_book_entry(mi)
            gui.library_view.model().db.add_format_with_hooks(
                book_id, new_ext.upper(), new_path, index_is_id=True
            )
            gui.library_view.model().books_added(1)
            gui.library_view.model().count_changed()
