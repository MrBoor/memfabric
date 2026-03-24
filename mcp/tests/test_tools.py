"""Tests for all MCP tool functions."""

import json
from datetime import date

import server

TODAY = date.today().isoformat()


# --- start ---


class TestStart:
    def test_returns_welcome_message(self):
        result = server.start()
        assert isinstance(result, str)
        assert "memory layer" in result.lower()
        assert "call you" in result.lower()


# --- remember ---


class TestRemember:
    def test_create_new_file(self):
        result = server.remember("about-alex", "Name: Alex", TODAY)
        assert result["status"] == "stored"
        assert result["filename"] == "about-alex"
        assert result["is_new_file"] is True
        assert result["entry_count"] == 1

    def test_append_to_existing(self):
        server.remember("about-alex", "Name: Alex", TODAY)
        result = server.remember("about-alex", "Lives in JC", TODAY)
        assert result["is_new_file"] is False
        assert result["entry_count"] == 2

    def test_creates_title_from_filename(self):
        server.remember("career-goals-2026", "Ship things", TODAY)
        content = server.read_memory("career-goals-2026")
        assert content.startswith("# Career Goals 2026")

    def test_entry_includes_date(self):
        server.remember("test-file", "Some content", TODAY)
        content = server.read_memory("test-file")
        assert f"## {TODAY}" in content

    def test_defaults_to_today(self):
        server.remember("test-file", "Some content")
        content = server.read_memory("test-file")
        assert f"## {date.today().isoformat()}" in content

    def test_sanitizes_filename(self):
        result = server.remember("My File Name", "content", TODAY)
        assert result["filename"] == "my-file-name"

    def test_invalid_filename(self):
        result = server.remember("!!!", "content")
        assert "error" in result

    def test_invalid_date_format(self):
        result = server.remember("test-file", "content", "March 19")
        assert "error" in result
        assert "Invalid date format" in result["error"]

    def test_valid_date_format(self):
        result = server.remember("test-file", "content", "2026-01-15")
        assert result["status"] == "stored"
        content = server.read_memory("test-file")
        assert "## 2026-01-15" in content

    def test_increments_status_counter(self):
        server.remember("file-one", "content", TODAY)
        server.remember("file-two", "content", TODAY)
        status = server._read_status()
        assert status["files_since_last_reorganize"] == 2

    def test_append_does_not_increment_counter(self):
        server.remember("file-one", "first", TODAY)
        server.remember("file-one", "second", TODAY)
        status = server._read_status()
        assert status["files_since_last_reorganize"] == 1

    def test_preserves_existing_entries(self):
        server.remember("topic", "Entry one", TODAY)
        server.remember("topic", "Entry two", TODAY)
        content = server.read_memory("topic")
        assert "Entry one" in content
        assert "Entry two" in content


# --- list_memories ---


class TestListMemories:
    def test_empty_memory(self):
        result = server.list_memories()
        assert result == []

    def test_lists_created_files(self):
        server.remember("about-alex", "Name: Alex", TODAY)
        server.remember("career-goals", "Ship things", TODAY)
        result = server.list_memories()
        assert len(result) == 2
        filenames = [m["filename"] for m in result]
        assert "about-alex" in filenames
        assert "career-goals" in filenames

    def test_metadata_fields(self):
        server.remember("about-alex", "Name: Alex", TODAY)
        result = server.list_memories()
        mem = result[0]
        assert "filename" in mem
        assert "entry_count" in mem
        assert "last_updated" in mem
        assert "size_bytes" in mem
        assert "first_line" in mem

    def test_entry_count_accurate(self):
        server.remember("topic", "First", TODAY)
        server.remember("topic", "Second", TODAY)
        server.remember("topic", "Third", TODAY)
        result = server.list_memories()
        assert result[0]["entry_count"] == 3

    def test_first_line_content(self):
        server.remember("topic", "Source: conversation\nThe actual insight.", TODAY)
        result = server.list_memories()
        assert result[0]["first_line"].startswith("Source: conversation")

    def test_sorted_alphabetically(self):
        server.remember("zebra-facts", "Stripes", TODAY)
        server.remember("apple-recipes", "Pie", TODAY)
        result = server.list_memories()
        assert result[0]["filename"] == "apple-recipes"
        assert result[1]["filename"] == "zebra-facts"


# --- read_memory ---


class TestReadMemory:
    def test_reads_existing_file(self):
        server.remember("about-alex", "Name: Alex", TODAY)
        content = server.read_memory("about-alex")
        assert "Name: Alex" in content

    def test_file_not_found(self):
        result = server.read_memory("nonexistent")
        assert "Error" in result
        assert "not found" in result

    def test_handles_md_extension_in_input(self):
        server.remember("about-alex", "Name: Alex", TODAY)
        content = server.read_memory("about-alex.md")
        assert "Name: Alex" in content


