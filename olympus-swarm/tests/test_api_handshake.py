# test_api_handshake.py - dynamic API key vault auth integration tests
import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Add hf-space to python path to import Nancy app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "hf-space")))

from main import app as nancy_app

client = TestClient(nancy_app)

# In-memory mock Redis database for isolated unit testing
mock_redis_db = {}

async def mock_set_json(key: str, value: any, ex=None):
    mock_redis_db[key] = value
    return True

async def mock_get_json(key: str):
    return mock_redis_db.get(key)

async def mock_delete(key: str):
    if key in mock_redis_db:
        del mock_redis_db[key]
        return True
    return False

async def mock_execute(cmd: str, *args):
    if cmd == "SADD":
        set_key = args[0]
        val = args[1]
        if set_key not in mock_redis_db:
            mock_redis_db[set_key] = set()
        mock_redis_db[set_key].add(val)
        return 1
    elif cmd == "SMEMBERS":
        set_key = args[0]
        return list(mock_redis_db.get(set_key, set()))
    elif cmd == "SREM":
        set_key = args[0]
        val = args[1]
        if set_key in mock_redis_db and val in mock_redis_db[set_key]:
            mock_redis_db[set_key].remove(val)
            return 1
        return 0
    return None

@pytest.mark.asyncio
@patch("core.redis_client.redis_client.set_json", side_effect=mock_set_json)
@patch("core.redis_client.redis_client.get_json", side_effect=mock_get_json)
@patch("core.redis_client.redis_client.delete", side_effect=mock_delete)
@patch("core.redis_client.redis_client._execute", side_effect=mock_execute)
async def test_dynamic_key_handshake_flow(mock_exec, mock_del, mock_get, mock_set):
    """E2E verification of key generation, storage, auth validation, and revocation."""
    # Ensure database starts empty
    mock_redis_db.clear()

    # 1. Assert accessing API endpoints without key fails with 401
    resp = client.post("/v1/chat/completions", json={"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]})
    assert resp.status_code == 401

    # 2. Generate a dynamic API access key
    desc = "Test Swarm Manager client"
    resp = client.post("/admin/keys/create", json={"description": desc})
    assert resp.status_code == 200
    data = resp.json()

    plaintext_key = data["plaintext_key"]
    data["key_id"]
    assert plaintext_key.startswith("ny_")
    assert data["description"] == desc

    # 3. Assert the key hash was recorded in our mocked Redis SET
    active_hashes = mock_redis_db.get("nancy:active_key_hashes", set())
    assert len(active_hashes) == 1
    hashed_token = list(active_hashes)[0]

    # 4. Fetch the keys list and assert metadata records correctly
    resp = client.get("/admin/keys/list")
    assert resp.status_code == 200
    keys_list = resp.json()
    assert len(keys_list) == 1
    assert keys_list[0]["description"] == desc
    assert keys_list[0]["hash"] == hashed_token

    # 5. Access the endpoint with our newly generated key - should pass 200 (or 500 depending on mock worker but auth passes!)
    headers = {"Authorization": f"Bearer {plaintext_key}"}

    # We mock task_queue.submit_task and task_queue.stream_chunks to bypass timeout blocks
    async def mock_submit_task(task):
        from models.task import TaskHandle
        return TaskHandle(task)

    async def mock_stream_chunks(*args, **kwargs):
        yield "Mock response"

    with patch("routers.api.task_queue.submit_task", side_effect=mock_submit_task), \
         patch("routers.api.task_queue.stream_chunks", side_effect=mock_stream_chunks):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "chatgpt", "messages": [{"role": "user", "content": "Ping"}]},
            headers=headers
        )
        # Authentication succeeded and request completed successfully
        assert resp.status_code == 200

    # 6. Revoke the key using its hash
    resp = client.delete(f"/admin/keys/revoke/{hashed_token}")
    assert resp.status_code == 200

    # 7. Assert key metadata was deleted and hash removed from SET
    assert f"nancy:api_keys:{hashed_token}" not in mock_redis_db
    assert hashed_token not in mock_redis_db["nancy:active_key_hashes"]

    # 8. Assert subsequent API requests with this key fail immediately with 401
    resp = client.post("/v1/chat/completions", json={"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]}, headers=headers)
    assert resp.status_code == 401
