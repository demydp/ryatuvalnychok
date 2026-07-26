"""
Классификация типа хука (первой фразы рилса) через Claude — вызывается ТОЛЬКО когда
простые ключевые правила (вопрос/цифра/провокация/боль) не дали уверенного ответа.

Модель — Haiku: самая дешёвая и быстрая в линейке Claude, для короткой классификации
в одно слово этого достаточно. Промпт + хук обычно укладываются в ~150-250 входных
токенов, ответ — 1 слово (макс. 10 токенов). При цене Haiku $1/$5 за 1М токенов
классификация одного хука стоит долю цента (см. hook_classification_cost_estimate).
"""
import anthropic

MODEL_ID = "claude-haiku-4-5"
INPUT_PRICE_PER_MTOK = 1.0
OUTPUT_PRICE_PER_MTOK = 5.0

HOOK_CATEGORIES = ("вопрос", "боль", "провокация", "цифра", "утверждение")

SYSTEM_PROMPT = (
    "Ты классифицируешь хук (первую фразу) короткого видео Reels ровно в одну категорию.\n"
    "Категории:\n"
    "вопрос — хук задаёт вопрос зрителю\n"
    "боль — хук называет проблему, страх или дискомфорт зрителя\n"
    "провокация — хук бросает вызов, спорит с распространённым мнением, провоцирует\n"
    "цифра — хук строится вокруг числа, статистики или суммы\n"
    "утверждение — прямое заявление без выраженного вопроса, боли, провокации или цифры\n"
    "Ответь ровно одним словом из списка категорий, без пояснений и знаков препинания."
)


def classify_hook_with_claude(hook_text: str, api_key: str) -> str | None:
    """Возвращает одну из HOOK_CATEGORIES или None (нет ключа / ошибка API / пустой ответ)."""
    if not hook_text or not hook_text.strip() or not api_key:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=10,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": hook_text.strip()}],
        )
    except anthropic.APIError as e:
        # Не роняем транскрипцию из-за проблем с Anthropic API (невалидный ключ,
        # рейт-лимит и т.п.) — просто откатываемся на "утверждение" по умолчанию.
        # Ошибку логируем, иначе неверный ключ будет молча портить классификацию.
        print(f"[hook_classifier] Anthropic API error, falling back to keyword rules: {e}")
        return None

    label = "".join(b.text for b in response.content if b.type == "text").strip().lower()
    return label if label in HOOK_CATEGORIES else None


def estimate_cost_usd(input_tokens: int = 200, output_tokens: int = 5) -> float:
    """Грубая оценка стоимости одной классификации — для показа пользователю в UI."""
    return (input_tokens / 1_000_000) * INPUT_PRICE_PER_MTOK + (
        output_tokens / 1_000_000
    ) * OUTPUT_PRICE_PER_MTOK
