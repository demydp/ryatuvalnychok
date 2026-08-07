"""
Клиент Facebook Marketing API (graph.facebook.com/v21.0, endpoint act_{id}).
Использует тот же access token, что и Instagram (app/instagram_api.py) — тут нужно
только право ads_read.

Честные правила (как в instagram_api.py):
- Метрику, которую API не отдал (не поддерживается / нет прав / нет данных за период) —
  никогда не показываем как 0, помечаем "нет данных" с причиной.
- "Результат" и "стоимость результата" зависят от цели кампании (objective) — если цель
  не сопоставлена ни с одним известным типом результата, честно говорим "нет данных".

Единицы измерения (частая ловушка Marketing API):
- Поля бюджета/ставки/баланса на нодах Campaign/AdSet/AdAccount (daily_budget,
  lifetime_budget, bid_amount, spend_cap, amount_spent, balance) — в МИНОРНЫХ единицах
  валюты (центы), кроме валют без дробной части (JPY, KRW и т.п.) — их нужно делить на 100.
- Поля из Insights API (spend, cpm, cpc, cost_per_action_type, action_values,
  purchase_roas) — уже в ПОЛНЫХ единицах валюты, делить не нужно.
Это разделение — сверьте оба типа чисел с Ads Manager на этапе проверки 4a.
"""
import json
import random
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from flask import copy_current_request_context, has_request_context

from app.i18n import t

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Валюты без дробной части — Meta (как и большинство платёжных API) не хранит центы.
ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}

ACCOUNT_STATUS_LABELS = {
    1: "Активен",
    2: "Отключён",
    3: "Не оплачен (UNSETTLED)",
    7: "На проверке риска",
    9: "Льготный период (просрочка оплаты)",
    100: "В процессе закрытия",
    101: "Закрыт",
    201: "Активен (ANY_ACTIVE)",
    202: "Закрыт (ANY_CLOSED)",
}

# ODAX (актуальные цели) + легаси-цели (могут встречаться в старых кампаниях).
# Список кандидатов action_type — берём первый найденный в ответе actions/cost_per_action_type.
OBJECTIVE_LABELS = {
    "OUTCOME_AWARENESS": "Узнаваемость",
    "OUTCOME_TRAFFIC": "Трафик",
    "OUTCOME_ENGAGEMENT": "Вовлечённость",
    "OUTCOME_LEADS": "Лиды",
    "OUTCOME_SALES": "Продажи",
    "OUTCOME_APP_PROMOTION": "Продвижение приложения",
    "BRAND_AWARENESS": "Узнаваемость бренда (легаси)",
    "REACH": "Охват (легаси)",
    "LINK_CLICKS": "Трафик / клики по ссылке (легаси)",
    "POST_ENGAGEMENT": "Вовлечённость (легаси)",
    "PAGE_LIKES": "Лайки страницы (легаси)",
    "EVENT_RESPONSES": "Отклики на событие (легаси)",
    "LEAD_GENERATION": "Лиды (легаси)",
    "MESSAGES": "Сообщения (легаси)",
    "CONVERSIONS": "Конверсии (легаси)",
    "PRODUCT_CATALOG_SALES": "Продажи по каталогу (легаси)",
    "STORE_VISITS": "Визиты в магазин (легаси)",
    "APP_INSTALLS": "Установки приложения (легаси)",
    "VIDEO_VIEWS": "Просмотры видео (легаси)",
}

OBJECTIVE_RESULT_ACTIONS = {
    "OUTCOME_LEADS": (["lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"], "Лиды"),
    "LEAD_GENERATION": (["lead", "onsite_conversion.lead_grouped"], "Лиды"),
    "OUTCOME_SALES": (["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"], "Покупки"),
    "CONVERSIONS": (["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"], "Конверсии"),
    "PRODUCT_CATALOG_SALES": (["omni_purchase", "purchase"], "Покупки"),
    "OUTCOME_TRAFFIC": (["link_click"], "Клики по ссылке"),
    "LINK_CLICKS": (["link_click"], "Клики по ссылке"),
    "OUTCOME_ENGAGEMENT": (["post_engagement", "onsite_conversion.messaging_conversation_started_7d"], "Вовлечённость"),
    "POST_ENGAGEMENT": (["post_engagement"], "Вовлечённость"),
    "MESSAGES": (["onsite_conversion.messaging_conversation_started_7d"], "Начатые переписки"),
    "OUTCOME_APP_PROMOTION": (["omni_app_install", "mobile_app_install"], "Установки приложения"),
    "APP_INSTALLS": (["omni_app_install", "mobile_app_install"], "Установки приложения"),
    "PAGE_LIKES": (["like"], "Лайки страницы"),
    "EVENT_RESPONSES": (["rsvp"], "Отклики на событие"),
    "STORE_VISITS": (["store_visit"], "Визиты в магазин"),
    "VIDEO_VIEWS": (["video_view"], "Просмотры видео"),
}
# У Узнаваемости/Охвата нет отдельного "результата" — по TZ результат = сам охват/CPM.
NO_RESULT_OBJECTIVES = {"OUTCOME_AWARENESS", "BRAND_AWARENESS", "REACH"}

# optimization_goal (поле AdSet) — то, что РЕАЛЬНО настроено для оптимизации показов, и точнее
# objective кампании: один и тот же objective (особенно OUTCOME_ENGAGEMENT) может означать
# и "вовлечённость с постом", и "начатые переписки" — Meta различает это только через
# optimization_goal. Без этого extract_result_metric всегда брал первый совпавший action_type
# по OBJECTIVE_RESULT_ACTIONS (обычно post_engagement, он почти всегда ненулевой), даже когда
# цель кампании — переписки, и показывал вовлечённость с её ценой вместо начатых переписок с их
# ценой. Проверяется ПЕРЕД OBJECTIVE_RESULT_ACTIONS (см. extract_result_metric), т.к. это более
# точный сигнал; если optimization_goal неизвестен/не сопоставлен — падаем обратно на objective.
OPTIMIZATION_GOAL_RESULT_ACTIONS = {
    "CONVERSATIONS": (["onsite_conversion.messaging_conversation_started_7d"], "Начатые переписки"),
    "POST_ENGAGEMENT": (["post_engagement"], "Вовлечённость"),
    "LINK_CLICKS": (["link_click"], "Клики по ссылке"),
    "LANDING_PAGE_VIEWS": (["landing_page_view", "link_click"], "Просмотры целевой страницы"),
    "LEAD_GENERATION": (["lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"], "Лиды"),
    "QUALITY_LEAD": (["lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"], "Лиды"),
    "OFFSITE_CONVERSIONS": (["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"], "Покупки"),
    "VALUE": (["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"], "Покупки"),
    "QUALITY_CALL": (["onsite_conversion.call_confirm"], "Звонки"),
    "APP_INSTALLS": (["omni_app_install", "mobile_app_install"], "Установки приложения"),
    "THRUPLAY": (["video_view"], "Просмотры видео"),
    "PAGE_LIKES": (["like"], "Лайки страницы"),
}
# optimization_goal без отдельного "результата" (охват/показы как таковые — вся суть) —
# приоритетнее NO_RESULT_OBJECTIVES там, где objective этого не выдаёт (например,
# OUTCOME_TRAFFIC с целью оптимизации REACH — редко, но бывает).
OPTIMIZATION_GOAL_NO_RESULT = {"REACH", "IMPRESSIONS"}

CTA_LABELS = {
    "LEARN_MORE": "Подробнее",
    "SHOP_NOW": "Купить",
    "SIGN_UP": "Зарегистрироваться",
    "SUBSCRIBE": "Подписаться",
    "DOWNLOAD": "Скачать",
    "BOOK_TRAVEL": "Забронировать",
    "GET_QUOTE": "Узнать цену",
    "CONTACT_US": "Связаться с нами",
    "APPLY_NOW": "Подать заявку",
    "GET_OFFER": "Получить предложение",
    "MESSAGE_PAGE": "Написать сообщение",
    "INSTAGRAM_MESSAGE": "Написать в Instagram",
    "WHATSAPP_MESSAGE": "Написать в WhatsApp",
    "CALL_NOW": "Позвонить",
    "GET_DIRECTIONS": "Проложить маршрут",
    "WATCH_MORE": "Смотреть ещё",
    "PLAY_GAME": "Играть",
    "INSTALL_MOBILE_APP": "Установить приложение",
    "USE_APP": "Открыть приложение",
    "NO_BUTTON": "Без кнопки",
}

# "maximum" — официальный date_preset Meta: вся статистика с момента создания рекламного
# кабинета. Нужен, чтобы поднимать старые/завершённые кампании без необходимости знать
# точные даты их показа.
DATE_PRESETS = {"today", "last_7d", "last_14d", "last_30d", "maximum"}

# Период по умолчанию для карточки объявления (см. routes/ads.py) — единственное место,
# где задаётся дефолт. Напарник (app/companion.py) явно запрашивает отчёт за этот же период,
# чтобы не называть по одному и тому же объявлению другие цифры, чем показывает карточка.
DEFAULT_PERIOD = "maximum"

