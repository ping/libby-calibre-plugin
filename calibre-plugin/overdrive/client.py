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
from socket import timeout as SocketTimeout, error as SocketError
from ssl import SSLError
from typing import Optional, Dict, List, Union, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlencode
from urllib.request import Request, build_opener

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

    def default_query(self) -> Dict:
        """
        Default set of GET request parameters.

        :return:
        """
        return {"x-client-id": CLIENT_ID}

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
