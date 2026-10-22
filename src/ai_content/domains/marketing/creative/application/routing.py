"""Deterministic production routing for Marketing-selected SKU work."""

from ai_content.domains.marketing.creative.ports.contracts import (
    MarketingCreativeAutomationRequest,
    ProductionRoute,
    ProductionRoutingDecision,
)


def decide_production_route(
    request: MarketingCreativeAutomationRequest,
) -> ProductionRoutingDecision:
    """Treat Lead Marketing SKU selection as approval for the automation lane."""
    if request.high_brand_risk and not request.automation_override:
        return ProductionRoutingDecision(
            route=ProductionRoute.MANUAL,
            reasons=("high brand risk requires human production",),
            requires_override=True,
        )
    reason = (
        "Lead Marketing explicitly approved automation for this high-risk SKU"
        if request.automation_override and request.high_brand_risk
        else "Lead Marketing selected this SKU for automated production"
    )
    return ProductionRoutingDecision(
        route=ProductionRoute.AUTOMATED,
        reasons=(reason,),
    )


__all__ = ["decide_production_route"]
