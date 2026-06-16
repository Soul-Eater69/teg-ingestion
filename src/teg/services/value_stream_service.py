"""Value Stream prediction service facade (Contract B).

The backend calls :meth:`ValueStreamService.predict`. Wires the pipeline:
retrieve (two lanes) -> build candidates + merge -> review-pool LLM selection.
Clients are injected so it can be unit-tested with fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from teg.contracts.value_stream_io import ValueStreamRequest, ValueStreamResponse
from teg.domain.value_stream import HistoricalTicket
from teg.integrations.llm import LLMClient
from teg.integrations.search import HistoricalHit, SearchClient
from teg.value_stream.candidate_merger import build_candidates, derive_runtime, select_review_pool
from teg.value_stream.config import ValueStreamConfig
from teg.value_stream.custom_instruction import parse_requested_count
from teg.value_stream.retrieval import retrieve
from teg.value_stream.selection import score_and_select, select_value_streams


# Each candidate-structure gets its own selection prompt (merge = lane-aware/historical-in-blocks;
# plain = pure VS list; evidence = pure VS list + a similar-past-tickets evidence block).
_PROMPT_BY_MODE = {
    "merge": "value_stream/selection",
    "historic_only": "value_stream/selection_historic",  # precedent-derived pool
    "all50": "value_stream/selection_plain",
    "topk": "value_stream/selection_plain",
    # evidence is the production default - the Recall prompt is the tuning winner
    # (recall 0.726 -> 0.776, hard-ticket recall +0.05; see docs/vs_selection_tuning.md).
    "evidence": "value_stream/selection_evidence_recall",
}


@dataclass(frozen=True)
class PredictionTrace:
    """What survived each stage, for eval miss-bucketing (not part of the API contract)."""

    retrieved_ids: list[str] = field(default_factory=list)  # all merged candidate ids
    review_pool: list = field(default_factory=list)  # ValueStreamCandidate objects the LLM saw
    vs_lane_ranked: list[str] = field(default_factory=list)  # VS ids in semantic-rank order (VS lane)
    historic_lane_ids: list[str] = field(default_factory=list)  # VS surfaced by the historic lane
    retrieval_seconds: float = 0.0  # candidate extraction (embed query + search)
    selection_seconds: float = 0.0  # the VS-selection LLM call
    llm_pick_count: int = 0  # how many the LLM picked itself (before count enforcement/padding)
    requested_count: int = 0  # the count asked of the LLM

    @property
    def review_pool_ids(self) -> list[str]:
        return [c.value_stream_id for c in self.review_pool]


class ValueStreamService:
    def __init__(
        self,
        search_client: SearchClient,
        llm_client: LLMClient,
        *,
        model_name: str = "",
        config: ValueStreamConfig = ValueStreamConfig(),
        base_rates: dict[str, float] | None = None,
        vs_details: dict[str, dict] | None = None,
        historic_content: dict[str, dict] | None = None,
        vs_candidates: list | None = None,
    ) -> None:
        self._search = search_client
        self._llm = llm_client
        self._model_name = model_name
        self._config = config
        # Corpus tag-frequency prior per VS (broad-stream penalty). Global default; the eval
        # passes a per-ticket leave-one-out override via predict_traced.
        self._base_rates = base_rates or {}
        # Per-VS selection context from the governed catalogue (the lean index carries only
        # id+name); used to enrich candidate blocks: {vs_id: {description, category, trigger,
        # valueProposition}}.
        self._vs_details = vs_details or {}
        # Richer per-historic-ticket content for the evidence block (experiment): {ticket_id:
        # {raw, description, summary}}. Production fills it from Cosmos point-reads; the eval from a
        # local lookup. Empty -> the evidence block falls back to the search snippet.
        self._historic_content = historic_content or {}
        # The 50 governed VS as candidates (from the catalogue, not the index). When set, the VS lane
        # is sourced from here and the index holds only historic docs. None -> legacy index search.
        self._vs_candidates = vs_candidates

    async def predict(self, request: ValueStreamRequest) -> ValueStreamResponse:
        response, _ = await self._predict(request)
        return response

    async def predict_traced(
        self, request: ValueStreamRequest, *, base_rates: dict[str, float] | None = None
    ) -> tuple[ValueStreamResponse, PredictionTrace]:
        """Same as :meth:`predict` but returns what reached the LLM (eval diagnostics).

        ``base_rates`` overrides the global prior for this call (the eval uses it to pass a
        leave-one-out frequency that excludes the ticket under test).
        """
        return await self._predict(request, base_rates=base_rates)

    async def _predict(
        self, request: ValueStreamRequest, *, base_rates: dict[str, float] | None = None
    ) -> tuple[ValueStreamResponse, PredictionTrace]:
        # The custom instruction may only set the count: parse it deterministically (the raw
        # text never reaches a prompt); a parsed count overrides requested_count.
        requested_count = parse_requested_count(request.custom_instruction) or request.requested_count

        # Fetch sizes + merge policy adapt to the requested count and the tuning config.
        vs_top_k, historical_top_k, policy = derive_runtime(requested_count, config=self._config)
        # Over-fetch by the exclude count so dropping self/excluded tickets still leaves a
        # full analog set.
        t_retrieve = perf_counter()
        result = await retrieve(
            request.summary_fields,
            self._search,
            vs_top_k=vs_top_k,
            historical_top_k=historical_top_k + len(request.exclude_ticket_ids),
            include_historical=self._config.use_historic_lane,
            vs_candidates=self._vs_candidates,  # None -> index search; set -> from the catalogue
        )
        retrieval_seconds = perf_counter() - t_retrieve
        # The index is retrieval-only - enrich each hit's VS labels from the historic lookup (keyed by
        # ticket id; Cosmos point-read in prod, local in the eval). Empty lookup -> hits keep [] VS.
        for hit in result.historical_hits:
            vs = (self._historic_content.get(hit.ticket_id) or {}).get("vs")
            if vs:
                hit.value_streams = vs
        historical_hits = _excluding(result.historical_hits, request.exclude_ticket_ids)[:historical_top_k]
        # SME-selected analogs become the evidence used for ranking (all retrieved if
        # none selected); the full retrieved set is still returned for the HITL step.
        evidence = _selected(historical_hits, request.selected_historical_ticket_ids)
        mode = self._config.selection_mode
        # In all50/topk/evidence the historic lane is NOT merged into candidates (VS-only pool);
        # in merge it is; in historic_only the pool is built from the historic VS only.
        hist_for_pool = [] if mode in ("all50", "topk", "evidence") else evidence
        candidates = build_candidates(
            [] if mode == "historic_only" else result.value_stream_hits,
            evidence if mode == "historic_only" else hist_for_pool,
            max_supporting_tickets=policy.max_supporting_tickets,
            base_rates=base_rates if base_rates is not None else self._base_rates,
            vs_details=self._vs_details,
        )
        review_pool = select_review_pool(candidates, policy=policy)
        # evidence mode: historic tickets shown as a context block, not merged.
        historic_evidence = _render_evidence(
            historical_hits, repr=self._config.historic_repr, budget=self._config.historic_budget,
            content=self._historic_content) if mode == "evidence" else ""
        t_select = perf_counter()
        select_trace: dict = {}
        query = request.prompt_text or request.summary_fields.generated_summary
        if self._config.score_select and mode == "evidence":
            # Two-stage: score every candidate independently, then take the top-N by score.
            recommendations = await score_and_select(
                query=query, candidates=review_pool, requested_count=requested_count,
                llm_client=self._llm, historic_evidence=historic_evidence,
                show_scores=self._config.show_candidate_scores, trace=select_trace,
            )
        else:
            recommendations = await select_value_streams(
                # Prompt reads raw text when provided (decoupled from retrieval, which uses summary).
                query=query,
                candidates=review_pool,
                requested_count=requested_count,
                llm_client=self._llm,
                min_confidence=self._config.min_confidence,
                historic_evidence=historic_evidence,
                prompt_name=self._config.selection_prompt_override
                or _PROMPT_BY_MODE.get(mode, "value_stream/selection"),
                show_scores=self._config.show_candidate_scores,
                trace=select_trace,
            )
        selection_seconds = perf_counter() - t_select
        response = ValueStreamResponse(
            ticket_id=request.ticket_id,
            recommendations=recommendations,
            historical_tickets=[_to_ticket(hit) for hit in historical_hits],
            model=self._model_name,
        )
        # Per-lane retrieval, for retrieval-recall metrics (separate from selection).
        vs_lane_ranked = [h.value_stream_id for h in result.value_stream_hits if h.value_stream_id]
        historic_lane_ids = _unique([
            v.value_stream_id for h in historical_hits for v in h.value_streams if v.value_stream_id
        ])
        trace = PredictionTrace(
            retrieved_ids=[c.value_stream_id for c in candidates],
            review_pool=review_pool,
            vs_lane_ranked=vs_lane_ranked,
            historic_lane_ids=historic_lane_ids,
            retrieval_seconds=retrieval_seconds,
            selection_seconds=selection_seconds,
            llm_pick_count=select_trace.get("llm_pick_count", 0),
            requested_count=select_trace.get("requested_count", requested_count),
        )
        return response, trace

    async def aclose(self) -> None:
        """Close the search + LLM clients' sessions (call when done; e.g. scripts)."""
        for client, name in ((self._search, "close"), (self._llm, "aclose")):
            fn = getattr(client, name, None)
            if fn is not None:
                await fn()


