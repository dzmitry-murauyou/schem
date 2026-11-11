#!/usr/bin/env python3
"""
Rebuild the EasyEDA v6 schematic for the ESP32 weather-station project so that it
matches the agreed hardware specification.

Inputs : SCH_New-Project1_2026-11-11.json   (the ORIGINAL, unmodified export)
Outputs: SCH_ESP32_WeatherStation_2026-11-11.json   (EasyEDA v6, importable)
         netlist.txt / netlist.json                 (derived from the drawn geometry)
         bom.csv

The generator keeps two things from the original file verbatim:
  * shape 0  -> the A4 drawing frame / title block
  * shape 1  -> the ESP32-DEVKIT-V1-30PIN_DZ symbol (all 30 pins)
Everything else is rebuilt from scratch.

Run:  python3 tools/build_schematic.py
"""

import csv
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "SCH_New-Project1_2026-11-11.json")
OUT_JSON = os.path.join(ROOT, "SCH_ESP32_WeatherStation_2026-11-11.json")

TS = "1794393600"          # 2026-11-11, used only for the symbol "last edited" stamps
WIRE_COLOR = "#008800"
BODY_COLOR = "#880000"
LABEL_COLOR = "#0000ff"


# --------------------------------------------------------------------------- #
#  small helpers
# --------------------------------------------------------------------------- #
def n(v):
    """Compact number formatting, EasyEDA style (no trailing zeros)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, float) and v == int(v):
        v = int(v)
    if isinstance(v, int):
        return str(v)
    s = "%.5f" % v
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Ids:
    """Deterministic, collision-free gge ids and md5 uuids."""

    def __init__(self, start=20000):
        self.counter = start

    def nid(self):
        self.counter += 1
        return "gge%d" % self.counter

    @staticmethod
    def uid(seed):
        return hashlib.md5(seed.encode("utf-8")).hexdigest()


IDS = Ids()


def attrs(pairs):
    """Build the EasyEDA `key`value`key`value`...` attribute blob (ends with `)."""
    return "".join("%s`%s`" % (k, v) for k, v in pairs)


def lib_head(x, y, att, sid, seed, rot=0):
    return "LIB~%s~%s~%s~~%d~%s~%s~%s~0~%s~yes~yes~%s~%s~%s" % (
        n(x), n(y), att, rot, sid,
        Ids.uid(seed + "a"), Ids.uid(seed + "b"), Ids.uid(seed + "c")[:16],
        Ids.uid(seed + "d"), TS, Ids.uid(seed + "e"),
    )


def txt(kind, x, y, s):
    """kind: 'N' = name/comment, 'P' = designator, 'L' = loose text."""
    return "T~%s~%s~%s~0~#000080~Arial~~~~~comment~%s~1~start~%s~0~pinpart" % (
        kind, n(x), n(y), s, IDS.nid()
    )


def pin(num, px, py, rot, body_edge, pin_name, show_name=1, show_num=1):
    """
    One schematic pin.

    rot 180 -> pin sits on the LEFT  of the body, stub is drawn  body_edge -> px (px < body_edge)
    rot   0 -> pin sits on the RIGHT of the body, stub is drawn  body_edge -> px (px > body_edge)
    """
    if rot == 180:
        path = "M %s %s h %s" % (n(px), n(py), n(body_edge - px))
        nx, ny, nanchor = body_edge + 3.7, py + 4, "start"
        mx, my, manchor = body_edge - 0.5, py - 1, "end"
        dx = px + 7
        arrow = "M %s %s L %s %s L %s %s" % (
            n(px + 10), n(py - 3), n(px + 13), n(py), n(px + 10), n(py + 3))
    else:
        path = "M %s %s h %s" % (n(body_edge), n(py), n(px - body_edge))
        nx, ny, nanchor = body_edge + 3.7, py + 4, "start"
        mx, my, manchor = body_edge - 0.5, py - 1, "end"
        dx = px - 7
        arrow = "M %s %s L %s %s L %s %s" % (
            n(px - 10), n(py - 3), n(px - 7), n(py), n(px - 10), n(py + 3))

    return "^^".join([
        "P~show~0~%s~%s~%s~%d~%s~0" % (num, n(px), n(py), rot, IDS.nid()),
        "%s~%s" % (n(px), n(py)),
        "%s~%s" % (path, BODY_COLOR),
        "%d~%s~%s~0~%s~%s~~~#0000FF" % (show_name, n(nx), n(ny), pin_name, nanchor),
        "%d~%s~%s~0~%s~%s~~~#0000FF" % (show_num, n(mx), n(my), num, manchor),
        "0~%s~%s" % (n(dx), n(py)),
        "0~%s" % arrow,
    ])


def rect(x, y, rx, ry, w, h, color=BODY_COLOR):
    return "R~%s~%s~%s~%s~%s~%s~%s~1~0~none~%s~0~" % (
        n(x), n(y), n(rx), n(ry), n(w), n(h), color, IDS.nid())


def pline(x1, y1, x2, y2, color=BODY_COLOR):
    return "PL~%s %s %s %s~%s~1~0~none~%s~0" % (n(x1), n(y1), n(x2), n(y2), color, IDS.nid())


def polyline(points, color=BODY_COLOR):
    return "PL~%s~%s~1~0~none~%s~0" % (
        " ".join("%s %s" % (n(a), n(b)) for a, b in points), color, IDS.nid())


def poly(pts, color=BODY_COLOR, fill=BODY_COLOR):
    return "PG~%s~%s~1~0~%s~%s~0" % (" ".join(n(p) for p in pts), color, fill, IDS.nid())


def ell(x, y, rx=1.5, ry=1.5):
    return "E~%s~%s~%s~%s~%s~1~0~%s~%s~0" % (n(x), n(y), n(rx), n(ry), BODY_COLOR, BODY_COLOR, IDS.nid())


def wire(x1, y1, x2, y2):
    return "W~%s %s %s %s~%s~1~0~none~%s~0" % (n(x1), n(y1), n(x2), n(y2), WIRE_COLOR, IDS.nid())


def netlabel(x, y, name, anchor="start"):
    """Net label. (x, y) is the attachment point, text is drawn 6 units above it."""
    return "N~%s~%s~0~%s~%s~%s~%s~%s~%s~Times New Roman~7pt~0" % (
        n(x), n(y), LABEL_COLOR, name, IDS.nid(), anchor, n(x), n(y - 6))


# --------------------------------------------------------------------------- #
#  component builders
#  Each returns (shape_string, {pin_number_or_name: (x, y)})
# --------------------------------------------------------------------------- #
def build_header(bl, yc, names, des, disp, pkg, spice, seed,
                 mfr="", mfrpn="", lcsc="", spacing=20.0):
    """Generic 1xN pin-header / solder-pad symbol. Body at x=bl..bl+20, pins point LEFT."""
    cnt = len(names)
    half = (cnt - 1) * spacing / 2.0
    top = yc - half - 10
    h = (cnt - 1) * spacing + 20

    body = [rect(bl, top, 2, 2, 20, h)]
    primitives = [
        txt("N", bl - 1.97, top - 3.33, disp),
        txt("P", bl - 1.97, top - 12.2, des),
    ]
    points = {}
    pin1_y = None
    for i, nm in enumerate(names, start=1):
        py = yc - half + (i - 1) * spacing
        if i == 1:
            pin1_y = py
        px = bl - 20
        primitives.append(pin(str(i), px, py, 180, bl, nm))
        points[str(i)] = (px, py)
        points[nm] = (px, py)
    body.append(ell(bl + 5, pin1_y - 5))

    att = attrs([
        ("package", pkg),
        ("Manufacturer Part", mfrpn),
        ("Supplier Part", lcsc),
        ("Manufacturer", mfr),
        ("Contributor", "schem-fix"),
        ("JLCPCB Part Class", "Extended Part"),
        ("spicePre", spice),
        ("spiceSymbolName", pkg),
    ])
    shape = lib_head(bl, yc, att, IDS.nid(), seed) + "#@$" + "#@$".join(primitives + body)
    return shape, points


def build_resistor(x0, py, des, value, pkg, seed):
    """Classic zig-zag resistor. pin1 at x0 (left), body x0+10..x0+50, pin2 at x0+60."""
    zig = [(x0 + 10, py), (x0 + 18, py - 6), (x0 + 26, py + 6),
           (x0 + 34, py - 6), (x0 + 42, py + 6), (x0 + 50, py)]
    primitives = [
        txt("N", x0 + 12, py - 13, value),
        txt("P", x0 + 12, py - 23, des),
        pline(x0, py, x0 + 10, py),
        polyline(zig, "#A00000"),
        pline(x0 + 50, py, x0 + 60, py),
        pin("1", x0, py, 180, x0 + 10, "1", show_name=0, show_num=0),
        pin("2", x0 + 60, py, 0, x0 + 50, "2", show_name=0, show_num=0),
    ]
    att = attrs([
        ("package", pkg),
        ("Manufacturer Part", value),
        ("Supplier Part", ""),
        ("Manufacturer", ""),
        ("Contributor", "schem-fix"),
        ("JLCPCB Part Class", "Extended Part"),
        ("spicePre", "R"),
        ("spiceSymbolName", "R"),
    ])
    shape = lib_head(x0, py, att, IDS.nid(), seed) + "#@$" + "#@$".join(primitives)
    return shape, {"1": (x0, py), "2": (x0 + 60, py)}


def build_led(x, py, des, disp, pkg, seed, color="#00A000"):
    """LED: triangle pointing right at x..x+20 + cathode bar. pin1 = A (left), pin2 = K (right)."""
    primitives = [
        txt("N", x + 0.03, py - 18, disp),
        txt("P", x + 0.03, py - 26.87, des),
        poly([x, py - 10, x + 20, py, x, py + 10], BODY_COLOR, color),
        pline(x + 20, py - 10, x + 20, py + 10),
        pline(x + 4, py - 6, x + 14, py - 16),
        poly([x + 10, py - 16, x + 14, py - 16, x + 14, py - 12]),
        pline(x + 10, py - 4, x + 20, py - 14),
        poly([x + 16, py - 14, x + 20, py - 14, x + 20, py - 10]),
        pin("1", x - 20, py, 180, x, "A", show_num=0),
        pin("2", x + 40, py, 0, x + 20, "K", show_num=0),
    ]
    att = attrs([
        ("package", pkg),
        ("Manufacturer Part", disp),
        ("Supplier Part", ""),
        ("Manufacturer", ""),
        ("Contributor", "schem-fix"),
        ("JLCPCB Part Class", "Extended Part"),
        ("spicePre", "D"),
        ("spiceSymbolName", "LED"),
    ])
    shape = lib_head(x, py, att, IDS.nid(), seed) + "#@$" + "#@$".join(primitives)
    return shape, {"1": (x - 20, py), "2": (x + 40, py), "A": (x - 20, py), "K": (x + 40, py)}


def build_buzzer(bx, by, des, disp, pkg, seed):
    """Passive buzzer: body bx..bx+30 / by..by+40, two pins on the left, pin1 = '+', pin2 = '-'."""
    primitives = [
        txt("N", bx - 1.97, by - 3.33, disp),
        txt("P", bx - 1.97, by - 12.2, des),
        rect(bx, by, 2, 2, 30, 40),
        pline(bx + 12, by + 20, bx + 18, by + 20),
        pline(bx + 15, by + 17, bx + 15, by + 23),
        pin("1", bx - 20, by + 10, 180, bx, "+", show_num=0),
        pin("2", bx - 20, by + 30, 180, bx, "-", show_num=0),
    ]
    att = attrs([
        ("package", pkg),
        ("Manufacturer Part", disp),
        ("Supplier Part", ""),
        ("Manufacturer", ""),
        ("Contributor", "schem-fix"),
        ("JLCPCB Part Class", "Extended Part"),
        ("spicePre", "BZ"),
        ("spiceSymbolName", "BUZZER"),
    ])
    shape = lib_head(bx, by, att, IDS.nid(), seed) + "#@$" + "#@$".join(primitives)
    return shape, {"1": (bx - 20, by + 10), "2": (bx - 20, by + 30),
                   "+": (bx - 20, by + 10), "-": (bx - 20, by + 30)}


# --------------------------------------------------------------------------- #
#  ESP32 symbol, taken from the original file and cleaned up
# --------------------------------------------------------------------------- #
ESP32_LEFT = {   # pin name -> y
    "3V3": -725, "GND": -715, "D15": -705, "D2": -695, "D4": -685,
    "RX2": -675, "TX2": -665, "D5": -655, "D18": -645, "D19": -635,
    "D21": -625, "RX0": -615, "TX0": -605, "D22": -595, "D23": -585,
}
ESP32_RIGHT = {
    "VIN": -725, "GND2": -715, "D13": -705, "D12": -695, "D14": -685,
    "D27": -675, "D26": -665, "D25": -655, "D33": -645, "D32": -635,
    "D35": -625, "D34": -615, "VN": -605, "VP": -595, "EN": -585,
}
ESP32_X = {"L": 135, "R": 295}


def esp32_shape(original):
    """Keep the original 30-pin symbol, but:
       - fix the designator (it was '1') -> U1
       - hide the duplicated outer pin-name text (it is drawn twice by the library
         symbol and would sit on top of the net-label stubs we are about to add)."""
    subs = original.split("#@$")
    out = [subs[0]]
    for s in subs[1:]:
        if s.startswith("P~show~3~"):
            f = s.split("^^")
            if len(f) > 4 and f[4].startswith("1~"):
                f[4] = "0" + f[4][1:]
            s = "^^".join(f)
        out.append(s)
    shape = "#@$".join(out)
    shape = shape.replace("~comment~1~1~start~gge239~0~pinpart",
                          "~comment~U1~1~start~gge239~0~pinpart")
    return shape


# --------------------------------------------------------------------------- #
#  net connectivity description  (designator, pin) -> net
# --------------------------------------------------------------------------- #
NETS = {
    "+5V":       [("U1", "VIN"), ("J_PWR", "1"), ("J_LCD", "2"), ("J_RTC", "1")],
    "+3V3":      [("U1", "3V3"), ("J_SENSOR", "1")],
    "GND":       [("U1", "GND"), ("U1", "GND2"), ("J_PWR", "2"), ("J_LCD", "1"), ("J_SENSOR", "2"),
                  ("J_RTC", "2"), ("J_BTN1", "2"), ("J_BTN2", "2"), ("J_BTN3", "2"), ("J_BTN4", "2"),
                  ("LED1", "2"), ("LED2", "2"), ("LED3", "2"), ("BZ1", "2")],
    "SDA":       [("U1", "D21"), ("J_LCD", "3"), ("J_SENSOR", "4")],
    "SCL":       [("U1", "D22"), ("J_LCD", "4"), ("J_SENSOR", "3")],
    "RTC_RST":   [("U1", "RX2"), ("J_RTC", "5")],
    "RTC_DAT":   [("U1", "TX2"), ("J_RTC", "4")],
    "RTC_CLK":   [("U1", "D19"), ("J_RTC", "3")],
    "BUZZER":    [("U1", "D18"), ("BZ1", "1")],
    "BTN_MENU":  [("U1", "D27"), ("J_BTN1", "1")],
    "BTN_UP":    [("U1", "D14"), ("J_BTN2", "1")],
    "BTN_DOWN":  [("U1", "D13"), ("J_BTN3", "1")],
    "BTN_BACK":  [("U1", "D32"), ("J_BTN4", "1")],
    "LED_GREEN": [("U1", "D25"), ("R1", "1")],
    "LED_BLUE":  [("U1", "D26"), ("R2", "1")],
    "LED_ALARM": [("U1", "D33"), ("R3", "1")],
}
# direct (drawn) point-to-point connections - resistor -> LED anode
DIRECT_WIRES = [(("R1", "2"), ("LED1", "1")),
                (("R2", "2"), ("LED2", "1")),
                (("R3", "2"), ("LED3", "1"))]


# --------------------------------------------------------------------------- #
#  build
# --------------------------------------------------------------------------- #
def main():
    src = json.load(open(SRC, encoding="utf-8"))
    original_shapes = src["schematics"][0]["dataStr"]["shape"]

    shapes = []
    pins = {}     # (designator, pin) -> (x, y)
    des_of = {}   # designator -> (name, package, spicePre)

    # ---- 0. drawing frame (kept, with the title block refreshed) ------------
    frame = original_shapes[0]
    frame = frame.replace("~comment~Sheet_1~1~start~gge148~0~frame_title",
                          "~comment~ESP32 Weather Station~1~start~gge148~0~frame_title")
    frame = frame.replace("~comment~1.0~1~start~gge160~0~frame_version",
                          "~comment~1.1~1~start~gge160~0~frame_version")
    frame = frame.replace("~comment~2026-11-04~1~start~gge172~0~frame_date",
                          "~comment~2026-11-11~1~start~gge172~0~frame_date")
    shapes.append(frame)

    # ---- 1. ESP32 ----------------------------------------------------------
    shapes.append(esp32_shape(original_shapes[1]))
    for nm, y in ESP32_LEFT.items():
        pins[("U1", nm)] = (ESP32_X["L"], y)
    for nm, y in ESP32_RIGHT.items():
        pins[("U1", nm)] = (ESP32_X["R"], y)
    des_of["U1"] = ("ESP32-DEVKIT-V1-30PIN_DZ", "ESP32-DEVKIT-V1-30PIN_DZ", "U")

    # ---- 2. power input ----------------------------------------------------
    s, p = build_header(70, -750, ["+5V", "GND"], "J_PWR", "USB-C Pigtail 2P 2.54",
                        "HDR-TH_1x2-P2.54-V-M", "J", "j_pwr",
                        mfr="Generic", mfrpn="USB-C 2-wire pigtail")
    shapes.append(s)
    for k, v in p.items():
        pins[("J_PWR", k)] = v
    des_of["J_PWR"] = ("USB-C pigtail +5V/GND (2P 2.54mm)", "HDR-TH_1x2-P2.54-V-M", "J")

    # ---- 3. off-board chassis buttons -------------------------------------
    buttons = [
        ("J_BTN1", -700, "MENU"),
        ("J_BTN2", -630, "UP"),
        ("J_BTN3", -560, "DOWN"),
        ("J_BTN4", -490, "BACK"),
    ]
    for des, yc, label in buttons:
        s, p = build_header(480, yc, ["SIG", "GND"], des,
                            "Panel button %s" % label, "HDR-TH_1x2-P2.54-V-M", "J", des.lower())
        shapes.append(s)
        for k, v in p.items():
            pins[(des, k)] = v
        des_of[des] = ("Off-board panel button %s (2P 2.54mm)" % label,
                       "HDR-TH_1x2-P2.54-V-M", "J")

    # ---- 4. resistors (through-hole, 220R) ---------------------------------
    for des, py in (("R1", -700), ("R2", -630), ("R3", -560)):
        s, p = build_resistor(560, py, des, "220\u03a9", "R_AXIAL-0.4", des.lower())
        shapes.append(s)
        for k, v in p.items():
            pins[(des, k)] = v
        des_of[des] = ("220\u03a9 1/4W axial resistor", "R_AXIAL-0.4", "R")

    # ---- 5. status LEDs ----------------------------------------------------
    for des, py, disp, col in (("LED1", -700, "LED-GREEN 5mm", "#00A000"),
                               ("LED2", -630, "LED-BLUE 5mm", "#0000FF"),
                               ("LED3", -560, "LED-RED/WHITE 5mm", "#FF0000")):
        s, p = build_led(680, py, des, disp, "LED-TH_F5", des.lower(), col)
        shapes.append(s)
        for k, v in p.items():
            pins[(des, k)] = v
        des_of[des] = (disp, "LED-TH_F5", "D")

    # ---- 6. buzzer ---------------------------------------------------------
    s, p = build_buzzer(850, -350, "BZ1", "Passive Buzzer 5V", "BUZ-TH_BD12.5", "bz1")
    shapes.append(s)
    for k, v in p.items():
        pins[("BZ1", k)] = v
    des_of["BZ1"] = ("Passive buzzer, 5V, GPIO18", "BUZ-TH_BD12.5", "BZ")

    # ---- 7. modules --------------------------------------------------------
    s, p = build_header(70, -310, ["GND", "VCC", "SDA", "SCL"], "J_LCD",
                        "LCD 2004 I2C", "HDR-TH_1x4-P2.54-V-M", "J", "j_lcd",
                        mfr="Generic", mfrpn="LCD2004 + I2C backpack")
    shapes.append(s)
    for k, v in p.items():
        pins[("J_LCD", k)] = v
    des_of["J_LCD"] = ("LCD 2004 with I2C backpack (4P 2.54mm)", "HDR-TH_1x4-P2.54-V-M", "J")

    s, p = build_header(70, -440, ["VCC", "GND", "SCL", "SDA"], "J_SENSOR",
                        "AHT20+BMP280 I2C", "HDR-TH_1x4-P2.54-V-M", "J", "j_sensor",
                        mfr="Generic", mfrpn="AHT20+BMP280 combo module")
    shapes.append(s)
    for k, v in p.items():
        pins[("J_SENSOR", k)] = v
    des_of["J_SENSOR"] = ("AHT20 + BMP280 combined module (4P 2.54mm)",
                          "HDR-TH_1x4-P2.54-V-M", "J")

    s, p = build_header(70, -590, ["VCC", "GND", "CLK", "DAT", "RST"], "J_RTC",
                        "DS1302 RTC", "HDR-TH_1x5-P2.54-V-M", "J", "j_rtc",
                        mfr="Generic", mfrpn="DS1302 RTC module")
    shapes.append(s)
    for k, v in p.items():
        pins[("J_RTC", k)] = v
    des_of["J_RTC"] = ("DS1302 RTC module (5P 2.54mm)", "HDR-TH_1x5-P2.54-V-M", "J")

    # ---- 8. wiring ---------------------------------------------------------
    # 8a. direct point-to-point wires (resistor -> LED anode)
    for (d1, p1), (d2, p2) in DIRECT_WIRES:
        x1, y1 = pins[(d1, p1)]
        x2, y2 = pins[(d2, p2)]
        shapes.append(wire(x1, y1, x2, y2))

    # 8b. for every other pin: a short stub + a net label.
    #     STUB[designator] = (stub length, direction, text anchor)
    STUB = {
        "U1":    (25, None, "start"),          # direction decided per pin below
        "J_PWR": (20, -1, "start"),
        "J_LCD": (20, -1, "start"),
        "J_SENSOR": (20, -1, "start"),
        "J_RTC": (20, -1, "start"),
        "J_BTN1": (20, -1, "end"),
        "J_BTN2": (20, -1, "end"),
        "J_BTN3": (20, -1, "end"),
        "J_BTN4": (20, -1, "end"),
        "R1": (20, -1, "end"),
        "R2": (20, -1, "end"),
        "R3": (20, -1, "end"),
        "LED1": (20, 1, "start"),
        "LED2": (20, 1, "start"),
        "LED3": (20, 1, "start"),
        "BZ1": (20, -1, "end"),
    }
    wired = set()
    for a, b in DIRECT_WIRES:
        wired.add(a)
        wired.add(b)
    for net, members in NETS.items():
        for des, pinname in members:
            if (des, pinname) in wired:
                continue
            x, y = pins[(des, pinname)]
            length, direction, anchor = STUB[des]
            if direction is None:                 # ESP32: stub away from the body
                direction = -1 if x == ESP32_X["L"] else 1
            x2 = x + direction * length
            shapes.append(wire(x, y, x2, y))
            shapes.append(netlabel(x2, y, net, anchor))

    # ---- 9. assemble the document -----------------------------------------
    head = dict(src["schematics"][0]["dataStr"]["head"])
    head["uuid"] = Ids.uid("esp32-weather-station-schematic")
    # 'Prefix Start' drives EasyEDA's auto-annotation. The original file had "1",
    # which is what turned the ESP32 designator into a bare "1". Start it past
    # every designator we already use so new parts never collide.
    head["c_para"] = {"Prefix Start": "100"}
    doc = {
        "head": head,
        "canvas": src["schematics"][0]["dataStr"]["canvas"],
        "shape": shapes,
        "BBox": {"x": 0, "y": -806.8, "width": 1149, "height": 807.2},
        "colors": {},
    }
    out = {
        "editorVersion": src["editorVersion"],
        "docType": src["docType"],
        "title": "ESP32 Weather Station",
        "description": "ESP32 DevKit V1 + LCD2004 I2C + AHT20/BMP280 + DS1302 + 4 panel buttons + 3 status LEDs + buzzer",
        "colors": {},
        "schematics": [{
            "docType": "1",
            "title": "Sheet_1",
            "description": "",
            "dataStr": doc,
        }],
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote %s (%d shapes)" % (OUT_JSON, len(shapes)))

    # ---- 10. netlist + BOM, derived from the DRAWN geometry ---------------
    ok = verify(OUT_JSON, NETS, DIRECT_WIRES)
    if not ok:
        sys.exit(1)
    write_netlist(NETS, des_of)
    write_bom(des_of)


# --------------------------------------------------------------------------- #
#  geometric verification: rebuild the netlist from what we actually drew
# --------------------------------------------------------------------------- #
def _parse_shapes(doc):
    pins, wires, labels = [], [], []
    for s in doc["schematics"][0]["dataStr"]["shape"]:
        if s.startswith("LIB~"):
            des = None
            for sub in s.split("#@$")[1:]:
                f = sub.split("~")
                if f[0] == "T" and f[1] == "P":
                    des = f[12]
                elif f[0] == "P":
                    parts = sub.split("^^")
                    xy = parts[1].split("~")
                    num = parts[0].split("~")[3]
                    pins.append((des, num, (float(xy[0]), float(xy[1]))))
        elif s.startswith("W~"):
            pts = s.split("~")[1].split()
            wires.append(((float(pts[0]), float(pts[1])), (float(pts[2]), float(pts[3]))))
        elif s.startswith("N~"):
            f = s.split("~")
            labels.append(((float(f[1]), float(f[2])), f[5]))
    return pins, wires, labels


def verify(path, nets, direct):
    doc = json.load(open(path, encoding="utf-8"))
    pins, wires, labels = _parse_shapes(doc)

    parent = {}

    def find(k):
        if k not in parent:
            parent[k] = k
            return k
        root = k
        while parent[root] != root:
            root = parent[root]
        while parent[k] != root:          # path compression
            parent[k], k = root, parent[k]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in wires:
        union(a, b)
    for _des, _num, pt in pins:
        find(pt)
    # a wire endpoint that lands exactly on a pin joins the pin to that wire
    for _des, _num, pt in pins:
        for a, b in wires:
            if pt == a or pt == b:
                union(pt, a)

    net_names = {}
    for pt, name in labels:
        net_names.setdefault(find(pt), set()).add(name)

    # assign every pin to its net
    result = {}
    errors = []
    for des, num, pt in pins:
        names = net_names.get(find(pt))
        if not names:
            continue
        if len(names) > 1:
            errors.append("pin %s/%s touches two different net names: %s" % (des, num, names))
            continue
        result.setdefault(next(iter(names)), set()).add((des, num))

    expected = {}
    for net, members in nets.items():
        expected[net] = set(members)
    for (d1, p1), (d2, p2) in direct:
        expected.setdefault("LOCAL_%s_%s" % (d1, p1), set()).update({(d1, p1), (d2, p2)})

    # merge the resistor->LED local nets into nothing (they are private nets)
    drawn = {k: v for k, v in result.items()}
    for net, members in expected.items():
        if net.startswith("LOCAL_"):
            continue
        got = drawn.get(net, set())
        if got != members:
            errors.append("net %-10s expected %s got %s  (missing %s / extra %s)" % (
                net, sorted(members), sorted(got),
                sorted(members - got), sorted(got - members)))

    # every drawn net must be one we asked for
    for net in drawn:
        if net not in expected:
            errors.append("unexpected drawn net %s : %s" % (net, sorted(drawn[net])))

    if errors:
        print("\nVERIFY FAILED")
        for e in errors:
            print("  !", e)
        return False
    print("VERIFY OK - %d nets, %d pins, %d wires, %d net labels"
          % (len(drawn), len(pins), len(wires), len(labels)))
    return True


def write_netlist(nets, des_of):
    lines = [
        "*",
        "* EasyEDA Netlist - ESP32 Weather Station",
        "* Generated 2026-11-11 from SCH_ESP32_WeatherStation_2026-11-11.json",
        "*",
        "",
    ]
    for net in sorted(nets, key=lambda s: (s != "GND", s)):
        lines.append("[ %s ]" % net)
        for des, pin in sorted(nets[net]):
            lines.append("    %-8s-%s" % (des, pin))
        lines.append("")
    # private (point-to-point) nets
    lines.append("[ R1_2 -> LED1_A ]")
    lines.append("    R1-2        LED1-1")
    lines.append("")
    lines.append("[ R2_2 -> LED2_A ]")
    lines.append("    R2-2        LED2-1")
    lines.append("")
    lines.append("[ R3_2 -> LED3_A ]")
    lines.append("    R3-2        LED3-1")
    lines.append("")
    p = os.path.join(ROOT, "netlist.txt")
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    print("wrote %s" % p)

    data = {
        "nets": {k: ["%s-%s" % (d, pin) for d, pin in v] for k, v in nets.items()},
        "local_nets": {
            "R1_2_LED1_A": ["R1-2", "LED1-1"],
            "R2_2_LED2_A": ["R2-2", "LED2-1"],
            "R3_2_LED3_A": ["R3-2", "LED3-1"],
        },
    }
    p = os.path.join(ROOT, "netlist.json")
    json.dump(data, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("wrote %s" % p)


def write_bom(des_of):
    order = ["U1", "J_PWR", "J_BTN1", "J_BTN2", "J_BTN3", "J_BTN4",
             "R1", "R2", "R3", "LED1", "LED2", "LED3", "BZ1",
             "J_LCD", "J_SENSOR", "J_RTC"]
    notes = {
        "U1": "ESP32 DevKit V1, 30-pin. Feeds 3V3 to the sensor only.",
        "J_PWR": "USB-C 2-wire pigtail: red = +5V (pin 1), black = GND (pin 2).",
        "J_BTN1": "Panel button MENU -> GPIO27, other leg to GND (uses internal pull-up).",
        "J_BTN2": "Panel button UP -> GPIO14, other leg to GND.",
        "J_BTN3": "Panel button DOWN -> GPIO13, other leg to GND.",
        "J_BTN4": "Panel button BACK -> GPIO32, other leg to GND.",
        "R1": "220R in series with LED1.",
        "R2": "220R in series with LED2.",
        "R3": "220R in series with LED3.",
        "LED1": "Green 5mm - heartbeat.",
        "LED2": "Blue 5mm - Bluetooth Rx activity.",
        "LED3": "Red or white 5mm - alarm.",
        "BZ1": "5V passive buzzer, + = GPIO18, - = GND.",
        "J_LCD": "LCD 2004 + I2C backpack: GND, VCC(5V), SDA, SCL.",
        "J_SENSOR": "AHT20 + BMP280 combo module: VCC(3V3), GND, SCL, SDA.",
        "J_RTC": "DS1302 module: VCC(5V), GND, CLK, DAT, RST.",
    }
    p = os.path.join(ROOT, "bom.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Value / Description", "Footprint", "Quantity", "Notes"])
        for d in order:
            name, pkg, _ = des_of[d]
            w.writerow([d, name, pkg, 1, notes.get(d, "")])
    print("wrote %s" % p)


if __name__ == "__main__":
    main()
