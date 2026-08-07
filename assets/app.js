// AI 每日资讯 —— 前端逻辑
// 读取 data/feed.json，渲染最新/历史日期的 AI 新闻与 GitHub 趋势。

const DATA_URL = "data/feed.json";

// 历史记录保留窗口：仅展示/保留最近 KEEP_DAYS 天
const KEEP_DAYS = 7;
// 过期清理分批大小（避免一次性删除大量数据阻塞主线程）
const PRUNE_BATCH = 20;

const state = {
  entries: {},
  dates: [],
  current: null,
};

function fmtDate(d) {
  // 输入 YYYY-MM-DD -> YYYY年MM月DD日
  const [y, m, day] = d.split("-");
  return `${y}年${Number(m)}月${Number(day)}日`;
}

function fmtTime(iso) {
  if (!iso) return "";
  const t = new Date(iso);
  if (isNaN(t)) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `更新于 ${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())} ${pad(t.getHours())}:${pad(t.getMinutes())}`;
}

// ----------------------------------------------------------------
// 历史记录过期清理（读取时触发，静默后台执行）
// 以最新日期为基准，仅保留最近 KEEP_DAYS 天：
//   1) 数组同步裁剪（轻量，立即生效，保证 UI 只渲染窗口内日期）；
//   2) 数据对象分批释放（PRUNE_BATCH 个一组，setTimeout 让出主线程，不阻塞交互）。
function pruneExpiredDates() {
  const latest = state.dates[0];
  if (!latest) return;
  const keepFrom = new Date(latest + "T00:00:00");
  keepFrom.setDate(keepFrom.getDate() - (KEEP_DAYS - 1));
  const y = keepFrom.getFullYear();
  const m = String(keepFrom.getMonth() + 1).padStart(2, "0");
  const d = String(keepFrom.getDate()).padStart(2, "0");
  const keepFromStr = `${y}-${m}-${d}`; // YYYY-MM-DD 字符串可直接比较

  const expired = state.dates.filter((dt) => dt < keepFromStr);
  if (!expired.length) return;

  // 1) 同步裁剪日期数组（量小，不阻塞）
  state.dates = state.dates.filter((dt) => dt >= keepFromStr);
  if (state.current && expired.indexOf(state.current) !== -1) {
    state.current = state.dates[0];
  }

  // 2) 分批释放过期数据对象（静默后台执行）
  let i = 0;
  (function nextBatch() {
    const slice = expired.slice(i, i + PRUNE_BATCH);
    slice.forEach((x) => {
      delete state.entries[x];
    });
    i += PRUNE_BATCH;
    if (i < expired.length) {
      setTimeout(nextBatch, 0);
    }
  })();
}

// ----------------------------------------------------------------
// 日期校验：按选定日期精准调取资源，若链接指向的文件名日期与当前日期不一致，
// 视为错配/串用，隐藏该入口并弹出告警，避免展示错误日期的内容。
function fileEndsWithDate(path, date, ext) {
  if (!path) return false;
  return path.endsWith(`${date}${ext}`);
}

let _warnShown = false;
function flagDateMismatch(kind, path, date) {
  const el = document.getElementById("date-warning");
  if (!el) return;
  el.hidden = false;
  el.textContent = `⚠️ 日期校验异常：${kind}资源（${path || "无"}）与当前查看日期 ${date} 不匹配，已隐藏该入口，避免展示错误日期的内容。`;
  _warnShown = true;
}

function clearDateWarning() {
  const el = document.getElementById("date-warning");
  if (el) {
    el.hidden = true;
    el.textContent = "";
  }
  _warnShown = false;
}

