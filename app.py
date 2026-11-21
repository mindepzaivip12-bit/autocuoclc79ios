import eventlet
eventlet.monkey_patch()

import os, json, time, base64, hashlib, logging, threading, re
import requests
from functools import wraps
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO
from socketio import Client as SocketClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet',
                    ping_timeout=60, ping_interval=25)

# ==========================================
# CẤU HÌNH
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://apibetvipbominh.onrender.com/lc79md5"
GAME_WS_URL     = "https://wtxmd52.tele68.com"
GAME_WS_PATH    = "txmd5/"
GAME_WS_NS      = "/txmd5"
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

LICENSE_SERVER_URL = os.environ.get("LICENSE_SERVER_URL", "https://lc79vipadmin-5orx.onrender.com").rstrip("/")
LICENSE_API_KEY   = os.environ.get("LICENSE_API_KEY", "").strip()
LICENSE_CACHE_TTL = 30

_LICENSE_CACHE = {}
_LICENSE_CACHE_LOCK = threading.Lock()

GLOBAL_HISTORY = []
MAX_GLOBAL_HISTORY = 2000
GLOBAL_HISTORY_LOCK = threading.Lock()

WEB_SESSIONS = {}
WS_CLIENTS   = {}

API_LAST_RAW = {"data": None, "ts": 0, "error": None}

# ==========================================
# 🔑 LICENSE CLIENT
# ==========================================
def _license_headers():
    h = {"Content-Type": "application/json", "Cache-Control": "no-store", "User-Agent": "BotClient/1.0"}
    if LICENSE_API_KEY:
        h["X-Api-Key"] = LICENSE_API_KEY
        h["Authorization"] = f"Bearer {LICENSE_API_KEY}"
    return h

def _now_ts(): return int(time.time())

def _cache_get(key):
    with _LICENSE_CACHE_LOCK:
        item = _LICENSE_CACHE.get(key)
    if not item or _now_ts() - item["ts"] > LICENSE_CACHE_TTL: return None
    return item["data"]

def _cache_set(key, data):
    with _LICENSE_CACHE_LOCK:
        _LICENSE_CACHE[key] = {"data": data, "ts": _now_ts()}

def _cache_clear(key=None):
    with _LICENSE_CACHE_LOCK:
        if key: _LICENSE_CACHE.pop(key, None)
        else: _LICENSE_CACHE.clear()

def license_check(key, fingerprint=None):
    key = (key or "").strip().upper()
    if not key: return {"ok": False, "valid": False, "message": "Thiếu key", "code": "NO_KEY"}
    if not LICENSE_SERVER_URL: return {"ok": False, "valid": False, "message": "Chưa cấu hình server key", "code": "SERVER_NOT_CONFIGURED"}

    cache_key = f"{key}|{fingerprint or '-'}"
    cached = _cache_get(cache_key)
    if cached: return cached

    try:
        params = {"key": key}
        if fingerprint: params["fingerprint"] = fingerprint
        r = requests.get(f"{LICENSE_SERVER_URL}/api/license/check", params=params, headers=_license_headers(), timeout=6)
        if r.status_code == 404:
            res = {"ok": False, "valid": False, "message": "Key không tồn tại", "code": "NOT_FOUND"}
        else:
            r.raise_for_status()
            res = r.json() if r.text.strip().startswith("{") else {"raw": r.text}
            res.setdefault("ok", True)
    except requests.exceptions.Timeout:
        return {"ok": False, "valid": False, "message": "Server key timeout", "code": "TIMEOUT"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "valid": False, "message": "Không kết nối được server key", "code": "CONN_ERROR"}
    except Exception as e:
        return {"ok": False, "valid": False, "message": f"Lỗi server key: {type(e).__name__}", "code": "SERVER_ERROR"}

    _cache_set(cache_key, res)
    return res