# Строим список инсайтов-полей отдельно от id-поля — при бисекции id-поле не трогаем,
# т.к. без него нельзя сопоставить строку ответа с нужным campaign/adset/ad.
INSIGHT_METRIC_FIELDS = [
    "spend",
    "impressions",
    "reach",
    "frequency",
    "cpm",
    "clicks",
    "inline_link_clicks",
    "ctr",
    "inline_link_click_ctr",
    "cpc",
    "cost_per_inline_link_click",
    "actions",
    "cost_per_action_type",
    "action_values",
    "purchase_roas",
    "video_30_sec_watched_actions",
    "video_thruplay_watched_actions",
    "video_p25_watch_actions",
    "video_p50_watch_actions",
    "video_p75_watch_actions",
    "video_p100_watch_actions",
    "video_avg_time_watched_actions",
]

LEVEL_ID_FIELD = {
    "campaign": "campaign_id",
    "adset": "adset_id",
    "ad": "ad_id",
}

# Разбивки аудитории (этап 4b) — каждая запрашивается отдельным вызовом insights на ноду
# кампании/группы (не на act_id), поэтому не нужен level= и не нужно решать, какие
# breakdown-измерения можно комбинировать друг с другом (у Meta есть ограничения на комбинации).
BREAKDOWN_DIMENSIONS = {
    "age": "Возраст",
    "gender": "Пол",
    "country": "Страна",
    "region": "Регион",
    "publisher_platform": "Платформа (FB/IG)",
    "platform_position": "Плейсмент",
    "impression_device": "Устройство",
}

# Поля, у которых значение — просто число/строка (не завязаны на action_type-структуру).
BASE_BREAKDOWN_FIELDS = [
    "spend",
    "impressions",
    "reach",
    "frequency",
    "cpm",
    "clicks",
    "inline_link_clicks",
    "ctr",
    "inline_link_click_ctr",
    "cpc",
    "cost_per_inline_link_click",
]

# Поля, где значение — список [{"action_type":..., "value":...}, ...] (по сути, всегда
# неявно "разбиты" по action_type). Meta не разрешает запрашивать их в ОДНОМ insights-запросе
# вместе с breakdown'ами "доставки" (плейсмент/платформа/устройство) — падает (#100)
# "Invalid parameter" с сообщением про недопустимую комбинацию (action_type, <breakdown>).
# См. DELIVERY_BREAKDOWNS и fetch_breakdown() ниже.
ACTION_BREAKDOWN_FIELDS = [
    "actions",
    "cost_per_action_type",
    "action_values",
    "purchase_roas",
    "video_30_sec_watched_actions",
    "video_thruplay_watched_actions",
]

DETAIL_FIELDS = BASE_BREAKDOWN_FIELDS + ACTION_BREAKDOWN_FIELDS

# Breakdown'ы "доставки" — единственные, у которых Meta не разрешает совмещать в одном
# запросе breakdown-колонку и action_type-based поля (см. ACTION_BREAKDOWN_FIELDS выше).
# Демографические/гео breakdown'ы (age/gender/country/region) этой проблемы не имеют —
# для них весь набор полей по-прежнему тянется одним запросом.
DELIVERY_BREAKDOWNS = {"platform_position", "publisher_platform", "impression_device"}

# По официальной таблице совместимости брейкдаунов Meta
# (developers.facebook.com/docs/marketing-api/insights/breakdowns/) с action_type можно
# джойнить только сочетания, помеченные "*" — "platform_position" и "impression_device"
# САМИ ПО СЕБЕ там не отмечены звёздочкой (т.е. недопустимы с action_type-полями вообще,
# даже отдельным запросом), а вот "publisher_platform" — отмечен, и пары
# "publisher_platform, platform_position" / "publisher_platform, impression_device" —
# тоже отмечены. Поэтому для этих двух breakdown'ов запрашиваем publisher_platform как
# обязательный "компаньон" вместе с ними (и в базовом, и в action-запросе), иначе Meta
# всё равно вернёт (#100) "Invalid parameter" про недопустимую комбинацию (action_type, <breakdown>)
# независимо от того, что запрос действий уже отдельный от базовых метрик.
DELIVERY_BREAKDOWN_COMPANION = {
    "platform_position": "publisher_platform",
    "impression_device": "publisher_platform",
}

# Явное объяснение "что такое результат" по цели — TZ п.4c требует показать это прямым текстом,
# а не только числом (см. OBJECTIVE_RESULT_ACTIONS выше, откуда берётся сам расчёт).
OBJECTIVE_RESULT_EXPLANATION = {
    "OUTCOME_AWARENESS": "Узнаваемость → результат = охват и CPM (не заявки и не покупки)",
    "BRAND_AWARENESS": "Узнаваемость → результат = охват и CPM (не заявки и не покупки)",
    "REACH": "Охват → результат = охват и CPM",
    "OUTCOME_TRAFFIC": "Трафик → результат = клики по ссылке, стоимость — CPC",
    "LINK_CLICKS": "Трафик → результат = клики по ссылке, стоимость — CPC",
    "OUTCOME_ENGAGEMENT": "Вовлечённость → результат = вовлечённость с постом, стоимость — цена за вовлечение",
    "POST_ENGAGEMENT": "Вовлечённость → результат = вовлечённость с постом, стоимость — цена за вовлечение",
    "OUTCOME_LEADS": "Лиды → результат = заявки (лиды), стоимость — CPL",
    "LEAD_GENERATION": "Лиды → результат = заявки (лиды), стоимость — CPL",
    "OUTCOME_SALES": "Продажи → результат = покупки, стоимость/окупаемость — CPA/ROAS",
    "CONVERSIONS": "Продажи/конверсии → результат = покупки, стоимость/окупаемость — CPA/ROAS",
    "PRODUCT_CATALOG_SALES": "Продажи по каталогу → результат = покупки, стоимость/окупаемость — CPA/ROAS",
    "OUTCOME_APP_PROMOTION": "Продвижение приложения → результат = установки, стоимость — цена установки",
    "APP_INSTALLS": "Продвижение приложения → результат = установки, стоимость — цена установки",
}

# То же самое объяснение, но по optimization_goal — приоритетнее OBJECTIVE_RESULT_EXPLANATION
# (см. result_explanation() ниже) по той же причине, что и OPTIMIZATION_GOAL_RESULT_ACTIONS:
# один objective=OUTCOME_ENGAGEMENT может означать и вовлечённость, и переписки.
OPTIMIZATION_GOAL_RESULT_EXPLANATION = {
    "CONVERSATIONS": "Переписки → результат = начатые переписки, стоимость — цена за переписку",
    "POST_ENGAGEMENT": "Вовлечённость → результат = вовлечённость с постом, стоимость — цена за вовлечение",
    "LINK_CLICKS": "Трафик → результат = клики по ссылке, стоимость — CPC",
    "LANDING_PAGE_VIEWS": "Трафик → результат = просмотры целевой страницы",
    "LEAD_GENERATION": "Лиды → результат = заявки (лиды), стоимость — CPL",
    "QUALITY_LEAD": "Лиды → результат = заявки (лиды), стоимость — CPL",
    "OFFSITE_CONVERSIONS": "Продажи → результат = покупки, стоимость/окупаемость — CPA/ROAS",
    "VALUE": "Продажи → результат = покупки, стоимость/окупаемость — CPA/ROAS",
    "QUALITY_CALL": "Звонки → результат = подтверждённые звонки",
    "APP_INSTALLS": "Продвижение приложения → результат = установки, стоимость — цена установки",
    "THRUPLAY": "Просмотры видео → результат = досмотры (ThruPlay)",
    "PAGE_LIKES": "Лайки страницы → результат = лайки",
    "REACH": "Охват → результат = охват и CPM",
    "IMPRESSIONS": "Охват → результат = охват и CPM",
}


def result_explanation(objective: str, optimization_goal: str = None) -> str:
    """Тот же приоритет optimization_goal -> objective, что и extract_result_metric() —
    текстовое объяснение "что считается результатом" не должно расходиться с самим расчётом."""
    return (
        OPTIMIZATION_GOAL_RESULT_EXPLANATION.get(optimization_goal)
        or OBJECTIVE_RESULT_EXPLANATION.get(objective)
        or t("ads.msg.no_result_explanation")
    )

# Диагностика релевантности Meta (этап "Аудитория: та или не та?") — доступна только на
# уровне объявления (ad), т.к. сравнивает конкретный креатив/оффер с конкурентами за ту же
# аудиторию. "UNKNOWN" у Meta означает "недостаточно показов для оценки" — честно None, не "средне".
RANKING_FIELDS = ["quality_ranking", "engagement_rate_ranking", "conversion_rate_ranking"]

RANKING_CODES = ("ABOVE_AVERAGE", "AVERAGE", "BELOW_AVERAGE_35", "BELOW_AVERAGE_20", "BELOW_AVERAGE_10", "BELOW_AVERAGE")

# Коды, которые бизнес-логика (app/ads_audience.py) трактует как "хуже конкурентов за эту
# аудиторию" — используются вместе с _ranking_label(), которая отдаёт уже переведённый текст
# для показа. Разделены специально: сравнивать по raw-коду надёжнее, чем по переведённой строке.
BELOW_AVERAGE_RANKING_CODES = {"BELOW_AVERAGE_35", "BELOW_AVERAGE_20", "BELOW_AVERAGE_10", "BELOW_AVERAGE"}


def objective_label(objective: str) -> str:
    if objective in OBJECTIVE_LABELS:
        return t(f"ads.objective.{objective}")
    return objective or t("common.no_data")


def _ranking_label(raw):
    if not raw or raw == "UNKNOWN":
        return None
    return t(f"ads.ranking.{raw}") if raw in RANKING_CODES else raw


