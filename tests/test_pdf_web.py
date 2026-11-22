"""Automated tests for PDF reading and web tools."""

import email.message
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

from tests.test_tools import TempProjectTestCase
from tools import execute_tool, read_pdf, web_search, web_fetch


def _make_pdf(text: str, pages: int = 1) -> bytes:
    """Build a minimal valid PDF containing the given text per page."""

    safe_text = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    stream = f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode(
        "latin-1"
    )

    objects: dict[int, bytes] = {}
    page_ids = list(range(3, 3 + pages))
    content_ids = list(range(3 + pages, 3 + 2 * pages))
    font_id = 3 + 2 * pages

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        "<< /Type /Pages /Kids ["
        + " ".join(f"{page_id} 0 R" for page_id in page_ids)
        + f"] /Count {pages} >>"
    ).encode("latin-1")

    for index, page_id in enumerate(page_ids):
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_ids[index]} 0 R >>"
        ).encode("latin-1")

    for content_id in content_ids:
        objects[content_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\n"
            b"stream\n" + stream + b"\nendstream"
        )

    objects[font_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )

    output = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        output += f"{object_id} 0 obj\n".encode("latin-1")
        output += objects[object_id] + b"\nendobj\n"

    xref_position = len(output)
    total = max(objects) + 1

    output += f"xref\n0 {total}\n".encode("latin-1")
    output += b"0000000000 65535 f \n"

    for object_id in range(1, total):
        output += (
            f"{offsets[object_id]:010d} 00000 n \n".encode("latin-1")
        )

    output += (
        f"trailer\n<< /Size {total} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode("latin-1")

    return bytes(output)


def _make_multipage_pdf(page_texts):
    """Build a valid PDF with a different text per page."""

    streams = [
        f"BT /F1 10 Tf 40 750 Td ({text}) Tj ET".encode("latin-1")
        for text in page_texts
    ]

    objects: dict[int, bytes] = {}
    count = len(streams)
    page_ids = list(range(3, 3 + count))
    content_ids = list(range(3 + count, 3 + 2 * count))
    font_id = 3 + 2 * count

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        "<< /Type /Pages /Kids ["
        + " ".join(f"{page_id} 0 R" for page_id in page_ids)
        + f"] /Count {count} >>"
    ).encode("latin-1")

    for index, page_id in enumerate(page_ids):
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_ids[index]} 0 R >>"
        ).encode("latin-1")

    for index, content_id in enumerate(content_ids):
        stream = streams[index]
        objects[content_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\n"
            b"stream\n" + stream + b"\nendstream"
        )

    objects[font_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )

    output = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        output += f"{object_id} 0 obj\n".encode("latin-1")
        output += objects[object_id] + b"\nendobj\n"

    xref_position = len(output)
    total = max(objects) + 1

    output += f"xref\n0 {total}\n".encode("latin-1")
    output += b"0000000000 65535 f \n"

    for object_id in range(1, total):
        output += (
            f"{offsets[object_id]:010d} 00000 n \n".encode("latin-1")
        )

    output += (
        f"trailer\n<< /Size {total} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode("latin-1")

    return bytes(output)


class PdfReadingTestCase(TempProjectTestCase):
    """Tests for PDF extraction from the private documents directory."""

    def setUp(self):
        super().setUp()
        self.documents_dir = self.project_root / "data" / "documents"
        self.documents_dir.mkdir(parents=True)

    def test_extracts_text_and_source_metadata(self):
        pdf_bytes = _make_pdf("Energy bill 42 kWh")
        (self.documents_dir / "bill.pdf").write_bytes(pdf_bytes)

        result = read_pdf("bill.pdf")

        self.assertIn("Energy bill 42 kWh", result["text"])
        self.assertEqual(result["page_count"], 1)
        self.assertFalse(result["text_truncated"])
        self.assertIsNone(result["note"])
        self.assertEqual(result["path"], "bill.pdf")
        self.assertEqual(result["documents_dir"], "internal")
        self.assertEqual(
            result["source"]["sha256"],
            hashlib.sha256(pdf_bytes).hexdigest(),
        )
        self.assertEqual(
            result["source"]["source_type"],
            "pdf_text_extraction",
        )
        self.assertEqual(result["source"]["documents_dir"], "internal")
        self.assertTrue(result["source"]["extracted_at"].endswith("Z"))

    def test_extracts_multiple_pages(self):
        pdf_bytes = _make_pdf("kWh", pages=3)
        (self.documents_dir / "bill.pdf").write_bytes(pdf_bytes)

        result = read_pdf("bill.pdf")

        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["text"].count("kWh"), 3)

    def test_reports_scanned_document_without_text(self):
        (self.documents_dir / "blank.pdf").write_bytes(_make_pdf(""))

        result = read_pdf("blank.pdf")

        self.assertEqual(result["text"], "")
        self.assertIn("scanned image", result["note"])

    def test_reads_selected_page_ranges(self):
        (self.documents_dir / "doc.pdf").write_bytes(
            _make_multipage_pdf(["Page one", "Page two", "Page three"])
        )

        result = read_pdf("doc.pdf", pages="2-3")

        self.assertEqual(result["pages_read"], [2, 3])
        self.assertIn("Page two", result["text"])
        self.assertIn("Page three", result["text"])
        self.assertNotIn("Page one", result["text"])

    def test_reads_single_page_selection(self):
        (self.documents_dir / "doc.pdf").write_bytes(
            _make_multipage_pdf(["Alpha", "Beta", "Gamma"])
        )

        result = read_pdf("doc.pdf", pages="2")

        self.assertEqual(result["pages_read"], [2])
        self.assertIn("Beta", result["text"])
        self.assertNotIn("Alpha", result["text"])

    def test_rejects_selection_out_of_range(self):
        (self.documents_dir / "doc.pdf").write_bytes(
            _make_multipage_pdf(["Alpha"])
        )

        with self.assertRaises(ValueError):
            read_pdf("doc.pdf", pages="5")

    def test_rejects_invalid_selection_format(self):
        (self.documents_dir / "doc.pdf").write_bytes(
            _make_multipage_pdf(["Alpha"])
        )

        for selection in ("abc", "0", "-2", "1,,2"):
            with self.subTest(selection=selection):
                with self.assertRaises(ValueError):
                    read_pdf("doc.pdf", pages=selection)

    def test_truncation_note_suggests_page_ranges(self):
        long_text = "word " * 6000
        (self.documents_dir / "big.pdf").write_bytes(_make_pdf(long_text))

        result = read_pdf("big.pdf")

        self.assertTrue(result["text_truncated"])
        self.assertIn("pages parameter", result["note"])

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            read_pdf("../bill.pdf")

    def test_rejects_absolute_path(self):
        absolute = self.documents_dir / "bill.pdf"

        with self.assertRaises(ValueError):
            read_pdf(str(absolute))

    def test_rejects_missing_document(self):
        with self.assertRaises(FileNotFoundError):
            read_pdf("missing.pdf")

    def test_rejects_non_pdf_extension(self):
        (self.documents_dir / "notes.txt").write_text("text")

        with self.assertRaises(ValueError):
            read_pdf("notes.txt")

    def test_rejects_oversized_document(self):
        oversized = b"%PDF-1.4" + b"x" * (tools.MAX_PDF_FILE_SIZE + 1)
        (self.documents_dir / "big.pdf").write_bytes(oversized)

        with self.assertRaises(ValueError):
            read_pdf("big.pdf")

    def test_rejects_too_many_pages(self):
        (self.documents_dir / "long.pdf").write_bytes(
            _make_pdf("page", pages=tools.MAX_PDF_PAGES + 1)
        )

        with self.assertRaises(ValueError):
            read_pdf("long.pdf")

    def test_read_pdf_dispatch_success_and_error(self):
        (self.documents_dir / "bill.pdf").write_bytes(
            _make_pdf("Energy bill")
        )

        envelope = json.loads(
            execute_tool("read_pdf", '{"path": "bill.pdf"}')
        )

        self.assertEqual(envelope["execution"]["status"], "success")
        self.assertIn("Energy bill", envelope["result"]["text"])

        error_envelope = json.loads(
            execute_tool("read_pdf", '{"path": "../bill.pdf"}')
        )

        self.assertEqual(error_envelope["execution"]["status"], "error")
        self.assertIn("traversal", error_envelope["error"]["message"])


