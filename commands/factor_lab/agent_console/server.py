"""Agent Console Server — 前端页面 + 路由"""
CONSOLE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hermes Agent Console — 控制塔</title>
  <style>
    :root { color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; background: #0b1020; color: #e8ecf8; display: flex; height: 100vh; }
    /* ===== Sidebar ===== */
    .sidebar { width: 260px; min-width: 260px; background: #111832; border-right: 1px solid #26304f; display: flex; flex-direction: column; overflow: hidden; }
    .sidebar-header { padding: 14px 16px; border-bottom: 1px solid #26304f; display: flex; align-items: center; gap: 8px; }
    .sidebar-header h2 { margin: 0; font-size: 14px; color: #cdd6f8; flex: 1; }
    .sidebar-filters { padding: 8px 12px; display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid #1a2440; }
    .sidebar-filters select, .sidebar-filters input { padding: 4px 8px; border-radius: 6px; border: 1px solid #26304f; background: #0b1020; color: #e8ecf8; font-size: 11px; flex: 1; min-width: 0; }
    .sidebar-list { flex: 1; overflow-y: auto; }
    .session-item { padding: 10px 14px; border-bottom: 1px solid #1a2440; cursor: pointer; font-size: 12px; transition: background 0.15s; }
    .session-item:hover { background: #1e2a4a; }
    .session-item.active { background: #1e2a4a; border-left: 3px solid #7aa2f7; }
    .session-item .si-agent { font-size: 10px; color: #9aa7c7; }
    .session-item .si-prompt { color: #cdd6f8; margin: 3px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .session-item .si-meta { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
    .session-item .si-version { color: #7aa2f7; font-size: 10px; }
    /* ===== Main ===== */
    .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    header { padding: 12px 20px; background: #111832; border-bottom: 1px solid #26304f; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    h1 { margin: 0; font-size: 16px; flex: 1; }
    .container { flex: 1; padding: 16px 20px; overflow-y: auto; display: flex; flex-direction: column; }
    .toolbar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
    .toolbar select, .toolbar button, .toolbar input { padding: 6px 12px; border-radius: 8px; border: 1px solid #26304f; background: #121a35; color: #e8ecf8; font-size: 13px; }
    .toolbar select { min-width: 140px; }
    .toolbar button { cursor: pointer; }
    .toolbar button:hover { background: #1e2a4a; }
    .toolbar button:disabled { opacity: 0.5; cursor: default; }
    .prompt-area { margin-bottom: 10px; }
    .prompt-area textarea { width: 100%; min-height: 52px; max-height: 120px; background: #121a35; border: 1px solid #26304f; border-radius: 8px; color: #e8ecf8; padding: 8px 10px; font-size: 13px; resize: vertical; box-sizing: border-box; }
    .answer-area { background: #121a35; border: 1px solid #26304f; border-radius: 8px; padding: 14px; min-height: 200px; flex: 1; white-space: pre-wrap; font-size: 14px; line-height: 1.6; overflow: auto; }
    .diagnostic-area { background: #080d1c; border: 1px solid #26304f; border-radius: 8px; padding: 10px; margin-top: 10px; font-size: 12px; line-height: 1.4; max-height: 160px; overflow: auto; display: none; }
    .diagnostic-area.show { display: block; }
    .status-badge { display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
    .status-pending { background: #44380c; color: #ffdc7a; }
    .status-running { background: #0f3d2e; color: #7df0bd; }
    .status-completed { background: #0f3d2e; color: #7df0bd; }
    .status-failed { background: #4a1620; color: #ff8ba0; }
    .status-cancelled { background: #44380c; color: #ffdc7a; }
    .status-orphaned { background: #44380c; color: #9aa7c7; }
    .toggle-diagnostic { font-size: 12px; color: #9aa7c7; cursor: pointer; margin-top: 6px; display: inline-block; }
    .toggle-diagnostic:hover { color: #cdd6f8; }
    .artifact-link { font-size: 12px; color: #7aa2f7; text-decoration: none; margin-left: 12px; }
    .artifact-link:hover { text-decoration: underline; }
    .pill { display: inline-flex; padding: 2px 6px; border-radius: 4px; font-size: 10px; background: #1a2440; color: #9aa7c7; }
    .answer-meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
    .section-label { font-size: 12px; color: #9aa7c7; margin: 8px 0 4px; }
    .refresh-btn { background: none; border: 1px solid #26304f; color: #9aa7c7; cursor: pointer; padding: 4px 8px; border-radius: 6px; font-size: 11px; }
    .refresh-btn:hover { background: #1e2a4a; color: #e8ecf8; }
  </style>
</head>
<body>
  <!-- Sidebar: Session History -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <h2>📋 会话历史</h2>
      <button class="refresh-btn" onclick="loadSessions()" title="刷新列表">⟳</button>
    </div>
    <div class="sidebar-filters">
      <select id="filterAgent" onchange="loadSessions()">
        <option value="">全部 Agent</option>
        <option value="hermes_demo">Hermes 演示</option>
        <option value="hermes_research">Hermes 研究</option>
        <option value="claude_code">Claude Code</option>
      </select>
      <select id="filterStatus" onchange="loadSessions()">
        <option value="">全部状态</option>
        <option value="running">运行中</option>
        <option value="completed">已完成</option>
        <option value="failed">失败</option>
        <option value="cancelled">已取消</option>
        <option value="pending">待处理</option>
      </select>
      <input id="filterVersion" placeholder="版本过滤 (如 V7.2)" oninput="loadSessions()" style="width:100%;"/>
    </div>
    <div class="sidebar-list" id="sessionList"><div style="padding:16px;color:#9aa7c7;font-size:12px;">加载中...</div></div>
  </aside>

  <!-- Main -->
  <div class="main">
    <header>
      <h1>Hermes Agent Console</h1>
      <a href="/" style="color:#9aa7c7;font-size:12px;">← Dashboard</a>
    </header>
    <div class="container">
      <div class="toolbar">
        <select id="agentSelect">
          <option value="hermes_demo">Hermes Agent (演示)</option>
          <option value="hermes_research">Hermes Agent (研究)</option>
          <option value="claude_code">Claude Code</option>
        </select>
        <span id="streamHint" style="font-size:12px;color:#9aa7c7;"></span>
        <button id="startBtn" onclick="startSession()">▶ 开始</button>
        <button id="cancelBtn" onclick="cancelSession()" disabled>⏹ 取消</button>
        <span id="sessionStatus" class="status-badge status-pending">就绪</span>
      </div>
      <div class="prompt-area">
        <textarea id="promptInput" placeholder="输入投研或开发任务...&#10;例如：分析 ret5 因子在 2026 年的表现"></textarea>
      </div>
      <div class="answer-meta" id="answerMeta"></div>
      <div id="answerArea" class="answer-area">等待输入...</div>
      <span class="toggle-diagnostic" onclick="toggleDiagnostic()">📋 显示诊断信息</span>
      <div id="diagnosticArea" class="diagnostic-area"></div>
    </div>
  </div>

<script>
const ADAPTER_INFO = {
  'hermes_demo':     {label:'Hermes Agent (演示)', streaming:'buffered', hint:'缓冲模式 — 非逐 token'},
  'hermes_research': {label:'Hermes Agent (研究)', streaming:'buffered', hint:'运行投研命令'},
  'claude_code':     {label:'Claude Code',      streaming:'buffered', hint:'缓冲模式 — 命令完成后输出'},
};
const STATUS_LABELS = {running:'运行中',completed:'已完成',failed:'失败',cancelled:'已取消',pending:'待处理',orphaned:'孤儿'};

let currentSession = null;
let eventSource = null;

// ─── Filter / Session List ──────────────────────────────────────

function loadSessions(){
  const agent = document.getElementById('filterAgent').value;
  const status = document.getElementById('filterStatus').value;
  const version = document.getElementById('filterVersion').value.trim();
  let url = '/api/agent-console/sessions-list?limit=100';
  if (agent) url += '&agent=' + encodeURIComponent(agent);
  if (status) url += '&status=' + encodeURIComponent(status);
  if (version) url += '&version=' + encodeURIComponent(version);
  fetch(url)
    .then(r => r.json())
    .then(data => renderSessionList(data.sessions || []))
    .catch(() => document.getElementById('sessionList').innerHTML = '<div style="padding:16px;color:#ff8ba0;">加载失败</div>');
}

function renderSessionList(sessions){
  const el = document.getElementById('sessionList');
  if (!sessions.length) {
    el.innerHTML = '<div style="padding:16px;color:#9aa7c7;font-size:12px;">暂无会话</div>';
    return;
  }
  el.innerHTML = sessions.map(s => {
    const active = s.session_id === currentSession ? 'active' : '';
    const statusC = 'status-' + (s.status || 'pending');
    const preview = (s.answer_preview || '(无回答)').substring(0, 80);
    const artifact = s.has_artifact ? '<span style="color:#7df0bd;font-size:10px;">📄</span>' : '';
    return `<div class="session-item ${active}" onclick="loadSession('${s.session_id}')">
      <div class="si-agent">${STATUS_LABELS[s.status] || s.status} · ${s.agent || '?'} ${artifact}</div>
      <div class="si-prompt">${esc(s.prompt || '')}</div>
      <div class="si-meta">
        <span class="si-version">${s.version || '—'}</span>
        <span class="pill">${s.events_count || 0} events</span>
        <span class="status-badge ${statusC}">${s.status}</span>
      </div>
    </div>`;
  }).join('');
}

function esc(v){ return String(v ?? '').replace(/[&<>]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[s])); }

// ─── Load a specific session ────────────────────────────────────

function loadSession(sid){
  if (eventSource) { eventSource.close(); eventSource = null; }
  currentSession = sid;
  document.getElementById('answerArea').textContent = '加载中...';
  document.getElementById('diagnosticArea').textContent = '';
  document.getElementById('diagnosticArea').classList.remove('show');
  loadSessions(); // refresh active highlight
  // Fetch session details
  fetch('/api/agent-console/sessions/' + sid)
    .then(r => r.json())
    .then(s => {
      document.getElementById('answerMeta').innerHTML =
        `<span class="status-badge status-${s.status}">${STATUS_LABELS[s.status] || s.status}</span>` +
        `<span class="pill">${esc(s.agent)}</span>` +
        `<span class="pill">${esc(s.version)}</span>` +
        `<span class="pill">${s.duration || '—'}</span>` +
        (s.git_commit ? `<span class="pill">${esc(s.git_commit)}</span>` : '') +
        `<a class="artifact-link" href="/api/agent-console/sessions/${sid}" target="_blank">📋 JSON</a>`;
      const answer = s.answer || '(无回答)';
      document.getElementById('answerArea').textContent = answer;
      const diag = (s.diagnostics || []).join('\n');
      const diagEl = document.getElementById('diagnosticArea');
      if (diag) {
        diagEl.textContent = diag;
        diagEl.classList.add('show');
      } else {
        diagEl.classList.remove('show');
      }
      document.getElementById('startBtn').disabled = false;
      document.getElementById('cancelBtn').disabled = s.status !== 'running';
    })
    .catch(e => { document.getElementById('answerArea').textContent = '加载失败: ' + e; });
}

// ─── Start / SSE / Cancel ───────────────────────────────────────

document.getElementById('agentSelect').addEventListener('change', function(){
  document.getElementById('streamHint').textContent = (ADAPTER_INFO[this.value] || {}).hint || '';
});

function startSession(){
  const agent = document.getElementById('agentSelect').value;
  const info = ADAPTER_INFO[agent] || {};
  const prompt = document.getElementById('promptInput').value.trim();
  if (!prompt) { alert('请输入任务描述'); return; }
  document.getElementById('answerArea').textContent = '正在启动 ' + (info.label || agent) + '...';
  document.getElementById('diagnosticArea').textContent = '';
  document.getElementById('diagnosticArea').classList.remove('show');
  document.getElementById('answerMeta').innerHTML = '';
  document.getElementById('startBtn').disabled = true;
  document.getElementById('cancelBtn').disabled = false;

  fetch('/api/agent-console/sessions?agent=' + encodeURIComponent(agent) + '&prompt=' + encodeURIComponent(prompt), {method: 'POST'})
    .then(r => r.json())
    .then(data => {
      currentSession = data.session_id;
      setStatus('running');
      connectSSE(data.session_id);
      loadSessions();
    })
    .catch(e => { setStatus('failed'); document.getElementById('answerArea').textContent = '启动失败: ' + e; });
}

function connectSSE(sid){
  if (eventSource) eventSource.close();
  document.getElementById('answerArea').textContent = '';
  const es = new EventSource('/api/agent-console/sessions/' + sid + '/stream');
  eventSource = es;
  es.addEventListener('message', function(ev){
    try {
      const d = JSON.parse(ev.data);
      if (d.type === 'answer_delta') {
        const el = document.getElementById('answerArea');
        el.textContent += d.data;
        el.scrollTop = el.scrollHeight;
      } else if (d.type === 'diagnostic') {
        const el = document.getElementById('diagnosticArea');
        el.textContent += d.data + '\n';
      } else if (d.type === 'error') {
        const el = document.getElementById('answerArea');
        el.textContent += '\n[错误] ' + d.data;
      } else if (d.type === 'done') {
        setStatus(d.status || 'completed');
        document.getElementById('startBtn').disabled = false;
        document.getElementById('cancelBtn').disabled = true;
        es.close();
        eventSource = null;
        loadSessions(); // refresh session list
      }
    } catch(e) {}
  });
  es.onerror = function(){
    es.close();
    eventSource = null;
    document.getElementById('startBtn').disabled = false;
    document.getElementById('cancelBtn').disabled = true;
  };
}

function cancelSession(){
  if (!currentSession) return;
  fetch('/api/agent-console/sessions/' + currentSession + '/cancel', {method: 'POST'})
    .then(r => r.json())
    .then(d => { setStatus('cancelled'); document.getElementById('startBtn').disabled = false; document.getElementById('cancelBtn').disabled = true; loadSessions(); });
}

function setStatus(s){
  const el = document.getElementById('sessionStatus');
  el.className = 'status-badge status-' + s;
  el.textContent = STATUS_LABELS[s] || s;
}

function toggleDiagnostic(){
  document.getElementById('diagnosticArea').classList.toggle('show');
}

// ─── Init ───────────────────────────────────────────────────────
document.getElementById('agentSelect').dispatchEvent(new Event('change'));
loadSessions();
setInterval(loadSessions, 15000);
</script>
</body>
</html>
"""
