import json
import os
from pathlib import Path
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db


@pytest.mark.asyncio
@pytest.mark.parametrize("watch", [False, True], ids=["no-watch", "watch"])
@pytest.mark.parametrize("other_initialized", [False, True], ids=["unrelated-folder", "other-repo"])
async def test_serve_pins_explicit_root(tmp_path: Path, watch: bool, other_initialized: bool):
    selected = tmp_path / "selected"
    selected.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {
        # Match the test process's imports even when it was started with an
        # editable installation or an external interpreter.
        "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
    }
    if other_initialized:
        other = Settings.for_repo(elsewhere)
        init_db(other.db_path)
        env["CLAUDE_REPO_MEM_ROOT"] = str(elsewhere)
        env["CLAUDE_PROJECT_DIR"] = str(elsewhere)

    # Process site-package hooks for interpreters using an external environment
    # (in particular the Windows DLL setup required by the MCP SDK).
    bootstrap = (
        "import site, sys\n"
        "for path in list(sys.path):\n"
        "    if path.endswith('site-packages'):\n"
        "        site.addsitedir(path)\n"
        "from claude_repo_mem.cli import main\n"
        "main()\n"
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-c", bootstrap, "serve", "--root", str(selected),
            "--watch" if watch else "--no-watch",
        ],
        cwd=str(elsewhere),
        env=env,
    )

    with anyio.fail_after(20):
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                saved = await session.call_tool(
                    "remember", {"fact": "Selected repository", "scope": "selected"},
                )
                assert not saved.isError, saved.content
                memory_path = Path(json.loads(saved.content[0].text)["path"])
                expected_dir = selected / ".claude-repo-mem" / "memory" / "selected"
                assert memory_path.parent == expected_dir
                assert memory_path.exists()

                scopes = await session.call_tool("scopes", {})
                assert not scopes.isError, scopes.content
                assert json.loads(scopes.content[0].text) == {
                    "scopes": [{"scope": "selected", "count": 1}],
                }

    assert not (elsewhere / ".claude-repo-mem" / "memory").exists()
