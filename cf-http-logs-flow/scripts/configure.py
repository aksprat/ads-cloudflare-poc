"""Configure this project for your workspace, from this project's folder:

    python3 scripts/configure.py --table my_table name=my-flow input.bucket=my-bucket

Each key.path=value sets a key that is already in data-flow.toml (a string). The file is read with tomllib and
written back whole, so comments in it are not kept; the old file is saved as data-flow.toml.bak.

--table sets the table name in s3_gzip/pipeline.py (table = ...) and s3_gzip/sink.ddl (CREATE TABLE).

It stops with one `error:` line, and changes nothing, for a key that is not in the file, an empty value, a table
name that is empty or not lowercase letters, digits and underscores starting with a letter, or a result that does
not read back as intended.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
MANIFEST, SCHEMA, DDL = "data-flow.toml", "s3_gzip/pipeline.py", "s3_gzip/sink.ddl"
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
TABLE_NAME = re.compile(r"[a-z][a-z0-9_]*")
SCHEMA_TABLE = re.compile(r'^    table = "([^"]+)"', re.M)
DDL_TABLE = re.compile(r"(CREATE TABLE IF NOT EXISTS )(\S+)")


class Refused(Exception):
    """Nothing is changed."""


def key_text(key: str) -> str:
    return key if BARE_KEY.fullmatch(key) else json.dumps(key)


def emit(table: dict, path: tuple[str, ...] = ()) -> list[str]:
    """The lines of a table: its own keys first, then each sub-table under its [a.b] header."""
    lines = ["%s = %s" % (key_text(key), json.dumps(value, ensure_ascii=False))
             for key, value in table.items() if not isinstance(value, dict)]
    for key, value in table.items():
        if isinstance(value, dict):
            here = path + (key,)
            if any(not isinstance(v, dict) for v in value.values()):
                lines += ["", "[%s]" % ".".join(key_text(part) for part in here)]
            lines += emit(value, here)
    return lines


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Refused("cannot read %s: %s" % (path, exc)) from None


def edited_manifest(path: Path, assignments: list[str]) -> tuple[str, list[str]]:
    try:
        data = tomllib.loads(read(path))
    except tomllib.TOMLDecodeError as exc:
        raise Refused("cannot read %s: %s" % (path, exc)) from None
    keys = []
    for assignment in assignments:
        key, equals, value = assignment.partition("=")
        if not equals or not key:
            raise Refused("%r is not key.path=value" % assignment)
        if not value.strip():
            raise Refused("%s is empty: set it first" % key)
        *parents, last = key.split(".")
        node = data
        for part in parents:
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict) or last not in node or isinstance(node[last], dict):
            raise Refused("%s is not a key in %s" % (key, path.name))
        if not isinstance(node[last], str):
            raise Refused("%s is not a string, so it cannot be set here" % key)
        node[last] = value
        keys.append(key)
    text = "\n".join(emit(data)).lstrip("\n") + "\n"
    try:
        intended = tomllib.loads(text) == data
    except tomllib.TOMLDecodeError:
        intended = False
    if not intended:
        raise Refused("%s could not be written back safely; nothing was changed" % path.name)
    return text, keys


def edited_table(project: Path, table: str) -> tuple[dict[Path, str], str]:
    if not table.strip():
        raise Refused("--table is empty: set TABLE_NAME first")
    if not TABLE_NAME.fullmatch(table):
        raise Refused("--table must be lowercase letters, digits and underscores, starting with a letter: %r" % table)
    schema, ddl = project / SCHEMA, project / DDL
    schema_text, ddl_text = read(schema), read(ddl)
    found = SCHEMA_TABLE.search(schema_text)
    if not found or not DDL_TABLE.search(ddl_text):
        raise Refused("cannot find the table name in %s and %s" % (SCHEMA, DDL))
    return ({schema: SCHEMA_TABLE.sub('    table = "%s"' % table, schema_text, count=1),
             ddl: DDL_TABLE.sub(lambda m: m.group(1) + table, ddl_text, count=1)}, found.group(1))


def configure(project: Path, assignments: list[str], table: str | None) -> list[str]:
    writes: dict[Path, str] = {}
    report = []
    manifest = project / MANIFEST
    if assignments:
        writes[manifest], keys = edited_manifest(manifest, assignments)
        report.append("updated %s: %s" % (MANIFEST, ", ".join(keys)))
    if table is not None:
        files, old = edited_table(project, table)
        writes.update(files)
        report.append("table: %s -> %s" % (old, table))
    if manifest in writes:
        shutil.copy(manifest, manifest.with_name(manifest.name + ".bak"))
    for path, text in writes.items():
        path.write_text(text, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("assignments", nargs="*", metavar="key.path=value", help="a key in data-flow.toml and its new value")
    parser.add_argument("--table", metavar="NAME", help="the table the data flow writes (pipeline.py and sink.ddl)")
    parser.add_argument("--project", type=Path, default=PROJECT, help="the project folder (default: this one)")
    args = parser.parse_args(argv)
    if not args.assignments and args.table is None:
        parser.error("give --table, at least one key.path=value, or both")
    try:
        report = configure(args.project, args.assignments, args.table)
    except Refused as exc:
        sys.exit("error: %s" % exc)
    print("\n".join(report))


if __name__ == "__main__":
    main()
