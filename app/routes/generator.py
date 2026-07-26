from flask import Blueprint, jsonify, request

from app.categories import load_categories
from app.i18n import t
from app.project_store import get_effective_config
from app.routes.metrics import load_cache
from app.saved_scripts import add_script, delete_script, load_saved_scripts, now_iso, update_script
from app.script_generator import (
    DEFAULT_FORMAT,
    DEFAULT_MODEL_KEY,
    FORMAT_CHOICES,
    MODEL_INFO,
    estimate_cost_usd,
    generate_script,
)
from app.script_verdict import (
    compute_baseline,
    evaluate_reel,
    normalize_verdict,
    render_verdict_reason,
    resolve_media_id_by_reference,
)
from app.style_profile import compute_style_profile, load_style_profile
from app.transcription import load_transcripts

generator_bp = Blueprint("generator", __name__)


@generator_bp.route("/models", methods=["GET"])
def get_models():
    models = {
        key: {**info, "description": t(f"generator.model.{key}.description")}
        for key, info in MODEL_INFO.items()
    }
    return jsonify({"models": models, "default": DEFAULT_MODEL_KEY})


@generator_bp.route("/profile", methods=["GET"])
def get_profile():
    return jsonify({"profile": load_style_profile()})


@generator_bp.route("/profile/refresh", methods=["POST"])
def refresh_profile():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("generator.msg.no_api_key")}), 400

    transcripts = load_transcripts()
    posts = load_cache().get("posts", [])
    try:
        profile = compute_style_profile(transcripts, posts, api_key)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": t("settings.msg.anthropic_api_error", error=e)}), 500

    return jsonify({"profile": profile})


