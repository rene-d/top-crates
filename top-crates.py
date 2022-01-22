#!/usr/bin/env python3

import multiprocessing
import requests
import tomli
import json
from pathlib import Path
from collections import defaultdict
import re
import subprocess
import argparse
import shutil
import requests
from dateutil.parser import parse as parsedate
import os
from multiprocessing import Pool, get_context
from functools import partial
import multiprocessing


class SemVer:
    # regex from https://github.com/python-semver/python-semver
    _REGEX = re.compile(
        r"""
            ^
            (?P<major>0|[1-9]\d*)
            \.
            (?P<minor>0|[1-9]\d*)
            \.
            (?P<patch>0|[1-9]\d*)
            (?:-(?P<prerelease>
                (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
                (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
            ))?
            (?:\+(?P<build>
                [0-9a-zA-Z-]+
                (?:\.[0-9a-zA-Z-]+)*
            ))?
            $
        """,
        re.VERBOSE,
    )

    def __init__(self, version):
        """Parse a SemVer string."""

        self.raw_version = version

        match = SemVer._REGEX.match(version)
        if match is None:
            raise ValueError(f"{version} is not valid SemVer string")

        parts = match.groups()
        self.parts = (int(parts[0]), int(parts[1]), int(parts[2]), parts[3], parts[4])

        assert str(self) == version

    def __str__(self):
        s = ".".join(map(str, self.parts[:3]))
        if self.parts[3]:
            s += f"-{self.parts[3]}"
        if self.parts[4]:
            s += f"+{self.parts[4]}"
        return s

    def compare(self, other, strict=False):
        """Compare two versions strings."""

        if not isinstance(other, SemVer):
            other = SemVer(other)

        def _cmp(a, b):
            return (a > b) - (a < b)

        def _nat_cmp(a, b):
            def convert(text):
                return int(text) if re.match("^[0-9]+$", text) else text

            def split_key(key):
                return [convert(c) for c in key.split(".")]

            def cmp_prerelease_tag(a, b):
                if isinstance(a, int) and isinstance(b, int):
                    return _cmp(a, b)
                elif isinstance(a, int):
                    return -1
                elif isinstance(b, int):
                    return 1
                else:
                    return _cmp(a, b)

            a, b = a or "", b or ""
            a_parts, b_parts = split_key(a), split_key(b)
            for sub_a, sub_b in zip(a_parts, b_parts):
                cmp_result = cmp_prerelease_tag(sub_a, sub_b)
                if cmp_result != 0:
                    return cmp_result
            else:
                return _cmp(len(a), len(b))

        c = _cmp(self.parts[:3], other.parts[:3])
        if c != 0 or strict:
            return c

        rc1, rc2 = self.parts[3], other.parts[3]

        if not rc1 and not rc2:
            rccmp = c
        elif not rc1:
            rccmp = 1
        elif not rc2:
            rccmp = -1
        else:
            rccmp = _nat_cmp(rc1, rc2)

        return rccmp

    # https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#caret-requirements
    def _caret_requirement(pattern):
        a = pattern[1:].split(".")
        length = len(a)

        min_pattern = f">={pattern[1:]}"
        if length == 1:
            min_pattern += ".0.0"
        elif length == 2:
            min_pattern += ".0"

        if a[0] == "0":
            if length == 1:
                max_pattern = "<1.0.0"
            elif len(a) == 2:
                max_pattern = f"<0.{int(a[1]) + 1}.0"
            else:
                if a[1] == "0":
                    max_pattern = f"<0.{a[1]}.{int(a[2]) + 1}"
                else:
                    max_pattern = f"<0.{int(a[1]) + 1}.0"
        else:
            max_pattern = f"<{int(a[0]) + 1}.0.0"

        # if a[1] == "0":
        #     if length == 1:
        #         max_pattern = "0.*"
        #     elif length == 2:
        #         max_pattern = f"0.{a[1]}.*"
        #     else:
        #         max_pattern = f"0.{a[1]}.{int(a[2])}-*"
        #         assert False, "not implemented"
        # else:
        #     max_pattern = f"{a[0]}.*"

        return min_pattern, max_pattern

    # https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#tilde-requirements
    def _tilde_requirement(pattern):
        a = pattern[1:].split(".")
        length = len(a)

        min_pattern = f">={pattern[1:]}"
        if length == 1:
            min_pattern += ".0.0"
        elif length == 2:
            min_pattern += ".0"

        if length == 1:
            max_pattern = f"<{int(a[0])+1}.0.0"
        else:
            max_pattern = f"<{a[0]}.{int(a[1]) + 1}.0"

        return min_pattern, max_pattern

    def match(self, pattern):
        """"""

        def expr(pattern, strict=False):

            pattern = pattern.strip()

            if pattern[0] == "^":
                p1, p2 = SemVer._caret_requirement(pattern)
                return expr(p1) and expr(p2, True)

            if pattern[0] == "~":
                p1, p2 = SemVer._tilde_requirement(pattern)
                return expr(p1) and expr(p2, True)

            try:
                if pattern == "*":
                    return True

                if pattern[0] == "=":
                    p = pattern[1:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1

                    if p != self.raw_version:
                        b = p.split(".")
                        if len(b) == 2:
                            p += ".0"
                        elif len(b) == 1:
                            p += ".0.0"
                        a = SemVer(p)
                        min_parts = min(len(self.parts), len(b))
                        return self.parts[:min_parts] == a.parts[:min_parts]

                    return p == self.raw_version

                if pattern[0:2] == ">=":
                    p = pattern[2:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1
                    if re.match(r"^\d+$", p):
                        p += ".0.0"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".0"
                    return self.compare(p) >= 0

                if pattern[0:2] == "<=":
                    p = pattern[2:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1
                    if re.match(r"^\d+$", p):
                        p += ".9999999.9999999"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".9999999"
                    return self.compare(p) <= 0

                if pattern[0:1] == ">":
                    p = pattern[1:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1
                    if re.match(r"^\d+$", p):
                        p += ".0.0"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".0"
                    return self.compare(p) > 0

                if pattern[0:1] == "<":
                    p = pattern[1:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1
                    if re.match(r"^\d+$", p):
                        p += ".9999999.9999999"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".9999999"
                    return self.compare(p, strict) < 0

                # if pattern[0] == "^":
                #     p = pattern[1:].lstrip()
                #     assert p[0].isdigit() and p.find("*") == -1
                #     a = p.split(".")
                #     b = self.raw_version.split(".")
                #     return a == b[: len(a)]

                # if pattern[0] == "~":
                #     p = pattern[1:].lstrip()
                #     assert p[0].isdigit() and p.find("*") == -1
                #     a = p.split(".")
                #     b = self.raw_version.split(".")
                #     return a == b[: len(a)]

                assert pattern[0].isdigit()

                if pattern.find("*") != -1:
                    p = re.escape(pattern)
                    p = p.replace(r"\*", r".*")
                    p = "^" + p + "$"
                    return re.match(p, self.raw_version) is not None

                return pattern == self.raw_version

            except Exception as e:
                print(f'ERROR semver_match("{pattern}", "{self}")')
                raise e

        return all(expr(p) for p in pattern.split(","))

    @staticmethod
    def find_matching(pattern, versions):

        try:
            m = None
            m_yanked = None
            last = None

            for v, item in versions.items():
                last = item
                w = SemVer(v)
                if w.match(pattern):
                    # print("match", pattern, item["name"], item["vers"], item["yanked"] and "yanked" or "")

                    if item["yanked"] == False:
                        if m is None or w.compare(m[0]) > 0:
                            m = (w, item)
                    else:
                        if m_yanked is None or w.compare(m_yanked[0]) > 0:
                            m_yanked = (w, item)

            if m_yanked and not m:
                print(
                    "WARNING: no matching version found, using yanked version",
                    m_yanked[1]["name"],
                    pattern,
                    m_yanked[0] and "yanked" or "",
                )
                m = m_yanked

            if not m:
                m = (None, last)
                print("WARNING: no matching version found, using latest version", m[1]["name"], pattern)

            return m[1]

        except Exception as e:
            print(f'ERROR find_matching("{pattern}", {versions.keys()})')
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


def init_mp_session(counter, total):
    get_context().session = requests.Session()
    get_context().counter = counter
    get_context().total = total


class TopCrates:
    def __init__(self):
        self.verbose = False
        self.session = None
        self.crates = defaultdict(set)

        conf = tomli.load(open("top-crates.toml", "rb"))

        self.conf_top_crates = conf.get("top-crates", 0)
        self.conf_categories = conf.get("categories", [])
        self.conf_cookbook = bool(conf.get("cookbook", False))
        self.conf_additions = conf.get("additions", [])
        self.conf_commands = conf.get("commands", [])

        self.exclusions = [
            re.compile("^" + re.escape(k).replace(r"\*", r".*") + "$") for k in conf.get("exclusions", [])
        ]

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
        def get_top(count, category=""):
            if category:
                category = f"&category={category}"

            per_page = 100
            page = 1

            while count > 0:
                url = f"https://crates.io/api/v1/crates?page={page}&per_page={min(count,per_page)}&sort=downloads{category}"
                data = requests.get(url).json()

                if self.verbose:
                    print(url, len(data["crates"]))

                for crate in data["crates"]:
                    if crate["max_stable_version"]:
                        self.add(crate["name"], crate["max_stable_version"])
                    self.add(crate["name"], crate["max_version"])

                page += 1
                count -= per_page

        get_top(self.conf_top_crates)

        for category in self.conf_categories:
            for name, count in category.items():
                get_top(count, name)

    def cookbook(self):
        if self.conf_cookbook:
            r = requests.get("https://raw.githubusercontent.com/rust-lang-nursery/rust-cookbook/master/Cargo.toml")
            d = tomli.loads(r.text)
            for name in d["dependencies"].keys():
                self.add(name)

    def curated(self):
        for k in self.conf_additions:
            self.add(k)
        for k in self.conf_commands:
            self.add(k)

    def resolve_deps(self, max_iterations=20000):

        print(f"Analyze {len(self.crates)} crates")

        seen = set()
        n = 0
        while len(self.crates) > 0:

            n += 1
            if n > max_iterations:
                print("too many iterations")
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

                k = SemVer.find_matching(vers, info)

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

                    if "package" in dep:
                        name = dep["package"]

                    if self.verbose:
                        print(f"      found: {name} {req}  {dep['kind']} {dep['optional'] and 'optional' or ''}")

                    # if dep["kind"] == "dev":
                    #     continue

                    # if dep["optional"] == True:
                    #     continue

                    assert dep["kind"] in ["normal", "build", "dev"]

                    if name not in seen:
                        self.add(name, req)
                        if self.verbose:
                            print("      adding", name, req)
                    else:
                        assert False

            if self.verbose:
                print()

        self.seen = seen

    def make_index(self, dest="top-crates-index", crates_dir=None):

        # selected_crates = json.load(open("selected_crates.json"))

        selected_crates = dict()
        for k, v in self.seen:
            selected_crates[k] = list()
        for k, v in self.seen:
            selected_crates[k].append(v)

        print(f"Found {len(selected_crates)} crates and {len(self.seen)} versions")

        json.dump(selected_crates, open("selected_crates.json", "w"), indent=2)

        for p in Path(dest).glob("*"):
            if len(p.name) <= 2 and p.is_dir():
                # skip .git, config.json, etc.
                shutil.rmtree(p, ignore_errors=True)

        downloads = []
        if crates_dir:
            crates_dir = Path(crates_dir)

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

                    if crates_dir:
                        version = v["vers"]
                        crate_file = f"{name}-{version}.crate"

                        if (crates_dir / crate_file).exists() == False:
                            downloads.append((name, version))

            f = Path(dest) / prefix_name(name)
            f.parent.mkdir(exist_ok=True, parents=True)
            new_data.append("")
            f.write_text("\n".join(new_data))

        num = multiprocessing.Value("i", 0)
        total = len(downloads)

        pool = Pool(16, initializer=init_mp_session, initargs=(num, total))
        download_func = partial(TopCrates.download_crate, crates_dir=crates_dir)
        pool.map(download_func, downloads)
        pool.close()
        pool.join()

        print()

    def download_crate(name_version, crates_dir):

        name, version = name_version
        context = get_context()
        session = context.session
        counter = context.counter

        with counter.get_lock():
            counter.value += 1

        url = f" https://static.crates.io/crates/{name}/{name}-{version}.crate"
        dest_file = crates_dir / f"{name}-{version}.crate"

        print(f" {counter.value:6}/{context.total}  {url.ljust(120)}\r", end="")

        r = session.get(url)
        dest_file.write_bytes(r.content)
        if "last-modified" in r.headers:
            url_date = parsedate(r.headers["last-modified"])
            mtime = round(url_date.timestamp() * 1_000_000_000)
            os.utime(dest_file, ns=(mtime, mtime))


def main():
    parser = argparse.ArgumentParser(description="Create an index for the top crates")

    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-d", "--download", action="store_true", help="Force build the list of crates")
    parser.add_argument("-u", "--update", action="store_true", help="Fetch the upstream")
    parser.add_argument("-c", "--commit", action="store_true", help="Commit the new index")
    parser.add_argument("-r", "--git-registry", action="store_true", help="Make a Git registry")

    parser.add_argument("-t", help="test")

    args = parser.parse_args()

    a = TopCrates()

    a.verbose = args.verbose

    if args.t:
        name, version = args.t.split(" ", 1)
        a.add(name, version)
        a.resolve_deps(1)
        exit()

    if args.download or not Path("crates.json").is_file():
        print("Build the top crates list")
        a.download()
        a.cookbook()
        a.curated()
        a.save("crates.json")

    else:
        a.load("crates.json")

    if args.update:
        print("Update main index")
        subprocess.run(["git", "fetch", "--all"], cwd="crates.io-index")
        subprocess.run(["git", "reset", "--hard", "origin/master"], cwd="crates.io-index")

    a.resolve_deps()

    if args.git_registry:
        # not well supported, should git clone/git init before
        if args.commit:
            subprocess.run(["git", "clean", "-ffdx"], cwd="top-crates-index")
            subprocess.run(["git", "reset", "--hard", "origin/master"], cwd="top-crates-index")

        a.make_index("top-crates-index")
        subprocess.run(["git", "status", "-s"], cwd="top-crates-index")

        if args.commit:
            subprocess.run(["git", "add", "."], cwd="top-crates-index")
            subprocess.run(["git", "commit", "-m", "Update top crates index"], cwd="top-crates-index")
            subprocess.run(["git", "push", "origin", "master"], cwd="top-crates-index")

    else:
        a.make_index("local-registry/index", "local-registry")


if __name__ == "__main__":
    main()
