import eventlet
eventlet.monkey_patch()

import os, json, time, base64, hashlib, logging, random, threading
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

# ==========================================
# GLOBAL DATA
# ==========================================
GLOBAL_HISTORY = []
MAX_GLOBAL_HISTORY = 2000
GLOBAL_HISTORY_LOCK = threading.Lock()

WEB_SESSIONS = {}
WS_CLIENTS   = {}

PREDICTION_CACHE = {"data": None, "ts": 0}
PREDICTION_CACHE_TTL = 3

# ==========================================
# PARSE RESULT — chấp nhận nhiều format
# ==========================================
def parse_result_side(result_raw):
    """Trả về 'TAI' / 'XIU' / None từ nhiều format khác nhau"""
    if not result_raw:
        return None
    s = str(result_raw).strip().upper()
    if s in ("TAI", "TÀI", "T"):
        return "TAI"
    if s in ("XIU", "XỈU", "X"):
        return "XIU"
    if "TÀI" in s or "TAI" in s:
        return "TAI"
    if "XỈU" in s or "XIU" in s:
        return "XIU"
    try:
        nums = [int(x) for x in s.replace("-", " ").replace(",", " ").split() if x.isdigit()]
        if len(nums) >= 3:
            total = sum(nums[:3])
            return "TAI" if total >= 11 else "XIU"
    except Exception:
        pass
    return None

# ==========================================
# API DATA WORKER
# ==========================================
def api_data_worker():
    logger.info("[API Worker] started")
    last_session = None
    while True:
        try:
            url = f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}"
            r = requests.get(url, timeout=5,
                             headers={"Cache-Control": "no-store",
                                      "User-Agent": "Mozilla/5.0"})
            data = r.json()

            session_id = data.get("phien")
            result_str = (data.get("ket_qua") or "").lower()
            du_doan    = data.get("du_doan")
            do_tin_cay = data.get("do_tin_cay", "0%")

            conf = 50
            try:
                conf = float(str(do_tin_cay).replace("%", "").replace(",", "."))
            except Exception:
                pass

            if du_doan:
                PREDICTION_CACHE["data"] = {
                    "side": du_doan.strip().capitalize(),
                    "conf": int(conf),
                    "ready": True,
                }
                PREDICTION_CACHE["ts"] = time.time()

            if session_id and result_str:
                side = None
                if "tài" in result_str or "tai" in result_str:
                    side = "Tài"
                elif "xỉu" in result_str or "xiu" in result_str:
                    side = "Xỉu"

                dices = []
                try:
                    parts = result_str.split()
                    if len(parts) > 1:
                        dices = [int(x) for x in parts[1].split("-")]
                except Exception:
                    pass

                if side and session_id != last_session:
                    with GLOBAL_HISTORY_LOCK:
                        exists = any(h["session"] == session_id for h in GLOBAL_HISTORY[-5:])
                        if not exists:
                            GLOBAL_HISTORY.append({
                                "session": session_id,
                                "dice": dices,
                                "total": sum(dices) if dices else 0,
                                "side": side,
                                "ts": time.time(),
                            })
                            if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY:
                                GLOBAL_HISTORY.pop(0)
                            logger.info(f"[API Worker] New session {session_id}: {side} {dices}")
                    last_session = session_id

        except Exception as e:
            logger.error(f"[API Worker] {e}")

        socketio.sleep(2)

socketio.start_background_task(api_data_worker)

# ==========================================
# DỰ ĐOÁN
# ==========================================
def get_prediction():
    if PREDICTION_CACHE["data"] and (time.time() - PREDICTION_CACHE["ts"]) < PREDICTION_CACHE_TTL:
        return PREDICTION_CACHE["data"]

    try:
        r = requests.get(API_HISTORY_URL, timeout=4,
                         headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        du_doan = data.get("du_doan")
        do_tin_cay = data.get("do_tin_cay", "50%")
        if du_doan:
            conf = 50
            try:
                conf = float(str(do_tin_cay).replace("%", "").replace(",", "."))
            except Exception:
                pass
            result = {"side": du_doan.strip().capitalize(), "conf": int(conf), "ready": True}
            PREDICTION_CACHE["data"] = result
            PREDICTION_CACHE["ts"] = time.time()
            return result
    except Exception as e:
        logger.warning(f"[Prediction] API fail: {e}")

    with GLOBAL_HISTORY_LOCK:
        recent = GLOBAL_HISTORY[-10:]

    if len(recent) >= 5:
        sides = [h["side"] for h in recent]
        tai_cnt = sides.count("Tài")
        xiu_cnt = sides.count("Xỉu")
        if len(sides) >= 4 and sides[-1] == sides[-2] == sides[-3] == sides[-4]:
            side = "Xỉu" if sides[-1] == "Tài" else "Tài"
        else:
            side = "Tài" if tai_cnt < xiu_cnt else "Xỉu"
        return {"side": side, "conf": 55, "ready": True}

    return {"side": random.choice(["Tài", "Xỉu"]), "conf": 50, "ready": False}

# ==========================================
# LOGIN
# ==========================================
def md5_hash(t): return hashlib.md5(t.encode()).hexdigest()

def login_game(username, password):
    try:
        pw = md5_hash(password)
        url = f"{API_LOGIN_URL}?c=3&un={username}&pw={pw}&{COMMON_PARAMS}&at="
        sess = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://tele68.com",
            "Referer": "https://tele68.com/",
        }
        r = sess.get(url, timeout=12, headers=headers)
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
            headers={"content-type": "application/json",
                     "authority": "wlb.tele68.com", **headers},
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
        logger.error(f"[Login] {e}")
        return {"_error": f"Lỗi kết nối: {e}"}

