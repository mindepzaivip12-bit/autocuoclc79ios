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
# CẤU HÌNH GAME
# ==========================================
API_LOGIN_URL   = "https://apifo88daigia.tele68.com/api"
API_LOBBY_URL   = "https://wlb.tele68.com/v1/lobby/auth/login"
API_HISTORY_URL = "https://apibetvipbominh.onrender.com/lc79md5"
GAME_WS_URL     = "wss://wtxmd52.tele68.com/txmd5/?token="
COMMON_PARAMS   = "cp=R&cl=R&pf=web"

# ==========================================
# 📌 LICENSE CONFIG
# ==========================================
LICENSE_SERVER_URL = os.environ.get("LICENSE_SERVER_URL", "https://lc79vipadmin-5orx.onrender.com").rstrip("/")
LICENSE_API_KEY   = os.environ.get("LICENSE_API_KEY", "").strip()
LICENSE_CACHE_TTL = 30

# 🚨 BẬT = true ĐỂ BỎ QUA LICENSE (TEST)
BYPASS_LICENSE = os.environ.get("BYPASS_LICENSE", "false").lower() == "true"

_LICENSE_CACHE = {}
_LICENSE_CACHE_LOCK = threading.Lock()
WEB_SESSIONS = {}
API_LAST_RAW = {"data": None, "ts": 0, "error": None}

# ==========================================
# 🔑 LICENSE HELPERS
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

def _cache_clear():
    with _LICENSE_CACHE_LOCK:
        _LICENSE_CACHE.clear()

def _request_with_retry(method, url, max_retries=3, timeout_per_try=30, **kwargs):
    """Retry 3 lần, chờ Render Free khởi động."""
    last_err = None
    for i in range(max_retries):
        try:
            logger.info(f"[LICENSE] {method} {url} (lần {i+1}/{max_retries})")
            r = requests.request(method, url, timeout=timeout_per_try, **kwargs)
            if r.status_code in (502, 503, 504):
                logger.warning(f"[LICENSE] Server đang khởi động ({r.status_code}), chờ 5s...")
                time.sleep(5)
                continue
            return r
        except requests.exceptions.Timeout:
            last_err = "Timeout"
            logger.warning(f"[LICENSE] Timeout lần {i+1}, chờ 5s...")
            time.sleep(5)
        except requests.exceptions.ConnectionError as e:
            last_err = f"ConnErr: {e}"
            logger.warning(f"[LICENSE] Lỗi kết nối lần {i+1}: {e}")
            time.sleep(5)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.error(f"[LICENSE] Lỗi: {e}")
            break
    logger.error(f"[LICENSE] Thất bại sau {max_retries} lần: {last_err}")
    return None

def license_check(key, fingerprint=None):
    key = (key or "").strip().upper()
    if not key: return {"ok": False, "valid": False, "message": "Thiếu key", "code": "NO_KEY"}
    if not LICENSE_SERVER_URL: return {"ok": False, "valid": False, "message": "Chưa cấu hình server key", "code": "SERVER_NOT_CONFIGURED"}

    cache_key = f"{key}|{fingerprint or '-'}"
    cached = _cache_get(cache_key)
    if cached: return cached

    params = {"key": key}
    if fingerprint: params["fingerprint"] = fingerprint
    
    r = _request_with_retry("GET", f"{LICENSE_SERVER_URL}/api/license/check",
                            params=params, headers=_license_headers(),
                            max_retries=3, timeout_per_try=30)
    if r is None:
        return {"ok": False, "valid": False, "message": "Server Key không phản hồi sau 3 lần thử. Thử lại sau 1 phút!", "code": "TIMEOUT"}
    
    if r.status_code == 404:
        return {"ok": False, "valid": False, "message": "API /api/license/check không tồn tại (404). Kiểm tra LICENSE_SERVER_URL!", "code": "API_NOT_FOUND"}
    if r.status_code == 403:
        return {"ok": False, "valid": False, "message": "Key bị từ chối (403). Có thể đã bị khoá!", "code": "FORBIDDEN"}
    if r.status_code == 401:
        return {"ok": False, "valid": False, "message": "Thiếu LICENSE_API_KEY (401).", "code": "UNAUTHORIZED"}
    if r.status_code >= 500:
        return {"ok": False, "valid": False, "message": f"Server Admin lỗi {r.status_code}.", "code": "SERVER_ERROR"}
    
    try:
        res = r.json() if r.text.strip().startswith("{") else {"ok": False, "raw": r.text[:200]}
    except Exception as e:
        return {"ok": False, "valid": False, "message": f"Response không hợp lệ: {e}", "code": "BAD_RESPONSE"}
    
    res.setdefault("ok", True)
    _cache_set(cache_key, res)
    return res

