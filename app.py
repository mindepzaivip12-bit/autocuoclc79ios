import eventlet
eventlet.monkey_patch()

import os, json, time, base64, hashlib, logging, threading
import requests
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO
from socketio import Client as SocketClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "lc79_minhdz_super_secret_2024")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet',
                    ping_timeout=60, ping_interval=25)

# ==========================================
# CẤU HÌNH GAME
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://apibetvipbominh.onrender.com/lc79md5"
GAME_WS_URL     = "https://wtxmd52.tele68.com"
GAME_WS_PATH    = "txmd5/"
GAME_WS_NS      = "/txmd5"
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

# ==========================================
# SERVER ADMIN
# ==========================================
ADMIN_BASE_URL = os.environ.get("ADMIN_BASE_URL", "https://lc79vipadmin-b8k2.onrender.com")
ADMIN_KEY_ENDPOINTS = [
    f"{ADMIN_BASE_URL}/api/check_key",
    f"{ADMIN_BASE_URL}/api/check-key",
]
ADMIN_API_TIMEOUT = 10
ADMIN_WORKING_ENDPOINT = None
ADMIN_ENDPOINT_LOCK = threading.Lock()

# ==========================================
# GLOBAL
# ==========================================
GLOBAL_HISTORY = []
MAX_GLOBAL_HISTORY = 2000
GLOBAL_HISTORY_LOCK = threading.Lock()

WEB_SESSIONS = {}        # sid -> state dict
WS_CLIENTS   = {}        # sid -> socketio.Client
SID_TO_NICK  = {}        # sid -> nickname

API_LAST_RAW = {"data": None, "ts": 0, "error": None}

# ==========================================
# HELPERS
# ==========================================
def normalize_side(value):
    if value is None: return None
    if isinstance(value, bool): return None
    if isinstance(value, (int, float)):
        if value == 1: return "TAI"
        if value == 0: return "XIU"
        return None
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

def get_sid_from_request():
    """Ưu tiên X-SID header, fallback về session."""
    sid = request.headers.get("X-SID", "").strip()
    if sid and sid in WEB_SESSIONS:
        return sid
    sid = session.get("sid")
    if sid and sid in WEB_SESSIONS:
        return sid
    return None

# ==========================================
# CHECK KEY ADMIN — FIX HOÀN CHỈNH
# ==========================================
def _try_admin_endpoint(url, payload, headers):
    try:
        r = requests.post(url, json=payload, timeout=ADMIN_API_TIMEOUT, headers=headers)
        if r.status_code in (404, 405): return None, None
        if not (200 <= r.status_code < 300): return None, None
        text = (r.text or "").strip()
        if not text: return None, None
        try: data = r.json()
        except Exception: return None, None
        if not isinstance(data, dict): return None, None

        if data.get("success") is True or data.get("valid") is True or data.get("ok") is True:
            info = data.get("info") or data.get("data") or {}
            return True, info
        msg = (data.get("message") or data.get("error") or data.get("msg")
               or "KEY không hợp lệ hoặc đã hết hạn")
        return False, str(msg)
    except requests.exceptions.Timeout:  return None, None
    except requests.exceptions.ConnectionError: return None, None
    except Exception: return None, None

def validate_key_remote(key, device_id=None, username=None):
    global ADMIN_WORKING_ENDPOINT
    if not key or not str(key).strip():
        return False, "Vui lòng nhập KEY"
    key = str(key).strip().upper()
    payload = {"key": key, "device": device_id or "", "username": username or ""}
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
               "Accept": "application/json"}

    endpoints = list(ADMIN_KEY_ENDPOINTS)
    if ADMIN_WORKING_ENDPOINT and ADMIN_WORKING_ENDPOINT in endpoints:
        endpoints.remove(ADMIN_WORKING_ENDPOINT)
        endpoints.insert(0, ADMIN_WORKING_ENDPOINT)

    network_fail = 0
    for url in endpoints:
        ok, info = _try_admin_endpoint(url, payload, headers)
        if ok is None:
            network_fail += 1; continue
        with ADMIN_ENDPOINT_LOCK:
            if ADMIN_WORKING_ENDPOINT != url:
                ADMIN_WORKING_ENDPOINT = url
        return (True, info) if ok else (False, info)

    if network_fail == len(endpoints):
        return False, "Không kết nối được Server Admin (kiểm tra mạng hoặc báo Admin)"
    return False, "Server Admin không phản hồi đúng API (báo Admin kiểm tra endpoint)"

