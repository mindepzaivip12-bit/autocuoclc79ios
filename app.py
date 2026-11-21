import eventlet
eventlet.monkey_patch()

import os, json, time, base64, hashlib, logging, threading, re, secrets
import requests
from datetime import datetime, timedelta
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
# 📌 LICENSE SERVER CONFIG (TỪ XA)
# ==========================================
LICENSE_SERVER_URL = os.environ.get(
    "LICENSE_SERVER_URL",
    "https://license-server-cua-ban.onrender.com"   # ← ĐỔI URL SERVER KEY CỦA BẠN
).rstrip("/")
LICENSE_API_KEY   = os.environ.get("LICENSE_API_KEY", "").strip()
LICENSE_CACHE_TTL = 30   # giây — cache status để giảm request server

# Cache: key -> {"data": {...}, "ts": epoch}
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
# 🔑 LICENSE CLIENT — GỌI SERVER TỪ XA
# ==========================================
def _license_headers():
    h = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "User-Agent": "BotClient/1.0",
    }
    if LICENSE_API_KEY:
        h["X-Api-Key"] = LICENSE_API_KEY
        h["Authorization"] = f"Bearer {LICENSE_API_KEY}"
    return h

def _now_ts():
    return int(time.time())

def _cache_get(key):
    with _LICENSE_CACHE_LOCK:
        item = _LICENSE_CACHE.get(key)
    if not item:
        return None
    if _now_ts() - item["ts"] > LICENSE_CACHE_TTL:
        return None
    return item["data"]

def _cache_set(key, data):
    with _LICENSE_CACHE_LOCK:
        _LICENSE_CACHE[key] = {"data": data, "ts": _now_ts()}

def _cache_clear(key=None):
    with _LICENSE_CACHE_LOCK:
        if key:
            _LICENSE_CACHE.pop(key, None)
        else:
            _LICENSE_CACHE.clear()

def license_check(key, fingerprint=None):
    """
    Kiểm tra key với server. Trả dict:
      {ok, valid, expired, revoked, expires_at, time_left, max_devices,
       devices, message, code}
    """
    key = (key or "").strip().upper()
    if not key:
        return {"ok": False, "valid": False, "expired": False, "revoked": False,
                "message": "Thiếu key", "code": "NO_KEY"}

    # cache cho key + fingerprint (nếu có bind)
    cache_key = f"{key}|{fingerprint or '-'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        params = {"key": key}
        if fingerprint:
            params["fingerprint"] = fingerprint
        r = requests.get(
            f"{LICENSE_SERVER_URL}/api/license/check",
            params=params,
            headers=_license_headers(),
            timeout=6,
        )
        if r.status_code == 404:
            res = {"ok": False, "valid": False, "expired": False, "revoked": False,
                   "message": "Key không tồn tại", "code": "NOT_FOUND"}
        else:
            r.raise_for_status()
            res = r.json() if r.text.strip().startswith("{") else {"raw": r.text}
            res.setdefault("ok", True)
    except Exception as e:
        logger.error(f"[License] Check fail: {e}")
        return {"ok": False, "valid": False, "expired": False, "revoked": False,
                "message": f"Không kết nối được server key: {e}", "code": "SERVER_ERROR"}

    _cache_set(cache_key, res)
    return res

def license_activate(key, fingerprint, ip=None, ua=None):
    """
    Kích hoạt key + bind thiết bị với server.
    Server chịu trách nhiệm enforce 1 key = N thiết bị.
    """
    key = (key or "").strip().upper()
    if not key:
        return {"ok": False, "success": False, "message": "Thiếu key", "code": "NO_KEY"}

    payload = {"key": key, "fingerprint": fingerprint, "ip": ip, "ua": ua}
    try:
        r = requests.post(
            f"{LICENSE_SERVER_URL}/api/license/activate",
            json=payload,
            headers=_license_headers(),
            timeout=8,
        )
        data = r.json() if r.text.strip().startswith("{") else {}
        if r.status_code in (200, 201):
            data.setdefault("ok", True)
            data.setdefault("success", True)
            _cache_clear()
            return data
        else:
            data.setdefault("ok", False)
            data.setdefault("success", False)
            data.setdefault("message", data.get("error") or f"HTTP {r.status_code}")
            return data
    except Exception as e:
        logger.error(f"[License] Activate fail: {e}")
        return {"ok": False, "success": False,
                "message": f"Không kết nối được server key: {e}",
                "code": "SERVER_ERROR"}

def license_heartbeat(key, fingerprint):
    """Báo server biết key còn sống (dùng trong watchdog)."""
    key = (key or "").strip().upper()
    try:
        requests.post(
            f"{LICENSE_SERVER_URL}/api/license/heartbeat",
            json={"key": key, "fingerprint": fingerprint, "ts": _now_ts()},
            headers=_license_headers(),
            timeout=4,
        )
        return True
    except Exception:
        return False

