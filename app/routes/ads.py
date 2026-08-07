import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from flask import Blueprint, copy_current_request_context, jsonify, request

import anthropic

from app.ads_api import (
    AdsAPIError,
    DEFAULT_PERIOD,
    build_time_range_params,
    campaign_optimization_goal,
    compute_trend,
    compute_video_trend,
    detect_creative_fatigue,
    estimate_period_days,
    extract_result_metric,
    fetch_ad_creative_detail,
    fetch_ad_diagnostics_by_adset,
    fetch_adset_targeting,
    fetch_ads_basic_list,
    fetch_all_breakdowns,
    fetch_breakdown,
    format_breakdown_row,
    fetch_entity_metrics,
    fetch_insights_by_level,
    fetch_learning_stage,
    fetch_single_campaign,
    fetch_structure,
    fetch_timeseries,
    fetch_timeseries_by_adset,
    format_attribution,
    format_creative,
    format_metrics_row,
    format_targeting,
    normalize_account_id,
    objective_label,
    result_explanation,
    to_currency_units,
    verify_ad_account_access,
)
from app.ads_audience import compute_audience_verdict
from app.instagram_api import InstagramAPIError, fetch_follower_demographics
from app.ads_creative_verdict import compute_baseline as compute_creative_baseline, compute_creative_verdict
from app.ads_placement import compute_placement_verdict
from app.ads_kpi import (
    compute_kpi_verdicts,
    delete_kpi_target,
    get_benchmark_hints,
    get_kpi_objectives,
    load_kpi_targets,
    save_kpi_targets as save_kpi_target_for_objective,
)
from app.ads_opus import (
    build_audience_verdict_prompt,
    build_creative_verdict_prompt,
    build_placement_verdict_prompt,
    build_recommendations_prompt,
    call_opus,
    format_organic_audience,
)
from app.i18n import current_lang, t
from app.project_data_store import get_json, set_json
from app.project_store import get_effective_config, get_project, update_active_project, update_project
from app.transcription import load_transcripts

ads_bp = Blueprint("ads", __name__)
logger = logging.getLogger("reels_dashboard")

_ADS_CACHE_KEY = "ads_cache.json"


def load_ads_cache(project_id: str = None) -> dict:
    """Снимок последней структуры кабинета (см. run_ads_sync) — пишется только фоновым
    авто-обновлением (app/scheduler.py) за период DEFAULT_PERIOD, чтобы при открытии вкладки
    «Реклама» сразу было что показать («обновлено N мин назад») без ручного нажатия «Загрузить»
    и без риска, что ручной просмотр другого периода перезатрёт этот снимок."""
    return get_json(_ADS_CACHE_KEY, default={"campaigns": [], "synced_at": None}, project_id=project_id)


def save_ads_cache(data: dict, project_id: str = None):
    set_json(_ADS_CACHE_KEY, data, project_id=project_id)


def _budget_info(node: dict, currency: str) -> dict:
    daily = to_currency_units(node.get("daily_budget"), currency)
    lifetime = to_currency_units(node.get("lifetime_budget"), currency)
    return {
        "daily_budget": daily,
        "lifetime_budget": lifetime,
        "budget_remaining": to_currency_units(node.get("budget_remaining"), currency),
        "has_own_budget": daily is not None or lifetime is not None,
    }


def _empty_metrics_block():
    empty = format_metrics_row({})
    empty["_note"] = t("ads.msg.no_data_for_period")
    return empty


