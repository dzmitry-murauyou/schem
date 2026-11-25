#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export an EasyEDA Standard PCB JSON (docType 3) to a 1:1 A4 PDF for printing
and LUT toner transfer, with optional independent X / Y printer calibration.

Example (when a 100 x 50 mm print measured 103.0 x 49.5 mm on paper):
    python3 tools/export_easyeda_pdf.py PCB_final.json -o pcb_calibrated.pdf \\
        --measured-w 103.0 --measured-h 49.5
"""
import argparse
import json
import os
import re
import sys

U = 1.0 / 0.254                              # EasyEDA 10-mil units per mm
MM_TO_PT = 72.0 / 25.4
A4_W, A4_H = 210.0, 297.0                    # Portrait A4, mm


def board_bounds_mm(doc):
    """Return (bx0, by0, W, H) in EasyEDA canvas mm from BoardOutLine (layer 10)."""
    xs, ys = [], []
    for sh in doc["shape"]:
        if sh.startswith("TRACK~"):
            f = sh.split("~")
            if f[2] == "10":
                coords = [float(v) / U for v in f[4].split()]
                xs.extend(coords[0::2])
                ys.extend(coords[1::2])
    if not xs:
        bx0 = doc["BBox"]["x"] / U
        by0 = doc["BBox"]["y"] / U
        return bx0, by0, doc["BBox"]["width"] / U, doc["BBox"]["height"] / U
    bx0, bx1 = min(xs), max(xs)
    by0, by1 = min(ys), max(ys)
    return bx0, by0, bx1 - bx0, by1 - by0


def parse_svg_subpaths(path_str):
    """Parse an SVG path string containing M/L/Z commands into [(cmd, x, y)]."""
    tokens = re.findall(r"[MLZmlz]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", path_str)
    out = []
    cmd = None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("M", "L", "m", "l", "Z", "z"):
            cmd = t.upper()
            i += 1
            if cmd == "Z":
                out.append(("Z", 0.0, 0.0))
        else:
            x = float(tokens[i])
            y = float(tokens[i + 1])
            i += 2
            out.append((cmd, x, y))
            if cmd == "M":
                cmd = "L"
    return out


def collect_shapes(doc, bx0, by0, H):
    """Extract normalized board-local primitives (+X right, +Y up, mm)."""
    def to_xy(ex_str, ey_str):
        x = float(ex_str) / U - bx0
        y = H - (float(ey_str) / U - by0)
        return x, y

    outlines = []
    silk_tracks = []
    silk_circles = []
    silk_paths = []
    cu_tracks = []       # (layer, width_mm, [(x, y)])
    pours = []           # (layer, [[(cmd, x, y)]])
    pads = []            # (x, y, w_mm, h_mm, drill_mm, layer)
    vias = []            # (x, y, d_mm, drill_mm)
    holes = []           # (x, y, drill_mm)

    def handle_track(f):
        w = float(f[1]) / U
        layer = f[2]
        coords = [float(v) for v in f[4].split()]
        pts = [(coords[i] / U - bx0, H - (coords[i + 1] / U - by0))
               for i in range(0, len(coords), 2)]
        if layer == "10":
            outlines.append((w, pts))
        elif layer == "3":
            silk_tracks.append((w, pts))
        elif layer in ("1", "2"):
            cu_tracks.append((layer, w, pts))

    def handle_circle(f):
        cx, cy = to_xy(f[1], f[2])
        r = float(f[3]) / U
        w = float(f[4]) / U
        layer = f[5]
        if layer == "3":
            silk_circles.append((cx, cy, r, w))
        elif layer == "10":
            outlines.append((w, []))

    def handle_text(f):
        layer = f[7]
        display = f[12] if len(f) > 12 else ""
        if display == "none":
            return
        w = float(f[4]) / U
        path_str = f[11] if len(f) > 11 else ""
        if layer == "3" and path_str:
            ops = parse_svg_subpaths(path_str)
            conv = [(c, ex / U - bx0, H - (ey / U - by0)) if c != "Z"
                    else ("Z", 0.0, 0.0) for c, ex, ey in ops]
            silk_paths.append((w, conv))

    for sh in doc["shape"]:
        if sh.startswith("LIB~"):
            for sub in sh.split("#@$")[1:]:
                f = sub.split("~")
                if f[0] == "PAD":
                    x, y = to_xy(f[2], f[3])
                    pads.append((x, y, float(f[4]) / U, float(f[5]) / U,
                                 2.0 * float(f[9]) / U, f[6]))
                elif f[0] == "TRACK":
                    handle_track(f)
                elif f[0] == "CIRCLE":
                    handle_circle(f)
                elif f[0] == "TEXT":
                    handle_text(f)
        else:
            f = sh.split("~")
            if f[0] == "TRACK":
                handle_track(f)
            elif f[0] == "CIRCLE":
                handle_circle(f)
            elif f[0] == "TEXT":
                handle_text(f)
            elif f[0] == "HOLE":
                x, y = to_xy(f[1], f[2])
                holes.append((x, y, 2.0 * float(f[3]) / U))
            elif f[0] == "VIA":
                x, y = to_xy(f[1], f[2])
                vias.append((x, y, float(f[3]) / U, 2.0 * float(f[4]) / U))
            elif f[0] == "COPPERAREA":
                layer = f[2]
                raw = f[10] if len(f) > 10 else ""
                if raw and raw != "none":
                    fill = json.loads(raw)
                    # EasyEDA stores [ [path0, path0_dup], ... ] or [ [path0] ]
                    seen = set()
                    polys = []
                    for group in fill:
                        for pstr in (group if isinstance(group, list) else [group]):
                            if not isinstance(pstr, str) or pstr in seen:
                                continue
                            seen.add(pstr)
                            ops = parse_svg_subpaths(pstr)
                            conv = [(c, ex / U - bx0, H - (ey / U - by0))
                                    if c != "Z" else ("Z", 0.0, 0.0)
                                    for c, ex, ey in ops]
                            polys.append(conv)
                    pours.append((layer, polys))

    return dict(outlines=outlines, silk_tracks=silk_tracks,
                silk_circles=silk_circles, silk_paths=silk_paths,
                cu_tracks=cu_tracks, pours=pours, pads=pads,
                vias=vias, holes=holes)


def draw_rulers(c, x_off, y_off, sx, sy, W, H):
    """Draw calibrated 10 mm / 5 mm scale ticks outside the printed board box."""
    from reportlab.lib.colors import Color
    c.saveState()
    c.setStrokeColor(Color(0.35, 0.35, 0.35))
    c.setFillColor(Color(0.25, 0.25, 0.25))
    c.setLineWidth(0.35)
    c.setFont("Helvetica", 6.5)

    def phys_pt(x, y):
        return (x_off + x * sx) * MM_TO_PT, (y_off + y * sy) * MM_TO_PT

    # horizontal ruler along the bottom (left-to-right 0..W mm)
    for mm in range(0, int(round(W)) + 1, 5):
        tick = 2.6 if mm % 10 == 0 else 1.4
        x0, y0 = phys_pt(mm, -1.5)
        x1, y1 = phys_pt(mm, -1.5 - tick)
        c.line(x0, y0, x1, y1)
        if mm % 20 == 0:
            xt, yt = phys_pt(mm, -7.2)
            c.drawCentredString(xt, yt, "%d" % mm)

    # vertical ruler along the left (bottom-to-top 0..H mm)
    for mm in range(0, int(round(H)) + 1, 5):
        tick = 2.6 if mm % 10 == 0 else 1.4
        x0, y0 = phys_pt(-1.5, mm)
        x1, y1 = phys_pt(-1.5 - tick, mm)
        c.line(x0, y0, x1, y1)
        if mm % 10 == 0:
            xt, yt = phys_pt(-7.0, mm)
            c.drawRightString(xt, yt - 2.0, "%d" % mm)

    c.restoreState()


def render_pdf(doc, out_pdf, measured_w=None, measured_h=None):
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import Color, black, white

    bx0, by0, W, H = board_bounds_mm(doc)
    mw = W if measured_w is None else measured_w
    mh = H if measured_h is None else measured_h
    sx = W / mw
    sy = H / mh
    data = collect_shapes(doc, bx0, by0, H)

    c = canvas.Canvas(out_pdf, pagesize=(A4_W * MM_TO_PT, A4_H * MM_TO_PT),
                      invariant=1)
    c.setCreator("tools/export_easyeda_pdf.py")
    c.setProducer("tools/export_easyeda_pdf.py")
    c.setTitle("Calibrated EasyEDA PCB Print (1:1)")
    c._doc.invariant = 1

    x_off = (A4_W - W * sx) / 2.0
    y_top_block = 178.0       # upper half of A4: non-mirrored fit check
    y_bot_block = 48.0        # lower half of A4: mirrored bottom copper (LUT)

    def make_mapper(y_off, mirror_x):
        def m(x, y):
            xx = (W - x) if mirror_x else x
            return (x_off + xx * sx) * MM_TO_PT, (y_off + y * sy) * MM_TO_PT
        return m

    # Page header
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString((A4_W / 2.0) * MM_TO_PT, (A4_H - 18.0) * MM_TO_PT,
                        "ESP32 Weather Station PCB - Exact 1:1 (%.1f x %.1f mm)" % (W, H))
    c.setFont("Helvetica", 9)
    if measured_w is None and measured_h is None:
        cal_txt = "Scale: X = 1.00000, Y = 1.00000 (no printer calibration)"
        tip_txt = ("On screen: adjust zoom until 0..%.0f mm matches a ruler on your monitor. "
                   "On paper: print at 100%% / Actual size." % W)
    else:
        cal_txt = (
            "Target board: %.1f x %.1f mm  |  Measured: %.1f x %.1f mm  |  "
            "Applied scale: X = %.5f, Y = %.5f"
            % (W, H, mw, mh, sx, sy)
        )
        tip_txt = ("Keep the same page orientation and 100%% scale; verify frame = %.1f x %.1f mm with a ruler."
                   % (W, H))
    c.drawCentredString((A4_W / 2.0) * MM_TO_PT, (A4_H - 25.0) * MM_TO_PT, cal_txt)
    c.drawCentredString((A4_W / 2.0) * MM_TO_PT, (A4_H - 31.0) * MM_TO_PT, tip_txt)

    # ------------------------------------------------------------------ #
    #  Block 1: TOP VIEW (NOT mirrored) - place real ESP32 here to test
    # ------------------------------------------------------------------ #
    m_top = make_mapper(y_top_block, mirror_x=False)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x_off * MM_TO_PT, (y_top_block + H * sy + 6.0) * MM_TO_PT,
                 "1. TOP VIEW (DO NOT MIRROR) - verify ESP32 & connector fit")

    # Board outline
    c.setStrokeColor(Color(0.2, 0.2, 0.2))
    c.setLineWidth(0.55)
    for _, pts in data["outlines"]:
        if len(pts) < 2:
            continue
        p = c.beginPath()
        p.moveTo(*m_top(*pts[0]))
        for x, y in pts[1:]:
            p.lineTo(*m_top(x, y))
        c.drawPath(p)

    # Top silkscreen tracks, circles & text paths
    c.setStrokeColor(Color(0.45, 0.45, 0.45))
    c.setLineCap(1)
    c.setLineJoin(1)
    for w, pts in data["silk_tracks"]:
        if len(pts) < 2:
            continue
        c.setLineWidth(max(w * 0.85, 0.14) * MM_TO_PT)
        p = c.beginPath()
        p.moveTo(*m_top(*pts[0]))
        for x, y in pts[1:]:
            p.lineTo(*m_top(x, y))
        c.drawPath(p)
    for cx, cy, r, w in data["silk_circles"]:
        c.setLineWidth(max(w * 0.85, 0.14) * MM_TO_PT)
        px, py = m_top(cx, cy)
        c.ellipse(px - r * sx * MM_TO_PT, py - r * sy * MM_TO_PT,
                  px + r * sx * MM_TO_PT, py + r * sy * MM_TO_PT,
                  stroke=1, fill=0)
    for w, ops in data["silk_paths"]:
        c.setLineWidth(max(w * 0.85, 0.12) * MM_TO_PT)
        p = c.beginPath()
        for cmd, x, y in ops:
            if cmd == "M":
                p.moveTo(*m_top(x, y))
            elif cmd == "L":
                p.lineTo(*m_top(x, y))
            elif cmd == "Z":
                p.close()
        c.drawPath(p)

    # Pads & drills (high contrast for eyeball check)
    for x, y, pw, ph, drill, _ in data["pads"]:
        px, py = m_top(x, y)
        rx = (pw / 2.0) * sx * MM_TO_PT
        ry = (ph / 2.0) * sy * MM_TO_PT
        c.setFillColor(Color(0.75, 0.25, 0.15))
        c.setStrokeColor(Color(0.45, 0.12, 0.08))
        c.setLineWidth(0.3)
        c.ellipse(px - rx, py - ry, px + rx, py + ry, stroke=1, fill=1)
        hrx = (drill / 2.0) * sx * MM_TO_PT
        hry = (drill / 2.0) * sy * MM_TO_PT
        c.setFillColor(white)
        c.ellipse(px - hrx, py - hry, px + hrx, py + hry, stroke=0, fill=1)
    for x, y, drill in data["holes"]:
        px, py = m_top(x, y)
        hrx = (drill / 2.0) * sx * MM_TO_PT
        hry = (drill / 2.0) * sy * MM_TO_PT
        c.setFillColor(Color(0.2, 0.2, 0.2))
        c.ellipse(px - hrx, py - hry, px + hrx, py + hry, stroke=0, fill=1)

    draw_rulers(c, x_off, y_top_block, sx, sy, W, H)

    # ------------------------------------------------------------------ #
    #  Block 2: BOTTOM COPPER (MIRRORED for LUT toner transfer)
    # ------------------------------------------------------------------ #
    m_bot = make_mapper(y_bot_block, mirror_x=True)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x_off * MM_TO_PT, (y_bot_block + H * sy + 6.0) * MM_TO_PT,
                 "2. BOTTOM COPPER (MIRRORED FOR LUT) - black = copper, white = etched/drill")

    # 1) Ground pour(s) on BottomLayer ("2"), even-odd fill
    c.setFillColor(black)
    for layer, polys in data["pours"]:
        if layer != "2":
            continue
        for ops in polys:
            p = c.beginPath()
            for cmd, x, y in ops:
                if cmd == "M":
                    p.moveTo(*m_bot(x, y))
                elif cmd == "L":
                    p.lineTo(*m_bot(x, y))
                elif cmd == "Z":
                    p.close()
            c.drawPath(p, stroke=0, fill=1, fillMode=0)

    # 2) Copper tracks on BottomLayer ("2")
    c.setStrokeColor(black)
    c.setLineCap(1)
    c.setLineJoin(1)
    for layer, w, pts in data["cu_tracks"]:
        if layer != "2" or len(pts) < 2:
            continue
        c.setLineWidth(w * ((sx + sy) / 2.0) * MM_TO_PT)
        p = c.beginPath()
        p.moveTo(*m_bot(*pts[0]))
        for x, y in pts[1:]:
            p.lineTo(*m_bot(x, y))
        c.drawPath(p)

    # 3) Through-hole pads + vias in solid black
    c.setFillColor(black)
    for x, y, pw, ph, _, _ in data["pads"]:
        px, py = m_bot(x, y)
        rx = (pw / 2.0) * sx * MM_TO_PT
        ry = (ph / 2.0) * sy * MM_TO_PT
        c.ellipse(px - rx, py - ry, px + rx, py + ry, stroke=0, fill=1)
    for x, y, d, _ in data["vias"]:
        px, py = m_bot(x, y)
        rx = (d / 2.0) * sx * MM_TO_PT
        ry = (d / 2.0) * sy * MM_TO_PT
        c.ellipse(px - rx, py - ry, px + rx, py + ry, stroke=0, fill=1)

    # 4) Drill pilot centers + mounting holes in crisp white
    c.setFillColor(white)
    for x, y, _, _, drill, _ in data["pads"]:
        px, py = m_bot(x, y)
        hrx = (drill / 2.0) * sx * MM_TO_PT
        hry = (drill / 2.0) * sy * MM_TO_PT
        c.ellipse(px - hrx, py - hry, px + hrx, py + hry, stroke=0, fill=1)
    for x, y, _, drill in data["vias"]:
        px, py = m_bot(x, y)
        hrx = (drill / 2.0) * sx * MM_TO_PT
        hry = (drill / 2.0) * sy * MM_TO_PT
        c.ellipse(px - hrx, py - hry, px + hrx, py + hry, stroke=0, fill=1)
    for x, y, drill in data["holes"]:
        px, py = m_bot(x, y)
        hrx = (drill / 2.0) * sx * MM_TO_PT
        hry = (drill / 2.0) * sy * MM_TO_PT
        c.ellipse(px - hrx, py - hry, px + hrx, py + hry, stroke=0, fill=1)

    # 5) Thin board cut outline outside the copper
    c.setStrokeColor(Color(0.3, 0.3, 0.3))
    c.setLineWidth(0.35)
    for _, pts in data["outlines"]:
        if len(pts) < 2:
            continue
        p = c.beginPath()
        p.moveTo(*m_bot(*pts[0]))
        for x, y in pts[1:]:
            p.lineTo(*m_bot(x, y))
        c.drawPath(p)

    draw_rulers(c, x_off, y_bot_block, sx, sy, W, H)

    c.showPage()
    c.save()
    print("wrote %s (target %.1fx%.1f mm, measured %.1fx%.1f mm, scale X=%.5f Y=%.5f)"
          % (out_pdf, W, H, mw, mh, sx, sy))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="Path to EasyEDA Standard PCB JSON")
    ap.add_argument("-o", "--output", required=True, help="Output PDF path")
    ap.add_argument("--measured-w", type=float, default=None,
                    help="Printed width (mm) measured on paper along the board X axis")
    ap.add_argument("--measured-h", type=float, default=None,
                    help="Printed height (mm) measured on paper along the board Y axis")
    args = ap.parse_args()
    with open(args.input, encoding="utf-8") as f:
        doc = json.load(f)
    render_pdf(doc, args.output, args.measured_w, args.measured_h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
