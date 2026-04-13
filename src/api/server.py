"""
FastAPI 后端 - WebSocket 实时游戏接口（DocStore + rules.md 架构）
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

from fastapi import FastAPI, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agents import GMConfig, GMAgent
from ..utils import bind_context, setup_logging


class GameCreateRequest(BaseModel):
    """创建游戏请求"""

    player_name: str = "玩家"
    ai_count: int = Field(default=2, ge=2, le=4)
    api_key: str = ""
    base_url: str = ""
    model: str = "claude-sonnet-4-20250514"
    game_id: str = Field(
        default="",
        description="游戏 ID（必填）",
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
    """从 DocStore 构建状态快照"""
    session = runtime.gm.session
    if session is None:
        return {}

    doc_store = runtime.gm.doc_store

    # 查找人类玩家作为 viewer
    viewer_player_id: Optional[str] = None
    player_info = getattr(session, "player_info", {}) or {}
    for pid, info in player_info.items():
        if info.get("is_human", False):
            viewer_player_id = str(pid)
            break

    # 使用 snapshot_for_player 过滤其他玩家私有数据
    if doc_store:
        if viewer_player_id:
            snapshot = doc_store.snapshot_for_player(viewer_player_id)
        else:
            snapshot = doc_store.snapshot()
    else:
        snapshot = {}

    state_payload: dict[str, Any] = dict(snapshot)
    state_payload["context_metrics"] = _build_context_metrics(runtime)

    # 提取 viewer 的手牌和完整数据
    viewer_hand_items: list[dict[str, str]] = []
    viewer_player_data: Optional[dict] = None

    if viewer_player_id:
        for player in snapshot.get("players", []):
            if player.get("_id") == viewer_player_id:
                viewer_player_data = player
                for card in player.get("hand", []):
                    if isinstance(card, dict):
                        card_id = str(card.get("id", card.get("card_id", card.get("_id", ""))))
                        card_name = str(card.get("name", card.get("card_name", "")))
                        viewer_hand_items.append({
                            "id": card_id,
                            "name": card_name,
                            "description": str(card.get("description", card.get("desc", ""))),
                            "effect": str(card.get("effect", "")),
                        })
                    elif isinstance(card, str):
                        viewer_hand_items.append({
                            "id": card,
                            "name": card,
                            "description": "",
                            "effect": "",
                        })
                break

    state_payload["viewer_player_id"] = viewer_player_id
    state_payload["viewer_hand_items"] = viewer_hand_items
    state_payload["viewer_player_data"] = viewer_player_data

    # 游戏元信息供前端标题栏使用
    meta = getattr(runtime.gm, "metadata", None) or {}
    state_payload["game_meta"] = {
        "game_name": meta.get("game_name", getattr(runtime.gm, "game_name", "")),
        "description": meta.get("description", ""),
    }

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



STATIC_DIR = Path(__file__).parent / "static"


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
    description="通用桌游 Agent 系统后端接口",
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

    from ..core.game_loader import load_game_rules
    result = load_game_rules(request.game_id)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail=f"未找到游戏: {request.game_id}",
        )
    rules_md, metadata = result

    gm = GMAgent(
        rules_md=rules_md,
        metadata=metadata,
        config=GMConfig(model=request.model),
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
    """列出所有可用的游戏"""
    from ..core.game_loader import discover_games
    games = discover_games()
    return {"definitions": games}


@app.get("/api/games/definitions/{game_id}")
async def get_game_definition(game_id: str):
    """获取指定游戏的规则和元数据"""
    from ..core.game_loader import load_game_rules
    result = load_game_rules(game_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"游戏不存在: {game_id}")
    rules_md, metadata = result
    return {"game_id": game_id, "metadata": metadata, "rules_md": rules_md}


@app.put("/api/games/definitions/{game_id}")
async def update_game_definition(game_id: str, body: dict[str, Any]):
    """更新（微调）指定游戏的元数据"""
    from ..core.game_loader import load_game_rules, save_game_rules

    result = load_game_rules(game_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"游戏不存在: {game_id}")
    rules_md, metadata = result

    # Merge updates into metadata
    for key, val in body.items():
        if key == "rules_md":
            rules_md = val
        else:
            metadata[key] = val

    save_game_rules(game_id, rules_md, metadata)
    return {"status": "ok", "game_id": game_id, "name": metadata.get("game_name", game_id)}


@app.delete("/api/games/definitions/{game_id}")
async def delete_game_definition(game_id: str):
    """删除指定游戏"""
    from ..core.game_loader import discover_games
    import shutil

    games = discover_games()
    target = next((g for g in games if g["id"] == game_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"游戏不存在: {game_id}")

    path = Path(target["path"])
    if path.is_dir() and path.exists():
        shutil.rmtree(path)
    return {"status": "ok", "game_id": game_id}


@app.post("/api/games/upload-rules")
async def upload_rules(
    file: UploadFile,
    api_key: str = Form(default=""),
    base_url: str = Form(default=""),
    model: str = Form(default=""),
):
    """上传规则书（PDF/DOCX/MD），解析后返回游戏信息"""
    supported = (".pdf", ".docx", ".md")
    if not file.filename or not any(file.filename.lower().endswith(ext) for ext in supported):
        raise HTTPException(status_code=400, detail="请上传 PDF、DOCX 或 MD 文件")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空")

    resolved_key = (api_key or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not resolved_key:
        raise HTTPException(status_code=400, detail="请提供 API Key（页面输入或服务器环境变量）")

    resolved_base_url = (base_url or "").strip() or None
    resolved_model = (model or "").strip() or "claude-sonnet-4-20250514"

    try:
        from ..parser.document_parser import parse_bytes
        from ..parser.rule_cleaner import RuleCleaner
        from ..parser.cache_manager import CacheManager
        from ..core.game_loader import save_game_rules
        import anthropic

        raw_doc = parse_bytes(content, file.filename)

        cache = CacheManager()
        cached = cache.get_rules(raw_doc.sha256)
        if cached:
            rules_md, metadata = cached
            game_name = metadata.get("game_name", "Unknown")
            game_id = raw_doc.sha256[:8]
            save_game_rules(game_id, rules_md, metadata)
            return {
                "status": "cached",
                "game_id": game_id,
                "metadata": metadata,
                "message": f"使用缓存: {game_name}",
            }

        client_kwargs: dict[str, Any] = {"api_key": resolved_key}
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url
        client = anthropic.Anthropic(**client_kwargs)
        cleaner = RuleCleaner(client=client, model=resolved_model)
        result = await asyncio.to_thread(cleaner.clean, raw_doc.raw_text)

        game_id = raw_doc.sha256[:8]
        save_game_rules(game_id, result.rules_md, result.metadata)
        cache.set_rules(raw_doc.sha256, result.rules_md, result.metadata)

        return {
            "status": "ok",
            "game_id": game_id,
            "metadata": result.metadata,
            "message": f"成功解析: {result.metadata.get('game_name', 'Unknown')}",
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


@app.get("/play")
async def play_page():
    return FileResponse(STATIC_DIR / "play.html", media_type="text/html")


@app.get("/manage")
async def manage_page():
    return FileResponse(STATIC_DIR / "manage.html", media_type="text/html")
