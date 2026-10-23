# FIESTA — changelog

## v2.0 "TURBO" — 2026-10-23
- Corrección de bugs críticos:
  - Fix crash en `showMsg`/`hideMsg` (`$("#msg")` con selector incorrecto).
  - Fix extracción de tempo en análisis de Spotify (`track` vs `tracks`).
  - Preservación de coros/voces secundarias (`back`) al trocear frases (`split_phrases`).
  - Ruta de iconos y scripts dinámica (elimina rutas absolutas fijas).
- Rendimiento y optimización:
  - Cache en memoria reutilizable para análisis de canvas y contraste (cero fuga de memoria).
  - Eliminado layout thrashing recurrente en fisheye y pintado de frames.
  - Caches del servidor acotados para evitar acumulación infinita de memoria en sesiones largas.
  - Caché de fuentes y favicon en memoria en el servidor con encabezados HTTP óptimos.
- Seguridad y privacidad:
  - Eliminado registro de código OAuth en texto plano en la consola.
  - Sanitización en transiciones de portada de vinilo contra inyecciones HTML.
  - Ámbito de permisos recortado al mínimo necesario (`user-read-email` removido).
- Interfaz y accesibilidad:
  - Enlace al favicon `fiesta.ico` en HTML.
  - Soporte de tecla Escape para cerrar panel de ajustes.
  - Etiquetas accesibles en botones de modo y controles.
  - Corrección de selector de transición URL (`flashcolor`) y respeto a preferencias de timing.

## v1.3 "CONFIG" — 2026-08-23
- Panel de configuración completo y funcional: 6 fuentes, 6 paletas, fuerza del flash,
  pulso de color vs flash blanco, grosor/sombra de letra, transición "flash de color"
- Botón "Restablecer configuración" con sincronización instantánea del panel
- Fix crítico: parpadeo de letra (dos fuentes peleándose) → una sola autoridad + freno anti-flip
- Fix: ghosting del texto (fisheye suavizado rotY -14°→-4°)
- Fix: contraste con histéresis anti-flicker
- Instalador end-to-end: install.ps1 (accesos directos con icono, auto-arranque, desinstalador)

### v1.2 "CHILL" — 2026-08-22
- Modo chill autodetectado (BPM/energía de letra <2.5 sílabas/s): fluido con paleta de portada
- Fluido interactivo canvas: blobs que respiran al BPM y rotan color por beat
- Ticker de cola ("A CONTINUACIÓN") + auto-hide UI 5s
- Selector rápido fiesta/fluido flotante

### v1.1 "SYNC" — 2026-08-22
- Easter egg EOO solo efectos (letra intacta), flip B/N puro
- Título 7s antes de la letra
- Fallback anti NO-LYRICS (nunca queda sin letra)
- Limpieza general del código

### BETA 1.0 "ARCADE" — 2026-08-19
- Letra sincronizada en tiempo real, RGB por beat, estética CRT arcade
- LED de estado SYNC/WAIT/OFFLINE, sync ante seeks instantáneo
- Transición TV al cambiar canción
