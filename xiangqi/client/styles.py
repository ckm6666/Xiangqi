"""应用级 QSS 样式（古风水墨 + 宣纸）。

界面整体采用淡墨山水、宣纸、朱砂与金的配色；图片背景、纸纹、印章和棋盘画框
由 :mod:`xiangqi.client.ui_theme` 与 :mod:`xiangqi.client.board_widget` 自绘，
本文件只负责颜色、字体、边距和控件状态。颜色值与 ``theme_palette`` 对应。

注意：不在这里指定全局 font-family，应用入口通过 QFont.setFamilies 设置
“站酷小薇体 → 微软雅黑 UI → Segoe UI”的字体回退链；标题控件单独使用
“Ma Shan Zheng”书法字体。
"""

from __future__ import annotations

from typing import Final

APP_STYLE: Final[str] = """
/* ------------------------------ 基础外观 ------------------------------ */
QMainWindow {
    background-color: #F5EFE3;
}

QWidget#centralWidget,
QStackedWidget#mainStack,
QWidget#menuPage,
QWidget#gamePage,
QWidget#onlinePanel,
QWidget#onlineStack,
QWidget#onlinePage,
QWidget#onlineScrollBody,
QScrollArea#onlineScroll,
QScrollArea#onlineScroll > QWidget#qt_scrollarea_viewport {
    background: transparent;
}

QLabel {
    color: #26221C;
    background-color: transparent;
}

QToolTip {
    color: #FFF9EF;
    background-color: #3C3127;
    border: 1px solid #B8934E;
    border-radius: 4px;
    padding: 6px 9px;
}

/* ------------------------------ 顶部标题 ------------------------------ */
QLabel#brandTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 31px;
    font-weight: normal;
}

QLabel#brandSubtitle {
    color: #756C5E;
    font-size: 12px;
    padding-top: 1px;
}

QLabel#turnPill {
    color: #4C463C;
    background-color: rgba(251, 247, 238, 228);
    border: 1px solid #C9B99F;
    border-left: 3px solid #B8934E;
    border-radius: 4px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: bold;
}

QLabel#turnPill[result="true"] {
    color: #FFF9EF;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
    border-left: 3px solid #E3D1A9;
}

/* ------------------------------ 联机页 ------------------------------ */
QWidget#onlineCentral {
    background: transparent;
}

QFrame#onlineCard {
    background-color: rgba(252, 248, 239, 232);
    border: 1px solid #D3C4AD;
    border-top: 3px solid #B8934E;
    border-radius: 8px;
}

QLabel#onlineTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 31px;
    font-weight: normal;
}

QLabel#onlineSubtitle {
    color: #756C5E;
    font-size: 13px;
}

QLabel#onlineRoomTitle {
    color: #26221C;
    font-size: 19px;
    font-weight: bold;
}

QLabel#onlineClock {
    color: #5A4A38;
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 4px 9px;
    font-size: 12px;
}

QLabel#rankBadge {
    color: #6B4725;
    background-color: #F1E4CC;
    border: 1px solid #B8934E;
    border-radius: 8px;
    padding: 4px 14px;
    font-size: 13px;
    font-weight: bold;
}

QLabel#rankSummary {
    color: #756C5E;
    font-size: 12px;
}

QLabel#sectionTitle {
    color: #4C463C;
    font-size: 13px;
    font-weight: bold;
    padding-top: 3px;
}

QLabel#onlineRatingResult {
    color: #7A4A24;
    background-color: #F3E6D2;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 13px;
    font-weight: bold;
}

QLabel#onlineAchievementResult {
    color: #7E2C22;
    background-color: rgba(184, 147, 78, 0.16);
    border: 1px solid #B8934E;
    border-radius: 4px;
    padding: 6px 10px;
    font-family: "Ma Shan Zheng";
    font-size: 15px;
    letter-spacing: 1px;
}

QLabel#onlineStatus {
    color: #756C5E;
    font-size: 12px;
}

QLabel#onlineStatus[error="true"] {
    color: #9E3B2E;
}

QLabel#onlineUndoStatus {
    color: #7A4A24;
    background-color: #F3E6D2;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 12px;
}

QLabel#onlineError {
    color: #9E3B2E;
    font-size: 12px;
}

QLabel#formLabel {
    color: #756C5E;
    font-size: 12px;
}

QPushButton#smallButton {
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    color: #5A4A38;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 11px;
}

QPushButton#smallButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QPushButton#lobbyBackButton {
    color: #4C463C;
    background-color: rgba(247, 239, 226, 235);
    border: 1px solid #C9B99F;
    border-left: 3px solid #B8934E;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton#lobbyBackButton:hover {
    background-color: #F0E2CC;
    border-color: #B8934E;
    border-left: 3px solid #9E3B2E;
}

QPushButton#lobbyNavButton {
    color: #5A4A38;
    background-color: rgba(251, 247, 238, 215);
    border: 1px solid #D8C9B2;
    border-bottom: 2px solid #B8934E;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton#lobbyNavButton:hover {
    color: #7E2C22;
    background-color: #F1E4CC;
    border-color: #B8934E;
}

QPushButton#lobbyNavButton:pressed {
    background-color: #E6D3B7;
}

QPushButton#lobbySecondaryButton {
    color: #7E2C22;
    background-color: transparent;
    border: 1px solid #D3C4AD;
    border-radius: 6px;
    padding: 9px 16px;
    font-size: 13px;
    font-weight: normal;
}

QPushButton#lobbySecondaryButton:hover {
    background-color: #F6EFE4;
    border-color: #B8934E;
    color: #4C463C;
}

QTableWidget#leaderboardTable {
    color: #3A3128;
    background-color: rgba(251, 247, 238, 238);
    alternate-background-color: #F7F1E5;
    border: 1px solid #D8C9B2;
    border-radius: 5px;
    gridline-color: transparent;
    font-size: 12px;
    selection-background-color: #F1E4CC;
    selection-color: #26221C;
}

QTableWidget#leaderboardTable::item {
    padding: 3px 6px;
}

QHeaderView::section {
    color: #756C5E;
    background-color: #E9DFCE;
    border: none;
    border-bottom: 1px solid #C9B99F;
    padding: 5px 6px;
    font-size: 11px;
    font-weight: bold;
}

QLineEdit#onlineInput {
    color: #332C24;
    background-color: #FBF7EE;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 8px 10px;
    min-height: 20px;
    font-size: 13px;
}

QLineEdit#onlineInput:hover {
    border-color: #B8934E;
}

QLineEdit#onlineInput:focus {
    border: 1px solid #8E6C32;
}

QLineEdit#onlineInput:disabled {
    color: #B3A898;
    background-color: #EEE8DF;
    border-color: #DCD0BC;
}

QScrollArea#onlineScroll {
    border: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background-color: #C9B99F;
    border-radius: 4px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover {
    background-color: #B8934E;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background-color: #C9B99F;
    border-radius: 4px;
    min-width: 28px;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
    width: 0px;
}

/* ------------------------------ 主菜单 ------------------------------ */
QFrame#menuCard {
    background: transparent;
    border: none;
}

QLabel#menuTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 40px;
    font-weight: normal;
    padding-top: 2px;
}

QLabel#menuSubtitle {
    color: #756C5E;
    font-size: 13px;
    padding-top: 2px;
}

QLabel#menuFootnote {
    color: #A89C8B;
    font-size: 11px;
}

QLabel#menuVersion {
    color: #4C463C;
    font-size: 12px;
    padding: 2px 8px;
}

QPushButton#menuButton {
    color: #332C24;
    background-color: #F7EFE2;
    border: 1px solid #CDBFA9;
    border-left: 3px solid #B8934E;
    border-radius: 6px;
    padding: 12px 18px;
    font-size: 16px;
    font-weight: bold;
}

QPushButton#menuButton:hover {
    background-color: #F0E2CC;
    border-color: #B8934E;
    border-left: 3px solid #9E3B2E;
}

QPushButton#menuButton:pressed {
    background-color: #E6D3B7;
}

QPushButton#menuPrimaryButton {
    color: #FFF9EF;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
    border-left: 3px solid #E3D1A9;
    border-radius: 6px;
    padding: 12px 18px;
    font-size: 16px;
    font-weight: bold;
}

QPushButton#menuPrimaryButton:hover {
    background-color: #8A3127;
    border-color: #6B241B;
    border-left: 3px solid #E3D1A9;
}

QPushButton#menuPrimaryButton:pressed {
    background-color: #6B241B;
}

QPushButton#menuQuietButton {
    color: #756C5E;
    background-color: transparent;
    border: 1px solid #D3C4AD;
    border-radius: 6px;
    padding: 11px 18px;
    font-size: 15px;
    font-weight: normal;
}

QPushButton#menuQuietButton:hover {
    background-color: #F6EFE4;
    border-color: #B8934E;
    color: #4C463C;
}

QPushButton#menuQuietButton:pressed {
    background-color: #EDE2D1;
}

QPushButton#menuButton:focus,
QPushButton#menuPrimaryButton:focus,
QPushButton#menuQuietButton:focus {
    border: 1px solid #B8934E;
    border-left: 3px solid #9E3B2E;
}

/* ------------------------------ 对局设置栏 ------------------------------ */
QFrame#settingsBar {
    background-color: rgba(251, 247, 238, 214);
    border: 1px solid #D8C9B2;
    border-radius: 6px;
}

QLabel#settingsLabel {
    color: #756C5E;
    font-size: 12px;
    background-color: transparent;
}

QComboBox {
    color: #3F382F;
    background-color: #FBF7EE;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 4px 25px 4px 9px;
    min-height: 20px;
    font-size: 12px;
}

QComboBox:hover {
    border-color: #B8934E;
}

QComboBox:focus {
    border: 1px solid #8E6C32;
}

QComboBox:disabled {
    color: #B3A898;
    background-color: #EEE8DF;
    border-color: #DCD0BC;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 21px;
    border-left: 1px solid #D8C9B2;
}

QComboBox QAbstractItemView {
    color: #3A3128;
    background-color: #FBF7EE;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    selection-background-color: #F1E4CC;
    selection-color: #26221C;
    outline: 0;
    padding: 3px;
}

QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 2px 8px;
}

/* ------------------------------ 声音设置 ------------------------------ */
QToolButton#soundButton {
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    border-radius: 6px;
}

QToolButton#soundButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QToolButton#soundButton:pressed {
    background-color: #E2D3BC;
}

QToolButton#soundButton:disabled {
    background-color: #EEE8DF;
    border-color: #DCD0BC;
}

QToolButton#soundButton::menu-indicator {
    image: none;
    width: 0px;
}

QMenu#soundMenu {
    background-color: #FBF7EE;
    border: 1px solid #C9B99F;
    border-radius: 6px;
    padding: 4px;
}

QMenu#soundMenu::item {
    color: #3F382F;
    padding: 6px 14px;
    border-radius: 3px;
}

QMenu#soundMenu::item:selected {
    background-color: #F1E4CC;
}

QMenu#soundMenu::separator {
    height: 1px;
    background-color: #D8C9B2;
    margin: 4px 8px;
}

QWidget#volumeRow {
    background-color: transparent;
}

QLabel#volumeLabel {
    color: #5A4A38;
    font-size: 12px;
    background-color: transparent;
}

QLabel#volumeValue {
    color: #A89C8B;
    font-size: 11px;
    background-color: transparent;
}

QSlider#volumeSlider {
    min-height: 18px;
    background-color: transparent;
}

QSlider#volumeSlider::groove:horizontal {
    height: 4px;
    border-radius: 2px;
    background-color: #DCD0BC;
}

QSlider#volumeSlider::sub-page:horizontal {
    height: 4px;
    border-radius: 2px;
    background-color: #B8934E;
}

QSlider#volumeSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -6px 0px;
    border-radius: 7px;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
}

/* ------------------------------ 棋手状态卡片 ------------------------------ */
QFrame#playerCard {
    background-color: rgba(252, 248, 239, 214);
    border: 1px solid #D3C4AD;
    border-radius: 8px;
}

QFrame#playerCard[active="true"] {
    background-color: #F3E6D2;
    border: 1px solid #9E3B2E;
}

QLabel#playerName {
    color: #332C24;
    font-size: 15px;
    font-weight: bold;
}

QLabel#playerCaption {
    color: #756C5E;
    font-size: 12px;
    padding-top: 2px;
}

QFrame#playerCard[active="true"] QLabel#playerName,
QFrame#playerCard[active="true"] QLabel#playerCaption {
    color: #7E2C22;
}

QLabel#stoneBadgeBlack {
    background-color: #171717;
    border: 1px solid #B8934E;
    border-radius: 13px;
}

QLabel#stoneBadgeWhite {
    background-color: #FBF7EE;
    border: 1px solid #A89C8B;
    border-radius: 13px;
}

/* ------------------------------ 底部操作区 ------------------------------ */
QLabel#moveInfo {
    color: #4C463C;
    font-size: 13px;
    font-weight: bold;
}

QLabel#hintLabel {
    color: #756C5E;
    font-size: 11px;
}

QPushButton {
    color: #3D3125;
    background-color: #F2E9DA;
    border: 1px solid #D9C9B3;
    border-radius: 5px;
    padding: 9px 17px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QPushButton:pressed {
    background-color: #E2D3BC;
}

QPushButton:focus {
    border: 1px solid #B8934E;
}

QPushButton#undoButton {
    background-color: #F3EADA;
    border: 1px solid #D9C9B3;
    color: #554534;
}

QPushButton#undoButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QPushButton#menuBackButton {
    background-color: #F3EADA;
    border: 1px solid #D9C9B3;
    color: #554534;
}

QPushButton#menuBackButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QPushButton#restartButton {
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
    color: #FFF9EF;
}

QPushButton#restartButton:hover {
    background-color: #8A3127;
    border-color: #6B241B;
}

QPushButton#restartButton:pressed {
    background-color: #6B241B;
}

QPushButton#undoButton:focus,
QPushButton#restartButton:focus,
QPushButton#menuBackButton:focus {
    border: 1px solid #B8934E;
}

QPushButton:disabled,
QPushButton#undoButton:disabled,
QPushButton#restartButton:disabled,
QPushButton#menuBackButton:disabled {
    background-color: #EEE8DF;
    border-color: #DCD0BC;
    color: #B3A898;
}

/* ------------------------------ 终局弹窗 ------------------------------ */
/* 弹窗是主窗口内的一层模态遮罩（QWidget），不再是独立 QDialog 窗口。 */
QWidget#resultDialog {
    background: transparent;
}

QLabel#resultSeal,
QLabel#resultDivider {
    background: transparent;
}

QLabel#resultTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 38px;
    font-weight: normal;
}

QLabel#resultSubtitle {
    color: #4C463C;
    font-size: 14px;
}

QLabel#resultDetail {
    color: #756C5E;
    font-size: 12px;
}

QWidget#confirmDialog {
    background: transparent;
}

QLabel#confirmSeal,
QLabel#confirmDivider {
    background: transparent;
}

QLabel#confirmTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 30px;
    font-weight: normal;
}

QLabel#confirmMessage {
    color: #4C463C;
    font-size: 13px;
}

/* 窗口内提示遮罩（取代原生 QMessageBox，保持全局只有一个窗口）。 */
QWidget#noticeDialog {
    background: transparent;
}

QLabel#noticeSeal {
    background: transparent;
}

QLabel#noticeTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 26px;
    font-weight: normal;
}

QLabel#noticeMessage {
    color: #4C463C;
    font-size: 13px;
}

QPushButton#resultPrimaryButton {
    color: #FFF9EF;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
    border-radius: 5px;
    padding: 10px 30px;
    min-width: 96px;
    font-size: 14px;
    font-weight: bold;
}

QPushButton#resultPrimaryButton:hover {
    background-color: #8A3127;
}

QPushButton#resultPrimaryButton:pressed {
    background-color: #6B241B;
}

QPushButton#resultSecondaryButton {
    color: #4C463C;
    background-color: #F7EFE2;
    border: 1px solid #C9B99F;
    border-radius: 5px;
    padding: 10px 26px;
    min-width: 96px;
    font-size: 14px;
}

QPushButton#resultSecondaryButton:hover {
    background-color: #EDE1CE;
    border-color: #B8934E;
}

QPushButton#resultPrimaryButton:focus,
QPushButton#resultSecondaryButton:focus {
    border: 1px solid #E3D1A9;
}

/* ------------------------------ 残局与棋谱 ------------------------------ */
QWidget#puzzleScrollBody,
QScrollArea#puzzleScroll,
QScrollArea#puzzleScroll > QWidget#qt_scrollarea_viewport,
QWidget#replayRecordsPanel,
QWidget#replayMovesPanel {
    background: transparent;
}

QLabel#puzzleProgress {
    color: #5A4A38;
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: bold;
}

QPushButton#puzzleCard {
    background: transparent;
    border: none;
    padding: 0;
}

QListWidget#replayList,
QListWidget#replayMoveList {
    color: #3A3128;
    background-color: rgba(251, 247, 238, 238);
    border: 1px solid #D8C9B2;
    border-radius: 5px;
    font-size: 12px;
    outline: 0;
}

QListWidget#replayList::item,
QListWidget#replayMoveList::item {
    padding: 6px 8px;
    border-bottom: 1px solid #E3D8C6;
}

QListWidget#replayList::item:selected,
QListWidget#replayMoveList::item:selected {
    background-color: #F1E4CC;
    color: #26221C;
}

QSlider#replaySlider {
    min-height: 20px;
    background-color: transparent;
}

QSlider#replaySlider::groove:horizontal {
    height: 4px;
    border-radius: 2px;
    background-color: #DCD0BC;
}

QSlider#replaySlider::sub-page:horizontal {
    height: 4px;
    border-radius: 2px;
    background-color: #B8934E;
}

QSlider#replaySlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -6px 0px;
    border-radius: 7px;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
}

/* ------------------------------ 弹窗 ------------------------------ */
QMessageBox {
    background-color: #FBF7EE;
}

QMessageBox QLabel {
    color: #332C24;
    font-size: 14px;
}

QMessageBox QPushButton {
    min-width: 84px;
}

/* ------------------------------ 联机聊天 ------------------------------ */
QFrame#chatLogPanel {
    background-color: rgba(252, 248, 239, 226);
    border: 1px solid #D3C4AD;
    border-top: 3px solid #B8934E;
    border-radius: 8px;
}

QScrollArea#chatLogScroll {
    background: transparent;
    border: none;
}

QScrollArea#chatLogScroll > QWidget#qt_scrollarea_viewport {
    background: transparent;
}

QWidget#chatLogBody {
    background: transparent;
}

QLabel#chatLogTitle {
    color: #4C463C;
    font-size: 13px;
    font-weight: bold;
    padding-top: 2px;
}

QLabel#chatLogEntry {
    color: #332C24;
    background-color: rgba(243, 234, 218, 190);
    border: 1px solid #E0D2B8;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
}

QLabel#chatLogEntry[side="self"] {
    color: #7E2C22;
    background-color: rgba(242, 220, 202, 214);
    border-color: #C9A98C;
}

QLabel#chatLogEntry[side="opponent"] {
    color: #2F4A5C;
    background-color: rgba(219, 230, 238, 200);
    border-color: #A9BFCB;
}

QPushButton#emojiPickerButton {
    color: #5A4A38;
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    border-radius: 5px;
    padding: 8px 14px;
    font-size: 13px;
}

QPushButton#emojiPickerButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QPushButton#emojiPickerButton:pressed {
    background-color: #E2D3BC;
}

QPushButton#emojiPickerButton:disabled {
    background-color: #EEE8DF;
    border-color: #DCD0BC;
    color: #B3A898;
}

QPushButton#presetCommentButton {
    color: #5A4A38;
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    border-radius: 5px;
    padding: 8px 14px;
    font-size: 13px;
}

QPushButton#presetCommentButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QPushButton#presetCommentButton:pressed {
    background-color: #E2D3BC;
}

QPushButton#presetCommentButton:disabled {
    background-color: #EEE8DF;
    border-color: #DCD0BC;
    color: #B3A898;
}

/* 对话日志开关：未展开时是普通的描边按钮，展开后用墨色实底表示
   “当前显示中”。 */
QPushButton#chatLogToggleButton {
    color: #5A4A38;
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    border-radius: 5px;
    padding: 8px 14px;
    font-size: 13px;
}

QPushButton#chatLogToggleButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

QPushButton#chatLogToggleButton:pressed {
    background-color: #E2D3BC;
}

QPushButton#chatLogToggleButton:checked {
    color: #FFF9EF;
    background-color: #4C463C;
    border-color: #332C24;
}

QLineEdit#chatInput {
    color: #332C24;
    background-color: #FBF7EE;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 8px 10px;
    min-height: 20px;
    font-size: 13px;
}

QLineEdit#chatInput:hover {
    border-color: #B8934E;
}

QLineEdit#chatInput:focus {
    border: 1px solid #8E6C32;
}

QLineEdit#chatInput:disabled {
    color: #B3A898;
    background-color: #EEE8DF;
    border-color: #DCD0BC;
}

QPushButton#chatSendButton {
    color: #FFF9EF;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
    border-radius: 5px;
    padding: 9px 18px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton#chatSendButton:hover {
    background-color: #8A3127;
}

QPushButton#chatSendButton:pressed {
    background-color: #6B241B;
}

QPushButton#chatSendButton:disabled {
    background-color: #EEE8DF;
    border-color: #DCD0BC;
    color: #B3A898;
}

QLabel#chatLogNotice {
    color: #8A5A2B;
    background-color: transparent;
    font-size: 12px;
    padding: 2px 4px;
}

/* 表情网格里的按钮必须清掉全局的内边距：全局 QPushButton 规则留了
   9px 17px，在 36x36 的小方块里内容宽度会被挤成 0，表情就看不见了。 */
QPushButton#emojiGridButton {
    padding: 0px;
    margin: 0px;
    border: 1px solid #E0D2B8;
    border-radius: 6px;
    background-color: rgba(251, 247, 238, 235);
    font-size: 19px;
    font-weight: normal;
}

QPushButton#emojiGridButton:hover {
    background-color: #F1E4CC;
    border-color: #B8934E;
}

QPushButton#emojiGridButton:pressed {
    background-color: #E6D6BB;
}

QMenu#chatMenu {
    background-color: #FBF7EE;
    border: 1px solid #C9B99F;
    border-radius: 6px;
    padding: 4px;
}

QMenu#chatMenu::item {
    color: #3F382F;
    padding: 6px 14px;
    border-radius: 3px;
}

QMenu#chatMenu::item:selected {
    background-color: #F1E4CC;
}

/* 个人信息 / 好友 / 头像选择：窗口内浮层，不是原生对话框 */
QWidget#paperPanel {
    background: transparent;
}

QLabel#socialPageTitle {
    font-family: "Ma Shan Zheng";
    font-size: 27px;
    color: #26221C;
    letter-spacing: 1px;
}

QLabel#socialSubtitle {
    font-size: 12px;
    color: #756C5E;
}

QLabel#socialSectionTitle {
    font-family: "Ma Shan Zheng";
    font-size: 18px;
    color: #26221C;
    letter-spacing: 1px;
}

QLabel#socialSectionCount {
    font-size: 11px;
    color: #A89C8B;
    padding-left: 4px;
}

QLabel#socialStatus {
    font-size: 11px;
    color: #756C5E;
    padding-left: 2px;
}

QLabel#friendsEmpty {
    color: #A89C8B;
    font-size: 12px;
    letter-spacing: 1px;
    padding: 10px 4px;
}

QLabel#friendsSectionMarker {
    color: #B8934E;
    font-size: 11px;
}

QLabel#friendsSectionMarker[accent="true"] {
    color: #9E3B2E;
}

QFrame#friendsSection {
    background-color: rgba(251, 247, 238, 0.58);
    border: 1px solid #DCCDB4;
    border-radius: 10px;
}

QFrame#friendsSection[accent="true"] {
    background-color: rgba(158, 59, 46, 0.045);
    border: 1px solid #C08A7F;
}

QLabel#profileName {
    font-family: "Ma Shan Zheng";
    font-size: 30px;
    color: #26221C;
    letter-spacing: 1px;
}

QLabel#profileOnline {
    font-size: 12px;
    color: #8A7F70;
}

QLabel#profileOnline[online="true"] {
    color: #4F7A5A;
}

QLabel#profileTagline {
    font-size: 11px;
    color: #A89C8B;
    letter-spacing: 1px;
}

QLabel#profileRankBadge {
    background-color: rgba(184, 147, 78, 0.14);
    border: 1px solid #B8934E;
    border-radius: 14px;
    color: #7E2C22;
    font-family: "Ma Shan Zheng";
    font-size: 17px;
    padding: 2px 12px;
}

QFrame#profileStatTile {
    background-color: rgba(251, 247, 238, 0.72);
    border: 1px solid #DCCDB4;
    border-radius: 9px;
    min-height: 58px;
}

QLabel#profileStatName {
    color: #756C5E;
    font-size: 11px;
    letter-spacing: 1px;
}

QLabel#profileStatValue {
    font-family: "Ma Shan Zheng";
    color: #26221C;
    font-size: 20px;
}

QFrame#friendRow {
    background-color: rgba(255, 252, 244, 0.78);
    border: 1px solid #E3D7C4;
    border-radius: 8px;
}

QFrame#friendRow[online="true"] {
    border-left: 3px solid #5D8A66;
}

QFrame#friendRow[online="false"] {
    border-left: 3px solid #C9B99F;
}

QLabel#friendName {
    color: #26221C;
    font-size: 14px;
    font-weight: bold;
}

QLabel#friendPresence {
    color: #A89C8B;
    font-size: 11px;
}

QLabel#friendPresence[online="true"] {
    color: #4F7A5A;
}

QLabel#friendUnread {
    background-color: #9E3B2E;
    color: #FBF7EE;
    border-radius: 8px;
    font-size: 10px;
    font-weight: bold;
    padding: 1px 7px;
}

QPushButton#socialPrimaryButton {
    background-color: #9E3B2E;
    color: #FBF7EE;
    border: 1px solid #7E2C22;
    border-radius: 8px;
    padding: 7px 16px;
    min-height: 20px;
    font-size: 13px;
}

QPushButton#socialPrimaryButton:hover {
    background-color: #B85546;
}

QPushButton#socialPrimaryButton:pressed {
    background-color: #7E2C22;
}

QPushButton#socialPrimaryButton:disabled {
    background-color: #D8CEC0;
    border-color: #C9B99F;
    color: #A89C8B;
}

QPushButton#socialSecondaryButton {
    background-color: rgba(251, 247, 238, 0.92);
    color: #4C463C;
    border: 1px solid #C9B99F;
    border-radius: 8px;
    padding: 7px 16px;
    min-height: 20px;
    font-size: 13px;
}

QPushButton#socialSecondaryButton:hover {
    background-color: #F5EFE3;
    border-color: #B8934E;
}

QPushButton#socialSecondaryButton:pressed {
    background-color: #E9DFCE;
}

QPushButton#socialSecondaryButton:disabled {
    background-color: #EEE8DF;
    border-color: #D8CEC0;
    color: #B3A898;
}

QPushButton#socialCompactButton {
    background-color: transparent;
    color: #756C5E;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 12px;
}

QPushButton#socialCompactButton:hover {
    background-color: #F1E4CC;
    color: #4C463C;
}

QPushButton#socialCompactButton:pressed {
    background-color: #E9DFCE;
}

QLineEdit#socialSearchInput {
    background-color: #FBF7EE;
    border: 1px solid #C9B99F;
    border-radius: 15px;
    padding: 6px 14px;
    min-height: 22px;
    color: #26221C;
    selection-background-color: #B8934E;
}

QLineEdit#socialSearchInput:focus {
    border-color: #B8934E;
}

QPushButton#avatarChoice {
    background-color: transparent;
    border: 2px solid transparent;
    border-radius: 34px;
    padding: 2px;
}

QPushButton#avatarChoice:hover {
    background-color: rgba(184, 147, 78, 0.10);
    border-color: #B8934E;
}

QPushButton#avatarChoice[current="true"] {
    background-color: rgba(158, 59, 46, 0.08);
    border-color: #9E3B2E;
}

QLabel#avatarPickerHint {
    color: #756C5E;
    font-size: 12px;
}

/* ------------------------------ 成就与勋章 ------------------------------ */
QLabel#achievementSummary {
    color: #756C5E;
    font-size: 12px;
}

QScrollArea#achievementScroll,
QWidget#achievementBody {
    background: transparent;
    border: none;
}

QScrollArea#achievementScroll > QWidget > QWidget {
    background: transparent;
}

QFrame#achievementTile {
    background-color: rgba(251, 247, 238, 0.72);
    border: 1px solid #DCCDB4;
    border-radius: 9px;
}

QFrame#achievementTile[unlocked="true"] {
    background-color: rgba(184, 147, 78, 0.10);
    border: 1px solid #B8934E;
}

QLabel#achievementName {
    font-family: "Ma Shan Zheng";
    font-size: 17px;
    color: #8C8377;
    letter-spacing: 1px;
}

QLabel#achievementName[unlocked="true"] {
    color: #7E2C22;
}

QLabel#achievementDesc {
    color: #8C8377;
    font-size: 10px;
}

QLabel#achievementProgress {
    color: #A89C8B;
    font-size: 10px;
}

QProgressBar#achievementProgressBar {
    background-color: #E7DECF;
    border: none;
    border-radius: 2px;
}

QProgressBar#achievementProgressBar::chunk {
    background-color: #B8934E;
    border-radius: 2px;
}

QScrollArea#socialScroll,
QWidget#socialScrollBody {
    background: transparent;
    border: none;
}

QScrollArea#socialScroll > QWidget > QWidget {
    background: transparent;
}

QTextBrowser#chatMessages {
    background-color: #FBF6EA;
    border: 1px solid #D9CBB3;
    border-radius: 8px;
    padding: 8px;
    color: #2B2118;
}

QLineEdit#chatMessageInput {
    background-color: #FBF6EA;
    border: 1px solid #C9B99F;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 24px;
    color: #2B2118;
}

QLineEdit#chatMessageInput:focus {
    border-color: #B8934E;
}

/* ------------------------------ 中国象棋补充 ------------------------------ */
QLabel#turnPill[check="true"] {
    color: #9E3B2E;
    border-color: #9E3B2E;
}

QLabel#kingBadgeRed {
    background-color: #F7EDDA;
    border: 2px solid #9E3B2E;
    border-radius: 15px;
    color: #A8382A;
    font-family: "KaiTi", "FangSong", "Microsoft YaHei UI";
    font-size: 17px;
    font-weight: bold;
}

QLabel#kingBadgeBlack {
    background-color: #F7EDDA;
    border: 2px solid #26221C;
    border-radius: 15px;
    color: #2A2620;
    font-family: "KaiTi", "FangSong", "Microsoft YaHei UI";
    font-size: 17px;
    font-weight: bold;
}

QWidget#replayPanel,
QWidget#onlinePanel {
    background: transparent;
}

/* ------------------------------ 个人资料 ------------------------------ */
QPushButton#avatarButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 30px;
    padding: 0px;
}

QPushButton#avatarButton:hover {
    background-color: rgba(184, 147, 78, 0.12);
    border-color: #B8934E;
}

QPushButton#avatarButton:focus {
    border-color: #B8934E;
}

QLabel#profileAvatar {
    background: transparent;
}

QLabel#profileName {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 28px;
}

QLabel#profileIdentity {
    color: #7A4A24;
    font-size: 13px;
    font-weight: bold;
}

QLabel#profileRecord {
    color: #4C463C;
    font-size: 13px;
}

QLabel#profileProgress {
    color: #756C5E;
    font-size: 11px;
}

QLabel#profileStatus {
    color: #756C5E;
    font-size: 12px;
}

QLabel#profileStatus[error="true"] {
    color: #9E3B2E;
}

QFrame#profileStatTile {
    background-color: rgba(251, 247, 238, 220);
    border: 1px solid #D8C9B2;
    border-radius: 6px;
}

QLabel#profileStatValue {
    color: #7E2C22;
    font-size: 18px;
    font-weight: bold;
}

QLabel#profileStatCaption {
    color: #756C5E;
    font-size: 11px;
}

QScrollArea#profileScroll,
QScrollArea#profileScroll > QWidget#qt_scrollarea_viewport,
QWidget#profileScrollBody {
    background: transparent;
    border: none;
}

QPushButton#avatarChoice {
    background-color: #F7EFE2;
    border: 1px solid #D3C4AD;
    border-radius: 24px;
    padding: 0px;
}

QPushButton#avatarChoice:hover {
    border-color: #B8934E;
    background-color: #F0E2CC;
}

QPushButton#avatarChoice[selected="true"] {
    border: 2px solid #9E3B2E;
    background-color: #F3E6D2;
}

QLabel#achievementChip {
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
}

QLabel#achievementChip[earned="true"] {
    color: #7E2C22;
    background-color: rgba(184, 147, 78, 0.18);
    border: 1px solid #B8934E;
}

QLabel#achievementChip[earned="false"] {
    color: #A89C8B;
    background-color: rgba(245, 239, 227, 160);
    border: 1px dashed #D3C4AD;
}

QListWidget#friendList {
    color: #3A3128;
    background-color: rgba(251, 247, 238, 200);
    border: 1px solid #D8C9B2;
    border-radius: 5px;
    font-size: 12px;
    outline: 0;
}

QListWidget#friendList::item {
    padding: 4px 8px;
}

QPushButton#profileFriendButton {
    color: #FFF9EF;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton#profileFriendButton:hover {
    background-color: #8A3127;
    border-color: #6B241B;
}

QPushButton#profileFriendButton:disabled {
    color: #B3A898;
    background-color: #EEE8DF;
    border-color: #DCD0BC;
}

/* ------------------------------ 排行榜 / 好友 ------------------------------ */
QLabel#leaderboardTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 29px;
}

QWidget#leaderboardBody,
QWidget#friendsBody {
    background: transparent;
}

QFrame#leaderboardRow,
QFrame#friendsRow {
    background-color: rgba(252, 248, 239, 210);
    border: 1px solid #D8C9B2;
    border-radius: 6px;
}

QFrame#leaderboardRow[self="true"] {
    background-color: #F3E6D2;
    border: 1px solid #B8934E;
}

QFrame#leaderboardRow:hover,
QFrame#friendsRow:hover {
    border-color: #B8934E;
}

QLabel#leaderboardRank {
    color: #756C5E;
    font-family: "Ma Shan Zheng";
    font-size: 22px;
}

QLabel#leaderboardRank[top="true"] {
    color: #9E3B2E;
}

QPushButton#leaderboardAvatar {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 21px;
    padding: 0px;
}

QPushButton#leaderboardAvatar:hover {
    border-color: #B8934E;
    background-color: rgba(184, 147, 78, 0.12);
}

QLabel#leaderboardName {
    color: #332C24;
    font-size: 14px;
    font-weight: bold;
}

QLabel#leaderboardTitleText {
    color: #756C5E;
    font-size: 11px;
}

QLabel#leaderboardRating {
    color: #7E2C22;
    font-size: 15px;
    font-weight: bold;
}

QLabel#leaderboardRecord {
    color: #756C5E;
    font-size: 10px;
}

QLabel#friendsEmpty {
    color: #A89C8B;
    font-size: 11px;
    padding: 3px 6px;
}

QPushButton#friendAcceptButton {
    color: #FFF9EF;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: bold;
}

QPushButton#friendAcceptButton:hover {
    background-color: #8A3127;
}

QPushButton#friendDeclineButton {
    color: #756C5E;
    background-color: #F3EADA;
    border: 1px solid #C9B99F;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 11px;
}

QPushButton#friendDeclineButton:hover {
    background-color: #EADCC8;
    border-color: #B8934E;
}

/* ------------------------------ 棋谱复盘 ------------------------------ */
QLabel#replayTitle {
    color: #26221C;
    font-family: "Ma Shan Zheng";
    font-size: 29px;
}

QFrame#replaySidebar {
    background-color: rgba(251, 247, 238, 205);
    border: 1px solid #D8C9B2;
    border-radius: 8px;
}

QListWidget#replayList {
    color: #3A3128;
    background-color: rgba(252, 248, 239, 200);
    alternate-background-color: rgba(247, 241, 229, 200);
    border: 1px solid #D8C9B2;
    border-radius: 5px;
    font-size: 12px;
    outline: 0;
    selection-background-color: #F1E4CC;
    selection-color: #26221C;
}

QListWidget#replayList::item {
    padding: 5px 7px;
    border-bottom: 1px solid rgba(211, 196, 173, 120);
}

QListWidget#replayList::item:selected {
    border-left: 3px solid #9E3B2E;
}

QLabel#replaySummary {
    color: #4C463C;
    font-size: 13px;
    font-weight: bold;
    padding: 2px 4px;
}

QLabel#replayFrame {
    color: #756C5E;
    font-size: 12px;
}

QSlider#replaySlider {
    min-height: 20px;
    background-color: transparent;
}

QSlider#replaySlider::groove:horizontal {
    height: 5px;
    border-radius: 2px;
    background-color: #DCD0BC;
}

QSlider#replaySlider::sub-page:horizontal {
    height: 5px;
    border-radius: 2px;
    background-color: #B8934E;
}

QSlider#replaySlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0px;
    border-radius: 8px;
    background-color: #9E3B2E;
    border: 1px solid #7E2C22;
}
"""
