"""
ServiceNow CMDB lookup agent: read JSON in cmdb_input_schema shape, normalize
internally (optional LLM), and emit cmdb_output_schema enrichment only on stdout.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import jsonschema
import requests

_DIR = Path(__file__).resolve().parent
INPUT_SCHEMA_PATH = _DIR / "cmdb_input_schema.json"
OUTPUT_SCHEMA_PATH = _DIR / "cmdb_output_schema.json"

LOOKUP_TYPES = frozenset({"hostname", "ip", "ci_name", "application"})
ENV_HINTS = frozenset({"prod", "staging", "dev"})
ADDITIONAL_CONTEXT_KEYS = frozenset({"ip_address", "fqdn", "application", "region"})

# OpenAI-compatible endpoint (same family as callmodel.py); credentials from env only.
API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
MODEL_ENDPOINT = os.environ.get("LITELLM_BASE_URL", "https://litellm-prod.apps.maas.redhatworkshops.io/v1").rstrip("/")
MODEL_NAME = os.environ.get("CMDB_AGENT_MODEL", "granite-3-2-8b-instruct")

_SYSTEM_PROMPT = """You normalize CMDB lookup requests for ServiceNow.
You receive JSON that may be partial or messy. You output ONE JSON object that strictly matches the user's schema.
Rules:
- Preserve lookup_key meaning; trim whitespace on strings.
- If lookup_type is missing or invalid, infer: ip (valid IP), else hostname if it looks like a DNS host/FQDN, else prefer ci_name unless the key is clearly an application/service name.
- If environment_hint is missing, infer prod/staging/dev only from explicit tokens in the input; if unclear, omit environment_hint.
- additional_context may include only: ip_address, fqdn, application, region (strings). Omit keys you cannot justify from input.
- Do not add keys outside the schema. Do not wrap in markdown. Return ONLY raw JSON."""


def _load_input_schema() -> dict[str, Any]:
    return json.loads(INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_output_schema() -> dict[str, Any]:
    return json.loads(OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8"))


def _parse_model_json(text: str) -> dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return json.loads(t)


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s.strip())
        return True
    except ValueError:
        return False


_HOSTLIKE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$")


def _infer_lookup_type(lookup_key: str, additional_context: dict[str, Any] | None) -> str | None:
    key = lookup_key.strip()
    if _is_ip(key):
        return "ip"
    if _HOSTLIKE.match(key):
        return "hostname"
    ctx = additional_context or {}
    if ctx.get("fqdn") and not _is_ip(key):
        return "hostname"
    return None


def _infer_environment_hint(*texts: str) -> str | None:
    blob = " ".join(t.lower() for t in texts if t)
    if re.search(r"\bprod(uction)?\b", blob):
        return "prod"
    if re.search(r"\bstaging\b|\bstg\b", blob):
        return "staging"
    if re.search(r"\bdev(elopment)?\b", blob):
        return "dev"
    return None


def _trim_additional_context(raw: Any) -> dict[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for k in ADDITIONAL_CONTEXT_KEYS:
        v = raw.get(k)
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out or None


def normalize_cmdb_input(
    data: dict[str, Any],
    *,
    default_lookup_type: str = "ci_name",
) -> dict[str, Any]:
    """Heuristic normalization to cmdb_input_schema shape (no LLM)."""
    if not isinstance(data, dict):
        raise TypeError("input must be a JSON object")

    lookup_key = data.get("lookup_key")
    if not isinstance(lookup_key, str) or not lookup_key.strip():
        raise ValueError("lookup_key is required and must be a non-empty string")

    additional = _trim_additional_context(data.get("additional_context"))

    lt = data.get("lookup_type")
    if lt not in LOOKUP_TYPES:
        lt = _infer_lookup_type(lookup_key, additional) or default_lookup_type

    eh = data.get("environment_hint")
    if eh not in ENV_HINTS:
        eh = _infer_environment_hint(
            lookup_key,
            *(str(v) for v in (additional or {}).values()),
        )

    out: dict[str, Any] = {"lookup_key": lookup_key.strip(), "lookup_type": lt}
    if eh is not None:
        out["environment_hint"] = eh
    if additional:
        out["additional_context"] = additional
    return out


def validate_cmdb_input(data: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    schema = schema or _load_input_schema()
    jsonschema.validate(instance=data, schema=schema)


def validate_cmdb_output(data: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    schema = schema or _load_output_schema()
    jsonschema.validate(instance=data, schema=schema)


def enrich_cmdb_output(normalized_input: dict[str, Any]) -> dict[str, Any]:
    """Synthetic CMDB enrichment matching cmdb_output_schema (no live ServiceNow call)."""
    lk = normalized_input["lookup_key"]
    lt = normalized_input.get("lookup_type", "ci_name")
    ctx = normalized_input.get("additional_context") or {}
    env_hint = normalized_input.get("environment_hint")

    hostname: str | None = None
    ip_address: str | None = None
    if lt == "hostname":
        hostname = lk
        ip_address = ctx.get("ip_address")
    elif lt == "ip":
        ip_address = lk
        hostname = ctx.get("fqdn")
    else:
        hostname = ctx.get("fqdn")
        ip_address = ctx.get("ip_address")

    application = ctx.get("application")
    if lt == "application":
        application = application or lk

    if lt == "application":
        ci_name = lk
    elif lt == "ci_name":
        ci_name = lk
    elif lt == "hostname":
        ci_name = lk
    elif lt == "ip":
        ci_name = ctx.get("fqdn") or lk
    else:
        ci_name = lk

    signals = [x for x in (hostname, ip_address, application, ctx.get("region"), env_hint) if x]
    if len(signals) >= 4:
        match_confidence = "high"
    elif len(signals) >= 2:
        match_confidence = "medium"
    else:
        match_confidence = "low"

    if lt in ("ip", "hostname") and (hostname or ip_address):
        match_type = "exact"
    elif lt == "ci_name":
        match_type = "exact"
    elif lt == "application":
        match_type = "fuzzy"
    else:
        match_type = "fuzzy"

    out: dict[str, Any] = {
        "ci_name": ci_name,
        "match_confidence": match_confidence,
        "match_type": match_type,
    }
    if hostname:
        out["hostname"] = hostname
    if ip_address:
        out["ip_address"] = ip_address
    if env_hint:
        out["environment"] = env_hint
    if ctx.get("region"):
        out["region"] = ctx["region"]
    if application:
        out["application"] = application

    base_label = application or ci_name
    env_tag = f" [{env_hint}]" if env_hint else ""
    region_tag = f" ({ctx['region']})" if ctx.get("region") else ""
    out["assignment_group"] = f"Assignment — {base_label}{env_tag}{region_tag}".strip()
    out["owning_team"] = f"Owning — {base_label}"
    out["support_group"] = f"Support — {base_label}{env_tag}"
    out["escalation_group"] = f"Escalation — {base_label}{env_tag}"

    return out


def process_payload_to_enrichment(
    payload: Any,
    *,
    use_llm: bool = False,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> Any:
    """Normalize input (same as process_payload), then map each record to cmdb output schema."""
    output_schema = output_schema or _load_output_schema()
    normalized = process_payload(payload, use_llm=use_llm, schema=input_schema)

    def enrich_one(obj: dict[str, Any]) -> dict[str, Any]:
        enriched = enrich_cmdb_output(obj)
        validate_cmdb_output(enriched, schema=output_schema)
        return enriched

    if isinstance(normalized, list):
        return [enrich_one(x) for x in normalized]
    return enrich_one(normalized)


def generate_cmdb_input_llm(
    data: dict[str, Any],
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use chat model to produce schema-conformant cmdb input."""
    if not API_KEY:
        raise ValueError("Set OPENAI_API_KEY or API_KEY for --llm mode.")

    schema = schema or _load_input_schema()
    user = (
        "JSON SCHEMA (conform output to this):\n"
        + json.dumps(schema, indent=2)
        + "\n\nINPUT (may be partial):\n"
        + json.dumps(data, indent=2)
        + "\n\nOutput a single JSON object matching the schema."
    )
    payload = {
        "model": MODEL_NAME,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    url = f"{MODEL_ENDPOINT}/chat/completions"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if response.status_code != 200:
        raise RuntimeError(f"LLM API error: {response.status_code} - {response.text}")

    text = response.json()["choices"][0]["message"]["content"].strip()
    parsed = _parse_model_json(text)
    if not isinstance(parsed, dict):
        raise ValueError("Model returned non-object JSON")
    validate_cmdb_input(parsed, schema=schema)
    return parsed


def process_payload(
    payload: Any,
    *,
    use_llm: bool = False,
    schema: dict[str, Any] | None = None,
) -> Any:
    """Accept a single object or a list of objects; return same structure."""
    schema = schema or _load_input_schema()

    def one(obj: Any) -> dict[str, Any]:
        if not isinstance(obj, dict):
            raise TypeError("each item must be a JSON object")
        if use_llm:
            merged = {**obj}
            return generate_cmdb_input_llm(merged, schema=schema)
        out = normalize_cmdb_input(obj)
        validate_cmdb_input(out, schema=schema)
        return out

    if isinstance(payload, list):
        return [one(x) for x in payload]
    return one(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CMDB agent: read cmdb_input_schema JSON, print cmdb_output_schema enrichment only."
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="JSON file to read (omit or '-' for stdin)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Use LLM to normalize lookup input first (requires OPENAI_API_KEY or API_KEY)",
    )
    args = parser.parse_args(argv)

    if args.path in (None, "-"):
        raw = sys.stdin.read()
    else:
        raw = Path(args.path).read_text(encoding="utf-8")

    payload = json.loads(raw)
    try:
        out = process_payload_to_enrichment(payload, use_llm=args.llm)
    except (jsonschema.ValidationError, ValueError, TypeError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(out, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
