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
  gameDef: document.getElementById("game-def"),
  actionForm: document.getElementById("action-form"),
  actionInput: document.getElementById("action-input"),
  chatBox: document.getElementById("chat-box"),
  connBadge: document.getElementById("conn-badge"),
  streamBadge: document.getElementById("stream-badge"),
  actionBadge: document.getElementById("action-badge"),
  roundNumber: document.getElementById("round-number"),
  phase: document.getElementById("phase"),
  stability: null,
  contextLength: document.getElementById("context-length"),
  globalResourcesList: document.getElementById("global-resources-list"),
  playersList: document.getElementById("players-list"),
  viewerHandCount: document.getElementById("viewer-hand-count"),
  viewerHandList: document.getElementById("viewer-hand-list"),
  zoneItems: document.getElementById("zone-items"),
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

const ZONE_NAME_MAP = {
  artifact_deck: "文物牌库",
  function_deck: "功能牌库",
  event_deck: "事件牌库",
  auction_zone: "拍卖区",
  event_zone: "事件区",
  discard_pile: "弃牌堆",
  system_warehouse: "系统仓库",
};

const GLOBAL_SKIP_KEYS = new Set([
  "_id", "game_id", "current_player", "starting_player",
  "start_player_index",
]);

function friendlyZoneName(id) {
  return ZONE_NAME_MAP[id] || id;
}

function extractGlobal(payload) {
  const arr = payload.global;
  if (Array.isArray(arr) && arr.length) return arr[0];
  return {};
}

function renderPlayers(players = [], currentPlayerId = null) {
  const list = Array.isArray(players) ? players : Object.values(players);
  if (!list.length) {
    els.playersList.innerHTML = '<div class="empty-card">暂无玩家数据</div>';
    return;
  }

  const SKIP_KEYS = new Set(["_id", "id", "name", "is_human", "has_acted", "type", "hand"]);
  const frag = document.createDocumentFragment();
  for (const p of list) {
    const playerId = p._id || p.id || "";
    const card = document.createElement("div");
    card.className = `player-card ${playerId === currentPlayerId ? "current" : ""}`;
    const name = document.createElement("div");
    const displayName = p.name ?? playerId;
    const typeLabel = p.type === "human" ? "👤" : "🤖";
    name.textContent = `${typeLabel} ${displayName}`;

    const stats = document.createElement("div");
    stats.className = "meta";
    const statParts = [];
    for (const [key, val] of Object.entries(p)) {
      if (SKIP_KEYS.has(key)) continue;
      if (typeof val === "number") {
        statParts.push(`${key}: ${val}`);
      } else if (typeof val === "object" && val !== null && !Array.isArray(val)) {
        const subParts = Object.entries(val).map(([k, v]) => `${k}:${v}`).join("/");
        if (subParts) statParts.push(`${key}: ${subParts}`);
      }
    }
    stats.textContent = statParts.join(" · ") || "无资源";

    const itemsDiv = document.createElement("div");
    itemsDiv.className = "meta";
    const itemParts = [];
    for (const [key, val] of Object.entries(p)) {
      if (SKIP_KEYS.has(key)) continue;
      if (Array.isArray(val)) {
        const names = val.slice(0, 3).map((v) => v?.name || v?.card_id || "?").join(", ");
        const suffix = val.length > 3 ? `… 共${val.length}件` : "";
        itemParts.push(`${key}(${val.length}): ${names}${suffix}`);
      }
    }
    if (itemParts.length) {
      itemsDiv.textContent = itemParts.join(" · ");
    }

    card.append(name, stats);
    if (itemParts.length) card.appendChild(itemsDiv);
    frag.appendChild(card);
  }
  els.playersList.innerHTML = "";
  els.playersList.appendChild(frag);
}

