#!/usr/bin/env python3
"""Gera o snapshot público (sem dados pessoais) do dashboard Funil SE."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "funil-se-data.json"
CAMPAIGN_ID = "120252209847160663"
API_VERSION = "v22.0"


def graph(path: str, **params: str) -> dict:
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("META_ACCESS_TOKEN não configurado")
    query = urlencode({**params, "access_token": token})
    with urlopen(f"https://graph.facebook.com/{API_VERSION}/{path}?{query}", timeout=30) as response:
        return json.load(response)


def number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def leads(actions: list[dict]) -> int:
    direct = [item for item in actions if item.get("action_type") == "lead"]
    source = direct or [item for item in actions if item.get("action_type") == "onsite_conversion.lead_grouped"]
    return round(sum(number(item.get("value")) for item in source))


def today_range() -> str:
    day = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
    return json.dumps({"since": day, "until": day})


def insights(object_id: str) -> dict:
    rows = graph(f"{object_id}/insights", fields="spend,impressions,reach,inline_link_clicks,ctr,actions", time_range=today_range()).get("data", [])
    return rows[0] if rows else {}


def main() -> None:
    campaign = graph(CAMPAIGN_ID, fields="name,status,daily_budget")
    metrics = insights(CAMPAIGN_ID)
    spend = round(number(metrics.get("spend")), 2)
    native_leads = leads(metrics.get("actions", []))
    payload = {
        "generatedAt": datetime.now(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
        "campaign": {
            "name": campaign.get("name", "Sessão Estratégica"),
            "status": campaign.get("status", "UNKNOWN"),
            "dailyBudget": round(number(campaign.get("daily_budget")) / 100, 2),
            "spend": spend,
            "impressions": round(number(metrics.get("impressions"))),
            "reach": round(number(metrics.get("reach"))),
            "linkClicks": round(number(metrics.get("inline_link_clicks"))),
            "ctr": round(number(metrics.get("ctr")), 2),
            "nativeLeads": native_leads,
            "cpl": round(spend / native_leads, 2) if native_leads else 0,
        },
        "adsets": [],
    }
    for adset in graph(f"{CAMPAIGN_ID}/adsets", fields="name").get("data", []):
        item = insights(adset["id"])
        payload["adsets"].append({"name": adset.get("name", "Sem conjunto"), "nativeLeads": leads(item.get("actions", []))})
    previous = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    comparable = {key: value for key, value in payload.items() if key != "generatedAt"}
    old_comparable = {key: value for key, value in previous.items() if key != "generatedAt"}
    if comparable == old_comparable:
        print("unchanged")
        return
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("updated")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"refresh failed: {error}", file=sys.stderr)
        raise