def _excluding(hits: list[HistoricalHit], exclude_ids: list[str]) -> list[HistoricalHit]:
    if not exclude_ids:
        return hits
    drop = set(exclude_ids)
    return [hit for hit in hits if hit.ticket_id not in drop]


def _selected(hits: list[HistoricalHit], selected_ids: list[str]) -> list[HistoricalHit]:
    if not selected_ids:
        return hits
    keep = set(selected_ids)
    return [hit for hit in hits if hit.ticket_id in keep]


def _to_ticket(hit: HistoricalHit) -> HistoricalTicket:
    return HistoricalTicket(
        ticket_id=hit.ticket_id, title=hit.title, score=hit.score, snippet=hit.snippet
    )


def _unique(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _render_evidence(hits: list[HistoricalHit], *, repr: str = "snippet", budget: int = 0,
                     content: dict[str, dict] | None = None) -> str:
    """Render the similar past tickets as an evidence block (their content + the VS they were tagged
    with) for the 'evidence' selection mode - context the LLM weighs when picking from all VS.

    ``repr`` chooses each ticket's content: snippet (search snippet), summary, description, or raw
    (truncated to ``budget`` tokens). Falls back to the snippet when the content lookup lacks it.
    """
    content = content or {}
    lines: list[str] = []
    for hit in hits:
        vs = ", ".join(f"{v.value_stream_name} ({v.value_stream_id})" for v in hit.value_streams)
        text = _historic_text(hit, repr, budget, content.get(hit.ticket_id, {}))
        lines.append(f"- {hit.ticket_id}: {text}\n  -> tagged value streams: {vs or '(none)'}")
    return "\n".join(lines)


def _historic_text(hit: HistoricalHit, repr: str, budget: int, c: dict) -> str:
    """The historic ticket's content for the chosen representation (~4 chars/token for truncation)."""
    if repr == "summary":
        text = c.get("summary") or hit.snippet
    elif repr == "description":
        text = c.get("description") or hit.snippet
    elif repr == "raw":
        text = c.get("raw") or hit.snippet
        if budget:
            text = (text or "")[:budget * 4]  # ~4 chars per token
    else:  # snippet (default): the existing 200-char search snippet
        text = (hit.snippet or "")[:200]
    return (text or "").strip().replace("\n", " ")
