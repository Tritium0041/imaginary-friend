/* 游戏管理页面逻辑 */

const $ = (sel) => document.querySelector(sel);
const gamesGrid = $("#games-grid");
const modal = $("#detail-modal");
const detailTitle = $("#detail-title");
const detailBody = $("#detail-body");
const detailClose = $("#detail-close");

// ---- 游戏列表 ----

async function loadGames() {
  try {
    const res = await fetch("/api/games/definitions");
    const data = await res.json();
    renderGames(data.definitions || []);
  } catch (err) {
    gamesGrid.innerHTML = `<div class="empty-text">加载失败: ${err.message}</div>`;
  }
}

function renderGames(games) {
  if (!games.length) {
    gamesGrid.innerHTML = '<div class="empty-text">暂无游戏定义，请上传规则书（PDF / DOCX / MD）</div>';
    return;
  }
  gamesGrid.innerHTML = games
    .map(
      (g) => `
    <div class="game-card" data-id="${g.id}">
      <div class="game-card-header">
        <span class="game-card-name">${g.name}</span>
        <span class="game-card-source ${g.source === "builtin" ? "source-builtin" : "source-cached"}">
          ${g.source === "builtin" ? "内置" : "导入"}
        </span>
      </div>
      <div class="game-card-desc">${g.description || "暂无描述"}</div>
      <div class="game-card-meta">
        <span>ID: ${g.id}</span>
      </div>
    </div>`
    )
    .join("");

  gamesGrid.querySelectorAll(".game-card").forEach((card) => {
    card.addEventListener("click", () => openDetail(card.dataset.id));
  });
}

// ---- 详情弹窗 ----

