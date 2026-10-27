"""Verifier: mechanical grounding check of a rendering against its insight's facts.

Deterministic by design. The gate that keeps ungrounded claims off screen must
not itself be able to hallucinate. Rules, per claim:

1. Every cited ``fact_id`` exists in the insight.
2. Every number in the text matches a cited fact: its value, its previous value, a number
   inside a string value (score "2-1", clock "59:15") or its label (window "5 min"), the 0-1
   value as a percentage, or the moment's own clock. A claim with no citations ("colour") may contain no numbers.
3. Every player named is an entity of the insight or the value of a cited fact.
   Every team named appears in the insight (entities, or fact keys, labels or values).
4. Affiliation: a player tied to a team ("Shapira scores for Northvale", "para Northvale") must play for it.
5. Categories: when the moment's facts say "through ball" or "header", no claim may use another category's word
   ("cross", "centro") for it, in any language.
6. Attribution: when a cited numeric fact's label names a team or player ("Northvale FC passes
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
# Function words for a mechanical language check of es / en renderings (names and numbers are language-neutral).
_STOP = {
    "en": {"the", "of", "and", "is", "are", "was", "with", "for", "from", "their", "his", "her", "they", "now", "in", "to", "has"},
    "es": {"el", "la", "los", "las", "de", "del", "y", "que", "en", "con", "por", "su", "sus", "se", "un", "una", "es", "al"},
    # not a rendering language: Portuguese is what a small model drifts into when asked for Spanish
    "pt": {"seu", "sua", "seus", "suas", "da", "das", "dos", "em", "não", "com", "um", "uma", "ao", "pelo", "pela", "é"},
}
_RENDER_LANGS = ("en", "es")

# Words for categorical fact values, per language. A claim may not use another value's words.
_CATEGORY_WORDS = {
    "pass": {
        "through ball": ("through ball", "through-ball", "pase al hueco", "pase filtrado", "थ्रू बॉल"),
        "cross": ("cross", "centro", "क्रॉस"),
    },
    "finish": {
        "header": ("header", "headed", "cabeza", "cabezazo", "हेडर"),
        "foot": ("right foot", "left foot", "con la derecha", "con la izquierda", "pierna derecha", "pierna izquierda"),
    },
}
_CATEGORY_OF = {"through ball": ("pass", "through ball"), "cross": ("pass", "cross"), "header": ("finish", "header")}
_CATEGORY_OF |= {v: ("finish", "foot") for v in ("right foot", "left foot")}
_DEVANAGARI_LETTER = re.compile(r"[ऀ-ॿ]")
_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


# Number words and ordinals count as numbers when they quantify a football noun ("second goal", "only one
# shot", "segundo gol"). Restricting them to these nouns keeps "second half" or "no one" from false rejections.
_WORD_VALUES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "once": 1,
    "twice": 2,
    "brace": 2,
    "hat-trick": 3,
    "uno": 1,  # not "un" / "una": in Spanish they are usually the article "a"
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "primer": 1,
    "primero": 1,
    "primera": 1,
    "segundo": 2,
    "segunda": 2,
    "tercer": 3,
    "tercero": 3,
    "tercera": 3,
    "cuarto": 4,
    "cuarta": 4,
    "quinto": 5,
    "quinta": 5,
}
_COUNTED = (
    r"goals?|shots?|assists?|saves?|chances?|appearances?|games?|matches|match|"
    r"goles?|gol|tiros?|disparos?|asistencias?|paradas?|ocasi[oó]n|ocasiones|partidos?"
)
_NUMBER_WORD = re.compile(
    rf"(?<![\w-])({'|'.join(sorted(map(re.escape, _WORD_VALUES), key=len, reverse=True))})\s+(?:[^\W\d_]+\s+)?(?:{_COUNTED})\b",
    re.IGNORECASE,
)
_NON_LATIN_LETTER = re.compile(r"[^\W\d_a-zA-Z\u00C0-\u024F]")


def counted_words(text: str) -> list[float]:
    """Values of number words that quantify a football noun, e.g. 'his second goal' -> [2.0]."""
    return [float(_WORD_VALUES[m.group(1).lower()]) for m in _NUMBER_WORD.finditer(text)]


def numbers_in(text: str) -> list[float]:
    """Every number written in digits, after normalizing Devanagari digits and decimal commas."""
    text = _DECIMAL_COMMA.sub(".", text.translate(_DEVANAGARI))
    return [float(m) for m in _NUMBER.findall(text)]


def allowed_numbers(fact: Fact) -> set[float]:
    """Numbers a claim citing ``fact`` may contain."""
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
    """The Verifier's verdict, with reasons per claim and for the headline."""

    verification: Verification
    claim_issues: dict[int, list[str]] = field(default_factory=dict)  # claim index -> reasons
    headline_issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the rendering passed every check."""
        return self.verification.status == "verified"

    def feedback(self) -> str:
        """Reasons as plain lines, sent back to the Narrator for its retry."""
        lines = [f"headline: {r}" for r in self.headline_issues]
        lines += [f"claim {i + 1}: {r}" for i, rs in sorted(self.claim_issues.items()) for r in rs]
        lines += [n for n in self.verification.notes if not n.startswith(("headline:", "claim "))]
        return "\n".join(lines)


class Verifier:
    """Mechanical grounding check of renderings against their insight (rules in the module docstring)."""

    def __init__(self, meta: MatchMeta) -> None:
        self.players: dict[str, tuple[str, ...]] = {}
        self.team_of: dict[str, str] = {}
        for team in (meta.home, meta.away):
            for p in team.players:
                self.players[p.player_id] = (p.name, p.short_name)
                self.team_of[p.player_id] = team.team_id
        # name, short name, id, plus the bare first word broadcasters use ("Northvale", "Saltmere")
        self.teams = {t.team_id: (t.name, t.short_name, t.team_id, t.name.split()[0]) for t in (meta.home, meta.away)}

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
        nums = numbers_in(text) + counted_words(text)
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

    def _affiliation_issues(self, text: str) -> list[str]:
        """A player tied to a team by "for" / "para" / "के लिए" must play for that team."""
        issues = []
        for pid, names in self.players.items():
            if not any(_word_in(n, text) for n in names):
                continue
            own = self.team_of[pid]
            for tid, tnames in self.teams.items():
                if tid == own:
                    continue
                for tn in tnames:
                    t = re.escape(tn)
                    tied = re.search(rf"(?<!\w)(?:for|para)\s+(?:[^\W\d_]+\s+){{0,2}}(?:the\s+|el\s+)?{t}(?!\w)", text, re.IGNORECASE)
                    if tied or re.search(rf"(?<!\w){t}\s+के\s+लिए", text):
                        issues.append(f"ties {names[1]} to {tnames[0]}, but {names[1]} plays for {self.teams[own][0]}")
                        break
        return issues

    @staticmethod
    def _category_issues(text: str, insight: Insight) -> list[str]:
        """Words for a different pass type or finish than the moment's facts state."""
        issues = []
        actual = {_CATEGORY_OF[v] for f in insight.facts if isinstance(f.value, str) and (v := f.value) in _CATEGORY_OF}
        low = text.lower()
        for group, value in actual:
            for other, words in _CATEGORY_WORDS[group].items():
                if other == value:
                    continue
                hit = next((w for w in words if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low)), None)
                if hit:
                    issues.append(f"says '{hit}' but the facts say {value}")
        return issues

    def check_claim(self, claim: Claim, insight: Insight) -> list[str]:
        """Citation, number and entity issues of one claim (empty list when it passes)."""
        by_id = {f.fact_id: f for f in insight.facts}
        unknown = [fid for fid in claim.fact_ids if fid not in by_id]
        if unknown:
            return [f"cites unknown fact id {fid}" for fid in unknown]
        cited = [by_id[fid] for fid in claim.fact_ids]
        return (
            self._number_issues(claim.text, cited, insight, not cited)
            + self._entity_issues(claim.text, insight, cited)
            + self._affiliation_issues(claim.text)
            + self._category_issues(claim.text, insight)
        )

    def verify(self, rendered: RenderedInsight, insight: Insight) -> VerifierReport:
        """Check a whole rendering: every claim, attribution, the headline, language, shape and the stat callout."""
        notes: list[str] = []
        claim_issues: dict[int, list[str]] = {}
        for i, c in enumerate(rendered.claims):
            context = rendered.headline + (" " + rendered.claims[i - 1].text if i else "")
            issues = self.check_claim(c, insight) or self._attribution_issues(c, context, insight)
            if issues:
                claim_issues[i] = issues
        headline_issues = self._number_issues(rendered.headline, insight.facts, insight, False)
        headline_issues += self._entity_issues(rendered.headline, insight, insight.facts)
        headline_issues += self._affiliation_issues(rendered.headline) + self._category_issues(rendered.headline, insight)
        if not rendered.claims:
            notes.append("no claims")
        if not _substantive(rendered.headline):
            notes.append("headline is empty or a placeholder")
        for i, c in enumerate(rendered.claims):
            if not _substantive(c.text):
                notes.append(f"claim {i + 1} is empty or a placeholder")
        if len(rendered.headline) > HEADLINE_MAX:
            notes.append(f"headline longer than {HEADLINE_MAX} characters")
        if len(rendered.body) > BODY_MAX:
            notes.append(f"body longer than {BODY_MAX} characters")
        if rendered.language == "hi":  # names stay in Latin script, but the sentences must be Hindi
            latin_only = [i + 1 for i, c in enumerate(rendered.claims) if not _DEVANAGARI_LETTER.search(c.text)]
            if latin_only:
                notes.append(f"claims {latin_only} are not in Hindi (Devanagari)")
        elif rendered.language in _RENDER_LANGS:
            foreign = [i + 1 for i, c in enumerate(rendered.claims) if _NON_LATIN_LETTER.search(c.text)]
            if foreign or _NON_LATIN_LETTER.search(rendered.headline):
                notes.append(f"text outside the Latin script in a {rendered.language} rendering (claims {foreign})")
            # A claim with no function word of the requested language but some of another one is in the wrong language.
            others = [lang for lang in _STOP if lang != rendered.language]
            wrong = [
                i + 1
                for i, c in enumerate(rendered.claims)
                if _language_votes(c.text, rendered.language) == 0 and sum(_language_votes(c.text, o) for o in others) >= 1
            ]
            if wrong:
                notes.append(f"claims {wrong} are not in the requested language ({rendered.language})")
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


def _language_votes(text: str, lang: str) -> int:
    return sum(1 for w in re.findall(r"[^\W\d_]+", text.lower()) if w in _STOP[lang])


def _substantive(text: str) -> bool:
    """At least two whitespace-separated tokens containing a letter: rules out "", "...", "-" and similar
    placeholders. Token-based because Devanagari vowel signs are combining marks, not word characters."""
    return sum(1 for tok in text.split() if re.search(r"[^\W\d_]", tok)) >= 2


def _word_in(word: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) is not None


def _fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else str(n)
