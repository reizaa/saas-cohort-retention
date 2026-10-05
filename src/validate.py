"""Before/after checks for each pipeline step.

Each check compares the frame going into a step with the frame coming out and
asserts an invariant (row counts explained, revenue conserved, bridge balances).
Results are collected into a small report so a reviewer sees *why* numbers moved.
"""
import pandas as pd


class Report:
    def __init__(self):
        self.rows = []

    def add(self, step, check, before, after, ok, note=""):
        self.rows.append(dict(step=step, check=check, before=before,
                              after=after, ok=bool(ok), note=note))

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    @property
    def all_ok(self) -> bool:
        return all(r["ok"] for r in self.rows)


def check_clean(rep: Report, raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    test = raw["account_id"].str.startswith(("test_", "internal_"))
    nonpos = raw["monthly_revenue"] <= 0
    dupes = raw[~test & ~nonpos].duplicated().sum()
    expected = len(raw) - test.sum() - (nonpos & ~test).sum() - dupes
    rep.add("1 clean", "rows = raw - test - non-positive - duplicates",
            len(raw), len(clean), expected == len(clean),
            f"test={test.sum()}, non_positive={(nonpos & ~test).sum()}, dupes={dupes}")
    kept = raw[~test & ~nonpos].drop_duplicates()["monthly_revenue"].sum()
    rep.add("1 clean", "revenue = revenue of kept rows",
            raw["monthly_revenue"].sum(), clean["monthly_revenue"].sum(),
            abs(kept - clean["monthly_revenue"].sum()) < 1e-6)


def check_cohort(rep: Report, clean: pd.DataFrame, coh: pd.DataFrame) -> None:
    rep.add("2 cohort", "rows unchanged", len(clean), len(coh), len(clean) == len(coh))
    rep.add("2 cohort", "one cohort per account",
            clean["account_id"].nunique(), coh.groupby("account_id")["cohort"].nunique().max(),
            coh.groupby("account_id")["cohort"].nunique().max() == 1)
    rep.add("2 cohort", "age >= 0", "", int(coh["age"].min()), coh["age"].min() >= 0)


def check_changes(rep: Report, coh: pd.DataFrame, ch: pd.DataFrame) -> None:
    rep.add("3 movements", "revenue conserved",
            coh["monthly_revenue"].sum(), ch["monthly_revenue"].sum(),
            abs(coh["monthly_revenue"].sum() - ch["monthly_revenue"].sum()) < 1e-6)
    # MRR bridge: previous MRR + sum of movement deltas = current MRR, every month
    by_month = ch.groupby("billing_month").agg(prev=("prev_revenue", "sum"),
                                                delta=("delta", "sum"),
                                                cur=("monthly_revenue", "sum"))
    gap = (by_month["prev"] + by_month["delta"] - by_month["cur"]).abs().max()
    rep.add("3 movements", "MRR bridge balances every month", "", float(gap), gap < 1e-6)
    totals = by_month["cur"].shift(1).fillna(0)
    rep.add("3 movements", "prev MRR = last month's MRR", "",
            float((totals - by_month["prev"]).abs().max()),
            (totals - by_month["prev"]).abs().max() < 1e-6)


def check_triangles(rep: Report, ch: pd.DataFrame, rev: pd.DataFrame,
                    ret: pd.DataFrame) -> None:
    rep.add("4 triangles", "revenue triangle total = total revenue",
            ch["monthly_revenue"].sum(), rev.values.sum(),
            abs(ch["monthly_revenue"].sum() - rev.values.sum()) < 1e-6)
    rep.add("4 triangles", "retention M0 = 100%", "", float(ret["M0"].min()),
            (ret["M0"] == 1).all())
    rep.add("4 triangles", "retention never above 100%", "", float(ret.values.max()),
            ret.values.max() <= 1)
