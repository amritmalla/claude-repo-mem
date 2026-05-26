from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from .config import Settings
from .db.connection import connect, init_db
from .db.repository import Repository
from .indexer.orchestrator import full_reindex


@click.group()
def main() -> None:
    """claude-repo-mem — contextual memory & retrieval for Claude Code."""


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Repo root (defaults to cwd)")
@click.option("--no-embed", is_flag=True, default=False,
              help="Skip embedding generation (faster, FTS-only retrieval)")
@click.option("--embedder", type=str, default=None,
              help="Embedder name (bge-small|openai|voyage); env CLAUDE_REPO_MEM_EMBEDDER")
@click.option("--reset", is_flag=True, default=False,
              help="Drop the DB before indexing (required when switching embedders)")
def index(root: Path | None, no_embed: bool, embedder: str | None, reset: bool) -> None:
    """Full reindex of the repo."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    if reset and settings.db_path.exists():
        settings.db_path.unlink()

    emb = None
    if not no_embed:
        from .embeddings.factory import make_embedder
        emb = make_embedder(embedder)
    init_db(settings.db_path, dim=emb.dim if emb else 384)

    stats = full_reindex(settings, embedder=emb)
    click.echo(f"units_written={stats['units_written']} "
               f"relations_written={stats['relations_written']} "
               f"files_seen={stats['files_seen']}")


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None)
def doctor(root: Path | None) -> None:
    """Diagnostics — index size, layer breakdown, T2 coverage, counters."""
    repo_root = root or Path.cwd()
    try:
        settings = Settings.discover(repo_root)
    except FileNotFoundError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    conn = connect(settings.db_path)
    n_units = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    n_rels = conn.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    by_layer = {
        r["layer"]: r["n"] for r in conn.execute(
            "SELECT layer, COUNT(*) AS n FROM unit GROUP BY layer"
        ).fetchall()
    }
    t2_eligible = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer IN ('code','docs')"
    ).fetchone()[0]
    t2_done = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer IN ('code','docs') AND t2_summary IS NOT NULL"
    ).fetchone()[0]
    from .observability.counters import get_counters
    counters = get_counters().to_dict()

    click.echo(f"repo_root: {settings.repo_root}")
    click.echo(f"db: {settings.db_path}")
    click.echo(f"units: {n_units}")
    click.echo(f"relations: {n_rels}")
    click.echo(f"by_layer: {by_layer}")
    click.echo(f"t2_coverage: {t2_done}/{t2_eligible}")
    click.echo(f"counters: {counters}")


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--fixture", type=click.Path(dir_okay=False, exists=True, path_type=Path), required=True)
@click.option("--k", type=int, default=5)
@click.option("--no-embed", is_flag=True, default=False, help="FTS-only (skip vector search)")
def bench(root: Path | None, fixture: Path, k: int, no_embed: bool) -> None:
    """Run a recall benchmark against a YAML fixture of (query, expected) pairs."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    from .bench.runner import run_benchmark
    emb = None
    if not no_embed:
        from .embeddings.factory import make_embedder
        emb = make_embedder()
    result = run_benchmark(settings, fixture, embedder=emb, k=k)
    click.echo(f"fixture: {fixture}")
    click.echo(f"queries: {result.total}")
    click.echo(f"recall@{k}: {result.hits_at_k}/{result.total} ({result.recall_at_k:.2%})")
    if result.p95_latency_ms:
        click.echo(f"p50_latency_ms: {result.p50_latency_ms:.1f}")
        click.echo(f"p95_latency_ms: {result.p95_latency_ms:.1f}")


@main.command("install-hooks")
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--force", is_flag=True, default=False)
def install_hooks(root: Path | None, force: bool) -> None:
    """Install a post-commit hook that runs `claude-repo-mem index --no-embed`."""
    repo_root = root or Path.cwd()
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        raise click.ClickException(f"not a git repo: {repo_root}")
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"
    if hook_path.exists() and not force:
        raise click.ClickException(
            f"{hook_path} already exists; rerun with --force to overwrite"
        )
    hook_path.write_text(
        "#!/bin/sh\n"
        "# Installed by claude-repo-mem install-hooks\n"
        "claude-repo-mem index --no-embed >/dev/null 2>&1 || true\n",
        encoding="utf-8",
    )
    try:
        hook_path.chmod(0o755)
    except Exception:
        pass  # Windows
    click.echo(f"installed: {hook_path}")


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--transcript", type=click.Path(dir_okay=False, exists=True, path_type=Path),
              default=None, help="Explicit transcript JSONL path (otherwise auto-located)")
@click.option("--yes", is_flag=True, default=False, help="Accept all proposals without prompting")
def distill(root: Path | None, transcript: Path | None, yes: bool) -> None:
    """Extract durable memories from the most recent Claude Code transcript."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    init_db(settings.db_path)

    from .distill.confirm import run_distill
    from .llm.factory import make_llm_client

    llm = make_llm_client(ctx=None) if False else _make_cli_llm()

    def prompt_fn(p) -> str:
        click.echo(f"\n[{p.kind} @ {p.scope} | conf={p.confidence:.2f}]")
        click.echo(p.fact)
        return click.prompt("[a]ccept / [s]kip / [q]uit", default="s",
                            type=click.Choice(["a", "s", "q"]), show_choices=False)

    result = asyncio.run(run_distill(
        settings, llm=llm, transcript_path=transcript,
        auto_accept=yes, prompt_fn=None if yes else prompt_fn,
    ))
    click.echo(f"transcript={result.get('transcript')} "
               f"proposals={result['proposals']} written={result['written']}")


def _make_cli_llm():
    """CLI path: prefer the Anthropic fallback (sampling requires MCP Context)."""
    import os
    os.environ.setdefault("CLAUDE_REPO_MEM_LLM", "anthropic")
    from .llm.factory import make_llm_client
    from .llm.base import LLMError
    try:
        return make_llm_client(ctx=None)
    except LLMError as e:
        raise click.ClickException(str(e))


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Repo root (defaults to cwd)")
@click.option("--watch/--no-watch", default=True,
              help="Run a file watcher in the background (default on)")
def serve(root: Path | None, watch: bool) -> None:
    """Run the MCP server on stdio."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    init_db(settings.db_path)

    watcher = None
    if watch:
        from .watcher.fs_watcher import FileWatcher
        watcher = FileWatcher(settings, embedder=None)
        watcher.start()

    try:
        from .server import serve_stdio
        asyncio.run(serve_stdio())
    finally:
        if watcher is not None:
            watcher.stop()


if __name__ == "__main__":
    main()