function renderViewerHand(handCards = [], viewerPlayerData = null) {
  // Count all viewer items: hand cards + other array fields from player data
  const VIEWER_SKIP_KEYS = new Set(["_id", "id", "name", "type", "is_human", "has_acted"]);
  let totalItems = 0;
  const sections = [];

  // 1) Hand cards (from viewer_hand_items for backward compat)
  const cards = Array.isArray(handCards) ? handCards : [];
  if (cards.length) {
    totalItems += cards.length;
    sections.push({ label: "手牌", tag: "手牌", items: cards, type: "card" });
  }

  // 2) Other array fields from viewer_player_data (artifacts, etc.)
  if (viewerPlayerData && typeof viewerPlayerData === "object") {
    for (const [key, val] of Object.entries(viewerPlayerData)) {
      if (VIEWER_SKIP_KEYS.has(key) || key === "hand") continue;
      if (Array.isArray(val) && val.length > 0) {
        totalItems += val.length;
        sections.push({ label: friendlyZoneName(key) || key, tag: key, items: val, type: "card" });
      }
    }
  }

  // 3) Numeric stats from viewer_player_data (gold, vp, etc.)
  const statParts = [];
  if (viewerPlayerData && typeof viewerPlayerData === "object") {
    for (const [key, val] of Object.entries(viewerPlayerData)) {
      if (VIEWER_SKIP_KEYS.has(key)) continue;
      if (typeof val === "number") {
        statParts.push({ key, val });
      } else if (typeof val === "object" && val !== null && !Array.isArray(val)) {
        const sub = Object.entries(val).map(([k, v]) => `${k}:${v}`).join("/");
        if (sub) statParts.push({ key, val: sub });
      }
    }
  }

  if (els.viewerHandCount) {
    els.viewerHandCount.textContent = `${totalItems} 件`;
  }
  if (!els.viewerHandList) return;

  if (!sections.length && !statParts.length) {
    els.viewerHandList.innerHTML = '<div class="hand-empty">暂无物品</div>';
    return;
  }

  const frag = document.createDocumentFragment();

  // Player resource stats bar
  if (statParts.length) {
    const statsBar = document.createElement("div");
    statsBar.className = "viewer-stats-bar";
    statsBar.innerHTML = statParts
      .map((s) => `<span class="viewer-stat"><b>${s.key}</b> ${s.val}</span>`)
      .join("");
    frag.appendChild(statsBar);
  }

  // Sections (hand, artifacts, etc.)
  for (const sec of sections) {
    const secDiv = document.createElement("div");
    secDiv.className = "viewer-section";
    const secTitle = document.createElement("div");
    secTitle.className = "viewer-section-title";
    secTitle.textContent = `${sec.label} (${sec.items.length})`;
    secDiv.appendChild(secTitle);

    for (const item of sec.items) {
      const row = document.createElement("div");
      row.className = "hand-card";

      const cardTop = document.createElement("div");
      cardTop.className = "hand-card-top";
      const cardName = document.createElement("h4");
      cardName.className = "hand-card-name";

      let displayName;
      if (typeof item === "string") {
        displayName = item;
      } else if (typeof item === "object" && item !== null) {
        displayName = item.name || item.card_name || item.card_id || item.id || item._id || "未知";
      } else {
        displayName = String(item);
      }
      cardName.textContent = displayName;

      const tag = document.createElement("span");
      tag.className = "hand-card-tag";
      tag.textContent = sec.tag;
      cardTop.append(cardName, tag);
      row.appendChild(cardTop);

      // Description and effect (for dict items)
      if (typeof item === "object" && item !== null) {
        const desc = (item.description || item.desc || "").toString().trim();
        const effect = (item.effect || "").toString().trim();
        if (desc) {
          const descDiv = document.createElement("div");
          descDiv.className = "hand-card-desc";
          descDiv.textContent = desc;
          row.appendChild(descDiv);
        }
        if (effect) {
          const effectDiv = document.createElement("div");
          effectDiv.className = "hand-card-effect";
          effectDiv.textContent = effect;
          row.appendChild(effectDiv);
        }
        // Extra fields as meta
        const extraParts = [];
        const CARD_SKIP = new Set(["name", "card_name", "card_id", "id", "_id", "description", "desc", "effect"]);
        for (const [k, v] of Object.entries(item)) {
          if (CARD_SKIP.has(k)) continue;
          if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
            extraParts.push(`${k}: ${v}`);
          }
        }
        if (extraParts.length) {
          const metaDiv = document.createElement("div");
          metaDiv.className = "hand-card-meta";
          metaDiv.textContent = extraParts.join(" · ");
          row.appendChild(metaDiv);
        }
      }

      secDiv.appendChild(row);
    }
    frag.appendChild(secDiv);
  }

  els.viewerHandList.innerHTML = "";
  els.viewerHandList.appendChild(frag);
}

