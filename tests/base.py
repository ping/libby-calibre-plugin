#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import logging
import sys
import unittest
from http.client import HTTPConnection

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
