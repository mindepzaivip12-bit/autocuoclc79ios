import eventlet
eventlet.monkey_patch() # Bắt buộc để tránh lỗi recursion

import os, json, time, base64, hashlib, threading, logging, random
import requests
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO
from socketio import Client as SocketClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'lc79-secret-2024')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ==========================================
# CẤU HÌNH API / ENDPOINT
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://leminhdzctemd5.onrender.com/lc79md5" # API mới của bạn
GAME_WS_URL     = "https://wtxmd52.tele68.com"
GAME_WS_PATH    = "txmd5/"
GAME_WS_NS      = "/txmd5"
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

# ==========================================
# DỮ LIỆU TOÀN CỤC
# ==========================================
GLOBAL_HISTORY = []
MAX_GLOBAL_HISTORY = 2000
WEB_SESSIONS = {}       
WS_CLIENTS = {}         

# ==========================================
# API DATA WORKER (Poll dữ liệu từ API của bạn)
# ==========================================
def api_data_worker():
    logger.info("API data worker started")
    while True:
        try:
            url = f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}"
            r = requests.get(url, timeout=5, headers={"Cache-Control":"no-store","User-Agent":"Mozilla/5.0"})
            data = r.json()
            
            # API mới trả về một dict duy nhất, không phải list
            session_id = data.get("phien")
            result_str = data.get("ket_qua", "").lower() # Ví dụ: "tài 4-6-5"
            
            if session_id and result_str:
                # Xác định Tài/Xỉu
                side = "Tài" if "tài" in result_str else ("Xỉu" if "xỉu" in result_str else None)
                
                # Trích xuất xúc xắc từ chuỗi (nếu có)
                dices = []
                try:
                    parts = result_str.split()
                    if len(parts) > 1:
                        dices = [int(x) for x in parts[1].split('-')]
                except:
                    pass

                if side:
                    # Cập nhật lịch sử toàn cục (tránh trùng lặp phiên)
                    if not GLOBAL_HISTORY or GLOBAL_HISTORY[-1]["session"] != session_id:
                        GLOBAL_HISTORY.append({
                            "session": session_id,
                            "dice": dices,
                            "total": sum(dices) if dices else 0,
                            "side": side,
                        })
                        # Giữ giới hạn bộ nhớ
                        if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY:
                            GLOBAL_HISTORY.pop(0)

        except Exception as e:
            logger.error(f"API Worker Error: {e}")
        
        time.sleep(2) # Cứ 2 giây gọi API một lần

threading.Thread(target=api_data_worker, daemon=True).start()

# ==========================================
# THUẬT TOÁN DỰ ĐOÁN (Dựa trên API của bạn)
# ==========================================
def get_prediction_from_api():
    """
    Hàm này lấy dự đoán trực tiếp từ API của bạn thay vì tự tính toán
    """
    try:
        r = requests.get(API_HISTORY_URL, timeout=5)
        data = r.json()
        
        du_doan = data.get("du_doan") # "Tài" hoặc "Xỉu"
        do_tin_cay = data.get("do_tin_cay", "0%") # "90,0%"
        
        # Xử lý độ tin cậy (bỏ dấu % và đổi dấu phẩy thành dấu chấm)
        conf = 50
        if do_tin_cay:
            try:
                conf = float(do_tin_cay.replace("%", "").replace(",", "."))
            except:
                pass

        if du_doan:
            return {"side": du_doan, "conf": int(conf), "ready": True}
    except:
        pass
    
    # Nếu API lỗi, trả về mặc định
    return {"side": random.choice(["Tài","Xỉu"]), "conf": 50, "ready": False}

# ==========================================
# LOGIN FLOW
# ==========================================
def md5_hash(t): return hashlib.md5(t.encode()).hexdigest()

def login_game(username, password):
    try:
        pw = md5_hash(password)
        url = f"{API_LOGIN_URL}?c=3&un={username}&pw={pw}&{COMMON_PARAMS}&at="
        
        sess = requests.Session()
        r = sess.get(url, timeout=12)
        r.raise_for_status()
        data = r.json()
        
        if not data.get("success"):
            return {"_error": data.get("message", "Sai thông tin đăng nhập")}

        sk = data["sessionKey"]
        sk += "=" * ((4 - len(sk) % 4) % 4)
        sk_data = json.loads(base64.b64decode(sk).decode("utf-8"))
        nickname = sk_data.get("nickname") or sk_data.get("nickName")

        access_token = data["accessToken"]
        r2 = sess.post(
            f"{API_LOBBY_URL}?{COMMON_PARAMS}&at=",
            headers={"content-type":"application/json","authority":"wlb.tele68.com"},
            json={"nickName": nickname, "accessToken": access_token},
            timeout=12,
        )
        lobby = r2.json()
        jwt = lobby.get("token")
        if not jwt:
            return {"_error": "Lobby không trả về token"}

        money = lobby.get("remoteLoginResp", {}).get("money", 0)
        return {"token": jwt, "nickname": nickname, "money": money}
    except Exception as e:
        logger.error(f"Login error: {e}")
        return {"_error": f"Lỗi kết nối: {e}"}

