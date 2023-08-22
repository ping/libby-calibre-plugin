#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlencode, urlparse

from calibre import browser
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ptempfile import PersistentTemporaryDirectory

from .compat import _c
from .config import PREFS, PreferenceKeys
from .download import LibbyDownload
from .libby import LibbyClient, LibbyMediaTypes
from .models import get_media_title
from .overdrive import OverDriveClient

# noinspection PyUnreachableCode
if False:
    load_translations = lambda x=None: x  # noqa: E731

load_translations()


class EmptyBookDownload(LibbyDownload):
    def _download_cover(self, loan, log):
        cover_url = OverDriveClient.get_best_cover_url(loan)
        if not cover_url:
            return None, None

        br = browser()
        if loan.get("type", {}).get("id", "") == LibbyMediaTypes.Audiobook:
            square_cover_url_params = {
                "type": "auto",
                "width": str(510),
                "height": str(510),
                "force": "true",
                "quality": str(80),
                "url": urlparse(cover_url).path,
            }
            resize_cover_url = "https://ic.od-cdn.com/resize?" + urlencode(
                square_cover_url_params
            )
            try:
                resize_cover_res = br.open(
                    resize_cover_url, timeout=PREFS[PreferenceKeys.NETWORK_TIMEOUT]
                )
                return "jpeg", resize_cover_res.read()
            except Exception as err:
                # fallback to original cover_url
                log.warning("Unable to download resized cover: %s" % str(err))

        try:
            cover_res = br.open(
                cover_url, timeout=PREFS[PreferenceKeys.NETWORK_TIMEOUT]
            )
            return "jpeg", cover_res.read()
        except Exception as err:
            log.warning("Unable to download cover: %s" % str(err))

        return None, None

    def _download_attachments(
        self,
        libby_client: LibbyClient,
        loan: Dict,
        log=None,
        abort=None,
        notifications=None,
    ) -> List[Path]:

        book_file_paths: List[Path] = []
        bundled_contents = loan.get("bundledContent", [])
        if not bundled_contents:
            return book_file_paths

        book_folder_path = Path(PersistentTemporaryDirectory())
        for i, content in enumerate(bundled_contents):
            try:
                format_id = LibbyClient.get_loan_format(
                    content,
                    PREFS[PreferenceKeys.PREFER_OPEN_FORMATS],
                    raise_if_not_downloadable=True,
                )
            except ValueError:
                continue

            filename = f'{content["id"]}.{LibbyClient.get_file_extension(format_id)}'
            book_file_path = book_folder_path.joinpath(filename)

            notifications.put((i / len(bundled_contents), _c("Downloading")))
            res_content = libby_client.fulfill_loan_file(
                content["id"], loan["cardId"], format_id
            )
            with book_file_path.open("w+b") as tf:
                tf.write(res_content)

            book_file_paths.append(book_file_path)

        return book_file_paths

    def _add_bundled_content(
        self, db, client, book_id, loan, log, abort, notifications
    ):
        # download bundled content for audiobooks
        if loan.get("type", {}).get("id", "") == LibbyMediaTypes.Audiobook and loan.get(
            "bundledContent"
        ):
            book_file_paths = self._download_attachments(
                client, loan, log, abort, notifications
            )
            for book_file_path in book_file_paths:
                ext = book_file_path.suffix[1:]  # remove the "." in suffix
                db.add_format(book_id, ext.upper(), str(book_file_path), replace=False)

    def __call__(
        self,
        gui,
        client: LibbyClient,
        overdrive_client: OverDriveClient,
        loan: Dict,
        card: Dict,
        library: Dict,
        format_id: str,
        book_id=None,
        metadata=None,
        tags=None,
        log=None,
        abort=None,
        notifications=None,
    ):
        if not tags:
            tags = []
        db = gui.current_db.new_api
        media = overdrive_client.media(loan["id"])
        if metadata and book_id:
            metadata = self.update_metadata(
                gui, loan, library, format_id, metadata, tags, media
            )
            db.set_metadata(book_id, metadata)
            if not metadata.cover_data:
                metadata.cover_data = self._download_cover(loan, log)
            self.update_custom_columns(book_id, loan, db, log)
            self._add_bundled_content(
                db, client, book_id, loan, log, abort, notifications
            )
            if PREFS[PreferenceKeys.MARK_UPDATED_BOOKS]:
                gui.current_db.set_marked_ids([book_id])  # mark updated book
            gui.library_view.model().refresh_ids([book_id])
        else:
            metadata = Metadata(
                title=get_media_title(loan),
                authors=[loan["firstCreatorName"]]
                if loan.get("firstCreatorName")
                else [],
            )
            metadata = self.update_metadata(
                gui, loan, library, format_id, metadata, tags, media
            )
            metadata.cover_data = self._download_cover(loan, log)

            book_id = gui.library_view.model().db.create_book_entry(metadata)
            self.update_custom_columns(book_id, loan, db, log)
            self._add_bundled_content(
                db, client, book_id, loan, log, abort, notifications
            )
            gui.library_view.model().books_added(1)
            gui.library_view.model().count_changed()

        return loan
