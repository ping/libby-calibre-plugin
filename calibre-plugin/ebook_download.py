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
from typing import Dict, Optional

from calibre.ptempfile import PersistentTemporaryDirectory

from .compat import _c
from .download import LibbyDownload
from .libby import LibbyClient

# noinspection PyUnreachableCode
if False:
    load_translations = lambda x=None: x  # noqa: E731

load_translations()


class CustomEbookDownload(LibbyDownload):
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        loan: Dict,
        card: Dict,
        library: Dict,
        format_id: str,
        book_id=None,
        metadata=None,
        cookie_file=None,
        url="",
        filename="",
        save_loc="",
        add_to_lib=True,
        tags=None,
        create_browser=None,
        log=None,
        abort=None,
        notifications=None,
    ):
        if not tags:
            tags = []
        downloaded_filepath: Optional[Path] = None
        try:
            downloaded_filepath = self._custom_download(
                libby_client,
                loan,
                format_id,
                filename,
                log=log,
                abort=abort,
                notifications=notifications,
            )
            self.add(
                gui,
                loan,
                card,
                library,
                format_id,
                downloaded_filepath,
                book_id,
                tags,
                metadata,
                log=log,
            )

        finally:
            try:
                if downloaded_filepath:
                    downloaded_filepath.unlink(missing_ok=True)
            except:  # noqa
                pass

    def _custom_download(
        self,
        libby_client: LibbyClient,
        loan: Dict,
        format_id: str,
        filename: str,
        log=None,
        abort=None,
        notifications=None,
    ) -> Path:
        book_folder_path = Path(PersistentTemporaryDirectory())
        book_file_path = book_folder_path.joinpath(filename)

        notifications.put((0.5, _c("Downloading")))
        res_content = libby_client.fulfill_loan_file(
            loan["id"], loan["cardId"], format_id
        )
        with book_file_path.open("w+b") as tf:
            tf.write(res_content)

        return book_file_path
