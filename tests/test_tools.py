"""Automated tests for the calculator, file, and dispatch tools."""

import hashlib
import json
import sys
import tempfile
import unittest

from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools

from tools import calculate, execute_tool, list_files, read_file, write_file


class CalculateTestCase(unittest.TestCase):
    """Tests for the restricted arithmetic calculator."""

    def test_valid_expressions(self):
        cases = {
            "2+2*3": 8,
            "(2+2)*3": 12,
            "10/4": 2.5,
            "7//2": 3,
            "7%3": 1,
            "2**10": 1024,
            "-5+3": -2,
            "2.5*2": 5.0,
        }

        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(calculate(expression), expected)

    def test_rejects_empty_expression(self):
        for expression in ("", "   ", None, 123):
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calculate(expression)

    def test_rejects_too_long_expression(self):
        with self.assertRaises(ValueError):
            calculate("1+" * 150)

    def test_rejects_comparison_operators(self):
        with self.assertRaises(ValueError):
            calculate("2 < 3")

    def test_rejects_variables(self):
        with self.assertRaises(ValueError):
            calculate("x")

    def test_rejects_function_calls(self):
        with self.assertRaises(ValueError):
            calculate("sqrt(4)")

    def test_rejects_boolean_and_string_constants(self):
        with self.assertRaises(ValueError):
            calculate("True")

        with self.assertRaises(ValueError):
            calculate("'a'")

    def test_rejects_excessive_exponent(self):
        with self.assertRaises(ValueError):
            calculate("2**1000")

    def test_rejects_out_of_range_result(self):
        with self.assertRaises(ValueError):
            calculate("1e300*1e300")

        with self.assertRaises(ValueError):
            calculate("99**100")

    def test_division_by_zero_raises(self):
        with self.assertRaises(ZeroDivisionError):
            calculate("1/0")