class DocumentsDirectoryTestCase(TempProjectTestCase):
    """Tests for the external documents directory mechanism."""

    def setUp(self):
        super().setUp()

        self.documents_dir = self.project_root / "data" / "documents"
        self.documents_dir.mkdir(parents=True)

        self._external_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._external_temp.cleanup)
        self.external_dir = Path(self._external_temp.name)

    def _configure_external(self, path_text):
        pointer = self.project_root / "data" / "documents_path.txt"
        pointer.write_text(path_text, encoding="utf-8")

    def test_reads_from_external_configured_directory(self):
        (self.external_dir / "real_bill.pdf").write_bytes(
            _make_pdf("Real external bill")
        )
        self._configure_external(str(self.external_dir))

        result = read_pdf("real_bill.pdf")

        self.assertIn("Real external bill", result["text"])
        self.assertEqual(result["documents_dir"], "external")
        self.assertEqual(result["path"], "real_bill.pdf")

    def test_internal_directory_still_works_alongside_external(self):
        (self.external_dir / "external_bill.pdf").write_bytes(
            _make_pdf("External")
        )
        (self.documents_dir / "internal_bill.pdf").write_bytes(
            _make_pdf("Internal")
        )
        self._configure_external(str(self.external_dir))

        self.assertIn("Internal", read_pdf("internal_bill.pdf")["text"])
        self.assertIn("External", read_pdf("external_bill.pdf")["text"])

    def test_external_takes_priority_on_name_collision(self):
        (self.external_dir / "bill.pdf").write_bytes(_make_pdf("External"))
        (self.documents_dir / "bill.pdf").write_bytes(_make_pdf("Internal"))
        self._configure_external(str(self.external_dir))

        result = read_pdf("bill.pdf")

        self.assertEqual(result["documents_dir"], "external")

    def test_list_documents_combines_both_directories(self):
        (self.external_dir / "a_external.pdf").write_bytes(
            _make_pdf("A")
        )
        (self.external_dir / "notes.txt").write_text("not a pdf")
        (self.documents_dir / "b_internal.pdf").write_bytes(
            _make_pdf("B")
        )
        self._configure_external(str(self.external_dir))

        from tools import list_documents

        result = list_documents()

        self.assertEqual(result["count"], 2)
        self.assertFalse(result["truncated"])

        names = {document["name"] for document in result["documents"]}

        self.assertEqual(names, {"a_external.pdf", "b_internal.pdf"})

        kinds = {
            document["name"]: document["documents_dir"]
            for document in result["documents"]
        }

        self.assertEqual(kinds["a_external.pdf"], "external")
        self.assertEqual(kinds["b_internal.pdf"], "internal")

        self.assertTrue(result["source"]["listed_at"].endswith("Z"))

    def test_list_documents_without_pdfs(self):
        from tools import list_documents

        result = list_documents()

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["documents"], [])

    def test_list_documents_without_pointer_file(self):
        (self.documents_dir / "bill.pdf").write_bytes(_make_pdf("X"))

        from tools import list_documents

        result = list_documents()

        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["documents"][0]["documents_dir"], "internal"
        )

    def test_invalid_pointer_relative_path_raises(self):
        self._configure_external("relative/path")

        with self.assertRaises(ValueError) as context:
            read_pdf("anything.pdf")

        self.assertIn("absolute", str(context.exception))

    def test_invalid_pointer_missing_directory_raises(self):
        self._configure_external(str(self.external_dir / "ghost"))

        with self.assertRaises(ValueError) as context:
            read_pdf("anything.pdf")

        self.assertIn("does not exist", str(context.exception))

    def test_list_documents_dispatch(self):
        (self.documents_dir / "bill.pdf").write_bytes(_make_pdf("X"))

        envelope = json.loads(
            execute_tool("list_documents", "{}")
        )

        self.assertEqual(envelope["execution"]["status"], "success")
        self.assertEqual(envelope["result"]["count"], 1)

        error_envelope = json.loads(
            execute_tool("list_documents", '{"bogus": 1}')
        )

        self.assertEqual(error_envelope["execution"]["status"], "error")

    def test_document_roots_are_deduplicated(self):
        (self.documents_dir / "single.pdf").write_bytes(_make_pdf("X"))

        tools.set_workspace(self.documents_dir)
        self.addCleanup(tools.set_workspace, None)

        from tools import list_documents

        result = list_documents()

        names = [document["name"] for document in result["documents"]]

        self.assertEqual(names.count("single.pdf"), 1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["documents"][0]["documents_dir"], "workspace"
        )

    def test_workspace_is_primary_document_root(self):
        workspace = self.project_root / "my_project"
        workspace.mkdir()
        (workspace / "factura.pdf").write_bytes(_make_pdf("Workspace bill"))

        tools.set_workspace(workspace)
        self.addCleanup(tools.set_workspace, None)

        result = read_pdf("factura.pdf")

        self.assertIn("Workspace bill", result["text"])
        self.assertEqual(result["documents_dir"], "workspace")
        self.assertEqual(result["path"], "factura.pdf")

    def test_workspace_priority_over_documents_dirs(self):
        workspace = self.project_root / "my_project"
        workspace.mkdir()
        (workspace / "bill.pdf").write_bytes(_make_pdf("From workspace"))
        (self.documents_dir / "bill.pdf").write_bytes(
            _make_pdf("From documents")
        )

        tools.set_workspace(workspace)
        self.addCleanup(tools.set_workspace, None)

        result = read_pdf("bill.pdf")

        self.assertIn("From workspace", result["text"])
        self.assertEqual(result["documents_dir"], "workspace")

    def test_documents_dir_fallback_with_active_workspace(self):
        workspace = self.project_root / "my_project"
        workspace.mkdir()

        tools.set_workspace(workspace)
        self.addCleanup(tools.set_workspace, None)

        (self.documents_dir / "internal_bill.pdf").write_bytes(
            _make_pdf("Internal document")
        )

        result = read_pdf("internal_bill.pdf")

        self.assertIn("Internal document", result["text"])
        self.assertEqual(result["documents_dir"], "internal")

    def test_list_documents_includes_workspace_pdfs(self):
        workspace = self.project_root / "my_project"
        workspace.mkdir()
        (workspace / "factura.pdf").write_bytes(_make_pdf("Workspace"))

        tools.set_workspace(workspace)
        self.addCleanup(tools.set_workspace, None)

        from tools import list_documents

        result = list_documents()

        kinds = {
            document["name"]: document["documents_dir"]
            for document in result["documents"]
        }

        self.assertEqual(kinds.get("factura.pdf"), "workspace")

    def test_context_file_is_hidden_and_readable(self):
        workspace = self.project_root / "my_project"
        workspace.mkdir()

        tools.set_workspace(workspace)
        self.addCleanup(tools.set_workspace, None)

        from tools import write_file

        result = write_file(
            ".ARACELI_CONTEXT.md", "# Context\nInitial state."
        )

        self.assertTrue(result["operation"]["verified"])
        self.assertEqual(result["path"], ".ARACELI_CONTEXT.md")


