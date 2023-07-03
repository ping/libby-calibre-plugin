from typing import Dict

from .libby import LibbyClient


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
        notifications.put((0.5, "Returning"))
        libby_client.return_loan(loan)
