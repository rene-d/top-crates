#!/usr/bin/env python3

import requests
import toml
import json
from pathlib import Path
from collections import defaultdict
import semver
import re
import sys
import subprocess


def semver_match(pattern, version):

    v = semver.VersionInfo.parse(version)

    def expr(pattern):

        pattern = pattern.strip()

        try:
            if pattern == "*":
                return True

            if pattern[0] == "=":
                p = pattern[1:].lstrip()
                assert p[0].isdigit() and p.find("*") == -1
                return p == version

            if pattern[0:2] == ">=":
                p = pattern[2:].lstrip()
                assert p[0].isdigit() and p.find("*") == -1
                if re.match(r"^\d+$", p):
                    p += ".0.0"
                elif re.match(r"^\d+\.\d+$", p):
                    p += ".0"
                return v.compare(p) >= 0

            if pattern[0:2] == "<=":
                p = pattern[2:].lstrip()
                assert p[0].isdigit() and p.find("*") == -1
                if re.match(r"^\d+$", p):
                    p += ".9999999.9999999"
                elif re.match(r"^\d+\.\d+$", p):
                    p += ".9999999"
                return v.compare(p) <= 0

            if pattern[0:1] == ">":
                p = pattern[1:].lstrip()
                assert p[0].isdigit() and p.find("*") == -1
                if re.match(r"^\d+$", p):
                    p += ".0.0"
                elif re.match(r"^\d+\.\d+$", p):
                    p += ".0"
                return v.compare(p) > 0

            if pattern[0:1] == "<":
                p = pattern[1:].lstrip()
                assert p[0].isdigit() and p.find("*") == -1
                if re.match(r"^\d+$", p):
                    p += ".9999999.9999999"
                elif re.match(r"^\d+\.\d+$", p):
                    p += ".9999999"
                return v.compare(p) < 0

            if pattern[0] == "^":
                p = pattern[1:].lstrip()
                assert p[0].isdigit() and p.find("*") == -1
                a = p.split(".")
                b = version.split(".")
                return a == b[: len(a)]

            if pattern[0] == "~":
                p = pattern[1:].lstrip()
                assert p[0].isdigit() and p.find("*") == -1
                a = p.split(".")
                b = version.split(".")
                return a == b[: len(a)]

            assert pattern[0].isdigit()

            if pattern.find("*") != -1:
                p = re.escape(pattern)
                p = p.replace(r"\*", r".*")
                p = "^" + p + "$"
                return re.match(p, version) is not None

            return pattern == version

        except Exception as e:
            print()
            print(f'ERROR semver_match("{pattern}", "{version}")')
            print()
            raise e

    return all(expr(p) for p in pattern.split(","))


def find_matching_version(pattern, versions):
    try:
        m = None
        last = None
        for v, item in versions.items():
            last = item
            if semver_match(pattern, v):
                w = semver.VersionInfo.parse(v)
                if m is None or w.compare(m[0]) > 0:
                    m = (w, item)

        if not m:
            # fallback
            # print(pattern, list(k["vers"] for k in versions.values()))
            # assert False
            m = (None, last)
        return m[1]

    except Exception as e:
        print()
        print(f'ERROR find_matching_version("{pattern}", {versions.keys()})')
        print()
        raise e


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


