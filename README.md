# SolarWinds AI Triage — Ansible EDA Demo

An Event-Driven Ansible (EDA) demo that ingests SolarWinds monitoring alerts,
uses an LLM to classify and triage them, and orchestrates automated remediation
through an Ansible Automation Platform (AAP) workflow.

---

## Overview

This project demonstrates a closed-loop AI operations pattern:

```
SolarWinds Alert
      │
      ▼
EDA Rulebook (solarwinds.yml)
      │  Routes event, suppresses maintenance window noise
      ▼
01 - Classify Alert          ← LLM call: real issue or false positive?
      │
      ▼
02 - Gather Host Data        ← SSH diagnostics: CPU, memory, disk, logs
      │
      ▼
03 - RCA Analysis            ← LLM call: root cause + remediation steps
      │
      ▼
04 - Create ServiceNow Ticket ← Ticket opened with full AI context
      │
      ▼
05 - Notify Mattermost       ← AI summary posted to ops channel
      │
      ▼
06 - Remediate Host          ← Automated fix executed (or pending human approval)
      │
      ▼
ServiceNow ticket updated with remediation outcome
```

---

## Repository Structure

```
solarwinds-ai/
├── rulebooks/
│   └── solarwinds.yml          # EDA rulebook — event ingestion and routing
├── vars/
│   └── triage_policies.yml     # Triage policies interpolated into LLM prompts
└── playbooks/
    ├── 01_classify_alert.yml   # LLM classifier: real issue vs. false positive
    ├── 02_gather_host_data.yml # Collect diagnostics from the affected host
    ├── 03_rca_analysis.yml     # LLM root cause analysis and recommendations
    ├── 04_create_snow_ticket.yml  # Open/update ServiceNow incident
    ├── 05_notify_mattermost.yml   # Post AI summary to Mattermost channel
    └── 06_remediate_host.yml   # Execute remediation, update ticket on completion
```

---

## How It Works

### Event Source
The EDA rulebook listens to a SolarWinds event stream. Each incoming alert
payload includes fields such as `alert_name`, `criticality`, `metric`,
`maintenance_window`, and `related_alerts_count`.

### Triage Policies (`vars/triage_policies.yml`)
Plain-language policies are defined in YAML and injected into the LLM classifier
prompt at runtime. This allows operations teams to update triage logic — such as
suppression rules, escalation thresholds, or auto-remediation eligibility —
without modifying any playbook code.

### AI Classification (Playbook 01)
The first LLM call evaluates the alert against the triage policies and returns:
- `classification`: `real_issue` or `false_positive`
- `recommended_action`: escalate, suppress, investigate, auto_remediate, or human_approval
- `matched_policy`: which policy drove the decision

### Host Diagnostics (Playbook 02)
If the alert is classified as a real issue, Ansible connects to the affected host
and collects CPU, memory, disk, service status, and recent syslog output.

### Root Cause Analysis (Playbook 03)
The second LLM call receives the alert context plus the host diagnostics and returns:
- Root cause determination
- Severity assessment
- Step-by-step remediation recommendations
- Whether automated remediation is safe to proceed

### ServiceNow Integration (Playbook 04)
An incident is opened in ServiceNow populated with the full AI triage context,
including classification reasoning, root cause, and recommended steps.

### Mattermost Notification (Playbook 05)
A formatted summary is posted to the configured ops channel with severity
indicators, root cause, and a link to the ServiceNow ticket.

### Remediation (Playbook 06)
Automated remediation is executed for known metric types
(`node unreachable`, `service down`, `high cpu`, `disk full`).
Unknown metrics are flagged for human approval before any action is taken.
The ServiceNow ticket is updated with the remediation outcome on completion.

---

## Prerequisites

- Ansible Automation Platform (AAP) 2.4+
- Event-Driven Ansible (EDA) controller
- A SolarWinds event stream or webhook configured to POST alert payloads
- An LLM API endpoint (compatible with OpenAI chat completions API format)
- ServiceNow instance with REST API access
- Mattermost incoming webhook

---

## Required Credentials / Environment Variables

| Variable | Description |
|---|---|
| `LLM_API_ENDPOINT` | Base URL of the LLM API (e.g. model-as-a-service endpoint) |
| `LLM_API_TOKEN` | Bearer token for LLM API authentication |
| `SNOW_INSTANCE` | ServiceNow instance name (e.g. `mycompany`) |
| `SNOW_USERNAME` | ServiceNow API username |
| `SNOW_PASSWORD` | ServiceNow API password |
| `MATTERMOST_WEBHOOK_URL` | Incoming webhook URL for your Mattermost channel |

Store these as AAP credentials or in an AAP credential type — do not hardcode them.

---

## Triage Policy Customization

Edit [`vars/triage_policies.yml`](vars/triage_policies.yml) to adjust triage behavior.
Policies are injected into the LLM prompt at runtime, so changes take effect
immediately on the next alert without any playbook modifications.

Example policy:
```yaml
- id: POL-002
  name: Tier3 maintenance window suppress
  condition: "criticality is tier3 AND maintenance_window is true"
  action: suppress
  description: >
    Tier3 alerts during an active maintenance window are expected noise.
    Suppress and log only; do not open a ticket.
```

---

## Workflow Setup in AAP

Create a workflow job template in AAP with the following node sequence:

```
01_classify_alert
      │
      ├─ (real_issue) ──► 02_gather_host_data ──► 03_rca_analysis
      │                                                  │
      │                                           04_create_snow_ticket
      │                                                  │
      │                                           05_notify_mattermost
      │                                                  │
      │                                    ┌─────────────┴──────────────┐
      │                             (auto_remediate)            (human_approval)
      │                                    │                            │
      │                             06_remediate_host          Approval Node
      │                                                                  │
      │                                                         06_remediate_host
      │
      └─ (false_positive) ──► 05_notify_mattermost
```

Each playbook passes output forward using `set_stats`, which AAP makes available
as extra variables to subsequent job templates in the workflow.