def license_activate(key, fingerprint, ip=None, ua=None):
    key = (key or "").strip().upper()
    if not key: return {"ok": False, "success": False, "message": "Thiếu key", "code": "NO_KEY"}
    if not LICENSE_SERVER_URL: return {"ok": False, "success": False, "message": "Chưa cấu hình server key", "code": "SERVER_NOT_CONFIGURED"}

    payload = {"key": key, "fingerprint": fingerprint, "ip": ip, "ua": ua}
    try:
        r = requests.post(f"{LICENSE_SERVER_URL}/api/license/activate", json=payload, headers=_license_headers(), timeout=8)
        data = r.json() if r.text.strip().startswith("{") else {}
        if r.status_code in (200, 201):
            data.setdefault("ok", True); data.setdefault("success", True); _cache_clear(); return data
        else:
            data.setdefault("ok", False); data.setdefault("success", False)
            data.setdefault("message", data.get("error") or f"HTTP {r.status_code}")
            return data
    except Exception as e:
        return {"ok": False, "success": False, "message": f"Lỗi server key: {type(e).__name__}", "code": "SERVER_ERROR"}

def license_heartbeat(key, fingerprint):
    if not LICENSE_SERVER_URL: return False
    try:
        requests.post(f"{LICENSE_SERVER_URL}/api/license/heartbeat", json={"key": key, "fingerprint": fingerprint, "ts": _now_ts()}, headers=_license_headers(), timeout=4)
        return True
    except: return False

def _is_license_valid(res):
    if not isinstance(res, dict) or not res.get("ok", False) or res.get("revoked") or res.get("expired") or res.get("valid") is False: return False
    left = res.get("time_left")
    if isinstance(left, (int, float)) and left <= 0: return False
    return True

def _license_msg(res):
    if not isinstance(res, dict): return "Key không hợp lệ"
    return res.get("message") or res.get("error") or "Key không hợp lệ"

def _license_time_left(res):
    if not isinstance(res, dict): return 0
    if isinstance(res.get("time_left"), (int, float)): return max(0, int(res["time_left"]))
    exp = res.get("expires_at")
    if isinstance(exp, (int, float)): return max(0, int(exp) - _now_ts())
    return 0

def _client_ip(): return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown")
def _client_ua(): return request.headers.get("User-Agent", "unknown")
def _device_fingerprint(ip, ua): return hashlib.sha256(f"{ip or 'unknown'}|{ua or 'unknown'}".encode()).hexdigest()[:32]

