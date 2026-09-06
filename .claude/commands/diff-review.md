---
description: Review only staged git changes, nothing else
---

Run `git diff --cached` and review only those changes. Do not read
unrelated files. Do not explore the codebase beyond what's needed to
understand the diff itself.

Read `.claude/docs/tdd-review-checklist.md` and apply it to the staged
diff only. Report issues concisely with `file:line` references.

If there are no staged changes, say so and stop — don't fall back to
reviewing unstaged or committed changes.
