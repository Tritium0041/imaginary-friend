"""
FastAPI 后端 - WebSocket 实时游戏接口（支持 GM 流式输出 + 通用桌游引擎）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agents import GMConfig, GMAgent
from ..tools import GameManager
from ..utils import bind_context, setup_logging


class GameCreateRequest(BaseModel):
    """创建游戏请求"""

    player_name: str = "玩家"
    ai_count: int = Field(default=2, ge=2, le=4)
    api_key: str = ""
    base_url: str = ""
    model: str = "claude-sonnet-4-20250514"
    game_definition_name: Optional[str] = Field(
        default=None,
        description="游戏定义 ID，为空则使用原版时空拍卖行",
    )


class GameActionRequest(BaseModel):
    """游戏行动请求"""

    game_id: Optional[str] = None
    action: str


@dataclass
class GameRuntime:
    """运行中的游戏上下文"""

    game_id: str
    gm: GMAgent
    game_mgr: GameManager
    config: dict[str, str]
    loop: asyncio.AbstractEventLoop
    action_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    event_queue: asyncio.Queue[dict[str, Any] | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=256)
    )
    dispatch_task: Optional[asyncio.Task[None]] = None


class ConnectionManager:
    """WebSocket 连接管理"""

    def __init__(self):
        self.connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, game_id: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.connections.setdefault(game_id, set()).add(websocket)

    async def disconnect(self, game_id: str, websocket: WebSocket):
        async with self._lock:
            sockets = self.connections.get(game_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self.connections.pop(game_id, None)

    async def broadcast(self, game_id: str, message: dict[str, Any]):
        async with self._lock:
            sockets = list(self.connections.get(game_id, set()))

        stale_connections: list[tuple[WebSocket, Exception]] = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception as exc:  # noqa: PERF203 - 需要逐个发送并清理失效连接
                stale_connections.append((ws, exc))

        if not stale_connections:
            return

        async with self._lock:
            active = self.connections.get(game_id)
            if not active:
                return
            for ws, exc in stale_connections:
                bind_context(logger, game_id=game_id).warning(
                    "WebSocket broadcast failed: %s",
                    exc,
                )
                active.discard(ws)
            if not active:
                self.connections.pop(game_id, None)

    async def close_all(self):
        async with self._lock:
            all_connections = [
                (game_id, ws)
                for game_id, sockets in self.connections.items()
                for ws in sockets
            ]
            self.connections.clear()

        for game_id, ws in all_connections:
            try:
                await ws.close()
            except Exception as exc:  # noqa: PERF203 - 退出时尽力关闭连接
                bind_context(logger, game_id=game_id).warning(
                    "WebSocket close failed: %s",
                    exc,
                )


active_games: dict[str, GameRuntime] = {}
manager = ConnectionManager()
logger = logging.getLogger(__name__)


def _normalize_output_message(message: str | dict[str, Any]) -> dict[str, Any]:
    """统一输出消息格式，供 HTTP 与 WebSocket 共用。"""
    if isinstance(message, dict):
        message_type = str(message.get("type", ""))
        if message_type == "ai_message":
            return {
                "kind": "ai",
                "player_id": message.get("player_id"),
                "player_name": message.get("player_name"),
                "content": str(message.get("content", "")),
            }
        if message_type == "error":
            return {"kind": "error", "content": str(message.get("content", ""))}
        return {"kind": "gm", "content": str(message.get("content", ""))}
    return {"kind": "gm", "content": str(message)}


def _flatten_content_for_estimation(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return str(content)


def _estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 0
    cjk_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_chars = max(0, len(text) - cjk_chars)
    return cjk_chars + ((other_chars + 3) // 4)


def _build_context_metrics(runtime: GameRuntime) -> dict[str, int]:
    session = runtime.gm.session
    messages = list(getattr(session, "messages", []) or [])

    message_count = len(messages)
    estimated_chars = 0
    estimated_tokens = 0

    for message in messages:
        role = str(getattr(message, "role", ""))
        name = getattr(message, "name", None)
        content_text = _flatten_content_for_estimation(getattr(message, "content", ""))
        message_text = "\n".join(
            part for part in (role, str(name) if name else "", content_text) if part
        )
        estimated_chars += len(message_text)
        estimated_tokens += _estimate_tokens_from_text(message_text) + 4

    api_request_count = int(getattr(session, "api_request_count", 0) or 0)
    api_input_tokens = int(getattr(session, "api_input_tokens", 0) or 0)
    api_output_tokens = int(getattr(session, "api_output_tokens", 0) or 0)
    api_cache_creation_input_tokens = int(
        getattr(session, "api_cache_creation_input_tokens", 0) or 0
    )
    api_cache_read_input_tokens = int(
        getattr(session, "api_cache_read_input_tokens", 0) or 0
    )

    api_request_count = max(0, api_request_count)
    api_input_tokens = max(0, api_input_tokens)
    api_output_tokens = max(0, api_output_tokens)
    api_cache_creation_input_tokens = max(0, api_cache_creation_input_tokens)
    api_cache_read_input_tokens = max(0, api_cache_read_input_tokens)

    api_total_tokens = api_input_tokens + api_output_tokens

    return {
        "message_count": message_count,
        "estimated_chars": estimated_chars,
        "estimated_tokens": estimated_tokens,
        "max_response_tokens": int(getattr(runtime.gm.config, "max_tokens", 0) or 0),
        "api_request_count": api_request_count,
        "api_input_tokens": api_input_tokens,
        "api_output_tokens": api_output_tokens,
        "api_total_tokens": api_total_tokens,
        "api_cache_creation_input_tokens": api_cache_creation_input_tokens,
        "api_cache_read_input_tokens": api_cache_read_input_tokens,
    }


def _build_state_snapshot(runtime: GameRuntime) -> dict[str, Any]:
    state = runtime.game_mgr.get_game_state()
    if not isinstance(state, dict):
        return {"state": state}
    if state.get("error"):
        return state
    state_payload = dict(state)
    state_payload["context_metrics"] = _build_context_metrics(runtime)

    viewer_player_id: Optional[str] = None
    viewer_function_cards: list[dict[str, str]] = []
    game_state = getattr(runtime.game_mgr, "game_state", None)
    players = getattr(game_state, "players", {}) if game_state is not None else {}
    if isinstance(players, dict):
        for player_id, player in players.items():
            if not getattr(player, "is_human", False):
                continue
            viewer_player_id = str(player_id)
            cards = list(getattr(player, "function_cards", []) or [])
            for card in cards:
                if hasattr(card, "model_dump"):
                    card_data = card.model_dump()
                elif isinstance(card, dict):
                    card_data = card
                else:
                    continue
                viewer_function_cards.append(
                    {
                        "id": str(card_data.get("id", "")),
                        "name": str(card_data.get("name", "")),
                        "description": str(card_data.get("description", "")),
                        "effect": str(card_data.get("effect", "")),
                    }
                )
            break

    state_payload["viewer_player_id"] = viewer_player_id
    state_payload["viewer_function_cards"] = viewer_function_cards
    return state_payload


def _build_progress_event(
    *,
    scope: str,
    stage: str,
    message: str,
    percent: Optional[int] = None,
    indeterminate: bool = False,
    status: str = "in_progress",
    game_id: Optional[str] = None,
    action_id: Optional[str] = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "progress",
        "scope": scope,
        "stage": stage,
        "message": message,
        "indeterminate": indeterminate,
        "status": status,
    }
    if percent is not None:
        event["percent"] = max(0, min(100, int(percent)))
    if game_id:
        event["game_id"] = game_id
    if action_id:
        event["action_id"] = action_id
    return event


def _enqueue_runtime_event(runtime: GameRuntime, event: dict[str, Any] | None):
    """无阻塞入队，队列满时丢弃最旧事件，保证最新流消息可达。"""
    try:
        runtime.event_queue.put_nowait(event)
        return
    except asyncio.QueueFull:
        pass

    try:
        runtime.event_queue.get_nowait()
    except asyncio.QueueEmpty:
        return

    try:
        runtime.event_queue.put_nowait(event)
    except asyncio.QueueFull:
        bind_context(logger, game_id=runtime.game_id).warning(
            "Stream queue overflow; dropped oldest event",
        )


def _emit_runtime_event_from_worker(runtime: GameRuntime, event: dict[str, Any]):
    """供线程中的 GM 回调使用，线程安全地把事件送回主事件循环。"""
    try:
        runtime.loop.call_soon_threadsafe(_enqueue_runtime_event, runtime, event)
    except RuntimeError as exc:
        bind_context(logger, game_id=runtime.game_id).warning(
            "Event loop closed while emitting runtime event: %s",
            exc,
        )


async def _dispatch_runtime_events(game_id: str):
    """将每个游戏的事件队列统一广播给对应 WebSocket 客户端。"""
    runtime = active_games.get(game_id)
    if runtime is None:
        return

    while True:
        event = await runtime.event_queue.get()
        if event is None:
            return
        await manager.broadcast(game_id, event)


def _require_runtime(game_id: str) -> GameRuntime:
    runtime = active_games.get(game_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="游戏不存在")
    return runtime


def _normalize_action(raw_action: str) -> str:
    action = raw_action.strip()
    if not action:
        raise ValueError("行动不能为空")
    return action


async def _run_gm_action(runtime: GameRuntime, action: str) -> dict[str, Any]:
    """串行执行 GM 行动，并持续推送流式消息。"""
    streamed_messages: list[dict[str, Any]] = []
    progress_events: list[dict[str, Any]] = []
    action_id = uuid.uuid4().hex[:8]
    action_logger = bind_context(
        logger,
        game_id=runtime.game_id,
        action_id=action_id,
    )

    def emit_progress(
        stage: str,
        message: str,
        *,
        percent: Optional[int] = None,
        indeterminate: bool = False,
        status: str = "in_progress",
    ):
        event = _build_progress_event(
            scope="action",
            stage=stage,
            message=message,
            percent=percent,
            indeterminate=indeterminate,
            status=status,
            game_id=runtime.game_id,
            action_id=action_id,
        )
        progress_events.append(event)
        _enqueue_runtime_event(runtime, event)

    async with runtime.action_lock:
        action_logger.info("Action execution started: %s", action)
        emit_progress("received", "已接收行动请求", percent=8)
        _enqueue_runtime_event(
            runtime,
            {
                "type": "action_status",
                "status": "started",
                "action": action,
                "action_id": action_id,
            },
        )
        emit_progress("processing", "GM 正在处理行动", percent=30, indeterminate=True)
        chunk_started = False

        def collect_output(message: str | dict[str, Any]):
            nonlocal chunk_started
            normalized = _normalize_output_message(message)
            content = normalized.get("content", "")
            if not content:
                return
            if not chunk_started:
                chunk_started = True
                emit_progress("streaming", "正在接收 GM 流式输出", percent=65, indeterminate=True)
            streamed_messages.append(normalized)
            _emit_runtime_event_from_worker(
                runtime,
                {"type": "gm_chunk", **normalized},
            )

        runtime.gm.on_output = collect_output

        try:
            await asyncio.to_thread(runtime.gm.process, action)
            action_logger.info("GM process completed")
        except Exception as exc:
            action_logger.exception("Action execution failed: %s", exc)
            emit_progress("failed", f"行动执行失败: {exc}", status="error")
            _emit_runtime_event_from_worker(
                runtime,
                {
                    "type": "action_status",
                    "status": "error",
                    "error": str(exc),
                    "action_id": action_id,
                },
            )
            raise

        emit_progress("sync_state", "正在同步最新状态", percent=90)
        state = _build_state_snapshot(runtime)
        is_waiting = runtime.gm.session.is_waiting_for_human if runtime.gm.session else False
        _enqueue_runtime_event(
            runtime,
            {
                "type": "state_update",
                "state": state,
                "is_waiting_for_human": is_waiting,
            },
        )
        _enqueue_runtime_event(
            runtime,
            {"type": "action_status", "status": "completed", "action_id": action_id},
        )
        emit_progress("completed", "行动处理完成", percent=100, status="completed")
        action_logger.info("Action execution finished successfully")

    return {
        "action_id": action_id,
        "messages": streamed_messages,
        "progress_events": progress_events,
        "state": state,
        "is_waiting_for_human": is_waiting,
    }


def _build_html_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>时空拍卖行 · 实时对局</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <h1>时空拍卖行</h1>
        <p>Chronos Auction House · 实时 GM 面板</p>
      </div>
      <div class="status-row">
        <span id="conn-badge" class="badge badge-offline">未连接</span>
        <span id="stream-badge" class="badge">流式空闲</span>
      </div>
    </header>
    <div id="reconnect-progress-wrap" class="progress-wrap hidden progress-inline">
      <div class="progress-meta">
        <span id="reconnect-progress-label">正在连接实时通道...</span>
        <span id="reconnect-progress-value">处理中</span>
      </div>
      <div class="progress-track">
        <div id="reconnect-progress-bar" class="progress-bar indeterminate"></div>
      </div>
    </div>

    <section id="setup-panel" class="panel">
      <h2>开始新游戏</h2>
      <div class="grid two-col">
        <label>
          <span>API Key *</span>
          <input id="api-key" type="password" placeholder="sk-ant-..." />
        </label>
        <label>
          <span>Base URL (可选)</span>
          <input id="base-url" type="text" placeholder="https://api.anthropic.com" />
        </label>
        <label>
          <span>模型</span>
          <input id="model" type="text" value="claude-sonnet-4-20250514" />
        </label>
        <label>
          <span>你的名字</span>
          <input id="player-name" type="text" value="玩家" />
        </label>
        <label>
          <span>AI 对手数量</span>
          <select id="ai-count">
            <option value="2">2 个 AI</option>
            <option value="3">3 个 AI</option>
            <option value="4">4 个 AI</option>
          </select>
        </label>
      </div>
      <button id="start-btn" class="btn-primary">开始游戏</button>
      <div id="startup-progress-wrap" class="progress-wrap hidden">
        <div class="progress-meta">
          <span id="startup-progress-label">正在创建游戏...</span>
          <span id="startup-progress-value">0%</span>
        </div>
        <div class="progress-track">
          <div id="startup-progress-bar" class="progress-bar"></div>
        </div>
      </div>
      <p id="setup-error" class="error-text hidden"></p>
    </section>

    <section id="game-panel" class="hidden">
      <div class="grid game-grid">
        <article class="panel">
          <h2>全局状态</h2>
          <div class="kv-list">
            <div><span>回合</span><strong id="round-number">1</strong></div>
            <div><span>阶段</span><strong id="phase">准备</strong></div>
            <div><span>稳定性</span><strong id="stability">100%</strong></div>
            <div><span>上下文长度</span><strong id="context-length">-</strong></div>
          </div>
        </article>

        <article class="panel">
          <h2>玩家面板</h2>
          <div id="players-list" class="stack-list"></div>
        </article>
      </div>

      <article class="panel">
        <div class="panel-title-row">
          <h2>GM 实时播报</h2>
          <span id="action-badge" class="badge">待命</span>
        </div>
        <div id="chat-box" class="chat-box"></div>
        <div id="action-progress-wrap" class="progress-wrap hidden">
          <div class="progress-meta">
            <span id="action-progress-label">等待行动...</span>
            <span id="action-progress-value">0%</span>
          </div>
          <div class="progress-track">
            <div id="action-progress-bar" class="progress-bar"></div>
          </div>
        </div>
        <form id="action-form" class="action-row">
          <input id="action-input" type="text" placeholder="输入你的行动，例如：我出价 24" />
          <button id="send-btn" class="btn-primary" type="submit">发送</button>
        </form>
      </article>

      <article class="panel">
        <div class="panel-title-row">
          <h2>我的手牌</h2>
          <span id="viewer-hand-count" class="badge">0 张</span>
        </div>
        <div id="viewer-hand-list" class="hand-list">
          <div class="hand-empty">暂无手牌</div>
        </div>
      </article>

      <article class="panel">
        <h2>拍卖区</h2>
        <div id="auction-items" class="auction-grid">
          <div class="empty-card">暂无拍卖物品</div>
        </div>
      </article>
    </section>
  </main>

  <script type="module" src="/static/app.js"></script>
</body>
</html>
"""


