# -*- coding: utf-8 -*-
"""Board layout shared by the EasyEDA PCB writer and the PCB preview writer.

One source of truth: the component placement below is used twice --

  * tools/build_easyeda_pcb.py turns it into an EasyEDA Standard PCB JSON,
    with footprints, pads, nets, board outline and ratlines ready to route;
  * tools/build_pcb_preview.py turns it into pcb_preview.png / .pdf.

All coordinates are millimetres, origin at the bottom-left corner of the
board, +X to the right, +Y up (the way you look at the component side).
The EasyEDA writers convert to EasyEDA units (1 unit = 10 mil = 0.254 mm).
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCH = os.path.join(ROOT, "SCH_ESP32_WeatherStation_2026-11-11.json")

BW, BH = 100.0, 50.0     # board outline, mm (longer side horizontal)

# If your module's silkscreen has VIN/3V3 at the *other* end, rebuild with
# --mirror-esp32: that 180 deg rotation of the module swaps the two rows and
# reverses each of them, exactly like turning the real board around.
MIRROR_ESP = False
EDGE = 0.3                # copper keep-out from the board edge

# --------------------------------------------------------------------------- #
#  ESP32 DevKit V1 (30 pin, DOIT) - body and header geometry
# --------------------------------------------------------------------------- #
ESP_W, ESP_L = 28.33, 51.45              # real module PCB body (~51 x 28 mm)
ROW_SPACE = 25.40                        # header rows, 25.40 mm (1.0") apart
PIN1_X, PIN1_Y = 11.0, 12.3              # pad 1 (3V3), bottom-left of U1
PITCH = 2.54
OVERHANG_USB = 5.70                      # PCB edge past pin 1 / 16 (USB end)
OVERHANG_ANT = ESP_L - 14 * PITCH - OVERHANG_USB  # ~10.19 mm past pin 15 / 30

# Physical pin numbering follows the DOIT / NodeMCU-32S silkscreen:
#   pin 1 = 3V3 (left row, USB end) ... pin 15 = D23 (left row, far end)
#   pin 16 = VIN (right row, USB end) ... pin 30 = EN (right row, far end)
LEFT_ROW = ["3V3", "GND", "D15", "D2", "D4", "RX2", "TX2", "D5", "D18", "D19",
            "D21", "RX0", "TX0", "D22", "D23"]
RIGHT_ROW = ["VIN", "GND2", "D13", "D12", "D14", "D27", "D26", "D25", "D33",
             "D32", "D35", "D34", "VN", "VP", "EN"]

PAD_HDR = 1.8          # 2.54 mm header pad
DRILL_HDR = 1.0
PAD_SMALL = 2.0        # resistor / LED / capacitor lead
DRILL_SMALL = 0.9
DRILL_MOUNT = 3.2      # mounting holes
MOUNT_RING = 2.2       # silk circle radius around a mounting hole


def esp_rows():
    """(left row, right row) after the optional 180 deg module rotation."""
    if MIRROR_ESP:
        return RIGHT_ROW[::-1], LEFT_ROW[::-1]
    return LEFT_ROW, RIGHT_ROW


def rotate(dx, dy, rot):
    """Rotate a footprint-local offset counter-clockwise by rot degrees."""
    if rot == 0:
        return dx, dy
    if rot == 90:
        return -dy, dx
    if rot == 180:
        return -dx, -dy
    if rot == 270:
        return dy, -dx
    raise ValueError("rotation %s not supported" % rot)


# --------------------------------------------------------------------------- #
#  parts
# --------------------------------------------------------------------------- #
class Footprint:
    """One through-hole part: circle pads + silkscreen graphics.

    pads: dict(num=, name=, net=, dx=, dy=, d=pad diameter, drill=hole,
               sch=schematic pin id)
    silk: ("line", [pts]) | ("circle", cx, cy, r) | ("text", x, y, s, size)
    """

    def __init__(self, ref, value, package, kind, x, y, rot=0, note=""):
        self.ref = ref
        self.value = value
        self.package = package
        self.kind = kind
        self.x = x
        self.y = y
        self.rot = rot
        self.pads = []
        self.silk = []
        self.body = []          # bounding box in board mm, for the overlay
        self.prefix = "".join(c for c in ref if c.isalpha())
        self.note = note

    # -- geometry ---------------------------------------------------------
    def at(self, dx, dy):
        """footprint-local -> board coordinates"""
        a, b = rotate(dx, dy, self.rot)
        return self.x + a, self.y + b

    def pad(self, num, name, net, dx, dy, d, drill, sch=None):
        self.pads.append(dict(num=num, name=name, net=net, dx=dx, dy=dy,
                              d=d, drill=drill,
                              sch=num if sch is None else sch))

    def abs_pad(self, p):
        return self.at(p["dx"], p["dy"])

    def set_body_box(self, x0, y0, x1, y1):
        """body box given in footprint-local coordinates"""
        pts = [self.at(x0, y0), self.at(x1, y0), self.at(x0, y1), self.at(x1, y1)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        self.body = [(min(xs), min(ys)), (max(xs), max(ys))]

    def size(self):
        """local (w, h) of the part, used for label placement"""
        xs = [p["dx"] for p in self.pads] + [0.0]
        ys = [p["dy"] for p in self.pads] + [0.0]
        return max(xs) - min(xs), max(ys) - min(ys)

    def ref_pos(self):
        """(x, y), size for the designator - board coordinates."""
        n = len(self.pads)
        if self.kind == "module":
            # centre of the ESP32 module footprint (horizontal or vertical)
            (x0, y0), (x1, y1) = self.body
            if self.rot in (90, 270):
                p0 = self.abs_pad(self.pads[0])
                p14 = self.abs_pad(self.pads[14])
                return ((p0[0] + p14[0]) / 2.0, (y0 + y1) / 2.0), 1.8
            return (self.at(0, 0)[0] + 12.7, y0 + 5.0), 1.6
        if self.kind == "cap":
            cx, cy = self.abs_pad(self.pads[0])
            return (cx, cy + 7.3), 1.0            # just above the can
        if self.kind == "buzzer":
            return (self.x + 3.8, self.y + 7.7), 1.05
        if self.kind == "led":
            ax, ay = self.abs_pad(self.pads[0])
            kx, ky = self.abs_pad(self.pads[1])
            cx, cy = (ax + kx) / 2.0, (ay + ky) / 2.0
            if abs(kx - ax) >= abs(ky - ay):      # horizontal -> label to the right
                return (max(ax, kx) + 5.0, cy), 1.0
            return (cx, cy + 3.5), 1.0
        if self.kind == "resistor":
            ax, ay = self.abs_pad(self.pads[0])
            kx, ky = self.abs_pad(self.pads[1])
            return ((ax + kx) / 2.0, (ay + ky) / 2.0 + 2.3), 1.0
        # header: label facing the interior of the board
        p0, pN = self.abs_pad(self.pads[0]), self.abs_pad(self.pads[-1])
        cx, cy = (p0[0] + pN[0]) / 2.0, (p0[1] + pN[1]) / 2.0
        if abs(pN[0] - p0[0]) >= abs(pN[1] - p0[1]):  # horizontal header
            off = -3.3 if cy > BH / 2.0 else 3.5
            return (cx, cy + off), 0.95
        return (self.x, self.y + (n - 1) * PITCH + 3.2), 1.0

    def value_pos(self):
        """(x, y), size for the value text, or None when there is no room."""
        return None

    def pin1_mark(self):
        """A small square around pin 1, like a real header footprint."""
        if self.kind != "header":
            return None
        x, y = self.abs_pad(self.pads[0])
        a = 1.05
        return [(x - a, y - a), (x + a, y - a), (x + a, y + a), (x - a, y + a),
                (x - a, y - a)]


def esp32_module(x1, y1, rot=90):
    """The ESP32 DOIT DevKit V1 (30 pin): 2 x 15 sockets + full module silk.

    (x1, y1) is pad 1 (3V3) at the USB end.  With rot=90, pad 1 sits at the
    bottom-left, rows run along +X (25.40 mm = 1.0" apart along Y), USB end is
    on the left and antenna end is on the right.
    """
    fp = Footprint("U1", "ESP32-DEVKIT-V1-30PIN", "ESP32-DEVKIT-V1-30PIN_DZ",
                   "module", x1, y1, rot=rot,
                   note="2 x 15 pin sockets, 25.40 mm (1.0\") apart; ~51.5 x 28.3 mm body")
    left, right = esp_rows()
    for i, nm in enumerate(left, start=1):
        fp.pad(str(i), nm, None, 0.0, -(i - 1) * PITCH, PAD_HDR, DRILL_HDR,
               sch=nm)
    for i, nm in enumerate(right, start=1):
        fp.pad(str(i + 15), nm, None, ROW_SPACE, -(i - 1) * PITCH, PAD_HDR,
               DRILL_HDR, sch=nm)

    w = ROW_SPACE
    bot = -(15 - 1) * PITCH              # -35.56 mm in local Y
    ox = (ESP_W - w) / 2.0               # 1.465 mm PCB overhang past each row
    if not MIRROR_ESP:
        y_top = OVERHANG_USB             # +5.70 mm above pad 1 (USB end)
        y_bot = bot - OVERHANG_ANT       # -45.75 mm below pad 15 (antenna end)
    else:
        y_top = OVERHANG_ANT             # antenna moves to pad-1 end when flipped
        y_bot = bot - OVERHANG_USB       # USB moves to far end

    # 1. Full DOIT DevKit V1 module PCB perimeter (~51.45 x 28.33 mm)
    fp.silk.append(("line", [
        fp.at(-ox, y_bot), fp.at(w + ox, y_bot),
        fp.at(w + ox, y_top), fp.at(-ox, y_top), fp.at(-ox, y_bot),
    ]))

    # 2. Separate 1x15 socket-strip outlines inside the module perimeter
    for sx in (0.0, w):
        fp.silk.append(("line", [
            fp.at(sx - 1.27, bot - 1.27), fp.at(sx + 1.27, bot - 1.27),
            fp.at(sx + 1.27, 1.27), fp.at(sx - 1.27, 1.27),
            fp.at(sx - 1.27, bot - 1.27),
        ]))

    if not MIRROR_ESP:
        # Micro-USB receptacle overhang past the USB PCB edge
        fp.silk.append(("line", [
            fp.at(w / 2 - 4.5, y_top), fp.at(w / 2 - 4.5, y_top + 1.8),
            fp.at(w / 2 + 4.5, y_top + 1.8), fp.at(w / 2 + 4.5, y_top),
        ]))
        # Antenna keepout divider + EN button at the antenna end (clear of pads)
        fp.silk.append(("line", [fp.at(-ox, bot - 3.6), fp.at(w + ox, bot - 3.6)]))
        fp.silk.append(("line", [
            fp.at(0.5, bot - 4.4), fp.at(3.7, bot - 4.4),
            fp.at(3.7, bot - 7.4), fp.at(0.5, bot - 7.4), fp.at(0.5, bot - 4.4),
        ]))
        # Pin-1 L-bracket outside pad 1 (3V3), clear of the socket strip
        fp.silk.append(("line", [
            fp.at(-1.55, 0.2), fp.at(-1.55, 2.15), fp.at(-0.2, 2.15),
        ]))
        fp.set_body_box(-ox, y_bot, w + ox, y_top + 1.8)
    else:
        # Module rotated 180 deg: USB connector and pin 1 (3V3) move to far end
        fp.silk.append(("line", [
            fp.at(w / 2 - 4.5, y_bot), fp.at(w / 2 - 4.5, y_bot - 1.8),
            fp.at(w / 2 + 4.5, y_bot - 1.8), fp.at(w / 2 + 4.5, y_bot),
        ]))
        fp.silk.append(("line", [fp.at(-ox, 3.6), fp.at(w + ox, 3.6)]))
        fp.silk.append(("line", [
            fp.at(w + 1.55, bot - 0.2), fp.at(w + 1.55, bot - 2.15),
            fp.at(w + 0.2, bot - 2.15),
        ]))
        fp.set_body_box(-ox, y_bot - 1.8, w + ox, y_top)
    return fp


def header_1xN(ref, value, package, x, y, names, gap=PITCH, rot=0, note=""):
    """1xN header; rot=0 pins run +Y, rot=270 pins run +X, rot=90 pins run -X."""
    fp = Footprint(ref, value, package, "header", x, y, rot=rot, note=note)
    for i, nm in enumerate(names):
        fp.pad(str(i + 1), nm, None, 0.0, i * gap, PAD_HDR, DRILL_HDR)
    top = (len(names) - 1) * gap
    w = 1.27
    fp.silk.append(("line", [fp.at(-w, -w), fp.at(w, -w), fp.at(w, top + w),
                             fp.at(-w, top + w), fp.at(-w, -w)]))
    fp.set_body_box(-w, -w, w, top + w)
    return fp


def axial_resistor(ref, value, x, y, rot=0):
    """Axial 1/4 W resistor, 6.3 mm body, 10.16 mm lead pitch.

    rot 0   -> pad 1 at (0,0), pad 2 at (0,10.16)   (vertical, 1 below)
    rot 90  -> pad 1 at (0,0), pad 2 at (10.16,0)   (horizontal, 2 right)
    rot 270 -> pad 1 at (0,0), pad 2 at (-10.16,0)  (horizontal, 2 right)
    """
    fp = Footprint(ref, value, "R_AXIAL-0.4", "resistor", x, y, rot=rot)
    fp.pad("1", "1", None, 0.0, 0.0, PAD_SMALL, DRILL_SMALL)
    fp.pad("2", "2", None, 0.0, 10.16 if rot != 90 and rot != 270 else 10.16,
           PAD_SMALL, DRILL_SMALL)
    # body outline: a thin box between the pads, clear of both of them
    (x1, y1), (x2, y2) = fp.abs_pad(fp.pads[0]), fp.abs_pad(fp.pads[1])
    half = 1.0
    if abs(y2 - y1) >= abs(x2 - x1):          # vertical
        x0 = x1
        mid = (y1 + y2) / 2.0
        lo, hi = mid - 3.25, mid + 3.25
        pts = [(x0 - half, lo), (x0 + half, lo), (x0 + half, hi),
               (x0 - half, hi), (x0 - half, lo)]
        fp.body = [(x0 - half, lo), (x0 + half, hi)]
    else:                                     # horizontal
        y0 = y1
        mid = (x1 + x2) / 2.0
        lo, hi = mid - 3.25, mid + 3.25
        pts = [(lo, y0 - half), (hi, y0 - half), (hi, y0 + half),
               (lo, y0 + half), (lo, y0 - half)]
        fp.body = [(lo, y0 - half), (hi, y0 + half)]
    fp.silk.append(("line", pts))
    return fp


def led_5mm(ref, value, x, y, rot=270):
    """5 mm through-hole LED, 2.54 mm pitch.

    rot 270 -> anode at (0,0), cathode at (-2.54,0): a left-pointing LED
    """
    fp = Footprint(ref, value, "LED-TH_F5", "led", x, y, rot=rot)
    fp.pad("A", "A", None, 0.0, 0.0, PAD_SMALL, DRILL_SMALL, sch="1")
    fp.pad("K", "K", None, 0.0, 2.54, PAD_SMALL, DRILL_SMALL, sch="2")
    ax, ay = fp.abs_pad(fp.pads[0])
    kx, ky = fp.abs_pad(fp.pads[1])
    cx, cy = (ax + kx) / 2.0, (ay + ky) / 2.0
    fp.silk.append(("circle", cx, cy, 2.2))
    # cathode bar, on the K side
    bar = PAD_SMALL / 2 + 0.55                 # just outside the K pad
    if abs(kx - ax) >= abs(ky - ay):           # horizontal LED
        dx = -1.0 if kx < ax else 1.0
        fp.silk.append(("line", [(kx + dx * bar, ky - 1.1),
                                 (kx + dx * bar, ky + 1.1)]))
    else:                                      # vertical LED
        dy = -1.0 if ky < ay else 1.0
        fp.silk.append(("line", [(kx - 1.1, ky + dy * bar),
                                 (kx + 1.1, ky + dy * bar)]))
    fp.body = [(cx - 1.95, cy - 1.95), (cx + 1.95, cy + 1.95)]
    return fp


def electrolytic(ref, value, x, y, rot=0):
    """Radial electrolytic, 8 mm case, 3.5 mm lead pitch. '+' is pad 1."""
    fp = Footprint(ref, value, "CAP-TH_D8.0-P3.5", "cap", x, y, rot=rot)
    fp.pad("1", "+", None, 0.0, 0.0, PAD_SMALL, DRILL_SMALL)
    fp.pad("2", "-", None, 0.0, 3.5, PAD_SMALL, DRILL_SMALL)
    px, py = fp.abs_pad(fp.pads[0])
    mx, my = fp.abs_pad(fp.pads[1])
    cx, cy = (px + mx) / 2.0, (py + my) / 2.0
    fp.silk.append(("circle", cx, cy, 4.0))
    # polarity marks: '+' near the + pad, '-' near the - pad
    if abs(my - py) >= abs(mx - px):
        sgn = -1.0 if py < my else 1.0
        # '+' on the + side
        fp.silk.append(("line", [(cx + 1.3, cy + sgn * 1.9),
                                 (cx + 2.7, cy + sgn * 1.9)]))
        fp.silk.append(("line", [(cx + 2.0, cy + sgn * 1.2),
                                 (cx + 2.0, cy + sgn * 2.6)]))
        # '-' on the - side
        fp.silk.append(("line", [(cx + 1.3, cy - sgn * 1.9),
                                 (cx + 2.7, cy - sgn * 1.9)]))
    fp.body = [(cx - 4.0, cy - 4.0), (cx + 4.0, cy + 4.0)]
    return fp


def buzzer(ref, value, x, y, rot=0):
    """12.5 mm passive buzzer, 7.6 mm lead pitch. '+' is pad 1 on the left."""
    fp = Footprint(ref, value, "BUZ-TH_BD12.5", "buzzer", x, y, rot=rot)
    fp.pad("1", "+", None, 0.0, 0.0, PAD_HDR, DRILL_HDR)
    fp.pad("2", "-", None, 7.6, 0.0, PAD_HDR, DRILL_HDR)
    cx, cy = x + 3.8, y
    fp.silk.append(("circle", cx, cy, 6.1))
    # crisp '+' mark above pad 1, clear of its copper ring
    fp.silk.append(("line", [(x - 0.7, y + 2.3), (x + 0.7, y + 2.3)]))
    fp.silk.append(("line", [(x, y + 1.6), (x, y + 3.0)]))
    fp.body = [(cx - 6.1, cy - 6.1), (cx + 6.1, cy + 6.1)]
    return fp

# --------------------------------------------------------------------------- #
#  the board
# --------------------------------------------------------------------------- #
def build_parts():
    """Every part, placed on a 100 x 50 mm horizontal board.

    Layout, left to right:
      x 1..58    U1 (DOIT ESP32 DevKit V1, ~51.5 x 28.3 mm, 25.40 mm rows)
                   centred horizontally along y=12.3..37.7 (USB on the left);
                 J_BTN1..4 along the top edge (above U1);
                 J_SENSOR, J_RTC, J_LCD along the bottom edge (below U1).
      x 60..97   J_PWR at the bottom, C1 & BZ1 above it,
                 3 x (220R -> LED) chains stacked neatly on the upper right.
    """
    parts = []

    # ---- ESP32 ------------------------------------------------------------
    parts.append(esp32_module(PIN1_X, PIN1_Y, rot=90))

    # ---- top edge: the four panel buttons ---------------------------------
    for ref, x in (("J_BTN1", 14.0), ("J_BTN2", 22.5),
                   ("J_BTN3", 31.0), ("J_BTN4", 39.5)):
        parts.append(header_1xN(ref, "", "HDR-TH_1x2-P2.54-V-M",
                                x, 45.4, ["SIG", "GND"], rot=270))

    # ---- bottom edge: off-board connectors --------------------------------
    parts.append(header_1xN("J_SENSOR", "", "HDR-TH_1x4-P2.54-V-M",
                            10.5, 4.6, ["VCC", "GND", "SCL", "SDA"], rot=270))
    parts.append(header_1xN("J_RTC", "", "HDR-TH_1x5-P2.54-V-M",
                            34.5, 4.6, ["VCC", "GND", "CLK", "DAT", "RST"],
                            rot=90))
    parts.append(header_1xN("J_LCD", "", "HDR-TH_1x4-P2.54-V-M",
                            40.5, 4.6, ["GND", "VCC", "SDA", "SCL"], rot=270))
    parts.append(header_1xN("J_PWR", "", "HDR-TH_1x2-P2.54-V-M",
                            61.5, 4.6, ["+5V", "GND"], rot=270))

    # ---- power reservoir + buzzer (bottom right) --------------------------
    parts.append(electrolytic("C1", "", 64.5, 14.5))
    parts.append(buzzer("BZ1", "", 76.5, 13.5))

    # ---- 3 x (220R -> LED) chains, running rightwards (upper right) -------
    # GPIO -> R.1 (left) -> R.2 (right) -> LED.A -> LED.K -> GND
    for i, y in enumerate((41.5, 34.0, 26.5), start=1):
        parts.append(axial_resistor("R%d" % i, "220R", 64.0, y, rot=270))
        parts.append(led_5mm("LED%d" % i, "", 81.5, y, rot=270))

    return parts


def mount_holes():
    return [(4.0, 4.0), (96.0, 4.0), (4.0, 46.0), (96.0, 46.0)]


# --------------------------------------------------------------------------- #
#  nets
# --------------------------------------------------------------------------- #
def load_netlist():
    """Load the schematic netlist -> ({(ref, pin): net}, {net: [(ref, pin)]}).

    The pin id is whatever the schematic calls the pin ("1", "A", "D21"...);
    each board pad carries that id in its "sch" field.
    """
    import json
    doc = json.load(open(os.path.join(ROOT, "netlist.json"), encoding="utf-8"))
    pin_net, net_pins = {}, {}
    for net, members in doc["nets"].items():
        net_pins[net] = []
        for m in members:
            ref, pin = m.rsplit("-", 1)
            pin_net[(ref, pin)] = net
            net_pins[net].append((ref, pin))
    for name, members in doc["local_nets"].items():
        net = name.upper()
        net_pins[net] = []
        for m in members:
            ref, pin = m.rsplit("-", 1)
            pin_net[(ref, pin)] = net
            net_pins[net].append((ref, pin))
    return pin_net, net_pins


def assign_nets(parts, pin_net):
    """Copy net names from the schematic netlist onto every pad."""
    for fp in parts:
        for p in fp.pads:
            p["net"] = pin_net.get((fp.ref, p["sch"]))
    return [(fp.ref, p["num"]) for fp in parts for p in fp.pads
            if not p["net"]]


def all_pads(parts):
    """[(ref, pad_dict, x, y)] in board coordinates."""
    out = []
    for fp in parts:
        for p in fp.pads:
            x, y = fp.abs_pad(p)
            out.append((fp.ref, p, x, y))
    return out


# --------------------------------------------------------------------------- #
#  silkscreen text
# --------------------------------------------------------------------------- #
# The module silkscreen prints "GND" on both ground pins; the schematic needs
# two distinct pin names, so it calls the second one GND2.
SILK_NAME = {"GND2": "GND"}


def esp_pin_names(parts):
    """Pin names of the ESP32 socket strip: [(text, x, y, size, rot)]."""
    out = []
    for fp in parts:
        if fp.kind != "module":
            continue
        half = ROW_SPACE / 2.0
        for p in fp.pads:
            near_left = p["dx"] < half
            x, y = fp.at(4.0 if near_left else ROW_SPACE - 4.0, p["dy"])
            out.append((SILK_NAME.get(p["name"], p["name"]), x, y, 0.85,
                        fp.rot))
    return out
import strokefont                                # noqa: E402


class SilkText:
    """One piece of silkscreen text plus its bounding box."""

    def __init__(self, s, x, y, size, rot=0, align="middle", anchor="middle",
                 owner=None):
        self.s = s
        self.x = x
        self.y = y
        self.size = size
        self.rot = rot
        self.align = align
        self.anchor = anchor
        self.owner = owner
        self.lines = strokefont.text_polylines(s, x, y, size, rot=rot,
                                               align=align, anchor=anchor)
        xs = [p[0] for ln in self.lines for p in ln]
        ys = [p[1] for ln in self.lines for p in ln]
        self.box = (min(xs), min(ys), max(xs), max(ys)) if xs else (x, y, x, y)

    def as_silk(self):
        return ("text", self.x, self.y, self.s, self.size, self.align,
                self.anchor)

    def centre(self):
        return (self.box[0] + self.box[2]) / 2.0, (self.box[1] + self.box[3]) / 2.0


BOARD_TITLE = ("ESP32 WEATHER STATION 100X50MM REV 1.2", 68.5, 47.4, 0.9)


def silk_texts(parts, include_title=False):
    """Every text that is going to be printed on the silkscreen."""
    out = []
    for fp in parts:
        (rx, ry), rsize = fp.ref_pos()
        out.append(SilkText(fp.ref, rx, ry, rsize, anchor="middle",
                            owner=fp.ref))
        v = fp.value_pos()
        if v:
            (vx, vy), vsize = v
            out.append(SilkText(fp.value, vx, vy, vsize, anchor="middle",
                                owner=fp.ref))
    if include_title:
        txt, tx, ty, tsz = BOARD_TITLE
        out.append(SilkText(txt, tx, ty, tsz, align="middle", anchor="baseline"))
    return out


def silk_graphics(parts, holes):
    """Every non-text silkscreen line/circle, in board coordinates."""
    out = []
    for fp in parts:
        for item in fp.silk:
            if item[0] == "line":
                for a, b in zip(item[1][:-1], item[1][1:]):
                    out.append((fp.ref, a, b))
            elif item[0] == "circle":
                cx, cy, r = item[1], item[2], item[3]
                n = 24
                ring = [(cx + r * math.cos(2 * math.pi * k / n),
                         cy + r * math.sin(2 * math.pi * k / n))
                        for k in range(n + 1)]
                for a, b in zip(ring[:-1], ring[1:]):
                    out.append((fp.ref, a, b))
    for hx, hy in holes:
        r = MOUNT_RING
        n = 24
        ring = [(hx + r * math.cos(2 * math.pi * k / n),
                 hy + r * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]
        for a, b in zip(ring[:-1], ring[1:]):
            out.append(("HOLE", a, b))
    return out


def _box_overlap(a, b, gap=0.0):
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0]
                or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def _seg_seg_dist(a, b, c, d):
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])

    d1, d2 = cross(c, d, a), cross(c, d, b)
    d3, d4 = cross(a, b, c), cross(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(_seg_point_dist(a, b, c), _seg_point_dist(a, b, d),
               _seg_point_dist(c, d, a), _seg_point_dist(c, d, b))


def check_silk(parts, holes):
    """Silkscreen must keep off the pads and must not collide with itself."""
    errs = []
    pads = all_pads(parts)
    texts = silk_texts(parts, include_title=True)
    texts += [SilkText(n, x, y, sz, rot=rot, owner="U1")
              for n, x, y, sz, rot in esp_pin_names(parts)]
    lines = silk_graphics(parts, holes)

    # 1. text boxes must be inside the board and away from every pad
    for t in texts:
        b = t.box
        if b[0] < 0.4 or b[1] < 0.4 or b[2] > BW - 0.4 or b[3] > BH - 0.4:
            errs.append("text %r leaves the board" % t.s)
        for ref, p, x, y in pads:
            r = p["d"] / 2.0
            if (b[0] - r < x < b[2] + r) and (b[1] - r < y < b[3] + r):
                errs.append("text %r sits on pad %s.%s" % (t.s, ref, p["num"]))

    # 1b. text against the mounting-hole rings
    for t in texts:
        b = t.box
        for hx, hy in holes:
            r = MOUNT_RING
            cx = min(max(hx, b[0]), b[2])
            cy = min(max(hy, b[1]), b[3])
            if math.hypot(cx - hx, cy - hy) < r + 0.1:
                errs.append("text %r sits on the mounting hole at (%.1f, %.1f)"
                            % (t.s, hx, hy))

    # 2. text against text
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _box_overlap(texts[i].box, texts[j].box, 0.1):
                errs.append("text %r overlaps %r" % (texts[i].s, texts[j].s))

    # 3. silk lines must not cross another part's pad.  A part's own silk may
    #    touch its own pads (LEDs and buzzers are drawn over them on purpose),
    #    and the mounting-hole rings are not part of any component.
    own = {}
    for fp in parts:
        for p in fp.pads:
            x, y = fp.abs_pad(p)
            own[(round(x, 3), round(y, 3))] = fp.ref
    for ref, a, b in lines:
        if ref == "HOLE":
            continue
        for pr, p, x, y in pads:
            if own.get((round(x, 3), round(y, 3))) == ref:
                continue
            if _seg_point_dist(a, b, (x, y)) < p["d"] / 2.0 + 0.05:
                errs.append("%s silk line crosses pad %s.%s"
                            % (ref, pr, p["num"]))

    # 4. text must not sit on another part's body/courtyard box
    #    (U1's own ref and pin labels belong inside U1; everything else must
    #     stay outside U1's full physical 51.45 x 28.33 mm envelope too)
    for t in texts:
        for fp in parts:
            if fp.ref == t.owner:
                continue
            (x0, y0), (x1, y1) = fp.body
            box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            if _box_overlap(t.box, box, 0.0):
                errs.append("text %r sits on %s" % (t.s, fp.ref))
    return errs


# --------------------------------------------------------------------------- #
#  checks
# --------------------------------------------------------------------------- #
def _seg_point_dist(a, b, p):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def pc_hole_r():
    return DRILL_MOUNT / 2.0


def drc(parts, holes, clearance=0.3):
    """Pad-to-pad clearance, board edge, mounting-hole & courtyard checks."""
    pads = all_pads(parts)
    errs = []
    for i in range(len(pads)):
        r1, p1, x1, y1 = pads[i]
        for j in range(i + 1, len(pads)):
            r2, p2, x2, y2 = pads[j]
            d = math.hypot(x1 - x2, y1 - y2) - (p1["d"] + p2["d"]) / 2.0
            if d < clearance - 1e-9:
                errs.append("%s.%s <-> %s.%s copper gap %.2f mm"
                            % (r1, p1["num"], r2, p2["num"], d))
    for ref, p, x, y in pads:
        r = p["d"] / 2.0
        if (x - r < EDGE or y - r < EDGE
                or x + r > BW - EDGE or y + r > BH - EDGE):
            errs.append("%s.%s too close to the board edge" % (ref, p["num"]))
    for hx, hy in holes:
        for ref, p, x, y in pads:
            d = math.hypot(x - hx, y - hy) - pc_hole_r() - p["d"] / 2.0
            if d < 0.15:
                errs.append("%s.%s is %.2f mm from the edge of a mounting hole"
                            % (ref, p["num"], d))
        if not (2.0 < hx < BW - 2.0 and 2.0 < hy < BH - 2.0):
            errs.append("mounting hole (%.1f, %.1f) too close to the edge"
                        % (hx, hy))

    # component body courtyard clearance (>= 0.5 mm between any two parts)
    for i in range(len(parts)):
        a0, a1 = parts[i].body
        ba = (min(a0[0], a1[0]), min(a0[1], a1[1]),
              max(a0[0], a1[0]), max(a0[1], a1[1]))
        for j in range(i + 1, len(parts)):
            b0, b1 = parts[j].body
            bb = (min(b0[0], b1[0]), min(b0[1], b1[1]),
                  max(b0[0], b1[0]), max(b0[1], b1[1]))
            if _box_overlap(ba, bb, 0.5):
                errs.append("%s body courtyard overlaps %s (< 0.5 mm gap)"
                            % (parts[i].ref, parts[j].ref))

    # silkscreen collisions are checked by check_silk()
    return errs


def nets_of(parts):
    groups = {}
    for ref, p, x, y in all_pads(parts):
        if p["net"]:
            groups.setdefault(p["net"], []).append((ref, p, x, y))
    return groups


def check_connectivity(parts, net_pins):
    """Every schematic net must exist on the board with exactly the same pads."""
    board = {}
    for ref, p, x, y in all_pads(parts):
        if p["net"]:
            board.setdefault(p["net"], set()).add("%s-%s" % (ref, p["sch"]))
    errs = []
    for net, pins in net_pins.items():
        want = {"%s-%s" % (r, n) for r, n in pins}
        have = board.get(net, set())
        if want != have:
            errs.append("net %s: missing %s, extra %s"
                        % (net, sorted(want - have), sorted(have - want)))
    for net in board:
        if net not in net_pins:
            errs.append("board net %s is not in the schematic" % net)
    return errs
