"""Public settings schema and read-count parity against the committed handler."""
import copy
import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

import server
from tools.capture_settings_response import environment

FIXTURE = json.loads((Path(__file__).parent / "fixtures/settings_response_1_3_1b.json").read_text())


@pytest.mark.parametrize("case", FIXTURE["cases"])
def test_settings_response_matches_baseline_with_one_direct_config_read(case):
    import asyncio
    cfg = copy.deepcopy(case["config"])
    reads = []
    bindings = environment(cfg, reads)
    with ExitStack() as stack:
        for name, value in bindings.items():
            if name not in ("web", "math"):
                stack.enter_context(patch.object(server, name, value))
        response = asyncio.run(server.settings_get(None))
    assert json.loads(response.text) == case["response"]
    assert cfg == case["config"]
    assert case["direct_config_reads"] == 5
    assert len(reads) == 1  # Deeper integration helpers are stubbed, not counted.
    assert "synthetic-secret-1234" not in response.text
    assert "never expose this" not in response.text


def test_settings_inventory_probes_vsr_and_runtime_path_once():
    import asyncio
    cfg = copy.deepcopy(FIXTURE["cases"][0]["config"])
    bindings = environment(cfg, [])
    with ExitStack() as stack:
        for name, value in bindings.items():
            if name not in ("web", "math"):
                stack.enter_context(patch.object(server, name, value))
        vsr = stack.enter_context(patch.object(server, "_video_upscale_node", return_value="VSR"))
        runtime = stack.enter_context(patch.object(server, "dlss5_runtime_dir", wraps=bindings["dlss5_runtime_dir"]))
        response = asyncio.run(server.settings_get(None))
    assert response.status == 200
    vsr.assert_called_once()
    runtime.assert_called_once()


def test_settings_read_uses_real_http_with_isolated_runtime_hooks():
    import asyncio
    case = FIXTURE["cases"][0]

    async def exercise():
        async with TestClient(TestServer(server.create_app())) as client:
            response = await client.get("/api/settings")
            assert response.status == 200
            assert await response.json() == case["response"]

    with ExitStack() as stack:
        for name, value in environment(copy.deepcopy(case["config"]), []).items():
            if name not in ("web", "math"):
                stack.enter_context(patch.object(server, name, value))
        for name in ("on_start", "on_shutdown", "on_cleanup"):
            stack.enter_context(patch.object(server, name, AsyncMock()))
        asyncio.run(exercise())


def test_llm_inventory_cannot_add_private_fields_to_the_response():
    from pixal.config.presentation import SettingsInventory, settings_response
    cfg = copy.deepcopy(FIXTURE["cases"][0]["config"])
    inventory = SettingsInventory(
        llm={"local_llms": [], "official_families": [], "api_key": "inventory-secret"},
        critic={}, upscale={}, edit={}, vae={}, pid={}, h3={}, video={}, still={},
        model_roots=[], catalog_size=0, vram={}, comfy_url="http://synthetic.invalid")
    payload = settings_response(cfg, inventory, version="synthetic", channel="test",
                                idle_minutes=10, de_shine_strength=.85,
                                dlss5_styles=("default",), h3_resolution="standard")
    assert "api_key" not in payload["llm"]
    assert "inventory-secret" not in json.dumps(payload)
