from __future__ import annotations

from agents import Agent, Runner, Usage

from app.ai.agents.factory import AgentFactory
from app.ai.config import EXTRACTOR_AGENT_CONFIG
from app.ai.context import RunContext
from app.core.common.logger import get_logger


class ExtractorAgentExecutor:
    """Runs the extractor agent over a document to extract billing records.

    Supplies all pages text in the rendered user prompt and triggers save_extracted_records tool.
    """

    def __init__(
        self,
        *,
        agent: Agent[RunContext] | None = None,
        max_turns: int = 10,
    ) -> None:
        """Initialise the executor.

        Args:
            agent: Optional pre-built agent. Uses AgentFactory if not provided.
            max_turns: Maximum agent turns before forced stop.
        """
        self.agent = agent if agent is not None else AgentFactory.build_extractor_agent()
        self.max_turns = max(1, max_turns)
        self.logger = get_logger(__name__)

    async def _render_user(self, ctx: RunContext, chunk_pages: list) -> str:
        """Render the user prompt template for this document chunk."""
        return await ctx.prompt_loader.render(
            EXTRACTOR_AGENT_CONFIG.input_key,
            {
                "doc_id": ctx.document.doc_id,
                "total_pages": ctx.document.num_pages,
                "pages": chunk_pages,
            },
        )

    async def run(self, ctx: RunContext) -> tuple[str, Usage]:
        """Run the extractor agent over chunks of pages and return (output_text, usage)."""
        self.logger.info("extractor_agent_started", doc_id=ctx.document.doc_id)

        pages = ctx.document.pages
        # Use chunk size of 10 pages. You can adjust this based on context length limits.
        chunk_size = 10
        chunks = [pages[i:i + chunk_size] for i in range(0, len(pages), chunk_size)]
        if not chunks:
            chunks = [[]] # Handle empty document

        total_usage = Usage()
        all_outputs = []

        for chunk in chunks:
            user_text = await self._render_user(ctx, chunk)

            result = await Runner.run(
                self.agent,
                user_text,
                context=ctx,
                max_turns=self.max_turns,
            )

            output = (
                result.final_output
                if isinstance(result.final_output, str)
                else str(result.final_output)
            )
            all_outputs.append(output)

            # Accumulate usage
            chunk_usage = result.context_wrapper.usage
            total_usage.input_tokens += chunk_usage.input_tokens
            total_usage.output_tokens += chunk_usage.output_tokens
            total_usage.requests += chunk_usage.requests

        final_output = "\n".join(all_outputs)

        self.logger.info(
            "extractor_agent_completed",
            doc_id=ctx.document.doc_id,
            chars=len(final_output),
        )

        return final_output, total_usage
