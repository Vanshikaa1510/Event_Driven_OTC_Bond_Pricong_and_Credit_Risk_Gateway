from __future__ import annotations

import json
from typing import Any

from huggingface_hub import InferenceClient


_PROVIDERS = frozenset(
    {
        "baseten",
        "cerebras",
        "cohere",
        "deepinfra",
        "fal-ai",
        "featherless-ai",
        "fireworks-ai",
        "groq",
        "hf-inference",
        "novita",
        "nscale",
        "openai",
        "ovhcloud",
        "publicai",
        "replicate",
        "scaleway",
        "together",
        "wavespeed",
        "zai-org",
    }
)


def chat_completion_json(
    *,
    hf_token: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> Any:
    model_id, separator, provider_suffix = model.rpartition(":")
    provider = provider_suffix if separator and provider_suffix in _PROVIDERS else "auto"
    if provider != "auto":
        model = model_id

    client = InferenceClient(model=model, provider=provider, token=hf_token, timeout=20)
    response = client.chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise ValueError("Hugging Face returned an empty JSON response.")
    return json.loads(content)
