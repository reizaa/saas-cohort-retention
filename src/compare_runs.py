"""Before vs after validation of two pipeline runs.

When the source extract is refreshed, the revenue triangle changes. This script
re-runs the pipeline on both extracts, lists every triangle cell that moved and
explains each one from the underlying account-month rows:

  new invoice      - the account-month did not exist before
  removed invoice  - the account-month disappeared (voided / filtered)
  amount changed   - same account-month, different revenue
  cohort moved     - the account's first month changed, so its history shifted

    python src/compare_runs.py [--before data/raw_payments.csv]
                               [--after data/raw_payments_refresh.csv]
"""
import argparse
from pathlib import Path

import pandas as pd

import cohort
from main import ROOT, run


def account_months(csv_path: Path) -> pd.DataFrame:
    return cohort.assign_cohort(cohort.clean(pd.read_csv(csv_path)))


def explain(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    key = ["account_id", "billing_month"]
    m = before.merge(after, on=key, how="outer", suffixes=("_before", "_after"),
                     indicator=True)
    m = m[(m["_merge"] != "both")
          | (m["monthly_revenue_before"] != m["monthly_revenue_after"])
          | (m["cohort_before"] != m["cohort_after"])].copy()
    reason = {"right_only": "new invoice", "left_only": "removed invoice"}
    m["reason"] = m["_merge"].map(reason).fillna("amount changed")
    moved = m["cohort_before"].notna() & m["cohort_after"].notna() & \
        (m["cohort_before"] != m["cohort_after"])
    m.loc[moved, "reason"] = "cohort moved"
    m["cohort"] = m["cohort_after"].fillna(m["cohort_before"]).astype(str)
    m = m.fillna({"monthly_revenue_before": 0, "monthly_revenue_after": 0})
    m["diff"] = m["monthly_revenue_after"] - m["monthly_revenue_before"]
    m["billing_month"] = m["billing_month"].astype(str)
    return m[["account_id", "cohort", "billing_month", "reason",
              "monthly_revenue_before", "monthly_revenue_after", "diff"]]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--before", default=ROOT / "data" / "raw_payments.csv", type=Path)
    p.add_argument("--after", default=ROOT / "data" / "raw_payments_refresh.csv", type=Path)
    a = p.parse_args()

    out = ROOT / "output" / "compare"
    rb = run(a.before, out / "before", quiet=True)
    ra = run(a.after, out / "after", quiet=True)
    tb = rb["outputs"]["revenue_triangle"]
    ta = ra["outputs"]["revenue_triangle"]
    tb, ta = tb.fillna(0).align(ta.fillna(0), fill_value=0)

    cells = (ta - tb).stack()
    cells = cells[cells.abs() > 1e-9].rename("diff").reset_index()
    cells.columns = ["cohort", "age", "diff"]
    print(f"Changed triangle cells: {len(cells)}")
    print(cells.to_string(index=False))

    rows = explain(account_months(a.before), account_months(a.after))
    print("\nWhy they changed (account-month level):")
    print(rows.to_string(index=False))

    # reconciliation: the sum of explained row diffs must equal the triangle diff
    # (cohort-moved rows shift between cells but net to the same total)
    tri_total = float((ta - tb).values.sum())
    row_total = float(rows.loc[rows["reason"] != "cohort moved", "diff"].sum())
    ok = abs(tri_total - row_total) < 1e-6 and rb["ok"] and ra["ok"]
    print(f"\ntriangle diff total = {tri_total:,.0f} | explained rows total = "
          f"{row_total:,.0f} -> {'RECONCILED' if ok else 'NOT RECONCILED'}")
    cells.to_csv(out / "changed_cells.csv", index=False)
    rows.to_csv(out / "change_reasons.csv", index=False)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
