#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

# noqa
import sys
from pathlib import Path

sys.path.append(str(Path("calibre-plugin/").absolute()))

from .libby import LibbyClientTests
from .overdrive import OverDriveClientTests
