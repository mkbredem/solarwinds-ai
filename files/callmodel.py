import json
import os
from pathlib import Path

import requests

# ================================
# CONFIGURATION (EDIT THESE)
# ================================

API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
MODEL_ENDPOINT = "https://litellm-prod.apps.maas.redhatworkshops.io/v1"
MODEL_NAME = "granite-3-2-8b-instruct"


HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

POLICY_FILE = Path(__file__).resolve().parent / "solarwinds_alert_policy_rules.txt"
POLICY_TEXT = POLICY_FILE.read_text(encoding="utf-8").strip()


def _set_policy_text(content: str) -> None:
    """Update in-memory policy used by classify_alert (typically after load or save)."""
    global POLICY_TEXT
    POLICY_TEXT = content.strip()


def _save_policy_file(content: str) -> None:
    """Write policy to disk and refresh POLICY_TEXT."""
    POLICY_FILE.write_text(content, encoding="utf-8")
    _set_policy_text(content)


# Streamlit: colored borders on the main two-column row (policy left, alert right).
_STREAMLIT_PANEL_BORDER_CSS = """
<style>
    /* Outer columns: first horizontal block row in main (policy | alert only) */
    section.main div[data-testid="stVerticalBlock"] > div > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-of-type(1) {
        border: 2px solid #c62828 !important;
        border-radius: 10px;
        padding: 10px 12px 16px 12px !important;
        box-sizing: border-box !important;
    }
    section.main div[data-testid="stVerticalBlock"] > div > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-of-type(2) {
        border: 2px solid #1565c0 !important;
        border-radius: 10px;
        padding: 10px 12px 16px 12px !important;
        box-sizing: border-box !important;
    }
</style>
"""

# Defaults aligned with test_ignore_alert1 (Streamlit form + reference dict)
TEST_IGNORE_ALERT1 = {
    "alert_name": "Node Down",
    "object_type": "app down",
    "environment": "qa",
    "criticality": "tier3",
    "metric": "node unreachable",
    "duration_minutes": 7,
    "history": " frequent",
    "maintenance_window": True,
    "corroboration": ["multiple_services_impacted"],
    "related_alerts_count": 3,
    "time_of_day": "outside of business hours",
    "additional_context": "internal-facing application impacted",
}

# ================================
# STATIC PROMPT COMPONENTS
# ================================

SYSTEM_PROMPT = """You are an expert NOC (Network Operations Center) alert triage analyst.

Your task is to classify SolarWinds alerts using:
1. The classification policy
2. The provided examples
3. The alert input data

STRICT RULES:
- Use ONLY the provided input data
- Do NOT assume missing information
- Follow the policy exactly
- Prefer conservative decisions (avoid missing real incidents)
- If uncertain, choose "needs_review"

You MUST NOT:
- Invent context
- Override policy
- Use external knowledge

Your output MUST:
- Be valid JSON
- Follow the exact schema provided
- Contain no extra text outside JSON
"""

FEW_SHOT_EXAMPLES = """
Example 1:
INPUT:
CPU > 90% for 2 minutes, env=dev, recurring auto-resolve, no corroboration

OUTPUT:
{
  "classification": "noise_likely",
  "confidence": 90,
  "reason_codes": ["short_duration", "non_prod", "recurring_pattern"],
  "explanation": "transient CPU spike in dev with no impact",
  "recommended_action": "suppress"
}

---

Example 2:
INPUT:
Node unreachable 6 min, env=prod, tier1, multiple services impacted

OUTPUT:
{
  "classification": "actionable_urgent",
  "confidence": 95,
  "reason_codes": ["prod_outage", "tier1", "corroborated_failure"],
  "explanation": "confirmed production outage with service impact",
  "recommended_action": "page_on_call"
}
"""

# ================================
# CORE FUNCTION
# ================================


def _parse_model_json(text: str) -> dict:
    """Strip optional ``` fences and parse JSON from model output."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return json.loads(t)


def classify_alert(alert_data: dict, *, return_raw: bool = False):
    user_prompt = f"""
CLASSIFICATION POLICY:
{POLICY_TEXT}

FEW-SHOT EXAMPLES:
{FEW_SHOT_EXAMPLES}

ALERT TO CLASSIFY:
{json.dumps(alert_data, indent=2)}

OUTPUT FORMAT:
Return ONLY JSON:

