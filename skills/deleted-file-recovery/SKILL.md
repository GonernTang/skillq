---
name: deleted-file-recovery
description: Recover deleted files from a container or filesystem using digital forensic techniques. Use when a file (config, secret, password, key, log) appears to have been deleted, when overlayfs layers may still hold a copy, or when you need to recover content from an ext4/btrfs block device with extundelete/foremost.
---

# Deleted file recovery (containers / overlayfs / extundelete)

When a file disappears in a container or Linux host, the bytes are often still on disk or in a lower filesystem layer. Don't treat "file not found" as terminal — search the layers and the raw block device before giving up.

## Procedure

1. **Confirm the file is actually gone** before escalating. Run `ls -la`, `find`, and `stat` on the expected path. Note the filesystem mount (run `mount | grep overlay`, `df -T`, `cat /proc/mounts`). A permission error is NOT a missing file — try `sudo` or check capabilities first.
2. **Check overlayfs lower layers explicitly.** If the mount is overlay, parse `mount` output to get `lowerdir=` paths and walk each one (e.g. `grep -r 'pattern' /var/lib/docker/overlay2/*/diff/`). Files deleted from the upper layer are still intact in the lower layers — this is the fastest path and should be tried before disk-level tools.
3. **Try host-level recovery next.** If you have access to the host filesystem backing the container, use `extundelete <device> --restore-all` (for ext3/ext4) or `foremost -t all -i <image> -o /tmp/out` (signature-based carve, works on any FS). Get the block device from `mount` or `lsblk`; if it's a loop/dm device, target the loop backing file.
4. **Check journaling and snapshots.** `debugfs -R 'lsdel'` for ext2/3/4 deleted inodes, `btrfs restore` for btrfs subvolume snapshots, ZFS snapshots via `zfs clone`. These contain the file even after deletion from the live FS.
5. **When the file is recovered, parse for the requested artifact.** Common patterns: `PASSWORD=...`, `password: ...` (YAML), `secret = "..."` (TOML/INI), JSON `"password": "..."`. Use `grep -aE` (binary-safe) and write the extracted value to the required output path.
6. **Stop recovery attempts once you have the artifact.** Don't run every tool — first lowerdir hit or first extundelete restore is usually enough.

## Diagnostic checklist

Run these BEFORE committing to a recovery approach:

1. `mount | grep -E 'overlay|/$'` — what filesystem and what layers back this container/host? If overlay, list the `lowerdir` paths and grep them directly. (Single fastest check — most container cases resolve here.)
2. `ls -la /path/to/missing/file` and `stat /path/to/missing/file` — distinguish "doesn't exist" from "permission denied" from "exists but empty". A 0-byte file means the file was created and emptied, not deleted — look for the original write in logs/history.
3. `lsblk && df -T /` — identify the block device and FS type. extundelete needs ext3/4; foremost needs a raw image or device; btrfs needs `btrfs restore`. Picking the wrong tool wastes a full scan.
4. `grep -r 'known-token-or-format' / 2>/dev/null | head` — if any single byte of the file content is predictable (a header line, the user remembers a substring, the filename pattern is known), grep the whole tree before doing block-level recovery. Fastest path when it works.

## Stop signal

If lowerdir scan, extundelete, foremost, and debugfs each fail to surface the file or its content, the data is genuinely gone (overwritten, never written, or encrypted) — STOP and tell the user the file is unrecoverable with the tools available. Do not chain a fifth recovery tool hoping for a different result; the diagnostic above already covered the recovery space for a typical Linux container.