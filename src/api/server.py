"""
FastAPI 后端 - WebSocket 实时游戏接口（支持 GM 流式输出）
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agents import GMConfig, GMAgent
from ..tools import GameManager


class GameCreateRequest(BaseModel):
    """创建游戏请求"""

    player_name: str = "玩家"
    ai_count: int = Field(default=2, ge=2, le=4)
    api_key: str = ""
    base_url: str = ""
    model: str = "claude-sonnet-4-20250514"


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
                print(f"[ws] broadcast failed: {exc}")
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
                print(f"[ws] close failed for {game_id}: {exc}")


active_games: dict[str, GameRuntime] = {}
manager = ConnectionManager()


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
        print(f"[stream] queue overflow for game {runtime.game_id}")


def _emit_runtime_event_from_worker(runtime: GameRuntime, event: dict[str, Any]):
    """供线程中的 GM 回调使用，线程安全地把事件送回主事件循环。"""
    try:
        runtime.loop.call_soon_threadsafe(_enqueue_runtime_event, runtime, event)
    except RuntimeError as exc:
        print(f"[stream] loop closed for {runtime.game_id}: {exc}")


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
    streamed_messages: list[str] = []

    async with runtime.action_lock:
        _enqueue_runtime_event(
            runtime,
            {"type": "action_status", "status": "started", "action": action},
        )

        def collect_output(message: str):
            text = str(message) if message is not None else ""
            if not text:
                return
            streamed_messages.append(text)
            _emit_runtime_event_from_worker(
                runtime,
                {"type": "gm_chunk", "content": text},
            )

        runtime.gm.on_output = collect_output

        try:
            await asyncio.to_thread(runtime.gm.process, action)
        except Exception as exc:
            _emit_runtime_event_from_worker(
                runtime,
                {
                    "type": "action_status",
                    "status": "error",
                    "error": str(exc),
                },
            )
            raise

        state = runtime.game_mgr.get_game_state()
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
            {"type": "action_status", "status": "completed"},
        )

    return {
        "messages": streamed_messages,
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
        <form id="action-form" class="action-row">
          <input id="action-input" type="text" placeholder="输入你的行动，例如：我出价 24" />
          <button id="send-btn" class="btn-primary" type="submit">发送</button>
        </form>
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


app = FastAPI(
    title="时空拍卖行 API",
    description="《时空拍卖行》桌游 Agent 系统后端接口",
    version="0.2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return {"message": "时空拍卖行 API", "version": "0.2.0"}


@app.post("/api/games")
async def create_game(request: GameCreateRequest):
    api_key = (request.api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请输入 API Key")

    player_name = request.player_name.strip() or "玩家"
    players = [(player_name, True)]
    for i in range(request.ai_count):
        players.append((f"AI玩家{i + 1}", False))

    startup_messages: list[str] = []

    def collect_output(message: str):
        text = str(message) if message is not None else ""
        if text:
            startup_messages.append(text)

    game_mgr = GameManager()
    gm = GMAgent(
        config=GMConfig(model=request.model),
        game_mgr=game_mgr,
        on_output=collect_output,
        api_key=api_key,
        base_url=request.base_url.strip() or None,
    )

    try:
        await asyncio.to_thread(gm.start_game, players)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建游戏失败: {exc}") from exc

    if gm.session is None:
        raise HTTPException(status_code=500, detail="创建游戏失败: GM 会话未创建")

    game_id = gm.session.game_id
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
    runtime.dispatch_task = asyncio.create_task(
        _dispatch_runtime_events(game_id),
        name=f"dispatch-{game_id}",
    )

    return {
        "game_id": game_id,
        "players": [name for name, _ in players],
        "messages": startup_messages,
        "state": runtime.game_mgr.get_game_state(),
        "is_waiting_for_human": gm.session.is_waiting_for_human,
    }


@app.get("/api/games/{game_id}")
async def get_game(game_id: str):
    runtime = _require_runtime(game_id)
    return {
        "game_id": game_id,
        "state": runtime.game_mgr.get_game_state(),
        "is_waiting_for_human": runtime.gm.session.is_waiting_for_human if runtime.gm.session else False,
    }


@app.post("/api/games/{game_id}/action")
async def game_action(game_id: str, request: GameActionRequest):
    runtime = _require_runtime(game_id)
    try:
        action = _normalize_action(request.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        result = await _run_gm_action(runtime, action)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"执行行动失败: {exc}") from exc

    return {
        "game_id": game_id,
        **result,
    }


@app.websocket("/ws/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    await manager.connect(game_id, websocket)
    runtime = active_games.get(game_id)
    if runtime is None:
        await websocket.send_json({"type": "error", "error": "游戏不存在"})
        await manager.disconnect(game_id, websocket)
        await websocket.close(code=4404)
        return

    await websocket.send_json(
        {
            "type": "connected",
            "game_id": game_id,
            "state": runtime.game_mgr.get_game_state(),
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
                await _run_gm_action(runtime, action)
            except Exception as exc:
                await websocket.send_json({"type": "error", "error": f"执行行动失败: {exc}"})
    except WebSocketDisconnect:
        await manager.disconnect(game_id, websocket)


@app.get("/play", response_class=HTMLResponse)
async def play_page():
    return HTML_PAGE
