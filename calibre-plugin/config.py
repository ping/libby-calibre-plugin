#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

from calibre.utils.config import JSONConfig
from qt.core import Qt, QWidget, QGridLayout, QLabel, QCheckBox, QLineEdit

from . import logger, PLUGIN_NAME

load_translations()


class PreferenceKeys:
    LIBBY_SETUP_CODE = "libby_setup_code"
    LIBBY_TOKEN = "libby_token"
    HIDE_MAGAZINES = "hide_magazines"
    HIDE_EBOOKS = "hide_ebooks"
    HIDE_BOOKS_ALREADY_IN_LIB = "hide_books_in_already_lib"
    PREFER_OPEN_FORMATS = "prefer_open_formats"
    MAIN_UI_WIDTH = "main_ui_width"
    MAIN_UI_HEIGHT = "main_ui_height"
    TAG_EBOOKS = "tag_ebooks"
    TAG_MAGAZINES = "tag_magazines"
    CONFIRM_RETURNS = "confirm_returns"


class PreferenceTexts:
    LIBBY_SETUP_CODE = _("Libby Setup Code")
    LIBBY_SETUP_CODE_DESC = _("8-digit setup code")
    HIDE_MAGAZINES = _("Hide Magazines")
    HIDE_EBOOKS = _("Hide Ebooks")
    HIDE_BOOKS_ALREADY_IN_LIB = _("Hide books already in library")
    PREFER_OPEN_FORMATS = _("Prefer Open Formats")
    TAG_EBOOKS = _("Tag downloaded ebooks with")
    TAG_EBOOKS_PLACEHOLDER = _("Example: library,books")
    TAG_MAGAZINES = _("Tag downloaded magazines with")
    TAG_MAGAZINES_PLACEHOLDER = _("Example: library,magazines")
    CONFIRM_RETURNS = _("Always confirm returns")


PREFS = JSONConfig(f"plugins/{PLUGIN_NAME}")

PREFS.defaults[PreferenceKeys.LIBBY_SETUP_CODE] = ""
PREFS.defaults[PreferenceKeys.LIBBY_TOKEN] = ""
PREFS.defaults[PreferenceKeys.HIDE_MAGAZINES] = False
PREFS.defaults[PreferenceKeys.HIDE_EBOOKS] = False
PREFS.defaults[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB] = False
PREFS.defaults[PreferenceKeys.PREFER_OPEN_FORMATS] = True
PREFS.defaults[PreferenceKeys.MAIN_UI_WIDTH] = 0
PREFS.defaults[PreferenceKeys.MAIN_UI_HEIGHT] = 0
PREFS.defaults[PreferenceKeys.TAG_EBOOKS] = ""
PREFS.defaults[PreferenceKeys.TAG_MAGAZINES] = ""
PREFS.defaults[PreferenceKeys.CONFIRM_RETURNS] = True


