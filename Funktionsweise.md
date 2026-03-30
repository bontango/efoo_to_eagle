# Funktionsweise efoo_to_eagle.py

## Uebersicht

Das Skript konvertiert EasyEDA-Bauteildaten in das Eagle-Library-XML-Format (.lbr).
Es verarbeitet zwei Eingabeformate und erzeugt eine einzige .lbr-Datei, die auch mehrere Bauteile enthalten kann.

```
.efoo  ──► nur Package (Footprint)
.elibz ──► Package + Symbol + DeviceSet (komplett)
```

---

## Eingabeformate

### .efoo (Footprint)

Textdatei im JSON-Lines-Format: jede Zeile ist ein JSON-Array, `[0]` bestimmt den Typ.

Koordinaten in **Mils** (1 mil = 0.0254 mm), Y-Achse invertiert gegenueber Eagle.

Relevante Elementtypen:

| Typ  | Aufbau | Beschreibung |
|------|--------|-------------|
| PAD  | `["PAD", id, 0, net, layer, pin_nr, x, y, rotation, [drill_shape, w, h], [pad_shape, w, h, ...], ...]` | Through-Hole oder SMD Pad. Wenn `drill_info` (Index 9) = `null` → SMD. |
| POLY | `["POLY", id, 0, net, layer, width, path_data, closed]` | Linienzuege. `path_data` ist Array mit Koordinatenpaaren, getrennt durch `"L"` (Linie) oder `"ARC"` (Bogen). Sonderfall: `["CIRCLE", cx, cy, r]`. |
| FILL | `["FILL", id, 0, net, layer, width, 0, [[shape_data]], 0]` | Gefuellte Flaechen. `shape_data` entweder Polygon (Koordinaten mit `"L"`) oder `["CIRCLE", cx, cy, r]`. |
| ATTR | `["ATTR", id, 0, "", layer, null, null, key, value, ...]` | Attribute. `key` = `"Designator"` → `>NAME`, `"Footprint"` → `>VALUE`. |

### .elibz (Bauteilbibliothek)

ZIP-Archiv mit folgender Struktur:

```
MeinBauteil.elibz (ZIP)
├── device.json                          Metadaten + Verknuepfungen
├── SYMBOL/{uuid}.esym                   Schaltplansymbol
└── FOOTPRINT/{uuid}.efoo                Footprint (wie oben)
```

**device.json** enthaelt:
- `devices` → Bauteil-Metadaten, Description, Attribute
- `devices[id].symbol.uuid` → verweist auf die .esym-Datei
- `devices[id].footprint.uuid` → verweist auf die .efoo-Datei
- `devices[id].symbol.display_title` → Symbolname
- `devices[id].footprint.display_title` → Footprintname

### .esym (Schaltplansymbol)

JSON-Lines-Format wie .efoo, aber fuer Symbole. Koordinaten in **10mil-Einheiten** (1 Einheit = 0.254 mm).

| Typ    | Aufbau | Beschreibung |
|--------|--------|-------------|
| PIN    | `["PIN", id, ?, ?, x, y, length, rotation, ...]` | Anschlusspin. Position, Laenge und Richtung. |
| RECT   | `["RECT", id, x1, y1, x2, y2, ...]` | Bauteilrahmen (Rechteck). |
| POLY   | `["POLY", id, [x1, y1, x2, y2, ...], ...]` | Linienzuege (z.B. 7-Segment-Grafik). Koordinaten paarweise. |
| CIRCLE | `["CIRCLE", id, cx, cy, radius, ...]` | Kreis (z.B. Dezimalpunkt). |
| TEXT   | `["TEXT", id, x, y, rotation, content, style]` | Textlabel (z.B. Segmentbezeichnungen). |
| ATTR   | `["ATTR", id, parent_ref, key, value, ...]` | Attribute. Bei Pins: `parent_ref` = Pin-ID, `key` = `"NAME"` oder `"NUMBER"`. |

Pin-Name und Pin-Nummer werden ueber ATTR-Eintraege zugeordnet:
```
["PIN", "e4", ...]                          ← Pin-Element
["ATTR", "e5", "e4", "NAME", "E", ...]     ← Pin heisst "E"
["ATTR", "e6", "e4", "NUMBER", "1", ...]   ← Pin-Nummer 1
```

---

## Ausgabeformat: Eagle .lbr (XML)

```xml
<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE eagle SYSTEM "eagle.dtd">
<eagle version="7.7.0">
  <drawing>
    <settings/>
    <grid/>
    <layers>...</layers>
    <library>
      <packages>
        <package name="...">          ← aus .efoo
          <pad .../>                  ← Through-Hole Pad
          <smd .../>                  ← SMD Pad
          <wire .../>                 ← Linie (aus POLY)
          <circle .../>              ← Kreis (aus POLY/FILL)
          <polygon><vertex .../></polygon>  ← Polygon (aus FILL)
          <text>NAME/VALUE</text>    ← aus ATTR
        </package>
      </packages>
      <symbols>                       ← nur bei .elibz
        <symbol name="...">          ← aus .esym
          <wire .../>                ← Rahmen (RECT) + Grafik (POLY)
          <circle .../>              ← aus CIRCLE
          <text .../>                ← Labels (TEXT) + >NAME/>VALUE
          <pin name="..." .../>      ← aus PIN + ATTR
        </symbol>
      </symbols>
      <devicesets>                    ← nur bei .elibz
        <deviceset name="...">
          <description>...</description>
          <gates>
            <gate name="G$1" symbol="..." />
          </gates>
          <devices>
            <device name="" package="...">
              <connects>
                <connect gate="G$1" pin="..." pad="..." />
              </connects>
              <technologies>
                <technology name="" />
              </technologies>
            </device>
          </devices>
        </deviceset>
      </devicesets>
    </library>
  </drawing>
</eagle>
```

