#!/usr/bin/env python3

import csv
import sqlite3
from pathlib import Path

csv.field_size_limit(1048576)


def open_db(name, load_data=False):
    reader = csv.DictReader(open(f"data/{name}.csv"), delimiter=",", quotechar='"', doublequote=True)
    print(f"{name}: {reader.fieldnames}")
    if load_data:
        data = dict()
        for row in reader:
            data[row["id"]] = row
        return data
    else:
        return reader


def import_db(conn, data, table):
    cur = conn.cursor()
    columns = ",".join(data.fieldnames)
    placeholders = ":" + ",:".join(data.fieldnames)
    query = f"INSERT INTO {table} (%s) VALUES (%s)" % (columns, placeholders)
    for row in data:
        cur.execute(query, row)
    conn.commit()
    cur.close()


Path("data.db").unlink(missing_ok=True)
conn = sqlite3.connect("data.db")

# Open database
crates = open_db("crates")
versions = open_db("versions")
dependencies = open_db("dependencies")

# Create tables
conn.executescript(Path("data.sql").read_text())

# Import data
import_db(conn, crates, "crates")
import_db(conn, dependencies, "dependencies")
import_db(conn, versions, "versions")

conn.commit()
conn.close()
