# FIESTA — Registro de versiones y arquitectura

## Nombre
**FIESTA** — Visualizador de música en tiempo real para Spotify

---

## ARQUITECTURA DEL PROYECTO

### Archivos

```
fiesta-visualizer/
├── server.py          ← Backend Python (stdlib, sin dependencias)
├── index.html         ← Frontend (HTML/CSS/JS vanilla)
├── config.json        ← Client ID de Spotify (NO commitear)
├── token.json         ← Tokens OAuth de Spotify (autogenerado, NO commitear)
├── start_fiesta.vbs   ← Script de auto-inicio (watchdog + arranque oculto)
├── fiesta.log         ← Log del servidor
├── fonts/
│   ├── arcadeclassic_full.woff   ← Fuente principal (Arcade Classic + acentos PS2P)
│   ├── spacegrotesk.woff2        ← Fuente alternativa (Grotesk)
│   └── check_cmap.py             ← Script de verificación de glifos (utilidad)
├── .gitignore
└── README.md
```

---

## server.py — Backend

### Qué hace
- OAuth 2.0 PKCE con Spotify (sin client secret, solo client_id).
- Consulta `GET /v1/me/player` cada 1s (rate-limit respetado) para saber qué canción está sonando.
- Obtiene letras de 3 fuentes en cascada: LRCLIB → endpoint interno Spotify → lyrics.ovh.
- Obtiene análisis de audio (beats, bars, sections, tempo) de `GET /v1/audio-analysis`.
- Sirve archivos estáticos (HTML, fuentes, CSS).
- Hace watchdog de sí mismo (si el proceso muere, se reinicia en 3s).

### Endpoints HTTP

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/` | GET | Sirve `index.html` |
| `/api/state` | GET | Estado completo: canción, letra sincronizada, beats, bars, sections, tempo. Usado solo al iniciar o cambiar de canción. |
| `/api/sync` | GET | Estado ligero para polling rápido (4×/s): progress_ms, is_playing, track_id, y **la letra activa** calculada según la posición exacta. |
| `/login` | GET | Inicia flujo OAuth PKCE: genera code_verifier, redirect a Spotify. |
| `/callback` | GET | Recibe code de Spotify, intercambia por tokens, guarda en `token.json`. |
| `/logout` | GET | Borra `token.json` y desconecta Spotify. |
| `/fonts/<archivo>` | GET | Sirve fuentes estáticas (.woff, .woff2, .ttf, .otf). |

### Cachés internos

| Variable | Contenido | Duración |
|----------|-----------|----------|
| `_player_cache` | Último estado del player (datos de `/me/player`) | 0.5s |
| `_track_cache` | Letras + beats + tempo por track_id | 6 horas |
| `_sync_cache` | progress_ms, is_playing, track_id, lyrics (de la canción activa) | canción activa |

### Flujo de datos

```
Spotify API
    ↓ (cada 1s cuando hay token válido)
fetch_player() → /v1/me/player
    ↓
_player_cache (0.5s)
    ↓
build_state() → /api/state (solo al cambiar canción)
    ↓
_track_cache (6h): lyrics + beats + sections
    ↓
_sync_cache → /api/sync (cada poll del cliente, 4×/s)
    ↓
FRONTEND → letra + color actualizados en tiempo real
```

### Fuente de letras (cascada)

1. **LRCLIB** (`https://lrclib.net/api/get`) — letra sincronizada de la comunidad. Mejor calidad.
2. **Endpoint interno Spotify** (`spclient.wg.spotify.com/lyrics/v1/track/<id>`) — misma letra que usa la app de Spotify.
3. **lyrics.ovh** (`https://api.lyrics.ovh/v1/artist/title`) — última opción, no sincronizada, dividida por duración de canción.

Si ninguna fuente tiene sync, se divide la letra en frases de ~4 palabras según duración total.

### Nota sobre tasas de requests
- Spotify limita a ~180 requests/minuto. El servidor consulta como máximo 1×/s cuando hay actividad.
- `GET /v1/audio-analysis` se llama solo una vez por canción (cachado 6h).
- `GET /v1/me/player` se llama cada 1s, cacheado 0.5s (protege de rate limits).

---

## index.html — Frontend

### Estructura HTML

