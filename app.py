<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TOOL AUTO LC79</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{box-sizing:border-box;margin:0;padding:0;font-family:'Inter',sans-serif}

/* ===== NỀN TỐI + XANH DƯƠNG NHẠT ===== */
body{
  background:linear-gradient(135deg,#0a0f1e 0%,#0f172a 50%,#0b1220 100%);
  min-height:100vh;display:flex;justify-content:center;align-items:center;
  padding:20px;color:#cbd5e1; overflow-x: hidden;
}
body::before{
  content:'';position:fixed;top:-20%;left:-20%;width:60%;height:60%;
  background:radial-gradient(circle,rgba(96,165,250,0.12) 0%,transparent 70%);
  pointer-events:none;z-index:0;
}
body::after{
  content:'';position:fixed;bottom:-20%;right:-20%;width:60%;height:60%;
  background:radial-gradient(circle,rgba(147,197,253,0.08) 0%,transparent 70%);
  pointer-events:none;z-index:0;
}

/* ===== LOGIN ===== */
.login-container{
  position:relative;z-index:1;
  background:#111827;width:100%;max-width:400px;border-radius:16px;padding:30px;
  box-shadow:0 10px 40px rgba(0,0,0,.6),0 0 0 1px rgba(96,165,250,0.15);
  border:1px solid rgba(96,165,250,0.1);
}
.login-container h2{
  text-align:center;color:#93c5fd;margin-bottom:20px;
  text-shadow:0 0 20px rgba(96,165,250,.3);
}
.form-group{margin-bottom:15px}
.form-group label{display:block;font-size:13px;font-weight:600;margin-bottom:5px;color:#94a3b8}
.form-group input{
  width:100%;padding:12px;background:#0b1220;color:#e2e8f0;
  border:1px solid #1e293b;border-radius:8px;outline:none;transition:.2s;
}
.form-group input::placeholder{color:#475569}
.form-group input:focus{border-color:#60a5fa;box-shadow:0 0 0 3px rgba(96,165,250,.15)}
.btn-login{
  width:100%;padding:12px;background:linear-gradient(135deg,#3b82f6,#60a5fa);
  color:#fff;border:none;border-radius:8px;font-weight:700;cursor:pointer;
  transition:.2s;box-shadow:0 4px 14px rgba(59,130,246,.3); margin-bottom: 15px;
}
.btn-login:hover{background:linear-gradient(135deg,#2563eb,#3b82f6);transform:translateY(-1px);box-shadow:0 6px 20px rgba(59,130,246,.45)}
.btn-login:disabled{opacity:.6;cursor:not-allowed;transform:none}
.tele-support {
  text-align: center; font-size: 13px; color: #94a3b8; margin-top: 10px;
}
.tele-support a {
  color: #60a5fa; text-decoration: none; font-weight: 700; transition: .2s;
  background: rgba(96,165,250,.1); padding: 4px 8px; border-radius: 6px; border: 1px solid rgba(96,165,250,.2);
}
.tele-support a:hover { background: rgba(96,165,250,.2); color: #93c5fd; }

/* ===== MAIN ===== */
.main-wrapper{display:none;width:100%;max-width:900px;flex-direction:column;gap:15px;position:relative;z-index:1}
.top-header{
  background:#111827;border-radius:12px;padding:15px 25px;
  display:flex;justify-content:space-between;align-items:center;
  box-shadow:0 4px 20px rgba(0,0,0,.4);border:1px solid rgba(96,165,250,0.12);
}
.logo-text h1{
  font-size:20px;color:#dbeafe;font-weight:800;letter-spacing:.5px;margin-bottom:4px;
  text-shadow:0 0 20px rgba(96,165,250,.25);
}
.logo-text p{font-size:13px;color:#64748b}
.menu-icon {
  font-size: 22px; color: #93c5fd; cursor: pointer; padding: 8px; transition: .2s;
}
.menu-icon:hover { color: #fff; transform: scale(1.1); }

.main-card{
  background:#111827;border-radius:16px;padding:25px;
  box-shadow:0 10px 40px rgba(0,0,0,.5);border:1px solid rgba(96,165,250,0.12);
}
.section-title{
  font-size:14px;color:#93c5fd;font-weight:600;display:flex;align-items:center;gap:8px;margin-bottom:20px;
}

/* ===== BADGES ===== */
.status-badges{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.badge{display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:20px;font-size:12px;font-weight:600}
.badge-online{background:rgba(16,185,129,.12);color:#34d399;border:1px solid rgba(16,185,129,.3)}
.badge-online.off{background:rgba(239,68,68,.12);color:#f87171;border-color:rgba(239,68,68,.3)}
.badge-auto{background:rgba(96,165,250,.12);color:#93c5fd;border:1px solid rgba(96,165,250,.3)}
.badge-auto.off{background:rgba(71,85,105,.3);color:#94a3b8;border-color:#334155}
.badge-bet{background:rgba(245,158,11,.12);color:#fbbf24;border:1px solid rgba(245,158,11,.3)}
.badge-bet.off{background:rgba(71,85,105,.3);color:#94a3b8;border-color:#334155}
.badge-bet.active{background:rgba(16,185,129,.15);color:#34d399;border-color:rgba(16,185,129,.4)}
.dot{width:6px;height:6px;border-radius:50%;background:#60a5fa}
.dot-green{background:#34d399;box-shadow:0 0 8px rgba(52,211,153,.6)}
.dot-red{background:#f87171;box-shadow:0 0 8px rgba(248,113,113,.6)}
.dot-gray{background:#64748b}
.dot-active{background:#34d399;box-shadow:0 0 8px rgba(52,211,153,.8)}

/* ===== PREDICTION BOX ===== */
.prediction-box{
  background:linear-gradient(135deg,#0b1220 0%,#0f172a 100%);
  border:1px solid rgba(96,165,250,0.2);border-radius:12px;padding:20px;
  display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;
  position:relative;overflow:hidden;transition:border-color .3s;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.03);
}
.prediction-box::before{
  content:'';position:absolute;top:0;left:0;width:100%;height:2px;
  background:linear-gradient(90deg,transparent,#60a5fa,transparent);opacity:.6;
}
.pred-left{display:flex;flex-direction:column;gap:5px;z-index:2}
.pred-label{font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.pred-value{
  font-size:32px;font-weight:800;color:#93c5fd;letter-spacing:1px;
  text-shadow:0 0 20px rgba(96,165,250,.4);transition:.3s;
}
.pred-value.val-tai{color:#60a5fa;text-shadow:0 0 24px rgba(96,165,250,.7)}
.pred-value.val-xiu{color:#f87171;text-shadow:0 0 24px rgba(248,113,113,.7)}
.pred-algo{
  font-size:11px;color:#93c5fd;background:rgba(96,165,250,.12);
  padding:2px 8px;border-radius:4px;display:inline-block;margin-top:4px;font-weight:600;
  border:1px solid rgba(96,165,250,.2);
}
.pred-percent{font-size:12px;color:#64748b;font-weight:500}
.pred-right{text-align:right;z-index:2}
.session-label{font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;margin-bottom:4px;display:block;letter-spacing:.5px}
.session-value{font-size:16px;font-weight:800;color:#e2e8f0;text-shadow:0 0 10px rgba(96,165,250,.2)}

/* ===== FLASH RESULT ===== */
.pred-result-flash{
  position:absolute;top:0;left:0;width:100%;height:100%;
  background:rgba(16,185,129,0.15);
  display:none;flex-direction:column;align-items:center;justify-content:center;
  font-size:26px;font-weight:800;z-index:10;animation:fadeIn 0.2s;
  backdrop-filter:blur(4px);
}
.pred-result-flash.lose{background:rgba(239,68,68,0.15)}
.pred-result-flash .text-win{color:#34d399;text-shadow:0 0 30px rgba(52,211,153,.8)}
.pred-result-flash .text-lose{color:#f87171;text-shadow:0 0 30px rgba(248,113,113,.8)}
.pred-result-flash small{font-size:14px;font-weight:600;color:#cbd5e1;margin-top:4px}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes pulse{0%{transform:scale(1)}50%{transform:scale(1.08)}100%{transform:scale(1)}}
.pred-result-flash .text-win, .pred-result-flash .text-lose{animation:pulse 0.5s ease}

/* ===== INFO GRID ===== */
.info-grid{
  display:grid;grid-template-columns:1fr 1fr;
  border:1px solid rgba(96,165,250,0.15);border-radius:12px;margin-bottom:20px;overflow:hidden;
  background:#0b1220;
}
.info-item{padding:15px 20px;border-bottom:1px solid rgba(96,165,250,0.1)}
.info-item:nth-child(odd){border-right:1px solid rgba(96,165,250,0.1)}
.info-item:nth-last-child(-n+2){border-bottom:none}
.info-label{font-size:11px;color:#64748b;font-weight:600;text-transform:uppercase;margin-bottom:6px;display:block;letter-spacing:.5px}
.info-value{font-size:15px;font-weight:700;color:#e2e8f0}
.info-item[style*="f8fafc"]{background:rgba(96,165,250,.05)!important; border-left: 2px solid #60a5fa;}

/* ===== BUTTONS ===== */
.action-buttons{display:flex;gap:12px;margin-bottom:25px;flex-wrap:wrap}
.btn-action{
  flex: 1; padding:12px 20px;border:none;border-radius:8px;font-size:14px;font-weight:700;
  cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;color:#fff;transition:.2s;
}
.btn-toggle-auto{background:linear-gradient(135deg,#10b981,#34d399);box-shadow:0 4px 14px rgba(16,185,129,.3)}
.btn-toggle-auto.off{background:linear-gradient(135deg,#3b82f6,#60a5fa);box-shadow:0 4px 14px rgba(59,130,246,.3)}
.btn-stop-bot{background:linear-gradient(135deg,#ef4444,#f87171);box-shadow:0 4px 14px rgba(239,68,68,.3)}
.btn-action:hover{transform:translateY(-2px);filter:brightness(1.1)}

/* ===== TABLE ===== */
.table-title{font-size:13px;color:#93c5fd;font-weight:600;text-transform:uppercase;margin-bottom:15px;letter-spacing:.5px; display: flex; justify-content: space-between;}
.table-wrapper{overflow-x:auto;border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{
  text-align:left;padding:12px 10px;color:#94a3b8;font-weight:600;
  border-bottom:1px solid rgba(96,165,250,0.15);font-size:11px;text-transform:uppercase;
  background:rgba(96,165,250,.04);letter-spacing:.5px;
}
td{padding:12px 10px;border-bottom:1px solid #1e293b;font-weight:600;color:#cbd5e1}
tr:hover td{background:rgba(96,165,250,.04)}
.val-tai{color:#60a5fa;text-shadow:0 0 8px rgba(96,165,250,.4)}
.val-xiu{color:#f87171;text-shadow:0 0 8px rgba(248,113,113,.4)}
.val-win{color:#34d399;text-shadow:0 0 8px rgba(52,211,153,.4)}
.val-lose{color:#f87171;text-shadow:0 0 8px rgba(248,113,113,.4)}

/* ===== SIDEBAR MENU 3 GẠCH ===== */
.sidebar {
  position: fixed; top: 0; right: -320px; width: 300px; height: 100vh;
  background: #111827; z-index: 1000; transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  padding: 25px 20px; box-shadow: -10px 0 30px rgba(0,0,0,0.5);
  border-left: 1px solid rgba(96,165,250,0.2); display: flex; flex-direction: column;
}
.sidebar.active { right: 0; }
.sidebar-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #1e293b;
}
.sidebar-header h3 { font-size: 15px; color: #93c5fd; font-weight: 700; letter-spacing: .5px;}
.sidebar-header .close-btn { font-size: 20px; color: #64748b; cursor: pointer; transition: .2s; }
.sidebar-header .close-btn:hover { color: #f87171; }

/* Box thống kê trong sidebar */
.sidebar-stats {
  background: #0b1220; border-radius: 12px; padding: 15px; margin-bottom: 25px;
  border: 1px solid rgba(96,165,250,0.15);
}
.sidebar-item { display: flex; justify-content: space-between; margin-bottom: 12px; align-items: center; }
.sidebar-item:last-child { margin-bottom: 0; }
.sidebar-item .label { font-size: 12px; color: #94a3b8; font-weight: 500; }
.sidebar-item .value { font-size: 14px; font-weight: 700; color: #e2e8f0; }
.sidebar-item.profit .value { color: #34d399; text-shadow: 0 0 10px rgba(52,211,153,.4); }
.sidebar-item.loss .value { color: #f87171; text-shadow: 0 0 10px rgba(248,113,113,.4); }

/* Form trong sidebar */
.sidebar-form { margin-bottom: 25px; }
.sidebar-form label { font-size: 12px; font-weight: 600; color: #94a3b8; display: block; margin-bottom: 8px; }
.sidebar-form input {
  width: 100%; padding: 12px; background: #0b1220; color: #e2e8f0;
  border: 1px solid #1e293b; border-radius: 8px; outline: none; transition: .2s; font-size: 14px;
}
.sidebar-form input:focus { border-color: #60a5fa; box-shadow: 0 0 0 3px rgba(96,165,250,.15); }
.sidebar-hint { font-size: 11px; color: #475569; margin-top: 6px; display: block; }

.overlay {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.6); backdrop-filter: blur(3px); z-index: 999;
  display: none; opacity: 0; transition: opacity 0.3s;
}
.overlay.active { display: block; opacity: 1; }

/* ===== TOAST ===== */
.toast-wrap{position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:320px}
.toast{
  padding:12px 16px;border-radius:8px;color:#fff;font-weight:600;font-size:13px;
  box-shadow:0 8px 24px rgba(0,0,0,.5);animation:slideIn .3s;backdrop-filter:blur(8px);
}
.toast.success{background:linear-gradient(135deg,rgba(16,185,129,.9),rgba(52,211,153,.9));border:1px solid rgba(52,211,153,.5)}
.toast.error{background:linear-gradient(135deg,rgba(239,68,68,.9),rgba(248,113,113,.9));border:1px solid rgba(248,113,113,.5)}
.toast.info{background:linear-gradient(135deg,rgba(59,130,246,.9),rgba(96,165,250,.9));border:1px solid rgba(96,165,250,.5)}
@keyframes slideIn{from{transform:translateX(400px);opacity:0}to{transform:translateX(0);opacity:1}}

/* ===== SPINNER ===== */
.spinner{
  display:inline-block;width:12px;height:12px;border:2px solid #fff;
  border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;
  vertical-align:middle;margin-right:6px;
}
@keyframes spin{to{transform:rotate(360deg)}}

/* ===== ANIMATIONS ===== */
.balance-update{animation:flashBalance 0.5s ease}
@keyframes flashBalance{0%{background:rgba(52,211,153,.25)}100%{background:transparent}}
.saved-indicator{display:inline-block;font-size:10px;color:#34d399;font-weight:600;margin-left:6px;opacity:0;transition:opacity .3s}
.saved-indicator.show{opacity:1}

/* ===== SCROLLBAR ===== */
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:#0b1220}
::-webkit-scrollbar-thumb{background:#1e293b;border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:#334155}
</style>
</head>
<body>

<div class="toast-wrap" id="toasts"></div>

<!-- SIDEBAR MENU (3 GẠCH) -->
<div class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <h3><i class="fa-solid fa-gear"></i> CÀI ĐẶT & THỐNG KÊ</h3>
    <i class="fa-solid fa-xmark close-btn" id="close-sidebar"></i>
  </div>
  
  <div class="sidebar-stats">
    <div class="sidebar-item">
      <span class="label">Số dư hiện tại:</span>
      <span class="value" id="sidebar-balance">0</span>
    </div>
    <div class="sidebar-item profit">
      <span class="label">Số dư chốt lãi:</span>
      <span class="value" id="sidebar-profit">+0</span>
    </div>
    <div class="sidebar-item loss">
      <span class="label">Số dư thua lỗ:</span>
      <span class="value" id="sidebar-loss">-0</span>
    </div>
  </div>

  <div class="sidebar-form">
    <label><i class="fa-solid fa-money-bill-wave"></i> Mức cược cố định (VNĐ)</label>
    <input type="number" id="sidebar-betAmount" value="10000" min="1000" step="1000" onchange="onSidebarConfigChange()">
    <span class="saved-indicator" id="savedSidebarBet">✓ Đã lưu</span>
    <span class="sidebar-hint">*Áp dụng cho phiên cược tiếp theo.</span>
  </div>
</div>
<div class="overlay" id="overlay"></div>

<!-- LOGIN -->
<div class="login-container" id="loginView">
  <h2>ĐĂNG NHẬP HỆ THỐNG</h2>
  <div class="form-group">
    <label>Tài khoản</label>
    <input type="text" id="username" placeholder="Nhập tài khoản game...">
  </div>
  <div class="form-group">
    <label>Mật khẩu</label>
    <input type="password" id="password" placeholder="Nhập mật khẩu..." onkeydown="if(event.key==='Enter')handleLogin()">
  </div>
  <button class="btn-login" id="btnLogin" onclick="handleLogin()">ĐĂNG NHẬP</button>
  
  <div class="tele-support">
    Hỗ trợ mua Key: <a href="https://t.me/cskhleminh" target="_blank"><i class="fa-brands fa-telegram"></i> @cskhleminh</a>
  </div>
</div>

<!-- MAIN -->
<div class="main-wrapper" id="mainView">
  <div class="top-header">
    <div class="logo-text">
      <h1>TOOL AUTO LC79</h1>
      <p>Hệ thống phân tích cầu & dự đoán Tài Xỉu tự động</p>
    </div>
    <i class="fa-solid fa-bars menu-icon" id="open-sidebar"></i>
  </div>

  <div class="main-card">
    <div class="section-title"><span>📊</span> BẢNG ĐIỀU KHIỂN</div>

    <div class="status-badges">
      <div class="badge badge-online off" id="socketBadge"><div class="dot dot-gray" id="socketDot"></div> Socket: OFF</div>
      <div class="badge badge-auto off" id="autoStatusBadge"><div class="dot dot-gray"></div> AUTO: OFF</div>
      <div class="badge badge-bet off" id="betStatusBadge"><div class="dot dot-gray"></div> CƯỢC: CHỜ</div>
    </div>

    <!-- KHUNG DỰ ĐOÁN AI -->
    <div class="prediction-box" id="predictionBox">
      <div class="pred-result-flash" id="predResultFlash"></div>
      <div class="pred-left">
        <span class="pred-label">DỰ ĐOÁN PHIÊN HIỆN TẠI</span>
        <div class="pred-value" id="predValue">—</div>
        <div class="pred-algo">Thuật toán LE MINH</div>
        <div class="pred-percent" id="predPercent">(Đang chờ dữ liệu...)</div>
      </div>
      <div class="pred-right">
        <span class="session-label">PHIÊN</span>
        <span class="session-value" id="sessionValue">#—</span>
      </div>
    </div>

    <!-- KHU VỰC THÔNG TIN & CHỐT LÃI -->
    <div class="info-grid">
      <div class="info-item"><span class="info-label">NICKNAME</span><div class="info-value" id="nicknameDisplay">—</div></div>
      <div class="info-item"><span class="info-label">SỐ DƯ</span><div class="info-value" id="balanceDisplay">0</div></div>
      <div class="info-item"><span class="info-label">CƯỢC PHIÊN</span><div class="info-value" id="betDisplay">0</div></div>
      <div class="info-item" style="background: #f8fafc;"><span class="info-label">LỢI NHUẬN (CHỐT LÃI)</span><div class="info-value" id="plDisplay" style="font-size: 18px;">0</div></div>
      <div class="info-item"><span class="info-label">WIN / LOSE</span><div class="info-value"><span class="val-win" id="winCount">0</span> / <span class="val-lose" id="loseCount">0</span></div></div>
      <div class="info-item"><span class="info-label">TRẠNG THÁI AUTO</span><div class="info-value" id="statusText">Chờ kết nối...</div></div>
    </div>

    <div class="action-buttons">
      <button class="btn-action btn-toggle-auto off" id="btnToggleAuto" onclick="toggleAuto()"><span>▶</span> BẬT AUTO</button>
      <button class="btn-action btn-stop-bot" onclick="stopBot()"><span></span> NGẮT BOT</button>
    </div>

    <div class="table-title">LỊCH SỬ CƯỢC</div>
    <div class="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>PHIÊN</th><th>DỰ ĐOÁN</th><th>CƯỢC</th>
            <th>KẾT QUẢ</th><th>XÚC XẮC</th><th>THẮNG / THUA</th>
          </tr>
        </thead>
        <tbody id="historyBody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
let socket = null;
let autoOn = false;
let curState = null;
let lastBalance = 0;
let saveTimer = null;
let lastProcessedSession = 0;

const STORAGE_KEY_BALANCE = 'lc79_balance';
const STORAGE_KEY_CONFIG  = 'lc79_config';

function saveBalance(b){ try{ localStorage.setItem(STORAGE_KEY_BALANCE, JSON.stringify({balance:b,timestamp:Date.now()})); }catch(e){} }
function loadBalance(){ try{ const r=localStorage.getItem(STORAGE_KEY_BALANCE); if(!r)return null; const d=JSON.parse(r); if(Date.now()-d.timestamp<864e5)return d.balance; localStorage.removeItem(STORAGE_KEY_BALANCE); }catch(e){} return null; }

function loadConfig(){ try{ const r=localStorage.getItem(STORAGE_KEY_CONFIG); return r?JSON.parse(r):null; }catch(e){ return null; } }
function saveConfig(cfg){ try{ localStorage.setItem(STORAGE_KEY_CONFIG, JSON.stringify({...cfg,timestamp:Date.now()})); }catch(e){} }
function applyConfigToInputs(cfg){
  if(!cfg)return;
  if(cfg.betAmount!==undefined) document.getElementById('sidebar-betAmount').value = cfg.betAmount;
}
function readConfigFromInputs(){
  return {
    betAmount: parseInt(document.getElementById('sidebar-betAmount').value) || 10000,
    x2Limit: 5, // Mặc định ẩn đi
    targetProfit: 0 // Mặc định ẩn đi
  };
}

function showSavedIndicator(id){
  const el=document.getElementById(id); if(!el)return;
  el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),1500);
}

// XỬ LÝ KHI THAY ĐỔI CƯỢC Ở SIDEBAR
function onSidebarConfigChange(){
  const cfg=readConfigFromInputs();
  saveConfig(cfg);
  showSavedIndicator('savedSidebarBet');
  clearTimeout(saveTimer);
  saveTimer=setTimeout(()=>pushConfigToServer(cfg),500);
}

async function pushConfigToServer(cfg){
  try{
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        auto_bet_enabled:autoOn,
        betAmount:cfg.betAmount,
        x2_loss_mode:true,
        x2_loss_limit:cfg.x2Limit,
        target_profit:cfg.targetProfit||null
      })});
    toast('💾 Đã lưu mức cược mới','success');
  }catch(e){ toast('Lỗi lưu cài đặt: '+e.message,'error'); }
}

// HIỆU ỨNG THẮNG THUA
function showResultFlash(isWin, result, pred, dice, bet){
  const flash=document.getElementById('predResultFlash');
  const box=document.getElementById('predictionBox');
  if(isWin){
    flash.innerHTML=`<div class="text-win">✓ THẮNG</div>
      <small>Phiên trước: ${pred?pred.toUpperCase():'—'} → ${result||'—'}</small>`;
    flash.className='pred-result-flash';
    playSound('win');
    box.style.borderColor='#34d399';
  }else{
    flash.innerHTML=`<div class="text-lose">✗ THUA</div>
      <small>Phiên trước: ${pred?pred.toUpperCase():'—'} → ${result||'—'}</small>`;
    flash.className='pred-result-flash lose';
    playSound('lose');
    box.style.borderColor='#f87171';
  }
  flash.style.display='flex';
  clearTimeout(showResultFlash._t);
  showResultFlash._t=setTimeout(()=>{
    flash.style.display='none';
    box.style.borderColor='rgba(96,165,250,0.2)';
  },4000);
}

let audioCtx=null;
function playSound(type){
  try{
    if(!audioCtx) audioCtx=new (window.AudioContext||window.webkitAudioContext)();
    const osc=audioCtx.createOscillator(); const gain=audioCtx.createGain();
    osc.connect(gain); gain.connect(audioCtx.destination);
    if(type==='win'){
      osc.frequency.setValueAtTime(880,audioCtx.currentTime);
      osc.frequency.setValueAtTime(1320,audioCtx.currentTime+0.1);
      gain.gain.setValueAtTime(0.15,audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001,audioCtx.currentTime+0.3);
      osc.start(); osc.stop(audioCtx.currentTime+0.3);
    }else{
      osc.frequency.setValueAtTime(220,audioCtx.currentTime);
      osc.frequency.setValueAtTime(165,audioCtx.currentTime+0.15);
      gain.gain.setValueAtTime(0.15,audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001,audioCtx.currentTime+0.3);
      osc.start(); osc.stop(audioCtx.currentTime+0.3);
    }
  }catch(e){}
}

function toast(msg,type='info'){
  const el=document.createElement('div');
  el.className='toast '+type; el.innerText=msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(()=>el.remove(),3500);
}

function updateBalanceUI(balance,animate=false){
  const el=document.getElementById('balanceDisplay');
  const sbEl=document.getElementById('sidebar-balance');
  const newVal=Number(balance).toLocaleString();
  
  if(el.innerText!==newVal){
    el.innerText=newVal;
    sbEl.innerText=newVal;
    if(animate){ el.classList.remove('balance-update'); void el.offsetWidth; el.classList.add('balance-update'); }
  }
  lastBalance=balance; saveBalance(balance);
}

let initialBalance = 0;
function updateProfitUI(profit){
  const pl=document.getElementById('plDisplay');
  pl.innerText=(profit>=0?'+':'')+Number(profit).toLocaleString();
  pl.style.color=profit>=0?'#34d399':'#f87171';
  
  // Cập nhật cả bên Sidebar
  const sbProfit = document.getElementById('sidebar-profit');
  const sbLoss = document.getElementById('sidebar-loss');
  if(profit >= 0){
    sbProfit.innerText = '+' + Number(profit).toLocaleString();
    sbLoss.innerText = '-0';
  } else {
    sbProfit.innerText = '+0';
    sbLoss.innerText = Number(profit).toLocaleString();
  }
}

function updateBetBadge(betAmount){
  const badge=document.getElementById('betStatusBadge');
  if(betAmount>0){
    badge.className='badge badge-bet active';
    badge.innerHTML=`<div class="dot dot-active"></div> CƯỢC: ${Number(betAmount).toLocaleString()}`;
  }else{
    badge.className='badge badge-bet off';
    badge.innerHTML='<div class="dot dot-gray"></div> CƯỢC: CHỜ';
  }
}

function processResult(payload){
  if(!payload) return;
  if(payload.balance!==undefined) updateBalanceUI(payload.balance,true);
  if(payload.profit_loss!==undefined) updateProfitUI(payload.profit_loss);
  if(payload.history) renderHistory(payload.history);
  if(payload.session && payload.session !== lastProcessedSession &&
     payload.is_win !== null && payload.is_win !== undefined && payload.result){
    lastProcessedSession = payload.session;
    showResultFlash(payload.is_win, payload.result, payload.pred, payload.dice, payload.bet);
  }
}

async function handleLogin(){
  const u=document.getElementById('username').value.trim();
  const p=document.getElementById('password').value.trim();
  if(!u||!p) return toast('Nhập đủ tài khoản/mật khẩu','error');

  const btn=document.getElementById('btnLogin');
  btn.disabled=true;
  btn.innerHTML='<span class="spinner"></span> Đang đăng nhập...';

  try{
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
    const d=await r.json();
    if(!d.success){
      toast(d.error||'Lỗi đăng nhập','error');
      btn.disabled=false; btn.innerText='ĐĂNG NHẬP'; return;
    }
    document.getElementById('loginView').style.display='none';
    document.getElementById('mainView').style.display='flex';
    document.getElementById('nicknameDisplay').innerText=d.nickname;

    const cachedBalance=loadBalance();
    updateBalanceUI(cachedBalance!==null?cachedBalance:d.balance);

    const cachedCfg=loadConfig();
    if(cachedCfg){
      applyConfigToInputs(cachedCfg);
      toast('Đã khôi phục cược: '+cachedCfg.betAmount.toLocaleString(),'info');
      setTimeout(()=>pushConfigToServer(cachedCfg),300);
    }

    connectSocket();
    toast('Đăng nhập thành công!','success');
    setTimeout(pollStats,500);
  }catch(e){
    toast('Lỗi kết nối server: '+e.message,'error');
    btn.disabled=false; btn.innerText='ĐĂNG NHẬP';
  }
}

function connectSocket(){
  socket=io(window.location.origin,{transports:['websocket','polling']});

  socket.on('connect',()=>{
    document.getElementById('statusText').innerText='Đã kết nối Server';
    document.getElementById('statusText').style.color='#34d399';
  });
  socket.on('disconnect',()=>{
    document.getElementById('statusText').innerText='Mất kết nối Server';
    document.getElementById('statusText').style.color='#f87171';
  });

  socket.on('toast',d=>toast(d.msg,d.type));

  socket.on('session_update',d=>{
    document.getElementById('sessionValue').innerText='#'+d.session_id;
    if(d.prediction){
      const el=document.getElementById('predValue');
      el.innerText=d.prediction.toUpperCase();
      el.className='pred-value '+(d.prediction==='Tài'?'val-tai':'val-xiu');
      document.getElementById('predPercent').innerText = d.ready?`(Độ tin cậy: ${d.conf}%)`:`(Đang lấy dữ liệu: ${d.history_len}/12)`;
    }else{
      document.getElementById('predPercent').innerText=`(Đang lấy dữ liệu: ${d.history_len}/12)`;
    }
    const betVal=Number(d.current_bet||0);
    document.getElementById('betDisplay').innerText=betVal.toLocaleString();
    updateBetBadge(betVal);
  });

  socket.on('result_update',d=>processResult(d));

  socket.on('stats_update',s=>{
    applyState(s);
    if(Array.isArray(s.history) && s.history.length){
      const newest=s.history[0];
      if(newest && newest.session > lastProcessedSession &&
         newest.win !== null && newest.win !== undefined && newest.result){
        processResult({
          session:newest.session, pred:newest.pred, result:newest.result,
          is_win:newest.win, dice:newest.dice, bet:newest.bet,
          balance:s.balance, profit_loss:s.profit_loss, history:s.history
        });
      }
    }
  });
}

async function pollStats(){
  try{
    const r=await fetch('/api/stats');
    const d=await r.json();
    if(d.success){
      applyState(d.state);
      const s=d.state;
      if(Array.isArray(s.history) && s.history.length){
        const newest=s.history[0];
        if(newest && newest.session > lastProcessedSession &&
           newest.win !== null && newest.win !== undefined && newest.result){
          processResult({
            session:newest.session, pred:newest.pred, result:newest.result,
            is_win:newest.win, dice:newest.dice, bet:newest.bet,
            balance:s.balance, profit_loss:s.profit_loss, history:s.history
          });
        }
      }
    }
  }catch(e){}
}

function applyState(s){
  curState=s; autoOn=s.auto_bet_enabled;

  if(s.balance!==undefined) updateBalanceUI(s.balance,true);
  if(s.profit_loss!==undefined) updateProfitUI(s.profit_loss);

  document.getElementById('winCount').innerText=s.win_count;
  document.getElementById('loseCount').innerText=s.lose_count;

  const betVal=Number(s.current_bet||0);
  document.getElementById('betDisplay').innerText=betVal.toLocaleString();
  updateBetBadge(betVal);

  if(s.session_id) document.getElementById('sessionValue').innerText='#'+s.session_id;

  if(s.current_prediction){
    const el=document.getElementById('predValue');
    el.innerText=s.current_prediction.toUpperCase();
    el.className='pred-value '+(s.current_prediction==='Tài'?'val-tai':'val-xiu');
  }

  if(s.base_bet_amount!==undefined && !loadConfig()){
    const cfg={betAmount:s.base_bet_amount};
    applyConfigToInputs(cfg); saveConfig(cfg);
  }

  const sb=document.getElementById('socketBadge');
  if(s.socket_connected){ sb.className='badge badge-online'; sb.innerHTML='<div class="dot dot-green"></div> Socket: ON'; }
  else{ sb.className='badge badge-online off'; sb.innerHTML='<div class="dot dot-red"></div> Socket: OFF'; }

  const badge=document.getElementById('autoStatusBadge');
  const btn=document.getElementById('btnToggleAuto');
  const statusTxt=document.getElementById('statusText');

  if(autoOn){
    btn.innerHTML='<span></span> TẮT AUTO'; btn.classList.remove('off');
    badge.className='badge badge-auto';
    badge.innerHTML='<div class="dot dot-green"></div> AUTO: ĐANG CHẠY';
    statusTxt.innerText='Đang tự động đặt cược';
    statusTxt.style.color='#34d399';
  }else{
    btn.innerHTML='<span>▶</span> BẬT AUTO'; btn.classList.add('off');
    badge.className='badge badge-auto off';
    badge.innerHTML='<div class="dot dot-gray"></div> AUTO: ĐANG TẮT';
    statusTxt.innerText='Đang chờ lệnh';
    statusTxt.style.color='#64748b';
  }

  if(s.history) renderHistory(s.history);
}

function renderHistory(rows){
  const tb=document.getElementById('historyBody');
  tb.innerHTML='';
  if(!rows||!rows.length){
    tb.innerHTML='<tr><td colspan="6" style="text-align:center;color:#475569;padding:20px">Chưa có lịch sử</td></tr>';
    return;
  }
  rows.forEach(r=>{
    const tr=document.createElement('tr');
    const predClass=r.pred==='TÀI'?'val-tai':'val-xiu';
    const resClass=r.result==='TÀI'?'val-tai':'val-xiu';
    const wl=r.win===true?'<span class="val-win">THẮNG</span>'
            :r.win===false?'<span class="val-lose">THUA</span>':'—';
    const dice=Array.isArray(r.dice)?r.dice.slice(0,3).join(' - '):'—';
    tr.innerHTML=`
      <td>#${r.session}</td>
      <td class="${predClass}">${r.pred}</td>
      <td>${Number(r.bet).toLocaleString()}</td>
      <td class="${resClass}">${r.result}</td>
      <td>${dice}</td>
      <td>${wl}</td>`;
    tb.appendChild(tr);
  });
}

async function toggleAuto(){
  const cfg=readConfigFromInputs(); saveConfig(cfg);
  const newVal=!autoOn;
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      auto_bet_enabled:newVal,
      betAmount:cfg.betAmount,
      x2_loss_mode:true,
      x2_loss_limit:cfg.x2Limit,
      target_profit:cfg.targetProfit||null
    })});
  toast(newVal?'✅ Đã bật chế độ Auto Cược':'⏸ Đã tắt chế độ Auto Cược',newVal?'success':'info');
  pollStats();
}

async function stopBot(){
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({auto_bet_enabled:false})});
  autoOn=false; toast('Đã ngắt Bot khẩn cấp','error'); pollStats();
}

// LOGIC MỞ/ĐÓNG SIDEBAR
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('overlay');

document.getElementById('open-sidebar').addEventListener('click', () => {
    sidebar.classList.add('active');
    overlay.classList.add('active');
});

function closeSidebar() {
    sidebar.classList.remove('active');
    overlay.classList.remove('active');
}

document.getElementById('close-sidebar').addEventListener('click', closeSidebar);
overlay.addEventListener('click', closeSidebar);

setInterval(()=>{
  if(socket && socket.connected) pollStats();
}, 3000);

(function init(){
  const cfg=loadConfig();
  if(cfg) applyConfigToInputs(cfg);
})();
</script>
</body>
</html>