class AdsAPIError(Exception):
    """Понятная ошибка для показа пользователю (проблема токена, прав, кабинета)."""


# Кэш ответов Marketing API — короткий TTL, только чтобы не дёргать Meta повторно за то же
# самое (тот же URL+параметры) в пределах одной "волны" запросов одной страницы дашборда
# (структура + разбивки + вердикт крео по нескольким объявлениям почти всегда пересекаются
# по entity_id/периоду). Не кэшируем ошибки — иначе временный сбой "залипнет" на весь TTL.
# 5 минут — открыл вкладку "Реклама", посмотрел, переключился на другую и вернулся через
# пару минут — не должно снова бить по Meta за те же самые данные (частая причина "Лимит
# запросов" при обычном использовании, не только при явном пересинке).
_CACHE_TTL_SECONDS = 300
_response_cache = {}
_cache_lock = threading.Lock()

# Коды/подстроки, которыми Meta помечает "слишком много запросов" (User/Application request
# limit reached, code 4/17/32/613) — при них мягко ждём и повторяем, а не рушим весь модуль.
_RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}
_MAX_RATE_LIMIT_RETRIES = 4
_RATE_LIMIT_BASE_DELAY_SEC = 2.0


def _cache_key(url, params):
    if not params:
        return url
    return url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params) if k != "access_token")


def _is_rate_limit_error(error: dict) -> bool:
    if not error:
        return False
    if error.get("code") in _RATE_LIMIT_ERROR_CODES:
        return True
    message = (error.get("message") or "").lower()
    return "request limit reached" in message or "too many calls" in message


def _sleep_before_retry(attempt: int) -> None:
    delay = _RATE_LIMIT_BASE_DELAY_SEC * (2 ** (attempt - 1)) + random.uniform(0, 1)
    time.sleep(delay)


def _get_raw(url, params=None):
    """GET с кэшем на _CACHE_TTL_SECONDS и мягким retry+backoff при ошибке лимита запросов
    Meta. Возвращает (data, error_dict_or_None) — не бросает исключение, чтобы одна неудачная
    подзапрос не рушила весь разбор (вызывающий код сам решает, насколько ошибка критична)."""
    key = _cache_key(url, params)
    with _cache_lock:
        cached = _response_cache.get(key)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    attempt = 0
    while True:
        try:
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()
        except requests.RequestException as e:
            return {}, {"message": t("ads.msg.marketing_api_unavailable", error=e)}
        except ValueError:
            return {}, {"message": t("ads.msg.marketing_api_bad_response")}

        error = data.get("error")
        if error and _is_rate_limit_error(error):
            attempt += 1
            if attempt <= _MAX_RATE_LIMIT_RETRIES:
                _sleep_before_retry(attempt)
                continue
            error = {**error, "message": t("ads.msg.rate_limited")}

        if not error:
            with _cache_lock:
                _response_cache[key] = (time.monotonic(), data, error)
        return data, error


def _get(url, params=None):
    data, error = _get_raw(url, params)
    if error:
        raise AdsAPIError(error.get("message") or t("ads.msg.unknown_marketing_api_error")) from None
    return data


# Ліміт Meta Graph API на кількість під-запитів в одному batch-виклику.
_BATCH_CHUNK_SIZE = 50


def _batch_get(access_token: str, relative_urls: list) -> list:
    """Один HTTP POST на кореневий Graph API endpoint з параметром batch=[...] замість
    len(relative_urls) окремих GET-запитів — головний важіль проти "Ліміт запитів Meta"
    там, де інакше був би N+1 (див. _populate_campaign_children: один запит "ads" на
    КОЖЕН adset). Повертає список розпарсених JSON-тіл у тому ж порядку, що й
    relative_urls; None для під-запиту, що впав (викликач честно трактує це як "нема
    даних", а не як 0/вигадку). Той самий retry+backoff на rate-limit, що й _get_raw —
    Meta для batch-викликів так само віддає error з тими ж кодами при перевантаженні."""
    if not relative_urls:
        return []

    results = [None] * len(relative_urls)
    for chunk_start in range(0, len(relative_urls), _BATCH_CHUNK_SIZE):
        chunk = relative_urls[chunk_start:chunk_start + _BATCH_CHUNK_SIZE]
        payload = json.dumps([{"method": "GET", "relative_url": u} for u in chunk])

        attempt = 0
        while True:
            try:
                resp = requests.post(
                    f"{GRAPH_BASE}/",
                    data={"access_token": access_token, "batch": payload},
                    timeout=45,
                )
                outer = resp.json()
            except (requests.RequestException, ValueError):
                outer = None
                break

            if isinstance(outer, dict) and _is_rate_limit_error(outer.get("error")):
                attempt += 1
                if attempt <= _MAX_RATE_LIMIT_RETRIES:
                    _sleep_before_retry(attempt)
                    continue
            break

        if not isinstance(outer, list):
            continue  # results для цього чанку лишаються None — чесно "нема даних"

        for i, item in enumerate(outer):
            if not item or item.get("code") != 200:
                continue
            try:
                results[chunk_start + i] = json.loads(item.get("body") or "{}")
            except ValueError:
                continue

    return results


def _wrap_for_thread(fn):
    """t() (переводы сообщений об ошибках) читает flask.request, а он не наследуется рабочими
    потоками ThreadPoolExecutor — без этого одна неподдерживаемая метрика внутри worker-потока
    рушит запрос с RuntimeError вместо честного переведённого сообщения. copy_current_request_context
    переносит текущий контекст запроса в поток, где реально выполнится функция."""
    return copy_current_request_context(fn) if has_request_context() else fn


def normalize_account_id(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def to_currency_units(minor_value, currency: str):
    """Переводит минорные единицы (центы) в валюту кабинета. None -> None (не 0!)."""
    if minor_value is None:
        return None
    try:
        value = float(minor_value)
    except (TypeError, ValueError):
        return None
    if (currency or "").upper() in ZERO_DECIMAL_CURRENCIES:
        return value
    return round(value / 100, 2)


def _first_action_value(actions, candidates):
    """actions — список [{"action_type":..., "value":...}, ...]. Возвращает (value, matched_type) для
    первого найденного action_type из candidates, либо (None, None)."""
    if not actions:
        return None, None
    by_type = {a.get("action_type"): a.get("value") for a in actions}
    for cand in candidates:
        if cand in by_type and by_type[cand] is not None:
            try:
                return float(by_type[cand]), cand
            except (TypeError, ValueError):
                continue
    return None, None


def _video_metric_value(field_list):
    """Поля video_p25_watch_actions и т.п. — список [{"action_type":"video_view","value":"123"}]."""
    if not field_list:
        return None
    try:
        return float(field_list[0].get("value"))
    except (TypeError, ValueError, AttributeError):
        return None


def extract_result_metric(objective: str, metrics_row: dict, optimization_goal: str = None) -> dict:
    """
    Считает "результат" и "стоимость результата" по ЦЕЛИ ОПТИМИЗАЦИИ группы (optimization_goal —
    точнее, т.к. отличает, например, "вовлечённость" от "переписок" внутри одного и того же
    objective=OUTCOME_ENGAGEMENT), а если её нет/не передана — по цели кампании (objective).
    Честно, без выдумывания. Возвращает {"label":..., "value":..., "cost_per_result":..., "roas":..., "note": "..."|None}.
    """
    if not objective and not optimization_goal:
        return {"label": None, "value": None, "cost_per_result": None, "roas": None,
                "note": "нет данных (цель кампании неизвестна)"}

    if objective in NO_RESULT_OBJECTIVES or optimization_goal in OPTIMIZATION_GOAL_NO_RESULT:
        return {"label": "Охват/CPM — см. метрики выше", "value": None, "cost_per_result": None,
                "roas": None, "note": "для цели «Узнаваемость» результатом считается охват и CPM, отдельного поля «результат» нет"}

    mapping = OPTIMIZATION_GOAL_RESULT_ACTIONS.get(optimization_goal) or OBJECTIVE_RESULT_ACTIONS.get(objective)
    if not mapping:
        goal_part = f", цель оптимизации «{optimization_goal}»" if optimization_goal else ""
        return {"label": None, "value": None, "cost_per_result": None, "roas": None,
                "note": f"нет данных (цель «{objective}»{goal_part} не сопоставлена с типом результата — не выдумываем)"}

    candidates, label = mapping
    actions = metrics_row.get("actions") or []
    cost_actions = metrics_row.get("cost_per_action_type") or []
    action_values = metrics_row.get("action_values") or []

    result_value, matched_type = _first_action_value(actions, candidates)
    cost_per_result, _ = _first_action_value(cost_actions, candidates)

    roas = None
    purchase_roas = metrics_row.get("purchase_roas")
    if objective in ("OUTCOME_SALES", "CONVERSIONS", "PRODUCT_CATALOG_SALES"):
        if purchase_roas:
            try:
                roas = float(purchase_roas[0].get("value"))
            except (TypeError, ValueError, AttributeError, IndexError):
                roas = None
        if roas is None:
            value_amt, _ = _first_action_value(action_values, candidates)
            spend = metrics_row.get("spend")
            if value_amt is not None and spend:
                try:
                    spend_f = float(spend)
                    if spend_f > 0:
                        roas = round(value_amt / spend_f, 2)
                except (TypeError, ValueError):
                    roas = None

    note = None
    if result_value is None:
        note = f"нет данных ({label.lower()}: тип результата «{'/'.join(candidates)}» не найден в ответе API — возможно, не настроен пиксель/CAPI или за период результатов нет)"
    if roas is None and objective in ("OUTCOME_SALES", "CONVERSIONS", "PRODUCT_CATALOG_SALES"):
        roas_note = "ROAS недоступен (нужна ценность конверсии — пиксель/CAPI с value)"
        note = f"{note}; {roas_note}" if note else roas_note

    return {
        "label": label,
        "value": result_value,
        "cost_per_result": cost_per_result,
        "roas": roas,
        "note": note,
    }


def campaign_optimization_goal(campaign: dict) -> str:
    """optimization_goal — поле AdSet, insights-строка кампании его не содержит напрямую, а
    extract_result_metric на уровне кампании нужен более точный сигнал, чем один только
    objective (см. OPTIMIZATION_GOAL_RESULT_ACTIONS выше). Берём самый частый optimization_goal
    среди её groups (campaign["_adsets"], уже заполнено fetch_structure/fetch_single_campaign) —
    в норме у всех групп кампании он один и тот же, "самый частый" лишь честно разруливает
    смешанные кампании, не выдумывая единственно верный ответ."""
    goals = [a.get("optimization_goal") for a in campaign.get("_adsets", []) if a.get("optimization_goal")]
    if not goals:
        return None
    return Counter(goals).most_common(1)[0][0]


def format_metrics_row(row: dict) -> dict:
    """Приводит сырую строку insights к удобным полям (без выдумывания недостающего)."""
    def f(name):
        v = row.get(name)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "spend": f("spend"),
        "impressions": f("impressions"),
        "reach": f("reach"),
        "frequency": f("frequency"),
        "cpm": f("cpm"),
        "clicks": f("clicks"),
        "link_clicks": f("inline_link_clicks"),
        "ctr": f("ctr"),
        "ctr_link": f("inline_link_click_ctr"),
        "cpc": f("cpc"),
        "cost_per_link_click": f("cost_per_inline_link_click"),
        "video_3s_views": _video_metric_value(row.get("video_30_sec_watched_actions")),
        "thruplay": _video_metric_value(row.get("video_thruplay_watched_actions")),
        "video_p25": _video_metric_value(row.get("video_p25_watch_actions")),
        "video_p50": _video_metric_value(row.get("video_p50_watch_actions")),
        "video_p75": _video_metric_value(row.get("video_p75_watch_actions")),
        "video_p100": _video_metric_value(row.get("video_p100_watch_actions")),
        "video_avg_watch_sec": _video_metric_value(row.get("video_avg_time_watched_actions")),
    }


