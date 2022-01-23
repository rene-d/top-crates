#!/usr/bin/env python3

import multiprocessing
import requests
import tomli
import json
from pathlib import Path
from collections import defaultdict
import re
import subprocess  # nosec
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

        assert str(self) == version  # nosec

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

    def _caret_requirement(pattern):
        """
        Match a [caret-requirement](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#caret-requirements).
        """
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

        return min_pattern, max_pattern

    def _tilde_requirement(pattern):
        """
        Match a [tilde requirement](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#tilde-requirements).
        """
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
        """
        Test if semver matches a pattern.
        """

        def _expr(pattern, strict=False):

            pattern = pattern.strip()

            if pattern[0] == "^":
                p1, p2 = SemVer._caret_requirement(pattern)
                return _expr(p1) and _expr(p2, True)

            if pattern[0] == "~":
                p1, p2 = SemVer._tilde_requirement(pattern)
                return _expr(p1) and _expr(p2, True)

            try:
                if pattern == "*":
                    return True

                if pattern[0] == "=":
                    p = pattern[1:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1  # nosec

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
                    assert p[0].isdigit() and p.find("*") == -1  # nosec
                    if re.match(r"^\d+$", p):
                        p += ".0.0"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".0"
                    return self.compare(p) >= 0

                if pattern[0:2] == "<=":
                    p = pattern[2:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1  # nosec
                    if re.match(r"^\d+$", p):
                        p += ".9999999.9999999"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".9999999"
                    return self.compare(p) <= 0

                if pattern[0:1] == ">":
                    p = pattern[1:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1  # nosec
                    if re.match(r"^\d+$", p):
                        p += ".0.0"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".0"
                    return self.compare(p) > 0

                if pattern[0:1] == "<":
                    p = pattern[1:].lstrip()
                    assert p[0].isdigit() and p.find("*") == -1  # nosec
                    if re.match(r"^\d+$", p):
                        p += ".9999999.9999999"
                    elif re.match(r"^\d+\.\d+$", p):
                        p += ".9999999"
                    return self.compare(p, strict) < 0

                assert pattern[0].isdigit()  # nosec

                if pattern.find("*") != -1:
                    p = re.escape(pattern)
                    p = p.replace(r"\*", r".*")
                    p = "^" + p + "$"
                    return re.match(p, self.raw_version) is not None

                return pattern == self.raw_version

            except Exception as e:
                print(f'ERROR semver_match("{pattern}", "{self}")')
                raise e

        return all(_expr(p) for p in pattern.split(","))

    @staticmethod
    def find_matching(pattern, versions):
        """
        Find the match version for a pattern.
        """
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
                # print(
                #     "WARNING: no matching version found, using yanked version",
                #     m_yanked[1]["name"],
                #     pattern,
                #     m_yanked[0] and "yanked" or "",
                # )
                m = m_yanked

            if not m:
                m = (None, last)
                print("WARNING: no matching version found, using latest version", m[1]["name"], pattern)

            return m[1]

        except Exception as e:
            print(f'ERROR find_matching("{pattern}", {versions.keys()})')
            raise e


class TopCrates:
    """
    Class to download crates and make a local Rust registry.
    """

    def __init__(self):
        """
        Constructor.
        """
        self.verbose = False
        self.crates = defaultdict(set)
        self.selected_crates = None

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
        """
        Load crates from a JSON file.
        """
        data = json.load(open(filename))
        for k, v in data.items():
            for version in v:
                self.add(k, version)

    def save(self, filename):
        """
        Save the crates list to a JSON file.
        """
        data = dict((k, list(v)) for k, v in self.crates.items())
        json.dump(data, open(filename, "w"), indent=2)

    def add(self, name, version="latest"):
        """
        Add a crate version to the list of crates.
        """
        if any(e.match(name) for e in self.exclusions):
            return
        self.crates[name].add(version)

    def top_crates(self):
        """
        Download the top crates from the [Rust registry](https://crates.io/).
        """

        def _get_top(count, category=""):
            """
            Use the crates.io API to fetch crates per download count.
            """
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

        _get_top(self.conf_top_crates)

        for category in self.conf_categories:
            for name, count in category.items():
                _get_top(count, name)

    def cookbook(self):
        """
        Add crates from the [Rust Cookbook](https://rust-lang-nursery.github.io/rust-cookbook/intro.html).
        """
        if self.conf_cookbook:
            r = requests.get("https://raw.githubusercontent.com/rust-lang-nursery/rust-cookbook/master/Cargo.toml")
            d = tomli.loads(r.text)
            for name in d["dependencies"].keys():
                self.add(name)

    def curated(self):
        """
        Add curated crates and commands.
        """
        for k in self.conf_additions:
            self.add(k)
        for k in self.conf_commands:
            self.add(k)

    @staticmethod
    def _prefix_name(name):
        """
        Make the path a crate to conform [registies](https://doc.rust-lang.org/cargo/reference/registries.html) rules.
        """
        l = len(name)
        if l == 1:
            return f"1/{name}"
        elif l == 2:
            return f"2/{name}"
        elif l == 3:
            return f"3/{name[0]}/{name}"
        else:
            return f"{name[:2]}/{name[2:4]}/{name}"

    def resolve_deps(self, max_iterations=20000):
        """
        Resolve dependencies of all crates, like Cargo does.
        """
        print(f"Analyze {len(self.crates)} crates")

        seen = set()  # memoize already resolved crates

        n = 0
        while len(self.crates) > 0:

            n += 1
            if n > max_iterations:
                print("too many iterations")
                break

            crate, versions = self.crates.popitem()

            if any(e.match(crate) for e in self.exclusions):
                print(f"excluded: {name} {versions}")
                continue

            try:
                if self.verbose:
                    print(f"{n:03d} {crate} {sorted(versions)}")
            except:
                print(f"{n:03d} {crate} {versions}")
                raise

            if len(versions) == 0:
                continue

            info_file = Path("crates.io-index") / TopCrates._prefix_name(crate)
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

                    assert dep["kind"] in ["normal", "build", "dev"]  # nosec

                    if name not in seen:
                        self.add(name, req)
                        if self.verbose:
                            print("      adding", name, req)
                    else:
                        assert False  # nosec

            if self.verbose:
                print()

        self.selected_crates = dict()
        for k, v in seen:
            self.selected_crates[k] = list()
        for k, v in seen:
            self.selected_crates[k].append(v)

        print(f"Found {len(self.selected_crates)} crates and {len(seen)} versions")
        json.dump(self.selected_crates, open("selected_crates.json", "w"), indent=2)

    def make_index(self, index_dir="local-registry/index"):
        """
        Build the crates index with the required arborescence: <prefix>/<crate>. Each line of a crate file describes a version.
        """
        if self.selected_crates is None:
            self.selected_crates = json.load(open("selected_crates.json"))

        # remove the whole index, it will be recreated
        for p in Path(index_dir).glob("*"):
            if len(p.name) <= 2 and p.is_dir():
                # skip .git, config.json, etc.
                shutil.rmtree(p, ignore_errors=True)

        for name, versions in self.selected_crates.items():

            data = Path(f"crates.io-index/{TopCrates._prefix_name(name)}")

            versions = set(versions)
            new_data = []
            for line in data.read_text().splitlines():
                v = json.loads(line)
                if v["vers"] in versions:
                    new_data.append(line)

            f = Path(index_dir) / TopCrates._prefix_name(name)
            f.parent.mkdir(exist_ok=True, parents=True)
            new_data.append("")
            f.write_text("\n".join(new_data))

    def download_crates(self, crates_dir="local-registry", purge=False):
        """
        Download crates to the local registry, in a flat directory structure.
        """
        crates_dir = Path(crates_dir)
        crates_dir.mkdir(exist_ok=True, parents=True)

        existing = set(f.name for f in crates_dir.glob("*.crate"))
        downloads = []

        for name, versions in self.selected_crates.items():
            for version in versions:
                crate_file = f"{name}-{version}.crate"
                if crate_file not in existing:
                    downloads.append((name, version))
                else:
                    existing.discard(crate_file)

        # existing now contains no more listed crates
        print(f"{len(existing)} unused crate{'' if len(existing) < 1 else 's'}")
        for f in existing:
            if purge:
                (crates_dir / f).unlink()
                if self.verbose:
                    print(f"deleted: {f}")
            else:
                if self.verbose:
                    print(f"unused: {f}")

        if len(downloads) == 0:
            print("No new crates to download")
            return

        num = multiprocessing.Value("i", 0)
        total = len(downloads)

        # multiprocessing download with 16 workers
        pool = Pool(16, initializer=TopCrates._init_mp_session, initargs=(num, total))
        download_func = partial(TopCrates._download_crate, crates_dir=crates_dir)
        pool.map(download_func, downloads)
        pool.close()
        pool.join()

        print(f"Downloaded {total} new crate{'' if total < 2 else 's'}", " " * 80)

    @staticmethod
    def _init_mp_session(counter, total):
        """
        Initialize a multiprocessing session.
        Set up a new Requests session for each process and set the shared counter.
        """
        get_context().session = requests.Session()
        get_context().counter = counter
        get_context().total = total

    @staticmethod
    def _download_crate(name_version, crates_dir):
        """
        Download a crate in a multiprocessing session. Requests session is reused and shared counter is updated.
        """
        name, version = name_version
        context = get_context()
        session = context.session
        counter = context.counter

        with counter.get_lock():
            counter.value += 1

        url = f" https://static.crates.io/crates/{name}/{name}-{version}.crate"
        dest_file = crates_dir / f"{name}-{version}.crate"

        print(f"{counter.value:6}/{context.total}  {url.ljust(100)[-100:]}\r", end="")

        r = session.get(url)
        dest_file.write_bytes(r.content)
        if "last-modified" in r.headers:
            url_date = parsedate(r.headers["last-modified"])
            mtime = round(url_date.timestamp() * 1_000_000_000)
            os.utime(dest_file, ns=(mtime, mtime))


def git_cmd(cmd, *args, **kwargs):
    """
    Run a git command.
    """
    return subprocess.run(["git"] + cmd, *args, **kwargs)  # nosec


def main():
    """
    Main function.
    Parse command line arguments and call the appropriate function.
    """
    parser = argparse.ArgumentParser(description="Create an index for the top crates")

    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-d", "--download", action="store_true", help="Force build the list of crates")
    parser.add_argument("-u", "--update", action="store_true", help="Fetch the upstream")
    parser.add_argument("-p", "--purge", action="store_true", help="Remove encumbered crates")
    parser.add_argument("-c", "--commit", action="store_true", help="Commit the new index")
    parser.add_argument("-g", "--git-registry", action="store_true", help="Make a Git registry")

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
        a.top_crates()
        a.cookbook()
        a.curated()
        a.save("crates.json")
    else:
        a.load("crates.json")

    if args.update:
        print("Update main index")
        git_cmd(["fetch", "--all"], cwd="crates.io-index")
        git_cmd(["reset", "--hard", "origin/master"], cwd="crates.io-index")

    a.resolve_deps()

    if args.git_registry:
        # not well supported, should git clone/git init before
        if args.commit:
            git_cmd(["clean", "-ffdx"], cwd="top-crates-index")
            git_cmd(["reset", "--hard", "origin/master"], cwd="top-crates-index")

        a.make_index("top-crates-index")
        git_cmd(["status", "-s"], cwd="top-crates-index")

        if args.commit:
            git_cmd(["add", "."], cwd="top-crates-index")
            git_cmd(["commit", "-m", "Update top crates index"], cwd="top-crates-index")
            git_cmd(["push", "origin", "master"], cwd="top-crates-index")

    else:
        a.make_index()
        a.download_crates(purge=args.purge)


if __name__ == "__main__":
    main()
