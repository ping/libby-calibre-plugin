from typing import Dict

from .libby import LibbyClient
from .model import get_loan_title

load_translations()


class LibbyLoanReturn:
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        loan: Dict,
        log=None,
        abort=None,
        notifications=None,
    ):
        logger = log
        notifications.put((0.5, _("Returning")))
        libby_client.return_loan(loan)
        logger.info("Returned %s successfully." % get_loan_title(loan))
