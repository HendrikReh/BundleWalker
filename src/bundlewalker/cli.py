from __future__ import annotations

import asyncio
from pathlib import Path
from typing import NoReturn

import typer

from bundlewalker.conventions import ConventionsStyle
from bundlewalker.errors import BundleWalkerError, UsageError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import PreparedTransaction, commit_transaction, discard_transaction
from bundlewalker.workflows.ask import (
    SynthesisAlreadyCurrent,
    answer_question,
    answer_synthesis_refresh,
    prepare_synthesis,
    prepare_synthesis_refresh,
    render_cited_answer,
)
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
def init_command(
    path: Path,
    conventions_style: ConventionsStyle = typer.Option(  # noqa: B008
        ConventionsStyle.DEFAULT,
        "--conventions-style",
        help=(
            "Initial conventions template. Styles: default, personal-workbook, "
            "agent-context, software-agent, research-agent."
        ),
    ),
) -> None:
    """Create a BundleWalker workspace at PATH."""
    try:
        workspace = initialize_workspace(path, conventions_style=conventions_style)
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
    refresh: str | None = typer.Option(None, "--refresh", metavar="SYNTHESIS_ID"),
) -> None:
    """Answer a cited question, save it, or review an in-place Synthesis refresh."""
    if save and refresh is not None:
        _exit_for_error(UsageError("--save and --refresh are mutually exclusive"))

    workspace = current_workspace(context)
    try:
        if refresh is not None:
            refreshed = asyncio.run(
                answer_synthesis_refresh(
                    workspace,
                    question,
                    refresh,
                    explicit_model=model,
                )
            )
            typer.echo(render_cited_answer(refreshed.answer, OkfRepository(workspace.wiki_dir)))
            outcome = prepare_synthesis_refresh(workspace, refreshed)
            if isinstance(outcome, SynthesisAlreadyCurrent):
                typer.echo("Synthesis is already current; no changes applied.")
                return
            transaction = outcome
        else:
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
