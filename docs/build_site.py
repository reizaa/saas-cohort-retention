"""Builds docs/index.html (GitHub Pages) from the CSVs in output/.

    python src/main.py && python src/pulse.py && python docs/build_site.py

Everything is baked into one static page, no server needed.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pulse  # noqa: E402

OUT = ROOT / "output"


def grid(df: pd.DataFrame) -> list:
    return [[None if pd.isna(v) else round(float(v), 3) for v in row] for row in df.values]


def triangles(folder: Path, suffix: str = "") -> dict:
    ret = pd.read_csv(folder / f"retention_triangle{suffix}.csv", index_col=0)
    rev = pd.read_csv(folder / f"revenue_triangle{suffix}.csv", index_col=0)
    kept = rev.div(rev["M0"].where(rev["M0"] > 0), axis=0)          # revenue kept vs month 0
    return {"cohorts": ret.index.tolist(), "accounts": grid(ret), "revenue": grid(kept)}


def profile(path: Path, purpose: str, date_col: str, id_col: str) -> dict:
    """Shape of one synthetic input file, shown on the page so readers know what the numbers stand on."""
    df = pd.read_csv(path)
    cols = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            desc = f"number · {s.min():,.0f} to {s.max():,.0f}"
        else:
            u = s.dropna().unique()
            desc = f"text · {len(u)} values" + (f" ({', '.join(map(str, sorted(u)[:4]))})" if len(u) <= 4 else f", e.g. {u[0]}")
        cols.append({"name": c, "desc": desc, "nulls": int(s.isna().sum())})
    return {"file": str(path.relative_to(ROOT)).replace("\\", "/"), "purpose": purpose, "rows": len(df),
            "ids": int(df[id_col].nunique()), "id_col": id_col,
            "period": f"{df[date_col].min()} to {df[date_col].max()}", "columns": cols}


def main() -> None:
    ret = pd.read_csv(OUT / "retention_triangle.csv", index_col=0)
    nrr = pd.read_csv(OUT / "net_revenue_retention.csv")
    checks = pd.read_csv(OUT / "validation_report.csv")
    summary = pulse.summarise(OUT)
    cmp_dir = OUT / "compare"
    before = pd.read_csv(cmp_dir / "before" / "revenue_triangle.csv", index_col=0)
    after = pd.read_csv(cmp_dir / "after" / "revenue_triangle.csv", index_col=0)
    hold = dict(summary, ok=False, failed_checks=[checks["check"].iloc[1]])
    data = {
        "profile": {
            "generator": "data/generate_dummy_data.py", "seed": 42,
            "files": [profile(ROOT / "data" / "raw_payments.csv", "monthly billing, first extract",
                              "billing_month", "account_id"),
                      profile(ROOT / "data" / "raw_payments_refresh.csv", "same extract one month later (for the refresh check)",
                              "billing_month", "account_id")],
            "quirks": ["an internal test account", "a non-positive invoice", "duplicate rows",
                       "one invoice removed and two added in the refresh"],
        },
        "segments": {"All": triangles(OUT), "SMB": triangles(OUT, "_smb"),
                     "Enterprise": triangles(OUT, "_enterprise")},
        "compare": {"cohorts": after.index.tolist(), "ages": after.columns.tolist(),
                    "before": grid(before), "after": grid(after),
                    "changed": pd.read_csv(cmp_dir / "changed_cells.csv").to_dict("records"),
                    "reasons": pd.read_csv(cmp_dir / "change_reasons.csv").to_dict("records")},
        "pulse_hold": pulse.build_message(json.loads(json.dumps(hold, default=float))),
        "cohorts": ret.index.tolist(),
        "ages": ret.columns.tolist(),
        "retention": [[None if pd.isna(v) else round(float(v), 3) for v in row] for row in ret.values],
        "months": sorted(nrr["billing_month"].unique().tolist()),
        "nrr": {s: g.set_index("billing_month")["nrr"].round(4).to_dict()
                for s, g in nrr.groupby("segment")},
        "checks": checks[["step", "check", "ok"]].to_dict("records"),
        "summary": json.loads(json.dumps(summary, default=float)),
        "pulse": pulse.build_message(summary),
    }
    html = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, default=float))
    (Path(__file__).parent / "index.html").write_text(html, encoding="utf-8")
    print("docs/index.html written")


if __name__ == "__main__":
    main()
