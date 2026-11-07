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
    r"(?:(?:real|actual|live)\s+)?(?:(?:ai|bot|chat\s?bot|chatgpt|gpt|automated|"
    r"automatic|auto[- ]?repl\w+|auto[- ]?respon\w+|virtual\s+assistant|artificial)\b|a\.i\.(?!\w)"
    # "Are you the person handling this?" is a property question, not an identity one.
    r"|(?:human|person|robot|machine|computer|program|software)\b(?=\s*(?:[?.!,;)]|$)|\s+(?:or|and|right|really|please|lol|haha|btw|by)\b))"
    r"|\bare\s+(?:you|u)\s+(?:really\s+)?real\b(?!\s+estate)"
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
    # "؟" is in the Arabic block but is not \w, so "انت بوت؟" still matches.
    r"(?:روبوت|(?<!\w)بوت(?!\w)|ذكاء\s+(?:اصطناعي|صناعي)|إنسان|انسان|"
    r"شخص|آلي|برنامج)"
    # "Real" is about the buyer's "you" ("انت حقيقي؟", "انت وسيط حقيقي؟"), never about "this"
    # ("هذا السعر حقيقي؟" asks whether the price is genuine).
    r"|(?<!\w)(?:أنت|انت|أنتي|انتي)\s+(?:\w+\s+)?حقيقي(?:ة)?(?!\w)"
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
# Indirect phrasings: who is writing, whether replies are automatic, "you sound like a bot",
# "is this Kian or an assistant". Each also in Arabic, Hindi/Hinglish and Russian.
_ACTOR = r"(?:human|person|someone|somebody|anyone|anybody|machine|bot|robot|ai|computer|program|software|chat\s?bot|real\s+person|actual\s+person)"
_WRITING = r"(?:replying|answering|responding|typing|writing|texting|reading|behind)"
_AUTOMATIC = (
    r"(?:automatic|automated|auto[- ]?generated|ai[- ]?generated|computer[- ]?generated|"
    r"machine[- ]?generated|bot[- ]?generated|scripted|pre[- ]?written|canned)"
)
_NOT_AR = r"(?!\w)"  # Arabic letters are \w; "؟" is not
_IDENTITY_INDIRECT = re.compile(
    r"(?i)\b(?:real|actual|live|living)\s+(?:person|human|people|being|agent)\s*\?"
    rf"|\b{_ACTOR}\s+(?:is\s+|are\s+)?(?:actually\s+|really\s+)?{_WRITING}\b"
    rf"|\bwho(?:'s|\s+is)\s+(?:actually\s+|really\s+)?{_WRITING}\b"
    r"|\b(?:repl(?:y|ies)|responses?|messages?|answers?|texts?|chats?|this)\s+(?:are\s+|is\s+|were\s+|"
    r"seems?\s+|feels?\s+|sounds?\s+|looks?\s+)?(?:all\s+|just\s+|being\s+|so\s+|very\s+)?"
    rf"{_AUTOMATIC}\b"
    r"|\b(?:us(?:e|es|ing)|with|via|through|by)\s+(?:an?\s+)?(?:ai|a\.i\.|bots?|chat\s?gpt|gpt|"
    r"chat\s?bots?|automation|software|a\s+program|machines?|robots?)\s+(?:to\s+|for\s+)?"
    r"(?:repl|respond|answer|writ|text|chat|talk|messag)"
    r"|\b(?:sound|seem|look|feel|talk|write|type|text)(?:s|ing)?\s+(?:like|as\s+if\s+you(?:'re|\s+are))"
    r"\s+(?:an?\s+)?(?:bot|robot|ai|machine|chat\s?bot|computer|program|automated)\b"
    r"|\b(?:sound|seem|feel|look)s?\s+(?:so\s+|very\s+|a\s+bit\s+|kind\s+of\s+|kinda\s+)?"
    r"(?:automated|robotic|scripted|generated|artificial)\b"
    r"|\bor\s+(?:an?\s+|the\s+|your\s+|some\s+)?(?:assistant|bot|robot|ai|a\.i\.|machine|chat\s?bot|"
    r"computer|program|auto[- ]?reply|auto[- ]?responder)(?!\w)(?!')"
    # Arabic
    r"|(?:إنسان|انسان|شخص)\s+حقيقي"
    r"|(?:يرد|يجاوب|يكتب|ترد|تجاوب|تكتب)\s.{0,10}(?:إنسان|انسان|شخص|آلة|الة|روبوت|بوت)"
    + _NOT_AR
    + r"|(?:آلة|الة|إنسان|انسان|روبوت|بوت|شخص)\s+(?:ي|ت)(?:رد|جاوب|كتب)"
    r"|(?<!\w)(?:الردود|ردود|الرد|رد|الرسائل|رسائل|الرسالة|رسالة)\s+"
    r"(?:آلي|الي|آلية|الية|تلقائي|تلقائية|اوتوماتيك\w*)"
    + _NOT_AR
    + r"|(?:تستخدم|تستعمل|يستخدم|يستعمل)\s.{0,10}(?:الذكاء\s+الاصطناعي|ذكاء\s+اصطناعي|روبوت|بوت|"
    r"برنامج|شات\s*جي\s*بي\s*تي)"
    r"|(?:تبدو|يبدو|كأنك|كانك|زي|مثل)\s.{0,6}(?:روبوت|بوت|آلة|الة|آلي)"
    + _NOT_AR
    + r"|(?<!\w)(?:أم|ام|أو|او)\s+(?:مساعد|روبوت|بوت|آلة|الة|برنامج)"
    + _NOT_AR
    # Hindi (Devanagari)
    + r"|असली\s+इंसान"
    r"|(?:इंसान|मशीन|बॉट|बोट|रोबोट|एआई|\bai\b)\s.{0,15}(?:जवाब|रिप्लाई|लिख|बात)"
    r"|(?:\bai\b|एआई|बॉट|बोट|चैटजीपीटी|\bchatgpt\b)\s.{0,6}(?:इस्तेमाल|उपयोग|यूज़|यूज)"
    r"|(?:जवाब|रिप्लाई|मैसेज)\s.{0,6}(?:ऑटोमैटिक|ऑटोमेटिक|स्वचालित|ऑटो)"
    r"|(?:बॉट|बोट|रोबोट|मशीन)\s+(?:जैसे|जैसा|जैसी)"
    r"|(?:या|अथवा)\s+(?:असिस्टेंट|बॉट|बोट|रोबोट|मशीन|एआई)"
    # Hinglish
    r"|\b(?:asli|asal|real)\s+(?:insaan|insan|banda|aadmi)\b"
    r"|\b(?:insaan|insan|banda|aadmi|machine|bot|robot|ai)\b.{0,12}\b(?:reply|jawab|javab|likh|type)"
    r"\w*\s+(?:kar|de|ho)\w*"
    r"|\b(?:replies|reply|jawab|javab|messages?)\b.{0,6}\b(?:automatic|automated|auto)\b"
    r"|\b(?:ai|bot|chatgpt|gpt|chatbot)\b.{0,6}\b(?:use|istemal|istemaal)\b"
    r"|\b(?:bot|robot|machine|ai)\s+(?:jaise|jaisa|jaisi|lagte|lagta|lagti|lag\s+rahe)\b"
    r"|\bya\s+(?:assistant|bot|robot|machine|ai)\b"
    # Russian
    r"|\b(?:живой|настоящий|реальный)\s+человек\b"
    r"|\b(?:отвечает|отвечают|пишет|печатает)\s+(?:мне\s+)?(?:живой\s+|настоящий\s+|реальный\s+)?"
    r"(?:человек|машина|бот|робот|программа|ии|нейросеть)\b"
    r"|\b(?:человек|машина|бот|робот|программа|ии|нейросеть)\s+(?:мне\s+)?(?:отвечает|пишет|печатает)\b"
    r"|\bавтоматическ\w*\s+(?:ответ|сообщени)\w*|автоответ"
    r"|\b(?:используете|используешь|пользуетесь|пользуешься)\s+(?:ли\s+)?(?:ии|нейросет\w*|chatgpt|"
    r"чатгпт|бот\w*|gpt)\b"
    r"|\b(?:похоже|похож|похожи|звучит|звучите)\s+(?:на\s+)?(?:бот\w*|робот\w*|машин\w*|ии)\b"
    r"|\bили\s+(?:ассистент|помощник|бот|робот|ии|нейросеть|программа)\b"
    # WhatsApp shorthand and typos ("u a bot?", "are yuo a bott", "r u real?")
    r"|\b(?:are|r|ar|is)\s+(?:you|u|yu|yuo|yo|ths|this|tis|it)\s+(?:an?\s+|the\s+)?"
    r"(?:real\s+|actual\s+|live\s+)?(?:bot+|chat\s?bot+|chat\s?gpt|gpt|"
    # "AI" and "robot" also describe features ("is it AI smart home enabled?").
    r"(?:ai|a\.i\.|robot)(?=\s*(?:[?.!,]|$)|\s+(?:or|right|really|lol|haha|agent|assistant|"
    r"bot|chat\w*)\b))(?!\w)"
    r"|\b(?:u|ur|youre|ure)\s+(?:an?\s+)?(?:bot+|robot|chat\s?bot|human|real\b(?!\s+estate)|"
    r"(?:ai|a\.i\.)(?=\s*(?:[?.!,]|$)|\s+(?:or|right|really|lol|haha)\b))"
    r"|\b(?:are|r)\s+(?:you|u)\s+(?:really\s+)?real\b(?!\s+estate)"
    r"|\b(?:are|r|is)\s+(?:you|u|this|it)\s+(?:an?\s+)?(?:real|actual|live)\s+"
    # Not "a real person's listing" or "actual agent or owner?": those ask about the property.
    r"(?:agent|broker|person|human|guy)\b(?!'s|\s+or\s+(?:the\s+|an?\s+)?(?:owner|landlord|"
    r"agency|agent|broker|developer|company|office)\b)"
    r"|\b(?:are|r)\s+(?:you|u)\s+(?:an?\s+|the\s+)?assistant\s*(?:[?.!]|$)"
    r"|\b(?:talking|speaking|chatting|texting|messaging)\s+(?:to|with|w/?)\s+(?:an?\s+|the\s+)?"
    r"(?:bot+|chat\s?bot|chat\s?gpt|gpt|"
    # Not "talking to an AI developer" or "a machine learning engineer".
    r"(?:robot|ai|machine|computer|program)(?=\s*(?:[?.!,]|$)|\s+(?:or|again|right|really|now|"
    r"here|lol|haha)\b)|a\.i\.(?=\s*(?:[?.!,]|$)|\s+(?:or|again|right|really|now|here|lol|haha)\b))(?!\w)"
    r"|\bwho\s+am\s+i\s+(?:talking|speaking|chatting|texting|messaging|writing)"
    # Not "who am I talking to about the viewing?": that asks which agent handles it.
    r"(?:\s+(?:to|with|w/?))?(?=\s*(?:[?.!,]|$)|\s+(?:here|now|rn|exactly|actually|really|"
    r"right|lol|haha|pls|please|a|an)\b)"
    r"|\bwho(?:'s|s|\s+is)\s+this\s*(?:\?|[.!]*\s*$)"
    r"|\b(?:is\s+this|are\s+(?:you|u)|r\s+u)\s+(?:chat\s+gpt|gemini|copilot)\b"
    r"(?!\s+(?:tower|towers|building|residence|residences|heights))"
    r"|\b(?:did|does|do)\s+(?:an?\s+)?(?:bot|robot|ai|a\.i\.|chat\s?gpt|gpt|machine|computer|"
    r"program)\s+(?:write|wrote|type|generate|send)\b"
    # The message itself, not "did a machine write the contract?"
    r"(?=\s*(?:[?.!,]|$)|\s+(?:this|that|it|these|those|ur|your|me|the\s+(?:message|reply|"
    r"text|response|answer)s?)\b)"
    r"|\b(?:written|typed|generated)\s+by\s+(?:an?\s+)?(?:bot|robot|ai|a\.i\.|chat\s?gpt|gpt|"
    r"machine|computer|program)(?!\w)"
    r"|\bnot\s+(?:an?\s+)?(?:bot+|robot|chat\s?bot)\b(?!\s+vacuum)"
    r"|^\W*(?:bot+|chat\s?bot|robot|ai|a\.i\.|human)\s*\?"
    # "automated reply?" or "is this an automatic reply", but not "do you send automated
    # messages about new listings?" or "is there an automatic reply to maintenance requests?"
    r"|(?:^\W*|\b(?:is\s+(?:this|that|it)|this\s+is|it'?s|that'?s|are\s+(?:these|those|they|you)"
    r"|ye|yeh|yah|kya)\s+(?:(?:an?|the|just|some|ur|your|kind|sort|of|like)\s+){0,3})"
    r"(?:automated|automatic|auto)[- ]?(?:repl(?:y|ies)|responses?|messages?|answers?)\b"
    r"|\b(?:is\s+there|any|anyone|anybody)\s+(?:an?\s+)?(?:real|human|actual\s+person|"
    r"real\s+person|live\s+person)(?:\s+(?:here|there|on\s+\w+(?:\s+\w+)?))?\s*\?"
    # Arabizi ("inta bot?") and Levantine "who's with me"
    r"|\b(?:inta|enta|inti|enti|anta|enty|inty)\b.{0,15}\b(?:bot+|robot|ai|insan|ensan|human|"
    r"7a2i2i|ha2i2i|haqiqi|real\b(?!\s+estate))\b"
    r"|(?<!\w)مين\s+(?:معي|معاي|معايا|انت|أنت|حضرتك|يرد|بيرد|يكتب)(?!\w)"
    r"|^\W*بوت\W*$"
    # Hinglish
    r"|\b(?:aap|ap|tum|tu)\b.{0,10}\breal\s+(?:ho|hai|hain)\b"
    r"|\b(?:bot|robot|ai|machine|insaan|insan|human|computer)\s+se\s+baat\b"
)