def run_ads_sync(period: str = DEFAULT_PERIOD, date_from: str = None, date_to: str = None, project_id: str = None) -> dict:
    """Тело загрузки структуры рекламного кабинета проекта — общая логика для ручной кнопки
    «Загрузить» (см. get_structure ниже) и фонового авто-обновления (см. app/scheduler.py).
    Возвращает {"error": ...} вместо исключения, как run_metrics_sync в app/routes/metrics.py —
    по той же причине (вызывающий код сам решает, как показать ошибку).

    project_id — явний (планувальник, Этап 2: фоновий синк конкретного проєкту, необов'язково
    активного); None = активний проєкт поточної сесії, як і раніше (ручна кнопка)."""
    cfg = get_effective_config(project_id)
    token = cfg.get("ig_access_token")
    account_id = cfg.get("ads_account_id")

    if not token:
        return {"error": t("ads.msg.no_token")}
    if not account_id:
        return {"error": t("ads.msg.no_account_id")}

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)

        # Пять запросов ниже независимы друг от друга (structure не требует insights и наоборот,
        # три уровня insights читаются напрямую с account_id, а не через дерево campaign->adset->ad) —
        # раньше шли строго по очереди, из-за чего вся структура кабинета грузилась намного
        # дольше органических метрик. Параллелим их через пул потоков.
        with ThreadPoolExecutor(max_workers=5) as pool:
            f_account = pool.submit(copy_current_request_context(verify_ad_account_access), token, account_id)
            f_campaigns = pool.submit(copy_current_request_context(fetch_structure), token, account_id)
            f_campaign_insights = pool.submit(copy_current_request_context(fetch_insights_by_level), token, account_id, "campaign", time_range_params)
            f_adset_insights = pool.submit(copy_current_request_context(fetch_insights_by_level), token, account_id, "adset", time_range_params)
            f_ad_insights = pool.submit(copy_current_request_context(fetch_insights_by_level), token, account_id, "ad", time_range_params)

            account = f_account.result()
            campaigns = f_campaigns.result()
            campaign_insights, campaign_unsupported = f_campaign_insights.result()
            adset_insights, adset_unsupported = f_adset_insights.result()
            ad_insights, ad_unsupported = f_ad_insights.result()

        currency = account.get("currency", "")
        all_kpi_targets = load_kpi_targets(project_id)
    except AdsAPIError as e:
        return {"error": str(e)}

    result_campaigns = []
    for campaign in campaigns:
        objective = campaign.get("objective")
        kpi_targets = all_kpi_targets.get(objective)
        campaign_opt_goal = campaign_optimization_goal(campaign)

        # c_row идёт напрямую из insights?level=campaign (campaign_insights выше) — цельная
        # цифра по кампании от Meta, а не сумма по её adset'ам ниже. Так и должно оставаться:
        # если когда-нибудь захочется считать campaign-тотал сложением adsets_out, это разойдётся
        # с Ads Manager при частично удалённых/архивных adset'ах, которые insights level=campaign
        # всё равно учитывает.
        c_row = campaign_insights.get(campaign["id"])
        c_metrics = format_metrics_row(c_row) if c_row else _empty_metrics_block()
        if campaign_unsupported:
            c_metrics["_unsupported"] = campaign_unsupported
        c_result = extract_result_metric(objective, c_row or {}, campaign_opt_goal)
        c_kpi_verdicts = compute_kpi_verdicts(c_metrics, c_result, kpi_targets)

        adsets_out = []
        for adset in campaign.get("_adsets", []):
            adset_opt_goal = adset.get("optimization_goal")
            a_row = adset_insights.get(adset["id"])
            a_metrics = format_metrics_row(a_row) if a_row else _empty_metrics_block()
            if adset_unsupported:
                a_metrics["_unsupported"] = adset_unsupported
            a_result = extract_result_metric(objective, a_row or {}, adset_opt_goal)
            a_kpi_verdicts = compute_kpi_verdicts(a_metrics, a_result, kpi_targets)

            ads_out = []
            for ad in adset.get("_ads", []):
                ad_row = ad_insights.get(ad["id"])
                ad_metrics = format_metrics_row(ad_row) if ad_row else _empty_metrics_block()
                if ad_unsupported:
                    ad_metrics["_unsupported"] = ad_unsupported
                ad_result = extract_result_metric(objective, ad_row or {}, adset_opt_goal)

                ads_out.append({
                    "id": ad["id"],
                    "name": ad.get("name", ""),
                    "status": ad.get("status"),
                    "effective_status": ad.get("effective_status"),
                    "creative": format_creative(ad.get("creative"), access_token=token),
                    "metrics": ad_metrics,
                    "result": ad_result,
                    "_raw_insights": ad_row,
                })

            adsets_out.append({
                "id": adset["id"],
                "name": adset.get("name", ""),
                "status": adset.get("status"),
                "effective_status": adset.get("effective_status"),
                "budget": _budget_info(adset, currency),
                "bid_amount": to_currency_units(adset.get("bid_amount"), currency),
                "bid_strategy": adset.get("bid_strategy"),
                "billing_event": adset.get("billing_event"),
                "optimization_goal": adset.get("optimization_goal"),
                "start_time": adset.get("start_time"),
                "end_time": adset.get("end_time"),
                "attribution": format_attribution(adset.get("attribution_spec")),
                "targeting": format_targeting(adset.get("targeting"), adset.get("targeting_automation")),
                "metrics": a_metrics,
                "result": a_result,
                "kpi_verdicts": a_kpi_verdicts,
                "_raw_insights": a_row,
                "ads": ads_out,
            })

        budget_info = _budget_info(campaign, currency)
        result_campaigns.append({
            "id": campaign["id"],
            "name": campaign.get("name", ""),
            "objective": objective,
            "objective_label": objective_label(objective),
            "result_explanation": result_explanation(objective, campaign_opt_goal),
            "status": campaign.get("status"),
            "effective_status": campaign.get("effective_status"),
            "buying_type": campaign.get("buying_type"),
            "bid_strategy": campaign.get("bid_strategy"),
            "budget": budget_info,
            "budget_type": "CBO" if budget_info["has_own_budget"] else "ABO",
            "kpi_verdicts": c_kpi_verdicts,
            "start_time": campaign.get("start_time"),
            "stop_time": campaign.get("stop_time"),
            "metrics": c_metrics,
            "result": c_result,
            "_raw_insights": c_row,
            "adsets": adsets_out,
        })

    return {
        "account": account,
        "period": period,
        "date_from": date_from,
        "date_to": date_to,
        "campaigns": result_campaigns,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


@ads_bp.route("/structure", methods=["GET"])
def get_structure():
    period = request.args.get("period", DEFAULT_PERIOD)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    result = run_ads_sync(period, date_from, date_to)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@ads_bp.route("/cached", methods=["GET"])
def get_cached_structure():
    """Последний снимок структуры кабинета, собранный фоновым авто-обновлением
    (см. app/scheduler.py) — вкладке «Реклама» есть что показать сразу при открытии,
    без ожидания клика по «Загрузить»."""
    return jsonify(load_ads_cache())


@ads_bp.route("/test-connection", methods=["POST"])
def test_ads_connection():
    """project_id в тілі — опційний: форма проєкту в Налаштуваннях передає його явно (щоб
    перевіряти/зберігати саме цей проєкт, навіть якщо він не активний зараз); без нього —
    стара поведінка, працює з активним проєктом."""
    body = request.get_json(force=True) or {}
    project_id = body.get("project_id")
    cfg = get_project(project_id) if project_id else get_effective_config()
    cfg = cfg or {}
    token = cfg.get("ig_access_token")
    account_id = body.get("ads_account_id") or cfg.get("ads_account_id")

    if not token:
        return jsonify({"error": t("ads.msg.no_token")}), 400
    if not account_id:
        return jsonify({"error": t("ads.msg.enter_account_id")}), 400

    try:
        account = verify_ad_account_access(token, account_id)
    except AdsAPIError as e:
        return jsonify({"error": str(e)}), 400

    normalized_id = normalize_account_id(account_id)
    if project_id:
        update_project(project_id, {"ads_account_id": normalized_id})
    else:
        update_active_project({"ads_account_id": normalized_id})

    return jsonify(account)


@ads_bp.route("/insights-detail", methods=["GET"])
def get_insights_detail():
    """Этап 4b: разбивки аудитории + динамика по дням для одной кампании/группы."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("ads.msg.no_token")}), 400

    entity_id = request.args.get("entity_id")
    objective = request.args.get("objective")
    # Приходит от фронтенда с уже загруженной структурой кабинета (adset.optimization_goal) —
    # entity_id тут всегда adset.id, лишний запрос к Meta ради этого поля не нужен.
    optimization_goal = request.args.get("optimization_goal")
    if not entity_id:
        return jsonify({"error": t("ads.msg.no_entity_id")}), 400

    period = request.args.get("period", DEFAULT_PERIOD)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)
        breakdowns, unsupported = fetch_all_breakdowns(token, entity_id, objective, time_range_params, optimization_goal)
        daily = fetch_timeseries(token, entity_id, objective, time_range_params, time_increment=1, optimization_goal=optimization_goal)
        trend = compute_trend(daily)
    except AdsAPIError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "breakdowns": breakdowns,
        "unsupported_breakdowns": unsupported,
        "timeseries": daily,
        "trend": trend,
    })


@ads_bp.route("/placement-breakdown", methods=["GET"])
def get_placement_breakdown():
    """Пункт C ТЗ: "в каком плейсменте это объявление реально заходит лучше" — по цифрам
    (цена результата / CTR / CPM в зависимости от того, что вообще доступно для этой цели),
    плюс человеческий вывод от Opus поверх той же раскладки (какой плейсмент дешевле, куда льёт
    бюджет алгоритм и почему, честно про Advantage+ — см. build_placement_verdict_prompt)."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("ads.msg.no_token")}), 400

    ad_id = request.args.get("ad_id")
    if not ad_id:
        return jsonify({"error": t("ads.msg.no_entity_id")}), 400
    objective = request.args.get("objective")
    adset_id = request.args.get("adset_id")
    ad_name = request.args.get("ad_name") or ""

    period = request.args.get("period", DEFAULT_PERIOD)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)
        rows, error = fetch_breakdown(token, ad_id, "platform_position", time_range_params)
    except AdsAPIError as e:
        return jsonify({"error": str(e)}), 400

    if error:
        return jsonify({"error": error}), 400

    # Режим плейсментов (авто/Advantage+ vs ручной) и optimization_goal живут в группе, а не в
    # объявлении — тянем ДО расчёта результата по плейсментам, иначе честный расчёт "результата"
    # (см. OPTIMIZATION_GOAL_RESULT_ACTIONS в ads_api.py) откатится на менее точный objective.
    placement_mode, placement_label, optimization_goal = None, None, None
    if adset_id:
        try:
            adset_data = fetch_adset_targeting(token, adset_id)
            placement_label = format_targeting(adset_data.get("targeting"), adset_data.get("targeting_automation")).get("placement")
            placement_mode = "auto" if placement_label and placement_label.startswith("Авто") else "manual"
            optimization_goal = adset_data.get("optimization_goal")
        except AdsAPIError:
            placement_label = None

    formatted_rows = [format_breakdown_row(row, "platform_position", objective, optimization_goal) for row in rows]
    verdict = compute_placement_verdict(formatted_rows, objective)

    opus_summary, opus_note = None, None
    anthropic_key = cfg.get("anthropic_api_key")
    if not anthropic_key:
        opus_note = t("ads.msg.no_anthropic_key_for_opus")
    elif not formatted_rows:
        opus_note = t("ads.msg.no_data_for_period")
    else:
        try:
            system_prompt, user_message = build_placement_verdict_prompt(
                ad_name,
                placement_label or "невідомо (не передано adset_id)",
                formatted_rows,
                verdict,
                objective_label=objective_label(objective) if objective else None,
                lang=current_lang(),
            )
            opus_summary = call_opus(anthropic_key, system_prompt, user_message, max_tokens=400)
        except anthropic.APIError as e:
            opus_note = t("ads.msg.opus_error", error=e)

    return jsonify({
        "rows": formatted_rows,
        "verdict": verdict,
        "placement_mode": placement_mode,
        "placement_label": placement_label,
        "opus_summary": opus_summary,
        "opus_note": opus_note,
    })


