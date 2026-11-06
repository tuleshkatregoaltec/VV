"""The agent's voice and the deterministic checks that keep generated replies honest.

The model writes the words; this module decides whether they may be sent. It has no
database or model access. A reply fails closed on any of: references to being automated,
claims of being human, assistant boilerplate, invented numbers/contacts/availability,
and commitments the automation cannot keep.
"""

import hashlib
import re

from pydantic import ValidationError

from app.whatsapp.customer_models import VoiceProfile

__all__ = [
    "HOLDING_LINES",
    "VoiceProfile",
    "asks_if_automated",
    "fallback_holding",
    "fallback_question",
    "normalize_reply",
    "prompt_voice",
    "question_variants",
    "reply_violations",
    "split_reply",
]

DEFAULT_TONE = "friendly, relaxed and to the point, like a busy agent texting from their phone"
MAX_REPLY_CHARS = 700

# --- Does the buyer sincerely want to know whether they are talking to a machine? -----
_IDENTITY = re.compile(
    r"(?i)\b(?:are|r|is)\s+(?:you|u|this|that)\s+(?:an?\s+|the\s+|really\s+|actually\s+|just\s+)?"
    r"(?:(?:real|actual|live)\s+)?(?:(?:ai|a\.i\.|bot|chat\s?bot|chatgpt|gpt|automated|"
    r"automatic|auto[- ]?repl\w+|auto[- ]?respon\w+|virtual\s+assistant|artificial)\b"
    # "Are you the person handling this?" is a property question, not an identity one.
    r"|(?:human|person|robot|machine|computer|program|software)\b(?=\s*(?:[?.!,;)]|$)|\s+(?:or|and|right|really|please|lol|haha|btw|by)\b))"
    r"|\bare\s+(?:you|u)\s+(?:really\s+)?real\b"
    r"|\byou(?:'re|\s+are|r)\s+(?:just\s+)?(?:an?\s+)?(?:bot|robot|ai|chat\s?bot|machine)\b"
    r"|\bam\s+i\s+(?:talking|speaking|chatting|texting|messaging|writing)\s+(?:to|with)\s+"
    r"(?:an?\s+|the\s+)?(?:real\s+|actual\s+|live\s+)?(?:ai|bot|robot|chat\s?bot|human|person|"
    r"machine|automated|auto\w*|someone\s+real|somebody\s+real)\b"
    r"|\b(?:person|human|man|people)\s+or\s+(?:a\s+)?(?:machine|bot|robot|ai)\b"
    r"|\b(?:machine|bot|robot|ai)\s+or\s+(?:a\s+)?(?:person|human|real)\b"
    # Hinglish
    r"|\b(?:aap|ap|tum|tu|ye|yeh|yah)\b.{0,15}\b(?:bot|robot|ai|insaan|insan|human)\b"
    r"|\b(?:bot|robot|ai|insaan|insan)\s+(?:ho|hai|hain)\b"
    r"|\bbot\s+ya\s+(?:insaan|insan|human)\b|\b(?:insaan|insan)\s+ya\s+bot\b"
    # Arabic
    r"|(?:أنت|انت|أنتي|انتي|هذا|هذه|أتحدث|اتحدث|أكلم|اكلم|أتكلم|اتكلم)\s.{0,30}"
    r"(?:روبوت|(?<![؀-ۿ])بوت(?![؀-ۿ])|ذكاء\s+(?:اصطناعي|صناعي)|إنسان|انسان|"
    r"شخص|آلي|برنامج)"
    # Hindi
    r"|(?:आप|तुम|यह|ये)\s.{0,25}(?:बॉट|बोट|रोबोट|एआई|चैटबॉट|इंसान|मशीन)"
    # Russian
    r"|\b(?:вы|ты|это)\b.{0,30}\b(?:бот|робот|нейросеть|нейросет\w+|ии|автоответчик|"
    r"искусственн\w+\s+интеллект)\b"
    r"|(?:говорю|общаюсь|пишу|разговариваю)\s+(?:с\s+)?(?:живым\s+|настоящим\s+|реальным\s+)?"
    r"(?:человеком|ботом|роботом)"
    r"|\b(?:вы|ты)\s+(?:живой\s+|настоящий\s+|реальный\s+)?человек\b"
    r"|\b(?:бот|робот)\s+или\s+человек\b|\bчеловек\s+или\s+(?:бот|робот)\b"
)


def asks_if_automated(text: str) -> bool:
    """Deliberately broad: a false positive only pauses the thread for the agent."""
    return bool(_IDENTITY.search(text.replace("’", "'")))


