"""scripts/configure.py sets manifest keys and the table name together, keeps a .bak of the manifest, and changes nothing when anything is refused."""

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "configure.py"
FILES = ("data-flow.toml", "s3_gzip/pipeline.py", "s3_gzip/sink.ddl")
POLL_KEY = "pump.options.poll_interval"


class Configure(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="configure-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "s3_gzip").mkdir()
        for name in FILES:
            shutil.copy(ROOT / name, self.tmp / name)
        self.original = {name: (self.tmp / name).read_text() for name in FILES}

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.tmp), *args],
                              env={"PATH": os.environ.get("PATH", "")}, capture_output=True, text=True, timeout=60)

    def text(self, name: str) -> str:
        return (self.tmp / name).read_text()

    def refused(self, *args: str, message: str) -> None:
        done = self.run_script(*args)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("error: " + message, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        for name in FILES:
            self.assertEqual(self.text(name), self.original[name], name)
        self.assertFalse((self.tmp / "data-flow.toml.bak").exists())

    def test_sets_the_keys_and_changes_nothing_else(self) -> None:
        done = self.run_script("name=my-flow", "input.bucket=my-bucket", POLL_KEY + "=30s")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "updated data-flow.toml: name, input.bucket, %s\n" % POLL_KEY)
        expected = tomllib.loads(self.original["data-flow.toml"])
        expected["name"] = "my-flow"
        expected["input"]["bucket"] = "my-bucket"
        expected["pump"]["options"]["poll_interval"] = "30s"
        self.assertEqual(tomllib.loads(self.text("data-flow.toml")), expected)
        self.assertEqual(self.text("s3_gzip/pipeline.py"), self.original["s3_gzip/pipeline.py"])
        self.assertEqual(self.text("s3_gzip/sink.ddl"), self.original["s3_gzip/sink.ddl"])

    def test_keeps_the_old_manifest_as_a_bak(self) -> None:
        self.assertEqual(self.run_script("name=my-flow").returncode, 0)
        self.assertEqual(self.text("data-flow.toml.bak"), self.original["data-flow.toml"])

    def test_the_shipped_manifest_is_written_back_byte_for_byte(self) -> None:
        name = tomllib.loads(self.original["data-flow.toml"])["name"]
        self.assertEqual(self.run_script("name=" + name).returncode, 0)
        self.assertEqual(self.text("data-flow.toml"), self.original["data-flow.toml"])

    def test_a_value_with_an_equals_sign_or_quotes_is_kept_whole(self) -> None:
        value = 'a=b "quoted" \\ back'
        self.assertEqual(self.run_script("name=" + value).returncode, 0)
        self.assertEqual(tomllib.loads(self.text("data-flow.toml"))["name"], value)

    def test_the_table_name_goes_into_pipeline_py_and_sink_ddl_only(self) -> None:
        done = self.run_script("--table", "my_table_2")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"^table: \w+ -> my_table_2\n$")
        pipeline, ddl = self.text("s3_gzip/pipeline.py"), self.text("s3_gzip/sink.ddl")
        self.assertIn('    table = "my_table_2"\n', pipeline)
        self.assertTrue(ddl.startswith("CREATE TABLE IF NOT EXISTS my_table_2 ("))
        before_pipeline, before_ddl = self.original["s3_gzip/pipeline.py"], self.original["s3_gzip/sink.ddl"]
        self.assertEqual(len(pipeline.splitlines()), len(before_pipeline.splitlines()))
        self.assertEqual(len(ddl.splitlines()), len(before_ddl.splitlines()))
        self.assertEqual(sum(a != b for a, b in zip(pipeline.splitlines(), before_pipeline.splitlines())), 1)
        self.assertEqual(self.text("data-flow.toml"), self.original["data-flow.toml"])
        self.assertFalse((self.tmp / "data-flow.toml.bak").exists())

    def test_the_table_name_and_the_keys_are_set_in_one_run(self) -> None:
        done = self.run_script("--table", "my_table", "name=my-flow", "input.bucket=my-bucket")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("updated data-flow.toml: name, input.bucket\n", done.stdout)
        self.assertIn("table: ", done.stdout)
        self.assertEqual(tomllib.loads(self.text("data-flow.toml"))["name"], "my-flow")
        self.assertIn('    table = "my_table"\n', self.text("s3_gzip/pipeline.py"))

    def test_running_again_with_another_table_changes_it_again(self) -> None:
        self.assertEqual(self.run_script("--table", "first_one").returncode, 0)
        done = self.run_script("--table", "second_one")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "table: first_one -> second_one\n")

    def test_a_bad_table_name_is_refused_and_nothing_changes(self) -> None:
        self.refused("--table", "", message="--table is empty: set TABLE_NAME first")
        self.refused("--table", "  ", message="--table is empty: set TABLE_NAME first")
        for bad in ("My_table", "my-table", "my table", "1table", "_table", "table;drop"):
            self.refused("--table", bad, message="--table must be lowercase letters, digits and underscores, starting with a letter")

    def test_a_bad_key_stops_the_table_change_too(self) -> None:
        self.refused("--table", "my_table", "input.buckt=x", message="input.buckt is not a key in data-flow.toml")

    def test_a_bad_table_stops_the_key_changes_too(self) -> None:
        self.refused("--table", "Bad-Table", "name=my-flow", message="--table must be lowercase letters")

    def test_a_key_that_is_not_in_the_file_is_refused(self) -> None:
        self.refused("input.buckt=x", message="input.buckt is not a key in data-flow.toml")
        self.refused("nowhere.at.all=x", message="nowhere.at.all is not a key in data-flow.toml")
        self.refused("input=x", message="input is not a key in data-flow.toml")

    def test_an_empty_value_is_refused(self) -> None:
        self.refused("name=", message="name is empty: set it first")
        self.refused("input.bucket=   ", message="input.bucket is empty: set it first")

    def test_a_key_that_is_not_a_string_is_refused(self) -> None:
        self.refused("runtime.source.options.max_records=5", message="runtime.source.options.max_records is not a string, so it cannot be set here")

    def test_an_argument_without_an_equals_sign_is_refused(self) -> None:
        self.refused("name", message="'name' is not key.path=value")

    def test_a_project_without_the_table_lines_is_refused(self) -> None:
        (self.tmp / "s3_gzip/pipeline.py").write_text("NOTHING = 1\n")
        self.original["s3_gzip/pipeline.py"] = "NOTHING = 1\n"
        self.refused("--table", "my_table", message="cannot find the table name")

    def test_a_manifest_that_is_not_toml_is_refused(self) -> None:
        (self.tmp / "data-flow.toml").write_text("{ not toml")
        self.original["data-flow.toml"] = "{ not toml"
        self.refused("name=x", message="cannot read")

    def test_a_missing_manifest_is_refused(self) -> None:
        (self.tmp / "data-flow.toml").unlink()
        done = self.run_script("name=x")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("error: cannot read", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_nothing_to_do_is_a_usage_error(self) -> None:
        done = self.run_script()
        self.assertEqual(done.returncode, 2)
        self.assertIn("give --table, at least one key.path=value, or both", done.stderr)


if __name__ == "__main__":
    unittest.main()
