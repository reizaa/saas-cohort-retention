"""Monthly cohort pulse for Slack.

    python src/pulse.py                 # dry-run, writes output/pulse_preview.json
    python src/pulse.py --send          # post (needs SLACK_* env vars, see slack_client.py)
    python src/pulse.py --json          # print a small JSON summary (used by the n8n flow)

Reads the CSVs that main.py wrote. If any validation check failed, the pulse turns into
a short "numbers on hold" message instead - I'd rather post nothing than post a cohort
table that doesn't reconcile.
"""
import argparse
import json
from pathlib import Path

import pandas as pd

import slack_client

ROOT = Path(__file__).resolve().parents[1]


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def arrow(now: float, before: float) -> str:
    if pd.isna(before):
        return ""
    d = (now - before) * 100
    return f" ({'+' if d >= 0 else ''}{d:.1f} pt vs prev)"


def summarise(out: Path) -> dict:
    checks = pd.read_csv(out / "validation_report.csv")
    nrr = pd.read_csv(out / "net_revenue_retention.csv")
    ret = pd.read_csv(out / "retention_triangle.csv", index_col=0)
    churned = pd.read_csv(out / "churned_accounts_triangle.csv", index_col=0)

    month = nrr["billing_month"].max()
    prev = sorted(nrr["billing_month"].unique())[-2]
    seg = {}
    for s, g in nrr.groupby("segment"):
        g = g.set_index("billing_month")
        seg[s] = {"nrr": g.loc[month, "nrr"],
                  "nrr_prev": g["nrr"].get(prev, float("nan")),
                  "upgrade": g.loc[month, "upgrade"], "downgrade": g.loc[month, "downgrade"],
                  "churn": g.loc[month, "churn"], "end_mrr": g.loc[month, "end_mrr"]}

    # month-3 retention: the latest cohort that is old enough vs the average of all of them
    m3 = ret["M3"].dropna()
    # accounts churned this month = last observed cell of every cohort row
    last_cells = churned.apply(lambda r: r.dropna().iloc[-1] if r.notna().any() else 0, axis=1)
    return {
        "month": month, "ok": bool(checks["ok"].all()),
        "failed_checks": checks.loc[~checks["ok"], "check"].tolist(),
        "segments": seg,
        "m3_latest_cohort": m3.index[-1] if len(m3) else None,
        "m3_latest": float(m3.iloc[-1]) if len(m3) else None,
        "m3_avg": float(m3.mean()) if len(m3) else None,
        "churned_accounts": int(last_cells.sum()),
    }


def build_message(s: dict) -> dict:
    if not s["ok"]:
        text = (f":pause_button: *Cohort update {s['month']} on hold* - "
                f"{len(s['failed_checks'])} validation check(s) failed: "
                + "; ".join(s["failed_checks"]))
        return {"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]}

    rows = []
    for name in ["All", "SMB", "Enterprise"]:
        v = s["segments"].get(name)
        if not v:
            continue
        rows.append(f"*{name}* NRR {pct(v['nrr'])}{arrow(v['nrr'], v['nrr_prev'])} | "
                    f"upgrade +{v['upgrade']:,.0f}, downgrade {v['downgrade']:,.0f}, "
                    f"churn {v['churn']:,.0f}")
    m3 = ""
    if s["m3_latest"] is not None:
        m3 = (f"Month-3 retention of the {s['m3_latest_cohort']} cohort: "
              f"{pct(s['m3_latest'])} (all cohorts avg {pct(s['m3_avg'])})")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f":bar_chart: *Cohort update - {s['month']}*\n" + "\n".join(rows)}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"{m3}\nAccounts churned this month: *{s['churned_accounts']}*"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            "All validation checks passed | NRR = revenue from last month's accounts / "
            "their revenue last month"}]},
    ]
    return {"text": f"Cohort update {s['month']}", "blocks": blocks}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=ROOT / "output", type=Path)
    p.add_argument("--send", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    summary = summarise(a.out)
    if a.json:
        print(json.dumps({**summary, "message": build_message(summary)}, default=float))
    else:
        print(slack_client.post(build_message(summary), send=a.send,
                                preview=a.out / "pulse_preview.json"))
