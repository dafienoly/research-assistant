"""Agent Console Server — 前端页面 + 路由"""
CONSOLE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hermes Agent Console</title>
  <style>
    :root { color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #0b1020; color: #e8ecf8; }
    header { padding: 16px 24px; background: #111832; border-bottom: 1px solid #26304f; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
    h1 { margin: 0; font-size: 18px; flex: 1; }
    .container { padding: 20px; max-width: 1100px; margin: auto; }
    .toolbar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
    .toolbar select, .toolbar button, .toolbar input { padding: 8px 14px; border-radius: 8px; border: 1px solid #26304f; background: #121a35; color: #e8ecf8; font-size: 14px; }
    .toolbar select { min-width: 160px; }
    .toolbar button { cursor: pointer; }
    .toolbar button:hover { background: #1e2a4a; }
    .toolbar button:disabled { opacity: 0.5; cursor: default; }
    .prompt-area { margin-bottom: 12px; }
    .prompt-area textarea { width: 100%; min-height: 60px; background: #121a35; border: 1px solid #26304f; border-radius: 8px; color: #e8ecf8; padding: 10px; font-size: 13px; resize: vertical; box-sizing: border-box; }
    .answer-area { background: #121a35; border: 1px solid #26304f; border-radius: 8px; padding: 16px; min-height: 300px; white-space: pre-wrap; font-size: 14px; line-height: 1.6; overflow: auto; max-height: 600px; }
    .diagnostic-area { background: #080d1c; border: 1px solid #26304f; border-radius: 8px; padding: 10px; margin-top: 12px; font-size: 12px; line-height: 1.4; max-height: 200px; overflow: auto; display: none; }
    .diagnostic-area.show { display: block; }
    .status-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .status-pending { background: #44380c; color: #ffdc7a; }
    .status-running { background: #0f3d2e; color: #7df0bd; }
    .status-completed { background: #0f3d2e; color: #7df0bd; }
    .status-failed { background: #4a1620; color: #ff8ba0; }
    .status-cancelled { background: #44380c; color: #ffdc7a; }
    .toggle-diagnostic { font-size: 12px; color: #9aa7c7; cursor: pointer; margin-top: 8px; display: inline-block; }
    .toggle-diagnostic:hover { color: #cdd6f8; }
  </style>
</head>
<body>
  <header>
    <h1>Hermes Agent Console</h1>
    <a href="/" style="color:#9aa7c7;font-size:12px;">← 返回 Dashboard</a>
  </header>
  <div class="container">
    <div class="toolbar">
      <select id="agentSelect">
        <option value="hermes_demo">Hermes Agent (演示)</option>
        <option value="hermes_research">Hermes Agent (研究)</option>
        <option value="claude_code">Claude Code</option>
        </select>
        <span id="streamHint" style="font-size:12px;color:#9aa7c7;"></span>
        <button id="startBtn" onclick="startSession()">开始</button>
      <button id="cancelBtn" onclick="cancelSession()" disabled>取消</button>
      <span id="sessionStatus" class="status-badge status-pending">就绪</span>
    </div>
    <div class="prompt-area">
      <textarea id="promptInput" placeholder="输入投研或开发任务...&#10;例如：分析 ret5 因子在 2026 年的表现"></textarea>
    </div>
    <h3 style="margin:12px 0 6px;font-size:14px;color:#cdd6f8;">回答</h3>
    <div id="answerArea" class="answer-area">等待输入...</div>
    <span class="toggle-diagnostic" onclick="toggleDiagnostic()">📋 显示诊断信息</span>
    <div id="diagnosticArea" class="diagnostic-area"></div>
  </div>
<script>
const ADAPTER_INFO = {
  'hermes_demo':  {label:'Hermes Agent (演示)', streaming:'buffered', hint:'缓冲模式 — 非逐 token'},
  'hermes_research': {label:'Hermes Agent (研究)', streaming:'buffered', hint:'运行投研命令'},
  'claude_code':  {label:'Claude Code', streaming:'buffered', hint:'缓冲模式 — 命令完成后输出'}
};

document.getElementById('agentSelect').addEventListener('change', function(){
  const info = ADAPTER_INFO[this.value] || {hint:''};
  document.getElementById('streamHint').textContent = info.hint;
});

let currentSession = null;
let eventSource = null;

function startSession(){
  const agent = document.getElementById('agentSelect').value;
  const info = ADAPTER_INFO[agent] || {};
  const prompt = document.getElementById('promptInput').value.trim();
  if (!prompt) { alert('请输入任务描述'); return; }
  document.getElementById('answerArea').textContent = '正在启动 ' + (info.label || agent) + '...';
  document.getElementById('diagnosticArea').textContent = '';
  document.getElementById('diagnosticArea').classList.remove('show');
  document.getElementById('startBtn').disabled = true;
  document.getElementById('cancelBtn').disabled = false;

  fetch('/api/agent-console/sessions?agent=' + encodeURIComponent(agent) + '&prompt=' + encodeURIComponent(prompt), {method: 'POST'})
    .then(r => r.json())
    .then(data => {
      currentSession = data.session_id;
      setStatus('running');
      connectSSE(data.session_id);
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
    .then(d => { setStatus('cancelled'); document.getElementById('startBtn').disabled = false; document.getElementById('cancelBtn').disabled = true; });
}

function setStatus(s){
  const el = document.getElementById('sessionStatus');
  el.className = 'status-badge status-' + s;
  el.textContent = {running:'运行中',completed:'已完成',failed:'失败',cancelled:'已取消',pending:'就绪'}[s] || s;
}

function toggleDiagnostic(){
  const el = document.getElementById('diagnosticArea');
  el.classList.toggle('show');
}
</script>
</body>
</html>
"""
