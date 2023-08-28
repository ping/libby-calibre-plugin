#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from typing import Dict
from urllib.parse import urljoin

from calibre.gui2 import open_url
from calibre.utils.config import tweaks
from calibre.utils.date import dt_as_local, format_date
from qt.core import (
    QApplication,
    QCursor,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPalette,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QThread,
    QVBoxLayout,
    QWidget,
    Qt,
)

from .base import BaseDialogMixin
from .widgets import ClickableQLabel, DefaultQPushButton
from .. import DEMO_MODE
from ..compat import _c
from ..libby import LibbyClient
from ..models import LibbyCardsModel, LibbyCardsSortFilterModel
from ..utils import (
    PluginImages,
    obfuscate_date,
    obfuscate_int,
    obfuscate_name,
)
from ..workers import LibbyAuthFormWorker, LibbyVerifyCardWorker

# noinspection PyUnreachableCode
if False:
    load_translations = _ = lambda x=None: x


load_translations()


class CardsDialogMixin(BaseDialogMixin):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)
        self._fetch_auth_form_thread = QThread()

        self.dpr = QApplication.instance().devicePixelRatio()
        self.card_widgets = []
        self.cards_tab_widget = QWidget()
        self.cards_tab_widget_layout = QVBoxLayout()
        self.cards_tab_widget.setSizePolicy(
            QSizePolicy.MinimumExpanding, QSizePolicy.Maximum
        )
        self.cards_tab_widget.setLayout(self.cards_tab_widget_layout)
        self.cards_scroll_area = QScrollArea()
        self.cards_scroll_area.setBackgroundRole(QPalette.Window)
        self.cards_scroll_area.setFrameShadow(QFrame.Plain)
        self.cards_scroll_area.setFrameShape(QFrame.NoFrame)
        self.cards_scroll_area.setWidgetResizable(True)
        self.cards_scroll_area.setWidget(self.cards_tab_widget)

        # Refresh button
        self.first_row_layout = QHBoxLayout()
        self.cards_refresh_btn = DefaultQPushButton(
            _c("Refresh"), self.resources[PluginImages.Refresh], self
        )
        self.cards_refresh_btn.setToolTip(_("Get latest cards"))
        self.cards_refresh_btn.setMinimumWidth(self.min_button_width)
        self.cards_refresh_btn.clicked.connect(self.cards_refresh_btn_clicked)
        btn_size = self.cards_refresh_btn.size()
        self.cards_refresh_btn.setMaximumSize(self.min_button_width, btn_size.height())
        self.first_row_layout.addWidget(self.cards_refresh_btn)

        self.cards_filter_txt = QLineEdit(self)
        self.cards_filter_txt.setMaximumWidth(self.min_button_width)
        self.cards_filter_txt.setClearButtonEnabled(True)
        self.cards_filter_txt.setToolTip(_("Filter by Library, Card"))
        self.cards_filter_txt.textChanged.connect(self.cards_filter_txt_textchanged)
        self.cards_filter_lbl = QLabel(_c("Filter"))
        self.cards_filter_lbl.setBuddy(self.cards_filter_txt)
        self.first_row_layout.addWidget(self.cards_filter_lbl, alignment=Qt.AlignRight)
        self.first_row_layout.addWidget(self.cards_filter_txt, 1)
        self.cards_tab_widget_layout.addLayout(self.first_row_layout)

        self.libby_cards_model = LibbyCardsModel(None, [], self.db)  # model
        self.libby_cards_search_proxy_model = LibbyCardsSortFilterModel(self)
        self.libby_cards_search_proxy_model.setSourceModel(self.libby_cards_model)
        self.libby_cards_search_proxy_model.modelReset.connect(
            self.libby_cards_search_proxy_model_reset, type=Qt.QueuedConnection
        )
        self.libby_cards_search_proxy_model.filter_text_set.connect(
            self.libby_cards_search_proxy_model_reset, type=Qt.QueuedConnection
        )

        self.cards_tab_index = self.add_tab(self.cards_scroll_area, _("Cards"))
        self.sync_starting.connect(self.base_sync_starting_cards)
        self.sync_ended.connect(self.base_sync_ended_cards)

    def base_sync_starting_cards(self):
        self.cards_refresh_btn.setEnabled(False)
        self.libby_cards_model.sync({})

    def base_sync_ended_cards(self, value):
        self.cards_refresh_btn.setEnabled(True)
        self.libby_cards_model.sync(value)

    def cards_filter_txt_textchanged(self, text):
        self.libby_cards_search_proxy_model.set_filter_text(text)

    def cards_refresh_btn_clicked(self):
        self.sync()

    def libby_cards_search_proxy_model_reset(self):
        for card_widget in self.card_widgets:
            self.cards_tab_widget_layout.removeWidget(card_widget)
            card_widget.setParent(None)
            del card_widget
        self.card_widgets = []
        widget_row_pos = self.cards_tab_widget_layout.count()
        for i in range(self.libby_cards_search_proxy_model.rowCount()):
            card = self.libby_cards_search_proxy_model.data(
                self.libby_cards_search_proxy_model.index(i, 0), Qt.UserRole
            )
            library = self.libby_cards_model.get_library(
                self.libby_cards_model.get_website_id(card)
            )
            card_widget = CardWidget(card, library, self, self.cards_tab_widget)
            self.card_widgets.append(card_widget)
            self.cards_tab_widget_layout.addWidget(card_widget)
            widget_row_pos += 1
            if DEMO_MODE:
                break

    def verify_card_btn_clicked(self, card, library, widget):
        if not self._fetch_auth_form_thread.isRunning():
            self._fetch_auth_form_thread = self._get_fetch_auth_form_thread(
                self.client, card, library, widget
            )
            self.widget.verify_card_btn.setEnabled(False)
            self.setCursor(Qt.WaitCursor)
            self._fetch_auth_form_thread.start()

    def _get_fetch_auth_form_thread(
        self, client: LibbyClient, card: Dict, library: Dict, widget
    ) -> QThread:
        self.widget = widget
        self.button = widget.verify_card_btn
        self.card = card
        self.library = library
        thread = QThread()
        worker = LibbyAuthFormWorker()
        worker.setup(client, card)
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(form: Dict):
            thread.quit()
            self.unsetCursor()
            self.button.setEnabled(True)
            if not form:
                open_url(
                    f'https://libbyapp.com/interview/authenticate/card?origination=interview%2Fconfigure%2Fcards%23listLibraryCards&intent=verify&cardId={card["cardId"]}&websiteId={card["library"]["websiteId"]}'
                )
                return
            d = CardVerificationDialog(
                self,
                self.gui,
                self.resources,
                self.client,
                form,
                self.card,
                self.library,
                self.widget,
            )
            d.setModal(True)
            d.open()

        def errored_out(err: Exception):
            self.unsetCursor()
            self.button.setEnabled(True)
            thread.quit()
            raise err

        worker.finished.connect(lambda form: loaded(form))
        worker.errored.connect(lambda err: errored_out(err))

        return thread


