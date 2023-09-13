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
import math
import os
import platform
import random
import re
import time
import unicodedata
from collections import OrderedDict, namedtuple
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

from calibre.constants import DEBUG as CALIBRE_DEBUG
from calibre.gui2 import is_dark_theme
from calibre.utils.logging import DEBUG, ERROR, INFO, WARN
from qt.core import QColor, QIcon, QPainter, QPixmap, QSvgRenderer, QXmlStreamReader

from . import PLUGIN_NAME
from .compat import (
    QPainter_CompositionMode_CompositionMode_SourceIn,
    Qt_GlobalColor_transparent,
)

try:
    from calibre_plugins.overdrive_link.link import (
        IDENT_AVAILABLE_LINK as OD_IDENTIFIER,
    )
except ImportError:
    OD_IDENTIFIER = "odid"

CARD_ICON = "images/card.svg"
COVER_PLACEHOLDER = "images/placeholder.png"


class CalibreLogHandler(logging.Handler):
    """
    Simple wrapper around the calibre job Log to support standard logging calls
    """

    def __init__(self, logger):
        self.calibre_log = None
        if not logger:
            super().__init__()
            return

        if isinstance(logger, CalibreLogHandler):
            # just in case we accidentally pass in a wrapped log
            self.calibre_log = logger.calibre_log
        else:
            self.calibre_log = logger
        calibre_log_level = self.calibre_log.filter_level
        level = logging.NOTSET
        if calibre_log_level <= DEBUG:
            level = logging.DEBUG
        elif calibre_log_level == INFO:
            level = logging.INFO
        elif calibre_log_level == WARN:
            level = logging.WARNING
        elif calibre_log_level >= ERROR:
            level = logging.ERROR
        super().__init__(level)

    def emit(self, record):
        if not self.calibre_log:
            return
        msg = self.format(record)
        if record.levelno <= logging.DEBUG:
            self.calibre_log.debug(msg)
        elif record.levelno == logging.INFO:
            self.calibre_log.info(msg)
        elif record.levelno == logging.WARNING:
            self.calibre_log.warning(msg)
        elif record.levelno >= logging.ERROR:
            self.calibre_log.error(msg)
        else:
            self.calibre_log.info(msg)


def create_job_logger(log) -> logging.Logger:
    """
    Convert calibre's logger into a more standardised logger

    :param log:
    :return:
    """
    logger = logging.getLogger(f"{PLUGIN_NAME}.jobs")
    ch = CalibreLogHandler(log)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)
    logger.setLevel(logging.INFO if not CALIBRE_DEBUG else logging.DEBUG)
    return logger


class SimpleCache:
    def __init__(
        self,
        capacity: int = 100,
        persist_to_path: Optional[Path] = None,
        cache_age_days: int = 3,
        logger: Optional[logging.Logger] = None,
    ):
        self.cache: OrderedDict = OrderedDict()
        self.capacity = capacity
        self.lock = Lock()
        self.persist_to_path = persist_to_path
        self.cache_age_days = cache_age_days
        if not logger:
            logger = logging.getLogger(__name__)
        self.logger = logger
        self.cache_timestamp_key = "__cached_at"
        self._load_from_file()

    def _load_from_file(self):
        if (
            self.cache_age_days
            and self.persist_to_path
            and self.persist_to_path.exists()
        ):
            with self.persist_to_path.open("r", encoding="utf-8") as fp:
                cached_items = list(json.load(fp).items())
                for k, v in cached_items:
                    if not v.get(self.cache_timestamp_key):
                        continue
                    cached_at = datetime.fromtimestamp(
                        v[self.cache_timestamp_key], tz=timezone.utc
                    )
                    cache_age = datetime.now(tz=timezone.utc) - cached_at
                    if cache_age > timedelta(days=self.cache_age_days):
                        continue
                    self.cache[k] = v
                self.logger.debug(
                    "Loaded %d items from file cache %s",
                    len(self.cache),
                    self.persist_to_path,
                )

    def reload(self):
        with self.lock:
            self.cache.clear()
            self._load_from_file()

    def save(self):
        if not self.persist_to_path:
            return
        for item in self.cache.values():
            for k in list(item.keys()):
                if isinstance(item[k], bytes):  # exclude bytes
                    del item[k]
        with self.persist_to_path.open("wt", encoding="utf-8") as fp:
            json.dump(self.cache, fp)
            self.logger.debug(
                "Saved %d items to file cache at %s",
                len(self.cache),
                self.persist_to_path,
            )

    def clear(self):
        with self.lock:
            self.cache.clear()

    def get(self, key: str) -> Optional[Dict]:
        if not self.cache_age_days:
            return None
        with self.lock:
            if key not in self.cache:
                return None
            else:
                self.cache.move_to_end(key)
                return self.cache[key]

    def put(self, key: str, value: Dict) -> None:
        if not self.cache_age_days:
            return
        with self.lock:
            if not value.get(self.cache_timestamp_key):
                value[self.cache_timestamp_key] = time.time()
            self.cache[key] = value
            self.cache.move_to_end(key)
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def count(self) -> int:
        with self.lock:
            return len(self.cache)

    def items(self):
        with self.lock:
            return self.cache.items()


