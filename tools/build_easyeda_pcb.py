#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a 100 x 50 mm PCB for the ESP32 weather station in the native
EasyEDA Standard format (docType 3), ready to open at easyeda.com/editor.

What comes out:
  ESP32_WeatherStation_2026-11-11_pcb.json
      board outline, all 17 footprints placed with their real pads, every pad
      named and assigned to its schematic net, mounting holes, silkscreen and
      a routing rule set.  Tracks are NOT drawn - the ratlines are there for
      you to route (that is the part you asked to do yourself).

  pcb_easyeda_check.txt
      what the script verified before writing: pads, nets, clearance,
      board fit, pin numbering, and the ratline length of every net.

The layout itself (coordinates of every part) lives in tools/pcb_common.py,
shared with the PCB preview generator.

EasyEDA Standard PCB conventions (verified against EasyEDA v6 format docs):
  * 1 unit = 10 mil = 0.254 mm  (U = 1 / 0.254 ~= 3.93700787 units/mm)
  * +X goes right, +Y goes DOWN; board top-left is placed at ORIGIN (4000, 3000)
    so board mm (x, y) (+Y up) maps to (4000 + x*U, 3000 + (BH - y)*U).
  * PAD width/height are diameters in EasyEDA units; holeRadius is a RADIUS.
  * HOLE radius is a RADIUS in EasyEDA units.
  * CIRCLE radius and strokeWidth are in EasyEDA units.
  * TEXT fontSize and strokeWidth are in EasyEDA units; SVG path uses +Y down.