def verify_ad_account_access(access_token: str, account_id: str) -> dict:
    """Проверка «Проверить рекламный доступ» — имя кабинета, валюта, статус, есть ли ads_read."""
    acc_id = normalize_account_id(account_id)
    if not acc_id:
        raise AdsAPIError(t("ads.msg.enter_account_id"))

    data = _get(
        f"{GRAPH_BASE}/{acc_id}",
        {
            "fields": "id,account_id,name,business_name,currency,timezone_name,account_status,amount_spent,balance,spend_cap",
            "access_token": access_token,
        },
    )

    currency = data.get("currency", "")
    status_code = data.get("account_status")
    return {
        "id": data.get("id"),
        "account_id": data.get("account_id"),
        "name": data.get("name", ""),
        "business_name": data.get("business_name", ""),
        "currency": currency,
        "timezone_name": data.get("timezone_name", ""),
        "account_status": status_code,
        "account_status_label": t(f"ads.account_status.{status_code}") if status_code in ACCOUNT_STATUS_LABELS else t("ads.account_status.unknown", code=status_code),
        "amount_spent": to_currency_units(data.get("amount_spent"), currency),
        "balance": to_currency_units(data.get("balance"), currency),
        "spend_cap": to_currency_units(data.get("spend_cap"), currency),
    }


def _fetch_all_pages(url, params, max_items=500):
    items = []
    while url and len(items) < max_items:
        data = _get(url, params)
        items.extend(data.get("data", []))
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        url = next_url
        params = None
    return items[:max_items]


CAMPAIGN_FIELDS = (
    "id,name,objective,status,effective_status,buying_type,bid_strategy,"
    "daily_budget,lifetime_budget,budget_remaining,special_ad_categories,start_time,stop_time"
)

ADSET_FIELDS = (
    "id,name,status,effective_status,daily_budget,lifetime_budget,budget_remaining,"
    "bid_amount,bid_strategy,billing_event,optimization_goal,start_time,end_time,"
    "attribution_spec,destination_type,is_dynamic_creative,"
    "targeting{age_min,age_max,genders,geo_locations,flexible_spec,custom_audiences,"
    "excluded_custom_audiences,publisher_platforms,facebook_positions,instagram_positions,"
    "device_platforms,targeting_optimization},"
    "targeting_automation{advantage_audience}"
)

AD_FIELDS = (
    "id,name,status,effective_status,created_time,"
    "creative{id,name,object_story_spec,asset_feed_spec,thumbnail_url,effective_object_story_id,"
    "effective_instagram_media_id,source_instagram_media_id,call_to_action_type}"
)


# Кабинет обычно имеет намного больше объявлений, чем кампаний/групп — N+1 запросов
# (по одному на каждую группу за объявлениями) была главной причиной, почему структура
# кабинета грузилась заметно дольше органических метрик. Ограничиваем пул, чтобы не
# упереться в rate limit Marketing API при большом кабинете.
_STRUCTURE_FETCH_WORKERS = 8


def _populate_campaign_children(access_token: str, campaign: dict) -> None:
    """Дозаполняет campaign["_adsets"][i]["_ads"] — общая логика для fetch_structure
    (весь кабинет) и fetch_single_campaign (одна кампания, этап 4d).

    Список объявлений по группам тянем ОДНИМ batch-запросом (см. _batch_get) вместо
    отдельного запроса на КАЖДУЮ группу — раньше это было N+1 запросов, выполняемых
    параллельно (до _STRUCTURE_FETCH_WORKERS одновременно), что и было главной причиной
    "Лимит запросов Meta" при кабинете с десятками групп. Пагинация внутри batch-ответа
    не поддерживается Meta — для группы с >100 объявлениями (редкость) честно берём
    только первые 100, а не тянем следующую страницу отдельным запросом."""
    adsets = _fetch_all_pages(
        f"{GRAPH_BASE}/{campaign['id']}/adsets",
        {"fields": ADSET_FIELDS, "limit": 100, "access_token": access_token},
    )
    campaign["_adsets"] = adsets
    if not adsets:
        return

    relative_urls = [f"{adset['id']}/ads?fields={AD_FIELDS}&limit=100" for adset in adsets]
    bodies = _batch_get(access_token, relative_urls)
    for adset, body in zip(adsets, bodies):
        adset["_ads"] = (body or {}).get("data", [])


def fetch_structure(access_token: str, account_id: str) -> list:
    """Кампании -> группы -> объявления, с их настройками (без метрик — метрики мержатся отдельно)."""
    acc_id = normalize_account_id(account_id)
    campaigns = _fetch_all_pages(
        f"{GRAPH_BASE}/{acc_id}/campaigns",
        {"fields": CAMPAIGN_FIELDS, "limit": 100, "access_token": access_token},
    )
    if not campaigns:
        return campaigns

    with ThreadPoolExecutor(max_workers=min(_STRUCTURE_FETCH_WORKERS, len(campaigns))) as pool:
        # Как и в _populate_campaign_children выше: _wrap_for_thread на каждую кампанию отдельно,
        # не одна обёртка на весь pool.map — иначе параллельные воркеры делят один request-контекст.
        futures = [pool.submit(_wrap_for_thread(lambda c=c: _populate_campaign_children(access_token, c))) for c in campaigns]
        for f in futures:
            f.result()
    return campaigns


def fetch_single_campaign(access_token: str, campaign_id: str) -> dict:
    """Как fetch_structure, но для одной уже известной кампании (этап 4d — рекомендации)."""
    campaign = _get(f"{GRAPH_BASE}/{campaign_id}", {"fields": CAMPAIGN_FIELDS, "access_token": access_token})
    _populate_campaign_children(access_token, campaign)
    return campaign


def fetch_ads_basic_list(access_token: str, adset_id: str) -> list:
    return _fetch_all_pages(
        f"{GRAPH_BASE}/{adset_id}/ads",
        {"fields": "id,name", "limit": 100, "access_token": access_token},
    )


def _fetch_insights_recursive(access_token, level, account_id, time_range_params, field_names):
    """Как _fetch_metrics_recursive в instagram_api.py, но бисекция по списку полей insights,
    а не по метрикам одного медиа. id-поле уровня всегда остаётся в запросе."""
    id_field = LEVEL_ID_FIELD[level]
    fields = f"{id_field}," + ",".join(field_names)
    params = {
        "level": level,
        "fields": fields,
        "limit": 200,
        "access_token": access_token,
        **time_range_params,
    }
    data, error = _get_raw(f"{GRAPH_BASE}/{account_id}/insights", params)

    if not error:
        rows_by_id = {}
        unsupported = {}
        all_rows = data.get("data", [])
        next_url = data.get("paging", {}).get("next")
        while next_url:
            page_data, page_error = _get_raw(next_url)
            if page_error:
                break
            all_rows.extend(page_data.get("data", []))
            next_url = page_data.get("paging", {}).get("next")
        for row in all_rows:
            rows_by_id[row.get(id_field)] = row
        return rows_by_id, unsupported

    message = error.get("message", "Метрика недоступна")
    if len(field_names) == 1:
        return {}, {field_names[0]: message}

    mid = len(field_names) // 2
    left_rows, left_unsupported = _fetch_insights_recursive(
        access_token, level, account_id, time_range_params, field_names[:mid]
    )
    right_rows, right_unsupported = _fetch_insights_recursive(
        access_token, level, account_id, time_range_params, field_names[mid:]
    )
    merged_rows = {
        entity_id: {**left_rows.get(entity_id, {}), **right_rows.get(entity_id, {})}
        for entity_id in set(left_rows) | set(right_rows)
    }
    return merged_rows, {**left_unsupported, **right_unsupported}


