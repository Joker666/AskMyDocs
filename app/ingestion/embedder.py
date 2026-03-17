from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

from app.config import Settings
from app.observability import start_observation
from app.runtime import safe_error_detail

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32
EMBED_TIMEOUT_SECONDS = 30.0
NATIVE_HEALTH_TIMEOUT_SECONDS = 5.0


class OllamaNativeError(Exception):
    """Raised when Ollama native operations fail."""


def _matching_model_name(configured_model: str, available_name: str) -> bool:
    configured = configured_model.strip()
    available = available_name.strip()
    return available == configured or (
        ":" not in configured and available == f"{configured}:latest"
    )


def _missing_model_message(model_name: str) -> str:
    return f"Ollama embedding model '{model_name}' is not available."


def _extract_error_message(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return safe_error_detail(error, fallback="Ollama native request failed.")
    return None


def _raise_for_error_response(response: httpx.Response, *, model_name: str) -> None:
    if response.status_code < 400:
        return

    error_message = _extract_error_message(response)
    if response.status_code in {400, 404} and error_message is not None:
        normalized = error_message.lower()
        if "model" in normalized and ("not found" in normalized or "pull" in normalized):
            raise OllamaNativeError(_missing_model_message(model_name))

    if response.status_code == 404:
        raise OllamaNativeError(_missing_model_message(model_name))

    if error_message is not None:
        raise OllamaNativeError(error_message)

    raise OllamaNativeError(f"Ollama native request failed with status {response.status_code}.")


def _request_json(
    *,
    settings: Settings,
    method: str,
    path: str,
    timeout: float,
    payload: dict[str, object] | None = None,
    model_name: str | None = None,
) -> dict[str, object]:
    try:
        with httpx.Client(base_url=settings.ollama_base_url, timeout=timeout) as client:
            response = client.request(method, path, json=payload)
    except httpx.HTTPError as exc:
        raise OllamaNativeError(
            safe_error_detail(exc, fallback="Ollama native request failed.")
        ) from exc

    _raise_for_error_response(response, model_name=model_name or settings.ollama_embed_model)

    try:
        body = response.json()
    except ValueError as exc:
        raise OllamaNativeError("Ollama native response was not valid JSON.") from exc

    if not isinstance(body, dict):
        raise OllamaNativeError("Ollama native response had an unexpected shape.")
    return body


def embed_texts(texts: Sequence[str], settings: Settings) -> list[list[float]]:
    if not texts:
        return []

    with start_observation(
        settings,
        name="ollama.embed",
        as_type="embedding",
        input={
            "text_count": len(texts),
            "batch_size": EMBED_BATCH_SIZE,
        },
        metadata={"model_name": settings.ollama_embed_model},
    ) as span:
        embeddings: list[list[float]] = []
        total_batches = (len(texts) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE

        for batch_index, start in enumerate(range(0, len(texts), EMBED_BATCH_SIZE), start=1):
            batch = list(texts[start : start + EMBED_BATCH_SIZE])
            body = _request_json(
                settings=settings,
                method="POST",
                path="/api/embed",
                timeout=EMBED_TIMEOUT_SECONDS,
                payload={
                    "model": settings.ollama_embed_model,
                    "input": batch,
                },
                model_name=settings.ollama_embed_model,
            )
            batch_embeddings = body.get("embeddings")
            if not isinstance(batch_embeddings, list):
                raise OllamaNativeError("Ollama embed response is missing embeddings.")
            if len(batch_embeddings) != len(batch):
                raise OllamaNativeError("Ollama embed response count did not match the request.")

            validated_batch: list[list[float]] = []
            for embedding in batch_embeddings:
                if not isinstance(embedding, list) or not all(
                    isinstance(value, int | float) for value in embedding
                ):
                    raise OllamaNativeError("Ollama embed response contained an invalid embedding.")
                vector = [float(value) for value in embedding]
                if len(vector) != settings.embedding_dimension:
                    raise OllamaNativeError(
                        "Ollama embedding dimension "
                        f"{len(vector)} did not match configured dimension "
                        f"{settings.embedding_dimension}."
                    )
                validated_batch.append(vector)

            embeddings.extend(validated_batch)
            logger.info(
                "embedding_batch_completed",
                extra={
                    "model_name": settings.ollama_embed_model,
                    "batch_index": batch_index,
                    "total_batches": total_batches,
                    "batch_size": len(batch),
                },
            )

        if span is not None:
            span.update(
                output={
                    "embedding_count": len(embeddings),
                    "batch_count": total_batches,
                    "embedding_dimension": settings.embedding_dimension,
                }
            )
        return embeddings


def check_ollama_native(settings: Settings) -> None:
    body = _request_json(
        settings=settings,
        method="GET",
        path="/api/tags",
        timeout=NATIVE_HEALTH_TIMEOUT_SECONDS,
        model_name=settings.ollama_embed_model,
    )
    models = body.get("models")
    if not isinstance(models, list):
        raise OllamaNativeError("Ollama native model listing had an unexpected shape.")

    available_names: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        for key in ("name", "model"):
            value = model.get(key)
            if isinstance(value, str):
                available_names.append(value)

    if not any(_matching_model_name(settings.ollama_embed_model, name) for name in available_names):
        raise OllamaNativeError(_missing_model_message(settings.ollama_embed_model))
