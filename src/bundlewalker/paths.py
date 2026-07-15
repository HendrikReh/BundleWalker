from pathlib import PurePosixPath


def normalize_workspace_config_path(value: object) -> str | None:
    """Return the canonical spelling of a safe workspace-relative config path."""
    if not isinstance(value, str) or not value:
        return None
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative == PurePosixPath(".")
    ):
        return None
    return relative.as_posix()
