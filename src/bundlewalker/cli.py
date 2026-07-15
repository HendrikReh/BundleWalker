from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from bundlewalker.errors import BundleWalkerError
from bundlewalker.workspace import Workspace, discover_workspace, initialize_workspace

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.callback()
def main(context: typer.Context) -> None:
    """Build and maintain a local, review-first OKF knowledge workspace."""
    if context.invoked_subcommand in {None, "init"}:
        return
    try:
        context.obj = discover_workspace()
    except BundleWalkerError as exc:
        _exit_for_error(exc)


@app.command("init")
def init_command(path: Path) -> None:
    """Create a BundleWalker workspace at PATH."""
    try:
        workspace = initialize_workspace(path)
    except BundleWalkerError as exc:
        _exit_for_error(exc)
    typer.echo(f"Initialized BundleWalker workspace at {workspace.root}")


def current_workspace(context: typer.Context) -> Workspace:
    """Return the workspace discovered by the application callback."""
    workspace = context.obj
    if not isinstance(workspace, Workspace):
        raise RuntimeError("workspace was not discovered")
    return workspace


def confirm_changes(prompt: str = "Apply these changes?") -> bool:
    """Confirm a reviewed proposal, treating interruption as an unchanged outcome."""
    try:
        return typer.confirm(prompt)
    except (KeyboardInterrupt, typer.Abort):
        typer.echo("No changes applied.")
        raise typer.Exit(code=0) from None


def _exit_for_error(error: BundleWalkerError) -> NoReturn:
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(code=error.exit_code)
