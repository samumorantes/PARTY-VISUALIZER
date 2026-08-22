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
SCOPE = "user-read-playback-state user-read-currently-playing user-read-email"
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


def _merge_alternating_voices(lines):
    """Detecta líneas con voces alternadas (Perreo -> Tra-tra, Mami -> baby -> Ey...)
    y las une como principal+back automáticamente cuando NO hay paréntesis."""
    if not lines:
        return lines
    out = []
    i = 0
    n = len(lines)
    while i < n:
        cur = lines[i]
        # Si ya tiene back, no tocar
        if cur.get("back"):
            out.append(cur)
            i += 1
            continue
        # Buscar siguientes líneas que sean MUY CORTAS (<=25 chars) y gap pequeño
        backs = []
        j = i + 1
        gap_threshold = 2.8   # gap máximo entre líneas para ser "alternada"
        while j < n:
            nxt = lines[j]
            gap = nxt["t"] - (lines[j-1]["t"] if j > 0 else cur["t"])
            # Solo agrupar si la siguiente línea es muy corta y gap pequeño
            if nxt.get("back") or len(nxt["text"]) > 25 or gap > gap_threshold:
                break
            # Stop si ya tenemos 4 backs
            if len(backs) >= 4:
                break
            backs.append(nxt)
            j += 1
        if backs and len(backs) <= 4:
            # Concatenar las siguientes líneas como back (voz alternada)
            back_text = " ".join(b["text"] for b in backs)
            new_item = {"t": cur["t"], "text": cur["text"], "back": back_text}
            out.append(new_item)
            i = j
            continue
        out.append(cur)
        i += 1
    return out


def fetch_lyrics(track, token=None):
    """Cadena de fuentes para que TODAS las canciones tengan letra con backs:
    1) Spotify interno (si tiene token y devuelve líneas) — TIENE paréntesis
    2) LRCLIB exacto
    3) LRCLIB búsqueda
    4) lyrics.ovh (sin sync)
    5) Respaldo sintético con el título — NUNCA devuelve vacío.

    Tras obtenerlas: si NO hay paréntesis, detectar voces alternadas
    (Perreo/Tra-tra/Mami/baby/ey...) y crear `back` automáticamente."""
    dur = round(track["duration_ms"] / 1000) if track.get("duration_ms") else None

    # 1) Spotify interno primero — usa paréntesis reales para los backs
    spotify_no_backs = None
    if token:
        found = fetch_lyrics_spotify(track, token)
        if found:
            if _has_backs(found):
                return found
            spotify_no_backs = found   # guardar por si LRCLIB tampoco tiene

    # 2) LRCLIB exacto
    params = {"artist_name": track["artist"], "track_name": track["name"],
              "album_name": track["album"]}
    if dur:
        params["duration"] = dur
    st, data = request(LRCLIB + "/get?" + urllib.parse.urlencode(params))
    if st == 200 and data and data.get("syncedLyrics"):
        lines = parse_lrc(data["syncedLyrics"])
        if _has_backs(lines):
            return lines
        # LRCLIB sin paréntesis → detectar voces alternadas
        merged = _merge_alternating_voices(lines)
        if _has_backs(merged):
            return merged

    # 3) LRCLIB búsqueda — PREFERIR la versión con paréntesis (backs reales)
    st, data = request(LRCLIB + "/search?" + urllib.parse.urlencode(
        {"track_name": track["name"], "artist_name": track["artist"]}))
    if st == 200 and isinstance(data, list) and data:
        # Primero intentar las versiones CON paréntesis
        for x in data:
            synced = x.get("syncedLyrics") or ""
            if not synced:
                continue
            # Solo versiones que tengan paréntesis con texto (backs reales)
            if re.search(r"\([^\d)][^)]*\)", synced):
                lines = parse_lrc(synced)
                if _has_backs(lines):
                    return lines
        # Si ninguna tenía paréntesis, mejor coincidencia por duración
        best, best_diff = None, None
        for x in data:
            if not x.get("syncedLyrics"):
                continue
            d = abs((x.get("duration") or 0) - dur) if dur else 0
            if best is None or d < best_diff:
                best, best_diff = x, d
        if best:
            lines = parse_lrc(best["syncedLyrics"])
            if _has_backs(lines):
                return lines
            merged = _merge_alternating_voices(lines)
            if _has_backs(merged):
                return merged

    # 4) Spotify interno sin backs + detección de voces alternadas
    if spotify_no_backs:
        merged = _merge_alternating_voices(spotify_no_backs)
        if _has_backs(merged):
            return merged
        return spotify_no_backs

    # 5) lyrics.ovh y, como último recurso, letra sintética (nunca vacío)
    plain = fetch_lyrics_plain(track)
    if plain:
        merged = _merge_alternating_voices(plain)
        return merged if _has_backs(merged) else plain
    return _fallback_lines(track)


