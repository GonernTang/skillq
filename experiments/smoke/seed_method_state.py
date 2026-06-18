#!/usr/bin/env python3
"""One-off: build a method_state.json with all seed_skills pre-populated.

The SkillQ paper method's container_wiring only reads
`library.skills` from method_state.json. There is no code path that
walks a seed_skills/ directory and adds skills to the library. This
script is a temporary work-around for the smoke test: it scans
seed_skills/, reads each SKILL.md, and writes a state file with
library.skills pre-filled so AgenticSearchWriter has something to
materialize into skillq_skills/<id>/SKILL.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SEED_DIR = Path("/home/gonern/workspace/skillq/experiments/smoke/seed_skills")
STATE_PATH = Path(
    "/home/gonern/workspace/skillq/output/tb2_git_smoke_hook/"
    ".skillq_library/.state/method_state.json"
)
SEED_INITIAL_Q = 0.5


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_skill_id(skill_md: Path, dir_name: str) -> str:
    """Extract a short skill_id from the YAML frontmatter's `name:`.

    Falls back to the directory name (lqrl uses dashes, e.g.
    'affaan-m-git-workflow' → name 'git-workflow').
    """
    raw = skill_md.read_text(encoding="utf-8")
    m = _FM_RE.match(raw)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if k.strip() == "name":
                v = v.strip().strip('"').strip("'").strip()
                if v:
                    return v
    return dir_name


def main() -> int:
    if not SEED_DIR.is_dir():
        print(f"seed dir not found: {SEED_DIR}", file=sys.stderr)
        return 1

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    skills: dict[str, dict] = {}
    q_table: list[list] = []

    for skill_dir in sorted(p for p in SEED_DIR.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            print(f"  skip {skill_dir.name}: no SKILL.md", file=sys.stderr)
            continue
        body = skill_md.read_text(encoding="utf-8")
        sid = parse_skill_id(skill_md, skill_dir.name)
        # de-dup: if two dirs have the same frontmatter `name`, last wins
        if sid in skills:
            print(f"  dedup {sid} (from {skill_dir.name}, kept earlier)", file=sys.stderr)
            continue
        skills[sid] = {
            "body": body,
            "n_retrievals": 0,
            "n_uses": 0,
            "n_success": 0,
            "metadata": {"source": "seed", "seed_dir": skill_dir.name},
        }
        q_table.append([sid, SEED_INITIAL_Q])

    state = {
        "step": 0,
        "seed_initial_q": SEED_INITIAL_Q,
        "q_table": q_table,
        "library": {
            "b_max": 50,
            "skills": skills,
        },
    }

    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {STATE_PATH}")
    print(f"  skills: {len(skills)}")
    print(f"  sample ids: {list(skills)[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
