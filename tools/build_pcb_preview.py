#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a preview of the EasyEDA board: 100 x 50 mm horizontal, top view.

pcb_preview.png  600 dpi raster, handy for a quick look
pcb_preview.pdf  1:1 vector, for printing

Shows the board outline, silkscreen, every pad with its drill, and the
ratsnest (the shortest set of connections still to be routed, exactly what
EasyEDA draws as thin blue lines).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import pcb_common as pc                      # noqa: E402
import strokefont                            # noqa: E402

PNG = os.path.join(ROOT, "pcb_preview.png")
PDF = os.path.join(ROOT, "pcb_preview.pdf")
DPI = 600
S = DPI / 25.4                               # mm -> px

C_BOARD = (245, 245, 240)
C_SILK = (190, 190, 190)
C_TEXT = (90, 90, 90)
C_PAD = (198, 74, 47)
C_DRILL = (255, 255, 255)
C_HOLE = (60, 60, 60)
C_RAT = (72, 96, 220)


def mst_edges(points):
    """Minimum spanning tree over 2-D points -> list of (p, q) index pairs."""
    n = len(points)
    if n < 2:
        return []
    used = [False] * n
    used[0] = True
    edges = []
    while sum(used) < n:
        best = None
        for i in range(n):
            if not used[i]:
                continue
            for j in range(n):
                if used[j]:
                    continue
                d = math.hypot(points[i][0] - points[j][0],
                               points[i][1] - points[j][1])
                if best is None or d < best[0]:
                    best = (d, i, j)
        edges.append((best[1], best[2]))
        used[best[2]] = True
    return edges


