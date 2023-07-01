#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import gzip
import json
import logging
from enum import Enum
from http.client import HTTPException
from http.cookiejar import CookieJar
from io import BytesIO
from socket import timeout as SocketTimeout, error as SocketError
from ssl import SSLError
from typing import Optional, Dict, List, Union, Tuple
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

from .errors import ClientConnectionError, ErrorHandler


class LibbyFormats(str, Enum):
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
    MagazineOverDrive = "magazine-overdrive"

    def __str__(self):
        return str(self.value)


class LibbyMediaTypes(str, Enum):
    """
    Loan type strings
    """

    Audiobook = "audiobook"
    EBook = "ebook"
    Magazine = "magazine"

    def __str__(self):
        return str(self.value)


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
    LibbyFormats.AudioBookMP3,
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
    def get_loan_format(loan: Dict, prefer_open_format: bool = True) -> str:
        locked_in_format = next(
            iter([f["id"] for f in loan["formats"] if f.get("isLockedIn")]), None
        )
        if locked_in_format:
            if locked_in_format in DOWNLOADABLE_FORMATS:
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

        raise ValueError("Unable to find a downloadable format")

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
            endpoint_url += "?" if "?" not in endpoint else "&" + urlencode(query)
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
                self.logger.info(
                    "REQUEST: {0!s} {1!s}".format(req.get_method(), endpoint)
                )
                self.logger.debug(
                    "REQ HEADERS: \n{0!s}".format(
                        "\n".join(
                            ["{}: {}".format(k, v) for k, v in req.headers.items()]
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
        endpoint: str, headers: Optional[Dict] = None, timeout: int = 15
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
        if format_id not in DOWNLOADABLE_FORMATS:
            raise ValueError(f"Unsupported format_id: {format_id}")

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
