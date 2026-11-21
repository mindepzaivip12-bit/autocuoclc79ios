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
app.config['SECRET_KEY'] = 'lc79-minh-dz-secret-key-fixed' # Cố định secret key để không bị mất session khi restart
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)

# ==========================================
# CẤU HÌNH
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://leminhlcdz.onrender.com/lc79md5"
GAME_WS_URL     = "https://wtxmd52.tele68.com"
GAME_WS_PATH    = "txmd5/"
GAME_WS_NS      = "/txmd5"
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

LICENSE_SERVER_URL = os.environ.get("LICENSE_SERVER_URL", "https://lc79vipadmin-5orx.onrender.com").rstrip("/")

WEB_SESSIONS = {}
WS_CLIENTS = {}
GLOBAL_HISTORY = []
API_LAST_RAW = {"data": None, "ts": 0, "error": None}

# ==========================================
# HÀM HỖ TRỢ
# ==========================================
def normalize_side(val):
    if val is None: return None
    s = str(val).strip().upper()
    if "X" in s: return "XIU"
    if "T" in s: return "TAI"
    return None

def get_prediction():
    try:
        r = requests.get(f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}", timeout=5)
        data = r.json()
        API_LAST_RAW["data"] = data
        API_LAST_RAW["ts"] = time.time()
        return {"side": normalize_side(data.get("du_doan")), "conf": data.get("do_tin_cay"), "ready": bool(data.get("du_doan")), "raw": data}
    except Exception as e:
        logger.error(f"API lịch sử lỗi: {e}")
        return {"side": None, "conf": 0, "ready": False, "raw": None}

def login_game(u, p):
    try:
        pw = hashlib.md5(p.encode()).hexdigest()
        r = requests.get(f"{API_LOGIN_URL}?c=3&un={u}&pw={pw}&{COMMON_PARAMS}&at=", timeout=12)
        d = r.json()
        if not d.get("success"): return {"_error": d.get("message", "Sai tài khoản")}
        
        sk = d["sessionKey"] + "=" * ((4 - len(d["sessionKey"]) % 4) % 4)
        sk_data = json.loads(base64.b64decode(sk).decode("utf-8"))
        nick = sk_data.get("nickname") or sk_data.get("nickName")
        
        r2 = requests.post(f"{API_LOBBY_URL}?{COMMON_PARAMS}&at=", json={"nickName": nick, "accessToken": d["accessToken"]}, timeout=12)
        lobby = r2.json()
        
        if not lobby.get("token"): return {"_error": "Không lấy được token game"}
        return {"token": lobby["token"], "nickname": nick, "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": f"Lỗi kết nối game: {e}"}

