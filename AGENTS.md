# AI Agent Instructions — `do-utility` (DO-HARNESS thin-pointer governance)

> **Governance mode**: thin pointer (`--mode thin`)
> **Central harness root**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS`

## 1. Central DO-HARNESS rules
This repository is governed by DO-HARNESS without local copies of `rules/`, `.agents/` or the gate scripts:

- **Orchestration and laws**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS/AGENTS.md`
- **SDLC and verification gate**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS/rules/RULES-SDLC.md`
- **Backend architecture**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS/rules/RULES-BE.md`
- **Database and anti-dummy data**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS/rules/RULES-DB.md`
- **AI and Google ADK patterns**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS/rules/RULES-AI.md`
- **UI/UX and design identity (per-app DESIGN.md)**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS/rules/RULES-UX.md`
- **Karpathy surgical discipline**: `/usr/local/google/home/priyambodo/Coding/DO-HARNESS/rules/KARPATHY.md`

## 2. Delegated quality gate (`Makefile`)
- `make verify` — run the central quality gate against this repository.
- `make docs` — validate Markdown links and make targets.
- `make secrets` — scan for leaked credentials.
- `make harness-pin` / `make harness-bootstrap` — record or restore the DO-HARNESS version.
- `make help` — list all targets.
