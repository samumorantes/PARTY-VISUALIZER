# 🎉 FIESTA — Visualizador de letras en tiempo real

Muestra la **frase que se está cantando** en pantalla grande, con fondos que laten al ritmo de la música. Conéctalo a tu Spotify y convierte cualquier pantalla en un karaoke de fiesta.

![FIESTA](fiesta.ico)

## ✨ Qué hace

- **Letra sincronizada** palabra a palabra (LRCLIB → Spotify → lyrics.ovh, con respaldo: nunca dice "NO LYRICS")
- **Modo fiesta**: el fondo cambia de color en cada beat
- **Modo fluido** (auto en baladas): gradiente vivo con los colores de la portada del álbum
- **Estética CRT arcade**: scanlines, fósforos RGB, ojo de pez — todo configurable
- **Título 7s** al empezar cada canción ("♪ Canción ♪")
- **Transición** al cambiar de canción: TV antigua, obturador, vinilo con la portada, flash de color
- **Cola de reproducción** y estado de conexión en pantalla
- **Easter eggs** 🐰

## 🚀 Instalación (Windows)

1. Instala [Python 3.11+](https://www.python.org/downloads/) (marca "Add to PATH")
2. Crea una app gratuita en [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) y pega tu **Client ID** en `config.json` (añade `http://127.0.0.1:8888/callback` como Redirect URI)
3. Doble clic en:

```
install.ps1   →   clic derecho → "Ejecutar con PowerShell"
```

Eso instala todo: accesos directos con icono, auto-arranque y abre FIESTA.

## 🖱️ Uso diario

Doble clic en el acceso directo **FIESTA** (Escritorio o Menú Inicio). Dale play en Spotify. Nada más.

## ⚙️ Personalización

Clic en ⚙️ dentro de la app: tamaño/fuente/color de letra, paletas, fuerza de los flashes, efectos CRT, transiciones… y botón de reset.

## 🗑️ Desinstalar

Menú Inicio → "Uninstall FIESTA".

---
Hecho con ❤️ y muchos beats. v1.3 "CONFIG"
