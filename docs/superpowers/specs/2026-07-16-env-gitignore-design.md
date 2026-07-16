# Environment File Ignore Design

## Goal

Prevent local environment files and their likely secret values from being tracked while keeping
the repository's example environment template trackable.

## Selected behavior

Append these patterns to the root `.gitignore`:

```gitignore
.env*
!.env.example
```

The first pattern ignores `.env` and every basename beginning with `.env` anywhere in the
repository. The second pattern re-includes `.env.example` so it can be committed as documentation.

## Scope

- Modify only the root `.gitignore` during implementation.
- Do not read, modify, stage, or commit the existing untracked `.env` file.
- Do not create an `.env.example` file as part of this change.

## Verification

- `git check-ignore --no-index .env` succeeds.
- `git check-ignore --no-index .env.local` succeeds.
- `git check-ignore --no-index .env.example` reports that the file is not ignored.
- `git status --short` no longer exposes `.env` as an untracked file.