```
body
├── #screen         ← Contenedor con perspectiva 3D y animación de deriva
│   ├── #bg         ← Fondo: color RGB sólido (cambia en cada beat)
│   ├── #flash      ← Flash blanco en cada beat (opacidad transitoria)
│   ├── #pbar       ← Barra de progreso (top, 5px)
│   ├── #lyrics     ← Contenedor de letra (flex centrado)
│   │   ├── #lCur   ← LETRA PRINCIPAL (frase actual)
│   │   └── #lBack  ← BACKING VOCAL / paréntesis (semi-transparente)
│   ├── #panel      ← Panel de configuración (oculto por defecto)
│   ├── #gear       ← Botón de ajustes (gear icon)
│   ├── #topInfo    ← Info superior (portada + nombre + artista)
│   ├── #badge      ← Badge "DEMO" o "🐰 EOO"
│   ├── #lineNone   ← Mensaje "SIN LETRAS"
│   ├── #msg        ← Mensajes de estado (conectando, error, etc.)
│   ├── #source     ← Footer con credits
│   ├── #bigLogin   ← Botón besarón de login Spotify
│   └── #channel    ← Animación de cambio de canal (TV antigua)
├── #crt            ← Capa de efecto CRT (scanlines, máscara RGB, viñeta)
└── #noise          ← Capa de ruido animado (gruesa, 7%)
```

### Variables JS principales

| Variable | Tipo | Descripción |
|----------|------|-------------|
| `S` | object | Estado completo devuelto por `/api/state` o `/api/sync` |
| `curTrack` | string | ID de la canción actual (detectado para saber si cambió) |
| `lineIdx` | int | Índice de la línea de letra activa en `S.lyrics` |
| `lastShown` | string | Texto de la última línea que se mostró (para evitar duplicados) |
| `beatPtr, barPtr, secPtr` | int | Punteros de posición en los arrays de beats/bars/sections |
| `playing` | bool | Si la canción está reproduciéndose (del server) |
| `pos, posAt, speed` | float | Reloj local con corrección de fase (sync-lock) |
| `eggActive` | bool | Si el easter egg (EOOO/PERREO) está activo |
| `cfg` | object | Configuración del usuario (guardada en localStorage) |

### Flujo de renderizado

```
tick() [cada 250ms]
  ├─ fetch /api/sync
  ├─ Si misma canción + mismo playing:
  │   └─ Corregir drift del reloj local (si drift > 0.5s → snap a posición del server)
  ├─ Si cambió canción o primer load:
  │   └─ fetch /api/state (letras + beats + tempo)
  │   └─ renderState() → mostrar letra, цвет фона
  └─ Si error:
      └─ Reintentar con /api/state

frame() [requestAnimationFrame, ~60fps]
  ├─ Calcular posición actual: t = nowPos()
  ├─ Si servidor envió S.lyric (autoritativo):
  │   └─ Usar S.lyric.text directamente (letra cambia al instante con seek)
  ├─ Sino (fallback local):
  │   └─ Avanzar lineIdx con while (L[lineIdx+1].t <= t)
  │   └─ Si línea cambió → setLyric() → actualizar DOM
  ├─ Si playing:
  │   ├─ beats: avanzar beatPtr → pulse() + onColor()
  │   ├─ bars: avanzar barPtr → onColor()
  │   └─ sections: avanzar secPtr → dropFlash()
  └─ Actualizar barra de progreso
```

### Sistema de color RGB

- `onColor()`: genera `rgb(r,g,b)` aleatorio y lo aplica a `$("bg").style.backgroundColor`.
- `setContrast()`: ajusta el color del texto (blanco/negro) según la luminosidad del fondo.
- Elige entre 3 modos: `rgb` (aleatorio), `pastel` (H SL 85% 62%), `byn` (escala de grises para easter egg).
- **Sincronizado con**: beats (cada beat), bars (cada 2 beats a 120BPM), o sections (cambios de sección musical).

### Efectos CRT (cristal curvado)
- **Perspectiva 3D**: `#screen` tiene `perspective(1100px) rotateX(1.1deg) rotateY(0.4deg)`.
- **Deriva analógica**: `@keyframes screenDrift` mueve la perspectiva 0.3px cada 11s.
- **Scanlines**: pseudo-elemento con `repeating-linear-gradient` de 2px negro cada 5px.
- **Máscara RGB**: pseudo-elemento con `repeating-linear-gradient` de 3px por canal (R/G/B).
- **Viñeta**: `radial-gradient` oscuro en los bordes.
- **Glare**: `radial-gradient` blanco semitransparente arriba.
- **Ruido**: `#noise` con gradiente radial que rota cada frame.
- **Refresh bar**: banda blanca que baja por la pantalla cada 8s.
- **Flicker**: animación de opacidad cada 7s.

### Easter egg
- **Palabras que lo disparan**: "EOOO", "PERREO EN GRANDE", "TRA TRA", "BEBE".
- **EOOO**: la letra se convierte en "E" y crece una "O" cada 85ms (`startGrowingE()`).
- **PERREO/TRA TRA**: ciclo de palabras entre "PERREO EN GRANDE" y "TRA TRA" cada 1.5s.
- Durante el easter egg: fondo en escala de grises, modo de fuente Impact.

