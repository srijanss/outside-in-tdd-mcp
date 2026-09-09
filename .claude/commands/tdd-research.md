---
description: Fetch/read a source and record a summary in the durable research log (.tdd-research.json)
argument-hint: <source> [related-feature]
---

Arguments: source = "$1" (a URL or a local file path), related feature =
"$2" (optional — a `featureName` from `.tdd-features.json` this research
informs).

If `$1` is missing, ask me for the source — don't guess what to research.

## Getting the content

- If `$1` looks like a URL, fetch it (use an X/Twitter mirror like
  `api.fxtwitter.com/<path>` if the direct link is blocked, same as
  fetching any other blocked URL).
- If `$1` is a local path, read it directly.

## Recording it

Summarize what you found in 2-5 sentences — enough for a future session to
know what was learned and why it mattered, without re-fetching the source.
Don't just paste the raw content.

Call `record_research(source="$1", summary=<your summary>, related_feature="$2")`
(omit `related_feature` if `$2` wasn't given).

Then confirm to me: the summary you recorded, and that it's saved (this
creates `.tdd-research.json` on first use — say so if this is the first
entry).

Do not do anything else with the source's content unless I separately ask
you to act on it (e.g. don't start implementing gaps it mentions) — this
command's only job is capturing it to the log.