def _fallback_lines(track):
    """Última instancia: línea mínima con el título para que JAMÁS diga NO LYRICS."""
    name = (track.get("name") or "♪").strip()
    artist = (track.get("artist") or "").strip()
    out = [{"t": 4.0, "text": "♪ %s ♪" % name}]
    if artist:
        out.append({"t": 12.0, "text": artist})
    return out


def _has_backs(lines):
    """True si al menos una línea tiene campo `back`."""
    return any("back" in l for l in lines)


# ---------------------------------------------------------------- ritmo (audio analysis)
def synth_beats(tempo, duration):
    """Beats sintéticos uniformes cuando Spotify no da análisis (o en demo)."""
    if not tempo or tempo <= 0:
        tempo = 120.0
    interval = 60.0 / tempo
    return [round(i * interval, 3) for i in range(int(duration / interval) + 1)]


def lyric_energy(lyrics):
    """Densidad de sílabas por segundo de la letra sincronizada.
    Proxy de energía SIN audio real (Spotify cerró audio-analysis):
    reggaetón/perreo ≈ 3.5-4.5 syl/s, baladas ≈ 1.2-1.6 syl/s. Umbral: 2.5."""
    if not lyrics or len(lyrics) < 5:
        return None
    syl_total = 0
    dur_total = 0
    for i, ln in enumerate(lyrics[:-1]):
        gap = lyrics[i + 1]["t"] - ln["t"]
        if gap <= 0 or gap > 15:
            continue
        text = (ln.get("text") or "") + " " + (ln.get("back") or "")
        syls = len(re.findall(r"[aeiouáéíóúü]+", text.lower()))
        syl_total += syls
        dur_total += gap
    if dur_total < 30:
        return None
    return syl_total / dur_total


def detect_mood(track, tempo, lyrics=None):
    """Detecta si la canción es 'chill' (balada → fluido portada) o 'party' (flashes por beat).

    Capas de detección (Spotify cerró audio-analysis, 403 desde nov 2024):
      1) BPM real < 100 (si algún día vuelve el análisis)
      2) Energía de la letra: sílabas/segundo < 2.5 → balada
      3) Palabras clave balada/acoustic/chill en título, artista o álbum
      4) Default: party
    """
    if tempo and tempo != 120.0 and tempo < 100:
        return "chill"
    energy = lyric_energy(lyrics or [])
    if energy is not None and energy < 2.5:
        return "chill"
    text = " ".join([track.get("name", ""), track.get("artist", ""), track.get("album", "")])
    if re.search(r"\b(balada|baladas|acoustic|acústico|unplugged|ballad|sad|lento|lenta|slow|"
                 r"chill|lofi|lo-fi|piano|stripped|versi[oó]n ac[uú]stica|solo voz)\b", text, re.I):
        return "chill"
    return "party"


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
_player_cache = {"data": None, "at": 0.0, "mw": 4}
_demo_start = time.time()
# cache del sync: guarda progress_ms + ts + track_id para poder servir todos los polls
# sin martillar Spotify. track_id se rellena siempre para que el cliente no recargue state.
_sync_cache = {
    "prog": 0, "is_playing": False, "track_id": "", "lyrics": [],
    "pos_at": 0.0,       # instante del reloj local al que corresponde prog
    "fetched_at": 0.0,   # último GET real a Spotify; NO usar para extrapolar progreso
}


