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
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet',
                    ping_timeout=60, ping_interval=25)

# ==========================================
# CẤU HÌNH
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://leminhapidz.onrender.com/lc79md5"
GAME_WS_URL     = "https://wtxmd52.tele68.com"
GAME_WS_PATH    = "txmd5/"
GAME_WS_NS      = "/txmd5"
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

# ===== KEY SERVER =====
KEY_SERVER_URL     = "https://leminhadminios.onrender.com"
KEY_CHECK_INTERVAL = 30

# ==========================================
# GLOBAL DATA
# ==========================================
GLOBAL_HISTORY = []
MAX_GLOBAL_HISTORY = 2000
GLOBAL_HISTORY_LOCK = threading.Lock()

WEB_SESSIONS = {}
WS_CLIENTS   = {}

API_LAST_RAW = {"data": None, "ts": 0, "error": None}

# ==========================================
# KEY SERVER HELPERS (ĐÃ NÂNG CẤP DEBUG)
# ==========================================
def key_server_verify(key, device):
    """Gọi API verify key, có retry nếu server Render đang ngủ."""
    url = f"{KEY_SERVER_URL}/api/verify_key"
    payload = {"key": key, "device": device}
    
    # Thử tối đa 3 lần
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=25)
            
            # Log raw response để debug
            logger.info(f"[KeyServer] Attempt {attempt+1} | Status: {r.status_code} | Body: {r.text[:300]}")
            
            # Nếu server trả về lỗi 5xx (thường do Render đang ngủ)
            if r.status_code >= 500:
                logger.warning(f"[KeyServer] Server đang bảo trì/ngủ (Status {r.status_code}). Chờ 4s...")
                time.sleep(4)
                continue
                
            # Thử parse JSON
            try:
                res_json = r.json()
                return res_json
            except ValueError:
                # Nếu không phải JSON, trả về lỗi chi tiết từ server
                error_msg = f"Server key trả về HTML/Lỗi (Status {r.status_code}). Chi tiết: {r.text[:50]}..."
                logger.error(f"[KeyServer] {error_msg}")
                if attempt == 2: # Lần cuối vẫn lỗi thì báo
                    return {"success": False, "error": "Server key đang bảo trì hoặc sai API. Vui lòng báo Admin."}
                time.sleep(4)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"[KeyServer] Lỗi mạng (lần {attempt+1}): {e}")
            if attempt == 2:
                return {"success": False, "error": "Không thể kết nối tới Server Key."}
            time.sleep(4)
            
    return {"success": False, "error": "Server Key không phản hồi sau nhiều lần thử."}

def key_server_check(key, device):
    """Check key định kỳ, bỏ qua nếu server key sập."""
    try:
        r = requests.post(f"{KEY_SERVER_URL}/api/check_key", json={"key": key, "device": device}, timeout=15)
        if r.status_code >= 500:
            return {"success": True, "grace": True}
        return r.json()
    except Exception:
        return {"success": True, "grace": True}

# ==========================================
# FORCE LOGOUT
# ==========================================
def force_logout(sid, reason, expired=False):
    logger.warning(f"[{sid}] 🔒 FORCE LOGOUT: {reason}")
    try:
        socketio.emit("force_logout", {"reason": reason, "expired": expired}, to=sid)
    except Exception:
        pass
    if sid in WS_CLIENTS:
        try: WS_CLIENTS[sid].disconnect()
        except Exception: pass
        del WS_CLIENTS[sid]
    if sid in WEB_SESSIONS:
        del WEB_SESSIONS[sid]

# ==========================================
# KEY MONITOR WORKER
# ==========================================
def key_monitor_worker(sid):
    st = WEB_SESSIONS.get(sid)
    if not st: return

    while True:
        socketio.sleep(KEY_CHECK_INTERVAL)
        if sid not in WEB_SESSIONS: break

        st = WEB_SESSIONS[sid]
        key, device = st.get("key"), st.get("device")
        expires_at = st.get("key_expires_at", 0)

        if not key or not device: break

        if expires_at and time.time() > expires_at:
            force_logout(sid, "Key đã hết hạn", expired=True)
            break

        result = key_server_check(key, device)
        if not result.get("success") and not result.get("grace"):
            force_logout(sid, result.get("error", "Key không hợp lệ"), expired=result.get("expired", False))
            break

