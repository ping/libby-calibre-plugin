from timeit import default_timer as timer

# noinspection PyUnresolvedReferences
from qt.core import QObject, pyqtSignal

from . import logger
from .config import PREFS, PreferenceKeys
from .libby import LibbyClient


class LoanDataWorker(QObject):
    finished = pyqtSignal(dict)

    def __int__(self):
        super().__init__()

    def run(self):
        libby_token = PREFS[PreferenceKeys.LIBBY_TOKEN]
        if not libby_token:
            self.finished.emit([])

        start = timer()
        client = LibbyClient(
            identity_token=libby_token, max_retries=1, timeout=30, logger=logger
        )
        synced_state = client.sync()
        logger.info("Request took %f seconds" % (timer() - start))
        self.finished.emit(synced_state)
