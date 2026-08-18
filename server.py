# -*- coding: utf-8 -*-
"""
FIESTA VISUALIZER — servidor local (solo stdlib, sin dependencias).

Qué hace:
  - OAuth Spotify (PKCE, sin client secret) para leer lo que estás escuchando.
  - Letra EXACTA sincronizada en tiempo real desde LRCLIB (comunidad).
  - Ritmo real de la canción desde Spotify Audio Analysis (lista de beats).
  - El frontend pinta la letra en grande y cambia el fondo a un color
    RGB aleatorio en cada beat.

Uso:
  python server.py   ->  http://localhost:8888
"""

import base64
import hashlib
import html
import http.server
import json
import os
import re
import secrets
import socketserver
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")
TOKENS = os.path.join(BASE, "token.json")
PORT = 8888
REDIRECT_URI = "http://127.0.0.1:%d/callback" % PORT
SCOPE = "user-read-playback-state user-read-currently-playing"
UA = "FiestaVisualizer/1.0 (proyecto local, Windows)"
LRCLIB = "https://lrclib.net/api"


def load_client_id():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return (json.load(f).get("client_id") or "").strip()
    except Exception:
        return ""


CLIENT_ID = load_client_id()

_pkce = {}          # state -> code_verifier (entre /login y /callback)
_track_cache = {}   # track_id -> {"lyrics": [...], "beats": [...], "tempo": float, "at": ts}


# ---------------------------------------------------------------- helpers HTTP
_last_raw = {"body": b""}  # último cuerpo crudo de respuesta (debug)

# Abridor SIN proxy: el proceso en background puede heredar proxies del sistema
# que corrompen los POST (error GFE "malformed request"); forzamos conexión directa.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, headers=None, method="GET", form=None, timeout=8):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with _opener.open(req, timeout=timeout) as r:
            raw = r.read()
            _last_raw["body"] = raw
            try:
                return r.status, json.loads(raw) if raw else None
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        _last_raw["body"] = raw
        try:
            return e.code, json.loads(raw.decode("utf-8", "replace")) if raw else None
        except Exception:
            return e.code, None
    except Exception as e:
        return 0, str(e)


def token_exchange(form):
    """Intercambio del código por token.
    http.client como stack principal (100% fiable en este equipo); urllib como respaldo
    (a veces el WAF de Google responde 400 'malformed request' a las peticiones urllib)."""
    body = urllib.parse.urlencode(form).encode()
    try:
        import http.client
        conn = http.client.HTTPSConnection("accounts.spotify.com", timeout=10)
        conn.request("POST", "/api/token", body=body, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": UA, "Accept": "application/json",
            "Content-Length": str(len(body)),
        })
        r = conn.getresponse()
        raw = r.read()
        _last_raw["body"] = raw
        try:
            parsed = json.loads(raw.decode("utf-8", "replace")) if raw else None
        except Exception:
            parsed = None
        print("[oauth] http.client -> HTTP %s | %r" % (r.status, raw[:300]))
        return r.status, parsed
    except Exception as e:
        print("[oauth] http.client falló (%r) -> respaldo urllib" % e)
        return request("https://accounts.spotify.com/api/token", form=form)


