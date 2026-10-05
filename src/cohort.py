"""Cohort logic: cleaning, cohort assignment and triangle builders.

Every function takes a DataFrame and returns a new one; nothing is mutated in place,
which makes the before/after checks in validate.py straightforward.
"""
import pandas as pd

TEST_PREFIXES = ("test_", "internal_")


# ---------------------------------------------------------------- step 1: clean
def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Drop test accounts, non-positive invoices and exact duplicates."""
    df = raw.copy()
    df["billing_month"] = pd.to_datetime(df["billing_month"]).dt.to_period("M")
    df = df[~df["account_id"].str.startswith(TEST_PREFIXES)]
    df = df[df["monthly_revenue"] > 0]
    df = df.drop_duplicates()
    # one row per account-month (sum if an account was billed twice in a month)
    return (df.groupby(["account_id", "segment", "billing_month"], as_index=False)
              ["monthly_revenue"].sum())


# ------------------------------------------------------- step 2: assign cohorts
def assign_cohort(df: pd.DataFrame) -> pd.DataFrame:
    """Cohort = first billed month of the account; age = months since cohort."""
    out = df.copy()
    out["cohort"] = out.groupby("account_id")["billing_month"].transform("min")
    out["age"] = (out["billing_month"] - out["cohort"]).apply(lambda x: x.n)
    return out


# -------------------------------------------------- step 3: account-month grid
def monthly_changes(df: pd.DataFrame) -> pd.DataFrame:
    """Compare each account with its previous month and label the movement.

    A churned account gets an explicit row in the month after its last invoice
    with revenue 0, so churn shows up in the triangles.
    """
    last_month = df["billing_month"].max()
    pieces = []
    for acc, g in df.sort_values("billing_month").groupby("account_id"):
        g = g.set_index("billing_month")
        months = pd.period_range(g.index.min(), last_month, freq="M")
        g = g.reindex(months)
        g["account_id"] = acc
        g[["segment", "cohort"]] = g[["segment", "cohort"]].ffill()
        g["monthly_revenue"] = g["monthly_revenue"].fillna(0)
        g["prev_revenue"] = g["monthly_revenue"].shift(1).fillna(0)
        # keep months while active, plus the first month after the last invoice
        active = g["monthly_revenue"] > 0
        keep = active | (active.shift(1, fill_value=False) & ~active)
        pieces.append(g[keep].rename_axis("billing_month").reset_index())
    out = pd.concat(pieces, ignore_index=True)
    out["age"] = (out["billing_month"] - out["cohort"]).apply(lambda x: x.n)

    def label(r):
        if r.prev_revenue == 0 and r.monthly_revenue > 0:
            return "new" if r.age == 0 else "reactivated"
        if r.prev_revenue > 0 and r.monthly_revenue == 0:
            return "churn"
        if r.monthly_revenue > r.prev_revenue:
            return "upgrade"
        if r.monthly_revenue < r.prev_revenue:
            return "downgrade"
        return "flat"

    out["movement"] = out.apply(label, axis=1)
    out["delta"] = out["monthly_revenue"] - out["prev_revenue"]
    return out


# ------------------------------------------------------------- step 4: triangles
def _triangle(df: pd.DataFrame, values: str, aggfunc) -> pd.DataFrame:
    t = df.pivot_table(index="cohort", columns="age", values=values,
                       aggfunc=aggfunc, fill_value=0)
    t.index = t.index.astype(str)
    t.columns = [f"M{c}" for c in t.columns]
    return t


def mask_unobserved(tri: pd.DataFrame, last: pd.Period) -> pd.DataFrame:
    """Blank the lower-right half of a triangle (ages not yet observed)."""
    first = min(pd.Period(c, "M") for c in tri.index)
    ages = [f"M{k}" for k in range((last - first).n + 1)]
    out = tri.astype(float).reindex(columns=ages, fill_value=0.0)
    for c in out.index:
        max_age = (last - pd.Period(c, "M")).n
        out.loc[c, [col for col in out.columns if int(col[1:]) > max_age]] = float("nan")
    return out


def revenue_triangle(ch: pd.DataFrame) -> pd.DataFrame:
    return _triangle(ch, "monthly_revenue", "sum")


def account_retention_triangle(ch: pd.DataFrame) -> pd.DataFrame:
    """Share of each cohort's accounts still paying at age k."""
    active = ch[ch["monthly_revenue"] > 0]
    counts = _triangle(active, "account_id", "nunique")
    return counts.div(counts["M0"], axis=0).round(3)


def churned_accounts_triangle(ch: pd.DataFrame) -> pd.DataFrame:
    return _triangle(ch[ch["movement"] == "churn"], "account_id", "nunique")


def upgrade_downgrade_triangle(ch: pd.DataFrame, kind: str) -> pd.DataFrame:
    return _triangle(ch[ch["movement"] == kind], "delta", "sum")


def net_revenue_retention(ch: pd.DataFrame) -> pd.DataFrame:
    """Monthly NRR per segment: revenue this month from accounts that already paid
    last month, divided by their revenue last month (new accounts excluded)."""
    existing = ch[ch["prev_revenue"] > 0].copy()
    for kind in ("upgrade", "downgrade", "churn"):
        existing[kind] = existing["delta"].where(existing["movement"] == kind, 0)
    cols = ["start_mrr", "end_mrr", "upgrade", "downgrade", "churn"]
    g = existing.groupby(["billing_month", "segment"]).agg(
        start_mrr=("prev_revenue", "sum"),
        end_mrr=("monthly_revenue", "sum"),
        upgrade=("upgrade", "sum"),
        downgrade=("downgrade", "sum"),
        churn=("churn", "sum"),
    ).reset_index()
    total = g.groupby("billing_month", as_index=False)[cols].sum()
    total["segment"] = "All"
    g = pd.concat([g, total], ignore_index=True)
    g["nrr"] = (g["end_mrr"] / g["start_mrr"]).round(4)
    g["billing_month"] = g["billing_month"].astype(str)
    return g.sort_values(["segment", "billing_month"]).reset_index(drop=True)