def fetch_insights_by_level(access_token: str, account_id: str, level: str, time_range_params: dict):
    """Возвращает (rows_by_id, unsupported_fields_reasons)."""
    acc_id = normalize_account_id(account_id)
    return _fetch_insights_recursive(access_token, level, acc_id, time_range_params, INSIGHT_METRIC_FIELDS)


def build_time_range_params(period: str, date_from: str = None, date_to: str = None) -> dict:
    if period == "custom":
        if not date_from or not date_to:
            raise AdsAPIError(t("ads.msg.custom_period_needs_dates"))
        return {"time_range": f'{{"since":"{date_from}","until":"{date_to}"}}'}
    if period in DATE_PRESETS:
        return {"date_preset": period}
    raise AdsAPIError(t("ads.msg.unknown_period", period=period))


PERIOD_PRESET_DAYS = {"today": 1, "last_7d": 7, "last_14d": 14, "last_30d": 30, "maximum": 90}


def estimate_period_days(period: str, date_from: str = None, date_to: str = None):
    """Грубая оценка длины анализируемого периода в днях — нужна только для защиты от
    выводов на слишком короткой выборке (см. MIN_PERIOD_DAYS в app/ads_audience.py).
    None, если period нераспознан — вызывающий код не должен считать это "коротким периодом"."""
    if period == "custom" and date_from and date_to:
        try:
            d1 = datetime.strptime(date_from, "%Y-%m-%d")
            d2 = datetime.strptime(date_to, "%Y-%m-%d")
            return (d2 - d1).days + 1
        except ValueError:
            return None
    return PERIOD_PRESET_DAYS.get(period)


def format_targeting(targeting: dict, targeting_automation: dict = None) -> dict:
    targeting = targeting or {}

    genders = targeting.get("genders") or []
    if not genders or set(genders) == {1, 2}:
        gender_label = "Все"
    elif genders == [1]:
        gender_label = "Мужчины"
    elif genders == [2]:
        gender_label = "Женщины"
    else:
        gender_label = str(genders)

    age_min = targeting.get("age_min")
    age_max = targeting.get("age_max")
    if age_min or age_max:
        age_label = f"{age_min or '?'}–{age_max or '?'}"
        advantage_audience = (targeting_automation or {}).get("advantage_audience")
        if advantage_audience in (1, "1", True):
            age_label += " · Advantage+ розширює заданий вік, максимум не жорсткий"
    else:
        age_label = "не задано"

    geo = targeting.get("geo_locations") or {}
    geo_parts = []
    for key, label in (("countries", None), ("regions", "name"), ("cities", "name"), ("geo_markets", "name")):
        vals = geo.get(key)
        if not vals:
            continue
        if label:
            geo_parts.extend([v.get(label, "") for v in vals if isinstance(v, dict)])
        else:
            geo_parts.extend(vals)
    geo_label = ", ".join(str(p) for p in geo_parts if p) or "не задано"

    interests = []
    for group in targeting.get("flexible_spec") or []:
        for interest in group.get("interests") or []:
            name = interest.get("name")
            if name and name not in interests:
                interests.append(name)
    interests_note = None
    if len(targeting.get("flexible_spec") or []) > 1:
        interests_note = "объединены интересы из нескольких групп таргетинга (AND/OR группы упрощены в один список)"

    custom_audiences = []
    lookalike_audiences = []
    for aud in targeting.get("custom_audiences") or []:
        name = aud.get("name", aud.get("id", "?"))
        if (aud.get("subtype") or "").upper() == "LOOKALIKE":
            lookalike_audiences.append(name)
        else:
            custom_audiences.append(name)

    has_manual_placement = any(
        targeting.get(k) for k in ("publisher_platforms", "facebook_positions", "instagram_positions", "device_platforms")
    )
    if has_manual_placement:
        placement_label = "Ручные: " + ", ".join(
            filter(None, [
                "платформы " + "/".join(targeting.get("publisher_platforms", [])) if targeting.get("publisher_platforms") else "",
                "плейсменты FB " + "/".join(targeting.get("facebook_positions", [])) if targeting.get("facebook_positions") else "",
                "плейсменты IG " + "/".join(targeting.get("instagram_positions", [])) if targeting.get("instagram_positions") else "",
                "устройства " + "/".join(targeting.get("device_platforms", [])) if targeting.get("device_platforms") else "",
            ])
        )
    else:
        placement_label = "Авто (Advantage+ / расширенные плейсменты)"

    return {
        "age": age_label,
        "gender": gender_label,
        "geo": geo_label,
        "interests": interests,
        "interests_note": interests_note,
        "custom_audiences": custom_audiences,
        "lookalike_audiences": lookalike_audiences,
        "placement": placement_label,
    }


def format_attribution(attribution_spec) -> str:
    if not attribution_spec:
        return "не задано (нет данных)"
    parts = []
    labels = {"CLICK_THROUGH": "клик", "VIEW_THROUGH": "показ"}
    for spec in attribution_spec:
        event = labels.get(spec.get("event_type"), spec.get("event_type", "?"))
        days = spec.get("window_days", "?")
        parts.append(f"{days}-дн. {event}")
    return " + ".join(parts)


_ASSET_FEED_FORMAT_LABELS = {
    "SINGLE_VIDEO": "video",
    "CAROUSEL_IMAGE": "carousel",
    "CAROUSEL_VIDEO": "carousel",
    "CAROUSEL": "carousel",
    "SINGLE_IMAGE": "image",
    "COLLECTION": "collection",
    "AUTOMATED_SHOPPING_ADS": "collection",
}


def _detect_asset_feed_format(asset_feed: dict) -> str:
    """asset_feed_spec.ad_formats — самый прямой сигнал (Advantage+/динамический креатив
    сам говорит, каким форматом показывается), но бывает пустым — тогда угадываем по
    фактически присутствующим медиа-полям, а не отдаём "dynamic" без уточнения."""
    for raw in asset_feed.get("ad_formats") or []:
        label = _ASSET_FEED_FORMAT_LABELS.get(raw)
        if label:
            return label
    if asset_feed.get("videos"):
        return "video"
    images = asset_feed.get("images") or []
    if len(images) > 1:
        return "carousel"
    if images:
        return "image"
    return "dynamic"


def _cta_type_from_asset_feed(asset_feed: dict):
    for cta in asset_feed.get("call_to_action_types") or []:
        cta_type = cta.get("type") if isinstance(cta, dict) else cta
        if cta_type:
            return cta_type
    return None


def _link_from_asset_feed(asset_feed: dict):
    for link_url in asset_feed.get("link_urls") or []:
        link = link_url.get("website_url") or link_url.get("display_url")
        if link:
            return link
    return None


def _guess_format_from_creative(creative: dict) -> str:
    """Последний резерв, когда ни одна известная структура не распозналась (или сама Meta
    не отдала ничего, кроме id) — определяем формат по фактически присутствующим полям,
    а не оставляем "unknown", которое пользователю ничего не говорит."""
    story = creative.get("object_story_spec") or {}
    if story.get("video_data"):
        return "video"
    link_data = story.get("link_data") or {}
    if link_data.get("child_attachments"):
        return "carousel"
    if link_data:
        return "image"
    if story.get("photo_data"):
        return "image"
    asset_feed = creative.get("asset_feed_spec") or {}
    if asset_feed.get("videos"):
        return "video"
    images = asset_feed.get("images") or []
    if len(images) > 1:
        return "carousel"
    if images:
        return "image"
    return "unknown"


_IG_MEDIA_TYPE_FORMAT = {"VIDEO": "video", "CAROUSEL_ALBUM": "carousel", "IMAGE": "image"}


def _fetch_instagram_media_for_creative(access_token: str, media_id: str) -> dict:
    """Резервный путь №1: объявление продвигает уже опубликованный Instagram-пост/Reels
    напрямую (без object_story_spec/asset_feed_spec) — этот узел читается ТЕМ ЖЕ токеном,
    что и вся остальная органика (instagram_basic/instagram_manage_insights, уже выданы), в
    отличие от effective_object_story_id (Facebook Page-пост), который на практике требует
    ОТДЕЛЬНОГО разрешения pages_read_engagement, которого у этого проекта чаще всего нет —
    поэтому пробуем Instagram-медиа ПЕРВЫМ, а Page-пост вторым (см. _fetch_object_story_post)."""
    try:
        return _get(
            f"{GRAPH_BASE}/{media_id}",
            {
                "fields": "caption,media_type,media_product_type,permalink,thumbnail_url,media_url",
                "access_token": access_token,
            },
        ) or {}
    except AdsAPIError:
        return {}


