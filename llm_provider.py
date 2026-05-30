"""LLM provider factory — supports Bedrock, Anthropic, OpenAI, and Ollama."""
from __future__ import annotations

import os


def get_model(model_id: str | None = None, max_tokens: int = 8192):
    """Return a Strands-compatible model based on LLM_PROVIDER env var.

    Supported providers (set LLM_PROVIDER env var):
        bedrock   — AWS Bedrock (default)
        anthropic — Anthropic direct API
        openai    — OpenAI API
        ollama    — Local Ollama instance
    """
    provider = os.environ.get("LLM_PROVIDER", "bedrock").lower()

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel
        return AnthropicModel(
            client_args={"api_key": os.environ["ANTHROPIC_API_KEY"]},
            model_id=model_id or os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6"),
            max_tokens=max_tokens,
        )

    if provider == "openai":
        from strands.models.openai import OpenAIModel
        return OpenAIModel(
            client_args={"api_key": os.environ["OPENAI_API_KEY"]},
            model_id=model_id or os.environ.get("OPENAI_MODEL_ID", "gpt-4o"),
        )

    if provider == "ollama":
        from strands.models.ollama import OllamaModel
        return OllamaModel(
            host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            model_id=model_id or os.environ.get("OLLAMA_MODEL_ID", "llama3"),
        )

    # Default: bedrock
    from strands.models.bedrock import BedrockModel
    return BedrockModel(
        model_id=model_id or os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        max_tokens=max_tokens,
    )
