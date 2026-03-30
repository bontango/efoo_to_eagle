#!/usr/bin/env python3
"""Convert EasyEDA .efoo/.elibz files to Eagle .lbr (XML) format."""

import argparse
import glob
import json
import math
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


# --- Helpers ---

def mils_to_mm(v):
    """Convert mils to mm, rounded to 4 decimal places."""
    return round(float(v) * 0.0254, 4)


def fmt(v):
    """Format a float for XML output: strip trailing zeros."""
    return f"{v:.4f}".rstrip("0").rstrip(".")


LAYER_MAP = {
    1: 1,    # Top -> Top
    2: 16,   # Bottom -> Bottom
    3: 21,   # Top Silk -> tPlace
    4: 22,   # Bot Silk -> bPlace
    5: 29,   # Top Solder Mask -> tStop
    6: 30,   # Bot Solder Mask -> bStop
    7: 31,   # Top Paste -> tCream
    8: 32,   # Bot Paste -> bCream
    11: 20,  # Outline -> Dimension
    12: 17,  # Multi -> Pads
    13: 51,  # Document -> tDocu
    48: 51,  # Component Shape -> tDocu
    49: 25,  # Component Marking -> tNames
    50: 51,  # Pin Soldering -> tDocu
}

EAGLE_LAYERS = [
    (1, "Top", 4, 1),
    (16, "Bottom", 1, 1),
    (17, "Pads", 2, 1),
    (18, "Vias", 2, 1),
    (20, "Dimension", 15, 1),
    (21, "tPlace", 7, 1),
    (22, "bPlace", 7, 1),
    (25, "tNames", 7, 1),
    (26, "bNames", 7, 1),
    (27, "tValues", 7, 1),
    (28, "bValues", 7, 1),
    (29, "tStop", 7, 3),
    (30, "bStop", 7, 6),
    (31, "tCream", 7, 4),
    (32, "bCream", 7, 5),
    (44, "Drills", 7, 1),
    (45, "Holes", 7, 1),
    (46, "Milling", 3, 1),
    (51, "tDocu", 7, 1),
    (52, "bDocu", 7, 1),
    (94, "Symbols", 4, 1),
    (95, "Names", 7, 1),
    (96, "Values", 7, 1),
]


def map_layer(easyeda_layer):
    return LAYER_MAP.get(int(easyeda_layer), 51)


def sym_to_mm(v):
    """Convert .esym coordinate units (10mil grid) to mm."""
    return round(float(v) * 0.254, 4)


# --- Parsers ---