def _format_from_instagram_media(media: dict, creative: dict, top_cta_type) -> dict:
    fmt = _IG_MEDIA_TYPE_FORMAT.get(media.get("media_type"), "unknown")
    return {
        "type": fmt,
        "primary_text": media.get("caption"),
        "headline": None,
        "cta": CTA_LABELS.get(top_cta_type, top_cta_type) if top_cta_type else None,
        "link": media.get("permalink"),
        "thumbnail_url": media.get("thumbnail_url") or media.get("media_url") or creative.get("thumbnail_url"),
        "note": "Креатив собран из уже опубликованного Instagram-поста — данные (текст/формат) взяты из самого поста, а не из настроек объявления.",
    }


def _fetch_object_story_post(access_token: str, object_story_id: str) -> dict:
    """Резервный путь №2 для объявлений, собранных из УЖЕ существующего Facebook Page-поста
    через effective_object_story_id (например, "продвижение публикации" не через
    object_story_spec/asset_feed_spec, и нет привязанного Instagram-медиа) — в самом creative
    тогда нет ни текста, ни медиа, их нужно взять напрямую с самого поста. На практике этот
    запрос требует разрешения pages_read_engagement — если его нет, Meta вернёт ошибку (#10),
    честно ловим её и идём в последний резерв (_guess_format_from_creative)."""
    try:
        return _get(
            f"{GRAPH_BASE}/{object_story_id}",
            {
                "fields": "message,full_picture,permalink_url,"
                          "attachments{media_type,title,unshimmed_url,url,subattachments}",
                "access_token": access_token,
            },
        ) or {}
    except AdsAPIError:
        return {}


def _format_from_post(post: dict, creative: dict, top_cta_type) -> dict:
    attachments = ((post.get("attachments") or {}).get("data")) or []
    first = attachments[0] if attachments else {}
    sub_attachments = ((first.get("subattachments") or {}).get("data")) or []
    media_type = (first.get("media_type") or "").lower()
    if "video" in media_type:
        fmt = "video"
    elif sub_attachments or media_type == "album":
        fmt = "carousel"
    elif media_type:
        fmt = "image"
    else:
        fmt = "unknown"
    return {
        "type": fmt,
        "primary_text": post.get("message"),
        "headline": first.get("title"),
        "cta": CTA_LABELS.get(top_cta_type, top_cta_type) if top_cta_type else None,
        "link": first.get("unshimmed_url") or first.get("url") or post.get("permalink_url"),
        "thumbnail_url": post.get("full_picture") or creative.get("thumbnail_url"),
        "note": "Креатив собран из уже опубликованного поста (effective_object_story_id) — данные взяты из самого поста, а не из настроек объявления.",
    }


def format_creative(creative: dict, access_token: str = None) -> dict:
    """Текст/заголовок/CTA/формат объявления — Meta хранит их в РАЗНЫХ структурах в
    зависимости от того, как объявление было собрано (см. модульный докстринг ads_api.py про
    единицы измерения — та же логика "честно, без выдумывания" здесь про сами поля):
    - object_story_spec (video_data/link_data/photo_data) — обычное объявление, собранное
      через Ads Manager/API с нуля;
    - asset_feed_spec — Advantage+/динамический креатив (несколько вариантов текста/медиа,
      Meta сама ротирует);
    - ни то ни другое, но есть effective_object_story_id — объявление "продвигает" уже
      существующий пост, тогда текст/медиа нужно тянуть с самого поста (см.
      _fetch_object_story_post), а не из creative;
    - если и этого нет — последний резерв: угадываем формат по тому, что фактически
      присутствует в ответе (_guess_format_from_creative), вместо голого "unknown"."""
    creative = creative or {}
    story = creative.get("object_story_spec") or {}
    asset_feed = creative.get("asset_feed_spec")
    top_cta_type = creative.get("call_to_action_type")

    video_data = story.get("video_data")
    link_data = story.get("link_data")
    photo_data = story.get("photo_data")

    if video_data:
        cta = video_data.get("call_to_action") or {}
        cta_type = cta.get("type") or top_cta_type
        return {
            "type": "video",
            "primary_text": video_data.get("message"),
            "headline": video_data.get("title"),
            "cta": CTA_LABELS.get(cta_type, cta_type),
            "link": (cta.get("value") or {}).get("link"),
            "thumbnail_url": video_data.get("image_url") or creative.get("thumbnail_url"),
            "note": None,
        }

    if link_data:
        cta = link_data.get("call_to_action") or {}
        cta_type = cta.get("type") or top_cta_type
        return {
            "type": "carousel" if link_data.get("child_attachments") else "image",
            "primary_text": link_data.get("message"),
            "headline": link_data.get("name"),
            "cta": CTA_LABELS.get(cta_type, cta_type),
            "link": (cta.get("value") or {}).get("link") or link_data.get("link"),
            "thumbnail_url": link_data.get("picture") or creative.get("thumbnail_url"),
            "note": None,
        }

    if photo_data:
        cta = photo_data.get("call_to_action") or {}
        cta_type = cta.get("type") or top_cta_type
        return {
            "type": "image",
            "primary_text": photo_data.get("caption"),
            "headline": None,
            "cta": CTA_LABELS.get(cta_type, cta_type),
            "link": (cta.get("value") or {}).get("link") or photo_data.get("url"),
            "thumbnail_url": photo_data.get("url") or creative.get("thumbnail_url"),
            "note": None,
        }

    if asset_feed:
        bodies = asset_feed.get("bodies") or []
        titles = asset_feed.get("titles") or []
        cta_type = _cta_type_from_asset_feed(asset_feed) or top_cta_type
        variants_note = None
        if len(bodies) > 1 or len(titles) > 1:
            variants_note = (
                f"Динамический креатив (Advantage+): {len(bodies)} вариант(ов) текста, "
                f"{len(titles)} вариант(ов) заголовка — показан первый, остальные ротируются автоматически"
            )
        return {
            "type": _detect_asset_feed_format(asset_feed),
            "primary_text": bodies[0].get("text") if bodies else None,
            "headline": titles[0].get("text") if titles else None,
            "cta": CTA_LABELS.get(cta_type, cta_type),
            "link": _link_from_asset_feed(asset_feed),
            "thumbnail_url": creative.get("thumbnail_url"),
            "note": variants_note,
        }

    media_id = creative.get("effective_instagram_media_id") or creative.get("source_instagram_media_id")
    object_story_id = creative.get("effective_object_story_id")
    tried_existing_post = bool(media_id or object_story_id)

    if media_id and access_token:
        media = _fetch_instagram_media_for_creative(access_token, media_id)
        if media:
            return _format_from_instagram_media(media, creative, top_cta_type)

    if object_story_id and access_token:
        post = _fetch_object_story_post(access_token, object_story_id)
        if post:
            return _format_from_post(post, creative, top_cta_type)

    return {
        "type": _guess_format_from_creative(creative),
        "primary_text": None,
        "headline": None,
        "cta": CTA_LABELS.get(top_cta_type, top_cta_type) if top_cta_type else None,
        "link": None,
        "thumbnail_url": creative.get("thumbnail_url"),
        "note": (
            "нет данных текста/заголовка (объявление собрано из существующего поста, но "
            "получить сам пост не удалось — нет доступа/поста больше нет)" if tried_existing_post else
            "нет данных текста/заголовка — формат определён по фактически присутствующим полям креатива"
        ),
    }


def _fetch_breakdown_page(access_token: str, entity_id: str, dimension: str, field_names: list, time_range_params: dict):
    """Один insights-запрос с конкретным breakdown'ом и конкретным набором полей, с пагинацией.
    Возвращает (rows, error_message_or_None)."""
    params = {
        "breakdowns": dimension,
        "fields": ",".join(field_names),
        "limit": 200,
        "access_token": access_token,
        **time_range_params,
    }
    data, error = _get_raw(f"{GRAPH_BASE}/{entity_id}/insights", params)
    if error:
        return None, error.get("message", "Разбивка недоступна")

    rows = data.get("data", [])
    next_url = data.get("paging", {}).get("next")
    while next_url:
        page, page_error = _get_raw(next_url)
        if page_error:
            break
        rows.extend(page.get("data", []))
        next_url = page.get("paging", {}).get("next")
    return rows, None


def fetch_breakdown(access_token: str, entity_id: str, dimension: str, time_range_params: dict):
    """Одна разбивка (age/gender/country/platform_position/...) для конкретной кампании/группы.
    Возвращает (rows, error_message_or_None) — ошибка не бросается, чтобы одна неподдерживаемая
    разбивка не срывала остальные шесть.

    Для breakdown'ов "доставки" (см. DELIVERY_BREAKDOWNS) Meta не разрешает получить
    action_type-based поля (actions/cost_per_action_type/action_values/purchase_roas/video_*)
    вместе с самим breakdown'ом — падает (#100) "Invalid parameter" про недопустимую комбинацию
    (action_type, <breakdown>), и это НЕ лечится простым разделением на два запроса: у
    "platform_position"/"impression_device" самих по себе с action_type вообще нет валидной
    комбинации (см. DELIVERY_BREAKDOWN_COMPANION) — Meta требует запрашивать их ВМЕСТЕ с
    publisher_platform. Поэтому для этих breakdown'ов оба запроса (базовый и action-полей)
    идут с составным breakdowns=publisher_platform,<dimension>, и строки мержатся по паре
    (publisher_platform, dimension), а не только по dimension."""
    if dimension not in DELIVERY_BREAKDOWNS:
        return _fetch_breakdown_page(access_token, entity_id, dimension, DETAIL_FIELDS, time_range_params)

    companion = DELIVERY_BREAKDOWN_COMPANION.get(dimension)
    breakdown_param = f"{companion},{dimension}" if companion else dimension

    def _row_key(row):
        return (row.get(companion), row.get(dimension)) if companion else row.get(dimension)

    base_rows, base_error = _fetch_breakdown_page(access_token, entity_id, breakdown_param, BASE_BREAKDOWN_FIELDS, time_range_params)
    if base_error:
        return None, base_error

    action_rows, action_error = _fetch_breakdown_page(access_token, entity_id, breakdown_param, ACTION_BREAKDOWN_FIELDS, time_range_params)
    # Если результаты/действия всё равно недоступны для этой разбивки — честно отдаём только
    # базовые метрики (extract_result_metric сам скажет «нет данных» там, где нет actions).
    action_by_key = {_row_key(row): row for row in (action_rows or [])} if not action_error else {}

    merged_rows = [{**row, **action_by_key.get(_row_key(row), {})} for row in base_rows]
    return merged_rows, None