class WebSearchTestCase(unittest.TestCase):
    """Tests for the DuckDuckGo search tool with a mocked engine."""

    def _fake_results(self):
        return [
            {
                "title": "Result A",
                "href": "https://a.example/1",
                "body": "Snippet A",
            },
            {
                "title": "Result B",
                "href": "https://b.example/2",
                "body": "Snippet B",
            },
            {"title": "No URL", "href": "", "body": "Filtered out"},
        ]

    def test_formats_results_with_source_metadata(self):
        with mock.patch.object(tools, "DDGS") as ddgs_class:
            ddgs_class.return_value.text.return_value = self._fake_results()

            result = web_search("generic query", max_results=5)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["query"], "generic query")
        self.assertEqual(
            result["results"][0]["url"], "https://a.example/1"
        )
        self.assertEqual(result["results"][0]["title"], "Result A")
        self.assertEqual(
            result["source"]["source_type"], "web_search"
        )
        self.assertEqual(result["source"]["engine"], "duckduckgo")
        self.assertTrue(result["source"]["searched_at"].endswith("Z"))

        ddgs_class.return_value.text.assert_called_once_with(
            "generic query", max_results=5
        )

    def test_retries_transient_failures(self):
        with mock.patch.object(tools, "DDGS") as ddgs_class, \
                mock.patch("time.sleep"):
            ddgs_class.return_value.text.side_effect = [
                RuntimeError("rate limited"),
                self._fake_results(),
            ]

            result = web_search("generic query")

        self.assertEqual(result["count"], 2)
        self.assertEqual(ddgs_class.return_value.text.call_count, 2)

    def test_raises_after_exhausting_retries(self):
        with mock.patch.object(tools, "DDGS") as ddgs_class, \
                mock.patch("time.sleep"):
            ddgs_class.return_value.text.side_effect = RuntimeError("down")

            with self.assertRaises(RuntimeError) as context:
                web_search("generic query")

        self.assertIn("Web search failed", str(context.exception))

    def test_validates_query_and_max_results(self):
        invalid_cases = [
            {"query": 123},
            {"query": "   "},
            {"query": "x" * (tools.MAX_QUERY_LENGTH + 1)},
            {"query": "valid", "max_results": True},
            {"query": "valid", "max_results": "5"},
            {"query": "valid", "max_results": 0},
            {"query": "valid", "max_results": tools.MAX_WEB_RESULTS + 1},
        ]

        for case in invalid_cases:
            with self.subTest(case=case):
                with mock.patch.object(tools, "DDGS") as ddgs_class:
                    with self.assertRaises(ValueError):
                        web_search(**case)

                    ddgs_class.return_value.text.assert_not_called()

    def test_web_search_dispatch_error_envelope(self):
        envelope = json.loads(
            execute_tool("web_search", '{"query": ""}')
        )

        self.assertEqual(envelope["execution"]["status"], "error")

        envelope = json.loads(
            execute_tool("web_search", '{"query": "x", "bogus": 1}')
        )

        self.assertEqual(envelope["execution"]["status"], "error")


