#!/usr/bin/env python3
"""Atualiza o snapshot do MetaAds ROI a partir das abas MetaAds."""
from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"
GOG = "/data/.openclaw/bin/gog"
ACCOUNT = "agente.drahelen@gmail.com"
SOURCES = {
    "laserterapia": {
        "name": "Laserterapia",
        "short": "Laser",
        "color": "#2563eb",
        "note": "Campanhas LT Dentistas identificadas com [Laser]",
        "sheet_id": "1AxPKOdZEDm16o3_QB-oOIod-G38iLNI5RFnXp4TLFN0",
        "has_header": True,
        "category": "laser",
    },
    "terapeutica": {
        "name": "Terapêutica",
        "short": "Terap",
        "color": "#8b5cf6",
        "note": "Campanhas LT Dentistas identificadas com [Terap]",
        "sheet_id": "1AxPKOdZEDm16o3_QB-oOIod-G38iLNI5RFnXp4TLFN0",
        "has_header": True,
        "category": "terap",
    },
    "planilha": {
        "name": "Planilha",
        "short": "Planilha",
        "color": "#f59e0b",
        "note": "Campanhas LT Dentistas identificadas com [Planilha]",
        "sheet_id": "1AxPKOdZEDm16o3_QB-oOIod-G38iLNI5RFnXp4TLFN0",
        "has_header": True,
        "category": "planilha",
    },
    "primeiros-dentinhos": {
        "name": "Primeiros Dentinhos",
        "short": "1osDent",
        "color": "#ec4899",
        "note": "Conta act_1552127232446226; campanhas com [LT] + [1osDent]",
        "sheet_id": "1fDbt8wRKLoVWQg2514pOYTuryAVgZETd_sW3nkIke-s",
        "has_header": False,
    },
}
FIELDS = ["date", "account", "account_id", "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name", "spend", "currency", "impressions", "clicks", "ctr", "cpc", "cpm", "leads_meta", "landing_views", "content_views", "checkouts_meta", "add_payment_info_meta", "purchases_meta", "value_meta"]


def values(sheet_id: str) -> list[list[str]]:
    out = subprocess.check_output([GOG, "-a", ACCOUNT, "sheets", "get", sheet_id, "MetaAds!A:X", "--json", "--results-only"], text=True)
    return json.loads(out)


def number(value: str) -> float:
    return float(str(value or "0").replace(".", "").replace(",", "."))


def daily(rows: list[list[str]], has_header: bool, category: str | None = None) -> dict[str, dict]:
    data = defaultdict(lambda: defaultdict(float))
    for row in rows[1 if has_header else 0:]:
        if not row or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row[0])):
            continue
        record = dict(zip(FIELDS, row))
        if category and f"[{category}]" not in record.get("campaign_name", "").lower():
            continue
        day = data[record["date"]]
        day["date"] = record["date"]
        day["currency"] = record.get("currency") or "BRL"
        for name in ("spend", "impressions", "clicks", "leads_meta", "landing_views", "content_views", "checkouts_meta", "add_payment_info_meta", "purchases_meta", "value_meta"):
            day[name] += number(record.get(name, "0"))
    for day in data.values():
        day["ctr"] = (day["clicks"] / day["impressions"] * 100) if day["impressions"] else 0
        day["cpc"] = day["spend"] / day["clicks"] if day["clicks"] else 0
        day["cpm"] = (day["spend"] / day["impressions"] * 1000) if day["impressions"] else 0
        for key, value in list(day.items()):
            if isinstance(value, float):
                day[key] = round(value, 2)
    return data


def main() -> None:
    text = HTML.read_text(encoding="utf-8")
    match = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', text, re.S)
    if not match:
        raise RuntimeError("Dados embutidos não encontrados")
    payload = json.loads(match.group(1))
    existing_projects = {project["key"]: project for project in payload["projects"]}
    projects = []
    report = {}
    sheets = {}
    for key, source in SOURCES.items():
        sheet_id = source["sheet_id"]
        if sheet_id not in sheets:
            sheets[sheet_id] = values(sheet_id)
        fresh = daily(sheets[sheet_id], source["has_header"], source.get("category"))
        previous = existing_projects.get(key, {})
        existing = {row["date"]: row for row in previous.get("rows", [])}
        for date, row in fresh.items():
            # Métricas da Meta são atualizadas; Voomp é preservado até existir
            # uma fonte própria dessa plataforma.
            existing[date] = {**existing.get(date, {}), **row}
            existing[date].setdefault("purchases_voomp", 0)
            existing[date].setdefault("value_voomp", 0)
        projects.append({
            "key": key,
            "name": source["name"],
            "short": source["short"],
            "color": source["color"],
            "note": source["note"],
            "rows": [existing[d] for d in sorted(existing)],
        })
        report[key] = {"days_updated": len(fresh), "last_date": max(fresh) if fresh else None}
    payload["projects"] = projects
    payload["generatedAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output = json.dumps(payload, ensure_ascii=False)
    HTML.write_text(text[:match.start(1)] + output + text[match.end(1):], encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