STATIC_DIR = Path(__file__).parent / "static"
HTML_PAGE = _build_html_page()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    setup_logging()
    logger.info("API lifespan started")
    yield

    for runtime in active_games.values():
        _enqueue_runtime_event(runtime, None)

    tasks = [
        runtime.dispatch_task
        for runtime in active_games.values()
        if runtime.dispatch_task is not None
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    await manager.close_all()
    active_games.clear()
    logger.info("API lifespan stopped")


app = FastAPI(
    title="通用桌游 Agent API",
    description="通用桌游 Agent 系统后端接口 — 支持时空拍卖行及自定义桌游",
    version="0.3.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return {"message": "通用桌游 Agent API", "version": "0.3.0"}


@app.post("/api/games")
async def create_game(request: GameCreateRequest):
    create_action_id = f"create-{uuid.uuid4().hex[:8]}"
    flow_logger = bind_context(logger, action_id=create_action_id)
    progress_events: list[dict[str, Any]] = []

    def record_progress(
        stage: str,
        message: str,
        *,
        percent: Optional[int] = None,
        indeterminate: bool = False,
        status: str = "in_progress",
        game_id: Optional[str] = None,
    ):
        progress_events.append(
            _build_progress_event(
                scope="create_game",
                stage=stage,
                message=message,
                percent=percent,
                indeterminate=indeterminate,
                status=status,
                game_id=game_id,
                action_id=create_action_id,
            )
        )

    record_progress("request_received", "已接收创建游戏请求", percent=5)
    api_key = (request.api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请输入 API Key")

    player_name = request.player_name.strip() or "玩家"
    players = [(player_name, True)]
    for i in range(request.ai_count):
        players.append((f"AI玩家{i + 1}", False))

    record_progress("request_validated", "请求参数校验完成", percent=15)
    flow_logger.info(
        "Creating game request validated (players=%s, model=%s)",
        len(players),
        request.model,
    )
    startup_messages: list[dict[str, Any]] = []

    def collect_output(message: str | dict[str, Any]):
        normalized = _normalize_output_message(message)
        if normalized.get("content"):
            startup_messages.append(normalized)

    record_progress("runtime_preparing", "正在构建游戏运行时", percent=30)
    game_mgr = GameManager()
    gm = GMAgent(
        config=GMConfig(model=request.model),
        game_mgr=game_mgr,
        on_output=collect_output,
        api_key=api_key,
        base_url=request.base_url.strip() or None,
    )

    record_progress("game_initializing", "正在初始化牌局与 GM 会话", percent=55, indeterminate=True)
    try:
        await asyncio.to_thread(gm.start_game, players)
    except Exception as exc:
        flow_logger.exception("Game creation failed: %s", exc)
        record_progress("failed", f"创建游戏失败: {exc}", status="error")
        raise HTTPException(status_code=500, detail=f"创建游戏失败: {exc}") from exc

    if gm.session is None:
        flow_logger.error("Game creation failed: session not created")
        record_progress("failed", "创建游戏失败: GM 会话未创建", status="error")
        raise HTTPException(status_code=500, detail="创建游戏失败: GM 会话未创建")

    game_id = gm.session.game_id
    game_logger = bind_context(logger, game_id=game_id, action_id=create_action_id)
    record_progress("game_initialized", "牌局初始化完成", percent=78, game_id=game_id)
    loop = asyncio.get_running_loop()
    runtime = GameRuntime(
        game_id=game_id,
        gm=gm,
        game_mgr=game_mgr,
        config={
            "api_key": api_key,
            "base_url": request.base_url.strip(),
            "model": request.model,
        },
        loop=loop,
    )
    active_games[game_id] = runtime
    game_logger.info("Game runtime registered")
    record_progress("runtime_registered", "运行时注册完成", percent=92, game_id=game_id)
    runtime.dispatch_task = asyncio.create_task(
        _dispatch_runtime_events(game_id),
        name=f"dispatch-{game_id}",
    )
    record_progress("completed", "游戏创建完成", percent=100, status="completed", game_id=game_id)
    game_logger.info("Game created successfully")

    return {
        "game_id": game_id,
        "players": [name for name, _ in players],
        "messages": startup_messages,
        "progress_events": progress_events,
        "state": _build_state_snapshot(runtime),
        "is_waiting_for_human": gm.session.is_waiting_for_human,
    }


# ========== 通用桌游引擎端点（必须在 /api/games/{game_id} 之前注册） ==========


@app.get("/api/games/definitions")
async def list_game_definitions():
    """列出所有可用的 GameDefinition"""
    from ..core.game_loader import discover_games
    games = discover_games()
    return {"definitions": games}


@app.get("/api/games/definitions/{game_id}")
async def get_game_definition(game_id: str):
    """获取指定游戏的 GameDefinition"""
    from ..core.game_loader import load_game_definition
    game_def = load_game_definition(game_id)
    if game_def is None:
        raise HTTPException(status_code=404, detail=f"游戏定义不存在: {game_id}")
    return game_def.model_dump()


@app.put("/api/games/definitions/{game_id}")
async def update_game_definition(game_id: str, body: dict[str, Any]):
    """更新（微调）指定游戏的 GameDefinition"""
    from ..core.game_loader import load_game_definition, save_game_definition
    from ..core.game_definition import GameDefinition

    existing = load_game_definition(game_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"游戏定义不存在: {game_id}")

    merged = existing.model_dump()
    merged.update(body)
    merged["id"] = game_id

    try:
        updated = GameDefinition(**merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"GameDefinition 校验失败: {exc}") from exc

    save_game_definition(updated)
    return {"status": "ok", "game_id": game_id, "name": updated.name}


@app.post("/api/games/upload-rules")
async def upload_rules(file: UploadFile):
    """上传 PDF 规则书，解析后返回 GameDefinition"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="请上传 PDF 文件")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="服务器未配置 ANTHROPIC_API_KEY")

    try:
        from ..parser.pdf_extractor import PdfExtractor
        from ..parser.llm_extractor import LlmExtractor
        from ..parser.cache_manager import CacheManager
        from ..core.game_loader import save_game_definition
        import anthropic

        extractor = PdfExtractor()
        doc = extractor.extract_from_bytes(content, file.filename)

        cache = CacheManager()
        cached = cache.get_game_def(doc.sha256)
        if cached:
            return {
                "status": "cached",
                "game_definition": cached.model_dump(),
                "message": f"使用缓存: {cached.name}",
            }

        client = anthropic.Anthropic(api_key=api_key)
        llm = LlmExtractor(client=client)
        game_def = await asyncio.to_thread(llm.extract, doc.full_text)
        save_game_definition(game_def)
        cache.set_game_def(doc.sha256, game_def)

        return {
            "status": "ok",
            "game_definition": game_def.model_dump(),
            "message": f"成功解析: {game_def.name}",
        }
    except Exception as exc:
        logger.exception("Rules upload failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc


@app.get("/api/games/{game_id}")
async def get_game(game_id: str):
    runtime = _require_runtime(game_id)
    return {
        "game_id": game_id,
        "state": _build_state_snapshot(runtime),
        "is_waiting_for_human": runtime.gm.session.is_waiting_for_human if runtime.gm.session else False,
    }


@app.post("/api/games/{game_id}/action")
async def game_action(game_id: str, request: GameActionRequest):
    runtime = _require_runtime(game_id)
    action_logger = bind_context(logger, game_id=game_id)
    try:
        action = _normalize_action(request.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    action_logger.info("Received HTTP action request: %s", action)
    try:
        result = await _run_gm_action(runtime, action)
    except Exception as exc:
        action_logger.exception("HTTP action failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"执行行动失败: {exc}") from exc
    action_logger.info("HTTP action completed")

    return {
        "game_id": game_id,
        **result,
    }


@app.websocket("/ws/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    await manager.connect(game_id, websocket)
    bind_context(logger, game_id=game_id).info("WebSocket connected")
    runtime = active_games.get(game_id)
    if runtime is None:
        bind_context(logger, game_id=game_id).warning("WebSocket connected to missing game")
        await websocket.send_json({"type": "error", "error": "游戏不存在"})
        await manager.disconnect(game_id, websocket)
        await websocket.close(code=4404)
        return

    await websocket.send_json(
        {
            "type": "connected",
            "game_id": game_id,
            "state": _build_state_snapshot(runtime),
            "is_waiting_for_human": runtime.gm.session.is_waiting_for_human if runtime.gm.session else False,
            "action_in_progress": runtime.action_lock.locked(),
        }
    )

    try:
        while True:
            payload = await websocket.receive_json()
            try:
                action = _normalize_action(str(payload.get("action", "")))
            except ValueError as exc:
                await websocket.send_json({"type": "error", "error": str(exc)})
                continue
            if runtime.action_lock.locked():
                await websocket.send_json({"type": "action_status", "status": "queued"})

            try:
                bind_context(logger, game_id=game_id).info("Received WebSocket action: %s", action)
                await _run_gm_action(runtime, action)
            except Exception as exc:
                bind_context(logger, game_id=game_id).exception("WebSocket action failed: %s", exc)
                await websocket.send_json({"type": "error", "error": f"执行行动失败: {exc}"})
    except WebSocketDisconnect:
        bind_context(logger, game_id=game_id).info("WebSocket disconnected")
        await manager.disconnect(game_id, websocket)


@app.get("/play", response_class=HTMLResponse)
async def play_page():
    return HTML_PAGE