def license_activate(key, fingerprint, ip=None, ua=None):
    key = (key or "").strip().upper()
    if not key: return {"ok": False, "success": False, "message": "Thiếu key", "code": "NO_KEY"}
    
    payload = {"key": key, "fingerprint": fingerprint, "ip": ip, "ua": ua}
    r = _request_with_retry("POST", f"{LICENSE_SERVER_URL}/api/license/activate",
                            json=payload, headers=_license_headers(),
                            max_retries=3, timeout_per_try=30)
    if r is None:
        return {"ok": False, "success": False, "message": "Server Key không phản hồi sau 3 lần thử!", "code": "TIMEOUT"}
    
    if r.status_code == 404:
        return {"ok": False, "success": False, "message": "API /api/license/activate không tồn tại (404).", "code": "API_NOT_FOUND"}
    if r.status_code >= 500:
        return {"ok": False, "success": False, "message": f"Server Admin lỗi {r.status_code}.", "code": "SERVER_ERROR"}
    
    try:
        data = r.json() if r.text.strip().startswith("{") else {}
    except Exception:
        data = {}
    
    if r.status_code in (200, 201):
        data.setdefault("ok", True)
        data.setdefault("success", True)
        _cache_clear()
        return data
    data.setdefault("ok", False)
    data.setdefault("success", False)
    data.setdefault("message", data.get("error") or f"HTTP {r.status_code}")
    return data

def _is_license_valid(res):
    if not isinstance(res, dict) or not res.get("ok", False): return False
    if res.get("revoked") or res.get("expired") or res.get("valid") is False: return False
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

def _client_ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown")
def _client_ua(): return request.headers.get("User-Agent", "unknown")
def _device_fingerprint(ip, ua):
    return hashlib.sha256(f"{ip or 'unknown'}|{ua or 'unknown'}".encode()).hexdigest()[:32]

# ==========================================
# GAME HELPERS
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
    if not data: return {"side": None, "conf": None, "ready": False}
    side = normalize_side(data.get("du_doan"))
    return {"side": side, "conf": data.get("do_tin_cay"), "ready": side is not None}

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
    except Exception as e:
        return {"_error": f"Lỗi kết nối Game: {e}"}

def public_state(st):
    return {
        "nickname": st.get("nickname", ""), "balance": st.get("balance", 0),
        "profit_loss": st.get("profit_loss", 0), "auto_bet_enabled": st.get("auto_bet_enabled", False),
        "base_bet_amount": st.get("base_bet_amount", 10000), "current_bet": st.get("current_bet", 10000),
        "current_prediction": st.get("current_prediction"), "session_id": st.get("session_id"),
        "win_count": st.get("win_count", 0), "lose_count": st.get("lose_count", 0),
        "socket_connected": st.get("socket_connected", False), "history": st.get("history", [])
    }

