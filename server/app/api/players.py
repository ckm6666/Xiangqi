"""排行榜与公开玩家资料接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from server.app.api.deps import make_current_user
from server.app.api.profile import profile_payload
from server.app.users import AuthManager, User, UserStore
from xiangqi.shared.profile import PlayerStats, title_for_rating


def create_router(
    users: UserStore,
    auth: AuthManager,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/players", tags=["players"])
    current_user = make_current_user(auth)

    @router.get("")
    def leaderboard(
        limit: int = 50,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        for rank, player in enumerate(
            users.leaderboard(limit), start=1
        ):
            stats = PlayerStats(
                player.wins, player.losses, player.draws
            )
            rows.append(
                {
                    "rank": rank,
                    "nickname": player.nickname,
                    "rating": player.rating,
                    "title": title_for_rating(player.rating),
                    "avatar": player.avatar,
                    "wins": stats.wins,
                    "losses": stats.losses,
                    "draws": stats.draws,
                    "games": stats.games,
                    "win_rate": stats.win_rate,
                    "record_text": stats.record_text,
                    "is_self": player.id == user.id,
                }
            )
        return {"players": rows, "count": len(rows)}

    @router.get("/search")
    def search_players(
        request: Request,
        q: str = "",
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        manager = getattr(
            request.app.state, "room_manager", None
        )
        rows: list[dict[str, object]] = []
        for player in users.search_users(
            q, limit=20, exclude_id=user.id
        ):
            rows.append(
                {
                    "nickname": player.nickname,
                    "rating": player.rating,
                    "title": title_for_rating(player.rating),
                    "avatar": player.avatar,
                    "record_text": PlayerStats(
                        player.wins, player.losses, player.draws
                    ).record_text,
                    "relationship": users.relationship(
                        user.id, player.id
                    ),
                    "online": bool(
                        manager is not None
                        and manager.is_online(player.id)
                    ),
                    "game_status": (
                        manager.game_status_for(player.id)
                        if manager is not None
                        else ""
                    ),
                    "in_game": bool(
                        manager is not None
                        and manager.in_game(player.id)
                    ),
                }
            )
        return {"players": rows, "query": q.strip()}

    def player_payload(
        nickname: str,
        user: User,
    ) -> dict[str, object]:
        target = users.find_by_nickname(nickname)
        if target is None:
            raise HTTPException(status_code=404, detail="玩家不存在")
        relationship = users.relationship(user.id, target.id)
        payload = profile_payload(
            target, relationship=relationship
        )
        payload["is_self"] = target.id == user.id
        return payload

    @router.get("/detail")
    def player_profile_by_query(
        nickname: str,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        """按查询参数读取资料，昵称可包含斜杠等特殊字符。"""
        return player_payload(nickname, user)

    @router.get("/{nickname}")
    def player_profile(
        nickname: str,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        return player_payload(nickname, user)

    return router


__all__ = ["create_router"]
