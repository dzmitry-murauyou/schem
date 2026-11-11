#!/usr/bin/env python3
"""Tiny EasyEDA v6 schematic -> PNG rasteriser (dev aid: lets us eyeball the layout)."""
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "SCH_ESP32_WeatherStation_2026-11-11.json")
DST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "preview.png")

SCALE = 2.0
OX, OY = 0.0, -806.8
W, H = 1149.0, 807.2

doc = json.load(open(SRC, encoding="utf-8"))
shapes = doc["schematics"][0]["dataStr"]["shape"]

img = Image.new("RGB", (int(W * SCALE), int(H * SCALE)), "white")
d = ImageDraw.Draw(img)


def P(x, y):
    return ((x - OX) * SCALE, (y - OY) * SCALE)


def font(size):
    size = max(6, int(size * SCALE))
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


NUM = re.compile(r"-?\d+(?:\.\d+)?")

for s in shapes:
    subs = s.split("#@$")
    head = subs[0]
    if head.startswith("W~"):
        pts = [float(v) for v in NUM.findall(head)]
        d.line([P(pts[0], pts[1]), P(pts[2], pts[3])], fill=(0, 136, 0))
        continue
    if head.startswith("N~"):
        f = head.split("~")
        x, y, name, anchor = float(f[1]), float(f[2]), f[5], f[7]
        d.ellipse([P(x, y)[0] - 2, P(y * 0, y)[1], P(x, y)[0] + 2, P(x, y)[1] + 4], fill=(0, 0, 255))
        ft = font(6)
        bb = d.textbbox((0, 0), name, font=ft)
        tx = P(x, y)[0] - (bb[2] - bb[0]) if anchor == "end" else P(x, y)[0]
        d.text((tx, P(x, y - 6)[1]), name, fill=(0, 0, 255), font=ft)
        continue
    if not head.startswith("LIB~"):
        continue
    for sub in subs[1:]:
        f = sub.split("~")
        t = f[0]
        if t == "R":
            x, y, w, h = float(f[1]), float(f[2]), float(f[5]), float(f[6])
            d.rectangle([P(x, y), P(x + w, y + h)], outline=(136, 0, 0))
        elif t == "E":
            x, y, rx, ry = float(f[1]), float(f[2]), float(f[3]), float(f[4])
            d.ellipse([P(x - rx, y - ry), P(x + rx, y + ry)], fill=(136, 0, 0))
        elif t == "PL":
            p = [float(v) for v in NUM.findall(f[1])]
            d.line([P(p[0], p[1]), P(p[2], p[3])], fill=(136, 0, 0))
        elif t == "PG":
            p = [float(v) for v in NUM.findall(f[1])]
            pts = [P(p[i], p[i + 1]) for i in range(0, len(p) - 1, 2)]
            fill = f[5] if f[5] != "none" else None
            d.polygon(pts, outline=(136, 0, 0), fill=fill)
        elif t == "PT":
            # only absolute M/L/h/v segments matter for the frame
            toks = re.findall(r"[MmLlHhVv]|-?\d+(?:\.\d+)?", f[1])
            cur = [0.0, 0.0]
            i = 0
            start = None
            while i < len(toks):
                c = toks[i]
                if c == "M":
                    cur = [float(toks[i + 1]), float(toks[i + 2])]
                    start = list(cur)
                    i += 3
                elif c == "L":
                    nx = [float(toks[i + 1]), float(toks[i + 2])]
                    d.line([P(*cur), P(*nx)], fill=(136, 0, 0))
                    cur = nx
                    i += 3
                else:
                    i += 1
        elif t == "T":
            x, y, val = float(f[2]), float(f[3]), f[12]
            if f[1] == "L":
                ft = font(6.5)
                col = (136, 0, 0)
            elif f[1] == "P":
                ft = font(6.5)
                col = (0, 0, 128)
            else:
                ft = font(6.0)
                col = (0, 0, 128)
            d.text(P(x, y), val, fill=col, font=ft)
        elif t == "P":
            parts = sub.split("^^")
            hh = parts[0].split("~")
            try:
                x, y = float(hh[4]), float(hh[5])
            except ValueError:
                continue
            d.ellipse([P(x, y)[0] - 2, P(x, y)[1] - 2, P(x, y)[0] + 2, P(x, y)[1] + 2],
                      fill=(200, 0, 0))
            seg = parts[2].split("~")[0]
            toks = re.findall(r"[MmLlHhVvZz]|-?\d+(?:\.\d+)?", seg)
            if len(toks) >= 6:
                sx, sy = float(toks[1]), float(toks[2])
                if toks[3] in ("h", "H"):
                    ex = sx + float(toks[4])
                    ey = sy
                elif toks[3] in ("v", "V"):
                    ex, ey = sx, sy + float(toks[4])
                else:
                    ex, ey = float(toks[4]), float(toks[5])
                d.line([P(sx, sy), P(ex, ey)], fill=(136, 0, 0))
            nm = parts[3].split("~")
            ft = font(4.5)
            if nm[0] == "1":
                d.text(P(float(nm[1]), float(nm[2])), nm[5], fill=(0, 0, 255), font=ft)
            nu = parts[4].split("~")
            if nu[0] == "1":
                d.text(P(float(nu[1]), float(nu[2])), nu[5], fill=(0, 100, 0), font=ft)

img.save(DST)
print("wrote", DST, img.size)
