const state = {
  gameId: null,
  ws: null,
  reconnectTimer: null,
  reconnecting: false,
  intentionallyClosed: false,
  pendingAction: false,
  flushScheduled: false,
  messageBuffer: [],
  startupHideTimer: null,
  actionHideTimer: null,
  reconnectHideTimer: null,
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
  contextLength: document.getElementById("context-length"),
  playersList: document.getElementById("players-list"),
  viewerHandCount: document.getElementById("viewer-hand-count"),
  viewerHandList: document.getElementById("viewer-hand-list"),
  auctionItems: document.getElementById("auction-items"),
  startupProgressWrap: document.getElementById("startup-progress-wrap"),
  startupProgressLabel: document.getElementById("startup-progress-label"),
  startupProgressValue: document.getElementById("startup-progress-value"),
  startupProgressBar: document.getElementById("startup-progress-bar"),
  actionProgressWrap: document.getElementById("action-progress-wrap"),
  actionProgressLabel: document.getElementById("action-progress-label"),
  actionProgressValue: document.getElementById("action-progress-value"),
  actionProgressBar: document.getElementById("action-progress-bar"),
  reconnectProgressWrap: document.getElementById("reconnect-progress-wrap"),
  reconnectProgressLabel: document.getElementById("reconnect-progress-label"),
  reconnectProgressValue: document.getElementById("reconnect-progress-value"),
  reconnectProgressBar: document.getElementById("reconnect-progress-bar"),
};

const progressTargets = {
  create_game: {
    wrap: els.startupProgressWrap,
    label: els.startupProgressLabel,
    value: els.startupProgressValue,
    bar: els.startupProgressBar,
  },
  action: {
    wrap: els.actionProgressWrap,
    label: els.actionProgressLabel,
    value: els.actionProgressValue,
    bar: els.actionProgressBar,
  },
  reconnect: {
    wrap: els.reconnectProgressWrap,
    label: els.reconnectProgressLabel,
    value: els.reconnectProgressValue,
    bar: els.reconnectProgressBar,
  },
};