# --- read_all_memories ---


class TestReadAllMemories:
    def test_empty(self):
        result = server.read_all_memories()
        assert result == "No memories stored yet."

    def test_returns_all_files(self):
        server.remember("topic-a", "Content A", TODAY)
        server.remember("topic-b", "Content B", TODAY)
        result = server.read_all_memories()
        assert "=== topic-a ===" in result
        assert "=== topic-b ===" in result
        assert "Content A" in result
        assert "Content B" in result


# --- update_memory ---


class TestUpdateMemory:
    def test_overwrites_content(self):
        server.remember("about-alex", "Lives in JC", TODAY)
        result = server.update_memory("about-alex", "# About Alex\n\nMoved to Berlin.")
        assert result["status"] == "updated"
        content = server.read_memory("about-alex")
        assert "Berlin" in content
        assert "JC" not in content

    def test_returns_new_size(self):
        server.remember("about-alex", "content", TODAY)
        result = server.update_memory("about-alex", "new content")
        assert result["size_bytes"] == len("new content")

    def test_file_not_found(self):
        result = server.update_memory("nonexistent", "content")
        assert "error" in result

    def test_invalid_filename(self):
        result = server.update_memory("!!!", "content")
        assert "error" in result


# --- get_rules / edit_rules ---


class TestRules:
    def test_default_rules(self):
        rules = server.get_rules()
        assert "is_onboarded: false" in rules
        assert "Memory Rules" in rules

    def test_edit_rules(self):
        new_rules = "# Custom Rules\nis_onboarded: true\n"
        result = server.edit_rules(new_rules)
        assert result["status"] == "rules_updated"
        assert result["size_bytes"] > 0
        assert server.get_rules() == new_rules

    def test_rules_persist(self):
        server.edit_rules("# Updated\nis_onboarded: true\n")
        assert "is_onboarded: true" in server.get_rules()


# --- get_status ---


class TestGetStatus:
    def test_empty_status(self):
        status = server.get_status()
        assert status["total_files"] == 0
        assert status["files_since_last_reorganize"] == 0
        assert status["reorganize_threshold"] == 10
        assert status["total_memory_size_bytes"] == 0
        assert status["largest_files"] == []
        assert status["oldest_untouched_files"] == []

    def test_tracks_file_count(self):
        server.remember("file-one", "content", TODAY)
        server.remember("file-two", "content", TODAY)
        status = server.get_status()
        assert status["total_files"] == 2
        assert status["files_since_last_reorganize"] == 2

    def test_largest_files(self):
        server.remember("small", "x", TODAY)
        server.remember("big", "x" * 1000, TODAY)
        status = server.get_status()
        assert status["largest_files"][0]["name"] == "big"

    def test_caps_at_five(self):
        for i in range(8):
            server.remember(f"file-{i}", f"content-{i}", TODAY)
        status = server.get_status()
        assert len(status["largest_files"]) == 5
        assert len(status["oldest_untouched_files"]) == 5

    def test_total_size(self):
        server.remember("file-one", "hello", TODAY)
        status = server.get_status()
        assert status["total_memory_size_bytes"] > 0


# --- reorganize ---