# ==========================================
# GAME SOCKET WORKER (Đã fix lỗi kết nối)
# ==========================================
def game_socket_worker(sid, jwt):
    st = WEB_SESSIONS.get(sid)
    if not st: return

    sio = SocketClient(reconnection=True, reconnection_attempts=10, reconnection_delay=2, logger=False, engineio_logger=False)
    WS_CLIENTS[sid] = sio

    @sio.event(namespace=GAME_WS_NS)
    def connect():
        logger.info(f"[{sid}] ✅ Đã kết nối Socket Game")
        st["socket_connected"] = True
        socketio.emit("stats_update", public_state(st), to=sid)
        socketio.emit("toast", {"type": "success", "msg": "Đã kết nối Game"}, to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def connect_error(data):
        logger.error(f"[{sid}] ❌ Lỗi Socket: {data}")
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)
        socketio.emit("toast", {"type": "error", "msg": f"Lỗi Socket: {data}"}, to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def disconnect():
        logger.warning(f"[{sid}] ⚠️ Mất kết nối Socket Game")
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        st["session_id"] = data.get("id") or data.get("sessionId")
        st["has_bet_this_session"] = False
        pred = get_prediction()
        st["current_prediction"] = pred["side"]
        
        socketio.emit("session_update", {
            "session_id": st["session_id"], "prediction": pred["side"], 
            "conf": pred["conf"], "ready": pred["ready"], "current_bet": st["current_bet"]
        }, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick(data):
        if data.get("state") == "BETTING" and st.get("auto_bet_enabled") and not st.get("has_bet_this_session"):
            if st.get("current_prediction"):
                sio.emit("bet", {"type": st["current_prediction"], "amount": st["current_bet"]}, namespace=GAME_WS_NS)
                st["has_bet_this_session"] = True
                st["current_bet_type"] = st["current_prediction"]
                socketio.emit("toast", {"type": "info", "msg": f"🚀 Đã cược {st['current_bet']:,}đ {st['current_prediction']}"}, to=sid)

    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_result(data):
        res_side = normalize_side(data.get("resultTruyenThong") or data.get("result"))
        is_win = False
        if st.get("current_bet_type") == res_side:
            is_win = True
            st["profit_loss"] += int(st["current_bet"] * 0.98)
            st["win_count"] += 1
        elif st.get("current_bet_type"):
            st["profit_loss"] -= int(st["current_bet"])
            st["lose_count"] += 1
        
        st["history"].insert(0, {"session": data.get("id"), "pred": st.get("current_bet_type"), "bet": st["current_bet"], "result": res_side, "win": is_win})
        st["current_bet_type"] = None
        
        socketio.emit("result_update", {"balance": st["balance"], "profit_loss": st["profit_loss"], "history": st["history"][:15]}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    try:
        logger.info(f"[{sid}] Đang kết nối tới Game Socket...")
        sio.connect(f"{GAME_WS_URL}?token={jwt}", socketio_path=GAME_WS_PATH, namespaces=[GAME_WS_NS], transports=["websocket"], wait_timeout=15)
        sio.wait()
    except Exception as e:
        logger.error(f"[{sid}] ❌ Lỗi khởi tạo Socket: {e}")
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

def public_state(st):
    return {
        "nickname": st["nickname"], "balance": st["balance"], "profit_loss": st["profit_loss"],
        "auto_bet_enabled": st["auto_bet_enabled"], "base_bet_amount": st["base_bet_amount"],
        "current_bet": st["current_bet"], "current_prediction": st["current_prediction"],
        "session_id": st["session_id"], "win_count": st["win_count"], "lose_count": st["lose_count"],
        "socket_connected": st["socket_connected"], "history": st["history"][:15]
    }

# ==========================================
# ROUTES
# ==========================================
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    u, p = (data.get("username") or "").strip(), (data.get("password") or "").strip()
    
    # Tạm bỏ qua check key để test
    if not u or not p: return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})

    r = login_game(u, p)
    if "_error" in r: return jsonify({"success": False, "error": r["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    
    WEB_SESSIONS[sid] = {
        "nickname": r["nickname"], "balance": r["money"], "username": u,
        "profit_loss": 0, "auto_bet_enabled": False, "base_bet_amount": 10000, "current_bet": 10000,
        "current_prediction": None, "current_bet_type": None, "has_bet_this_session": False, "session_id": None,
        "win_count": 0, "lose_count": 0, "socket_connected": False, "history": []
    }

    socketio.start_background_task(game_socket_worker, sid, r["token"])
    
    return jsonify({
        "success": True, "sid": sid, "nickname": r["nickname"], "balance": r["money"],
        "license_expires_at": int(time.time()) + 86400*30
    })

@app.route("/api/stats")
def api_stats():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS:
        return jsonify({"success": False, "error": "Phiên hết hạn", "code": "NO_SESSION"}), 401
    return jsonify({"success": True, "state": public_state(WEB_SESSIONS[sid])})

@app.route("/api/config", methods=["POST"])
def api_config():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS: return jsonify({"success": False}), 401
    st = WEB_SESSIONS[sid]; data = request.json or {}
    if "betAmount" in data: st["base_bet_amount"] = st["current_bet"] = int(data["betAmount"])
    if "auto_bet_enabled" in data:
        st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
        st["has_bet_this_session"] = False
    socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    if sid in WS_CLIENTS: WS_CLIENTS[sid].disconnect()
    WEB_SESSIONS.pop(sid, None); session.clear()
    return jsonify({"success": True})

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
