# efoo_to_eagle

Konvertiert EasyEDA/JLCPCB Bauteildateien in das Eagle-Library-Format (`.lbr` XML), um sie z.B. in Target 3001 importieren zu können.

## Unterstützte Eingabeformate

### `.efoo` – Nur Footprint
Erzeugt eine Eagle-Library mit dem PCB-Footprint (Package).

### `.elibz` – Komplette Bauteilbibliothek
Erzeugt eine Eagle-Library mit:
- **Package** (Footprint/Landemuster, Through-Hole und SMD)
- **Symbol** (Schaltplansymbol mit Pins, Rahmen, Grafik)
- **DeviceSet** (Verknüpfung Symbol ↔ Package mit Pin-Zuordnung)

## Voraussetzungen

Python 3 (keine externen Pakete nötig).

## Benutzung

```bash
# Nur Footprint aus .efoo
python efoo_to_eagle.py MeinBauteil.efoo

# Komplettes Bauteil aus .elibz (Footprint + Symbol + Device)
python efoo_to_eagle.py MeineBibliothek.elibz

# Mehrere Dateien in eine gemeinsame Library
python efoo_to_eagle.py Bauteil1.elibz Bauteil2.elibz Bauteil3.elibz -o meine_lib.lbr

# Mix aus .efoo und .elibz
python efoo_to_eagle.py Bauteil.elibz Footprint.efoo -o combined.lbr

# Ausgabedatei und Name explizit angeben (nur bei einzelner .efoo)
python efoo_to_eagle.py MeinBauteil.efoo -o ausgabe.lbr -n CustomName
```

| Parameter | Beschreibung |
|-----------|-------------|
| `input` | Eine oder mehrere `.efoo`- / `.elibz`-Dateien |
| `-o`, `--output` | Ausgabe-`.lbr`-Datei (Standard: Name der ersten Eingabedatei) |
| `-n`, `--name` | Footprint-Name (nur bei einzelner `.efoo`-Eingabe) |
