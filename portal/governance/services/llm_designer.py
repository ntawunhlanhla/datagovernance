"""Domain-driven dataset designer using Emergent LLM.

Given a domain keyword like "school" or "restaurant", the LLM:
  1. Picks a realistic random instance (e.g. "Greenwood High School").
  2. Designs 3-5 logically related datasets with columns + types.
  3. Returns column-level generator hints (e.g. {"faker": "name"}, {"choices": [...]}).
  4. Returns inter-dataset relationships for lineage.

The output is a strict JSON spec consumed by data_generator.py.
"""
import json
import logging
import asyncio
import re

from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior data architect. Given a business DOMAIN keyword, you:

1. Pick a REALISTIC, randomly-chosen example of that domain (e.g. for "school" -> "Westridge Academy"; for "restaurant" -> "Bella Notte Trattoria"). Use varied creative names.
2. Design 3-5 normalized, logically-related datasets that such an organization would realistically own.
3. For each dataset, list 5-12 columns with realistic names, types, and generator hints.
4. Define 2-4 lineage edges between datasets (e.g. enrollments downstream of students + courses).

Return ONLY valid minified JSON matching this schema (no markdown, no code fences, no commentary):

{
  "domain": "<echo input>",
  "instance_name": "<creative realistic name>",
  "description": "<one-sentence description of the organization>",
  "product_name": "<snake_case data product name>",
  "datasets": [
    {
      "name": "<snake_case_table_name>",
      "description": "<short>",
      "pii_flag": <bool>,
      "columns": [
        {
          "name": "<snake_case>",
          "data_type": "<int|long|float|string|bool|date|datetime>",
          "nullable": <bool>,
          "description": "<short>",
          "pii": <bool>,
          "business_glossary_term": "<optional>",
          "generator": {
            "type": "<faker|choices|int_range|float_range|date_range|sequence|foreign_key|uuid|email>",
            ... // type-specific keys
          }
        }
      ]
    }
  ],
  "lineage": [
    {"upstream": "<dataset>", "downstream": "<dataset>", "transformation": "<short>"}
  ],
  "quality_rules": [
    {"dataset": "<name>", "column": "<name>", "rule_type": "not_null|unique|range|regex", "expression": "<optional>"}
  ]
}

Generator type cheatsheet (use these EXACT type names):
- "faker"        -> {"type":"faker","method":"name|first_name|last_name|email|phone_number|address|city|country|company|job|date_of_birth|date_this_decade|date_this_year|word|sentence|catch_phrase|ssn|credit_card_number|iban"}
- "choices"      -> {"type":"choices","values":["A","B","C"]}
- "int_range"    -> {"type":"int_range","min":0,"max":100}
- "float_range"  -> {"type":"float_range","min":0.0,"max":1000.0,"decimals":2}
- "date_range"   -> {"type":"date_range","start":"2020-01-01","end":"2024-12-31"}
- "sequence"     -> {"type":"sequence","start":1} (use this for primary keys)
- "foreign_key"  -> {"type":"foreign_key","references":"<other_dataset>.<column>"}
- "uuid"         -> {"type":"uuid"}
- "email"        -> {"type":"email"}

Rules:
- The FIRST column of every dataset MUST be the primary key, named "<dataset_singular>_id", type "long", generator "sequence".
- Use "foreign_key" generator to link related datasets.
- Mark columns with personal data (names, emails, SSN, addresses, DOB, phone) as pii=true.
- Keep dataset names plural snake_case. Column names snake_case.
- 3 to 5 datasets total. 5 to 12 columns each. Do NOT exceed.
"""


def _extract_json(text: str) -> dict:
    """Robustly extract JSON object from LLM response."""
    text = text.strip()
    # Strip code fences if present
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # Fallback: take from first { to last }
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
    return json.loads(text)


def design_data_product(domain: str) -> dict:
    """Synchronous wrapper. Calls Emergent LLM and returns the parsed spec dict."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    api_key = settings.EMERGENT_LLM_KEY
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY not set")

    provider = settings.LLM_PROVIDER
    model = settings.LLM_MODEL

    chat = LlmChat(
        api_key=api_key,
        session_id=f"design-{domain}",
        system_message=SYSTEM_PROMPT,
    ).with_model(provider, model)

    user_msg = UserMessage(text=f"DOMAIN: {domain}\n\nReturn ONLY the JSON spec, no other text.")

    async def _run():
        result_text = ""
        from emergentintegrations.llm.chat import TextDelta, StreamDone
        async for ev in chat.stream_message(user_msg):
            if isinstance(ev, TextDelta):
                result_text += ev.content
            elif isinstance(ev, StreamDone):
                break
        return result_text

    loop = asyncio.new_event_loop()
    try:
        text = loop.run_until_complete(_run())
    finally:
        loop.close()

    spec = _extract_json(text)
    # Validation
    if "datasets" not in spec or not spec["datasets"]:
        raise ValueError(f"LLM returned invalid spec: {spec}")
    logger.info("LLM designed product '%s' with %d datasets for domain '%s'",
                spec.get("instance_name"), len(spec["datasets"]), domain)
    return spec
