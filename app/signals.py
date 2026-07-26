"""
Движок правил "Сигнали" (Фаза 4) — сам проганяє дані по кабінету/органіці і показує готові
алерти з причиною і дією, щоб власник не мусив вручну моніторити цифри. Дані беруться з тих
самих джерел, що app/companion.py (медіа-кеш, категорії, рекламна структура/insights, статус
токена) — але тут потрібні СИРІ структуровані числа для порогів, а не текстовий зріз для LLM.

Чесність понад усе (як і в решті проєкту): бракує даних/подій/днів — сигналу немає, а не
вигаданий висновок на шумі. Кожне правило явно перевіряє свій мінімальний поріг вибірки.
"""
import logging
from datetime import datetime, timezone
from statistics import median

from app.ads_api import (
    FATIGUE_FREQUENCY_THRESHOLD,
    AdsAPIError,
    build_time_range_params,
    extract_result_metric,
    fetch_entity_metrics,
    fetch_learning_stage,
    fetch_structure,
    fetch_timeseries_by_adset,
)
from app.ads_kpi import load_kpi_targets
from app.categories import load_categories
from app.project_store import get_effective_config
from app.i18n import t
from app.routes.metrics import load_cache
from app.signals_state import load_state
from app.token_refresh import check_token_status

logger = logging.getLogger("reels_dashboard")

# Загальний "не спамити шумом" поріг для рекламних правил: 50+ подій і 4+ дні спостереження
# (TZ п. "пороги реалістичні, НЕ алерти на шумі"). Для органіки в кожного правила свій поріг —
# вони прив'язані не до "подій", а до кількості вже дозрілих рілсів/днів паузи.
SIGNAL_MIN_EVENTS = 50
SIGNAL_MIN_DAYS = 4
ADS_WINDOW_FATIGUE = "last_14d"
ADS_WINDOW_EXPENSIVE = "last_14d"
ADS_WINDOW_LEARNING = "last_7d"

FATIGUE_CTR_DROP_FROM_START_PCT = 30
EXPENSIVE_MULTIPLIER = 2.0
LEARNING_EXIT_MIN_EVENTS = 50
TOKEN_EXPIRING_DAYS = 7
TOKEN_EXPIRING_RED_DAYS = 3

REEL_MATURITY_DAYS = 3          # молодше — охоплення ще накопичується, порівнювати нечесно
REEL_DROP_MIN_BASELINE = 5      # менше дозрілих рілсів для медіани — вибірка занадто мала
REEL_DROP_RATIO = 0.5           # < 50% медіани
REEL_WIN_FRESH_DAYS = 2         # проксі "перша доба" — власної погодинної історії по посту нема
REEL_WIN_RATIO = 1.8            # > 180% медіани
POSTING_PAUSE_DAYS = 3
CATEGORY_IMBALANCE_WINDOW_DAYS = 14
CATEGORY_IMBALANCE_MIN_POSTS = 5
CATEGORY_IMBALANCE_SHARE = 0.15
# Рубрика "особистість" — довільна користувацька назва (auto/manual), шукаємо по підрядку
# українською і російською, бо мова інтерфейсу/рубрик не фіксована.
PERSONALITY_NAME_HINTS = ("особист", "личност", "особов")


def _signal(signal_id, group, rule, level, title, reason, action, tab):
    return {
        "id": signal_id,
        "group": group,
        "rule": rule,
        "level": level,
        "title": title,
        "reason": reason,
        "action": action,
        "tab": tab,
    }


