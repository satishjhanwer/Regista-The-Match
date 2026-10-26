"""Verifier rules, template narration in every language and mode, and profile relevance."""

from __future__ import annotations

import pytest

from regista.agents.profiles import PRESETS, display_for, profile_from_params, relevance
from regista.agents.templates import TemplateNarrator
from regista.agents.verifier import Verifier, numbers_in
from regista.contracts.insight import Claim, FanProfile
from regista.detect import run_match

SEEDS = [1, 2, 3, 4, 5, 7]
PROFILES = list(PRESETS.values()) + [
    FanProfile(profile_id=f"t-{lang}-{mode}", mode=mode, language=lang, favorite_team_id="SLM", focus_player_id="SLM-11")
    for lang in ("en", "es", "hi")
    for mode in ("analyst", "casual", "player_focus")
]


@pytest.fixture(scope="module")
def seed7(sims):
    match, _ = sims[7]
    insights, _ = run_match(match)
    return match, insights


def press_insight(insights):
    return next(i for i in insights if i.kind == "press_change")


def test_numbers_are_language_neutral():
    assert numbers_in("0,57 presiones y 64%") == [0.57, 64.0]
    assert numbers_in("गोल नंबर ५०") == [50.0]
    assert numbers_in("59:15 and 2-1") == [59.0, 15.0, 2.0, 1.0]


@pytest.mark.parametrize("seed", SEEDS)
def test_every_template_rendering_verifies(sims, seed):
    match, _ = sims[seed]
    insights, _ = run_match(match)
    narrator, verifier = TemplateNarrator(match.meta), Verifier(match.meta)
    for ins in insights:
        for profile in PROFILES:
            r = narrator.render(ins, profile)
            report = verifier.verify(r, ins)
            assert report.ok, (ins.kind, profile.profile_id, report.verification.notes, r.body)
            assert r.language == profile.language and r.claims


def test_verifier_rejects_wrong_number(seed7):
    match, insights = seed7
    ins = press_insight(insights)
    r = TemplateNarrator(match.meta).render(ins, PRESETS["analyst-en"])
    bad = r.claims[0].text.replace("64%", "71%")
    claims = [Claim(text=bad, fact_ids=r.claims[0].fact_ids), *r.claims[1:]]
    r2 = r.model_copy(update={"claims": claims, "body": " ".join(c.text for c in claims)})
    report = Verifier(match.meta).verify(r2, ins)
    assert not report.ok and report.verification.rejected_claims == 1
    assert "number 71" in report.feedback()


def test_verifier_rejects_unknown_fact_colour_numbers_and_strangers(seed7):
    match, insights = seed7
    ins = press_insight(insights)
    v = Verifier(match.meta)
    assert v.check_claim(Claim(text="Pressing hard.", fact_ids=["nope"]), ins) == ["cites unknown fact id nope"]
    assert v.check_claim(Claim(text="They pressed 3 times.", fact_ids=[]), ins)
    assert v.check_claim(Claim(text="Pressing hard.", fact_ids=[]), ins) == []
    issues = v.check_claim(Claim(text="Balogun leads the press.", fact_ids=[ins.facts[0].fact_id]), ins)
    assert any("Balogun" in i for i in issues)


def test_verifier_checks_shape(seed7):
    match, insights = seed7
    ins = press_insight(insights)
    r = TemplateNarrator(match.meta).render(ins, PRESETS["analyst-en"])
    v = Verifier(match.meta)
    assert v.verify(r, ins).ok
    assert not v.verify(r.model_copy(update={"body": r.body + " Extra."}), ins).ok
    assert not v.verify(r.model_copy(update={"claims": [], "body": ""}), ins).ok


def test_relevance_by_mode(seed7):
    _, insights = seed7
    focus, casual, analyst = PRESETS["focus-hi-nvl09"], PRESETS["casual-en-nvl"], PRESETS["analyst-en"]
    for ins in insights:
        assert relevance(ins, analyst) is not None
        if ins.kind == "goal":
            assert relevance(ins, focus) == 5 and relevance(ins, casual) == 5
        if ins.priority <= 2 and ins.kind not in ("milestone", "period_summary"):
            assert relevance(ins, casual) is None
    brace = next(i for i in insights if i.kind == "milestone" and "NVL-09" in i.entities.player_ids)
    assert relevance(brace, focus) == 5
    d = display_for(press_insight(insights), analyst)
    assert d.slot == "side_panel" and d.show_at_match_clock_s == press_insight(insights).clock.match_clock_s


def test_profile_from_params():
    assert profile_from_params("casual-es-slm") is PRESETS["casual-es-slm"]
    p = profile_from_params("casual-es-slm", language="hi", player="SLM-11")
    assert p.language == "hi" and p.focus_player_id == "SLM-11" and p.profile_id == "casual-hi-SLM-SLM-11-_"
    assert profile_from_params(language="xx").language == "en"


