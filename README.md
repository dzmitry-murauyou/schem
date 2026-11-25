# ESP32 Weather Station — schematic review & rebuild

Corrected EasyEDA v6 schematic rebuilt from your original export to match the
hardware specification.

| File | What it is |
| --- | --- |
| `SCH_ESP32_WeatherStation_2026-11-11.json` | **The deliverable** — EasyEDA v6.5.61 schematic, import it directly |
| `SCH_New-Project1_2026-11-11.json` | Your original export, kept untouched for reference |
| `netlist.txt` / `netlist.json` | Netlist extracted from the drawn geometry |
| `bom.csv` | Bill of materials |
| `preview.png` | Quick raster preview of the new sheet (handy to eyeball placement) |
| `ESP32_WeatherStation_2026-11-11_pcb.json` | **PCB for EasyEDA Standard** — 100 × 50 mm horizontal, open it, ratlines are ready, route and go |
| `pcb_preview.png` / `.pdf` | 100 × 50 mm horizontal board, top view with the ratsnest (see what you are about to route) |
| `pcb_easyeda_check.txt` | What the PCB generator verified: pads, nets, DRC, courtyard clearance, silk, ratline length |
| `tools/build_easyeda_pcb.py` | The PCB generator (writes the JSON above) |
| `tools/pcb_common.py` | Placement of every part on the 100 × 50 mm board — shared by `build_easyeda_pcb.py` and `build_pcb_preview.py` |
| `tools/build_pcb_preview.py` | Draws `pcb_preview.*` from the same placement |
| `tools/build_schematic.py` | The generator — edit this and re-run to change anything |
| `tools/check_layout.py` | Layout guard: bounds, component overlap, label collision |
| `tools/render_png.py` | Dev-only preview renderer |

Rebuild everything with:

```bash
python3 tools/build_schematic.py && python3 tools/check_layout.py
```

Both scripts verify themselves: the first rebuilds the netlist **from the drawn
wires and net labels** and asserts it matches the intended connectivity
(`VERIFY OK - 16 nets, 69 pins, 53 wires, 50 net labels`), the second asserts
nothing escapes the drawing frame or collides (`LAYOUT OK - 17 components`).

## How to import

Two files, two documents:

1. **the schematic** — EasyEDA → **File → Open → EasyEDA** and pick
   `SCH_ESP32_WeatherStation_2026-11-11.json`. Same format and `editorVersion`
   (6.5.61) as your original, so it drops straight in.