class _FakeResponse:
    """Minimal stand-in for the object returned by urlopen."""

    def __init__(self, body, content_type, url):
        self._body = body
        self._url = url
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type

    def read(self, amount=-1):
        if amount < 0:
            return self._body

        return self._body[:amount]

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


PUBLIC_IP_URL = "https://93.184.216.34/page"

SAMPLE_HTML = (
    "<html><head><title>Sample Page</title>"
    "<style>body { color: red; }</style>"
    "<script>alert('ignored')</script></head>"
    "<body><h1>Heading</h1>"
    "<p>First paragraph.</p>"
    "<p>Second paragraph.</p>"
    "</body></html>"
)


class WebFetchTestCase(unittest.TestCase):
    """Tests for URL validation, HTML extraction, and web_fetch."""

    def test_url_validation_rejects_non_http_schemes(self):
        for url in ("ftp://example.com", "file:///etc/hosts", 123, ""):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    tools._validate_public_http_url(url)

    def test_url_validation_rejects_private_addresses(self):
        for url in (
            "http://192.168.1.1/",
            "http://10.0.0.5/",
            "http://127.0.0.1/",
            "http://localhost/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    tools._validate_public_http_url(url)

    def test_url_validation_rejects_non_standard_ports(self):
        with self.assertRaises(ValueError):
            tools._validate_public_http_url("https://93.184.216.34:8080/")

    def test_url_validation_rejects_missing_host(self):
        with self.assertRaises(ValueError):
            tools._validate_public_http_url("https:///path")

    def test_url_validation_accepts_public_url(self):
        validated = tools._validate_public_http_url(PUBLIC_IP_URL)

        self.assertEqual(validated, PUBLIC_IP_URL)

    def test_html_extractor_skips_scripts_and_styles(self):
        extractor = tools._HTMLTextExtractor()
        extractor.feed(SAMPLE_HTML)

        text = extractor.get_text()

        self.assertEqual(extractor.title.strip(), "Sample Page")
        self.assertIn("Heading", text)
        self.assertIn("First paragraph.", text)
        self.assertIn("Second paragraph.", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("color: red", text)

    def test_web_fetch_returns_page_text_and_metadata(self):
        response = _FakeResponse(
            SAMPLE_HTML.encode("utf-8"),
            "text/html; charset=utf-8",
            PUBLIC_IP_URL,
        )

        with mock.patch(
            "urllib.request.urlopen", return_value=response
        ):
            result = web_fetch(PUBLIC_IP_URL)

        self.assertEqual(result["url"], PUBLIC_IP_URL)
        self.assertEqual(result["title"], "Sample Page")
        self.assertIn("First paragraph.", result["text"])
        self.assertFalse(result["text_truncated"])
        self.assertEqual(
            result["source"]["source_type"], "web_page_fetch"
        )
        self.assertTrue(result["source"]["fetched_at"].endswith("Z"))

    def test_web_fetch_rejects_redirect_to_private_address(self):
        response = _FakeResponse(
            b"<html></html>",
            "text/html",
            "http://192.168.1.1/redirected",
        )

        with mock.patch(
            "urllib.request.urlopen", return_value=response
        ):
            with self.assertRaises(ValueError):
                web_fetch(PUBLIC_IP_URL)

    def test_web_fetch_rejects_unsupported_content_type(self):
        response = _FakeResponse(
            b"binary",
            "application/pdf",
            PUBLIC_IP_URL,
        )

        with mock.patch(
            "urllib.request.urlopen", return_value=response
        ):
            with self.assertRaises(ValueError):
                web_fetch(PUBLIC_IP_URL)

    def test_web_fetch_rejects_oversized_page(self):
        response = _FakeResponse(
            b"x" * (tools.MAX_FETCH_BYTES + 1),
            "text/html",
            PUBLIC_IP_URL,
        )

        with mock.patch(
            "urllib.request.urlopen", return_value=response
        ):
            with self.assertRaises(ValueError):
                web_fetch(PUBLIC_IP_URL)

    def test_web_fetch_rejects_plain_text_truncation_marker(self):
        response = _FakeResponse(
            b"plain content",
            "text/plain",
            PUBLIC_IP_URL,
        )

        with mock.patch(
            "urllib.request.urlopen", return_value=response
        ):
            result = web_fetch(PUBLIC_IP_URL)

        self.assertEqual(result["text"], "plain content")
        self.assertEqual(result["title"], "")

    def test_web_fetch_dispatch_error_envelope(self):
        envelope = json.loads(
            execute_tool("web_fetch", '{"url": "ftp://example.com"}')
        )

        self.assertEqual(envelope["execution"]["status"], "error")
        self.assertIn(
            "Only http and https", envelope["error"]["message"]
        )


class PdfNoiseSuppressionTestCase(unittest.TestCase):
    """pypdf library warnings must not flood the console."""

    def test_pypdf_logger_level_is_error_or_higher(self):
        import logging

        self.assertGreaterEqual(
            logging.getLogger("pypdf").getEffectiveLevel(),
            logging.ERROR,
        )


if __name__ == "__main__":
    unittest.main()