def parse_lines(text):
    """Parse JSON-lines text, return rows grouped by type."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def parse_efoo(filepath):
    """Parse .efoo file, return list of typed elements."""
    elements = {"PAD": [], "POLY": [], "FILL": [], "ATTR": []}
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    for row in parse_lines(text):
        typ = row[0] if row else None
        if typ in elements:
            elements[typ].append(row)
    return elements


def parse_efoo_text(text):
    """Parse .efoo text content, return list of typed elements."""
    elements = {"PAD": [], "POLY": [], "FILL": [], "ATTR": []}
    for row in parse_lines(text):
        typ = row[0] if row else None
        if typ in elements:
            elements[typ].append(row)
    return elements


def parse_esym(text):
    """Parse .esym text, return elements and pin mapping."""
    elements = {"PIN": [], "RECT": [], "POLY": [], "CIRCLE": [], "TEXT": [], "ATTR": []}
    for row in parse_lines(text):
        typ = row[0] if row else None
        if typ in elements:
            elements[typ].append(row)

    # Build pin mapping: pin_id -> {name, number, x, y, length, rotation}
    pin_attrs = {}  # pin_id -> {NAME: ..., NUMBER: ...}
    for attr in elements["ATTR"]:
        # ["ATTR", id, parent_ref, key, value, ...]
        parent_ref = attr[2]
        key = attr[3]
        value = attr[4]
        if parent_ref and key in ("NAME", "NUMBER"):
            pin_attrs.setdefault(parent_ref, {})[key] = value

    pins = []
    for pin in elements["PIN"]:
        # ["PIN", id, ?, ?, x, y, length, rotation, ...]
        pin_id = pin[1]
        x = float(pin[4])
        y = float(pin[5])
        length = float(pin[6])
        rotation = float(pin[7])
        attrs = pin_attrs.get(pin_id, {})
        pins.append({
            "id": pin_id,
            "name": attrs.get("NAME", pin_id),
            "number": attrs.get("NUMBER", ""),
            "x": x, "y": y,
            "length": length,
            "rotation": rotation,
        })

    return elements, pins


def parse_elibz(filepath):
    """Parse .elibz ZIP, return device info, symbol data, footprint data."""
    with zipfile.ZipFile(filepath, "r") as z:
        device_json = json.loads(z.read("device.json").decode("utf-8"))

        # Find the first device entry
        device_id = next(iter(device_json["devices"]))
        device = device_json["devices"][device_id]

        sym_uuid = device["symbol"]["uuid"]
        fp_uuid = device["footprint"]["uuid"]

        sym_text = z.read(f"SYMBOL/{sym_uuid}.esym").decode("utf-8")
        fp_text = z.read(f"FOOTPRINT/{fp_uuid}.efoo").decode("utf-8")

    return {
        "device": device,
        "symbol_name": device["symbol"]["display_title"],
        "footprint_name": device["footprint"]["display_title"],
        "symbol_text": sym_text,
        "footprint_text": fp_text,
    }


# --- Converters ---

def convert_pad(pad, package_el):
    """PAD -> <pad> (through-hole) or <smd> (surface mount)."""
    # ["PAD", id, 0, net, layer, pin_nr, x, y, rotation, drill_info, pad_info, ...]
    pin_nr = str(pad[5])
    x = mils_to_mm(pad[6])
    y = -mils_to_mm(pad[7])  # Y inversion
    rotation = float(pad[8])

    drill_info = pad[9]
    pad_info = pad[10]
    pad_shape_str = pad_info[0] if pad_info else "RECT"
    pad_w = mils_to_mm(pad_info[1]) if pad_info else 0
    pad_h = mils_to_mm(pad_info[2]) if pad_info and len(pad_info) > 2 else pad_w

    if drill_info is None:
        # SMD pad
        easyeda_layer = int(pad[4])
        eagle_layer = map_layer(easyeda_layer)
        attribs = {
            "name": pin_nr,
            "x": fmt(x),
            "y": fmt(y),
            "dx": fmt(pad_w),
            "dy": fmt(pad_h),
            "layer": str(eagle_layer),
        }
        if pad_shape_str == "ELLIPSE" or pad_shape_str == "OVAL":
            attribs["roundness"] = "100"
        if rotation and rotation != 0:
            attribs["rot"] = f"R{int(rotation)}"
        ET.SubElement(package_el, "smd", attribs)
    else:
        # Through-hole pad
        drill_w = mils_to_mm(drill_info[1])
        shape_map = {"RECT": "square", "ELLIPSE": "round", "OVAL": "long", "ROUND": "round"}
        shape = shape_map.get(pad_shape_str, "round")

        attribs = {
            "name": pin_nr,
            "x": fmt(x),
            "y": fmt(y),
            "drill": fmt(drill_w),
            "diameter": fmt(pad_w),
            "shape": shape,
        }
        if rotation and rotation != 0:
            attribs["rot"] = f"R{int(rotation)}"
        ET.SubElement(package_el, "pad", attribs)


def convert_poly(poly, package_el):
    """POLY -> <wire> elements."""
    # ["POLY", id, 0, net, layer, width, path_data, closed]
    layer = map_layer(poly[4])
    width = mils_to_mm(poly[5])
    path_data = poly[6]
    # closed flag is at index 7
    closed = poly[7] if len(poly) > 7 else 0

    # Handle CIRCLE shorthand in POLY
    if isinstance(path_data, list) and len(path_data) >= 1 and path_data[0] == "CIRCLE":
        cx = mils_to_mm(path_data[1])
        cy = -mils_to_mm(path_data[2])
        r = mils_to_mm(path_data[3])
        ET.SubElement(package_el, "circle", {
            "x": fmt(cx),
            "y": fmt(cy),
            "radius": fmt(r),
            "width": fmt(width),
            "layer": str(layer),
        })
        return

    if not isinstance(path_data, list):
        return

    # Parse path: sequence of coordinates and commands
    points = []
    arcs = []  # list of (from_idx, angle)
    i = 0
    while i < len(path_data):
        val = path_data[i]
        if val == "L":
            i += 1
            continue
        elif val == "ARC":
            angle = float(path_data[i + 1])
            end_x = float(path_data[i + 2])
            end_y = float(path_data[i + 3])
            # The arc angle might need /10 based on format
            arcs.append((len(points), angle))
            points.append((end_x, end_y))
            i += 4
            continue
        else:
            # Should be a coordinate pair
            try:
                px = float(val)
                py = float(path_data[i + 1])
                points.append((px, py))
                i += 2
            except (ValueError, IndexError):
                i += 1
                continue

    if len(points) < 2:
        return

    # Build arc lookup: arc_from_idx -> angle
    arc_lookup = {idx: angle for idx, angle in arcs}

    # Generate wires between consecutive points
    for j in range(len(points) - 1):
        x1 = mils_to_mm(points[j][0])
        y1 = -mils_to_mm(points[j][1])
        x2 = mils_to_mm(points[j + 1][0])
        y2 = -mils_to_mm(points[j + 1][1])

        attribs = {
            "x1": fmt(x1),
            "y1": fmt(y1),
            "x2": fmt(x2),
            "y2": fmt(y2),
            "width": fmt(width),
            "layer": str(layer),
        }

        if (j + 1) in arc_lookup:
            attribs["curve"] = fmt(arc_lookup[j + 1])

        ET.SubElement(package_el, "wire", attribs)

    # Close polygon if needed
    if closed and len(points) >= 3:
        x1 = mils_to_mm(points[-1][0])
        y1 = -mils_to_mm(points[-1][1])
        x2 = mils_to_mm(points[0][0])
        y2 = -mils_to_mm(points[0][1])
        ET.SubElement(package_el, "wire", {
            "x1": fmt(x1),
            "y1": fmt(y1),
            "x2": fmt(x2),
            "y2": fmt(y2),
            "width": fmt(width),
            "layer": str(layer),
        })


def convert_fill(fill, package_el):
    """FILL -> <polygon> or <circle>."""
    # ["FILL", id, 0, net, layer, width, 0, [[shape_data]], 0]
    layer = map_layer(fill[4])
    shape_data_list = fill[7]

    if not isinstance(shape_data_list, list) or len(shape_data_list) == 0:
        return

    shape_data = shape_data_list[0]
    if not isinstance(shape_data, list) or len(shape_data) == 0:
        return

    # Circle
    if shape_data[0] == "CIRCLE":
        cx = mils_to_mm(shape_data[1])
        cy = -mils_to_mm(shape_data[2])
        r = mils_to_mm(shape_data[3])
        ET.SubElement(package_el, "circle", {
            "x": fmt(cx),
            "y": fmt(cy),
            "radius": fmt(r),
            "width": "0",
            "layer": str(layer),
        })
        return

    # Polygon
    polygon_el = ET.SubElement(package_el, "polygon", {
        "width": "0.005",
        "layer": str(layer),
    })

    i = 0
    while i < len(shape_data):
        val = shape_data[i]
        if val == "L":
            i += 1
            continue
        try:
            px = float(val)
            py = float(shape_data[i + 1])
            ET.SubElement(polygon_el, "vertex", {
                "x": fmt(mils_to_mm(px)),
                "y": fmt(-mils_to_mm(py)),
            })
            i += 2
        except (ValueError, IndexError):
            i += 1


def convert_attrs(attrs, package_el):
    """ATTR -> <text> for >NAME and >VALUE."""
    has_name = False
    has_value = False
    for attr in attrs:
        # ["ATTR", id, 0, "", layer, null, null, key, value, ...]
        key = attr[7]
        if key == "Designator":
            has_name = True
        elif key == "Footprint":
            has_value = True

    if has_name:
        ET.SubElement(package_el, "text", {
            "x": "0",
            "y": fmt(mils_to_mm(400)),
            "size": "1.27",
            "layer": "25",
        }).text = ">NAME"

    if has_value:
        ET.SubElement(package_el, "text", {
            "x": "0",
            "y": fmt(-mils_to_mm(400)),
            "size": "1.27",
            "layer": "27",
        }).text = ">VALUE"


# --- Symbol Converters ---

def build_symbol(esym_elements, pins, symbol_name):
    """Build an Eagle <symbol> element from parsed .esym data."""
    symbol_el = ET.Element("symbol", name=symbol_name)

    # RECT -> 4 wires (component frame) on layer 94 (Symbols)
    for rect in esym_elements["RECT"]:
        # ["RECT", id, x1, y1, x2, y2, ...]
        x1 = sym_to_mm(rect[2])
        y1 = -sym_to_mm(rect[3])
        x2 = sym_to_mm(rect[4])
        y2 = -sym_to_mm(rect[5])
        for wx1, wy1, wx2, wy2 in [
            (x1, y1, x2, y1), (x2, y1, x2, y2),
            (x2, y2, x1, y2), (x1, y2, x1, y1),
        ]:
            ET.SubElement(symbol_el, "wire", {
                "x1": fmt(wx1), "y1": fmt(wy1),
                "x2": fmt(wx2), "y2": fmt(wy2),
                "width": "0.254", "layer": "94",
            })

    # POLY -> wires (segment drawings) on layer 94
    for poly in esym_elements["POLY"]:
        # ["POLY", id, [x1,y1,x2,y2,...], ...]
        coords = poly[2]
        if not isinstance(coords, list) or len(coords) < 4:
            continue
        for i in range(0, len(coords) - 2, 2):
            x1 = sym_to_mm(coords[i])
            y1 = -sym_to_mm(coords[i + 1])
            x2 = sym_to_mm(coords[i + 2])
            y2 = -sym_to_mm(coords[i + 3])
            ET.SubElement(symbol_el, "wire", {
                "x1": fmt(x1), "y1": fmt(y1),
                "x2": fmt(x2), "y2": fmt(y2),
                "width": "0.254", "layer": "94",
            })

    # CIRCLE on layer 94
    for circ in esym_elements["CIRCLE"]:
        # ["CIRCLE", id, cx, cy, radius, ...]
        ET.SubElement(symbol_el, "circle", {
            "x": fmt(sym_to_mm(circ[2])),
            "y": fmt(-sym_to_mm(circ[3])),
            "radius": fmt(sym_to_mm(circ[4])),
            "width": "0.254", "layer": "94",
        })

    # TEXT -> segment labels on layer 94
    for text in esym_elements["TEXT"]:
        # ["TEXT", id, x, y, rotation, content, style]
        ET.SubElement(symbol_el, "text", {
            "x": fmt(sym_to_mm(text[2])),
            "y": fmt(-sym_to_mm(text[3])),
            "size": "1.778", "layer": "94",
        }).text = text[5]

    # >NAME and >VALUE placeholders
    ET.SubElement(symbol_el, "text", {
        "x": fmt(sym_to_mm(-40)), "y": fmt(-sym_to_mm(-33)),
        "size": "1.778", "layer": "95",
    }).text = ">NAME"
    ET.SubElement(symbol_el, "text", {
        "x": fmt(sym_to_mm(-40)), "y": fmt(-sym_to_mm(33)),
        "size": "1.778", "layer": "96",
    }).text = ">VALUE"

    # PINs
    for pin in pins:
        rot = pin["rotation"]
        length_val = pin["length"]
        if length_val <= 5:
            length_str = "point"
        elif length_val <= 10:
            length_str = "short"
        elif length_val <= 20:
            length_str = "middle"
        else:
            length_str = "long"

        attribs = {
            "name": pin["name"],
            "x": fmt(sym_to_mm(pin["x"])),
            "y": fmt(-sym_to_mm(pin["y"])),
            "length": length_str,
            "direction": "pas",
        }
        if rot and rot != 0:
            attribs["rot"] = f"R{int(rot)}"

        ET.SubElement(symbol_el, "pin", attribs)

    return symbol_el


def build_deviceset(symbol_name, footprint_name, pins, description=""):
    """Build Eagle <devicesets> element linking symbol to package."""
    devicesets_el = ET.Element("devicesets")
    deviceset = ET.SubElement(devicesets_el, "deviceset", name=symbol_name)

    ET.SubElement(deviceset, "description").text = description or f"Converted from EasyEDA"

    gates = ET.SubElement(deviceset, "gates")
    ET.SubElement(gates, "gate", name="G$1", symbol=symbol_name, x="0", y="0")

    devices = ET.SubElement(deviceset, "devices")
    device = ET.SubElement(devices, "device", name="", package=footprint_name)
    connects = ET.SubElement(device, "connects")

    for pin in pins:
        ET.SubElement(connects, "connect", {
            "gate": "G$1",
            "pin": pin["name"],
            "pad": pin["number"],
        })

    technologies = ET.SubElement(device, "technologies")
    ET.SubElement(technologies, "technology", name="")

    return devicesets_el


# --- XML Builder ---

def add_package(packages_el, elements, footprint_name):
    """Add a footprint package to the <packages> element."""
    package = ET.SubElement(packages_el, "package", name=footprint_name)
    ET.SubElement(package, "description").text = "Converted from EasyEDA"

    for pad in elements["PAD"]:
        convert_pad(pad, package)
    for poly in elements["POLY"]:
        convert_poly(poly, package)
    for fill in elements["FILL"]:
        convert_fill(fill, package)
    convert_attrs(elements["ATTR"], package)


def build_lbr(components):
    """Build the Eagle .lbr XML tree from a list of components.

    Each component is a dict with keys:
      - fp_elements, footprint_name (required)
      - symbol_el, devicesets_el (optional, from .elibz)
    """
    eagle = ET.Element("eagle", version="7.7.0")
    drawing = ET.SubElement(eagle, "drawing")

    # Settings
    settings = ET.SubElement(drawing, "settings")
    ET.SubElement(settings, "setting", alwaysvectorfont="no")

    # Grid
    ET.SubElement(drawing, "grid", distance="1.27", unitdist="mm", unit="mm")

    # Layers
    layers_el = ET.SubElement(drawing, "layers")
    for num, name, color, fill in EAGLE_LAYERS:
        ET.SubElement(layers_el, "layer", {
            "number": str(num),
            "name": name,
            "color": str(color),
            "fill": str(fill),
            "visible": "yes",
            "active": "yes",
        })

    library = ET.SubElement(drawing, "library")

    # Packages
    packages_el = ET.SubElement(library, "packages")
    for comp in components:
        add_package(packages_el, comp["fp_elements"], comp["footprint_name"])

    # Symbols
    symbol_els = [c["symbol_el"] for c in components if c.get("symbol_el") is not None]
    if symbol_els:
        symbols_el = ET.SubElement(library, "symbols")
        for s in symbol_els:
            symbols_el.append(s)

    # DeviceSets
    ds_els = [c["devicesets_el"] for c in components if c.get("devicesets_el") is not None]
    if ds_els:
        devicesets_el = ET.SubElement(library, "devicesets")
        for ds in ds_els:
            # ds is a <devicesets> element, append its <deviceset> children
            for child in ds:
                devicesets_el.append(child)

    return eagle


def write_lbr(eagle_root, output_path):
    """Write Eagle XML with DOCTYPE to file."""
    ET.indent(eagle_root, space="  ")
    tree = ET.ElementTree(eagle_root)

    import io
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    xml_str = buf.getvalue().decode("utf-8")

    # Insert DOCTYPE after XML declaration
    lines = xml_str.split("\n", 1)
    if len(lines) == 2:
        xml_str = lines[0] + "\n<!DOCTYPE eagle SYSTEM \"eagle.dtd\">\n" + lines[1]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_str)


# --- Main ---

def process_elibz(input_path):
    """Process a single .elibz file, return component dict."""
    lib_data = parse_elibz(input_path)
    footprint_name = lib_data["footprint_name"]
    symbol_name = lib_data["symbol_name"]

    print(f"  [{symbol_name}]")
    print(f"    Footprint: {footprint_name}")

    fp_elements = parse_efoo_text(lib_data["footprint_text"])
    print(f"    PADs: {len(fp_elements['PAD'])}, POLYs: {len(fp_elements['POLY'])}, "
          f"FILLs: {len(fp_elements['FILL'])}")

    esym_elements, pins = parse_esym(lib_data["symbol_text"])
    print(f"    PINs: {len(pins)}, Symbol POLYs: {len(esym_elements['POLY'])}")

    symbol_el = build_symbol(esym_elements, pins, symbol_name)
    description = lib_data["device"].get("description", "")
    devicesets_el = build_deviceset(symbol_name, footprint_name, pins, description)

    return {
        "fp_elements": fp_elements,
        "footprint_name": footprint_name,
        "symbol_el": symbol_el,
        "devicesets_el": devicesets_el,
    }


def process_efoo(input_path, name_override=None):
    """Process a single .efoo file, return component dict."""
    footprint_name = name_override if name_override else input_path.stem

    print(f"  [{footprint_name}]")

    fp_elements = parse_efoo(input_path)
    print(f"    PADs: {len(fp_elements['PAD'])}, POLYs: {len(fp_elements['POLY'])}, "
          f"FILLs: {len(fp_elements['FILL'])}")

    return {
        "fp_elements": fp_elements,
        "footprint_name": footprint_name,
    }


def main():
    parser = argparse.ArgumentParser(description="Convert EasyEDA .efoo/.elibz to Eagle .lbr")
    parser.add_argument("input", nargs="+", help="Input .efoo or .elibz file(s)")
    parser.add_argument("-o", "--output", help="Output .lbr file (default: derived from first input)")
    parser.add_argument("-n", "--name", help="Footprint name (only for single .efoo input)")
    args = parser.parse_args()

    # Expand glob patterns (Windows doesn't expand *.elibz automatically)
    input_paths = []
    for pattern in args.input:
        expanded = glob.glob(pattern)
        if expanded:
            input_paths.extend(Path(p) for p in sorted(expanded))
        else:
            print(f"Error: No files matching: {pattern}", file=sys.stderr)
            sys.exit(1)

    output_path = Path(args.output) if args.output else input_paths[0].with_suffix(".lbr")

    print(f"Output: {output_path}")
    print(f"Processing {len(input_paths)} file(s)...")

    components = []
    for input_path in input_paths:
        if input_path.suffix.lower() == ".elibz":
            components.append(process_elibz(input_path))
        else:
            name_override = args.name if args.name and len(input_paths) == 1 else None
            components.append(process_efoo(input_path, name_override))

    eagle_root = build_lbr(components)
    write_lbr(eagle_root, output_path)
    print(f"Done! {len(components)} component(s) -> {output_path}")


if __name__ == "__main__":
    main()
