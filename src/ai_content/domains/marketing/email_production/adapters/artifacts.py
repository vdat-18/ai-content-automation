"""Machine-readable records and safe HTML previews for Email production."""

from __future__ import annotations

import html
import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import EmailPackage, EmailProductionJob
from .serialization import job_to_dict


def _render_preview(package: EmailPackage) -> str:
    sections = []
    for section in package.sections:
        cta = ""
        if section.cta_label and section.destination_url:
            cta = (
                '<p><a class="cta" href="'
                + html.escape(section.destination_url, quote=True)
                + '">'
                + html.escape(section.cta_label)
                + "</a></p>"
            )
        sections.append(
            '<section><p class="design">'
            + html.escape(section.design_note)
            + "</p><h2>"
            + html.escape(section.heading)
            + "</h2><p>"
            + html.escape(section.body)
            + "</p>"
            + cta
            + "</section>"
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title><style>
body{{margin:0;background:#eee9df;color:#24231f;font:16px/1.55 Georgia,serif}}
main{{max-width:680px;margin:24px auto;background:#fff;padding:44px}}
.preview,.design{{color:#716c61;font:13px/1.4 Calibri,sans-serif}}
section{{border-top:1px solid #ddd5c8;padding:28px 0}}h1,h2{{font-weight:500}}
.cta{{display:inline-block;background:#26372e;color:#fff;padding:12px 20px;text-decoration:none}}
@media(max-width:720px){{main{{margin:0;padding:24px}}}}
</style></head><body><main><p class="preview">{preview}</p><h1>{subject}</h1>{sections}</main></body></html>
""".format(
        title=html.escape(package.campaign_name),
        preview=html.escape(package.preview_text),
        subject=html.escape(package.subject_variants[0]),
        sections="".join(sections),
    )


def write_email_production_artifacts(store: ArtifactStore, job: EmailProductionJob) -> Path:
    base = ("email-production", job.source_run_id)
    manifest = store.write_text(
        json.dumps(job_to_dict(job), ensure_ascii=False, indent=2),
        *base,
        "manifest.json",
    )
    store.write_text(
        json.dumps(job_to_dict(job)["context"], ensure_ascii=False, indent=2),
        *base,
        "context_snapshot.json",
    )
    for version in job.versions:
        version_parts = (*base, "versions", f"v{version.version_number}")
        payload = next(
            item
            for item in job_to_dict(job)["versions"]
            if item["version_id"] == version.version_id
        )
        store.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            *version_parts,
            "email_package.json",
        )
        store.write_text(_render_preview(version.package), *version_parts, "preview.html")
    if job.preflight is not None:
        store.write_text(
            json.dumps(
                {
                    "run_id": job.preflight.run_id,
                    "evaluation_id": job.preflight.evaluation_id,
                    "email_version_id": job.preflight.email_version_id,
                    "classification": job.preflight.classification,
                    "allowed_for_approval": job.preflight.allowed_for_approval,
                    "warnings": list(job.preflight.warnings),
                },
                ensure_ascii=False,
                indent=2,
            ),
            *base,
            "preflight_reference.json",
        )
    if job.handoff_preview is not None:
        store.write_text(
            json.dumps(job_to_dict(job)["handoff_preview"], ensure_ascii=False, indent=2),
            *base,
            "handoff",
            "klaviyo_draft_preview.json",
        )
    return manifest


__all__ = ["write_email_production_artifacts"]