# ==========================================
# GAME WEBSOCKET WORKER
# ==========================================
def game_socket_worker(sid, jwt_token):
    st = WEB_SESSIONS.get(sid)
    if not st: return

    sio = SocketClient(reconnection=True, reconnection_attempts=20,
                       logger=False, engineio_logger=False)
    WS_CLIENTS[sid] = sio

    @sio.event(namespace=GAME_WS_NS)
    def connect():
        logger.info(f"[{sid}] game socket connected")
        st["socket_connected"] = True
        socketio.emit("toast", {"type":"success","msg":"Đã kết nối socket game"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def disconnect():
        st["socket_connected"] = False
        socketio.emit("toast", {"type":"error","msg":"Mất kết nối socket game"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        st["has_bet_this_session"] = False
        st["session_id"] = data.get("id", "N/A")

        # Target check
        if st["auto_bet_enabled"] and st["target_profit"]:
            if st["profit_loss"] >= st["target_profit"]:
                st["auto_bet_enabled"] = False
                socketio.emit("toast", {"type":"success",
                    "msg": f"🏆 Chốt lãi! +{st['profit_loss']:,}"}, to=sid)

        # Tính tiền cược
        cur_bet = st["base_bet_amount"]
        if st["x2_mode"] and st["win_streak"] >= 1:
            cur_bet = st["base_bet_amount"] * 2
        elif st["x2_loss_mode"] and st["loss_streak"] >= 1:
            if st["loss_streak"] <= st["x2_loss_limit"]:
                cur_bet = st["base_bet_amount"] * (2 ** st["loss_streak"])
            else:
                cur_bet = st["base_bet_amount"]
        st["current_bet"] = cur_bet

        # LẤY DỰ ĐOÁN TỪ API BÊN NGOÀI
        pred_res = get_prediction_from_api()
        st["current_prediction"] = pred_res["side"]
        st["last_pred_detail"] = pred_res

        socketio.emit("session_update", {
            "session_id": st["session_id"],
            "prediction": pred_res["side"],
            "conf": pred_res["conf"],
            "ready": pred_res["ready"],
            "history_len": len(GLOBAL_HISTORY),
            "current_bet": cur_bet,
            "auto_bet_enabled": st["auto_bet_enabled"],
        }, to=sid)

    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick_update(data):
        if data.get("state") != "BETTING": return
        if not st["auto_bet_enabled"]: return
        if not st["current_prediction"]: return
        if st["has_bet_this_session"]: return

        bet_type = "TAI" if st["current_prediction"] == "Tài" else "XIU"
        sio.emit("bet", {"type": bet_type, "amount": st["current_bet"]},
                 namespace=GAME_WS_NS)
        st["has_bet_this_session"] = True
        st["waiting_for_result"] = True
        socketio.emit("toast", {"type":"info",
            "msg": f"🚀 Cược {st['current_bet']:,} vào {st['current_prediction'].upper()}"},
            to=sid)

    @sio.on("bet-result", namespace=GAME_WS_NS)
    def on_bet_result(data):
        if "postBalance" in data:
            st["balance"] = data["postBalance"]
            socketio.emit("stats_update", public_state(st), to=sid)
        try: sio.emit("get-current-my-info", None, namespace=GAME_WS_NS)
        except: pass

    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_session_result(data):
        result = data.get("resultTruyenThong", "N/A")
        dices = data.get("dices", [0,0,0])
        pred = st.get("current_prediction")
        is_win = None

        if pred:
            pred_tx = "TAI" if pred == "Tài" else "XIU"
            is_win = (pred_tx == result)
            if st["waiting_for_result"]:
                if is_win:
                    win_amt = int(st["current_bet"] * 0.98)
                    st["profit_loss"] += win_amt
                    st["win_streak"] += 1
                    st["loss_streak"] = 0
                    st["win_count"] += 1
                else:
                    st["profit_loss"] -= st["current_bet"]
                    st["win_streak"] = 0
                    st["loss_streak"] += 1
                    st["lose_count"] += 1
                st["waiting_for_result"] = False

            st["history"].insert(0, {
                "session": data.get("id") or st["session_id"],
                "pred": pred.upper(),
                "bet": st["current_bet"],
                "result": "TÀI" if result == "TAI" else ("XỈU" if result == "XIU" else "?"),
                "dice": dices,
                "win": is_win,
            })
            st["history"] = st["history"][:30]

        socketio.emit("result_update", {
            "result": result, "dices": dices,
            "is_win": is_win, "history": st["history"],
        }, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    try:
        sio.connect(
            GAME_WS_URL,
            socketio_path=GAME_WS_PATH,
            namespaces=[GAME_WS_NS],
            transports=["websocket"],
            auth={"token": jwt_token},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        sio.wait()
    except Exception as e:
        logger.error(f"[{sid}] socket error: {e}")
        st["socket_connected"] = False
        socketio.emit("toast", {"type":"error","msg":f"Socket lỗi: {e}"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

# ==========================================
# HELPERS
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
        "target_profit": st["target_profit"],
        "current_prediction": st["current_prediction"],
        "session_id": st["session_id"],
        "win_count": st["win_count"],
        "lose_count": st["lose_count"],
        "win_streak": st["win_streak"],
        "loss_streak": st["loss_streak"],
        "socket_connected": st["socket_connected"],
        "history": st["history"][:15],
    }

# ==========================================
# ROUTES
# ==========================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})

    res = login_game(username, password)
    if "_error" in res:
        return jsonify({"success": False, "error": res["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    WEB_SESSIONS[sid] = {
        "nickname": res["nickname"],
        "balance": res["money"],
        "token": res["token"],
        "username": username,
        "profit_loss": 0,
        "auto_bet_enabled": False,
        "x2_mode": False,
        "x2_loss_mode": True,
        "x2_loss_limit": 5,
        "win_streak": 0,
        "loss_streak": 0,
        "base_bet_amount": 10000,
        "current_bet": 10000,
        "target_profit": None,
        "current_prediction": None,
        "waiting_for_result": False,
        "has_bet_this_session": False,
        "session_id": None,
        "last_pred_detail": {},
        "win_count": 0,
        "lose_count": 0,
        "socket_connected": False,
        "history": [],
    }

    threading.Thread(target=game_socket_worker, args=(sid, res["token"]), daemon=True).start()

    return jsonify({
        "success": True,
        "sid": sid,
        "nickname": res["nickname"],
        "balance": res["money"],
    })

@app.route("/api/config", methods=["POST"])
def api_config():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS:
        return jsonify({"success": False, "error": "Chưa login"})
    st = WEB_SESSIONS[sid]
    data = request.json or {}

    if "betAmount" in data and data["betAmount"]:
        st["base_bet_amount"] = int(data["betAmount"])
    if "auto_bet_enabled" in data:
        st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
    if "x2_mode" in data:
        st["x2_mode"] = bool(data["x2_mode"])
        if st["x2_mode"]: st["x2_loss_mode"] = False
    if "x2_loss_mode" in data:
        st["x2_loss_mode"] = bool(data["x2_loss_mode"])
        if st["x2_loss_mode"]: st["x2_mode"] = False
    if "x2_loss_limit" in data and data["x2_loss_limit"]:
        st["x2_loss_limit"] = int(data["x2_loss_limit"])
    if "target_profit" in data:
        tp = data["target_profit"]
        st["target_profit"] = int(tp) if tp else None

    return jsonify({"success": True, "state": public_state(st)})

@app.route("/api/stats")
def api_stats():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS:
        return jsonify({"success": False})
    return jsonify({"success": True, "state": public_state(WEB_SESSIONS[sid])})

@app.route("/api/reset_history", methods=["POST"])
def api_reset_history():
    sid = session.get("sid")
    if sid and sid in WEB_SESSIONS:
        st = WEB_SESSIONS[sid]
        st["history"] = []
        st["win_count"] = 0
        st["lose_count"] = 0
        st["profit_loss"] = 0
        socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    if sid in WS_CLIENTS:
        try: WS_CLIENTS[sid].disconnect()
        except: pass
        del WS_CLIENTS[sid]
    if sid in WEB_SESSIONS:
        del WEB_SESSIONS[sid]
    session.pop("sid", None)
    return jsonify({"success": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