---

## start_fiesta.vbs — Auto-inicio

### Qué hace
- Arranca `server.py` de forma **oculta** (ventana minimizada, sin pop-up).
- Si el servidor se cae, lo **reinicia en 3 segundos**.
- Registrado en el Programador de tareas de Windows para ejecutarse al iniciar sesión.

### Línea de comando del watchdog
```
cmd /c cd /d "C:\Users\moran\fiesta-visualizer" && "C:\Users\moran\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" server.py >> fiesta.log 2>&1
```

### Cómo registrar/retirar el auto-inicio
```batch
# Registrar (como administrador):
schtasks /create /tn "FIESTA Visualizer" /tr "wscript.exe /B C:\Users\moran\fiesta-visualizer\start_fiesta.vbs" /sc onlogon /rl limited

# Retirar:
schtasks /delete /tn "FIESTA Visualizer"
```

---

## Changelog

### v1.2 "CHILL" — 2026-08-22
**Nuevas funcionalidades**:
- **Modo chill autodetectado**: si el BPM de la canción es < 100 (baladas), la app cambia automáticamente de flashes por beat a un **gradiente fluido con los colores de la portada del álbum** (estilo Apple Music). El color fluye y respira lentamente, sin flashes.
- Extracción de paleta desde la portada (canvas 24×24, cuantización a 5 colores dominantes).
- Checkbox en ajustes: «Auto: baladas → modo fluido (portada)» para activar/desactivar.
- **Icono de app** (`fiesta.ico`) + `fiesta_launcher.py` (Python puro, sin .bat — los .bat disparan el SmartScreen de Windows) para abrir el visualizador en ventana propia de Chrome.

---

### v1.1 "MASTER" — 2026-08-19
**Bug fixes**:
- La letra ahora se actualiza en tiempo real sin F5. El servidor calcula la línea activa en `/api/sync` y el cliente la usa como autoridad.
- Fix: `fetch_lyrics` recibía el objeto `item` de Spotify en lugar del track formateado `{artist, name, album, duration_ms, id}`. Ahora adapta el formato correctamente.
- Fix: el reloj local (`pos`, `speed`) se reseteaba correctamente al cambiar de canción.
- Fix: el puntero de línea (`lineIdx`) se resetea cuando la posición retrocede (seek hacia atrás).
- Fix: `_tickBusy` evita que se acumulen ticks重叠ados si la red se pone lenta.
- Fix: `visibilitychange` fuerza re-sync cuando la pestaña vuelve al primer plano.

**Nuevas funcionalidades**:
- El endpoint `/api/sync` ahora devuelve `lyric: {text, back, t, next_t, idx}` con la línea activa según el `progress_ms` exacto.
- Cache de letras: `_sync_cache["lyrics"]` se mantiene mientras la canción no cambie.

**Cambios**:
- `server.py`: `_current_lyric()` nueva función para calcular línea activa.
- `server.py`: `_sync_cache` ahora incluye `"lyrics": []`.
- `server.py`: cambio de canción ahora adapta el item al formato correcto para `fetch_lyrics`.
- `index.html`: `frame()` ahora usa `S.lyric` del servidor como autoridad (con fallback local).
- `index.html`: `document.addEventListener("visibilitychange")` fuerza re-sync al volver de background.
- `index.html`: `let _tickBusy = false` para evitar ticksacumulados.

---

### v1.0 ALPHA "ARCADE" — 2026-08-18
**Primera versión funcional**. Características:
- OAuth Spotify con PKCE (sin client secret).
- Letra sincronizada de LRCLIB + Spotify interno + lyrics.ovh.
- Fuente Arcade Classic con acentos de Press Start 2P (fusión con fontTools).
- Efecto CRT completo: scanlines, máscara RGB, viñeta, ruido, glare, refresh bar, flicker, perspectiva 3D con deriva.
- Fondo RGB aleatorio que cambia en cada beat/bar/section (configurable).
- Easter egg para "EOOO", "PERREO EN GRANDE", "TRA TRA".
- Cambio de canal tipo TV antigua (estática + barras de color).
- Auto-inicio con watchdog VBS.
- Panel de configuración (modo de color, timing, fuente, efectos CRT).

---

### v0.9 BETA "TAINY" — 2026-08-17
**Prototipo inicial**. Solo Space Grotesk, sin fusión de fuentes, efecto CRT experimental, letra sin actualizar en tiempo real (necesitaba F5).