@generator_bp.route("/generate", methods=["POST"])
def generate():
    cfg = get_effective_config()
    api_key = cfg.get("anthropic_api_key")
    if not api_key:
        return jsonify({"error": t("generator.msg.no_api_key")}), 400
    niche = (cfg.get("account_niche") or "").strip()

    body = request.get_json(force=True) or {}
    topic = (body.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": t("generator.msg.enter_topic")}), 400

    hook_type_pref = body.get("hook_type") or None
    model_key = body.get("model") or DEFAULT_MODEL_KEY
    clean_for_ads = bool(body.get("clean_for_ads"))
    category_id = body.get("category_id") or None
    format_ = body.get("format") or DEFAULT_FORMAT
    if format_ not in FORMAT_CHOICES:
        format_ = DEFAULT_FORMAT

    posts = load_cache().get("posts", [])
    transcripts = load_transcripts()
    style_profile = load_style_profile()
    saved_scripts = load_saved_scripts()

    category_name = None
    category_assignments = None
    if category_id:
        categories_data = load_categories()
        category_assignments = categories_data["assignments"]
        cat = next((c for c in categories_data["categories"] if c["id"] == category_id), None)
        category_name = cat["name"] if cat else None

    try:
        result = generate_script(
            topic,
            hook_type_pref,
            model_key,
            clean_for_ads,
            api_key,
            posts,
            transcripts,
            style_profile,
            saved_scripts,
            category_id=category_id,
            category_name=category_name,
            category_assignments=category_assignments,
            niche=niche,
            format_=format_,
        )
    except Exception as e:
        return jsonify({"error": t("generator.msg.generation_error", error=e)}), 500

    result["estimated_cost_usd"] = round(
        estimate_cost_usd(
            result["model_key"], result["usage"]["input_tokens"], result["usage"]["output_tokens"]
        ),
        5,
    )

    # Автосохранение — каждый сгенерированный скрипт пишется на диск сразу, без отдельной кнопки
    saved = add_script(
        {
            "topic": topic,
            "hook_type_pref": hook_type_pref,
            "model_key": result["model_key"],
            "model_id": result["model_id"],
            "clean_for_ads": clean_for_ads,
            "category_id": result["category_id"],
            "category_name": result["category_name"],
            "format": result["format"],
            "script": result["script"],
            "raw_text": result["raw_text"],
            "notes": result["notes"],
            "estimated_cost_usd": result["estimated_cost_usd"],
        }
    )
    result["saved_script_id"] = saved["id"]

    return jsonify(result)


@generator_bp.route("/scripts", methods=["GET"])
def list_scripts():
    scripts = load_saved_scripts()
    for s in scripts:
        # verdict_metrics — структурные данные (ключи метрик, не готовый текст), рендерим
        # текст обоснования заново на текущем языке при каждой отдаче, а не берём то, что
        # было сохранено при последнем пересчёте (иначе смена языка не подхватывается).
        if s.get("verdict_metrics") is not None:
            s["verdict"] = normalize_verdict(s.get("verdict"))
            s["verdict_reason"] = render_verdict_reason(s["verdict"], s["verdict_metrics"])
    return jsonify({"scripts": scripts})


@generator_bp.route("/scripts/manual", methods=["POST"])
def add_manual_script():
    body = request.get_json(force=True) or {}
    topic = (body.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": t("generator.msg.enter_manual_title")}), 400

    hook_type_pref = (body.get("hook_type_pref") or "").strip() or None
    model_key = (body.get("model_key") or "").strip() or None
    model_id = MODEL_INFO.get(model_key, {}).get("id") if model_key else None

    hook = (body.get("hook") or "").strip()
    script_body = (body.get("body") or "").strip()
    cta = (body.get("cta") or "").strip()
    raw_text = "\n".join(
        part
        for part in [
            f"ХУК: {hook}" if hook else "",
            f"ТЕЛО: {script_body}" if script_body else "",
            f"CTA: {cta}" if cta else "",
        ]
        if part
    )

    notes_raw = body.get("notes") or ""
    notes = [line.strip() for line in notes_raw.split("\n") if line.strip()]

    record = {
        "topic": topic,
        "hook_type_pref": hook_type_pref,
        "model_key": model_key,
        "model_id": model_id,
        "clean_for_ads": False,
        "category_id": None,
        "category_name": None,
        "format": "reels",
        "script": {"hook": hook or None, "body": script_body or None, "cta": cta or None},
        "raw_text": raw_text,
        "notes": notes,
        "estimated_cost_usd": 0,
        "manual": True,
    }

    created_at = (body.get("created_at") or "").strip()
    if created_at:
        record["created_at"] = created_at

    saved = add_script(record)
    return jsonify({"script": saved})


@generator_bp.route("/scripts/<script_id>", methods=["PATCH"])
def patch_script(script_id):
    body = request.get_json(force=True) or {}
    allowed = {"is_favorite"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({"error": t("generator.msg.nothing_to_update")}), 400
    script = update_script(script_id, updates)
    if not script:
        return jsonify({"error": t("generator.msg.script_not_found")}), 404
    return jsonify({"script": script})


@generator_bp.route("/scripts/<script_id>", methods=["DELETE"])
def remove_script(script_id):
    if not delete_script(script_id):
        return jsonify({"error": t("generator.msg.script_not_found")}), 404
    return jsonify({"deleted": True})


@generator_bp.route("/scripts/<script_id>/link", methods=["POST"])
def link_script(script_id):
    body = request.get_json(force=True) or {}
    posts = load_cache().get("posts", [])

    media_id = body.get("media_id") or resolve_media_id_by_reference(posts, body.get("reference"))
    if not media_id:
        return jsonify({"error": t("generator.msg.cannot_resolve_reel")}), 400

    post = next((p for p in posts if p["id"] == media_id), None)
    if not post:
        return jsonify({"error": t("generator.msg.reel_not_found")}), 404

    transcripts = load_transcripts()
    baseline = compute_baseline(posts, transcripts, exclude_id=media_id)
    result = evaluate_reel(post, transcripts.get(media_id), baseline)

    script = update_script(
        script_id,
        {
            "linked_media_id": media_id,
            "linked_at": now_iso(),
            "verdict": result["verdict"],
            "verdict_reason": result["reason"],
            "verdict_metrics": result["metrics"],
            "verdict_computed_at": now_iso(),
            "baseline_used": baseline,
        },
    )
    if not script:
        return jsonify({"error": t("generator.msg.script_not_found")}), 404

    return jsonify(
        {
            "script": script,
            "post": {
                "id": post["id"],
                "caption": post.get("caption", ""),
                "permalink": post.get("permalink"),
                "thumbnail_url": post.get("thumbnail_url"),
            },
        }
    )


@generator_bp.route("/scripts/<script_id>/unlink", methods=["POST"])
def unlink_script(script_id):
    script = update_script(
        script_id,
        {
            "linked_media_id": None,
            "linked_at": None,
            "verdict": None,
            "verdict_reason": None,
            "verdict_metrics": [],
            "verdict_computed_at": None,
            "baseline_used": None,
        },
    )
    if not script:
        return jsonify({"error": t("generator.msg.script_not_found")}), 404
    return jsonify({"script": script})


@generator_bp.route("/reels", methods=["GET"])
def list_reels_for_linking():
    posts = load_cache().get("posts", [])
    reels = [
        {
            "id": p["id"],
            "caption": p.get("caption", ""),
            "permalink": p.get("permalink"),
            "thumbnail_url": p.get("thumbnail_url"),
            "timestamp": p.get("timestamp"),
            "engagement_rate": p.get("engagement_rate"),
            "is_ad": p.get("is_ad", False),
        }
        for p in posts
        if p.get("media_product_type") == "REELS"
    ]
    return jsonify({"reels": reels})
