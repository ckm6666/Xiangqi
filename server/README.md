# Xiangqi Online Server（0.7.0 账号 + 排位 + 个人资料）

**状态：可运行。** 账号、积分、战绩、头像与好友持久化在 SQLite，房间在
内存：

- 昵称 + 密码注册/登录，PBKDF2-HMAC-SHA256 哈希，REST 签发令牌；
- WebSocket 首帧用令牌认证，之后以账号身份自建房或排位匹配；
- 自建房：创建者执红，可直接邀请在线好友；好友收到挑战弹窗，接受后
  执黑入座；房间号仅内部使用，客户端不需要输入房间码；
- 排位匹配队列：按积分相近（±300）优先配对，取消匹配或断线立即出队，
  Elo K=32 更新并持久化；普通房间不影响积分；
- 每局联机终局累计双方胜/负/连胜；成就由累计战绩与积分实时派生；
- 个人资料接口：称号、战绩、胜率、成就、6 个内置头像/自定义上传；
- 好友系统：好友申请、同意/拒绝、好友列表；排行榜按积分降序返回
  所有已登录账号的名次、称号、头像与战绩，并可查看任意玩家资料；
- 好友私聊：消息持久化在 SQLite，支持历史、未读/已读和 WebSocket
  实时推送；好友列表返回在线状态与未读数；
- 对局聊天：表情/快捷评论/文本由服务端校验、限流后广播给对局双方；
- 好友观战：好友列表返回在线/对局状态；观战连接实时接收权威快照，
  不参与走子、聊天、结算与房间在线状态；
- 服务器权威走子：客户端只发送 `move_intent`，由服务端复用
  `xiangqi.shared.game_model.GameModel` 校验并广播完整 `game_state`；
  `game_state.moves` 携带完整着法历史供客户端棋谱复盘；
- 悔棋请求/回应（对手同意后撤销一手）；
- 认输、双方同意的再来一局；
- 断线状态展示与同账号重连。

尚未实现：每步时钟与超时判负。房间在进程内存中；
登录令牌保存在服务端内存，有效期 24 小时，服务端重启后需重新登录。
本实现面向本地/局域网娱乐，不是公网生产级认证系统。

## 安装与启动

```powershell
cd <项目根目录>
py -3 -m venv server\.venv
server\.venv\Scripts\python.exe -m pip install -r server\requirements-dev.txt
python run_server.py
# 等价于：
# server\.venv\Scripts\python.exe -m uvicorn server.app.main:app --host 127.0.0.1 --port 8765

# 后台运行（无控制台窗口；也可在项目根目录双击 start_server.vbs）
python run_server.py --background
python run_server.py --status
python run_server.py --stop        # 或双击 stop_server.vbs
```

后台模式的 PID 与日志位于 `server/data/server-<端口>.pid`、
`server-<端口>.out.log` 与 `server-<端口>.err.log`。

健康检查：`GET http://127.0.0.1:8765/api/v1/health` 返回
`{"status": "ok", "version": "0.7.0"}`。

客户端默认连接固定公网入口
`wss://gomoku-host.taild407ad.ts.net:8443/api/v1/ws`（Tailscale Funnel
代理本机 8765 端口）；本机调试可在大厅改为
`ws://127.0.0.1:8765/api/v1/ws`。

## 账号接口

- `POST /api/v1/auth/register`：`{"nickname","password"}`；
  昵称 2-20 字符且唯一，密码至少 6 位；返回令牌、昵称与初始排位分。
- `POST /api/v1/auth/login`：`{"nickname","password"}`；
  返回新的令牌、昵称、当前排位分与头像标识。
- 昵称即登录账号；账号、积分、战绩、头像与好友写入
  `server/data/xiangqi.db`。
- WebSocket 连接后必须先发送 `auth`（`{"token": "..."}`），收到
  `auth_ok` 后才能自建房、排位匹配或接收好友挑战。
- 令牌保存在服务端内存，默认 24 小时有效；服务端重启后需重新登录。

## 个人资料接口

写操作统一使用 `Authorization: Bearer <token>`：

- `GET /api/v1/profile`：昵称、积分、称号、下一称号阈值、胜/和/负、
  总对局、胜率、最高连胜、头像标识与成就列表。个人资料不再包含好友。
- `POST /api/v1/profile/avatar`：`{"avatar": "default:1"}` 选择内置头像
  （`default:1`～`default:6`）。
- `POST /api/v1/profile/avatar/upload`：请求体为原始 PNG 字节
  （≤ 512 KB），保存为自定义头像；客户端会先裁剪为 256×256。
