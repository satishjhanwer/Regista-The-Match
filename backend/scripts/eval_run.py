"""Evaluate a recorded warm-path run: how often the model's drafts were grounded, and why the Verifier rejected them.

    python scripts/eval_run.py ../data/RGS-2026-0001.renders.json [--markdown]

Reported:

* on-air audit: every rendering in the file is checked again with today's Verifier (should be 100%)
* model drafts: first-draft pass rate, revision success, fallback rate, per language
* rejection reasons, grouped by Verifier rule
* claims on air: how many, how many cite facts, how many are fan colour (no numbers allowed)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from regista.agents.orchestrator import RenderResult  # noqa: E402
from regista.agents.verifier import Verifier  # noqa: E402
from regista.contracts.events import MatchFile  # noqa: E402

RULES = [
    ("number not in a cited fact", r"number .* does not match|number .* with no cited fact"),
    ("unknown fact id", r"unknown fact id"),
    ("number not attributed to its team / player", r"does not say who it is about"),
    ("names someone not in the moment", r"not part of this insight"),
    ("player tied to the wrong club", r"ties .* to .*, but"),
    ("wrong pass type or finish", r"but the facts say"),
    ("wrong language or script", r"not in the requested language|not in Hindi|outside the Latin script"),
    ("placeholder or empty text", r"placeholder|no claims"),
    ("too long for the overlay", r"limit is"),
    ("body / stat callout shape", r"body must be|stat callout"),
]


def rule_of(note: str) -> str:
    """The Verifier rule a rejection note belongs to."""
    return next((name for name, pattern in RULES if re.search(pattern, note)), "other")


def evaluate(renders_path: Path, match_path: Path) -> dict:
    """Compute every metric for one recorded run."""
    data = json.loads(renders_path.read_text(encoding="utf-8"))
    match = MatchFile.model_validate(json.loads(match_path.read_text(encoding="utf-8")))
    verifier = Verifier(match.meta)
    rows = [RenderResult.from_json(r) for r in data["renders"]]

    audit_ok = sum(verifier.verify(r.rendered, r.insight).ok for r in rows)
    sources = Counter(r.source for r in rows)
    drafts = first_pass = revised = 0
    by_lang: dict[str, Counter] = defaultdict(Counter)
    reasons: Counter = Counter()
    for r in rows:
        checks = [s for s in r.trace if s.agent == "verifier" and s.action != "check draft 0"]
        if not checks:
            continue
        drafts += len(checks)
        first = checks[0].status == "ok"
        first_pass += first
        revised += r.source == "llm_revised"
        lang = r.rendered.language
        by_lang[lang]["renders"] += 1
        by_lang[lang]["first_pass"] += first
        by_lang[lang]["on_air_llm"] += r.source in ("llm", "llm_revised")
        for s in checks:
            if s.status == "rejected":
                for note in s.detail.get("notes", []):
                    reasons[rule_of(note)] += 1
    model_renders = sum(c["renders"] for c in by_lang.values())
    claims = [c for r in rows for c in r.rendered.claims]
    narrated_by = Counter(r.narrated_by or "unknown" for r in rows)
    return {
        "renders": len(rows),
        "narrated_by": dict(narrated_by.most_common()),
        "audit_ok": audit_ok,
        "sources": dict(sources),
        "model_renders": model_renders,
        "model_drafts": drafts,
        "first_draft_pass": first_pass,
        "revised_after_feedback": revised,
        "fallback_after_rejection": sources.get("template_fallback", 0),
        "by_language": {k: dict(v) for k, v in sorted(by_lang.items())},
        "rejections_by_rule": dict(reasons.most_common()),
        "claims_on_air": len(claims),
        "claims_citing_facts": sum(bool(c.fact_ids) for c in claims),
        "colour_claims": sum(not c.fact_ids for c in claims),
    }


def markdown(m: dict) -> str:
    """The metrics as Markdown tables, ready for the README."""
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"  # noqa: E731
    out = [
        "| Metric | Value |",
        "| --- | --- |",
        f"| Renderings on air re-checked by today's Verifier | {m['audit_ok']} / {m['renders']} pass |",
        f"| Narrated by | {', '.join(f'{k} ({v})' for k, v in m['narrated_by'].items())} |",
        f"| Renderings attempted by the model | {m['model_renders']} |",
        f"| Model drafts checked | {m['model_drafts']} |",
        f"| First draft passed | {m['first_draft_pass']} ({pct(m['first_draft_pass'], m['model_renders'])}) |",
        f"| Passed after Verifier feedback | {m['revised_after_feedback']} |",
        f"| Blocked twice, verified template aired | {m['fallback_after_rejection']}"
        f" ({pct(m['fallback_after_rejection'], m['model_renders'])}) |",
        f"| Claims on air citing facts / fan colour | {m['claims_citing_facts']} / {m['colour_claims']} |",
        "",
        "| Rejection reason | Count |",
        "| --- | --- |",
        *(f"| {k} | {v} |" for k, v in m["rejections_by_rule"].items()),
    ]
    return "\n".join(out)


def main() -> None:
    """Print the evaluation of a recorded run (JSON, or Markdown with ``--markdown``)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("renders", type=Path)
    ap.add_argument("--match", type=Path, default=Path(__file__).resolve().parents[2] / "data" / "RGS-2026-0001.json")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    metrics = evaluate(args.renders, args.match)
    print(markdown(metrics) if args.markdown else json.dumps(metrics, indent=1))


if __name__ == "__main__":
    main()
