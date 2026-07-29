# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authenticated workspace and concept browser API coverage."""

from typing import Protocol
from urllib.parse import quote

from httpx2 import Response


class AuthenticatedWebClient(Protocol):
    csrf_token: str

    def get(self, path: str) -> Response: ...


def test_workspace_endpoint_returns_status_and_csrf(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/api/v1/workspace")

    assert response.status_code == 200
    assert response.json() == {
        "display_name": "knowledge",
        "config_version": 1,
        "concept_counts": {"Entity": 1, "Topic": 1},
        "pending_review": None,
        "csrf_token": authenticated_client.csrf_token,
    }


def test_hierarchical_concept_id_uses_path_converter(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/api/v1/concepts/topics/agents")

    assert response.status_code == 200
    assert response.json()["concept_id"] == "topics/agents"
    assert response.json()["title"] == "Agents"


def test_concept_page_is_bounded_and_passes_through_opaque_cursor(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    first = authenticated_client.get("/api/v1/concepts?limit=1")
    cursor = first.json()["next_cursor"]
    second = authenticated_client.get(f"/api/v1/concepts?limit=1&cursor={quote(cursor, safe='')}")

    assert first.status_code == 200
    assert cursor is not None
    assert second.status_code == 200
    assert first.json()["items"][0]["concept_id"] != second.json()["items"][0]["concept_id"]
    assert second.json()["next_cursor"] is None


def test_search_passes_query_type_and_limit(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/api/v1/concepts/search?query=tools&type=Entity&limit=1")

    assert response.status_code == 200
    assert [item["concept_id"] for item in response.json()["items"]] == ["entities/tools"]


def test_search_route_precedes_hierarchical_concept_route(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/api/v1/concepts/search?query=agents")

    assert response.status_code == 200
    assert response.json()["items"][0]["concept_id"] == "topics/agents"


def test_invalid_page_and_search_parameters_are_bounded_json_errors(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    responses = (
        authenticated_client.get("/api/v1/concepts?limit=not-a-number"),
        authenticated_client.get("/api/v1/concepts?limit=101"),
        authenticated_client.get("/api/v1/concepts/search?query=&limit=1"),
        authenticated_client.get("/api/v1/concepts/search?query=agents&limit=11"),
    )

    for response in responses:
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "invalid_input"
        assert body["error"]["retryable"] is False
        assert len(body["error"]["message"]) <= 200


def test_dot_segments_are_rejected_before_concept_lookup(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/api/v1/concepts/topics/%2E%2E/agents")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


def test_hierarchical_concept_id_is_not_double_decoded(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    # TestClient performs URL parsing before Starlette receives the already-decoded ASGI path.
    # Three encoded layers therefore leave one literal encoded layer at the route handler.
    response = authenticated_client.get("/api/v1/concepts/topics/%25252E%25252E/agents")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "concept_not_found"


def test_missing_concept_returns_safe_not_found_without_absolute_paths(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/api/v1/concepts/topics/missing")

    assert response.status_code == 404
    serialized = response.text
    assert response.json()["error"]["code"] == "concept_not_found"
    assert "/tmp/" not in serialized
    assert "/private/" not in serialized
    assert "resource_uri" not in serialized


def test_concept_responses_do_not_expose_server_paths(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/api/v1/concepts/topics/agents")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "concept_id",
        "type",
        "title",
        "description",
        "tags",
        "markdown",
        "digest",
    }
    assert "resource_uri" not in response.text
