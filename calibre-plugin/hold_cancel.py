from typing import Dict

from .libby import LibbyClient
from .model import get_loan_title

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
        logger = log
        notifications.put((0.5, _("Cancelling")))
        libby_client.cancel_hold(hold)
        logger.info("Cancelled hold for %s successfully." % get_loan_title(hold))
