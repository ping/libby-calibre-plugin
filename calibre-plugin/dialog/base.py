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
from collections import OrderedDict
from functools import cmp_to_key, partial
from typing import Dict, List, Optional

from calibre import prepare_string_for_xml
from calibre.constants import DEBUG
from calibre.ebooks.metadata.sources.identify import urls_from_identifiers
from calibre.gui2 import Dispatcher, error_dialog, info_dialog, open_url, rating_font
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre.gui2.widgets2 import CenteredToolButton  # available from calibre 5.33.0
from calibre.utils.config import tweaks
from calibre.utils.date import dt_as_local, format_date
from lxml import etree
from polyglot.builtins import as_unicode
from polyglot.io import PolyglotStringIO
from qt.core import (
    QApplication,
    QDialog,
    QFont,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPalette,
    QPixmap,
    QPixmapCache,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QThread,
    QVBoxLayout,
    QWidget,
    Qt,
    pyqtSignal,
)

from .widgets import ClickableQLabel, CustomLoadingOverlay, DefaultQPushButton
from .. import DEMO_MODE, logger
from ..compat import QToolButton_ToolButtonPopupMode_DelayedPopup, _c, ngettext_c
from ..config import BorrowActions, PREFS, PreferenceKeys, SearchMode
from ..hold_actions import LibbyHoldCreate
from ..libby import LibbyClient, LibbyMediaTypes
from ..libby.errors import (
    ClientConnectionError as LibbyConnectionError,
    ClientError as LibbyClientError,
)
from ..models import (
    CREATOR_ROLE_TRANSLATION,
    LOAN_TYPE_TRANSLATION,
    LibbyModel,
    get_media_title,
    truncate_for_display,
)
from ..overdrive import OverDriveClient
from ..overdrive.errors import ClientConnectionError as OverDriveConnectionError
from ..utils import (
    OD_IDENTIFIER,
    PluginImages,
    SimpleCache,
    generate_od_identifier,
    rating_to_stars,
    svg_to_pixmap,
)
from ..workers import OverDriveMediaWorker, SyncDataWorker

# noinspection PyUnreachableCode
if False:
    load_translations = _ = lambda x=None: x

load_translations()

gui_create_hold = LibbyHoldCreate()


class BorrowAndDownloadButton(CenteredToolButton):
    def __init__(self, text, icon=None, action=None, parent=None):
        super().__init__(icon, text, parent)
        self.setText(text)
        if icon is not None:
            self.setIcon(icon)
        self.setStyleSheet("padding: 2px 16px")
        self.setFont(QFont(QApplication.font()))  # make it bigger
        self.action = None
        self.set_action(action)

    def set_action(self, action):
        try:
            self.clicked.disconnect()
        except TypeError:
            pass
        self.action = action
        if self.action:
            self.clicked.connect(self.action)