def obfuscate_date(dt: datetime, day=None, month=None, year=None):
    if not dt:
        return dt
    return dt.replace(day=day or 1, month=month or 1, year=year or datetime.now().year)


def obfuscate_name(name: str, offset=5, min_word_len=1, max_word_len=8):
    obfuscated = []
    if not name:
        return name
    for n in name.split(" "):
        min_n = max(min_word_len, len(n) - offset)
        max_n = min(max_word_len, len(n) + offset)
        if min_n == max_n:
            min_n = min_word_len
            max_n = max_word_len
        choices = range(min_n, max_n, 1 if max_n > min_n else -1)
        obfuscated.append(
            "*" * random.choice(choices or range(min_word_len, max_word_len))
        )
    return " ".join(obfuscated)


def obfuscate_int(value: int, offset=5, min_value=0, max_val=30):
    return random.choice(
        range(
            max(min_value, min(value, max_val) - offset), min(max_val, value + offset)
        )
    )


def is_windows() -> bool:
    """
    Returns True if running on Windows.

    :return:
    """
    return os.name == "nt" or platform.system().lower() == "windows"


# From django
def slugify(value: str, allow_unicode: bool = False) -> str:
    """
    Convert to ASCII if 'allow_unicode' is False. Convert spaces to hyphens.
    Remove characters that aren't alphanumerics, underscores, or hyphens.
    Convert to lowercase. Also strip leading and trailing whitespace.
    """
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
        value = re.sub(r"[^\w\s-]", "", value, flags=re.U).strip().lower()
        return re.sub(r"[-\s]+", "-", value, flags=re.U)
    value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def generate_od_identifier(media: Dict, library: Dict) -> str:
    """
    Generates the OverDrive Link identifier.
    Should probably find a way to call the plugin to do it though.

    :param media:
    :param library:
    :return:
    """
    try:
        from calibre_plugins.overdrive_link.link import ODLink

        return str(
            ODLink(
                provider_id="",
                library_id=f'{library["preferredKey"]}.overdrive.com',
                book_id=media["id"],
            )
        )
    except ImportError:
        return f'{media["id"]}@{library["preferredKey"]}.overdrive.com'


def rating_to_stars(value, star="★", half="⯨"):
    r = round(value * 2) / 2  # round to halves
    t = star * math.floor(r)
    if r - math.floor(r):
        t += half
    return t


