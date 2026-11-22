"""Automated tests for the project registry and active project section."""

import sys
import tempfile
import unittest

from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import main
import projects

from projects import (
    add_project,
    find_project,
    load_projects,
    read_project_context,
    remove_project,
)


class ProjectRegistryTestCase(unittest.TestCase):
    """Tests for the projects registry stored on disk."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

        self.base = Path(self._temp_dir.name)
        self.registry_path = self.base / "data" / "projects.json"
        self.araceli_root = self.base / "araceli"
        self.araceli_root.mkdir()

        self.project_one = self.base / "RenovacionCasa"
        self.project_two = self.base / "Tesis"
        self.project_one.mkdir()
        self.project_two.mkdir()

    def _patched_root(self):
        patcher = mock.patch.object(projects, "ARACELI_ROOT", self.araceli_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_add_registers_project(self):
        self._patched_root()

        entry = add_project(str(self.project_one), self.registry_path)

        self.assertEqual(entry["name"], "RenovacionCasa")
        self.assertEqual(entry["path"], str(self.project_one.resolve()))
        self.assertTrue(entry["added_at"].endswith("Z"))

        stored = load_projects(self.registry_path)

        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["name"], "RenovacionCasa")

    def test_add_strips_surrounding_quotes(self):
        self._patched_root()

        entry = add_project(
            f'"{self.project_one}"', self.registry_path
        )

        self.assertEqual(entry["name"], "RenovacionCasa")

    def test_add_rejects_relative_path(self):
        self._patched_root()

        with self.assertRaises(ValueError):
            add_project("some/relative/path", self.registry_path)

    def test_add_rejects_missing_directory(self):
        self._patched_root()

        with self.assertRaises(ValueError):
            add_project(str(self.base / "Ghost"), self.registry_path)

    def test_add_rejects_drive_root(self):
        self._patched_root()

        with self.assertRaises(ValueError):
            add_project("D:\\", self.registry_path)

    def test_add_rejects_araceli_root_and_inside(self):
        self._patched_root()

        with self.assertRaises(ValueError):
            add_project(str(self.araceli_root), self.registry_path)

        nested = self.araceli_root / "data" / "something"
        nested.mkdir(parents=True)

        with self.assertRaises(ValueError):
            add_project(str(nested), self.registry_path)

    def test_add_rejects_parent_of_araceli_root(self):
        self._patched_root()

        with self.assertRaises(ValueError):
            add_project(str(self.base), self.registry_path)

    def test_add_rejects_system_directory_names(self):
        self._patched_root()

        windows_dir = self.base / "Windows"
        windows_dir.mkdir()

        with self.assertRaises(ValueError):
            add_project(str(windows_dir), self.registry_path)

    def test_add_rejects_duplicate_path_and_name(self):
        self._patched_root()

        add_project(str(self.project_one), self.registry_path)

        with self.assertRaises(ValueError) as context:
            add_project(str(self.project_one), self.registry_path)

        self.assertIn("already registered", str(context.exception))

        # Duplicate name with a different existing directory.
        same_name = self.base / "other" / "RenovacionCasa"
        same_name.mkdir(parents=True)

        with self.assertRaises(ValueError):
            add_project(str(same_name), self.registry_path)

    def test_remove_project(self):
        self._patched_root()

        add_project(str(self.project_one), self.registry_path)
        add_project(str(self.project_two), self.registry_path)

        removed = remove_project("tesis", self.registry_path)

        self.assertEqual(removed["name"], "Tesis")

        remaining = load_projects(self.registry_path)

        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["name"], "RenovacionCasa")

    def test_remove_unknown_project_raises(self):
        self._patched_root()

        with self.assertRaises(ValueError):
            remove_project("nope", self.registry_path)

    def test_find_project_is_case_insensitive(self):
        self._patched_root()

        add_project(str(self.project_one), self.registry_path)

        entry = find_project("RENOVACIONCASA", self.registry_path)

        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "RenovacionCasa")

        self.assertIsNone(find_project("missing", self.registry_path))

    def test_load_projects_without_registry_file(self):
        self.assertEqual(load_projects(self.registry_path), [])


class ProjectContextTestCase(unittest.TestCase):
    """Tests for reading the ARACELI_CONTEXT.md project context file."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

        self.project_dir = Path(self._temp_dir.name)
        self.entry = {
            "name": self.project_dir.name,
            "path": str(self.project_dir),
            "added_at": "2026-11-21T00:00:00.000Z",
        }

    def test_reads_existing_context(self):
        context_path = self.project_dir / projects.CONTEXT_FILE_NAME
        context_path.write_text(
            "# Project context\n\nProgress so far.", encoding="utf-8"
        )

        content, metadata = read_project_context(self.entry)

        self.assertIn("Progress so far.", content)
        self.assertEqual(metadata["status"], "loaded")
        self.assertEqual(metadata["path"], ".ARACELI_CONTEXT.md")
        self.assertIn("sha256", metadata)
        self.assertTrue(metadata["read_at"].endswith("Z"))

    def test_missing_context_reports_not_found(self):
        content, metadata = read_project_context(self.entry)

        self.assertIsNone(content)
        self.assertEqual(metadata["status"], "not_found")

    def test_empty_context_reports_empty(self):
        context_path = self.project_dir / projects.CONTEXT_FILE_NAME
        context_path.write_text("   ", encoding="utf-8")

        content, metadata = read_project_context(self.entry)

        self.assertIsNone(content)
        self.assertEqual(metadata["status"], "empty")

    def test_oversized_context_reports_oversized(self):
        context_path = self.project_dir / projects.CONTEXT_FILE_NAME
        context_path.write_bytes(
            b"x" * (projects.MAX_CONTEXT_FILE_SIZE + 1)
        )

        content, metadata = read_project_context(self.entry)

        self.assertIsNone(content)
        self.assertEqual(metadata["status"], "oversized")


