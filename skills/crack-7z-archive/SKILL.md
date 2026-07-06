---
name: crack-7z-archive
description: Recover the password of a password-protected 7z archive by first trying a small list of common passwords, then escalating to hash extraction with 7z2hashcat and hashcat (mode 11600) with a wordlist or mask attack. Use when given a locked .7z file and a target file inside it whose contents must be extracted to an output location.
---

# Crack 7z Archive Password

## Goal

Recover the password of a 7z archive, extract the contents, and write the target file's data to a required output path.

## Procedure

### 1. Verify tooling

- Confirm `7z` is available (`command -v 7z`); if not, install `p7zip-full` via the system package manager.
- Confirm `7z2hashcat` is available; obtain it (often shipped with `7z2john`/`7z2hashcat` in john-jumbo packages) if missing.
- Confirm `hashcat` is available if escalation is needed.
- Confirm the archive path exists and is readable.

### 2. Quick win — try common passwords first

Before invoking heavy cracking, iterate over a short list of likely passwords. This is the cheapest path and often succeeds.

```
COMMON=("" "password" "secret" "1234" "12345" "123456" "admin" "root" "test" "qwerty" "letmein")
for pw in "${COMMON[@]}"; do
  if 7z x -y -p"$pw" -o/tmp/extract_$$ "$ARCHIVE" >/dev/null 2>&1; then
    echo "Cracked: '$pw'"
    break
  fi
done
```

Detection: success is indicated by a zero exit code and the presence of extracted files in the output directory.

### 3. Escalate — extract hash and run hashcat

If the common list fails, extract the hash in hashcat-compatible form:

```
7z2hashcat "$ARCHIVE" > /tmp/7z.hash
```

Then run hashcat. For 7z archives the hash mode is `11600`. Choose one attack shape:

- **Wordlist (preferred when rockyou or similar is available):**
  ```
  hashcat -m 11600 -a 0 /tmp/7z.hash /path/to/wordlist.txt --force
  ```
- **Mask/brute-force fallback:**
  ```
  hashcat -m 11600 -a 3 /tmp/7z.hash '?a?a?a?a?a?a' --force
  ```
  Adjust mask length to the expected password complexity; bail on excessive candidate counts.

Recovered candidate lands in hashcat's pot file or stdout in the form `$7z$...:password`.

### 4. Extract with recovered password and write output

Once a password is known (from step 2 or 3):

```
7z x -y -p"$RECOVERED_PW" -o/tmp/final "$ARCHIVE"
```

Locate the target file inside the extracted tree, read it, and write its bytes verbatim to the required output path (e.g., `/app/solution.txt`). Do not truncate, reformat, or wrap — write raw content.

## Guard rails

- Always `-y` to overwrite without prompt and capture stdout/stderr to avoid hangs.
- Use a unique per-attempt output directory (`-o/tmp/extract_$$`) so successive attempts don't collide.
- Treat any zero exit from `7z x` as success only after confirming the expected file is present.
- If `7z2hashcat` is not installed and you can't add packages, fall back to a longer curated password list before resorting to full brute force — but never silently skip escalation when no password is found.
- When writing the final output, verify the file size > 0 and contents are non-empty before declaring success.

## Decision summary

1. Common passwords → if cracked, jump to step 4.
2. Hash + wordlist → if cracked, jump to step 4.
3. Mask attack → bounded by expected complexity.
4. Extract and write target to output path.