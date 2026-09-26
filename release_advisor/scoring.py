"""Deterministic compliance score, computed in code so it is stable run to run."""

from __future__ import annotations

from .releases import release_to_api
from .report import SubmittedReport

BREAKING_PENALTY = {"Critical": 30, "High": 15, "Medium": 5, "Low": 0}
API_LAG_PENALTY = 10  # when the project is more than one release behind current GA


def score_report(
    submitted: SubmittedReport,
    static_findings: list[dict],
    project_api_version: str | None,
) -> tuple[int, str, list[str]]:
    score = 100
    breakdown: list[str] = []
    has_critical = False

    for item in submitted.breaking_issues:
        penalty = BREAKING_PENALTY[item.severity]
        has_critical |= item.severity == "Critical"
        if penalty:
            score -= penalty
            breakdown.append(f"-{penalty} {item.severity}: {item.title}")

    for finding in static_findings:
        penalty = BREAKING_PENALTY.get(finding["severity"], 0)
        has_critical |= finding["severity"] == "Critical"
        if penalty:
            score -= penalty
            breakdown.append(f"-{penalty} {finding['severity']} (static check): {finding['title']}")

    current_api = release_to_api(submitted.current_release)
    if current_api and project_api_version:
        try:
            lag = current_api - int(float(project_api_version))
        except ValueError:
            lag = 0
        if lag > 1:
            score -= API_LAG_PENALTY
            breakdown.append(
                f"-{API_LAG_PENALTY} project API v{project_api_version} is {lag} releases behind "
                f"{submitted.current_release} (v{current_api}.0)"
            )

    score = max(0, min(100, score))
    if has_critical or score < 50:
        status = "Red"
    elif score < 80:
        status = "Amber"
    else:
        status = "Green"
    return score, status, breakdown
