#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
import base64
import gzip
import json
import logging
from datetime import datetime, timezone
from http.client import HTTPException
from http.cookiejar import CookieJar
from io import BytesIO
from socket import error as SocketError, timeout as SocketTimeout
from ssl import SSLError
from typing import Dict, List, Optional, Tuple, Union
from urllib import parse, request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .errors import ClientConnectionError, ErrorHandler
from .utils import StringEnum


class LibbyTagTypes(StringEnum):
    """
    Document tag behavior "types". Not currently used.
    """

    Autonomous = "autonomous"  # for sampled, borrowed
    Subscription = "subscription"  # for notifyme
    Coordination = "coordination"  # for wishlist


class LibbyTagBehaviors(StringEnum):
    """
    Document tag "behaviors" keys. Not currently used.
    """

    Borrowed = "borrowed"  # type autonomous
    Sampled = "sampled"  # type autonomous
    NotifyMe = "notify-me"  # type subscription
    WishlistSync = "wish-list-sync"  # type coordination


class LibbyFormats(StringEnum):
    """
    Format strings
    """

    AudioBookMP3 = "audiobook-mp3"
    AudioBookOverDrive = "audiobook-overdrive"  # not used
    EBookEPubAdobe = "ebook-epub-adobe"
    EBookEPubOpen = "ebook-epub-open"
    EBookPDFAdobe = "ebook-pdf-adobe"
    EBookPDFOpen = "ebook-pdf-open"
    EBookKobo = "ebook-kobo"  # not used
    EBookKindle = "ebook-kindle"  # not used
    EBookOverdrive = "ebook-overdrive"
    EBookOverdriveProvisional = "ebook-overdrive-provisional"
    MagazineOverDrive = "magazine-overdrive"


class LibbyMediaTypes(StringEnum):
    """
    Loan type strings
    """

    Audiobook = "audiobook"
    EBook = "ebook"
    Magazine = "magazine"


EBOOK_DOWNLOADABLE_FORMATS = (
    LibbyFormats.EBookEPubAdobe,
    LibbyFormats.EBookEPubOpen,
    LibbyFormats.EBookPDFAdobe,
    LibbyFormats.EBookPDFOpen,
)
DOWNLOADABLE_FORMATS = (
    LibbyFormats.EBookEPubAdobe,
    LibbyFormats.EBookEPubOpen,
    LibbyFormats.EBookPDFAdobe,
    LibbyFormats.EBookPDFOpen,
    LibbyFormats.MagazineOverDrive,
    # LibbyFormats.AudioBookMP3,
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_1) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/14.0.2 Safari/605.1.15"
)


