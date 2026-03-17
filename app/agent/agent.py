from __future__ import annotations

import logging
from difflib import SequenceMatcher

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
MIN_QUOTE_SIMILARITY_RATIO = 0.7


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
    if not data.citations and data.confidence > 0.0:
        raise ModelRetry(
            "Non-zero confidence requires at least one citation. "
            "Set confidence to 0.0 if no relevant information was found."
        )

    if not data.citations:
        return data

    fetched_chunks = deps.fetched_chunks_by_id
    if not fetched_chunks:
        raise ModelRetry("Fetch chunk context before returning the final answer.")

    for citation in data.citations:
        _backfill_citation_metadata(fetched_chunks, citation)
        _validate_citation(fetched_chunks, citation)

    return data


def _backfill_citation_metadata(
    fetched_chunks: dict[int, ChunkContextResult],
    citation: Citation,
) -> None:
    """Overwrite citation metadata fields from the fetched chunk record.

    This removes the burden from the LLM to echo metadata exactly and
    eliminates document_id / filename / page_number / section_title
    mismatches as a source of validation failures.
    """
    chunk = fetched_chunks.get(citation.chunk_id)
    if chunk is None:
        return
    citation.document_id = chunk.document_id
    citation.filename = chunk.filename
    citation.page_number = chunk.page_number
    citation.section_title = chunk.section_title


def _validate_citation(
    fetched_chunks: dict[int, ChunkContextResult],
    citation: Citation,
) -> None:
    record = fetched_chunks.get(citation.chunk_id)
    if record is None:
        raise ModelRetry(f"Citation chunk {citation.chunk_id} was not fetched.")

    quote = citation.quote.strip()
    if not quote:
        raise ModelRetry(f"Citation quote is empty for chunk {citation.chunk_id}.")
    if len(quote) > MAX_CITATION_QUOTE_LENGTH:
        raise ModelRetry(f"Citation quote is too long for chunk {citation.chunk_id}.")

    normalized_quote = _normalize_whitespace(quote).lower()
    normalized_text = _normalize_whitespace(record.text).lower()
    if normalized_quote in normalized_text:
        return

    ratio = SequenceMatcher(None, normalized_quote, normalized_text).ratio()
    if ratio < MIN_QUOTE_SIMILARITY_RATIO:
        raise ModelRetry(
            f"Citation quote for chunk {citation.chunk_id} does not closely match "
            f"the chunk text (similarity {ratio:.0%}, need {MIN_QUOTE_SIMILARITY_RATIO:.0%}). "
            f"Copy the quote verbatim from the chunk text."
        )


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