- `GET /api/v1/profile/avatar?nickname=昵称`（也兼容
  `GET /api/v1/profile/avatar/{昵称}`）：公开读取自定义头像 PNG；
  内置头像返回 404，由客户端本地绘制。
- `GET /api/v1/profile/friends`：返回 `friends`（好友）、`incoming`
  （收到的申请）、`outgoing`（我发出的申请）；好友项附带 `online`、
  未读私聊数 `unread`、`game_status`（`playing` / `waiting` / 空）与
  `in_game`。
- `POST /api/v1/profile/friends`：`{"nickname": "棋友"}` 发送好友申请；
  若对方已先申请则直接成为好友。
- `POST /api/v1/profile/friends/accept` / `decline`：
  `{"nickname": "申请人"}` 同意或拒绝收到的申请。

## 好友私聊接口

私聊只允许已接受的好友之间进行；正文最多 200 字，服务端会净化控制/
格式字符并做 10 秒 10 条的限流。

- `GET /api/v1/messages?nickname=好友&limit=50`：读取最近私聊（时间正序），
  本次返回的来信会被标记为已读。
- `POST /api/v1/messages?nickname=好友`：`{"content": "你好"}` 发送私聊；
  对方在线时通过 WebSocket `direct_message` 实时推送，离线时存入 SQLite。
- `POST /api/v1/messages/read?nickname=好友`：
  `{"message_ids": ["12", "13"]}` 把聊天窗已显示的来信标记为已读。

## 玩家与排行榜接口

- `GET /api/v1/players?limit=50`：按积分降序的排行榜；收录所有已登录
  （注册）的账号，没有对局记录的玩家也会以初始积分上榜。每项包含
  `rank`、昵称、积分、称号、头像、战绩与 `is_self`。
- `GET /api/v1/players/search?q=昵称`：按昵称模糊搜索玩家（排除自己），
  返回称号、积分、头像与好友关系。
- `GET /api/v1/players/detail?nickname=昵称`（也兼容
  `GET /api/v1/players/{昵称}`）：查看任意玩家资料，附带
  `relationship`：`self` / `friend` / `pending_out` / `pending_in` /
  `none`，客户端据此显示「申请加好友 / 已发送申请 / 同意好友申请 /
  已是好友」。

称号阈值与成就规则位于 `xiangqi.shared.profile` /
`xiangqi.shared.achievements`，客户端与服务端共用：

| 积分 | 称号 |
|---|---|
| < 1200 | 棋童 |
| 1200+ | 棋士 |
| 1400+ | 上品棋士 |
| 1600+ | 棋师 |
| 1800+ | 大师 |
| 2000+ | 特级大师 |
| 2200+ | 棋圣 |

积分只在 `ranked: true` 的排位房间结算：胜方加 Elo、负方减 Elo；
普通房间终局只累计战绩与连胜，不改变积分。

## 目录

```text
server/
├── app/
│   ├── main.py          # create_app()、/api/v1/health、路由装配
│   ├── users.py         # SQLite 账号/积分/战绩/头像/好友/私聊、PBKDF2、令牌
│   ├── api/auth.py      # REST 注册/登录
│   ├── api/profile.py   # 个人资料/头像/好友申请
│   ├── api/messages.py  # 好友私聊历史/发送/已读
│   ├── api/players.py   # 排行榜与公开玩家资料
│   ├── api/deps.py      # Bearer 令牌依赖
│   └── ws/
│       ├── endpoint.py  # /api/v1/ws 收发循环、令牌认证
│       └── rooms.py     # RoomManager：房间、排位、战绩、权威走子、悔棋、观战
├── data/xiangqi.db      # 运行期账号数据库（不提交）
├── tests/test_online.py
├── requirements.txt
└── requirements-dev.txt
```

## 协议（v1）

信封：

```json
{
  "protocol": 1,
  "type": "move_intent",
  "request_id": "b7c1…",
  "payload": {}
}
```

棋盘编码：10×9 整数数组，空格 0，红方棋子 `+1..+7`，黑方 `-1..-7`
（与 `PieceKind` 一致）。行 0 = 黑方底线。

消息类型：