2. **the PCB** — same menu, pick `ESP32_WeatherStation_2026-11-11_pcb.json`.
   Footprints, pads, nets and the board outline are already there; the ratlines
   show what to connect. See [section 5](#5-pcb-for-easyeda-route-it-yourself).

EasyEDA Standard keeps one document per file, so the two stay separate — the net
names are what tie them together. (The old advice "use *Design → Convert to PCB*"
is no longer needed: the board is in section 5, already laid out and unrouted.)

---

## 1. What was wrong in the original

| # | Problem in `SCH_New-Project1_2026-11-11.json` | Fix |
| --- | --- | --- |
| 1 | Switches `SW1–SW4` were PCB-mount tact switches (`SW-TH_KH-6X6X5H-B2J-FS`) | Replaced with `J_BTN1–J_BTN4`, 2-pin 2.54 mm headers for off-board panel buttons |
| 2 | LEDs were three identical **red** LEDs (`F5红光食人鱼`) | `LED1` green, `LED2` blue, `LED3` red/white, driven from GPIO 25 / 26 / 33 |
| 3 | Resistors were designators **U4, U5, U6** with SPICE prefix `U` and value `R0805测试` (a test placeholder) | Renamed **R1, R2, R3**, prefix `R`, value **220 Ω** |
| 4 | Resistors had no stated value and were in the wrong place relative to the LEDs | Each LED is now `GPIO → 220R → anode`, cathode → GND |
| 5 | Power input `H1` was a **1.27 mm pitch** header (`HX-PZ1.27-1X2P-ZZ`) | `J_PWR`, 2-pin **2.54 mm**, pin 1 = +5 V, pin 2 = GND (USB-C pigtail) |
| 6 | The **AHT20 + BMP280 sensor was missing entirely** | Added `J_SENSOR`, 4-pin header, VCC on the **3.3 V** rail |
| 7 | No 3.3 V rail was used anywhere | `+3V3` net created from ESP32 `3V3`, feeding the sensor only |
| 8 | LCD was `U1` "Display", an unnamed 1×4 header with SCL/SDA/VCC/GND | `J_LCD` — LCD 2004 + I2C backpack, 4-pin, VCC on **+5 V** |
| 9 | RTC connector `U3` was a 6.35 mm-pitch 1×5 header (a mains-style connector) | `J_RTC` — 5-pin **2.54 mm**: RST / DAT / CLK / VCC / GND |
| 10 | Buzzer `U7` was an **SMD** buzzer with prefix `U` | `BZ1`, through-hole passive buzzer, prefix `BZ`, + → GPIO 18, − → GND |
| 11 | ESP32 designator was literally **`1`** (the sheet's `Prefix Start` was `1`, so auto-annotation had eaten it) | `U1`; document `Prefix Start` moved to `100` so new parts can't collide |
| 12 | Only **one wire** and three `+5v` labels existed in the whole schematic — no connectivity at all | 51 wires + 48 net labels, fully connected and machine-verified |
| 13 | The ESP32 library symbol draws every pin name **twice** (once inside the body, once just outside where it lands on top of any stub) | The duplicate outer text is hidden |
| 14 | No `GND` net, no `SDA`/`SCL` nets | Full netlist, see below |

## 2. Final connectivity

### Power

| Net | Members |
| --- | --- |
| `+5V` | `J_PWR.1` (USB-C red), `U1.VIN`, `J_LCD.2` (VCC), `J_RTC.1` (VCC), `C1.+` |
| `+3V3` | `U1.3V3`, `J_SENSOR.1` (VCC) — **nothing else** |
| `GND` | `J_PWR.2`, `U1.GND`, `U1.GND2`, `J_LCD.1`, `J_SENSOR.2`, `J_RTC.2`, `J_BTN1-4.2`, `LED1-3.K`, `BZ1.2`, `C1.-` |

### Signals

| ESP32 pin | GPIO | Net | Destination |
| --- | --- | --- | --- |
| `D21` | 21 | `SDA` | `J_LCD.3`, `J_SENSOR.4` |
| `D22` | 22 | `SCL` | `J_LCD.4`, `J_SENSOR.3` |
| `RX2` | 16 | `RTC_RST` | `J_RTC.5` |
| `TX2` | 17 | `RTC_DAT` | `J_RTC.4` |
| `D19` | 19 | `RTC_CLK` | `J_RTC.3` |
| `D18` | 18 | `BUZZER` | `BZ1.1` (+) |
| `D27` | 27 | `BTN_MENU` | `J_BTN1.1` |
| `D14` | 14 | `BTN_UP` | `J_BTN2.1` |
| `D13` | 13 | `BTN_DOWN` | `J_BTN3.1` |
| `D32` | 32 | `BTN_BACK` | `J_BTN4.1` |
| `D25` | 25 | `LED_GREEN` | `R1.1` → `R1.2` → `LED1.A` |
| `D26` | 26 | `LED_BLUE` | `R2.1` → `R2.2` → `LED2.A` |
| `D33` | 33 | `LED_ALARM` | `R3.1` → `R3.2` → `LED3.A` |

Every button header is `pin 1 = signal, pin 2 = GND`, so configure the four
inputs as `INPUT_PULLUP` (pressed = LOW).

### Power reservoir

`C1` — **1000 µF / 10 V electrolytic**, straight across `+5V` and `GND` next to
the power input. Pin 1 is `+` (long leg), pin 2 is `−` (short leg / stripe).
It holds the 5 V rail up during the ESP32's Wi-Fi transmit peaks (~500 mA), which
otherwise show up as a dip on `VIN`. The working voltage is 10 V against a 5 V
rail, so there is 2× margin; do not fit it the other way round — it will pop.

## 3. Things you should still check before ordering

These are judgement calls I could not make from the spec alone:

1. **DS1302 module at 5 V on 3.3 V GPIOs.** Most DS1302 breakouts pull DAT/CLK/RST
   up to their own VCC. Powered from 5 V they will push 5 V into GPIO 16/17/19.
   The ESP32 is *not* 5 V-tolerant. Either power the DS1302 module from 3.3 V,
   or add a level shifter / series resistors. I wired VCC to +5 V exactly as
   specified.
2. **LCD 2004 I2C at 5 V.** The backpack pulls SDA/SCL up to 5 V. In practice
   almost every build works because the ESP32 sees 5 V only through a pull-up,
   but it is out of spec. If you want to be strict, run the backpack from 3.3 V
   (the contrast may need adjusting) or add a proper level shifter.
3. **Buzzer driven straight from GPIO 18** (your choice). A passive buzzer coil
   wants more than the ~12 mA an ESP32 pin should comfortably source, and it is
   an inductive load. If it is too quiet, add the usual NPN + 1 k base resistor
   + flyback diode, or use a 3-pin buzzer module (VCC/GND/SIG).
4. **Footprint names are placeholders to confirm when you convert to PCB:**
   `HDR-TH_1x2-P2.54-V-M`, `HDR-TH_1x4-P2.54-V-M`, `HDR-TH_1x5-P2.54-V-M`,
   `R_AXIAL-0.4`, `LED-TH_F5`, `BUZ-TH_BD12.5`. Pick the exact part you are
   buying in the *Convert to PCB* dialog.
5. **GPIO strapping pins are all avoided** — nothing is wired to GPIO 0, 2, 5, 12
   or 15, and nothing is wired to the input-only pins 34/35/36/39. GPIO 32/33,
   25/26, 27, 14, 13, 18, 19, 21, 22, 16, 17 are all safe here.
6. The ESP32 DevKit V1 has an onboard 5 V→3.3 V regulator, so feeding 5 V into
   `VIN` from the USB-C pigtail is correct. Do **not** also feed 5 V into the
   `3V3` pin.

## 4. Layout

The sheet is organised left-to-right:

* **left column** — power input, DS1302, AHT20/BMP280, LCD 2004 (all the 5 V /
  3.3 V / I2C modules that hang off the ESP32's left-hand pins)
* **centre** — `U1`, ESP32 DevKit V1, 30-pin
* **right column** — buttons, then the 220 Ω resistors and their LEDs, with the
  buzzer below

Every net is carried by a short stub wire plus a net label rather than long
routed wires, which keeps the 10-unit pin pitch on the ESP32 symbol readable.

## 5. PCB for EasyEDA (route it yourself)

`ESP32_WeatherStation_2026-11-11_pcb.json` is a **100 × 50 mm horizontal board
in native EasyEDA Standard format** (`docType 3`, editorVersion 6.4.25 — the same
format family as the schematic). Everything except the tracks is done:

* all **17 footprints** placed and rotated, silkscreen drawn, **pin 1 marked**;
* **69 pads**, each carrying its real pin number and its **net name from the
  schematic** — so EasyEDA draws the ratlines for you;
* board outline 100 × 50 mm (longer side along X) on the outline layer,
  **4 × 3.2 mm M3 mounting holes**;
* routing rules inside the file: track 0.6 mm, clearance 0.3 mm, via 0.8/0.4 mm,
  `+5V` and `GND` flagged as 1.2 mm nets.

Open `easyeda.com/editor` → **File → Open → EasyEDA File** and pick the JSON.
The schematic and the PCB are separate documents in EasyEDA Standard (one file
per document), so keep the schematic file next to it — the net names are what
tie the two together.

| | value |
|---|---|
| board | 100 × 50 mm horizontal, origin bottom-left, USB end on the left |
| ESP32 (`U1`) | DOIT DevKit V1, body **51.45 × 28.33 mm**, 2 × 15 sockets on 2.54 mm, rows **25.40 mm (1.0") apart** |
| physical keepout | non-`U1` pads ≥ 5.3 mm, non-`U1` silk ≥ 3.7 mm, and M3 holes ≥ 5.3 mm clear of `U1`'s full 51.45 × 28.33 mm PCB body |
| pin 1 | `3V3`, bottom-left at the USB end (`VIN` top-left opposite it), `EN` at the far right |
| footprints | `ESP32-DEVKIT-V1-30PIN_DZ`, headers `HDR-TH_1xN-P2.54-V-M`, `R_AXIAL-0.4`, `LED-TH_F5`, `CAP-TH_D8.0-P3.5`, `BUZ-TH_BD12.5` |
| pads | ⌀1.8 mm / 1.0 mm drill on headers & `U1`, ⌀2.0 mm / 0.9 mm on R, LED, C1 |

Note on module footprint naming: the current schematic (`SCH_ESP32_WeatherStation_2026-11-11.json`)
and EasyEDA PCB both keep the 30-pin **DOIT ESP32 DevKit V1** pinout and
`ESP32-DEVKIT-V1-30PIN_DZ` footprint (**25.40 mm / 1.0"** row spacing, ~51 × 28 mm
PCB body) rather than the narrower `COMM-TH_30P-P2.54_ESP32-C3-32S-KIT`
footprint (22.86 mm / 0.9" spacing) that came from the original seed schematic.

What the generator checks before it writes the file (`pcb_easyeda_check.txt`):

```
pad clearance  : OK (>= 0.30 mm)
silkscreen     : OK - no text or line on a pad, no text collisions
connectivity   : OK - board pads match the schematic netlist exactly
```

i.e. all **19 nets / 56 wired pads** land on the right pads, and the 13 spare
GPIO (D15, D2, D4, D5, RX0, TX0, D23, D12, D35, D34, VN, VP, EN) are left free
on purpose. `pcb_preview.png` shows the ratsnest: about **609 mm** of track to
route — `J_BTN1..4` sit cleanly along the top edge, `J_SENSOR`, `J_RTC`, and
`J_LCD` along the bottom edge right next to `U1`'s matching pins, and `J_PWR`,
`C1`, `BZ1`, `R1..R3`, and `LED1..LED3` fill the right half of the board.

If your module's silkscreen has `VIN`/`3V3` at the other end, rebuild with
`python3 tools/build_easyeda_pcb.py --mirror-esp32`: that writes
`..._pcb_mirrored.json` with the module rotated 180°, so the two socket rows swap
exactly like turning the real board around. Use that file instead.

Rebuild:

```bash
python3 tools/build_easyeda_pcb.py && python3 tools/build_pcb_preview.py
```

## 6. Alternative: 50 × 100 mm single sided, for ЛУТ (toner transfer)

Generated by `tools/build_pcb.py` (deterministic — same input, same artwork).

```bash
pip install --break-system-packages pillow shapely reportlab
python3 tools/build_pcb.py          # add --mirror-esp32 if your module is flipped
```

### Does the ESP32 fit on 50 × 100 mm?

Yes — but only in one orientation. The DOIT ESP32 DevKit V1 body is
**51.45 × 28.33 mm**, so its long axis must run along the 100 mm side
(51.45 > 50). It sits flush with one short edge, which leaves roughly
48.5 mm × 50 mm — about half the board — for everything else.

| | value |
|---|---|
| board | 50 × 100 mm, origin bottom-left, antenna at the top (`y = 100`), USB at the bottom (`y = 48.55`) |
| ESP32 body | x 10.835…39.165, y 48.55…100 |
| header rows | x = 12.3 / 37.7 (25.4 mm apart), 2.54 mm pitch, pins y 51.94…87.5 |
| trace width | 0.5 mm |
| clearance | 0.3 mm (copper-to-copper, and pour-to-copper) |
| pads | ⌀1.8 mm on 2.54 mm pitch parts, ⌀2.0 mm on resistors / LEDs / C1 |
| drills | 1.0 mm headers, 0.9 mm resistors / LEDs, 3.2 mm mounting |

### What is routed

* **18 signal nets are routed as real traces** — 23 trace segments, 1010 mm of
  copper in total. Nothing is left unrouted. `C1` sits on the `+5V`/`GND` pads
  next to `J_PWR`.
* **GND is a copper pour.** A single-sided pour always gets cut into islands by
  the signal traces, so the generator floods it, finds the islands, and wires
  the ones that stray with **4 insulated jumpers on the component side**. Those
  jumpers are drawn as dashed red wires on `pcb_top_overlay.*` and listed in
  `pcb_report.txt`.
* The whole board is checked before it is written: pad-to-pad clearance, and a
  connectivity test that unions the pads, traces, pour islands and jumpers of
  every net and asserts each one comes out as a **single piece of copper**.
  `connectivity: OK - all 19 nets connected`.

The pour covers most of the board, which is good for ЛУТ: far less copper to
dissolve, so it etches faster and more evenly.

### Files

| file | what it is |
|---|---|
| `lut_bottom_mirrored.pdf` | **print this** — bottom copper, mirrored, exactly 1:1 |
| `lut_bottom_mirrored.png` | same thing, 600 dpi, for image editors |
| `lut_bottom_mirrored.svg` | vector source of the above |
| `pcb_top_overlay.pdf` / `.svg` | component placement, pin names, jumper wires — 1:1, **not** mirrored |
| `gerber/bottom_copper.gbl` | Gerber bottom copper (for a fab) |
| `gerber/board_outline.gm1` | Gerber board outline |
| `gerber/drill.drl` | Excellon drill file |
| `pcb_report.txt` | DRC, connectivity, jumper list, net → pads |

### Before you etch — read this

1. **Check the ESP32 row order against your actual module.** Unlike the
   EasyEDA board in section 5 (where the USB end is at the top), the ЛУТ
   generator places the module the other way round (antenna at the top, USB
   end at `y = 48.55`): `EN, VP, VN, IO34, IO35, IO32, IO33, IO25, IO26, IO27,
   IO14, IO12, IO13, GND, VIN` down the left row and `IO23, IO22, TX0, RX0,
   IO21, IO19, IO18, IO5, TX2, RX2, IO4, IO2, IO15, GND, 3V3` down the right
   one (every pin name is printed on `pcb_top_overlay.pdf`). Check one or two
   pins before soldering. This is the one thing that will scrap the board if it
   is wrong.
2. **Mount the ESP32 on female header sockets**, not soldered flush. Several
   traces pass under the module body; sockets give the clearance they need.
3. Print `lut_bottom_mirrored.pdf` with **"Actual size"**, never "Fit to page",
   and check the 50 mm / 100 mm scale bars print true before ironing.
4. The `+5V` net and `GND` are the two that carry real current (the ESP32 can
   draw ~500 mA peak on transmit) — do not let the etch undercut them.