class ConfigWidget(QWidget):
    def __init__(self, plugin_action):
        super().__init__()
        self.layout = QGridLayout()
        self.setLayout(self.layout)
        label_column_widths = []
        widget_row_pos = 0

        # Setup Status
        is_configured = bool(PREFS[PreferenceKeys.LIBBY_TOKEN])
        self.libby_setup_status_lbl = QLabel(
            _("Libby is configured.")
            if is_configured
            else _("Libby is not configured yet.")
        )
        self.libby_setup_status_lbl.setStyleSheet(
            "font-weight: bold; " f'color: {"#00D228" if is_configured else "#FF0F00"};'
        )
        self.layout.addWidget(self.libby_setup_status_lbl, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        widget_row_pos += 1

        # Libby Setup Code
        self.libby_setup_code_lbl = QLabel(
            PreferenceTexts.LIBBY_SETUP_CODE
            + ' [<a style="padding: 0 4px;" href="https://help.libbyapp.com/en-us/6070.htm"> ? </a>]'
        )
        self.libby_setup_code_lbl.setTextFormat(Qt.RichText)
        self.libby_setup_code_lbl.setOpenExternalLinks(True)
        self.layout.addWidget(self.libby_setup_code_lbl, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        self.libby_setup_code_txt = QLineEdit(self)
        self.libby_setup_code_txt.setPlaceholderText(
            PreferenceTexts.LIBBY_SETUP_CODE_DESC
        )
        self.libby_setup_code_txt.setInputMask("99999999")
        self.libby_setup_code_txt.setText(PREFS[PreferenceKeys.LIBBY_SETUP_CODE])
        self.layout.addWidget(self.libby_setup_code_txt, widget_row_pos, 1, 1, 1)
        self.libby_setup_code_lbl.setBuddy(self.libby_setup_code_txt)
        widget_row_pos += 1

        # Tag Ebooks
        self.tag_ebooks_lbl = QLabel(PreferenceTexts.TAG_EBOOKS)
        self.layout.addWidget(self.tag_ebooks_lbl, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        self.tag_ebooks_txt = QLineEdit(self)
        self.tag_ebooks_txt.setPlaceholderText(PreferenceTexts.TAG_EBOOKS_PLACEHOLDER)
        self.tag_ebooks_txt.setText(PREFS[PreferenceKeys.TAG_EBOOKS])
        self.layout.addWidget(self.tag_ebooks_txt, widget_row_pos, 1, 1, 1)
        self.tag_ebooks_lbl.setBuddy(self.tag_ebooks_txt)
        widget_row_pos += 1

        # Tag Magazines
        self.tag_magazines_lbl = QLabel(PreferenceTexts.TAG_MAGAZINES)
        self.layout.addWidget(self.tag_magazines_lbl, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        self.tag_magazines_txt = QLineEdit(self)
        self.tag_magazines_txt.setPlaceholderText(
            PreferenceTexts.TAG_MAGAZINES_PLACEHOLDER
        )
        self.tag_magazines_txt.setText(PREFS[PreferenceKeys.TAG_MAGAZINES])
        self.layout.addWidget(self.tag_magazines_txt, widget_row_pos, 1, 1, 1)
        self.tag_magazines_lbl.setBuddy(self.tag_magazines_txt)
        widget_row_pos += 1

        # Hide Ebooks
        self.hide_ebooks_checkbox = QCheckBox(PreferenceTexts.HIDE_EBOOKS, self)
        self.hide_ebooks_checkbox.setChecked(PREFS[PreferenceKeys.HIDE_EBOOKS])
        self.layout.addWidget(self.hide_ebooks_checkbox, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        widget_row_pos += 1

        # Hide Magazine
        self.hide_magazines_checkbox = QCheckBox(PreferenceTexts.HIDE_MAGAZINES, self)
        self.hide_magazines_checkbox.setChecked(PREFS[PreferenceKeys.HIDE_MAGAZINES])
        self.layout.addWidget(self.hide_magazines_checkbox, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        widget_row_pos += 1

        # Prefer Open Formats
        self.prefer_open_formats_checkbox = QCheckBox(
            PreferenceTexts.PREFER_OPEN_FORMATS, self
        )
        self.prefer_open_formats_checkbox.setChecked(
            PREFS[PreferenceKeys.PREFER_OPEN_FORMATS]
        )
        self.layout.addWidget(self.prefer_open_formats_checkbox, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        widget_row_pos += 1

        # Hide books already in library
        self.hide_books_already_in_lib_checkbox = QCheckBox(
            PreferenceTexts.HIDE_BOOKS_ALREADY_IN_LIB, self
        )
        self.hide_books_already_in_lib_checkbox.setChecked(
            PREFS[PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB]
        )
        self.layout.addWidget(
            self.hide_books_already_in_lib_checkbox, widget_row_pos, 0
        )
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        widget_row_pos += 1

        # Always confirm returns
        self.confirm_returns_checkbox = QCheckBox(PreferenceTexts.CONFIRM_RETURNS, self)
        self.confirm_returns_checkbox.setChecked(PREFS[PreferenceKeys.CONFIRM_RETURNS])
        self.layout.addWidget(self.confirm_returns_checkbox, widget_row_pos, 0)
        label_column_widths.append(
            self.layout.itemAtPosition(widget_row_pos, 0).sizeHint().width()
        )
        widget_row_pos += 1

        label_column_width = max(label_column_widths)
        self.layout.setColumnMinimumWidth(1, label_column_width)

    def save_settings(self):
        PREFS[PreferenceKeys.HIDE_MAGAZINES] = self.hide_magazines_checkbox.isChecked()
        PREFS[PreferenceKeys.HIDE_EBOOKS] = self.hide_ebooks_checkbox.isChecked()
        PREFS[
            PreferenceKeys.PREFER_OPEN_FORMATS
        ] = self.prefer_open_formats_checkbox.isChecked()
        PREFS[
            PreferenceKeys.HIDE_BOOKS_ALREADY_IN_LIB
        ] = self.hide_books_already_in_lib_checkbox.isChecked()
        PREFS[PreferenceKeys.TAG_EBOOKS] = self.tag_ebooks_txt.text().strip()
        PREFS[PreferenceKeys.TAG_MAGAZINES] = self.tag_magazines_txt.text().strip()
        PREFS[
            PreferenceKeys.CONFIRM_RETURNS
        ] = self.confirm_returns_checkbox.isChecked()

        setup_code = self.libby_setup_code_txt.text().strip()
        if setup_code != PREFS[PreferenceKeys.LIBBY_SETUP_CODE]:
            # if libby sync code has changed, do sync and save token
            from .libby import LibbyClient

            if not LibbyClient.is_valid_sync_code(setup_code):
                # save a http request for get_chip()
                raise Exception(
                    _("Invalid setup code format: {code}").format(code=setup_code)
                )

            libby_client = LibbyClient(logger=logger)
            chip_res = libby_client.get_chip()
            libby_client.clone_by_code(setup_code)
            if libby_client.is_logged_in():
                PREFS[PreferenceKeys.LIBBY_SETUP_CODE] = setup_code
                PREFS[PreferenceKeys.LIBBY_TOKEN] = chip_res["identity"]
