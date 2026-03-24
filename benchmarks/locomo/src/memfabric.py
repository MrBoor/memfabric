"""MemFabric local implementation for benchmarking.

Plain Python functions that replicate the MCP server's memory tools.
No server, no protocol — just files on disk + tool definitions for the LLM.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime


def _sanitize_filename(filename: str) -> str:
    """Sanitize a filename to kebab-case, matching the production server."""
    name = filename.removesuffix(".md") if hasattr(filename, "removesuffix") else filename.replace(".md", "")
    sanitized = ""
    for c in name.lower():
        if c.isalnum() or c == "-":
            sanitized += c
        elif c in (" ", "_"):
            sanitized += "-"
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized.strip("-")


def _content_preview(content: str, num_lines: int = 2) -> str:
    """Get first N non-header, non-empty lines from content as preview."""
    lines = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped[:120])
            if len(lines) >= num_lines:
                break
    return " | ".join(lines) if lines else ""


def _count_entries(content: str) -> int:
    """Count ## dated entries in content."""
    count = content.count("\n## ")
    if content.startswith("## "):
        count += 1
    return count


class MemFabricLocal:
    """Local implementation of MemFabric memory tools.

    Memory lives in plain Markdown files with descriptive kebab-case names.
    The LLM picks which files to read based on filenames alone.
    """

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        os.makedirs(memory_dir, exist_ok=True)

    def list_memories(self) -> list[dict]:
        """Returns list of memory files with metadata for the LLM to scan."""
        results = []
        for f in sorted(os.listdir(self.memory_dir)):
            if not f.endswith(".md"):
                continue
            path = os.path.join(self.memory_dir, f)
            stat = os.stat(path)
            content = open(path).read()
            results.append(
                {
                    "filename": f.replace(".md", ""),
                    "entry_count": _count_entries(content),
                    "last_updated": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                    "size_bytes": stat.st_size,
                    "preview": _content_preview(content),
                }
            )
        return results

    def read_memory(self, filename: str | None = None, filenames: list[str] | None = None) -> str:
        """Returns full contents of one or more memory files."""
        names = filenames or ([filename] if filename else [])
        if not names:
            return "Error: provide filename or filenames."

        parts = []
        for name in names:
            safe = _sanitize_filename(name)
            path = os.path.join(self.memory_dir, f"{safe}.md")
            if not os.path.exists(path):
                parts.append(f"=== {safe} ===\nError: Memory file '{safe}.md' not found.")
                continue
            content = open(path).read()
            if len(content) > 25000:
                content = content[:25000] + "\n\n[Truncated — file exceeds 25,000 characters]"
            if len(names) > 1:
                parts.append(f"=== {safe} ===\n{content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)

    def remember(self, filename: str, content: str, entry_date: str | None = None, new_filename: str | None = None) -> dict:
        """Appends a dated entry to a memory file. Creates file with title if new.
        Optionally renames the file if new_filename is provided."""
        safe = _sanitize_filename(filename)
        if not safe:
            return {"error": "Invalid filename"}
        path = os.path.join(self.memory_dir, f"{safe}.md")
        date = entry_date or datetime.now().strftime("%Y-%m-%d")
        is_new = not os.path.exists(path)

        # Strip leading ## date header if the LLM included one in content
        # (we add our own ## date header, so this prevents duplicates)
        stripped = content.lstrip()
        if stripped.startswith("## "):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                content = stripped[first_newline + 1:]
            else:
                content = stripped[3:]

        entry = f"\n## {date}\n{content}\n"

        if is_new:
            title = safe.replace("-", " ").title()
            with open(path, "w") as f:
                f.write(f"# {title}\n{entry}")
        else:
            with open(path, "a") as f:
                f.write(entry)

        # Rename if new_filename provided
        renamed_from = None
        if new_filename and not is_new:
            new_safe = _sanitize_filename(new_filename)
            if new_safe and new_safe != safe:
                new_path = os.path.join(self.memory_dir, f"{new_safe}.md")
                os.rename(path, new_path)
                renamed_from = safe
                safe = new_safe

        entry_count = _count_entries(open(os.path.join(self.memory_dir, f"{safe}.md")).read())
        result = {
            "status": "stored",
            "filename": safe,
            "is_new_file": is_new,
            "entry_count": entry_count,
            "all_files": self._file_summary(),
        }
        if renamed_from:
            result["renamed_from"] = renamed_from
        return result

    def update_memory(self, filename: str, content: str) -> dict:
        """Replaces entire file content. Use when ground truth has changed."""
        safe = _sanitize_filename(filename)
        if not safe:
            return {"error": "Invalid filename"}
        path = os.path.join(self.memory_dir, f"{safe}.md")
        if not os.path.exists(path):
            return {"error": f"Memory file '{safe}.md' not found. Use remember() to create new files."}
        with open(path, "w") as f:
            f.write(content)
        return {
            "status": "updated",
            "filename": safe,
            "size_bytes": os.path.getsize(path),
            "all_files": self._file_summary(),
        }

    def _file_summary(self) -> list[dict]:
        """Returns compact summary of all files with sizes for write responses."""
        summary = []
        for f in sorted(os.listdir(self.memory_dir)):
            if not f.endswith(".md"):
                continue
            size = os.path.getsize(os.path.join(self.memory_dir, f))
            entry = {"filename": f.replace(".md", ""), "size_bytes": size}
            if size > 3072:
                entry["warning"] = "File exceeds 3KB — consider: (1) rewriting with update_memory() to condense without losing facts, or (2) splitting into focused sub-files with reorganize()"
            summary.append(entry)
        return summary

    def get_status(self) -> dict:
        """Returns memory system status for reorganization decisions."""
        files = [f for f in os.listdir(self.memory_dir) if f.endswith(".md")]
        total_size = 0
        file_stats = []
        for f in files:
            path = os.path.join(self.memory_dir, f)
            stat = os.stat(path)
            content = open(path).read()
            total_size += stat.st_size
            file_stats.append({
                "name": f.replace(".md", ""),
                "entries": _count_entries(content),
                "bytes": stat.st_size,
                "last_updated": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
            })

        largest = sorted(file_stats, key=lambda x: x["bytes"], reverse=True)[:5]
        return {
            "total_files": len(files),
            "total_memory_size_bytes": total_size,
            "largest_files": [
                {"name": f["name"], "entries": f["entries"], "bytes": f["bytes"]}
                for f in largest
            ],
        }

    def reorganize(self, operations: list[dict]) -> dict:
        """Merge, split, synthesize, rename, or delete memory files."""
        results = {
            "operations_completed": 0,
            "files_created": [],
            "files_deleted": [],
            "files_renamed": [],
            "errors": [],
        }

        for op in operations:
            op_type = op.get("type", "").lower()

            if op_type == "merge":
                source_files = op.get("source_files", op.get("sources", []))
                target = _sanitize_filename(op.get("target_filename", op.get("target", "")))
                content = op.get("content", "")
                if not target or not content or len(source_files) < 2:
                    results["errors"].append("Merge: need target, content, and at least 2 sources")
                    continue
                target_path = os.path.join(self.memory_dir, f"{target}.md")
                with open(target_path, "w") as f:
                    f.write(content)
                results["files_created"].append(target)
                for src in source_files:
                    src_safe = _sanitize_filename(src)
                    src_path = os.path.join(self.memory_dir, f"{src_safe}.md")
                    if os.path.exists(src_path) and src_safe != target:
                        os.remove(src_path)
                        results["files_deleted"].append(src_safe)
                results["operations_completed"] += 1

            elif op_type == "split":
                source = _sanitize_filename(op.get("source_file", op.get("source", "")))
                new_files = op.get("new_files", op.get("targets", []))
                src_path = os.path.join(self.memory_dir, f"{source}.md")
                if not os.path.exists(src_path):
                    results["errors"].append(f"Split: '{source}.md' not found")
                    continue
                if isinstance(new_files, dict):
                    for fname, fcontent in new_files.items():
                        safe = _sanitize_filename(fname)
                        with open(os.path.join(self.memory_dir, f"{safe}.md"), "w") as f:
                            f.write(fcontent)
                        results["files_created"].append(safe)
                elif isinstance(new_files, list):
                    for target in new_files:
                        safe = _sanitize_filename(target.get("filename", ""))
                        with open(os.path.join(self.memory_dir, f"{safe}.md"), "w") as f:
                            f.write(target.get("content", ""))
                        results["files_created"].append(safe)
                os.remove(src_path)
                results["files_deleted"].append(source)
                results["operations_completed"] += 1

            elif op_type == "synthesize":
                source_files = op.get("source_files", [])
                target = _sanitize_filename(op.get("target_filename", ""))
                content = op.get("content", "")
                if not target or not content or not source_files:
                    results["errors"].append("Synthesize: need source_files, target, and content")
                    continue
                target_path = os.path.join(self.memory_dir, f"{target}.md")
                with open(target_path, "w") as f:
                    f.write(content)
                results["files_created"].append(target)
                # synthesize keeps source files (unlike merge)
                results["operations_completed"] += 1

            elif op_type == "rename":
                old = _sanitize_filename(op.get("old_filename", op.get("old_name", "")))
                new = _sanitize_filename(op.get("new_filename", op.get("new_name", "")))
                old_path = os.path.join(self.memory_dir, f"{old}.md")
                new_path = os.path.join(self.memory_dir, f"{new}.md")
                if os.path.exists(old_path):
                    os.rename(old_path, new_path)
                    results["files_renamed"].append({"from": old, "to": new})
                    results["operations_completed"] += 1
                else:
                    results["errors"].append(f"Rename: '{old}.md' not found")

            elif op_type == "delete":
                fname = _sanitize_filename(op.get("filename", ""))
                path = os.path.join(self.memory_dir, f"{fname}.md")
                if os.path.exists(path):
                    os.remove(path)
                    results["files_deleted"].append(fname)
                    results["operations_completed"] += 1

            else:
                results["errors"].append(f"Unknown operation type: '{op_type}'")

        return results

    def execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Dispatch a tool call to the appropriate method. Returns JSON string."""
        if tool_name == "list_memories":
            result = self.list_memories()
        elif tool_name == "read_memory":
            result = self.read_memory(
                filename=tool_input.get("filename"),
                filenames=tool_input.get("filenames"),
            )
        elif tool_name == "remember":
            result = self.remember(
                tool_input["filename"],
                tool_input["content"],
                tool_input.get("entry_date"),
                tool_input.get("new_filename"),
            )
        elif tool_name == "update_memory":
            result = self.update_memory(tool_input["filename"], tool_input["content"])
        elif tool_name == "get_status":
            result = self.get_status()
        elif tool_name == "reorganize":
            result = self.reorganize(tool_input["operations"])
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else result


# Backwards-compatible re-export: tools now live in src/versions.py
from .versions import get_version as _get_version

MEMORY_TOOLS = _get_version().tools