# ---------------------------------------------------------------- tokens
def load_tokens():
    try:
        with open(TOKENS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_tokens(t):
    with open(TOKENS, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=2)


def access_token():
    """Devuelve un access token válido, refrescándolo si hace falta."""
    t = load_tokens()
    if not t:
        return None
    if t.get("expires_at", 0) <= time.time() + 60:
        st, data = request("https://accounts.spotify.com/api/token", form={
            "grant_type": "refresh_token",
            "refresh_token": t.get("refresh_token", ""),
            "client_id": CLIENT_ID,
        })
        if st == 200 and data:
            t["access_token"] = data["access_token"]
            t["expires_at"] = time.time() + data.get("expires_in", 3600)
            if data.get("refresh_token"):
                t["refresh_token"] = data["refresh_token"]
            save_tokens(t)
        else:
            return None
    return t["access_token"]


# ---------------------------------------------------------------- Spotify
def fetch_player(token):
    """Estado actual del reproductor: {is_playing, progress_ms, item}."""
    h = {"Authorization": "Bearer " + token}

    st, data = request("https://api.spotify.com/v1/me/player/currently-playing", headers=h)
    if st == 204:  # nada sonando -> probar /player (pausado sin pista activa)
        st, data = request("https://api.spotify.com/v1/me/player", headers=h)
        if st == 200 and data:
            data = {"item": data.get("item"), "progress_ms": data.get("progress_ms"),
                    "is_playing": bool(data.get("is_playing"))}
        else:
            data = None
    elif st in (401, 429):
        token2 = access_token()
        if token2:
            h = {"Authorization": "Bearer " + token2}
            st, data = request("https://api.spotify.com/v1/me/player/currently-playing", headers=h)
            if st == 204:
                st, data = 200, None

    if st == 403:
        return {"error": "premium"}
    if st == 401:
        return {"error": "reconnect"}
    if st == 429:
        return {"error": "ratelimit"}
    if not data or not data.get("item"):
        return {"is_playing": False, "progress_ms": 0, "item": None}
    return {"is_playing": bool(data.get("is_playing")),
            "progress_ms": data.get("progress_ms") or 0,
            "item": data["item"]}


def track_info(item):
    imgs = (item.get("album") or {}).get("images") or []
    return {
        "id": item.get("id") or item.get("uri", ""),
        "name": item.get("name", "?"),
        "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
        "album": (item.get("album") or {}).get("name", ""),
        "duration_ms": item.get("duration_ms", 0),
        "cover": imgs[0]["url"] if imgs else None,
        "type": item.get("type", "track"),
    }


def _extract_back_into(item):
    """Extrae (contenido) del text y lo guarda en item['back']. Sin paréntesis = sin back."""
    txt = item.get("text", "")
    if "(" not in txt or ")" not in txt:
        return
    main_parts, back_parts = [], []
    for part in re.split(r"(\([^)]*\))", txt):
        p = part.strip()
        if not p:
            continue
        if p.startswith("(") and p.endswith(")"):
            back_parts.append(p[1:-1])
        else:
            main_parts.append(p)
    new_text = " ".join(main_parts)
    if new_text:
        item["text"] = new_text
    if back_parts:
        item["back"] = " ".join(back_parts)


# ---------------------------------------------------------------- letras (LRCLIB)
def parse_lrc(text):
    """Convierte LRC ('[mm:ss.xx] línea') en [{t, text, back?}].
    Los paréntesis (así) NO son línea separada — se devuelven en `back`
    dentro del mismo item, para que aparezcan como subtítulo debajo."""
    out = []
    if not text:
        return out
    for m in re.finditer(r"\[(\d+):(\d+)(?:[.:](\d+))?\]([^\[]*)", text):
        mm, ss = int(m.group(1)), int(m.group(2))
        frac = int(m.group(3) or 0)
        txt = m.group(4).strip()
        if not txt:
            continue
        denom = 10 ** len(m.group(3)) if m.group(3) else 1
        t = mm * 60 + ss + frac / float(denom)
        # Extraer partes: principal vs (back)
        main_parts, back_parts = [], []
        for part in re.split(r"(\([^)]*\))", txt):
            p = part.strip()
            if not p:
                continue
            if p.startswith("(") and p.endswith(")"):
                back_parts.append(p[1:-1])
            else:
                main_parts.append(p)
        main_text = " ".join(main_parts)
        if main_text:
            item = {"t": round(t, 3), "text": main_text}
            if back_parts:
                item["back"] = " ".join(back_parts)
            out.append(item)
    return out


def split_phrases(lines, duration, max_words=4):
    """Convierte líneas largas en FRASES CORTAS (máx. max_words palabras),
    repartiendo el tiempo de la línea original entre las frases."""
    MAX_W = max(2, min(int(max_words), 8))
    out = []
    for i, ln in enumerate(lines):
        start = ln["t"]
        end = lines[i + 1]["t"] if i + 1 < len(lines) else min(start + 6.0, (duration or start + 6.0))
        span = max(end - start, 1.2)
        words = ln["text"].split()
        if len(words) <= MAX_W:
            out.append({"t": round(start, 3), "text": ln["text"]})
            continue
        # cortar primero por signos (comas, puntos, guiones)
        parts = [p.strip() for p in re.split(r"[,;:—–]\s*|\s*\.\s*|\s+-\s+", ln["text"]) if p.strip()]
        chunks = []
        for p in parts:
            ws = p.split()
            while ws:
                chunks.append(" ".join(ws[:MAX_W]))
                ws = ws[MAX_W:]
        n = len(chunks)
        for j, c in enumerate(chunks):
            out.append({"t": round(start + span * j / n, 3), "text": c})
    return out


def fetch_lyrics_spotify(track, token):
    """Plan B: endpoint interno de letras de Spotify (usa tu token).
    LINE_SYNCED -> tiempos reales; UNSYNCED -> repartidas por la duración."""
    try:
        url = ("https://spclient.wg.spotify.com/lyrics/v1/track/%s?format=json"
               % urllib.parse.quote(track["id"]))
        st, data = request(url, headers={"Authorization": "Bearer " + token,
                                         "app-platform": "WebPlayer",
                                         "Accept": "application/json"})
        if st == 200 and isinstance(data, dict) and data.get("lyrics"):
            ly = data["lyrics"]
            raw_lines = ly.get("lines") or []
            if ly.get("syncType") == "LINE_SYNCED":
                out = []
                for l in raw_lines:
                    w = (l.get("words") or "").strip()
                    if w:
                        item = {"t": (l.get("startTimeMs") or 0) / 1000.0, "text": w}
                        _extract_back_into(item)
                        out.append(item)
                if out:
                    return out
            else:
                ws = [l.get("words", "").strip() for l in raw_lines if (l.get("words") or "").strip()]
                if ws:
                    dur = track.get("duration_ms", 0) / 1000.0 or 180.0
                    step = min(dur / len(ws), 9.0) if dur else 5.0
                    return [{"t": round(1.0 + i * step, 3), "text": w} for i, w in enumerate(ws)]
    except Exception as e:
        print("[lyrics] spclient:", e)
    return []


def fetch_lyrics_plain(track):
    """Plan C: letras sin sincronizar (lyrics.ovh) repartidas por la duración."""
    try:
        url = "https://api.lyrics.ovh/v1/%s/%s" % (
            urllib.parse.quote(track["artist"].split(",")[0].strip()),
            urllib.parse.quote(track["name"]))
        st, data = request(url)
        if st == 200 and isinstance(data, dict) and data.get("lyrics"):
            raw = data["lyrics"]
            lines = []
            for l in raw.splitlines():
                l = l.strip()
                if not l or re.match(r"^\[.*\]$", l):  # saltar [Verso 1], [Coro]...
                    continue
                lines.append(l)
            if lines:
                dur = track.get("duration_ms", 0) / 1000.0 or 180.0
                step = min(dur / len(lines), 9.0) if dur else 5.0
                out = []
                for i, l in enumerate(lines):
                    item = {"t": round(1.0 + i * step, 3), "text": l}
                    _extract_back_into(item)
                    out.append(item)
                return out
    except Exception:
        pass
    return []


def fetch_lyrics(track, token=None):
    """Cadena de fuentes para que TODAS las canciones tengan letra:
    1) LRCLIB exacto  2) LRCLIB búsqueda  3) Spotify interno  4) lyrics.ovh (sin sync)."""
    dur = round(track["duration_ms"] / 1000) if track.get("duration_ms") else None
    params = {"artist_name": track["artist"], "track_name": track["name"],
              "album_name": track["album"]}
    if dur:
        params["duration"] = dur
    st, data = request(LRCLIB + "/get?" + urllib.parse.urlencode(params))
    if st == 200 and data and data.get("syncedLyrics"):
        return parse_lrc(data["syncedLyrics"])

    st, data = request(LRCLIB + "/search?" + urllib.parse.urlencode(
        {"track_name": track["name"], "artist_name": track["artist"]}))
    if st == 200 and isinstance(data, list) and data:
        best, best_diff = None, None
        for x in data:
            if not x.get("syncedLyrics"):
                continue
            d = abs((x.get("duration") or 0) - dur) if dur else 0
            if best is None or d < best_diff:
                best, best_diff = x, d
        if best:
            return parse_lrc(best["syncedLyrics"])

    if token:
        found = fetch_lyrics_spotify(track, token)
        if found:
            return found
    return fetch_lyrics_plain(track)


# ---------------------------------------------------------------- ritmo (audio analysis)
def synth_beats(tempo, duration):
    """Beats sintéticos uniformes cuando Spotify no da análisis (o en demo)."""
    if not tempo or tempo <= 0:
        tempo = 120.0
    interval = 60.0 / tempo
    return [round(i * interval, 3) for i in range(int(duration / interval) + 1)]


def fetch_rhythm(track, token):
    """Ritmo real desde Spotify Audio Analysis:
    beats (pulsos), bars (downbeats/compases) y sections (cambios estructurales = drops)."""
    try:
        st, data = request(
            "https://api.spotify.com/v1/audio-analysis/%s" % urllib.parse.quote(track["id"]),
            headers={"Authorization": "Bearer " + token})
        if st == 200 and data:
            def times(k):
                return [round(x["start"], 3) for x in (data.get(k) or [])]
            beats, bars, sections = times("beats"), times("bars"), times("sections")
            tempo = float((data.get("tracks") or {}).get("tempo") or 120.0)
            if beats:
                return {"beats": beats, "bars": bars, "sections": sections, "tempo": tempo}
    except Exception:
        pass
    tempo = 120.0
    beats = synth_beats(tempo, track["duration_ms"] / 1000)
    return {"beats": beats, "bars": beats[::4], "sections": beats[::32], "tempo": tempo}


def enrich(track, token, max_words=4):
    """Letras + ritmo con caché por canción y por tamaño de frase (6 h)."""
    tid = "%s|%s" % (track["id"], max_words)
    cached = _track_cache.get(tid)
    if cached and time.time() - cached["at"] < 6 * 3600:
        return cached
    lyrics, beats, bars, sections, tempo = [], [], [], [], 120.0
    if track.get("type") == "track" and tid and not tid.startswith("spotify:local"):
        dur = track.get("duration_ms", 0) / 1000.0 or 240.0
        lyrics = split_phrases(fetch_lyrics(track, token), dur, max_words)
        rhythm = fetch_rhythm(track, token)
        beats, bars, sections, tempo = (rhythm["beats"], rhythm["bars"],
                                        rhythm["sections"], rhythm["tempo"])
    res = {"lyrics": lyrics, "beats": beats, "bars": bars, "sections": sections,
           "tempo": tempo, "at": time.time()}
    _track_cache[tid] = res
    return res


# ---------------------------------------------------------------- estado / demo
_player_cache = {"data": None, "at": 0.0, "mw": 4}  # caché corta (0.5s) por tamaño de frase


def demo_state():
    DUR = 40.0
    lines = [
        (0.0, "🎉 MODO DEMO 🎉"),
        (3.0, "Conecta tu Spotify"),
        (6.5, "para ver tu letra"),
        (10.0, "exacta en tiempo real"),
        (13.5, "mientras el fondo"),
        (17.0, "cambia de color"),
        (20.5, "al ritmo de la música"),
        (24.0, "— pon tu Client ID —"),
        (27.5, "en config.json"),
        (31.0, "y dale al play 🎧"),
    ]
    tempo = 124.0
    beats = synth_beats(tempo, DUR)
    return {
        "logged_in": False, "demo": True, "is_playing": True,
        "progress_ms": (time.time() * 1000) % (DUR * 1000),
        "track": {"id": "demo", "name": "Modo Demo", "artist": "Fiesta Visualizer",
                  "album": "", "duration_ms": int(DUR * 1000), "cover": None, "type": "track"},
        "lyrics": [{"t": t, "text": s} for t, s in lines],
        "beats": beats,
        "bars": beats[::4],
        "sections": beats[::32],
        "tempo": tempo,
    }


def build_state(max_words=4):
    if not CLIENT_ID or not load_tokens():
        return demo_state()
    token = access_token()
    if not token:
        return demo_state()
    now = time.time()
    if _player_cache["data"] and _player_cache["mw"] == max_words and now - _player_cache["at"] < 0.5:
        return _player_cache["data"]
    player = fetch_player(token)
    out = {"logged_in": True, "demo": False, "is_playing": False, "progress_ms": 0,
           "track": None, "lyrics": [], "beats": [], "bars": [], "sections": [], "tempo": 120.0}
    if player.get("error"):
        if player["error"] == "ratelimit" and _player_cache["data"]:
            return _player_cache["data"]  # rate-limit transitorio: sirve el último estado
        out["error"] = player["error"]
        return out
    if not player.get("item"):
        _player_cache["data"] = out
        _player_cache["at"] = now
        _player_cache["mw"] = max_words
        return out
    track = track_info(player["item"])
    out["is_playing"] = player["is_playing"]
    out["progress_ms"] = player["progress_ms"]
    out["track"] = track
    enr = enrich(track, token, max_words)
    out["lyrics"] = enr["lyrics"]
    out["beats"], out["bars"], out["sections"] = enr["beats"], enr["bars"], enr["sections"]
    out["tempo"] = enr["tempo"]
    _player_cache["data"] = out
    _player_cache["at"] = time.time()
    _player_cache["mw"] = max_words
    return out


# ---------------------------------------------------------------- HTTP server
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login(self):
        if not CLIENT_ID:
            self._send(200, "<h2>Falta el Client ID</h2><p>Abre <b>config.json</b> y pega tu "
                            "Client ID de Spotify (ver README.md).</p><a href='/'>Volver</a>",
                       "text/html; charset=utf-8")
            return
        verifier = secrets.token_urlsafe(64)[:100]
        state = secrets.token_urlsafe(16)
        _pkce[state] = verifier
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        q = urllib.parse.urlencode({
            "client_id": CLIENT_ID, "response_type": "code",
            "redirect_uri": REDIRECT_URI, "scope": SCOPE,
            "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        self._redirect("https://accounts.spotify.com/authorize?" + q)

    def _callback(self, query):
        q = urllib.parse.parse_qs(query)
        if q.get("error"):
            self._send(200, "<h2>Autorización rechazada</h2><p>%s</p><a href='/'>Volver</a>"
                       % html.escape(q["error"][0]), "text/html; charset=utf-8")
            return
        code, state = q.get("code", [""])[0], q.get("state", [""])[0]
        verifier = _pkce.pop(state, None)
        print("[oauth] callback recibido | code len=%d full=%r | state=%r | verifier len=%s" % (
            len(code), code, state, len(verifier) if verifier else None))
        if not verifier:
            self._send(400, "state inválido", "text/plain")
            return
        form = {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI, "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }
        st, data = token_exchange(form)
        if st == 0:  # fallo de red transitorio -> un reintento
            print("[oauth] fallo de red (%s), reintentando..." % data)
            time.sleep(1)
            st, data = request("https://accounts.spotify.com/api/token", form=form)
        print("[oauth] intercambio de token -> HTTP %s | json: %s" % (
            st, json.dumps(data, ensure_ascii=False)[:300] if data is not None else "respuesta vacía"))
        raw = _last_raw["body"]
        print("[oauth] cuerpo crudo (%d bytes): %r" % (len(raw), raw[:400]))
        if st == 200 and isinstance(data, dict) and data.get("access_token"):
            save_tokens({
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", ""),
                "expires_at": time.time() + data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
            })
            self._redirect("/")
        else:
            raw_txt = raw.decode("utf-8", "replace") if raw else "(respuesta vacía)"
            body = data if isinstance(data, str) else (
                json.dumps(data, ensure_ascii=False) if data else raw_txt)
            self._send(200, "<h2>Error al obtener el token</h2><p>HTTP %s</p><p>%s</p>"
                       "<p><a href='/login'>Reintentar conexión</a></p><a href='/'>Volver</a>"
                       % (st, html.escape(str(body))), "text/html; charset=utf-8")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        if p in ("/", "/index.html"):
            try:
                with open(os.path.join(BASE, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception:
                self._send(500, "index.html no encontrado", "text/plain")
        elif p == "/api/state":
            mw = 4
            try:
                mw = max(2, min(int(urllib.parse.parse_qs(u.query).get("mw", ["4"])[0]), 8))
            except Exception:
                mw = 4
            try:
                self._send(200, json.dumps(build_state(mw), ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False),
                           "application/json; charset=utf-8")
        elif p == "/login":
            self._login()
        elif p.startswith("/fonts/"):
            fn = os.path.basename(p)
            fp = os.path.join(BASE, "fonts", fn)
            if fn.endswith((".woff2", ".woff", ".ttf", ".otf")) and os.path.exists(fp):
                ctype = {"woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf",
                         "otf": "font/otf"}.get(fn.rsplit(".", 1)[-1], "application/octet-stream")
                with open(fp, "rb") as f:
                    self._send(200, f.read(), ctype)
            else:
                self._send(404, "no", "text/plain")
        elif p == "/callback":
            self._callback(u.query)
        elif p == "/logout":
            try:
                os.remove(TOKENS)
            except Exception:
                pass
            self._redirect("/")
        else:
            self._send(404, "no encontrado", "text/plain")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def port_in_use(port):
    """True si ya hay un servidor escuchando en el puerto (evita duplicados)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


if __name__ == "__main__":
    if port_in_use(PORT):
        print("Ya hay un Fiesta Visualizer en el puerto %d — saliendo." % PORT)
        raise SystemExit(0)
    print("=" * 52)
    print("  FIESTA VISUALIZER  ->  http://localhost:%d" % PORT)
    print("  proxies visibles por este proceso:", urllib.request.getproxies() or "ninguno")
    if not CLIENT_ID:
        print("  AVISO: config.json sin client_id -> MODO DEMO")
        print("  (sigue el README.md para conectar tu Spotify)")
    print("  Ctrl+C para salir")
    print("=" * 52)
    Server(("127.0.0.1", PORT), Handler).serve_forever()
