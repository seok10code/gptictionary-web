"""Structured study content. Conversation evidence is not external fact verification."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict


class StudyPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    area: Literal["meaning", "explanation", "usage", "caution"]
    status: Literal["supported", "uncertain", "superseded", "unverified"]
    text: str
    source_id: int | None
    quote: str
    review_reason: str = ""
    uncertainty_basis: Literal["", "source_uncertainty", "dialogue_correction"] = ""


class StudyContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key_expression: str
    has_correction: bool
    change_type: Literal["format_only", "content_update"]
    points: list[StudyPoint]
    correction_summary: list[str]


def display_text(value):
    """Decode textual newlines without decoding Unicode or modifying code/path tokens."""
    text = str(value or "").replace("\r\n", "\n")
    parts = re.split(r"(```[\s\S]*?```|`[^`\n]*`|\b[A-Za-z]:\\[^\s]+)", text)
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("\\r\\n", "\n").replace("\\n", "\n")
    return "".join(parts)


AREAS = {"meaning": "뜻", "explanation": "핵심 설명", "usage": "사용 상황", "caution": "주의할 점"}


# Meta-language about whether an explanation is known, not uncertainty inside
# an example such as "I may be late" or the Korean translation "것 같아".
SOURCE_UNCERTAINTY = re.compile(
    r"확실하지|불확실|추측|추정|단정.{0,30}(?:어렵|못|안)|"
    r"(?:뜻|의미|해석).{0,35}(?:확인|맥락|문맥).{0,20}(?:필요|없)|"
    r"(?:문맥|맥락).{0,30}(?:필요|모르)|모르겠|"
    r"\b(?:not sure|uncertain|speculative|might mean|cannot confirm|can't confirm)\b",
    re.IGNORECASE)


def source_uncertainty(text):
    return bool(SOURCE_UNCERTAINTY.search(text or ''))


def uncertainty_reason(point, has_correction=False):
    if point.review_reason:return point.review_reason
    if point.area=='meaning' and has_correction:
        return '후속 답변에서 앞선 설명을 정정했으며, 이 해석은 확정하지 않은 상태입니다.'
    return '이전 정리에서 대화 근거로 확정하지 못한 항목입니다.'


def validate_study(study, turns):
    if not study or not study.key_expression or len(study.key_expression) > 300:
        raise ValueError("핵심 표현을 확인할 수 없습니다.")
    if not 1 <= len(study.points) <= 20 or len(study.correction_summary) > 8:
        raise ValueError("학습 내용의 항목 수가 올바르지 않습니다.")
    sources = {turn["source_id"]: turn for turn in turns}
    for point in study.points:
        if len(point.review_reason)>2000:
            raise ValueError("검토 이유가 너무 깁니다.")
        point.text = display_text(point.text)
        if not point.text or len(point.text) > 1600 or len(point.quote) > 3000:
            raise ValueError("학습 항목의 길이를 확인해 주세요.")
        if point.status == "supported":
            if point.source_id not in sources or not point.quote or point.quote not in sources[point.source_id]["answer"]:
                raise ValueError("학습 설명을 뒷받침하는 원문을 확인할 수 없습니다.")
        elif point.source_id is not None:
            if point.source_id not in sources or (point.quote and point.quote not in sources[point.source_id]["answer"]):
                raise ValueError("이전 설명 또는 확인 필요 항목의 출처를 확인해 주세요.")
    study.key_expression = display_text(study.key_expression)
    study.correction_summary = [display_text(line) for line in study.correction_summary]
    if any(len(line) > 1600 for line in study.correction_summary):
        raise ValueError("정정 설명이 너무 깁니다.")
    if study.has_correction and not study.correction_summary:
        raise ValueError("무엇이 정정됐는지 설명이 필요합니다.")
    return study


def study_to_text(study):
    lines = [study.key_expression]
    for area, label in AREAS.items():
        values = [p.text for p in study.points if p.status == "supported" and p.area == area]
        if values:
            lines += ["", label] + values
    if study.correction_summary:
        lines += ["", "정정 반영"] + study.correction_summary
    pending = [p.text for p in study.points if p.status == "uncertain"]
    if pending:
        lines += ["", "해석이 확정되지 않았어요 · 확정된 정답으로 외우지 마세요"] + pending
    return "\n".join(lines)


def study_view(binding, section):
    if not binding or not section or binding.section_id != section.id:
        return None
    note = ((binding.data or {}).get("plan") or {}).get("note") or {}
    if not note.get("study"):
        return None
    try:
        content = StudyContent.model_validate(note["study"])
    except ValueError:
        return None
    uncertain = [p for p in content.points if p.status=='uncertain']
    semantic = [p for p in uncertain if p.area=='meaning' or p.uncertainty_basis in {'source_uncertainty','dialogue_correction'}]
    extras = [p for p in uncertain if p not in semantic]
    return {"content": content, "recall_question": recall_for_study(content),
            "blocks": {key: [p for p in content.points if p.status == "supported" and p.area == key] for key in AREAS},
            "uncertain": semantic,
            "uncertain_details": [{"point":p,"reason":uncertainty_reason(p,content.has_correction)} for p in semantic],
            "excluded_extras": extras,
            "unverified": [p for p in content.points if p.status == "unverified"],
            "superseded": [p for p in content.points if p.status == "superseded"]}


def study_preview(view, fallback, limit=220):
    if view:
        blocks = view["blocks"]
        points = blocks["meaning"] + blocks["explanation"] + blocks["caution"] + blocks["usage"]
        if points:
            return points[0].text[:limit]
        return "의미 확인이 필요한 항목이 있어요." if view["uncertain"] else "출처 대조가 끝난 학습 설명이 아직 없습니다."
    return display_text(fallback)[:limit]


def recall_for_study(study):
    supported = {point.area for point in study.points if point.status == "supported"}
    expression = study.key_expression
    has_uncertain_meaning = any(point.area == "meaning" and point.status == "uncertain" for point in study.points)
    if has_uncertain_meaning:
        if "caution" in supported:
            return f"'{expression}'를 쓸 때 확인된 주의점과 아직 불확실한 해석은 각각 무엇인가요?"
        if "usage" in supported:
            return f"'{expression}'는 어떤 상황에서 쓰며, 어떤 해석은 아직 확인이 필요한가요?"
        return "이 노트에서 근거가 확인된 설명과 아직 확인이 필요한 해석을 구분해 보세요."
    if "meaning" in supported:
        return f"'{expression}'의 이 문맥에서 정리한 뜻은 무엇인가요?"
    if "caution" in supported:
        return f"'{expression}'를 쓸 때 주의할 점은 무엇인가요?"
    if "usage" in supported:
        return f"'{expression}'는 어떤 상황에서 쓰나요?"
    if "explanation" in supported:
        return f"'{expression}'의 핵심 설명을 자신의 말로 정리해 보세요."
    if any(point.status == "uncertain" for point in study.points):
        return "아직 확실하지 않은 부분은 무엇이며, 어떤 맥락을 더 확인해야 할까요?"
    return "출처 대조가 끝난 학습 설명이 아직 없습니다."
