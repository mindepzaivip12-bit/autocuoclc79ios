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
# CẤU HÌNH GAME
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://leminhlcdz.onrender.com/lc79md5"
API_ADMIN_URL   = os.environ.get("ADMIN_API_URL", "https://lc79vipadmin-5orx.onrender.com").rstrip("/")
GAME_WS_URL     = "https://wtxmd52.tele68.com"
GAME_WS_PATH    = "txmd5/"
GAME_WS_NS      = "/txmd5"
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

# ==========================================
# 📌 LICENSE SERVER CONFIG
# ==========================================
LICENSE_SERVER_URL = os.environ.get(
    "LICENSE_SERVER_URL",
    "https://lc79vipadmin-5orx.onrender.com"   # ← ĐÃ ĐỔI SANG SERVER ADMIN CỦA BẠN
).rstrip("/")
LICENSE_API_KEY   = os.environ.get("LICENSE_API_KEY", "").strip()
LICENSE_CACHE_TTL = 30

if LICENSE_SERVER_URL and not LICENSE_SERVER_URL.startswith(("http://", "https://")):
    logger.error(f"[License] ❌ URL không hợp lệ: {LICENSE_SERVER_URL!r}")
    LICENSE_SERVER_URL = ""

if not LICENSE_SERVER_URL:
    logger.warning("[License] ⚠️ LICENSE_SERVER_URL chưa cấu hình")
else:
    logger.info(f"[License] ✅ License server: {LICENSE_SERVER_URL}")

_LICENSE_CACHE = {}
_LICENSE_CACHE_LOCK = threading.Lock()

# ==========================================
# GLOBAL DATA
# ==========================================
GLOBAL_HISTORY = []
MAX_GLOBAL_HISTORY = 2000
GLOBAL_HISTORY_LOCK = threading.Lock()

WEB_SESSIONS = {}
WS_CLIENTS   = {}

API_LAST_RAW   = {"data": None, "ts": 0, "error": None}
ADMIN_LAST_RAW = {"data": None, "ts": 0, "error": None, "last_push_ts": 0}

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
    if not item or _now_ts() - item["ts"] > LICENSE_CACHE_TTL:
        return None
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
    if not LICENSE_SERVER_URL: return {"ok": False, "valid": False, "message": "Server key chưa cấu hình", "code": "SERVER_NOT_CONFIGURED"}

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
        return {"ok": False, "valid": False, "message": f"Lỗi: {type(e).__name__}", "code": "SERVER_ERROR"}

    _cache_set(cache_key, res)
    return res

def license_activate(key, fingerprint, ip=None, ua=None):
    key = (key or "").strip().upper()
    if not key: return {"ok": False, "success": False, "message": "Thiếu key", "code": "NO_KEY"}
    if not LICENSE_SERVER_URL: return {"ok": False, "success": False, "message": "Server key chưa cấu hình", "code": "SERVER_NOT_CONFIGURED"}

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
        return {"ok": False, "success": False, "message": f"Lỗi: {type(e).__name__}", "code": "SERVER_ERROR"}

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
    st = WEB_SESSIONS.get(sid)
    if st: push_telemetry_to_admin("force_logout", sid=sid, st=st, extra={"reason": reason})
    if sid in WS_CLIENTS:
        try: WS_CLIENTS[sid].disconnect()
        except: pass
        WS_CLIENTS.pop(sid, None)
    WEB_SESSIONS.pop(sid, None)
    try: socketio.emit("force_logout", {"reason": reason}, to=sid)
    except: pass

# ==========================================
# WORKERS
# ==========================================
def license_watchdog_worker():
    logger.info("[License Watchdog] started")
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

def normalize_side(value):
    if value is None or isinstance(value, bool): return None
    if isinstance(value, (int, float)): return "TAI" if value == 1 else ("XIU" if value == 0 else None)
    s = str(value).strip().upper()
    if "XỈU" in s or "XIU" in s: return "XIU"
    if "TÀI" in s or "TAI" in s: return "TAI"
    if len(s) <= 3:
        if s.startswith("T"): return "TAI"
        if s.startswith("X"): return "XIU"
    return None

