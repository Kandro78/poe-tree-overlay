"""Extract the cluster jewel orbit offsets from Path of Building's data
(Data/ClusterJewels.lua, MIT licence, (c) the PoB Community contributors) into
treeoverlay/cluster_offsets.json.

    python tools/extract_cluster_offsets.py [path to Path of Building Community]
"""
import json
import os
import re
import sys
from pathlib import Path

pob = Path(sys.argv[1] if len(sys.argv) > 1 else os.path.expandvars(r"%APPDATA%\Path of Building Community"))
text = (pob / "Data" / "ClusterJewels.lua").read_text(encoding="utf-8")
block = text[text.index("orbitOffsets = {"):]
offsets = {}
for proxy, body in re.findall(r"\[(\d+)\] = \{([^}]*)\}", block):
    offsets[proxy] = {k: int(v) for k, v in re.findall(r"\[(\d)\] = (\d+)", body)}
out = Path(__file__).resolve().parent.parent / "treeoverlay" / "cluster_offsets.json"
out.write_text(json.dumps(offsets, indent=1, sort_keys=True))
print(f"{len(offsets)} proxy groups -> {out}")
