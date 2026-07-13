---
name: crack-7z-hash
description: >-
  Recover the password of a password-protected 7-Zip (.7z) archive by
  extracting its hash and cracking it offline. Use when given a .7z file (or an
  already-extracted 7z hash string) and asked to find/recover/crack its
  password, open a locked 7z archive, or audit 7z archive password strength.
  Covers hash extraction with 7z2john and cracking with hashcat (mode 11600) or
  John the Ripper (7z format). Authorized/CTF/security-testing use only.
---

# Crack 7z Hash

Recover a 7-Zip archive password by extracting the hash and running an offline
attack. 7z uses AES-256 with a SHA-256-based key derivation (many hash
iterations), so cracking is CPU/GPU-bound — success depends on password
weakness, not on a flaw in the format.

## When to use this

- You have a `.7z` file and need its password.
- You already have a 7z hash string (starts with `$7z$...`) to crack.
- You are auditing the strength of a 7z archive password.

Only proceed with proper authorization (your own file, a CTF, or an
engagement with written permission).

## Workflow overview

1. Extract the hash from the archive (`7z2john`).
2. Identify the hash format.
3. Crack it with hashcat (GPU, mode `11600`) or John the Ripper.
4. Read out the recovered password and verify it opens the archive.

## Step 1 — Extract the hash

`7z2john` (ships with John the Ripper's `run/` tools, often as a Perl or
Python script) reads the archive header and prints a `$7z$` hash.

```bash
# Locate the tool (name/path varies by install)
which 7z2john 7z2john.pl 2>/dev/null
ls /usr/share/john/7z2john.pl /opt/homebrew/opt/john*/share/john/7z2john.pl 2>/dev/null
find / -name '7z2john*' 2>/dev/null | head

# Extract (Perl version)
7z2john.pl secret.7z > hash.txt
# or Python version, if that's what's installed
python3 7z2john.py secret.7z > hash.txt

cat hash.txt
```

The output line looks like `secret.7z:$7z$2$19$0$...$...`. hashcat needs only
the `$7z$...` portion; John accepts the full `file:hash` line.

```bash
# Strip the "filename:" prefix for hashcat, keep only the $7z$ token
grep -o '\$7z\$[^ ]*' hash.txt > hash.hc
cat hash.hc
```

If `7z2john` is not installed, get it via John the Ripper (see
"Installing tools" below). The Perl script depends on `Compress::Raw::Lzma`
for some archives; install `libcompress-raw-lzma-perl` if it errors.

## Step 2 — Identify the hash

- hashcat mode: **`11600`** (7-Zip).
- John format: **`7z`** (auto-detected from the `$7z$` prefix).

The `$7z$` fields encode the KDF cost, AES params, and ciphertext; you do not
need to parse them by hand.

## Step 3a — Crack with hashcat (preferred if a GPU is available)

```bash
# Dictionary attack
hashcat -m 11600 -a 0 hash.hc /path/to/wordlist.txt

# Dictionary + rules (good default: rockyou + best64)
hashcat -m 11600 -a 0 hash.hc rockyou.txt -r /usr/share/hashcat/rules/best64.rule

# Mask / brute force (example: 8 chars, all classes) — only for short passwords
hashcat -m 11600 -a 3 hash.hc '?a?a?a?a?a?a?a?a'

# Show a previously cracked result
hashcat -m 11600 hash.hc --show
```

Notes:
- 7z has a very high iteration count, so keyspace throughput is low. Prefer
  targeted wordlists + rules over unbounded brute force.
- Add `--status --status-timer=30` to monitor progress on long runs.
- Cracked passwords land in hashcat's potfile (`~/.hashcat/hashcat.potfile`);
  `--show` reprints them.

## Step 3b — Crack with John the Ripper (CPU fallback)

```bash
# Dictionary attack (use the full file:hash line)
john --format=7z --wordlist=rockyou.txt hash.txt

# With rules
john --format=7z --wordlist=rockyou.txt --rules=Jumbo hash.txt

# Incremental / brute force
john --format=7z --incremental hash.txt

# Show recovered passwords
john --format=7z --show hash.txt
```

## Step 4 — Verify

Confirm the password actually opens the archive:

```bash
7z t -p'RECOVERED_PASSWORD' secret.7z   # test integrity
7z x -p'RECOVERED_PASSWORD' secret.7z   # extract
```

Report the recovered password to the user.

## Installing tools (if missing)

```bash
# Debian/Ubuntu
sudo apt-get install -y john hashcat p7zip-full
#   7z2john.pl -> /usr/share/john/7z2john.pl  (or /usr/sbin/7z2john)

# macOS (Homebrew)
brew install john-jumbo hashcat sevenzip
#   7z2john -> $(brew --prefix)/share/john/7z2john.pl

# From source (John "jumbo" has the 7z2john scripts under run/)
git clone https://github.com/openwall/john && cd john/src && ./configure && make -sj4
ls ../run/7z2john*
```

Wordlists: `rockyou.txt` is the standard starter (often at
`/usr/share/wordlists/rockyou.txt`, sometimes gzipped —
`gunzip -k rockyou.txt.gz`). SecLists provides broader coverage.

## Tips & gotchas

- **hashcat vs John input differ:** hashcat wants the bare `$7z$...` token;
  John wants the whole `filename:$7z$...` line. Mixing them causes
  "No hashes loaded" / "Token length exception".
- **"Salt-value exception" / truncated hash:** re-extract; very large archives
  produce long hashes — do not manually edit or wrap the line.
- **Compressed-header archives:** `7z2john` may embed a chunk of compressed
  data in the hash; this is normal and needed for verification.
- **Speed reality check:** 7z KDF is deliberately slow. A weak/human password
  from a wordlist may fall in seconds–minutes; a random 10+ char password is
  effectively infeasible to brute force. Set expectations accordingly and lead
  with dictionary + rules.
- **Resume long runs:** hashcat supports `--restore`; John checkpoints to
  `john.pot` / `.rec` automatically.
- **Keep the potfile:** re-running with `--show` retrieves prior results
  without recracking.

## Authorization

Only crack archives you own or are explicitly authorized to test (CTF,
documented pentest scope, or personal password recovery). Do not use against
third-party data without permission.