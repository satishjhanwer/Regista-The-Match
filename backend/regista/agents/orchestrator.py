"""Warm-path orchestration: Analyst -> Narrator -> Verifier, per insight and fan profile.

* The Analyst runs once per insight (single-flight; concurrent profiles share it).
* For each profile the Narrator drafts; the Verifier checks every claim. A rejected draft
  goes back to the Narrator once with the Verifier's reasons. A second rejection, a
  timeout or an error falls back to the template Narrator, which is verified as well.
* Results are cached by (insight_id, profile_id). A recorded cache makes demo runs
  deterministic and independent of model latency or rate limits.
* Every step is traced for the agent trace panel.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..contracts.events import MatchMeta
from ..contracts.insight import FanProfile, Insight, RenderedInsight, Verification
from .analyst import Analyst, Brief, rule_brief
from .context import InsightContext
from .narrator import DraftShapeError, LLMNarrator
from .templates import TemplateNarrator
from .verifier import Verifier

# Per-call budget for the Analyst and each Narrator draft. Cloud models answer in seconds; a CPU-only local
# model can need minutes, so recording runs raise it with REGISTA_LLM_TIMEOUT_S.
LLM_TIMEOUT_S = 20.0


@dataclass
class TraceStep:
    agent: str  # analyst | narrator | verifier | template | cache
    action: str
    status: str  # ok | rejected | error | fallback
    ms: float
    detail: dict = field(default_factory=dict)


@dataclass
class RenderResult:
    insight: Insight  # as rendered (may carry Analyst-promoted facts)
    rendered: RenderedInsight
    trace: list[TraceStep]
    source: str  # llm | llm_revised | template | template_fallback | cache

    def to_json(self) -> dict:
        return {
            "insight": json.loads(self.insight.model_dump_json()),
            "rendered": json.loads(self.rendered.model_dump_json()),
            "trace": [asdict(s) for s in self.trace],
            "source": self.source,
        }

    @classmethod
    def from_json(cls, d: dict) -> RenderResult:
        return cls(
            Insight.model_validate(d["insight"]),
            RenderedInsight.model_validate(d["rendered"]),
            [TraceStep(**s) for s in d["trace"]],
            d["source"],
        )


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


class WarmPath:
    def __init__(
        self, meta: MatchMeta, client=None, *, analyst=None, narrator=None, cache: dict | None = None, timeout_s: float | None = None
    ):
        self.meta = meta
        self.analyst = analyst or Analyst(client)
        self.narrator = narrator if narrator is not None else (LLMNarrator(client, meta) if client is not None else None)
        self.templates = TemplateNarrator(meta)
        self.verifier = Verifier(meta)
        # read at construction, after any .env has been loaded
        # Languages the LLM Narrator is trusted with (validated by hand); others render from verified templates.
        langs = os.getenv("REGISTA_LLM_LANGUAGES", "")
        self.llm_languages = {x.strip() for x in langs.split(",") if x.strip()} or None
        self.timeout_s = timeout_s if timeout_s is not None else float(os.getenv("REGISTA_LLM_TIMEOUT_S", LLM_TIMEOUT_S))
        self.cache: dict[tuple[str, str], RenderResult] = cache if cache is not None else {}
        self._briefs: dict[str, asyncio.Future] = {}
        self._inflight: dict[tuple[str, str], asyncio.Future] = {}
        self._brief_steps: dict[str, list[TraceStep]] = {}

    # ------------------------------------------------------------------ #
    async def brief(self, ctx: InsightContext) -> tuple[Brief, list[TraceStep]]:
        iid = ctx.insight.insight_id
        fut = self._briefs.get(iid)
        if fut is None:
            fut = self._briefs[iid] = asyncio.ensure_future(self._analyze(ctx))
        brief = await fut
        return brief, self._brief_steps[iid]

    async def _analyze(self, ctx: InsightContext) -> Brief:
        t0 = time.perf_counter()
        try:
            brief = await asyncio.wait_for(self.analyst.brief(ctx), self.timeout_s)
            steps = [
                TraceStep(
                    "analyst",
                    "brief",
                    "ok",
                    _ms(t0),
                    {"source": brief.source, "fact_ids": brief.fact_ids, "angle": brief.angle, "tool_calls": brief.tool_calls},
                )
            ]
        except Exception as exc:  # model error, timeout, bad JSON: fall back to the rule-based Analyst
            brief = rule_brief(ctx)
            steps = [
                TraceStep(
                    "analyst", "brief", "fallback", _ms(t0), {"error": f"{type(exc).__name__}: {exc}"[:300], "fact_ids": brief.fact_ids}
                )
            ]
        self._brief_steps[ctx.insight.insight_id] = steps
        return brief

    async def render(self, ctx: InsightContext, profile: FanProfile) -> RenderResult:
        key = (ctx.insight.insight_id, profile.profile_id)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        fut = self._inflight.get(key)
        if fut is None:  # single-flight: viewers sharing a profile share one render
            fut = self._inflight[key] = asyncio.ensure_future(self._render(ctx, profile))
        try:
            result = await fut
        finally:
            self._inflight.pop(key, None)
        self.cache[key] = result
        return result

    def _verify(self, r: RenderedInsight, insight: Insight, trace: list[TraceStep], attempt: int):
        t0 = time.perf_counter()
        report = self.verifier.verify(r, insight)
        status = "ok" if report.ok else "rejected"
        trace.append(
            TraceStep(
                "verifier",
                f"check draft {attempt}",
                status,
                _ms(t0),
                {"notes": report.verification.notes, "claims": report.verification.checked_claims},
            )
        )
        return report

    async def _render(self, ctx: InsightContext, profile: FanProfile) -> RenderResult:
        brief, brief_steps = await self.brief(ctx)
        trace = list(brief_steps)
        insight = brief.insight
        use_llm = self.narrator is not None and (self.llm_languages is None or profile.language in self.llm_languages)
        if use_llm:
            feedback = None
            for attempt in (1, 2):
                t0 = time.perf_counter()
                try:
                    draft = await asyncio.wait_for(self.narrator.render(brief, profile, feedback), self.timeout_s)
                except DraftShapeError as exc:  # too long to display: a rejection with feedback, not an error
                    trace.append(TraceStep("narrator", f"draft {attempt}", "ok", _ms(t0), {}))
                    trace.append(TraceStep("verifier", f"check draft {attempt}", "rejected", 0.0, {"notes": [str(exc)], "claims": 0}))
                    feedback = str(exc)
                    continue
                except Exception as exc:
                    trace.append(
                        TraceStep("narrator", f"draft {attempt}", "error", _ms(t0), {"error": f"{type(exc).__name__}: {exc}"[:300]})
                    )
                    break
                trace.append(
                    TraceStep(
                        "narrator",
                        f"draft {attempt}",
                        "ok",
                        _ms(t0),
                        {"headline": draft.headline, "claims": [c.model_dump() for c in draft.claims]},
                    )
                )
                report = self._verify(draft, insight, trace, attempt)
                if report.ok:
                    status = "verified" if attempt == 1 else "revised"
                    v = Verification(
                        status=status,
                        checked_claims=report.verification.checked_claims,
                        rejected_claims=0,
                        notes=[] if attempt == 1 else ["revised after Verifier feedback"],
                    )
                    return RenderResult(
                        insight, draft.model_copy(update={"verification": v}), trace, "llm" if attempt == 1 else "llm_revised"
                    )
                feedback = report.feedback()
        # Template narration over the detector's facts only (it never cites Analyst-promoted facts).
        t0 = time.perf_counter()
        r = self.templates.render(ctx.insight, profile)
        detail = {"headline": r.headline}
        if self.narrator is not None and not use_llm:
            detail["reason"] = f"LLM narration not enabled for '{profile.language}' (REGISTA_LLM_LANGUAGES)"
        trace.append(TraceStep("template", "render", "fallback" if use_llm else "ok", _ms(t0), detail))
        report = self._verify(r, ctx.insight, trace, 0)
        notes = ["template fallback after LLM drafts failed verification or errored"] if use_llm else []
        v = Verification(
            status="verified" if report.ok else "rejected",
            checked_claims=report.verification.checked_claims,
            rejected_claims=report.verification.rejected_claims,
            notes=notes + report.verification.notes,
        )
        return RenderResult(ctx.insight, r.model_copy(update={"verification": v}), trace, "template_fallback" if use_llm else "template")

    # ------------------------------------------------------------------ #
    def save_cache(self, path: Path) -> None:
        rows = [{"insight_id": k[0], "profile_id": k[1], **v.to_json()} for k, v in sorted(self.cache.items())]
        path.write_text(json.dumps({"match_id": self.meta.match_id, "renders": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def load_cache(path: Path) -> dict[tuple[str, str], RenderResult]:
        data = json.loads(path.read_text(encoding="utf-8"))
        out = {}
        for row in data["renders"]:
            r = RenderResult.from_json(row)
            r.trace = [TraceStep("cache", "recorded run", "ok", 0.0, {"source": r.source}), *r.trace]
            out[(row["insight_id"], row["profile_id"])] = r
        return out
