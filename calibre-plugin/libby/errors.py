#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import json
from http import HTTPStatus
from typing import List
from urllib.error import HTTPError


class ClientError(Exception):
    """Generic error class, catch-all for most client issues."""

    def __init__(
        self,
        msg: str,
        http_status: int = 0,
        error_response: str = "",
    ):
        self.http_status = http_status or 0
        self.error_response = error_response
        try:
            self.error_response_obj = json.loads(self.error_response)
        except ValueError:
            self.error_response_obj = {}
        super().__init__(msg)

    @property
    def msg(self):
        return self.args[0]

    def __str__(self):
        return (
            f"<{type(self).__module__}.{type(self).__name__}; http_status={self.http_status}, "
            f"msg='{self.msg}', error_response='{self.error_response}''>"
        )


class ClientConnectionError(ClientError):
    """Connection error"""

    pass


class ClientBadRequestError(ClientError):
    """Raised when an HTTP 401, or upstream_failure is received."""

    pass


class ClientUnauthorisedError(ClientError):
    """Raised when an HTTP 401 response is received."""

    pass


class ClientForbiddenError(ClientError):
    """Raised when an HTTP 403 response is received."""

    pass


class ClientNotFoundError(ClientError):
    """Raised when an HTTP 404 response is received."""

    pass


class ClientThrottledError(ClientError):
    """Raised when an HTTP 429 response is received."""

    pass


class InternalServerError(ClientError):
    """Raised when an HTTP 500 response is received."""

    pass


class ErrorHandler(object):
    ERRORS_MAP: List[dict] = [
        # Generic errors based on HTTP status code
        {"code": [HTTPStatus.BAD_REQUEST], "error": ClientBadRequestError},  # 400
        {"code": [HTTPStatus.UNAUTHORIZED], "error": ClientUnauthorisedError},  # 401
        {"code": [HTTPStatus.FORBIDDEN], "error": ClientForbiddenError},  # 403
        {"code": [HTTPStatus.NOT_FOUND], "error": ClientNotFoundError},  # 404
        {"code": [HTTPStatus.TOO_MANY_REQUESTS], "error": ClientThrottledError},  # 429
        {
            "code": [HTTPStatus.INTERNAL_SERVER_ERROR],
            "error": InternalServerError,
        },  # 500
    ]

    @staticmethod
    def process(http_err: HTTPError, error_response: str):
        """
        Try to process an HTTP error from the api appropriately.

        :param http_err:
        :param error_response:
        :raises ClientError:
        :return:
        """
        # json response
        if http_err.headers.get("content-type").startswith("application/json"):
            error = json.loads(error_response)
            if error.get("result", "") == "upstream_failure":
                upstream = error.get("upstream", {})
                if upstream:
                    raise ClientBadRequestError(
                        msg=f'{upstream.get("userExplanation", "")} [errorcode: {upstream.get("errorCode", "")}]',
                        http_status=http_err.code,
                        error_response=error_response,
                    ) from http_err

                raise ClientBadRequestError(
                    msg=str(http_err),
                    http_status=http_err.code,
                    error_response=error_response,
                ) from http_err

            elif error.get("result", "") == "not_found":
                raise ClientNotFoundError(
                    msg=str(http_err),
                    http_status=http_err.code,
                    error_response=error_response,
                )

        for error_info in ErrorHandler.ERRORS_MAP:
            if http_err.code in error_info["code"]:
                raise error_info["error"](
                    msg=str(http_err),
                    http_status=http_err.code,
                    error_response=error_response,
                ) from http_err

        # final fallback
        raise ClientError(
            msg=str(http_err),
            http_status=http_err.code,
            error_response=error_response,
        ) from http_err
