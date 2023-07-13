#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import math
from timeit import default_timer as timer
from typing import Dict

from qt.core import QObject, pyqtSignal

from . import logger
from .config import PREFS, PreferenceKeys
from .libby import LibbyClient
from .overdrive import OverDriveClient


class OverDriveLibraryMediaWorker(QObject):
    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def __int__(self):
        super().__init__()

    def run(self, overdrive_client: OverDriveClient, card: Dict, title_id: str):
        total_start = timer()
        try:
            media = overdrive_client.library_media(card["advantageKey"], title_id)
            logger.info(
                "Total OverDrive Library Media Fetch took %f seconds"
                % (timer() - total_start)
            )
            self.finished.emit(media)
        except Exception as err:
            logger.info(
                "OverDrive Library Media Fetch failed after %f seconds"
                % (timer() - total_start)
            )
            self.errored.emit(err)


class SyncDataWorker(QObject):
    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def __int__(self):
        super().__init__()

    def run(self):
        libby_token: str = PREFS[PreferenceKeys.LIBBY_TOKEN]
        if not libby_token:
            self.finished.emit({})
            return

        subscriptions = PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS]
        total_start = timer()
        try:
            # Fetch libby sync state
            start = timer()
            libby_client = LibbyClient(
                identity_token=libby_token, max_retries=1, timeout=30, logger=logger
            )
            synced_state = libby_client.sync()
            logger.info("Libby Sync request took %f seconds" % (timer() - start))

            # Fetch libraries details from OD and patch it onto synced state
            start = timer()
            cards = synced_state.get("cards", [])
            all_website_ids = [c["library"]["websiteId"] for c in cards]

            logger.info("Fetching %d libraries" % len(all_website_ids))
            od_client = OverDriveClient(max_retries=1, timeout=30, logger=logger)
            max_per_page = 24
            total_pages = math.ceil(len(all_website_ids) / max_per_page)
            libraries = []
            for page in range(1, 1 + total_pages):
                website_ids = all_website_ids[
                    (page - 1) * max_per_page : page * max_per_page
                ]
                results = od_client.libraries(
                    website_ids=website_ids, per_page=max_per_page
                )
                libraries.extend(results.get("items", []))
            logger.info(
                "OverDrive Libraries requests took %f seconds" % (timer() - start)
            )
            synced_state["__libraries"] = libraries

            subbed_magazines = []
            if subscriptions:
                logger.info("Checking %d magazines" % len(subscriptions))
                # Fetch magazine details from OD
                start = timer()
                all_parent_magazine_ids = [
                    s["parent_magazine_id"] for s in subscriptions
                ]
                total_pages = math.ceil(
                    len(all_parent_magazine_ids) / OverDriveClient.MAX_PER_PAGE
                )
                for page in range(1, 1 + total_pages):
                    parent_magazine_ids = all_parent_magazine_ids[
                        (page - 1)
                        * OverDriveClient.MAX_PER_PAGE : page
                        * OverDriveClient.MAX_PER_PAGE
                    ]
                    parent_magazines = od_client.media_bulk(
                        title_ids=parent_magazine_ids
                    )
                    # we re-query with the new title IDs because querying with the parent magazine ID
                    # returns an old estimatedReleaseDate, so if we want to sort by estimatedReleaseDate
                    # we need to re-query
                    titles = od_client.media_bulk(
                        title_ids=[
                            # sometimes t["id"] is not the latest issue (due to misconfig?)
                            # so use t["recentIssues"] instead
                            t["recentIssues"][0]["id"]
                            if t.get("recentIssues")
                            else t["id"]
                            for t in parent_magazines
                        ]
                    )
                    for t in titles:
                        t["cardId"] = next(
                            iter(
                                [
                                    s["card_id"]
                                    for s in subscriptions
                                    if s["parent_magazine_id"]
                                    == t["parentMagazineTitleId"]
                                ]
                            ),
                            None,
                        )
                    subbed_magazines.extend(titles)
                logger.info(
                    "OverDrive Magazines requests took %f seconds" % (timer() - start)
                )
            synced_state["__subscriptions"] = subbed_magazines
            logger.info("Total Sync Time took %f seconds" % (timer() - total_start))

            self.finished.emit(synced_state)
        except Exception as err:
            logger.info("Sync failed after %f seconds" % (timer() - total_start))

            self.errored.emit(err)