| 方向 | 类型 | 载荷 |
|---|---|---|
| C→S | `auth` | `{"token": "..."}`（连接后首帧） |
| C→S | `create_room` | 空 |
| C→S | `join_room` | `{"room_code": "ABCD"}`（兼容旧客户端，当前 UI 不使用） |
| C→S | `join_queue` | 空（排位匹配） |
| C→S | `invite_friend` | `{"nickname": "好友"}`（自建房邀请） |
| C→S | `challenge_response` | `{"challenge_id", "accept": true}` |
| C→S | `move_intent` | `{"from_row", "from_col", "to_row", "to_col"}` |
| C→S | `undo_request` | 空 |
| C→S | `undo_response` | `{"accept": true}` |
| C→S | `resign` / `rematch` / `leave` | 空；排队中发送 `leave` 即取消匹配 |
| C→S | `chat` | `{"kind": "emoji"\|"text", "content": "..."}`（对局内） |
| C→S | `spectate` | `{"nickname": "好友"}`（仅限好友且对方正在对局） |
| S→C | `auth_ok` | `{"user_id", "nickname", "rating"}` |
| S→C | `game_state` | 房间、双方、棋盘、行棋方、终局、悔棋/再战、排位信息 |
| S→C | `queue_status` | `{"message", "position", "queued", "rating"}` |
| S→C | `move_rejected` | `{"reason"}` |
| S→C | `undo_requested` | `{"name", "side"}` |
| S→C | `undo_result` | `{"accepted", "reason"}` |
| S→C | `rematch_requested` | `{"name"}` |
| S→C | `invite_result` | `{"status", "accepted", "name", "reason"}` |
| S→C | `challenge` | `{"challenge_id", "name"}`（好友收到挑战） |
| S→C | `challenge_cancelled` | `{"challenge_id", "reason"}` |
| S→C | `chat_message` | `{"kind", "content", "sender_id", "sender_name", "sent_at_ms"}` |
| S→C | `direct_message` | `{"id", "sender_id", "sender_name", "recipient_id", "content", "sent_at_ms"}` |
| S→C | `spectate_ended` | `{"reason"}`（房间关闭时通知观战者） |
| S→C | `error` | `{"message"}`（发言被拒时带 `request_id`） |

`game_state` 关键字段：

```json
{
  "room_code": "WXYZ",
  "status": "waiting | playing | finished",
  "ranked": true,
  "your_side": "red | black | null",
  "spectator": false,
  "players": {
    "red": {
      "name": "...", "connected": true,
      "rating": 1216, "rating_delta": 16
    },
    "black": {
      "name": "...", "connected": true,
      "rating": 1184, "rating_delta": -16
    }
  },
  "board": [[0, -5, ...], ...],
  "moves": [
    {"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0}
  ],
  "side_to_move": "red",
  "last_move": {"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0},
  "is_check": false,
  "winner": null,
  "end_reason": null,
  "move_count": 0,
  "undo_requester": null,
  "rematch_requests": [],
  "state_version": 1
}
```

服务器权威：客户端在收到 `game_state` 前不提交本地落子；客户端用
`request_id` / `state_version` 忽略过期消息。

积分与战绩：

- 初始 1200，Elo K=32；胜负按双方分差计算期望得分；
- 仅排位匹配产生的房间（`ranked: true`）计分；
- 终局快照的 `players.*.rating_delta` 为本局加减分，再来一局后清空；
- 所有联机终局都会给双方累计胜/负与当前/最高连胜，且只记录一次；
- 积分与战绩写入 SQLite 账号表，排行榜、个人资料与好友列表直接读取。

## 测试

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_online -v
```

测试使用 FastAPI `TestClient` 的双 WebSocket 连接，覆盖注册/登录、
重复昵称、错误密码、未认证连接拒绝、权威走子与完整着法历史、错误回合、
非法着法、悔棋同意/拒绝、认输、再战、断线、同账号重连、满房拒绝，
排位队列配对/取消/出队、Elo 加减分与持久化、再战清除加减分，以及
个人资料、战绩、成就、默认/自定义头像、好友申请/同意/拒绝、昵称搜索、
排行榜（包含尚无对局的新账号）、玩家资料、自建房邀请与挑战接受/拒绝、
对局表情/评论广播与限流、好友私聊持久化/未读/已读/实时推送、
好友对局状态与观战只读快照。

## 已知限制

- 房间在进程内存中；账号、积分、战绩、头像、好友与私聊消息持久化在
  `server/data/xiangqi.db`；对局聊天不落库；
- 登录令牌保存在进程内存，24 小时有效，服务端重启后需重新登录；
- 断线后房间保留以便同账号重连，但双方都断开后房间删除；
- 无每步时钟与超时判负；
- 协议仍为 v1，后续加入时钟等能力时会保持向后兼容或升级版本。
