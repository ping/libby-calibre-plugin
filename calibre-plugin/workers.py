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
from typing import Dict, List, Tuple

from calibre import browser
from qt.core import QObject, pyqtSignal

from . import logger
from .config import PREFS, PreferenceKeys
from .libby import LibbyClient, LibbyFormats
from .overdrive import OverDriveClient, LibraryMediaSearchParams
from .utils import SimpleCache


class OverDriveMediaSearchWorker(QObject):
    """
    Search media
    """

    finished = pyqtSignal(list)
    errored = pyqtSignal(Exception)

    def setup(
        self,
        overdrive_client: OverDriveClient,
        query: str,
        library_keys: List[str],
        formats: List[LibbyFormats],
        max_items: int = 20,
    ):
        self.client = overdrive_client
        self.query = query
        self.library_keys = library_keys
        self.formats = formats
        self.max_items = max_items

    def run(self):
        total_start = timer()
        try:
            results = self.client.media_search(
                self.library_keys,
                self.query,
                maxItems=self.max_items,
                format=self.formats,
            )
            logger.info(
                "OverDrive Media Search took %f seconds" % (timer() - total_start)
            )
            self.finished.emit(results)
        except Exception as err:
            logger.info(
                "OverDrive Media Search failed after %f seconds"
                % (timer() - total_start)
            )
            self.errored.emit(err)


class OverDriveLibraryMediaSearchWorker(QObject):
    """
    Search library media
    """

    finished = pyqtSignal(str, dict)
    errored = pyqtSignal(str, Exception)

    def setup(
        self,
        overdrive_client: OverDriveClient,
        library_key: str,
        query: LibraryMediaSearchParams,
    ):
        self.client = overdrive_client
        self.library_key = library_key
        self.query = query

    def run(self):
        total_start = timer()
        try:
            results = self.client.library_medias(self.library_key, self.query)
            logger.info(
                "OverDrive Library Media Search (%s) took %f seconds"
                % (self.library_key, timer() - total_start)
            )
            self.finished.emit(self.library_key, results)
        except Exception as err:
            logger.info(
                "OverDrive Library Media Search (%s) failed after %f seconds"
                % (self.library_key, timer() - total_start)
            )
            self.errored.emit(self.library_key, err)


class OverDriveMediaWorker(QObject):
    """
    Fetches a media detail (for preview)
    """

    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)
    cover_data_key = "_cover_data"

    def setup(
        self, overdrive_client: OverDriveClient, title_id: str, media_cache: SimpleCache
    ):
        self.client = overdrive_client
        self.title_id = title_id
        self.media_cache = media_cache

    def run(self):
        total_start = timer()
        try:
            media = self.media_cache.get(self.title_id) or self.client.media(
                self.title_id
            )
            if not media.get(self.cover_data_key):
                try:
                    cover_url = OverDriveClient.get_best_cover_url(
                        media, rank=0 if PREFS[PreferenceKeys.USE_BEST_COVER] else -1
                    )
                    if cover_url:
                        logger.debug(f"Downloading cover: {cover_url}")
                        br = browser()
                        cover_res = br.open_novisit(
                            cover_url, timeout=self.client.timeout
                        )
                        media[self.cover_data_key] = cover_res.read()
                except Exception as cover_err:
                    logger.warning(f"Error loading cover: {cover_err}")
            self.media_cache.put(self.title_id, media)
            logger.info(
                "OverDrive Media Fetch took %f seconds" % (timer() - total_start)
            )
            self.finished.emit(media)
        except Exception as err:
            logger.info(
                "OverDrive Media Fetch failed after %f seconds"
                % (timer() - total_start)
            )
            self.errored.emit(err)


class OverDriveLibraryMediaWorker(QObject):
    """
    Fetches a library's media detail (for Magazines tab)
    """

    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def setup(self, overdrive_client: OverDriveClient, card: Dict, title_id: str):
        self.client = overdrive_client
        self.card = card
        self.title_id = title_id

    def run(self):
        total_start = timer()
        try:
            media = self.client.library_media(self.card["advantageKey"], self.title_id)
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


class LibbyAuthFormWorker(QObject):
    """
    Fetches the auth form details for a library
    """

    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def setup(self, libby_client: LibbyClient, card: Dict):
        self.client = libby_client
        self.card = card

    def run(self):
        total_start = timer()
        try:
            ils_name = self.card["ilsName"]
            res = self.client.auth_form(self.card["library"]["websiteId"])
            form: Dict = next(
                iter(
                    [
                        f
                        for f in res.get("forms", [])
                        if f["ilsName"] == ils_name and f["type"] == "Local"
                    ]
                ),
                {},
            )
            logger.info(
                "Total Libby Auth Form Fetch took %f seconds" % (timer() - total_start)
            )
            self.finished.emit(form)
        except Exception as err:
            logger.info(
                "Libby Auth Form Fetch failed after %f seconds"
                % (timer() - total_start)
            )
            self.errored.emit(err)


