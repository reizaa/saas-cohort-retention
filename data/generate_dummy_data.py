"""Generate a small, fully synthetic monthly-billing dataset for the cohort pipeline.

Output: data/raw_payments.csv with one row per account per billed month.
The data deliberately contains a few "dirty" rows (duplicates, an internal test
account, a zero-value row) so that the cleaning step has something to do.

Only the standard library is used and the seed is fixed, so the file is reproducible.
"""
import csv
import random
from datetime import date
from pathlib import Path

SEED = 42
N_ACCOUNTS = 36
FIRST_MONTH = date(2025, 1, 1)
N_MONTHS = 12
OUT = Path(__file__).parent / "raw_payments.csv"
OUT_V2 = Path(__file__).parent / "raw_payments_refresh.csv"


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def main() -> None:
    rng = random.Random(SEED)
    rows = []
    for i in range(1, N_ACCOUNTS + 1):
        account = f"company_{i:03d}"
        segment = "Enterprise" if rng.random() < 0.3 else "SMB"
        start = rng.randrange(0, N_MONTHS - 1)
        mrr = rng.choice([1500, 2500, 4000, 6000]) if segment == "Enterprise" \
            else rng.choice([100, 150, 250, 400])
        for k in range(start, N_MONTHS):
            month = add_months(FIRST_MONTH, k)
            rows.append([account, segment, month.isoformat(), mrr])
            # monthly events: churn, upgrade, downgrade or no change
            r = rng.random()
            if r < 0.07:
                break                                   # churned, no more invoices
            if r < 0.17:
                mrr = round(mrr * rng.choice([1.25, 1.5, 2.0]))  # upgrade
            elif r < 0.24:
                mrr = round(mrr * rng.choice([0.5, 0.75]))       # downgrade

    # dirty rows the cleaning step must remove
    rows.append(rows[5][:])                              # exact duplicate
    rows.append(rows[20][:])                             # exact duplicate
    rows.append(["test_account_999", "SMB", "2025-03-01", 100])  # internal test
    rows.append(["company_003", "SMB", "2025-07-01", 0])         # zero-value invoice

    rows.sort(key=lambda r: (r[2], r[0]))
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["account_id", "segment", "billing_month", "monthly_revenue"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {OUT}")

    # a later "refresh" of the same extract, used by src/compare_runs.py:
    # two late-arriving invoices, one invoice voided, one amount corrected
    v2 = [r[:] for r in rows]
    seg = {r[0]: r[1] for r in rows}
    billed_dec = {r[0] for r in rows if r[2] == "2025-12-01"}
    late = [a for a in sorted(seg) if a not in billed_dec and a.startswith("company_")][:2]
    for acc in late:
        v2.append([acc, seg[acc], "2025-12-01", 200])
    voided = v2.pop(40)
    v2[60][3] = v2[60][3] + 50
    with OUT_V2.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["account_id", "segment", "billing_month", "monthly_revenue"])
        w.writerows(sorted(v2, key=lambda r: (r[2], r[0])))
    print(f"wrote {len(v2)} rows -> {OUT_V2} (voided {voided[0]} {voided[2]})")


if __name__ == "__main__":
    main()