class TempProjectTestCase(unittest.TestCase):
    """Base class providing a temporary project root and patching."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)

        for directory in ("memory", "tests", "docs", "data", ".venv"):
            (self.project_root / directory).mkdir()

        root_patcher = mock.patch.object(
            tools,
            "PROJECT_ROOT",
            self.project_root,
        )
        backup_patcher = mock.patch.object(
            tools,
            "BACKUP_ROOT",
            self.project_root / ".backups",
        )

        root_patcher.start()
        backup_patcher.start()

        self.addCleanup(root_patcher.stop)
        self.addCleanup(backup_patcher.stop)

    def tearDown(self):
        self._temp_dir.cleanup()


class FileToolsTestCase(TempProjectTestCase):
    """Tests for file tools against a temporary project root."""

    def test_write_creates_file_with_verification(self):
        result = write_file("memory/note.md", "Hello")

        self.assertEqual(result["path"], "memory/note.md")
        self.assertEqual(result["bytes_written"], 5)
        self.assertIsNone(result["backup"])
        self.assertTrue(result["operation"]["verified"])
        self.assertEqual(
            result["operation"]["sha256"],
            hashlib.sha256(b"Hello").hexdigest(),
        )
        self.assertEqual(
            (self.project_root / "memory" / "note.md").read_text(),
            "Hello",
        )

    def test_write_overwrite_creates_backup(self):
        write_file("memory/note.md", "Old content")
        result = write_file("memory/note.md", "New content")

        self.assertTrue(result["operation"]["verified"])
        self.assertIsNotNone(result["backup"])

        backup_path = self.project_root / result["backup"]
        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.read_text(), "Old content")
        self.assertEqual(
            (self.project_root / "memory" / "note.md").read_text(),
            "New content",
        )

    def test_write_rejects_project_root_files(self):
        with self.assertRaises(PermissionError):
            write_file("main.py", "x")

    def test_write_rejects_excluded_directory(self):
        with self.assertRaises(ValueError):
            write_file("data/notes.txt", "x")

    def test_write_rejects_disallowed_extension(self):
        with self.assertRaises(ValueError):
            write_file("memory/app.exe", "x")

    def test_write_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            write_file("../outside.txt", "x")

    def test_write_rejects_absolute_path(self):
        absolute = self.project_root / "memory" / "x.txt"

        with self.assertRaises(ValueError):
            write_file(str(absolute), "x")

    def test_write_rejects_oversized_content(self):
        content = "x" * (tools.MAX_FILE_SIZE + 1)

        with self.assertRaises(ValueError):
            write_file("memory/big.txt", content)

    def test_write_rejects_non_string_content(self):
        with self.assertRaises(ValueError):
            write_file("memory/x.txt", 123)

    def test_write_rejects_empty_path(self):
        with self.assertRaises(ValueError):
            write_file("", "x")

    def test_read_returns_content_and_source_metadata(self):
        write_file("memory/note.md", "Sample text")

        result = read_file("memory/note.md")

        self.assertEqual(result["path"], "memory/note.md")
        self.assertEqual(result["content"], "Sample text")
        self.assertEqual(result["size"], 11)
        self.assertEqual(
            result["source"]["sha256"],
            hashlib.sha256(b"Sample text").hexdigest(),
        )
        self.assertTrue(result["source"]["read_at"].endswith("Z"))

    def test_read_rejects_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            read_file("memory/ghost.txt")

    def test_read_rejects_disallowed_extension(self):
        path = self.project_root / "memory" / "blob.bin"
        path.write_bytes(b"\x00\x01")

        with self.assertRaises(ValueError):
            read_file("memory/blob.bin")

    def test_read_rejects_excluded_directory(self):
        path = self.project_root / "data" / "secret.txt"
        path.write_text("secret")

        with self.assertRaises(ValueError):
            read_file("data/secret.txt")

    def test_read_rejects_oversized_file(self):
        path = self.project_root / "memory" / "big.txt"
        path.write_bytes(b"x" * (tools.MAX_FILE_SIZE + 1))

        with self.assertRaises(ValueError):
            read_file("memory/big.txt")

    def test_read_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            read_file("../secret.txt")

    def test_read_rejects_absolute_path(self):
        absolute = self.project_root / "memory" / "x.txt"
        absolute.write_text("x")

        with self.assertRaises(ValueError):
            read_file(str(absolute))

    def test_list_files_returns_only_allowed_files(self):
        (self.project_root / "memory" / "a.md").write_text("a")
        (self.project_root / "docs" / "b.py").write_text("b")
        (self.project_root / "tests" / "c.txt").write_text("c")
        (self.project_root / "data" / "secret.txt").write_text("s")
        (self.project_root / ".venv" / "v.py").write_text("v")
        (self.project_root / "memory" / "image.png").write_bytes(b"\x00")

        result = list_files(".")

        self.assertEqual(
            result["files"],
            ["docs/b.py", "memory/a.md", "tests/c.txt"],
        )
        self.assertFalse(result["truncated"])
        self.assertTrue(result["source"]["listed_at"].endswith("Z"))

    def test_list_files_truncates_at_limit(self):
        for index in range(tools.MAX_LIST_RESULTS + 1):
            name = f"{index:04d}.txt"
            (self.project_root / "memory" / name).write_text("x")

        result = list_files("memory")

        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["files"]), tools.MAX_LIST_RESULTS)

    def test_list_files_rejects_missing_directory(self):
        with self.assertRaises(NotADirectoryError):
            list_files("nonexistent")

    def test_list_files_rejects_excluded_directory(self):
        with self.assertRaises(ValueError):
            list_files("data")


class FileToolDispatchTestCase(TempProjectTestCase):
    """Tests for file and calculator tools through execution envelopes."""

    def test_calculate_success_envelope(self):
        envelope = json.loads(
            execute_tool("calculate", '{"expression": "2+2"}')
        )

        execution = envelope["execution"]

        self.assertEqual(execution["status"], "success")
        self.assertEqual(execution["tool"], "calculate")
        self.assertTrue(execution["id"])
        self.assertTrue(execution["started_at"].endswith("Z"))
        self.assertTrue(execution["completed_at"].endswith("Z"))
        self.assertEqual(envelope["result"], 4)

    def test_calculate_error_envelope_for_division_by_zero(self):
        envelope = json.loads(
            execute_tool("calculate", '{"expression": "1/0"}')
        )

        self.assertEqual(envelope["execution"]["status"], "error")
        self.assertEqual(envelope["error"]["type"], "ZeroDivisionError")

    def test_read_file_success_envelope(self):
        write_file("memory/note.md", "Hello")

        envelope = json.loads(
            execute_tool("read_file", '{"path": "memory/note.md"}')
        )

        self.assertEqual(envelope["execution"]["status"], "success")
        self.assertEqual(envelope["execution"]["target"], "memory/note.md")
        self.assertEqual(envelope["result"]["content"], "Hello")

    def test_read_file_error_envelope_for_traversal(self):
        envelope = json.loads(
            execute_tool("read_file", '{"path": "../secret.txt"}')
        )

        self.assertEqual(envelope["execution"]["status"], "error")
        self.assertIn(
            "traversal",
            envelope["error"]["message"],
        )

    def test_write_file_success_envelope(self):
        envelope = json.loads(
            execute_tool(
                "write_file",
                '{"path": "memory/note.md", "content": "Hello"}',
            )
        )

        self.assertEqual(envelope["execution"]["status"], "success")
        self.assertTrue(envelope["result"]["operation"]["verified"])

    def test_missing_arguments_produce_error_envelope(self):
        cases = [
            ("calculate", "{}"),
            ("read_file", '{"path2": "memory/note.md"}'),
            ("read_file", '{"path": "memory/x.txt", "extra": 1}'),
            ("write_file", '{"path": "memory/x.txt"}'),
        ]

        for name, arguments in cases:
            with self.subTest(tool=name, arguments=arguments):
                envelope = json.loads(execute_tool(name, arguments))

                self.assertEqual(envelope["execution"]["status"], "error")
                self.assertEqual(envelope["execution"]["tool"], name)

    def test_invalid_json_produces_error_envelope(self):
        envelope = json.loads(execute_tool("calculate", "not json"))

        self.assertEqual(envelope["execution"]["status"], "error")

    def test_non_object_json_produces_error_envelope(self):
        envelope = json.loads(execute_tool("calculate", '"a string"'))

        self.assertEqual(envelope["execution"]["status"], "error")

    def test_unknown_tool_produces_error_envelope(self):
        envelope = json.loads(
            execute_tool("nonexistent_tool", '{"x": 1}')
        )

        self.assertEqual(envelope["execution"]["status"], "error")
        self.assertIn("Unknown tool", envelope["error"]["message"])


if __name__ == "__main__":
    unittest.main()