async function openDetail(gameId) {
  detailTitle.textContent = "加载中...";
  detailBody.innerHTML = "";
  modal.classList.remove("hidden");

  try {
    const res = await fetch(`/api/games/definitions/${gameId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const def = await res.json();
    renderDetail(def);
  } catch (err) {
    detailTitle.textContent = "加载失败";
    detailBody.innerHTML = `<p class="detail-msg error">${err.message}</p>`;
  }
}

function renderDetail(def) {
  const meta = def.metadata || {};
  const gameId = def.game_id || def.id || "";
  const card = gamesGrid.querySelector(`[data-id="${gameId}"]`);
  const source = card?.querySelector(".source-builtin") ? "builtin" : "cached";

  detailTitle.textContent = meta.game_name || gameId;

  detailBody.innerHTML = `
    <div class="detail-field">
      <label>游戏 ID</label>
      <div class="readonly-text">${gameId}</div>
    </div>
    <div class="detail-field">
      <label>名称</label>
      <input type="text" id="edit-name" value="${esc(meta.game_name || "")}" />
    </div>
    <div class="detail-field">
      <label>简介</label>
      <textarea id="edit-description" rows="2">${esc(meta.description || "")}</textarea>
    </div>
    <div class="detail-field">
      <label>玩家人数</label>
      <div style="display:flex;gap:0.5rem;align-items:center;">
        <input type="number" id="edit-min" value="${meta.player_count_min ?? ""}" style="width:60px" min="1" />
        <span>~</span>
        <input type="number" id="edit-max" value="${meta.player_count_max ?? ""}" style="width:60px" min="1" />
      </div>
    </div>
    <div class="detail-field">
      <label>规则书（Markdown）</label>
      <textarea id="edit-rules" class="rules-textarea" readonly>${esc(def.rules_md || "")}</textarea>
    </div>
    <p id="detail-msg" class="detail-msg"></p>
    <div class="detail-actions">
      <button id="save-btn" class="btn-primary btn-sm">💾 保存修改</button>
      ${source !== "builtin" ? '<button id="delete-btn" class="btn-danger btn-sm">🗑️ 删除游戏</button>' : ""}
      <a href="/play?game=${gameId}" class="btn-primary btn-sm" style="text-decoration:none;text-align:center;">🎮 开始游戏</a>
    </div>
  `;

  $("#save-btn").addEventListener("click", () => saveDefinition(gameId));
  const delBtn = $("#delete-btn");
  if (delBtn) delBtn.addEventListener("click", () => deleteDefinition(gameId));
}

function esc(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function saveDefinition(gameId) {
  const msg = $("#detail-msg");
  msg.className = "detail-msg";
  msg.textContent = "保存中...";

  const body = {
    game_name: $("#edit-name").value,
    description: $("#edit-description").value,
    player_count_min: parseInt($("#edit-min").value, 10) || 2,
    player_count_max: parseInt($("#edit-max").value, 10) || 6,
  };

  try {
    const res = await fetch(`/api/games/definitions/${gameId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    msg.textContent = "✅ 保存成功";
    msg.className = "detail-msg success";
    loadGames();
  } catch (err) {
    msg.textContent = `❌ ${err.message}`;
    msg.className = "detail-msg error";
  }
}

async function deleteDefinition(gameId) {
  if (!confirm(`确定要删除游戏 "${gameId}" 吗？此操作不可撤销。`)) return;

  const msg = $("#detail-msg");
  msg.className = "detail-msg";
  msg.textContent = "删除中...";

  try {
    const res = await fetch(`/api/games/definitions/${gameId}`, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    modal.classList.add("hidden");
    loadGames();
  } catch (err) {
    msg.textContent = `❌ ${err.message}`;
    msg.className = "detail-msg error";
  }
}

// 关闭弹窗
detailClose.addEventListener("click", () => modal.classList.add("hidden"));
$("#detail-modal .modal-backdrop").addEventListener("click", () =>
  modal.classList.add("hidden")
);

// ---- 规则书上传（PDF / DOCX / MD）----

(function initUpload() {
  const dropZone = $("#manage-drop-zone");
  const fileInput = $("#manage-pdf-file");
  const browseLink = $("#manage-browse-link");
  const fileInfo = $("#manage-upload-file-info");
  const filename = $("#manage-upload-filename");
  const uploadBtn = $("#manage-upload-btn");
  const cancelBtn = $("#manage-upload-cancel-btn");
  const progressWrap = $("#manage-upload-progress-wrap");
  const result = $("#manage-upload-result");
  const apiKeyInput = $("#manage-api-key");
  const baseUrlInput = $("#manage-base-url");
  const modelInput = $("#manage-model");

  let selectedFile = null;

  function showFile(file) {
    if (!file || !/\.(pdf|docx|md)$/i.test(file.name)) {
      result.textContent = "❌ 请选择 PDF、DOCX 或 MD 文件";
      result.className = "error";
      result.classList.remove("hidden");
      return;
    }
    selectedFile = file;
    const sizeMB = (file.size / 1024 / 1024).toFixed(1);
    filename.textContent = `${file.name} (${sizeMB} MB)`;
    fileInfo.classList.remove("hidden");
    result.classList.add("hidden");
  }

  function resetUpload() {
    selectedFile = null;
    fileInput.value = "";
    fileInfo.classList.add("hidden");
    progressWrap.classList.add("hidden");
    result.classList.add("hidden");
  }

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    if (e.dataTransfer.files.length) showFile(e.dataTransfer.files[0]);
  });

  browseLink.addEventListener("click", (e) => {
    e.preventDefault();
    fileInput.click();
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) showFile(fileInput.files[0]);
  });

  cancelBtn.addEventListener("click", resetUpload);

  uploadBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    fileInfo.classList.add("hidden");
    progressWrap.classList.remove("hidden");
    result.classList.add("hidden");

    const formData = new FormData();
    formData.append("file", selectedFile);
    const key = apiKeyInput.value.trim();
    if (key) formData.append("api_key", key);
    const baseUrl = baseUrlInput.value.trim();
    if (baseUrl) formData.append("base_url", baseUrl);
    const model = modelInput.value.trim();
    if (model) formData.append("model", model);

    try {
      const res = await fetch("/api/games/upload-rules", { method: "POST", body: formData });
      progressWrap.classList.add("hidden");

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const gameName = data.metadata?.game_name || "未知游戏";
      const cached = data.status === "cached" ? "（使用缓存）" : "";
      result.textContent = `✅ 成功导入: ${gameName} ${cached}`;
      result.className = "success";
      result.classList.remove("hidden");
      resetUpload();
      result.classList.remove("hidden"); // keep visible after reset
      loadGames();
    } catch (err) {
      progressWrap.classList.add("hidden");
      result.textContent = `❌ ${err.message}`;
      result.className = "error";
      result.classList.remove("hidden");
    }
  });
})();

// ---- 初始化 ----
loadGames();