{{
  "classification": "ignore | noise_likely | false_positive_likely | actionable_nonurgent | actionable_urgent | needs_review",
  "confidence": 0-100,
  "reason_codes": ["string"],
  "explanation": "short explanation",
  "recommended_action": "suppress | dedupe | create_ticket | route_to_team | page_on_call | needs_review"
}}
"""

    payload = {
        "model": MODEL_NAME,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    url = f"{MODEL_ENDPOINT.rstrip('/')}/chat/completions"
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code != 200:
        raise Exception(f"LLM API error: {response.status_code} - {response.text}")

    result = response.json()
    output_text = result["choices"][0]["message"]["content"].strip()

    parsed = None
    err = None
    try:
        parsed = _parse_model_json(output_text)
    except json.JSONDecodeError as e:
        err = e

    if return_raw:
        return parsed, output_text

    if err is not None or parsed is None:
        raise Exception(f"Invalid JSON response from model:\n{output_text}") from err
    return parsed


def _run_streamlit_ui() -> None:
    import streamlit as st

    st.set_page_config(page_title="SolarWinds alerts to LLM", layout="wide")
    st.markdown(_STREAMLIT_PANEL_BORDER_CSS, unsafe_allow_html=True)
    st.title("SolarWinds alerts to LLM for classification")
    st.caption(
        "Left: edit `solarwinds_alert_policy_rules.txt` and save to disk. Classification uses the "
        "current left-panel text (save when you want the file on disk to match)."
    )

    if "policy_editor" not in st.session_state:
        st.session_state.policy_editor = POLICY_FILE.read_text(encoding="utf-8")

    panel_left, panel_right = st.columns([1, 1], gap="large")

    with panel_left:
        st.subheader("Classification policy")
        st.caption(str(POLICY_FILE))
        st.text_area(
            "Policy file contents",
            height=560,
            key="policy_editor",
            label_visibility="collapsed",
            help="Edits stay in the browser until you click Save policy changes.",
        )
        if st.button("Save policy changes", type="primary"):
            try:
                _save_policy_file(st.session_state.policy_editor)
            except OSError as e:
                st.error(f"Could not save policy file: {e}")
            else:
                st.success("Policy saved to disk. Classify will use the updated text.")

    d = TEST_IGNORE_ALERT1
    corroboration_default = ", ".join(d["corroboration"])

    with panel_right:
        st.subheader("Alert input")
        with st.form("alert_form"):
            col1, col2 = st.columns(2)
            with col1:
                alert_name = st.text_input("alert_name", value=d["alert_name"])
                object_type = st.text_input("object_type", value=d["object_type"])
                environment = st.text_input("environment", value=d["environment"])
                criticality = st.selectbox(
                    "criticality",
                    options=["tier1", "tier2", "tier3"],
                    index=["tier1", "tier2", "tier3"].index(d["criticality"]),
                )
                metric = st.text_input("metric", value=d["metric"])
                duration_minutes = st.number_input(
                    "duration_minutes", min_value=0, value=int(d["duration_minutes"]), step=1
                )
                history = st.text_input("history", value=d["history"])
            with col2:
                maintenance_window = st.checkbox("maintenance_window", value=d["maintenance_window"])
                corroboration_str = st.text_input(
                    "corroboration (comma-separated)",
                    value=corroboration_default,
                )
                related_alerts_count = st.number_input(
                    "related_alerts_count", min_value=0, value=int(d["related_alerts_count"]), step=1
                )
                time_of_day = st.text_input("time_of_day", value=d["time_of_day"])
                additional_context = st.text_area(
                    "additional_context", value=d["additional_context"], height=100
                )

            submitted = st.form_submit_button("Classify alert", type="primary")

    if submitted:
        _set_policy_text(st.session_state.policy_editor)

        corroboration = [x.strip() for x in corroboration_str.split(",") if x.strip()]
        alert = {
            "alert_name": alert_name,
            "object_type": object_type,
            "environment": environment,
            "criticality": criticality,
            "metric": metric,
            "duration_minutes": int(duration_minutes),
            "history": history,
            "maintenance_window": bool(maintenance_window),
            "corroboration": corroboration,
            "related_alerts_count": int(related_alerts_count),
            "time_of_day": time_of_day,
            "additional_context": additional_context,
        }

        with st.spinner("Calling model…"):
            try:
                parsed, output_text = classify_alert(alert, return_raw=True)
            except Exception as e:
                st.error(str(e))
            else:
                st.subheader("Model output")
                if parsed is not None:
                    st.json(parsed)
                else:
                    st.warning("Model response was not valid JSON.")
                    st.code(output_text, language="json")

                with st.expander("Raw `output_text` from API"):
                    st.code(output_text, language="text")


def _run_cli_demo() -> None:
    sample_actionable_alert = {
        "alert_name": "Node Down",
        "object_type": "server",
        "environment": "prod",
        "criticality": "tier1",
        "metric": "node unreachable",
        "duration_minutes": 7,
        "history": "not frequent",
        "maintenance_window": False,
        "corroboration": ["multiple_services_impacted"],
        "related_alerts_count": 3,
        "time_of_day": "business_hours",
        "additional_context": "customer-facing application impacted",
    }

    test_ignore_alert1 = dict(TEST_IGNORE_ALERT1)

    test_ignore_alert2 = {
        "alert_name": "Node Down",
        "object_type": "app down",
        "environment": "qa",
        "criticality": "tier1",
        "metric": "node unreachable",
        "duration_minutes": 7,
        "history": " frequent",
        "maintenance_window": True,
        "corroboration": ["multiple_services_impacted"],
        "related_alerts_count": 20,
        "time_of_day": "outside of business hours",
        "additional_context": "internal-facing production application impacted",
    }

    _ = test_ignore_alert1, test_ignore_alert2

    result = classify_alert(sample_actionable_alert)

    print("\n=== CLASSIFICATION RESULT ===")
    print(json.dumps(result, indent=2))


def _running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        return False
    return get_script_run_ctx() is not None


if __name__ == "__main__":
    if _running_under_streamlit():
        _run_streamlit_ui()
    else:
        _run_cli_demo()
