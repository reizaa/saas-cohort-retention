"""Run the cohort pipeline end to end.

    python data/generate_dummy_data.py
    python src/main.py [--input data/raw_payments.csv] [--out output]
"""
import argparse
from pathlib import Path

import pandas as pd

import cohort
import validate

ROOT = Path(__file__).resolve().parents[1]


def run(input_csv: Path, out_dir: Path, quiet: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = validate.Report()

    raw = pd.read_csv(input_csv)
    clean = cohort.clean(raw)
    validate.check_clean(rep, raw, clean)

    coh = cohort.assign_cohort(clean)
    validate.check_cohort(rep, clean, coh)

    ch = cohort.monthly_changes(coh)
    validate.check_changes(rep, coh, ch)

    outputs = {}
    for seg in ["All", "SMB", "Enterprise"]:
        part = ch if seg == "All" else ch[ch["segment"] == seg]
        suffix = "" if seg == "All" else f"_{seg.lower()}"
        rev = cohort.revenue_triangle(part)
        ret = cohort.account_retention_triangle(part)
        if seg == "All":
            validate.check_triangles(rep, part, rev, ret)
        outputs[f"revenue_triangle{suffix}"] = rev
        outputs[f"retention_triangle{suffix}"] = ret
    outputs["churned_accounts_triangle"] = cohort.churned_accounts_triangle(ch)
    outputs["upgrade_value_triangle"] = cohort.upgrade_downgrade_triangle(ch, "upgrade")
    outputs["downgrade_value_triangle"] = cohort.upgrade_downgrade_triangle(ch, "downgrade")
    outputs["net_revenue_retention"] = cohort.net_revenue_retention(ch)

    last = ch["billing_month"].max()
    for name in [n for n in outputs if "triangle" in n]:
        outputs[name] = cohort.mask_unobserved(outputs[name], last)
    for name, df in outputs.items():
        df.to_csv(out_dir / f"{name}.csv", index="triangle" in name)
    rep.frame().to_csv(out_dir / "validation_report.csv", index=False)

    if not quiet:
        print(rep.frame().to_string(index=False))
        print("\nAll checks passed" if rep.all_ok else "\nSOME CHECKS FAILED")
        nrr = outputs["net_revenue_retention"]
        print("\nLatest NRR by segment:")
        print(nrr[nrr["billing_month"] == nrr["billing_month"].max()]
              [["segment", "start_mrr", "upgrade", "downgrade", "churn", "end_mrr", "nrr"]]
              .to_string(index=False))
        plot(outputs, out_dir)
    return {"ok": rep.all_ok, "outputs": outputs, "changes": ch}


def plot(outputs: dict, out_dir: Path) -> None:
    """Optional chart: cohort retention curves + NRR per segment."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - skipping chart")
        return
    ret = outputs["retention_triangle"]
    nrr = outputs["net_revenue_retention"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.5))
    last = pd.Period(nrr["billing_month"].max(), "M")
    for cohort_month, row in ret.iterrows():
        # only plot the observed part of the triangle (ages up to the last month)
        n = (last - pd.Period(cohort_month, "M")).n + 1
        a.plot(range(n), row.values[:n], alpha=0.6, label=cohort_month)
    a.set(title="Account retention by cohort", xlabel="Months since start",
          ylabel="Share of accounts still paying", ylim=(0, 1.05))
    a.legend(fontsize=7, ncol=2)
    for seg, g in nrr.groupby("segment"):
        b.plot(g["billing_month"], g["nrr"], marker="o", label=seg)
    b.axhline(1, color="grey", lw=0.8, ls="--")
    b.set(title="Monthly net revenue retention", ylabel="NRR")
    b.tick_params(axis="x", rotation=45)
    b.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "cohort_chart.png", dpi=110)
    print(f"\nchart -> {out_dir / 'cohort_chart.png'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=ROOT / "data" / "raw_payments.csv", type=Path)
    p.add_argument("--out", default=ROOT / "output", type=Path)
    a = p.parse_args()
    result = run(a.input, a.out)
    raise SystemExit(0 if result["ok"] else 1)
