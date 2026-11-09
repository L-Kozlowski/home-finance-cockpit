"""Package the supplied PNG icons and adapt the existing SVG for the dark UI.

No artwork is regenerated: ICO embeds the original PNG bytes, and the UI SVGs only
remove the backgrounds and extra margins from the supplied dark/light wordmarks.
"""

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "home_finance_cockpit" / "ui" / "assets" / "branding"


def build():
    sizes = (16, 32, 64, 128, 256)
    images = [(size, (ASSETS / f"app-icon-{size}.png").read_bytes()) for size in sizes]
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        if data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != (size, size):
            raise ValueError(f"Unexpected icon dimensions: {size}")
        entries.append(
            struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        )
        offset += len(data)
    (ASSETS / "app-icon.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(images))
        + b"".join(entries)
        + b"".join(data for _, data in images)
    )
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    for variant in ("dark", "light"):
        tree = ET.parse(ASSETS / f"wordmark-{variant}.svg")
        root = tree.getroot()
        for child in list(root):
            if child.tag.endswith("}rect") and child.attrib.get("width") == "920":
                root.remove(child)
        root.set("viewBox", "25 35 800 190")
        root.set("width", "1600")
        root.set("height", "380")
        tree.write(ASSETS / f"wordmark-ui-{variant}.svg", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    build()
