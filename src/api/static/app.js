const state = {
  gameId: null,
  ws: null,
  reconnectTimer: null,
  intentionallyClosed: false,
  pendingAction: false,
  flushScheduled: false,
  messageBuffer: [],
};

const els = {
  setupPanel: document.getElementById("setup-panel"),
  gamePanel: document.getElementById("game-panel"),
  startBtn: document.getElementById("start-btn"),
  sendBtn: document.getElementById("send-btn"),
  setupError: document.getElementById("setup-error"),
  apiKey: document.getElementById("api-key"),
  baseUrl: document.getElementById("base-url"),
  model: document.getElementById("model"),
  playerName: document.getElementById("player-name"),
  aiCount: document.getElementById("ai-count"),
  actionForm: document.getElementById("action-form"),
  actionInput: document.getElementById("action-input"),
  chatBox: document.getElementById("chat-box"),
  connBadge: document.getElementById("conn-badge"),
  streamBadge: document.getElementById("stream-badge"),
  actionBadge: document.getElementById("action-badge"),
  roundNumber: document.getElementById("round-number"),
  phase: document.getElementById("phase"),
  stability: document.getElementById("stability"),
  playersList: document.getElementById("players-list"),
  auctionItems: document.getElementById("auction-items"),
};

function setSetupError(message = "") {
  if (!message) {
    els.setupError.classList.add("hidden");
    els.setupError.textContent = "";
    return;
  }
  els.setupError.classList.remove("hidden");
  els.setupError.textContent = message;
}

function setConnectionBadge(connected) {
  els.connBadge.textContent = connected ? "已连接" : "未连接";
  els.connBadge.classList.toggle("badge-online", connected);
  els.connBadge.classList.toggle("badge-offline", !connected);
}

function setActionRunning(running) {
  state.pendingAction = running;
  els.actionBadge.textContent = running ? "处理中…" : "待命";
  els.streamBadge.textContent = running ? "流式输出中" : "流式空闲";
  els.sendBtn.disabled = running;
}

function appendMessage(text, kind = "gm") {
  state.messageBuffer.push({ text, kind });
  scheduleFlushMessages();
}

function scheduleFlushMessages() {
  if (state.flushScheduled) return;
  state.flushScheduled = true;
  requestAnimationFrame(flushMessages);
}

function flushMessages() {
  state.flushScheduled = false;
  if (!state.messageBuffer.length) return;

  const frag = document.createDocumentFragment();
  for (const item of state.messageBuffer.splice(0, state.messageBuffer.length)) {
    const div = document.createElement("div");
    div.className = `message ${item.kind}`;
    div.textContent = item.text;
    frag.appendChild(div);
  }
  els.chatBox.appendChild(frag);
  els.chatBox.scrollTop = els.chatBox.scrollHeight;
}

function translatePhase(phase) {
  const map = {
    setup: "准备",
    excavation: "挖掘",
    auction: "拍卖",
    trading: "交易",
    buyback: "回购",
    event: "事件",
    vote: "投票",
    stabilize: "稳态",
    game_over: "结束",
  };
  return map[phase] ?? phase ?? "-";
}

function translateEra(era) {
  const map = {
    ancient: "远古",
    modern: "近代",
    future: "未来",
  };
  return map[era] ?? era ?? "-";
}

function renderPlayers(players = {}, currentPlayerId = null) {
  const ids = Object.keys(players);
  if (!ids.length) {
    els.playersList.innerHTML = '<div class="empty-card">暂无玩家数据</div>';
    return;
  }

  const frag = document.createDocumentFragment();
  for (const playerId of ids) {
    const p = players[playerId];
    const card = document.createElement("div");
    card.className = `player-card ${playerId === currentPlayerId ? "current" : ""}`;
    const name = document.createElement("div");
    name.textContent = p.name ?? playerId;
    const stats = document.createElement("div");
    stats.className = "meta";
    stats.textContent = `💰 ${p.money ?? 0} · 🏆 ${p.victory_points ?? 0} VP`;
    const cards = document.createElement("div");
    cards.className = "meta";
    cards.textContent = `文物 ${p.artifact_count ?? 0} · 功能卡 ${p.card_count ?? 0}`;
    card.append(name, stats, cards);
    frag.appendChild(card);
  }
  els.playersList.innerHTML = "";
  els.playersList.appendChild(frag);
}

