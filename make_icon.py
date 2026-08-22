# -*- coding: utf-8 -*-
"""Genera el icono de FIESTA (nota musical arcade sobre fondo degradado fiesta) en .ico"""
from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]

def make(size):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # fondo: esquina redondeada con degradado vertical fiesta (magenta->naranja)
    rad = max(2, s // 5)
    # degradado dibujado por líneas
    grad = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    top = (214, 31, 105)   # magenta fiesta
    bot = (255, 140, 27)   # naranja
    for y in range(s):
        t = y / max(1, s - 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
        gd.line([(0, y), (s, y)], fill=c)
    # máscara redondeada
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, s - 1, s - 1], radius=rad, fill=255)
    img.paste(grad, (0, 0), mask)

    # nota musical blanca estilo pixel/arcade: círculo + palo + banderín
    fg = (255, 255, 255, 255)
    u = s / 16.0  # unidad
    def R(x0, y0, x1, y1):
        d.rectangle([x0*u, y0*u, x1*u, y1*u], fill=fg)
    # cabeza de la nota (elipse doble)
    cx, cy = 6.2*u, 12.2*u
    r = 2.1*u
    d.ellipse([cx-r, cy-r*0.78, cx+r, cy+r*0.78], fill=fg)
    # palo
    R(7.9, 3.4, 9.3, 12.4)
    # banderín
    d.polygon([(7.9*u, 3.4*u), (12.6*u, 5.6*u), (9.3*u, 8.0*u)], fill=fg)
    return img

imgs = [make(sz) for sz in SIZES]
imgs[-1].save(r"C:\Users\moran\fiesta-visualizer\fiesta.ico", format="ICO",
              sizes=[(sz, sz) for sz in SIZES], append_images=imgs[:-1])
print("fiesta.ico OK")