def asks_if_automated(text: str) -> bool:
    """Deliberately broad: a false positive only pauses the thread for the agent."""
    text = text.replace("’", "'")
    return bool(_IDENTITY.search(text) or _IDENTITY_INDIRECT.search(text))


# --- Output screening -----------------------------------------------------------------
_AI_REFERENCE = re.compile(
    r"(?i)\bas an? (?:ai|artificial|language model|virtual|digital|automated)\b"
    r"|\b(?:i am|i'm|im|this is|we are|we're) (?:just |only |actually )?(?:an? |the )?"
    r"(?:ai|a\.i\.|bot|chatbot|robot|virtual|digital|automated|language model|assistant)\b"
    r"|\b(?:chat\s?bot|language model|artificial intelligence|virtual assistant|"
    r"digital assistant|ai assistant|ai-powered|auto-?repl(?:y|ies)|machine learning|llm|gpt|"
    r"openai|chat\s?gpt|automated (?:reply|response|message|assistant|system|service))\b"
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
# Left in the text where `_without_introduction` removed "it's me, <agent>", so the screening
# patterns can still see what follows the introduction.
_INTRODUCTION = "\ue000"
# Any talk about what is writing the reply is the agent's to answer, never the drafter's:
# claims, denials and jokes alike ("not a bot, just quick", "it's really me").
_SELF_IDENTITY = re.compile(
    r"(?i)\b(?:bots?|chat\s?bots?|robots?|robotic|humans?|ai|artificial\s+intelligence|"
    r"auto[- ]?repl\w*|auto[- ]?respon\w*)\b"
    # "A.I." ends in a dot, so no word boundary follows it.
    r"|(?<!\w)a\.i\.?(?!\w)"
    r"|\b(?:real|actual|live|living)\s+(?:person|people|human|humans|man|woman|guy)\b"
    r"|\bperson\s+(?:is\s+)?(?:replying|typing|answering|texting|writing|here|behind)\b"
    r"|\b(?:it'?s|it\s+is|i'?m|i\s+am)\s+(?:an?\s+|the\s+)(?:person|man|woman|guy)\b"
    r"|\b(?:it'?s|it\s+is|this\s+is)\s+(?:really\s+|actually\s+|just\s+|truly\s+|only\s+|"
    r"definitely\s+)?me\b|\breally\s+me\b|\bme\s+(?:typing|replying|texting|writing)\b"
    r"|\b(?:not|no|isn'?t|is\s+not|aren'?t|never|nothing)\s+"
    r"(?:(?:an?|the|some|any|just|one\s+of\s+those|at\s+all)\s+)*"
    r"(?:automat\w*|assistants?|machines?|programs?|computers?|software|script\w*)\b"
    r"|\b(?:automat\w*|machine|assistant)\s+(?:nahi|nahin|nai)\b"
    r"|\b(?:insaan|insan)\b|\bmain\s+hi\s+(?:hoon|hu|hun)\b"
    # Implicit claims: "Ha, all me!", "I'm the one replying", "typed it myself"
    r"|\ball\s+me\b|\breal\s+me\b|\bflesh\s+and\s+blood\b|\bliving,?\s+breathing\b"
    r"|\bthe\s+one\s+(?:replying|typing|texting|writing|answering|responding|messaging)\b"
    r"|\b(?:just|only)\s+me\s+(?:here|on\s+(?:this|the|my)\b|typing|replying|texting|writing)"
    r"|\b(?:nobody|no\s+one|no-one)\s+(?:else\s+)?but\s+me\b"
    r"|(?:^|\b(?:yes|yep|yeah|yup|it'?s|just|only)\W+)me\s+personally\b"
    r"|\b(?:typ\w*|writ\w*|wrote|repl(?:y|ies|ying))\b[^.!?\n]{0,25}\b(?:myself|by\s+hand)\b"
    r"|\b(?:written|typed)\s+by\s+me\b"
    r"|\bpersonally\s+(?:typ\w*|writ\w*|wrote|repl(?:y|ies|ying))\b"
    # Claims that follow an introduction ("it's me, Sara, in person", "Sara here, typing
    # this"). `_INTRODUCTION` stands in for a stripped "it's me, <name>". Plain "in person"
    # is a viewing format and stays allowed ("happy to show it in person").
    rf"|(?:{_INTRODUCTION}|\bhere|\bme|\byes|\byep|\byeah|\byup|\bof\s+course|\bi'?m)\W+"
    r"in\s+person(?=\s*(?:[.!?]|$))"
    rf"|(?:{_INTRODUCTION}|\bhere)[\s,;:\-\u2013\u2014]+(?:(?:i'?m\s+)?(?:typing|writing|replying|texting)"
    r"\s+(?:this|these|it)\b|who\s+else\b)"
    r"|\bwho\s+else\s+would\s+(?:it\s+be|be\s+(?:replying|typing|writing)|reply|answer|type|write)\b"
    r"|\bi'?m\s+typing\s+this\b"
    # Arabic
    r"|روبوت|(?<!\w)بوت(?!\w)|(?<!\w)آلي(?!\w)|تلقائي|ذكاء\s+(?:اصطناعي|صناعي)"
    r"|(?<!\w)(?:إنسان|انسان|بشر)(?!\w)|(?:شخص|إنسان|انسان)\s+حقيقي|(?<!\w)مساعد(?!\w)"
    r"|(?:أنا|انا)\s+(?:بنفسي|نفسي)"
    # Hindi
    r"|बॉट|बोट|रोबोट|एआई|इंसान|मशीन|ऑटोमैटिक|ऑटोमेटिक|स्वचालित|असिस्टेंट|मैं\s+ही\s+हू"
    # Russian
    r"|(?<!\w)(?:бот|бота|ботом|боты|ботов)(?!\w)|робот|(?<!\w)ии(?!\w)|нейросет"
    r"|искусственн\w+\s+интеллект|автоматическ|автоответ|ассистент"
    r"|(?:живой|настоящий|реальный)\s+человек|(?:я|это)\s+человек(?!\w)"
    r"|(?<!\w)(?:это|тут|здесь)\s+(?:правда\s+|действительно\s+|реально\s+|точно\s+)?я(?!\w)"
    r"|(?<!\w)правда\s+я(?!\w)"
)
# Words that also name property features ("automated parking", "washing machine"). Allowed
# only beside the same neighbouring word in the approved facts; anywhere else they are
# self-identity talk.
_NATURE_WORD = re.compile(r"(?i)automat\w*|machines?|assistants?|computers?|programs?|software")
_TOKEN = re.compile(r"[\w'-]+")


def _bigrams(text: str) -> set[tuple[str, str]]:
    words = _TOKEN.findall(text.lower())
    return set(zip(words, words[1:], strict=False))


# Bot words hidden inside a name: "SaraBot", "Realtybot", "PropGPT".
_BOT_IN_NAME = re.compile(r"(?i)bot|gpt")
# Whole words in a name that mark it as an assistant: well-known assistant and AI product
# names, and words like "Virtual Sara" or "Robo Sara". Some are also real names (Alexa,
# Claude, Gemini); those only lose the "it's me, <name>" allowance, "Claude here" and
# "This is Claude from X Realty" never depended on it.
_ASSISTANT_NAME_WORD = re.compile(
    r"(?i)siri|alexa|cortana|bixby|jarvis|claude|gemini|copilot|bard|grok|llama|mistral|"
    r"deepseek|perplexity|openai|anthropic|virtual|digital|robo|droid|android|cyborg|cyber"
)


def _sounds_automated(name: str) -> bool:
    """A name that is itself bot talk ("Bot", "Vitevue AI", "Sara.ai", "SaraBot")."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|[._-]", " ", name)
    return bool(
        _BOT_IN_NAME.search(spaced)
        # Separators are gone from `spaced`, so "Sara A.I." needs the raw name too.
        or _SELF_IDENTITY.search(name)
        or any(_ASSISTANT_NAME_WORD.fullmatch(word) for word in _TOKEN.findall(spaced))
        or _SELF_IDENTITY.search(spaced)
        or _AI_REFERENCE.search(spaced)
        or _HUMAN_CLAIM.search(spaced)
        or any(_NATURE_WORD.fullmatch(word) for word in _TOKEN.findall(spaced))
    )


def _without_introduction(text: str, agent_name: str) -> str:
    """Drop "it's me, <agent>" so the agent's own introduction is not read as a claim.

    Only the agent's configured name (or its first word) qualifies; "it's me, <anyone else>"
    and "it's really me" stay self-identity talk. The name falls back to the WhatsApp display
    name, which may be a brand like "Vitevue AI": a name that is itself bot talk never
    qualifies, or the introduction would hide the admission.
    """
    names = {
        name
        for name in (agent_name.strip(), *agent_name.split()[:1])
        if len(name) > 1 and not _sounds_automated(name)
    }
    if not names:
        return text
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    return re.sub(
        rf"(?i)\b(?:it'?s|it\s+is|this\s+is)\s+me[\s,-]+(?:{alternatives})\b", _INTRODUCTION, text
    )


def _self_identity(text: str, sources: list[str]) -> bool:
    if _SELF_IDENTITY.search(text):
        return True
    allowed = _bigrams("\n".join(sources))
    words = _TOKEN.findall(text.lower())
    for index, word in enumerate(words):
        if not _NATURE_WORD.fullmatch(word):
            continue
        before = (words[index - 1], word) if index else None
        after = (word, words[index + 1]) if index + 1 < len(words) else None
        if before not in allowed and after not in allowed:
            return True
    return False


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


def reply_violations(
    reply: str, *, sources: list[str], context=(), agent_name: str = ""
) -> list[str]:
    """Codes for everything wrong with a generated reply; empty means it may be sent.

    `sources` are the approved facts the reply may state. `context` is what the buyer
    already said (current message and history): numbers there may be echoed back, but
    never treated as facts about a property. `agent_name` is the voice profile's name: the
    only name the reply may introduce itself with ("it's me, Sara").
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
    if _self_identity(_without_introduction(text, agent_name), sources):
        codes.append("self_identity")
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