# ==========================================
# API LỊCH SỬ
# ==========================================
def fetch_api_raw():
    try:
        url = f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}"
        r = requests.get(url, timeout=5, headers={"Cache-Control": "no-store", "User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()
        API_LAST_RAW["data"]  = data
        API_LAST_RAW["ts"]    = time.time()
        API_LAST_RAW["error"] = None
        return data
    except Exception as e:
        API_LAST_RAW["error"] = str(e)
        logger.error(f"[API] Fetch fail: {e}")
        return None

def api_data_worker():
    logger.info("[API Worker] started")
    last_session_logged = None
    while True:
        data = fetch_api_raw()
        if data:
            session_id = data.get("phien")
            result_str = data.get("ket_qua") or ""
            du_doan    = data.get("du_doan")
            do_tin_cay = data.get("do_tin_cay")

            if session_id and result_str and session_id != last_session_logged:
                side = None
                low = result_str.lower()
                if "tài" in low or "tai" in low: side = "Tài"
                elif "xỉu" in low or "xiu" in low: side = "Xỉu"

                dices = []
                try:
                    parts = result_str.split()
                    if len(parts) > 1:
                        dices = [int(x) for x in parts[1].split("-")]
                except Exception: pass

                if side:
                    with GLOBAL_HISTORY_LOCK:
                        if not any(h["session"] == session_id for h in GLOBAL_HISTORY[-5:]):
                            GLOBAL_HISTORY.append({"session": session_id, "dice": dices, "side": side, "ts": time.time()})
                            if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY: GLOBAL_HISTORY.pop(0)
                            logger.info(f"[API] 📥 {session_id}: {side} {dices} | du_doan={du_doan} | conf={do_tin_cay}")
                    last_session_logged = session_id
        socketio.sleep(1.5)

socketio.start_background_task(api_data_worker)

# ==========================================
# DỰ ĐOÁN
# ==========================================
def get_prediction():
    if API_LAST_RAW["data"] and (time.time() - API_LAST_RAW["ts"]) < 1.5:
        data = API_LAST_RAW["data"]
    else:
        data = fetch_api_raw()

    if not data:
        return {"side": None, "conf": None, "ready": False, "api_ok": False, "api_error": API_LAST_RAW.get("error") or "API không phản hồi"}

    du_doan, do_tin_cay = data.get("du_doan"), data.get("do_tin_cay")
    return {"side": du_doan, "conf": do_tin_cay, "ready": du_doan is not None, "api_ok": True, "api_error": None, "raw": data}

# ==========================================
# PARSE RESULT
# ==========================================
def parse_result_side(result_raw):
    if not result_raw: return None
    s = str(result_raw).strip().upper()
    if s in ("TAI", "TÀI", "T"):   return "TAI"
    if s in ("XIU", "XỈU", "X"):   return "XIU"
    if "TÀI" in s or "TAI" in s:   return "TAI"
    if "XỈU" in s or "XIU" in s:   return "XIU"
    try:
        nums = [int(x) for x in s.replace("-", " ").replace(",", " ").split() if x.isdigit()]
        if len(nums) >= 3: return "TAI" if sum(nums[:3]) >= 11 else "XIU"
    except Exception: pass
    return None

# ==========================================
# LOGIN GAME
# ==========================================
def md5_hash(t): return hashlib.md5(t.encode()).hexdigest()

def login_game(username, password):
    try:
        pw  = md5_hash(password)
        url = f"{API_LOGIN_URL}?c=3&un={username}&pw={pw}&{COMMON_PARAMS}&at="
        sess = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0", "Origin": "https://tele68.com", "Referer": "https://tele68.com/"}
        r = sess.get(url, timeout=12, headers=headers)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {"_error": data.get("message", "Sai thông tin đăng nhập")}

        sk = data["sessionKey"]
        sk += "=" * ((4 - len(sk) % 4) % 4)
        sk_data  = json.loads(base64.b64decode(sk).decode("utf-8"))
        nickname = sk_data.get("nickname") or sk_data.get("nickName")

        access_token = data["accessToken"]
        r2 = sess.post(f"{API_LOBBY_URL}?{COMMON_PARAMS}&at=", headers={"content-type": "application/json", "authority": "wlb.tele68.com", **headers}, json={"nickName": nickname, "accessToken": access_token}, timeout=12)
        lobby = r2.json()
        jwt = lobby.get("token")
        if not jwt:
            return {"_error": "Lobby không trả về token"}
        return {"token": jwt, "nickname": nickname, "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": f"Lỗi kết nối: {e}"}

# ==========================================
# TÍNH CƯỢC
# ==========================================
def calc_next_bet(st):
    base = int(st["base_bet_amount"])
    if st["x2_mode"] and st["win_streak"] >= 1: return base * (2 ** min(st["win_streak"], 10))
    if st["x2_loss_mode"] and st["loss_streak"] >= 1:
        if st["loss_streak"] <= st["x2_loss_limit"]: return base * (2 ** st["loss_streak"])
        return base
    return base

# ==========================================
# GAME SOCKET WORKER
# ==========================================
def game_socket_worker(sid, jwt_token):
    st = WEB_SESSIONS.get(sid)
    if not st: return

    sio = SocketClient(reconnection=True, reconnection_attempts=100, reconnection_delay=2, logger=False, engineio_logger=False)
    WS_CLIENTS[sid] = sio

    def check_target_profit():
        if (st["auto_bet_enabled"] and st["target_profit"] and st["profit_loss"] >= st["target_profit"]):
            st["auto_bet_enabled"] = False
            socketio.emit("toast", {"type": "success", "msg": f"🏆 CHỐT LÃI! +{st['profit_loss']:,}đ — Auto đã tắt"}, to=sid)
            socketio.emit("stats_update", public_state(st), to=sid)
            return True
        return False

    @sio.event(namespace=GAME_WS_NS)
    def connect():
        st["socket_connected"] = True
        socketio.emit("toast", {"type": "success", "msg": "Đã kết nối socket game"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def connect_error(data):
        st["socket_connected"] = False
        socketio.emit("toast", {"type": "error", "msg": f"Lỗi kết nối: {data}"}, to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def disconnect():
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        st["session_id"] = data.get("id") or data.get("sessionId") or "N/A"
        st["has_bet_this_session"] = False
        st["waiting_for_result"]    = False
        if check_target_profit(): return

        st["current_bet"] = calc_next_bet(st)
        pred = get_prediction()
        st["current_prediction"] = pred["side"]
        
        socketio.emit("session_update", {
            "session_id": st["session_id"], "prediction": pred["side"], "conf": pred["conf"],
            "ready": pred["ready"], "api_ok": pred["api_ok"], "api_error": pred["api_error"],
            "history_len": len(GLOBAL_HISTORY), "current_bet": st["current_bet"], "auto_bet_enabled": st["auto_bet_enabled"]
        }, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick_update(data):
        if data.get("state") != "BETTING" or not st["auto_bet_enabled"] or st["has_bet_this_session"] or not st["current_prediction"] or not st["session_id"]: return

        pred_str = str(st["current_prediction"]).strip().upper()
        bet_type = "TAI" if pred_str.startswith("T") else ("XIU" if pred_str.startswith("X") else None)
        if not bet_type: return

        try:
            sio.emit("bet", {"type": bet_type, "amount": st["current_bet"]}, namespace=GAME_WS_NS)
            st["has_bet_this_session"] = True
            st["waiting_for_result"]   = True
            socketio.emit("toast", {"type": "info", "msg": f"🚀 Cược {st['current_bet']:,}đ vào {pred_str}"}, to=sid)
        except Exception as e:
            pass

    @sio.on("bet-result", namespace=GAME_WS_NS)
    def on_bet_result(data):
        if "postBalance" in data:
            st["balance"] = data["postBalance"]
            socketio.emit("stats_update", public_state(st), to=sid)
        try: sio.emit("get-current-my-info", None, namespace=GAME_WS_NS)
        except Exception: pass

    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_session_result(data):
        result_raw = (data.get("resultTruyenThong") or data.get("result") or data.get("resultString"))
        dices = data.get("dices") or data.get("dice") or [0, 0, 0]
        session_of_result = data.get("id") or st.get("session_id")

        result_side = parse_result_side(result_raw)
        pred = st.get("current_prediction")
        is_win, profit_delta = None, 0

        if pred and result_side:
            pred_str = str(pred).strip().upper()
            pred_key = "TAI" if pred_str.startswith("T") else ("XIU" if pred_str.startswith("X") else None)
            if pred_key:
                is_win = (pred_key == result_side)
                if st["waiting_for_result"]:
                    bet_amt = int(st["current_bet"])
                    if is_win:
                        profit_delta = int(bet_amt * 0.98)
                        st["profit_loss"] += profit_delta
                        st["win_streak"]  += 1; st["loss_streak"]  = 0; st["win_count"]   += 1
                    else:
                        profit_delta = -bet_amt
                        st["profit_loss"] += profit_delta
                        st["win_streak"]   = 0; st["loss_streak"] += 1; st["lose_count"]  += 1
                    st["waiting_for_result"] = False
                    st["balance"] += profit_delta

                st["history"].insert(0, {"session": session_of_result, "pred": pred, "bet": st["current_bet"], "result": result_side, "dice": dices, "win": is_win})
                st["history"] = st["history"][:30]

        socketio.emit("result_update", {
            "session": session_of_result, "pred": pred, "result": result_side or result_raw,
            "dices": dices, "is_win": is_win, "bet": st["current_bet"], "balance": st["balance"],
            "profit_loss": st["profit_loss"], "profit_delta": profit_delta, "history": st["history"][:15]
        }, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)
        check_target_profit()

    try:
        sio.connect(f"{GAME_WS_URL}?token={jwt_token}", socketio_path=GAME_WS_PATH, namespaces=[GAME_WS_NS],
                    headers={"User-Agent": "Mozilla/5.0", "Origin": "https://tele68.com"}, auth={"token": jwt_token},
                    transports=["websocket"], wait_timeout=15)
        sio.wait()
    except Exception as e:
        st["socket_connected"] = False
        socketio.emit("toast", {"type": "error", "msg": f"Socket lỗi: {e}"}, to=sid)

# ==========================================
# PUBLIC STATE
# ==========================================
def public_state(st):
    return {
        "nickname": st["nickname"], "balance": st["balance"], "profit_loss": st["profit_loss"],
        "auto_bet_enabled": st["auto_bet_enabled"], "x2_mode": st["x2_mode"], "x2_loss_mode": st["x2_loss_mode"],
        "x2_loss_limit": st["x2_loss_limit"], "base_bet_amount": st["base_bet_amount"], "current_bet": st["current_bet"],
        "target_profit": st["target_profit"], "current_prediction": st["current_prediction"], "session_id": st["session_id"],
        "win_count": st["win_count"], "lose_count": st["lose_count"], "win_streak": st["win_streak"], "loss_streak": st["loss_streak"],
        "socket_connected": st["socket_connected"], "history": st["history"][:15],
        "key_expires_at": st.get("key_expires_at"), "key_remaining": max(0, (st.get("key_expires_at") or 0) - time.time()),
    }

# ==========================================
# STATS BROADCAST
# ==========================================
def stats_broadcast_worker():
    while True:
        try:
            for sid, st in list(WEB_SESSIONS.items()):
                try: socketio.emit("stats_update", public_state(st), to=sid)
                except Exception: pass
        except Exception as e: logger.error(f"[Stats Worker] {e}")
        socketio.sleep(5)

socketio.start_background_task(stats_broadcast_worker)

# ==========================================
# SOCKET JOIN
# ==========================================
@socketio.on("join_session")
def on_join_session(data):
    custom_sid = (data or {}).get("sid")
    if custom_sid and custom_sid in WEB_SESSIONS:
        from flask_socketio import join_room
        join_room(custom_sid)

# ==========================================
# ROUTES
# ==========================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/verify_key", methods=["POST"])
def api_verify_key():
    data   = request.json or {}
    key    = (data.get("key") or "").strip().upper()
    device = (data.get("device") or "").strip()
    if not key or not device: return jsonify({"success": False, "error": "Thiếu key hoặc device"})
    return jsonify(key_server_verify(key, device))

@app.route("/api/login", methods=["POST"])
def api_login():
    data     = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    key      = (data.get("key") or "").strip().upper()
    device   = (data.get("device") or "").strip()

    if not username or not password: return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})
    if not key: return jsonify({"success": False, "error": "Thiếu key bản quyền"})
    if not device: return jsonify({"success": False, "error": "Thiếu mã thiết bị"})

    kr = key_server_verify(key, device)
    if not kr.get("success"):
        return jsonify({"success": False, "error": kr.get("error", "Key không hợp lệ"), "expired": kr.get("expired", False)})

    res = login_game(username, password)
    if "_error" in res: return jsonify({"success": False, "error": res["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    WEB_SESSIONS[sid] = {
        "nickname": res["nickname"], "balance": res["money"], "token": res["token"], "username": username, "key": key, "device": device,
        "key_expires_at": kr.get("expires_at", 0), "profit_loss": 0, "auto_bet_enabled": False, "x2_mode": False, "x2_loss_mode": True,
        "x2_loss_limit": 5, "win_streak": 0, "loss_streak": 0, "base_bet_amount": 10000, "current_bet": 10000, "target_profit": None,
        "current_prediction": None, "waiting_for_result": False, "has_bet_this_session": False, "session_id": None,
        "win_count": 0, "lose_count": 0, "socket_connected": False, "history": [], "last_api_raw": None,
    }
    socketio.start_background_task(game_socket_worker, sid, res["token"])
    socketio.start_background_task(key_monitor_worker, sid)

    return jsonify({"success": True, "sid": sid, "nickname": res["nickname"], "balance": res["money"], "key_expires_at": kr.get("expires_at"), "key_remaining": kr.get("remaining")})

@app.route("/api/config", methods=["POST"])
def api_config():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS: return jsonify({"success": False, "error": "Chưa login"})
    st, data = WEB_SESSIONS[sid], request.json or {}

    if "betAmount" in data:
        try:
            new_amt = int(data["betAmount"])
            if new_amt >= 1000: st["base_bet_amount"] = new_amt; st["current_bet"] = new_amt
        except Exception: pass
    if "auto_bet_enabled" in data: st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
    if "x2_mode" in data:
        st["x2_mode"] = bool(data["x2_mode"])
        if st["x2_mode"]: st["x2_loss_mode"] = False
    if "x2_loss_mode" in data:
        st["x2_loss_mode"] = bool(data["x2_loss_mode"])
        if st["x2_loss_mode"]: st["x2_mode"] = False
    if "x2_loss_limit" in data and data["x2_loss_limit"]: st["x2_loss_limit"] = int(data["x2_loss_limit"])
    if "target_profit" in data: st["target_profit"] = int(data["target_profit"]) if data["target_profit"] else None

    socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True, "state": public_state(st)})

@app.route("/api/stats")
def api_stats():
    sid = session.get("sid")
    return jsonify({"success": False}) if not sid or sid not in WEB_SESSIONS else jsonify({"success": True, "state": public_state(WEB_SESSIONS[sid])})

@app.route("/api/debug_api")
def api_debug_api():
    return jsonify({"ok": fetch_api_raw() is not None, "error": API_LAST_RAW.get("error"), "ts": API_LAST_RAW.get("ts"), "raw": API_LAST_RAW.get("data")})

@app.route("/api/reset_history", methods=["POST"])
def api_reset_history():
    sid = session.get("sid")
    if sid and sid in WEB_SESSIONS:
        st = WEB_SESSIONS[sid]
        st["history"], st["win_count"], st["lose_count"], st["profit_loss"] = [], 0, 0, 0
        socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    if sid in WS_CLIENTS:
        try: WS_CLIENTS[sid].disconnect()
        except Exception: pass
        del WS_CLIENTS[sid]
    if sid in WEB_SESSIONS: del WEB_SESSIONS[sid]
    session.pop("sid", None)
    return jsonify({"success": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