class ActiveProjectSectionTestCase(unittest.TestCase):
    """Tests for the system prompt section of an active project."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

        self.project_dir = Path(self._temp_dir.name)
        self.entry = {
            "name": "Demo",
            "path": str(self.project_dir),
            "added_at": "2026-11-21T00:00:00.000Z",
        }

    def test_section_contains_project_name_and_instructions(self):
        section = main.build_active_project_section(self.entry)

        self.assertIn("## Active Project — Demo", section)
        self.assertIn(".ARACELI_CONTEXT.md", section)
        self.assertIn("write access covers the entire project", section)
        self.assertIn("working method", section)
        self.assertIn("as compact as possible", section)
        self.assertIn("Prefer general rules over enumerations", section)
        self.assertIn("not derivable from the files", section)
        self.assertIn("Reconciliation needs no permission", section)

    def test_section_includes_context_snapshot(self):
        context_path = (
            self.project_dir / projects.CONTEXT_FILE_NAME
        )
        context_path.write_text(
            "# Context\nStep 3 completed.", encoding="utf-8"
        )

        section = main.build_active_project_section(self.entry)

        self.assertIn("Step 3 completed.", section)
        self.assertIn("Snapshot Read at Activation", section)

    def test_section_without_context_prompts_creation(self):
        section = main.build_active_project_section(self.entry)

        self.assertIn("No usable project context file exists", section)
        self.assertIn("first step", section)


class ProjectInfoCommandTestCase(unittest.TestCase):
    """Tests for the /project info console command."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

        self.base = Path(self._temp_dir.name)
        self.registry_path = self.base / "data" / "projects.json"

        self.araceli_root = self.base / "araceli"
        self.araceli_root.mkdir()

        root_patcher = mock.patch.object(
            projects, "ARACELI_ROOT", self.araceli_root
        )
        root_patcher.start()
        self.addCleanup(root_patcher.stop)

        registry_patcher = mock.patch.object(
            projects, "PROJECTS_FILE", self.registry_path
        )
        registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

        self.project_dir = self.base / "FacLuzGas"
        (self.project_dir / "sub").mkdir(parents=True)
        (self.project_dir / "factura.pdf").write_bytes(b"%PDF-1.4 fake")
        (self.project_dir / "sub" / "result.md").write_text("data")

        self.entry = add_project(str(self.project_dir))

    def test_info_without_active_project(self):
        message, active, changed = main._handle_project_command(
            "/project info", None
        )

        self.assertIn("No active project", message)
        self.assertIn("1 registered", message)
        self.assertIsNone(active)
        self.assertFalse(changed)

    def test_info_active_project_with_context(self):
        context_file = self.project_dir / projects.CONTEXT_FILE_NAME
        context_file.write_text(
            "# Context\n\nWork done: bill analysis.\n"
            "Pending: switch provider.",
            encoding="utf-8",
        )

        message, active, changed = main._handle_project_command(
            "/project info", self.entry
        )

        self.assertIn("Project: FacLuzGas (active)", message)
        self.assertIn(str(self.project_dir), message)
        self.assertIn("Work done: bill analysis.", message)
        self.assertIn("Pending: switch provider.", message)
        self.assertIn("Files: 3", message)
        self.assertIn("(1 PDFs)", message)
        self.assertEqual(active, self.entry)
        self.assertFalse(changed)

    def test_info_active_project_without_context(self):
        message, _, _ = main._handle_project_command(
            "/project info", self.entry
        )

        self.assertIn(projects.CONTEXT_FILE_NAME, message)
        self.assertIn("does not exist yet", message)

    def test_info_by_name_without_activating(self):
        other_dir = self.base / "Other"
        other_dir.mkdir()
        (other_dir / projects.CONTEXT_FILE_NAME).write_text(
            "# Other context", encoding="utf-8"
        )
        add_project(str(other_dir))

        message, active, changed = main._handle_project_command(
            "/project info other", self.entry
        )

        self.assertIn("Project: Other", message)
        self.assertIn("# Other context", message)
        self.assertNotIn("(active)", message)
        self.assertEqual(active, self.entry)
        self.assertFalse(changed)

    def test_info_marks_active_project_by_name(self):
        message, _, _ = main._handle_project_command(
            "/project info facluzgas", self.entry
        )

        self.assertIn("(active)", message)

    def test_info_with_unknown_name(self):
        message, active, changed = main._handle_project_command(
            "/project info ghost", None
        )

        self.assertIn("No project is registered", message)
        self.assertIsNone(active)
        self.assertFalse(changed)