def format_breakdown_row(row: dict, dimension: str, objective: str, optimization_goal: str = None) -> dict:
    companion = DELIVERY_BREAKDOWN_COMPANION.get(dimension)
    label = row.get(dimension) or "нет данных"
    if companion and row.get(companion):
        label = f"{row[companion]} / {label}"
    return {
        "label": label,
        "metrics": format_metrics_row(row),
        "result": extract_result_metric(objective, row, optimization_goal),
    }


def fetch_all_breakdowns(access_token: str, entity_id: str, objective: str, time_range_params: dict, optimization_goal: str = None):
    """Возвращает (breakdowns_by_dimension, unsupported_reasons) — честно пропускает разбивки,
    которые Meta не отдаёт для этой ноды/периода, не роняя остальные."""
    breakdowns = {}
    unsupported = {}
    for dimension in BREAKDOWN_DIMENSIONS:
        rows, error = fetch_breakdown(access_token, entity_id, dimension, time_range_params)
        if error:
            unsupported[dimension] = error
            continue
        breakdowns[dimension] = [format_breakdown_row(row, dimension, objective, optimization_goal) for row in rows]
    return breakdowns, unsupported


def fetch_timeseries(access_token: str, entity_id: str, objective: str, time_range_params: dict, time_increment: int = 1, optimization_goal: str = None) -> list:
    """Дневная (или недельная) динамика по одной кампании/группе — для графиков и сатурации."""
    params = {
        "time_increment": time_increment,
        "fields": ",".join(DETAIL_FIELDS),
        "limit": 500,
        "access_token": access_token,
        **time_range_params,
    }
    data, error = _get_raw(f"{GRAPH_BASE}/{entity_id}/insights", params)
    if error:
        raise AdsAPIError(error.get("message", t("ads.msg.timeseries_unavailable")))

    rows = data.get("data", [])
    next_url = data.get("paging", {}).get("next")
    while next_url:
        page, page_error = _get_raw(next_url)
        if page_error:
            break
        rows.extend(page.get("data", []))
        next_url = page.get("paging", {}).get("next")

    rows.sort(key=lambda r: r.get("date_start", ""))
    return [
        {
            "date_start": row.get("date_start"),
            "date_stop": row.get("date_stop"),
            "metrics": format_metrics_row(row),
            "result": extract_result_metric(objective, row, optimization_goal),
        }
        for row in rows
    ]


def _trend_for_field(first_half: list, second_half: list, field: str, lower_is_better: bool) -> dict:
    def avg(rows):
        vals = [r["metrics"].get(field) for r in rows if r["metrics"].get(field) is not None]
        return sum(vals) / len(vals) if vals else None

    before, after = avg(first_half), avg(second_half)
    if before is None or after is None or before == 0:
        return {"direction": None, "direction_label": None, "change_pct": None, "note": t("common.no_data")}

    change_pct = round((after - before) / before * 100, 1)
    if abs(change_pct) < 10:
        direction = "stable"
    elif (change_pct > 0) == (not lower_is_better):
        direction = "improving"
    else:
        direction = "worsening"
    return {"direction": direction, "direction_label": t(f"ads.trend.{direction}"), "change_pct": change_pct, "note": None}


def compute_trend(daily_rows: list) -> dict:
    """Честный сигнал сатурации: сравнивает среднее 1-й и 2-й половины периода —
    без предсказаний, без сглаживания, без выдумывания тренда там, где данных мало."""
    if len(daily_rows) < 4:
        return {"available": False, "note": t("ads.trend.msg.period_too_short")}

    mid = len(daily_rows) // 2
    first_half, second_half = daily_rows[:mid], daily_rows[mid:]

    frequency_trend = _trend_for_field(first_half, second_half, "frequency", lower_is_better=True)
    ctr_trend = _trend_for_field(first_half, second_half, "ctr", lower_is_better=False)
    cpm_trend = _trend_for_field(first_half, second_half, "cpm", lower_is_better=True)

    saturation_note = None
    if frequency_trend["direction"] == "worsening" and ctr_trend["direction"] == "worsening":
        saturation_note = t("ads.trend.msg.saturation_freq_and_ctr")
    elif frequency_trend["direction"] == "worsening":
        saturation_note = t("ads.trend.msg.saturation_freq_only")

    return {
        "available": True,
        "frequency": frequency_trend,
        "ctr": ctr_trend,
        "cpm": cpm_trend,
        "saturation_note": saturation_note,
    }


FATIGUE_FREQUENCY_THRESHOLD = 2.5
FATIGUE_CTR_DROP = 0.15   # CTR ниже базовой линии на >15%
FATIGUE_CPM_RISE = 0.15   # CPM выше базовой линии на >15%
FATIGUE_BASELINE_DAYS = 3


def detect_creative_fatigue(daily_rows: list) -> dict:
    """
    Этап 4c: усталость крео = частота ≥2.5 (TZ: ">2-3") + CTR упал от базового уровня + CPM вырос
    от базового уровня, одновременно, в один и тот же день. Базовый уровень — среднее по первым
    FATIGUE_BASELINE_DAYS дням периода. Возвращает первый день, где все три условия совпали
    (не последний — TZ просит "с какого дня началось падение").
    Честно: короткий период / нет CTR-CPM в начале периода -> "нет данных", не гадаем.
    """
    if len(daily_rows) < FATIGUE_BASELINE_DAYS + 1:
        return {
            "fatigued": False,
            "since_date": None,
            "reason": None,
            "note": t("ads.fatigue.msg.period_too_short", days=FATIGUE_BASELINE_DAYS + 1),
        }

    baseline_rows = daily_rows[:FATIGUE_BASELINE_DAYS]

    def avg(rows, field):
        vals = [r["metrics"].get(field) for r in rows if r["metrics"].get(field) is not None]
        return sum(vals) / len(vals) if vals else None

    baseline_ctr = avg(baseline_rows, "ctr")
    baseline_cpm = avg(baseline_rows, "cpm")

    if baseline_ctr is None or baseline_cpm is None:
        return {
            "fatigued": False,
            "since_date": None,
            "reason": None,
            "note": t("ads.fatigue.msg.no_baseline"),
        }

    for row in daily_rows[FATIGUE_BASELINE_DAYS:]:
        freq = row["metrics"].get("frequency")
        ctr = row["metrics"].get("ctr")
        cpm = row["metrics"].get("cpm")
        if freq is None or ctr is None or cpm is None:
            continue
        if (
            freq >= FATIGUE_FREQUENCY_THRESHOLD
            and ctr <= baseline_ctr * (1 - FATIGUE_CTR_DROP)
            and cpm >= baseline_cpm * (1 + FATIGUE_CPM_RISE)
        ):
            return {
                "fatigued": True,
                "since_date": row["date_start"],
                "reason": t(
                    "ads.fatigue.msg.reason",
                    freq_threshold=FATIGUE_FREQUENCY_THRESHOLD,
                    ctr_drop_pct=int(FATIGUE_CTR_DROP * 100),
                    cpm_rise_pct=int(FATIGUE_CPM_RISE * 100),
                ),
                "note": None,
            }

    return {"fatigued": False, "since_date": None, "reason": None, "note": None}


def _with_video_rates(daily_rows: list) -> list:
    """hook_rate/thruplay_rate — доля показов, досмотренных ≥3с / до ThruPlay. Честно: если у
    объявления нет видео (video_3s_views всегда None), ставим None, а не 0."""
    enriched = []
    for row in daily_rows:
        metrics = dict(row["metrics"])
        impressions = metrics.get("impressions")
        video_3s = metrics.get("video_3s_views")
        thruplay = metrics.get("thruplay")
        metrics["hook_rate"] = round(video_3s / impressions * 100, 2) if (impressions and video_3s is not None) else None
        metrics["thruplay_rate"] = round(thruplay / impressions * 100, 2) if (impressions and thruplay is not None) else None
        enriched.append({**row, "metrics": metrics})
    return enriched


