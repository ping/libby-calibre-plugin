#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import os
from typing import Dict

from calibre.gui2.ebook_download import EbookDownload
from calibre.ptempfile import PersistentTemporaryDirectory

from .libby import LibbyClient


class CustomEbookDownload(EbookDownload):
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        loan: Dict,
        format_id: str,
        cookie_file=None,
        url="",
        filename="",
        save_loc="",
        add_to_lib=True,
        tags=[],
        create_browser=None,
        log=None,
        abort=None,
        notifications=None,
    ):
        dfilename = ""
        try:
            dfilename = self._custom_download(libby_client, loan, format_id, filename)
            self._add(dfilename, gui, add_to_lib, tags)
            self._save_as(dfilename, save_loc)
        finally:
            try:
                if dfilename:
                    os.remove(dfilename)
            except:
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
    ):
        temp_path = os.path.join(PersistentTemporaryDirectory(), filename)
        notifications.put((0.5, "Downloading"))
        res_content = libby_client.fulfill_loan_file(
            loan["id"], loan["cardId"], format_id
        )
        with open(temp_path, "w+b") as tf:
            tf.write(res_content)
            dfilename = tf.name
        return dfilename
