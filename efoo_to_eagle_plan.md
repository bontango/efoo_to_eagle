# Plan: EasyEDA .efoo to Eagle .lbr Converter

## Context
Footprints von EasyEDA/JLCPCB sollen in Target 3001 importiert werden. Target 3001 unterstuetzt kein .efoo-Format, aber Eagle .lbr (XML). Ein Python-Skript konvertiert .efoo -> .lbr.

## .efoo Format (analysiert anhand LED-SEG-TH_FJ5161BH.efoo)
- JSON-Lines: jede Zeile ein JSON-Array, `[0]` = Typ-String
- Koordinaten in **Mils** (1 mil = 0.0254 mm)
- Y-Achse invertiert gegenueber Eagle (EasyEDA: Y runter, Eagle: Y hoch) -> negieren
- Relevante Elemente: PAD, POLY, FILL, ATTR

### PAD-Format
```
["PAD", id, 0, net, layer, pin_nr, x, y, rotation, [drill_shape, drill_w, drill_h], [pad_shape, pad_w, pad_h, ...], ...]
```
- Pin 1: pad_shape="RECT" (quadratisch), andere: "ELLIPSE" (rund)
- Beispiel: Drill 31.496 mil = 0.8mm, Pad 47.244 mil = 1.2mm

### POLY-Format (Silk, Umriss)
```
["POLY", id, 0, net, layer, width, [x1,y1,"L",x2,y2,...], closed]
```
- "L" = Linie, "ARC" = Bogen (gefolgt von angle, end_x, end_y)
- Layer 3 = Top Silk, 48 = Component Shape, 13 = Document

### FILL-Format
```
["FILL", id, 0, net, layer, width, 0, [[shape_data]], 0]
```
- Polygon: `[[x1,y1,"L",x2,y2,...]]`
- Kreis: `[["CIRCLE", cx, cy, radius]]`

### ATTR-Format
```
["ATTR", id, 0, "", layer, null, null, "Footprint"|"Designator", value, ...]
```

## Layer-Mapping (EasyEDA -> Eagle)
| EasyEDA | Eagle | Beschreibung |
|---------|-------|-------------|
| 1 (Top) | 1 (Top) | Kupfer oben |
| 2 (Bottom) | 16 (Bottom) | Kupfer unten |
| 3 (Top Silk) | 21 (tPlace) | Silk Screen |
| 4 (Bot Silk) | 22 (bPlace) | Silk unten |
| 5 (Top Solder Mask) | 29 (tStop) | Loetmaske |
| 6 (Bot Solder Mask) | 30 (bStop) | Loetmaske unten |
| 7 (Top Paste) | 31 (tCream) | Paste oben |
| 8 (Bot Paste) | 32 (bCream) | Paste unten |
| 11 (Outline) | 20 (Dimension) | Platinenumriss |
| 12 (Multi) | 17 (Pads) | Pad-Layer |
| 13 (Document) | 51 (tDocu) | Dokumentation |
| 48 (Component Shape) | 51 (tDocu) | Bauteilumriss |
| 49 (Component Marking) | 25 (tNames) | Bauteil-Name |
| 50 (Pin Soldering) | 51 (tDocu) | Pin-Markierungen |

## Einheiten-Konvertierung
- `mils_to_mm(v) = v * 0.0254` (auf 4 Dezimalstellen runden)
- Y-Achse: `eagle_y = -easyeda_y`

