---
name: crack-7z-archive
description: Crack a password-protected 7z archive using John the Ripper and extract its contents. Use when given an encrypted .7z file and a wordlist to recover the password and retrieve the archive contents.
---

# Crack a password-protected 7z archive

Recover the password of an AES-encrypted 7z archive via John the Ripper, then extract its contents.

## Prerequisites

Install the required tools (Debian/Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y p7zip-full john libcompress-raw-lzma-perl
```

- `p7zip-full` provides the `7z` CLI.
- `john` is John the Ripper (community / jumbo build supports the 7z hash format).
- `libcompress-raw-lzma-perl` provides the `Compress::Raw::Lzma` Perl module required by `7z2john.pl`.

## Procedure

### 1. Confirm the archive is encrypted

```bash
7z l <archive>.7z
```

Look for a line containing `AES` under the `Method` column. If AES is not present, this skill does not apply.

### 2. Extract a John-compatible hash

Locate `7z2john.pl` (commonly shipped under John's `run/` directory, e.g. `/usr/share/john/7z2john.pl` or in the jumbo source tree).

```bash
7z2john.pl <archive>.7z > <archive>.hash
```

If the script fails with a missing-module error mentioning `Compress::Raw::Lzma`, install `libcompress-raw-lzma-perl` (or `perl-Compress-Raw-Lzma` on RPM systems) and retry.

Inspect the hash file to confirm a non-empty `$7z$...$` line was produced.

### 3. Crack the password with John

```bash
john --wordlist=<wordlist> <archive>.hash
```

To monitor progress in another terminal: `john --show <archive>.hash`. Once cracked, retrieve the recovered password with `john --show <archive>.hash` (it prints `user:password`).

If no candidate is found, try a larger wordlist, apply mangling rules (`--rules`), or run incremental mode (`--incremental`).

### 4. Extract the archive

```bash
7z x <archive>.7z -p<RECOVERED_PASSWORD> -o<output_dir> -y
```

- `-p<password>` — supply the password immediately after `p` with no space (escape special shell characters as needed, or use `--` and `-ppassword` quoting).
- `-o<dir>` — output directory (created if missing; the path must be followed immediately by `o`, no space).
- `-y` — assume "Yes" on overwrite/permission prompts (use only when extracting into a fresh or sacrificial directory).

### 5. Verify the extraction

List the output directory and inspect the recovered file(s). If the task specifies a target file and required content, write the required content to the designated solution path and confirm the file exists with the expected contents.

## Pitfalls

- `-p` and `-o` flags must butt directly against their argument — a space turns the argument into a positional filename.
- `7z2john.pl` writes to stdout; forgetting the redirect silently discards the hash.
- John requires the **jumbo** build for `$7z$` support; the stock `john` package on some distros does not include it.
- Long or unusual passwords will not be found via a small wordlist — escalate to rules or incremental mode before concluding the password is unrecoverable.