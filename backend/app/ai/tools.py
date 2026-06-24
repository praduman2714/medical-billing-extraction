from agents import function_tool
from agents.tool_context import ToolContext

from app.ai.context import RunContext
from app.models.extraction import BillingRecord, FlaggedRecord


@function_tool
async def echo_tool(
    ctx: ToolContext[RunContext],
    message: str,
) -> str:
    """Echo a message back. Used only by the echo agent as a demonstration tool.

    Args:
        message: Any string to echo.

    Returns:
        The input string prefixed with 'Echo: '.
    """
    return f"Echo: {message}"


@function_tool
async def save_extracted_records(
    ctx: ToolContext[RunContext],
    records: list[BillingRecord],
    flagged: list[FlaggedRecord],
) -> str:
    """Save the extracted billing records and flagged records to the run context.

    Call this tool once you have completed the extraction process for the document.

    Args:
        ctx: The runtime context.
        records: A list of extracted billing episodes.
        flagged: A list of flagged records requiring manual review.

    Returns:
        A confirmation message that the records have been saved.
    """
    ctx.context.billing_records = records
    ctx.context.flagged_records = flagged
    return f"Successfully saved {len(records)} billing records and {len(flagged)} flagged records to context."