class NoRedirectHandler(request.HTTPRedirectHandler):
    """
    Used by the LibbyClient to have a no-redirect opener for handling open formats
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Original reverse engineering of the libby endpoints is thanks to https://github.com/lullius/pylibby

# this doesn't guarantee that sensitive data will be scrubbed fully
# it's just a best effort attempt
_scrub_sensitive_data = True


class LibbyClient(object):
    def __init__(
        self,
        identity_token: Optional[str] = None,
        max_retries: int = 0,
        timeout: float = 30.0,
        logger: Optional[logging.Logger] = None,
        **kwargs,
    ) -> None:
        if not logger:
            logger = logging.getLogger(__name__)
        self.logger = logger

        self.timeout = timeout
        self.identity_token = identity_token
        self.max_retries = max_retries
        self.user_agent = kwargs.pop("user_agent", USER_AGENT)
        self.api_base = "https://sentry-read.svc.overdrive.com/"

        cookie_jar = CookieJar()
        handlers = [
            HTTPCookieProcessor(cookie_jar),
        ]
        self.opener = build_opener(*handlers)
        self.opener_noredirect = build_opener(NoRedirectHandler)
        self.cookie_jar = cookie_jar

    @staticmethod
    def is_valid_sync_code(code: str) -> bool:
        return code.isdigit() and len(code) == 8

    def default_headers(self) -> Dict:
        """
        Default HTTP headers.

        :return:
        """
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Referer": "https://libbyapp.com/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    @staticmethod
    def is_downloadable_audiobook_loan(book: Dict) -> bool:
        """
        Verify if book is a downloadable audiobook.

        :param book:
        :return:
        """
        return bool(
            [f for f in book.get("formats", []) if f["id"] == LibbyFormats.AudioBookMP3]
        )

    @staticmethod
    def is_downloadable_ebook_loan(book: Dict) -> bool:
        """
        Verify if book is a downloadable ebook.

        :param book:
        :return:
        """
        return bool(
            [
                f
                for f in book.get("formats", [])
                if f["id"] in EBOOK_DOWNLOADABLE_FORMATS
            ]
        )

    @staticmethod
    def is_downloadable_magazine_loan(book: Dict) -> bool:
        """
        Verify if loan is a downloadable magazine.

        :param book:
        :return:
        """
        return bool(
            [
                f
                for f in book.get("formats", [])
                if f["id"] == LibbyFormats.MagazineOverDrive
            ]
        )

    @staticmethod
    def is_open_ebook_loan(book: Dict) -> bool:
        """
        Verify if book is an open epub.

        :param book:
        :return:
        """
        return bool(
            [
                f
                for f in book.get("formats", [])
                if f["id"] == LibbyFormats.EBookEPubOpen
            ]
        )

    @staticmethod
    def has_format(loan: Dict, format_id: str) -> bool:
        return bool(
            next(iter([f["id"] for f in loan["formats"] if f["id"] == format_id]), None)
        )

    @staticmethod
    def get_locked_in_format(loan: Dict):
        return next(
            iter([f["id"] for f in loan["formats"] if f.get("isLockedIn")]), None
        )

    @staticmethod
    def get_loan_format(
        loan: Dict, prefer_open_format: bool = True, raise_if_not_downloadable=True
    ) -> str:
        """

        :param loan:
        :param prefer_open_format:
        :param raise_if_not_downloadable: If True, raise ValueError if format is not a downloadable format
        :return:
        """
        formats = loan.get("formats", [])
        if not formats:
            raise ValueError("No formats found")

        locked_in_format = next(
            iter([f["id"] for f in formats if f.get("isLockedIn")]), None
        )
        if locked_in_format:
            if (
                locked_in_format in DOWNLOADABLE_FORMATS
                or not raise_if_not_downloadable
            ):
                return locked_in_format
            raise ValueError(
                f'Loan is locked to a non-downloadable format "{locked_in_format}"'
            )

        if not locked_in_format:
            # the order of these checks will determine the output format
            # the "open" version of the format (example open epub, open pdf) should
            # be prioritised
            if LibbyClient.is_downloadable_audiobook_loan(
                loan
            ) and LibbyClient.has_format(loan, LibbyFormats.AudioBookMP3):
                return LibbyFormats.AudioBookMP3
            elif (
                LibbyClient.is_open_ebook_loan(loan)
                and LibbyClient.has_format(loan, LibbyFormats.EBookEPubOpen)
                and prefer_open_format
            ):
                return LibbyFormats.EBookEPubOpen
            elif LibbyClient.is_downloadable_magazine_loan(
                loan
            ) and LibbyClient.has_format(loan, LibbyFormats.MagazineOverDrive):
                return LibbyFormats.MagazineOverDrive
            elif LibbyClient.is_downloadable_ebook_loan(
                loan
            ) and LibbyClient.has_format(loan, LibbyFormats.EBookEPubAdobe):
                return LibbyFormats.EBookEPubAdobe
            elif (
                LibbyClient.is_downloadable_ebook_loan(loan)
                and LibbyClient.has_format(loan, LibbyFormats.EBookPDFOpen)
                and prefer_open_format
            ):
                return LibbyFormats.EBookPDFOpen
            elif LibbyClient.is_downloadable_ebook_loan(
                loan
            ) and LibbyClient.has_format(loan, LibbyFormats.EBookPDFAdobe):
                return LibbyFormats.EBookPDFAdobe
            # no epub format available, prioritised in this sequence
            elif LibbyClient.has_format(loan, LibbyFormats.EBookKindle):
                return LibbyFormats.EBookKindle
            elif LibbyClient.has_format(loan, LibbyFormats.EBookOverdrive):
                return LibbyFormats.EBookOverdrive
            elif LibbyClient.has_format(loan, LibbyFormats.EBookOverdriveProvisional):
                return LibbyFormats.EBookOverdriveProvisional
            elif LibbyClient.has_format(loan, LibbyFormats.EBookKobo):
                return LibbyFormats.EBookKobo

        if len(formats) == 1:
            return formats[0]["id"]
        raise ValueError("Unable to find a downloadable format")

    @staticmethod
    def parse_datetime(value: str) -> Optional[datetime]:  # type: ignore[return]
        """
        Parses a datetime string from the API into a datetime.

        :param value:
        :return:
        """
        if not value:
            return None

        formats = (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%m/%d/%Y",  # publishDateText
        )
        for i, fmt in enumerate(formats, start=1):
            try:
                dt = datetime.strptime(value, fmt)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass

        raise ValueError(f"time data '{value}' does not match known formats {formats}")

    @staticmethod
    def is_renewable(loan: Dict) -> bool:
        """
        Check if loan can be renewed.

        :param loan:
        :return:
        """
        if not loan.get("renewableOn"):
            return False
        # Example: 2023-02-23T07:33:55Z
        return LibbyClient.parse_datetime(loan["renewableOn"]) <= datetime.now(
            tz=timezone.utc
        )

    @staticmethod
    def libby_title_permalink(library_key: str, title_id: str) -> str:
        """
        Generates a Libby library permalink for a title.

        :param title_id:
        :param library_key:
        :return:
        """
        return (
            f"https://libbyapp.com/library/{library_key}/everything/page-1/{title_id}"
        )

    @staticmethod
    def libby_title_share_link(title_id: str) -> str:
        """
        Generates a Libby share link for a title.
        :param title_id:
        :return:
        """
        return f"https://share.libbyapp.com/title/{title_id}"

    @staticmethod
    def can_borrow(card):
        """
        Checks if card can be used to make a new loan.

        :param card:
        :return:
        """
        loan_limit = card.get("limits", {}).get("loan", 0)
        loan_count = card.get("counts", {}).get("loan", 0)
        return loan_limit > loan_count

    @staticmethod
    def can_place_hold(card):
        """
        Checks if a card can be used to place a hold.

        :param card:
        :return:
        """
        hold_limit = card.get("limits", {}).get("hold", 0)
        hold_count = card.get("counts", {}).get("hold", 0)
        return hold_limit > hold_count

    def _read_response(self, response, decode: bool = True) -> Union[bytes, str]:
        """
        Extract the response body from a http response.

        :param response:
        :return:
        """
        if response.info().get("Content-Encoding") == "gzip":
            buf = BytesIO(response.read())
            res = gzip.GzipFile(fileobj=buf).read()
        else:
            res = response.read()
        if not decode:
            return res

        decoded_res = res.decode("utf8")
        if _scrub_sensitive_data and self.logger.level == logging.DEBUG:
            try:
                res_obj = json.loads(decoded_res)
                if "identity" in res_obj:
                    res_obj["identity"] = "*" * int(len(res_obj["identity"]) / 10)
                self.logger.debug(
                    "RES BODY: {0:s}".format(json.dumps(res_obj, separators=(",", ":")))
                )
            except:  # noqa
                # do nothing
                pass
        else:
            self.logger.debug("RES BODY: {0:s}".format(decoded_res))
        return decoded_res

    def send_request(
        self,
        endpoint: str,
        query: Optional[Dict] = None,
        params: Union[Dict, str, None] = None,
        method: Optional[str] = None,
        headers: Optional[Dict] = None,
        is_form: bool = True,
        authenticated: bool = True,
        decode_response: bool = True,
        no_redirect: bool = False,
        return_response: bool = False,
    ):
        """
        Calls the private Libby api.

        :param endpoint: Full endpoint url
        :param query: GET url query parameters
        :param params: POST parameters
        :param method: HTTP method name
        :param headers: Request headers
        :param is_form: If True, content-type is set to 'application/x-www-form-urlencoded'
                        and params are urlencoded in the request body.
                        If False, content-type is set to 'application/json'
                        and params are json-encoded in the request body.
        :param authenticated: If True, send bearer token in headers
        :param decode_response: If False, return raw bytes
        :param no_redirect: If True, don't follow redirects
        :param return_response: If True, return the response object
        """
        if not query:
            query = {}
        endpoint_url = urljoin(self.api_base, endpoint)
        if headers is None:
            headers = self.default_headers()
        if authenticated and self.identity_token:
            headers["Authorization"] = f"Bearer {self.identity_token}"
        if query:
            endpoint_url += ("?" if "?" not in endpoint else "&") + urlencode(query)
        if not method:
            # try to set an HTTP method
            if params is None:
                method = "GET"
            else:
                method = "POST"

        data = None
        if params or params == "":
            if is_form:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                headers["Content-Type"] = "application/json; charset=UTF-8"
            if params == "":  # force post if empty string
                data = "".encode("ascii")
            elif is_form:
                data = urlencode(params).encode("ascii")
            else:
                data = json.dumps(params, separators=(",", ":")).encode("ascii")

        req = Request(endpoint_url, data, headers=headers)
        if method:
            req.get_method = (
                lambda: method.upper()  # pylint: disable=unnecessary-lambda
            )

        for attempt in range(0, self.max_retries + 1):
            try:
                self.logger.debug(
                    "REQUEST: {0!s} {1!s}".format(req.get_method(), endpoint_url)
                )
                bearer_token = req.headers.get("Authorization", "")
                if _scrub_sensitive_data and bearer_token:
                    bearer_token = bearer_token[: len("Bearer ")] + "*" * int(
                        len(bearer_token[len("Bearer ") :]) / 10
                    )
                self.logger.debug(
                    "REQ HEADERS: \n{0!s}".format(
                        "\n".join(
                            [
                                "{}: {}".format(
                                    k, v if k != "Authorization" else bearer_token
                                )
                                for k, v in req.headers.items()
                            ]
                        )
                    )
                )
                if data:
                    self.logger.debug("REQ BODY: \n{0!s}".format(data))
                req_opener = self.opener if not no_redirect else self.opener_noredirect
                response = req_opener.open(req, timeout=self.timeout)
            except HTTPError as e:
                if e.code in (301, 302) and no_redirect:
                    response = e
                else:
                    self.logger.debug("RESPONSE: {0:d} {1:s}".format(e.code, e.url))
                    self.logger.debug(
                        "RES HEADERS: \n{0!s}".format(
                            "\n".join(
                                ["{}: {}".format(k, v) for k, v in e.info().items()]
                            )
                        )
                    )
                    error_response = self._read_response(e)
                    if (
                        attempt < self.max_retries and e.code >= 500
                    ):  # retry for server 5XX errors
                        # do nothing, try
                        self.logger.warning(
                            "Retrying due to {}: {}".format(
                                e.__class__.__name__, str(e)
                            )
                        )
                        self.logger.debug(error_response)
                        continue
                    ErrorHandler.process(e, error_response)

            except (
                SSLError,
                SocketTimeout,
                SocketError,
                URLError,  # URLError is base of HTTPError
                HTTPException,
                ConnectionError,
            ) as connection_error:
                if attempt < self.max_retries:
                    self.logger.warning(
                        "Retrying due to {}: {}".format(
                            connection_error.__class__.__name__, str(connection_error)
                        )
                    )
                    # do nothing, try
                    continue
                raise ClientConnectionError(
                    "{} {}".format(
                        connection_error.__class__.__name__, str(connection_error)
                    )
                ) from connection_error

            self.logger.debug(
                "RESPONSE: {0:d} {1:s}".format(response.code, response.url)
            )
            self.logger.debug(
                "RES HEADERS: \n{0!s}".format(
                    "\n".join(
                        ["{}: {}".format(k, v) for k, v in response.info().items()]
                    )
                )
            )
            if return_response:
                return response

            if not decode_response:
                return self._read_response(response, decode_response)

            response_content = self._read_response(response)
            if not response_content.strip():
                return {}

            if response.headers["content-type"].startswith("application/json"):
                res_obj = json.loads(response_content)
                return res_obj

            return response_content

    def get_chip(
        self, update_internal_token: bool = True, authenticated: bool = False
    ) -> Dict:
        """
        Get an identity chip (contains auth token).

        :param update_internal_token:
        :param authenticated:
        :return:
        """
        res: Dict = self.send_request(
            "chip",
            query={"client": "dewey"},
            method="POST",
            authenticated=authenticated,
        )
        if update_internal_token and res.get("identity"):
            self.identity_token = res["identity"]
        return res

    def clone_by_code(self, code: str) -> Dict:
        """
        Link account to identy token retrieved in `get_chip()`.

        :param code:
        :return:
        """
        if not self.is_valid_sync_code(code):
            raise ValueError(f"Invalid code: {code}")

        res: Dict = self.send_request("chip/clone/code", params={"code": code})
        return res

    def generate_clone_code(self):
        """
        Get a clone code for setting up another device

        :return:
        """
        res: Dict = self.send_request("chip/clone/code")
        return res

    def sync(self) -> Dict:
        """
        Get the user account state, which includes loans, holds, etc.

        :return:
        """
        res: Dict = self.send_request("chip/sync")
        return res

    def is_logged_in(self) -> bool:
        """
        Check if successfully logged in.

        :return:
        """
        synced_state = self.sync()
        return synced_state.get("result", "") == "synchronized" and bool(
            synced_state.get("cards")
        )

    def get_loans(self) -> List[Dict]:
        """
        Get loans

        :return:
        """
        return self.sync().get("loans", [])

    def open_loan(self, loan_type: str, card_id: str, title_id: str) -> Dict:
        """
        Gets the meta urls needed to fulfill a loan.

        :param loan_type:
        :param card_id:
        :param title_id:
        :return:
        """
        res: Dict = self.send_request(
            f"open/{loan_type}/card/{card_id}/title/{title_id}"
        )
        return res

    def prepare_loan(self, loan: Dict) -> Tuple[str, Dict]:
        """
        Pre-requisite step for processing a loan.

        :param loan:
        :return:
        """
        loan_type = "book"
        if loan["type"]["id"] == LibbyMediaTypes.Audiobook:
            loan_type = "audiobook"
        if loan["type"]["id"] == LibbyMediaTypes.Magazine:
            loan_type = "magazine"
        card_id = loan["cardId"]
        title_id = loan["id"]
        meta = self.open_loan(loan_type, card_id, title_id)
        download_base: str = meta["urls"]["web"]

        # Sets a needed cookie
        web_url = download_base + "?" + meta["message"]
        _ = self.send_request(
            web_url,
            headers={"Accept": "*/*"},
            method="HEAD",
            authenticated=False,
            return_response=True,
        )
        return download_base, meta

    @staticmethod
    def get_file_extension(format_id: str) -> str:
        file_ext = "odm"
        if format_id in (
            LibbyFormats.EBookEPubAdobe,
            LibbyFormats.EBookEPubOpen,
            LibbyFormats.EBookOverdrive,
            LibbyFormats.MagazineOverDrive,
            LibbyFormats.EBookPDFAdobe,
            LibbyFormats.EBookPDFOpen,
        ):
            file_ext = (
                "acsm"
                if format_id
                in (LibbyFormats.EBookEPubAdobe, LibbyFormats.EBookPDFAdobe)
                else "pdf"
                if format_id == LibbyFormats.EBookPDFOpen
                else "epub"
            )
        return file_ext

    def get_loan_fulfilment_details(
        self, loan_id: str, card_id: str, format_id: str
    ) -> Tuple[str, Dict]:
        """
        Helper method for details needed to use with calibre

        :param loan_id:
        :param card_id:
        :param format_id:
        :return:
        """
        endpoint_url = urljoin(
            self.api_base, f"card/{card_id}/loan/{loan_id}/fulfill/{format_id}"
        )
        headers = self.default_headers()
        headers["Accept"] = "*/*"
        headers["Authorization"] = f"Bearer {self.identity_token}"
        return endpoint_url, headers

    @staticmethod
    def _urlretrieve(
        endpoint: str, headers: Optional[Dict] = None, timeout: float = 15
    ) -> bytes:
        """
        Workaround for downloading an open (non-drm) epub or pdf.

        The fulfillment url 403s when using requests but
        works in curl, request.urlretrieve, etc.

        GET API fulfill endpoint -> 302 https://fulfill.contentreserve.com (fulfillment url)
        GET https://fulfill.contentreserve.com -> 302 https://openepub-gk.cdn.overdrive.com
        GET https://openepub-gk.cdn.overdrive.com 403

        Fresh session doesn't work either, headers doesn't seem to
        matter.

        .. code-block:: python
            sess = requests.Session()
            sess.headers.update({"User-Agent": USER_AGENT})
            res = sess.get(res_redirect.headers["Location"], timeout=self.timeout)
            res.raise_for_status()
            return res.content

        :param endpoint: fulfillment url
        :param headers:
        :param timeout:
        :return:
        """
        if not headers:
            headers = {}

        opener = request.build_opener()
        req = request.Request(endpoint, headers=headers)
        res = opener.open(req, timeout=timeout)
        return res.read()

    def fulfill_loan_file(self, loan_id: str, card_id: str, format_id: str) -> bytes:
        """
        Returns the loan file contents directly for MP3 audiobooks (.odm)
        and DRM epub (.acsm) loans.
        For open epub/pdf loans, the actual epub/pdf contents are returned.

        :param loan_id:
        :param card_id:
        :param format_id:
        :return:
        """
        if format_id not in DOWNLOADABLE_FORMATS + (LibbyFormats.EBookKindle,):
            raise ValueError(f"Unsupported format_id: {format_id}")

        if format_id == LibbyFormats.EBookKindle:
            # used to get the Read with Kindle redirect link
            return self.send_request(
                f"card/{card_id}/loan/{loan_id}/fulfill/{format_id}"
            )

        headers = self.default_headers()
        headers["Accept"] = "*/*"

        if format_id in (LibbyFormats.EBookEPubOpen, LibbyFormats.EBookPDFOpen):
            res_redirect = self.send_request(
                f"card/{card_id}/loan/{loan_id}/fulfill/{format_id}",
                headers=headers,
                no_redirect=True,
                return_response=True,
            )
            return self._urlretrieve(
                res_redirect.info()["Location"], headers=headers, timeout=self.timeout
            )

        res: bytes = self.send_request(
            f"card/{card_id}/loan/{loan_id}/fulfill/{format_id}",
            headers=headers,
            decode_response=False,
        )
        return res

    def process_ebook(self, loan: Dict) -> Tuple[str, Dict, List[Dict]]:
        """
        Returns the data needed to download an ebook/magazine directly.

        :param loan:
        :return:
        """
        download_base, meta = self.prepare_loan(loan)
        # contains nav/toc and spine, manifest
        openbook = self.send_request(meta["urls"]["openbook"])
        rosters: List[Dict] = self.send_request(meta["urls"]["rosters"])
        return download_base, openbook, rosters

    def return_title(self, title_id: str, card_id: str) -> None:
        """
        Return a title.

        :param title_id:
        :param card_id:
        :return:
        """
        self.send_request(
            f"card/{card_id}/loan/{title_id}", method="DELETE", return_response=True
        )

    def return_loan(self, loan: Dict) -> None:
        """
        Return a loan.

        :param loan:
        :return:
        """
        self.return_title(loan["id"], loan["cardId"])

    def cancel_hold_title(self, title_id: str, card_id: str) -> None:
        """
        Cancel a hold by title and card.

        :param title_id:
        :param card_id:
        :return:
        """
        self.send_request(
            f"card/{card_id}/hold/{title_id}", method="DELETE", return_response=True
        )

    def cancel_hold(self, hold: Dict) -> None:
        """
        Cancel a hold.

        :param hold:
        :return:
        """
        self.cancel_hold_title(hold["id"], hold["cardId"])

    def borrow_title(
        self,
        title_id: str,
        title_format: str,
        card_id: str,
        days: int = 21,
        is_lucky_day_loan: bool = False,
    ) -> Dict:
        """
        Return a title.

        :param title_id:
        :param title_format: Type ID
        :param card_id:
        :param days:
        :param is_lucky_day_loan:
        :return:
        """
        if days <= 0:
            raise ValueError("days cannot be %d" % days)
        data = {
            "period": days,
            "units": "days",
            "lucky_day": 1 if is_lucky_day_loan else None,
            "title_format": title_format,
        }

        res: Dict = self.send_request(
            f"card/{card_id}/loan/{title_id}", params=data, is_form=False, method="POST"
        )
        return res

    def borrow_media(
        self, media: Dict, card: Optional[Dict] = None, is_lucky_day_loan: bool = False
    ) -> Dict:
        """
        Borrow a media (or hold).

        :param card:
        :param media:
        :param is_lucky_day_loan:
        :return:
        """
        if card:
            # map ebook -> book
            lending_period_type = {"ebook": "book"}.get(media["type"]["id"]) or media[
                "type"
            ]["id"]
            lending_period = card.get("lendingPeriods", {}).get(lending_period_type, {})
            days = lending_period.get("preference", [0, "days"])[0]
            if not days:
                days = lending_period.get("options", [[0, "days"]])[-1][0]
            return self.borrow_title(
                media["id"],
                media["type"]["id"],
                media["cardId"],
                days=days,
                is_lucky_day_loan=is_lucky_day_loan,
            )
        return self.borrow_title(
            media["id"],
            media["type"]["id"],
            media["cardId"],
            is_lucky_day_loan=is_lucky_day_loan,
        )

    def suspend_hold_title(self, card_id, title_id, days_to_suspend: int = 7, **kwargs):
        """
        Suspend a hold for X days.
        If a hold is actually available, this sets the hold to be delivered after X days.

        :param card_id:
        :param title_id:
        :param days_to_suspend:
        :param kwargs:
        :return:
        """
        valid_days = (0 <= days_to_suspend <= 30) or days_to_suspend in (60, 90)
        if not valid_days:
            raise ValueError()
        params = {"days_to_suspend": days_to_suspend}
        params.update(kwargs)
        return self.send_request(
            f"card/{card_id}/hold/{title_id}",
            params=params,
            method="PUT",
            is_form=False,
        )

    def unsuspend_hold(self, hold):
        """
        Unsuspend a hold.

        :param hold:
        :return:
        """
        return self.suspend_hold_title(hold["cardId"], hold["id"], 0)

    def suspend_hold(self, hold, days_to_suspend: int = 7) -> Dict:
        """
        Suspend a hold.

        :param hold:
        :param days_to_suspend:
        :return:
        """
        return self.suspend_hold_title(hold["cardId"], hold["id"], days_to_suspend)

    def create_hold(self, title_id: str, card_id: str) -> Dict:
        """
        Create a hold on the title.

        :param title_id:
        :param card_id:
        :return:
        """
        return self.send_request(
            f"card/{card_id}/hold/{title_id}",
            params={"days_to_suspend": 0, "email_address": ""},
            method="POST",
            is_form=False,
        )

    def renew_title(
        self, title_id: str, title_format: str, card_id: str, days: int = 21
    ) -> Dict:
        """
        Return a title.

        :param title_id:
        :param title_format: Type ID
        :param card_id:
        :param days:
        :return:
        """
        data = {
            "period": days,
            "units": "days",
            "lucky_day": None,
            "title_format": title_format,
        }

        res: Dict = self.send_request(
            f"card/{card_id}/loan/{title_id}", params=data, is_form=False, method="PUT"
        )
        return res

    def renew_loan(self, loan: Dict) -> Dict:
        """
        Renew a loan.

        :param loan:
        :return:
        """
        return self.renew_title(loan["id"], loan["type"]["id"], loan["cardId"])

    def auth_form(self, website_id: str) -> Dict:
        """
        Returns the details of the auth form required for card verification.
        Multiple forms may be returned. Use "ilsName" to pick the correct form.

        :param website_id: From card["library"]["websiteId"]
        :return:
        """
        res: Dict = self.send_request(f"auth/forms/{website_id}")
        return res

    def verify_card(
        self, website_id: str, ils: str, username: str, password: Optional[str]
    ) -> Dict:
        """
        Verify a card.

        :param website_id:
        :param ils:
        :param username:
        :param password:
        :return:
        """
        data = {"ils": ils, "username": username}
        if password:
            data["password"] = password

        res: Dict = self.send_request(
            f"auth/link/{website_id}", params=data, is_form=False, method="POST"
        )
        return res

    def tags(self) -> Dict:
        """
        Get user tags.

        :return:
        """
        res: Dict = self.send_request("https://vandal.svc.overdrive.com/tags")
        return res

    def tag(
        self,
        tag_id: str,
        tag_name: str,
        paging_range: Tuple[int, int] = (0, 12),
        **kwargs,
    ) -> Dict:
        """
        Details of a tag, including titles ("taggings").

        :param tag_id: UUID string
        :param tag_name: string
        :param paging_range: tuple(start, end) for paging titles ("taggings"). 0-indexed. Defaults to a page size of 12.
        :param: kwargs:
                - sort: "newest", "oldest", "author", "title"
        :return:
        """
        query = {
            "enc": "1",  # ??
            "sort": "newest",  # oldest / author / title
            "range": f"{paging_range[0]}...{paging_range[1]}",
        }
        if kwargs:
            query.update(kwargs)
        b64encoded_tag_name = base64.b64encode(tag_name.encode("utf-8")).decode("ascii")
        res: Dict = self.send_request(
            f"https://vandal.svc.overdrive.com/tag/{tag_id}/{b64encoded_tag_name}",
            query=query,
        )
        return res

    def tag_paged(
        self, tag_id: str, tag_name: str, page: int = 0, per_page: int = 12, **kwargs
    ) -> Dict:
        """
        Helper method to get details of a tag with more standardised paging parameters

        :param tag_id:
        :param tag_name:
        :param page: 0-indexed. For paging titles ("taggings").
        :param per_page: Default 12. Does not appear to be constrained. Tested up to 400.
        :param: kwargs:
                - sort: "newest", "oldest", "author", "title"
        :return:
        """
        paging_range = (page * per_page, (page + 1) * per_page)
        return self.tag(tag_id, tag_name, paging_range, **kwargs)

    def taggings(self, title_ids: List[str]) -> Dict:
        """
        Get tagging information for title IDs

        :param title_ids:
        :return:
        """
        res: Dict = self.send_request(
            f'https://vandal.svc.overdrive.com/taggings/{parse.quote(",".join(title_ids))}'
        )
        return res