@ads_bp.route("/fatigue", methods=["GET"])
def get_fatigue():
    """Этап 4c: усталость крео по одному объявлению (частота+CTR+CPM, и hook/ThruPlay-тренд)."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("ads.msg.no_token")}), 400

    entity_id = request.args.get("entity_id")
    if not entity_id:
        return jsonify({"error": t("ads.msg.no_entity_id")}), 400
    objective = request.args.get("objective")

    period = request.args.get("period", DEFAULT_PERIOD)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)
        daily = fetch_timeseries(token, entity_id, objective, time_range_params, time_increment=1)
        fatigue = detect_creative_fatigue(daily)
        video_trend = compute_video_trend(daily)
    except AdsAPIError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "fatigue": fatigue,
        "video_trend": video_trend,
        "timeseries": daily,
    })


@ads_bp.route("/creative-verdict", methods=["GET"])
def get_creative_verdict():
    """Вердикт «зайшло/не зайшло» по одному крео — розкладка на хук/текст/CTA/візуал за
    цифрами (порівняння з сусідніми об'явленнями тієї ж групи) + транскрипт, якщо є."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("ads.msg.no_token")}), 400

    ad_id = request.args.get("ad_id")
    adset_id = request.args.get("adset_id")
    if not ad_id or not adset_id:
        return jsonify({"error": t("ads.msg.no_entity_id")}), 400
    objective = request.args.get("objective")

    period = request.args.get("period", DEFAULT_PERIOD)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)

        # Один запрос (level=ad на ноду группы) вместо отдельного /insights на каждое
        # объявление группы — раньше вердикт крео + разбор соседних креативов вместе
        # упирались в лимит запросов Meta на группах с несколькими объявлениями.
        diagnostics_by_ad, diag_error = fetch_ad_diagnostics_by_adset(token, adset_id, objective, time_range_params)
        diag = diagnostics_by_ad.get(ad_id)
        if not diag:
            return jsonify({"error": diag_error or t("ads.msg.diagnostics_unavailable")}), 400

        siblings_basic = fetch_ads_basic_list(token, adset_id)
        sibling_rows = [
            {"id": ad["id"], "metrics": (diagnostics_by_ad.get(ad["id"]) or {}).get("metrics")}
            for ad in siblings_basic
        ]

        creative_detail = fetch_ad_creative_detail(token, ad_id)
    except AdsAPIError as e:
        return jsonify({"error": str(e)}), 400

    baseline = compute_creative_baseline(sibling_rows, exclude_ad_id=ad_id)
    verdict = compute_creative_verdict(diag["metrics"], creative_detail["creative"], diag["rankings"], baseline)

    transcript = None
    media_id = creative_detail.get("source_instagram_media_id")
    if media_id:
        transcript = load_transcripts().get(media_id)

    opus_summary, opus_note = None, None
    anthropic_key = cfg.get("anthropic_api_key")
    if not anthropic_key:
        opus_note = t("ads.msg.no_anthropic_key_for_opus")
    else:
        try:
            ad_name = next((a.get("name", "") for a in siblings_basic if a.get("id") == ad_id), "")
            system_prompt, user_message = build_creative_verdict_prompt(
                ad_name, creative_detail["creative"], verdict, lang=current_lang()
            )
            opus_summary = call_opus(anthropic_key, system_prompt, user_message, max_tokens=400)
        except anthropic.APIError as e:
            opus_note = t("ads.msg.opus_error", error=e)

    return jsonify({
        "creative": creative_detail["creative"],
        "metrics": diag["metrics"],
        "rankings": diag["rankings"],
        "verdict": verdict,
        "source_instagram_media_id": media_id,
        "transcript": transcript,
        "opus_summary": opus_summary,
        "opus_note": opus_note,
    })


