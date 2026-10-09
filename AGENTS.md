# AGENTS.md - Python Scheduler (env_log_scheduler)

Read `/Users/fordwang/Documents/Code/AGENTS.md` first. This file adds project-specific
rules for `/Users/fordwang/Documents/Code/Python/env_log_scheduler`.

## Project Overview

Python background scheduler split out from `Python/env`. It builds daily `log_10min` pre-aggregations from raw `log` records, supports incremental updates, and performs scheduled maintenance tasks.

## Tech Stack

- **Language**: Python
- **Deployment**: local script execution or Docker
- **Type Checker**: Pylance / Pyright (`pyrightconfig.json`)

## Scheduler Rules

- Preserve `log` to `log_10min` aggregation semantics unless the task explicitly changes them
- Be careful with force rebuild paths such as `build_log_10min.py --force`
- Treat MongoDB/environment access as external state; do not assume it is available locally

## Code Style

- Provide **full code snippets** when modifying code
- Modify **only necessary sections**
- Prefer clear architecture and efficient algorithms
- No assumptions without evidence
- If debugging: explain root cause
- Ensure code runs correctly after modification

## Verification

- Prefer narrow checks such as import/script syntax checks or `build_log_10min.py --status` when environment variables are configured
- If database or environment access is unavailable, report that clearly instead of pretending verification passed

## Documentation

- New and updated project documentation goes first to the Obsidian knowledge
  base at:
  `/Users/fordwang/Library/Mobile Documents/iCloud~md~obsidian/Documents/Ford Obsidian/工作/AIRYZONE`.
- Follow the shared `Documentation And Obsidian` rules: update existing topic
  notes when appropriate, preserve source/evidence context, and avoid duplicate
  full documents in this repository's `document/` or `docs/` directories.
- Keep agent instructions, essential README/index files, and documents directly
  required by builds/tests/tooling in the repository. Direct user instructions
  may specify another destination.
- If vault writing is restricted, use the available narrowly scoped approval
  mechanism or explain how to allow this AIRYZONE directory. Do not silently
  generate the document in the project instead; these instructions do not
  override filesystem permissions.
