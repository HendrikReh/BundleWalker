from __future__ import annotations

import asyncio
from pathlib import Path
from typing import NoReturn

import typer

from bundlewalker.errors import BundleWalkerError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import PreparedTransaction, commit_transaction, discard_transaction
from bundlewalker.workflows.ask import answer_question, prepare_synthesis, render_cited_answer
from bundlewalker.workflows.ingest import DuplicateIngestion, prepare_ingestion
from bundlewalker.workflows.lint import run_lint
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
        context.obj = exc


@app.command("init")
def init_command(path: Path) -> None:
    """Create a BundleWalker workspace at PATH."""
    try:
        workspace = initialize_workspace(path)
    except BundleWalkerError as exc:
        _exit_for_error(exc)
    typer.echo(f"Initialized BundleWalker workspace at {workspace.root}")


@app.command("ingest")
def ingest_command(
    context: typer.Context,
    file: Path,
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Propose and review knowledge changes from one Markdown or text source."""
    workspace = current_workspace(context)
    try:
        outcome = asyncio.run(
            prepare_ingestion(
                workspace,
                file,
                explicit_model=model,
            )
        )
    except BundleWalkerError as exc:
        _exit_for_error(exc)

    if isinstance(outcome, DuplicateIngestion):
        typer.echo("Source already ingested; no changes applied.")
        return

    _review_transaction(outcome.transaction)


@app.command("ask")
def ask_command(
    context: typer.Context,
    question: str,
    model: str | None = typer.Option(None, "--model"),
    save: bool = typer.Option(False, "--save"),
) -> None:
    """Answer a cited knowledge question and optionally save a reviewed synthesis."""
    workspace = current_workspace(context)
    try:
        answered = asyncio.run(
            answer_question(
                workspace,
                question,
                explicit_model=model,
            )
        )
        typer.echo(render_cited_answer(answered.answer, OkfRepository(workspace.wiki_dir)))
        if not save:
            return
        transaction = prepare_synthesis(workspace, answered)
    except BundleWalkerError as exc:
        _exit_for_error(exc)

    _review_transaction(transaction)


@app.command("lint")
def lint_command(
    context: typer.Context,
    semantic: bool = typer.Option(False, "--semantic"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Check deterministic wiki health and optionally add semantic advisories."""
    workspace = current_workspace(context)
    try:
        result = asyncio.run(
            run_lint(
                workspace,
                semantic=semantic,
                explicit_model=model,
            )
        )
    except BundleWalkerError as exc:
        _exit_for_error(exc)

    if not result.findings:
        typer.echo("No lint findings.")
    for finding in result.findings:
        location = f" {finding.path}:" if finding.path is not None else ":"
        typer.echo(
            f"{finding.severity.value.upper()} {finding.code} "
            f"[{finding.origin.value}]{location} {finding.message}"
        )
    if result.deterministic_has_errors:
        raise typer.Exit(code=1)


def _review_transaction(transaction: PreparedTransaction) -> None:
    """Display, confirm, and apply the shared reviewed-transaction path."""
    typer.echo(f"Summary: {transaction.summary}")
    typer.echo(transaction.diff, nl=not transaction.diff.endswith("\n"))
    try:
        try:
            accepted = confirm_changes()
        except typer.Exit:
            discard_transaction(transaction)
            raise
        if not accepted:
            discard_transaction(transaction)
            typer.echo("No changes applied.")
            return
        commit_transaction(transaction)
    except BundleWalkerError as exc:
        _exit_for_error(exc)
    typer.echo("Changes applied.")


def current_workspace(context: typer.Context) -> Workspace:
    """Return the workspace discovered by the application callback."""
    workspace = context.obj
    if isinstance(workspace, BundleWalkerError):
        _exit_for_error(workspace)
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
