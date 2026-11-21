"""Automated tests for the persistent memory system."""

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest

from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import main

from memory import (
    MemoryRecord,
    get_recent_memories,
    init_database,
    save_memory,
    search_memories,
    update_memory,
)
from memory import database
from tools import execute_tool


class MemoryStoreTestCase(unittest.TestCase):
    """Tests for the memory store against a temporary database."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "araceli.db"
        init_database(self.db_path)

    def tearDown(self):
        self._temp_dir.cleanup()

    def _save_sample(
        self,
        category="fact",
        title="Sample title",
        content="Sample content",
        tags="sample",
        source=None,
    ):
        return save_memory(
            category, title, content, tags, source, db_path=self.db_path
        )

    def test_init_database_creates_schema(self):
        connection = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        finally:
            connection.close()

        self.assertIn("memories", tables)
        self.assertIn("idx_memories_category", indexes)
        self.assertIn("idx_memories_status", indexes)

    def test_init_database_is_idempotent(self):
        init_database(self.db_path)

        self.assertTrue(self.db_path.is_file())

    def test_save_returns_complete_record(self):
        record = self._save_sample(
            source="unit test"
        )

        self.assertIsInstance(record, MemoryRecord)
        self.assertGreaterEqual(record.id, 1)
        self.assertEqual(record.category, "fact")
        self.assertEqual(record.title, "Sample title")
        self.assertEqual(record.content, "Sample content")
        self.assertEqual(record.tags, "sample")
        self.assertEqual(record.status, "active")
        self.assertEqual(record.source, "unit test")
        self.assertTrue(record.created_at.endswith("Z"))
        self.assertTrue(record.updated_at.endswith("Z"))

    def test_save_without_optional_fields(self):
        record = save_memory(
            "preference", "No tags", "No tags here", db_path=self.db_path
        )

        self.assertEqual(record.tags, "")
        self.assertIsNone(record.source)

    def test_save_rejects_duplicate_active_memory(self):
        self._save_sample()

        with self.assertRaises(ValueError) as context:
            self._save_sample()

        self.assertIn("update_memory", str(context.exception))

    def test_save_allows_title_reuse_after_supersede(self):
        first = self._save_sample()
        update_memory(first.id, status="superseded", db_path=self.db_path)

        second = self._save_sample(content="New version")

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(second.status, "active")

    def test_save_rejects_invalid_category(self):
        with self.assertRaises(ValueError):
            self._save_sample(category="invalid_category")

    def test_save_rejects_empty_title(self):
        with self.assertRaises(ValueError):
            self._save_sample(title="   ")

    def test_save_rejects_empty_content(self):
        with self.assertRaises(ValueError):
            self._save_sample(content="")

    def test_save_rejects_oversized_fields(self):
        with self.assertRaises(ValueError):
            self._save_sample(title="x" * 201)

        with self.assertRaises(ValueError):
            self._save_sample(content="x" * 4001)

        with self.assertRaises(ValueError):
            self._save_sample(tags="x" * 201)

    def test_save_rejects_non_string_fields(self):
        with self.assertRaises(ValueError):
            save_memory(123, "Title", "Content", db_path=self.db_path)

    def test_search_matches_title_content_and_tags(self):
        self._save_sample(
            title="Python version",
            content="The project uses Python 3.13.",
            tags="runtime,language",
        )

        for query in ("python", "3.13", "runtime"):
            results = search_memories(query, db_path=self.db_path)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "Python version")

    def test_search_is_case_insensitive_for_ascii(self):
        self._save_sample(title="Keyboard layout", content="Spanish layout")

        results = search_memories("SPANISH", db_path=self.db_path)

        self.assertEqual(len(results), 1)

    def test_search_escapes_like_wildcards(self):
        self._save_sample()

        results = search_memories("%", db_path=self.db_path)

        self.assertEqual(results, [])

    def test_search_filters_by_category(self):
        self._save_sample(category="fact", title="Python release")
        self._save_sample(category="preference", title="Python editor")

        results = search_memories(
            "python", category="preference", db_path=self.db_path
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, "preference")

    def test_search_honors_limit(self):
        for index in range(5):
            self._save_sample(title=f"Repeated fact {index}")

        results = search_memories("repeated", limit=2, db_path=self.db_path)

        self.assertEqual(len(results), 2)

    def test_search_excludes_superseded_by_default(self):
        record = self._save_sample()
        update_memory(record.id, status="superseded", db_path=self.db_path)

        self.assertEqual(
            search_memories("sample", db_path=self.db_path), []
        )

        all_results = search_memories(
            "sample", status="all", db_path=self.db_path
        )

        self.assertEqual(len(all_results), 1)
        self.assertEqual(all_results[0].status, "superseded")

    def test_search_rejects_invalid_query(self):
        with self.assertRaises(ValueError):
            search_memories("", db_path=self.db_path)

        with self.assertRaises(ValueError):
            search_memories("x" * 201, db_path=self.db_path)

        with self.assertRaises(ValueError):
            search_memories("x", category="nope", db_path=self.db_path)

        with self.assertRaises(ValueError):
            search_memories("x", limit=51, db_path=self.db_path)

        with self.assertRaises(ValueError):
            search_memories("x", limit="10", db_path=self.db_path)

    def test_search_on_empty_database(self):
        self.assertEqual(
            search_memories("anything", db_path=self.db_path), []
        )

    def test_update_changes_fields_and_timestamp(self):
        record = self._save_sample()

        updated = update_memory(
            record.id,
            content="Corrected content",
            tags="corrected",
            db_path=self.db_path,
        )

        self.assertEqual(updated.content, "Corrected content")
        self.assertEqual(updated.tags, "corrected")
        self.assertEqual(updated.title, record.title)
        self.assertGreaterEqual(updated.updated_at, record.updated_at)

    def test_update_supersedes_memory(self):
        record = self._save_sample()

        updated = update_memory(
            record.id, status="superseded", db_path=self.db_path
        )

        self.assertEqual(updated.status, "superseded")

    def test_update_reactivates_memory(self):
        record = self._save_sample()
        update_memory(record.id, status="superseded", db_path=self.db_path)

        updated = update_memory(
            record.id, status="active", db_path=self.db_path
        )

        self.assertEqual(updated.status, "active")

    def test_update_rejects_unknown_id(self):
        with self.assertRaises(ValueError):
            update_memory(999, content="Nope", db_path=self.db_path)

    def test_update_rejects_missing_fields(self):
        record = self._save_sample()

        with self.assertRaises(ValueError):
            update_memory(record.id, db_path=self.db_path)

    def test_update_rejects_invalid_values(self):
        record = self._save_sample()

        with self.assertRaises(ValueError):
            update_memory(
                record.id, status="deleted", db_path=self.db_path
            )

        with self.assertRaises(ValueError):
            update_memory(
                record.id, category="invalid_category", db_path=self.db_path
            )

        with self.assertRaises(ValueError):
            update_memory("1", content="Nope", db_path=self.db_path)

    def test_update_rejects_duplicate_creation(self):
        self._save_sample(title="Unique title")
        other = self._save_sample(title="Other title")

        with self.assertRaises(ValueError):
            update_memory(
                other.id, title="Unique title", db_path=self.db_path
            )

    def test_get_recent_orders_by_update_time_and_limits(self):
        first = self._save_sample(title="First memory")
        second = self._save_sample(title="Second memory")

        update_memory(first.id, content="Bumped", db_path=self.db_path)

        recent = get_recent_memories(db_path=self.db_path)

        self.assertEqual(
            [record.id for record in recent],
            [first.id, second.id],
        )

        limited = get_recent_memories(limit=1, db_path=self.db_path)

        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0].id, first.id)

    def test_get_recent_excludes_superseded(self):
        record = self._save_sample()
        update_memory(record.id, status="superseded", db_path=self.db_path)

        self.assertEqual(
            get_recent_memories(db_path=self.db_path), []
        )


class MemoryToolDispatchTestCase(unittest.TestCase):
    """Tests for memory tools through the execution envelope."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "araceli.db"
        init_database(self.db_path)

        patcher = mock.patch.object(
            database,
            "DEFAULT_DB_PATH",
            self.db_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._temp_dir.cleanup()

    def _execute(self, name, arguments):
        envelope = json.loads(execute_tool(name, json.dumps(arguments)))

        return envelope

    def test_save_memory_success_envelope(self):
        envelope = self._execute(
            "save_memory",
            {
                "category": "preference",
                "title": "Editor preference",
                "content": "The user prefers plain editors.",
                "tags": "editor",
                "source": "dispatch test",
            },
        )

        self.assertEqual(envelope["execution"]["status"], "success")
        self.assertEqual(envelope["execution"]["tool"], "save_memory")
        self.assertEqual(
            envelope["result"]["memory"]["title"], "Editor preference"
        )
        self.assertEqual(envelope["result"]["memory"]["status"], "active")

    def test_search_memories_success_envelope(self):
        self._execute(
            "save_memory",
            {
                "category": "fact",
                "title": "Editor preference",
                "content": "The user prefers plain editors.",
            },
        )

        envelope = self._execute(
            "search_memories", {"query": "editor"}
        )

        self.assertEqual(envelope["execution"]["status"], "success")
        self.assertEqual(envelope["result"]["count"], 1)
        self.assertEqual(
            envelope["result"]["memories"][0]["title"],
            "Editor preference",
        )

    def test_update_memory_success_envelope(self):
        save_envelope = self._execute(
            "save_memory",
            {
                "category": "fact",
                "title": "Editor preference",
                "content": "The user prefers plain editors.",
            },
        )

        memory_id = save_envelope["result"]["memory"]["id"]

        envelope = self._execute(
            "update_memory",
            {"memory_id": memory_id, "content": "Updated content."},
        )

        self.assertEqual(envelope["execution"]["status"], "success")
        self.assertEqual(
            envelope["result"]["memory"]["content"], "Updated content."
        )

    def test_save_memory_error_on_duplicate(self):
        arguments = {
            "category": "fact",
            "title": "Editor preference",
            "content": "The user prefers plain editors.",
        }

        self._execute("save_memory", arguments)

        envelope = self._execute("save_memory", arguments)

        self.assertEqual(envelope["execution"]["status"], "error")
        self.assertIn("update_memory", envelope["error"]["message"])

    def test_invalid_arguments_produce_error_envelope(self):
        cases = [
            ("save_memory", {"category": "fact", "title": "No content"}),
            ("save_memory", {"title": "No category"}),
            (
                "save_memory",
                {"category": "fact", "title": "X", "content": "Y", "bogus": 1},
            ),
            ("search_memories", {}),
            ("search_memories", {"query": "x", "bogus": 1}),
            ("update_memory", {}),
            ("update_memory", {"memory_id": 1}),
            ("update_memory", {"memory_id": "1", "content": "X"}),
        ]

        for name, arguments in cases:
            with self.subTest(tool=name, arguments=arguments):
                envelope = self._execute(name, arguments)

                self.assertEqual(envelope["execution"]["status"], "error")
                self.assertEqual(envelope["execution"]["tool"], name)

    def test_unknown_memory_id_produces_error_envelope(self):
        envelope = self._execute(
            "update_memory", {"memory_id": 4242, "content": "Nothing"}
        )

        self.assertEqual(envelope["execution"]["status"], "error")
        self.assertIn("not found", envelope["error"]["message"])


class ToolConsoleVisibilityTestCase(unittest.TestCase):
    """Tests for the console tool execution reporting."""

    def _capture(self, tool_name, result_text):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            main._print_tool_execution(tool_name, result_text)

        return output.getvalue()

    def test_success_line_contains_tool_status_and_target(self):
        envelope = json.dumps(
            {
                "execution": {
                    "id": "abc123",
                    "tool": "save_memory",
                    "status": "success",
                    "target": "Sample title",
                },
                "result": {},
            }
        )

        text = self._capture("save_memory", envelope)

        self.assertIn("[tool] save_memory -> success", text)
        self.assertIn("target: Sample title", text)

    def test_error_line_contains_error_message(self):
        envelope = json.dumps(
            {
                "execution": {
                    "id": "abc123",
                    "tool": "read_file",
                    "status": "error",
                    "target": "../secret.txt",
                },
                "error": {
                    "type": "ValueError",
                    "message": "Parent directory traversal is not allowed.",
                },
            }
        )

        text = self._capture("read_file", envelope)

        self.assertIn("[tool] read_file -> error", text)
        self.assertIn(
            "Parent directory traversal is not allowed.", text
        )

    def test_line_without_target_omits_target_section(self):
        envelope = json.dumps(
            {
                "execution": {
                    "id": "abc123",
                    "tool": "calculate",
                    "status": "success",
                    "target": None,
                },
                "result": 8,
            }
        )

        text = self._capture("calculate", envelope)

        self.assertIn("[tool] calculate -> success", text)
        self.assertNotIn("target", text)

    def test_invalid_result_text_does_not_raise(self):
        text = self._capture("calculate", "not json")

        self.assertIn("[tool] calculate -> unknown", text)


if __name__ == "__main__":
    unittest.main()