class ProjectLoadUnloadCommandTestCase(unittest.TestCase):
    """Tests for /project load and /project unload command names."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

        self.base = Path(self._temp_dir.name)
        self.registry_path = self.base / "data" / "projects.json"

        self.araceli_root = self.base / "araceli"
        self.araceli_root.mkdir()

        root_patcher = mock.patch.object(
            projects, "ARACELI_ROOT", self.araceli_root
        )
        root_patcher.start()
        self.addCleanup(root_patcher.stop)

        registry_patcher = mock.patch.object(
            projects, "PROJECTS_FILE", self.registry_path
        )
        registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

        self.project_dir = self.base / "Demo"
        self.project_dir.mkdir()

        self.entry = add_project(str(self.project_dir))

    def test_load_activates_project(self):
        message, active, changed = main._handle_project_command(
            "/project load demo", None
        )

        self.assertEqual(active["name"], "Demo")
        self.assertTrue(changed)
        self.assertIn("Active project: Demo", message)

    def test_load_unknown_name_reports_error(self):
        message, active, changed = main._handle_project_command(
            "/project load ghost", None
        )

        self.assertIn("No project is registered", message)
        self.assertIsNone(active)
        self.assertFalse(changed)

    def test_unload_deactivates_project(self):
        message, active, changed = main._handle_project_command(
            "/project unload", self.entry
        )

        self.assertIsNone(active)
        self.assertTrue(changed)
        self.assertIn("Project deactivated: Demo", message)

    def test_unload_without_active_project(self):
        message, active, changed = main._handle_project_command(
            "/project unload", None
        )

        self.assertIn("No active project.", message)
        self.assertIsNone(active)
        self.assertFalse(changed)

    def test_old_command_names_fall_to_usage(self):
        message, _, _ = main._handle_project_command(
            "/project set demo", None
        )

        self.assertIn("Usage:", message)


if __name__ == "__main__":
    unittest.main()
