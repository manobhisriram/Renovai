"""Conversation-level agents: intent routing and grounded Q&A."""

from __future__ import annotations

from typing import Any

from app.llm.client import LLMClient, context_block
from app.llm.safety import wrap_untrusted
from app.schemas.ai import AnswerText, ChatIntent
from app.utils.errors import LLMOutputError


def classify_intent(llm: LLMClient, *, message: str, awaiting_clarification: bool, has_quote: bool) -> ChatIntent:
    user = context_block({"awaiting_clarification": awaiting_clarification, "has_quote": has_quote}) + "\n" + wrap_untrusted("user_input", message)
    try:
        return llm.structured("intent_classification", ChatIntent, user=user, system=(
            "Classify the client's message: negotiate (price/budget pushback), clarification_answer (answers our pending questions), "
            "replan (wants to change/add scope), suggest (asks for ideas or is unsure), visualize (wants to see an image), "
            "question (asks something), other."))
    except LLMOutputError:
        return ChatIntent(intent="other", confidence=0.0)


def answer_question(llm: LLMClient, *, message: str, facts: dict[str, Any]) -> str:
    user = context_block(facts) + "\n" + wrap_untrusted("user_input", message)
    return llm.structured("qa", AnswerText, user=user, system=(
        "Answer the client's question using ONLY the facts in the context. If the answer is not there, say you don't know and "
        "that the team can follow up. Never invent prices or dates; quote figures exactly as given.")).answer