function renderZones(zonesDocs = [], globalDoc = {}) {
  const container = els.zoneItems;
  if (!container) return;

  const frag = document.createDocumentFragment();

  // Build a map: zone_id -> { meta: zone doc, items: [] from global }
  const zoneMap = new Map();

  // Seed from zones docs
  const zonesArr = Array.isArray(zonesDocs) ? zonesDocs : [];
  for (const zone of zonesArr) {
    const zid = zone._id || zone.id || "";
    if (!zid) continue;
    zoneMap.set(zid, { meta: zone, items: [] });
  }

  // Match global array fields to zones
  for (const [key, val] of Object.entries(globalDoc)) {
    if (GLOBAL_SKIP_KEYS.has(key)) continue;
    if (!Array.isArray(val) || !val.length) continue;
    if (typeof val[0] !== "object") continue;
    if (!zoneMap.has(key)) {
      zoneMap.set(key, { meta: null, items: [] });
    }
    zoneMap.get(key).items = val;
  }

  for (const [zoneId, { meta, items }] of zoneMap) {
    const group = document.createElement("div");
    group.className = "zone-group";

    // Zone header
    const header = document.createElement("div");
    header.className = "zone-group-header";
    const title = document.createElement("span");
    title.className = "zone-group-name";
    title.textContent = friendlyZoneName(zoneId);
    header.appendChild(title);

    // Meta badge (remaining/count/type)
    if (meta) {
      const badge = document.createElement("span");
      badge.className = "zone-group-badge";
      const parts = [];
      for (const [k, v] of Object.entries(meta)) {
        if (k === "_id" || k === "id") continue;
        if (typeof v === "string" || typeof v === "number") {
          parts.push(`${k}: ${v}`);
        }
      }
      if (items.length && !parts.some((p) => p.startsWith("count"))) {
        parts.unshift(`${items.length} 件`);
      }
      badge.textContent = parts.join(" · ");
      header.appendChild(badge);
    } else if (items.length) {
      const badge = document.createElement("span");
      badge.className = "zone-group-badge";
      badge.textContent = `${items.length} 件`;
      header.appendChild(badge);
    }

    group.appendChild(header);

    // Zone items
    if (items.length) {
      const itemsWrap = document.createElement("div");
      itemsWrap.className = "zone-group-items";
      for (const item of items) {
        const box = document.createElement("div");
        box.className = "zone-item";
        const itemTitle = document.createElement("div");
        itemTitle.className = "title";
        itemTitle.textContent = item?.name || item?.card_name || item?.card_id || item?._id || "未知物品";
        box.appendChild(itemTitle);

        const metaParts = [];
        const ITEM_SKIP = new Set(["name", "card_name", "card_id", "_id"]);
        for (const [k, v] of Object.entries(item)) {
          if (ITEM_SKIP.has(k)) continue;
          if (Array.isArray(v)) {
            metaParts.push(`${k}: ${v.join(", ")}`);
          } else if (typeof v === "string" || typeof v === "number") {
            metaParts.push(`${k}: ${v}`);
          }
        }
        if (metaParts.length) {
          const metaDiv = document.createElement("div");
          metaDiv.className = "meta";
          metaDiv.textContent = metaParts.join(" · ");
          box.appendChild(metaDiv);
        }
        itemsWrap.appendChild(box);
      }
      group.appendChild(itemsWrap);
    } else {
      const empty = document.createElement("div");
      empty.className = "zone-group-empty";
      empty.textContent = "空";
      group.appendChild(empty);
    }

    frag.appendChild(group);
  }

  if (!frag.childNodes.length) {
    container.innerHTML = '<div class="empty-card">暂无公共物品</div>';
    return;
  }
  container.innerHTML = "";
  container.appendChild(frag);
}

function renderState(payload) {
  if (!payload || payload.error) return;

  const g = extractGlobal(payload);

  els.roundNumber.textContent = g.round ?? g.current_round ?? 1;
  els.phase.textContent = g.phase ?? g.current_phase ?? "-";

  // 动态渲染全局资源（数字和倍率字段）
  if (els.globalResourcesList) {
    const resParts = [];
    for (const [key, val] of Object.entries(g)) {
      if (GLOBAL_SKIP_KEYS.has(key)) continue;
      if (key === "round" || key === "current_round" || key === "phase" || key === "current_phase") continue;
      if (typeof val === "number") {
        resParts.push(`<div><span>${key}</span><strong>${val}</strong></div>`);
      }
    }
    els.globalResourcesList.innerHTML = resParts.join("");
  }

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

  const currentPlayer = g.current_player ?? g.current_player_id ?? null;
  renderPlayers(payload.players, currentPlayer);
  renderViewerHand(payload.viewer_hand_items ?? [], payload.viewer_player_data ?? null);
  renderZones(payload.zones || [], g);
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

  const gameDef = els.gameDef ? els.gameDef.value : "";
  if (!gameDef) {
    setSetupError("请选择一个游戏定义");
    els.startBtn.disabled = false;
    return;
  }
  body.game_id = gameDef;

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

// 加载可用的游戏定义列表
async function loadGameDefinitions(selectValue) {
  try {
    const res = await fetch("/api/games/definitions");
    if (!res.ok) return;
    const data = await res.json();
    const select = els.gameDef;
    if (!select) return;
    select.innerHTML = "";
    for (const def of data.definitions || []) {
      const opt = document.createElement("option");
      opt.value = def.id || def.name || "";
      opt.textContent = def.name || def.id;
      select.appendChild(opt);
    }
    if (!select.options.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "（无可用游戏）";
      opt.disabled = true;
      select.appendChild(opt);
    }
    if (selectValue) {
      select.value = selectValue;
    }
  } catch (e) {
    console.warn("加载游戏定义列表失败:", e);
    const select = els.gameDef;
    if (select) {
      select.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "（加载失败）";
      opt.disabled = true;
      select.appendChild(opt);
    }
  }
}
loadGameDefinitions();
