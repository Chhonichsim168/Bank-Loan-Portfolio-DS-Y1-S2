"""
risk_economics.py
=================
Pricing, loss and staging arithmetic. Pure functions - no Streamlit, no database.

What is and is not claimed
--------------------------
The approval model estimates *how likely this bank was to approve* an application. It does NOT
estimate default. So the default probabilities used here are **assumptions you set** (per
routing band, on the Policy page) - not model output. Once the Loan book holds seasoned loans,
``observed_default_rates`` shows what actually happened per band so the assumptions can be
replaced with evidence.

Staging uses the common days-past-due back-stops (Stage 2 from 30 days, Stage 3 from 90 days).
Confirm the thresholds and the provisioning method against your own regulator's rules; this is an
illustration of the arithmetic, not a regulatory provision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STAGE2_DPD, STAGE3_DPD = 30, 90
STAGE2_PD = 0.25            # assumed lifetime PD once a loan is 30+ days late (Stage 2)
LGD_FLOOR = 0.05            # even fully secured loans keep a small loss allowance
BANDS = ["Fast-track", "Review", "Refer", "Decline"]


def emi(principal: float, annual_rate: float, term_months: int) -> float:
    """Level monthly instalment of an annuity loan."""
    if principal <= 0 or term_months <= 0:
        return 0.0
    r = annual_rate / 12
    if r == 0:
        return principal / term_months
    f = (1 + r) ** term_months
    return principal * r * f / (f - 1)


def suggested_rate(routing: str, settings) -> float | None:
    """Risk-based rate for a routing band; None where the band is a decline."""
    spread = {"Fast-track": 0.0, "Review": settings.spread_review, "Refer": settings.spread_refer}
    if routing not in spread:
        return None
    return settings.base_rate + spread[routing]


def band_pd(routing: str, settings) -> float:
    return {"Fast-track": settings.pd_fast_track, "Review": settings.pd_review,
            "Refer": settings.pd_refer, "Decline": settings.pd_decline}.get(routing, settings.pd_decline)


def loss_given_default(exposure: float, collateral_value: float, settings, haircut_shock: float = 0.0) -> float:
    """Unsecured LGD, reduced by the haircut-adjusted collateral cover. ``haircut_shock`` is
    added to the haircut for stress tests."""
    if exposure <= 0:
        return 0.0
    if collateral_value <= 0:
        return float(settings.lgd_unsecured)
    cover = collateral_value * (1 - min(1.0, settings.collateral_haircut + haircut_shock)) / exposure
    return float(min(settings.lgd_unsecured, max(LGD_FLOOR, 1.0 - cover)))


def expected_loss(exposure: float, collateral_value: float, routing: str, settings,
                  pd_multiplier: float = 1.0, haircut_shock: float = 0.0) -> dict:
    """EL = PD x LGD x EAD for a new loan at origination (12-month PD from the band assumption)."""
    pd_ = min(1.0, band_pd(routing, settings) * pd_multiplier)
    lgd = loss_given_default(exposure, collateral_value, settings, haircut_shock)
    el = pd_ * lgd * exposure
    return {"pd": pd_, "lgd": lgd, "ead": float(exposure), "el": el,
            "el_pct": el / exposure if exposure else 0.0}


def pricing_view(principal: float, term_months: int, routing: str, collateral_value: float, settings) -> dict | None:
    """Suggested rate, instalment and a one-line risk-adjusted view for a new loan."""
    rate = suggested_rate(routing, settings)
    if rate is None:
        return None
    el = expected_loss(principal, collateral_value, routing, settings)
    return {"rate": rate, "emi": emi(principal, rate, term_months), "el": el,
            "risk_adjusted_rate": rate - el["el_pct"]}   # rate left after one year's expected loss


def stage_for(dpd: int, status: str = "Active") -> int:
    if status == "Written off" or dpd >= STAGE3_DPD:
        return 3
    return 2 if dpd >= STAGE2_DPD else 1


def provision_row(exposure: float, stage: int, band: str, collateral_value: float, settings,
                  pd_multiplier: float = 1.0, haircut_shock: float = 0.0) -> float:
    """Illustrative expected loss on a live loan: band PD (Stage 1), a fixed assumed PD (Stage 2),
    100% PD (Stage 3, already impaired)."""
    pd_ = {1: band_pd(band, settings), 2: STAGE2_PD, 3: 1.0}[stage]
    pd_ = min(1.0, pd_ * pd_multiplier) if stage < 3 else 1.0
    return pd_ * loss_given_default(exposure, collateral_value, settings, haircut_shock) * exposure


def observed_default_rates(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Per band: loans seasoned enough to judge, and the share that went 90+ days late or was
    written off. ``outcomes`` needs columns ``band`` and ``repaid`` (1 good, 0 bad)."""
    if outcomes.empty:
        return pd.DataFrame(columns=["band", "loans", "observed_default_rate"])
    g = outcomes.groupby("band")["repaid"].agg(loans="size", observed_default_rate=lambda x: 1 - x.mean())
    return g.reindex([b for b in BANDS if b in g.index]).reset_index()