def _is_license_valid(res):
    if not isinstance(res, dict):
        return False
    if not res.get("ok", False):
        return False
    if res.get("revoked"):
        return False
    if res.get("expired"):
        return False
    if res.get("valid") is False:
        return False
    left = res.get("time_left")
    if isinstance(left, (int, float)) and left <= 0:
        return False
    return True

def _license_msg(res):
    if not isinstance(res, dict):
        return "Key không hợp lệ"
    return (res.get("message")
            or res.get("error")
            or ("Key đã hết hạn sử dụng" if res.get("expired") else "Key không hợp lệ"))

def _license_time_left(res):
    if not isinstance(res, dict):
        return 0
    if isinstance(res.get("time_left"), (int, float)):
        return max(0, int(res["time_left"]))
    exp = res.get("expires_at")
    if isinstance(exp, (int, float)):
        return max(0, int(exp) - _now_ts())
    return 0

def _client_ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "unknown")

def _client_ua():
    return request.headers.get("User-Agent", "unknown")

def _device_fingerprint(ip, ua):
    raw = f"{ip or 'unknown'}|{ua or 'unknown'}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

def require_license(f):
    """Decorator bảo vệ route — key phải còn hạn trên server."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        sid = session.get("sid")
        if not sid or sid not in WEB_SESSIONS:
            return jsonify({"success": False, "error": "Chưa đăng nhập", "code": "NO_SESSION"}), 401
        st = WEB_SESSIONS[sid]
        key = st.get("license_key")
        fp = st.get("license_fp")
        if not key:
            return jsonify({"success": False, "error": "Chưa kích hoạt key", "code": "NO_KEY"}), 401

        res = license_check(key, fp)
        if not _is_license_valid(res):
            _force_logout(sid, reason="KEY_EXPIRED")
            return jsonify({
                "success": False,
                "error": _license_msg(res) or "Key đã hết hạn sử dụng",
                "code": res.get("code") or "KEY_EXPIRED",
            }), 403
        return f(*args, **kwargs)
    return wrapper

def _force_logout(sid, reason="MANUAL"):
    st = WEB_SESSIONS.get(sid)
    if st:
        try:
            push_telemetry_to_admin("force_logout", sid=sid, st=st, extra={"reason": reason})
        except Exception:
            pass
    if sid in WS_CLIENTS:
        try:
            WS_CLIENTS[sid].disconnect()
        except Exception:
            pass
        WS_CLIENTS.pop(sid, None)
    WEB_SESSIONS.pop(sid, None)
    try:
        socketio.emit("force_logout", {"reason": reason}, to=sid)
    except Exception:
        pass
    logger.warning(f"[License] 🚪 Force logout {sid} — {reason}")

# ==========================================
# LICENSE WATCHDOG — 30s check + heartbeat
# ==========================================
def license_watchdog_worker():
    logger.info("[License Watchdog] started")
    while True:
        try:
            for sid, st in list(WEB_SESSIONS.items()):
                key = st.get("license_key")
                fp  = st.get("license_fp")
                if not key:
                    continue

                # clear cache để chắc chắn lấy trạng thái mới
                _cache_clear(f"{key}|{fp or '-'}")
                res = license_check(key, fp)

                if not _is_license_valid(res):
                    socketio.emit("toast", {
                        "type": "error",
                        "msg": f"⛔ {_license_msg(res) or 'Key đã hết hạn sử dụng'} — đăng xuất"
                    }, to=sid)
                    _force_logout(sid, reason="KEY_EXPIRED")
                    continue

                # heartbeat nhẹ
                license_heartbeat(key, fp)

                left = _license_time_left(res)
                if 0 < left <= 300 and not st.get("_warned_expiry"):
                    st["_warned_expiry"] = True
                    socketio.emit("toast", {
                        "type": "warning",
                        "msg": f"⚠️ Key còn {left // 60} phút sử dụng"
                    }, to=sid)
        except Exception as e:
            logger.error(f"[License Watchdog] {e}")
        socketio.sleep(30)

socketio.start_background_task(license_watchdog_worker)

# ==========================================
# ✅ HÀM CHUẨN HÓA SIDE
# ==========================================
def normalize_side(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value == 1: return "TAI"
        if value == 0: return "XIU"
        return None

    s = str(value).strip().upper()
    if not s:
        return None

    if "XỈU" in s or "XIU" in s:
        return "XIU"
    if "TÀI" in s or "TAI" in s:
        return "TAI"

    if len(s) <= 3:
        if s.startswith("T"): return "TAI"
        if s.startswith("X"): return "XIU"

    if "HIGH" in s or "BIG" in s: return "TAI"
    if "LOW" in s or "SMALL" in s: return "XIU"
    return None

# ==========================================
# ✅ LIÊN KẾT RENDER ADMIN API
# ==========================================
def _admin_headers():
    headers = {
        "Cache-Control": "no-store",
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
    }
    admin_key = os.environ.get("ADMIN_API_KEY", "").strip()
    if admin_key:
        headers["Authorization"] = f"Bearer {admin_key}"
        headers["X-Admin-Key"] = admin_key
    return headers

def fetch_admin_config(username=None, sid=None):
    endpoints = ["/api/config", "/api/bot/config", "/config", "/"]
    params = {"_t": int(time.time() * 1000)}
    if username:
        params["username"] = username
    if sid:
        params["sid"] = sid

    for ep in endpoints:
        try:
            url = f"{API_ADMIN_URL}{ep}"
            r = requests.get(url, params=params, timeout=5, headers=_admin_headers())
            if r.status_code == 404:
                continue
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            data = r.json() if "application/json" in ctype or r.text.strip().startswith("{") else {"raw_text": r.text}
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
                payload = data["data"]
            elif isinstance(data, dict):
                payload = data
            else:
                continue

            ADMIN_LAST_RAW["data"] = payload
            ADMIN_LAST_RAW["ts"] = time.time()
            ADMIN_LAST_RAW["error"] = None
            return payload
        except Exception as e:
            ADMIN_LAST_RAW["error"] = str(e)
            continue
    return ADMIN_LAST_RAW.get("data")

def apply_admin_config_to_session(st, sid, admin_cfg):
    if not isinstance(admin_cfg, dict):
        return False
    changed = False

    if "betAmount" in admin_cfg or "base_bet_amount" in admin_cfg:
        raw_amt = admin_cfg.get("betAmount", admin_cfg.get("base_bet_amount"))
        try:
            new_amt = int(raw_amt)
            if new_amt >= 1000 and new_amt != st["base_bet_amount"]:
                st["base_bet_amount"] = new_amt
                if not st.get("has_bet_this_session"):
                    st["current_bet"] = new_amt
                changed = True
        except (TypeError, ValueError):
            pass

    if "auto_bet_enabled" in admin_cfg:
        new_auto = bool(admin_cfg["auto_bet_enabled"])
        if new_auto != st["auto_bet_enabled"]:
            st["auto_bet_enabled"] = new_auto
            st["has_bet_this_session"] = not new_auto
            changed = True

    if "x2_mode" in admin_cfg:
        new_x2 = bool(admin_cfg["x2_mode"])
        if new_x2 != st["x2_mode"]:
            st["x2_mode"] = new_x2
            if new_x2:
                st["x2_loss_mode"] = False
            changed = True

    if "x2_loss_mode" in admin_cfg:
        new_x2_loss = bool(admin_cfg["x2_loss_mode"])
        if new_x2_loss != st["x2_loss_mode"]:
            st["x2_loss_mode"] = new_x2_loss
            if new_x2_loss:
                st["x2_mode"] = False
            changed = True

    if "x2_loss_limit" in admin_cfg and admin_cfg["x2_loss_limit"]:
        try:
            new_lim = int(admin_cfg["x2_loss_limit"])
            if new_lim > 0 and new_lim != st["x2_loss_limit"]:
                st["x2_loss_limit"] = new_lim
                changed = True
        except (TypeError, ValueError):
            pass

    if "target_profit" in admin_cfg:
        tp = admin_cfg["target_profit"]
        new_tp = int(tp) if tp not in (None, "", 0) else None
        if new_tp != st["target_profit"]:
            st["target_profit"] = new_tp
            changed = True

    if changed:
        logger.info(f"[Admin Sync {sid}] ⚙️ Applied remote config: {admin_cfg}")
    return changed

def push_telemetry_to_admin(event_name="heartbeat", sid=None, st=None, extra=None):
    payload = {
        "event": event_name,
        "ts": int(time.time()),
        "sid": sid,
        "history_len": len(GLOBAL_HISTORY),
        "api_ok": API_LAST_RAW.get("error") is None and API_LAST_RAW.get("data") is not None,
        "api_session": (API_LAST_RAW.get("data") or {}).get("phien"),
    }
    if st:
        payload.update({
            "nickname": st.get("nickname"),
            "username": st.get("username"),
            "balance": st.get("balance"),
            "profit_loss": st.get("profit_loss"),
            "auto_bet_enabled": st.get("auto_bet_enabled"),
            "x2_mode": st.get("x2_mode"),
            "x2_loss_mode": st.get("x2_loss_mode"),
            "x2_loss_limit": st.get("x2_loss_limit"),
            "base_bet_amount": st.get("base_bet_amount"),
            "current_bet": st.get("current_bet"),
            "target_profit": st.get("target_profit"),
            "current_prediction": st.get("current_prediction"),
            "session_id": st.get("session_id"),
            "win_count": st.get("win_count"),
            "lose_count": st.get("lose_count"),
            "win_streak": st.get("win_streak"),
            "loss_streak": st.get("loss_streak"),
            "socket_connected": st.get("socket_connected"),
            "license_key": st.get("license_key"),
        })
    if extra:
        payload["extra"] = extra

    endpoints = ["/api/telemetry", "/api/bot/report", "/api/status", "/api/sync"]
    for ep in endpoints:
        try:
            r = requests.post(f"{API_ADMIN_URL}{ep}", json=payload, timeout=4, headers=_admin_headers())
            if r.status_code in (200, 201, 202, 204):
                ADMIN_LAST_RAW["last_push_ts"] = time.time()
                try:
                    resp_json = r.json()
                    if isinstance(resp_json, dict):
                        cfg = resp_json.get("config") or resp_json.get("data")
                        if isinstance(cfg, dict) and sid and st:
                            if apply_admin_config_to_session(st, sid, cfg):
                                socketio.emit("stats_update", public_state(st), to=sid)
                except Exception:
                    pass
                return True
        except Exception:
            continue
    return False

# ==========================================
# GỌI API LỊCH SỬ
# ==========================================
def fetch_api_raw():
    try:
        url = f"{API_HISTORY_URL}?{COMMON_PARAMS}&at=&_t={int(time.time()*1000)}"
        r = requests.get(url, timeout=5,
                         headers={"Cache-Control": "no-store",
                                  "User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()
        API_LAST_RAW["data"] = data
        API_LAST_RAW["ts"] = time.time()
        API_LAST_RAW["error"] = None
        return data
    except Exception as e:
        API_LAST_RAW["error"] = str(e)
        logger.error(f"[API] Fetch fail: {e}")
        return None

# ==========================================
# API DATA WORKER
# ==========================================
def api_data_worker():
    logger.info("[API Worker] started")
    last_session_logged = None
    tick_counter = 0

    while True:
        data = fetch_api_raw()
        if data:
            session_id = data.get("phien")
            result_str = data.get("ket_qua") or ""
            du_doan    = data.get("du_doan")
            do_tin_cay = data.get("do_tin_cay")

            if session_id and result_str and session_id != last_session_logged:
                side = normalize_side(result_str)
                dices = []
                try:
                    parts = str(result_str).split()
                    if len(parts) > 1:
                        dices = [int(x) for x in parts[1].split("-")]
                except Exception:
                    pass

                if side:
                    with GLOBAL_HISTORY_LOCK:
                        if not any(h["session"] == session_id for h in GLOBAL_HISTORY[-5:]):
                            GLOBAL_HISTORY.append({
                                "session": session_id,
                                "dice": dices,
                                "side": side,
                                "ts": time.time(),
                            })
                            if len(GLOBAL_HISTORY) > MAX_GLOBAL_HISTORY:
                                GLOBAL_HISTORY.pop(0)
                            logger.info(f"[API] 📥 {session_id}: {side} {dices} | "
                                        f"du_doan={du_doan} | conf={do_tin_cay}")
                    last_session_logged = session_id

        tick_counter += 1
        if tick_counter % 4 == 0:
            admin_cfg = fetch_admin_config()
            if isinstance(admin_cfg, dict):
                for sid, st in list(WEB_SESSIONS.items()):
                    if apply_admin_config_to_session(st, sid, admin_cfg):
                        socketio.emit("stats_update", public_state(st), to=sid)
            if WEB_SESSIONS:
                for sid, st in list(WEB_SESSIONS.items()):
                    push_telemetry_to_admin("heartbeat", sid=sid, st=st)
            else:
                push_telemetry_to_admin("heartbeat_idle")

        socketio.sleep(1.5)

socketio.start_background_task(api_data_worker)

# ==========================================
# DỰ ĐOÁN
# ==========================================
def get_prediction():
    now = time.time()
    if API_LAST_RAW["data"] and (now - API_LAST_RAW["ts"]) < 1.5:
        data = API_LAST_RAW["data"]
    else:
        data = fetch_api_raw()

    if not data:
        return {
            "side": None, "conf": None, "ready": False,
            "api_ok": False,
            "api_error": API_LAST_RAW.get("error") or "API không phản hồi",
            "api_session": None,
            "raw": None,
        }

    du_doan = data.get("du_doan")
    do_tin_cay = data.get("do_tin_cay")
    side_out = normalize_side(du_doan)

    return {
        "side": side_out,
        "conf": do_tin_cay,
        "ready": side_out is not None,
        "api_ok": True,
        "api_error": None,
        "api_session": data.get("phien"),
        "raw": data,
    }

# ==========================================
# PARSE KẾT QUẢ
# ==========================================
def parse_result_side(result_raw):
    if not result_raw:
        return None
    side = normalize_side(result_raw)
    if side:
        return side

    s = str(result_raw).strip().upper()
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if len(nums) >= 3:
        total = sum(nums[:3])
        return "TAI" if total >= 11 else "XIU"
    return None

# ==========================================
# LOGIN GAME
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
# TÍNH TIỀN CƯỢC — HỖ TRỢ X2
# ==========================================
def calc_next_bet(st):
    base = int(st["base_bet_amount"])

    if st.get("x2_mode") and st["win_streak"] > 0:
        multiplier = min(2 ** st["win_streak"], 32)
        return base * multiplier

    if st.get("x2_loss_mode") and st["loss_streak"] > 0:
        limit = int(st.get("x2_loss_limit", 5))
        if st["loss_streak"] <= limit:
            multiplier = min(2 ** st["loss_streak"], 32)
            return base * multiplier

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
            push_telemetry_to_admin("target_profit_reached", sid=sid, st=st)
            return True
        return False

    @sio.event(namespace=GAME_WS_NS)
    def connect():
        logger.info(f"[{sid}] ✅ Game socket CONNECTED")
        st["socket_connected"] = True
        socketio.emit("toast", {"type": "success", "msg": "Đã kết nối socket game"}, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)
        push_telemetry_to_admin("socket_connected", sid=sid, st=st)

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
        push_telemetry_to_admin("socket_disconnected", sid=sid, st=st)

    @sio.on("new-session", namespace=GAME_WS_NS)
    def on_new_session(data):
        new_id = data.get("id") or data.get("sessionId") or "N/A"
        logger.info(f"[{sid}] 🆕 New session: {new_id}")

        admin_cfg = fetch_admin_config(username=st.get("username"), sid=sid)
        if isinstance(admin_cfg, dict):
            apply_admin_config_to_session(st, sid, admin_cfg)

        st["session_id"] = new_id
        st["has_bet_this_session"] = False
        st["current_bet_type"] = None
        st["current_bet_session"] = None
        st["current_prediction"] = None

        if check_target_profit():
            return

        pred = get_prediction()
        api_session = pred.get("api_session")
        pred_side = pred["side"]

        if pred_side and api_session:
            try:
                diff = int(new_id) - int(api_session)
            except (TypeError, ValueError):
                diff = 0
            if diff not in (0, 1):
                logger.warning(f"[{sid}] ⚠ API session {api_session} lệch xa new {new_id} → bỏ")
                pred_side = None
                api_session = None

        st["current_prediction"] = pred_side
        st["current_pred_session"] = api_session
        st["last_api_raw"] = pred.get("raw")

        st["current_bet"] = calc_next_bet(st) if st["auto_bet_enabled"] else int(st["base_bet_amount"])

        logger.info(f"[{sid}] 🎯 Session {new_id} | Bet={st['current_bet']:,}đ | "
                    f"API_session={api_session} | Pred={pred_side} | conf={pred['conf']}")

        socketio.emit("session_update", {
            "session_id": new_id,
            "prediction": pred_side,
            "conf": pred["conf"],
            "ready": pred["ready"] and pred_side is not None,
            "api_ok": pred["api_ok"],
            "api_error": pred["api_error"],
            "api_session": api_session,
            "history_len": len(GLOBAL_HISTORY),
            "current_bet": st["current_bet"],
            "auto_bet_enabled": st["auto_bet_enabled"],
        }, to=sid)
        socketio.emit("stats_update", public_state(st), to=sid)

    @sio.on("tick-update", namespace=GAME_WS_NS)
    def on_tick_update(data):
        if data.get("state") != "BETTING":
            return
        if not st["auto_bet_enabled"]:
            return
        if st["has_bet_this_session"]:
            return
        if not st["session_id"]:
            return

        pred_raw = st.get("current_prediction")
        bet_type = normalize_side(pred_raw)
        if not bet_type:
            logger.warning(f"[{sid}] ⚠ API chưa báo dự đoán → KHÔNG cược phiên {st['session_id']}")
            return

        pred_session = st.get("current_pred_session")
        if pred_session and str(pred_session) != str(st["session_id"]):
            logger.info(f"[{sid}] 🔄 Pred session {pred_session} != current {st['session_id']} → refresh")
            new_pred = get_prediction()
            new_pred_side = normalize_side(new_pred.get("side"))
            new_api_session = new_pred.get("api_session")

            if new_pred_side and new_api_session:
                try:
                    diff = int(st["session_id"]) - int(new_api_session)
                except (TypeError, ValueError):
                    diff = 999
                if diff in (0, 1):
                    bet_type = new_pred_side
                    st["current_prediction"] = new_pred_side
                    st["current_pred_session"] = new_api_session
                    logger.info(f"[{sid}] ✅ Refreshed pred: {new_pred_side} (API {new_api_session})")
                else:
                    logger.warning(f"[{sid}] ⚠ API session {new_api_session} lệch → KHÔNG cược")
                    return
            else:
                logger.warning(f"[{sid}] ⚠ Không refresh được pred → KHÔNG cược")
                return

        bet_amount = int(st["current_bet"])

        try:
            sio.emit("bet", {"type": bet_type, "amount": bet_amount},
                     namespace=GAME_WS_NS)
            st["has_bet_this_session"] = True
            st["waiting_for_result"] = True
            st["current_bet_type"] = bet_type
            st["current_bet_session"] = st["session_id"]

            logger.info(f"[{sid}] 🚀 BET {bet_amount:,} → {bet_type} "
                        f"(session {st['session_id']}, API báo {pred_raw})")
            socketio.emit("toast", {
                "type": "info",
                "msg": f"🚀 Cược {bet_amount:,}đ vào {bet_type}"
            }, to=sid)
            push_telemetry_to_admin("bet_placed", sid=sid, st=st, extra={
                "bet_type": bet_type,
                "bet_amount": bet_amount,
                "session_id": st["session_id"],
            })
        except Exception as e:
            logger.error(f"[{sid}] Bet error: {e}")

    @sio.on("bet-result", namespace=GAME_WS_NS)
    def on_bet_result(data):
        if "postBalance" in data:
            st["balance"] = data["postBalance"]
            socketio.emit("stats_update", public_state(st), to=sid)
        try:
            sio.emit("get-current-my-info", None, namespace=GAME_WS_NS)
        except Exception:
            pass

    @sio.on("session-result", namespace=GAME_WS_NS)
    def on_session_result(data):
        result_raw = (data.get("resultTruyenThong")
                      or data.get("result")
                      or data.get("resultString"))
        dices = data.get("dices") or data.get("dice") or []
        session_of_result = data.get("id") or st.get("session_id")

        if st.get("last_result_session") == str(session_of_result):
            logger.info(f"[{sid}] ⏭ Skip duplicate result session {session_of_result}")
            return
        st["last_result_session"] = str(session_of_result)

        result_side = parse_result_side(result_raw)
        is_win = None
        profit_delta = 0

        bet_type_used = st.get("current_bet_type")
        bet_session = st.get("current_bet_session")

        if (st.get("waiting_for_result")
                and bet_type_used
                and result_side
                and str(session_of_result) == str(bet_session)):
            is_win = (bet_type_used == result_side)
            bet_amt = int(st["current_bet"])
            if is_win:
                profit_delta = int(bet_amt * 0.98)
                st["win_streak"] += 1
                st["loss_streak"] = 0
                st["win_count"] += 1
            else:
                profit_delta = -bet_amt
                st["win_streak"] = 0
                st["loss_streak"] += 1
                st["lose_count"] += 1
            st["profit_loss"] += profit_delta
            st["waiting_for_result"] = False

        st["history"].insert(0, {
            "session": session_of_result,
            "pred": bet_type_used or st.get("current_prediction"),
            "bet": st["current_bet"] if is_win is not None else 0,
            "result": result_side or result_raw,
            "dice": dices,
            "win": is_win,
        })
        st["history"] = st["history"][:30]

        logger.info(f"[{sid}] 📊 Result {session_of_result}: {result_side} "
                    f"| bet_type={bet_type_used} | win={is_win} | profit={st['profit_loss']:,}")

        socketio.emit("result_update", {
            "session": session_of_result,
            "pred": bet_type_used,
            "result": result_side or result_raw,
            "dices": dices,
            "is_win": is_win,
            "bet": st["current_bet"],
            "balance": st["balance"],
            "profit_loss": st["profit_loss"],
            "profit_delta": profit_delta,
            "history": st["history"][:15],
        }, to=sid)

        socketio.emit("stats_update", public_state(st), to=sid)
        push_telemetry_to_admin("session_result", sid=sid, st=st, extra={
            "session": session_of_result,
            "result": result_side or result_raw,
            "dices": dices,
            "is_win": is_win,
            "profit_delta": profit_delta,
        })
        check_target_profit()

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
    key = st.get("license_key")
    fp = st.get("license_fp")
    lic = license_check(key, fp) if key else None
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
        "current_bet_type": st.get("current_bet_type"),
        "session_id": st["session_id"],
        "win_count": st["win_count"],
        "lose_count": st["lose_count"],
        "win_streak": st["win_streak"],
        "loss_streak": st["loss_streak"],
        "socket_connected": st["socket_connected"],
        "waiting_for_result": st.get("waiting_for_result", False),
        "has_bet_this_session": st.get("has_bet_this_session", False),
        "admin_url": API_ADMIN_URL,
        "admin_ok": ADMIN_LAST_RAW.get("error") is None and ADMIN_LAST_RAW.get("data") is not None,
        "license_key": key,
        "license_expires_at": (lic or {}).get("expires_at"),
        "license_time_left": _license_time_left(lic or {}),
        "license_active": _is_license_valid(lic or {}),
        "history": st["history"][:15],
    }

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

# ---- LICENSE: kích hoạt key (proxy tới License Server) ----
@app.route("/api/license/activate", methods=["POST"])
def api_license_activate():
    data = request.json or {}
    key = (data.get("key") or "").strip().upper()
    if not key:
        return jsonify({"success": False, "error": "Vui lòng nhập key"}), 400

    ip = _client_ip()
    ua = _client_ua()
    fp = _device_fingerprint(ip, ua)

    res = license_activate(key, fp, ip=ip, ua=ua)
    if not res.get("success", False):
        return jsonify({
            "success": False,
            "error": _license_msg(res) or "Kích hoạt thất bại",
            "code": res.get("code") or "ACTIVATE_FAIL",
        }), 403

    # server trả OK → lưu session
    session["license_key"] = key
    session["license_fp"] = fp
    _cache_clear()

    left = _license_time_left(res)
    return jsonify({
        "success": True,
        "key": key,
        "expires_at": res.get("expires_at"),
        "time_left": left,
        "time_left_text": f"{left // 86400} ngày {left % 86400 // 3600} giờ",
        "devices": res.get("devices"),
        "max_devices": res.get("max_devices"),
    })

# ---- LICENSE: xem trạng thái ----
@app.route("/api/license/status", methods=["GET"])
def api_license_status():
    key = session.get("license_key")
    fp = session.get("license_fp")
    if not key:
        return jsonify({"success": False, "error": "Chưa kích hoạt key", "code": "NO_KEY"}), 401

    res = license_check(key, fp)
    if not _is_license_valid(res):
        return jsonify({
            "success": False,
            "error": _license_msg(res) or "Key đã hết hạn sử dụng",
            "code": res.get("code") or "KEY_EXPIRED",
        }), 403

    left = _license_time_left(res)
    return jsonify({
        "success": True,
        "key": key,
        "expires_at": res.get("expires_at"),
        "time_left": left,
        "time_left_text": f"{left // 86400} ngày {left % 86400 // 3600} giờ",
        "devices": res.get("devices"),
        "max_devices": res.get("max_devices"),
    })

# ---- LOGIN GAME (yêu cầu key hợp lệ) ----
@app.route("/api/login", methods=["POST"])
def api_login():
    key = session.get("license_key")
    fp = session.get("license_fp")
    if not key:
        return jsonify({"success": False, "error": "Chưa kích hoạt key", "code": "NO_KEY"}), 401

    res = license_check(key, fp)
    if not _is_license_valid(res):
        session.pop("license_key", None)
        session.pop("license_fp", None)
        return jsonify({
            "success": False,
            "error": _license_msg(res) or "Key đã hết hạn sử dụng",
            "code": res.get("code") or "KEY_EXPIRED",
        }), 403

    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"success": False, "error": "Thiếu tài khoản/mật khẩu"})

    r = login_game(username, password)
    if "_error" in r:
        return jsonify({"success": False, "error": r["_error"]})

    sid = os.urandom(8).hex()
    session["sid"] = sid
    WEB_SESSIONS[sid] = {
        "nickname": r["nickname"],
        "balance": r["money"],
        "token": r["token"],
        "username": username,
        "license_key": key,
        "license_fp": fp,
        "profit_loss": 0,
        "auto_bet_enabled": False,
        "x2_mode": False,
        "x2_loss_mode": False,
        "x2_loss_limit": 5,
        "win_streak": 0,
        "loss_streak": 0,
        "base_bet_amount": 10000,
        "current_bet": 10000,
        "target_profit": None,
        "current_prediction": None,
        "current_pred_session": None,
        "current_bet_type": None,
        "current_bet_session": None,
        "waiting_for_result": False,
        "has_bet_this_session": False,
        "last_result_session": None,
        "session_id": None,
        "win_count": 0,
        "lose_count": 0,
        "socket_connected": False,
        "history": [],
        "last_api_raw": None,
    }

    admin_cfg = fetch_admin_config(username=username, sid=sid)
    if isinstance(admin_cfg, dict):
        apply_admin_config_to_session(WEB_SESSIONS[sid], sid, admin_cfg)
    push_telemetry_to_admin("login", sid=sid, st=WEB_SESSIONS[sid])

    socketio.start_background_task(game_socket_worker, sid, r["token"])

    left = _license_time_left(res)
    return jsonify({
        "success": True,
        "sid": sid,
        "nickname": r["nickname"],
        "balance": r["money"],
        "license_time_left": left,
    })

@app.route("/api/config", methods=["POST"])
@require_license
def api_config():
    sid = session.get("sid")
    st = WEB_SESSIONS[sid]
    data = request.json or {}

    if "betAmount" in data:
        try:
            new_amt = int(data["betAmount"])
            if new_amt >= 1000:
                st["base_bet_amount"] = new_amt
                st["current_bet"] = new_amt
                logger.info(f"[Config {sid}] 💰 Bet cố định = {new_amt:,}đ")
        except (TypeError, ValueError):
            pass

    if "auto_bet_enabled" in data:
        new_auto = bool(data["auto_bet_enabled"])
        if new_auto != st["auto_bet_enabled"]:
            st["auto_bet_enabled"] = new_auto
            if not new_auto:
                st["has_bet_this_session"] = True
                logger.info(f"[Config {sid}] ⏸ AUTO OFF")
            else:
                st["has_bet_this_session"] = False
                logger.info(f"[Config {sid}] ▶️ AUTO ON")
            socketio.emit("toast", {
                "type": "info",
                "msg": f"{'▶️ Bật' if new_auto else '⏸ Tắt'} auto cược"
            }, to=sid)

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

    push_telemetry_to_admin("config_updated", sid=sid, st=st)
    socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True, "state": public_state(st)})

@app.route("/api/stats")
@require_license
def api_stats():
    sid = session.get("sid")
    return jsonify({"success": True, "state": public_state(WEB_SESSIONS[sid])})

@app.route("/api/admin_sync", methods=["GET", "POST"])
@require_license
def api_admin_sync():
    sid = session.get("sid")
    st = WEB_SESSIONS.get(sid)
    cfg = fetch_admin_config(username=st.get("username") if st else None, sid=sid)
    applied = False
    if st and isinstance(cfg, dict):
        applied = apply_admin_config_to_session(st, sid, cfg)
        socketio.emit("stats_update", public_state(st), to=sid)
    pushed = push_telemetry_to_admin("manual_sync", sid=sid, st=st)
    return jsonify({
        "success": True,
        "admin_url": API_ADMIN_URL,
        "applied": applied,
        "pushed": pushed,
        "admin_error": ADMIN_LAST_RAW.get("error"),
        "admin_data": ADMIN_LAST_RAW.get("data"),
        "state": public_state(st) if st else None,
    })

@app.route("/api/debug_api")
def api_debug_api():
    data = fetch_api_raw()
    return jsonify({
        "ok": data is not None,
        "error": API_LAST_RAW.get("error"),
        "ts": API_LAST_RAW.get("ts"),
        "raw": API_LAST_RAW.get("data"),
        "normalized": {
            "du_doan": normalize_side((data or {}).get("du_doan")),
            "ket_qua": normalize_side((data or {}).get("ket_qua")),
        },
        "summary": {
            "phien": (data or {}).get("phien"),
            "ket_qua": (data or {}).get("ket_qua"),
            "du_doan": (data or {}).get("du_doan"),
            "do_tin_cay": (data or {}).get("do_tin_cay"),
        } if data else None,
        "admin": {
            "url": API_ADMIN_URL,
            "error": ADMIN_LAST_RAW.get("error"),
            "ts": ADMIN_LAST_RAW.get("ts"),
            "last_push_ts": ADMIN_LAST_RAW.get("last_push_ts"),
            "data": ADMIN_LAST_RAW.get("data"),
        },
        "license_server": LICENSE_SERVER_URL,
    })

@app.route("/api/reset_history", methods=["POST"])
@require_license
def api_reset_history():
    sid = session.get("sid")
    if sid and sid in WEB_SESSIONS:
        st = WEB_SESSIONS[sid]
        st["history"] = []
        st["win_count"] = 0
        st["lose_count"] = 0
        st["profit_loss"] = 0
        st["win_streak"] = 0
        st["loss_streak"] = 0
        push_telemetry_to_admin("reset_history", sid=sid, st=st)
        socketio.emit("stats_update", public_state(st), to=sid)
    return jsonify({"success": True})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    st = WEB_SESSIONS.get(sid)
    if st:
        push_telemetry_to_admin("logout", sid=sid, st=st)
    if sid in WS_CLIENTS:
        try:
            WS_CLIENTS[sid].disconnect()
        except Exception:
            pass
        del WS_CLIENTS[sid]
    if sid in WEB_SESSIONS:
        del WEB_SESSIONS[sid]
    session.pop("sid", None)
    # giữ license_key/fp để khỏi phải nhập lại key
    return jsonify({"success": True})

# ==========================================
# SOCKET EVENTS
# ==========================================
@socketio.on("connect")
def on_connect():
    logger.info(f"[WebSocket] client connected sid={request.sid}")

@socketio.on("disconnect")
def on_disconnect():
    logger.info(f"[WebSocket] client disconnected sid={request.sid}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
