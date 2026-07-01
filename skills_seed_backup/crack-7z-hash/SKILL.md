---
name: crack-7z-hash
description: Recover a password from a password-protected 7z archive by extracting its hash with 7z2john and cracking it with John the Ripper, then extract the archive contents. Use when given a `.7z` file whose password is unknown and a wordlist is available.
---

# Crack a password-protected 7z archive

## Procedure

1. **Install required tools.**
   - `p7zip-full` (provides the `7z` CLI for extraction).
   - `John the Ripper` (provides `john` and, in most builds, the `*2john` helper scripts).
   Install via the system package manager (e.g. `apt-get install p7zip-full john`).

2. **Extract the hash from the archive.**
   Run the matching `*2john` helper (commonly `7z2john` on PATH, or `john`'s bundled variant) against the archive and write the hash to a file:
   ```
   7z2john secrets.7z > hash.txt
   ```
   Some builds name the tool `7z2john.pl`; the wrapper `7z2john` resolves it.

3. **Crack the hash with a wordlist.**
   Run `john` against the hash file using a wordlist such as the one shipped with John (`password.lst`):
   ```
   john --wordlist=/usr/share/john/password.lst hash.txt
   ```
   If a session file already exists and you want to keep going, add `--restore`. To see the cracked password without rerunning, use `john --show hash.txt`.

4. **Extract the archive with the recovered password.**
   Use the password (no space after `-p`) with `7z x`:
   ```
   7z x -p<PASSWORD> secrets.7z
   ```
   Verify the password first with a quick `7z t -p<PASSWORD> secrets.7z` if the archive layout is unknown.

5. **Locate the target file and read it.**
   Files are extracted into the current directory (or a subdirectory mirroring the archive tree). `ls` the extracted contents, identify the target file by name/extension, and read it.

## Notes

- On Debian/Ubuntu, John the Ripper's `7z2john` may live under `/usr/share/john/` even when `john` itself is on PATH — invoke it by full path if the bare `7z2john` is not found.
- Some 7z headers include the encryption method; very old or rare formats may need a Jumbo build of John.
- If the wordlist fails, try a larger one (e.g. `rockyou.txt`) or add rules: `john --wordlist=... --rules hash.txt`.