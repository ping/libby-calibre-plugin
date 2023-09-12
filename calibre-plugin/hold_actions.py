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


class LibbyHoldCancel:
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        hold: Dict,
        log=None,
        abort=None,
        notifications=None,
    ):
        notifications.put((0.5, _("Cancelling")))
        libby_client.cancel_hold(hold)
        log.info("Cancelled hold for %s successfully." % get_media_title(hold))
        return hold


class LibbyHoldUpdate:
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        hold: Dict,
        days_to_suspend: int,
        log=None,
        abort=None,
        notifications=None,
    ):
        notifications.put((0.5, _("Updating hold")))
        hold = libby_client.suspend_hold(hold, days_to_suspend)
        log.info("Updated hold for %s successfully." % get_media_title(hold))
        return hold


class LibbyHoldCreate:
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        media: Dict,
        card: Dict,
        log=None,
        abort=None,
        notifications=None,
    ):
        notifications.put((0.5, _("Creating hold")))
        hold = libby_client.create_hold(media["id"], card["cardId"])
        log.info(
            "Created hold for %s at %s successfully."
            % (get_media_title(hold), card["advantageKey"])
        )
        return hold
