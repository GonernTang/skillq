---
name: preserve-build-output
description: When building software that generates output artifacts (images, meshes, binaries, logs), ensure the build writes the artifact to the exact path and format the verifier expects. Use when building renderers, compilers emitting files, image generators, or any task where a downstream grader compares output bytes rather than exit codes.
---

# preserve-build-output

A green build (exit code 0, no stderr errors) is **not** the same as a successful submission. Many grading harnesses ignore exit codes entirely and instead read the bytes of a specific output path to compare against a reference. If the artifact is discarded, written to the wrong path, or saved under a different name, the local test looks fine but the submission fails.

## Why this fails silently

- The tool exited 0 → agent assumes success and moves on.
- The verifier, however, looks for a specific file (e.g. `output.png`, `scene.png`) at a specific path and finds nothing or the wrong content.
- Result: time spent debugging a "broken" implementation when the build was actually correct — only the output sink was wrong.

## Diagnostic checklist (run BEFORE committing to a build command)

1. **Identify the verifier's exact expected output.** Read the task spec, grader config, README "verification" section, or harness script. Record the full path, filename, and format the verifier will read (e.g. `output.png` at repo root, `+O/output.png`, `./build/result.obj`).
2. **Make the build write to that path explicitly.** Don't rely on tool defaults — defaults vary by version, working directory, and flags. Pass an explicit output flag (`+O/path`, `--out=path`, `-o path`) that matches the verifier's expected path byte-for-byte.
3. **Never discard the artifact stream.** Do NOT pipe the tool's output to `> /dev/null`, `| head`, or any redirect that swallows the artifact. Redirect only the logs/stderr if needed; keep the artifact on disk at the expected location.
4. **Re-run and verify the file exists with non-zero size.** After the build, `ls -la <expected path>` (or `file <path>`) and confirm: file exists, size > 0, format matches. A zero-byte or missing file is a failure regardless of exit code.

## Stop signal

If after the build, the expected output path does not exist, OR the file is zero bytes, OR the verifier reports "no output found" / "checksum mismatch" / "format unsupported" / "file not readable":
- **STOP** — do not declare the task complete.
- Reset: re-read the verifier spec to find the exact path and format. Re-run the build with an explicit output flag pointing to the verifier's path.
- Verify again: `file <output>` to confirm format, `stat` for size, and (if possible) visually inspect or compare header bytes against the reference.
- If the tool cannot write to the expected path directly, write to a temp path then `mv`/`cp` it to the exact expected path before reporting done.

## Anti-patterns to avoid

- Trusting exit code 0 as proof the artifact was created.
- Piping a renderer's stdout to `/dev/null` to "keep logs clean" — this discards the artifact.
- Writing to `./out.png` (or any default) when the verifier reads a different path.
- Assuming the working directory of the build equals the verifier's read path.
- Skipping a post-build `ls` because "the command clearly succeeded."