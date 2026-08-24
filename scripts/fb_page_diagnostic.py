"""
Разовая диагностика Facebook Page Graph API — перепроверка через PAGE access token
(не user token), т.к. в 2026 Meta убрала read_insights как отдельное выдаваемое разрешение
(его нет в Graph API Explorer, Live-приложения с ним в списке permissions блокируются).
Органический охват/показы страницы (page_impressions*) официально требуют read_insights,
поэтому ожидаемо недоступны — тест это фиксирует, а не пытается обойти.

Шаги:
1. User token (Business Login, тот же ig_access_token) -> granular_scopes -> page id
   (тот же путь, что app/instagram_api.py::resolve_ig_user использует для IG, т.к.
   /me/accounts у Business Login токенов пустой).
2. GET /{page-id}?fields=access_token с user token -> Page Access Token.
3. Page token (+ pages_read_engagement, уже выдан) -> fan_count, посты, реакции/клики/просмотры
   по постам, page_post_engagements/page_follows/page_video_views.
4. page_impressions* -> ожидаемо error, фиксируем как "недоступно, ограничение Meta 2026".
5. Если по странице пусто -> проверяем назначенные задачи (tasks) юзера на странице через
   /me/accounts (с page token это не сработает, поэтому used /{page-id}/roles правами page token
   не читается — используем tasks, которые Meta возвращает вместе с access_token на /me/accounts
   при наличии pages_show_list; здесь же на всякий случай логируем raw ответ для ручного разбора).

Запуск: .venv/Scripts/python.exe scripts/fb_page_diagnostic.py
"""
import json
import sys

import requests

sys.path.insert(0, ".")

from app import create_app
from app.db import db
from app.models import Project

GRAPH_BASE = "https://graph.facebook.com/v21.0"


def gget(path, token, **params):
    params["access_token"] = token
    r = requests.get(f"{GRAPH_BASE}/{path}", params=params, timeout=30)
    try:
        data = r.json()
    except ValueError:
        data = {"non_json_body": r.text[:500]}
    return r.status_code, data


def line(title):
    print(f"\n{'=' * 10} {title} {'=' * 10}")


def main():
    app = create_app()
    with app.app_context():
        project = Project.query.filter_by(is_active=True).first() or Project.query.first()
        if not project or not project.ig_access_token:
            print("Нет проекта с ig_access_token в БД — нечем диагностировать.")
            return

        user_token = project.ig_access_token
        print(f"Проект: {project.name!r} (id={project.id})")

        line("1. debug_token -> granular_scopes")
        status, dbg = gget("debug_token", user_token, input_token=user_token)
        print(status, json.dumps(dbg, ensure_ascii=False, indent=2)[:3000])

        scopes = dbg.get("data", {}).get("granular_scopes", []) or []
        page_ids = []
        for entry in scopes:
            if entry.get("scope", "").startswith("pages_"):
                for tid in entry.get("target_ids", []) or []:
                    if tid not in page_ids:
                        page_ids.append(tid)
        print(f"\nНайдено page_id в granular_scopes: {page_ids}")

        if not page_ids:
            line("me/accounts (фоллбэк)")
            status, accounts = gget("me/accounts", user_token, fields="id,name,access_token,tasks")
            print(status, json.dumps(accounts, ensure_ascii=False, indent=2)[:3000])
            for p in accounts.get("data", []) or []:
                if p.get("id"):
                    page_ids.append(p["id"])

        if not page_ids:
            print("\nНи granular_scopes, ни /me/accounts не дали page_id. Диагностика дальше невозможна.")
            return

        for page_id in page_ids:
            line(f"2. Page access_token для page_id={page_id}")
            status, page_tok_resp = gget(page_id, user_token, fields="access_token,name")
            print(status, json.dumps(page_tok_resp, ensure_ascii=False, indent=2)[:1000])

            page_token = page_tok_resp.get("access_token")
            page_name = page_tok_resp.get("name", "?")
            if not page_token:
                print(f"Нет page access_token для {page_id} ({page_name}) — пропускаю.")
                continue

            line(f"3a. fan_count/followers_count — {page_name}")
            status, info = gget(page_id, page_token, fields="id,name,fan_count,followers_count")
            print(status, json.dumps(info, ensure_ascii=False, indent=2))

            line(f"3b. Посты страницы — {page_name}")
            status, posts = gget(f"{page_id}/posts", page_token, fields="id,message,created_time", limit=5)
            print(status, json.dumps(posts, ensure_ascii=False, indent=2)[:3000])
            post_ids = [p["id"] for p in posts.get("data", []) or [] if p.get("id")]

            if post_ids:
                sample_post = post_ids[0]
                line(f"3c. По посту {sample_post}: reactions (через edge reactions.summary)")
                status, post_reactions = gget(
                    sample_post,
                    page_token,
                    fields=(
                        "reactions.type(LIKE).summary(total_count).limit(0).as(like),"
                        "reactions.type(LOVE).summary(total_count).limit(0).as(love),"
                        "reactions.type(WOW).summary(total_count).limit(0).as(wow),"
                        "reactions.type(HAHA).summary(total_count).limit(0).as(haha),"
                        "reactions.type(SAD).summary(total_count).limit(0).as(sad),"
                        "reactions.type(ANGRY).summary(total_count).limit(0).as(angry),"
                        "shares,comments.summary(total_count).limit(0)"
                    ),
                )
                print(status, json.dumps(post_reactions, ensure_ascii=False, indent=2)[:2000])

                line(f"3c'. По посту {sample_post}: /insights edge (post_clicks, post_video_views, post_impressions...)")
                status, post_insights = gget(
                    f"{sample_post}/insights",
                    page_token,
                    metric="post_clicks,post_video_views,post_impressions,post_engaged_users",
                )
                print(status, json.dumps(post_insights, ensure_ascii=False, indent=2)[:2000])
            else:
                print("Постов нет — пропускаю проверку по-постовых метрик.")

            line(f"3d. /{page_id}/insights edge — page_post_engagements/page_follows/page_video_views — {page_name}")
            status, page_metrics = gget(
                f"{page_id}/insights",
                page_token,
                metric="page_post_engagements,page_follows,page_video_views",
                period="day",
            )
            print(status, json.dumps(page_metrics, ensure_ascii=False, indent=2)[:2000])
            if "error" in page_metrics:
                msg = page_metrics["error"].get("message", "")
                if "read_insights" in msg or "permission" in msg.lower():
                    print(">>> ПОМЕЧЕНО: недоступно, ограничение Meta 2026 (read_insights убран как выдаваемое разрешение).")

            line(f"4. /{page_id}/insights — page_impressions* (охват/показы) — {page_name}")
            status, impressions = gget(
                f"{page_id}/insights",
                page_token,
                metric="page_impressions,page_impressions_unique,page_impressions_paid",
                period="day",
            )
            print(status, json.dumps(impressions, ensure_ascii=False, indent=2)[:2000])
            if "error" in impressions:
                msg = impressions["error"].get("message", "")
                if "read_insights" in msg or "permission" in msg.lower():
                    print(">>> ПОМЕЧЕНО: недоступно, ограничение Meta 2026 (read_insights убран как выдаваемое разрешение).")

            line(f"5. Проверка задачи 'Анализ' (tasks) на странице — {page_name}")
            status, accounts = gget("me/accounts", user_token, fields="id,name,tasks")
            print(status, json.dumps(accounts, ensure_ascii=False, indent=2)[:2000])
            for p in accounts.get("data", []) or []:
                if p.get("id") == page_id:
                    print(f"tasks на {page_name}: {p.get('tasks')}")


if __name__ == "__main__":
    main()