def main():
    parts = pc.build_parts()
    pin_net, net_pins = pc.load_netlist()
    pc.assign_nets(parts, pin_net)
    nets = pc.nets_of(parts)
    holes = pc.mount_holes()

    # ---------------------------------------------------------------- png
    from PIL import Image, ImageDraw
    W, H = int(round(pc.BW * S)), int(round(pc.BH * S))
    img = Image.new("RGB", (W, H), C_BOARD)
    dr = ImageDraw.Draw(img)

    def P(x, y):
        return x * S, (pc.BH - y) * S

    # board edge
    dr.rectangle([1, 1, W - 2, H - 2], outline=(120, 120, 120), width=3)

    # ratlines first (under the pads)
    for net, g in nets.items():
        pts = [(x, y) for _, _, x, y in g]
        for i, j in mst_edges(pts):
            dr.line([P(*pts[i]), P(*pts[j])], fill=C_RAT, width=2)

    # silkscreen
    for fp in parts:
        for item in fp.silk:
            if item[0] == "line":
                dr.line([P(x, y) for x, y in item[1]], fill=C_SILK, width=2,
                        joint="curve")
            elif item[0] == "circle":
                cx, cy, r = item[1], item[2], item[3]
                box = [P(cx - r, cy + r), P(cx + r, cy - r)]
                dr.ellipse(box, outline=C_SILK, width=2)

    # pads
    for ref, p, x, y in pc.all_pads(parts):
        r = p["d"] / 2.0
        dr.ellipse([P(x - r, y + r), P(x + r, y - r)], fill=C_PAD)
        rh = p["drill"] / 2.0
        dr.ellipse([P(x - rh, y + rh), P(x + rh, y - rh)], fill=C_DRILL)
    for hx, hy in holes:
        rm = pc.MOUNT_RING
        dr.ellipse([P(hx - rm, hy + rm), P(hx + rm, hy - rm)],
                   outline=C_SILK, width=2)
        rh = pc.DRILL_MOUNT / 2.0
        dr.ellipse([P(hx - rh, hy + rh), P(hx + rh, hy - rh)], fill=C_HOLE)

    # text: exactly the silk text the PCB file carries, via the stroke font
    def draw_stroke(texts, colour, width=2):
        for t in texts:
            for line in t.lines:
                if len(line) > 1:
                    dr.line([P(*p) for p in line], fill=colour, width=width,
                            joint="curve")

    draw_stroke(pc.silk_texts(parts, include_title=True), C_TEXT, width=2)

    # pad names of the ESP32, inside the socket strip
    draw_stroke([pc.SilkText(n, x, y, sz, rot=rot, owner="U1")
                 for n, x, y, sz, rot in pc.esp_pin_names(parts)],
                (120, 120, 120), width=2)

    img.save(PNG)
    print("wrote %s (%dx%d px, %d dpi)" % (PNG, W, H, DPI))

    # ---------------------------------------------------------------- pdf
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import Color
    c = canvas.Canvas(PDF, pagesize=(pc.BW * 72 / 25.4, pc.BH * 72 / 25.4),
                      invariant=1)
    # fixed metadata, so the same board always produces the same file
    c.setCreator("tools/build_pcb_preview.py")
    c.setProducer("tools/build_pcb_preview.py")
    c.setAuthor("schem-fix")
    c._doc.invariant = 1
    k = 72 / 25.4                            # mm -> pt

    def PP(x, y):
        return x * k, y * k

    c.setLineWidth(0.25)
    c.setStrokeColor(Color(0.55, 0.55, 0.55))
    c.rect(0.3 * k, 0.3 * k, (pc.BW - 0.6) * k, (pc.BH - 0.6) * k)

    c.setStrokeColor(Color(0.28, 0.38, 0.86))
    c.setLineWidth(0.15)
    for net, g in nets.items():
        pts = [(x, y) for _, _, x, y in g]
        for i, j in mst_edges(pts):
            c.line(*PP(*pts[i]), *PP(*pts[j]))

    c.setStrokeColor(Color(0.72, 0.72, 0.72))
    c.setLineWidth(0.18)
    for fp in parts:
        for item in fp.silk:
            if item[0] == "line":
                pth = c.beginPath()
                pth.moveTo(*PP(*item[1][0]))
                for x, y in item[1][1:]:
                    pth.lineTo(*PP(x, y))
                c.drawPath(pth)
            elif item[0] == "circle":
                cx, cy, r = item[1], item[2], item[3]
                c.circle(cx * k, cy * k, r * k, stroke=1, fill=0)

    c.setFillColor(Color(0.78, 0.29, 0.18))
    c.setStrokeColor(Color(0.62, 0.2, 0.12))
    for ref, p, x, y in pc.all_pads(parts):
        c.circle(x * k, y * k, p["d"] / 2.0 * k, stroke=1, fill=1)
    c.setFillColor(Color(1, 1, 1))
    for ref, p, x, y in pc.all_pads(parts):
        c.circle(x * k, y * k, p["drill"] / 2.0 * k, stroke=0, fill=1)
    c.setStrokeColor(Color(0.72, 0.72, 0.72))
    c.setLineWidth(0.18)
    for hx, hy in holes:
        c.circle(hx * k, hy * k, pc.MOUNT_RING * k, stroke=1, fill=0)
    c.setFillColor(Color(0.25, 0.25, 0.25))
    for hx, hy in holes:
        c.circle(hx * k, hy * k, pc.DRILL_MOUNT / 2.0 * k, stroke=0, fill=1)

    # text via the stroke font, exactly as it goes on the silk
    c.setStrokeColor(Color(0.35, 0.35, 0.35))
    c.setLineWidth(0.12)
    texts = pc.silk_texts(parts, include_title=True)
    texts += [pc.SilkText(n, x, y, sz, rot=rot, owner="U1")
              for n, x, y, sz, rot in pc.esp_pin_names(parts)]
    for t in texts:
        for line in t.lines:
            if len(line) < 2:
                continue
            pth = c.beginPath()
            pth.moveTo(*PP(*line[0]))
            for x, y in line[1:]:
                pth.lineTo(*PP(x, y))
            c.drawPath(pth)

    c.setTitle("ESP32 weather station - 100x50 mm horizontal PCB, top view")
    c.showPage()
    c.save()
    print("wrote %s (1:1, %.0f x %.0f mm)" % (PDF, pc.BW, pc.BH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
