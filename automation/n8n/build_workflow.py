"""Generates automation/n8n/cohort_monthly_pulse.json.

The pipeline itself stays in Python - n8n only schedules it, checks the result and talks
to Slack. That way there is a single implementation of the cohort logic.
Credentials are placeholders; pick your own after importing.

    python automation/n8n/build_workflow.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
BI = {"httpHeaderAuth": {"id": "REPLACE_ME", "name": "BI API key"}}
SLACK = {"slackApi": {"id": "REPLACE_ME", "name": "Slack bot"}}
WORKDIR = "/opt/cohort"          # where the repo is checked out on the n8n host


def node(name, kind, x, y, params, version=1, creds=None):
    n = {"name": name, "type": f"n8n-nodes-base.{kind}", "typeVersion": version,
         "position": [x, y], "parameters": params}
    if creds:
        n["credentials"] = creds
    return n


def slack_post(name, x, y, text):
    return node(name, "slack", x, y, {
        "select": "channel",
        "channelId": {"__rl": True, "mode": "id", "value": "={{$env.PULSE_CHANNEL_ID}}"},
        "text": text}, 2.2, SLACK)


nodes = [
    node("3rd of every month 08:00", "scheduleTrigger", 0, 0, {"rule": {"interval": [
        {"field": "cronExpression", "expression": "0 8 3 * *"}]}}, 1.2),
    # day 3, not day 1: late invoices for the previous month usually land in the first days
    node("Download billing extract", "httpRequest", 220, 0, {
        "method": "POST",
        "url": "={{$env.BI_BASE_URL}}/api/card/{{$env.BILLING_QUESTION_ID}}/query/csv",
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
        "options": {"response": {"response": {"responseFormat": "file"}}}}, 4.2, BI),
    node("Save as CSV", "readWriteFile", 440, 0, {
        "operation": "write", "fileName": f"{WORKDIR}/data/billing_latest.csv"}),
    node("Run pipeline", "executeCommand", 660, 0, {
        "command": f"cd {WORKDIR} && python src/main.py --input data/billing_latest.csv "
                   f"--out output/latest > /dev/null; python src/pulse.py --out output/latest --json"}),
    node("Parse summary", "code", 880, 0, {"jsCode":
        "return [{ json: JSON.parse($input.first().json.stdout) }];"}, 2),
    node("Checks passed?", "if", 1100, 0, {"conditions": {"conditions": [{
        "leftValue": "={{$json.ok}}", "rightValue": True,
        "operator": {"type": "boolean", "operation": "true"}}]}}, 2),
    slack_post("Post cohort pulse", 1320, -100, "={{$json.message.text}}"),
    slack_post("Post 'on hold' note", 1320, 100,
               "={{$json.message.text}}\nI'll rerun after the source is fixed."),
]
nodes[-2]["parameters"]["blocksUi"] = "={{ JSON.stringify($json.message.blocks) }}"
nodes[-2]["parameters"]["messageType"] = "block"

conn = {}
for a, b in zip(nodes[:5], nodes[1:6]):
    conn[a["name"]] = {"main": [[{"node": b["name"], "type": "main", "index": 0}]]}
conn["Checks passed?"] = {"main": [[{"node": "Post cohort pulse", "type": "main", "index": 0}],
                                   [{"node": "Post 'on hold' note", "type": "main", "index": 0}]]}

wf = {"name": "Cohort - monthly refresh + Slack pulse", "nodes": nodes, "connections": conn,
      "settings": {"executionOrder": "v1", "timezone": "UTC",
                   "errorWorkflow": "REPLACE_WITH_ERROR_HANDLER_ID"}}
(HERE / "cohort_monthly_pulse.json").write_text(json.dumps(wf, indent=2) + "\n")
print(f"cohort_monthly_pulse.json: {len(nodes)} nodes")
