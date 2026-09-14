"""What to do once every claim has a verdict.

The whole point of the project lives here, and it is deliberately boring
logic: score claims, drop or regenerate, and never let an unsupported
sentence reach the user unmarked.
"""

from __future__ import annotations

import re

from grounded_rag.config import GuardConfig
from grounded_rag.generation.citation import extract_citations, strip_citations
from grounded_rag.guard.claim_splitter import split_claims
from grounded_rag.guard.nli_verifier import Verifier
from grounded_rag.types import ABSTAIN_TEXT, Answer, AnswerStatus, Claim, RetrievedChunk, Verdict


def is_abstention(text: str) -> bool:
    """The model declined on its own, with the refusal sentence the prompt
    gave it. That is an abstention to report - not a claim to verify, and not
    a reason to regenerate."""
    body = _plain(strip_citations(text))
    refusal = _plain(ABSTAIN_TEXT)
    return body == refusal or (refusal in body and not extract_citations(text))


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def verify_claims(
    answer_text: str,
    sources: list[RetrievedChunk],
    verifier: Verifier,
    threshold: float,
) -> list[Claim]:
    by_label = {s.label: s.chunk.text for s in sources}
    claims = split_claims(answer_text)

    for claim in claims:
        if not claim.citations:
            claim.verdict = Verdict.UNCITED
            claim.entailment = 0.0
            continue

        premise = "\n".join(by_label.get(label, "") for label in claim.citations).strip()
        score = verifier.entailment(premise, claim.text) if premise else 0.0
        claim.entailment = round(score, 4)
        claim.verdict = Verdict.SUPPORTED if score >= threshold else Verdict.UNSUPPORTED

    return claims


def unsupported(claims: list[Claim]) -> list[Claim]:
    return [c for c in claims if c.verdict is not Verdict.SUPPORTED]


def apply_policy(
    claims: list[Claim],
    sources: list[RetrievedChunk],
    cfg: GuardConfig,
    *,
    regenerated: bool = False,
    raw_text: str | None = None,
) -> Answer:
    """Assemble the final answer from claims that survived verification.

    With the guard disabled nothing is dropped: verdicts are still reported so
    the baseline is observable, but the answer must reach the user exactly as
    the model wrote it. Filtering here too would give the baseline part of the
    guard's benefit and make the comparison table meaningless.
    """
    if not cfg.enabled:
        text = raw_text if raw_text is not None else _join(claims)
        return _answer(text, claims, sources, regenerated)

    bad = unsupported(claims)
    kept = [c for c in claims if c.verdict is Verdict.SUPPORTED]

    if not kept:
        # Nothing survived. Either the guard dropped every claim, or the model
        # never produced a citable one: a weak model that answers "[1]" leaves
        # an empty string once that invalid citation is stripped, and an empty
        # answer reported as `answered` is worse than an honest refusal.
        status = AnswerStatus.ABSTAINED
    elif not bad:
        status = AnswerStatus.ANSWERED
    elif cfg.on_unsupported == "abstain_all":
        status = AnswerStatus.ABSTAINED
    else:
        status = AnswerStatus.PARTIAL

    text = ABSTAIN_TEXT if status is AnswerStatus.ABSTAINED else _join(kept)

    out = Answer(answer=text, status=status, claims=claims, sources=sources)
    out.meta.regenerated = regenerated
    return out


def _answer(
    text: str, claims: list[Claim], sources: list[RetrievedChunk], regenerated: bool
) -> Answer:
    """Guard disabled: the answer reaches the user exactly as written, but an
    answer with no text left is still an abstention, not an empty success."""
    blank = not text.strip()
    out = Answer(
        answer=ABSTAIN_TEXT if blank else text,
        status=AnswerStatus.ABSTAINED if blank else AnswerStatus.ANSWERED,
        claims=claims,
        sources=sources,
    )
    out.meta.regenerated = regenerated
    return out


def _join(claims: list[Claim]) -> str:
    return " ".join(
        f"{c.text} {' '.join(f'[{x}]' for x in c.citations)}".strip() for c in claims
    )


def should_regenerate(claims: list[Claim], cfg: GuardConfig, attempts: int) -> bool:
    if not cfg.enabled or attempts > cfg.max_regenerations:
        return False
    # No claims at all is a failed generation, not a refusal: the model answered
    # "[C1]" - a valid label with no sentence attached, so citation validation
    # has nothing to catch and there is nothing to verify. A refusal would have
    # been caught earlier by is_abstention(). Spend the retry the budget allows.
    return not claims or bool(unsupported(claims))


def regeneration_feedback(claims: list[Claim]) -> str:
    if not claims:
        return (
            "Câu trả lời trước chỉ gồm mã trích dẫn, không có câu văn nào. "
            "Hãy viết lại thành câu hoàn chỉnh, mỗi câu kết thúc bằng mã trích dẫn "
            "của đoạn chứng minh câu đó. Nếu tài liệu không đủ thông tin, trả lời "
            f'đúng một câu: "{ABSTAIN_TEXT}"'
        )
    bad = unsupported(claims)
    listed = "\n".join(f"- {c.text}" for c in bad)
    return (
        "Câu trả lời trước có những mệnh đề KHÔNG được tài liệu chứng minh:\n"
        f"{listed}\n"
        "Hãy viết lại, chỉ dùng thông tin có trong tài liệu được cung cấp. "
        "Nếu tài liệu không đủ thông tin, trả lời đúng một câu: "
        f'"{ABSTAIN_TEXT}"'
    )
