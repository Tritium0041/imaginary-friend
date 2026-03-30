"""
FastAPI 后端 - WebSocket 实时游戏接口
"""
from __future__ import annotations

import os
import asyncio
import json
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..agents import GMAgent, GMConfig
from ..tools import game_manager


# 检查 API Key
def check_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    return True


# 全局游戏会话
active_games: dict[str, GMAgent] = {}


class GameCreateRequest(BaseModel):
    """创建游戏请求"""
    player_name: str = "玩家"
    ai_count: int = 2
    api_key: str = ""
    base_url: str = ""
    model: str = "claude-sonnet-4-20250514"


class GameActionRequest(BaseModel):
    """游戏行动请求"""
    game_id: str
    action: str


# 存储游戏配置
game_configs: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    yield
    # 清理
    active_games.clear()


app = FastAPI(
    title="时空拍卖行 API",
    description="《时空拍卖行》桌游 Agent 系统后端接口",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """根路径"""
    return {"message": "时空拍卖行 API", "version": "0.1.0"}


@app.post("/api/games")
async def create_game(request: GameCreateRequest):
    """创建新游戏"""
    # 检查 API Key（优先使用请求中的，其次环境变量）
    api_key = request.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=400, 
            detail="请输入 API Key"
        )
    
    if not 2 <= request.ai_count <= 4:
        raise HTTPException(status_code=400, detail="AI 玩家数量必须在 2-4 之间")
    
    # 构建玩家列表
    players = [(request.player_name, True)]
    for i in range(request.ai_count):
        players.append((f"AI玩家{i+1}", False))
    
    # 创建 GM，传入配置
    messages: list[str] = []
    def collect_output(msg: str):
        messages.append(msg)
    
    try:
        # 配置 GMAgent
        config = GMConfig(model=request.model)
        gm = GMAgent(
            config=config,
            on_output=collect_output,
            api_key=api_key,
            base_url=request.base_url if request.base_url else None,
        )
        gm.start_game(players)
        
        game_id = gm.session.game_id if gm.session else "unknown"
        active_games[game_id] = gm
        
        # 保存配置供后续使用
        game_configs[game_id] = {
            "api_key": api_key,
            "base_url": request.base_url,
            "model": request.model,
        }
        
        return {
            "game_id": game_id,
            "players": [name for name, _ in players],
            "messages": messages,
            "state": game_manager.get_game_state(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建游戏失败: {str(e)}")


@app.get("/api/games/{game_id}")
async def get_game(game_id: str):
    """获取游戏状态"""
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    gm = active_games[game_id]
    return {
        "game_id": game_id,
        "state": game_manager.get_game_state(),
        "is_waiting_for_human": gm.session.is_waiting_for_human if gm.session else False,
        "logs": game_manager.get_action_log(20),
    }


@app.post("/api/games/{game_id}/action")
async def game_action(game_id: str, request: GameActionRequest):
    """执行游戏行动"""
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    gm = active_games[game_id]
    messages: list[str] = []
    
    def collect_output(msg: str):
        messages.append(msg)
    
    gm.on_output = collect_output
    gm.process(request.action)
    
    return {
        "game_id": game_id,
        "messages": messages,
        "state": game_manager.get_game_state(),
        "is_waiting_for_human": gm.session.is_waiting_for_human if gm.session else False,
    }


class ConnectionManager:
    """WebSocket 连接管理"""
    
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}
    
    async def connect(self, game_id: str, websocket: WebSocket):
        await websocket.accept()
        if game_id not in self.connections:
            self.connections[game_id] = []
        self.connections[game_id].append(websocket)
    
    def disconnect(self, game_id: str, websocket: WebSocket):
        if game_id in self.connections:
            self.connections[game_id].remove(websocket)
    
    async def broadcast(self, game_id: str, message: dict):
        if game_id in self.connections:
            for ws in self.connections[game_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass


manager = ConnectionManager()


@app.websocket("/ws/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    """WebSocket 游戏连接"""
    await manager.connect(game_id, websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if game_id not in active_games:
                await websocket.send_json({"error": "游戏不存在"})
                continue
            
            gm = active_games[game_id]
            messages: list[str] = []
            
            async def async_output(msg: str):
                messages.append(msg)
                await manager.broadcast(game_id, {
                    "type": "message",
                    "content": msg
                })
            
            # 同步回调包装
            def sync_output(msg: str):
                messages.append(msg)
            
            gm.on_output = sync_output
            
            action = data.get("action", "")
            if action:
                gm.process(action)
                
                # 广播结果
                await manager.broadcast(game_id, {
                    "type": "update",
                    "messages": messages,
                    "state": game_manager.get_game_state(),
                    "is_waiting_for_human": gm.session.is_waiting_for_human if gm.session else False,
                })
    
    except WebSocketDisconnect:
        manager.disconnect(game_id, websocket)


# 简单的 HTML 页面
HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>时空拍卖行</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .chat-box { height: 400px; overflow-y: auto; }
        .player-card { transition: all 0.3s ease; }
        .player-card:hover { transform: translateY(-2px); }
    </style>
</head>
<body class="bg-gray-900 text-white min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- 标题 -->
        <header class="text-center mb-8">
            <h1 class="text-4xl font-bold text-amber-400">🏛️ 时空拍卖行</h1>
            <p class="text-gray-400 mt-2">Chronos Auction House</p>
        </header>
        
        <!-- 游戏设置 (初始显示) -->
        <div id="setup-panel" class="max-w-lg mx-auto bg-gray-800 rounded-lg p-6">
            <h2 class="text-xl font-semibold mb-4">开始新游戏</h2>
            <div class="space-y-4">
                <!-- API 配置 -->
                <div class="border-b border-gray-700 pb-4 mb-4">
                    <h3 class="text-sm font-semibold text-amber-400 mb-3">🔑 API 配置</h3>
                    <div class="space-y-3">
                        <div>
                            <label class="block text-sm text-gray-400 mb-1">API Key *</label>
                            <input type="password" id="api-key" placeholder="sk-ant-..." 
                                   class="w-full bg-gray-700 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400">
                        </div>
                        <div>
                            <label class="block text-sm text-gray-400 mb-1">Base URL (可选)</label>
                            <input type="text" id="base-url" placeholder="https://api.anthropic.com" 
                                   class="w-full bg-gray-700 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400">
                        </div>
                        <div>
                            <label class="block text-sm text-gray-400 mb-1">模型</label>
                            <input type="text" id="model" value="claude-sonnet-4-20250514" placeholder="claude-sonnet-4-20250514"
                                   class="w-full bg-gray-700 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400">
                        </div>
                    </div>
                </div>
                
                <!-- 游戏设置 -->
                <div>
                    <label class="block text-sm text-gray-400 mb-1">你的名字</label>
                    <input type="text" id="player-name" value="玩家" 
                           class="w-full bg-gray-700 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400">
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">AI 对手数量</label>
                    <select id="ai-count" class="w-full bg-gray-700 rounded px-3 py-2">
                        <option value="2">2 个 AI</option>
                        <option value="3">3 个 AI</option>
                        <option value="4">4 个 AI</option>
                    </select>
                </div>
                <button onclick="startGame()" 
                        class="w-full bg-amber-500 hover:bg-amber-600 text-black font-semibold py-2 rounded transition">
                    开始游戏
                </button>
            </div>
        </div>
        
        <!-- 游戏面板 (游戏开始后显示) -->
        <div id="game-panel" class="hidden">
            <!-- 状态栏 -->
            <div class="bg-gray-800 rounded-lg p-4 mb-4 flex justify-between items-center">
                <div>
                    <span class="text-gray-400">回合</span>
                    <span id="round-number" class="text-xl font-bold ml-2">1</span>
                </div>
                <div>
                    <span class="text-gray-400">阶段</span>
                    <span id="phase" class="text-xl font-bold ml-2 text-amber-400">准备</span>
                </div>
                <div>
                    <span class="text-gray-400">稳定性</span>
                    <span id="stability" class="text-xl font-bold ml-2">100%</span>
                </div>
            </div>
            
            <!-- 主游戏区 -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <!-- 玩家面板 -->
                <div class="lg:col-span-1">
                    <div class="bg-gray-800 rounded-lg p-4">
                        <h3 class="text-lg font-semibold mb-3 text-amber-400">玩家</h3>
                        <div id="players-list" class="space-y-3">
                            <!-- 玩家卡片将在这里动态生成 -->
                        </div>
                    </div>
                </div>
                
                <!-- 聊天/日志区 -->
                <div class="lg:col-span-2">
                    <div class="bg-gray-800 rounded-lg p-4">
                        <h3 class="text-lg font-semibold mb-3 text-amber-400">游戏进程</h3>
                        <div id="chat-box" class="chat-box bg-gray-900 rounded p-3 mb-3 font-mono text-sm">
                            <!-- 消息将在这里显示 -->
                        </div>
                        
                        <!-- 输入区 -->
                        <div class="flex gap-2">
                            <input type="text" id="action-input" placeholder="输入你的行动..." 
                                   class="flex-1 bg-gray-700 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400"
                                   onkeypress="if(event.key==='Enter')sendAction()">
                            <button onclick="sendAction()" 
                                    class="bg-amber-500 hover:bg-amber-600 text-black font-semibold px-6 py-2 rounded transition">
                                发送
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 拍卖区 -->
            <div id="auction-area" class="mt-4 bg-gray-800 rounded-lg p-4">
                <h3 class="text-lg font-semibold mb-3 text-amber-400">🎯 拍卖区</h3>
                <div id="auction-items" class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <!-- 拍卖物品将在这里显示 -->
                    <div class="text-gray-500 text-center py-8">暂无拍卖物品</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let gameId = null;
        let ws = null;
        
        async function startGame() {
            const apiKey = document.getElementById('api-key').value.trim();
            const baseUrl = document.getElementById('base-url').value.trim();
            const model = document.getElementById('model').value;
            const playerName = document.getElementById('player-name').value || '玩家';
            const aiCount = parseInt(document.getElementById('ai-count').value);
            
            if (!apiKey) {
                alert('请输入 API Key');
                return;
            }
            
            try {
                const response = await fetch('/api/games', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_name: playerName, 
                        ai_count: aiCount,
                        api_key: apiKey,
                        base_url: baseUrl,
                        model: model
                    })
                });
                
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.detail || '创建游戏失败');
                }
                
                gameId = data.game_id;
                
                // 显示游戏面板
                document.getElementById('setup-panel').classList.add('hidden');
                document.getElementById('game-panel').classList.remove('hidden');
                
                // 显示初始消息
                data.messages.forEach(msg => addMessage(msg));
                
                // 更新状态
                updateState(data.state);
                
                // 连接 WebSocket
                connectWebSocket();
                
            } catch (error) {
                alert('创建游戏失败: ' + error.message);
            }
        }
        
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/${gameId}`);
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'message') {
                    addMessage(data.content);
                } else if (data.type === 'update') {
                    data.messages.forEach(msg => addMessage(msg));
                    updateState(data.state);
                }
            };
            
            ws.onclose = () => {
                setTimeout(connectWebSocket, 3000);
            };
        }
        
        async function sendAction() {
            const input = document.getElementById('action-input');
            const action = input.value.trim();
            if (!action) return;
            
            input.value = '';
            addMessage(`> ${action}`, 'text-blue-400');
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({action}));
            } else {
                // 降级到 HTTP
                try {
                    const response = await fetch(`/api/games/${gameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({game_id: gameId, action})
                    });
                    const data = await response.json();
                    data.messages.forEach(msg => addMessage(msg));
                    updateState(data.state);
                } catch (error) {
                    addMessage('发送失败: ' + error.message, 'text-red-400');
                }
            }
        }
        
        function addMessage(msg, className = '') {
            const chatBox = document.getElementById('chat-box');
            const div = document.createElement('div');
            div.className = `mb-2 ${className}`;
            div.innerHTML = msg.replace(/\\n/g, '<br>');
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
        }
        
        function updateState(state) {
            if (!state) return;
            
            // 更新状态栏
            document.getElementById('round-number').textContent = state.current_round || 1;
            document.getElementById('phase').textContent = translatePhase(state.current_phase);
            document.getElementById('stability').textContent = (state.stability || 100) + '%';
            
            // 更新玩家列表
            const playersList = document.getElementById('players-list');
            playersList.innerHTML = '';
            
            if (state.players) {
                Object.entries(state.players).forEach(([id, player]) => {
                    const isCurrentPlayer = state.current_player === id;
                    const card = document.createElement('div');
                    card.className = `player-card bg-gray-700 rounded p-3 ${isCurrentPlayer ? 'ring-2 ring-amber-400' : ''}`;
                    card.innerHTML = `
                        <div class="font-semibold">${player.name}</div>
                        <div class="text-sm text-gray-400 mt-1">
                            💰 ${player.money} &nbsp; 🏆 ${player.victory_points} VP
                        </div>
                        <div class="text-xs text-gray-500 mt-1">
                            文物: ${player.artifact_count || 0} | 卡牌: ${player.card_count || 0}
                        </div>
                    `;
                    playersList.appendChild(card);
                });
            }
            
            // 更新拍卖区
            const auctionItems = document.getElementById('auction-items');
            if (state.auction_pool && state.auction_pool.length > 0) {
                auctionItems.innerHTML = state.auction_pool.map(item => `
                    <div class="bg-gray-700 rounded p-4">
                        <div class="font-semibold text-amber-300">${item.artifact?.name || '未知'}</div>
                        <div class="text-sm text-gray-400 mt-1">
                            时代: ${translateEra(item.artifact?.era)} | 
                            价值: ${item.artifact?.base_value || 0}
                        </div>
                        <div class="text-xs mt-2">
                            ${item.auction_type === 'sealed' ? '🔒 密封竞标' : '📢 公开拍卖'}
                        </div>
                        ${item.current_highest_bid ? `<div class="text-sm text-green-400 mt-1">当前最高: ${item.current_highest_bid}</div>` : ''}
                    </div>
                `).join('');
            } else {
                auctionItems.innerHTML = '<div class="text-gray-500 text-center py-8 col-span-3">暂无拍卖物品</div>';
            }
        }
        
        function translatePhase(phase) {
            const map = {
                'setup': '准备',
                'excavation': '挖掘',
                'auction': '拍卖',
                'trading': '交易',
                'settlement': '结算',
                'game_over': '结束'
            };
            return map[phase] || phase;
        }
        
        function translateEra(era) {
            const map = {
                'ancient': '远古',
                'medieval': '中世纪',
                'modern': '近代',
                'future': '未来'
            };
            return map[era] || era;
        }
    </script>
</body>
</html>
"""


@app.get("/play", response_class=HTMLResponse)
async def play_page():
    """游戏页面"""
    return HTML_PAGE
