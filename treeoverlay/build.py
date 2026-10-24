"""Read a build's passive tree(s) from the formats players share.

Supported inputs:
  * Path of Building export code (the long base64 string)
  * pobb.in / pastebin.com links to such a code
  * pathofexile.com/passive-skill-tree/... URLs
  * Path of Building .xml build files
"""
import base64
import re
import struct
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Spec:
    title: str
    class_id: int
    nodes: list
    tree_version: str = ""
    masteries: dict = field(default_factory=dict)  # mastery node -> effect id
    ascend_id: int = 0  # PoB's ascendClassId: 1-based index into the class's ascendancies, 0 = none


def _b64decode(text):
    text = text.strip().replace("-", "+").replace("_", "/")
    text += "=" * (-len(text) % 4)
    return base64.b64decode(text)


def specs_from_xml(xml_text):
    root = ET.fromstring(xml_text)
    tree = root.find("Tree")
    if tree is None:
        raise ValueError("build has no <Tree> section")
    specs = []
    for i, spec in enumerate(tree.findall("Spec"), 1):
        nodes = [int(n) for n in (spec.get("nodes") or "").split(",") if n.strip()]
        masteries = {int(a): int(b) for a, b in re.findall(r"\{(\d+),(\d+)\}", spec.get("masteryEffects") or "")}
        if not nodes:
            url = (spec.findtext("URL") or "").strip()
            if url:
                specs.append(spec_from_tree_url(url, spec.get("title") or f"Tree {i}"))
                continue
        specs.append(Spec(
            title=spec.get("title") or f"Tree {i}",
            class_id=int(spec.get("classId") or 0),
            nodes=nodes,
            ascend_id=int(spec.get("ascendClassId") or 0),
            tree_version=spec.get("treeVersion") or "",
            masteries=masteries,
        ))
    active = int(tree.get("activeSpec") or 1) - 1
    return specs, max(0, min(active, len(specs) - 1))


def spec_from_tree_url(url, title="Tree URL"):
    m = re.search(r"passive-skill-tree/(?:[0-9_.]+/)?([A-Za-z0-9_\-+/=]+)", url)
    if not m:
        raise ValueError("not a passive-skill-tree URL")
    data = _b64decode(m.group(1))
    version = struct.unpack(">I", data[:4])[0]
    class_id = data[4]
    ascend_id = data[5] & 0x3   # low bits: ascendancy; high bits: bloodline
    if version <= 3:
        raise ValueError(f"tree URL version {version} is too old")
    if version == 4:
        # version, class, ascendancy, fullscreen flag, then uint16 nodes to the end
        nodes = list(struct.unpack(f">{(len(data) - 7) // 2}H", data[7:7 + (len(data) - 7) // 2 * 2]))
        return Spec(title, class_id, nodes, ascend_id=ascend_id)
    pos = 6
    count = data[pos]; pos += 1
    nodes = list(struct.unpack(f">{count}H", data[pos:pos + 2 * count])); pos += 2 * count
    masteries = {}
    if pos < len(data):
        count = data[pos]; pos += 1
        nodes += struct.unpack(f">{count}H", data[pos:pos + 2 * count]); pos += 2 * count
    if version >= 6 and pos < len(data):
        count = data[pos]; pos += 1
        for _ in range(count):
            effect, node = struct.unpack(">HH", data[pos:pos + 4]); pos += 4
            masteries[node] = effect
    return Spec(title, class_id, nodes, masteries=masteries, ascend_id=ascend_id)


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PoE-TreeOverlay/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", "replace")


def load(text):
    """Returns (specs, active_index) for whatever the user pasted or a file path."""
    text = text.strip().strip('"')
    if not text:
        raise ValueError("nothing to load")
    if "passive-skill-tree/" in text:
        return [spec_from_tree_url(text)], 0
    m = re.match(r"https?://(?:www\.)?pobb\.in/([\w-]+)", text)
    if m:
        text = _fetch(f"https://pobb.in/{m.group(1)}/raw").strip()
    m = re.match(r"https?://(?:www\.)?pastebin\.com/(?:raw/)?(\w+)", text)
    if m:
        text = _fetch(f"https://pastebin.com/raw/{m.group(1)}").strip()
    if text.lstrip().startswith("<"):
        return specs_from_xml(text)
    if len(text) < 260 and Path(text).is_file():
        return specs_from_xml(Path(text).read_text(encoding="utf-8"))
    try:
        xml_text = zlib.decompress(_b64decode(text)).decode("utf-8")
    except Exception as exc:
        raise ValueError("not a Path of Building code, tree URL or build file") from exc
    return specs_from_xml(xml_text)
