"""Claude wrapper. Every bot that uses Claude also has a simple rule-based fallback,
so a missing key or an API hiccup never crashes a run - it just trades on the rules."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

# Models that accept server-side refusal fallbacks ("default" routing).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class AI:
    def __init__(self, model: str, effort: str = "low", api_key: str | None = None):
        self.model = model
        self.effort = effort
        self.client = None
        self.calls = 0
        key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        if key:
            import anthropic
            self.client = anthropic.Anthropic(api_key=key, max_retries=3)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def ask(self, system: str, prompt: str, schema: dict) -> dict | None:
        """Ask Claude for JSON matching `schema`. Returns None if Claude is unavailable or declines."""
        if not self.client:
            return None
        import anthropic

        kwargs = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            self.calls += 1
            if self.model in FALLBACK_MODELS:
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            log.warning("Claude API error %s: %s", e.status_code, e.message)
            return None
        except anthropic.APIConnectionError:
            log.warning("Could not reach Claude")
            return None
        if resp.stop_reason == "refusal":
            log.warning("Claude declined this request; using rules instead")
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Claude returned unreadable JSON")
            return None