# ==========================================
# 🚀 GAME SOCKET WORKER
# ==========================================
def game_socket_worker(sid, jwt):
    st = WEB_SESSIONS.get(sid)
    if not st: return
    retry = 0
    while retry < 5:
        try:
            logger.info(f"[{sid}] Kết nối Game WS (lần {retry+1})...")
            headers = {"User-Agent": "Mozilla/5.0", "Origin": "https://tele68.com"}
            ws = websocket.create_connection(f"{GAME_WS_URL}{jwt}", timeout=20, header=headers)
            logger.info(f"[{sid}] ✅ Game WS OK!")
            st["socket_connected"] = True
            socketio.emit("stats_update", public_state(st), to=sid)
            socketio.emit("toast", {"type": "success", "msg": "Game: Đã kết nối"}, to=sid)
            retry = 0
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
                    socketio.emit("session_update", {
                        "session_id": st["session_id"], "prediction": pred["side"],
                        "conf": pred["conf"], "ready": pred["ready"], "current_bet": st["current_bet"]
                    }, to=sid)
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
                    if st.get("has_bet_this_session"):
                        if st.get("current_prediction") == res_side:
                            is_win = True
                            st["profit_loss"] += int(st["current_bet"] * 0.98)
                            st["win_count"] += 1
                        else:
                            st["profit_loss"] -= int(st["current_bet"])
                            st["lose_count"] += 1
                    st["history"].insert(0, {
                        "session": payload.get("id"), "pred": st.get("current_prediction"),
                        "bet": st["current_bet"], "result": res_side, "win": is_win
                    })
                    st["has_bet_this_session"] = False
                    socketio.emit("result_update", {"balance": st["balance"], "profit_loss": st["profit_loss"], "history": st["history"][:15]}, to=sid)
                    socketio.emit("stats_update", public_state(st), to=sid)
        except Exception as e:
            logger.error(f"[{sid}] ❌ Lỗi Socket: {type(e).__name__} - {e}")
            st["socket_connected"] = False
            socketio.emit("stats_update", public_state(st), to=sid)
            retry += 1
            time.sleep(3)

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

    if not username or not password:
        return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"}), 400
    if not key:
        return jsonify({"success": False, "error": "Vui lòng nhập KEY truy cập", "code": "NO_KEY"}), 400

    # 1. CHECK LICENSE
    if BYPASS_LICENSE:
        logger.warning("⚠️ BYPASS_LICENSE=True - Bỏ qua kiểm tra Key!")
        expires = _now_ts() + 86400*30
        left = 86400*30
    elif LICENSE_SERVER_URL:
        ip, ua = _client_ip(), _client_ua()
        fp = _device_fingerprint(ip, ua)
        
        act_res = license_activate(key, fp, ip=ip, ua=ua)
        if act_res.get("code") == "API_NOT_FOUND":
            return jsonify({"success": False, "error": "❌ Server Admin đã đổi API License (404). Liên hệ Admin cập nhật URL!", "code": "API_NOT_FOUND"}), 404
        if act_res.get("code") == "TIMEOUT":
            return jsonify({"success": False, "error": "⏳ Server Admin đang khởi động. Đợi 1 phút rồi thử lại!", "code": "TIMEOUT"}), 503
        
        chk = license_check(key, fp)
        if chk.get("code") in ("API_NOT_FOUND", "TIMEOUT"):
            return jsonify({"success": False, "error": chk.get("message") or "Lỗi server Admin", "code": chk.get("code")}), 503
        
        if not _is_license_valid(chk):
            err = _license_msg(chk) if chk.get("ok") else _license_msg(act_res)
            return jsonify({"success": False, "error": err or "Key không hợp lệ", "code": "KEY_INVALID"}), 403
        
        expires = chk.get("expires_at")
        left = _license_time_left(chk)
    else:
        expires = _now_ts() + 86400*30
        left = 86400*30

    # 2. LOGIN GAME
    res = login_game(username, password)
    if "_error" in res:
        return jsonify({"success": False, "error": res["_error"]}), 401

    # 3. TẠO SESSION
    sid = os.urandom(8).hex()
    session["sid"] = sid
    WEB_SESSIONS[sid] = {
        "nickname": res["nickname"], "balance": res["money"], "username": username,
        "profit_loss": 0, "auto_bet_enabled": False, "base_bet_amount": 10000, "current_bet": 10000,
        "current_prediction": None, "has_bet_this_session": False, "session_id": None,
        "win_count": 0, "lose_count": 0, "socket_connected": False, "history": []
    }
    socketio.start_background_task(game_socket_worker, sid, res["token"])
    return jsonify({"success": True, "sid": sid, "nickname": res["nickname"],
                    "balance": res["money"], "license_expires_at": expires, "license_time_left": left})

@app.route("/api/stats")
def api_stats():
    sid = session.get("sid")
    if not sid or sid not in WEB_SESSIONS:
        return jsonify({"success": False, "error": "Phiên hết hạn"}), 401
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