class CardWidget(QWidget):
    def __init__(self, card, library, tab: CardsDialogMixin, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.card = card
        self.library = library
        self.tab = tab
        self.resources = self.tab.resources
        layout = QGridLayout()
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)
        widget_row_pos = 0

        # Library Card Icon
        library_card_lbl = QLabel(self)
        card_icon_size = (40, 30)
        card_pixmap = self.tab.get_card_pixmap(
            library, size=tuple([int(tab.dpr * s) for s in card_icon_size])
        )
        card_pixmap.setDevicePixelRatio(tab.dpr)
        library_card_lbl.setPixmap(card_pixmap)
        layout.addWidget(library_card_lbl, widget_row_pos, 0)

        # Library Name
        library_lbl = ClickableQLabel(
            f'{library["name"]} ({card["advantageKey"]})'
            if not DEMO_MODE
            else (
                "Random "
                f'#{obfuscate_int(library["websiteId"], offset=int(library["websiteId"]/2), min_value=1, max_val=999)}'
                f' Library ({obfuscate_name(card["advantageKey"])})'
            )
        )
        curr_font = library_lbl.font()
        curr_font.setPointSizeF(curr_font.pointSizeF() * 1.2)
        library_lbl.setFont(curr_font)
        library_lbl.setStyleSheet("font-weight: bold;")
        library_lbl.doubleClicked.connect(
            lambda: self.tab.display_debug("Library", self.library)
        )
        library_lbl.setContextMenuPolicy(Qt.CustomContextMenu)
        library_lbl.customContextMenuRequested.connect(
            self.library_lbl_context_menu_requested
        )
        library_lbl.setToolTip(_("Right-click for shortcuts"))
        layout.addWidget(library_lbl, widget_row_pos, 1, 1, 2)

        self.verify_card_btn = DefaultQPushButton(
            _("Verify Card"),
            icon=self.tab.resources[PluginImages.Okay],
            parent=self,
        )
        self.verify_card_btn.setMaximumWidth(self.tab.min_button_width)
        self.verify_card_btn.clicked.connect(
            lambda: self.tab.verify_card_btn_clicked(self.card, self.library, self)
        )
        layout.addWidget(
            self.verify_card_btn, widget_row_pos, 2, alignment=Qt.AlignRight
        )
        widget_row_pos += 1

        # Card Name
        card_name = (
            card["cardName"]
            if not DEMO_MODE
            else obfuscate_name(card["cardName"] or "")
        ) or ""
        card_lbl = ClickableQLabel("<b>" + _("Card name") + "</b>: " + card_name)
        card_lbl.setTextFormat(Qt.RichText)
        card_lbl.doubleClicked.connect(
            lambda: self.tab.display_debug("Card", self.card)
        )
        layout.addWidget(card_lbl, widget_row_pos, 0, 1, 2)

        # Card Number
        if card.get("username"):
            card_username = (
                card["username"] if not DEMO_MODE else obfuscate_name(card["username"])
            )
            card_user_lbl = QLabel(
                "<b>" + _("Username/Card number") + "</b>: " + card_username
            )
            card_user_lbl.setTextInteractionFlags(
                Qt.TextSelectableByKeyboard | Qt.TextSelectableByMouse
            )
            layout.addWidget(card_user_lbl, widget_row_pos, 2)
        widget_row_pos += 1

        # Card Created Date
        if card.get("createDate"):
            dt_value = dt_as_local(LibbyClient.parse_datetime(card["createDate"]))
            card_create_lbl = QLabel(
                "<b>"
                + _("Created date")
                + "</b>: "
                + format_date(
                    dt_value
                    if not DEMO_MODE
                    else obfuscate_date(dt_value, year=dt_value.year),
                    tweaks["gui_timestamp_display_format"],
                )
            )
            card_create_lbl.setTextFormat(Qt.RichText)
            layout.addWidget(card_create_lbl, widget_row_pos, 0, 1, 2)

            # Verified Date
            self.card_auth_lbl = QLabel()
            self.card_auth_lbl.setTextFormat(Qt.RichText)
            if card.get("authorizeDate"):
                self.card_auth_lbl.setText(
                    self.format_authorized_date(card["authorizeDate"])
                )
            layout.addWidget(self.card_auth_lbl, widget_row_pos, 2)
            widget_row_pos += 1

        # loans limits
        loans_limit = card.get("limits", {}).get("loan", 0)
        loans_count = card.get("counts", {}).get("loan", 0)
        loans_progressbar = QProgressBar(self)
        loans_progressbar.setFormat(_("Loans") + " %v/%m")
        loans_progressbar.setMinimum(0)
        loans_progressbar.setMaximum(
            loans_limit
            if not DEMO_MODE
            else obfuscate_int(loans_limit, offset=10, min_value=10)
        )
        loans_progressbar.setValue(
            loans_count if not DEMO_MODE else obfuscate_int(loans_count)
        )
        loans_progressbar.setContextMenuPolicy(Qt.CustomContextMenu)
        loans_progressbar.customContextMenuRequested.connect(
            self.loans_progressbar_context_menu_requested
        )
        loans_progressbar.setToolTip(_("Right-click for shortcuts"))
        layout.addWidget(loans_progressbar, widget_row_pos, 0, 1, 4)
        widget_row_pos += 1

        # holds limits
        holds_limit = card.get("limits", {}).get("hold", 0)
        holds_count = card.get("counts", {}).get("hold", 0)
        holds_progressbar = QProgressBar(self)
        holds_progressbar.setFormat(_("Holds") + " %v/%m")
        holds_progressbar.setMinimum(0)
        holds_progressbar.setMaximum(
            holds_limit
            if not DEMO_MODE
            else obfuscate_int(holds_limit, offset=10, min_value=3)
        )
        holds_progressbar.setValue(
            holds_count if not DEMO_MODE else obfuscate_int(holds_count)
        )
        holds_progressbar.setContextMenuPolicy(Qt.CustomContextMenu)
        holds_progressbar.customContextMenuRequested.connect(
            self.holds_progressbar_context_menu_requested
        )
        holds_progressbar.setToolTip(_("Right-click for shortcuts"))
        layout.addWidget(holds_progressbar, widget_row_pos, 0, 1, 4)

    def format_authorized_date(self, authorize_date: str):
        dt_value = dt_as_local(LibbyClient.parse_datetime(authorize_date))
        return (
            "<b>"
            + _("Verified date")
            + "</b>: "
            + format_date(
                dt_value
                if not DEMO_MODE
                else obfuscate_date(dt_value, year=dt_value.year),
                tweaks["gui_timestamp_display_format"],
            )
        )

    def library_lbl_context_menu_requested(self):
        menu = QMenu(self)
        menu.addSection(_("Library"))
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_libby_action.triggered.connect(self.open_libby_library)
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_overdrive_action.triggered.connect(self.open_overdrive_library)
        menu.exec(QCursor.pos())

    def loans_progressbar_context_menu_requested(self):
        menu = QMenu(self)
        menu.addSection(_("Loans"))
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_libby_action.triggered.connect(self.open_libby_loans)
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_overdrive_action.triggered.connect(self.open_overdrive_loans)
        menu.exec(QCursor.pos())

    def holds_progressbar_context_menu_requested(self):
        menu = QMenu(self)
        menu.addSection(_("Holds"))
        view_in_libby_action = menu.addAction(_("View in Libby"))
        view_in_libby_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_libby_action.triggered.connect(self.open_libby_holds)
        view_in_overdrive_action = menu.addAction(_("View in OverDrive"))
        view_in_overdrive_action.setIcon(self.resources[PluginImages.ExternalLink])
        view_in_overdrive_action.triggered.connect(self.open_overdrive_holds)
        menu.exec(QCursor.pos())

    def overdrive_url(self):
        return f'https://{self.library["preferredKey"]}.overdrive.com/'

    def open_libby_library(self):
        open_url(f'https://libbyapp.com/library/{self.library["preferredKey"]}')

    def open_overdrive_library(self):
        open_url(self.overdrive_url())

    def open_libby_loans(self):
        open_url(
            f'https://libbyapp.com/shelf/loans/default,all,{self.library["websiteId"]}'
        )

    def open_libby_holds(self):
        open_url(
            f'https://libbyapp.com/shelf/holds/default,all,{self.library["websiteId"]}'
        )

    def open_overdrive_loans(self):
        open_url(urljoin(self.overdrive_url(), "account/loans"))

    def open_overdrive_holds(self):
        open_url(urljoin(self.overdrive_url(), "account/holds"))


