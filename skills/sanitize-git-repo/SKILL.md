---
name: sanitize-git-repo
description: Sanitize a git repository of API keys, tokens, and secrets. Use when asked to scrub credentials, remove leaked secrets, or clean a repo before publishing.
---

# Sanitize a Git Repository

Remove API keys, tokens, and secrets from a git repository while preserving file structure and history consistency.

## When to use

- Cleaning a repo before pushing to a public remote
- Scrubbing credentials from a project dump
- Preparing a repo for archival, sharing, or handoff
- Responding to a leaked-secret incident in commit history

## Procedure

### 1. Survey credential patterns

Search the working tree for known credential formats. Build a regex set covering the providers in scope:

- **AWS**: access key IDs (`AKIA[0-9A-Z]{16}`), secret access keys
- **GitHub**: `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` prefixed tokens
- **Huggingface**: `hf_` prefixed tokens
- **OpenAI / Anthropic**: `sk-...` style keys
- **Slack**: `xox[baprs]-...` tokens
- **Google API keys**: `AIza...` strings
- **Private keys**: `-----BEGIN ... PRIVATE KEY-----` blocks
- **Generic credentials**: any line containing `token`, `api_key`, `secret`, `password`, `credential`, `access_key` (case-insensitive)

Run each pattern across the tree. Use ripgrep or `grep -rE` with sensible include globs (text files only, skip `node_modules`, `.git/`, binary blobs).

### 2. Inspect git history

Commits are part of the surface area. Find files added to history with credential-related names:

```
git log --all --diff-filter=A --name-only --pretty=format:
```

Also `git grep` against `HEAD`, against all branches, and against the reflog. A secret deleted in a later commit is still reachable.

### 3. Build a placeholder map

For each distinct secret value found, choose a stable placeholder that names the slot, not the value:

| Real value kind | Placeholder |
| --- | --- |
| AWS access key ID | `<your-aws-access-key-id>` |
| AWS secret access key | `<your-aws-secret-access-key>` |
| GitHub token | `<your-github-token>` |
| Huggingface token | `<your-huggingface-token>` |
| OpenAI key | `<your-openai-api-key>` |
| Slack token | `<your-slack-token>` |
| Google API key | `<your-google-api-key>` |
| Private key block | `<your-private-key>` |
| Generic password | `<your-password>` |
| Generic secret | `<your-secret>` |

Consistency matters: the same real value must always map to the same placeholder so downstream diffs stay readable.

### 4. Replace in place

For each contaminated file, rewrite the secret value to its placeholder. Use `sed -i` or a small script. Constraints:

- **Preserve line structure** — keep quoting, escaping, and indentation intact.
- **Preserve variable names** — only the value changes, not the assignment.
- **Do not delete or rewrite clean files.**
- **Do not touch `.gitignore` rules, lock files, or vendored binaries** unless they contain a real secret.

For multi-line secrets (private keys, PEM blocks), replace the entire block with a single placeholder line.

### 5. Handle history (if required)

Working-tree replacement does **not** erase a secret from prior commits. If the secret has already been pushed or the history must be clean:

- Use `git filter-repo` (preferred) or `git filter-branch` to rewrite history, removing or rewriting the affected paths/strings.
- Force-push all branches and tags.
- Notify any collaborators to rebase.

Skip this step if the secret was never committed and only lived in working files, scratch notes, or untracked directories.

### 6. Verify

Re-run every regex from step 1 against both the working tree **and** the full history (`git rev-list --all | xargs git grep -E ...`). The verification must return zero matches for real secret values. Spot-check a few placeholders to confirm the rewrite preserved structure.

### 7. Commit the sanitized state

Commit with a clear message such as `chore: replace leaked credentials with placeholders`. Do not amend an existing commit that already contained a secret — the value is still reachable from the reflog.

## Common pitfalls

- **Replacing only one occurrence of a value** when it appears in multiple files — a single missed instance defeats the scrub.
- **Replacing a value with a different value per file** — produces noisy diffs and confuses future readers.
- **Forgetting binary or minified files** — secrets can hide in `.map`, `.min.js`, or compiled assets.
- **Trusting `.env.example` style files as "safe"** — they sometimes contain real values copied during early development.
- **Stopping at the working tree** — git history is the most common leak vector.
- **Amending instead of new commit** — leaves the secret in the reflog and may be force-pushed back.