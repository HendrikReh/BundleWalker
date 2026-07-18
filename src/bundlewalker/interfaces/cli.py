# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import NoReturn

import typer

from bundlewalker.application import (
    ApplicationError,
    ApplicationErrorCode,
    ReviewResult,
    WorkspaceApplication,
)
from bundlewalker.conventions import ConventionsStyle
from bundlewalker.errors import BundleWalkerError, UsageError
from bundlewalker.workspace import Workspace, discover_workspace, initialize_workspace

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
review_app = typer.Typer(no_args_is_help=True)
app.add_typer(review_app, name="review")


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
    application = WorkspaceApplication(current_workspace(context))
    try:
        outcome = asyncio.run(
            application.prepare_file_ingestion(
                file,
                explicit_model=model,
            )
        )
    except ApplicationError as exc:
        _exit_for_application_error(exc)

    if outcome.status == "duplicate":
        typer.echo("Source already ingested; no changes applied.")
        return
    if outcome.review is None:
        raise RuntimeError("pending ingestion returned without a review")
    _review_changes(application, outcome.review)


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

    application = WorkspaceApplication(current_workspace(context))
    try:
        if refresh is not None:
            outcome = asyncio.run(
                application.prepare_refresh(
                    question,
                    refresh,
                    explicit_model=model,
                )
            )
            typer.echo(outcome.answer.markdown)
            if outcome.status == "current":
                typer.echo("Synthesis is already current; no changes applied.")
                return
            if outcome.review is None:
                raise RuntimeError("pending refresh returned without a review")
            review = outcome.review
        elif save:
            outcome = asyncio.run(
                application.prepare_synthesis(
                    question,
                    explicit_model=model,
                )
            )
            typer.echo(outcome.answer.markdown)
            review = outcome.review
        else:
            answer = asyncio.run(application.ask(question, explicit_model=model))
            typer.echo(answer.markdown)
            return
    except ApplicationError as exc:
        _exit_for_application_error(exc)

    _review_changes(application, review)


@app.command("lint")
def lint_command(
    context: typer.Context,
    semantic: bool = typer.Option(False, "--semantic"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Check deterministic wiki health and optionally add semantic advisories."""
    application = WorkspaceApplication(current_workspace(context))
    try:
        result = asyncio.run(application.lint(semantic=semantic, explicit_model=model))
    except ApplicationError as exc:
        _exit_for_application_error(exc)

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


@review_app.command("show")
def review_show(context: typer.Context) -> None:
    application = WorkspaceApplication(current_workspace(context))
    try:
        review = asyncio.run(application.get_pending_review())
    except ApplicationError as exc:
        _exit_for_application_error(exc)
    if review is None:
        typer.echo("No pending review.")
        return
    _render_review(review)


@review_app.command("apply")
def review_apply(context: typer.Context, review_id: str) -> None:
    application = WorkspaceApplication(current_workspace(context))
    try:
        asyncio.run(application.apply_review(review_id))
    except ApplicationError as exc:
        _exit_for_application_error(exc)
    typer.echo("Changes applied.")


@review_app.command("discard")
def review_discard(context: typer.Context, review_id: str) -> None:
    application = WorkspaceApplication(current_workspace(context))
    try:
        asyncio.run(application.discard_review(review_id))
    except ApplicationError as exc:
        _exit_for_application_error(exc)
    typer.echo("No changes applied.")


def _render_review(review: ReviewResult, *, include_id: bool = True) -> None:
    if include_id:
        typer.echo(f"Review ID: {review.review_id}")
    typer.echo(f"Status: {review.status}")
    typer.echo(f"Summary: {review.summary}")
    typer.echo(review.diff, nl=not review.diff.endswith("\n"))


def _review_changes(application: WorkspaceApplication, review: ReviewResult) -> None:
    """Display, confirm, and resolve a persisted review."""
    _render_review(review, include_id=False)
    try:
        try:
            accepted = confirm_changes()
        except typer.Exit:
            asyncio.run(application.discard_review(review.review_id))
            raise
        if not accepted:
            asyncio.run(application.discard_review(review.review_id))
            typer.echo("No changes applied.")
            return
        asyncio.run(application.apply_review(review.review_id))
    except ApplicationError as exc:
        _exit_for_application_error(exc)
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


def _exit_for_application_error(error: ApplicationError) -> NoReturn:
    typer.echo(f"Error: {error.safe_message}", err=True)
    if error.code is ApplicationErrorCode.REVIEW_PENDING and error.review_id is not None:
        typer.echo(f"Pending review: {error.review_id}", err=True)
        typer.echo("Resolve it with one of:", err=True)
        typer.echo("  bundlewalker review show", err=True)
        typer.echo(f"  bundlewalker review apply {error.review_id}", err=True)
        typer.echo(f"  bundlewalker review discard {error.review_id}", err=True)
    usage_codes = {
        ApplicationErrorCode.INVALID_INPUT,
        ApplicationErrorCode.CONFIGURATION_ERROR,
    }
    raise typer.Exit(code=2 if error.code in usage_codes else 1)


def _exit_for_error(error: BundleWalkerError) -> NoReturn:
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(code=error.exit_code)
