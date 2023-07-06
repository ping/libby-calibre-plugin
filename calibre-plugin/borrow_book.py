from typing import Dict

from .libby import LibbyClient
from .model import get_loan_title


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
        notifications.put((0.5, "Borrowing"))
        libby_client.borrow_hold(hold, card)
        logger.info(
            "Borrowed %s successfully from %s."
            % (get_loan_title(hold), card["advantageKey"])
        )