class CardVerificationDialog(QDialog):
    def __init__(
        self,
        parent: CardsDialogMixin,
        gui,
        resources: Dict,
        client: LibbyClient,
        form: Dict,
        card: Dict,
        library: Dict,
        card_widget: CardWidget,
    ):
        super().__init__(parent)
        self.gui = gui
        self.resources = resources
        self.client = client
        self.form = form
        self.card = card
        self.library = library
        self.card_widget = card_widget
        layout = QFormLayout()
        self.setLayout(layout)
        self.setWindowTitle(_("Verify Card"))
        self._verify_card_thread = QThread()

        username_field = form.get("local", {}).get("username", {})
        password_field = form.get("local", {}).get("password", {})

        name_lbl = ClickableQLabel(library["name"])
        name_lbl.setAlignment(Qt.AlignCenter)
        curr_font = name_lbl.font()
        curr_font.setPointSizeF(curr_font.pointSizeF() * 1.1)
        name_lbl.setFont(curr_font)
        name_lbl.setStyleSheet("font-weight: bold;")
        layout.addRow(name_lbl)

        if username_field.get("enabled"):
            self.username_txt = QLineEdit(self)
            self.username_txt.setMinimumWidth(self.parent().min_button_width)
            self.username_txt.setText(card.get("username"))
            self.username_txt.setToolTip(username_field.get("label") or "")
            self.username_txt.setPlaceholderText(username_field.get("label") or "")
            layout.addRow(_("Username/Card number"), self.username_txt)
        if password_field.get("enabled"):
            self.password_txt = QLineEdit(self)
            self.password_txt.setMinimumWidth(self.parent().min_button_width)
            self.password_txt.setEchoMode(QLineEdit.Password)
            self.password_txt.setToolTip(password_field.get("label") or "")
            self.password_txt.setPlaceholderText(password_field.get("label") or "")
            layout.addRow(_("Password"), self.password_txt)

        buttons_layout = QHBoxLayout()
        self.cancel_btn = DefaultQPushButton(
            _c("Cancel"), self.resources[PluginImages.Cancel], self
        )
        self.cancel_btn.clicked.connect(lambda: self.reject())
        buttons_layout.addWidget(self.cancel_btn)

        self.update_btn = DefaultQPushButton(
            _("Sign In"), self.resources[PluginImages.Okay], self
        )
        self.update_btn.clicked.connect(self.update_btn_clicked)
        buttons_layout.addWidget(self.update_btn)
        layout.addRow(buttons_layout)

    def update_btn_clicked(self):
        if not self.username_txt.text():
            return
        if hasattr(self, "password_txt") and not self.password_txt.text():
            return

        if not self._verify_card_thread.isRunning():
            self._verify_card_thread = self._get_verify_card_thread(
                self.client,
                self.card,
                self.username_txt.text(),
                self.password_txt.text() if hasattr(self, "password_txt") else "",
            )
            self.update_btn.setEnabled(False)
            self.setCursor(Qt.WaitCursor)
            self._verify_card_thread.start()

    def _get_verify_card_thread(
        self, client: LibbyClient, card: Dict, username: str, password: str
    ) -> QThread:
        thread = QThread()
        worker = LibbyVerifyCardWorker()
        worker.setup(client, card, username, password)
        worker.moveToThread(thread)
        thread.worker = worker
        thread.started.connect(worker.run)

        def loaded(updated_card: Dict):
            thread.quit()
            self.unsetCursor()
            self.update_btn.setEnabled(True)
            if updated_card and updated_card.get("authorizeDate"):
                self.card_widget.card_auth_lbl.setText(
                    self.card_widget.format_authorized_date(
                        updated_card["authorizeDate"]
                    )
                )
                self.parent().status_bar.showMessage(
                    _('Verified "{library}" card').format(
                        library=updated_card["advantageKey"]
                    ),
                    5000,
                )
            self.accept()

        def errored_out(err: Exception):
            self.unsetCursor()
            self.update_btn.setEnabled(True)
            thread.quit()
            return self.parent().unhandled_exception(err, msg=_("Error verifying card"))

        worker.finished.connect(lambda updated_card: loaded(updated_card))
        worker.errored.connect(lambda err: errored_out(err))

        return thread
