#!/usr/bin/env python3

import json
from pathlib import Path


def prefix_name(name):
    l = len(name)
    if l == 1:
        return f"1/{name}"
    elif l == 2:
        return f"2/{name}"
    elif l == 3:
        return f"3/{name[0]}/{name}"
    else:
        return f"{name[:2]}/{name[2:4]}/{name}"


crates = json.load(open("crate-information.json"))
for crate in crates:
    name = crate["name"]
    version = crate["version"]
    data = Path(f"crates.io-index/{prefix_name(name)}")

    new_data = []
    for line in data.read_text().splitlines():
        v = json.loads(line)
        if v["vers"] == version:
            new_data.append(line)

    f = Path("crates.io-index-top100") / prefix_name(name)
    f.parent.mkdir(exist_ok=True, parents=True)
    f.write_text("\n".join(new_data))
