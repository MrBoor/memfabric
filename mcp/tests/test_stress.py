"""Stress tests with 100+ memory files to verify performance and correctness at scale."""

import time
from datetime import date, timedelta

import server

TODAY = date.today().isoformat()


class TestStressMemoryFiles:
    def test_create_150_files(self):
        for i in range(150):
            result = server.remember(
                f"topic-{i:03d}-stress-test",
                f"Content for topic {i}. This simulates real memory entries.",
                TODAY,
            )
            assert result["status"] == "stored"
            assert result["is_new_file"] is True

        memories = server.list_memories()
        assert len(memories) == 150

    def test_list_memories_performance_at_scale(self):
        for i in range(200):
            server.remember(
                f"perf-file-{i:03d}",
                f"Entry content number {i} with some realistic text length.",
                TODAY,
            )

        start = time.perf_counter()
        memories = server.list_memories()
        elapsed = time.perf_counter() - start

        assert len(memories) == 200
        assert elapsed < 2.0, f"list_memories took {elapsed:.2f}s for 200 files"

    def test_get_status_at_scale(self):
        for i in range(120):
            server.remember(f"status-file-{i:03d}", f"Content {i}", TODAY)

        start = time.perf_counter()
        status = server.get_status()
        elapsed = time.perf_counter() - start

        assert status["total_files"] == 120
        assert status["files_since_last_reorganize"] == 120
        assert len(status["largest_files"]) == 5
        assert len(status["oldest_untouched_files"]) == 5
        assert status["total_memory_size_bytes"] > 0
        assert elapsed < 2.0, f"get_status took {elapsed:.2f}s for 120 files"

    def test_many_entries_single_file(self):
        for i in range(100):
            server.remember(
                "single-large-file",
                f"Entry {i}: This is a longer entry to simulate real usage with "
                f"enough text to make the file grow substantially over time.",
                (date.today() + timedelta(days=i)).isoformat(),
            )

        content = server.read_memory("single-large-file")
        assert content.count("\n## ") == 100

        memories = server.list_memories()
        assert memories[0]["entry_count"] == 100

    def test_read_write_cycle_at_scale(self):
        filenames = []
        for i in range(100):
            name = f"cycle-file-{i:03d}"
            server.remember(name, f"Original content {i}", TODAY)
            filenames.append(name)

        for name in filenames:
            content = server.read_memory(name)
            assert "Original content" in content

        for name in filenames[:50]:
            server.update_memory(name, f"# Updated\n\nNew content for {name}")

        for name in filenames[:50]:
            content = server.read_memory(name)
            assert "New content" in content
            assert "Original content" not in content

        for name in filenames[50:]:
            content = server.read_memory(name)
            assert "Original content" in content

    def test_reorganize_at_scale(self):
        for i in range(20):
            server.remember(f"reorg-{i:02d}", f"Content {i}", TODAY)

        # Merge 5 pairs
        merge_ops = []
        for i in range(0, 10, 2):
            merge_ops.append({
                "type": "merge",
                "source_files": [f"reorg-{i:02d}", f"reorg-{i + 1:02d}"],
                "target_filename": f"reorg-merged-{i:02d}-{i + 1:02d}",
                "content": f"# Merged {i} and {i + 1}\n\nCombined content.",
            })

        result = server.reorganize(merge_ops)
        assert result["operations_completed"] == 5
        assert len(result["files_created"]) == 5
        assert len(result["files_deleted"]) == 10
        assert result["errors"] == []

        # Split 2 files
        split_ops = []
        for i in range(10, 12):
            split_ops.append({
                "type": "split",
                "source_file": f"reorg-{i:02d}",
                "new_files": {
                    f"reorg-{i:02d}-part-a": f"# Part A of {i}\n\nFirst half.",
                    f"reorg-{i:02d}-part-b": f"# Part B of {i}\n\nSecond half.",
                },
            })

        result = server.reorganize(split_ops)
        assert result["operations_completed"] == 2
        assert len(result["files_created"]) == 4
        assert len(result["files_deleted"]) == 2

        # Synthesize across remaining files
        result = server.reorganize([{
            "type": "synthesize",
            "source_files": [f"reorg-{i:02d}" for i in range(12, 15)],
            "target_filename": "reorg-pattern-insight",
            "content": "# Pattern Insight\n\nA pattern found across files 12-14.",
        }])
        assert result["operations_completed"] == 1
        # Source files still exist
        for i in range(12, 15):
            assert "not found" not in server.read_memory(f"reorg-{i:02d}")

        # Rename a few
        rename_ops = [
            {
                "type": "rename",
                "old_filename": f"reorg-{i:02d}",
                "new_filename": f"reorg-renamed-{i:02d}",
            }
            for i in range(15, 18)
        ]
        result = server.reorganize(rename_ops)
        assert result["operations_completed"] == 3

        # Verify final state is consistent
        memories = server.list_memories()
        filenames = [m["filename"] for m in memories]
        # Merged sources gone
        for i in range(0, 10):
            assert f"reorg-{i:02d}" not in filenames
        # Merged targets exist
        for i in range(0, 10, 2):
            assert f"reorg-merged-{i:02d}-{i + 1:02d}" in filenames
        # Split sources gone, parts exist
        for i in range(10, 12):
            assert f"reorg-{i:02d}" not in filenames
            assert f"reorg-{i:02d}-part-a" in filenames
            assert f"reorg-{i:02d}-part-b" in filenames
        # Synthesize sources still present, synthesis exists
        assert "reorg-pattern-insight" in filenames
        # Renamed files
        for i in range(15, 18):
            assert f"reorg-{i:02d}" not in filenames
            assert f"reorg-renamed-{i:02d}" in filenames

    def test_filename_uniqueness_at_scale(self):
        for i in range(100):
            server.remember(f"unique-{i:03d}", f"Content {i}", TODAY)

        memories = server.list_memories()
        filenames = [m["filename"] for m in memories]
        assert len(filenames) == len(set(filenames)), "Duplicate filenames found"
