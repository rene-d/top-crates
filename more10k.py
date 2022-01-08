#!/usr/bin/env python3

import requests
from pathlib import Path
import tarfile
import io
import csv

# download or read the crates.io dump
db_dump = Path("db-dump.tar.gz")
if not db_dump.exists():
    data = requests.get("https://static.crates.io/db-dump.tar.gz").content
    # db_dump.write_bytes(data)
    db_dump = io.BytesIO(data)
else:
    db_dump = db_dump.open("rb")

# extract crates.csv in memory
crates = None
tar = tarfile.open(fileobj=db_dump, mode="r:gz")
info: tarfile.TarInfo
for info in tar:
    name = Path(info.name)
    if name.name == "crates.csv":
        crates = tar.extractfile(info)
        break

# read the crates from csv file
crates = (crate.decode() for crate in crates)
csv.field_size_limit(1048576)
reader = csv.DictReader(crates, delimiter=",", quotechar='"', doublequote=True)
crates = (row for row in reader)

# own the crates list
crates = list(crates)

prefix = lambda name: str(len(name)) if len(name) < 4 else name[:2] + "/" + name[2:4]

# find lesser downloaded crates
for crate in crates:
    if int(crate["downloads"]) < 10000:
        name = crate["name"]
        # print(f"{prefix(name)}/{name}")

# find most downloaded crates
for crate in crates:
    if int(crate["downloads"]) > 1_000_000:
        name = crate["name"]
        # print(f"{prefix(name)}/{name}")
