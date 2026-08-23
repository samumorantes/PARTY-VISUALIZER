# FIESTA — changelog

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
