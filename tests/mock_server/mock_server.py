"""
Mock server for frontend visual testing.
Serves static files + fake API endpoints so play.html and manage.html render with sample data.
"""
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "src" / "api" / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---- Sample data ----

SAMPLE_STATE = {
    "global": [
        {
            "_id": "global",
            "game_id": "chronos_auction",
            "round": 3,
            "phase": "行动阶段",
            "current_player": "player_human",
            "market_multiplier": 1.5,
            "tax_rate": 10,
            "artifact_deck": [
                {"card_id": "a1", "name": "时光沙漏", "description": "每回合额外获得 1 金币", "effect": "+1 gold/turn"},
                {"card_id": "a2", "name": "永恒之石", "description": "防止一次负面事件", "effect": "shield"},
            ],
            "event_zone": [
                {"card_id": "e1", "name": "市场繁荣", "description": "所有交易价格 +20%"},
            ],
        }
    ],
    "players": [
        {
            "_id": "player_human",
            "name": "探险家小明",
            "type": "human",
            "is_human": True,
            "gold": 150,
            "victory_points": 12,
            "reputation": 8,
            "hand": [
                {"card_id": "h1", "name": "闪电交易", "description": "立即完成一笔拍卖", "effect": "instant_auction"},
                {"card_id": "h2", "name": "时间加速", "description": "跳过等待阶段", "effect": "skip_wait"},
                {"card_id": "h3", "name": "金币雨", "description": "获得 50 金币", "effect": "+50 gold"},
            ],
            "artifacts": [
                {"card_id": "art1", "name": "古代王冠", "description": "声望 +2", "effect": "+2 reputation"},
            ],
        },
        {
            "_id": "player_ai_1",
            "name": "AI·收藏家",
            "type": "ai",
            "gold": 200,
            "victory_points": 15,
            "reputation": 6,
        },
        {
            "_id": "player_ai_2",
            "name": "AI·投机者",
            "type": "ai",
            "gold": 80,
            "victory_points": 9,
            "reputation": 11,
        },
    ],
    "zones": [
        {"_id": "artifact_deck", "type": "deck", "remaining": 18},
        {"_id": "event_deck", "type": "deck", "remaining": 12},
        {"_id": "auction_zone", "type": "public"},
        {"_id": "discard_pile", "type": "pile", "count": 7},
    ],
    "viewer_player_id": "player_human",
    "viewer_hand_items": [
        {"id": "h1", "name": "闪电交易", "description": "立即完成一笔拍卖", "effect": "instant_auction"},
        {"id": "h2", "name": "时间加速", "description": "跳过等待阶段", "effect": "skip_wait"},
        {"id": "h3", "name": "金币雨", "description": "获得 50 金币", "effect": "+50 gold"},
    ],
    "viewer_player_data": {
        "_id": "player_human",
        "name": "探险家小明",
        "type": "human",
        "is_human": True,
        "gold": 150,
        "victory_points": 12,
        "reputation": 8,
        "hand": [
            {"card_id": "h1", "name": "闪电交易", "description": "立即完成一笔拍卖", "effect": "instant_auction"},
            {"card_id": "h2", "name": "时间加速", "description": "跳过等待阶段", "effect": "skip_wait"},
            {"card_id": "h3", "name": "金币雨", "description": "获得 50 金币", "effect": "+50 gold"},
        ],
        "artifacts": [
            {"card_id": "art1", "name": "古代王冠", "description": "声望 +2", "effect": "+2 reputation"},
        ],
    },
    "context_metrics": {
        "message_count": 24,
        "estimated_chars": 18500,
        "estimated_tokens": 6200,
        "api_request_count": 8,
        "api_input_tokens": 42000,
        "api_output_tokens": 8500,
        "api_total_tokens": 50500,
        "api_cache_creation_input_tokens": 12000,
        "api_cache_read_input_tokens": 30000,
    },
    "game_meta": {
        "game_name": "时光拍卖行 · Chronos Auction",
        "description": "一款以时间旅行为主题的策略拍卖桌游，玩家扮演时空收藏家，竞拍来自不同时代的珍贵文物。",
    },
}

SAMPLE_MESSAGES = [
    {"kind": "gm", "content": "# 🎲 第 3 回合 — 行动阶段\n\n欢迎来到时光拍卖行！当前市场繁荣，交易价格上浮 20%。\n\n**当前拍品**: 时光沙漏 — 起拍价 30 金币\n\n- 探险家小明: 150 💰\n- AI·收藏家: 200 💰\n- AI·投机者: 80 💰"},
    {"kind": "ai", "content": "我出价 **35 金币**竞拍时光沙漏。这件文物的每回合收益很可观。", "player_id": "player_ai_1", "player_name": "AI·收藏家"},
    {"kind": "gm", "content": "AI·收藏家出价 **35 金币**！\n\n> 探险家小明，轮到你了。你可以选择：\n> - `加价` — 提高出价\n> - `放弃` — 退出本轮竞拍\n> - `使用道具` — 使用手中的功能牌"},
]

SAMPLE_DEFINITIONS = {
    "definitions": [
        {"id": "chronos_auction", "name": "时光拍卖行", "description": "时间旅行主题的策略拍卖桌游"},
        {"id": "island_survival", "name": "荒岛求生", "description": "合作生存类桌游，在荒岛上收集资源"},
        {"id": "space_trader", "name": "星际贸易", "description": "太空背景的经济模拟桌游"},
    ]
}


@app.get("/play")
async def play_page():
    return FileResponse(STATIC_DIR / "play.html", media_type="text/html")


@app.get("/manage")
async def manage_page():
    return FileResponse(STATIC_DIR / "manage.html", media_type="text/html")


@app.get("/api/games/definitions")
async def list_definitions():
    return SAMPLE_DEFINITIONS


@app.get("/api/games/definitions/{game_id}")
async def get_definition(game_id: str):
    return {
        "game_id": game_id,
        "id": game_id,
        "metadata": {
            "game_name": "时光拍卖行",
            "description": "时间旅行主题的策略拍卖桌游",
            "player_count_min": 2,
            "player_count_max": 4,
        },
        "rules_md": "# 时光拍卖行规则\n\n## 概述\n玩家扮演时空收藏家...\n\n## 回合流程\n1. 抽取事件牌\n2. 拍卖阶段\n3. 结算阶段",
    }


@app.post("/api/games")
async def create_game():
    return {
        "game_id": "mock-game-001",
        "state": SAMPLE_STATE,
        "messages": SAMPLE_MESSAGES,
        "progress_events": [
            {"type": "progress", "scope": "create_game", "stage": "completed", "message": "游戏创建完成", "percent": 100, "status": "completed"},
        ],
    }


@app.websocket("/ws/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    await websocket.accept()
    # Send connected event with state
    await websocket.send_json({
        "type": "connected",
        "state": SAMPLE_STATE,
        "action_in_progress": False,
    })
    # Keep connection alive
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            # Echo back an action cycle
            await websocket.send_json({"type": "action_status", "status": "started"})
            await asyncio.sleep(0.5)
            await websocket.send_json({
                "type": "gm_chunk",
                "kind": "gm",
                "content": f"你选择了: **{msg.get('action', '???')}**\n\nGM 正在处理你的行动...",
            })
            await asyncio.sleep(0.3)
            await websocket.send_json({"type": "state_update", "state": SAMPLE_STATE})
            await websocket.send_json({"type": "action_status", "status": "completed"})
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9999)
