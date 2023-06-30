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
