---
name: extend-project
description: Suggest concrete extensions for the current project, then explain how to build the one that's picked
---

For extending the project's own architecture, not for starting a TDD
feature (use `tdd-start` for that).

If a specific extension was already named, use it and skip to "Scope it."

## Find suggestions

Look at the actual project instead of asking generically:
- Roadmap/TODO/"not yet implemented" sections in any README/ARCHITECTURE/
  SPEC-style doc at the repo root.
- `TODO`/`FIXME`/`XXX` comments in source.
- A pluggable-units directory (adapters/plugins/drivers/providers/...)
  with only one or two entries — a sibling addition is low-risk.
- Stubbed code (`NotImplementedError`, always-off flags, a single
  hardcoded case where a registry would generalize it).

Turn findings into 3-5 specific, named suggestions (not generic
categories) via a structured choice tool if one is available, plus an
"Other — describe it" option. If nothing turns up, say so and ask
generically instead.

## Scope it

1. Re-check whatever doc surfaced the idea for build details it already
   gives.
2. If a pluggable-units directory exists, read one existing entry as the
   pattern to copy, plus its contract/interface.
3. Otherwise, find the most structurally similar existing feature and
   treat it as the template.
4. For a command/skill/agent, use existing files in `.agents/skills/`, or
   this tool's own command/agent directory (e.g. `.claude/commands/`,
   `.claude/agents/`, or their Codex equivalents), as the style reference.

Give an ordered checklist: files to create/edit, the contract they must
satisfy, and the one example to copy. Don't write the files unless
explicitly asked — this skill is orientation, not execution.