---

## Konvertierungsregeln

### Einheiten

| Quelle | Formel | Beispiel |
|--------|--------|----------|
| .efoo (Mils) | `mm = wert * 0.0254` | 31.496 mil → 0.8 mm |
| .esym (10mil) | `mm = wert * 0.254` | 20 → 5.08 mm |

Y-Achse wird bei beiden invertiert: `eagle_y = -easyeda_y`

### Layer-Zuordnung (Footprint)

| EasyEDA | Eagle | Name |
|---------|-------|------|
| 1       | 1     | Top (Kupfer) |
| 2       | 16    | Bottom |
| 3       | 21    | tPlace (Silkscreen) |
| 4       | 22    | bPlace |
| 5       | 29    | tStop (Loetmaske) |
| 6       | 30    | bStop |
| 7       | 31    | tCream (Paste) |
| 8       | 32    | bCream |
| 11      | 20    | Dimension |
| 12      | 17    | Pads (Multi) |
| 13      | 51    | tDocu |
| 48      | 51    | tDocu (Component Shape) |
| 49      | 25    | tNames |
| 50      | 51    | tDocu (Pin Soldering) |

### Pad-Konvertierung

- **Through-Hole** (drill_info vorhanden): `<pad>` mit drill, diameter, shape
  - Shape: RECT→square, ELLIPSE→round, OVAL→long
- **SMD** (drill_info = null): `<smd>` mit dx, dy, layer
  - ELLIPSE/OVAL: roundness="100"

### Symbol-Elemente (Layer 94/95/96)

| .esym Element | Eagle Element | Layer |
|---------------|---------------|-------|
| RECT          | 4x `<wire>` (Rahmen) | 94 (Symbols) |
| POLY          | `<wire>` (Linienzuege) | 94 |
| CIRCLE        | `<circle>` | 94 |
| TEXT          | `<text>` (Labels) | 94 |
| PIN           | `<pin>` mit name, direction="pas" | - |
| (automatisch) | `<text>>NAME</text>` | 95 (Names) |
| (automatisch) | `<text>>VALUE</text>` | 96 (Values) |

Pin-Laenge wird aus dem .esym length-Feld abgeleitet:
- ≤5 → point, ≤10 → short, ≤20 → middle, >20 → long

### DeviceSet

Verbindet Symbol-Pins mit Footprint-Pads ueber Pin-Nummer:
```
Pin "E" (NUMBER=1) ←→ Pad "1"
```

---

## Programmablauf

```
main()
  ├── Glob-Expansion der Eingabedateien (fuer Windows-Kompatibilitaet)
  ├── Pro Datei:
  │   ├── .elibz: parse_elibz() → parse_efoo_text() + parse_esym()
  │   │           → build_symbol() + build_deviceset()
  │   └── .efoo:  parse_efoo()
  ├── build_lbr(components)
  │   ├── XML-Grundgeruest (eagle/drawing/settings/grid/layers)
  │   ├── add_package() pro Bauteil  → <packages>
  │   ├── Symbole sammeln            → <symbols>
  │   └── DeviceSets sammeln         → <devicesets>
  └── write_lbr()
      ├── ET.indent() fuer lesbare Formatierung
      ├── XML-Serialisierung
      └── DOCTYPE manuell einfuegen
```

### Kernfunktionen

| Funktion | Aufgabe |
|----------|---------|
| `parse_lines(text)` | JSON-Lines Text in Liste von Arrays parsen |
| `parse_efoo(path)` / `parse_efoo_text(text)` | .efoo in {PAD, POLY, FILL, ATTR} gruppieren |
| `parse_esym(text)` | .esym parsen + Pin-Mapping (Name/Nummer) aufbauen |
| `parse_elibz(path)` | ZIP entpacken, device.json + .esym + .efoo lesen |
| `convert_pad(pad, el)` | PAD → `<pad>` oder `<smd>` |
| `convert_poly(poly, el)` | POLY → `<wire>` / `<circle>` (inkl. ARC-Boegen) |
| `convert_fill(fill, el)` | FILL → `<polygon>` / `<circle>` |
| `convert_attrs(attrs, el)` | ATTR → `<text>>NAME</text>` / `<text>>VALUE</text>` |
| `build_symbol(esym, pins, name)` | .esym-Elemente → Eagle `<symbol>` |
| `build_deviceset(sym, fp, pins, desc)` | Symbol↔Package-Verknuepfung mit Pin-Zuordnung |
| `add_package(el, elements, name)` | Footprint-Elemente in `<package>` einfuegen |
| `build_lbr(components)` | Alle Bauteile in eine Eagle-XML-Struktur zusammenfuehren |
| `write_lbr(root, path)` | XML mit DOCTYPE und Einrueckung in Datei schreiben |

### Hilfsfunktionen

| Funktion | Aufgabe |
|----------|---------|
| `mils_to_mm(v)` | Mils → mm (Faktor 0.0254), 4 Dezimalstellen |
| `sym_to_mm(v)` | 10mil-Einheiten → mm (Faktor 0.254), 4 Dezimalstellen |
| `fmt(v)` | Float formatieren fuer XML (Nullen am Ende entfernen) |
| `map_layer(layer)` | EasyEDA-Layer → Eagle-Layer (Fallback: 51/tDocu) |