class LibbyVerifyCardWorker(QObject):
    """
    Verifies a card
    """

    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def setup(
        self, libby_client: LibbyClient, card: Dict, username: str, password: str
    ):
        self.client = libby_client
        self.card = card
        self.username = username
        self.password = password

    def run(self):
        total_start = timer()
        try:
            ils_name = self.card["ilsName"]
            res = self.client.verify_card(
                self.card["library"]["websiteId"],
                ils_name,
                self.username,
                self.password,
            )
            updated_card: Dict = next(
                iter(
                    [
                        card
                        for card in res.get("cards", [])
                        if card["cardId"] == self.card["cardId"]
                    ]
                ),
                {},
            )
            logger.info(
                "Total Libby Verify Card took %f seconds" % (timer() - total_start)
            )
            self.finished.emit(updated_card)
            self.finished.emit(self.card)
        except Exception as err:
            logger.info(
                "Libby Libby Verify Card failed after %f seconds"
                % (timer() - total_start)
            )
            self.errored.emit(err)


class LibbyFulfillLoanWorker(QObject):
    """
    Fetches loan fulfilment detail for a Kindle loan
    """

    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def setup(self, libby_client: LibbyClient, loan: Dict, format_id: str):
        self.client = libby_client
        self.loan = loan
        self.format_id = format_id

    def run(self):
        total_start = timer()
        try:
            fulfilment_details = self.client.fulfill_loan_file(
                self.loan["id"], self.loan["cardId"], self.format_id
            )
            logger.info(
                "Total Libby Fulfilment Details Fetch took %f seconds"
                % (timer() - total_start)
            )
            self.finished.emit(fulfilment_details)
        except Exception as err:
            logger.info(
                "Libby Fulfilment Details Fetch failed after %f seconds"
                % (timer() - total_start)
            )
            self.errored.emit(err)


def extract_cached_items(
    object_ids: List[str], cache: SimpleCache
) -> Tuple[List[str], List[Dict]]:
    """
    Helper method to extract uncached IDs and cached objects
    for a list of object IDs.

    :param object_ids:
    :param cache:
    :return:
    """
    uncached_object_ids: List[str] = []
    cached_objects: List[dict] = []
    for object_id in object_ids:
        cached_obj = cache.get(object_id)
        if cached_obj:
            cached_objects.append(cached_obj)
        else:
            uncached_object_ids.append(object_id)

    return uncached_object_ids, cached_objects


class SyncDataWorker(QObject):
    """
    Main sync worker
    """

    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def __int__(self):
        super().__init__()

    def setup(self, libraries_cache: SimpleCache, media_cache: SimpleCache):
        self.libraries_cache = libraries_cache
        self.media_cache = media_cache

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
                identity_token=libby_token,
                max_retries=PREFS[PreferenceKeys.NETWORK_RETRY],
                timeout=PREFS[PreferenceKeys.NETWORK_TIMEOUT],
                logger=logger,
            )
            synced_state = libby_client.sync()
            logger.info("Libby Sync request took %f seconds" % (timer() - start))

            # Fetch libraries details from OD and patch it onto synced state
            start = timer()
            cards = synced_state.get("cards", [])
            all_website_ids = [str(c["library"]["websiteId"]) for c in cards]
            uncached_website_ids, libraries = extract_cached_items(
                all_website_ids, self.libraries_cache
            )
            logger.debug("Reusing %d cached libraries" % len(libraries))
            logger.debug("Fetching %d new libraries" % len(uncached_website_ids))
            od_client = OverDriveClient(
                max_retries=PREFS[PreferenceKeys.NETWORK_RETRY],
                timeout=PREFS[PreferenceKeys.NETWORK_TIMEOUT],
                logger=logger,
            )
            max_per_page = 24
            total_pages = math.ceil(len(uncached_website_ids) / max_per_page)
            for page in range(1, 1 + total_pages):
                website_ids = uncached_website_ids[
                    (page - 1) * max_per_page : page * max_per_page
                ]
                results = od_client.libraries(
                    website_ids=website_ids, per_page=max_per_page
                )
                found = results.get("items", [])
                for library in found:
                    self.libraries_cache.put(str(library["websiteId"]), library)
                libraries.extend(found)
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
                    # don't cache parent magazine IDs, only the latest issues
                    # to make sure that we'll always have the correct latest issue
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
                    latest_magazine_ids = [
                        # sometimes t["id"] is not the latest issue (due to misconfig?)
                        # so use t["recentIssues"] instead
                        t["recentIssues"][0]["id"] if t.get("recentIssues") else t["id"]
                        for t in parent_magazines
                    ]
                    uncached_latest_magazine_ids, titles = extract_cached_items(
                        latest_magazine_ids, self.media_cache
                    )
                    logger.debug("Reusing %d cached media" % len(titles))
                    logger.debug(
                        "Fetching %d new media" % len(uncached_latest_magazine_ids)
                    )
                    if uncached_latest_magazine_ids:
                        found = od_client.media_bulk(
                            title_ids=uncached_latest_magazine_ids
                        )
                        for m in found:
                            self.media_cache.put(m["id"], m)
                        titles.extend(found)
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