def _current_lyric(lyrics, pos_sec):
    """Devuelve la línea de letra activa según pos_sec (segundos), o None."""
    if not lyrics:
        return None
    idx = -1
    for i, l in enumerate(lyrics):
        if l["t"] <= pos_sec:
            idx = i
        else:
            break
    if idx < 0:
        return None
    cur = lyrics[idx]
    nxt = lyrics[idx + 1] if idx + 1 < len(lyrics) else None
    return {
        "text": cur["text"],
        "back": cur.get("back"),
        "t": cur["t"],
        "next_t": nxt["t"] if nxt else None,
        "idx": idx,
    }


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
        "mood": "party",
        "cover": None,
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
           "track": None, "lyrics": [], "beats": [], "bars": [], "sections": [],
           "tempo": 120.0, "mood": "party", "cover": None}
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
    # mood con letra SIN dividir (energía real), no las frases recortadas del enrich
    raw_lyrics = fetch_lyrics(track, token)
    out["mood"] = detect_mood(track, enr["tempo"], raw_lyrics)
    out["cover"] = track.get("cover")
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
        elif p == "/api/sync":
            global _sync_cache
            try:
                _t = time.time()
                if CLIENT_ID and load_tokens():
                    tok = access_token()
                    # siempre incluir el último track_id conocido (para que el cliente
                    # no recargue /api/state innecesariamente)
                    out = {"progress_ms": _sync_cache["prog"],
                           "is_playing": _sync_cache["is_playing"],
                           "track_id": _sync_cache["track_id"],
                           "ts": _t, "health": "waiting"}
                    if tok:
                        # Fuente de verdad: refrescar Spotify 2 veces/segundo.
                        # pos_at y fetched_at tienen funciones separadas: así el polling
                        # no bloquea para siempre los seeks/cambios de canción.
                        if _t - _sync_cache["fetched_at"] >= 0.5 or _sync_cache["fetched_at"] == 0:
                            player = fetch_player(tok)
                            if player:
                                _sync_cache["is_playing"] = player.get("is_playing", False)
                                _sync_cache["prog"] = player.get("progress_ms", 0) or 0
                                _sync_cache["pos_at"] = _t
                                item = player.get("item") or {}
                                new_tid = item.get("id", "")
                                if new_tid and new_tid != _sync_cache["track_id"]:
                                    _sync_cache["track_id"] = new_tid
                                    artists = item.get("artists") or []
                                    track_for_lyrics = {
                                        "artist": artists[0]["name"] if artists else "",
                                        "name": item.get("name", ""),
                                        "album": (item.get("album") or {}).get("name", ""),
                                        "duration_ms": item.get("duration_ms", 0), "id": new_tid,
                                    }
                                    _sync_cache["lyrics"] = fetch_lyrics(track_for_lyrics, tok)
                                elif not new_tid:
                                    _sync_cache["track_id"] = new_tid
                            _sync_cache["fetched_at"] = _t
                        # Extrapolación pura: no muta el cache ni el timestamp de fetch.
                        prog = _sync_cache["prog"]
                        if _sync_cache["is_playing"]:
                            prog += int(max(0, _t - _sync_cache["pos_at"]) * 1000)
                        out["progress_ms"] = prog
                        out["is_playing"] = _sync_cache["is_playing"]
                        out["track_id"] = _sync_cache["track_id"]
                        out["ts"] = _t
                        out["health"] = "synced" if _sync_cache["track_id"] else "waiting"
                        cur = _current_lyric(_sync_cache["lyrics"], prog / 1000.0)
                        if cur:
                            out["lyric"] = cur
                else:
                    elapsed = max(0, _t - _demo_start)
                    cyc = 180.0
                    out = {"progress_ms": int((elapsed % cyc) * 1000),
                           "is_playing": True,
                           "track_id": "demo", "ts": _t}
                self._send(200, json.dumps(out), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}), "application/json; charset=utf-8")
        elif p == "/api/queue":
            # Cola de Spotify: próximas canciones (para el ticker inferior-izquierdo)
            try:
                tok = access_token()
                if not tok:
                    self._send(200, json.dumps({"queue": []}), "application/json; charset=utf-8")
                    return
                st, data = request("https://api.spotify.com/v1/me/player/queue",
                                   headers={"Authorization": "Bearer " + tok})
                items = []
                if st == 200 and isinstance(data, dict):
                    for it in (data.get("queue") or [])[:5]:
                        artists = ", ".join(a.get("name", "") for a in it.get("artists", []))
                        imgs = (it.get("album") or {}).get("images") or []
                        items.append({
                            "name": it.get("name", "?"),
                            "artist": artists,
                            "cover": imgs[-1]["url"] if imgs else None,
                        })
                self._send(200, json.dumps({"queue": items}), "application/json; charset=utf-8")
            except Exception as e:
                self._send(200, json.dumps({"queue": [], "error": str(e)}),
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