def svg_to_pixmap(
    data: bytes, color: Optional[QColor] = None, size=(64, 64)
) -> QPixmap:
    renderer = QSvgRenderer(QXmlStreamReader(data))
    pixmap = QPixmap(*size)
    pixmap.fill(Qt_GlobalColor_transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.setCompositionMode(QPainter_CompositionMode_CompositionMode_SourceIn)
    if color:
        painter.fillRect(pixmap.rect(), color)
    painter.end()
    return pixmap


def svg_to_qicon(data: bytes, color: Optional[QColor] = None, size=(64, 64)):
    """
    Converts an SVG to QIcon

    :param data:
    :param color:
    :param size:
    :return:
    """
    return QIcon(svg_to_pixmap(data, color, size))


class PluginColors(str, Enum):
    Red = "#FF0F00" if is_dark_theme() else "#E70E00"
    Green = "#00D228" if is_dark_theme() else "#00BA28"
    Blue = "#6EA8FE" if is_dark_theme() else "#0E6EFD"
    Purple = "#C0A4FF" if is_dark_theme() else "#7B47D1"
    Turquoise = "#07CAF0" if is_dark_theme() else "#07B0D3"
    Gray = "#CCCCCC" if is_dark_theme() else "#333333"
    Gray2 = "#9DB2BF" if is_dark_theme() else "#526D82"
    OrangeYellow = "#FFC107" if is_dark_theme() else "#FD7E14"
    ThemeGreen = "#63CBC1" if is_dark_theme() else "#25B0A7"

    def __str__(self):
        return str(self.value)


class PluginImages(str, Enum):
    Return = "return"
    Download = "download"
    ExternalLink = "ext-link"
    Refresh = "refresh"
    Add = "add-file"
    Delete = "delete"
    AddMagazine = "magazines-add"
    CancelMagazine = "cancel-sub"
    Edit = "pencil-line"
    Cancel = "cancel"
    Okay = "okay"
    Clover = "clover"
    Card = "card"
    Search = "search"
    Amazon = "amazon"
    Unlock = "unlock"
    CoverPlaceholder = "cover-placeholder"
    Information = "information"
    Renew = "renew"
    Share = "share"
    SearchToggle = "search-toggle"
    Switch = "switch"

    def __str__(self):
        return str(self.value)


IconDefinition = namedtuple("IconDefinition", ["file", "color"])

ICON_MAP = {
    PluginImages.Return: IconDefinition(
        file="images/arrow-go-back-line.svg", color=PluginColors.Red
    ),
    PluginImages.Download: IconDefinition(
        file="images/download-line.svg", color=PluginColors.Blue
    ),
    PluginImages.ExternalLink: IconDefinition(
        file="images/external-link-line.svg", color=PluginColors.Purple
    ),
    PluginImages.Refresh: IconDefinition(
        file="images/refresh-line.svg", color=PluginColors.OrangeYellow
    ),
    PluginImages.Add: IconDefinition(
        file="images/file-add-line.svg", color=PluginColors.Blue
    ),
    PluginImages.Delete: IconDefinition(
        file="images/delete-bin-line.svg", color=PluginColors.Red
    ),
    PluginImages.AddMagazine: IconDefinition(
        file="images/heart-add-line.svg",
        color="#EA868E" if is_dark_theme() else "#D63284",
    ),
    PluginImages.CancelMagazine: IconDefinition(
        file="images/dislike-line.svg", color=PluginColors.Red
    ),
    PluginImages.Edit: IconDefinition(
        file="images/pencil-line.svg", color=PluginColors.Turquoise
    ),
    PluginImages.Cancel: IconDefinition(
        file="images/close-line.svg", color=PluginColors.Gray
    ),
    PluginImages.Okay: IconDefinition(
        file="images/check-line.svg", color=PluginColors.Green
    ),
    PluginImages.Clover: IconDefinition(
        file="images/clover.svg", color=PluginColors.Green
    ),
    PluginImages.Search: IconDefinition(
        file="images/search-line.svg", color=PluginColors.Gray2
    ),
    PluginImages.Amazon: IconDefinition(
        file="images/brand-amazon.svg",
        color="#FF9900" if is_dark_theme() else "#FD9700",
    ),
    PluginImages.Unlock: IconDefinition(
        file="images/lock-unlock-line.svg", color=PluginColors.Green
    ),
    PluginImages.Information: IconDefinition(
        file="images/information-line.svg", color=PluginColors.Blue
    ),
    PluginImages.Renew: IconDefinition(
        file="images/arrow-go-forward-line.svg", color=PluginColors.Green
    ),
    PluginImages.Share: IconDefinition(
        file="images/share-line.svg", color=PluginColors.ThemeGreen
    ),
    PluginImages.SearchToggle: IconDefinition(
        file="images/menu-search-line.svg", color=PluginColors.Turquoise
    ),
    PluginImages.Switch: IconDefinition(
        file="images/arrow-left-right-line.svg", color=PluginColors.Turquoise
    ),
}