function renderMarkdown(md) {
  if (!md || !md.trim()) return '<p class="loading">今日尚未更新</p>';
  try {
    if (typeof marked === "undefined" || !marked.parse) {
      // marked 未加载时的安全降级：原文转义展示，绝不白屏
      const esc = (md || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
      return '<pre class="md-fallback">' + esc + "</pre>";
    }
    const html = marked.parse(md);
    if (typeof DOMPurify !== "undefined") return DOMPurify.sanitize(html);
    return html;
  } catch (e) {
    const esc = (md || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    return '<pre class="md-fallback">' + esc + "</pre>";
  }
}

// ----------------------------------------------------------------
// GitHub 趋势：首页紧凑榜单（排名+项目+Star，无注解），点击展开完整信息
function esc(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

function parseRow(cells, kind) {
  const rank = cells[0];
  const proj = cells[1];
  const pm = proj.match(/\[([^\]]+)\]\(([^)]+)\)/);
  const repo = pm ? pm[1].trim() : proj;
  const url = pm ? pm[2].trim() : "#";
  const dm = proj.match(/repo-desc"[^>]*>(.*?)<\/span>/);
  const repoDesc = dm ? dm[1].trim() : "";
  let added, total = null;
  if (kind === "本周榜") {
    total = cells[2];
    added = cells[3];
  } else {
    added = cells[2];
  }
  const note = cells[cells.length - 1];
  return { rank, repo, url, repoDesc, added, total, note };
}

function renderBoard(chunk, kind) {
  const headM = chunk.match(/^##\s*(.+)$/m);
  const title = headM ? headM[1].trim() : kind;
  const quoteM = chunk.match(/^>\s*(.+)$/m);
  const intro = quoteM ? quoteM[1].trim() : "";
  const commentM = chunk.match(/\*\*([^*]+)\*\*[：:]\s*([\s\S]*?)(?=\n##|$)/);
  const comment = commentM ? commentM[2].trim() : "";

  const rows = [];
  chunk.split("\n").forEach((line) => {
    if (!/^\|\s*\d+\s*\|/.test(line)) return;
    let cells = line.split("|").slice(1);
    if (cells.length && cells[cells.length - 1].trim() === "") cells.pop();
    cells = cells.map((c) => c.trim());
    if (!/^\d+$/.test(cells[0])) return; // 跳过表头
    rows.push(parseRow(cells, kind));
  });

  const starLabel = kind === "本周榜" ? "本周新增" : "今日新增";
  const rowHtml = rows
    .map((r) => {
      const star =
        `<b class="gh-star-num">${esc(r.added)}</b>` +
        `<span class="gh-star-sub">${starLabel}</span>` +
        (kind === "本周榜" && r.total
          ? `<span class="gh-star-total">总 ${esc(r.total)}</span>`
          : "");
      return (
        `<li class="gh-row">` +
        `<span class="gh-rank">${esc(r.rank)}</span>` +
        `<div class="gh-main">` +
        `<a class="gh-repo" href="${esc(r.url)}" target="_blank" rel="noopener" title="${esc(r.repo)}">${esc(r.repo)}</a>` +
        (r.repoDesc ? `<span class="gh-desc">${esc(r.repoDesc)}</span>` : "") +
        (r.note ? `<p class="gh-note">${esc(r.note)}</p>` : "") +
        `</div>` +
        `<span class="gh-star">${star}</span>` +
        `</li>`
      );
    })
    .join("");

  return (
    `<div class="gh-board" data-expanded="false">` +
    `<div class="gh-board-head">` +
    `<span class="gh-board-title">${esc(title)}</span>` +
    `<button class="gh-toggle" type="button">展开完整注解 ▾</button>` +
    `</div>` +
    `<ul class="gh-list">${rowHtml}</ul>` +
    // 「看点 / 趋势点评」跟随展开状态显示，位置放在榜单之后，阅读顺序与原文一致
    (intro ? `<p class="gh-intro">${esc(intro)}</p>` : "") +
    (comment
      ? `<p class="gh-comment"><strong>${esc(commentM[1])}：</strong>${esc(comment)}</p>`
      : "") +
    `</div>`
  );
}

function renderGithub(md) {
  if (!md || !md.trim()) return '<p class="loading">今日尚未更新</p>';
  try {
    const idxWeek = md.search(/^##\s*二、/m);
    const todayChunk = idxWeek >= 0 ? md.slice(0, idxWeek) : md;
    const weekChunk = idxWeek >= 0 ? md.slice(idxWeek) : "";
    let html = renderBoard(todayChunk, "今日榜");
    if (weekChunk.trim()) html += renderBoard(weekChunk, "本周榜");
    return html;
  } catch (e) {
    // 榜单解析异常时降级为普通 Markdown 渲染，绝不白屏
    return renderMarkdown(md);
  }
}

function bindGithubToggles() {
  document.querySelectorAll("#gh-content .gh-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const board = btn.closest(".gh-board");
      const expanded = board.getAttribute("data-expanded") === "true";
      board.setAttribute("data-expanded", String(!expanded));
      btn.textContent = !expanded ? "收起完整注解 ▴" : "展开完整注解 ▾";
    });
  });
}

function render() {
  const date = state.current;
  const entry = state.entries[date] || {};

  document.getElementById("viewing-date").textContent = fmtDate(date);
  clearDateWarning();

  const ai = entry.aiNews;
  const gh = entry.github;
  document.getElementById("ai-content").innerHTML = renderMarkdown(ai && ai.markdown);
  document.getElementById("gh-content").innerHTML = renderGithub(gh && gh.markdown);
  bindGithubToggles();
  document.getElementById("ai-time").textContent = ai ? fmtTime(ai.generatedAt) : "暂无";
  document.getElementById("gh-time").textContent = gh ? fmtTime(gh.generatedAt) : "暂无";

  // 给 GitHub 表格 td 补上移动端 data-label
  requestAnimationFrame(() => {
    document.querySelectorAll(".content table").forEach((table) => {
      const headers = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent.trim());
      if (!headers.length) return;
      table.querySelectorAll("tbody tr").forEach((row) => {
        Array.from(row.children).forEach((td, i) => {
          if (headers[i]) td.setAttribute("data-label", headers[i]);
        });
      });
    });
  });

  const isLatest = date === state.dates[0];
  document.getElementById("latest-btn").hidden = isLatest;

  // 海报：该日期有真实生成的海报文件时显示，并指向对应日期（不再统一 latest）
  const posterLink = document.getElementById("poster-link");
  if (posterLink) {
    const poster = entry.poster;
    // 校验：链接文件名日期必须与当前查看日期一致，严防串用
    if (poster && fileEndsWithDate(poster, date, ".png")) {
      posterLink.hidden = false;
      posterLink.href = poster;
    } else {
      posterLink.hidden = true;
      if (poster) flagDateMismatch("海报", poster, date);
    }
  }

  // 速览模式：该日期有真实生成的速览页时显示，并指向对应日期（不再统一 latest）
  const summaryLink = document.getElementById("summary-link");
  if (summaryLink) {
    const sumHtml =
      entry.summaryHtml ||
      (entry.summary && entry.summary.markdown && entry.summary.markdown.trim()
        ? `output/summary/${date}.html`
        : "");
    // 校验：速览页文件名日期必须与当前查看日期一致
    if (sumHtml && fileEndsWithDate(sumHtml, date, ".html")) {
      summaryLink.hidden = false;
      summaryLink.href = sumHtml;
    } else {
      summaryLink.hidden = true;
      if (sumHtml) flagDateMismatch("速览模式", sumHtml, date);
    }
  }

  // 高亮当前日期
  document.querySelectorAll(".date-chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.date === date);
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderHistory() {
  const bar = document.getElementById("history-bar");
  bar.innerHTML = "";

  // 仅渲染最近 KEEP_DAYS 个日期的直达按钮（数量由 pruneExpiredDates 保证，
  // 这里再兜底截断，避免渲染窗口外日期）
  state.dates.slice(0, KEEP_DAYS).forEach((d) => {
    const chip = document.createElement("button");
    chip.className = "date-chip";
    chip.dataset.date = d;
    chip.textContent = fmtDate(d);
    chip.addEventListener("click", () => {
      state.current = d;
      render();
    });
    bar.appendChild(chip);
  });
}

// —— 按 年/月/日 精确选择历史（数据变多时仍可快速定位）——
// 已移除：历史记录仅保留最近 7 天，无需年/月/日层级查找与筛选。

async function init() {
  try {
    const res = await fetch(DATA_URL + "?t=" + Date.now(), { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    state.entries = data.entries || {};
    state.dates = Object.keys(state.entries).sort().reverse();
    state.current = state.dates[0] || null;

    // 读取时触发过期清理：静默移除超过 7 天的历史记录（分批后台执行）
    pruneExpiredDates();

    if (!state.current) {
      document.getElementById("ai-content").innerHTML = '<p class="loading">暂无数据</p>';
      document.getElementById("gh-content").innerHTML = '<p class="loading">暂无数据</p>';
      return;
    }

    renderHistory();
    render();
  } catch (e) {
    document.getElementById("ai-content").innerHTML =
      '<p class="loading">数据加载失败：' + e.message + "</p>";
    document.getElementById("gh-content").innerHTML =
      '<p class="loading">请确认 data/feed.json 存在，并通过本地服务器或已部署站点访问。</p>';
  }
}

document.getElementById("latest-btn").addEventListener("click", () => {
  state.current = state.dates[0];
  render();
});

marked.setOptions({ gfm: true, breaks: false });
init();