@ads_bp.route("/kpi-targets", methods=["GET"])
def get_kpi_targets():
    return jsonify({
        "targets": load_kpi_targets(),
        "objectives": get_kpi_objectives(),
        "benchmarks": get_benchmark_hints(),
    })


@ads_bp.route("/kpi-targets", methods=["POST"])
def post_kpi_targets():
    body = request.get_json(force=True) or {}
    objective = body.get("objective")
    if not objective:
        return jsonify({"error": t("ads.msg.no_objective")}), 400

    saved = save_kpi_target_for_objective(objective, body)
    return jsonify({"objective": objective, "targets": saved})


@ads_bp.route("/kpi-targets/<objective>", methods=["DELETE"])
def remove_kpi_target(objective):
    if not delete_kpi_target(objective):
        return jsonify({"error": t("ads.kpi.msg.not_found")}), 404
    return jsonify({"deleted": True})


def _analyze_adset(
    token: str, adset_id: str, objective: str, time_range_params: dict,
    period_days: int = None, organic_audience: dict = None,
) -> dict:
    """Полный разбор одной группы: настройки, метрики, breakdown'ы, ranking-диагностика по
    объявлениям, learning stage, тренд частоты и алгоритмический вердикт. Общая логика для
    /audience-verdict и /recommendations (4d) — без Opus-вызова, это уровнем выше.

    period_days/organic_audience — защита вердикта от шума на маленькой выборке и сверка
    "дешёвого" сегмента с реальной органической аудиторией (см. app/ads_audience.py)."""
    adset_info = fetch_adset_targeting(token, adset_id)
    raw_targeting = adset_info.get("targeting") or {}
    targeting_display = format_targeting(raw_targeting, adset_info.get("targeting_automation"))
    optimization_goal = adset_info.get("optimization_goal")

    adset_row, _metrics_error = fetch_entity_metrics(token, adset_id, time_range_params)
    adset_metrics = format_metrics_row(adset_row or {})
    adset_result = extract_result_metric(objective, adset_row or {}, optimization_goal)

    breakdowns, unsupported_breakdowns = fetch_all_breakdowns(token, adset_id, objective, time_range_params, optimization_goal)

    ads_basic = fetch_ads_basic_list(token, adset_id)

    # Один запрос на всю группу (level=ad) вместо N параллельных запросов по каждому
    # объявлению — та же диагностика, но без риска упереться в лимит запросов Meta.
    diagnostics_by_ad, diagnostics_error = fetch_ad_diagnostics_by_adset(token, adset_id, objective, time_range_params, optimization_goal)
    ads_diagnostics = []
    for ad in ads_basic:
        entry = {"id": ad["id"], "name": ad.get("name", "")}
        diag = diagnostics_by_ad.get(ad["id"])
        if diag:
            entry.update(diag)
        else:
            entry.update({"metrics": None, "result": None, "rankings": {}, "_error": diagnostics_error or t("ads.msg.diagnostics_unavailable")})
        ads_diagnostics.append(entry)

    learning_stage = fetch_learning_stage(token, adset_id)
    daily = fetch_timeseries(token, adset_id, objective, time_range_params, time_increment=1, optimization_goal=optimization_goal)
    trend = compute_trend(daily)
    frequency_trend = trend.get("frequency") if trend.get("available") else None

    verdict = compute_audience_verdict(
        adset_metrics, adset_result, raw_targeting, breakdowns, ads_diagnostics, learning_stage, frequency_trend,
        period_days=period_days, organic_audience=organic_audience,
    )

    return {
        "adset_name": adset_info.get("name", ""),
        "targeting_display": targeting_display,
        "raw_targeting": raw_targeting,
        "metrics": adset_metrics,
        "result": adset_result,
        "breakdowns": breakdowns,
        "unsupported_breakdowns": unsupported_breakdowns,
        "ads_diagnostics": ads_diagnostics,
        "learning_stage": learning_stage,
        "trend": trend,
        "verdict": verdict,
    }