function clampPercent(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function clearHideTimer(timerKey) {
  if (state[timerKey]) {
    clearTimeout(state[timerKey]);
    state[timerKey] = null;
  }
}

function hideProgress(target) {
  if (!target?.wrap || !target?.bar) return;
  target.wrap.classList.add("hidden");
  target.bar.classList.remove("indeterminate");
  target.bar.classList.remove("error");
  target.bar.style.width = "0%";
  if (target.value) target.value.textContent = "0%";
}

function scheduleHideProgress(target, timerKey, delay = 700) {
  clearHideTimer(timerKey);
  state[timerKey] = setTimeout(() => {
    hideProgress(target);
    state[timerKey] = null;
  }, delay);
}

function updateProgress(target, event) {
  if (!target?.wrap || !target?.bar || !event) return;
  target.wrap.classList.remove("hidden");
  target.bar.classList.toggle("error", event.status === "error");
  target.bar.classList.toggle("indeterminate", Boolean(event.indeterminate));
  if (target.label && event.message) target.label.textContent = event.message;

  if (Number.isFinite(event.percent)) {
    const pct = clampPercent(event.percent);
    target.bar.style.width = `${pct}%`;
    if (target.value) target.value.textContent = `${pct}%`;
  } else if (event.indeterminate) {
    target.bar.style.width = "35%";
    if (target.value) target.value.textContent = "处理中";
  }

  if (event.status === "completed") {
    target.bar.classList.remove("indeterminate");
    target.bar.style.width = "100%";
    if (target.value) target.value.textContent = "100%";
  }
}

function handleProgressEvent(event) {
  if (!event || event.type !== "progress") return;
  const target = progressTargets[event.scope];
  if (!target) return;
  const timerKey =
    event.scope === "create_game"
      ? "startupHideTimer"
      : event.scope === "action"
        ? "actionHideTimer"
        : "reconnectHideTimer";
  clearHideTimer(timerKey);
  updateProgress(target, event);
  if (event.status === "completed") {
    scheduleHideProgress(target, timerKey);
  }
}

function setReconnectProgress(active, message) {
  if (!active) {
    clearHideTimer("reconnectHideTimer");
    hideProgress(progressTargets.reconnect);
    return;
  }
  clearHideTimer("reconnectHideTimer");
  updateProgress(progressTargets.reconnect, {
    type: "progress",
    scope: "reconnect",
    stage: "connecting",
    message: message || "正在连接实时通道...",
    indeterminate: true,
    status: "in_progress",
  });
}

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

function escapeHtml(input) {
  return String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderSafeMarkdown(text) {
  let html = escapeHtml(text ?? "");
  html = html.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^##\s+(.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^#\s+(.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>[\s\S]*<\/li>)/g, "<ul>$1</ul>");
  html = html.replace(/\n\n+/g, "</p><p>");
  html = `<p>${html}</p>`;
  html = html.replace(/<p>\s*<\/p>/g, "");
  return html;
}

function normalizeIncomingMessage(payload) {
  if (typeof payload === "string") {
    return { kind: "gm", content: payload };
  }
  if (!payload || typeof payload !== "object") {
    return { kind: "gm", content: String(payload ?? "") };
  }
  if (payload.kind) {
    return payload;
  }
  return {
    kind: payload.type === "ai_message" ? "ai" : "gm",
    content: String(payload.content ?? ""),
    player_id: payload.player_id,
    player_name: payload.player_name,
  };
}

function appendStructuredMessage(payload) {
  const normalized = normalizeIncomingMessage(payload);
  state.messageBuffer.push(normalized);
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
    const kind = item.kind || "gm";
    div.className = `message ${kind}`;
    if (kind === "ai") {
      div.classList.add("ai-message-card");
      const title = document.createElement("div");
      title.className = "ai-message-title";
      title.textContent = `🤖 ${item.player_name || item.player_id || "AI玩家"}`;
      const body = document.createElement("div");
      body.className = "md-body";
      body.innerHTML = renderSafeMarkdown(item.content || item.text || "");
      div.append(title, body);
    } else if (kind === "gm") {
      div.classList.add("md-body");
      div.innerHTML = renderSafeMarkdown(item.content || item.text || "");
    } else {
      div.textContent = item.content || item.text || "";
    }
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
    const artifacts = document.createElement("div");
    artifacts.className = "artifact-list";
    const items = Array.isArray(p.artifacts) ? p.artifacts : [];
    if (items.length === 0) {
      artifacts.innerHTML = '<span class="artifact-chip artifact-empty">暂无文物</span>';
    } else {
      for (const a of items) {
        const chip = document.createElement("span");
        chip.className = "artifact-chip";
        const era = translateEra(a.era);
        chip.textContent = `${a.name} · ${era} · ${a.base_value}`;
        artifacts.appendChild(chip);
      }
    }
    card.append(name, stats, cards, artifacts);
    frag.appendChild(card);
  }
  els.playersList.innerHTML = "";
  els.playersList.appendChild(frag);
}

function renderViewerHand(cards = []) {
  const handCards = Array.isArray(cards) ? cards : [];
  if (els.viewerHandCount) {
    els.viewerHandCount.textContent = `${handCards.length} 张`;
  }
  if (!els.viewerHandList) return;

  if (!handCards.length) {
    els.viewerHandList.innerHTML = '<div class="hand-empty">暂无手牌</div>';
    return;
  }

  const frag = document.createDocumentFragment();
  for (const cardInfo of handCards) {
    const row = document.createElement("div");
    row.className = "hand-card";

    const cardTop = document.createElement("div");
    cardTop.className = "hand-card-top";

    const cardName = document.createElement("h4");
    cardName.className = "hand-card-name";
    cardName.textContent = cardInfo?.name || cardInfo?.id || "未知功能卡";

    const tag = document.createElement("span");
    tag.className = "hand-card-tag";
    tag.textContent = "功能卡";

    cardTop.append(cardName, tag);

    const desc = (cardInfo?.description || "").trim();
    const effect = (cardInfo?.effect || "").trim();
    const detail = document.createElement("div");
    detail.className = "hand-card-desc";
    detail.textContent = desc || "无描述";

    row.append(cardTop, detail);

    if (effect) {
      const effectLine = document.createElement("div");
      effectLine.className = "hand-card-effect";
      effectLine.textContent = effect;
      row.appendChild(effectLine);
    }

    frag.appendChild(row);
  }
  els.viewerHandList.innerHTML = "";
  els.viewerHandList.appendChild(frag);
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
  const metrics = payload.context_metrics || {};
  const apiTotalTokens = Number.isFinite(metrics.api_total_tokens) ? metrics.api_total_tokens : null;
  const apiInputTokens = Number.isFinite(metrics.api_input_tokens) ? metrics.api_input_tokens : null;
  const apiOutputTokens = Number.isFinite(metrics.api_output_tokens) ? metrics.api_output_tokens : null;
  const apiRequestCount = Number.isFinite(metrics.api_request_count) ? metrics.api_request_count : 0;
  const estTokens = Number.isFinite(metrics.estimated_tokens) ? metrics.estimated_tokens : null;

  if (apiTotalTokens !== null && apiRequestCount > 0) {
    const parts = [`${apiTotalTokens} tokens`];
    if (apiInputTokens !== null && apiOutputTokens !== null) {
      parts.push(`in ${apiInputTokens} · out ${apiOutputTokens}`);
    }
    parts.push(`${apiRequestCount} req`);
    els.contextLength.textContent = parts.join(" · ");
  } else if (estTokens !== null) {
    els.contextLength.textContent = `≈${estTokens} tokens`;
  } else {
    els.contextLength.textContent = "-";
  }
  renderPlayers(payload.players, payload.current_player_id ?? payload.current_player);
  renderViewerHand(payload.viewer_function_cards ?? []);
  renderAuctionPool(payload.auction_pool ?? []);
}

async function startGame() {
  setSetupError("");
  els.startBtn.disabled = true;
  updateProgress(progressTargets.create_game, {
    type: "progress",
    scope: "create_game",
    stage: "submitting",
    message: "正在提交创建请求...",
    percent: 10,
    status: "in_progress",
  });

  const apiKey = els.apiKey.value.trim();
  if (!apiKey) {
    setSetupError("请输入 API Key");
    updateProgress(progressTargets.create_game, {
      type: "progress",
      scope: "create_game",
      stage: "validation_failed",
      message: "缺少 API Key",
      status: "error",
    });
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
    for (const event of data.progress_events || []) handleProgressEvent(event);

    state.gameId = data.game_id;
    els.setupPanel.classList.add("hidden");
    els.gamePanel.classList.remove("hidden");
    renderState(data.state);
    for (const msg of data.messages || []) {
      appendStructuredMessage(msg);
    }
    connectWebSocket();
  } catch (err) {
    setSetupError(err.message || String(err));
    updateProgress(progressTargets.create_game, {
      type: "progress",
      scope: "create_game",
      stage: "request_failed",
      message: `创建失败: ${err.message || String(err)}`,
      status: "error",
    });
  } finally {
    els.startBtn.disabled = false;
  }
}

function reconnectWebSocketSoon() {
  if (state.intentionallyClosed || !state.gameId) return;
  state.reconnecting = true;
  setReconnectProgress(true, "连接中断，正在重连...");
  if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
  state.reconnectTimer = setTimeout(connectWebSocket, 1500);
}

function connectWebSocket() {
  if (!state.gameId) return;
  if (state.ws && state.ws.readyState <= 1) return;
  setReconnectProgress(true, "正在连接实时通道...");

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  state.ws = new WebSocket(`${protocol}//${window.location.host}/ws/${state.gameId}`);

  state.ws.onopen = () => {
    setConnectionBadge(true);
    state.reconnecting = false;
    setReconnectProgress(false);
  };

  state.ws.onclose = () => {
    setConnectionBadge(false);
    setReconnectProgress(true, "连接中断，正在重连...");
    reconnectWebSocketSoon();
  };

  state.ws.onerror = () => {
    setConnectionBadge(false);
    setReconnectProgress(true, "连接异常，准备重连...");
  };

  state.ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "progress") {
      handleProgressEvent(data);
      return;
    }
    if (data.type === "connected") {
      renderState(data.state);
      setActionRunning(Boolean(data.action_in_progress));
      return;
    }
    if (data.type === "gm_chunk") {
      appendStructuredMessage(data);
      return;
    }
    if (data.type === "state_update") {
      renderState(data.state);
      return;
    }
    if (data.type === "action_status") {
      if (data.status === "started") {
        setActionRunning(true);
        updateProgress(progressTargets.action, {
          type: "progress",
          scope: "action",
          stage: "started",
          message: "行动已开始处理",
          indeterminate: true,
          status: "in_progress",
        });
      }
      if (data.status === "completed" || data.status === "error") {
        setActionRunning(false);
        if (data.status === "completed") {
          scheduleHideProgress(progressTargets.action, "actionHideTimer");
        }
      }
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
    updateProgress(progressTargets.action, {
      type: "progress",
      scope: "action",
      stage: "queued",
      message: "行动已发送，等待服务器处理...",
      indeterminate: true,
      status: "in_progress",
    });
    state.ws.send(JSON.stringify({ action }));
    return;
  }

  setActionRunning(true);
  updateProgress(progressTargets.action, {
    type: "progress",
    scope: "action",
    stage: "http_fallback",
    message: "连接不可用，正在通过 HTTP 执行动作...",
    indeterminate: true,
    status: "in_progress",
  });
  try {
    const res = await fetch(`/api/games/${state.gameId}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: state.gameId, action }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "发送失败");
    for (const event of data.progress_events || []) handleProgressEvent(event);
    for (const msg of data.messages || []) {
      appendStructuredMessage(msg);
    }
    renderState(data.state);
    scheduleHideProgress(progressTargets.action, "actionHideTimer");
  } catch (err) {
    appendMessage(`发送失败: ${err.message || String(err)}`, "error");
    updateProgress(progressTargets.action, {
      type: "progress",
      scope: "action",
      stage: "failed",
      message: `行动失败: ${err.message || String(err)}`,
      status: "error",
    });
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
hideProgress(progressTargets.create_game);
hideProgress(progressTargets.action);
hideProgress(progressTargets.reconnect);
