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
    """claude-mem — contextual memory & retrieval for Claude Code."""


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Repo root (defaults to cwd)")
@click.option("--no-embed", is_flag=True, default=False,
              help="Skip embedding generation (faster, FTS-only retrieval)")
def index(root: Path | None, no_embed: bool) -> None:
    """Full reindex of the repo."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    init_db(settings.db_path)

    embedder = None
    if not no_embed:
        from .embeddings.bge_small import BgeSmallEmbedder
        embedder = BgeSmallEmbedder()

    stats = full_reindex(settings, embedder=embedder)
    click.echo(f"units_written={stats['units_written']} "
               f"relations_written={stats['relations_written']} "
               f"files_seen={stats['files_seen']}")


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None)
def doctor(root: Path | None) -> None:
    """Diagnostics — show index size and config."""
    repo_root = root or Path.cwd()
    try:
        settings = Settings.discover(repo_root)
    except FileNotFoundError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    conn = connect(settings.db_path)
    n_units = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    n_rels = conn.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    click.echo(f"repo_root: {settings.repo_root}")
    click.echo(f"db: {settings.db_path}")
    click.echo(f"units: {n_units}")
    click.echo(f"relations: {n_rels}")


@main.command()
def serve() -> None:
    """Run the MCP server on stdio."""
    from .server import serve_stdio
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
