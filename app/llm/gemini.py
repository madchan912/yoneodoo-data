import os
import json
import re
from google import genai

_client = None
_MODEL = "gemini-2.5-flash"


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
        _client = genai.Client(api_key=api_key)
    return _client

_PROMPT_TEMPLATE = """\
너는 요리 레시피 정보를 JSON으로 추출하는 AI야.
아래 영상 데이터(자막·더보기·댓글)를 보고, 요리 레시피를 추출해줘.

[지시사항]
1. 이 영상이 요리 레시피와 관련 없으면 ingredients를 빈 배열([])로 반환해.
2. recipe_name: 요리 이름 (한국어).
3. ingredients 각 항목:
   - name: 재료명, 띄어쓰기 없이 붙여 써. (예: "다진마늘", "저당고추장")
   - amount: 수량+단위. (예: "0.5스푼", "1개", "200g"). 정보가 없으면 null.
4. JSON만 반환. 다른 텍스트나 설명 절대 금지.

[출력 형식]
{{
  "recipe_name": "요리이름",
  "ingredients": [
    {{"name": "재료명", "amount": "수량단위"}},
    {{"name": "재료명", "amount": null}}
  ]
}}

[데이터]
자막: {transcript}

더보기(description): {description}

첫번째 댓글: {comment}
"""


def extract_recipe(transcript: str, description: str, comment: str) -> dict:
    prompt = _PROMPT_TEMPLATE.format(
        transcript=transcript[:2000],
        description=description[:1000],
        comment=comment[:500],
    )
    try:
        response = _get_client().models.generate_content(model=_MODEL, contents=prompt)
        raw = response.text
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"    ❌ Gemini 분석 실패: {type(e).__name__} - {e}")

    return {"recipe_name": "AI 실패", "ingredients": []}
