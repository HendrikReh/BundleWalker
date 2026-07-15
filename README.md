# BundleWalker

*Exploring portable knowledge with the Open Knowledge Format and Pydantic AI.*

BundleWalker is a hands-on exploration of how structured knowledge can move between tools, workflows, and AI agents. It combines the Open Knowledge Format (OKF) with Pydantic AI's typed agent model to investigate knowledge that is portable, inspectable, and explicit about its structure.

## Purpose

The project is a practical space for exploring questions such as:

- How can knowledge be packaged so that it remains understandable outside the system that created it?
- How can typed models make agent inputs, outputs, and knowledge boundaries easier to inspect?
- How might OKF bundles be validated, loaded, and reused across Pydantic AI workflows?

The emphasis is on learning by building small, concrete experiments rather than defining a production framework upfront.

## Project status

> [!NOTE]
> BundleWalker is an early-stage learning and experimentation project. The repository currently contains the initial Python scaffold; the ideas described here are its direction, not completed features.

Expect the structure, examples, and API to evolve as the project develops.

## Setup

### Prerequisites

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)

Install the locked dependencies:

```bash
uv sync --locked
```

Run the current scaffold:

```bash
uv run main.py
```

## Current direction

BundleWalker is intended to explore:

- representing portable knowledge as explicit, inspectable bundles;
- mapping OKF structures to typed Python models;
- giving Pydantic AI agents well-defined access to bundled knowledge; and
- documenting small experiments that reveal useful patterns and limitations.
