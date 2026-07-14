"""Relatórios diários baseados somente no estado persistido."""

from __future__ import annotations

from datetime import date

from .db import Database


def build_daily_report(db: Database, day: date, daily_target_min: int = 10) -> str:
    rows = db.applications_for_date(day.isoformat())
    submitted = [row for row in rows if row["status"] == "submitted"]
    blocked = [row for row in rows if row["status"] == "blocked"]
    reviewed = [row for row in rows if row["status"] in ("review", "dry_run")]
    gap = max(0, daily_target_min - len(submitted))
    target_status = "meta atingida; excedentes permitidos" if gap == 0 else f"faltam {gap}"

    lines = [
        f"# Relatório de candidaturas — {day.strftime('%d/%m/%Y')}", "",
        f"**Resumo:** {len(submitted)} candidatura enviada" + ("s" if len(submitted) != 1 else "")
        + f" · {len(blocked)} bloqueada" + ("s" if len(blocked) != 1 else "")
        + f" · {len(reviewed)} em simulação/revisão",
        f"**Meta mínima: {len(submitted)}/{daily_target_min}** · {target_status}", "",
    ]
    for row in rows:
        label = {"submitted": "ENVIADA", "blocked": "BLOQUEADA", "review": "REVISÃO", "dry_run": "SIMULAÇÃO"}.get(row["status"], row["status"].upper())
        lines.extend([
            f"## {label} — {row['title']}",
            f"**Empresa:** {row['company']}",
            f"**Aderência:** {row['fit_score']}/100",
            f"**ATS:** {row.get('ats') or 'não identificado'}",
            f"**Link:** {row['source_url']}", "",
        ])
    if not rows:
        lines.append("Nenhuma candidatura processada neste dia.")
    lines.extend([
        "---", "",
        "Aderência é um score explicável de compatibilidade, não uma probabilidade de contratação. Chance real depende também de concorrência, triagem e entrevista.",
    ])
    return "\n".join(lines)
