#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

from typing import Dict

from .libby import LibbyClient
from .models import get_media_title

# noinspection PyUnreachableCode
if False:
    load_translations = _ = lambda x=None: x

load_translations()


class LibbyBorrowHold:
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        hold: Dict,
        card: Dict,
        log=None,
        abort=None,
        notifications=None,
    ):
        logger = log
        notifications.put((0.5, _("Borrowing")))
        loan = libby_client.borrow_hold(hold, card)
        logger.info(
            "Borrowed %s successfully from %s."
            % (get_media_title(loan), card["advantageKey"])
        )
        return loan
