---
name: tdd-research
description: Fetch/read a source and record a summary in the durable research log (.tdd-research.json)
---

You have been given a source (a URL or a local file path) and optionally a
related feature (a `featureName` from `.tdd-features.json` this research
informs).

If the source is missing, ask for it — don't guess what to research.

## Getting the content

- If the source looks like a URL, fetch it (use an X/Twitter mirror like
  `api.fxtwitter.com/<path>` if the direct link is blocked, same as
  fetching any other blocked URL).
- If the source is a local path, read it directly.

## Recording it

Summarize what was found in 2-5 sentences — enough for a future session to
know what was learned and why it mattered, without re-fetching the source.
Don't just paste the raw content.

Call `record_research(source=<the source>, summary=<the summary>,
related_feature=<the related feature>)` (omit `related_feature` if none was
given).

Then confirm: the summary recorded, and that it's saved (this creates
`.tdd-research.json` on first use — say so if this is the first entry).

Do not do anything else with the source's content unless separately asked
to act on it (e.g. don't start implementing gaps it mentions) — this
skill's only job is capturing it to the log.