def require_license(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        sid = session.get("sid")
        if not sid or sid not in WEB_SESSIONS: return jsonify({"success": False, "error": "Chưa đăng nhập", "code": "NO_SESSION"}), 401
        st = WEB_SESSIONS[sid]
        key = st.get("license_key"); fp = st.get("license_fp")
        if not key: return jsonify({"success": False, "error": "Chưa kích hoạt key", "code": "NO_KEY"}), 401
        res = license_check(key, fp)
        if not _is_license_valid(res):
            _force_logout(sid, reason="KEY_EXPIRED")
            return jsonify({"success": False, "error": _license_msg(res), "code": res.get("code") or "KEY_EXPIRED"}), 403
        return f(*args, **kwargs)
    return wrapper

def _force_logout(sid, reason="MANUAL"):
    if sid in WS_CLIENTS:
        try: WS_CLIENTS[sid].disconnect()
        except: pass
        WS_CLIENTS.pop(sid, None)
    WEB_SESSIONS.pop(sid, None)
    try: socketio.emit("force_logout", {"reason": reason}, to=sid)
    except: pass

def license_watchdog_worker():
    while True:
        try:
            if LICENSE_SERVER_URL:
                for sid, st in list(WEB_SESSIONS.items()):
                    key = st.get("license_key"); fp = st.get("license_fp")
                    if not key: continue
                    _cache_clear(f"{key}|{fp or '-'}")
                    res = license_check(key, fp)
                    if not _is_license_valid(res):
                        socketio.emit("toast", {"type": "error", "msg": f"⛔ {_license_msg(res)} — đăng xuất"}, to=sid)
                        _force_logout(sid, reason="KEY_EXPIRED")
                        continue
                    license_heartbeat(key, fp)
        except Exception as e: logger.error(f"[License Watchdog] {e}")
        socketio.sleep(30)
socketio.start_background_task(license_watchdog_worker)

# ==========================================
# HÀM HỖ TRỢ GAME
# ==========================================
def normalize_side(value):
    if value is None: return None
    if isinstance(value, bool): return None
    if isinstance(value, (int, float)): return "TAI" if value == 1 else ("XIU" if value == 0 else None)
    s = str(value).strip().upper()
    if not s: return None
    if "XỈU" in s or "XIU" in s: return "XIU"
    if "TÀI" in s or "TAI" in s: return "TAI"
    if len(s) <= 3:
        if s.startswith("T"): return "TAI"
        if s.startswith("X"): return "XIU"
    if "HIGH" in s or "BIG" in s: return "TAI"
    if "LOW" in s or "SMALL" in s: return "XIU"
    return None

def fetch_api_raw():
    try:
        url = f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}"
        r = requests.get(url, timeout=5, headers={"Cache-Control": "no-store", "User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()
        API_LAST_RAW.update({"data": data, "ts": time.time(), "error": None})
        return data
    except Exception as e:
        API_LAST_RAW["error"] = str(e)
        return None

def api_data_worker():
    last_session_logged = None
    while True:
        data = fetch_api_raw()
        if data:
            session_id = data.get("phien"); result_str = data.get("ket_qua") or ""
            if session_id and result_str and session_id != last_session_logged:
                side = normalize_side(result_str)
                if side:
                    with GLOBAL_HISTORY_LOCK:
                        if not any(h["session"] == session_id for h in GLOBAL_HISTORY[-5:]):
                            GLOBAL_HISTORY.append({"session": session_id, "side": side, "ts": time.time()})
                            if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY: GLOBAL_HISTORY.pop(0)
                    last_session_logged = session_id
        socketio.sleep(1.5)
socketio.start_background_task(api_data_worker)

def get_prediction():
    now = time.time()
    data = API_LAST_RAW["data"] if API_LAST_RAW["data"] and (now - API_LAST_RAW["ts"]) < 1.5 else fetch_api_raw()
    if not data: return {"side": None, "conf": None, "ready": False, "api_session": None}
    du_doan = data.get("du_doan"); do_tin_cay = data.get("do_tin_cay")
    side_out = normalize_side(du_doan)
    return {"side": side_out, "conf": do_tin_cay, "ready": side_out is not None, "api_session": data.get("phien")}

def parse_result_side(result_raw):
    if not result_raw: return None
    side = normalize_side(result_raw)
    if side: return side
    nums = [int(x) for x in re.findall(r"\d+", str(result_raw))]
    if len(nums) >= 3: return "TAI" if sum(nums[:3]) >= 11 else "XIU"
    return None

def login_game(username, password):
    try:
        pw = hashlib.md5(password.encode()).hexdigest()
        url = f"{API_LOGIN_URL}?c=3&un={username}&pw={pw}&{COMMON_PARAMS}&at="
        sess = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://tele68.com", "Referer": "https://tele68.com/"}
        r = sess.get(url, timeout=12, headers=headers)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"): return {"_error": data.get("message", "Sai thông tin đăng nhập")}
        sk = data["sessionKey"] + "=" * ((4 - len(data["sessionKey"]) % 4) % 4)
        sk_data = json.loads(base64.b64decode(sk).decode("utf-8"))
        nickname = sk_data.get("nickname") or sk_data.get("nickName")
        r2 = sess.post(f"{API_LOBBY_URL}?{COMMON_PARAMS}&at=", headers={"content-type": "application/json", **headers}, json={"nickName": nickname, "accessToken": data["accessToken"]}, timeout=12)
        lobby = r2.json()
        jwt = lobby.get("token")
        if not jwt: return {"_error": "Lobby không trả về token"}
        money = lobby.get("remoteLoginResp", {}).get("money", 0)
        return {"token": jwt, "nickname": nickname, "money": money}
    except Exception as e: return {"_error": f"Lỗi kết nối: {e}"}

def calc_next_bet(st):
    base = int(st["base_bet_amount"])
    if st.get("x2_mode") and st["win_streak"] > 0: return base * min(2 ** st["win_streak"], 32)
    if st.get("x2_loss_mode") and st["loss_streak"] > 0:
        if st["loss_streak"] <= int(st.get("x2_loss_limit", 5)): return base * min(2 ** st["loss_streak"], 32)
    return base

# ==========================================
# 🚀 GAME SOCKET WORKER (FIX TRIỆT ĐỂ LỖI OFF)
# ==========================================
def game_socket_worker(sid, jwt_token):
    st = WEB_SESSIONS.get(sid)
    if not st: return

    # Xoá client cũ nếu có
    if sid in WS_CLIENTS:
        try: WS_CLIENTS[sid].disconnect()
        except: pass
        del WS_CLIENTS[sid]

    # Cấu hình reconnect chặt chẽ
    sio = SocketClient(
        reconnection=True, 
        reconnection_attempts=0, # 0 = vô hạn
        reconnection_delay=2, 
        reconnection_delay_max=10,
        logger=False, 
        engineio_logger=False
    )
    WS_CLIENTS[sid] = sio

    def check_target_profit():
        if (st["auto_bet_enabled"] and st["target_profit"] and st["profit_loss"] >= st["target_profit"]):
            st["auto_bet_enabled"] = False
            socketio.emit("toast", {"type": "success", "msg": f"🏆 CHỐT LÃI! +{st['profit_loss']:,}đ"}, to=sid)
            socketio.emit("stats_update", public_state(st), to=sid)
            return True
        return False

    @sio.event(namespace=GAME_WS_NS)
    def connect():
        logger.info(f"[{sid}] ✅ Game socket CONNECTED")
        st["socket_connected"] = True
        socketio.emit("stats_update", public_state(st), to=sid)
        socketio.emit("toast", {"type": "success", "msg": "Game: Đã kết nối"}, to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def connect_error(data):
        logger.error(f"[{sid}] ❌ Game socket CONNECT ERROR: {data}")
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def disconnect():
        logger.warning(f"[{sid}] ❌ Game socket DISCONNECTED. Reconnecting...")
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        st["session_id"] = data.get("id") or data.get("sessionId") or "N/A"
        st["has_bet_this_session"] = False
        st["current_bet_type"] = None; st["current_bet_session"] = None; st["current_prediction"] = None
        if check_target_profit(): return
        pred = get_prediction(); api_session = pred.get("api_session"); pred_side = pred["side"]
        if pred_side and api_session:
            try: diff = int(st["session_id"]) - int(api_session)
            except: diff = 0
            if diff not in (0, 1): pred_side = None; api_session = None
        st["current_prediction"] = pred_side; st["current_pred_session"] = api_session
        st["current_bet"] = calc_next_bet(st) if st["auto_bet_enabled"] else int(st["base_bet_amount"])
        socketio.emit("session_update", {"session_id": st["session_id"], "prediction": pred_side, "conf": pred["conf"], "ready": pred["ready"] and pred_side is not None, "history_len": len(GLOBAL_HISTORY), "current_bet": st["current_bet"]}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick_update(data):
        if data.get("state") != "BETTING" or not st["auto_bet_enabled"] or st["has_bet_this_session"] or not st["session_id"]: return
        pred_raw = st.get("current_prediction"); bet_type = normalize_side(pred_raw)
        if not bet_type: return
        pred_session = st.get("current_pred_session")
        if pred_session and str(pred_session) != str(st["session_id"]):
            new_pred = get_prediction(); new_side = new_pred["side"]; new_sess = new_pred["api_session"]
            if new_side and new_sess:
                try: diff = int(st["session_id"]) - int(new_sess)
                except: diff = 999
                if diff in (0, 1): bet_type = new_side; st["current_prediction"] = new_side; st["current_pred_session"] = new_sess
                else: return
            else: return
        try:
            sio.emit("bet", {"type": bet_type, "amount": int(st["current_bet"])}, namespace=GAME_WS_NS)
            st["has_bet_this_session"] = True; st["waiting_for_result"] = True
            st["current_bet_type"] = bet_type; st["current_bet_session"] = st["session_id"]
            socketio.emit("toast", {"type": "info", "msg": f"🚀 Cược {st['current_bet']:,}đ vào {bet_type}"}, to=sid)
        except: pass

    @sio.on("bet-result", namespace=GAME_WS_NS)
    def on_bet_result(data):
        if "postBalance" in data: st["balance"] = data["postBalance"]; socketio.emit("stats_update", public_state(st), to=sid)
        try: sio.emit("get-current-my-info", None, namespace=GAME_WS_NS)
        except: pass

    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_session_result(data):
        result_raw = data.get("resultTruyenThong") or data.get("result") or data.get("resultString")
        dices = data.get("dices") or data.get("dice") or []
        sess = data.get("id") or st.get("session_id")
        if st.get("last_result_session") == str(sess): return
        st["last_result_session"] = str(sess)
        result_side = parse_result_side(result_raw); is_win = None; profit_delta = 0
        bet_type = st.get("current_bet_type"); bet_sess = st.get("current_bet_session")
        if st.get("waiting_for_result") and bet_type and result_side and str(sess) == str(bet_sess):
            is_win = (bet_type == result_side); amt = int(st["current_bet"])
            if is_win:
                profit_delta = int(amt * 0.98); st["win_streak"] += 1; st["loss_streak"] = 0; st["win_count"] += 1
            else:
                profit_delta = -amt; st["win_streak"] = 0; st["loss_streak"] += 1; st["lose_count"] += 1
            st["profit_loss"] += profit_delta; st["waiting_for_result"] = False
        st["history"].insert(0, {"session": sess, "pred": bet_type, "bet": st["current_bet"] if is_win is not None else 0, "result": result_side or result_raw, "dice": dices, "win": is_win})
        st["history"] = st["history"][:30]
        socketio.emit("result_update", {"session": sess, "pred": bet_type, "result": result_side or result_raw, "is_win": is_win, "balance": st["balance"], "profit_loss": st["profit_loss"], "history": st["history"][:15]}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)
        check_target_profit()

    try:
        logger.info(f"[{sid}] Đang kết nối tới Game Socket: {GAME_WS_URL}...")
        connect_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://tele68.com",
            "Referer": "https://tele68.com/",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"
        }
        
        # Tham số truyền vào được tinh chỉnh để fix lỗi handshake
        sio.connect(
            f"{GAME_WS_URL}?token={jwt_token}",
            socketio_path=GAME_WS_PATH,
            namespaces=[GAME_WS_NS],
            headers=connect_headers,
            transports=['websocket'], # Ép buộc dùng websocket, tránh polling lỗi
            wait_timeout=20
        )
        sio.wait()
    except Exception as e:
        logger.error(f"[{sid}] ❌ SOCKET FATAL ERROR: {type(e).__name__} - {e}")
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)
        socketio.emit("toast", {"type": "error", "msg": f"Lỗi Socket: {type(e).__name__}"}, to=sid)

# ==========================================
# PUBLIC STATE & WORKER
# ==========================================
def public_state(st):
    return {
        "nickname": st["nickname"], "balance": st["balance"], "profit_loss": st["profit_loss"],
        "auto_bet_enabled": st["auto_bet_enabled"], "base_bet_amount": st["base_bet_amount"],
        "current_bet": st["current_bet"], "target_profit": st["target_profit"],
        "current_prediction": st["current_prediction"], "session_id": st["session_id"],
        "win_count": st["win_count"], "lose_count": st["lose_count"], "win_streak": st["win_streak"],
        "loss_streak": st["loss_streak"], "socket_connected": st["socket_connected"], "history": st["history"][:15],
    }

def stats_broadcast_worker():
    while True:
        try:
            for sid, st in list(WEB_SESSIONS.items()):
                try: socketio.emit("stats_update", public_state(st), to=sid)
                except: pass
        except: pass
        socketio.sleep(5)
socketio.start_background_task(stats_broadcast_worker)

# ==========================================
# ROUTES
# ==========================================
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    key = (data.get("key") or "").strip().upper()

    if not username or not password: return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})
    if not key: return jsonify({"success": False, "error": "Vui lòng nhập KEY truy cập", "code": "NO_KEY"})

    if LICENSE_SERVER_URL:
        ip, ua = _client_ip(), _client_ua()
        fp = _device_fingerprint(ip, ua)
        act_res = license_activate(key, fp, ip=ip, ua=ua)
        if not act_res.get("success", False):
            chk = license_check(key, fp)
            if not _is_license_valid(chk):
                return jsonify({"success": False, "error": _license_msg(act_res) or _license_msg(chk), "code": "KEY_INVALID"}), 403
        chk = license_check(key, fp)
        if not _is_license_valid(chk):
            return jsonify({"success": False, "error": _license_msg(chk), "code": "KEY_EXPIRED"}), 403
        expires = chk.get("expires_at"); left = _license_time_left(chk)
    else:
        fp = "no_license"; expires = int(time.time()) + 86400*30; left = 86400*30

    res = login_game(username, password)
    if "_error" in res: return jsonify({"success": False, "error": res["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    WEB_SESSIONS[sid] = {
        "nickname": res["nickname"], "balance": res["money"], "token": res["token"],
        "username": username, "license_key": key, "license_fp": fp,
        "profit_loss": 0, "auto_bet_enabled": False, "base_bet_amount": 10000, "current_bet": 10000,
        "current_prediction": None, "current_bet_type": None, "current_bet_session": None,
        "waiting_for_result": False, "has_bet_this_session": False, "session_id": None,
        "win_count": 0, "lose_count": 0, "win_streak": 0, "loss_streak": 0,
        "socket_connected": False, "history": []
    }

    socketio.start_background_task(game_socket_worker, sid, res["token"])

    return jsonify({
        "success": True, "sid": sid, "nickname": res["nickname"], "balance": res["money"],
        "license_key": key, "license_expires_at": expires, "license_time_left": left
    })

@app.route("/api/config", methods=["POST"])
@require_license
def api_config():
    sid = session.get("sid"); st = WEB_SESSIONS[sid]; data = request.json or {}
    
    if "reset_history" in data and data["reset_history"]:
        st["history"] = []; st["win_count"] = 0; st["lose_count"] = 0
        st["profit_loss"] = 0; st["win_streak"] = 0; st["loss_streak"] = 0
    if "betAmount" in data: st["base_bet_amount"] = st["current_bet"] = int(data["betAmount"])
    if "auto_bet_enabled" in data:
        st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
        st["has_bet_this_session"] = not st["auto_bet_enabled"]
    
    socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True, "state": public_state(st)})

@app.route("/api/stats")
@require_license
def api_stats(): return jsonify({"success": True, "state": public_state(WEB_SESSIONS[session.get("sid")])})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    if sid in WS_CLIENTS:
        try: WS_CLIENTS[sid].disconnect()
        except: pass
        WS_CLIENTS.pop(sid, None)
    WEB_SESSIONS.pop(sid, None); session.pop("sid", None)
    return jsonify({"success": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
