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


def historical_metrics() -> dict[str, dict]:
    """Métricas diárias públicas desde o início da campanha."""
    rows = graph(
        f"{CAMPAIGN_ID}/insights",
        fields="spend,impressions,reach,inline_link_clicks,ctr,cpm,cpc,frequency,actions,video_play_actions",
        date_preset="maximum",
        time_increment="1",
    ).get("data", [])
    return {row["date_start"]: metric_values(row) for row in rows if row.get("date_start")}


def lead_followup_metrics() -> tuple[dict, dict[str, dict]]:
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
    empty = {"averageResponseMinutes": None, "respondedLeads": 0, "appointments": 0, "pastAppointments": 0, "attendances": 0, "sales": 0}
    if not rows:
        return empty, {}
    headers = rows[0]
    required = {name: headers.index(name) for name in ("created_time", "campaign_id", "Respondido em", "Agendado", "Realizado em", "Aderiu Mentoria em") if name in headers}
    if len(required) != 6:
        return empty, {}
    now = datetime.now(BRT)
    replies: list[tuple[str, float]] = []
    appointments = 0
    past_appointments = 0
    attendances = 0
    sales = 0
    daily: dict[str, dict] = {}

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
        day = converted_at.date().isoformat()
        daily.setdefault(day, {"responseMinutes": [], "respondedLeads": 0, "appointments": 0, "pastAppointments": 0, "attendances": 0, "sales": 0})
        day_metrics = daily[day]
        scheduled_at = short_date(value("Agendado"), converted_at.year)
        if scheduled_at:
            appointments += 1
            day_metrics["appointments"] += 1
            if scheduled_at <= now:
                past_appointments += 1
                day_metrics["pastAppointments"] += 1
                realized_at = short_date(value("Realizado em"), converted_at.year)
                if realized_at:
                    attendances += 1
                    day_metrics["attendances"] += 1
        if short_date(value("Aderiu Mentoria em"), converted_at.year):
            sales += 1
            day_metrics["sales"] += 1
        replied_at = short_date(value("Respondido em"), converted_at.year)
        if replied_at:
            elapsed = (replied_at - converted_at).total_seconds() / 60
            if 0 <= elapsed and replied_at <= now:
                replies.append((day, elapsed))
    # Os dois maiores tempos de resposta distorcem a média operacional. Eles
    # permanecem na planilha; são excluídos apenas do indicador público.
    outlier_indexes = set(sorted(range(len(replies)), key=lambda index: replies[index][1], reverse=True)[:2])
    minutes: list[float] = []
    for index, (day, elapsed) in enumerate(replies):
        if index in outlier_indexes:
            continue
        minutes.append(elapsed)
        daily[day]["responseMinutes"].append(elapsed)
        daily[day]["respondedLeads"] += 1
    summary = {
        "averageResponseMinutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
        "respondedLeads": len(minutes),
        "appointments": appointments,
        "pastAppointments": past_appointments,
        "attendances": attendances,
        "sales": sales,
    }
    public_daily = {
        day: {
            "averageResponseMinutes": round(sum(values["responseMinutes"]) / len(values["responseMinutes"]), 1) if values["responseMinutes"] else None,
            "respondedLeads": values["respondedLeads"],
            "appointments": values["appointments"],
            "pastAppointments": values["pastAppointments"],
            "attendances": values["attendances"],
            "sales": values["sales"],
        }
        for day, values in daily.items()
    }
    return summary, public_daily


def main() -> None:
    campaign = graph(CAMPAIGN_ID, fields="name,status,daily_budget")
    campaign_metrics = metric_values(insights(CAMPAIGN_ID, lifetime=True))
    daily_campaign_metrics = metric_values(insights(CAMPAIGN_ID))
    weekly_frequency = round(number(insights(CAMPAIGN_ID, days=7).get("frequency")), 2)
    followup, followup_daily = lead_followup_metrics()
    history = historical_metrics()
    for day, values in followup_daily.items():
        history.setdefault(day, metric_values({}))
        history[day].update(values)
    for values in history.values():
        values.setdefault("averageResponseMinutes", None)
        values.setdefault("respondedLeads", 0)
        values.setdefault("appointments", 0)
        values.setdefault("pastAppointments", 0)
        values.setdefault("attendances", 0)
        values.setdefault("sales", 0)
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
        "history": [{"dateBRT": day, **values} for day, values in sorted(history.items())],
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
