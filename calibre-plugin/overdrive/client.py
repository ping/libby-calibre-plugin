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
from http.client import HTTPException
from io import BytesIO
from socket import error as SocketError, timeout as SocketTimeout
from ssl import SSLError
from typing import Dict, List, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, build_opener

from .common import pageable
from .errors import ClientConnectionError

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_1) AppleWebKit/605.1.15 (KHTML, like Gecko) "  # noqa
    "Version/14.0.2 Safari/605.1.15"
)
SITE_URL = "https://libbyapp.com"
THUNDER_API_URL = "https://thunder.api.overdrive.com/v2/"
CLIENT_ID = "dewey"


class OverDriveClient(object):
    """
    A really simplified OverDrive Thunder API client
    """

    MAX_PER_PAGE = 24

    def __init__(
        self,
        max_retries: int = 0,
        timeout: float = 30.0,
        logger: Optional[logging.Logger] = None,
        **kwargs,
    ) -> None:
        if not logger:
            logger = logging.getLogger(__name__)
        self.logger = logger

        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = kwargs.pop("user_agent", USER_AGENT)
        self.api_base = THUNDER_API_URL
        self.opener = build_opener()

    def default_headers(self) -> Dict:
        """
        Default http request headers.

        :return:
        """
        headers = {
            "User-Agent": self.user_agent,
            "Referer": SITE_URL + "/",
            "Origin": SITE_URL,
            "Accept-Encoding": "gzip",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        return headers

    def default_query(self, paging: bool = False) -> Dict:
        """
        Default set of GET request parameters.

        :return:
        """
        query = {"x-client-id": CLIENT_ID}
        if paging:
            query.update({"page": 1, "perPage": self.MAX_PER_PAGE})  # type: ignore[dict-item]
        return query

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
        decode_response: bool = True,
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
        :param decode_response: If False, return raw bytes
        """
        if not query:
            query = {}
        endpoint_url = urljoin(self.api_base, endpoint)
        if headers is None:
            headers = self.default_headers()
        if query:
            endpoint_url += ("?" if "?" not in endpoint else "&") + urlencode(
                query, doseq=True
            )
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
                self.logger.debug(
                    "REQ HEADERS: \n{0!s}".format(
                        "\n".join(
                            ["{}: {}".format(k, v) for k, v in req.headers.items()]
                        )
                    )
                )
                if data:
                    self.logger.debug("REQ BODY: \n{0!s}".format(data))
                response = self.opener.open(req, timeout=self.timeout)
            except HTTPError as e:
                self.logger.debug("RESPONSE: {0:d} {1:s}".format(e.code, e.url))
                self.logger.debug(
                    "RES HEADERS: \n{0!s}".format(
                        "\n".join(["{}: {}".format(k, v) for k, v in e.info().items()])
                    )
                )
                if (
                    attempt < self.max_retries and e.code >= 500
                ):  # retry for server 5XX errors
                    # do nothing, try
                    self.logger.warning(
                        "Retrying due to {}: {}".format(e.__class__.__name__, str(e))
                    )
                    self.logger.debug(self._read_response(e))
                    continue
                raise

            except (
                SSLError,
                SocketTimeout,
                SocketError,
                URLError,  # URLError is base of HTTPError
                HTTPException,
                ConnectionError,
            ) as connection_error:
                if attempt < self.max_retries:
                    # do nothing, try
                    self.logger.warning(
                        "Retrying due to {}: {}".format(
                            connection_error.__class__.__name__, str(connection_error)
                        )
                    )
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
            if not decode_response:
                return self._read_response(response, decode_response)

            response_content = self._read_response(response)
            if not response_content.strip():
                return {}

            if response.headers["content-type"].startswith("application/json"):
                res_obj = json.loads(response_content)
                return res_obj

            return response_content

    @staticmethod
    def library_title_permalink(library_key: str, title_id: str) -> str:
        """
        Generates an OverDrive library permalink for a title.

        :param title_id:
        :param library_key:
        :return:
        """
        return f"https://{library_key}.overdrive.com/media/{title_id}"

    @staticmethod
    def get_best_cover_url(media: Dict) -> Optional[str]:
        """
        Extracts the highest resolution cover image for the media

        :param media:
        :return:
        """
        covers: List[Dict] = sorted(
            list(media.get("covers", []).values()),
            key=lambda c: c.get("width", 0),
            reverse=True,
        )
        cover_highest_res: Optional[Dict] = next(iter(covers), None)
        return cover_highest_res["href"] if cover_highest_res else None

    @staticmethod
    def extract_asin(formats: List[Dict]) -> str:
        """
        Extract Amazon's ASIN from media_info["formats"]

        :param formats:
        :return:
        """
        for media_format in [
            f
            for f in formats
            if [i for i in f.get("identifiers", []) if i["type"] == "ASIN"]
        ]:
            asin = next(
                iter(
                    [
                        identifier["value"]
                        for identifier in media_format.get("identifiers", [])
                        if identifier["type"] == "ASIN"
                    ]
                ),
                "",
            )
            if asin:
                return asin
        return ""

    @staticmethod
    def extract_isbn(formats: List[Dict], format_types: List[str]) -> str:
        """
        Extract ISBN from media_info["formats"]

        :param formats:
        :param format_types:
        :return:
        """
        # a format can contain 2 different "ISBN"s.. one type "ISBN", and another "LibraryISBN"
        # in format["identifiers"]
        # format["isbn"] reflects the "LibraryISBN" value

        if not format_types:
            # use any
            format_types = [f["id"] for f in formats]
        isbn = next(
            iter(
                [
                    f["isbn"]
                    for f in formats
                    if f.get("isbn") and f["id"] in format_types
                ]
            ),
            "",
        )
        if isbn:
            return isbn

        for isbn_type in ("LibraryISBN", "ISBN"):
            for media_format in [
                f
                for f in formats
                if f["id"] in format_types
                and [i for i in f.get("identifiers", []) if i["type"] == isbn_type]
            ]:
                isbn = next(
                    iter(
                        [
                            identifier["value"]
                            for identifier in media_format.get("identifiers", [])
                            if identifier["type"] == isbn_type
                        ]
                    ),
                    "",
                )
                if isbn:
                    return isbn

        return ""

    def media(self, title_id: str, **kwargs) -> Dict:
        """
        Retrieve a title.
        Title id can also be a reserve id.

        :param title_id: A unique id that identifies the content.
        :return:
        """
        params = self.default_query()
        params.update(kwargs)
        return self.send_request(f"media/{title_id}", query=params)

    def media_bulk(self, title_ids: List[str], **kwargs) -> List[dict]:
        """
        Retrieve a list of titles.

        :param title_ids: The ids passed in this request can be titleIds or reserveIds.
        :return:
        """
        params = self.default_query()
        params.update({"titleIds": ",".join(title_ids)})
        params.update(kwargs)
        return self.send_request("media/bulk", query=params)

    @pageable
    def libraries(self, website_ids: Optional[List[int]] = None, **kwargs) -> dict:
        """
        Get a list of libraries.

        :param website_ids: Comma-separated list of website IDs to get the information for. Max 24 items.
        :param kwargs:
            - websiteId: A unique id that identifies the library
            - libraryKeys: Comma-separated list of library keys to get the information for.
            - perPage: The number of items to return per page, up to a max of 100 (defaults to 24)
            - page: The current page being requested (defaults to 1)
        :return:
        """
        params = self.default_query(paging=True)
        if website_ids:
            params["websiteIds"] = ",".join(
                [str(website_id) for website_id in website_ids]
            )
        params.update(kwargs)
        return self.send_request("libraries/", query=params)

    def library_media(self, library_key: str, title_id: str, **kwargs) -> dict:
        """
        Get title.

        :param library_key: A unique key that identifies the library
        :param title_id:
        :return:
        """
        params = self.default_query()
        params.update({"titleIds": title_id})
        params.update(kwargs)
        return self.send_request(
            f"libraries/{library_key}/media/{title_id}", query=params
        )

    @staticmethod
    def sort_availabilities(a, b):
        for key, default, fn in [
            ("isAvailable", False, None),
            ("luckyDayAvailableCopies", 0, None),
            ("estimatedWaitDays", 9999, lambda v: -1 * v),
            ("holdsRatio", 9999, lambda v: -1 * v),
            ("ownedCopies", 0, None),
        ]:
            value_a = a.get(key, default)
            value_b = b.get(key, default)
            if fn:
                value_a = fn(value_a)
                value_b = fn(value_b)
            if value_a > value_b:
                return 1
            if value_a < value_b:
                return -1
        return 0

    def media_search(self, library_keys: List[str], query: str, **kwargs) -> List[dict]:
        """
        Search multiple libraries for a query.

        :param library_keys: Search library key
        :param query:
        :param kwargs:
            - maxItems: int
            - format: List[str]
            - showOnlyAvailable: true/false
        :return:
        """
        params = self.default_query()
        params.update({"libraryKey": library_keys, "query": query})
        params.update(kwargs)
        return self.send_request("media/search/", query=params)
