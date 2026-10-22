"""API schemas for read-only Email report snapshots."""

from pydantic import BaseModel


class EmailReportMetricResponse(BaseModel):
    metric_id: str
    display_name: str
    current_status: str
    current_value: str | None
    baseline_status: str
    baseline_value: str | None
    delta: str | None
    change_rate: str | None
    current_snapshot_id: str | None


class EmailReportIssueResponse(BaseModel):
    code: str
    severity: str
    detail: str
    source_ref: str | None


class EmailReportSummaryResponse(BaseModel):
    report_id: str
    source_run_id: str
    report_type: str
    brand_id: str
    account_id: str
    subject_id: str
    status: str
    metric_version: str
    created_at: str
    metrics: list[EmailReportMetricResponse]
    issues: list[EmailReportIssueResponse]


class EmailReportListResponse(BaseModel):
    items: list[EmailReportSummaryResponse]
    total: int
