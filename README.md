# 🎉 Fiesta Visualizer

Visualizador para fiestas: muestra la **letra exacta de la canción en tiempo real, en grande**,
mientras el fondo es un **color plano RGB aleatorio que cambia en cada beat** (ritmo real
de la canción, no un temporizador inventado).

![stack](https://img.shields.io/badge/Python-3.11+-blue) ![dep](https://img.shields.io/badge/dependencias-solo%20stdlib-success)

## Cómo funciona

| Qué | De dónde |
|---|---|
| Canción, artista, progreso, portada | Spotify Web API (`currently-playing`) |
| Letra sincronizada EXACTA | [LRCLIB](https://lrclib.net) (letras LRC de la comunidad) |
| Beats / ritmo real | Spotify Audio Analysis (`/audio-analysis/{id}` → lista de beats) |
| Pantalla | HTML/JS local: letra gigante + fondo RGB que cambia en cada beat + pulso blanco |

La música **sigue sonando en tu Spotify** (PC, móvil, TV…). El visualizador solo lo *observa*:
no necesita reproducir nada, ni se entera de dónde está el audio.

## Requisitos

- Python 3.11+ (ya lo tienes; **no instala nada**, usa solo la librería estándar)
- Cuenta de Spotify. **Importante:** leer el estado del reproductor vía API funciona con
  cuenta gratuita en la mayoría de casos, pero Spotify puede exigir **Premium** según la
  cuenta. Si ves el aviso de Premium en pantalla, esa es la causa.
- La música puede sonar en cualquier dispositivo (no hace falta que suene en el PC).

## 🚀 Puesta en marcha (2 minutos)

### Paso 1 — Crear la "app" de Spotify (1 vez)

1. Entra en **https://developer.spotify.com/dashboard** (inicia sesión con tu cuenta).
2. **Create app** → nombre: `Fiesta Visualizer`, descripción: lo que quieras.
3. En **Redirect URIs** pon EXACTAMENTE:
   ```
   http://127.0.0.1:8888/callback
   ```
4. **Save**. (No necesitas el Client Secret: usamos PKCE.)

### Paso 2 — Pegar tu Client ID

En **`config.json`** pega el **Client ID** (no el secret) que aparece en el dashboard:

```json
{
  "client_id": "2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d"
}
```

### Paso 3 — Arrancar

```bash
python server.py
```

Abre **http://localhost:8888** → pulsa **Conectar con Spotify** → autoriza →
¡dale al play! 🎶

> Sin Client ID el servidor arranca igual en **MODO DEMO** para que veas el efecto
> (letra + color al ritmo) antes de conectar nada.

## Controles

- **⚙** — ajustes: tamaño de la letra, modo de color (RGB aleatorio puro / HSV pastel)
  y pulso blanco por beat. Se guardan en el navegador.
- Texto claro/oscuro automático según el color de fondo (siempre legible).
- Botón **Desconectar** en el panel para revocar la sesión.

## Archivos

```
fiesta-visualizer/
├── server.py      # servidor local: OAuth Spotify, LRCLIB, audio-analysis, /api/state
├── index.html     # la pantalla: letra gigante + fondo RGB al ritmo
├── config.json    # tu Client ID de Spotify
└── token.json     # (se crea solo) tu sesión de Spotify — no lo compartas
```

## Solución de problemas

- **"Tu cuenta necesita Premium"** → Spotify ha denegado la lectura del reproductor;
  necesitas Premium (o prueba con otra cuenta).
- **No sale letra** → LRCLIB es de la comunidad: canciones raras o nuevas pueden no tener
  LRC sincronizado. La portada y el ritmo sí funcionan igual.
- **El ritmo se siente raro** → los beats son los del propio análisis de Spotify; si la
  canción tiene tiempo variable, los beats también (es lo correcto).
- **Cambiar de puerto** → edita `PORT` en `server.py` y actualiza el Redirect URI en el
  dashboard de Spotify a `http://127.0.0.1:<puerto>/callback`.
- **Firewall de Windows** → permite Python en localhost cuando lo pregunte (solo red local).

## Ideas para después

- Efecto "flash" por beat más agresivo (modo rave)
- Transiciones de color interpoladas entre beats
- Fuente personalizada, modo quiosco a pantalla completa (F11)
