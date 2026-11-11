#!/usr/bin/env python3
"""Layout sanity checks for the generated EasyEDA schematic.

  * everything inside the drawing frame
  * no two component bodies overlap
  * no two net-label texts overlap (estimated from the string length)
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "SCH_ESP32_WeatherStation_2026-11-11.json")

FRAME = dict(x=10.0, y=-796.0, w=1129.0, h=786.0)   # inner border of the A4 frame

doc = json.load(open(SRC, encoding="utf-8"))
shapes = doc["schematics"][0]["dataStr"]["shape"]

NUM = re.compile(r"-?\d+(?:\.\d+)?")
bodies = []      # (designator, x0, y0, x1, y1)
labels = []      # (name, x0, y0, x1, y1)
problems = []
allpts = []


def track(x, y):
    allpts.append((x, y))


for s in shapes:
    subs = s.split("#@$")
    head = subs[0]
    if head.startswith("W~"):
        p = [float(v) for v in NUM.findall(head)]
        for i in (0, 2):
            track(p[i], p[i + 1])
        continue
    if head.startswith("N~"):
        f = head.split("~")
        x, y, name, anchor = float(f[1]), float(f[2]), f[5], f[7]
        w = len(name) * 3.6 + 2
        x0 = x - w if anchor == "end" else x
        labels.append((name, x0, y - 6 - 7, x0 + w, y - 6 + 2))
        track(x, y)
        continue
    if not head.startswith("LIB~"):
        continue

    des = None
    bx0 = by0 = bx1 = by1 = None
    for sub in subs[1:]:
        f = sub.split("~")
        t = f[0]
        if t == "T" and f[1] == "P":
            des = f[12]
        elif t == "R":
            x, y, w, h = float(f[1]), float(f[2]), float(f[5]), float(f[6])
            bx0 = x if bx0 is None else min(bx0, x)
            by0 = y if by0 is None else min(by0, y)
            bx1 = x + w if bx1 is None else max(bx1, x + w)
            by1 = y + h if by1 is None else max(by1, y + h)
        elif t == "PL":
            p = [float(v) for v in NUM.findall(f[1])]
            for i in (0, 2):
                track(p[i], p[i + 1])
            if bx0 is None:
                bx0 = min(p[0], p[2]); bx1 = max(p[0], p[2])
                by0 = min(p[1], p[3]); by1 = max(p[1], p[3])
            else:
                bx0 = min(bx0, p[0], p[2]); bx1 = max(bx1, p[0], p[2])
                by0 = min(by0, p[1], p[3]); by1 = max(by1, p[1], p[3])
        elif t == "PG":
            p = [float(v) for v in NUM.findall(f[1])]
            xs = p[0::2]; ys = p[1::2]
            if bx0 is None:
                bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
            else:
                bx0 = min(bx0, min(xs)); bx1 = max(bx1, max(xs))
                by0 = min(by0, min(ys)); by1 = max(by1, max(ys))
        elif t == "P":
            parts = sub.split("^^")
            hh = parts[0].split("~")
            x, y = float(hh[4]), float(hh[5])
            track(x, y)
    if des and des != "A" and bx0 is not None:
        # include the designator text sitting above the body
        bodies.append((des, bx0, by0 - 26, bx1, by1))

# --- 1. inside the frame ----------------------------------------------------
for x, y in allpts:
    if not (FRAME["x"] - 1 <= x <= FRAME["x"] + FRAME["w"] + 1):
        problems.append("point (%g,%g) outside the frame horizontally" % (x, y))
    if not (FRAME["y"] - 1 <= y <= FRAME["y"] + FRAME["h"] + 1):
        problems.append("point (%g,%g) outside the frame vertically" % (x, y))

for name, x0, y0, x1, y1 in labels:
    if x0 < FRAME["x"] or x1 > FRAME["x"] + FRAME["w"] or y0 < FRAME["y"]:
        problems.append("net label %-10s text box (%g,%g)-(%g,%g) escapes the frame"
                        % (name, x0, y0, x1, y1))

# --- 2. component bodies must not overlap ----------------------------------
def ov(a, b):
    return not (a[3] <= b[1] or b[3] <= a[1] or a[4] <= b[2] or b[4] <= a[2])


for i in range(len(bodies)):
    for j in range(i + 1, len(bodies)):
        if ov(bodies[i], bodies[j]):
            problems.append("component bodies overlap: %s <-> %s" % (bodies[i][0], bodies[j][0]))

# --- 3. net label texts must not overlap each other ------------------------
for i in range(len(labels)):
    for j in range(i + 1, len(labels)):
        if ov(("a",) + labels[i][1:], ("b",) + labels[j][1:]):
            problems.append("net label texts overlap: %s <-> %s" % (labels[i][0], labels[j][0]))

# --- 4. net label texts must not sit on top of a component body ------------
for name, x0, y0, x1, y1 in labels:
    for b in bodies:
        if ov(("a", x0, y0, x1, y1), ("b",) + b[1:]):
            problems.append("net label %s overlaps the body of %s" % (name, b[0]))

if problems:
    print("LAYOUT CHECK FAILED (%d)" % len(problems))
    for p in problems:
        print("  !", p)
    sys.exit(1)
print("LAYOUT OK - %d components, %d net labels, all inside the frame, no overlaps"
      % (len(bodies), len(labels)))