def _fetch_organic_audience(cfg: dict, token: str) -> dict:
    """Реальная органическая аудитория аккаунта (follower_demographics) — общая логика для
    /audience-verdict и /recommendations, никогда не роняет запрос: нет ig_user_id/ошибка API ->
    честное {"available": False, "note": ...}, не 500 и не выдумка."""
    ig_user_id = cfg.get("ig_user_id")
    if not ig_user_id:
        return {"available": False, "by_age": {}, "by_gender": {}, "note": t("ads.msg.no_ig_user_for_demographics")}
    try:
        return fetch_follower_demographics(token, ig_user_id)
    except InstagramAPIError as e:
        return {"available": False, "by_age": {}, "by_gender": {}, "note": str(e)}


@ads_bp.route("/audience-verdict", methods=["GET"])
def get_audience_verdict():
    """«Аудитория: та или не та?» — углублённый разбор одной группы (adset)."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("ads.msg.no_token")}), 400

    adset_id = request.args.get("adset_id")
    if not adset_id:
        return jsonify({"error": t("ads.msg.no_adset_id")}), 400
    objective = request.args.get("objective")

    period = request.args.get("period", DEFAULT_PERIOD)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    period_days = estimate_period_days(period, date_from, date_to)
    organic_audience = _fetch_organic_audience(cfg, token)

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)
        analysis = _analyze_adset(
            token, adset_id, objective, time_range_params,
            period_days=period_days, organic_audience=organic_audience,
        )
    except AdsAPIError as e:
        return jsonify({"error": str(e)}), 400

    opus_summary, opus_note = None, None
    anthropic_key = cfg.get("anthropic_api_key")
    if not anthropic_key:
        opus_note = t("ads.msg.no_anthropic_key_for_opus")
    else:
        try:
            system_prompt, user_message = build_audience_verdict_prompt(
                analysis["adset_name"],
                analysis["targeting_display"],
                analysis["verdict"],
                objective_label=objective_label(objective),
                account_niche=cfg.get("account_niche") or "",
                organic_audience=organic_audience,
                lang=current_lang(),
            )
            opus_summary = call_opus(anthropic_key, system_prompt, user_message, max_tokens=400)
        except anthropic.APIError as e:
            opus_note = t("ads.msg.opus_error", error=e)

    analysis.pop("raw_targeting", None)
    analysis["organic_audience"] = organic_audience
    analysis["opus_summary"] = opus_summary
    analysis["opus_note"] = opus_note
    return jsonify(analysis)


def _fmt(value, suffix=""):
    if value is None:
        return "нет данных"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _kpi_lines(kpi_verdicts: list) -> str:
    if not kpi_verdicts:
        return "цели не заданы"
    return "; ".join(f"{v['metric']}: факт {_fmt(v['fact'])} vs цель {_fmt(v['target'])} — {v['verdict'] or 'нет данных'}" for v in kpi_verdicts)


def _build_recommendations_context(campaign_ctx: dict, adsets_ctx: list) -> str:
    organic_audience = campaign_ctx.get("organic_audience") or {}
    organic_line = (
        format_organic_audience(organic_audience) if organic_audience.get("available")
        else (organic_audience.get("note") or "нет данных")
    )
    lines = [
        f"КАМПАНИЯ: «{campaign_ctx['name']}»",
        f"Ниша/тематика аккаунта: {campaign_ctx.get('account_niche') or 'нет данных (не указана в настройках)'}",
        f"Реальная органическая аудитория аккаунта (Instagram): {organic_line}",
        f"Цель: {campaign_ctx['objective_label']} ({campaign_ctx['objective']})",
        f"Что считается результатом: {campaign_ctx['result_explanation']}",
        f"Статус: {campaign_ctx['status']}/{campaign_ctx['effective_status']}",
        f"Бюджет: {campaign_ctx['budget_type']}",
        (
            f"Метрики за период: расход {_fmt(campaign_ctx['metrics'].get('spend'))}, "
            f"показы {_fmt(campaign_ctx['metrics'].get('impressions'))}, "
            f"CTR {_fmt(campaign_ctx['metrics'].get('ctr'), '%')}, CPM {_fmt(campaign_ctx['metrics'].get('cpm'))}, "
            f"частота {_fmt(campaign_ctx['metrics'].get('frequency'))}"
        ),
        (
            f"Результат: {campaign_ctx['result'].get('label') or 'нет данных'} = {_fmt(campaign_ctx['result'].get('value'))}, "
            f"цена результата {_fmt(campaign_ctx['result'].get('cost_per_result'))}, ROAS {_fmt(campaign_ctx['result'].get('roas'))}"
            + (f" ({campaign_ctx['result']['note']})" if campaign_ctx['result'].get('note') else "")
        ),
        f"Мои KPI (кампания в целом): {_kpi_lines(campaign_ctx['kpi_verdicts'])}",
        "",
        "ГРУППЫ:",
    ]

    for a in adsets_ctx:
        lines.append(f"--- Группа «{a['adset_name']}» ---")
        t = a["targeting_display"]
        lines.append(f"Таргетинг: возраст {t['age']}, пол {t['gender']}, гео {t['geo']}, плейсменты {t['placement']}")
        m = a["metrics"]
        lines.append(f"Метрики: расход {_fmt(m.get('spend'))}, показы {_fmt(m.get('impressions'))}, CTR {_fmt(m.get('ctr'), '%')}, CPM {_fmt(m.get('cpm'))}, частота {_fmt(m.get('frequency'))}")
        r = a["result"]
        lines.append(f"Результат: {r.get('label') or 'нет данных'} = {_fmt(r.get('value'))}, цена результата {_fmt(r.get('cost_per_result'))}")
        lines.append(f"Мои KPI (эта группа): {_kpi_lines(a['kpi_verdicts'])}")
        lines.append(f"Learning stage: {a['learning_stage'] or 'нет данных'}")
        lines.append(f"Вердикт аудитории (посчитан по цифрам): {a['verdict']['verdict_label']}")
        lines.append("Обоснование вердикта: " + "; ".join(a["verdict"]["reasoning"]))
        lines.append("Объявления:")
        for ad in a["ads"]:
            am = ad.get("metrics") or {}
            ar = ad.get("result") or {}
            rankings = ad.get("rankings") or {}
            lines.append(
                f"  - «{ad['name']}»: показы {_fmt(am.get('impressions'))}, CTR {_fmt(am.get('ctr'), '%')}, расход {_fmt(am.get('spend'))}, "
                f"результат {_fmt(ar.get('value'))} (цена результата {_fmt(ar.get('cost_per_result'))}), "
                f"ranking: quality={rankings.get('quality') or 'нет данных'}, "
                f"engagement={rankings.get('engagement_rate') or 'нет данных'}, conversion={rankings.get('conversion_rate') or 'нет данных'}"
            )
            fatigue = ad.get("fatigue") or {}
            if fatigue.get("fatigued"):
                lines.append(f"    Усталость крео: ДА, с {fatigue.get('since_date')} — {fatigue.get('reason')}")
            elif fatigue.get("note"):
                lines.append(f"    Усталость крео: {fatigue['note']}")
            else:
                lines.append("    Усталость крео: признаков не обнаружено за период")
        lines.append("")

    return "\n".join(lines)


@ads_bp.route("/recommendations", methods=["GET"])
def get_recommendations():
    """Этап 4d — финал: сводит настройки, метрики, аудиторию, динамику, усталость крео и
    мои KPI по кампании в один контекст и просит Opus дать конкретные, честные рекомендации."""
    cfg = get_effective_config()
    token = cfg.get("ig_access_token")
    if not token:
        return jsonify({"error": t("ads.msg.no_token")}), 400
    anthropic_key = cfg.get("anthropic_api_key")
    if not anthropic_key:
        return jsonify({"error": t("ads.msg.no_anthropic_key")}), 400

    campaign_id = request.args.get("campaign_id")
    if not campaign_id:
        return jsonify({"error": t("ads.msg.no_campaign_id")}), 400

    period = request.args.get("period", DEFAULT_PERIOD)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    period_days = estimate_period_days(period, date_from, date_to)
    organic_audience = _fetch_organic_audience(cfg, token)

    try:
        time_range_params = build_time_range_params(period, date_from, date_to)

        campaign = fetch_single_campaign(token, campaign_id)
        objective = campaign.get("objective")
        campaign_opt_goal = campaign_optimization_goal(campaign)
        all_kpi_targets = load_kpi_targets()
        kpi_targets = all_kpi_targets.get(objective)

        campaign_row, _err = fetch_entity_metrics(token, campaign_id, time_range_params)
        campaign_metrics = format_metrics_row(campaign_row or {})
        campaign_result = extract_result_metric(objective, campaign_row or {}, campaign_opt_goal)
        campaign_kpi_verdicts = compute_kpi_verdicts(campaign_metrics, campaign_result, kpi_targets)

        campaign_ctx = {
            "name": campaign.get("name", ""),
            "objective": objective,
            "objective_label": objective_label(objective),
            "result_explanation": result_explanation(objective, campaign_opt_goal),
            "status": campaign.get("status"),
            "effective_status": campaign.get("effective_status"),
            "budget_type": "CBO" if (campaign.get("daily_budget") or campaign.get("lifetime_budget")) else "ABO",
            "metrics": campaign_metrics,
            "result": campaign_result,
            "kpi_verdicts": campaign_kpi_verdicts,
            "account_niche": cfg.get("account_niche") or "",
            "organic_audience": organic_audience,
        }

        adsets_ctx = []
        for adset in campaign.get("_adsets", []):
            analysis = _analyze_adset(
                token, adset["id"], objective, time_range_params,
                period_days=period_days, organic_audience=organic_audience,
            )
            analysis["kpi_verdicts"] = compute_kpi_verdicts(analysis["metrics"], analysis["result"], kpi_targets)

            # Один запрос на всю группу (level=ad) вместо отдельного timeseries-запроса на
            # каждое объявление — при разборе кампании целиком (много групп × много крео)
            # именно эти повторные точечные вызовы упирались в лимит запросов Meta.
            try:
                daily_by_ad = fetch_timeseries_by_adset(
                    token, adset["id"], objective, time_range_params, time_increment=1,
                    optimization_goal=adset.get("optimization_goal"),
                )
            except AdsAPIError:
                daily_by_ad = {}

            ads_with_fatigue = []
            for ad_diag in analysis["ads_diagnostics"]:
                ad_kpi = compute_kpi_verdicts(ad_diag.get("metrics") or {}, ad_diag.get("result") or {}, kpi_targets)
                ad_daily = daily_by_ad.get(ad_diag["id"])
                if ad_daily:
                    fatigue = detect_creative_fatigue(ad_daily)
                else:
                    fatigue = {"fatigued": False, "since_date": None, "reason": None, "note": t("ads.msg.no_dynamics_data")}
                ads_with_fatigue.append({**ad_diag, "kpi_verdicts": ad_kpi, "fatigue": fatigue})

            analysis["ads"] = ads_with_fatigue
            adsets_ctx.append(analysis)
    except AdsAPIError as e:
        return jsonify({"error": str(e)}), 400

    context_text = _build_recommendations_context(campaign_ctx, adsets_ctx)

    try:
        system_prompt, user_message = build_recommendations_prompt(context_text, lang=current_lang())
        recommendations_text = call_opus(anthropic_key, system_prompt, user_message, max_tokens=1500)
    except anthropic.APIError as e:
        return jsonify({"error": t("ads.msg.opus_error", error=e)}), 400

    return jsonify({
        "campaign": campaign_ctx,
        "adsets": adsets_ctx,
        "context_used": context_text,
        "recommendations": recommendations_text,
    })