class BaseDialogMixin(QDialog):
    """
    Base mixin class for the main QDialog
    """

    last_borrow_action_changed = pyqtSignal(str)
    search_mode_changed = pyqtSignal(str)
    hide_title_already_in_lib_pref_changed = pyqtSignal(bool)
    sync_starting = pyqtSignal()
    sync_ended = pyqtSignal(dict)
    loan_added = pyqtSignal(dict)
    hold_added = pyqtSignal(dict)
    loan_removed = pyqtSignal(dict)
    hold_removed = pyqtSignal(dict)

    def __init__(
        self,
        gui,
        icon,
        do_user_config,
        resources: Dict,
        libraries_cache: SimpleCache,
        media_cache: SimpleCache,
    ):
        super().__init__(gui)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.gui = gui
        self.do_user_config = do_user_config
        self.resources = resources
        self.db = gui.current_db.new_api
        self.client = None
        self._sync_thread = QThread()  # main sync thread
        self.logger = logger
        self.libraries_cache = libraries_cache
        self.media_cache = media_cache
        self.setWindowIcon(icon)
        self.view_vspan = 1
        self.view_hspan = 4
        self.min_button_width = (
            150  # use this to set min col width for cols containing buttons
        )
        self.min_view_width = 740

        libby_token = PREFS[PreferenceKeys.LIBBY_TOKEN]
        if libby_token:
            self.client = LibbyClient(
                identity_token=libby_token,
                max_retries=PREFS[PreferenceKeys.NETWORK_RETRY],
                timeout=PREFS[PreferenceKeys.NETWORK_TIMEOUT],
                logger=logger,
            )
        self.overdrive_client = OverDriveClient(
            max_retries=PREFS[PreferenceKeys.NETWORK_RETRY],
            timeout=PREFS[PreferenceKeys.NETWORK_TIMEOUT],
            logger=logger,
        )

        layout = QGridLayout()
        self.setLayout(layout)
        self.tabs = QTabWidget(self)
        self.tabs.currentChanged.connect(self.tab_current_changed)
        layout.addWidget(self.tabs, 0, 0)

        # Status bar
        self.status_bar = QStatusBar(self)
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setStyleSheet(
            "background-color: rgba(127, 127, 127, 0.1); border-radius: 4px;"
        )
        help_lbl = QLabel(
            '<a href="https://github.com/ping/libby-calibre-plugin#usage">'
            + _c("Help")
            + '</a> / <a href="https://www.mobileread.com/forums/showthread.php?t=354816">'
            + _("MobileRead")
            + "</a>"
        )
        help_lbl.setStyleSheet("margin: 0 4px")
        help_lbl.setAttribute(Qt.WA_TranslucentBackground)
        help_lbl.setTextFormat(Qt.RichText)
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setTextInteractionFlags(
            Qt.LinksAccessibleByKeyboard | Qt.LinksAccessibleByMouse
        )
        self.status_bar.addPermanentWidget(help_lbl)
        layout.addWidget(self.status_bar, 1, 0)

        self.loading_overlay = CustomLoadingOverlay(self)

        self.finished.connect(self.dialog_finished)

    def dialog_finished(self):
        dialog_size = self.size()
        new_width = dialog_size.width()
        new_height = dialog_size.height()
        if PREFS[PreferenceKeys.MAIN_UI_WIDTH] != new_width:
            PREFS[PreferenceKeys.MAIN_UI_HEIGHT] = new_width
            logger.debug("Saved new UI width preference: %d", new_width)
        if PREFS[PreferenceKeys.MAIN_UI_HEIGHT] != new_height:
            PREFS[PreferenceKeys.MAIN_UI_HEIGHT] = new_height
            logger.debug("Saved new UI height preference: %d", new_height)
        self.libraries_cache.save()
        self.media_cache.save()

    def add_tab(self, widget, label) -> int:
        """
        Helper method for adding tabs.
        We temporarily block QTabWidget signals because the `currentChanged` signal is emitted
        even on `addTab()`.

        :param widget:
        :param label:
        :return:
        """
        prev = self.tabs.blockSignals(True)
        new_tab_index = self.tabs.addTab(widget, label)
        self.tabs.blockSignals(prev)
        return new_tab_index

    def tab_current_changed(self, index: int):
        if index > -1:
            PREFS[PreferenceKeys.LAST_SELECTED_TAB] = index

    def add_view_in_menu_actions(self, menu, indices, libby_model):
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_libby_action.triggered.connect(
            lambda: self.view_in_libby_action_triggered(indices, libby_model)
        )
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_overdrive_action.triggered.connect(
            lambda: self.view_in_overdrive_action_triggered(indices, libby_model)
        )

    def view_in_libby_action_triggered(
        self, indices, model: LibbyModel, card: Optional[Dict] = None
    ):
        """
        Open title in Libby

        :param indices:
        :param model:
        :param card:
        :return:
        """
        for index in indices:
            data = index.data(Qt.UserRole)
            library_key = (card or model.get_card(data["cardId"]))["advantageKey"]
            open_url(LibbyClient.libby_title_permalink(library_key, data["id"]))

    def view_in_overdrive_action_triggered(
        self, indices, model: LibbyModel, card: Optional[Dict] = None
    ):
        """
        Open title in library OverDrive site

        :param indices:
        :param model:
        :param card:
        :return:
        """
        for index in indices:
            data = index.data(Qt.UserRole)
            card_ = card or model.get_card(data["cardId"]) or {}
            if not card_:
                continue
            library = model.get_library(model.get_website_id(card_)) or {}
            if not library:
                continue

            open_url(
                OverDriveClient.library_title_permalink(
                    library["preferredKey"], data["id"]
                )
            )

    def add_view_book_details_menu_action(self, menu, media):
        preview_action = menu.addAction(_c("Book details"))
        preview_action.setIcon(self.resources[PluginImages.Information])
        preview_action.triggered.connect(lambda: self.show_book_details(media))

    def show_book_details(self, media):
        preview_dialog = BookPreviewDialog(
            self, self.gui, self.resources, self.overdrive_client, media
        )
        preview_dialog.setModal(True)
        preview_dialog.open()

    def add_find_library_match_menu_action(self, menu, media):
        preview_action = menu.addAction(_("Search in calibre library"))
        preview_action.setIcon(self.resources[PluginImages.Search])
        preview_action.triggered.connect(lambda: self.find_library_matches(media))

    def add_search_for_title_menu_action(self, menu, media, search_for_author=False):
        if (
            hasattr(self, "search_for")
            and PREFS[PreferenceKeys.SEARCH_MODE] == SearchMode.BASIC
        ):
            search_action = menu.addAction(
                _('Search for "{book}"').format(
                    book=truncate_for_display(get_media_title(media))
                )
            )
            search_action.setIcon(self.resources[PluginImages.Search])
            search_action.triggered.connect(
                lambda: self.search_for(
                    f'{get_media_title(media)} {media.get("firstCreatorName", "")}'.strip()
                )
            )
            if search_for_author and media.get("firstCreatorName"):
                search_author_action = menu.addAction(
                    _('Search for "{book}"').format(
                        book=truncate_for_display(media["firstCreatorName"])
                    )
                )
                search_author_action.setIcon(self.resources[PluginImages.Search])
                search_author_action.triggered.connect(
                    lambda: self.search_for(media["firstCreatorName"].strip())
                )
        if (
            hasattr(self, "adv_search_for")
            and PREFS[PreferenceKeys.SEARCH_MODE] == SearchMode.ADVANCED
        ):
            search_action = menu.addAction(
                _('Search for "{book}"').format(
                    book=truncate_for_display(get_media_title(media))
                )
            )
            search_action.setIcon(self.resources[PluginImages.Search])
            search_action.triggered.connect(
                lambda: self.adv_search_for(
                    f"{get_media_title(media)}".strip(),
                    f'{media.get("firstCreatorName", "")}'.strip(),
                )
            )
            if search_for_author and media.get("firstCreatorName"):
                search_author_action = menu.addAction(
                    _('Search for "{book}"').format(
                        book=truncate_for_display(media["firstCreatorName"])
                    )
                )
                search_author_action.setIcon(self.resources[PluginImages.Search])
                search_author_action.triggered.connect(
                    lambda: self.adv_search_for(
                        "", f'{media.get("firstCreatorName", "")}'.strip()
                    )
                )

    def add_copy_share_link_menu_action(self, menu, media):
        copy_share_link_action = menu.addAction(_("Copy Libby share link"))
        copy_share_link_action.setIcon(self.resources[PluginImages.Share])
        copy_share_link_action.triggered.connect(lambda: self.copy_share_link(media))

    def copy_share_link(self, media):
        clipboard = QApplication.clipboard()
        link = LibbyClient.libby_title_share_link(media["id"])
        clipboard.setText(link)
        self.status_bar.showMessage(_("Copied {link}").format(link=link), 3000)

    def generate_search_conditions(
        self, media, library: Optional[Dict] = None, format_id: Optional[str] = None
    ) -> List[str]:
        isbn = OverDriveClient.extract_isbn(
            media.get("formats", []), [format_id] if format_id else []
        )
        if format_id and not isbn:
            # try again without format_id
            isbn = OverDriveClient.extract_isbn(media.get("formats", []), [])
        asin = OverDriveClient.extract_asin(media.get("formats", []))
        search_conditions: List[str] = [f'title:"""={get_media_title(media)}"""']
        if media.get("subtitle"):
            search_conditions.append(
                f'title:"""={get_media_title(media, include_subtitle=True)}"""'
            )
        if isbn:
            search_conditions.append(f'identifiers:"=isbn:{isbn}"')
        if asin:
            search_conditions.append(f'identifiers:"=asin:{asin}"')
            search_conditions.append(f'identifiers:"=amazon:{asin}"')
        if PREFS[PreferenceKeys.OVERDRIVELINK_INTEGRATION]:
            if library:
                search_conditions.append(
                    f'identifiers:"={OD_IDENTIFIER}:{generate_od_identifier(media, library)}"'
                )
            else:
                search_conditions.append(
                    rf'identifiers:"={OD_IDENTIFIER}:~^{media["id"]}\@"'
                )
        return search_conditions

    def find_library_matches(self, media):
        search_conditions = self.generate_search_conditions(media)
        self.gui.search.set_search_string(" or ".join(search_conditions))

    def sync(self):
        if not self.client:
            self.status_bar.showMessage(_("Libby is not configured yet."))
            return
        if not self._sync_thread.isRunning():
            self.status_bar.showMessage(_("Synchronizing..."))
            self.loading_overlay(_("Synchronizing..."))
            self.sync_starting.emit()
            self._sync_thread = self._get_sync_thread()
            self._sync_thread.start()

    def _get_sync_thread(self):
        thread = QThread()
        worker = SyncDataWorker()
        worker.setup(self.libraries_cache, self.media_cache)
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(value: Dict):
            self.sync_ended.emit(value)
            self.loading_overlay.hide()
            try:
                holds = value.get("holds", [])
                holds_count = len(holds)
                holds_unique_count = len(list(set([h["id"] for h in holds])))
                self.status_bar.showMessage(
                    _(
                        "Synced {loans} loans, {holds} holds ({unique_holds} unique), {cards} cards, "
                        "and {magazines} magazines."
                    ).format(
                        loans=len(value.get("loans", [])),
                        holds=holds_count,
                        unique_holds=holds_unique_count,
                        cards=len(value.get("cards", [])),
                        magazines=len(PREFS[PreferenceKeys.MAGAZINE_SUBSCRIPTIONS]),
                    )
                    if not DEMO_MODE
                    else "",
                    8000,
                )
            except RuntimeError as err:
                # most likely because the UI has been closed before syncing was completed
                logger.warning("Error processing sync results: %s", err)
            finally:
                thread.quit()

        def errored_out(err: Exception):
            self.sync_ended.emit({})
            try:
                thread.quit()
                self.loading_overlay.hide()
                self.status_bar.showMessage(
                    _("An error occured during sync: {err}").format(err=str(err))
                )
                return self.unhandled_exception(err, msg=_("Error synchronizing data"))
            except RuntimeError as err:
                # most likely because the UI has been closed before syncing was completed
                logger.warning("Error processing sync results: %s", err)

        worker.finished.connect(lambda value: loaded(value))
        worker.errored.connect(lambda err: errored_out(err))

        return thread

    def init_borrow_btn(self, borrow_function):
        """
        Build a borrow button for Holds and Magazines tabs

        :param borrow_function:
        :return:
        """
        borrow_action_default_is_borrow = PREFS[
            PreferenceKeys.LAST_BORROW_ACTION
        ] == BorrowActions.BORROW or not hasattr(self, "download_loan")

        borrow_btn = BorrowAndDownloadButton(
            _("Borrow")
            if borrow_action_default_is_borrow
            else _("Borrow and Download"),
            self.resources[PluginImages.Add],
            lambda: borrow_function(do_download=not borrow_action_default_is_borrow),
            self,
        )
        borrow_btn.setToolTip(
            _("Borrow selected title")
            if borrow_action_default_is_borrow
            else _("Borrow and download selected title")
        )
        if hasattr(self, "download_loan"):
            borrow_btn.setPopupMode(QToolButton_ToolButtonPopupMode_DelayedPopup)
            borrow_btn_menu = QMenu(borrow_btn)
            borrow_btn_menu_bnd_action = borrow_btn_menu.addAction(
                _("Borrow and Download")
                if borrow_action_default_is_borrow
                else _("Borrow")
            )
            borrow_btn_menu_bnd_action.triggered.connect(
                lambda: borrow_function(do_download=borrow_action_default_is_borrow)
            )
            borrow_btn_menu.borrow_action = borrow_btn_menu_bnd_action
            borrow_btn.borrow_menu = borrow_btn_menu
            borrow_btn.setMenu(borrow_btn_menu)
        return borrow_btn

    def rebind_borrow_btn(self, borrow_action: str, borrow_btn, borrow_function):
        """
        Shared func for rebinding and toggling the borrow button in the Holds and Mgazines tabs.

        :param borrow_action:
        :param borrow_btn:
        :param borrow_function:
        :return:
        """
        borrow_action_default_is_borrow = (
            borrow_action == BorrowActions.BORROW or not hasattr(self, "download_loan")
        )
        borrow_btn.setText(
            _("Borrow") if borrow_action_default_is_borrow else _("Borrow and Download")
        )
        borrow_btn.setToolTip(
            _("Borrow selected title")
            if borrow_action_default_is_borrow
            else _("Borrow and download selected title")
        )
        borrow_btn.set_action(
            lambda: borrow_function(do_download=not borrow_action_default_is_borrow)
        )
        if hasattr(borrow_btn, "borrow_menu") and hasattr(
            borrow_btn.borrow_menu, "borrow_action"
        ):
            borrow_btn.borrow_menu.borrow_action.setText(
                _("Borrow and Download")
                if borrow_action_default_is_borrow
                else _("Borrow")
            )
            try:
                borrow_btn.borrow_menu.borrow_action.triggered.disconnect()
            except TypeError:
                pass
            borrow_btn.borrow_menu.borrow_action.triggered.connect(
                lambda: borrow_function(do_download=borrow_action_default_is_borrow)
            )

    def rebind_borrow_buttons(self, do_download=False):
        """
        Calls the known rebind borrow button functions from tabs

        :param do_download:
        :return:
        """
        borrow_action = (
            BorrowActions.BORROW_AND_DOWNLOAD if do_download else BorrowActions.BORROW
        )
        if PREFS[PreferenceKeys.LAST_BORROW_ACTION] != borrow_action:
            PREFS[PreferenceKeys.LAST_BORROW_ACTION] = borrow_action
            self.last_borrow_action_changed.emit(borrow_action)

    def display_debug(self, text, data):
        """
        Used to display the underlying data for an item in a tableview.

        :param text:
        :param data:
        :return:
        """
        if DEBUG:
            try:
                data_json = json.dumps(data, indent=2)
            except TypeError:
                import copy

                data2 = copy.deepcopy(data)
                for k in list(data2.keys()):
                    if isinstance(data2[k], bytes):  # exclude bytes
                        del data2[k]
                data_json = json.dumps(data2, indent=2)

            return info_dialog(
                self,
                _c("Debug"),
                text,
                det_msg=data_json,
                show=True,
            )

    def get_card_pixmap(self, library, size=(40, 30)):
        """
        Generate a card image for a library

        :param library:
        :param size:
        :return:
        """
        card_pixmap_cache_id = (
            f'card_website_{library["websiteId"]}_{size[0]}x{size[1]}'
        )
        card_pixmap = QPixmapCache.find(card_pixmap_cache_id)
        if not QPixmapCache.find(card_pixmap_cache_id):
            svg_root = etree.fromstring(self.resources[PluginImages.Card])
            if not DEMO_MODE:
                stop1 = svg_root.find('.//stop[@class="stop1"]', svg_root.nsmap)
                stop1.attrib["stop-color"] = library["settings"]["primaryColor"]["hex"]
                stop2 = svg_root.find('.//stop[@class="stop2"]', svg_root.nsmap)
                stop2.attrib["stop-color"] = library["settings"]["secondaryColor"][
                    "hex"
                ]
            card_pixmap = svg_to_pixmap(etree.tostring(svg_root), size=size)
            QPixmapCache.insert(card_pixmap_cache_id, card_pixmap)
        return card_pixmap

    def unhandled_exception(self, err, msg=None):
        """
        Use this to handle unexpected job/sync errors instead of letting calibre's main window do it,
        so that it doesn't go behind our modal plugin window.

        Adapted from
        https://github.com/kovidgoyal/calibre/blob/ffcaf382a277bd980771d36ce915cc451ef30b25/src/calibre/gui2/main_window.py#L216-L243

        :param err:
        :param msg:
        :return:
        """
        if not err:
            return
        if err is KeyboardInterrupt:
            return
        import traceback

        try:
            sio = PolyglotStringIO(errors="replace")
            try:
                from calibre.debug import print_basic_debug_info

                print_basic_debug_info(out=sio)
            except:  # noqa
                pass
            traceback.print_exception(err.__class__, err, err.__traceback__, file=sio)
            fe = sio.getvalue()
            if msg:
                msg = "<b>%s</b>: %s" % (err.__class__.__name__, msg)
            else:
                msg = "<b>%s</b>" % err.__class__.__name__

            if type(err) in (
                LibbyConnectionError,
                OverDriveConnectionError,
            ):
                msg += (
                    "<p>"
                    + _("Check your connection or retry in a few minutes.")
                    + "</p>"
                )
            elif isinstance(err, LibbyClientError):
                msg += f"<p>{err.msg}</p>"

            return error_dialog(
                self, _c("Unhandled exception"), msg, det_msg=fe, show=True
            )
        except Exception as err:
            logger.exception(err)

    def create_hold(self, media, card):
        # create the hold
        description = _("Placing hold on {book}").format(
            book=as_unicode(get_media_title(media), errors="replace")
        )
        callback = Dispatcher(self.hold_created)
        job = ThreadedJob(
            "overdrive_libby_create_hold",
            description,
            gui_create_hold,
            (self.gui, self.client, media, card),
            {},
            callback,
            max_concurrent_count=2,
            killable=False,
        )
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(description, 3000)

    def hold_created(self, job):
        # callback after hold is created
        if job.failed:
            return self.unhandled_exception(
                job.exception, msg=_("Failed to create hold")
            )
        self.hold_added.emit(job.result)
        self.gui.status_bar.show_message(job.description + " " + _c("finished"), 5000)

    def get_available_sites(self, media, model: LibbyModel):
        # Use by search
        available_sites = []
        for k, site in media.get("siteAvailabilities", {}).items():
            site["advantageKey"] = k
            if site.get("ownedCopies") or site.get("isAvailable"):
                _card = next(
                    iter(model.get_cards_for_library_key(site["advantageKey"])),
                    None,
                )
                site["__card"] = _card
                library = model.get_library(model.get_website_id(_card))
                site["__library"] = library
                available_sites.append(site)
        return sorted(
            available_sites,
            key=cmp_to_key(OverDriveClient.sort_availabilities),
            reverse=True,
        )


