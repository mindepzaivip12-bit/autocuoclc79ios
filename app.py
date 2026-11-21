import eventlet
eventlet.monkey_patch()

import os, json, time, base64, hashlib, logging, threading, re, websocket
import requests
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'lc79-minh-dz-fixed-key-2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)

# ==========================================
# CẤU HÌNH
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://apibetvipbominh.onrender.com/lc79md5"
GAME_WS_URL     = "wss://wtxmd52.tele68.com/txmd5/?token="
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

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

def fetch_api_raw():
    try:
        r = requests.get(f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}", timeout=5)
        data = r.json()
        API_LAST_RAW.update({"data": data, "ts": time.time(), "error": None})
        return data
    except Exception as e:
        API_LAST_RAW["error"] = str(e)
        return None

def get_prediction():
    data = fetch_api_raw() if not API_LAST_RAW["data"] or (time.time() - API_LAST_RAW["ts"]) > 1.5 else API_LAST_RAW["data"]
    if not data: return {"side": None, "conf": None, "ready": False, "api_session": None}
    side = normalize_side(data.get("du_doan"))
    return {"side": side, "conf": data.get("do_tin_cay"), "ready": side is not None, "api_session": data.get("phien")}

def parse_result_side(raw):
    if not raw: return None
    side = normalize_side(raw)
    if side: return side
    nums = [int(x) for x in re.findall(r"\d+", str(raw))]
    return "TAI" if len(nums) >= 3 and sum(nums[:3]) >= 11 else ("XIU" if len(nums) >= 3 else None)

def login_game(u, p):
    try:
        r = requests.get(f"{API_LOGIN_URL}?c=3&un={u}&pw={hashlib.md5(p.encode()).hexdigest()}&{COMMON_PARAMS}&at=", timeout=12)
        d = r.json()
        if not d.get("success"): return {"_error": d.get("message", "Sai tài khoản")}
        sk = d["sessionKey"] + "=" * ((4 - len(d["sessionKey"]) % 4) % 4)
        nick = json.loads(base64.b64decode(sk).decode("utf-8")).get("nickname")
        r2 = requests.post(f"{API_LOBBY_URL}?{COMMON_PARAMS}&at=", json={"nickName": nick, "accessToken": d["accessToken"]}, timeout=12)
        lobby = r2.json()
        return {"token": lobby["token"], "nickname": nick, "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e: return {"_error": f"Lỗi kết nối: {e}"}

def public_state(st):
    return {
        "nickname": st.get("nickname", ""), "balance": st.get("balance", 0), "profit_loss": st.get("profit_loss", 0),
        "auto_bet_enabled": st.get("auto_bet_enabled", False), "base_bet_amount": st.get("base_bet_amount", 10000),
        "current_bet": st.get("current_bet", 10000), "current_prediction": st.get("current_prediction"),
        "session_id": st.get("session_id"), "win_count": st.get("win_count", 0), "lose_count": st.get("lose_count", 0),
        "socket_connected": st.get("socket_connected", False), "history": st.get("history", [])
    }

# ==========================================
# GAME SOCKET WORKER (DÙNG WEBSOCKET-CLIENT)
# ==========================================
def game_socket_worker(sid, jwt):
    st = WEB_SESSIONS.get(sid)
    if not st: return

    try:
        logger.info(f"[{sid}] Đang kết nối WebSocket: {GAME_WS_URL}...")
        ws = websocket.create_connection(f"{GAME_WS_URL}{jwt}", timeout=15)
        st["socket_connected"] = True
        socketio.emit("stats_update", public_state(st), to=sid)
        socketio.emit("toast", {"type": "success", "msg": "Đã kết nối Game Server"}, to=sid)

        while True:
            msg = ws.recv()
            if not msg: continue
            
            data = json.loads(msg)
            event = data.get("event") or data.get("name") or data.get("type")
            payload = data.get("data") or data.get("payload") or data

            if event == "new-session":
                st["session_id"] = payload.get("id")
                st["has_bet_this_session"] = False
                pred = get_prediction()
                st["current_prediction"] = pred["side"]
                socketio.emit("session_update", {"session_id": st["session_id"], "prediction": pred["side"], "conf": pred["conf"], "ready": pred["ready"], "current_bet": st["current_bet"]}, to=sid)
                socketio.emit("stats_update", public_state(st), to=sid)

            elif event == "tick-update" and payload.get("state") == "BETTING":
                if st.get("auto_bet_enabled") and not st.get("has_bet_this_session") and st.get("current_prediction"):
                    bet_msg = json.dumps({"event": "bet", "data": {"type": st["current_prediction"], "amount": st["current_bet"]}})
                    ws.send(bet_msg)
                    st["has_bet_this_session"] = True
                    socketio.emit("toast", {"type": "info", "msg": f"🚀 Đã cược {st['current_bet']:,}đ {st['current_prediction']}"}, to=sid)

            elif event == "session-result":
                res_side = parse_result_side(payload.get("resultTruyenThong") or payload.get("result"))
                is_win = False
                if st.get("current_prediction") == res_side:
                    is_win = True
                    st["profit_loss"] += int(st["current_bet"] * 0.98)
                    st["win_count"] += 1
                elif st.get("has_bet_this_session"):
                    st["profit_loss"] -= int(st["current_bet"])
                    st["lose_count"] += 1
                
                st["history"].insert(0, {"session": payload.get("id"), "pred": st.get("current_prediction"), "bet": st["current_bet"], "result": res_side, "win": is_win})
                st["has_bet_this_session"] = False
                socketio.emit("result_update", {"balance": st["balance"], "profit_loss": st["profit_loss"], "history": st["history"][:15]}, to=sid)
                socketio.emit("stats_update", public_state(st), to=sid)

    except Exception as e:
        logger.error(f"[{sid}] Lỗi Socket: {e}")
    finally:
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

# ==========================================
# ROUTES
# ==========================================
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    u, p = data.get("username"), data.get("password")
    if not u or not p: return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})

    r = login_game(u, p)
    if "_error" in r: return jsonify({"success": False, "error": r["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    WEB_SESSIONS[sid] = {
        "nickname": r["nickname"], "balance": r["money"], "username": u,
        "profit_loss": 0, "auto_bet_enabled": False, "base_bet_amount": 10000, "current_bet": 10000,
        "current_prediction": None, "has_bet_this_session": False, "session_id": None,
        "win_count": 0, "lose_count": 0, "socket_connected": False, "history": []
    }

    socketio.start_background_task(game_socket_worker, sid, r["token"])
    
    return jsonify({"success": True, "sid": sid, "nickname": r["nickname"], "balance": r["money"], "license_expires_at": int(time.time()) + 86400*30})

@app.route("/api/stats")
def api_stats():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS: return jsonify({"success": False, "error": "Phiên hết hạn"}), 401
    return jsonify({"success": True, "state": public_state(WEB_SESSIONS[sid])})

@app.route("/api/config", methods=["POST"])
def api_config():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS: return jsonify({"success": False}), 401
    st = WEB_SESSIONS[sid]; data = request.json or {}
    if "betAmount" in data: st["base_bet_amount"] = st["current_bet"] = int(data["betAmount"])
    if "auto_bet_enabled" in data:
        st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
        st["has_bet_this_session"] = not st["auto_bet_enabled"]
    if "reset_history" in data and data["reset_history"]:
        st["history"] = []; st["win_count"] = 0; st["lose_count"] = 0; st["profit_loss"] = 0
    socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    WEB_SESSIONS.pop(sid, None); session.clear()
    return jsonify({"success": True})

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