# ==========================================
# API LỊCH SỬ GAME
# ==========================================
def fetch_api_raw():
    try:
        url = f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}"
        r = requests.get(url, timeout=5, headers={"Cache-Control": "no-store",
                                                   "User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()
        API_LAST_RAW["data"] = data
        API_LAST_RAW["ts"] = time.time()
        API_LAST_RAW["error"] = None
        return data
    except Exception as e:
        API_LAST_RAW["error"] = str(e)
        return None

def api_data_worker():
    last_session_logged = None
    while True:
        data = fetch_api_raw()
        if data:
            session_id = data.get("phien")
            result_str = data.get("ket_qua") or ""
            if session_id and result_str and session_id != last_session_logged:
                side = normalize_side(result_str)
                if side:
                    with GLOBAL_HISTORY_LOCK:
                        if not any(h["session"] == session_id for h in GLOBAL_HISTORY[-5:]):
                            GLOBAL_HISTORY.append({"session": session_id, "side": side, "ts": time.time()})
                            if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY:
                                GLOBAL_HISTORY.pop(0)
                    last_session_logged = session_id
        socketio.sleep(1.5)

socketio.start_background_task(api_data_worker)

def get_prediction():
    now = time.time()
    data = API_LAST_RAW["data"] if (API_LAST_RAW["data"] and (now - API_LAST_RAW["ts"]) < 1.5) else fetch_api_raw()
    if not data:
        return {"side": None, "conf": None, "ready": False, "api_ok": False, "api_session": None}
    side_out = normalize_side(data.get("du_doan"))
    return {
        "side": side_out,
        "conf": data.get("do_tin_cay"),
        "ready": side_out is not None,
        "api_ok": True,
        "api_session": data.get("phien"),
    }

# ==========================================
# LOGIN GAME
# ==========================================
def md5_hash(t): return hashlib.md5(t.encode()).hexdigest()

def login_game(username, password):
    try:
        pw = md5_hash(password)
        url = f"{API_LOGIN_URL}?c=3&un={username}&pw={pw}&{COMMON_PARAMS}&at="
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://tele68.com",
            "Referer": "https://tele68.com/",
        }
        r = requests.get(url, timeout=12, headers=headers)
        data = r.json()
        if not data.get("success"):
            return {"_error": data.get("message", "Sai thông tin đăng nhập")}

        sk = data["sessionKey"]
        sk += "=" * ((4 - len(sk) % 4) % 4)
        nickname = json.loads(base64.b64decode(sk).decode("utf-8")).get("nickname")

        r2 = requests.post(
            f"{API_LOBBY_URL}?{COMMON_PARAMS}&at=",
            headers={"content-type": "application/json", **headers},
            json={"nickName": nickname, "accessToken": data["accessToken"]},
            timeout=12,
        )
        lobby = r2.json()
        jwt = lobby.get("token")
        if not jwt: return {"_error": "Lobby không trả về token"}

        return {
            "token": jwt,
            "nickname": nickname,
            "money": lobby.get("remoteLoginResp", {}).get("money", 0)
        }
    except Exception as e:
        return {"_error": f"Lỗi kết nối Game: {e}"}

# ==========================================
# CƯỢC
# ==========================================
def calc_next_bet(st):
    base = int(st["base_bet_amount"])
    if st.get("x2_mode") and st["win_streak"] > 0:
        return base * min(2 ** st["win_streak"], 32)
    if st.get("x2_loss_mode") and st["loss_streak"] > 0:
        limit = int(st.get("x2_loss_limit", 5))
        if st["loss_streak"] <= limit:
            return base * min(2 ** st["loss_streak"], 32)
    return base

# ==========================================
# SOCKET GAME
# ==========================================
def game_socket_worker(sid, jwt_token):
    st = WEB_SESSIONS.get(sid)
    if not st: return

    sio = SocketClient(reconnection=True, reconnection_attempts=100, reconnection_delay=2)
    WS_CLIENTS[sid] = sio

    @sio.event(namespace=GAME_WS_NS)
    def connect():
        st["socket_connected"] = True
        socketio.emit("toast", {"type": "success", "msg": "Đã kết nối socket game"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def disconnect():
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        st["session_id"] = data.get("id")
        st["has_bet_this_session"] = False
        st["current_bet_type"] = None
        st["current_bet_side"] = None

        pred = get_prediction()
        st["current_prediction"] = pred["side"]
        st["prediction"] = pred["side"]
        st["current_bet"] = calc_next_bet(st) if st["auto_bet_enabled"] else int(st["base_bet_amount"])

        socketio.emit("session_update", {
            "session_id": st["session_id"],
            "prediction": pred["side"],
            "conf": pred["conf"],
            "ready": pred["ready"],
            "history_len": len(GLOBAL_HISTORY),
            "current_bet": st["current_bet"],
            "current_bet_side": st.get("current_bet_side"),
            "auto_bet_enabled": st["auto_bet_enabled"],
        }, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick_update(data):
        if data.get("state") != "BETTING" or not st["auto_bet_enabled"] or st["has_bet_this_session"]:
            return
        bet_type = normalize_side(st.get("current_prediction"))
        if not bet_type: return
        try:
            sio.emit("bet", {"type": bet_type, "amount": st["current_bet"]}, namespace=GAME_WS_NS)
            st["has_bet_this_session"] = True
            st["waiting_for_result"] = True
            st["current_bet_type"] = bet_type
            st["current_bet_side"] = bet_type
            socketio.emit("toast", {"type": "info",
                                    "msg": f"🚀 Cược {st['current_bet']:,}đ vào {bet_type}"}, to=sid)
        except: pass

    @sio.on("bet-result", namespace=GAME_WS_NS)
    def on_bet_result(data):
        if "postBalance" in data:
            st["balance"] = data["postBalance"]
            socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_session_result(data):
        result_side = normalize_side(data.get("result") or data.get("resultTruyenThong"))
        dice_list = data.get("dice") or data.get("xuc_xac") or []
        if st.get("waiting_for_result") and st.get("current_bet_type") and result_side:
            is_win = (st["current_bet_type"] == result_side)
            bet_amt = int(st["current_bet"])
            profit_delta = int(bet_amt * 0.98) if is_win else -bet_amt

            if is_win:
                st["win_streak"] += 1; st["loss_streak"] = 0; st["win_count"] += 1
            else:
                st["win_streak"] = 0; st["loss_streak"] += 1; st["lose_count"] += 1

            st["profit_loss"] += profit_delta
            st["waiting_for_result"] = False

            history_entry = {
                "session": st["session_id"],
                "pred": st["current_bet_type"],
                "bet_side": st["current_bet_type"],
                "bet": bet_amt,
                "result": result_side,
                "dice": dice_list[:3] if isinstance(dice_list, list) else [],
                "win": is_win,
            }
            st["history"].insert(0, history_entry)
            st["history"] = st["history"][:30]

            socketio.emit("result_update", {
                "session": st["session_id"], "pred": st["current_bet_type"],
                "bet_side": st["current_bet_type"],
                "result": result_side, "is_win": is_win, "bet": bet_amt,
                "dice": history_entry["dice"],
                "balance": st["balance"],
                "profit_loss": st["profit_loss"], "profit_delta": profit_delta,
                "history": st["history"][:15],
            }, to=sid)

        socketio.emit("stats_update", public_state(st), to=sid)

    try:
        sio.connect(f"{GAME_WS_URL}?token={jwt_token}", socketio_path=GAME_WS_PATH,
                    namespaces=[GAME_WS_NS], transports=["websocket"], wait_timeout=15)
        sio.wait()
    except Exception as e:
        logger.error(f"[{sid}] Socket lỗi: {e}")

# ==========================================
# PUBLIC STATE — KHỚP HTML
# ==========================================
def public_state(st):
    return {
        "nickname": st["nickname"],
        "balance": st["balance"],
        "profit_loss": st["profit_loss"],
        "auto_bet_enabled": st["auto_bet_enabled"],
        "x2_mode": st["x2_mode"],
        "x2_loss_mode": st["x2_loss_mode"],
        "x2_loss_limit": st["x2_loss_limit"],
        "base_bet_amount": st["base_bet_amount"],
        "current_bet": st["current_bet"],
        "current_bet_side": st.get("current_bet_side"),   # HTML dùng
        "target_profit": st["target_profit"],
        "current_prediction": st["current_prediction"],
        "prediction": st.get("prediction") or st["current_prediction"],  # HTML dùng
        "conf": st.get("conf"),
        "ready": st.get("ready", False),
        "history_len": len(GLOBAL_HISTORY),                # HTML dùng
        "current_bet_type": st.get("current_bet_type"),
        "session_id": st["session_id"],
        "win_count": st["win_count"],
        "lose_count": st["lose_count"],
        "win_streak": st["win_streak"],
        "loss_streak": st["loss_streak"],
        "socket_connected": st["socket_connected"],
        "waiting_for_result": st.get("waiting_for_result", False),
        "has_bet_this_session": st.get("has_bet_this_session", False),
        "history": st["history"][:15],
    }

def stats_broadcast_worker():
    while True:
        for sid, st in list(WEB_SESSIONS.items()):
            try: socketio.emit("stats_update", public_state(st), to=sid)
            except: pass
        socketio.sleep(5)

socketio.start_background_task(stats_broadcast_worker)

# ==========================================
# ROUTES
# ==========================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    access_key = data.get("key", "").strip()
    device_id = data.get("device", "").strip()

    if not username or not password:
        return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})
    if not access_key:
        return jsonify({"success": False, "error": "Vui lòng nhập KEY"})

    ok, key_info = validate_key_remote(access_key, device_id, username)
    if not ok:
        return jsonify({"success": False, "error": f"❌ {key_info}"})

    res = login_game(username, password)
    if "_error" in res:
        return jsonify({"success": False, "error": res["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    WEB_SESSIONS[sid] = {
        "nickname": res["nickname"], "balance": res["money"], "token": res["token"],
        "username": username, "access_key": access_key, "key_info": key_info,
        "device_id": device_id,
        "profit_loss": 0, "auto_bet_enabled": False,
        "x2_mode": False, "x2_loss_mode": False, "x2_loss_limit": 5,
        "win_streak": 0, "loss_streak": 0,
        "base_bet_amount": 10000, "current_bet": 10000, "current_bet_side": None,
        "target_profit": None,
        "current_prediction": None, "prediction": None,
        "conf": None, "ready": False,
        "current_bet_type": None,
        "waiting_for_result": False, "has_bet_this_session": False,
        "session_id": None,
        "win_count": 0, "lose_count": 0,
        "socket_connected": False, "history": [],
        "last_heartbeat": time.time(),
    }
    SID_TO_NICK[sid] = res["nickname"]

    socketio.start_background_task(game_socket_worker, sid, res["token"])
    return jsonify({
        "success": True, "sid": sid,
        "nickname": res["nickname"], "balance": res["money"],
    })

@app.route("/api/config", methods=["POST"])
def api_config():
    sid = get_sid_from_request()
    if not sid:
        return jsonify({"success": False, "error": "Chưa login"})
    st = WEB_SESSIONS[sid]
    data = request.json or {}

    if "betAmount" in data:
        try: st["base_bet_amount"] = max(1000, int(data["betAmount"]))
        except: pass
    if "auto_bet_enabled" in data:
        st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
        st["has_bet_this_session"] = not st["auto_bet_enabled"]
    if "x2_mode" in data: st["x2_mode"] = bool(data["x2_mode"])
    if "x2_loss_mode" in data: st["x2_loss_mode"] = bool(data["x2_loss_mode"])
    if "x2_loss_limit" in data:
        try: st["x2_loss_limit"] = int(data["x2_loss_limit"])
        except: pass
    if "target_profit" in data:
        try: st["target_profit"] = int(data["target_profit"]) if data["target_profit"] else None
        except: st["target_profit"] = None

    socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True, "state": public_state(st)})

@app.route("/api/stats")
def api_stats():
    sid = get_sid_from_request()
    if not sid:
        return jsonify({"success": False})
    return jsonify({"success": True, "state": public_state(WEB_SESSIONS[sid])})

@app.route("/api/heartbeat", methods=["POST"])
def api_heartbeat():
    sid = get_sid_from_request()
    if not sid:
        return jsonify({"success": False, "error": "Chưa login"})
    WEB_SESSIONS[sid]["last_heartbeat"] = time.time()
    return jsonify({"success": True})

@app.route("/api/reset_history", methods=["POST"])
def api_reset_history():
    sid = get_sid_from_request()
    if sid:
        st = WEB_SESSIONS[sid]
        st["history"] = []
        st["win_count"] = 0; st["lose_count"] = 0
        st["profit_loss"] = 0
        st["win_streak"] = 0; st["loss_streak"] = 0
        socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = get_sid_from_request()
    if sid:
        if sid in WS_CLIENTS:
            try: WS_CLIENTS[sid].disconnect()
            except: pass
            del WS_CLIENTS[sid]
        if sid in WEB_SESSIONS: del WEB_SESSIONS[sid]
        if sid in SID_TO_NICK: del SID_TO_NICK[sid]
    session.pop("sid", None)
    return jsonify({"success": True})

# ==========================================
# SOCKETIO — FRONTEND JOIN ROOM
# ==========================================
@socketio.on("join_session")
def handle_join_session(data):
    sid = (data or {}).get("sid")
    if sid and sid in WEB_SESSIONS:
        from flask_socketio import join_room
        join_room(sid)
        socketio.emit("stats_update", public_state(WEB_SESSIONS[sid]), to=request.sid)

# ==========================================
# DEBUG
# ==========================================
@app.route("/api/debug/admin")
def api_debug_admin():
    results = {}
    for url in ADMIN_KEY_ENDPOINTS:
        try:
            r = requests.post(url, json={"key": "DEBUG_TEST", "device": "", "username": ""},
                              timeout=8, headers={"Content-Type": "application/json"})
            results[url] = {"status": r.status_code, "body": (r.text or "")[:300]}
        except Exception as e:
            results[url] = {"error": str(e)}
    return jsonify({
        "base_url": ADMIN_BASE_URL,
        "working_endpoint": ADMIN_WORKING_ENDPOINT,
        "results": results,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
