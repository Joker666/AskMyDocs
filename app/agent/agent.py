from __future__ import annotations

import logging

from anthropic import Anthropic
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.tools import RunContext

from app.agent.models import AnswerResult, Citation
from app.agent.prompts import QUERY_SYSTEM_PROMPT
from app.agent.tools import ChunkContextResult, QueryAgentDeps, register_query_tools
from app.config import Settings
from app.observability import build_pydantic_ai_instrumentation
from app.runtime import safe_error_detail

logger = logging.getLogger(__name__)

ANTHROPIC_COMPAT_TIMEOUT_SECONDS = 5.0
QUERY_AGENT_OUTPUT_RETRIES = 2
MAX_CITATION_QUOTE_LENGTH = 300


class AnthropicCompatError(Exception):
    """Raised when Anthropic-compatible connectivity checks fail."""
def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _build_provider(settings: Settings) -> AnthropicProvider:
    return AnthropicProvider(
        api_key=settings.anthropic_auth_token.get_secret_value(),
        base_url=settings.anthropic_base_url,
    )


def build_query_agent(
    settings: Settings,
    *,
    model: Model | None = None,
) -> Agent[QueryAgentDeps, AnswerResult]:
    agent_model: Model = model or AnthropicModel(
        settings.anthropic_model_name,
        provider=_build_provider(settings),
        settings={"temperature": 0.0, "max_tokens": 1024},
    )
    agent = Agent[QueryAgentDeps, AnswerResult](
        model=agent_model,
        deps_type=QueryAgentDeps,
        output_type=AnswerResult,
        system_prompt=QUERY_SYSTEM_PROMPT,
        output_retries=QUERY_AGENT_OUTPUT_RETRIES,
        instrument=build_pydantic_ai_instrumentation(settings),
    )
    register_query_tools(agent)

    @agent.output_validator
    def validate_output(
        ctx: RunContext[QueryAgentDeps],
        data: AnswerResult,
    ) -> AnswerResult:
        return validate_answer_result(ctx.deps, data)

    return agent


def validate_answer_result(deps: QueryAgentDeps, data: AnswerResult) -> AnswerResult:
    if not data.citations:
        raise ModelRetry("The final answer must include citations from fetched chunk context.")

    fetched_chunks = deps.fetched_chunks_by_id
    if not fetched_chunks:
        raise ModelRetry("Fetch chunk context before returning the final answer.")

    for citation in data.citations:
        _validate_citation(fetched_chunks, citation)

    return data


def _validate_citation(
    fetched_chunks: dict[int, ChunkContextResult],
    citation: Citation,
) -> None:
    record = fetched_chunks.get(citation.chunk_id)
    if record is None:
        raise ModelRetry(f"Citation chunk {citation.chunk_id} was not fetched.")

    chunk = record
    chunk_document_id = chunk.document_id
    if citation.document_id != chunk_document_id:
        raise ModelRetry(f"Citation document mismatch for chunk {citation.chunk_id}.")

    if citation.filename != chunk.filename:
        raise ModelRetry(f"Citation filename mismatch for chunk {citation.chunk_id}.")

    if citation.page_number != chunk.page_number:
        raise ModelRetry(f"Citation page number mismatch for chunk {citation.chunk_id}.")

    if citation.section_title != chunk.section_title:
        raise ModelRetry(f"Citation section title mismatch for chunk {citation.chunk_id}.")

    quote = citation.quote.strip()
    if not quote:
        raise ModelRetry(f"Citation quote is empty for chunk {citation.chunk_id}.")
    if len(quote) > MAX_CITATION_QUOTE_LENGTH:
        raise ModelRetry(f"Citation quote is too long for chunk {citation.chunk_id}.")

    normalized_quote = _normalize_whitespace(quote)
    normalized_text = _normalize_whitespace(chunk.text)
    if normalized_quote not in normalized_text:
        raise ModelRetry(f"Citation quote was not found in chunk {citation.chunk_id}.")


def check_anthropic_compat(settings: Settings) -> None:
    client = Anthropic(
        api_key=settings.anthropic_auth_token.get_secret_value(),
        base_url=settings.anthropic_base_url,
        timeout=ANTHROPIC_COMPAT_TIMEOUT_SECONDS,
        max_retries=0,
    )
    try:
        client.beta.messages.create(
            model=settings.anthropic_model_name,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:
        raise AnthropicCompatError(
            safe_error_detail(exc, fallback="Anthropic-compatible request failed.")
        ) from exc
