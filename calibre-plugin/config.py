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

from calibre.utils.config import JSONConfig
from qt.core import QWidget, QGridLayout, QLabel, QCheckBox, QLineEdit

from . import logger, PLUGIN_NAME

try:
    load_translations()
except NameError:
    pass  # load_translations() added in calibre 1.9


class KEY:
    LIBBY_SETUP_CODE = "libby_setup_code"
    LIBBY_TOKEN = "libby_token"
    HIDE_MAGAZINES = "hide_magazines"
    HIDE_EBOOKS = "hide_ebooks"
    HIDE_BOOKS_ALREADY_IN_LIB = "hide_books_in_already_lib"
    VERBOSE_LOGS = "verbose_logs"


class TEXT:
    LIBBY_SETUP_CODE = _("Libby Setup Code:")
    LIBBY_SETUP_CODE_DESC = _("8-digit setup code")
    HIDE_MAGAZINES = _("Hide Magazines")
    HIDE_EBOOKS = _("Hide Ebooks")
    HIDE_BOOKS_ALREADY_IN_LIB = _("Hide books already in library")
    VERBOSE_LOGS = _("Verbose Logs")


PREFS = JSONConfig(f"plugins/{PLUGIN_NAME}")

PREFS.defaults[KEY.LIBBY_SETUP_CODE] = ""
PREFS.defaults[KEY.LIBBY_TOKEN] = ""
PREFS.defaults[KEY.HIDE_MAGAZINES] = False
PREFS.defaults[KEY.HIDE_EBOOKS] = False
PREFS.defaults[KEY.HIDE_BOOKS_ALREADY_IN_LIB] = False
PREFS.defaults[KEY.VERBOSE_LOGS] = False


class ConfigWidget(QWidget):
    def __init__(self, plugin_action):
        super().__init__()
        self.layout = QGridLayout()
        self.setLayout(self.layout)
        label_column_widths = []

        self.libby_setup_status_lbl = QLabel(
            _("Libby is configured.")
            if PREFS[KEY.LIBBY_TOKEN]
            else _("Libby is not configured yet.")
        )
        self.layout.addWidget(self.libby_setup_status_lbl, 0, 0)
        label_column_widths.append(self.layout.itemAtPosition(0, 0).sizeHint().width())

        self.libby_setup_code_lbl = QLabel(TEXT.LIBBY_SETUP_CODE)
        self.layout.addWidget(self.libby_setup_code_lbl, 1, 0)
        label_column_widths.append(self.layout.itemAtPosition(0, 0).sizeHint().width())

        self.libby_setup_code_txt = QLineEdit(self)
        self.libby_setup_code_txt.setPlaceholderText(TEXT.LIBBY_SETUP_CODE_DESC)
        self.libby_setup_code_txt.setText(PREFS[KEY.LIBBY_SETUP_CODE])
        self.layout.addWidget(self.libby_setup_code_txt, 1, 1)
        self.libby_setup_code_lbl.setBuddy(self.libby_setup_code_txt)

        self.hide_magazines_checkbox = QCheckBox(TEXT.HIDE_MAGAZINES, self)
        self.hide_magazines_checkbox.setChecked(PREFS[KEY.HIDE_MAGAZINES])
        self.layout.addWidget(self.hide_magazines_checkbox, 2, 0)
        label_column_widths.append(self.layout.itemAtPosition(2, 0).sizeHint().width())

        self.hide_ebooks_checkbox = QCheckBox(TEXT.HIDE_EBOOKS, self)
        self.hide_ebooks_checkbox.setChecked(PREFS[KEY.HIDE_EBOOKS])
        self.layout.addWidget(self.hide_ebooks_checkbox, 3, 0)
        label_column_widths.append(self.layout.itemAtPosition(3, 0).sizeHint().width())

        self.hide_books_already_in_lib_checkbox = QCheckBox(
            TEXT.HIDE_BOOKS_ALREADY_IN_LIB, self
        )
        self.hide_books_already_in_lib_checkbox.setChecked(
            PREFS[KEY.HIDE_BOOKS_ALREADY_IN_LIB]
        )
        self.layout.addWidget(self.hide_books_already_in_lib_checkbox, 4, 0)
        label_column_widths.append(self.layout.itemAtPosition(4, 0).sizeHint().width())

        self.verbose_logs_checkbox = QCheckBox(TEXT.VERBOSE_LOGS, self)
        self.verbose_logs_checkbox.setChecked(PREFS[KEY.VERBOSE_LOGS])
        self.layout.addWidget(self.verbose_logs_checkbox, 5, 0)
        label_column_widths.append(self.layout.itemAtPosition(5, 0).sizeHint().width())

        label_column_width = max(label_column_widths)
        self.layout.setColumnMinimumWidth(1, label_column_width * 2)

    def save_settings(self):
        PREFS[KEY.HIDE_MAGAZINES] = self.hide_magazines_checkbox.isChecked()
        PREFS[KEY.HIDE_EBOOKS] = self.hide_ebooks_checkbox.isChecked()
        PREFS[
            KEY.HIDE_BOOKS_ALREADY_IN_LIB
        ] = self.hide_books_already_in_lib_checkbox.isChecked()
        PREFS[KEY.VERBOSE_LOGS] = self.verbose_logs_checkbox.isChecked()
        setup_code = self.libby_setup_code_txt.text().strip()
        if PREFS[KEY.VERBOSE_LOGS]:
            logger.setLevel(logging.DEBUG)
        if setup_code != PREFS[KEY.LIBBY_SETUP_CODE]:
            # if libby sync code has changed, do sync and save token
            from .libby import LibbyClient

            libby_client = LibbyClient(logger=logger)
            chip_res = libby_client.get_chip()
            libby_client.clone_by_code(setup_code)
            if libby_client.is_logged_in():
                PREFS[KEY.LIBBY_SETUP_CODE] = setup_code
                PREFS[KEY.LIBBY_TOKEN] = chip_res["identity"]
