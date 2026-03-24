"""Tests for OAuth and token auth."""

import asyncio
import time

import pytest
from starlette.testclient import TestClient

import server
from mcp.shared.auth import OAuthClientInformationFull


@pytest.fixture
def oauth_provider():
    return server.MemFabricOAuthProvider()


class TestStaticTokenAuth:
    def test_static_token_accepted(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "test-secret")
        result = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_access_token("test-secret")
        )
        assert result is not None
        assert result.client_id == "static"

    def test_wrong_token_rejected(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "test-secret")
        result = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_access_token("wrong-token")
        )
        assert result is None

    def test_no_token_configured(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "")
        result = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_access_token("anything")
        )
        assert result is None


class TestOAuthProvider:
    def test_register_and_get_client(self, oauth_provider):
        from mcp.shared.auth import OAuthClientInformationFull

        client = OAuthClientInformationFull(
            client_id="test-client-id",
            client_secret="test-secret",
            redirect_uris=["http://localhost/callback"],
        )
        asyncio.get_event_loop().run_until_complete(
            oauth_provider.register_client(client)
        )
        result = asyncio.get_event_loop().run_until_complete(
            oauth_provider.get_client("test-client-id")
        )
        assert result is not None
        assert result.client_id == "test-client-id"

    def test_get_unknown_client(self, oauth_provider):
        result = asyncio.get_event_loop().run_until_complete(
            oauth_provider.get_client("nonexistent")
        )
        assert result is None

    def test_authorize_returns_redirect(self, oauth_provider):
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull

        client = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["http://localhost/callback"],
        )
        params = AuthorizationParams(
            state="test-state",
            scopes=[],
            code_challenge="test-challenge",
            redirect_uri="http://localhost/callback",
            redirect_uri_provided_explicitly=True,
        )
        redirect_url = asyncio.get_event_loop().run_until_complete(
            oauth_provider.authorize(client, params)
        )
        assert "http://localhost/callback" in redirect_url
        assert "code=" in redirect_url
        assert "state=test-state" in redirect_url

    def test_full_token_flow(self, oauth_provider):
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull

        client = OAuthClientInformationFull(
            client_id="flow-client",
            redirect_uris=["http://localhost/callback"],
        )
        asyncio.get_event_loop().run_until_complete(
            oauth_provider.register_client(client)
        )

        # Authorize
        params = AuthorizationParams(
            state="s1",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="http://localhost/callback",
            redirect_uri_provided_explicitly=True,
        )
        redirect_url = asyncio.get_event_loop().run_until_complete(
            oauth_provider.authorize(client, params)
        )
        # Extract code from redirect URL
        from urllib.parse import parse_qs, urlparse

        code = parse_qs(urlparse(redirect_url).query)["code"][0]

        # Load auth code
        auth_code = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_authorization_code(client, code)
        )
        assert auth_code is not None
        assert auth_code.code == code

        # Exchange for token
        token = asyncio.get_event_loop().run_until_complete(
            oauth_provider.exchange_authorization_code(client, auth_code)
        )
        assert token.access_token
        assert token.refresh_token
        assert token.token_type == "Bearer"

        # Auth code consumed
        auth_code_again = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_authorization_code(client, code)
        )
        assert auth_code_again is None

        # Access token works
        access = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_access_token(token.access_token)
        )
        assert access is not None
        assert access.client_id == "flow-client"

        # Refresh token works
        refresh = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_refresh_token(client, token.refresh_token)
        )
        assert refresh is not None

        new_token = asyncio.get_event_loop().run_until_complete(
            oauth_provider.exchange_refresh_token(client, refresh, [])
        )
        assert new_token.access_token != token.access_token
        assert new_token.refresh_token != token.refresh_token

        # Old refresh token consumed
        old_refresh = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_refresh_token(client, token.refresh_token)
        )
        assert old_refresh is None

    def test_expired_access_token_rejected(self, oauth_provider):
        from mcp.server.auth.provider import AccessToken

        oauth_provider._access_tokens["expired"] = AccessToken(
            token="expired",
            client_id="test",
            scopes=[],
            expires_at=0,  # expired
        )
        result = asyncio.get_event_loop().run_until_complete(
            oauth_provider.load_access_token("expired")
        )
        assert result is None
        assert "expired" not in oauth_provider._access_tokens

    def test_revoke_access_token(self, oauth_provider):
        from mcp.server.auth.provider import AccessToken

        token = AccessToken(token="to-revoke", client_id="test", scopes=[])
        oauth_provider._access_tokens["to-revoke"] = token
        asyncio.get_event_loop().run_until_complete(oauth_provider.revoke_token(token))
        assert "to-revoke" not in oauth_provider._access_tokens

    def test_revoke_refresh_token(self, oauth_provider):
        from mcp.server.auth.provider import RefreshToken

        token = RefreshToken(token="to-revoke", client_id="test", scopes=[])
        oauth_provider._refresh_tokens["to-revoke"] = token
        asyncio.get_event_loop().run_until_complete(oauth_provider.revoke_token(token))
        assert "to-revoke" not in oauth_provider._refresh_tokens


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        app = server.mcp.streamable_http_app()
        app.add_middleware(server.MemFabricMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.text == "OK"


class TestDownload:
    def test_download_returns_zip(self, isolated_data, monkeypatch):
        import zipfile, io

        monkeypatch.setattr(server, "AUTH_TOKEN", "")
        server.remember("topic-a", "Content A", "2026-03-19")
        server.remember("topic-b", "Content B", "2026-03-19")

        app = server.mcp.streamable_http_app()
        app.add_middleware(server.MemFabricMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "memory/topic-a.md" in names
        assert "memory/topic-b.md" in names
        assert "system/rules.md" in names

    def test_download_requires_token(self, isolated_data, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "my-secret")
        app = server.mcp.streamable_http_app()
        app.add_middleware(server.MemFabricMiddleware)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/download")
        assert resp.status_code == 401

        resp = client.get("/download", headers={"Authorization": "Bearer my-secret"})
        assert resp.status_code == 200


class TestLoginGate:
    def test_authorize_redirects_to_login_when_token_set(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "my-secret")
        monkeypatch.setattr(server, "SERVER_URL", "http://localhost:8000")
        params = server.AuthorizationParams(
            state="s1",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="http://localhost/callback",
            redirect_uri_provided_explicitly=True,
        )
        client = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["http://localhost/callback"],
        )
        redirect_url = asyncio.get_event_loop().run_until_complete(
            oauth_provider.authorize(client, params)
        )
        assert "/login?pending=" in redirect_url
        assert len(oauth_provider._pending_auths) == 1

    def test_authorize_auto_approves_when_no_token(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "")
        params = server.AuthorizationParams(
            state="s1",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="http://localhost/callback",
            redirect_uri_provided_explicitly=True,
        )
        client = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["http://localhost/callback"],
        )
        redirect_url = asyncio.get_event_loop().run_until_complete(
            oauth_provider.authorize(client, params)
        )
        assert "code=" in redirect_url
        assert "/login" not in redirect_url

    def test_login_page_renders(self, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "my-secret")
        app = server.mcp.streamable_http_app()
        app.add_middleware(server.MemFabricMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/login?pending=abc123")
        assert resp.status_code == 200
        assert "MemFabric" in resp.text
        assert "abc123" in resp.text

    def test_login_wrong_token_rejected(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "my-secret")
        monkeypatch.setattr(server, "SERVER_URL", "http://localhost:8000")
        # Create a pending auth
        params = server.AuthorizationParams(
            state="s1",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="http://localhost/callback",
            redirect_uri_provided_explicitly=True,
        )
        client_info = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["http://localhost/callback"],
        )
        asyncio.get_event_loop().run_until_complete(
            oauth_provider.authorize(client_info, params)
        )
        pending_id = list(oauth_provider._pending_auths.keys())[0]

        # Patch the global provider so middleware sees our pending auth
        monkeypatch.setattr(server, "_oauth_provider", oauth_provider)
        app = server.mcp.streamable_http_app()
        app.add_middleware(server.MemFabricMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/login", data={"token": "wrong", "pending": pending_id})
        assert resp.status_code == 401
        assert "Invalid token" in resp.text

    def test_login_correct_token_redirects(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "my-secret")
        monkeypatch.setattr(server, "SERVER_URL", "http://localhost:8000")
        params = server.AuthorizationParams(
            state="s1",
            scopes=[],
            code_challenge="challenge",
            redirect_uri="http://localhost/callback",
            redirect_uri_provided_explicitly=True,
        )
        client_info = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["http://localhost/callback"],
        )
        asyncio.get_event_loop().run_until_complete(
            oauth_provider.authorize(client_info, params)
        )
        pending_id = list(oauth_provider._pending_auths.keys())[0]

        monkeypatch.setattr(server, "_oauth_provider", oauth_provider)
        app = server.mcp.streamable_http_app()
        app.add_middleware(server.MemFabricMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/login",
            data={"token": "my-secret", "pending": pending_id},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "code=" in resp.headers["location"]
        assert "state=s1" in resp.headers["location"]

    def test_login_expired_pending_rejected(self, oauth_provider, monkeypatch):
        monkeypatch.setattr(server, "AUTH_TOKEN", "my-secret")
        monkeypatch.setattr(server, "SERVER_URL", "http://localhost:8000")
        # Manually create an expired pending auth
        oauth_provider._pending_auths["expired123"] = {
            "client_id": "test",
            "params": server.AuthorizationParams(
                state="s1",
                scopes=[],
                code_challenge="challenge",
                redirect_uri="http://localhost/callback",
                redirect_uri_provided_explicitly=True,
            ),
            "created_at": time.time() - 700,  # expired
        }
        monkeypatch.setattr(server, "_oauth_provider", oauth_provider)
        app = server.mcp.streamable_http_app()
        app.add_middleware(server.MemFabricMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/login", data={"token": "my-secret", "pending": "expired123"})
        assert resp.status_code == 400
        assert "expired" in resp.text.lower()
