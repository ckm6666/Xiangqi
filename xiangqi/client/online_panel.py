"""联机大厅：登录/注册、房间与排位入口。

流程：
    1. 输入服务器地址、昵称与密码，登录或注册；
    2. REST 认证成功后拿到令牌，切换到大厅表单；
    3. 创建/加入房间或排位匹配时，使用令牌建立 WebSocket 并认证；
    4. 收到第一份 game_state 后把会话交给主窗口。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional
from urllib.parse import urlsplit

from PySide6.QtCore import QSize, Signal, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.avatars import (
    pixmap_from_png_bytes,
    render_default_avatar,
)
from xiangqi.client.config import AppConfig
from xiangqi.client.net.auth_api import AuthApi
from xiangqi.client.net.profile_api import ProfileApi
from xiangqi.client.net.websocket_transport import WebSocketTransport
from xiangqi.client.sessions.online import (
    ACTION_CREATE,
    ACTION_LOBBY,
    ACTION_QUEUE,
    OnlineGameSession,
)
from xiangqi.client.sound_control import SoundButton
from xiangqi.client.ui_theme import (
    ONLINE_BACKDROP_SPEC,
    InkBackdrop,
    RicePaperCard,
    make_ink_divider,
)
from xiangqi.shared.profile import DEFAULT_AVATAR_IDS, title_for_rating

logger = logging.getLogger(__name__)

#: 固定公网入口（Tailscale Funnel 代理本机 8765 端口）。
#: 本机离线调试时可在大厅中手动改回 ws://127.0.0.1:8765/api/v1/ws。
DEFAULT_WS_URL = "wss://gomoku-host.taild407ad.ts.net:8443/api/v1/ws"


class OnlinePanel(InkBackdrop):
    """联机大厅与账号状态。"""

    session_ready = Signal(object)
    back_requested = Signal()
    profile_requested = Signal()
    friends_requested = Signal()
    leaderboard_requested = Signal()
    challenge_received = Signal(str, str)
    challenge_cancelled = Signal(str, str)

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        parent: Optional[QWidget] = None,
        *,
        transport_factory: Optional[Callable[[QWidget], object]] = None,
        auth_factory: Optional[Callable[[QWidget], object]] = None,
    ) -> None:
        super().__init__(parent, spec=ONLINE_BACKDROP_SPEC)
        self.setObjectName("onlinePage")
        self._config = config or AppConfig()
        self._transport_factory = transport_factory or WebSocketTransport
        self._auth_factory = auth_factory or AuthApi
        self._session: Optional[OnlineGameSession] = None
        self._lobby_session: Optional[OnlineGameSession] = None
        self._busy = False
        self._auth_busy = False
        self._queued = False
        self._token = ""
        self._nickname = ""
        self._rating = 1200
        self._profile_info: dict = {}
        self._ws_url = ""
        self._pending_ws_url = ""

        self._auth_api = self._auth_factory(self)
        self._auth_api.authenticated.connect(self._on_authenticated)
        self._auth_api.failed.connect(self._on_auth_failed)
        avatar_signal = getattr(self._auth_api, "avatar_known", None)
        if avatar_signal is not None:
            avatar_signal.connect(self._on_avatar_known)
        self._profile_api = ProfileApi(self)
        self._profile_api.avatar_loaded.connect(
            self._on_account_avatar_loaded
        )
        self._build_ui()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        utility_row = QHBoxLayout()
        self.back_button = QPushButton("返回主菜单", self)
        self.back_button.setObjectName("lobbyBackButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.setMinimumSize(116, 38)
        self.back_button.clicked.connect(self._on_back)
        utility_row.addWidget(self.back_button)
        utility_row.addStretch(1)
        self.sound_button = SoundButton(self)
        utility_row.addWidget(
            self.sound_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        layout.addLayout(utility_row)
        layout.addStretch(1)

        card = RicePaperCard(self, seal_text="联", opaque=True)
        card.setObjectName("onlineCard")
        card.setFixedWidth(580)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(42, 30, 42, 30)
        card_layout.setSpacing(10)

        title = QLabel("联机对战", card)
        title.setObjectName("onlineTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(
            "排位匹配，或自建房邀请好友对战", card
        )
        subtitle.setObjectName("onlineSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        divider = QLabel(card)
        divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
        divider.setPixmap(
            make_ink_divider(300, 15, dpr=card.devicePixelRatioF())
        )
        card_layout.addWidget(divider)
        card_layout.addSpacing(4)

        self.login_form = QWidget(card)
        login_layout = QVBoxLayout(self.login_form)
        login_layout.setContentsMargins(0, 0, 0, 0)
        login_layout.setSpacing(8)

        self.url_input = self._add_field(
            login_layout,
            self.login_form,
            "服务器",
            self._default_url(),
            "ws://127.0.0.1:8765/api/v1/ws（本机）",
        )
        self.name_input = self._add_field(
            login_layout,
            self.login_form,
            "昵称",
            "",
            "2-20 个字符",
        )
        self.name_input.setMaxLength(20)
        self.password_input = self._add_field(
            login_layout,
            self.login_form,
            "密码",
            "",
            "至少 6 位",
            password=True,
        )
        self.password_input.setMaxLength(128)

        # 输入昵称与密码后直接按 Enter 即可登录，无需再点按钮。
        for field in (
            self.url_input,
            self.name_input,
            self.password_input,
        ):
            field.returnPressed.connect(self._on_login)

        auth_buttons = QHBoxLayout()
        auth_buttons.setContentsMargins(0, 0, 0, 0)
        auth_buttons.setSpacing(8)
        self.login_button = QPushButton("登录", self.login_form)
        self.login_button.setObjectName("menuPrimaryButton")
        self.login_button.setMinimumHeight(46)
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.setAutoDefault(False)
        self.login_button.clicked.connect(self._on_login)

        self.register_button = QPushButton("注册", self.login_form)
        self.register_button.setObjectName("menuButton")
        self.register_button.setMinimumHeight(46)
        self.register_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.register_button.setAutoDefault(False)
        self.register_button.clicked.connect(self._on_register)

        auth_buttons.addWidget(self.login_button, 1)
        auth_buttons.addWidget(self.register_button, 1)
        login_layout.addLayout(auth_buttons)

        login_help = QLabel(
            "首次使用请先注册；昵称即登录账号。\n"
            "默认使用公网入口，本机调试时可改为 ws://127.0.0.1:8765/api/v1/ws",
            self.login_form,
        )
        login_help.setObjectName("onlineSubtitle")
        login_help.setWordWrap(True)
        login_help.setAlignment(Qt.AlignmentFlag.AlignCenter)
        login_layout.addWidget(login_help)
        card_layout.addWidget(self.login_form)

        self.lobby_form = QWidget(card)
        lobby_layout = QVBoxLayout(self.lobby_form)
        lobby_layout.setContentsMargins(0, 0, 0, 0)
        lobby_layout.setSpacing(11)

        account_row = QHBoxLayout()
        account_row.setContentsMargins(0, 0, 0, 2)
        account_row.setSpacing(10)

        self.avatar_button = QPushButton(self.lobby_form)
        self.avatar_button.setObjectName("avatarButton")
        self.avatar_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.avatar_button.setFixedSize(60, 60)
        self.avatar_button.setIconSize(QSize(52, 52))
        self.avatar_button.setToolTip("查看个人信息")
        self.avatar_button.setAccessibleName("个人信息头像")
        self.avatar_button.clicked.connect(self._on_profile_requested)
        self._set_account_avatar(
            render_default_avatar(
                DEFAULT_AVATAR_IDS[0], 52, dpr=self.devicePixelRatioF()
            )
        )

        account_text = QVBoxLayout()
        account_text.setContentsMargins(0, 0, 0, 0)
        account_text.setSpacing(4)
        self.account_label = QLabel("", self.lobby_form)
        self.account_label.setObjectName("onlineRoomTitle")
        self.account_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(6)
        self.profile_button = QPushButton("个人信息", self.lobby_form)
        self.profile_button.setObjectName("lobbyNavButton")
        self.profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_button.setToolTip(
            "查看头像、战绩、称号与成就"
        )
        self.profile_button.clicked.connect(self._on_profile_requested)

        self.friends_button = QPushButton("好友", self.lobby_form)
        self.friends_button.setObjectName("lobbyNavButton")
        self.friends_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.friends_button.setToolTip("好友列表与好友申请")
        self.friends_button.clicked.connect(self._on_friends_requested)

        self.leaderboard_button = QPushButton(
            "排行榜", self.lobby_form
        )
        self.leaderboard_button.setObjectName("lobbyNavButton")
        self.leaderboard_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.leaderboard_button.setToolTip(
            "按积分与称号排序，点击头像查看资料"
        )
        self.leaderboard_button.clicked.connect(
            self._on_leaderboard_requested
        )

        for button in (
            self.profile_button,
            self.friends_button,
            self.leaderboard_button,
        ):
            button.setMinimumHeight(38)
            nav_row.addWidget(button, 1)
        account_text.addWidget(self.account_label)
        account_text.addLayout(nav_row)

        account_row.addWidget(self.avatar_button)
        account_row.addLayout(account_text, 1)
        lobby_layout.addLayout(account_row)

        ranked_row = QHBoxLayout()
        ranked_row.setContentsMargins(0, 2, 0, 2)
        ranked_row.setSpacing(8)
        self.ranked_button = QPushButton("排位匹配", self.lobby_form)
        self.ranked_button.setObjectName("menuPrimaryButton")
        self.ranked_button.setMinimumHeight(56)
        self.ranked_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ranked_button.setAutoDefault(False)
        self.ranked_button.setToolTip(
            "按排位分相近优先匹配；胜负会更新积分与称号"
        )
        self.ranked_button.clicked.connect(self._on_ranked)

        self.cancel_queue_button = QPushButton(
            "取消匹配", self.lobby_form
        )
        self.cancel_queue_button.setObjectName("menuButton")
        self.cancel_queue_button.setMinimumHeight(56)
        self.cancel_queue_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.cancel_queue_button.setAutoDefault(False)
        self.cancel_queue_button.setToolTip("退出排位队列")
        self.cancel_queue_button.clicked.connect(self._on_cancel_queue)
        self.cancel_queue_button.setVisible(False)

        ranked_row.addWidget(self.ranked_button, 2)
        ranked_row.addWidget(self.cancel_queue_button, 1)
        lobby_layout.addLayout(ranked_row)

        self.create_button = QPushButton("自建房", self.lobby_form)
        self.create_button.setObjectName("menuButton")
        self.create_button.setMinimumHeight(50)
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.setAutoDefault(False)
        self.create_button.setToolTip(
            "创建房间后可直接邀请好友，无需房间号"
        )
        self.create_button.clicked.connect(self._on_create)
        lobby_layout.addWidget(self.create_button)

        self.logout_button = QPushButton("退出登录", self.lobby_form)
        self.logout_button.setObjectName("lobbySecondaryButton")
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.setMinimumHeight(40)
        self.logout_button.clicked.connect(self._on_logout)
        lobby_layout.addSpacing(2)
        lobby_layout.addWidget(self.logout_button)
        self.lobby_form.setVisible(False)
        card_layout.addWidget(self.lobby_form)

        self.status_label = QLabel("", card)
        self.status_label.setObjectName("onlineStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(20)
        self.status_label.setProperty("error", "false")
        card_layout.addWidget(self.status_label)

        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def _add_field(
        self,
        layout: QVBoxLayout,
        parent: QWidget,
        label_text: str,
        value: str,
        placeholder: str,
        *,
        password: bool = False,
    ) -> QLineEdit:
        label = QLabel(label_text, parent)
        label.setObjectName("formLabel")
        field = QLineEdit(value, parent)
        field.setObjectName("onlineInput")
        field.setPlaceholderText(placeholder)
        field.setMinimumHeight(36)
        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        label.setBuddy(field)
        layout.addWidget(label)
        layout.addWidget(field)
        return field

    def _default_url(self) -> str:
        configured = self._config.ws_base_url
        return configured or DEFAULT_WS_URL

    @property
    def token(self) -> str:
        """当前登录令牌；未登录时为空。"""
        return self._token

    @property
    def nickname(self) -> str:
        return self._nickname

    @property
    def rating(self) -> int:
        return self._rating

    @property
    def profile_info(self) -> dict:
        """最近一次从服务端读取的完整资料。"""
        return dict(self._profile_info)

    @property
    def http_base_url(self) -> str:
        """由 WebSocket 地址推导的 REST 地址。"""
        url = self._ws_url or self.url_input.text().strip()
        return self._http_base(url) if url else ""

    @staticmethod
    def _http_base(ws_url: str) -> str:
        parts = urlsplit(ws_url)
        scheme = "https" if parts.scheme == "wss" else "http"
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return f"{scheme}://{host}{port}"

    def _update_account_label(self) -> None:
        if not self._nickname:
            self.account_label.setText("")
            return
        self.account_label.setText(
            f"已登录：{self._nickname} · {self._rating}分 · "
            f"{title_for_rating(self._rating)}"
        )

    def _set_account_avatar(self, pixmap: QPixmap) -> None:
        self.avatar_button.setIcon(QIcon(pixmap))

    def _on_avatar_known(self, avatar_id: str) -> None:
        """登录响应携带头像标识后立即渲染（自定义头像异步拉取）。"""
        if not self._token or not isinstance(avatar_id, str):
            return
        if avatar_id.startswith("default:"):
            self._set_account_avatar(
                render_default_avatar(
                    avatar_id, 52, dpr=self.devicePixelRatioF()
                )
            )
            return
        if avatar_id == "custom" and self._nickname:
            self._profile_api.fetch_avatar(
                self.http_base_url, self._nickname
            )

    def _on_account_avatar_loaded(self, data: bytes) -> None:
        if not self._token:
            return
        pixmap = pixmap_from_png_bytes(
            data, 52, dpr=self.devicePixelRatioF()
        )
        if pixmap is not None:
            self._set_account_avatar(pixmap)

    def _on_profile_requested(self) -> None:
        if not self._token:
            self._set_status("请先登录", True)
            return
        self.profile_requested.emit()

    def _on_friends_requested(self) -> None:
        if not self._token:
            self._set_status("请先登录", True)
            return
        self.friends_requested.emit()

    def _on_leaderboard_requested(self) -> None:
        if not self._token:
            self._set_status("请先登录", True)
            return
        self.leaderboard_requested.emit()

    def apply_profile(
        self,
        data: dict,
        avatar_pixmap: Optional[QPixmap] = None,
    ) -> None:
        """把个人资料窗口的结果同步回大厅。"""
        if not isinstance(data, dict):
            return
        self._profile_info = dict(data)
        rating = data.get("rating")
        if isinstance(rating, int) and not isinstance(rating, bool):
            self._rating = rating
        self._update_account_label()
        if avatar_pixmap is not None:
            self._set_account_avatar(avatar_pixmap)
        elif isinstance(data.get("avatar"), str):
            self._set_account_avatar(
                render_default_avatar(
                    data["avatar"],
                    52,
                    dpr=self.devicePixelRatioF(),
                )
            )
        if isinstance(data.get("friends"), list):
            self._profile_info["friends"] = list(data["friends"])

    # ------------------------------------------------------------------
    # 登录 / 注册
    # ------------------------------------------------------------------
    def _on_login(self) -> None:
        self._authenticate("login")

    def _on_register(self) -> None:
        self._authenticate("register")

    def _authenticate(self, action: str) -> None:
        if self._auth_busy:
            return
        url = self.url_input.text().strip()
        nickname = self.name_input.text().strip()
        password = self.password_input.text()
        if not (url.startswith("ws://") or url.startswith("wss://")):
            self._set_status("服务器地址必须是 ws:// 或 wss:// URL", True)
            return
        if not nickname:
            self._set_status("请填写昵称", True)
            return
        if not password:
            self._set_status("请填写密码", True)
            return

        self._pending_ws_url = url
        self._set_auth_busy(True)
        self._set_status(
            "正在登录…" if action == "login" else "正在注册…"
        )
        base_url = self._http_base(url)
        if action == "login":
            self._auth_api.login(base_url, nickname, password)
        else:
            self._auth_api.register(base_url, nickname, password)

    def _on_authenticated(
        self,
        token: str,
        nickname: str,
        rating: int,
    ) -> None:
        ws_url = self._pending_ws_url or self.url_input.text().strip()
        self.apply_auth(token, nickname, rating, ws_url=ws_url)
        self._set_status("登录成功")

    def _on_auth_failed(self, message: str) -> None:
        self._set_auth_busy(False)
        self._set_status(f"登录失败：{message}", True)

    def apply_auth(
        self,
        token: str,
        nickname: str,
        rating: int,
        *,
        ws_url: Optional[str] = None,
    ) -> None:
        """认证成功（或测试注入）后切换到大厅表单。"""
        self._token = token
        self._nickname = nickname
        self._rating = int(rating)
        self._queued = False
        self._profile_info = {}
        if ws_url:
            self._ws_url = ws_url
        elif not self._ws_url:
            self._ws_url = self.url_input.text().strip()
        self._update_account_label()
        self._set_account_avatar(
            render_default_avatar(
                DEFAULT_AVATAR_IDS[0],
                52,
                dpr=self.devicePixelRatioF(),
            )
        )
        self._set_auth_busy(False)
        self.login_form.setVisible(False)
        self.lobby_form.setVisible(True)
        self._set_busy(False)
        self._ensure_lobby()

    def ensure_lobby_connection(self) -> None:
        """回到联机大厅时确保在线监听连接存在。"""
        self._ensure_lobby()

    def _ensure_lobby(self) -> None:
        """建立常驻大厅连接，用于接收好友挑战。"""
        if self._lobby_session is not None or not self._token:
            return
        url = self._ws_url or self.url_input.text().strip()
        if not (url.startswith("ws://") or url.startswith("wss://")):
            return
        transport = self._transport_factory(self)
        session = OnlineGameSession(
            transport,
            token=self._token,
            action=ACTION_LOBBY,
            parent=None,
        )
        set_parent = getattr(transport, "setParent", None)
        if callable(set_parent):
            set_parent(session)
        session.room_ready.connect(
            lambda current=session: self._on_lobby_ready(current)
        )
        session.challenge_received.connect(
            lambda challenge_id, name: self.challenge_received.emit(
                challenge_id, name
            )
        )
        session.challenge_cancelled.connect(
            lambda challenge_id, reason: self.challenge_cancelled.emit(
                challenge_id, reason
            )
        )
        session.error.connect(
            lambda message, current=session: self._on_lobby_error(
                message, current
            )
        )
        self._lobby_session = session
        session.connect_to(url)

    def respond_challenge(
        self, challenge_id: str, accept: bool
    ) -> bool:
        session = self._lobby_session
        if session is None:
            return False
        return session.respond_challenge(challenge_id, accept)

    def _on_lobby_ready(self, session: OnlineGameSession) -> None:
        if session is not self._lobby_session:
            return
        action = self._session
        self._session = None
        self._lobby_session = None
        self._queued = False
        if action is not None:
            action.shutdown()
            action.deleteLater()
        self._set_busy(False)
        self._sync_queue_controls()
        self._set_status("挑战已接受，正在进入对局…")
        self.session_ready.emit(session)

    def _on_lobby_error(
        self,
        message: str,
        source: Optional[OnlineGameSession] = None,
    ) -> None:
        if source is not None and source is not self._lobby_session:
            return
        if source is not None and source.connected:
            # 认证失败/挑战失效等服务器提示不应关闭常驻大厅连接。
            self._set_status(f"大厅提示：{message}", True)
            return
        session = self._lobby_session
        self._lobby_session = None
        if session is not None:
            session.shutdown()
            session.deleteLater()
        if self._session is None and not self._busy:
            self._set_status(f"大厅连接已断开：{message}", True)

    def update_account_rating(self, rating: int) -> None:
        """排位赛结束后同步大厅显示的积分与称号。"""
        self._rating = int(rating)
        self._update_account_label()

    def _on_logout(self) -> None:
        self.reset()
        self._token = ""
        self._nickname = ""
        self._rating = 1200
        self._profile_info = {}
        self._ws_url = ""
        self.password_input.clear()
        self.account_label.setText("")
        self._set_account_avatar(
            render_default_avatar(
                DEFAULT_AVATAR_IDS[0],
                52,
                dpr=self.devicePixelRatioF(),
            )
        )
        self.lobby_form.setVisible(False)
        self.login_form.setVisible(True)
        self._set_auth_busy(False)
        self._set_status("已退出登录")

    # ------------------------------------------------------------------
    # 房间 / 排位
    # ------------------------------------------------------------------
    def _on_create(self) -> None:
        self._start(ACTION_CREATE)

    def _on_ranked(self) -> None:
        if self._session is not None or self._busy:
            return
        self._queued = True
        if not self._start(ACTION_QUEUE):
            self._queued = False

    def _on_cancel_queue(self) -> None:
        """取消排位匹配：通知服务端离开队列并关闭连接。"""
        session = self._session
        if session is None or not self._queued:
            return
        self._session = None
        self._queued = False
        try:
            session.cancel_queue()
        finally:
            session.deleteLater()
        self._set_busy(False)
        self._sync_queue_controls()
        self._set_status("已取消排位匹配")
        self.ranked_button.setFocus()

    def _on_back(self) -> None:
        self.reset()
        self.back_requested.emit()

    def _start(self, action: str) -> bool:
        if self._session is not None or self._busy:
            return False
        if not self._token:
            self._set_status("请先登录", True)
            return False

        url = self._ws_url or self.url_input.text().strip()
        if not (url.startswith("ws://") or url.startswith("wss://")):
            self._set_status("服务器地址必须是 ws:// 或 wss:// URL", True)
            return False

        self._ensure_lobby()
        self._set_busy(True)
        self._set_status("正在连接服务器…")
        transport = self._transport_factory(self)
        session = OnlineGameSession(
            transport,
            token=self._token,
            action=action,
            parent=None,
        )
        # 传输层随会话一起销毁，取消匹配/连接失败时不残留子对象。
        set_parent = getattr(transport, "setParent", None)
        if callable(set_parent):
            set_parent(session)
        session.room_ready.connect(
            lambda current=session: self._on_ready(current)
        )
        session.queue_status.connect(
            lambda message, current=session: self._on_queue_status(
                message, current
            )
        )
        session.error.connect(
            lambda message, current=session: self._on_error(
                message, current
            )
        )
        self._session = session
        self._sync_queue_controls()
        session.connect_to(url)
        return True

    def _on_ready(self, session: OnlineGameSession) -> None:
        if session is not self._session:
            return
        self._session = None
        self._queued = False
        self._set_busy(False)
        self._sync_queue_controls()
        self._set_status("对局已连接")
        self.session_ready.emit(session)

    def _on_queue_status(
        self,
        message: str,
        source: Optional[OnlineGameSession] = None,
    ) -> None:
        if self._session is None:
            return
        if source is not None and source is not self._session:
            return
        self._queued = True
        self._sync_queue_controls()
        self._set_status(message)

    def _on_error(
        self,
        message: str,
        source: Optional[OnlineGameSession] = None,
    ) -> None:
        session = self._session
        if session is None:
            return
        if source is not None and source is not session:
            return
        self._session = None
        self._queued = False
        session.shutdown()
        session.deleteLater()
        self._set_busy(False)
        self._sync_queue_controls()
        self._set_status(f"连接失败：{message}", True)

    def _sync_queue_controls(self) -> None:
        queued = self._queued and self._session is not None
        self.cancel_queue_button.setVisible(queued)
        self.cancel_queue_button.setEnabled(queued)
        self.ranked_button.setEnabled(not self._busy and not queued)
        self.ranked_button.setText("匹配中…" if queued else "排位匹配")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.create_button.setEnabled(not busy)
        self.logout_button.setEnabled(not busy)
        self.profile_button.setEnabled(not busy)
        self.friends_button.setEnabled(not busy)
        self.leaderboard_button.setEnabled(not busy)
        self.avatar_button.setEnabled(not busy)
        self._sync_queue_controls()

    def _set_auth_busy(self, busy: bool) -> None:
        self._auth_busy = busy
        for widget in (
            self.url_input,
            self.name_input,
            self.password_input,
        ):
            widget.setEnabled(not busy)
        self.login_button.setEnabled(not busy)
        self.register_button.setEnabled(not busy)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        error_value = "true" if error else "false"
        if self.status_label.property("error") != error_value:
            self.status_label.setProperty("error", error_value)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            self.status_label.update()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def reset(self) -> None:
        session = self._session
        lobby = self._lobby_session
        self._session = None
        self._lobby_session = None
        self._queued = False
        if session is not None:
            session.shutdown()
            session.deleteLater()
        if lobby is not None:
            lobby.shutdown()
            lobby.deleteLater()
        self._set_busy(False)
        self._sync_queue_controls()
        self._set_status("")

    def shutdown(self) -> None:
        self.reset()


__all__ = ["OnlinePanel", "DEFAULT_WS_URL"]