def test_verifier_rejects_numbers_pinned_on_the_wrong_subject(seed7):
    """The draft llama3.2:3b actually produced for the 61' press change: numbers right, meaning wrong."""
    match, insights = seed7
    ins = press_insight(insights)
    f1, f2 = ins.facts[0], ins.facts[1]  # Northvale FC passes under pressure; Saltmere pressures per Northvale pass
    v = Verifier(match.meta)
    text = "The player completed 64% of passes under pressure, while Saltmere Athletic applied 0.57 pressures per pass."
    wrong = Claim(text=text, fact_ids=[f1.fact_id, f2.fact_id])
    issues = v._attribution_issues(wrong, "Tactical Shift", ins)
    assert issues == ["cites 'Northvale FC passes under pressure' but does not say who it is about (name Northvale FC)"]
    right = Claim(text="Northvale now play 64% of their passes under pressure.", fact_ids=[f1.fact_id])
    assert v._attribution_issues(right, "Saltmere squeeze", ins) == []
    follow_up = Claim(text="They complete just 57% of them.", fact_ids=[ins.facts[2].fact_id])
    assert v._attribution_issues(follow_up, "x " + right.text, ins) == []


def test_extract_json_takes_the_first_object():
    from regista.agents.analyst import extract_json

    assert extract_json('Sure! ```json\n{"a": 1, "b": {"c": 2}}\n``` and also {"a": 9}') == {"a": 1, "b": {"c": 2}}
    assert extract_json('{"broken": } then {"ok": true}') == {"ok": True}
    with pytest.raises(ValueError):
        extract_json("no json at all")


def test_hindi_rendering_must_be_in_devanagari(seed7):
    match, insights = seed7
    ins = press_insight(insights)
    r = TemplateNarrator(match.meta).render(ins, PRESETS["focus-hi-nvl09"])
    v = Verifier(match.meta)
    assert v.verify(r, ins).ok
    english = [Claim(text="Saltmere Athletic are pressing high.", fact_ids=[])]
    bad = r.model_copy(update={"claims": english, "body": english[0].text})
    assert any("not in Hindi" in n for n in v.verify(bad, ins).verification.notes)


def test_spanish_rendering_must_be_spanish(seed7):
    match, insights = seed7
    ins = press_insight(insights)
    v = Verifier(match.meta)
    r = TemplateNarrator(match.meta).render(ins, PRESETS["casual-es-slm"])
    assert v.verify(r, ins).ok
    # what qwen2.5:3b produced for the Spanish casual viewer
    text = "Northvale FC now passes under pressure: 64% against Saltmere Athletic, up from 24% earlier."
    english = [Claim(text=text, fact_ids=[ins.facts[0].fact_id])]
    bad = r.model_copy(update={"claims": english, "body": text})
    assert any("not in the requested language (es)" in n for n in v.verify(bad, ins).verification.notes)


def test_number_words_and_foreign_script_are_checked(seed7):
    """Drafts qwen2.5:3b actually got past the digit-only checks in the first recording."""
    from regista.agents.verifier import counted_words

    assert counted_words("Shapira scored his second goal of the match") == [2.0]
    assert counted_words("Saltmere took only one shot") == [1.0]
    assert counted_words("Vukovic anota su segundo gol") == [2.0]
    assert counted_words("early in the second half, no one could stop him") == []

    match, insights = seed7
    goal = next(i for i in insights if i.kind == "goal" and i.entities.player_ids[0] == "SLM-09")
    v = Verifier(match.meta)
    scorer = next(f for f in goal.facts if f.key == "goal.scorer")
    tally = next(f for f in goal.facts if f.key == "SLM-09.match_goals")
    claim = Claim(text="Shapira scored his second goal of the match.", fact_ids=[scorer.fact_id, tally.fact_id])
    assert v.check_claim(claim, goal) == ["number 2 does not match any cited fact"]

    r = TemplateNarrator(match.meta).render(goal, PRESETS["casual-es-slm"])
    mixed = [Claim(text="Shapira anota su gol en la比赛中.", fact_ids=[scorer.fact_id])]
    bad = r.model_copy(update={"claims": mixed, "body": mixed[0].text})
    assert any("outside the Latin script" in n for n in v.verify(bad, goal).verification.notes)


@pytest.mark.parametrize(
    "text",
    [
        "Saltmere Athletic scores a crucial goal, tying the game 1-1.",  # English, one stopword
        "Vukovic anota seu segundo gol da partida, colocando o NVL em 2x1.",  # Portuguese
    ],
)
def test_spanish_viewer_rejects_english_and_portuguese_drafts(seed7, text):
    """Both drafts are what qwen2.5:3b wrote for the Spanish casual viewer in the second recording."""
    match, insights = seed7
    goal = next(i for i in insights if i.kind == "goal")
    r = TemplateNarrator(match.meta).render(goal, PRESETS["casual-es-slm"])
    bad = r.model_copy(update={"claims": [Claim(text=text, fact_ids=[])], "body": text})
    notes = Verifier(match.meta).verify(bad, goal).verification.notes
    assert any("not in the requested language (es)" in n for n in notes)