class TestReorganize:
    # -- merge --

    def test_merge(self):
        server.remember("topic-a", "Content A", TODAY)
        server.remember("topic-b", "Content B", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "merge",
                    "source_files": ["topic-a", "topic-b"],
                    "target_filename": "topic-combined",
                    "content": "# Combined\n\nMerged content from A and B.",
                }
            ]
        )
        assert result["operations_completed"] == 1
        assert "topic-combined" in result["files_created"]
        assert "topic-a" in result["files_deleted"]
        assert "topic-b" in result["files_deleted"]
        assert "Merged content" in server.read_memory("topic-combined")
        assert "not found" in server.read_memory("topic-a")

    def test_merge_target_is_source(self):
        server.remember("topic-a", "Content A", TODAY)
        server.remember("topic-b", "Content B", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "merge",
                    "source_files": ["topic-a", "topic-b"],
                    "target_filename": "topic-a",
                    "content": "# Merged\n\nAll content.",
                }
            ]
        )
        assert result["operations_completed"] == 1
        # topic-a should still exist (it's the target)
        assert "not found" not in server.read_memory("topic-a")
        # topic-b should be deleted
        assert "not found" in server.read_memory("topic-b")

    def test_merge_missing_source(self):
        server.remember("topic-a", "Content A", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "merge",
                    "source_files": ["topic-a", "nonexistent"],
                    "target_filename": "merged",
                    "content": "content",
                }
            ]
        )
        assert result["operations_completed"] == 0
        assert len(result["errors"]) == 1

    def test_merge_less_than_two_sources(self):
        server.remember("topic-a", "Content A", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "merge",
                    "source_files": ["topic-a"],
                    "target_filename": "merged",
                    "content": "content",
                }
            ]
        )
        assert result["operations_completed"] == 0
        assert len(result["errors"]) == 1

    # -- split --

    def test_split(self):
        server.remember("big-topic", "Pricing and hiring mixed", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "split",
                    "source_file": "big-topic",
                    "new_files": {
                        "pricing-decisions": "# Pricing\n\nCharge per seat.",
                        "hiring-strategy": "# Hiring\n\nLook for generalists.",
                    },
                }
            ]
        )
        assert result["operations_completed"] == 1
        assert "pricing-decisions" in result["files_created"]
        assert "hiring-strategy" in result["files_created"]
        assert "big-topic" in result["files_deleted"]
        assert "not found" in server.read_memory("big-topic")
        assert "per seat" in server.read_memory("pricing-decisions")

    def test_split_missing_source(self):
        result = server.reorganize(
            [
                {
                    "type": "split",
                    "source_file": "nonexistent",
                    "new_files": {"a": "content"},
                }
            ]
        )
        assert result["operations_completed"] == 0
        assert len(result["errors"]) == 1

    # -- synthesize --

    def test_synthesize(self):
        server.remember("pricing", "Charge per seat", TODAY)
        server.remember("audience", "Target AI practitioners", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "synthesize",
                    "source_files": ["pricing", "audience"],
                    "target_filename": "pattern-value-pricing",
                    "content": "# Pattern\n\nValue-based pricing for AI audience.",
                }
            ]
        )
        assert result["operations_completed"] == 1
        assert "pattern-value-pricing" in result["files_created"]
        assert result["files_deleted"] == []
        # Source files preserved
        assert "not found" not in server.read_memory("pricing")
        assert "not found" not in server.read_memory("audience")

    def test_synthesize_missing_source(self):
        server.remember("pricing", "content", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "synthesize",
                    "source_files": ["pricing", "nonexistent"],
                    "target_filename": "pattern",
                    "content": "content",
                }
            ]
        )
        assert result["operations_completed"] == 0
        assert len(result["errors"]) == 1

    # -- rename --

    def test_rename(self):
        server.remember("old-name", "Some content", TODAY)
        original = server.read_memory("old-name")
        result = server.reorganize(
            [
                {
                    "type": "rename",
                    "old_filename": "old-name",
                    "new_filename": "new-name",
                }
            ]
        )
        assert result["operations_completed"] == 1
        assert result["files_renamed"] == [{"from": "old-name", "to": "new-name"}]
        assert "not found" in server.read_memory("old-name")
        assert server.read_memory("new-name") == original

    def test_rename_missing_source(self):
        result = server.reorganize(
            [
                {
                    "type": "rename",
                    "old_filename": "nonexistent",
                    "new_filename": "new-name",
                }
            ]
        )
        assert result["operations_completed"] == 0
        assert len(result["errors"]) == 1

    # -- general --

    def test_unknown_operation(self):
        result = server.reorganize([{"type": "delete"}])
        assert result["operations_completed"] == 0
        assert len(result["errors"]) == 1

    def test_multiple_operations(self):
        server.remember("a", "content-a", TODAY)
        server.remember("b", "content-b", TODAY)
        server.remember("c", "content-c", TODAY)
        result = server.reorganize(
            [
                {
                    "type": "merge",
                    "source_files": ["a", "b"],
                    "target_filename": "ab-merged",
                    "content": "# Merged\n\nA and B together.",
                },
                {
                    "type": "rename",
                    "old_filename": "c",
                    "new_filename": "c-renamed",
                },
            ]
        )
        assert result["operations_completed"] == 2

    def test_resets_status_counter(self):
        server.remember("file-one", "content", TODAY)
        server.remember("file-two", "content", TODAY)
        assert server._read_status()["files_since_last_reorganize"] == 2
        server.reorganize(
            [
                {
                    "type": "rename",
                    "old_filename": "file-one",
                    "new_filename": "file-one-renamed",
                }
            ]
        )
        status = server._read_status()
        assert status["files_since_last_reorganize"] == 0
        assert status["last_reorganize_date"] == date.today().isoformat()

    def test_empty_operations_list(self):
        result = server.reorganize([])
        assert result["operations_completed"] == 0
        assert result["errors"] == []
