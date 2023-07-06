import math
from timeit import default_timer as timer

# noinspection PyUnresolvedReferences
from qt.core import QObject, pyqtSignal

from . import logger
from .config import PREFS, PreferenceKeys
from .libby import LibbyClient
from .overdrive import OverDriveClient


class SyncDataWorker(QObject):
    finished = pyqtSignal(dict)
    errored = pyqtSignal(Exception)

    def __int__(self):
        super().__init__()

    def run(self):
        libby_token: str = PREFS[PreferenceKeys.LIBBY_TOKEN]
        if not libby_token:
            self.finished.emit([])

        try:
            # Fetch libby sync state
            start = timer()
            libby_client = LibbyClient(
                identity_token=libby_token, max_retries=1, timeout=30, logger=logger
            )
            synced_state = libby_client.sync()
            logger.info("Libby request took %f seconds" % (timer() - start))

            # Fetch libraries details from OD and patch it onto synced state
            start = timer()
            cards = synced_state.get("cards", [])
            all_website_ids = [c["library"]["websiteId"] for c in cards]
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
            logger.info("OverDrive request took %f seconds" % (timer() - start))
            synced_state["__libraries"] = libraries

            self.finished.emit(synced_state)
        except Exception as err:
            self.errored.emit(err)
