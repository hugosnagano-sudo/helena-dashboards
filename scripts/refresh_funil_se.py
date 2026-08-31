#!/usr/bin/env python3
"""Gera o snapshot público (sem dados pessoais) do dashboard Funil SE."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "funil-se-data.json"
CAMPAIGN_ID = "120252209847160663"
API_VERSION = "v22.0"
SHEET_ID = "1-GcIIV5mq3nu2OVs0xNMN17m5093UtgV1wJqQ_Xzdss"
GOG = "/data/.openclaw/bin/gog"
GOG_HOME = "/data/.openclaw/gog"
GOG_ACCOUNT = "agente.drahelen@gmail.com"
BRT = ZoneInfo("America/Sao_Paulo")


def graph(path: str, **params: str) -> dict:
    token = os.environ.get("META_ADS_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("META_ADS_ACCESS_TOKEN não configurado")
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


def date_range(days: int = 1) -> str:
    day = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
    start = (datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=days - 1)).isoformat()
    return json.dumps({"since": start, "until": day})


def insights(object_id: str, days: int | None = None, lifetime: bool = False) -> dict:
    params = {"fields": "spend,impressions,reach,inline_link_clicks,ctr,cpm,cpc,frequency,actions,video_play_actions"}
    if lifetime:
        params["date_preset"] = "maximum"
    else:
        params["time_range"] = date_range(days or 1)
    rows = graph(f"{object_id}/insights", **params).get("data", [])
    return rows[0] if rows else {}


def metric_values(metrics: dict) -> dict:
    spend = round(number(metrics.get("spend")), 2)
    native_leads = leads(metrics.get("actions", []))
    return {
        "spend": spend,
        "impressions": round(number(metrics.get("impressions"))),
        "reach": round(number(metrics.get("reach"))),
        "linkClicks": round(number(metrics.get("inline_link_clicks"))),
        "ctr": round(number(metrics.get("ctr")), 2),
        "nativeLeads": native_leads,
        "cpl": round(spend / native_leads, 2) if native_leads else 0,
        "cpm": round(number(metrics.get("cpm")), 2),
        "cpc": round(number(metrics.get("cpc")), 2),
        "frequency": round(number(metrics.get("frequency")), 2),
        "hookRate": round(100 * sum(number(item.get("value")) for item in metrics.get("video_play_actions", []) if item.get("action_type") == "video_view") / number(metrics.get("impressions")), 2) if number(metrics.get("impressions")) else 0,
    }


def lead_followup_metrics() -> dict:
    """Métricas de resposta/agendamento da Página1, sem expor leads."""
    environment = {**os.environ, "GOG_HOME": GOG_HOME}
    raw = subprocess.check_output(
        # O gog omite a última coluna de intervalos abertos; usar uma faixa com
        # colunas de folga mantém "Aderiu Mentoria em" (coluna V) disponível.
        [GOG, "-a", GOG_ACCOUNT, "sheets", "get", SHEET_ID, "Página1!A:Z", "--json", "--results-only"],
        text=True,
        env=environment,
    )
    rows = json.loads(raw)
    if not rows:
        return {"averageResponseMinutes": None, "respondedLeads": 0, "appointments": 0, "pastAppointments": 0, "attendances": 0, "sales": 0}
    headers = rows[0]
    required = {name: headers.index(name) for name in ("created_time", "campaign_id", "Respondido em", "Agendado", "Realizado em", "Aderiu Mentoria em") if name in headers}
    if len(required) != 6:
        return {"averageResponseMinutes": None, "respondedLeads": 0, "appointments": 0, "pastAppointments": 0, "attendances": 0, "sales": 0}
    now = datetime.now(BRT)
    minutes: list[float] = []
    appointments = 0
    past_appointments = 0
    attendances = 0
    sales = 0

    def short_date(raw: str, year: int) -> datetime | None:
        for pattern, needs_year in (("%d/%m %H:%M", True), ("%d/%m/%Y %H:%M", False), ("%d/%m/%y %H:%M", False), ("%d/%m", True), ("%d/%m/%Y", False), ("%d/%m/%y", False)):
            try:
                parsed = datetime.strptime(f"{raw} {year}" if needs_year else raw, f"{pattern} %Y" if needs_year else pattern)
                return parsed.replace(tzinfo=BRT)
            except ValueError:
                continue
        return None
    for values in rows[1:]:
        def value(name: str) -> str:
            index = required[name]
            return str(values[index]).strip() if index < len(values) else ""
        if value("campaign_id").removeprefix("c:") != CAMPAIGN_ID:
            continue
        try:
            converted_at = datetime.fromisoformat(value("created_time")).astimezone(BRT)
        except ValueError:
            continue
        scheduled_at = short_date(value("Agendado"), converted_at.year)
        if scheduled_at:
            appointments += 1
            if scheduled_at <= now:
                past_appointments += 1
                realized_at = short_date(value("Realizado em"), converted_at.year)
                if realized_at:
                    attendances += 1
        if short_date(value("Aderiu Mentoria em"), converted_at.year):
            sales += 1
        replied_at = short_date(value("Respondido em"), converted_at.year)
        if replied_at:
            elapsed = (replied_at - converted_at).total_seconds() / 60
            if 0 <= elapsed and replied_at <= now:
                minutes.append(elapsed)
    return {
        "averageResponseMinutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
        "respondedLeads": len(minutes),
        "appointments": appointments,
        "pastAppointments": past_appointments,
        "attendances": attendances,
        "sales": sales,
    }


def main() -> None:
    campaign = graph(CAMPAIGN_ID, fields="name,status,daily_budget")
    campaign_metrics = metric_values(insights(CAMPAIGN_ID, lifetime=True))
    daily_campaign_metrics = metric_values(insights(CAMPAIGN_ID))
    weekly_frequency = round(number(insights(CAMPAIGN_ID, days=7).get("frequency")), 2)
    followup = lead_followup_metrics()
    payload = {
        "generatedAt": datetime.now(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
        "campaign": {
            "name": campaign.get("name", "Sessão Estratégica"),
            "status": campaign.get("status", "UNKNOWN"),
            "dailyBudget": round(number(campaign.get("daily_budget")) / 100, 2),
            "weeklyFrequency": weekly_frequency,
            **followup,
            **campaign_metrics,
        },
        "adsets": [],
        "daily": {
            "dateBRT": datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat(),
            "campaign": {
                "name": campaign.get("name", "Sessão Estratégica"),
                "status": campaign.get("status", "UNKNOWN"),
                "dailyBudget": round(number(campaign.get("daily_budget")) / 100, 2),
                **daily_campaign_metrics,
            },
            "adsets": [],
        },
    }
    for adset in graph(f"{CAMPAIGN_ID}/adsets", fields="name").get("data", []):
        name = adset.get("name", "Sem conjunto")
        payload["adsets"].append({"name": name, **metric_values(insights(adset["id"], lifetime=True))})
        payload["daily"]["adsets"].append({"name": name, **metric_values(insights(adset["id"]))})
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
