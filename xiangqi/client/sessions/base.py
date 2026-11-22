"""对局会话抽象。

界面只依赖 GameSession 暴露的只读视图、能力声明和信号；具体规则、AI 线程
或未来的网络服务器交互分别由 LocalGameSession / AIGameSession /
OnlineGameSession 实现。这样可以避免把网络状态继续堆进 MainWindow。

所有具体会话都创建在主线程；异步任务（AI 线程、未来网络事件）必须把结果
排队回主线程后再向 UI 发信号。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from xiangqi.client.board_view import BoardView
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.rules import Move


class GameSession(QObject):
    """一局棋的会话接口。

    信号：
        state_changed: 棋盘、回合或忙碌状态发生变化，界面应重新读取 view。
        move_made:     一手棋真实落在权威棋盘上；悔棋、被拒绝或仅发送未
                       确认意图时不会发出，供音效等一次性反馈使用。
        game_over:     本次对局刚刚结束（只在对局结束的那个事件发出）。
        error:         非致命的会话/网络错误，界面可记录或提示，不应阻塞操作。
    """

    state_changed = Signal()
    move_made = Signal()
    game_over = Signal()
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    # ------------------------------------------------------------------
    # 只读状态
    # ------------------------------------------------------------------
    @property
    def view(self) -> BoardView:
        """当前棋盘只读快照；具体会话必须实现。"""
        raise NotImplementedError

    @property
    def model(self) -> Optional[GameModel]:
        """本地/AI 会话可暴露模型用于兼容和测试；在线会话返回 None。"""
        return None

    @property
    def busy(self) -> bool:
        """是否正在等待 AI 计算或远程服务器，应暂时锁住设置。"""
        return False

    @property
    def accepts_human_input(self) -> bool:
        """当前是否允许通过棋盘提交人类落子。"""
        return False

    @property
    def can_undo(self) -> bool:
        """当前会话是否支持并允许悔棋。"""
        return False

    @property
    def move_history(self) -> tuple[Move, ...]:
        """权威完整着法历史；用于棋谱记录与复盘。"""
        return ()

    # ------------------------------------------------------------------
    # 意图/生命周期
    # ------------------------------------------------------------------
    def legal_moves_from(self, row: int, col: int) -> tuple[Move, ...]:
        """返回指定棋子的合法着法；默认无。"""
        return ()

    def request_move(
        self,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
    ) -> bool:
        """请求落子；返回是否被会话接受（不代表在线服务器最终确认）。"""
        return False

    def request_undo(self) -> bool:
        """请求悔棋；联机会话应把请求发给对手，由对手决定是否同意。"""
        return False

    def request_restart(self) -> bool:
        """请求重新开始/再来一局；联机会话以后应改成服务器授权流程。"""
        return False

    def pause(self) -> None:
        """暂停由本会话发起的异步动作，供模态框或切页使用。"""
        return None

    def resume(self) -> None:
        """恢复因 pause 暂停的异步动作。"""
        return None

    def shutdown(self) -> None:
        """关闭会话并等待后台任务结束；由主窗口替换/关闭时调用。"""
        return None


__all__ = ["GameSession"]