def compute_video_trend(daily_rows: list) -> dict:
    """Второй сигнал усталости из TZ: "Hook rate / ThruPlay снижается со временем" —
    для не-видео объявлений честно возвращает "нет данных", а не 0%."""
    enriched = _with_video_rates(daily_rows)
    if len(enriched) < 4:
        return {"available": False, "note": t("ads.trend.msg.period_too_short_short")}

    mid = len(enriched) // 2
    first_half, second_half = enriched[:mid], enriched[mid:]

    hook_trend = _trend_for_field(first_half, second_half, "hook_rate", lower_is_better=False)
    thruplay_trend = _trend_for_field(first_half, second_half, "thruplay_rate", lower_is_better=False)

    if hook_trend["direction"] is None and thruplay_trend["direction"] is None:
        return {"available": False, "note": t("ads.trend.msg.no_video_metrics")}

    return {"available": True, "hook_rate": hook_trend, "thruplay_rate": thruplay_trend}


AD_DIAGNOSTIC_FIELDS = DETAIL_FIELDS + RANKING_FIELDS


def fetch_learning_stage(access_token: str, adset_id: str):
    """Статус фазы обучения группы (LEARNING / LEARNING_LIMITED / SUCCESS) — отдельный
    необязательный запрос на ноду AdSet. LEARNING_LIMITED — прямой сигнал Meta о том, что
    аудитория слишком узкая или конверсий мало для выхода из обучения. Не роняем остальной
    анализ, если поле недоступно — просто честно возвращаем None."""
    try:
        data = _get(f"{GRAPH_BASE}/{adset_id}", {"fields": "learning_stage_info", "access_token": access_token})
    except AdsAPIError:
        return None
    info = data.get("learning_stage_info") or {}
    return info.get("status")


def fetch_adset_targeting(access_token: str, adset_id: str) -> dict:
    """Имя, сырой targeting и optimization_goal группы — targeting для сравнения выигрышного
    сегмента с настроенным таргетингом, optimization_goal для честного extract_result_metric
    (см. OPTIMIZATION_GOAL_RESULT_ACTIONS) в местах, куда группа приходит только по id
    (без всего дерева fetch_structure, где optimization_goal уже есть в самой группе)."""
    data = _get(
        f"{GRAPH_BASE}/{adset_id}",
        {"fields": "name,targeting,targeting_automation{advantage_audience},optimization_goal", "access_token": access_token},
    )
    return {
        "name": data.get("name", ""),
        "targeting": data.get("targeting") or {},
        "targeting_automation": data.get("targeting_automation") or {},
        "optimization_goal": data.get("optimization_goal"),
    }


def fetch_entity_metrics(access_token: str, entity_id: str, time_range_params: dict):
    """Один агрегированный ряд метрик за период (без breakdowns, без time_increment) —
    для группы/кампании целиком. Возвращает (raw_row_or_None, error_message_or_None)."""
    params = {"fields": ",".join(DETAIL_FIELDS), "access_token": access_token, **time_range_params}
    data, error = _get_raw(f"{GRAPH_BASE}/{entity_id}/insights", params)
    if error:
        return None, error.get("message", t("ads.msg.metrics_unavailable"))
    rows = data.get("data", [])
    return (rows[0] if rows else None), None


def fetch_ad_creative_detail(access_token: str, ad_id: str) -> dict:
    """creative (текст/заголовок/CTA) + ID органічного Instagram-медіа одного оголошення —
    окремий вузький запит (не поле в /structure), потрібен лише для панелі вердикту крео.
    Міст до транскрипту органічного Reels (data/transcripts.json, app/transcription.py),
    якщо ця реклама була запущена з опублікованого поста.

    source_instagram_media_id/effective_instagram_media_id — поля AdCreative, а НЕ Ad
    (запит "id,source_instagram_media_id,creative{...}" на ноду Ad падає (#100) "Tried
    accessing nonexisting field" — цього поля просто нема на рівні Ad). Тягнемо обидва
    прямо всередині creative{...}: effective_instagram_media_id — це вже resolved-значення
    Meta (як і effective_object_story_id вище), тому пріоритетне; source_instagram_media_id —
    запасний варіант, якщо effective з якоїсь причини порожній."""
    data = _get(
        f"{GRAPH_BASE}/{ad_id}",
        {
            "fields": "id,"
                      "creative{id,name,object_story_spec,asset_feed_spec,thumbnail_url,"
                      "effective_object_story_id,effective_instagram_media_id,source_instagram_media_id,"
                      "call_to_action_type}",
            "access_token": access_token,
        },
    )
    creative_raw = data.get("creative") or {}
    media_id = creative_raw.get("effective_instagram_media_id") or creative_raw.get("source_instagram_media_id")
    return {
        "creative": format_creative(creative_raw, access_token=access_token),
        "source_instagram_media_id": media_id,
    }


def _diagnostics_from_row(objective: str, row: dict, optimization_goal: str = None) -> dict:
    return {
        "metrics": format_metrics_row(row),
        "result": extract_result_metric(objective, row, optimization_goal),
        "rankings": {
            "quality": _ranking_label(row.get("quality_ranking")),
            "engagement_rate": _ranking_label(row.get("engagement_rate_ranking")),
            "conversion_rate": _ranking_label(row.get("conversion_rate_ranking")),
            "quality_code": row.get("quality_ranking"),
            "engagement_rate_code": row.get("engagement_rate_ranking"),
            "conversion_rate_code": row.get("conversion_rate_ranking"),
        },
    }


def fetch_ad_diagnostics(access_token: str, ad_id: str, objective: str, time_range_params: dict, optimization_goal: str = None):
    """Метрики + результат + ranking-диагностика одного объявления за период.
    Возвращает (dict_or_None, error_message_or_None).
    Точечный запрос — там, где нужно ровно одно объявление. Для целой группы (несколько
    объявлений подряд — вердикт крео, аудитория, рекомендации) используй
    fetch_ad_diagnostics_by_adset(): один запрос на всю группу вместо N запросов по каждому
    ad_id — именно повторные точечные вызовы на каждое крео упирались в лимит запросов Meta."""
    params = {"fields": ",".join(AD_DIAGNOSTIC_FIELDS), "access_token": access_token, **time_range_params}
    data, error = _get_raw(f"{GRAPH_BASE}/{ad_id}/insights", params)
    if error:
        return None, error.get("message", t("ads.msg.diagnostics_unavailable"))
    rows = data.get("data", [])
    row = rows[0] if rows else {}
    return _diagnostics_from_row(objective, row, optimization_goal), None


def fetch_ad_diagnostics_by_adset(access_token: str, adset_id: str, objective: str, time_range_params: dict, optimization_goal: str = None):
    """То же, что fetch_ad_diagnostics(), но сразу для ВСЕХ объявлений группы одним запросом
    (level=ad на ноду adset) — вместо отдельного /insights на каждое ad_id. Раньше разбор
    группы с несколькими крео (вердикт крео, аудитория, рекомендации) делал по запросу на
    каждое объявление параллельно, что и упиралось в "User request limit reached" на
    аккаунтах с большим числом креативов. Возвращает (rows_by_ad_id, error_message_or_None)."""
    params = {
        "level": "ad",
        "fields": "ad_id," + ",".join(AD_DIAGNOSTIC_FIELDS),
        "limit": 500,
        "access_token": access_token,
        **time_range_params,
    }
    data, error = _get_raw(f"{GRAPH_BASE}/{adset_id}/insights", params)
    if error:
        return {}, error.get("message", t("ads.msg.diagnostics_unavailable"))

    rows = data.get("data", [])
    next_url = data.get("paging", {}).get("next")
    while next_url:
        page, page_error = _get_raw(next_url)
        if page_error:
            break
        rows.extend(page.get("data", []))
        next_url = page.get("paging", {}).get("next")

    return {row.get("ad_id"): _diagnostics_from_row(objective, row, optimization_goal) for row in rows if row.get("ad_id")}, None


def fetch_timeseries_by_adset(access_token: str, adset_id: str, objective: str, time_range_params: dict, time_increment: int = 1, optimization_goal: str = None):
    """Дневная динамика сразу по ВСЕМ объявлениям группы одним запросом (level=ad + тот же
    time_increment, что и fetch_timeseries) — вместо отдельного timeseries-запроса на каждое
    креативо (см. fetch_ad_diagnostics_by_adset — та же причина: лимит запросов Meta при
    разборе группы с несколькими крео). Возвращает {ad_id: [daily_row, ...], ...}, где
    daily_row — в том же формате, что и элементы списка из fetch_timeseries()."""
    params = {
        "level": "ad",
        "time_increment": time_increment,
        "fields": "ad_id," + ",".join(DETAIL_FIELDS),
        "limit": 1000,
        "access_token": access_token,
        **time_range_params,
    }
    data, error = _get_raw(f"{GRAPH_BASE}/{adset_id}/insights", params)
    if error:
        raise AdsAPIError(error.get("message", t("ads.msg.timeseries_unavailable")))

    rows = data.get("data", [])
    next_url = data.get("paging", {}).get("next")
    while next_url:
        page, page_error = _get_raw(next_url)
        if page_error:
            break
        rows.extend(page.get("data", []))
        next_url = page.get("paging", {}).get("next")

    by_ad = defaultdict(list)
    for row in rows:
        ad_id = row.get("ad_id")
        if ad_id:
            by_ad[ad_id].append(row)

    result = {}
    for ad_id, ad_rows in by_ad.items():
        ad_rows.sort(key=lambda r: r.get("date_start", ""))
        result[ad_id] = [
            {
                "date_start": r.get("date_start"),
                "date_stop": r.get("date_stop"),
                "metrics": format_metrics_row(r),
                "result": extract_result_metric(objective, r, optimization_goal),
            }
            for r in ad_rows
        ]
    return result