class BookPreviewDialog(QDialog):
    def __init__(
        self,
        parent: BaseDialogMixin,
        gui,
        resources: Dict,
        client: OverDriveClient,
        media: Dict,
    ):
        super().__init__(parent)
        self.gui = gui
        self.resources = resources
        self.client = client
        self.media = media
        self.setWindowFlag(Qt.Sheet)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(_c("Book details"))

        self._media_info_thread = QThread()

        layout = QGridLayout()
        self.layout = layout
        self.setLayout(layout)
        self.widget_row_pos = 0

        title = f"<b>{get_media_title(media)}</b>"
        if media.get("subtitle"):
            title += f': {media["subtitle"]}'
        self.title_lbl = QLabel(title)
        self.title_lbl.setWordWrap(True)
        curr_font = self.title_lbl.font()
        curr_font.setPointSizeF(curr_font.pointSizeF() * 1.2)
        self.title_lbl.setFont(curr_font)
        layout.addWidget(self.title_lbl, 0, 0, 1, 2)
        self.widget_row_pos += 1

        self.image_lbl = ClickableQLabel(self)
        self.image_lbl.setPixmap(self.resources[PluginImages.CoverPlaceholder])
        self.image_lbl.setScaledContents(True)
        self.image_lbl.setMaximumSize(150, 200)
        layout.addWidget(self.image_lbl, self.widget_row_pos, 0, alignment=Qt.AlignTop)

        media_type = media.get("type", {}).get("id", "")
        type_lbl = QLabel(LOAN_TYPE_TRANSLATION.get(media_type, media_type))
        layout.addWidget(type_lbl, self.widget_row_pos + 1, 0, alignment=Qt.AlignTop)

        self.close_btn = DefaultQPushButton(
            _c("Close"), self.resources[PluginImages.Cancel], self
        )
        self.close_btn.setMinimumWidth(parent.min_button_width)
        self.close_btn.clicked.connect(lambda: self.reject())
        layout.addWidget(
            self.close_btn, self.widget_row_pos + 2, 0, 1, 2, alignment=Qt.AlignCenter
        )

        if not self._media_info_thread.isRunning():
            self._media_info_thread = self._get_media_info_thread(
                self.client, self.media["id"], self.parent().media_cache
            )
            self.setCursor(Qt.WaitCursor)
            self._media_info_thread.start()

    def _get_media_info_thread(self, overdrive_client, title_id, media_cache):
        thread = QThread()
        worker = OverDriveMediaWorker()
        worker.setup(overdrive_client, title_id, media_cache)
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(media):
            try:
                self.unsetCursor()
                if media.get(worker.cover_data_key):
                    cover_pixmap = QPixmap()
                    cover_pixmap.loadFromData(media[worker.cover_data_key])
                    self.image_lbl.setPixmap(cover_pixmap)

                self.image_lbl.doubleClicked.connect(
                    lambda: self.parent().display_debug("Media", media)
                )

                det_layout = QVBoxLayout()
                det_widget = QWidget(self)
                det_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                det_widget.setLayout(det_layout)
                det_scroll_area = QScrollArea()
                det_scroll_area.setAlignment(Qt.AlignTop)
                det_scroll_area.setBackgroundRole(QPalette.Window)
                det_scroll_area.setFrameShadow(QFrame.Plain)
                det_scroll_area.setFrameShape(QFrame.StyledPanel)
                det_scroll_area.setWidgetResizable(True)
                det_scroll_area.setMinimumWidth(480)
                det_scroll_area.setWidget(det_widget)

                detail_labels = []
                creators = OrderedDict()
                # group creators by role
                for creator in media.get("creators", []):
                    creators.setdefault(creator["role"], []).append(creator["name"])
                for role, creator_names in creators.items():
                    detail_labels.append(
                        QLabel(
                            "<b>"
                            + CREATOR_ROLE_TRANSLATION.get(role, _c(role))
                            + f'</b>: {", ".join(creator_names)}'
                        )
                    )
                if media.get("series"):
                    detail_labels.append(
                        QLabel(
                            "<b>"
                            + ngettext_c("Series", "Series", 1)
                            + f'</b>: {media["series"]}'
                        )
                    )
                media_formats = media.get("formats", []) or self.media.get(
                    "formats", []
                )
                if media_formats:
                    identifiers = {}

                    isbn = OverDriveClient.extract_isbn(
                        media_formats,
                        [
                            LibbyClient.get_loan_format(
                                media if media.get("formats") else self.media,
                                raise_if_not_downloadable=False,
                            )
                        ],
                    ) or OverDriveClient.extract_isbn(media_formats, [])
                    if isbn:
                        identifiers["isbn"] = isbn
                    asin = OverDriveClient.extract_asin(media_formats)
                    if asin:
                        identifiers["amazon"] = asin
                    if identifiers:
                        # ref https://github.com/kovidgoyal/calibre/blob/522b23db12f25b43a2a6cfd76c3143aee5bd4211/src/calibre/utils/formatter_functions.py#L2328-L2347
                        a = partial(prepare_string_for_xml, attribute=True)
                        links = [
                            f'<a href="{a(url)}" title="{a(id_typ)}:{a(id_val)}">{prepare_string_for_xml(name)}</a>'
                            for name, id_typ, id_val, url in urls_from_identifiers(
                                identifiers, sort_results=True
                            )
                        ]
                        identifiers_lbl = QLabel(
                            "<b>" + _c("Ids") + "</b>: " + ", ".join(links)
                        )
                        identifiers_lbl.setTextFormat(Qt.RichText)
                        identifiers_lbl.setOpenExternalLinks(True)
                        detail_labels.append(identifiers_lbl)

                for lang in media.get("languages", []):
                    detail_labels.append(
                        QLabel("<b>" + _c("Language") + f'</b>: {lang["name"]}')
                    )
                if media.get("publisher", {}).get("name"):
                    detail_labels.append(
                        QLabel(
                            "<b>"
                            + _c("Publisher")
                            + f'</b>: {media["publisher"]["name"]}'
                        )
                    )
                publish_date_txt = (
                    self.media.get("publishDate")
                    or media.get("publishDate")
                    or media.get("estimatedReleaseDate")
                )
                if publish_date_txt:
                    pub_date = dt_as_local(LibbyClient.parse_datetime(publish_date_txt))
                    detail_labels.append(
                        QLabel(
                            "<b>"
                            + _c("Published")
                            + f'</b>: {format_date(pub_date, tweaks["gui_timestamp_display_format"])}'
                        )
                    )
                if media.get("type", {}).get("id", "") == LibbyMediaTypes.Audiobook:
                    media_formats = self.media.get("formats") or media.get("formats")
                    duration = next(
                        iter(
                            [f["duration"] for f in media_formats if f.get("duration")]
                        ),
                        None,
                    )
                    if duration:
                        detail_labels.append(
                            QLabel("<b>" + _("Duration") + f"</b>: {duration}")
                        )
                if media.get("subjects"):
                    subjects = [s["name"] for s in media["subjects"]]
                    detail_labels.append(
                        QLabel("<b>" + _("Subjects") + f'</b>: {", ".join(subjects)}')
                    )
                if media.get("starRating") and media.get("starRatingCount"):
                    ratings_layout = QHBoxLayout()
                    ratings_layout.addWidget(QLabel("<b>" + _("Rating") + "</b>: "))
                    ratings_lbl = QLabel(f'{rating_to_stars(media["starRating"])}')
                    ratings_lbl.setToolTip(
                        f'{media["starRating"]}/5 ({media["starRatingCount"]})'
                    )
                    ratings_lbl.setFont(QFont(rating_font()))
                    ratings_layout.addWidget(ratings_lbl)
                    ratings_layout.addWidget(QLabel(f'({media["starRatingCount"]})'), 1)
                    detail_labels.append(ratings_layout)

                description = (
                    media.get("description")
                    or media.get("fullDescription")
                    or media.get("shortDescription")
                )
                if description:
                    description_lbl = QLabel(description)
                    description_lbl.setTextFormat(Qt.RichText)
                    detail_labels.append(description_lbl)

                for widget in detail_labels:
                    if isinstance(widget, QLabel):
                        widget.setWordWrap(True)
                        det_layout.addWidget(widget, alignment=Qt.AlignTop)
                    elif isinstance(widget, QLayout):
                        det_layout.addLayout(widget)

                self.layout.addWidget(det_scroll_area, self.widget_row_pos, 1, 2, 1)
            except RuntimeError as runtime_err:
                # most likely because the UI has been closed before fetch was completed
                logger.warning("Error displaying media results: %s", runtime_err)
            finally:
                thread.quit()

        def errored_out(err: Exception):
            try:
                self.unsetCursor()
            except RuntimeError:
                pass
            finally:
                thread.quit()
            raise err

        worker.finished.connect(lambda media: loaded(media))
        worker.errored.connect(lambda err: errored_out(err))

        return thread