function renderAuctionPool(items = []) {
  if (!items.length) {
    els.auctionItems.innerHTML = '<div class="empty-card">暂无拍卖物品</div>';
    return;
  }

  const frag = document.createDocumentFragment();
  for (const item of items) {
    const box = document.createElement("div");
    box.className = "auction-item";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = item.artifact?.name ?? "未知文物";
    const meta = document.createElement("div");
    meta.className = "meta";
    const era = translateEra(item.artifact?.era);
    const value = item.artifact?.base_value ?? 0;
    const type = item.auction_type === "sealed" ? "🔒 密封" : "📢 公开";
    const bid = item.current_highest_bid ? ` · 当前最高 ${item.current_highest_bid}` : "";
    meta.textContent = `${era} · 价值 ${value} · ${type}${bid}`;
    box.append(title, meta);
    frag.appendChild(box);
  }
  els.auctionItems.innerHTML = "";
  els.auctionItems.appendChild(frag);
}

function renderState(payload) {
  if (!payload || payload.error) return;
  els.roundNumber.textContent = payload.current_round ?? 1;
  els.phase.textContent = translatePhase(payload.current_phase);
  els.stability.textContent = `${payload.stability ?? 100}%`;
  renderPlayers(payload.players, payload.current_player_id ?? payload.current_player);
  renderAuctionPool(payload.auction_pool ?? []);
}

async function startGame() {
  setSetupError("");
  els.startBtn.disabled = true;

  const apiKey = els.apiKey.value.trim();
  if (!apiKey) {
    setSetupError("请输入 API Key");
    els.startBtn.disabled = false;
    return;
  }

  const body = {
    player_name: els.playerName.value.trim() || "玩家",
    ai_count: Number(els.aiCount.value),
    api_key: apiKey,
    base_url: els.baseUrl.value.trim(),
    model: els.model.value.trim() || "claude-sonnet-4-20250514",
  };

  try {
    const res = await fetch("/api/games", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "创建游戏失败");

    state.gameId = data.game_id;
    els.setupPanel.classList.add("hidden");
    els.gamePanel.classList.remove("hidden");
    renderState(data.state);
    for (const msg of data.messages || []) {
      appendMessage(msg, "gm");
    }
    connectWebSocket();
  } catch (err) {
    setSetupError(err.message || String(err));
  } finally {
    els.startBtn.disabled = false;
  }
}

function reconnectWebSocketSoon() {
  if (state.intentionallyClosed || !state.gameId) return;
  if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
  state.reconnectTimer = setTimeout(connectWebSocket, 1500);
}

function connectWebSocket() {
  if (!state.gameId) return;
  if (state.ws && state.ws.readyState <= 1) return;

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  state.ws = new WebSocket(`${protocol}//${window.location.host}/ws/${state.gameId}`);

  state.ws.onopen = () => {
    setConnectionBadge(true);
  };

  state.ws.onclose = () => {
    setConnectionBadge(false);
    reconnectWebSocketSoon();
  };

  state.ws.onerror = () => {
    setConnectionBadge(false);
  };

  state.ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "connected") {
      renderState(data.state);
      setActionRunning(Boolean(data.action_in_progress));
      return;
    }
    if (data.type === "gm_chunk") {
      appendMessage(data.content || "", "gm");
      return;
    }
    if (data.type === "state_update") {
      renderState(data.state);
      return;
    }
    if (data.type === "action_status") {
      if (data.status === "started") setActionRunning(true);
      if (data.status === "completed" || data.status === "error") setActionRunning(false);
      if (data.status === "queued") appendMessage("系统繁忙，行动已排队。", "gm");
      return;
    }
    if (data.type === "error") {
      appendMessage(`错误: ${data.error || "未知错误"}`, "error");
      setActionRunning(false);
      return;
    }
  };
}

async function sendAction(actionText) {
  const action = actionText.trim();
  if (!action || !state.gameId) return;

  appendMessage(`> ${action}`, "user");
  els.actionInput.value = "";

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ action }));
    return;
  }

  setActionRunning(true);
  try {
    const res = await fetch(`/api/games/${state.gameId}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: state.gameId, action }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "发送失败");
    for (const msg of data.messages || []) {
      appendMessage(msg, "gm");
    }
    renderState(data.state);
  } catch (err) {
    appendMessage(`发送失败: ${err.message || String(err)}`, "error");
  } finally {
    setActionRunning(false);
  }
}

els.startBtn.addEventListener("click", startGame);
els.actionForm.addEventListener("submit", (evt) => {
  evt.preventDefault();
  if (state.pendingAction) return;
  sendAction(els.actionInput.value);
});

window.addEventListener("beforeunload", () => {
  state.intentionallyClosed = true;
  if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
  if (state.ws && state.ws.readyState <= 1) state.ws.close();
});

setConnectionBadge(false);
