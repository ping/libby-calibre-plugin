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
from pathlib import Path

from calibre.constants import DEBUG, config_dir
from calibre.gui2 import open_url
from calibre.gui2.actions import InterfaceAction
from qt.core import QIcon, QPixmap, QSize, QToolButton

from . import (
    DEMO_MODE,
    PLUGINS_FOLDER_NAME,
    PLUGIN_ICON,
    PLUGIN_NAME,
    __version__,
    logger,
)
from .compat import QColor_fromString, _c
from .config import PREFS, PreferenceKeys, SearchMode
from .dialog import (
    BaseDialogMixin,
    CardsDialogMixin,
    HoldsDialogMixin,
    LoansDialogMixin,
    MagazinesDialogMixin,
    SearchDialogMixin,
    AdvancedSearchDialogMixin,
)
from .utils import (
    CARD_ICON,
    COVER_PLACEHOLDER,
    ICON_MAP,
    PluginImages,
    SimpleCache,
    svg_to_qicon,
)

PLUGIN_DIR = Path(config_dir, PLUGINS_FOLDER_NAME)
CI_COMMIT_TXT = "commit.txt"

# noinspection PyUnreachableCode
if False:
    load_translations = _ = get_resources = lambda x=None: x

load_translations()


class OverdriveLibbyAction(InterfaceAction):
    name = PLUGIN_NAME
    action_spec = (
        "OverDrive Libby",
        None,
        _("Import loans from your OverDrive Libby account"),
        (),
    )
    popup_type = QToolButton.MenuButtonPopup
    action_type = "current"
    action_add_menu = True
    action_menu_clone_qaction = _("Libby")
    dont_add_to = frozenset(["context-menu-device"])
    main_dialog = None
    development_version = None

    def genesis(self):
        # This method is called once per plugin, do initial setup here

        # extract icons
        image_resources = get_resources(
            [v.file for v in ICON_MAP.values()]
            + [PLUGIN_ICON, CARD_ICON, COVER_PLACEHOLDER, CI_COMMIT_TXT],
            print_tracebacks_for_missing_resources=DEBUG,  # noqa
        )
        self.resources = {}
        for k, v in ICON_MAP.items():
            self.resources[k] = svg_to_qicon(
                image_resources.pop(v.file), QColor_fromString(v.color)
            )

        # card icon
        self.resources[PluginImages.Card] = image_resources.pop(CARD_ICON)
        if CI_COMMIT_TXT in image_resources:
            self.development_version = (
                image_resources.pop(CI_COMMIT_TXT).decode("utf-8").strip()
            )
            if logger.handlers:
                logger.handlers[0].setFormatter(
                    logging.Formatter(
                        f'[{PLUGIN_NAME}/{".".join([str(d) for d in __version__])}'
                        f"*{self.development_version[:7]}] %(message)s"
                    )
                )

        # book cover placeholder
        cover_pixmap = QPixmap(150, 200)
        cover_pixmap.loadFromData(image_resources.pop(COVER_PLACEHOLDER))
        cover_pixmap.setDevicePixelRatio(self.gui.devicePixelRatio())
        self.resources[PluginImages.CoverPlaceholder] = cover_pixmap

        # action icon
        plugin_icon = svg_to_qicon(image_resources.pop(PLUGIN_ICON), size=(300, 300))
        self.qaction.setIcon(plugin_icon)
        # set the cloned menu icon
        mini_plugin_icon = QIcon(
            plugin_icon.pixmap(QSize(32, 32), self.gui.devicePixelRatio())
        )
        self.menuless_qaction.setIcon(mini_plugin_icon)
        self.qaction.triggered.connect(self.show_dialog)
        qaction_menu = self.qaction.menu()
        qaction_menu.setToolTipsVisible(True)

        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-config",
            _c("&Customize plugin"),
            "config.png",
            triggered=lambda: self.interface_action_base_plugin.do_user_config(
                self.gui
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-clear-cache",
            _("Clear cache"),
            self.resources[PluginImages.Delete],
            description=_("Clear cached data, e.g. titles, libraries"),
            triggered=self.clear_cache,
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-help",
            _c("Help"),
            "help.png",
            description=_("View setup and usage help"),
            triggered=lambda: open_url(
                "https://github.com/ping/libby-calibre-plugin#setup"
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-changelog",
            _("What's New"),
            self.resources[PluginImages.Information],
            description=_("See what's changed in the latest release"),
            triggered=lambda: open_url(
                "https://github.com/ping/libby-calibre-plugin/blob/main/CHANGELOG.md"
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-mr",
            _("MobileRead"),
            self.resources[PluginImages.ExternalLink],
            description=_("Plugin thread on the MobileRead forums"),
            triggered=lambda: open_url(
                "https://www.mobileread.com/forums/showthread.php?t=354816"
            ),
        )
        self.libraries_cache = SimpleCache(
            persist_to_path=PLUGIN_DIR.joinpath(f"{PLUGIN_NAME}.libraries.json"),
            cache_age_days=PREFS[PreferenceKeys.CACHE_AGE_DAYS],
            logger=logger,
        )
        self.media_cache = SimpleCache(
            persist_to_path=PLUGIN_DIR.joinpath(f"{PLUGIN_NAME}.media.json"),
            cache_age_days=PREFS[PreferenceKeys.CACHE_AGE_DAYS],
            logger=logger,
        )

    def main_dialog_finished(self):
        self.main_dialog = None

    def clear_cache(self):
        self.libraries_cache.clear()
        self.libraries_cache.save()
        self.media_cache.clear()
        self.media_cache.save()

    def show_dialog(self):
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        if not self.main_dialog:
            self.main_dialog = OverdriveLibbyDialog(
                self.gui,
                self.qaction.icon(),
                do_user_config,
                self.resources,
                self.libraries_cache,
                self.media_cache,
            )
            self.main_dialog.finished.connect(self.main_dialog_finished)
            window_title = _("OverDrive Libby v{version}{dev}").format(
                version=".".join([str(d) for d in __version__]),
                dev=f"*{self.development_version[:7]}"
                if self.development_version
                else "",
            )
            if DEMO_MODE:
                window_title = "OverDrive Libby"
            self.main_dialog.setWindowTitle(window_title)
        self.main_dialog.show()
        self.main_dialog.raise_()
        self.main_dialog.activateWindow()

    def apply_settings(self):
        self.libraries_cache.cache_age_days = PREFS[PreferenceKeys.CACHE_AGE_DAYS]
        self.media_cache.cache_age_days = PREFS[PreferenceKeys.CACHE_AGE_DAYS]
        self.libraries_cache.reload()
        self.media_cache.reload()
        if self.main_dialog:
            # close off main UI to make sure everything is consistent
            self.main_dialog.close()


class OverdriveLibbyDialog(
    CardsDialogMixin,
    AdvancedSearchDialogMixin,
    SearchDialogMixin,
    MagazinesDialogMixin,
    HoldsDialogMixin,
    LoansDialogMixin,
    BaseDialogMixin,
):
    def __init__(self, gui, icon, do_user_config, icons, libraries_cache, media_cache):
        super().__init__(gui, icon, do_user_config, icons, libraries_cache, media_cache)

        # this non-intuitive code is because Windows
        size_hint = self.sizeHint()
        w = size_hint.width()
        h = size_hint.height()
        if (
            PREFS[PreferenceKeys.MAIN_UI_WIDTH]
            and PREFS[PreferenceKeys.MAIN_UI_WIDTH] > 0
        ):
            w = PREFS[PreferenceKeys.MAIN_UI_WIDTH]
            logger.debug("Using saved window width: %d", w)
        if (
            PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
            and PREFS[PreferenceKeys.MAIN_UI_HEIGHT] > 0
        ):
            h = PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
            logger.debug("Using saved windows height: %d", h)

        logger.debug("Resizing window to: (%d, %d)", w, h)
        self.resize(QSize(w, h))

        if PREFS[PreferenceKeys.DISABLE_TAB_MAGAZINES]:
            self.tabs.setTabVisible(self.magazines_tab_index, False)

        if (
            PREFS[PreferenceKeys.LAST_SELECTED_TAB]
            and self.tabs.count() > PREFS[PreferenceKeys.LAST_SELECTED_TAB]
        ):
            self.tabs.setCurrentIndex(PREFS[PreferenceKeys.LAST_SELECTED_TAB])

        self.search_mode_changed.connect(lambda s: self.toggle_search_mode(s))
        self.search_mode_changed.emit(PREFS[PreferenceKeys.SEARCH_MODE])

        self.sync()

    def toggle_search_mode(self, search_mode: str):
        # this doesn't seem to work when toggling between basic and advance
        if search_mode == SearchMode.BASIC:
            if hasattr(self, "adv_search_btn"):
                self.adv_search_btn.setAutoDefault(False)
            if hasattr(self, "search_btn"):
                self.search_btn.setAutoDefault(True)
        elif search_mode == SearchMode.ADVANCED:
            if hasattr(self, "search_btn"):
                self.search_btn.setAutoDefault(False)
            if hasattr(self, "adv_search_btn"):
                self.adv_search_btn.setAutoDefault(True)

        if (
            search_mode == SearchMode.ADVANCED
            and hasattr(self, "search_tab_index")
            and hasattr(self, "adv_search_tab_index")
        ):
            self.tabs.setTabVisible(self.search_tab_index, False)
            self.tabs.setTabVisible(self.adv_search_tab_index, True)
        elif (
            search_mode == SearchMode.BASIC
            and hasattr(self, "search_tab_index")
            and hasattr(self, "adv_search_tab_index")
        ):
            self.tabs.setTabVisible(self.adv_search_tab_index, False)
            self.tabs.setTabVisible(self.search_tab_index, True)
