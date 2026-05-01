"""
Streamlit UI: enter SolarWinds-style alert fields (same shape as callmodel.py),
then POST the payload to an Ansible EDA external event stream webhook.

Run:
    streamlit run EnergyTransfer/Trigger_SW.py
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

# ================================
# CONFIGURATION
# ================================

WEBHOOK_URL = os.environ.get(
    "TRIGGER_SW_WEBHOOK_URL",
    "https://aap.shadowman.dev/eda-event-streams/api/eda/v1/external_event_stream/"
    "7c41f7fb-2a4c-4b0f-ab85-fafed64c0c8a/post/",
)

# Defaults aligned with callmodel.py TEST_IGNORE_ALERT1
DEFAULT_ALERT: dict[str, Any] = {
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

# Streamlit: colored borders on the main two-column row (preview left, form right).
_STREAMLIT_PANEL_BORDER_CSS = """
<style>
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


def _post_webhook(
    payload: dict[str, Any],
    *,
    authorization: str | None,
    timeout: int = 60,
) -> requests.Response:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if authorization and authorization.strip():
        token = authorization.strip()
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        headers["Authorization"] = token
    return requests.post(WEBHOOK_URL, headers=headers, json=payload, timeout=timeout)


def _run_streamlit_ui() -> None:
    import streamlit as st

    st.set_page_config(page_title="EDA webhook trigger", layout="wide")
    st.markdown(_STREAMLIT_PANEL_BORDER_CSS, unsafe_allow_html=True)
    st.title("Trigger event to Ansible EDA (webhook)")
    st.caption(
        "Right: same alert fields as `callmodel.py` (TEST_IGNORE_ALERT1). **Submit event** POSTs JSON to the EDA "
        "external event stream. Left: envelope options and the last payload sent."
    )
    st.caption(f"Endpoint: `{WEBHOOK_URL}`")

    d = DEFAULT_ALERT
    corroboration_default = ", ".join(d["corroboration"])

    panel_left, panel_right = st.columns([1, 1], gap="large")

    with panel_left:
        st.subheader("Envelope")
        st.text_input(
            "source",
            value="EnergyTransfer/Trigger_SW",
            key="tw_source",
            help="Top-level `source` when wrapping under `alert`.",
        )
        st.checkbox("Wrap alert under `alert` key", value=True, key="tw_wrap")

        if "tw_last_payload" in st.session_state:
            st.divider()
            st.subheader("Last payload sent")
            st.json(st.session_state.tw_last_payload)

    with panel_right:
        st.subheader("Alert input")
        with st.form("webhook_alert_form"):
            col1, col2 = st.columns(2)
            with col1:
                alert_name = st.text_input("alert_name", value=d["alert_name"])
                object_type = st.text_input("object_type", value=d["object_type"])
                environment = st.text_input("environment", value=d["environment"])
                criticality = st.selectbox(
                    "criticality",
                    options=["tier1", "tier2", "tier3"],
                    index=["tier1", "tier2", "tier3"].index(str(d["criticality"])),
                )
                metric = st.text_input("metric", value=d["metric"])
                duration_minutes = st.number_input(
                    "duration_minutes", min_value=0, value=int(d["duration_minutes"]), step=1
                )
                history = st.text_input("history", value=d["history"])
            with col2:
                maintenance_window = st.checkbox("maintenance_window", value=bool(d["maintenance_window"]))
                corroboration_str = st.text_input(
                    "corroboration (comma-separated)",
                    value=corroboration_default,
                )
                related_alerts_count = st.number_input(
                    "related_alerts_count", min_value=0, value=int(d["related_alerts_count"]), step=1
                )
                time_of_day = st.text_input("time_of_day", value=d["time_of_day"])
                additional_context = st.text_area(
                    "additional_context", value=str(d["additional_context"]), height=100
                )

            authorization = st.text_input(
                "Authorization (optional)",
                type="password",
                help="Bearer token if required by the endpoint.",
                placeholder="paste token or leave empty",
            )
            submitted = st.form_submit_button("Submit event", type="primary")

    if submitted:
        corroboration = [x.strip() for x in corroboration_str.split(",") if x.strip()]
        alert: dict[str, Any] = {
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
        src = (st.session_state.get("tw_source") or "EnergyTransfer/Trigger_SW").strip()
        wrap_alert = bool(st.session_state.get("tw_wrap", True))
        if wrap_alert:
            payload: dict[str, Any] = {"source": src or "EnergyTransfer/Trigger_SW", "alert": alert}
        else:
            payload = dict(alert)
            if src:
                payload["source"] = src

        st.session_state.tw_last_payload = payload

        with st.expander("Payload for this request", expanded=True):
            st.json(payload)

        with st.spinner("POSTing to webhook…"):
            try:
                resp = _post_webhook(payload, authorization=authorization or None)
            except requests.RequestException as e:
                st.error(f"Request failed: {e}")
            else:
                st.subheader("Response")
                st.metric("HTTP status", resp.status_code)
                ct = (resp.headers.get("Content-Type") or "").lower()
                body = resp.text or "(empty body)"
                if "json" in ct:
                    try:
                        st.json(resp.json())
                    except ValueError:
                        st.code(body, language="text")
                else:
                    st.code(body, language="text")


def _running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        return False
    return get_script_run_ctx() is not None


def _run_cli_demo() -> None:
    payload = {
        "source": "EnergyTransfer/Trigger_SW",
        "alert": dict(DEFAULT_ALERT),
    }
    print(f"POST {WEBHOOK_URL}")
    print(json.dumps(payload, indent=2))
    resp = _post_webhook(payload, authorization=os.environ.get("TRIGGER_SW_AUTH"))
    print(resp.status_code, resp.reason)
    print(resp.text[:4000])


if __name__ == "__main__":
    if _running_under_streamlit():
        _run_streamlit_ui()
    else:
        _run_cli_demo()