class TopCrates:
    def __init__(self):
        self.verbose = False
        self.crates = defaultdict(set)

        d = toml.load("crate-modifications.toml")
        self.exclusions = [re.compile("^" + re.escape(k).replace(r"\*", r".*") + "$") for k in d["exclusions"]]

    def load(self, filename):
        data = json.load(open(filename))
        for k, v in data.items():
            for version in v:
                self.add(k, version)

    def save(self, filename):
        data = dict((k, list(v)) for k, v in self.crates.items())
        json.dump(data, open(filename, "w"), indent=2)

    def add(self, name, version="latest"):
        if any(e.match(name) for e in self.exclusions):
            return
        self.crates[name].add(version)

    def download(self):
        def get_top(pages, count, category):
            if category:
                category = f"&category={category}"

            for page in range(1, pages + 1):
                url = f"https://crates.io/api/v1/crates?page={page}&per_page={count}&sort=downloads{category}"
                r = requests.get(url).json()

                for crate in r["crates"]:
                    if crate["max_stable_version"]:
                        self.add(crate["name"], crate["max_stable_version"])
                    self.add(crate["name"], crate["max_version"])

        get_top(5, 100, "")
        get_top(1, 100, "network-programming")
        get_top(1, 50, "filesystem")
        get_top(1, 50, "web-programming")
        get_top(1, 50, "mathematics")
        get_top(1, 50, "science")
        get_top(1, 50, "data-structures")
        get_top(1, 50, "asynchronous")
        get_top(1, 50, "api-bindings")
        get_top(1, 50, "command-line-utilities")
        get_top(1, 50, "embedded")

    def cookbook(self):
        r = requests.get("https://raw.githubusercontent.com/rust-lang-nursery/rust-cookbook/master/Cargo.toml")
        d = toml.loads(r.text)
        for name in d["dependencies"].keys():
            self.add(name)

    def curated(self):
        d = toml.load("crate-modifications.toml")
        for k in d["additions"]:
            self.add(k)
        for k in d["commands"]:
            self.add(k)

    def resolve_deps(self):

        print(f"Analyzing {len(self.crates)} crates")

        seen = set()
        n = 0
        while len(self.crates) > 0:

            n += 1
            if n > 10000:
                break

            crate, versions = self.crates.popitem()

            try:
                if self.verbose:
                    print(f"{n:03d} {crate} {sorted(versions)}")
            except:
                print(f"{n:03d} {crate} {versions}")
                raise
            if len(versions) == 0:
                continue

            info_file = Path("crates.io-index") / prefix_name(crate)
            if not info_file.is_file():
                continue

            info = {}
            lines = info_file.read_text().splitlines()
            latest = None
            for line in lines:
                data = json.loads(line)
                latest = data["vers"]
                info[latest] = data

            if latest and "latest" in versions:
                versions.remove("latest")
                versions.add(latest)

            for vers in versions:

                k = find_matching_version(vers, info)

                slug = (crate, k["vers"])
                if slug in seen:
                    if self.verbose:
                        print(f"    seen {crate} {k['vers']}")
                    continue
                seen.add(slug)

                if self.verbose:
                    print(f"    deps of {crate} {k['vers']}")

                for dep in k["deps"]:
                    name, req = dep["name"], dep["req"]

                    if self.verbose:
                        print(f"      found: {name} {req}  {dep['kind']} {dep['optional'] and 'optional' or ''}")

                    if dep["kind"] == "dev":
                        continue

                    if dep["optional"] == True:
                        continue

                    assert dep["kind"] in ["normal", "build"]

                    if name not in seen:
                        self.add(name, req)
                        if self.verbose:
                            print("      adding", name, req)
                    else:
                        assert False

            if self.verbose:
                print()

            self.seen = seen

    def make_git_index(self):

        selected_crates = dict()
        for k, v in self.seen:
            selected_crates[k] = list()
        for k, v in self.seen:
            selected_crates[k].append(v)

        print(f"Got {len(selected_crates)} crates and {len(self.seen)} versions")

        json.dump(selected_crates, open("selected_crates.json", "w"), indent=2)

        for name, versions in selected_crates.items():

            data = Path(f"crates.io-index/{prefix_name(name)}")

            if any(e.match(name) for e in self.exclusions):
                print(f"excluded: {name} {versions}")
                if data.exists():
                    data.unlink()
                continue

            versions = set(versions)
            new_data = []
            for line in data.read_text().splitlines():
                v = json.loads(line)
                if v["vers"] in versions:
                    new_data.append(line)

            f = Path("top-crates-index") / prefix_name(name)
            f.parent.mkdir(exist_ok=True, parents=True)
            new_data.append("")
            f.write_text("\n".join(new_data))

        subprocess.run(["git", "status", "-s"], cwd="top-crates-index")


def main():
    a = TopCrates()

    if Path("crates.json").is_file() == False or (len(sys.argv) > 1 and sys.argv[1] == "download"):
        a.download()
        a.cookbook()
        a.curated()
        a.save("crates.json")

    else:
        a.load("crates.json")

    a.resolve_deps()
    a.make_git_index()


if __name__ == "__main__":
    main()