## Eagle .lbr XML-Zielstruktur
```xml
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE eagle SYSTEM "eagle.dtd">
<eagle version="7.7.0">
  <drawing>
    <settings>
      <setting alwaysvectorfont="no"/>
    </settings>
    <grid distance="1.27" unitdist="mm" unit="mm"/>
    <layers>
      <layer number="1" name="Top" color="4" fill="1" visible="yes" active="yes"/>
      <layer number="16" name="Bottom" color="1" fill="1" visible="yes" active="yes"/>
      <layer number="17" name="Pads" color="2" fill="1" visible="yes" active="yes"/>
      <layer number="20" name="Dimension" color="15" fill="1" visible="yes" active="yes"/>
      <layer number="21" name="tPlace" color="7" fill="1" visible="yes" active="yes"/>
      <layer number="22" name="bPlace" color="7" fill="1" visible="yes" active="yes"/>
      <layer number="25" name="tNames" color="7" fill="1" visible="yes" active="yes"/>
      <layer number="27" name="tValues" color="7" fill="1" visible="yes" active="yes"/>
      <layer number="29" name="tStop" color="7" fill="3" visible="yes" active="yes"/>
      <layer number="30" name="bStop" color="7" fill="6" visible="yes" active="yes"/>
      <layer number="31" name="tCream" color="7" fill="4" visible="yes" active="yes"/>
      <layer number="32" name="bCream" color="7" fill="5" visible="yes" active="yes"/>
      <layer number="44" name="Drills" color="7" fill="1" visible="no" active="yes"/>
      <layer number="45" name="Holes" color="7" fill="1" visible="no" active="yes"/>
      <layer number="51" name="tDocu" color="7" fill="1" visible="yes" active="yes"/>
      <!-- ... weitere Standard-Layer -->
    </layers>
    <library>
      <packages>
        <package name="FOOTPRINT_NAME">
          <description>Converted from EasyEDA</description>
          <pad name="1" x="..." y="..." drill="0.8" diameter="1.2" shape="square"/>
          <wire x1="..." y1="..." x2="..." y2="..." width="0.3" layer="21"/>
          <polygon width="0.005" layer="51">
            <vertex x="..." y="..."/>
          </polygon>
          <circle x="..." y="..." radius="..." width="0" layer="51"/>
          <text x="0" y="..." size="1.27" layer="25">&gt;NAME</text>
          <text x="0" y="..." size="1.27" layer="27">&gt;VALUE</text>
        </package>
      </packages>
    </library>
  </drawing>
</eagle>
```

## Konvertierungsdetails

### PAD -> `<pad>`
```python
shape_map = {"RECT": "square", "ELLIPSE": "round", "OVAL": "long"}
# <pad name=pin_nr x=mm(x) y=-mm(y) drill=mm(drill_w) diameter=mm(pad_w) shape=... rot=R{rot}/>
```

### POLY -> `<wire>`
- Jeden "L"-Abschnitt als `<wire x1 y1 x2 y2 width layer/>`
- "ARC"-Abschnitte als `<wire ... curve="angle"/>` (Winkel ggf. /10)
- Geschlossene Polys (closed=1): letzten Punkt mit erstem verbinden

### FILL-Polygon -> `<polygon>`
```xml
<polygon width="0.005" layer="51">
  <vertex x="..." y="..."/>
  ...
</polygon>
```

### FILL-Kreis -> `<circle>`
```xml
<circle x="mm(cx)" y="-mm(cy)" radius="mm(r)" width="0" layer="51"/>
```

### ATTR -> `<text>`
- Designator -> `>NAME` auf Layer 25 (tNames)
- Footprint -> `>VALUE` auf Layer 27 (tValues)

## Implementierungsschritte
1. CLI mit argparse (input .efoo, optional -o output, -n name)
2. .efoo einlesen und nach Typ klassifizieren
3. Hilfsfunktionen: mils_to_mm, layer_map, fmt, parse_poly_path
4. PAD-Konverter
5. POLY-Konverter (Linien + Boegen)
6. FILL-Konverter (Polygone + Kreise)
7. ATTR-Konverter (>NAME, >VALUE)
8. XML zusammenbauen mit xml.etree.ElementTree
9. DOCTYPE manuell einfuegen (ElementTree kann das nicht nativ)
10. Test mit FJ5161BH.efoo

## Ausfuehrung
```bash
python efoo_to_eagle.py LED-SEG-TH_FJ5161BH.efoo
# Erzeugt: LED-SEG-TH_FJ5161BH.lbr
```

## Keine externen Abhaengigkeiten
Nur Python stdlib: json, xml.etree.ElementTree, math, argparse, sys, io
