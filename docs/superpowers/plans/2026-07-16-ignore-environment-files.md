# Ignore Environment Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ignore local `.env` variants throughout the repository while keeping `.env.example` trackable.

**Architecture:** Add an ordered ignore-and-negation rule pair to the repository root `.gitignore`. Verify the behavior with Git's ignore matcher and confirm that the existing local `.env` disappears from status without ever being read or staged.

**Tech Stack:** Git ignore patterns, Git CLI

## Global Constraints

- Modify only the root `.gitignore` during implementation.
- Do not read, modify, stage, or commit the existing untracked `.env` file.
- Do not create an `.env.example` file as part of this change.
- The first pattern must ignore `.env` and every basename beginning with `.env` anywhere in the repository.
- The later negation must re-include `.env.example` so it remains trackable.

---

### Task 1: Configure and verify environment-file ignores

**Files:**
- Modify: `.gitignore`
- Test: Git ignore-matcher commands against `.env`, `.env.local`, and `.env.example`

**Interfaces:**
- Consumes: Git's ordered `.gitignore` pattern matching
- Produces: Repository-wide ignore behavior for `.env*` with a trackable `.env.example` exception

- [ ] **Step 1: Verify the current ignore behavior does not satisfy the design**

Run:

```bash
if git check-ignore -q --no-index .env; then
  echo "unexpected: .env is already ignored"
  exit 1
fi
```

Expected: exit status `0` from the shell block, with no output. The inner `git check-ignore` returns nonzero because `.env` is not yet ignored.

- [ ] **Step 2: Append the ordered environment patterns to `.gitignore`**

Add these exact lines after the existing cache and workspace directory patterns and before `*.py[cod]`:

```gitignore
.env*
!.env.example
```

- [ ] **Step 3: Verify both ignored variants and the example exception**

Run:

```bash
git check-ignore -q --no-index .env
git check-ignore -q --no-index .env.local
if git check-ignore -q --no-index .env.example; then
  echo "unexpected: .env.example is ignored"
  exit 1
fi
```

Expected: exit status `0` with no output. `.env` and `.env.local` are ignored, while `.env.example` is not ignored.

- [ ] **Step 4: Confirm the change is clean and the real `.env` is absent from status**

Run:

```bash
git status --short
git diff --check -- .gitignore
git diff -- .gitignore
```

Expected: status lists `.gitignore` and any already-existing plan or specification changes, but does not list `.env`; `git diff --check` has no output; the `.gitignore` diff contains only the two ordered patterns.

- [ ] **Step 5: Commit only the implementation file**

Run:

```bash
git add .gitignore
git diff --cached --check
git diff --cached --name-only
git commit -m "chore: ignore environment files"
```

Expected: the staged-name output contains only `.gitignore`, the staged diff check has no output, and the commit succeeds. Do not use `git add .` or any command that stages `.env`.
