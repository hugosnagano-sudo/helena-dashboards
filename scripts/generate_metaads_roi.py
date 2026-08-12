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
        "voomp_product": "Laserterapia na Odontopediatria",
    },
    "terapeutica": {
        "name": "Terapêutica",
        "short": "Terap",
        "color": "#8b5cf6",
        "note": "Campanhas LT Dentistas identificadas com [Terap]",
        "sheet_id": "1AxPKOdZEDm16o3_QB-oOIod-G38iLNI5RFnXp4TLFN0",
        "has_header": True,
        "category": "terap",
        "voomp_product": "Terapêutica Medicamentosa em Odontopediatria",
    },
    "planilha": {
        "name": "Planilha",
        "short": "Planilha",
        "color": "#f59e0b",
        "note": "Campanhas LT Dentistas identificadas com [Planilha]",
        "sheet_id": "1AxPKOdZEDm16o3_QB-oOIod-G38iLNI5RFnXp4TLFN0",
        "has_header": True,
        "category": "planilha",
        "voomp_product": "Planilha de controle financeiro e cálculo de hora clínica",
    },
    "primeiros-dentinhos": {
        "name": "Primeiros Dentinhos",
        "short": "1osDent",
        "color": "#ec4899",
        "note": "Conta act_1552127232446226; campanhas com [LT] + [1osDent]",
        "sheet_id": "1fDbt8wRKLoVWQg2514pOYTuryAVgZETd_sW3nkIke-s",
        "has_header": False,
        "voomp_product": None,
    },
}
VOOMP_SHEETS = {
    "lt": "1JQPLF1diqFFvDENstwsa6NUdVoJOC5phSSrbYe1qZiI",
    "primeiros-dentinhos": "1pUaUDlMpkki6_ribAaif2f6h3QRBZNq9fbymMBalKu8",
}
FIELDS = ["date", "account", "account_id", "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name", "spend", "currency", "impressions", "clicks", "ctr", "cpc", "cpm", "leads_meta", "landing_views", "content_views", "checkouts_meta", "add_payment_info_meta", "purchases_meta", "value_meta"]


def values(sheet_id: str, range_name: str = "MetaAds!A:X") -> list[list[str]]:
    out = subprocess.check_output([GOG, "-a", ACCOUNT, "sheets", "get", sheet_id, range_name, "--json", "--results-only"], text=True)
    return json.loads(out)


def number(value: str) -> float:
    return float(str(value or "0").replace(".", "").replace(",", "."))


def voomp_daily(rows: list[list[str]], product_name: str | None = None) -> dict[str, dict]:
    """Agrupa vendas pagas por data de confirmação e saldo real ao vendedor."""
    if not rows:
        return {}
    header = {name: index for index, name in enumerate(rows[0])}
    required = ("sale.id", "sale.status", "sale.paid_at", "sale.seller_balance", "product.name")
    missing = [name for name in required if name not in header]
    if missing:
        raise RuntimeError(f"Colunas Voomp ausentes: {', '.join(missing)}")
    data = defaultdict(lambda: {"purchases_voomp": 0, "value_voomp": 0.0})
    seen_sales = set()
    for row in rows[1:]:
        def value(name: str) -> str:
            index = header[name]
            return str(row[index]) if index < len(row) else ""
        sale_id = value("sale.id")
        if not sale_id or sale_id in seen_sales or value("sale.status").lower() != "paid":
            continue
        if product_name and value("product.name") != product_name:
            continue
        paid_at = value("sale.paid_at")
        date = paid_at[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        seen_sales.add(sale_id)
        data[date]["purchases_voomp"] += 1
        data[date]["value_voomp"] += number(value("sale.seller_balance"))
    return {date: {"purchases_voomp": values["purchases_voomp"], "value_voomp": round(values["value_voomp"], 2)}
            for date, values in data.items()}


def daily(rows: list[list[str]], has_header: bool, category: str | None = None) -> tuple[dict[str, dict], list[dict]]:
    data = defaultdict(lambda: defaultdict(float))
    details = []
    for row in rows[1 if has_header else 0:]:
        if not row or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row[0])):
            continue
        record = dict(zip(FIELDS, row))
        if category and f"[{category}]" not in record.get("campaign_name", "").lower():
            continue
        detail = {
            "date": record["date"], "currency": record.get("currency") or "BRL",
            "campaign_id": record.get("campaign_id", ""), "campaign_name": record.get("campaign_name", "Sem campanha"),
            "adset_id": record.get("adset_id", ""), "adset_name": record.get("adset_name", "Sem conjunto de anúncios"),
            "ad_id": record.get("ad_id", ""), "ad_name": record.get("ad_name", "Sem anúncio"),
        }
        for name in ("spend", "impressions", "clicks", "leads_meta", "landing_views", "content_views", "checkouts_meta", "add_payment_info_meta", "purchases_meta", "value_meta"):
            detail[name] = number(record.get(name, "0"))
        details.append(detail)
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
    return data, details


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
    voomp_rows = {
        "lt": values(VOOMP_SHEETS["lt"], "Vendas!A:CO"),
        "primeiros-dentinhos": values(VOOMP_SHEETS["primeiros-dentinhos"], "Vendas!A:CO"),
    }
    voomp = {"primeiros-dentinhos": voomp_daily(voomp_rows["primeiros-dentinhos"])}
    for key, source in SOURCES.items():
        sheet_id = source["sheet_id"]
        if sheet_id not in sheets:
            sheets[sheet_id] = values(sheet_id)
        fresh, details = daily(sheets[sheet_id], source["has_header"], source.get("category"))
        previous = existing_projects.get(key, {})
        existing = {row["date"]: row for row in previous.get("rows", [])}
        product_sales = (voomp["primeiros-dentinhos"] if key == "primeiros-dentinhos"
                         else voomp_daily(voomp_rows["lt"], source.get("voomp_product")))
        all_dates = sorted(set(existing) | set(fresh) | set(product_sales))
        for date in all_dates:
            row = fresh.get(date, existing.get(date, {"date": date, "currency": "BRL"}) )
            existing[date] = {**existing.get(date, {}), **row}
            existing[date].update(product_sales.get(date, {"purchases_voomp": 0, "value_voomp": 0}))
        projects.append({
            "key": key,
            "name": source["name"],
            "short": source["short"],
            "color": source["color"],
            "note": source["note"],
            "rows": [existing[d] for d in sorted(existing)],
            "detailRows": details,
        })
        report[key] = {"days_updated": len(fresh), "last_date": max(fresh) if fresh else None,
                       "voomp_sales": sum(day["purchases_voomp"] for day in product_sales.values())}
    payload["projects"] = projects
    payload["generatedAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output = json.dumps(payload, ensure_ascii=False)
    HTML.write_text(text[:match.start(1)] + output + text[match.end(1):], encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