# --- Output screening -----------------------------------------------------------------
_AI_REFERENCE = re.compile(
    r"(?i)\bas an? (?:ai|artificial|language model|virtual|digital|automated)\b"
    r"|\b(?:i am|i'm|im|this is|we are|we're) (?:just |only |actually )?(?:an? |the )?"
    r"(?:ai|a\.i\.|bot|chatbot|robot|virtual|digital|automated|language model|assistant)\b"
    r"|\b(?:chat\s?bot|language model|artificial intelligence|virtual assistant|"
    r"digital assistant|ai assistant|ai-powered|auto-?repl(?:y|ies)|machine learning|llm|gpt|"
    r"openai|automated (?:reply|response|message|assistant|system|service))\b"
    r"|مساعد\s+افتراضي|ذكاء\s+(?:اصطناعي|صناعي)|روبوت|رد\s+(?:آلي|تلقائي)"
    r"|(?<![؀-ۿ])بوت(?![؀-ۿ])"
    r"|(?<!\w)бот(?:а|ом)?(?!\w)|робот|нейросет|искусственн\w+\s+интеллект"
    r"|виртуальн\w+\s+(?:помощник|ассистент)|автоответчик|(?<!\w)ии(?!\w)"
    r"|बॉट|चैटबॉट|रोबोट|एआई|कृत्रिम\s+बुद्धि|वर्चुअल\s+असिस्टेंट"
)
_HUMAN_CLAIM = re.compile(
    r"(?i)\b(?:i am|i'm|im|yes,? i am|yes,? i'm|this is) (?:a |an |just a |actually a )?"
    r"(?:real|actual|live|living|flesh)\b"
    r"|\b(?:real|actual|live) (?:person|human|people|man|woman)\b"
    r"|\bi(?:'m| am) (?:a )?(?:human|person|man|woman)\b"
    r"|\b(?:i(?:'m| am) not|im not|no,? i(?:'m| am) not|definitely not) (?:an? )?"
    r"(?:bot|robot|ai|chat\s?bot|machine|automated)\b"
    r"|\bhuman\b"
    r"|أنا\s+(?:إنسان|انسان|بشر|شخص\s+حقيقي)|لست\s+(?:روبوت|بوت)|(?:إنسان|انسان|شخص)\s+حقيقي"
    r"|я\s+(?:живой\s+)?человек\b|живой\s+человек|я\s+не\s+(?:бот|робот)"
    r"|(?:настоящий|реальный)\s+человек"
    r"|मैं\s+(?:एक\s+)?(?:असली\s+)?इंसान|असली\s+इंसान|मैं\s+(?:बॉट|रोबोट)\s+नहीं"
    r"|\bmain\s+(?:insaan|insan)\b|\bmain\s+bot\s+nahi\b"
)
_BOILERPLATE = re.compile(
    r"(?i)thank you for (?:reaching out|contacting|your (?:inquiry|enquiry|interest))"
    r"|how (?:may|can) i (?:assist|help) you(?: today)?"
    r"|(?:i'd|i would) be (?:happy|glad|delighted) to (?:assist|help)"
    r"|great question|certainly!|absolutely!|of course!|i hope this (?:helps|finds)"
    r"|feel free to (?:reach out|contact)|don't hesitate"
    r"|please (?:let me know|do not hesitate) if you (?:have|need|require)"
    r"|is there anything else|i understand your (?:concern|frustration)"
    r"|i apologi[sz]e for (?:any|the) (?:inconvenience|confusion)|at your service"
    r"|valued customer"
)
_COMMITMENT = re.compile(
    r"(?i)\b(?:is|are|was|has been|have been|been|will be|all) (?:now )?"
    r"(?:confirmed|booked|reserved|scheduled|secured|arranged|locked in|guaranteed)\b"
    r"|\bi(?:'ve| have|'ll| will) (?:booked|reserved|scheduled|secured|arranged|put (?:it )?on hold)"
    r"|\bi(?:'ve| have) sent\b|\bi (?:promise|guarantee)\b|\bguarantee[ds]?\b|\bpromise[ds]?\b"
    r"|\bconfirmed\b|\bdeal (?:done|is done)\b|\bsee you (?:on|at|tomorrow|then)\b"
    r"|\b(?:in|within) (?:a few|a couple of|a|an|the next)\s+(?:minutes?|hours?|mins?)\b"
)
_CONTACT = re.compile(r"(?i)https?://\S+|www\.\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+")
_CLAIM_STEMS = ("availab", "vacant", "sold", "off market", "off-market", "ready to move")

_SUFFIX = {
    "k": 1e3, "thousand": 1e3, "الف": 1e3, "ألف": 1e3,
    "lakh": 1e5, "lac": 1e5, "crore": 1e7,
    "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6, "millions": 1e6,
    "مليون": 1e6, "ملايين": 1e6, "млн": 1e6, "миллион": 1e6, "миллиона": 1e6,
    "миллионов": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
}  # fmt: skip
_NUMBER = re.compile(
    r"(?i)(?<![\w.])(\d{1,3}(?:[\u00a0\u202f ]\d{3})+(?:[.,٫]\d+)?|\d[\d,٬،]*(?:[.٫]\d+)?)"
    r"(?:\s*(k|m|mn|mm|bn|b|million|millions|thousand|lakh|lac|crore|مليون|ملايين|ألف|الف|"
    r"млн|миллион\w*)(?!\w))?"
)
_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
}  # fmt: skip
_WORD = re.compile(r"(?i)\b(" + "|".join(_WORDS) + r")\b")
ROUNDING = 0.05


