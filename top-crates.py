#!/usr/bin/env python3

import requests
import toml
import json
from pathlib import Path
from collections import defaultdict
import re
import sys
import subprocess
import argparse


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

    def resolve_deps(self, max_iterations=20000):

        print(f"Analyzing {len(self.crates)} crates")

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
    parser = argparse.ArgumentParser(description="Create an index for the top crates")

    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-d", "--download", action="store_true", help="Force build the list of crates")
    parser.add_argument("-u", "--update", action="store_true", help="Fetch the upstream")
    parser.add_argument("-c", "--commit", action="store_true", help="Commit the new index")

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
        print("Building the top crates list")
        a.download()
        a.cookbook()
        a.curated()
        a.save("crates.json")

    else:
        a.load("crates.json")

    if args.update:
        subprocess.run(["git", "fetch", "--all"], cwd="crates.io-index")
        subprocess.run(["git", "reset", "--hard", "origin/master"], cwd="crates.io-index")

    a.resolve_deps()

    if args.commit:
        subprocess.run(["git", "clean", "-ffdx"], cwd="top-crates-index")
        subprocess.run(["git", "reset", "--hard", "origin/master"], cwd="top-crates-index")

    a.make_git_index()

    if args.commit:
        subprocess.run(["git", "add", "."], cwd="top-crates-index")
        subprocess.run(["git", "commit", "-m", "Update top crates index"], cwd="top-crates-index")
        subprocess.run(["git", "push", "origin", "master"], cwd="top-crates-index")


assert SemVer._caret_requirement("^1.2.3".strip()) == (">=1.2.3", "<2.0.0")
assert SemVer._caret_requirement("^1.2  ".strip()) == (">=1.2.0", "<2.0.0")
assert SemVer._caret_requirement("^1    ".strip()) == (">=1.0.0", "<2.0.0")
assert SemVer._caret_requirement("^0.2.3".strip()) == (">=0.2.3", "<0.3.0")
assert SemVer._caret_requirement("^0.2  ".strip()) == (">=0.2.0", "<0.3.0")
assert SemVer._caret_requirement("^0.0.3".strip()) == (">=0.0.3", "<0.0.4")
assert SemVer._caret_requirement("^0.0  ".strip()) == (">=0.0.0", "<0.1.0")
assert SemVer._caret_requirement("^0    ".strip()) == (">=0.0.0", "<1.0.0")

assert SemVer._tilde_requirement("~1.2.3".strip()) == (">=1.2.3", "<1.3.0")
assert SemVer._tilde_requirement("~1.2  ".strip()) == (">=1.2.0", "<1.3.0")
assert SemVer._tilde_requirement("~1    ".strip()) == (">=1.0.0", "<2.0.0")


# v = SemVer("0.4.0-alpha.1")
# print(v.compare("0.4.0"))
# print(v.match("^0.3.0"))


if __name__ == "__main__":
    main()
