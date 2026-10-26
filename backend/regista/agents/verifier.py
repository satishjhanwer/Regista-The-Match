"""Verifier: mechanical grounding check of a rendering against its insight's facts.

Deterministic by design. The gate that keeps ungrounded claims off screen must
not itself be able to hallucinate. Rules, per claim:

1. Every cited ``fact_id`` exists in the insight.
2. Every number in the text matches a cited fact: its value, its previous value, a number
   inside a string value (score "2-1", clock "59:15") or its label (window "5 min"), the 0-1
   value as a percentage, or the moment's own clock. A claim with no citations ("colour") may contain no numbers.
3. Every player named is an entity of the insight or the value of a cited fact.
   Every team named appears in the insight (entities, or fact keys, labels or values).
4. Attribution: when a cited numeric fact's label names a team or player ("Northvale FC passes
   under pressure"), that subject must be named in the claim, the previous claim or the headline.
   Numbers that match but are pinned on the wrong subject (or on nobody) are rejected.

The headline is checked against all of the insight's facts. Length limits come from the contract.
Numbers are read after normalizing Devanagari digits and decimal commas, so the
check works the same in every language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..contracts.events import MatchMeta
from ..contracts.insight import Claim, Fact, Insight, RenderedInsight, Verification

HEADLINE_MAX, BODY_MAX = 80, 320
_DEVANAGARI_LETTER = re.compile(r"[ऀ-ॿ]")
_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def numbers_in(text: str) -> list[float]:
    text = _DECIMAL_COMMA.sub(".", text.translate(_DEVANAGARI))
    return [float(m) for m in _NUMBER.findall(text)]


def allowed_numbers(fact: Fact) -> set[float]:
    out: set[float] = set(numbers_in(fact.label))  # e.g. the window in "xG (10 min)"
    for v in (fact.value, fact.previous_value):
        if v is None:
            continue
        if isinstance(v, str):
            out.update(numbers_in(v))
            continue
        fv = float(v)
        out.update({fv, round(fv), round(fv, 1), round(fv, 2)})
        if isinstance(v, float) and 0.0 <= fv <= 1.0:
            out.add(round(fv * 100))
    return out


def _matches(n: float, allowed: set[float]) -> bool:
    return any(abs(n - a) < 1e-6 for a in allowed)


@dataclass
class VerifierReport:
    verification: Verification
    claim_issues: dict[int, list[str]] = field(default_factory=dict)  # claim index -> reasons
    headline_issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verification.status == "verified"

    def feedback(self) -> str:
        lines = [f"headline: {r}" for r in self.headline_issues]
        lines += [f"claim {i + 1}: {r}" for i, rs in sorted(self.claim_issues.items()) for r in rs]
        lines += [n for n in self.verification.notes if not n.startswith(("headline:", "claim "))]
        return "\n".join(lines)


class Verifier:
    def __init__(self, meta: MatchMeta) -> None:
        self.players: dict[str, tuple[str, ...]] = {}
        for team in (meta.home, meta.away):
            for p in team.players:
                self.players[p.player_id] = (p.name, p.short_name)
        # name, short name, id, plus the bare first word broadcasters use ("Northvale", "Saltmere")
        self.teams = {t.team_id: (t.name, t.short_name, t.team_id, t.name.split()[0]) for t in (meta.home, meta.away)}

    # ------------------------------------------------------------------ #
    def _entity_issues(self, text: str, insight: Insight, facts: list[Fact]) -> list[str]:
        issues = []
        fact_strings = {str(f.value) for f in facts} | {str(f.previous_value) for f in facts if f.previous_value is not None}
        for pid, names in self.players.items():
            if not any(_word_in(n, text) for n in names):
                continue
            if pid in insight.entities.player_ids or any(n in fact_strings for n in names):
                continue
            issues.append(f"mentions {names[1]}, who is not part of this insight")
        blob = " ".join(f"{f.key} {f.label} {f.value}" for f in insight.facts)
        for tid, names in self.teams.items():
            mentioned = any(_word_in(n, text) for n in names[:2]) or _word_in(tid, text)
            if mentioned and tid not in insight.entities.team_ids and not any(n in blob for n in names):
                issues.append(f"mentions {names[0]}, which is not part of this insight")
        return issues

    def _number_issues(self, text: str, facts: list[Fact], insight: Insight, colour: bool) -> list[str]:
        nums = numbers_in(text)
        if colour and nums:
            return [f"number {_fmt(nums[0])} with no cited fact"]
        allowed = set().union(*(allowed_numbers(f) for f in facts)) if facts else set()
        allowed |= set(numbers_in(insight.clock.display))
        return [f"number {_fmt(n)} does not match any cited fact" for n in nums if not _matches(n, allowed)]

    def _subjects(self, label: str) -> list[tuple[str, ...]]:
        """Name variants of each team or player that a fact label names."""
        out = [names for names in self.players.values() if any(_word_in(n, label) for n in names)]
        out += [names for names in self.teams.values() if any(_word_in(n, label) for n in names)]
        return out

    def _attribution_issues(self, claim: Claim, context: str, insight: Insight) -> list[str]:
        by_id = {f.fact_id: f for f in insight.facts}
        issues = []
        for fid in claim.fact_ids:
            f = by_id.get(fid)
            if f is None or isinstance(f.value, str) or not numbers_in(claim.text):
                continue
            subjects = self._subjects(f.label)
            if subjects and not any(_word_in(n, f"{claim.text} {context}") for names in subjects for n in names):
                issues.append(f"cites '{f.label}' but does not say who it is about (name {subjects[0][0]})")
        return issues

    def check_claim(self, claim: Claim, insight: Insight) -> list[str]:
        by_id = {f.fact_id: f for f in insight.facts}
        unknown = [fid for fid in claim.fact_ids if fid not in by_id]
        if unknown:
            return [f"cites unknown fact id {fid}" for fid in unknown]
        cited = [by_id[fid] for fid in claim.fact_ids]
        return self._number_issues(claim.text, cited, insight, not cited) + self._entity_issues(claim.text, insight, cited)

    def verify(self, rendered: RenderedInsight, insight: Insight) -> VerifierReport:
        notes: list[str] = []
        claim_issues: dict[int, list[str]] = {}
        for i, c in enumerate(rendered.claims):
            context = rendered.headline + (" " + rendered.claims[i - 1].text if i else "")
            issues = self.check_claim(c, insight) or self._attribution_issues(c, context, insight)
            if issues:
                claim_issues[i] = issues
        headline_issues = self._number_issues(rendered.headline, insight.facts, insight, False)
        headline_issues += self._entity_issues(rendered.headline, insight, insight.facts)
        if not rendered.claims:
            notes.append("no claims")
        if len(rendered.headline) > HEADLINE_MAX:
            notes.append(f"headline longer than {HEADLINE_MAX} characters")
        if len(rendered.body) > BODY_MAX:
            notes.append(f"body longer than {BODY_MAX} characters")
        if rendered.language == "hi":  # names stay in Latin script, but the sentences must be Hindi
            latin_only = [i + 1 for i, c in enumerate(rendered.claims) if not _DEVANAGARI_LETTER.search(c.text)]
            if latin_only:
                notes.append(f"claims {latin_only} are not in Hindi (Devanagari)")
        if rendered.body.strip() != " ".join(c.text.strip() for c in rendered.claims):
            notes.append("body must be exactly the claims joined by spaces")
        sc = rendered.stat_callout
        if sc is not None:
            fact = next((f for f in insight.facts if f.fact_id == sc.fact_id), None)
            if fact is None:
                notes.append(f"stat callout cites unknown fact id {sc.fact_id}")
            elif not all(_matches(n, allowed_numbers(fact)) for n in numbers_in(sc.value)):
                notes.append(f"stat callout value {sc.value!r} does not match fact {sc.fact_id}")
        notes = [f"headline: {r}" for r in headline_issues] + [f"claim {i + 1}: {r}" for i, rs in claim_issues.items() for r in rs] + notes
        rejected = len(claim_issues)
        status = "verified" if not notes else "rejected"
        return VerifierReport(
            Verification(status=status, checked_claims=len(rendered.claims), rejected_claims=rejected, notes=notes),
            claim_issues,
            headline_issues,
        )


def _word_in(word: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) is not None


def _fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else str(n)
