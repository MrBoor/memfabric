"""Tests for storage helper functions."""

from pathlib import Path

import server


class TestSanitizeFilename:
    def test_basic_kebab_case(self):
        assert server._sanitize_filename("career-goals-2026") == "career-goals-2026"

    def test_strips_md_extension(self):
        assert server._sanitize_filename("about-alex.md") == "about-alex"

    def test_lowercases(self):
        assert server._sanitize_filename("About-Alex") == "about-alex"

    def test_spaces_to_hyphens(self):
        assert server._sanitize_filename("career goals 2026") == "career-goals-2026"

    def test_underscores_to_hyphens(self):
        assert server._sanitize_filename("career_goals_2026") == "career-goals-2026"

    def test_collapses_multiple_hyphens(self):
        assert server._sanitize_filename("career--goals---2026") == "career-goals-2026"

    def test_strips_leading_trailing_hyphens(self):
        assert server._sanitize_filename("-career-goals-") == "career-goals"

    def test_removes_special_characters(self):
        assert server._sanitize_filename("hello!@#world") == "helloworld"

    def test_empty_after_sanitize(self):
        assert server._sanitize_filename("!!!") == ""

    def test_already_clean(self):
        assert (
            server._sanitize_filename("product-pricing-strategy")
            == "product-pricing-strategy"
        )

    def test_mixed_separators(self):
        assert server._sanitize_filename("my file_name") == "my-file-name"


class TestCountEntries:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("")
        assert server._count_entries(f) == 0

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "nope.md"
        assert server._count_entries(f) == 0

    def test_single_entry(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n\n## 2026-03-19\nSome content\n")
        assert server._count_entries(f) == 1

    def test_multiple_entries(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(
            "# Title\n\n## 2026-03-19\nFirst\n\n## 2026-03-20\nSecond\n\n## 2026-03-21\nThird\n"
        )
        assert server._count_entries(f) == 3

    def test_entry_at_start_of_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## 2026-03-19\nContent without a title header\n")
        assert server._count_entries(f) == 1


class TestFirstContentLine:
    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "nope.md"
        assert server._first_content_line(f) == ""

    def test_skips_headers(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n## Date\nActual content here\n")
        assert server._first_content_line(f) == "Actual content here"

    def test_truncates_long_lines(self, tmp_path):
        f = tmp_path / "test.md"
        long_line = "x" * 200
        f.write_text(f"# Title\n{long_line}\n")
        assert len(server._first_content_line(f)) == 100

    def test_empty_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("")
        assert server._first_content_line(f) == ""

    def test_only_headers(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n## Subtitle\n")
        assert server._first_content_line(f) == ""


class TestMemoryPath:
    def test_adds_md_extension(self):
        path = server._memory_path("about-alex")
        assert path.name == "about-alex.md"

    def test_no_double_extension(self):
        path = server._memory_path("about-alex.md")
        assert path.name == "about-alex.md"
