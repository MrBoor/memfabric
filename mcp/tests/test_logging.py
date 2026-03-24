"""Tests for logging to log.txt."""

import logging

import server


class TestLogging:
    def test_remember_logs_to_file(self, isolated_data):
        log_file = isolated_data / "log.txt"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(server._formatter)
        server.logger.addHandler(handler)
        try:
            server.remember("test-topic", "Some content", "2026-03-19")
            log_content = log_file.read_text()
            assert "tool=remember" in log_content
            assert "file=test-topic" in log_content
            assert "is_new=True" in log_content
        finally:
            server.logger.removeHandler(handler)
            handler.close()

    def test_read_memory_not_found_logs_warning(self, isolated_data):
        log_file = isolated_data / "log.txt"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(server._formatter)
        server.logger.addHandler(handler)
        try:
            server.read_memory("nonexistent")
            log_content = log_file.read_text()
            assert "tool=read_memory" in log_content
            assert "not found" in log_content
        finally:
            server.logger.removeHandler(handler)
            handler.close()

    def test_reorganize_logs_summary(self, isolated_data):
        log_file = isolated_data / "log.txt"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(server._formatter)
        server.logger.addHandler(handler)
        try:
            server.remember("a", "content", "2026-03-19")
            server.remember("b", "content", "2026-03-19")
            server.reorganize([{
                "type": "merge",
                "source_files": ["a", "b"],
                "target_filename": "ab",
                "content": "# Merged",
            }])
            log_content = log_file.read_text()
            assert "tool=reorganize" in log_content
            assert "completed=1" in log_content
        finally:
            server.logger.removeHandler(handler)
            handler.close()

    def test_oauth_register_logged(self, isolated_data):
        import asyncio

        log_file = isolated_data / "log.txt"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(server._formatter)
        server.logger.addHandler(handler)
        try:
            from mcp.shared.auth import OAuthClientInformationFull

            provider = server.MemFabricOAuthProvider()
            client = OAuthClientInformationFull(
                client_id="log-test",
                redirect_uris=["http://localhost/cb"],
            )
            asyncio.get_event_loop().run_until_complete(
                provider.register_client(client)
            )
            log_content = log_file.read_text()
            assert "oauth=register" in log_content
        finally:
            server.logger.removeHandler(handler)
            handler.close()

    def test_start_logs(self, isolated_data):
        log_file = isolated_data / "log.txt"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(server._formatter)
        server.logger.addHandler(handler)
        try:
            server.start()
            log_content = log_file.read_text()
            assert "tool=start" in log_content
        finally:
            server.logger.removeHandler(handler)
            handler.close()
