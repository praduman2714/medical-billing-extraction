from __future__ import annotations

import time

from pydantic import BaseModel, Field

from app.ai.agents.extractor.executor import ExtractorAgentExecutor
from app.ai.context import RunContext
from app.ai.types import RunMetrics


class OrchestratorResult(BaseModel):
    """Combined outputs and metrics for one document run."""

    echo_result: str | None = None
    billing_records: list[dict] = Field(default_factory=list)
    flagged_records: list[dict] = Field(default_factory=list)
    run_metrics: dict[str, RunMetrics] = Field(default_factory=dict)
    wall_clock_seconds: float = 0.0


class ExtractionOrchestrator:
    """Runs the extraction pipeline for one document.

    Wire additional executors here as you extend the pipeline; attach outputs on
    `RunContext` when later stages need them, and aggregate metrics as you go.
    """

    async def run(self, ctx: RunContext) -> OrchestratorResult:
        """Run pipeline stages and return combined result."""
        t_start = time.perf_counter()
        metrics: dict[str, RunMetrics] = {}

        # Run extractor agent
        extractor_output, extractor_usage = await ExtractorAgentExecutor().run(ctx)

        # Bridge raw Usage object to RunMetrics model
        # Calculate cost for gpt-4o-mini:
        # Input: $0.150 per 1M tokens ($0.15 / 1_000_000)
        # Output: $0.600 per 1M tokens ($0.60 / 1_000_000)
        # Cached input: $0.075 per 1M tokens ($0.075 / 1_000_000)
        input_tokens = extractor_usage.input_tokens
        output_tokens = extractor_usage.output_tokens
        
        cached_input_tokens = getattr(getattr(extractor_usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        reasoning_tokens = getattr(getattr(extractor_usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0

        # Calculate cost:
        # non-cached input: (input_tokens - cached_input_tokens) * 0.15 / 1_000_000
        # cached input: cached_input_tokens * 0.075 / 1_000_000
        # output: output_tokens * 0.60 / 1_000_000
        cost_usd = (
            ((input_tokens - cached_input_tokens) * 0.15 / 1_000_000) +
            (cached_input_tokens * 0.075 / 1_000_000) +
            (output_tokens * 0.60 / 1_000_000)
        )

        metrics["extractor"] = RunMetrics(
            cost_usd=cost_usd,
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            total_reasoning_tokens=reasoning_tokens,
            total_cached_input_tokens=cached_input_tokens,
            total_num_calls=extractor_usage.requests,
            usage_records={"extractor": [extractor_usage]}
        )

        # Serialize billing and flagged records from the run context
        billing_records_dict = [rec.model_dump(by_alias=True) for rec in ctx.billing_records]
        flagged_records_dict = [rec.model_dump(by_alias=True) for rec in ctx.flagged_records]

        return OrchestratorResult(
            echo_result=extractor_output,
            billing_records=billing_records_dict,
            flagged_records=flagged_records_dict,
            run_metrics=metrics,
            wall_clock_seconds=time.perf_counter() - t_start,
        )
