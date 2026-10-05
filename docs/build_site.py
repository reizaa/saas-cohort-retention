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


def main() -> None:
    ret = pd.read_csv(OUT / "retention_triangle.csv", index_col=0)
    nrr = pd.read_csv(OUT / "net_revenue_retention.csv")
    checks = pd.read_csv(OUT / "validation_report.csv")
    summary = pulse.summarise(OUT)
    data = {
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
