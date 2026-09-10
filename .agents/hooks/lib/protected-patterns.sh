#!/usr/bin/env bash
# protected-patterns.sh — shared extended-regex (ERE) patterns for files Claude
# should never touch directly. Sourced by protect-sensitive-files.sh (Edit/Write)
# and danger-guard.sh (Bash writes to the same paths).
#
# Generic across projects — no framework/cloud-vendor-specific paths. If a
# project has its own sensitive paths (e.g. a specific settings file), add
# them in that project's own hook rather than here.

PROTECTED_FILE_PATTERNS=(
  '(^|/)\.env$'
  '(^|/)\.env\.[a-zA-Z0-9_-]+$'    # .env.production, .env.staging, .env.local, etc.
  '(^|/)k8s/'                      # Kubernetes manifests — review manually
  '(^|/)deploy/'
  '(^|/)helm/'
  'docker-compose\.prod'
  'docker-compose\.staging'
  '(^|/)secrets\.ya?ml$'
  '\.pem$'                         # SSL certs
  '\.key$'                         # private keys
  '(^|/)service-account\.json$'    # GCP/Firebase service accounts
)

# Checked before PROTECTED_FILE_PATTERNS/_LOOSE: a match here means "safe,
# don't block" even though the path also matches a protected pattern above.
# Covers committed templates like .env.example that aren't live secrets.
EXEMPT_FILE_PATTERNS=(
  '\.env\.(example|sample|template)([^a-zA-Z0-9._-]|$)'
)

# Same intent as PROTECTED_FILE_PATTERNS, but for matching against a whole shell
# command line (danger-guard.sh) instead of a bare file_path. There the target
# is preceded by spaces/redirects/quotes rather than "/" or start-of-string, and
# not necessarily the last token, so the anchors above don't fire. ".env" is
# boundary-checked so it doesn't false-positive on ".env.example".
PROTECTED_FILE_PATTERNS_LOOSE=(
  '\.env([^a-zA-Z0-9._-]|$)'
  '\.env\.[a-zA-Z0-9_-]+'
  'k8s/'
  'deploy/'
  'helm/'
  'docker-compose\.prod'
  'docker-compose\.staging'
  'secrets\.ya?ml'
  '\.pem([^a-zA-Z0-9]|$)'
  '\.key([^a-zA-Z0-9]|$)'
  'service-account\.json'
)