# ==========================================
# TÍNH TIỀN CƯỢC — KHÔNG reset về 1k
# ==========================================
def calc_next_bet(st):
    base = int(st["base_bet_amount"])
    if st["x2_mode"] and st["win_streak"] >= 1:
        return base * (2 ** min(st["win_streak"], 10))
    if st["x2_loss_mode"] and st["loss_streak"] >= 1:
        if st["loss_streak"] <= st["x2_loss_limit"]:
            return base * (2 ** st["loss_streak"])
        return base
    return base

# ==========================================
# GAME SOCKET WORKER
# ==========================================
def game_socket_worker(sid, jwt_token):
    st = WEB_SESSIONS.get(sid)
    if not st:
        return

    logger.info(f"[{sid}] Initializing game socket...")
    sio = SocketClient(reconnection=True, reconnection_attempts=100,
                       reconnection_delay=2, logger=False, engineio_logger=False)
    WS_CLIENTS[sid] = sio

    def check_target_profit():
        if (st["auto_bet_enabled"] and st["target_profit"]
                and st["profit_loss"] >= st["target_profit"]):
            st["auto_bet_enabled"] = False
            socketio.emit("toast", {
                "type": "success",
                "msg": f"🏆 CHỐT LÃI! +{st['profit_loss']:,}đ — Auto đã tắt"
            }, to=sid)
            socketio.emit("stats_update", public_state(st), to=sid)
            return True
        return False

    # ---- CONNECT ----
    @sio.event(namespace=GAME_WS_NS)
    def connect():
        logger.info(f"[{sid}] ✅ Game socket CONNECTED")
        st["socket_connected"] = True
        socketio.emit("toast", {"type": "success", "msg": "Đã kết nối socket game"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def connect_error(data):
        logger.error(f"[{sid}] ❌ CONNECT ERROR: {data}")
        st["socket_connected"] = False
        socketio.emit("toast", {"type": "error", "msg": f"Lỗi kết nối: {data}"}, to=sid)

    @sio.event(namespace=GAME_WS_NS)
    def disconnect():
        logger.warning(f"[{sid}] ❌ DISCONNECTED")
        st["socket_connected"] = False
        socketio.emit("stats_update", public_state(st), to=sid)

    # ---- NEW SESSION ----
    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        new_id = data.get("id") or data.get("sessionId") or "N/A"
        logger.info(f"[{sid}] 🆕 New session: {new_id}")

        st["session_id"] = new_id
        st["has_bet_this_session"] = False
        st["waiting_for_result"] = False

        if check_target_profit():
            return

        st["current_bet"] = calc_next_bet(st)
        pred = get_prediction()
        st["current_prediction"] = pred["side"]

        socketio.emit("session_update", {
            "session_id": new_id,
            "prediction": pred["side"],
            "conf": pred["conf"],
            "ready": pred["ready"],
            "history_len": len(GLOBAL_HISTORY),
            "current_bet": st["current_bet"],
            "auto_bet_enabled": st["auto_bet_enabled"],
        }, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    # ---- TICK UPDATE ----
    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick_update(data):
        if data.get("state") != "BETTING":
            return
        if not st["auto_bet_enabled"]:
            return
        if st["has_bet_this_session"]:
            return
        if not st["current_prediction"]:
            return
        if not st["session_id"]:
            return

        bet_type = "TAI" if st["current_prediction"] == "Tài" else "XIU"
        try:
            sio.emit("bet", {"type": bet_type, "amount": st["current_bet"]},
                     namespace=GAME_WS_NS)
            st["has_bet_this_session"] = True
            st["waiting_for_result"] = True
            logger.info(f"[{sid}] 🚀 BET {st['current_bet']:,} → {bet_type} (session {st['session_id']})")
            socketio.emit("toast", {
                "type": "info",
                "msg": f"🚀 Cược {st['current_bet']:,}đ vào {st['current_prediction'].upper()}"
            }, to=sid)
        except Exception as e:
            logger.error(f"[{sid}] Bet error: {e}")

    # ---- BET RESULT ----
    @sio.on("bet-result", namespace=GAME_WS_NS)
    def on_bet_result(data):
        if "postBalance" in data:
            st["balance"] = data["postBalance"]
            socketio.emit("stats_update", public_state(st), to=sid)
        try:
            sio.emit("get-current-my-info", None, namespace=GAME_WS_NS)
        except Exception:
            pass

    # ---- SESSION RESULT — nhận diện thắng thua NGAY ----
    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_session_result(data):
        result_raw = (data.get("resultTruyenThong")
                      or data.get("result")
                      or data.get("resultString"))
        dices = data.get("dices") or data.get("dice") or [0, 0, 0]
        session_of_result = data.get("id") or st.get("session_id")

        result_side = parse_result_side(result_raw)

        if result_side is None and dices and len(dices) >= 3:
            try:
                total = sum(int(x) for x in dices[:3])
                result_side = "TAI" if total >= 11 else "XIU"
            except Exception:
                pass

        pred = st.get("current_prediction")
        is_win = None
        profit_delta = 0

        if pred and result_side:
            pred_key = "TAI" if pred == "Tài" else "XIU"
            is_win = (pred_key == result_side)

            if st["waiting_for_result"]:
                bet_amt = int(st["current_bet"])
                if is_win:
                    profit_delta = int(bet_amt * 0.98)
                    st["profit_loss"] += profit_delta
                    st["win_streak"] += 1
                    st["loss_streak"] = 0
                    st["win_count"] += 1
                else:
                    profit_delta = -bet_amt
                    st["profit_loss"] += profit_delta
                    st["win_streak"] = 0
                    st["loss_streak"] += 1
                    st["lose_count"] += 1
                st["waiting_for_result"] = False
                st["balance"] = st["balance"] + profit_delta

            st["history"].insert(0, {
                "session": session_of_result,
                "pred": pred.upper(),
                "bet": st["current_bet"],
                "result": result_side,
                "dice": dices,
                "win": is_win,
            })
            st["history"] = st["history"][:30]

        logger.info(f"[{sid}] 📊 Result {session_of_result}: {result_side} "
                    f"| pred={pred} | win={is_win} | profit={st['profit_loss']:,}")

        socketio.emit("result_update", {
            "session": session_of_result,
            "pred": pred.upper() if pred else None,
            "result": result_side or "?",
            "dices": dices,
            "is_win": is_win,
            "bet": st["current_bet"],
            "balance": st["balance"],
            "profit_loss": st["profit_loss"],
            "profit_delta": profit_delta,
            "history": st["history"][:15],
        }, to=sid)

        socketio.emit("stats_update", public_state(st), to=sid)
        check_target_profit()

    # ---- CONNECT ----
    try:
        logger.info(f"[{sid}] Calling sio.connect()...")
        connect_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://tele68.com",
            "Referer": "https://tele68.com/",
        }
        connect_url = f"{GAME_WS_URL}?token={jwt_token}"
        sio.connect(
            connect_url,
            socketio_path=GAME_WS_PATH,
            namespaces=[GAME_WS_NS],
            headers=connect_headers,
            auth={"token": jwt_token},
            transports=["websocket"],
            wait_timeout=15,
        )
        logger.info(f"[{sid}] Connected, waiting...")
        sio.wait()
    except Exception as e:
        logger.error(f"[{sid}] ❌ SOCKET ERROR: {type(e).__name__} - {e}")
        st["socket_connected"] = False
        socketio.emit("toast", {"type": "error", "msg": f"Socket lỗi: {e}"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

# ==========================================
# PUBLIC STATE
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
# BACKGROUND: đồng bộ stats định kỳ
# ==========================================
def stats_broadcast_worker():
    while True:
        try:
            for sid, st in list(WEB_SESSIONS.items()):
                try:
                    socketio.emit("stats_update", public_state(st), to=sid)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[Stats Worker] {e}")
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
        "win_count": 0,
        "lose_count": 0,
        "socket_connected": False,
        "history": [],
    }

    socketio.start_background_task(game_socket_worker, sid, res["token"])

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

    # === FIX: giữ nguyên số tiền user nhập ===
    if "betAmount" in data:
        try:
            new_amt = int(data["betAmount"])
            if new_amt >= 1000:
                st["base_bet_amount"] = new_amt
                st["current_bet"] = new_amt
        except (TypeError, ValueError):
            pass

    if "auto_bet_enabled" in data:
        st["auto_bet_enabled"] = bool(data["auto_bet_enabled"])
        logger.info(f"[{sid}] Auto: {st['auto_bet_enabled']}")
    if "x2_mode" in data:
        st["x2_mode"] = bool(data["x2_mode"])
        if st["x2_mode"]:
            st["x2_loss_mode"] = False
    if "x2_loss_mode" in data:
        st["x2_loss_mode"] = bool(data["x2_loss_mode"])
        if st["x2_loss_mode"]:
            st["x2_mode"] = False
    if "x2_loss_limit" in data and data["x2_loss_limit"]:
        st["x2_loss_limit"] = int(data["x2_loss_limit"])
    if "target_profit" in data:
        tp = data["target_profit"]
        st["target_profit"] = int(tp) if tp else None

    socketio.emit("stats_update", public_state(st), to=sid)
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
        try:
            WS_CLIENTS[sid].disconnect()
        except Exception:
            pass
        del WS_CLIENTS[sid]
    if sid in WEB_SESSIONS:
        del WEB_SESSIONS[sid]
    session.pop("sid", None)
    return jsonify({"success": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