def _parse_dt(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso_week_key(dt=None) -> str:
    dt = dt or datetime.now(timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _active_campaigns(campaigns: list) -> list:
    return [c for c in campaigns if c.get("effective_status") == "ACTIVE"]


# === Реклама ================================================================

def _rule_creative_fatigue(token: str, campaigns: list) -> list:
    signals = []
    window = build_time_range_params(ADS_WINDOW_FATIGUE)
    for campaign in _active_campaigns(campaigns):
        objective = campaign.get("objective")
        for adset in campaign.get("_adsets", []):
            if adset.get("effective_status") != "ACTIVE":
                continue
            active_ads = {a["id"]: a.get("name") or a["id"] for a in adset.get("_ads", []) if a.get("effective_status") == "ACTIVE"}
            if not active_ads:
                continue
            try:
                daily_by_ad = fetch_timeseries_by_adset(token, adset["id"], objective, window, time_increment=1)
            except AdsAPIError:
                continue

            for ad_id, ad_name in active_ads.items():
                rows = daily_by_ad.get(ad_id) or []
                valid_days = [
                    r for r in rows
                    if (r["metrics"].get("impressions") or 0) >= SIGNAL_MIN_EVENTS
                    and r["metrics"].get("ctr") is not None
                    and r["metrics"].get("frequency") is not None
                ]
                if len(valid_days) < SIGNAL_MIN_DAYS:
                    continue

                baseline_ctr = valid_days[0]["metrics"]["ctr"]
                latest = valid_days[-1]
                if not baseline_ctr:
                    continue
                ctr_drop_pct = round((1 - latest["metrics"]["ctr"] / baseline_ctr) * 100)
                freq = latest["metrics"]["frequency"]
                if freq <= FATIGUE_FREQUENCY_THRESHOLD or ctr_drop_pct < FATIGUE_CTR_DROP_FROM_START_PCT:
                    continue

                signals.append(_signal(
                    signal_id=f"fatigue:{ad_id}:{valid_days[0]['date_start']}",
                    group="ads", rule="creative_fatigue", level="yellow",
                    title=t("signals.ads.fatigue.title", name=ad_name),
                    reason=t("signals.ads.fatigue.reason", freq=round(freq, 2), drop=ctr_drop_pct, days=len(valid_days)),
                    action=t("signals.ads.fatigue.action"),
                    tab="ads",
                ))
    return signals


def _rule_expensive_campaign(token: str, campaigns: list, kpi_targets: dict) -> list:
    signals = []
    window = build_time_range_params(ADS_WINDOW_EXPENSIVE)
    now = datetime.now(timezone.utc)
    for campaign in _active_campaigns(campaigns):
        objective = campaign.get("objective")
        targets = kpi_targets.get(objective) or {}
        # target_cost_per_result — узагальнена ціль; target_cpl — запасний варіант для Leads,
        # якщо користувач заповнив тільки його (див. форму KPI на вкладці "Реклама").
        target_cost = targets.get("target_cost_per_result") or targets.get("target_cpl")
        if not target_cost:
            continue

        start = _parse_dt(campaign.get("start_time"))
        if not start or (now - start).days < SIGNAL_MIN_DAYS:
            continue

        row, err = fetch_entity_metrics(token, campaign["id"], window)
        if err or not row:
            continue
        result = extract_result_metric(objective, row)
        if result["value"] is None or result["value"] < SIGNAL_MIN_EVENTS:
            continue
        cost = result["cost_per_result"]
        if cost is None or cost <= target_cost * EXPENSIVE_MULTIPLIER:
            continue

        signals.append(_signal(
            signal_id=f"expensive:{campaign['id']}:{_iso_week_key(now)}",
            group="ads", rule="expensive_campaign", level="red",
            title=t("signals.ads.expensive.title", name=campaign.get("name", "")),
            reason=t("signals.ads.expensive.reason", cost=round(cost, 2), target=round(target_cost, 2), events=int(result["value"])),
            action=t("signals.ads.expensive.action"),
            tab="ads",
        ))
    return signals


def _rule_learning_exit(token: str, campaigns: list) -> list:
    signals = []
    window = build_time_range_params(ADS_WINDOW_LEARNING)
    now = datetime.now(timezone.utc)
    for campaign in _active_campaigns(campaigns):
        objective = campaign.get("objective")
        for adset in campaign.get("_adsets", []):
            if adset.get("effective_status") != "ACTIVE":
                continue
            stage = fetch_learning_stage(token, adset["id"])
            if stage != "SUCCESS":
                continue

            row, err = fetch_entity_metrics(token, adset["id"], window)
            if err or not row:
                continue
            result = extract_result_metric(objective, row)
            if result["value"] is None or result["value"] < LEARNING_EXIT_MIN_EVENTS:
                continue

            signals.append(_signal(
                signal_id=f"learning_exit:{adset['id']}:{_iso_week_key(now)}",
                group="ads", rule="learning_exit", level="green",
                title=t("signals.ads.learning_exit.title", name=adset.get("name", "")),
                reason=t("signals.ads.learning_exit.reason", events=int(result["value"]), label=result["label"] or ""),
                action=t("signals.ads.learning_exit.action"),
                tab="ads",
            ))
    return signals


def _rule_token_expiring(token: str) -> list:
    status = check_token_status(token)
    expires_at = status.get("expires_at")
    if not expires_at:
        return []
    days_left = (expires_at - datetime.now(timezone.utc)).days
    if days_left >= TOKEN_EXPIRING_DAYS:
        return []

    level = "red" if days_left < TOKEN_EXPIRING_RED_DAYS else "yellow"
    reason = t("signals.ads.token.reason_expired") if days_left < 0 else t("signals.ads.token.reason", days=days_left)
    return [_signal(
        signal_id=f"token_expiring:{expires_at.isoformat()}",
        group="ads", rule="token_expiring", level=level,
        title=t("signals.ads.token.title"),
        reason=reason,
        action=t("signals.ads.token.action"),
        tab="settings",
    )]


# === Органіка ================================================================

def _organic_posts(posts: list) -> list:
    return [p for p in posts if not p.get("is_ad") and p.get("timestamp")]


def _rule_reel_drop(posts: list) -> list:
    now = datetime.now(timezone.utc)
    organic = [p for p in _organic_posts(posts) if p.get("insights_status") == "ok"]
    matured = sorted(
        (p for p in organic if (now - _parse_dt(p["timestamp"])).days >= REEL_MATURITY_DAYS),
        key=lambda p: p["timestamp"], reverse=True,
    )
    if len(matured) <= REEL_DROP_MIN_BASELINE:
        return []

    candidate, baseline = matured[0], matured[1:11]
    reach_pool = [p["reach"] for p in baseline if p.get("reach") is not None]
    skip_pool = [p["skip_rate"] for p in baseline if p.get("skip_rate") is not None]

    reason = None
    if candidate.get("reach") is not None and len(reach_pool) >= REEL_DROP_MIN_BASELINE:
        med_reach = median(reach_pool)
        if med_reach and candidate["reach"] < med_reach * REEL_DROP_RATIO:
            reason = t("signals.organic.drop.reason_reach", reach=int(candidate["reach"]), median=int(med_reach))
    if reason is None and candidate.get("skip_rate") is not None and len(skip_pool) >= REEL_DROP_MIN_BASELINE:
        med_skip = median(skip_pool)
        # Власної метрики "досмотру" нема — reels_skip_rate обернено пов'язаний з нею, тож
        # "досмотр впав вдвічі" наближено читаємо як "skip rate виріс приблизно вдвічі".
        if med_skip and candidate["skip_rate"] > med_skip / REEL_DROP_RATIO:
            reason = t("signals.organic.drop.reason_skip", skip=round(candidate["skip_rate"], 1), median=round(med_skip, 1))

    if not reason:
        return []
    return [_signal(
        signal_id=f"reel_drop:{candidate['id']}",
        group="organic", rule="reel_drop", level="yellow",
        title=t("signals.organic.drop.title", caption=(candidate.get("caption") or "").strip()[:60] or t("common.no_data")),
        reason=reason,
        action=t("signals.organic.drop.action"),
        tab="metrics",
    )]


def _rule_posting_pause(posts: list) -> list:
    organic = _organic_posts(posts)
    if not organic:
        return []
    latest = max(organic, key=lambda p: p["timestamp"])
    last_dt = _parse_dt(latest["timestamp"])
    if not last_dt:
        return []
    days_since = (datetime.now(timezone.utc) - last_dt).days
    if days_since <= POSTING_PAUSE_DAYS:
        return []

    return [_signal(
        signal_id=f"posting_pause:{latest['id']}",
        group="organic", rule="posting_pause", level="yellow",
        title=t("signals.organic.pause.title", days=days_since),
        reason=t("signals.organic.pause.reason", days=days_since),
        action=t("signals.organic.pause.action"),
        tab="metrics",
    )]


def _rule_reel_win(posts: list) -> list:
    now = datetime.now(timezone.utc)
    organic = [p for p in _organic_posts(posts) if p.get("insights_status") == "ok"]

    def age_days(p):
        return (now - _parse_dt(p["timestamp"])).days

    matured = sorted((p for p in organic if age_days(p) >= REEL_MATURITY_DAYS), key=lambda p: p["timestamp"], reverse=True)
    # Проксі "перша доба": власної погодинної/подобової історії по посту не зберігаємо (медіа-кеш —
    # знімок поточного стану), тому чесно порівнюємо СВІЖІ (ще не "дозрілі") публікації з медіаною
    # вже дозрілих — а не вигадуємо точну цифру "охоплення за перші 24 години".
    fresh = sorted((p for p in organic if age_days(p) < REEL_MATURITY_DAYS and age_days(p) <= REEL_WIN_FRESH_DAYS),
                   key=lambda p: p["timestamp"], reverse=True)
    if len(matured) <= REEL_DROP_MIN_BASELINE or not fresh:
        return []

    baseline = matured[:10]
    reach_pool = [p["reach"] for p in baseline if p.get("reach") is not None]
    er_pool = [p["engagement_rate"] for p in baseline if p.get("engagement_rate") is not None]

    candidate = fresh[0]
    reason = None
    if reach_pool and len(reach_pool) >= REEL_DROP_MIN_BASELINE and candidate.get("reach") is not None:
        med_reach = median(reach_pool)
        if med_reach and candidate["reach"] > med_reach * REEL_WIN_RATIO:
            reason = t("signals.organic.win.reason_reach", reach=int(candidate["reach"]), median=int(med_reach))
    if reason is None and er_pool and len(er_pool) >= REEL_DROP_MIN_BASELINE and candidate.get("engagement_rate") is not None:
        med_er = median(er_pool)
        if med_er and candidate["engagement_rate"] > med_er * REEL_WIN_RATIO:
            reason = t("signals.organic.win.reason_er", er=candidate["engagement_rate"], median=round(med_er, 2))

    if not reason:
        return []
    return [_signal(
        signal_id=f"reel_win:{candidate['id']}",
        group="organic", rule="reel_win", level="green",
        title=t("signals.organic.win.title", caption=(candidate.get("caption") or "").strip()[:60] or t("common.no_data")),
        reason=reason,
        action=t("signals.organic.win.action"),
        tab="metrics",
    )]


def _rule_category_imbalance(posts: list) -> list:
    now = datetime.now(timezone.utc)
    cutoff_days = CATEGORY_IMBALANCE_WINDOW_DAYS
    recent = [p for p in _organic_posts(posts) if (now - _parse_dt(p["timestamp"])).days <= cutoff_days]
    if len(recent) < CATEGORY_IMBALANCE_MIN_POSTS:
        return []

    data = load_categories()
    personality_cat = next(
        (c for c in data["categories"] if any(hint in c["name"].lower() for hint in PERSONALITY_NAME_HINTS)),
        None,
    )
    if not personality_cat:
        return []

    assignments = data["assignments"]
    count = sum(1 for p in recent if assignments.get(p["id"]) == personality_cat["id"])
    share = count / len(recent)
    if share >= CATEGORY_IMBALANCE_SHARE:
        return []

    return [_signal(
        signal_id=f"category_imbalance:{personality_cat['id']}:{_iso_week_key(now)}",
        group="organic", rule="category_imbalance", level="yellow",
        title=t("signals.organic.imbalance.title", name=personality_cat["name"]),
        reason=t("signals.organic.imbalance.reason", pct=round(share * 100), count=count, total=len(recent), days=cutoff_days),
        action=t("signals.organic.imbalance.action"),
        tab="categories",
    )]


# === Оркестрація ==============================================================

_LEVEL_ORDER = {"red": 0, "yellow": 1, "green": 2}


def evaluate_signals() -> list:
    """Проганяє всі правила по свіжих даних і мержить збережений стан (відхилено/виконано).
    Кожна група правил падає незалежно (немає токена/кабінету/мало даних) — решта сигналів
    все одно рахується, вкладку/блок ніколи не роняємо через одне джерело даних."""
    cfg = get_effective_config()
    signals = []

    try:
        posts = (load_cache() or {}).get("posts") or []
    except Exception:
        logger.exception("Сигнали: не вдалося прочитати media_cache.json")
        posts = []

    for rule_fn in (_rule_reel_drop, _rule_posting_pause, _rule_reel_win, _rule_category_imbalance):
        try:
            signals.extend(rule_fn(posts))
        except Exception:
            logger.exception("Сигнали: правило %s впало", rule_fn.__name__)

    token = cfg.get("ig_access_token")
    account_id = cfg.get("ads_account_id")

    if token:
        try:
            signals.extend(_rule_token_expiring(token))
        except Exception:
            logger.exception("Сигнали: перевірка токена впала")

    if token and account_id:
        try:
            campaigns = fetch_structure(token, account_id)
        except AdsAPIError:
            campaigns = None
        if campaigns is not None:
            kpi_targets = load_kpi_targets()
            for rule_fn, args in (
                (_rule_creative_fatigue, (token, campaigns)),
                (_rule_expensive_campaign, (token, campaigns, kpi_targets)),
                (_rule_learning_exit, (token, campaigns)),
            ):
                try:
                    signals.extend(rule_fn(*args))
                except AdsAPIError:
                    continue

    state = load_state()
    for s in signals:
        saved = state.get(s["id"])
        s["status"] = saved["status"] if saved else "new"

    signals.sort(key=lambda s: (s["status"] != "new", _LEVEL_ORDER.get(s["level"], 3)))
    return signals
