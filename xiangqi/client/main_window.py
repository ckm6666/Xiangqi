"""中国象棋主窗口：主菜单、本地双人对局页与窗口内弹窗。

设计约束（沿用 Gomoku）：
    * 只创建一个原生窗口；菜单/对局都是 QStackedWidget 页面；
    * 终局、确认、提示均为窗口内 ModalOverlay，不使用 QDialog；
    * 界面只读取会话的只读 BoardView，通过 request_* 提交意图；
    * 选中格与合法目标是 UI 叠加状态，不写入领域模型。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPointF, QSettings, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.ai_engine import AIDifficulty
from xiangqi.client.audio import get_audio_manager
from xiangqi.client.board_view import BoardView
from xiangqi.client.board_widget import BoardWidget
from xiangqi.client.chat_widgets import (
    ChatLogPanel,
    EmojiPickerButton,
    PresetCommentButton,
)
from xiangqi.client.config import AppConfig
from xiangqi.client.confirm_dialog import ConfirmDialog
from xiangqi.client.danmaku import DanmakuOverlay
from xiangqi.client.constants import (
    AI_START_DELAY_MS,
    APP_NAME,
    APP_TITLE,
    APP_VERSION,
    RESULT_DIALOG_DELAY_MS,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_SCREEN_MARGIN,
)
from xiangqi.client.friends_overlay import FriendsOverlay
from xiangqi.client.invite_overlay import InviteFriendOverlay
from xiangqi.client.leaderboard_overlay import LeaderboardOverlay
from xiangqi.client.modal_overlay import ModalOverlay, NoticeOverlay
from xiangqi.client.online_panel import OnlinePanel
from xiangqi.client.private_chat_overlay import PrivateChatOverlay
from xiangqi.client.profile_overlay import ProfileOverlay
from xiangqi.client.records import LocalRecordStore
from xiangqi.client.replay_panel import ReplayPanel
from xiangqi.client.result_dialog import ResultDialog, ResultPresentation
from xiangqi.client.sessions import (
    AIGameSession,
    GameSession,
    LocalGameSession,
    OnlineGameSession,
)
from xiangqi.client.sessions.online import (
    STATUS_DISCONNECTED as ONLINE_DISCONNECTED,
    STATUS_FINISHED as ONLINE_FINISHED,
    STATUS_PLAYING as ONLINE_PLAYING,
    STATUS_WAITING as ONLINE_WAITING,
)
from xiangqi.client.sound_control import SoundButton
from xiangqi.client.theme_palette import INK_FAINT, INK_MUTED
from xiangqi.client.ui_theme import (
    GAME_BACKDROP_SPEC,
    MENU_BACKDROP_SPEC,
    InkBackdrop,
    RicePaperCard,
)
from xiangqi.client.voice import get_voice_announcer
from xiangqi.shared.chat import (
    CHAT_KIND_EMOJI,
    MAX_COMMENT_LENGTH,
)
from xiangqi.shared.profile import title_for_rating
from xiangqi.shared.record import GameRecord
from xiangqi.shared.social import DirectMessage
from xiangqi.shared.rules import (
    BOARD_COLS,
    BOARD_ROWS,
    EndReason,
    Piece,
    PieceKind,
    Side,
    Square,
)

logger = logging.getLogger(__name__)

#: 对局聊天输入框的常规占位提示。
CHAT_INPUT_HINT = "说点什么…（回车发送）"
#: 对话日志展开状态在 QSettings 里的键名。
SETTINGS_CHAT_LOG_VISIBLE = "chat_log_visible"


class GameMode(Enum):
    """对局模式。"""

    LOCAL = "local"
    AI = "ai"
    ONLINE = "online"

    @property
    def label(self) -> str:
        return {
            GameMode.LOCAL: "本地双人",
            GameMode.AI: "人机对战",
            GameMode.ONLINE: "联机对战",
        }[self]


class ThemedComboBox(QComboBox):
    """在自定义 QSS 下仍显示下拉箭头的组合框。"""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(INK_MUTED) if self.isEnabled() else QColor(INK_FAINT)
        pen = QPen(
            color,
            1.4,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        center_x = self.width() - 11.0
        center_y = self.height() / 2.0
        arrow = QPainterPath(QPointF(center_x - 3.5, center_y - 1.8))
        arrow.lineTo(QPointF(center_x, center_y + 1.8))
        arrow.lineTo(QPointF(center_x + 3.5, center_y - 1.8))
        painter.drawPath(arrow)
        painter.end()


class PlayerCard(QFrame):
    """顶部棋手信息卡片：将/帅徽记 + 身份 + 对局状态。"""

    def __init__(
        self,
        side: Side,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._side = side
        self._base_caption = "先手" if side is Side.RED else "后手"

        self.setObjectName("playerCard")
        self.setProperty("active", "false")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(62)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)

        self._king_badge = QLabel(self)
        self._king_badge.setObjectName(
            "kingBadgeRed" if side is Side.RED else "kingBadgeBlack"
        )
        self._king_badge.setText(Piece(side, PieceKind.KING).glyph)
        self._king_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._king_badge.setFixedSize(30, 30)
        self._king_badge.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        self._king_badge.setAccessibleName(f"{side.label}徽记")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self._name_label = QLabel(side.label, self)
        self._name_label.setObjectName("playerName")
        self._status_label = QLabel("等待", self)
        self._status_label.setObjectName("playerCaption")

        text_layout.addWidget(self._name_label)
        text_layout.addWidget(self._status_label)

        layout.addWidget(self._king_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_layout, 1)

    def set_identity(self, display_name: str, base_caption: str) -> None:
        """更新身份名称与状态副标题前缀。"""
        if self._name_label.text() != display_name:
            self._name_label.setText(display_name)
            self._name_label.setAccessibleName(display_name)
        self._base_caption = base_caption

    def set_state(self, active: bool, status: str) -> None:
        """更新高亮与状态文字。"""
        active_value = "true" if active else "false"
        if self.property("active") != active_value:
            self.setProperty("active", active_value)
            self._repolish()
            for label in (self._name_label, self._status_label):
                label.style().unpolish(label)
                label.style().polish(label)

        self._status_label.setText(f"{self._base_caption}，{status}")
        self._king_badge.setAccessibleDescription(status)

    def _repolish(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        *,
        record_store: Optional[LocalRecordStore] = None,
    ) -> None:
        super().__init__()
        self.config = config or AppConfig()
        self._record_store = record_store or LocalRecordStore()
        self._record_saved = False

        self._active_modal: Optional[ModalOverlay] = None
        self._result_dialog_open = False
        self._modal_dialog_open = False
        self._closing = False
        self._invite_overlay: Optional[InviteFriendOverlay] = None
        self._friends_overlay: Optional[FriendsOverlay] = None
        self._private_chat_overlay: Optional[PrivateChatOverlay] = None
        self._challenge_dialog: Optional[ConfirmDialog] = None
        self._challenge_dialog_id = ""
        self._challenge_cancelled = False

        # 对局聊天：对话日志默认收起，用户展开状态保存在 QSettings。
        self._settings = QSettings()
        self._chat_log_expanded = False
        self._chat_unread = 0

        # 单次终局弹窗定时器：用于等待绝杀特效/语音结束后再弹窗。
        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.timeout.connect(self._on_result_timer)
        self._result_generation = 0

        # 对局模式与设置；首次启动默认本地双人。
        self._game_mode = GameMode.LOCAL
        self._human_side = Side.RED
        self._difficulty = AIDifficulty.MEDIUM
        self._syncing_settings = False

        # 每次替换会话递增，用于丢弃过期的终局弹窗定时器。
        self._game_generation = 0
        self._selected: Optional[Square] = None

        # 启动页是主菜单；先创建一个安全的本地会话，保证棋盘控件有视图。
        self._session: GameSession = self._make_session()
        self._connect_session(self._session)

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self._build_ui()
        self._create_shortcuts()
        self._sync_ui()
        self._apply_initial_geometry()

    # ------------------------------------------------------------------
    # 基础访问
    # ------------------------------------------------------------------
    @property
    def session(self) -> GameSession:
        """当前对局会话。"""
        return self._session

    @property
    def game(self):  # type: ignore[no-untyped-def]
        """兼容测试读取底层模型；联机会话返回 None。"""
        return self._session.model

    @property
    def selected(self) -> Optional[Square]:
        """当前选中的棋盘格。"""
        return self._selected

    def active_modal(self) -> Optional[ModalOverlay]:
        """当前正在显示的窗口内模态层（测试用）。"""
        return self._active_modal

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------
    def _make_session(self) -> GameSession:
        """按当前模式创建会话；联机会话由联机页创建。"""
        if self._game_mode is GameMode.AI:
            return AIGameSession(
                human_side=self._human_side,
                difficulty=self._difficulty,
                ai_start_delay_ms=AI_START_DELAY_MS,
            )
        if self._game_mode is GameMode.ONLINE:
            raise RuntimeError("联机会话必须由联机页创建")
        return LocalGameSession()

    def _connect_session(self, session: GameSession) -> None:
        session.state_changed.connect(self._on_session_state_changed)
        session.move_made.connect(self._on_session_move_made)
        session.game_over.connect(self._on_session_game_over)
        session.error.connect(self._on_session_error)
        if isinstance(session, OnlineGameSession):
            session.undo_requested.connect(
                self._on_online_undo_requested
            )
            session.undo_resolved.connect(
                self._on_online_undo_resolved
            )
            session.rematch_requested.connect(
                self._on_online_rematch_requested
            )
            session.chat_received.connect(self._on_chat_received)
            session.chat_failed.connect(self._on_chat_failed)

    def _replace_session(self) -> None:
        """关闭旧会话、创建新会话并刷新界面。"""
        old = self._session
        if old is not None:
            try:
                old.shutdown()
                old.deleteLater()
            except RuntimeError:
                pass

        self._result_timer.stop()
        self._game_generation += 1
        self._selected = None
        self._record_saved = False
        self._session = self._make_session()
        self._connect_session(self._session)
        self._sync_ui()
        self._play_start_sound()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        central_widget.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.stack = QStackedWidget(central_widget)
        self.stack.setObjectName("mainStack")
        self.menu_page = self._build_menu_page()
        self.game_page = self._build_game_page()
        self.online_page = OnlinePanel(self.config, self.stack)
        self.online_page.session_ready.connect(
            self._on_online_session_ready
        )
        self.online_page.back_requested.connect(
            self._return_to_menu_from_online
        )
        self.online_page.profile_requested.connect(
            self._open_profile_window
        )
        self.online_page.friends_requested.connect(
            self._open_friends_window
        )
        self.online_page.leaderboard_requested.connect(
            self._open_leaderboard_window
        )
        self.online_page.challenge_received.connect(
            self._on_challenge_received
        )
        self.online_page.challenge_cancelled.connect(
            self._on_challenge_cancelled
        )
        self.online_page.direct_message_received.connect(
            self._on_direct_message_received
        )
        self.replay_page = ReplayPanel(self._record_store, self.stack)
        self.replay_page.back_requested.connect(
            self._close_replay_page
        )
        self.stack.addWidget(self.menu_page)
        self.stack.addWidget(self.game_page)
        self.stack.addWidget(self.online_page)
        self.stack.addWidget(self.replay_page)
        self.stack.setCurrentWidget(self.menu_page)

        root_layout.addWidget(self.stack)
        self.setCentralWidget(central_widget)

    def _build_menu_page(self) -> QWidget:
        page = InkBackdrop(self.stack, spec=MENU_BACKDROP_SPEC)
        page.setObjectName("menuPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        utility_row = QHBoxLayout()
        utility_row.setContentsMargins(0, 0, 2, 0)
        utility_row.addStretch(1)
        self.menu_sound_button = SoundButton(page)
        utility_row.addWidget(
            self.menu_sound_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        layout.addLayout(utility_row)
        layout.addStretch(1)

        self.menu_card = RicePaperCard(page, seal_text="棋")
        self.menu_card.setObjectName("menuCard")
        self.menu_card.setFixedWidth(500)

        card_layout = QVBoxLayout(self.menu_card)
        card_layout.setContentsMargins(42, 30, 42, 30)
        card_layout.setSpacing(10)

        title = QLabel(APP_NAME, self.menu_card)
        title.setObjectName("menuTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel(
            "楚河汉界 · 红先黑后 · 将死或困毙即胜", self.menu_card
        )
        subtitle.setObjectName("menuSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        footnote = QLabel(
            "一局棋，一壶茶，纸上谈兵", self.menu_card
        )
        footnote.setObjectName("menuFootnote")
        footnote.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addWidget(footnote)
        card_layout.addSpacing(10)

        # 联机是当前主推入口：红色主按钮，独占第一排。
        self.online_button = self._make_menu_button(
            "联机对战",
            "menuPrimaryButton",
            "排位匹配、好友、头像与个人信息",
            self._open_online_page,
        )
        self.online_button.setMinimumHeight(56)

        self.local_button = self._make_menu_button(
            "本地双人",
            "menuButton",
            "同一台电脑红黑轮流走子",
            self.start_local_game,
        )
        self.ai_button = self._make_menu_button(
            "人机对战",
            "menuButton",
            "与本地 AI 对弈，可选择难度与先手方",
            self.start_ai_game,
        )
        self.replay_button = self._make_menu_button(
            "棋谱复盘",
            "menuButton",
            "回看历史对局，逐手复盘",
            self._open_replay_page,
        )
        self.puzzle_button = self._make_menu_button(
            "残局挑战",
            "menuButton",
            "残局题库将在后续版本开放",
            lambda: self._show_notice(
                "敬请期待", "残局挑战将在后续版本开放。"
            ),
        )
        self.exit_button = self._make_menu_button(
            "退出游戏",
            "menuQuietButton",
            "退出游戏",
            self._exit_game,
        )

        card_layout.addWidget(self.online_button)
        card_layout.addWidget(self.local_button)
        card_layout.addWidget(self.ai_button)
        card_layout.addWidget(self.replay_button)
        card_layout.addWidget(self.puzzle_button)

        card_layout.addSpacing(8)
        card_layout.addWidget(self.exit_button)

        layout.addWidget(
            self.menu_card, 0, Qt.AlignmentFlag.AlignHCenter
        )
        layout.addStretch(1)

        version_label = QLabel(f"版本 {APP_VERSION}", page)
        version_label.setObjectName("menuVersion")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)
        return page

    def _make_menu_button(
        self,
        text: str,
        object_name: str,
        tooltip: str,
        handler: Callable[[], None],
    ) -> QPushButton:
        button = QPushButton(text, self.menu_card)
        button.setObjectName(object_name)
        button.setToolTip(tooltip)
        button.setAccessibleName(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(50)
        button.setAutoDefault(False)
        button.clicked.connect(handler)
        return button

    def _build_game_page(self) -> QWidget:
        page = InkBackdrop(self.stack, spec=GAME_BACKDROP_SPEC)
        page.setObjectName("gamePage")

        root_layout = QVBoxLayout(page)
        root_layout.setContentsMargins(24, 18, 24, 18)
        root_layout.setSpacing(14)

        root_layout.addLayout(self._build_header())
        root_layout.addWidget(self._build_settings_bar())
        root_layout.addLayout(self._build_player_cards())

        self.board_widget = BoardWidget(self._session.view, page)
        self.board_widget.cell_clicked.connect(self._on_cell_clicked)
        self.danmaku_overlay = DanmakuOverlay(self.board_widget)
        self.danmaku_overlay.set_board_widget(self.board_widget)
        self.danmaku_overlay.setGeometry(self.board_widget.rect())
        self.danmaku_overlay.raise_()
        self.board_widget.installEventFilter(self)

        play_area = QHBoxLayout()
        play_area.setContentsMargins(0, 0, 0, 0)
        play_area.setSpacing(10)
        play_area.addWidget(self.board_widget, 1)

        self.chat_log = ChatLogPanel(page)
        self.chat_log.setMinimumWidth(210)
        self.chat_log.setMaximumWidth(300)
        self.chat_log.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        play_area.addWidget(self.chat_log, 0)
        root_layout.addLayout(play_area, 1)

        self.chat_bar = QWidget(page)
        chat_bar = QHBoxLayout(self.chat_bar)
        chat_bar.setContentsMargins(0, 0, 0, 0)
        chat_bar.setSpacing(8)
        self.emoji_button = EmojiPickerButton(self.chat_bar)
        self.preset_comment_button = PresetCommentButton(
            self.chat_bar
        )
        self.chat_input = QLineEdit(self.chat_bar)
        self.chat_input.setObjectName("chatInput")
        self.chat_input.setMaxLength(MAX_COMMENT_LENGTH)
        self.chat_input.setPlaceholderText(CHAT_INPUT_HINT)
        self.chat_send_button = QPushButton("发送", self.chat_bar)
        self.chat_send_button.setObjectName("chatSendButton")
        self.chat_log_toggle_button = QPushButton(
            "对话日志", self.chat_bar
        )
        self.chat_log_toggle_button.setObjectName(
            "chatLogToggleButton"
        )
        self.chat_log_toggle_button.setCheckable(True)
        for button in (
            self.emoji_button,
            self.preset_comment_button,
            self.chat_send_button,
            self.chat_log_toggle_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
        chat_bar.addWidget(self.emoji_button)
        chat_bar.addWidget(self.preset_comment_button)
        chat_bar.addWidget(self.chat_input, 1)
        chat_bar.addWidget(self.chat_send_button)
        chat_bar.addWidget(self.chat_log_toggle_button)
        self.chat_bar.setVisible(False)
        root_layout.addWidget(self.chat_bar)

        root_layout.addLayout(self._build_footer())

        self.emoji_button.emoji_picked.connect(
            self._on_emoji_picked
        )
        self.preset_comment_button.comment_picked.connect(
            self._on_preset_comment_picked
        )
        self.chat_send_button.clicked.connect(self._on_send_comment)
        self.chat_input.returnPressed.connect(self._on_send_comment)
        self.chat_log_toggle_button.toggled.connect(
            self._on_chat_log_toggled
        )
        self._apply_chat_log_visibility(
            self._load_chat_log_visible()
        )
        self._refresh_chat_controls()
        return page

    def _build_header(self) -> QHBoxLayout:
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(2, 0, 2, 0)
        header_layout.setSpacing(12)

        brand_layout = QVBoxLayout()
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)

        title_label = QLabel(APP_NAME, self)
        title_label.setObjectName("brandTitle")
        subtitle_label = QLabel("楚河汉界，运筹帷幄", self)
        subtitle_label.setObjectName("brandSubtitle")

        brand_layout.addWidget(title_label)
        brand_layout.addWidget(subtitle_label)

        self.turn_pill = QLabel("红方回合", self)
        self.turn_pill.setObjectName("turnPill")
        self.turn_pill.setProperty("result", "false")
        self.turn_pill.setProperty("check", "false")
        self.turn_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.turn_pill.setMinimumWidth(136)
        self.turn_pill.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.turn_pill.setAccessibleName("当前对局状态")

        header_layout.addLayout(brand_layout)
        header_layout.addStretch(1)
        header_layout.addWidget(
            self.turn_pill, 0, Qt.AlignmentFlag.AlignVCenter
        )
        return header_layout

    def _build_settings_bar(self) -> QFrame:
        settings_bar = QFrame(self)
        settings_bar.setObjectName("settingsBar")
        settings_bar.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        settings_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        bar_layout = QHBoxLayout(settings_bar)
        bar_layout.setContentsMargins(12, 6, 12, 6)
        bar_layout.setSpacing(12)

        self.difficulty_combo = ThemedComboBox(settings_bar)
        self.difficulty_combo.setObjectName("difficultyCombo")
        self.difficulty_combo.setAccessibleName("AI 难度")
        self.difficulty_combo.setToolTip("人机模式下 AI 的棋力与搜索强度")
        for difficulty in AIDifficulty:
            self.difficulty_combo.addItem(difficulty.label, difficulty)
        self.difficulty_combo.setMinimumWidth(78)
        self.difficulty_combo.setMinimumHeight(28)
        self.difficulty_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.difficulty_combo.currentIndexChanged.connect(
            self._on_difficulty_changed
        )

        self.first_combo = ThemedComboBox(settings_bar)
        self.first_combo.setObjectName("firstPlayerCombo")
        self.first_combo.setAccessibleName("先手方")
        self.first_combo.setToolTip("玩家先手执红；AI 先手时玩家执黑")
        self.first_combo.addItem("玩家先手", Side.RED)
        self.first_combo.addItem("AI 先手", Side.BLACK)
        self.first_combo.setMinimumWidth(92)
        self.first_combo.setMinimumHeight(28)
        self.first_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.first_combo.currentIndexChanged.connect(
            self._on_first_side_changed
        )

        self.difficulty_group = self._make_settings_group(
            "难度", self.difficulty_combo
        )
        self.first_group = self._make_settings_group(
            "先手", self.first_combo
        )

        self.local_mode_label = QLabel(
            "本地双人 · 红方先行", settings_bar
        )
        self.local_mode_label.setObjectName("settingsLabel")
        self.move_hint_label = QLabel(
            "点击己方棋子，再点目标位置落子", settings_bar
        )
        self.move_hint_label.setObjectName("settingsLabel")

        bar_layout.addWidget(self.difficulty_group)
        bar_layout.addWidget(self.first_group)
        bar_layout.addWidget(self.local_mode_label)
        bar_layout.addWidget(self.move_hint_label)
        bar_layout.addStretch(1)

        self.sound_button = SoundButton(settings_bar)
        bar_layout.addWidget(
            self.sound_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        return settings_bar

    def _make_settings_group(
        self,
        title: str,
        combo: QComboBox,
    ) -> QWidget:
        """创建“标签 + 组合框”的设置组，便于整组显示/隐藏。"""
        container = QWidget(self)
        group = QHBoxLayout(container)
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(6)

        label = QLabel(title, container)
        label.setObjectName("settingsLabel")
        label.setBuddy(combo)

        group.addWidget(label)
        group.addWidget(combo)
        return container

    def _build_player_cards(self) -> QHBoxLayout:
        cards_layout = QHBoxLayout()
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(12)

        self.red_card = PlayerCard(Side.RED, self)
        self.black_card = PlayerCard(Side.BLACK, self)
        cards_layout.addWidget(self.red_card, 1)
        cards_layout.addWidget(self.black_card, 1)
        return cards_layout

    def _build_footer(self) -> QHBoxLayout:
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(2, 0, 2, 0)
        footer_layout.setSpacing(10)

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(1)

        self.move_label = QLabel("第 0 手 · 红方行棋", self)
        self.move_label.setObjectName("moveInfo")
        self.hint_label = QLabel(
            "Ctrl+Z 悔棋  Ctrl+N 重开", self
        )
        self.hint_label.setObjectName("hintLabel")
        self.hint_label.setToolTip(
            "Ctrl+Z 悔棋，Ctrl+N 重新开始"
        )

        info_layout.addWidget(self.move_label)
        info_layout.addWidget(self.hint_label)

        self.menu_back_button = QPushButton("返回主菜单", self)
        self.menu_back_button.setObjectName("menuBackButton")
        self.menu_back_button.setToolTip("结束当前棋局并返回主菜单")
        self.menu_back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_back_button.setMinimumWidth(104)
        self.menu_back_button.setMinimumHeight(38)
        self.menu_back_button.setAutoDefault(False)
        self.menu_back_button.clicked.connect(self._on_back_requested)

        self.invite_button = QPushButton("邀请好友", self)
        self.invite_button.setObjectName("inviteFriendButton")
        self.invite_button.setToolTip(
            "邀请好友加入自建房，好友接受后立即开局"
        )
        self.invite_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.invite_button.setMinimumWidth(100)
        self.invite_button.setMinimumHeight(38)
        self.invite_button.setAutoDefault(False)
        self.invite_button.clicked.connect(self._open_invite_window)
        self.invite_button.setVisible(False)

        self.undo_button = QPushButton("悔棋", self)
        self.undo_button.setObjectName("undoButton")
        self.undo_button.setToolTip("撤销上一手（Ctrl+Z）")
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_button.setMinimumWidth(84)
        self.undo_button.setMinimumHeight(38)
        self.undo_button.setAutoDefault(False)
        self.undo_button.clicked.connect(self._undo_move)

        self.restart_button = QPushButton("重新开始", self)
        self.restart_button.setObjectName("restartButton")
        self.restart_button.setToolTip("清空棋盘并重新开始（Ctrl+N）")
        self.restart_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restart_button.setMinimumWidth(102)
        self.restart_button.setMinimumHeight(38)
        self.restart_button.setAutoDefault(False)
        self.restart_button.clicked.connect(self._request_restart)

        footer_layout.addLayout(info_layout)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.invite_button)
        footer_layout.addWidget(self.menu_back_button)
        footer_layout.addWidget(self.undo_button)
        footer_layout.addWidget(self.restart_button)
        return footer_layout

    def _create_shortcuts(self) -> None:
        self._undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._undo_shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self._undo_shortcut.activated.connect(self._undo_move)

        self._restart_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self._restart_shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self._restart_shortcut.activated.connect(self._request_restart)

        self._set_game_shortcuts_enabled(False)

    # ------------------------------------------------------------------
    # 导航
    # ------------------------------------------------------------------
    def start_local_game(self) -> None:
        """从主菜单开始一局本地双人对战。"""
        self._start_game(GameMode.LOCAL)

    def start_ai_game(self) -> None:
        """从主菜单开始一局人机对战。"""
        self._start_game(GameMode.AI)

    def _start_game(self, mode: GameMode) -> None:
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
        ):
            return
        self._game_mode = mode
        self._replace_session()
        self.stack.setCurrentWidget(self.game_page)
        self._set_game_shortcuts_enabled(True)
        self._sync_ui()
        self.board_widget.setFocus()

    def show_main_menu(self) -> None:
        """返回主菜单；进行中的棋局需要确认放弃。"""
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
            or not self._is_game_page_active()
        ):
            return

        if isinstance(self._session, OnlineGameSession):
            self._leave_online_to_lobby()
            return

        self._session.pause()
        if self._session.view.move_count > 0:
            if not self._confirm_discard_game(
                "返回主菜单",
                "返回主菜单将结束当前棋局，确定要返回吗？",
                confirm_text="返回主菜单",
            ):
                self._session.resume()
                self._sync_ui()
                return

        self._result_timer.stop()
        self._game_generation += 1
        self._selected = None
        self.stack.setCurrentWidget(self.menu_page)
        self._set_game_shortcuts_enabled(False)
        self.local_button.setFocus()

    def _leave_online_to_lobby(self) -> None:
        """离开联机房间后回到联机模式主页面。"""
        session = self._session
        if not isinstance(session, OnlineGameSession):
            return
        if session.status in (ONLINE_PLAYING, ONLINE_FINISHED):
            session.pause()
            if not self._confirm_discard_game(
                "离开房间",
                "离开房间将结束当前联机对局并回到联机大厅，确定吗？",
                confirm_text="离开房间",
                cancel_text="继续对局",
            ):
                session.resume()
                self._sync_ui()
                return
        if session.ranked and session.human_side is not None:
            self.online_page.update_account_rating(
                session.rating_for(session.human_side)
            )
        session.shutdown()
        self.online_page.reset()
        self._result_timer.stop()
        self._game_generation += 1
        self._selected = None
        self.stack.setCurrentWidget(self.online_page)
        self._set_game_shortcuts_enabled(False)
        self.online_page.ensure_lobby_connection()
        self.online_page.ranked_button.setFocus()

    def _open_online_page(self) -> None:
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
        ):
            return
        if not isinstance(self._session, OnlineGameSession):
            self.online_page.reset()
        self.stack.setCurrentWidget(self.online_page)
        self._set_game_shortcuts_enabled(False)
        self.online_page.ensure_lobby_connection()
        self.online_page.name_input.setFocus()

    def _return_to_menu_from_online(self) -> None:
        if self._closing or self._modal_dialog_open:
            return
        self.online_page.reset()
        self.stack.setCurrentWidget(self.menu_page)
        self._set_game_shortcuts_enabled(False)
        self.local_button.setFocus()

    def _open_replay_page(self) -> None:
        """打开棋谱复盘页并刷新本地历史对局。"""
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
        ):
            return
        self.replay_page.refresh()
        self.stack.setCurrentWidget(self.replay_page)
        self._set_game_shortcuts_enabled(False)
        self.replay_page.back_button.setFocus()

    def _close_replay_page(self) -> None:
        if self._closing or self._modal_dialog_open:
            return
        self.stack.setCurrentWidget(self.menu_page)
        self._set_game_shortcuts_enabled(False)
        self.local_button.setFocus()

    def _open_profile_window(self) -> None:
        """打开自己的个人信息窗口；异步读取/更新服务端资料。"""
        self._show_profile_overlay(None, nested=False)

    def _show_profile_overlay(
        self,
        nickname: Optional[str],
        *,
        nested: bool,
    ) -> None:
        """显示自己或他人资料；``nested`` 用于排行榜/好友窗口上层。"""
        if self._closing or self._result_dialog_open:
            return
        if not nested and self._modal_dialog_open:
            return
        token = self.online_page.token
        base_url = self.online_page.http_base_url
        if not token or not base_url:
            return
        if nickname is not None and nickname == self.online_page.nickname:
            nickname = None

        previous_modal = self._active_modal
        if not nested:
            self._modal_dialog_open = True
        overlay: Optional[ProfileOverlay] = None
        profile: Optional[dict] = None
        avatar_pixmap = None
        try:
            overlay = ProfileOverlay(
                None,
                base_url,
                token,
                nickname,
                parent=self._overlay_host(),
            )
            self._active_modal = overlay
            overlay.exec()
            profile = overlay.profile
            avatar_pixmap = overlay.avatar_pixmap
        finally:
            self._active_modal = previous_modal
            if overlay is not None:
                overlay.deleteLater()
            if not nested:
                self._modal_dialog_open = False
            elif previous_modal is not None:
                previous_modal.setFocus()
                refresher = getattr(previous_modal, "refresh", None)
                if callable(refresher):
                    refresher()
        if nickname is None and isinstance(profile, dict):
            self.online_page.apply_profile(profile, avatar_pixmap)

    def _open_friends_window(self) -> None:
        """打开好友窗口。"""
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
        ):
            return
        token = self.online_page.token
        base_url = self.online_page.http_base_url
        if not token or not base_url:
            return
        self._modal_dialog_open = True
        overlay: Optional[FriendsOverlay] = None
        try:
            overlay = FriendsOverlay(
                None, base_url, token, parent=self._overlay_host()
            )
            overlay.profile_requested.connect(
                self._on_social_profile_requested
            )
            overlay.chat_requested.connect(
                self._on_friend_chat_requested
            )
            self._friends_overlay = overlay
            self._active_modal = overlay
            overlay.exec()
        finally:
            self._friends_overlay = None
            self._active_modal = None
            self._modal_dialog_open = False
            if overlay is not None:
                overlay.deleteLater()

    def _open_leaderboard_window(self) -> None:
        """打开积分/称号排行榜。"""
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
        ):
            return
        token = self.online_page.token
        base_url = self.online_page.http_base_url
        if not token or not base_url:
            return
        self._modal_dialog_open = True
        overlay: Optional[LeaderboardOverlay] = None
        try:
            overlay = LeaderboardOverlay(
                None, base_url, token, parent=self._overlay_host()
            )
            overlay.profile_requested.connect(
                self._on_social_profile_requested
            )
            self._active_modal = overlay
            overlay.exec()
        finally:
            self._active_modal = None
            self._modal_dialog_open = False
            if overlay is not None:
                overlay.deleteLater()

    def _on_social_profile_requested(self, nickname: str) -> None:
        """排行榜/好友窗口中点击头像：在模态层上方再打开资料窗口。"""
        self._show_profile_overlay(nickname, nested=True)

    def _on_friend_chat_requested(
        self,
        nickname: str,
        avatar: str,
        online: bool,
    ) -> None:
        """好友窗口中点击「聊天」：打开私聊浮层。"""
        if not nickname:
            return
        self._show_private_chat_overlay(
            nickname, avatar, online
        )

    def _show_private_chat_overlay(
        self,
        nickname: str,
        avatar: str,
        online: Optional[bool],
    ) -> None:
        """显示与某位好友的私聊窗口（可叠在好友窗口之上）。"""
        if self._closing or self._result_dialog_open:
            return
        token = self.online_page.token
        base_url = self.online_page.http_base_url
        if not token or not base_url:
            return

        previous_modal = self._active_modal
        was_modal_open = self._modal_dialog_open
        self._modal_dialog_open = True
        overlay: Optional[PrivateChatOverlay] = None
        try:
            overlay = PrivateChatOverlay(
                None,
                base_url,
                token,
                nickname,
                self.online_page.nickname,
                avatar=avatar,
                online=online,
                parent=self._overlay_host(),
            )
            self._private_chat_overlay = overlay
            self._active_modal = overlay
            overlay.exec()
        finally:
            self._private_chat_overlay = None
            self._active_modal = previous_modal
            self._modal_dialog_open = was_modal_open
            if overlay is not None:
                overlay.deleteLater()
            if previous_modal is not None:
                previous_modal.setFocus()
                refresher = getattr(previous_modal, "refresh", None)
                if callable(refresher):
                    refresher()

    def _on_direct_message_received(self, message: object) -> None:
        """好友私聊实时推送：追加到打开中的聊天窗或刷新未读。"""
        if not isinstance(message, DirectMessage):
            return
        overlay = self._private_chat_overlay
        if (
            overlay is not None
            and message.sender_name == overlay.friend_nickname
        ):
            overlay.append_realtime(
                {
                    "id": message.id,
                    "sender_id": message.sender_id,
                    "sender_name": message.sender_name,
                    "recipient_id": message.recipient_id,
                    "content": message.content,
                    "sent_at_ms": message.sent_at_ms,
                }
            )
        if self._friends_overlay is not None and (
            overlay is None
            or message.sender_name != overlay.friend_nickname
        ):
            self._friends_overlay.refresh()

    def _open_invite_window(self) -> None:
        """自建房等待阶段打开好友邀请窗口。"""
        session = self._session
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
            or not isinstance(session, OnlineGameSession)
            or session.status != ONLINE_WAITING
        ):
            return
        token = self.online_page.token
        base_url = self.online_page.http_base_url
        if not token or not base_url:
            return
        self._modal_dialog_open = True
        overlay: Optional[InviteFriendOverlay] = None
        try:
            overlay = InviteFriendOverlay(
                None,
                base_url,
                token,
                session,
                parent=self._overlay_host(),
            )
            self._invite_overlay = overlay
            self._active_modal = overlay
            overlay.exec()
        finally:
            self._invite_overlay = None
            self._active_modal = None
            self._modal_dialog_open = False
            if overlay is not None:
                overlay.deleteLater()
            # 好友接受挑战时邀请窗口会自动关闭；关闭前的状态同步发生在
            # 模态标记仍为 True 的时候，棋盘交互会被禁用。这里在模态
            # 状态清理后再同步一次，确保开局后可以立即落子。
            if not self._closing:
                self._sync_ui()

    def _on_challenge_received(
        self, challenge_id: str, name: str
    ) -> None:
        """好友邀请自建房对局：弹出接受/拒绝窗口。"""
        if self._closing:
            self.online_page.respond_challenge(challenge_id, False)
            return
        if self._challenge_dialog is not None:
            self.online_page.respond_challenge(challenge_id, False)
            return

        previous_modal = self._active_modal
        was_modal_open = self._modal_dialog_open
        self._modal_dialog_open = True
        self._challenge_dialog_id = challenge_id
        self._challenge_cancelled = False
        dialog = ConfirmDialog(
            "挑战邀请",
            f"好友 {name} 邀请你进行自建房对局，是否接受？",
            confirm_text="接受",
            cancel_text="拒绝",
            parent=self._overlay_host(),
        )
        self._challenge_dialog = dialog
        self._active_modal = dialog
        accepted = False
        cancelled = False
        try:
            dialog.exec()
            accepted = dialog.confirm_requested
            cancelled = self._challenge_cancelled
        finally:
            dialog.deleteLater()
            self._challenge_dialog = None
            self._challenge_dialog_id = ""
            self._active_modal = previous_modal
            self._modal_dialog_open = was_modal_open
        if cancelled:
            return
        if accepted and previous_modal is not None:
            # 接受挑战后关闭底下的资料/好友/排行榜窗口，避免遮住对局页。
            try:
                previous_modal.accept()
            except RuntimeError:
                pass
        self.online_page.respond_challenge(challenge_id, accepted)

    def _on_challenge_cancelled(
        self, challenge_id: str, reason: str
    ) -> None:
        del reason
        if challenge_id != self._challenge_dialog_id:
            return
        self._challenge_cancelled = True
        dialog = self._challenge_dialog
        if dialog is not None:
            dialog.reject()

    def _on_online_session_ready(
        self,
        session: OnlineGameSession,
    ) -> None:
        if self._closing:
            session.shutdown()
            return

        old = self._session
        if old is not None:
            try:
                old.shutdown()
                old.deleteLater()
            except RuntimeError:
                pass

        self._game_mode = GameMode.ONLINE
        self._session = session
        self._connect_session(session)
        self._game_generation += 1
        self._selected = None
        self._record_saved = False
        self._clear_chat_log()
        self.stack.setCurrentWidget(self.game_page)
        self._set_game_shortcuts_enabled(True)
        self._sync_ui()
        self._play_start_sound()
        self.board_widget.setFocus()

    def _on_back_requested(self) -> None:
        self.show_main_menu()

    def _exit_game(self) -> None:
        if not self._closing:
            self.close()

    def _is_game_page_active(self) -> bool:
        return self.stack.currentWidget() is self.game_page

    def _set_game_shortcuts_enabled(self, enabled: bool) -> None:
        self._undo_shortcut.setEnabled(enabled)
        self._restart_shortcut.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 对局设置
    # ------------------------------------------------------------------
    @staticmethod
    def _combo_index_for_data(combo: QComboBox, data) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == data:
                return index
        return -1

    def _on_difficulty_changed(self, index: int) -> None:
        if self._syncing_settings:
            return
        difficulty = self.difficulty_combo.itemData(index)
        if not isinstance(difficulty, AIDifficulty):
            return
        if difficulty is self._difficulty:
            return
        self._difficulty = difficulty
        session = self._session
        if isinstance(session, AIGameSession):
            session.set_difficulty(difficulty)
        else:
            self._sync_ui()

    def _on_first_side_changed(self, index: int) -> None:
        if self._syncing_settings:
            return
        human_side = self.first_combo.itemData(index)
        if human_side not in (Side.RED, Side.BLACK):
            return
        if human_side is self._human_side:
            return
        if self._game_mode is not GameMode.AI:
            self._sync_settings_controls()
            return

        previous = self._human_side
        self._human_side = human_side
        if self._session.view.move_count > 0:
            self._session.pause()
            if not self._confirm_discard_game(
                "切换先手方",
                "切换先手方将重新开始当前棋局，确定吗？",
                confirm_text="重新开始",
            ):
                self._human_side = previous
                self._session.resume()
                self._sync_ui()
                return
        self._replace_session()

    def _sync_settings_controls(self) -> None:
        ai_mode = self._game_mode is GameMode.AI
        online_mode = self._game_mode is GameMode.ONLINE
        self.difficulty_group.setVisible(ai_mode)
        self.first_group.setVisible(ai_mode)
        if online_mode:
            session = self._session
            code = (
                session.room_code
                if isinstance(session, OnlineGameSession)
                else ""
            )
            prefix = (
                "排位赛"
                if isinstance(session, OnlineGameSession)
                and session.ranked
                else "自建房"
            )
            del code
            self.local_mode_label.setText(prefix)
            self.move_hint_label.setVisible(False)
        elif ai_mode:
            self.local_mode_label.setText("人机对战")
            self.move_hint_label.setVisible(False)
        else:
            self.local_mode_label.setText("本地双人 · 红方先行")
            self.move_hint_label.setVisible(True)

        self._syncing_settings = True
        try:
            difficulty_index = self._combo_index_for_data(
                self.difficulty_combo, self._difficulty
            )
            if (
                difficulty_index >= 0
                and self.difficulty_combo.currentIndex() != difficulty_index
            ):
                self.difficulty_combo.setCurrentIndex(difficulty_index)

            side_index = self._combo_index_for_data(
                self.first_combo, self._human_side
            )
            if (
                side_index >= 0
                and self.first_combo.currentIndex() != side_index
            ):
                self.first_combo.setCurrentIndex(side_index)
        finally:
            self._syncing_settings = False

        busy = self._session.busy
        self.difficulty_combo.setEnabled(ai_mode and not busy)
        self.first_combo.setEnabled(ai_mode and not busy)

    def _apply_initial_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)
            return

        available = screen.availableGeometry()
        width = min(
            WINDOW_DEFAULT_WIDTH,
            max(WINDOW_MIN_WIDTH, available.width() - WINDOW_SCREEN_MARGIN),
        )
        height = min(
            WINDOW_DEFAULT_HEIGHT,
            max(WINDOW_MIN_HEIGHT, available.height() - WINDOW_SCREEN_MARGIN),
        )
        self.resize(width, height)

        window_rect = self.frameGeometry()
        window_rect.moveCenter(available.center())
        self.move(window_rect.topLeft())

    # ------------------------------------------------------------------
    # 选中与落子
    # ------------------------------------------------------------------
    def _human_can_play(self) -> bool:
        return (
            not self._closing
            and not self._modal_dialog_open
            and not self._result_dialog_open
            and self._is_game_page_active()
            and self._session.accepts_human_input
            and not self._session.view.is_game_over
        )

    def _set_selection(self, square: Optional[Square]) -> None:
        if self._selected == square:
            return
        self._selected = square
        self._sync_ui()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if not self._human_can_play():
            return
        if not (0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS):
            return

        view = self._session.view
        piece = view.board[row][col]

        if self._selected is None:
            if piece is not None and piece.side is view.side_to_move:
                self._set_selection((row, col))
            return

        if (row, col) == self._selected:
            self._set_selection(None)
            return

        targets = {
            move.target
            for move in self._session.legal_moves_from(*self._selected)
        }
        if (row, col) in targets:
            from_row, from_col = self._selected
            if self._session.request_move(from_row, from_col, row, col):
                self._selected = None
                self._sync_ui()
            return

        if piece is not None and piece.side is view.side_to_move:
            self._set_selection((row, col))
        else:
            self._set_selection(None)

    def _undo_move(self) -> None:
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
            or not self._is_game_page_active()
        ):
            return
        if self._session.request_undo():
            self._selected = None
            self._sync_ui()

    def _request_restart(self) -> None:
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
            or not self._is_game_page_active()
        ):
            return

        if isinstance(self._session, OnlineGameSession):
            session = self._session
            if session.status == ONLINE_PLAYING:
                if not self._confirm_discard_game(
                    "认输",
                    "确定要认输吗？",
                    confirm_text="认输",
                    cancel_text="继续对局",
                ):
                    return
                session.request_resign()
            elif session.status == ONLINE_FINISHED:
                if session.request_restart():
                    self._show_notice(
                        "已发送再战请求",
                        "等待对手同意后再来一局。",
                    )
            return

        if self._session.view.move_count > 0:
            self._session.pause()
            if not self._confirm_discard_game(
                "重新开始",
                "当前棋局将被清空，确定要重新开始吗？",
                confirm_text="重新开始",
            ):
                self._session.resume()
                self._sync_ui()
                return

        self._replace_session()

    # ------------------------------------------------------------------
    # 会话信号
    # ------------------------------------------------------------------
    def _on_session_state_changed(self) -> None:
        session = self._session
        if (
            self._invite_overlay is not None
            and isinstance(session, OnlineGameSession)
            and session.status != ONLINE_WAITING
        ):
            self._invite_overlay.accept()
        self._sync_ui()

    # ------------------------------------------------------------------
    # 对局聊天
    # ------------------------------------------------------------------
    def _refresh_chat_controls(
        self, online_mode: Optional[bool] = None
    ) -> None:
        """按当前会话状态启用/禁用聊天控件（不含发言冷却）。"""
        if online_mode is None:
            online_mode = isinstance(
                self._session, OnlineGameSession
            )
        session = self._session if online_mode else None
        available = bool(
            isinstance(session, OnlineGameSession)
            and session.chat_available
        )
        for widget in (
            self.emoji_button,
            self.preset_comment_button,
            self.chat_input,
            self.chat_send_button,
        ):
            widget.setEnabled(available)
        self.chat_log_toggle_button.setEnabled(bool(online_mode))

    def _on_emoji_picked(self, emoji: str) -> None:
        session = self._session
        if isinstance(session, OnlineGameSession):
            session.send_emoji(emoji)

    def _on_preset_comment_picked(self, text: str) -> None:
        session = self._session
        if isinstance(session, OnlineGameSession):
            session.send_comment(text)

    def _on_send_comment(self) -> None:
        session = self._session
        if not isinstance(session, OnlineGameSession):
            return
        text = self.chat_input.text().strip()
        if not text:
            return
        if session.send_comment(text):
            self.chat_input.clear()

    def _on_chat_received(self, message: object) -> None:
        """收到服务端广播的对局表情/评论：弹幕 + 对话日志。"""
        is_self = self._chat_is_self(message)
        kind = str(getattr(message, "kind", ""))
        content = str(getattr(message, "content", ""))
        if kind == CHAT_KIND_EMOJI:
            self.danmaku_overlay.push_emoji(content, is_self)
        else:
            self.danmaku_overlay.push_text(content, is_self)
        self.chat_log.append_message(message, is_self)
        if not self._chat_log_expanded:
            self._chat_unread += 1
            self._update_chat_toggle_text()

    def _chat_is_self(self, message: object) -> bool:
        session = self._session
        if not isinstance(session, OnlineGameSession):
            return False
        sender_id = str(getattr(message, "sender_id", ""))
        if session.account_id is not None:
            return sender_id == str(session.account_id)
        return (
            getattr(message, "sender_name", "")
            == session.account_nickname
        )

    def _on_chat_failed(self, reason: str) -> None:
        text = reason or "发言未发送"
        self.chat_log.append_notice(f"（{text}）")
        if not self._chat_log_expanded:
            self._flash_chat_hint(text)

    def _flash_chat_hint(self, text: str) -> None:
        self.chat_input.setPlaceholderText(text)
        QTimer.singleShot(3000, self._restore_chat_hint)

    def _restore_chat_hint(self) -> None:
        if not self._closing:
            self.chat_input.setPlaceholderText(CHAT_INPUT_HINT)

    def _on_chat_log_toggled(self, checked: bool) -> None:
        self._apply_chat_log_visibility(checked)
        self._save_chat_log_visible(checked)

    def _apply_chat_log_visibility(self, visible: bool) -> None:
        expanded = bool(visible)
        self._chat_log_expanded = expanded
        online = isinstance(self._session, OnlineGameSession)
        self.chat_log.setVisible(expanded and online)
        button = self.chat_log_toggle_button
        button.blockSignals(True)
        button.setChecked(expanded)
        button.blockSignals(False)
        if expanded:
            self._chat_unread = 0
        self._update_chat_toggle_text()
        button.setToolTip(
            "收起对话日志，让棋盘占满整行"
            if expanded
            else "展开对话日志，查看双方的发言"
        )

    def _update_chat_toggle_text(self) -> None:
        button = self.chat_log_toggle_button
        if self._chat_log_expanded:
            button.setText("隐藏日志")
        elif self._chat_unread > 0:
            button.setText(f"对话日志 ({self._chat_unread})")
        else:
            button.setText("对话日志")

    def _clear_chat_log(self) -> None:
        self.chat_log.clear_log()
        self.danmaku_overlay.clear()
        self._chat_unread = 0
        self._update_chat_toggle_text()

    def _load_chat_log_visible(self) -> bool:
        value = self._settings.value(
            SETTINGS_CHAT_LOG_VISIBLE, False
        )
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in (
                "1", "true", "yes"
            )
        return False

    def _save_chat_log_visible(self, visible: bool) -> None:
        self._settings.setValue(
            SETTINGS_CHAT_LOG_VISIBLE, bool(visible)
        )
        self._settings.sync()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 接口
        """棋盘尺寸变化时让弹幕覆盖层随之铺满。"""
        if (
            obj is getattr(self, "board_widget", None)
            and event.type() == QEvent.Type.Resize
            and hasattr(self, "danmaku_overlay")
        ):
            self.danmaku_overlay.setGeometry(
                self.board_widget.rect()
            )
            self.danmaku_overlay.raise_()
        return super().eventFilter(obj, event)

    def _on_session_move_made(self) -> None:
        self._play_move_sound()
        self._announce_move_events()

    def _announce_move_events(self) -> None:
        """根据最新一手触发吃子/将军/绝杀的语音与棋盘特效。"""
        view = self._session.view
        move = view.last_move
        if move is None:
            return

        kinds: list[str] = []
        if (
            view.is_game_over
            and view.end_reason is EndReason.CHECKMATE
        ):
            if move.captured is not None:
                kinds.append("capture")
            kinds.append("checkmate")
        else:
            if move.captured is not None:
                kinds.append("capture")
            if view.is_check:
                kinds.append("check")

        if not kinds:
            return

        try:
            voice = get_voice_announcer()
        except Exception:
            logger.exception("获取语音播报器失败")
            voice = None

        for kind in kinds:
            self.board_widget.show_effect(kind)
            if voice is not None:
                try:
                    voice.say(kind)
                except Exception:
                    logger.exception("语音播报失败")

    def _on_session_game_over(self) -> None:
        view = self._session.view
        self._save_game_record()
        session = self._session
        if (
            isinstance(session, OnlineGameSession)
            and session.ranked
            and session.human_side is not None
        ):
            self.online_page.update_account_rating(
                session.rating_for(session.human_side)
            )
        is_checkmate = view.end_reason is EndReason.CHECKMATE
        if not is_checkmate:
            self._play_game_over_sound()
        delay = self.board_widget.transient_remaining_ms()
        self._schedule_result_dialog(delay + RESULT_DIALOG_DELAY_MS)

    def _save_game_record(self) -> None:
        """终局时把完整棋谱追加到本地 JSONL；同一局只写一次。"""
        if self._record_saved:
            return
        session = self._session
        view = session.view
        if not view.is_game_over:
            return

        moves = tuple(session.move_history)
        metadata: dict[str, object] = {}
        if isinstance(session, OnlineGameSession):
            mode = "online"
            red_name = (
                session.players.get(Side.RED, ("红方", False))[0]
                or "红方"
            )
            black_name = (
                session.players.get(Side.BLACK, ("黑方", False))[0]
                or "黑方"
            )
            rated = session.ranked
            metadata["room_code"] = session.room_code
            metadata["ranked"] = session.ranked
            deltas = {}
            for side in (Side.RED, Side.BLACK):
                delta = session.rating_delta_for(side)
                if delta is not None:
                    deltas[side.value] = int(delta)
            if deltas:
                metadata["rating_deltas"] = deltas
        elif isinstance(session, AIGameSession):
            mode = "ai"
            human_side = session.human_side
            ai_name = f"AI（{session.difficulty.label}）"
            red_name = "你" if human_side is Side.RED else ai_name
            black_name = ai_name if human_side is Side.RED else "你"
            rated = False
            metadata["difficulty"] = session.difficulty.name.lower()
            metadata["human_side"] = human_side.value
        else:
            mode = "local"
            red_name = "红方"
            black_name = "黑方"
            rated = False

        if not moves and view.move_count > 0:
            metadata["moves_missing"] = True
        reason = (
            view.end_reason.value
            if isinstance(view.end_reason, EndReason)
            else ""
        )
        record = GameRecord(
            record_id=uuid.uuid4().hex,
            created_at=datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            mode=mode,
            moves=moves,
            winner=view.winner,
            result_reason=reason,
            red_name=red_name,
            black_name=black_name,
            rated=rated,
            metadata=metadata,
        )
        try:
            self._record_store.append(record)
        except Exception:
            logger.exception("保存本地棋谱失败")
            return
        self._record_saved = True

    def _on_session_error(self, message: str) -> None:
        logger.warning("会话错误：%s", message)
        if isinstance(self._session, OnlineGameSession):
            if self._closing or not self._is_game_page_active():
                return
            if self._modal_dialog_open or self._result_dialog_open:
                return
            QTimer.singleShot(
                0, lambda: self._show_online_error(message)
            )

    def _show_online_error(self, message: str) -> None:
        if (
            self._closing
            or self._modal_dialog_open
            or self._result_dialog_open
        ):
            return
        self._show_notice("联机提示", message)

    # ------------------------------------------------------------------
    # 联机请求
    # ------------------------------------------------------------------
    def _on_online_undo_requested(self, name: str) -> None:
        session = self._session
        if not isinstance(session, OnlineGameSession):
            return
        if session.undo_requester is None:
            return
        if self._closing or not self._is_game_page_active():
            return
        if self._modal_dialog_open or self._result_dialog_open:
            QTimer.singleShot(
                100,
                lambda: self._on_online_undo_requested(name),
            )
            return

        session.pause()
        accepted = self._confirm_discard_game(
            "悔棋请求",
            f"对手 {name} 请求悔棋，是否同意？",
            confirm_text="同意",
            cancel_text="拒绝",
        )
        session.resume()
        session.respond_undo(accepted)

    def _on_online_undo_resolved(
        self,
        accepted: bool,
        reason: str,
    ) -> None:
        if self._closing or not self._is_game_page_active():
            return
        if self._modal_dialog_open or self._result_dialog_open:
            return
        message = reason or ("已同意悔棋" if accepted else "未悔棋")
        self._show_notice("悔棋结果", message)

    def _on_online_rematch_requested(self, name: str) -> None:
        session = self._session
        if not isinstance(session, OnlineGameSession):
            return
        if session.status != ONLINE_FINISHED:
            return
        if self._closing or not self._is_game_page_active():
            return
        if self._modal_dialog_open or self._result_dialog_open:
            QTimer.singleShot(
                100,
                lambda: self._on_online_rematch_requested(name),
            )
            return

        session.pause()
        accepted = self._confirm_discard_game(
            "再来一局",
            f"对手 {name} 请求再来一局，是否同意？",
            confirm_text="同意",
            cancel_text="暂不",
        )
        session.resume()
        if accepted:
            session.request_restart()

    # ------------------------------------------------------------------
    # 音效
    # ------------------------------------------------------------------
    def _play_start_sound(self) -> None:
        try:
            get_audio_manager().play_start()
        except Exception:  # 音频失败不应影响对局
            logger.exception("播放开局音效失败")

    def _play_move_sound(self) -> None:
        try:
            get_audio_manager().play_move()
        except Exception:
            logger.exception("播放落子音效失败")

    def _play_game_over_sound(self) -> None:
        try:
            session = self._session
            if session.view.end_reason is EndReason.CHECKMATE:
                return
            manager = get_audio_manager()
            if isinstance(session, OnlineGameSession):
                human_side = session.human_side
                if (
                    human_side is not None
                    and session.view.winner is human_side.opponent
                ):
                    manager.play_lose()
                else:
                    manager.play_win()
            elif (
                isinstance(session, AIGameSession)
                and session.view.winner is session.ai_side
            ):
                manager.play_lose()
            else:
                manager.play_win()
        except Exception:
            logger.exception("播放终局音效失败")

    # ------------------------------------------------------------------
    # 终局与弹窗
    # ------------------------------------------------------------------
    def _schedule_result_dialog(self, delay_ms: int = 0) -> None:
        self._result_generation = self._game_generation
        self._result_timer.stop()
        self._result_timer.start(max(0, int(delay_ms)))

    def _on_result_timer(self) -> None:
        self._show_result_dialog(self._result_generation)

    def _show_result_dialog(self, generation: Optional[int] = None) -> None:
        if self._closing or self._result_dialog_open:
            return
        if not self._is_game_page_active():
            return
        if generation is not None and generation != self._game_generation:
            return
        view = self._session.view
        if not view.is_game_over:
            return
        if self._modal_dialog_open:
            QTimer.singleShot(
                100, lambda: self._show_result_dialog(generation)
            )
            return

        self._result_dialog_open = True
        self._modal_dialog_open = True
        restart = False
        try:
            presentation = self._build_result_presentation(view)
            dialog = ResultDialog(presentation, self._overlay_host())
            self._active_modal = dialog
            dialog.exec()
            restart = dialog.restart_requested
            dialog.deleteLater()
            self._active_modal = None
        finally:
            self._result_dialog_open = False
            self._modal_dialog_open = False

        if restart:
            if isinstance(self._session, OnlineGameSession):
                if self._session.request_restart():
                    self._show_notice(
                        "已发送再战请求",
                        "等待对手同意后再来一局。",
                    )
            else:
                self._replace_session()

    def _build_result_presentation(
        self,
        view: BoardView,
    ) -> ResultPresentation:
        """根据胜者与结束原因生成古风终局文案。"""
        if view.winner is None:
            return ResultPresentation(
                kind="draw",
                title="和棋",
                subtitle="胜负未分",
                detail=f"本局共 {view.move_count} 手",
                seal_text="和",
            )

        reason = view.end_reason
        subtitle = reason.label if isinstance(reason, EndReason) else "胜负已分"

        if isinstance(self._session, OnlineGameSession):
            human_side = self._session.human_side
            opponent = self._session.opponent_name
            detail = f"本局共 {view.move_count} 手"
            if self._session.ranked and human_side is not None:
                delta = self._session.rating_delta_for(human_side)
                rating = self._session.rating_for(human_side)
                new_title = title_for_rating(rating)
                if delta is not None:
                    detail += f" · 排位分 {delta:+d}"
                    old_title = title_for_rating(rating - delta)
                    if old_title != new_title:
                        action = (
                            "晋升" if rating > rating - delta else "变更"
                        )
                        detail += (
                            f" · 称号{action}：{old_title}→{new_title}"
                        )
                detail += f" · 当前称号：{new_title}"
            if view.winner is human_side:
                return ResultPresentation(
                    kind="win",
                    title="胜利",
                    subtitle=f"{subtitle} · 对手：{opponent}",
                    detail=detail,
                    seal_text="胜",
                )
            return ResultPresentation(
                kind="lose",
                title="惜败",
                subtitle=f"{subtitle} · 对手：{opponent}",
                detail=f"{detail}，胜败乃兵家常事",
                seal_text="负",
            )

        if self._game_mode is GameMode.AI:
            if view.winner is self._human_side:
                return ResultPresentation(
                    kind="win",
                    title="胜利",
                    subtitle=f"{subtitle} · AI（{self._difficulty.label}）",
                    detail=f"本局共 {view.move_count} 手",
                    seal_text="胜",
                )
            return ResultPresentation(
                kind="lose",
                title="惜败",
                subtitle=f"{subtitle} · AI（{self._difficulty.label}）",
                detail=f"本局共 {view.move_count} 手，胜负乃兵家常事",
                seal_text="负",
            )

        return ResultPresentation(
            kind="win",
            title=f"{view.winner.label}胜",
            subtitle=subtitle,
            detail=f"本局共 {view.move_count} 手",
            seal_text="胜",
        )

    def _confirm_discard_game(
        self,
        title: str,
        message: str,
        *,
        confirm_text: str = "开始新对局",
        cancel_text: str = "取消",
    ) -> bool:
        self._modal_dialog_open = True
        try:
            dialog = ConfirmDialog(
                title,
                message,
                confirm_text=confirm_text,
                cancel_text=cancel_text,
                parent=self._overlay_host(),
            )
            self._active_modal = dialog
            dialog.exec()
            confirmed = dialog.confirm_requested
            dialog.deleteLater()
            self._active_modal = None
            return confirmed
        finally:
            self._modal_dialog_open = False

    def _overlay_host(self) -> QWidget:
        host = self.centralWidget()
        return host if host is not None else self

    def _show_notice(self, title: str, message: str) -> None:
        notice = NoticeOverlay(title, message, parent=self._overlay_host())
        self._active_modal = notice
        try:
            notice.exec()
        finally:
            notice.deleteLater()
            self._active_modal = None

    # ------------------------------------------------------------------
    # 状态同步
    # ------------------------------------------------------------------
    def _sync_ui(self) -> None:
        view = self._session.view
        winner = view.winner
        game_over = view.is_game_over
        if (
            self._record_saved
            and not game_over
            and view.move_count == 0
        ):
            # 联机「再来一局」复用同一个会话，需要为新对局重置记录标记。
            self._record_saved = False

        selected = self._selected
        if selected is not None:
            row, col = selected
            piece = view.board[row][col]
            if (
                game_over
                or piece is None
                or piece.side is not view.side_to_move
            ):
                selected = None
                self._selected = None

        legal_targets: tuple[Square, ...] = ()
        if selected is not None:
            legal_targets = tuple(
                move.target
                for move in self._session.legal_moves_from(*selected)
            )

        online_mode = isinstance(self._session, OnlineGameSession)
        online_session = self._session if online_mode else None
        ai_mode = isinstance(self._session, AIGameSession)
        human_side = (
            self._session.human_side
            if (ai_mode or online_mode)
            else None
        )
        # 联机执黑时棋盘整体颠倒，让自己的棋子在下方。
        self.board_widget.set_flipped(
            online_mode and human_side is Side.BLACK
        )
        self.chat_bar.setVisible(online_mode)
        self.chat_log.setVisible(
            online_mode and self._chat_log_expanded
        )
        self._refresh_chat_controls(online_mode)
        difficulty_label = (
            self._session.difficulty.label if ai_mode else ""
        )
        busy = self._session.busy
        online_status = online_session.status if online_mode else ""
        opponent_connected = True
        if online_mode:
            if human_side is not None:
                players = online_session.players
                opponent_connected = players[human_side.opponent][1]

        for side, card in (
            (Side.RED, self.red_card),
            (Side.BLACK, self.black_card),
        ):
            if online_mode:
                name, connected = online_session.players.get(
                    side, ("", False)
                )
                is_you = side is human_side
                if not name:
                    display_name = (
                        "等待加入" if side is Side.BLACK else "房主"
                    )
                else:
                    display_name = (
                        f"{name}（你）" if is_you else name
                    )
                base_caption = f"执{'红' if side is Side.RED else '黑'}"
                if online_session.ranked:
                    rating = online_session.rating_for(side)
                    base_caption += (
                        f" · {rating}分 · "
                        f"{title_for_rating(rating)}"
                    )
            elif ai_mode:
                display_name = (
                    "你" if side is human_side else f"AI（{difficulty_label}）"
                )
                base_caption = (
                    f"执{'红' if side is Side.RED else '黑'}，"
                    f"{'先手' if side is Side.RED else '后手'}"
                )
            else:
                display_name = side.label
                base_caption = "先手" if side is Side.RED else "后手"
            card.set_identity(display_name, base_caption)

            if winner is not None:
                active = winner is side
                status = "获胜" if active else "本局结束"
            elif online_mode:
                if online_status == ONLINE_WAITING:
                    active = False
                    status = "等待对手" if side is Side.RED else "未加入"
                elif online_status == ONLINE_DISCONNECTED:
                    active = False
                    status = "连接断开"
                elif not connected:
                    active = False
                    status = "已断开"
                elif view.is_check and side is view.side_to_move:
                    active = True
                    status = "被将军"
                else:
                    active = side is view.side_to_move
                    status = "行棋" if active else "等待"
            elif view.is_check and side is view.side_to_move:
                active = True
                status = "被将军"
            elif ai_mode:
                active = side is view.side_to_move
                if active and side is not human_side and busy:
                    status = "思考中"
                elif active:
                    status = "行棋"
                else:
                    status = "等待"
            else:
                active = side is view.side_to_move
                status = "行棋" if active else "等待"
            card.set_state(active, status)

        reason_label = (
            view.end_reason.label
            if isinstance(view.end_reason, EndReason)
            else "胜负已分"
        )
        if winner is not None:
            if online_mode:
                who = "你" if winner is human_side else "对手"
                pill_text = f"{who}获胜 · {reason_label}"
            elif ai_mode:
                who = "你" if winner is human_side else "AI"
                pill_text = f"{who}获胜 · {reason_label}"
            else:
                pill_text = f"{winner.label}胜 · {reason_label}"
        elif online_mode:
            if online_status == ONLINE_WAITING:
                pill_text = "等待好友接受挑战…"
            elif online_status == ONLINE_DISCONNECTED:
                pill_text = "连接已断开"
            elif not opponent_connected:
                pill_text = "对手已断开"
            elif busy:
                pill_text = "同步中…"
            elif view.is_check:
                pill_text = (
                    "你被将军"
                    if view.side_to_move is human_side
                    else "对手被将军"
                )
            elif view.side_to_move is human_side:
                pill_text = "你的回合"
            else:
                pill_text = "等待对手…"
        elif view.is_check:
            if ai_mode:
                who = "你" if view.side_to_move is human_side else "AI"
                pill_text = f"{who}被将军"
            else:
                pill_text = f"{view.side_to_move.label}被将军"
        elif ai_mode and busy:
            pill_text = "AI 思考中…"
        elif ai_mode:
            pill_text = (
                "你的回合"
                if view.side_to_move is human_side
                else "AI 回合"
            )
        else:
            pill_text = f"{view.side_to_move.label}回合"
        self.turn_pill.setText(pill_text)
        self._set_turn_style(
            result=game_over,
            check=view.is_check and not game_over,
        )

        if game_over:
            self.move_label.setText(
                f"第 {view.move_count} 手 · 对局结束"
            )
        elif online_mode:
            if online_status == ONLINE_WAITING:
                self.move_label.setText("自建房 · 等待好友接受挑战")
            elif online_status == ONLINE_DISCONNECTED:
                self.move_label.setText("第 0 手 · 连接已断开")
            elif not opponent_connected:
                self.move_label.setText(
                    f"第 {view.move_count} 手 · 对手已断开"
                )
            elif busy:
                self.move_label.setText(
                    f"第 {view.move_count} 手 · 同步中…"
                )
            else:
                who = (
                    "你"
                    if view.side_to_move is human_side
                    else "对手"
                )
                self.move_label.setText(
                    f"第 {view.move_count} 手 · {who}行棋"
                )
        elif ai_mode and busy:
            self.move_label.setText(
                f"第 {view.move_count} 手 · AI 思考中…"
            )
        elif ai_mode:
            who = "你" if view.side_to_move is human_side else "AI"
            self.move_label.setText(
                f"第 {view.move_count} 手 · {who}行棋"
            )
        else:
            self.move_label.setText(
                f"第 {view.move_count} 手 · {view.side_to_move.label}行棋"
            )

        if online_mode:
            waiting_host = (
                online_status == ONLINE_WAITING
                and human_side is Side.RED
            )
            self.invite_button.setVisible(waiting_host)
            self.invite_button.setEnabled(waiting_host)
            self.undo_button.setToolTip("请求悔棋（需对手同意）")
            if online_status == ONLINE_PLAYING:
                self.restart_button.setText("认输")
                self.restart_button.setEnabled(True)
            elif online_status == ONLINE_FINISHED:
                self.restart_button.setText("请求再战")
                self.restart_button.setEnabled(opponent_connected)
            else:
                self.restart_button.setText("认输")
                self.restart_button.setEnabled(False)
            self.menu_back_button.setText("离开房间")
            self.hint_label.setText(
                "点击「邀请好友」让好友接受挑战后开局"
                if waiting_host
                else "Ctrl+Z 请求悔棋"
            )
        else:
            self.invite_button.setVisible(False)
            self.undo_button.setToolTip(
                "撤销你与 AI 的上一回合（Ctrl+Z）"
                if ai_mode
                else "撤销上一手（Ctrl+Z）"
            )
            self.restart_button.setText("重新开始")
            self.restart_button.setEnabled(True)
            self.menu_back_button.setText("返回主菜单")
            self.hint_label.setText("Ctrl+Z 悔棋  Ctrl+N 重开")
        self.undo_button.setEnabled(self._session.can_undo)
        self.menu_back_button.setEnabled(True)

        board_view = view.with_selection(selected, legal_targets)
        self.board_widget.set_view(board_view)
        self.board_widget.set_interaction_enabled(self._human_can_play())
        self._sync_settings_controls()

    def _set_turn_style(self, *, result: bool, check: bool) -> None:
        result_value = "true" if result else "false"
        check_value = "true" if check else "false"
        changed = False
        if self.turn_pill.property("result") != result_value:
            self.turn_pill.setProperty("result", result_value)
            changed = True
        if self.turn_pill.property("check") != check_value:
            self.turn_pill.setProperty("check", check_value)
            changed = True
        if changed:
            self.turn_pill.style().unpolish(self.turn_pill)
            self.turn_pill.style().polish(self.turn_pill)
            self.turn_pill.update()

    # ------------------------------------------------------------------
    # 关闭保护
    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 接口
        self._closing = True
        self._result_timer.stop()
        modal = self._active_modal
        if modal is not None:
            modal.reject()
        try:
            self.online_page.shutdown()
        except RuntimeError:
            pass
        self._session.shutdown()
        super().closeEvent(event)


__all__ = ["MainWindow", "PlayerCard"]