def _numbers(text: str) -> list[tuple[float, bool]]:
    """(value, was_rounded_with_suffix) for each number in the text."""
    found = []
    for raw, suffix in _NUMBER.findall(text):
        raw = re.sub(r"[\u00a0\u202f ]", "", raw)
        if re.fullmatch(r"\d+,\d{1,2}", raw):  # decimal comma: 2,45 million
            raw = raw.replace(",", ".")
        cleaned = re.sub(r"[,٬،]", "", raw).replace("٫", ".")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if suffix:
            value *= _SUFFIX.get(suffix.lower(), 1e6)
        found.append((value, bool(suffix)))
    found.extend((float(_WORDS[word.lower()]), False) for word in _WORD.findall(text))
    return found


def _grounded_number(value: float, rounded: bool, allowed: list[float]) -> bool:
    for known in allowed:
        tolerance = ROUNDING if rounded else 1e-9
        if abs(value - known) <= tolerance * max(abs(known), 1.0):
            return True
    return False


def reply_violations(reply: str, *, sources: list[str], context=()) -> list[str]:
    """Codes for everything wrong with a generated reply; empty means it may be sent.

    `sources` are the approved facts the reply may state. `context` is what the buyer
    already said (current message and history): numbers there may be echoed back, but
    never treated as facts about a property.
    """
    text = reply.replace("’", "'")
    codes = []
    if not text.strip() or len(text) > MAX_REPLY_CHARS:
        codes.append("length")
    for code, pattern in (
        ("ai_reference", _AI_REFERENCE),
        ("human_claim", _HUMAN_CLAIM),
        ("boilerplate", _BOILERPLATE),
        ("commitment", _COMMITMENT),
    ):
        if pattern.search(text):
            codes.append(code)
    known_text = "\n".join([*sources, *context])
    allowed = [value for value, _ in _numbers(known_text)]
    if any(not _grounded_number(value, rounded, allowed) for value, rounded in _numbers(text)):
        codes.append("ungrounded_number")
    lowered = known_text.lower()
    if any(token.lower().rstrip(".,)") not in lowered for token in _CONTACT.findall(text)):
        codes.append("ungrounded_contact")
    facts = "\n".join(sources).lower()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.lower()):
        if sentence.rstrip().endswith("?"):
            continue
        if any(stem in sentence and stem not in facts for stem in _CLAIM_STEMS):
            codes.append("ungrounded_claim")
            break
    return codes


_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿️‍]")


def normalize_reply(text: str, *, emoji: bool = False) -> str:
    """Strip formatting that reads as machine-written in a WhatsApp chat."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"').replace("…", "...")
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = text.replace("*", "")
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-•]\s+)", "", text)
    if not emoji:
        text = _EMOJI.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r",\s*,", ",", text)
    return text.strip()


def split_reply(reply: str) -> list[str]:
    """People text in short bursts: at most two messages, split on a blank line."""
    parts = [part.strip() for part in reply.split("\n\n") if part.strip()]
    if len(parts) <= 2:
        return parts
    return [parts[0], "\n\n".join(parts[1:])]


def prompt_voice(stored: dict | None, *, display_name: str) -> dict:
    """The voice block the drafter sees; defaults when nothing (valid) is stored."""
    try:
        profile = VoiceProfile.model_validate(stored or {})
    except ValidationError:
        profile = VoiceProfile()
    return {
        "agent_name": profile.agent_name or display_name,
        "tone": profile.tone or DEFAULT_TONE,
        "sign_off": profile.sign_off,
        "languages": profile.languages,
        "sample_messages": profile.sample_messages,
        "emoji": profile.emoji,
    }


# --- Last-resort wording when the model output fails the checks ------------------------
_QUESTIONS = {
    "transaction": (
        "Are you looking to buy or rent?",
        "Buying or renting?",
        "Is this to buy or to rent?",
    ),
    "budget": (
        "What budget do you have in mind, and in which currency?",
        "Roughly what budget are you working with? Which currency?",
        "What's your budget, and in which currency?",
    ),
    "timeframe": (
        "When are you looking to move?",
        "And when would you like to move in?",
        "What's your timeline for moving?",
    ),
}
HOLDING_LINES = (
    "Let me check on that and get back to you.",
    "Good one, let me look into it and come back to you.",
    "Let me check with the owner and get back to you.",
    "Give me a moment to look into this properly, I'll revert.",
)


def _pick(options: tuple[str, ...], seed: str) -> str:
    return options[int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(options)]


def question_variants(detail: str) -> tuple[str, ...]:
    return _QUESTIONS[detail]


def fallback_question(detail: str, seed: str) -> str:
    return _pick(_QUESTIONS[detail], seed)


def fallback_holding(seed: str) -> str:
    return _pick(HOLDING_LINES, seed)