"""
import hashlib
import json
import math
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import pcb_common as pc                      # noqa: E402
import strokefont                            # noqa: E402

if "--mirror-esp32" in sys.argv:
    pc.MIRROR_ESP = True

SUFFIX = "_mirrored" if "--mirror-esp32" in sys.argv else ""
OUT = os.path.join(ROOT, "ESP32_WeatherStation_2026-11-11_pcb%s.json" % SUFFIX)
REPORT = os.path.join(ROOT, "pcb_easyeda_check%s.txt" % SUFFIX)

U = 1.0 / 0.254                              # mm -> EasyEDA units (10 mil)
EDITOR_VERSION = "6.4.25"
ORIGIN = (4000.0, 3000.0)                    # top-left of board in EasyEDA units


def fmt(v):
    """Format a value already in EasyEDA units (10 mil), 4 decimals max."""
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def dim(mm):
    """Length/radius/diameter in mm -> EasyEDA units (10 mil)."""
    return fmt(mm * U)


def pt(x_mm, y_mm):
    """Board mm (+X right, +Y up) -> EasyEDA canvas coords (+X right, +Y down)."""
    return fmt(ORIGIN[0] + x_mm * U), fmt(ORIGIN[1] + (pc.BH - y_mm) * U)


class Ids:
    """Deterministic gge / uuid ids (same board in, same file out)."""

    def __init__(self, seed):
        self.seed = seed
        self.n = 0

    def gge(self):
        self.n += 1
        return "gge%d" % self.n

    def uid(self, tag):
        return hashlib.md5(("%s|%s" % (self.seed, tag)).encode()).hexdigest()


IDS = Ids("esp32-weather-station-pcb-2026-11-11")

LAYERS = [
    "1~TopLayer~#FF0000~true~true~true~",
    "2~BottomLayer~#0000FF~true~false~true~",
    "3~TopSilkLayer~#FFCC00~true~false~true~",
    "4~BottomSilkLayer~#66CC33~true~false~true~",
    "5~TopPasteMaskLayer~#808080~true~false~true~",
    "6~BottomPasteMaskLayer~#800000~true~false~true~",
    "7~TopSolderMaskLayer~#800080~true~false~true~0.3",
    "8~BottomSolderMaskLayer~#AA00FF~true~false~true~0.3",
    "9~Ratlines~#6464FF~true~false~true~",
    "10~BoardOutLine~#FF00FF~true~false~true~",
    "11~Multi-Layer~#C0C0C0~true~false~true~",
    "12~Document~#FFFFFF~true~false~true~",
    "13~TopAssembly~#33CC99~false~false~false~",
    "14~BottomAssembly~#5555FF~false~false~false~",
    "15~Mechanical~#F022F0~false~false~false~",
    "19~3DModel~#66CCFF~false~false~false~",
    "Hole~Hole~#222222~false~false~true~",
    "DRCError~DRCError~#FAD609~false~false~true~",
]

OBJECTS = [
    "All~true~false", "Component~true~true", "Prefix~true~true",
    "Name~true~false", "Track~true~true", "Pad~true~true", "Via~true~true",
    "Hole~true~true", "Copper_Area~true~true", "Circle~true~true",
    "Arc~true~true", "Solid_Region~true~true", "Text~true~true",
    "Image~true~true", "Rect~true~true", "Dimension~true~true",
    "Protractor~true~true",
]


# --------------------------------------------------------------------------- #
#  EasyEDA shapes
# --------------------------------------------------------------------------- #
def pad_shape(x_mm, y_mm, d_mm, drill_mm, num, net, rot=0):
    """Through-hole pad on layer 11 (all copper layers).

    Field 4,5: pad width/height (diameter in 10-mil units).
    Field 8  : pad number, binding the footprint pad to the schematic pin.
    Field 9  : hole RADIUS in 10-mil units (drill_mm / 2).
    """
    cx, cy = pt(x_mm, y_mm)
    return ("PAD~ELLIPSE~%s~%s~%s~%s~11~%s~%s~%s~~%s~%s~0~~Y~0~~~%s,%s"
            % (cx, cy, dim(d_mm), dim(d_mm), net or "", num,
               dim(drill_mm / 2.0), rot, IDS.gge(), cx, cy))


def line_shape(pts_mm, layer=3, width_mm=0.15, net=""):
    """Silkscreen / outline polyline (TRACK on a non-copper layer)."""
    flat = " ".join("%s %s" % pt(x, y) for x, y in pts_mm)
    return "TRACK~%s~%d~%s~%s~%s~0" % (dim(width_mm), layer, net, flat, IDS.gge())


def circle_shape(cx_mm, cy_mm, r_mm, layer=3, width_mm=0.15):
    cx, cy = pt(cx_mm, cy_mm)
    return "CIRCLE~%s~%s~%s~%s~%d~%s~0" % (
        cx, cy, dim(r_mm), dim(width_mm), layer, IDS.gge())


def text_shape(x_mm, y_mm, s, size_mm=1.0, layer=3, rot=0, align="middle",
               anchor="baseline", width_mm=0.15, text_type="L"):
    """Silkscreen text, stored as stroke geometry in EasyEDA +Y-down coords.

    text_type: 'P' for component Prefix/Designator, 'N' for Value, 'L' for label.
    """
    lines = strokefont.text_polylines(s, x_mm, y_mm, size_mm, rot=rot,
                                      align=align, anchor=anchor)
    path = " ".join(
        "M %s %s" % pt(p[0][0], p[0][1])
        + "".join(" L %s %s" % pt(qx, qy) for qx, qy in p[1:])
        for p in lines if len(p) > 1
    )
    # EasyEDA stores TEXT (x, y) at the rotated bottom-left baseline origin
    w_mm = strokefont.text_width(s, size_mm)
    if align == "middle":
        px0 = -w_mm / 2.0
    elif align == "end":
        px0 = -w_mm
    else:
        px0 = 0.0
    py0 = -size_mm / 2.0 if anchor == "middle" else 0.0
    rx0, ry0 = pc.rotate(px0, py0, rot)
    tx, ty = pt(x_mm + rx0, y_mm + ry0)
    return ("TEXT~%s~%s~%s~%s~%d~0~%d~~%s~%s~%s~~%s~~0~"
            % (text_type, tx, ty, dim(width_mm), rot, layer, dim(size_mm),
               s, path, IDS.gge()))


def footprint_shape(fp):
    """LIB block: header + pads + silk + designator + value."""
    child = []
    # designator (Prefix = P)
    (rx, ry), rsize = fp.ref_pos()
    child.append(text_shape(rx, ry, fp.ref, size_mm=rsize, align="middle",
                            anchor="middle", text_type="P"))

    # silkscreen graphics
    for item in fp.silk:
        if item[0] == "line":
            child.append(line_shape(item[1], layer=3))
        elif item[0] == "circle":
            child.append(circle_shape(item[1], item[2], item[3]))
        elif item[0] == "text":
            child.append(text_shape(item[1], item[2], item[3], size_mm=item[4]))

    # value, only where there is room for it
    v = fp.value_pos()
    if v and fp.value.strip():
        (vx, vy), vsize = v
        child.append(text_shape(vx, vy, fp.value, size_mm=vsize, align="middle",
                                anchor="middle", text_type="N"))

    # pin-1 square
    m = fp.pin1_mark()
    if m:
        child.append(line_shape(m, layer=3, width_mm=0.15))

    # pad names, tucked in next to each pad (the ESP32 header needs them)
    for nm, lx, ly, lsz, lrot in pc.esp_pin_names([fp]):
        if fp.kind == "module":
            child.append(text_shape(lx, ly, nm, size_mm=lsz, rot=lrot,
                                    align="middle", anchor="middle",
                                    text_type="L"))

    # pads
    for p in fp.pads:
        x, y = fp.abs_pad(p)
        child.append(pad_shape(x, y, p["d"], p["drill"], p["num"], p["net"]))

    params = ("package`%s`BOM_Manufacturer Part`%s`spicePre`%s`"
              "spiceSymbolName`%s`Contributor`schem-fix`"
              % (fp.package, fp.value, fp.prefix, fp.package))
    fx, fy = pt(fp.x, fp.y)
    # LIB~x~y~params~rot~importFlag~id~layer~uuid~utime~locked
    head = "LIB~%s~%s~%s~0~~%s~1~%s~1794393600~0" % (
        fx, fy, params, IDS.gge(), IDS.uid(fp.ref))
    return head + "#@$" + "#@$".join(child)


def board_outline():
    """Rounded-rectangle outline on layer 10 (BoardOutLine)."""
    r = 2.0
    pts = []
    corners = [(r, r, 180), (pc.BW - r, r, 270),
               (pc.BW - r, pc.BH - r, 0), (r, pc.BH - r, 90)]
    for cx, cy, a0 in corners:
        for k in range(7):
            a = math.radians(a0 + 90.0 * k / 6.0)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return line_shape(pts, layer=10, width_mm=0.254)


# --------------------------------------------------------------------------- #
#  build
# --------------------------------------------------------------------------- #
def main():
    parts = pc.build_parts()
    pin_net, net_pins = pc.load_netlist()
    pc.assign_nets(parts, pin_net)
    holes = pc.mount_holes()

    pads = pc.all_pads(parts)
    nets = sorted({p["net"] for _, p, _, _ in pads if p["net"]})
    unconnected = [(r, p["num"], p["name"]) for r, p, _, _ in pads if not p["net"]]

    shapes = [board_outline()]
    for fp in parts:
        shapes.append(footprint_shape(fp))

    # mounting holes: NPTH (no copper ring), drawn as a HOLE (radius) + silk circle
    for hx, hy in holes:
        ex, ey = pt(hx, hy)
        shapes.append("HOLE~%s~%s~%s~%s~0" % (ex, ey,
                                             dim(pc.DRILL_MOUNT / 2.0),
                                             IDS.gge()))
        shapes.append(circle_shape(hx, hy, pc.MOUNT_RING, layer=3,
                                   width_mm=0.12))

    # --- title block / notes on the top silk --------------------------------
    title_s, tx, ty, tsz = pc.BOARD_TITLE
    shapes.append(text_shape(tx, ty, title_s, size_mm=tsz, align="middle",
                             anchor="baseline", text_type="L"))

    # User origin (bottom-left corner of the board = (0, 0) in pcb_common)
    orig_x, orig_y = pt(0.0, 0.0)

    doc = {
        "head": {
            "docType": "3",
            "editorVersion": EDITOR_VERSION,
            "newgId": True,
            "c_para": {},
            "hasIdFlag": True,
            "x": orig_x,
            "y": orig_y,
            "importFlag": 0,
            "transformList": "",
        },
        "canvas": ("CA~1000~1000~#000000~yes~#FFFFFF~10~1000~1000~line~0.5~mm~"
                   "2.54~45~visible~0.5~%s~%s~0~yes" % (orig_x, orig_y)),
        "shape": shapes,
        "layers": LAYERS,
        "objects": OBJECTS,
        "BBox": {
            "x": ORIGIN[0],
            "y": ORIGIN[1],
            "width": round(pc.BW * U, 2),
            "height": round(pc.BH * U, 2),
        },
        "preference": {"hideFootprints": "", "hideNets": ""},
        "DRCRULE": {
            "Default": {
                "trackWidth": round(0.60 * U, 4),       # 0.60 mm
                "clearance": round(0.30 * U, 4),        # 0.30 mm
                "viaHoleDiameter": round(0.80 * U, 4),  # 0.80 mm
                "viaHoleD": round(0.40 * U, 4),         # 0.40 mm
            },
            "isRealtime": True,
            "isDrcOnRoutingOrPlaceVia": False,
            "checkObjectToCopperarea": True,
            "showDRCRangeLine": True,
        },
        "routerRule": {
            "unit": "mm",
            "trackWidth": 0.6,
            "trackClearance": 0.3,
            "viaHoleD": 0.4,
            "viaDiameter": 0.8,
            "routerLayers": [1, 2],
            "smdClearance": 0.2,
            "specialNets": [
                {"net": "+5V", "width": "1.2px", "clearance": "0.3px",
                 "viaHoleD": "0.4px", "viaHoleDiameter": "0.8px"},
                {"net": "GND", "width": "1.2px", "clearance": "0.3px",
                 "viaHoleD": "0.4px", "viaHoleDiameter": "0.8px"},
            ],
            "nets": nets,
            "padsCount": len(pads),
            "skipNets": [],
            "realtime": True,
        },
        "netColors": {},
        "title": "ESP32_WeatherStation_PCB",
        "description": ("ESP32 weather station, 100x50 mm horizontal, "
                        "EasyEDA Standard format, unrouted with ratlines"),
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ #
    #  report
    # ------------------------------------------------------------------ #
    dart = pc.drc(parts, holes)
    silk = pc.check_silk(parts, holes)
    conn = pc.check_connectivity(parts, net_pins)
    lines = []
    lines.append("EasyEDA PCB check - %s" % date.today().isoformat())
    lines.append("=" * 68)
    usb_side = "right (mirrored)" if pc.MIRROR_ESP else "left"
    lines.append("board          : %.0f x %.0f mm horizontal, origin bottom-left, USB on the %s"
                 % (pc.BW, pc.BH, usb_side))
    lines.append("footprints     : %d" % len(parts))
    lines.append("pads           : %d  (%d connected, %d spare GPIO pads)"
                 % (len(pads), len(pads) - len(unconnected), len(unconnected)))
    lines.append("nets           : %d (all from the schematic netlist)" % len(nets))
    lines.append("mounting holes : %d, %.1f mm NPTH" % (len(holes), pc.DRILL_MOUNT))
    lines.append("")
    lines.append("pad clearance  : %s" % ("OK (>= 0.30 mm)" if not dart
                                          else "FAILED"))
    for e in dart:
        lines.append("   ! " + e)
    lines.append("silkscreen     : %s" % ("OK - no text or line on a pad, no "
                                          "text collisions" if not silk
                                          else "FAILED"))
    for e in silk:
        lines.append("   ! " + e)
    lines.append("connectivity   : %s" % ("OK - board pads match the schematic "
                                          "netlist exactly" if not conn
                                          else "FAILED"))
    for e in conn:
        lines.append("   ! " + e)
    lines.append("")
    lines.append("Unconnected (spare) ESP32 pins, left for future use:")
    lines.append("   " + ", ".join("%s(%s)" % (n, p) for _, p, n in unconnected))
    lines.append("")
    lines.append("Netlist and ratline length (route these):")
    groups = {}
    for ref, p, x, y in pads:
        if p["net"]:
            groups.setdefault(p["net"], []).append((ref, p, x, y))
    total = 0.0
    for net in sorted(groups, key=lambda n: -len(groups[n])):
        g = groups[net]
        rest = g[1:]
        cur = g[0]
        ln = 0.0
        while rest:
            nxt = min(rest, key=lambda q: math.hypot(q[2] - cur[2], q[3] - cur[3]))
            ln += math.hypot(nxt[2] - cur[2], nxt[3] - cur[3])
            cur = nxt
            rest.remove(nxt)
        total += ln
        pads_s = " ".join("%s.%s" % (r, q["num"]) for r, q, _, _ in g)
        lines.append("  %-12s %2d pads  ~%5.0f mm  %s"
                     % (net, len(g), ln, pads_s))
    lines.append("")
    lines.append("  approx. total track length to route: %.0f mm" % total)
    lines.append("")
    lines.append("Routing rules written into the file:")
    lines.append("  track width %.2f mm, clearance %.2f mm, via 0.8/0.4 mm"
                 % (0.6, 0.3))
    lines.append("  +5V and GND are flagged as wide nets (1.2 mm) in routerRule")
    lines.append("")
    if not pc.MIRROR_ESP:
        lines.append("WARNING: pin 1 of U1 is 3V3 at the USB end. Check the silkscreen")
        lines.append("         of your module before soldering the sockets.")
    else:
        lines.append("NOTE: built with --mirror-esp32 (module rotated 180 deg).")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("wrote %s (%d shapes)" % (OUT, len(shapes)))
    print("wrote %s" % REPORT)
    print("pads %d, nets %d, spare pins %d, drc %s, silk %s, connectivity %s"
          % (len(pads), len(nets), len(unconnected),
             "OK" if not dart else "FAILED", "OK" if not silk else "FAILED",
             "OK" if not conn else "FAILED"))
    if dart or silk or conn:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