def _admin_headers():
    h = {"Cache-Control": "no-store", "User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    ak = os.environ.get("ADMIN_API_KEY", "").strip()
    if ak: h["Authorization"] = f"Bearer {ak}"; h["X-Admin-Key"] = ak
    return h

def fetch_admin_config(username=None, sid=None):
    for ep in ["/api/config", "/api/bot/config", "/config", "/"]:
        try:
            params = {"_t": int(time.time() * 1000)}
            if username: params["username"] = username
            if sid: params["sid"] = sid
            r = requests.get(f"{API_ADMIN_URL}{ep}", params=params, timeout=5, headers=_admin_headers())
            if r.status_code == 404: continue
            r.raise_for_status()
            data = r.json() if r.text.strip().startswith("{") else {}
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            ADMIN_LAST_RAW.update({"data": payload, "ts": time.time(), "error": None})
            return payload
        except Exception as e: ADMIN_LAST_RAW["error"] = str(e)
    return ADMIN_LAST_RAW.get("data")

def apply_admin_config_to_session(st, sid, admin_cfg):
    if not isinstance(admin_cfg, dict): return False
    changed = False
    if "betAmount" in admin_cfg or "base_bet_amount" in admin_cfg:
        try:
            new_amt = int(admin_cfg.get("betAmount", admin_cfg.get("base_bet_amount")))
            if new_amt >= 1000 and new_amt != st["base_bet_amount"]:
                st["base_bet_amount"] = new_amt
                if not st.get("has_bet_this_session"): st["current_bet"] = new_amt
                changed = True
        except: pass
    if "auto_bet_enabled" in admin_cfg:
        na = bool(admin_cfg["auto_bet_enabled"])
        if na != st["auto_bet_enabled"]: st["auto_bet_enabled"] = na; st["has_bet_this_session"] = not na; changed = True
    if "target_profit" in admin_cfg:
        tp = admin_cfg["target_profit"]; ntp = int(tp) if tp not in (None, "", 0) else None
        if ntp != st["target_profit"]: st["target_profit"] = ntp; changed = True
    return changed

def push_telemetry_to_admin(event_name="heartbeat", sid=None, st=None, extra=None):
    payload = {"event": event_name, "ts": int(time.time()), "sid": sid, "history_len": len(GLOBAL_HISTORY)}
    if st: payload.update({"nickname": st.get("nickname"), "balance": st.get("balance"), "profit_loss": st.get("profit_loss"), "auto_bet_enabled": st.get("auto_bet_enabled"), "current_bet": st.get("current_bet"), "session_id": st.get("session_id"), "win_count": st.get("win_count"), "lose_count": st.get("lose_count")})
    if extra: payload["extra"] = extra
    for ep in ["/api/telemetry", "/api/bot/report", "/api/sync"]:
        try:
            if requests.post(f"{API_ADMIN_URL}{ep}", json=payload, timeout=4, headers=_admin_headers()).status_code in (200, 201, 202, 204):
                return True
        except: continue
    return False

def fetch_api_raw():
    try:
        r = requests.get(f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}", timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()
        API_LAST_RAW.update({"data": data, "ts": time.time(), "error": None})
        return data
    except Exception as e:
        API_LAST_RAW["error"] = str(e)
        return None

def api_data_worker():
    last_logged = None
    while True:
        data = fetch_api_raw()
        if data and data.get("phien") and data.get("ket_qua") and data.get("phien") != last_logged:
            side = normalize_side(data.get("ket_qua"))
            if side:
                with GLOBAL_HISTORY_LOCK:
                    if not any(h["session"] == data["phien"] for h in GLOBAL_HISTORY[-5:]):
                        GLOBAL_HISTORY.append({"session": data["phien"], "side": side, "ts": time.time()})
                        if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY: GLOBAL_HISTORY.pop(0)
                last_logged = data["phien"]
        socketio.sleep(1.5)
socketio.start_background_task(api_data_worker)

def get_prediction():
    data = fetch_api_raw() if not API_LAST_RAW["data"] or (time.time() - API_LAST_RAW["ts"]) > 1.5 else API_LAST_RAW["data"]
    if not data: return {"side": None, "conf": None, "ready": False, "api_ok": False, "api_session": None, "raw": None}
    side = normalize_side(data.get("du_doan"))
    return {"side": side, "conf": data.get("do_tin_cay"), "ready": side is not None, "api_ok": True, "api_session": data.get("phien"), "raw": data}

def parse_result_side(raw):
    if not raw: return None
    side = normalize_side(raw)
    if side: return side
    nums = [int(x) for x in re.findall(r"\d+", str(raw))]
    return "TAI" if len(nums) >= 3 and sum(nums[:3]) >= 11 else ("XIU" if len(nums) >= 3 else None)

def login_game(u, p):
    try:
        r = requests.get(f"{API_LOGIN_URL}?c=3&un={u}&pw={hashlib.md5(p.encode()).hexdigest()}&{COMMON_PARAMS}&at=", timeout=12, headers={"User-Agent": "Mozilla/5.0", "Origin": "https://tele68.com"})
        r.raise_for_status()
        d = r.json()
        if not d.get("success"): return {"_error": d.get("message", "Sai tài khoản")}
        sk = d["sessionKey"] + "=" * ((4 - len(d["sessionKey"]) % 4) % 4)
        nick = json.loads(base64.b64decode(sk).decode("utf-8")).get("nickname") or json.loads(base64.b64decode(sk).decode("utf-8")).get("nickName")
        r2 = requests.post(f"{API_LOBBY_URL}?{COMMON_PARAMS}&at=", json={"nickName": nick, "accessToken": d["accessToken"]}, timeout=12, headers={"content-type": "application/json"})
        lobby = r2.json()
        return {"token": lobby["token"], "nickname": nick, "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e: return {"_error": f"Lỗi: {e}"}

def calc_next_bet(st):
    base = int(st["base_bet_amount"])
    if st.get("x2_mode") and st["win_streak"] > 0: return base * min(2 ** st["win_streak"], 32)
    if st.get("x2_loss_mode") and st["loss_streak"] > 0 and st["loss_streak"] <= int(st.get("x2_loss_limit", 5)): return base * min(2 ** st["loss_streak"], 32)
    return base

def public_state(st):
    lic = license_check(st.get("license_key"), st.get("license_fp")) if st.get("license_key") else None
    return {
        "nickname": st["nickname"], "balance": st["balance"], "profit_loss": st["profit_loss"],
        "auto_bet_enabled": st["auto_bet_enabled"], "base_bet_amount": st["base_bet_amount"],
        "current_bet": st["current_bet"], "target_profit": st["target_profit"],
        "current_prediction": st["current_prediction"], "session_id": st["session_id"],
        "win_count": st["win_count"], "lose_count": st["lose_count"], "socket_connected": st["socket_connected"],
        "license_expires_at": (lic or {}).get("expires_at"), "license_time_left": _license_time_left(lic or {}),
        "history": st["history"][:15],
    }

def game_socket_worker(sid, jwt):
    st = WEB_SESSIONS.get(sid)
    if not st: return
    sio = SocketClient(reconnection=True, logger=False)
    WS_CLIENTS[sid] = sio

    @sio.event(namespace=GAME_WS_NS)
    def connect(): st["socket_connected"] = True; socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        st.update({"session_id": data.get("id"), "has_bet_this_session": False})
        pred = get_prediction()
        st["current_prediction"] = pred["side"]
        socketio.emit("session_update", {"session_id": st["session_id"], "prediction": pred["side"], "conf": pred["conf"], "ready": pred["ready"], "history_len": len(GLOBAL_HISTORY), "current_bet": st["current_bet"]}, to=sid)

    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick(data):
        if data.get("state") == "BETTING" and st["auto_bet_enabled"] and not st["has_bet_this_session"] and st["current_prediction"]:
            bet_type = normalize_side(st["current_prediction"])
            if bet_type:
                sio.emit("bet", {"type": bet_type, "amount": int(st["current_bet"])}, namespace=GAME_WS_NS)
                st.update({"has_bet_this_session": True, "waiting_for_result": True, "current_bet_type": bet_type, "current_bet_session": st["session_id"]})

    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_result(data):
        res_side = parse_result_side(data.get("resultTruyenThong") or data.get("result"))
        is_win = None
        if st.get("waiting_for_result") and st.get("current_bet_type") == res_side:
            is_win = True
            st["profit_loss"] += int(st["current_bet"] * 0.98)
            st["win_count"] += 1
        elif st.get("waiting_for_result"):
            is_win = False
            st["profit_loss"] -= int(st["current_bet"])
            st["lose_count"] += 1
        st["waiting_for_result"] = False
        st["history"].insert(0, {"session": data.get("id"), "pred": st["current_bet_type"], "bet": st["current_bet"], "result": res_side, "dice": data.get("dices"), "win": is_win})
        socketio.emit("result_update", {"session": data.get("id"), "pred": st["current_bet_type"], "result": res_side, "is_win": is_win, "balance": st["balance"], "profit_loss": st["profit_loss"], "history": st["history"]}, to=sid)

    try:
        sio.connect(f"{GAME_WS_URL}?token={jwt}", socketio_path=GAME_WS_PATH, namespaces=[GAME_WS_NS], transports=["websocket"], wait_timeout=15)
        sio.wait()
    except Exception as e:
        logger.error(f"[{sid}] Socket fail: {e}")
        st["socket_connected"] = False

# ==========================================
# ROUTES
# ==========================================
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    u, p, key = (data.get("username") or "").strip(), (data.get("password") or "").strip(), (data.get("key") or "").strip().upper()
    if not u or not p: return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})
    if not key: return jsonify({"success": False, "error": "Vui lòng nhập KEY", "code": "NO_KEY"})
    if not LICENSE_SERVER_URL: return jsonify({"success": False, "error": "Server key chưa cấu hình", "code": "SERVER_NOT_CONFIGURED"}), 503

    ip, ua = _client_ip(), _client_ua()
    fp = _device_fingerprint(ip, ua)

    # ✅ TEST: Bỏ qua license server để test login game trước (Nếu bạn muốn xài thật thì xoá khối if True này)
    if False: 
        act_res = license_activate(key, fp, ip=ip, ua=ua)
        if not act_res.get("success", False):
            chk = license_check(key, fp)
            if not _is_license_valid(chk):
                return jsonify({"success": False, "error": _license_msg(act_res) or _license_msg(chk), "code": act_res.get("code") or "KEY_INVALID"}), 403
    
    chk = {"expires_at": int(time.time()) + 86400*30, "time_left": 86400*30}  # Fake license data
    
    r = login_game(u, p)
    if "_error" in r: return jsonify({"success": False, "error": r["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    session["license_key"] = key
    session["license_fp"] = fp

    WEB_SESSIONS[sid] = {
        "nickname": r["nickname"], "balance": r["money"], "token": r["token"], "username": u,
        "license_key": key, "license_fp": fp, "profit_loss": 0, "auto_bet_enabled": False,
        "x2_mode": False, "x2_loss_mode": False, "x2_loss_limit": 5, "win_streak": 0, "loss_streak": 0,
        "base_bet_amount": 10000, "current_bet": 10000, "target_profit": None, "current_prediction": None,
        "current_bet_type": None, "current_bet_session": None, "waiting_for_result": False,
        "has_bet_this_session": False, "session_id": None, "win_count": 0, "lose_count": 0,
        "socket_connected": False, "history": []
    }

    socketio.start_background_task(game_socket_worker, sid, r["token"])

    return jsonify({
        "success": True, "sid": sid, "nickname": r["nickname"], "balance": r["money"],
        "license_key": key, "license_expires_at": chk.get("expires_at"), "license_time_left": _license_time_left(chk)
    })

@app.route("/api/stats")
@require_license
def api_stats(): return jsonify({"success": True, "state": public_state(WEB_SESSIONS[session.get("sid")])})

@app.route("/api/config", methods=["POST"])
@require_license
def api_config():
    sid = session.get("sid"); st = WEB_SESSIONS[sid]; data = request.json or {}
    if "betAmount" in data and int(data["betAmount"]) >= 1000:
        st["base_bet_amount"] = st["current_bet"] = int(data["betAmount"])
    if "auto_bet_enabled" in data:
        st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
        st["has_bet_this_session"] = not st["auto_bet_enabled"]
    if "target_profit" in data:
        st["target_profit"] = int(data["target_profit"]) if data["target_profit"] else None
    socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True, "state": public_state(st)})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    if sid in WS_CLIENTS: WS_CLIENTS[sid].disconnect()
    WEB_SESSIONS.pop(sid, None); session.clear()
    return jsonify({"success": True})

@app.route("/api/debug_license")
def debug_license():
    return jsonify({"url": LICENSE_SERVER_URL, "configured": bool(LICENSE_SERVER_URL), "ping": requests.get(LICENSE_SERVER_URL, timeout=5).status_code if LICENSE_SERVER_URL else 0})

@socketio.on("connect")
def on_connect(): pass

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
