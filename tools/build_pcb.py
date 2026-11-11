#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a 50 x 100 mm single-sided PCB for the ESP32 weather station, ready for
LUT (laser-iron / toner-transfer) home etching.

Outputs (all written to the repository root, or gerber/ for the Gerbers):
  lut_bottom_mirrored.pdf / .svg / .png   <- the LUT master: bottom copper, mirrored, 1:1
  pcb_top_overlay.pdf / .svg              <- component placement + pin names, 1:1
  gerber/*.gbl .gm1 .gto .drl             <- Gerbers + Excellon drill
  pcb_report.txt                          <- DRC / connectivity summary

Usage:  python3 tools/build_pcb.py [--mirror-esp32]
        --mirror-esp32 swaps the two ESP32 header rows (see README).
"""
import math
import os
import sys
from collections import deque

from shapely.geometry import Point, LineString, Polygon, box
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = ROOT
GBR = os.path.join(ROOT, "gerber")

MIRROR = "--mirror-esp32" in sys.argv

# --------------------------------------------------------------------------- #
#  board + technology
# --------------------------------------------------------------------------- #
BW, BH = 50.0, 100.0          # board size, mm; origin bottom-left, +Y up
EDGE = 0.3                    # copper keep-out from the board edge
TRACE = 0.5                   # trace width (mm) - generous, LUT friendly
CLEAR = 0.3                   # copper-to-copper clearance
RES = 0.25                    # routing grid
POUR_CLEAR = 0.30             # copper-to-pad clearance of the ground pour
POUR_TRACE = 0.30             # copper-to-trace clearance of the ground pour
# Extra spacing the router reserves so the ground copper can actually flow
# between two traces (neck = 2 * NECK). Tried widest-first, relaxed on failure.
# (BLOCK_TRACE / BLOCK_PAD are set by the configuration search at the bottom:
#  they are the DRC clearance widened by a reserve so that ground copper can
#  still flow between two traces.  Widest reserve that still routes wins.)

PAD_HDR = 1.8                 # header pad diameter (2.54 mm pitch parts)
PAD_SMALL = 2.0               # resistor / LED pad diameter
DRILL_HDR = 1.0
DRILL_SMALL = 0.9
DRILL_MOUNT = 3.2

# --------------------------------------------------------------------------- #
#  ESP32 DevKit V1 (30 pin, DOIT)
#  51.45 x 28.33 mm body; two 15-pin rows, 25.4 mm apart, 2.54 mm pitch.
#  USB connector points to +Y.  Board sits x 10.835 .. 39.165, y 48.55 .. 100.
# --------------------------------------------------------------------------- #
ESP_X0, ESP_X1 = 10.835, 39.165
ESP_Y0, ESP_Y1 = 48.55, 100.0
ROW_L, ROW_R = 12.3, 37.7                 # header row X (25.4 mm apart)
PIN1_Y = 87.5                             # first pin (nearest the USB end)
PITCH = 2.54

LEFT_ROW = ["EN", "VP", "VN", "IO34", "IO35", "IO32", "IO33",
            "IO25", "IO26", "IO27", "IO14", "IO12", "IO13", "GND", "VIN"]
RIGHT_ROW = ["IO23", "IO22", "TX0", "RX0", "IO21", "IO19", "IO18", "IO5",
             "TX2", "RX2", "IO4", "IO2", "IO15", "GND", "3V3"]
if MIRROR:
    # A 180 deg rotation of the module swaps the two rows *and* reverses each
    # of them, so that physical pin 1 always stays next to the USB connector.
    LEFT_ROW, RIGHT_ROW = RIGHT_ROW[::-1], LEFT_ROW[::-1]

ESP_NET = {
    "VIN": "+5V", "3V3": "+3V3", "GND": "GND",
    "IO32": "BTN_BACK", "IO33": "LED_ALARM", "IO25": "LED_GREEN",
    "IO26": "LED_BLUE", "IO27": "BTN_MENU", "IO14": "BTN_UP", "IO13": "BTN_DOWN",
    "IO18": "BUZZER", "IO19": "RTC_CLK", "TX2": "RTC_DAT", "RX2": "RTC_RST",
    "IO21": "SDA", "IO22": "SCL",
}


def esp_pin_xy(side, pos):
    """side: 'L' | 'R'; pos: 1..15 counted from the USB end."""
    return (ROW_L if side == "L" else ROW_R), PIN1_Y - (pos - 1) * PITCH


# --------------------------------------------------------------------------- #
#  part list
# --------------------------------------------------------------------------- #
PADS = []      # dict(ref, pin, name, net, x, y, d, drill)
BODIES = []    # dict(kind, ...) purely for the drawing
HOLES = []     # (x, y, d)  non-plated mounting holes


def pad(ref, pin, name, net, x, y, d=PAD_HDR, drill=DRILL_HDR):
    PADS.append(dict(ref=ref, pin=pin, name=name, net=net, x=x, y=y, d=d, drill=drill))


# --- ESP32 -----------------------------------------------------------------
# Physical pin 1 is the one nearest the USB connector.  Pin numbering and the
# row order follow the davidkleymann/doit-esp32-devkit-kicad symbol+footprint
# pair (the only matched pair we could verify).  If your module is labelled the
# other way round, rebuild with --flip-esp32 (180 deg rotation of the module).
for p, nm in enumerate(LEFT_ROW, start=1):
    x, y = esp_pin_xy("L", p)
    pad("U1", str(p), nm, ESP_NET.get(nm), x, y)
for p, nm in enumerate(RIGHT_ROW, start=1):
    x, y = esp_pin_xy("R", p)
    pad("U1", str(p + 15), nm, ESP_NET.get(nm), x, y)

# --- ground buses ------------------------------------------------------------
# Three strips along the board edges that no signal trace is allowed to enter.
# They guarantee that the ground copper is continuous all round the board, so
# every GND pad placed on a bus is connected without any jumper.
BUSES = bool(os.environ.get("BUSES"))   # reserve edge strips as ground buses
BUS_L_X = 2.5            # left bus:   x <= 2.5
BUS_R_X = 47.5           # right bus:  x >= 47.5
BUS_B_Y = 2.0            # bottom bus: y <= 2.0
GND_L, GND_R = 2.5, 47.2     # where GND pads sit so they land on a bus
SIG_L, SIG_R = 5.04, 44.66   # first signal pin inboard of the bus
RES_X = 8.5                  # resistor column
P2 = 2.54

# --- buttons: left margin, spread out beside the ESP32 pin rows ---------------
for ref, net, y in (("J_BTN1", "BTN_MENU", 88.0), ("J_BTN2", "BTN_UP", 78.0),
                    ("J_BTN3", "BTN_DOWN", 68.0), ("J_BTN4", "BTN_BACK", 58.0)):
    pad(ref, "1", "SIG", net, 6.54, y)
    pad(ref, "2", "GND", "GND", 4.0, y)

# --- status LEDs + series resistors: bottom left ------------------------------
# GPIO -> R(1) -> R(2) -> LED anode -> LED cathode -> GND, so the resistor is
# genuinely in series; pad "1" of each resistor is the GPIO side.  Resistors
# stand vertically (7.62 mm lead spacing); a 5 mm LED goes in A/K directly.
LOCAL = {"LED1": "LED1_A", "LED2": "LED2_A", "LED3": "LED3_A"}
for ref, net, y in (("LED1", "LED_GREEN", 46.0), ("LED2", "LED_BLUE", 30.0),
                    ("LED3", "LED_ALARM", 14.0)):
    pad(ref, "A", "A", LOCAL[ref], 8.54, y, PAD_SMALL, DRILL_SMALL)
    pad(ref, "K", "K", "GND", 6.0, y, PAD_SMALL, DRILL_SMALL)
    rid = "R" + ref[-1]
    pad(rid, "2", "2", LOCAL[ref], 8.54, y - 4.0, PAD_SMALL, DRILL_SMALL)
    pad(rid, "1", "1", net, 8.54, y - 11.62, PAD_SMALL, DRILL_SMALL)

# --- connectors: horizontal rows with a clear service lane above each ---------
# A 2.54 mm pin row is a wall, so every pad has to be reached from above its
# own row; the 10 mm row pitch leaves a ~7.6 mm lane for that.
for i, (nm, net) in enumerate([("VCC", "+5V"), ("GND", "GND"), ("CLK", "RTC_CLK"),
                               ("DAT", "RTC_DAT"), ("RST", "RTC_RST")]):
    pad("J_RTC", str(i + 1), nm, net, 22.0 + i * P2, 8.0)
for i, (nm, net) in enumerate([("VCC", "+3V3"), ("GND", "GND"),
                               ("SCL", "SCL"), ("SDA", "SDA")]):
    pad("J_SENSOR", str(i + 1), nm, net, 22.0 + i * P2, 18.0)
for i, (nm, net) in enumerate([("GND", "GND"), ("VCC", "+5V"),
                               ("SDA", "SDA"), ("SCL", "SCL")]):
    pad("J_LCD", str(i + 1), nm, net, 22.0 + i * P2, 28.0)
pad("J_PWR", "1", "+5V", "+5V", 22.0, 38.0)
pad("J_PWR", "2", "GND", "GND", 24.54, 38.0)
pad("BZ1", "1", "+", "BUZZER", 34.0, 38.0)
pad("BZ1", "2", "-", "GND", 41.6, 38.0)

# --- mounting holes ----------------------------------------------------------
# Kept clear of the ground buses so they cannot sever the ground copper.
for hx, hy in ((4.0, 4.0), (46.0, 4.0), (4.0, 96.0), (46.0, 96.0)):
    HOLES.append((hx, hy, DRILL_MOUNT))

# --------------------------------------------------------------------------- #
#  routing grid
# --------------------------------------------------------------------------- #
NX, NY = int(round(BW / RES)), int(round(BH / RES))
N = NX * NY


def ci(i, j):
    return j * NX + i


def cx(x):
    return int(round(min(max(x, 0), BW - 1e-9) / RES))


def cy(y):
    return int(round(min(max(y, 0), BH - 1e-9) / RES))


blocked = bytearray(N)


def disc_cells(x, y, r_mm):
    """All grid cells whose centre lies inside the disc."""
    i0, j0 = cx(x), cy(y)
    k = int(math.ceil(r_mm / RES))
    out = []
    for j in range(max(0, j0 - k), min(NY, j0 + k + 1)):
        for i in range(max(0, i0 - k), min(NX, i0 + k + 1)):
            dx = (i + 0.5) * RES - x
            dy = (j + 0.5) * RES - y
            if dx * dx + dy * dy <= r_mm * r_mm:
                out.append(ci(i, j))
    return out


def block_disc(x, y, r_mm):
    for c in disc_cells(x, y, r_mm):
        blocked[c] = 1


# static obstacles: every pad, mounting hole and the board edge keep-out.
# BLOCK_PAD / BLOCK_TRACE are the router spacing (DRC clearance widened by the
# ground-neck reserve) and are set by the configuration search below.
BLOCK_PAD = 0.0
BLOCK_TRACE = 0.0


def rescan_static():
    global blocked, blocked0
    blocked = bytearray(N)
    for p in PADS:
        block_disc(p["x"], p["y"], p["d"] / 2.0 + BLOCK_PAD)
    for hx, hy, hd in HOLES:
        block_disc(hx, hy, hd / 2.0 + 0.7)
    for j in range(NY):
        for i in range(NX):
            x = (i + 0.5) * RES
            y = (j + 0.5) * RES
            if (x < EDGE or x > BW - EDGE or y < EDGE or y > BH - EDGE
                    or (BUSES and (x <= BUS_L_X or x >= BUS_R_X or y <= BUS_B_Y))):
                blocked[ci(i, j)] = 1
    blocked0 = bytearray(blocked)
    return blocked


rescan_static()


def bfs(sources, targets):
    """Shortest 4-connected path from any source cell to a target cell."""
    dist = [-1] * N
    prev = [-1] * N
    q = deque()
    for s in sources:
        if dist[s] == -1:
            dist[s] = 0
            q.append(s)
    tset = set(targets)
    while q:
        c = q.popleft()
        if c in tset:
            path = [c]
            while prev[path[-1]] != -1:
                path.append(prev[path[-1]])
            return path[::-1], c
        i, j = c % NX, c // NX
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < NX and 0 <= nj < NY:
                nk = ci(ni, nj)
                if dist[nk] == -1 and not blocked[nk]:
                    dist[nk] = dist[c] + 1
                    prev[nk] = c
                    q.append(nk)
    return None, None


def cells_of_path(path, r_mm):
    """Path cells dilated by r_mm (trace half width + clearance)."""
    out = set()
    for c in path:
        i, j = c % NX, c // NX
        x = (i + 0.5) * RES
        y = (j + 0.5) * RES
        k = int(math.ceil(r_mm / RES))
        for jj in range(max(0, j - k), min(NY, j + k + 1)):
            for ii in range(max(0, i - k), min(NX, i + k + 1)):
                dx = (ii + 0.5) * RES - x
                dy = (jj + 0.5) * RES - y
                if dx * dx + dy * dy <= r_mm * r_mm:
                    out.add(ci(ii, jj))
    return out


def simplify(path):
    """Cell path -> list of (x, y) mm waypoints, collinear points merged."""
    pts = [((c % NX + 0.5) * RES, (c // NX + 0.5) * RES) for c in path]
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        ax, ay = out[-1]
        bx, by = pts[k]
        cx2, cy2 = pts[k + 1]
        if abs((bx - ax) * (cy2 - ay) - (by - ay) * (cx2 - ax)) > 1e-9:
            out.append(pts[k])
    out.append(pts[-1])
    return out


# --------------------------------------------------------------------------- #
#  route every net except GND (GND is a copper pour)
# --------------------------------------------------------------------------- #
NETS = {}
for p in PADS:
    if p["net"]:
        NETS.setdefault(p["net"], []).append(p)

board_poly = box(EDGE / 2, EDGE / 2, BW - EDGE / 2, BH - EDGE / 2)


def net_span(net):
    xs = [p["x"] for p in NETS[net]]
    ys = [p["y"] for p in NETS[net]]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def cells_of_line(ln):
    """(x, y) waypoints -> the cells the polyline passes through."""
    out = []
    for (x1, y1), (x2, y2) in zip(ln, ln[1:]):
        nstep = int(max(abs(x2 - x1), abs(y2 - y1)) / RES) + 1
        for k in range(nstep + 1):
            t = k / float(nstep)
            out.append(ci(cx(x1 + (x2 - x1) * t), cy(y1 + (y2 - y1) * t)))
    return out


owner = [None] * N          # grid cell -> net that currently owns it


def try_route_pads(pins, clear, width, prim=True):
    """Route an arbitrary pad list.

    prim=True  - grow Prim style: each new leg springs off the *nearest* point
                 of the copper already laid down, which keeps big nets compact.
    prim=False - connect the pads in the order given (a simple chain).

    Returns (lines, cells) on success, or (None, connected, targets, halo) so
    the caller can work out which other nets are in the way."""
    snap_b = bytearray(blocked)
    snap_o = list(owner)
    own = [ci(cx(p["x"]), cy(p["y"])) for p in pins]
    halo = set()
    for p in pins:
        halo |= set(disc_cells(p["x"], p["y"], p["d"] / 2.0 + BLOCK_PAD))
    for c in halo:
        blocked[c] = 0
    connected = {own[0]}
    remaining = list(own[1:])
    lines, cells = [], set()
    while remaining:
        dist = [-1] * N
        prev = [-1] * N
        q = deque()
        for sc in connected:
            if dist[sc] == -1:
                dist[sc] = 0
                q.append(sc)
        tset = set(remaining) if prim else {remaining[0]}
        hit = None
        while q:
            c = q.popleft()
            if c in tset:
                hit = c
                break
            i, j = c % NX, c // NX
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < NX and 0 <= nj < NY:
                    nk = ci(ni, nj)
                    if dist[nk] == -1 and not blocked[nk]:
                        dist[nk] = dist[c] + 1
                        prev[nk] = c
                        q.append(nk)
        if hit is None:
            blocked[:] = snap_b
            owner[:] = snap_o
            return None, connected, remaining, halo
        path = [hit]
        while prev[path[-1]] != -1:
            path.append(prev[path[-1]])
        path = path[::-1]
        lines.append(simplify(path))
        cc = cells_of_path(path, width / 2.0 + BLOCK_TRACE)
        connected |= set(path)
        for c in cc:
            if c not in halo:        # never seal this net's own remaining pads
                blocked[c] = 1
        cells |= cc
        remaining.remove(hit)
    for c in halo:
        blocked[c] = 1
    return lines, cells | halo


def try_route(net, clear, width):
    """Route one net, trying both growth orders for multi-pin nets."""
    pins = NETS[net]
    r = try_route_pads(pins, clear, width, prim=False)
    if r[0] is not None or len(pins) < 3:
        return r
    return try_route_pads(pins, clear, width, prim=True)


def claim(net, cells):
    global blocked
    net_cells[net] = set(cells)
    for c in cells:
        owner[c] = net
        blocked[c] = 1


def release(net):
    global blocked
    for c in net_cells.pop(net, ()):
        owner[c] = None
        blocked[c] = blocked0[c]


def route_pass(order, clear, width):
    """One greedy pass over `order`. Returns (routed, failed)."""
    global blocked
    blocked = bytearray(blocked0)
    done, failed = {}, []
    for net in order:
        r = try_route(net, clear, width)
        if r[0] is None:
            failed.append(net)
        else:
            done[net] = r
    return done, failed


def solve(order, clear, width, budget=45.0, verbose=False, seed=20261111):
    """Greedy routing with randomised restarts, inside a time budget.

    Each round the net that failed with the longest span is promoted to the
    front (it is the one that most needs a clear board); every time that reduces
    the number of unrouted nets the ordering is kept, otherwise the tail is
    perturbed.  Deterministic seed -> reproducible artwork."""
    import random
    import time
    rnd = random.Random(seed)
    t0 = time.time()
    base = list(order)
    best_order, best_fail = list(base), None
    since = 0
    while time.time() - t0 < budget:
        done, failed = route_pass(base, clear, width)
        if not failed:
            return {n: v[0] for n, v in done.items()}, []
        if best_fail is None or len(failed) < len(best_fail):
            best_fail, best_order = failed, list(base)
            since = 0
            if verbose:
                print("   %5.1fs  %d unrouted: %s"
                      % (time.time() - t0, len(failed), ",".join(failed)))
        hard = max(failed, key=net_span)
        base.remove(hard)
        base.insert(0, hard)
        since += 1
        if since > 5:
            since = 0
            base = list(best_order)
            for _ in range(rnd.randint(1, 3)):
                if len(base) > 3:
                    a = rnd.randrange(len(base))
                    v = base.pop(a)
                    base.insert(rnd.randrange(len(base)), v)
    done, failed = route_pass(best_order, clear, width)
    return ({n: v[0] for n, v in done.items()}, failed)


net_lines = {}
net_cells = {}

# --------------------------------------------------------------------------- #
#  ground: the pour is the primary GND.  A single-sided pour gets cut into
#  islands by the signal traces, so every island holding a GND pad that is not
#  part of the main island is bridged with a real trace; whatever still cannot
#  be bridged is reported as a jumper for the component side.
# --------------------------------------------------------------------------- #
GND_PADS = [p for p in PADS if p["net"] == "GND"]


def analyse_pour(traces):
    """Flood the ground and work out islands / bridges / jumpers."""
    cut = []
    for p in PADS:
        if p["net"] != "GND":
            cut.append(Point(p["x"], p["y"]).buffer(p["d"] / 2.0 + POUR_CLEAR, 24))
    for net, lines in traces.items():
        for ln in lines:
            cut.append(LineString(ln).buffer(TRACE / 2.0 + POUR_TRACE, 8))
    for hx, hy, hd in HOLES:
        cut.append(Point(hx, hy).buffer(hd / 2.0 + 0.8, 24))
    pour = board_poly.difference(unary_union(cut))
    if pour.geom_type == "Polygon":
        parts = [pour]
    elif pour.geom_type == "MultiPolygon":
        parts = [g for g in pour.geoms if g.area > 0.4]
    else:
        parts = []

    groups, orphan = {}, []
    for p in GND_PADS:
        hit = None
        for i, g in enumerate(parts):
            if Point(p["x"], p["y"]).within(g.buffer(0.02)):
                hit = i
                break
        if hit is None:
            orphan.append(p)
        else:
            groups.setdefault(hit, []).append(p)
    return pour, parts, groups, orphan



def bottom_bridges(traces, groups):
    """Try to link stray ground islands with real copper on the bottom layer."""
    global blocked
    bridges = []
    if not groups or len(groups) == 1:
        return bridges
    main = max(groups, key=lambda k: len(groups[k]))
    blocked = bytearray(blocked0)
    for net, lines in traces.items():
        for ln in lines:
            for c in cells_of_path(cells_of_line(ln), TRACE / 2.0 + BLOCK_TRACE):
                blocked[c] = 1
    for k in sorted(groups):
        if k == main:
            continue
        src = groups[k][0]
        for tgt in sorted(groups[main],
                          key=lambda t: (t["x"] - src["x"]) ** 2
                                        + (t["y"] - src["y"]) ** 2):
            r = try_route_pads([src, tgt], CLEAR, TRACE)
            if r[0] is None:
                continue
            lines, cells = r
            bridges.append((src, tgt, lines))
            for c in cells:
                blocked[c] = 1
            groups.setdefault(main, []).extend(groups.pop(k))
            break
    return bridges


def top_jumper(src_pads, dst_pads):
    """Route an insulated wire on the component side.  That layer carries no
    copper at all, so the only things to avoid are the component pads."""
    global blocked
    save = bytearray(blocked)
    blocked = bytearray(N)
    for p in PADS:
        block_disc(p["x"], p["y"], p["d"] / 2.0 + 0.7)
    for hx, hy, hd in HOLES:
        block_disc(hx, hy, hd / 2.0 + 1.0)
    for j in range(NY):
        for i in range(NX):
            x = (i + 0.5) * RES
            y = (j + 0.5) * RES
            if x < 0.8 or x > BW - 0.8 or y < 0.8 or y > BH - 0.8:
                blocked[ci(i, j)] = 1
    out = []
    src = min(src_pads, key=lambda p: min((p["x"] - t["x"]) ** 2
                                          + (p["y"] - t["y"]) ** 2
                                          for t in dst_pads))
    for tgt in sorted(dst_pads, key=lambda t: (t["x"] - src["x"]) ** 2
                                              + (t["y"] - src["y"]) ** 2):
        # open a landing zone around both ends: the wire is soldered to them
        for p in (src, tgt):
            for c in disc_cells(p["x"], p["y"], p["d"] / 2.0 + 1.2):
                blocked[c] = 0
        r = try_route_pads([src, tgt], CLEAR, TRACE)
        if r[0] is None:
            continue
        lines, cells = r
        for c in cells:
            blocked[c] = 1
        out.append((src, tgt, lines))
        break
    blocked = save
    return out


def attempt(bpad, btrace, nm, kf, budget, verbose, seeds=8):
    """One full routing configuration -> a result dict."""
    global BLOCK_PAD, BLOCK_TRACE, blocked
    BLOCK_PAD, BLOCK_TRACE = bpad, btrace
    rescan_static()
    ordn = [k for k in sorted(NETS, key=kf)
            if k != "GND" or ROUTE_GND]
    traces, unrouted = None, ordn
    # several independent randomised restarts: the board is tight enough that a
    # single greedy trajectory often dead-ends, so keep the best of the lot.
    for k in range(seeds):
        t2, u2 = solve(ordn, CLEAR, TRACE, budget=budget / float(seeds),
                       verbose=verbose, seed=20261111 + 7919 * k)
        if traces is None or len(u2) < len(unrouted):
            traces, unrouted = t2, u2
        if not unrouted:
            break
    if unrouted:
        return dict(bpad=bpad, btrace=btrace, order=nm, traces=traces,
                    unrouted=unrouted, bridges=[], jumpers=[], pour_parts=[],
                    groups={}, orphan=[], pour=None)
    pour, parts, groups, orphan = analyse_pour(traces)
    bridges = bottom_bridges(traces, groups)
    jumpers = []

    # Whatever the ground still cannot reach is wired on the COMPONENT side,
    # where the board is completely empty, so those routes always succeed.
    if groups and len(groups) > 1:
        main = max(groups, key=lambda k: len(groups[k]))
        for k in sorted(groups):
            if k == main:
                continue
            jumpers += top_jumper(groups[k], groups[main])
            del groups[k]
    # re-flood so the artwork matches the analysis
    # re-flood with the bridges in place so the artwork matches the analysis
    all_traces = {n: list(v) for n, v in traces.items()}
    for src, tgt, lines in bridges:
        all_traces.setdefault("GND_BRIDGE", []).extend(lines)
    pour2, parts2, groups2, orphan2 = analyse_pour(all_traces)
    return dict(bpad=bpad, btrace=btrace, order=nm, traces=all_traces,
                unrouted=[], bridges=bridges, jumpers=jumpers, pour_parts=parts2,
                groups=groups2, orphan=orphan2, pour=pour2)


def dest_depth(net):
    """Y of the deepest (lowest) pad - how far down the board the net must go."""
    return min(p["y"] for p in NETS[net])


ORDERINGS = [
    ("deepest-first", lambda k: (dest_depth(k), -net_span(k))),
    ("longest-first", lambda k: -net_span(k)),
    ("shallow-first", lambda k: (-dest_depth(k), -net_span(k))),
]

VERBOSE = bool(os.environ.get("DBG"))
BUDGET = float(os.environ.get("BUDGET", "70"))
ROUTE_GND = bool(os.environ.get("ROUTE_GND"))

# Widest ground reserve first: a wider reserve means a healthier ground pour,
# so the first configuration that routes cleanly is the one we ship.
best = None
for btrace in ([0.55] if ROUTE_GND else [0.65, 0.55]):
    bpad = btrace - 0.25
    for nm, kf in ORDERINGS:
        if VERBOSE:
            print("== %s  spacing trace=%.2f pad=%.2f (pour neck %.2f mm)"
                  % (nm, btrace, bpad, 2 * (btrace - TRACE / 2.0 - POUR_TRACE)))
        r = attempt(bpad, btrace, nm, kf, BUDGET, VERBOSE)
        score = (len(r["unrouted"]), len(r["jumpers"]), len(r["groups"]),
                 len(r["pour_parts"]))
        if best is None or score < best[0]:
            best = (score, r)
        if len(r["unrouted"]) == 0:
            break
    if best is not None and len(best[1]["unrouted"]) == 0:
        break

TRACES = best[1]["traces"]
BRIDGES = best[1]["bridges"]
JUMPERS = best[1]["jumpers"]
pour_parts = best[1]["pour_parts"]
groups = best[1]["groups"]
orphan = best[1]["orphan"]
pour = best[1]["pour"]
pour_errs = []
for p in orphan:
    pour_errs.append("GND pad %s.%s is not inside any pour island" % (p["ref"], p["pin"]))
if len(groups) > 1:
    pour_errs.append("ground still split into %d islands - %.0f%% of the GND pads "
                     "are on the main one" % (len(groups),
                                              100.0 * len(max(groups.values(), key=len)) / max(1, len(GND_PADS))))
for src, tgt, _ln in JUMPERS:
    pour_errs.append("JUMPER on the component side: %s.%s -> %s.%s"
                     % (src["ref"], src["pin"], tgt["ref"], tgt["pin"]))
if len(pour_parts) > 1:
    pour_errs.append("ground fill ends up in %d fragments (%d hold GND pads)"
                     % (len(pour_parts), len(groups)))
if best[1]["unrouted"]:
    pour_errs.append("UNROUTED NETS: %s" % ", ".join(best[1]["unrouted"]))
print("chosen: trace spacing %.2f, pad spacing %.2f, order %s, %d bottom bridges, "
      "%d component-side jumpers"
      % (best[1]["btrace"], best[1]["bpad"], best[1]["order"], len(BRIDGES),
         len(JUMPERS)))



# --------------------------------------------------------------------------- #
#  DRC: pad-to-pad clearance in the placement
# --------------------------------------------------------------------------- #
drc = []
for i in range(len(PADS)):
    for j in range(i + 1, len(PADS)):
        a, b = PADS[i], PADS[j]
        d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
        need = (a["d"] + b["d"]) / 2.0 + CLEAR
        if d < need - 1e-6:
            drc.append("pads %s.%s <-> %s.%s : %.2f mm (need %.2f)"
                       % (a["ref"], a["pin"], b["ref"], b["pin"], d, need))
for hx, hy, hd in HOLES:
    for p in PADS:
        d = math.hypot(p["x"] - hx, p["y"] - hy)
        if d < hd / 2.0 + p["d"] / 2.0 + 0.5:
            drc.append("mounting hole (%.0f,%.0f) too close to %s.%s" % (hx, hy, p["ref"], p["pin"]))

# --------------------------------------------------------------------------- #
#  connectivity: the copper of every net must come out as ONE piece.
#  For GND that means pads + the pour islands that touch them + the jumpers
#  and any bottom-side bridges (the jumpers are wires on the component side,
#  soldered to the same pads, so they count as part of the net).
# --------------------------------------------------------------------------- #
conn = {}
for net in sorted(NETS):
    geoms = []
    for p in PADS:
        if p["net"] == net:
            geoms.append(Point(p["x"], p["y"]).buffer(p["d"] / 2.0, 16))
    for ln in TRACES.get(net, []):
        geoms.append(LineString(ln).buffer(TRACE / 2.0, 8))
    if net == "GND":
        for g in pour_parts:
            if any(Point(p["x"], p["y"]).within(g.buffer(0.02)) for p in GND_PADS):
                geoms.append(g)
        for _s, _t, lines in list(BRIDGES) + list(JUMPERS):
            for ln in lines:
                geoms.append(LineString(ln).buffer(0.3, 8))
    u = unary_union(geoms)
    comps = [u] if u.geom_type == "Polygon" else [g for g in getattr(u, "geoms", [])
                                                  if g.area > 1e-6]
    conn[net] = comps

conn_errs = ["%s: copper is in %d separate pieces" % (n, len(c))
             for n, c in conn.items() if len(c) > 1]

# --------------------------------------------------------------------------- #
#  output helpers
# --------------------------------------------------------------------------- #
def svg_path_polys(polys):
    d = []
    for g in polys:
        for ring in [g.exterior] + list(g.interiors):
            pts = list(ring.coords)
            d.append("M %.3f %.3f " % (pts[0][0], BH - pts[0][1]) +
                     " ".join("L %.3f %.3f" % (x, BH - y) for x, y in pts[1:]) + " Z")
    return " ".join(d)


def write_svg(path, bottom=False, overlay=True):
    W, H = BW, BH
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%.2fmm" height="%.2fmm" '
             'viewBox="0 0 %.2f %.2f">' % (W, H, W, H)]
    parts.append('<rect width="%.2f" height="%.2f" fill="%s"/>' % (W, H, "#111" if bottom else "#fff"))

    def T(x):
        return (BW - x) if bottom else x

    if bottom:
        parts.append('<path d="%s" fill-rule="evenodd" fill="#c8c8c8"/>' % svg_path_polys(pour_parts))
        for net, lines in TRACES.items():
            for ln in lines:
                pts = " ".join("%.3f,%.3f" % (T(x), y) for x, y in ln)
                parts.append('<polyline points="%s" fill="none" stroke="#c8c8c8" '
                             'stroke-width="%.3f" stroke-linejoin="round" stroke-linecap="round"/>'
                             % (pts, TRACE))
        for p in PADS:
            parts.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="#c8c8c8"/>' %
                         (T(p["x"]), p["y"], p["d"] / 2.0))
    if overlay:
        # board outline
        parts.append('<rect x="0.15" y="0.15" width="%.2f" height="%.2f" fill="none" '
                     'stroke="#000" stroke-width="0.2"/>' % (W - 0.3, H - 0.3))
        for hx, hy, hd in HOLES:
            parts.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="none" stroke="#000" '
                         'stroke-width="0.15"/>' % (T(hx), hy, hd / 2.0))
        # ESP32 outline
        parts.append('<rect x="%.3f" y="%.3f" width="%.2f" height="%.2f" fill="none" '
                     'stroke="#000" stroke-width="0.2"/>' %
                     (min(T(ESP_X0), T(ESP_X1)), ESP_Y0, abs(ESP_X1 - ESP_X0), ESP_Y1 - ESP_Y0))
        parts.append('<text x="%.2f" y="%.2f" font-size="2" fill="#000">ESP32 DevKit V1</text>'
                     % (min(T(ESP_X0), T(ESP_X1)) + 1.5, ESP_Y1 - 2.5))
        for p in PADS:
            if p["ref"] == "U1":
                rot = -90
                lx = T(p["x"]) + (1.6 if p["x"] == ROW_R else -1.6)
                parts.append('<text x="%.3f" y="%.3f" font-size="1.15" fill="#000" '
                             'transform="rotate(%d %.3f %.3f)" text-anchor="start">%s</text>'
                             % (lx, p["y"] + 0.4, rot, lx, p["y"] + 0.4, p["name"]))
        for p in PADS:
            if p["ref"] != "U1":
                parts.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="none" stroke="#555" '
                             'stroke-width="0.1"/>' % (T(p["x"]), p["y"], p["d"] / 2.0))
        for src, tgt, lines in JUMPERS:
            for ln in lines:
                pts = " ".join("%.3f,%.3f" % (T(x), y) for x, y in ln)
                parts.append('<polyline points="%s" fill="none" stroke="#c00000" '
                             'stroke-width="0.35" stroke-dasharray="1.2 0.8"/>' % pts)
            parts.append('<text x="%.2f" y="%.2f" font-size="1.2" fill="#c00000">'
                         'jump %s.%s</text>'
                         % (T(src["x"]) + 1.0, src["y"] + 1.0, src["ref"], src["pin"]))
        seen = {}
        for p in PADS:
            seen.setdefault(p["ref"], []).append(p)
        for ref, ps in seen.items():
            if ref == "U1":
                continue
            xs = [q["x"] for q in ps]
            ys = [q["y"] for q in ps]
            tx = min(T(x) for x in xs)
            parts.append('<text x="%.2f" y="%.2f" font-size="1.6" fill="#000">%s</text>'
                         % (tx, max(ys) + 3.2, ref))
            for q in ps:
                parts.append('<text x="%.2f" y="%.2f" font-size="1.1" fill="#444">%s</text>'
                             % (T(q["x"]) - 0.8, q["y"] - 2.0, q["name"]))
    parts.append("</svg>")
    open(path, "w", encoding="utf-8").write("\n".join(parts))


def write_png(path, ppi=600):
    from PIL import Image, ImageDraw
    s = ppi / 25.4
    img = Image.new("L", (int(BW * s), int(BH * s)), 0)
    d = ImageDraw.Draw(img)

    def P(x, y):
        return ((BW - x) * s, (BH - y) * s)      # bottom layer => mirrored

    for g in pour_parts:
        pts = [P(x, y) for x, y in g.exterior.coords]
        d.polygon(pts, fill=255)
        for ring in g.interiors:
            d.polygon([P(x, y) for x, y in ring.coords], fill=0)
    wpx = max(1, int(TRACE * s))
    for net, lines in TRACES.items():
        for ln in lines:
            d.line([P(x, y) for x, y in ln], fill=255, width=wpx)
    for p in PADS:
        r = p["d"] / 2.0 * s
        x, y = P(p["x"], p["y"])
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    img.save(path)
    return img.size


def write_pdf(path, bottom=True):
    from reportlab.pdfgen import canvas as rlc
    from reportlab.lib.units import mm as MM
    c = rlc.Canvas(path, pagesize=(BW * MM, BH * MM))
    c.setTitle("ESP32 weather station - 50x100 mm PCB")

    def P(x, y):
        return ((BW - x) if bottom else x) * MM, y * MM

    if bottom:
        for g in pour_parts:
            pts = [P(x, y) for x, y in g.exterior.coords]
            c.setFillColorRGB(0.15, 0.15, 0.15)
            c.setStrokeColorRGB(0.15, 0.15, 0.15)
            pth = c.beginPath()
            pth.moveTo(*pts[0])
            for q in pts[1:]:
                pth.lineTo(*q)
            pth.close()
            c.drawPath(pth, fill=1, stroke=1)
            c.setFillColorRGB(1, 1, 1)
            for ring in g.interiors:
                pts = [P(x, y) for x, y in ring.coords]
                pth = c.beginPath()
                pth.moveTo(*pts[0])
                for q in pts[1:]:
                    pth.lineTo(*q)
                pth.close()
                c.drawPath(pth, fill=1, stroke=0)
        c.setStrokeColorRGB(0.15, 0.15, 0.15)
        c.setLineWidth(TRACE * MM)
        c.setLineCap(1)
        c.setLineJoin(1)
        for net, lines in TRACES.items():
            for ln in lines:
                pts = [P(x, y) for x, y in ln]
                pth = c.beginPath()
                pth.moveTo(*pts[0])
                for q in pts[1:]:
                    pth.lineTo(*q)
                c.drawPath(pth, fill=0, stroke=1)
        c.setFillColorRGB(0.15, 0.15, 0.15)
        for p in PADS:
            x, y = P(p["x"], p["y"])
            c.circle(x, y, p["d"] / 2.0 * MM, fill=1, stroke=0)
    if not bottom:
        c.setStrokeColorRGB(0.75, 0.0, 0.0)
        c.setLineWidth(0.35 * MM)
        c.setDash(1.2 * MM, 0.8 * MM)
        for src, tgt, lines in JUMPERS:
            for ln in lines:
                pts = [P(x, y) for x, y in ln]
                pth = c.beginPath()
                pth.moveTo(*pts[0])
                for q in pts[1:]:
                    pth.lineTo(*q)
                c.drawPath(pth, fill=0, stroke=1)
        c.setDash()
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.2 * MM)
    c.rect(0.15 * MM, 0.15 * MM, (BW - 0.3) * MM, (BH - 0.3) * MM, fill=0, stroke=1)
    for hx, hy, hd in HOLES:
        x, y = P(hx, hy)
        c.circle(x, y, hd / 2.0 * MM, fill=0, stroke=1)
    # component overlay
    x0 = min((BW - ESP_X0) if bottom else ESP_X0, (BW - ESP_X1) if bottom else ESP_X1)
    c.rect(x0 * MM, ESP_Y0 * MM, abs(ESP_X1 - ESP_X0) * MM, (ESP_Y1 - ESP_Y0) * MM, fill=0, stroke=1)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 5)
    c.drawString((x0 + 1) * MM, (ESP_Y1 - 3) * MM, "ESP32 DevKit V1 (USB up)")
    c.setFont("Helvetica", 3)
    for p in PADS:
        if p["ref"] != "U1":
            continue
        lx = (BW - p["x"]) if bottom else p["x"]
        c.saveState()
        c.translate(lx * MM, p["y"] * MM)
        c.rotate(90)
        c.drawString(0.6 * MM, -0.4 * MM, p["name"])
        c.restoreState()
    c.setFont("Helvetica", 4)
    seen = {}
    for p in PADS:
        seen.setdefault(p["ref"], []).append(p)
    for ref, ps in seen.items():
        if ref == "U1":
            continue
        xs = [((BW - q["x"]) if bottom else q["x"]) for q in ps]
        ys = [q["y"] for q in ps]
        c.drawString(min(xs) * MM, (max(ys) + 2.2) * MM, ref)
        c.setFont("Helvetica", 2.6)
        for q in ps:
            c.drawString((((BW - q["x"]) if bottom else q["x"]) - 0.9) * MM,
                         (q["y"] + 0.9) * MM, q["name"])
        c.setFont("Helvetica", 4)
    c.setFont("Helvetica", 3)
    c.drawString(2 * MM, 1 * MM, "Bottom copper, MIRRORED, 1:1 - print at 100% (no scaling) for LUT"
                 if bottom else "Component side, 1:1")
    c.showPage()
    c.save()


def write_gerbers():
    os.makedirs(GBR, exist_ok=True)

    def hdr(name, polarity="D"):
        return ["%FSLAX44Y44*%", "%MOMM*%", "%LNPBC*%", "G04 %s*" % name]

    # ---- bottom copper ----------------------------------------------------
    L = hdr("Bottom copper (LUT layer)")
    L.append("%%ADD10C,%.4f*%%" % TRACE)
    L.append("%%ADD11C,%.4f*%%" % PAD_HDR)
    L.append("%%ADD12C,%.4f*%%" % PAD_SMALL)
    L.append("D10*")
    # traces are stroked with the round TRACE aperture
    for net, lines in TRACES.items():
        for ln in lines:
            pts = [(x, BH - y) for x, y in ln]
            L.append("G01*")
            L.append("X%07.0fY%07.0fD02*" % (pts[0][0] * 10000, pts[0][1] * 10000))
            for x, y in pts[1:]:
                L.append("X%07.0fY%07.0fD01*" % (x * 10000, y * 10000))
    for p in PADS:
        L.append("D%s*" % ("11" if abs(p["d"] - PAD_HDR) < 1e-6 else "12"))
        L.append("X%07.0fY%07.0fD03*" % (p["x"] * 10000, (BH - p["y"]) * 10000))
    L.append("G36*")
    for g in pour_parts:
        for ring in [g.exterior] + list(g.interiors):
            pts = list(ring.coords)
            L.append("G01*")
            L.append("X%07.0fY%07.0fD02*" % (pts[0][0] * 10000, (BH - pts[0][1]) * 10000))
            for x, y in pts[1:]:
                L.append("X%07.0fY%07.0fD01*" % (x * 10000, (BH - y) * 10000))
            L.append("X%07.0fY%07.0fD01*" % (pts[0][0] * 10000, (BH - pts[0][1]) * 10000))
    L.append("G37*")
    L.append("M02*")
    open(os.path.join(GBR, "bottom_copper.gbl"), "w").write("\n".join(L) + "\n")

    # ---- board outline ----------------------------------------------------
    O = hdr("Board outline")
    O.append("%ADD10C,0.2000*%")
    O.append("D10*")
    pts = [(0, 0), (BW, 0), (BW, BH), (0, BH), (0, 0)]
    O.append("G01*")
    O.append("X%07.0fY%07.0fD02*" % (pts[0][0] * 10000, (BH - pts[0][1]) * 10000))
    for x, y in pts[1:]:
        O.append("X%07.0fY%07.0fD01*" % (x * 10000, (BH - y) * 10000))
    O.append("M02*")
    open(os.path.join(GBR, "board_outline.gm1"), "w").write("\n".join(O) + "\n")

    # ---- drill ------------------------------------------------------------
    sizes = sorted({round(p["drill"], 2) for p in PADS} | {DRILL_MOUNT})
    D = ["M48", "; Excellon drill file, metric, leading zeros suppressed",
         "METRIC,TZ"]
    for k, s in enumerate(sizes, start=1):
        D.append("T%dC%.3f" % (k, s))
    D.append("%")
    D.append("G90")
    for k, s in enumerate(sizes, start=1):
        D.append("T%d" % k)
        for p in PADS:
            if abs(p["drill"] - s) < 1e-6:
                D.append("X%07.0fY%07.0f" % (p["x"] * 1000, (BH - p["y"]) * 1000))
        if abs(s - DRILL_MOUNT) < 1e-6:
            for hx, hy, hd in HOLES:
                D.append("X%07.0fY%07.0f" % (hx * 1000, (BH - hy) * 1000))
    D.append("M30")
    open(os.path.join(GBR, "drill.drl"), "w").write("\n".join(D) + "\n")


# --------------------------------------------------------------------------- #
os.makedirs(GBR, exist_ok=True)
write_svg(os.path.join(OUT, "lut_bottom_mirrored.svg"), bottom=True, overlay=False)
write_svg(os.path.join(OUT, "pcb_top_overlay.svg"), bottom=False, overlay=True)
write_png(os.path.join(OUT, "lut_bottom_mirrored.png"))
write_pdf(os.path.join(OUT, "lut_bottom_mirrored.pdf"), bottom=True)
write_pdf(os.path.join(OUT, "pcb_top_overlay.pdf"), bottom=False)
write_gerbers()

rep = []
rep.append("PCB  %.0f x %.0f mm, single sided, %d pads, %d holes"
           % (BW, BH, len(PADS), len(HOLES)))
rep.append("routed nets: %d ; traces: %d ; GND = copper pour"
           % (len(TRACES), sum(len(v) for v in TRACES.values())))
tl = sum(sum(math.dist(a, b) for a, b in zip(ln, ln[1:])) for v in TRACES.values() for ln in v)
rep.append("total trace length: %.0f mm" % tl)
rep.append("")
rep.append("placement DRC (pad clearance %.2f mm): %s"
            % (CLEAR, "clean" if not drc else "%d problem(s)" % len(drc)))
for e in drc:
    rep.append("  ! " + e)
rep.append("connectivity (every net in one piece): %s"
            % ("OK - all %d nets connected" % len(NETS) if not conn_errs
               else "FAILED"))
for e in conn_errs:
    rep.append("  ! " + e)
for e in drc:
    rep.append("  ! " + e)
rep.append("")
rep.append("pour check: %s" % ("clean" if not pour_errs else "see below"))
for e in pour_errs:
    rep.append("  " + e)
rep.append("")
rep.append("net -> pads")
for net in sorted(NETS):
    rep.append("  %-10s %s" % (net, " ".join("%s.%s" % (p["ref"], p["pin"])
                                             for p in NETS[net])))
open(os.path.join(OUT, "pcb_report.txt"), "w", encoding="utf-8").write("\n".join(rep) + "\n")
print("\n".join(rep))
if drc:
    sys.exit(1)
