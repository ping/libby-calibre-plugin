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
import logging
import sys
import unittest
from http.client import HTTPConnection
from io import BytesIO
from typing import Dict, Optional
from urllib.error import HTTPError

test_logger = logging.getLogger(__name__)
test_logger.setLevel(logging.WARNING)


class BaseTests(unittest.TestCase):
    def setUp(self):
        self.logger = test_logger
        # hijack unittest -v/-vv arg to toggle log verbosity in test
        if "-v" in sys.argv:
            self.logger.setLevel(logging.INFO)
            logging.basicConfig(stream=sys.stdout)
        self.is_verbose = "-vv" in sys.argv
        if self.is_verbose:
            self.logger.setLevel(logging.DEBUG)
            HTTPConnection.debuglevel = 1
            logging.basicConfig(stream=sys.stdout)


class MockHTTPError(HTTPError):
    def __init__(
        self,
        code: int,
        res_obj: Dict,
        url: str = "",
        msg: str = "",
        headers: Optional[Dict] = None,
    ):
        if not headers:
            headers = {"content-type": "application/json"}
        super().__init__(
            url, code, msg, headers, BytesIO(json.dumps(res_obj).encode("ascii"))
        )
