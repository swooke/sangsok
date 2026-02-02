"""상속세 계산기 - 대화형 UI (LLM 연동)"""
import streamlit as st
import re
import json
import os
import sys

# Streamlit Cloud 배포를 위한 경로 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.asset import (
    InheritanceInfo, Asset, Heir, ChildInfo, SpouseInfo,
    Deductions, PriorGift, CoResidenceInfo
)
from calculator.cases import compare_cases
from calculator.inheritance_tax import TAX_BRACKETS

# Gemini API (신규 google.genai 패키지)
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# API 키 설정
GEMINI_API_KEY = "AIzaSyC1a6GP-gsfBLlyjta0zukn2LEJbnXcd9U"

# Gemini 클라이언트 설정
gemini_client = None
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# ============================================
# LLM 파싱 함수
# ============================================

def get_gemini_client():
    """Gemini 클라이언트 반환"""
    if GEMINI_API_KEY and GEMINI_AVAILABLE and gemini_client:
        return gemini_client
    return None


def parse_with_llm(user_input: str, parse_type: str) -> dict:
    """
    LLM을 사용하여 사용자 입력 파싱
    parse_type: assets, spouse, children, debts, prior_gift, yes_no
    """
    client = get_gemini_client()
    if not client:
        return None

    prompts = {
        "assets": """상속재산을 분류하세요. 금액은 원 단위 정수로 변환하세요.

분류 기준:
- real_estate: 모든 부동산 (건물, 토지, 주거/상업/산업용 모두 포함)
- financial: 금융자산 (은행 예금, 적금 등)
- securities: 유가증권 (주식, 채권, 펀드, ETF 등)
- cash: 현금
- insurance: 사망보험금, 생명보험 등
- retirement: 퇴직금, 퇴직연금
- trust: 신탁재산
- other: 위에 해당하지 않는 기타 자산

중요: 사용자가 줄임말이나 은어를 사용해도 문맥에서 추론하여 분류하세요.
예: 지산=지식산업센터(부동산), 오피=오피스텔(부동산), 통장/적금/예금=금융자산, 주식/펀드=유가증권

{
    "real_estate": 부동산 합계,
    "financial": 금융자산 합계,
    "securities": 유가증권 합계,
    "cash": 현금,
    "insurance": 보험금,
    "retirement": 퇴직금,
    "trust": 신탁재산,
    "other": 기타 자산
}""",

        "spouse": """배우자 정보를 추출하세요. 현재 연도는 2025년입니다.
- 나이: "65세", "65살" → 65 / "1960년생" → 2025-1960=65세 / "60년생" → 2025-1960=65세
- 장애인 여부와 기대여명도 언급되면 추출

{
    "exists": 배우자가 있는지 (true/false),
    "age": 배우자 나이 (숫자로 계산, 언급 없으면 60),
    "is_disabled": 장애인 여부 (true/false),
    "life_expectancy": 기대여명 연수 (장애인인 경우)
}""",

        "children_count": """자녀가 있는지, 몇 명인지 파악하세요.
- "2명", "둘", "두명" → 2
- "아들 하나 딸 하나" → 2
- "3명 있어요" → 3
- "없어", "없습니다" → 0
- 자녀 수를 명확히 알 수 없으면 null

{
    "has_children": 자녀가 있는지 (true/false),
    "num_children": 자녀 수 (숫자, 불명확하면 null)
}""",

        "children": """자녀 정보를 추출하세요. 현재 연도는 2025년입니다.
- 나이: "35세" → 35 / "1990년생" → 2025-1990=35세 / "90년생" → 2025-1990=35세
- 손자녀, 장애인 여부도 언급되면 추출

{
    "num_children": 자녀 수 (없으면 0),
    "ages": [각 자녀 나이 배열] (예: [35, 32]),
    "has_grandchild": 손자녀 포함 여부,
    "has_disabled": 장애인 자녀 포함 여부
}""",

        "funeral_costs": """장례비용 정보를 추출하세요. 금액은 원 단위 정수로 변환하세요.

분류 기준:
- funeral_expense: 장례 진행 비용 (장례식장, 조문, 음식, 운구 등)
- funeral_memorial: 안치/매장 비용 (납골당, 봉안, 묘지, 화장, 수목장 등)

중요: 사용자가 구체적으로 구분하지 않으면 전체 금액을 funeral_expense로 분류하세요.
문맥에서 추론하여 적절히 분류하세요.

{
    "has_costs": 장례비용이 있는지 (true/false),
    "funeral_expense": 장례비용 (숫자, 없으면 0),
    "funeral_memorial": 봉안/묘지 비용 (숫자, 없으면 0)
}""",

        "other_debts": """기타 채무 정보를 추출하세요. 금액은 원 단위 정수로 변환하세요.
(부동산 관련 채무는 이미 입력받았으므로 제외)

분류 기준:
- public_charges: 세금, 공공요금, 관리비 등 정부/공공기관에 내는 비용
- debt: 그 외 모든 채무 (은행대출, 카드빚, 개인빚, 줄임말/은어 포함)

중요: 사용자가 줄임말이나 은어를 사용해도 문맥에서 추론하여 분류하세요.
예: 마통=마이너스통장, 신대=신용대출, 카드깡 등

{
    "has_debts": 채무가 있는지 (true/false),
    "public_charges": 공과금 (숫자, 없으면 0),
    "debt": 기타 채무 (숫자, 없으면 0)
}""",

        "real_estate_debt": """부동산 관련 채무 정보를 추출하세요. 금액은 원 단위 정수로 변환하세요.

분류 기준:
- deposit: 세입자에게 돌려줘야 할 보증금 (전세, 월세, 임대 보증금 등)
- loan: 부동산 담보 대출 (주담대, 근저당, 담보대출 등)

중요: 사용자가 줄임말이나 은어를 사용해도 문맥에서 추론하여 분류하세요.
예: 전세끼고/세낀/세놓은=보증금, 주담대=주택담보대출, 근저당=대출

{
    "has_debt": 채무가 있는지 (true/false),
    "deposit": 보증금 합계 (숫자, 없으면 0),
    "loan": 대출 합계 (숫자, 없으면 0)
}""",

        "prior_gift": """사전증여 정보를 추출하세요. 금액은 원 단위 정수로 변환하세요.

추출 항목:
- amount: 증여한 총 금액
- tax: 그때 납부한 증여세 (언급 없으면 0)

중요: "줬다", "물려줬다", "넘겨줬다" 등 다양한 표현도 증여로 인식하세요.
증여세 언급이 없으면 tax는 0으로 처리하세요.

{
    "has_gift": 사전증여가 있는지 (true/false),
    "amount": 증여 금액 (숫자, 없으면 0),
    "tax": 납부한 증여세 (숫자, 없으면 0)
}""",

        "yes_no": """사용자의 답변이 긍정적인 의미인지 부정적인 의미인지 판단하세요.
문맥과 의도를 파악하여 결정하세요. 예를 들어 "배우자가 생존해 계신가요?"라는 질문에 "살아계셔", "계셔", "생존해요" 등은 모두 긍정(true)입니다.

{
    "answer": true 또는 false
}""",

        "grandchild": """세대생략 상속(손자녀에게 직접 상속) 여부를 파악하세요.

긍정 표현 예시:
- "네", "예", "있어요", "할 예정이에요"
- "손자한테 줄 거예요", "손녀에게 상속해요"
- "세대생략 할 거예요", "손주한테요"

부정 표현 예시:
- "아니오", "없어요", "안 해요"
- "자녀한테만", "그냥 자녀에게"

{
    "has_grandchild": 세대생략 상속 예정 여부 (true/false)
}""",

        "grandchild_detail": """손자녀 상속 정보를 추출하세요. 현재 연도는 2025년입니다.

- 나이: "25세" → 25 / "2000년생" → 2025-2000=25세 / "10살" → 10
- 금액: 원 단위 정수로 변환 (5억 = 500000000)

예시:
- "25세 손자에게 5억" → age: 25, amount: 500000000
- "10세, 3억원" → age: 10, amount: 300000000
- "손녀 15살, 2억 줄 예정" → age: 15, amount: 200000000

{
    "age": 손자녀 나이 (숫자),
    "amount": 상속 예정 금액 (숫자),
    "is_minor": 미성년자 여부 (19세 미만이면 true)
}"""
    }

    prompt = f"""당신은 상속세 계산을 위한 정보 추출 AI입니다.

## 규칙
1. 사용자의 자연어 답변을 분석하여 JSON으로 변환
2. 금액은 반드시 원 단위 정수로 (10억=1000000000, 5천만원=50000000, 3백만원=3000000)
3. 같은 카테고리의 항목은 합산
4. 언급되지 않은 항목은 0 또는 false
5. JSON만 출력 (다른 설명 없이)
6. 줄임말, 은어, 비표준 표현도 문맥에서 추론하여 올바른 카테고리로 분류

## 출력 형식
{prompts.get(parse_type, "")}

## 사용자 입력
{user_input}

JSON 응답:"""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )

        # JSON 파싱
        result_text = response.text.strip()
        # JSON 블록 추출 (```json ... ``` 형태 처리)
        if "```" in result_text:
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', result_text, re.DOTALL)
            if match:
                result_text = match.group(1)

        return json.loads(result_text)

    except Exception as e:
        st.error(f"LLM 파싱 오류: {e}")
        return None


# ============================================
# 유틸리티 함수
# ============================================

def format_currency(amount: int) -> str:
    """금액을 한국 원화 형식으로 포맷"""
    if amount >= 100_000_000:
        억 = amount // 100_000_000
        만 = (amount % 100_000_000) // 10_000
        if 만 > 0:
            return f"{억}억 {만:,}만원"
        return f"{억}억원"
    elif amount >= 10_000:
        return f"{amount // 10_000:,}만원"
    else:
        return f"{amount:,}원"


def get_tax_rate_info(taxable_amount: int) -> str:
    """해당 과세표준에 적용되는 세율 정보 반환"""
    if taxable_amount <= 0:
        return "과세표준 0원 → 세금 없음"

    for bracket, rate, deduction in TAX_BRACKETS:
        if taxable_amount <= bracket:
            rate_pct = int(rate * 100)
            if deduction > 0:
                return f"세율 {rate_pct}%, 누진공제 {format_currency(deduction)}"
            return f"세율 {rate_pct}%"

    rate_pct = int(TAX_BRACKETS[-1][1] * 100)
    deduction = TAX_BRACKETS[-1][2]
    return f"세율 {rate_pct}%, 누진공제 {format_currency(deduction)}"


def get_legal_inheritance_shares(has_spouse: bool, num_children: int) -> dict:
    """
    법정 상속분 비율 계산
    - 배우자 + 직계비속: 배우자 1.5 : 자녀 각 1
    - 직계비속만: 균등 분배
    - 배우자만: 배우자 100%
    """
    shares = {}

    if has_spouse and num_children > 0:
        # 배우자 1.5, 자녀 각 1
        total = 1.5 + num_children
        shares["배우자"] = 1.5 / total
        shares["자녀 1인당"] = 1.0 / total
    elif has_spouse:
        shares["배우자"] = 1.0
    elif num_children > 0:
        shares["자녀 1인당"] = 1.0 / num_children
    else:
        shares["상속인 없음"] = 0

    return shares


def format_share_ratio(shares: dict) -> str:
    """법정 상속분을 보기 좋게 포맷"""
    lines = []
    for name, ratio in shares.items():
        if ratio > 0:
            percentage = ratio * 100
            # 분수 표현 계산
            if name == "배우자" and "자녀 1인당" in shares:
                # 배우자 + 자녀 케이스
                child_ratio = shares["자녀 1인당"]
                total_parts = 1.5 + (1.0 / child_ratio - 1.5)
                lines.append(f"  - {name}: {percentage:.1f}% (1.5/{total_parts:.1f})")
            else:
                lines.append(f"  - {name}: {percentage:.1f}%")
    return "\n".join(lines)


# ============================================
# 자연어 파싱 함수
# ============================================

def parse_korean_number(text: str) -> int:
    """
    한글 숫자 표현을 정수로 변환
    예: "10억", "5천만원", "3000만", "1.5억", "천만원" → 정수
    """
    text = text.strip().replace(",", "").replace("원", "")

    # 억 단위
    match = re.match(r"(\d+\.?\d*)\s*억", text)
    if match:
        num = float(match.group(1))
        return int(num * 100_000_000)

    # 천만 단위 (숫자 + 천만)
    match = re.match(r"(\d+\.?\d*)\s*천만", text)
    if match:
        num = float(match.group(1))
        return int(num * 10_000_000)

    # 순수 "천만" (숫자 없이)
    if text == "천만" or text.startswith("천만"):
        return 10_000_000

    # 백만 단위
    match = re.match(r"(\d+\.?\d*)\s*백만", text)
    if match:
        num = float(match.group(1))
        return int(num * 1_000_000)

    # 순수 "백만" (숫자 없이)
    if text == "백만" or text.startswith("백만"):
        return 1_000_000

    # 만 단위
    match = re.match(r"(\d+\.?\d*)\s*만", text)
    if match:
        num = float(match.group(1))
        return int(num * 10_000)

    # 순수 숫자 (이미 원 단위라고 가정)
    match = re.match(r"(\d+)", text)
    if match:
        return int(match.group(1))

    return 0


def parse_assets(text: str) -> dict:
    """
    자연어 입력에서 자산 정보 추출
    예: "부동산 10억, 현금 5천만원, 금융자산 3억"
    """
    assets = {
        "real_estate": 0,
        "financial": 0,
        "securities": 0,
        "cash": 0,
        "insurance": 0,
        "retirement": 0,
        "trust": 0,
        "other": 0
    }

    # 카테고리 매핑
    category_map = {
        # 부동산
        "부동산": "real_estate",
        "아파트": "real_estate",
        "토지": "real_estate",
        "건물": "real_estate",
        "주택": "real_estate",
        "집": "real_estate",
        "상가": "real_estate",
        "빌딩": "real_estate",
        "오피스텔": "real_estate",
        "땅": "real_estate",
        "다세대": "real_estate",
        "단독주택": "real_estate",
        "빌라": "real_estate",
        "지식산업센터": "real_estate",
        "지산": "real_estate",
        "공장": "real_estate",
        "창고": "real_estate",
        "사무실": "real_estate",
        "원룸": "real_estate",
        "다가구": "real_estate",
        "타운하우스": "real_estate",
        "펜션": "real_estate",
        "모텔": "real_estate",
        "호텔": "real_estate",
        # 금융자산
        "금융": "financial",
        "금융자산": "financial",
        "예금": "financial",
        "적금": "financial",
        "저축": "financial",
        "통장": "financial",
        # 유가증권
        "유가증권": "securities",
        "주식": "securities",
        "채권": "securities",
        "펀드": "securities",
        # 기타
        "현금": "cash",
        "보험": "insurance",
        "보험금": "insurance",
        "퇴직금": "retirement",
        "신탁": "trust",
        "신탁재산": "trust",
        "기타": "other",
        "자동차": "other",
        "차량": "other"
    }

    # 패턴: (카테고리)(금액) - 수량 단위(채, 개, 동, 호 등)는 제외
    for category_kr, category_en in category_map.items():
        # "부동산 10억" 또는 "부동산10억" 형태
        # 숫자 뒤에 채/개/동/호 등이 오면 수량이므로 제외
        pattern = rf"{category_kr}\s*(?:\d+\s*(?:채|개|동|호|곳|군데)\s*)?(?:.*?)?(\d+\.?\d*\s*(?:억|천만|백만|만))\s*(?:원|정도|쯤)?"
        matches = re.findall(pattern, text)
        for match in matches:
            amount = parse_korean_number(match)
            if amount > 0:
                assets[category_en] += amount

    return assets


def parse_yes_no(text: str) -> bool:
    """예/아니오 파싱"""
    positive = ["예", "네", "응", "그래", "있어", "있습니다", "있어요", "생존", "살아계셔", "yes", "y"]
    text_lower = text.lower().strip()
    return any(p in text_lower for p in positive)


def parse_age(text: str) -> int:
    """나이 파싱"""
    match = re.search(r"(\d+)\s*(?:세|살)?", text)
    if match:
        return int(match.group(1))
    return 0


def parse_children_count(text: str) -> int:
    """자녀 수 파싱"""
    # "없어", "없습니다" 등
    if any(neg in text for neg in ["없", "0명", "영"]):
        return 0

    match = re.search(r"(\d+)\s*(?:명)?", text)
    if match:
        return int(match.group(1))
    return 0


def parse_children_ages(text: str) -> list:
    """자녀 나이들 파싱"""
    ages = re.findall(r"(\d+)\s*(?:세|살)?", text)
    return [int(age) for age in ages]


def parse_debts(text: str) -> dict:
    """채무/비용 파싱"""
    result = {
        "public_charges": 0,
        "funeral_expense": 0,
        "funeral_memorial": 0,
        "debt": 0
    }

    # 카테고리별 키워드 목록 (긴 키워드부터 정렬하여 중복 방지)
    category_keywords = {
        "public_charges": ["공공요금", "공과금", "세금"],
        "funeral_expense": ["장례식장", "장례식", "장례비", "장례", "장의"],
        "funeral_memorial": ["봉안시설", "봉안", "묘지", "납골", "매장", "화장"],
        "debt": ["근저당", "담보대출", "대출", "채무", "부채", "차입", "빚"]
    }

    # 이미 매칭된 위치 추적
    matched_positions = set()

    # 각 카테고리별로 금액 찾기
    for category_en, keywords in category_keywords.items():
        for keyword in keywords:
            # "키워드 금액" 또는 "키워드비용 금액" 형태
            pattern = rf"{keyword}(?:비용|비|용|액)?\s*(\d+\.?\d*\s*(?:억|천만|백만|만)?(?:원)?)"
            for match in re.finditer(pattern, text):
                start_pos = match.start()
                # 이미 매칭된 위치면 건너뛰기
                if any(start_pos >= s and start_pos < e for s, e in matched_positions):
                    continue
                amount = parse_korean_number(match.group(1))
                if amount > 0:
                    result[category_en] += amount
                    matched_positions.add((match.start(), match.end()))

    return result


def parse_prior_gift(text: str) -> dict:
    """사전증여 파싱"""
    result = {
        "amount": 0,
        "tax": 0
    }

    # 금액 찾기
    amount_patterns = [r"(\d+\.?\d*\s*(?:억|천만|백만|만)?)"]
    for pattern in amount_patterns:
        matches = re.findall(pattern, text)
        if matches:
            result["amount"] = parse_korean_number(matches[0])
            break

    # 납부세액 찾기
    tax_pattern = r"(?:세금|증여세)\s*(\d+\.?\d*\s*(?:억|천만|백만|만)?)"
    tax_match = re.search(tax_pattern, text)
    if tax_match:
        result["tax"] = parse_korean_number(tax_match.group(1))

    return result


# ============================================
# 대화 단계 정의
# ============================================

STEPS = [
    "assets",           # 0: 상속재산
    "real_estate_debt", # 1: 부동산 관련 채무 (임대보증금, 대출)
    "spouse",           # 2: 배우자 유무
    "spouse_detail",    # 3: 배우자 상세 (있는 경우)
    "children",         # 4: 자녀 유무/수
    "children_detail",  # 5: 자녀 상세 (있는 경우)
    "grandchild",       # 6: 세대생략 상속 여부
    "grandchild_detail",# 7: 세대생략 상세 (있는 경우)
    "funeral_costs",    # 8: 장례비용
    "other_debts",      # 9: 기타 채무
    "prior_gift",       # 10: 사전증여 유무
    "prior_gift_detail",# 11: 사전증여 상세 (있는 경우)
    "co_residence",     # 12: 동거주택공제
    "confirm",          # 13: 최종 확인
    "result"            # 14: 결과
]


def get_step_question(step: str, data: dict) -> str:
    """각 단계별 질문 반환"""
    questions = {
        "assets": """상속재산을 알려주세요.

**예시**: "15억 짜리 아파트가 하나 있고, 사망보험금 2억원이 있어요" 처럼 자유롭게 적어주세요.""",

        "real_estate_debt": """해당 부동산에 임대보증금이나 대출(담보대출)이 있으신가요?

**예시**: "임대보증금 2억, 대출 3억" 또는 "없어요"

이 금액은 채무로 공제됩니다.""",

        "spouse": "배우자가 생존해 계신가요?",

        "spouse_detail": """배우자 정보를 알려주세요.

**예시**: "65세" 또는 "60세, 장애인"

장애인인 경우 기대여명도 함께 알려주세요. (예: "70세, 장애인, 기대여명 15년")""",

        "children": """자녀가 있으신가요? 몇 명인가요?

**예시**: "2명" 또는 "없어요" """,

        "children_detail": f"""자녀 {data.get('num_children', 0)}명의 나이를 알려주세요.

**예시**: "35세, 30세" 또는 "40살, 38살, 35살"

미성년자나 장애인이 있으면 추가로 알려주세요.""",

        "grandchild": """혹시 **세대생략 상속**을 계획하고 계신가요?

**세대생략 상속이란?**
자녀를 건너뛰고 손자녀에게 직접 상속하는 것을 말합니다.
- 장점: 상속세를 한 번만 내고 2세대에 걸쳐 재산 이전 가능
- 단점: 산출세액의 **30% 할증** (미성년 손자녀가 20억 초과 상속 시 40%)
- 예외: 자녀가 먼저 사망한 경우 손자녀가 대습상속하면 할증 없음""",

        "grandchild_detail": """손자녀 정보를 알려주세요.

**예시**: "25세 손자에게 5억" 또는 "10세, 3억원 상속 예정"

손자녀의 나이와 상속 예정 금액을 알려주세요.""",

        "funeral_costs": """장례비용이 있으신가요?

**예시**: "장례비 1000만원" 또는 "장례식 800만원, 봉안시설 300만원" 또는 "없어요"

(장례비는 최소 500만원 ~ 최대 1000만원 공제, 봉안시설은 별도 500만원 한도)""",

        "other_debts": """기타 채무나 공과금이 있으신가요?

**예시**: "채무 5천만원, 공과금 100만원" 또는 "없어요"

(부동산 관련 채무는 이미 입력하셨으므로 제외)""",

        "prior_gift": "10년 내에 상속인에게 증여한 재산이 있으신가요?",

        "prior_gift_detail": """증여 금액과 납부한 증여세를 알려주세요.

**예시**: "3억, 증여세 2천만원 납부" 또는 "5억원 증여, 세금 5천만원"

증여세를 납부하지 않았다면 금액만 입력하셔도 됩니다.""",

        "co_residence": """**동거주택공제** 요건을 충족하시나요?

요건:
- 피상속인과 상속인(직계비속)이 10년 이상 동거
- 10년 이상 1세대 1주택
- 상속인이 무주택자

(공제 한도: 6억원)""",

        "confirm": "모든 정보 입력이 완료되었습니다. 아래에서 입력 내용을 확인해주세요."
    }
    return questions.get(step, "")


def get_data_summary(data: dict) -> str:
    """현재까지 입력된 데이터 요약"""
    lines = []

    # 상속재산
    if data.get("assets"):
        assets = data["assets"]
        total = sum(assets.values())
        if total > 0:
            lines.append("### 상속재산")
            name_map = {
                "real_estate": "부동산",
                "financial": "금융자산",
                "securities": "유가증권",
                "cash": "현금",
                "insurance": "보험금",
                "retirement": "퇴직금",
                "trust": "신탁재산",
                "other": "기타"
            }
            for key, value in assets.items():
                if value > 0:
                    lines.append(f"- {name_map.get(key, key)}: {format_currency(value)}")
            lines.append(f"- **합계: {format_currency(total)}**")
            lines.append("")

    # 상속인
    lines.append("### 상속인")
    if data.get("has_spouse"):
        spouse_info = f"- 배우자: {data.get('spouse_age', 60)}세"
        if data.get("spouse_disabled"):
            spouse_info += " (장애인)"
        lines.append(spouse_info)
    else:
        lines.append("- 배우자: 없음")

    if data.get("num_children", 0) > 0:
        children_ages = data.get("children_ages", [])
        ages_str = ', '.join(f"{a}세" for a in children_ages) if children_ages else ""
        lines.append(f"- 자녀: {data['num_children']}명 ({ages_str})")
    else:
        lines.append("- 자녀: 없음")

    if data.get("has_grandchild"):
        gc_age = data.get("grandchild_age")
        gc_amount = data.get("grandchild_amount", 0)
        if gc_age:
            gc_text = f"- **세대생략 상속**: 손자녀 {gc_age}세"
            if gc_age < 19:
                gc_text += " (미성년)"
            if gc_amount > 0:
                gc_text += f", {format_currency(gc_amount)}"
            if gc_age < 19 and gc_amount > 2_000_000_000:
                gc_text += " - **40% 할증**"
            else:
                gc_text += " - **30% 할증**"
            lines.append(gc_text)
        else:
            lines.append("- **세대생략 상속: 예정** (30% 할증 적용)")
    lines.append("")

    # 장례비용
    lines.append("### 장례비용")
    debts = data.get("debts", {})
    has_funeral = False
    if debts.get("funeral_expense", 0) > 0:
        lines.append(f"- 장례비: {format_currency(debts['funeral_expense'])}")
        has_funeral = True
    if debts.get("funeral_memorial", 0) > 0:
        lines.append(f"- 봉안시설: {format_currency(debts['funeral_memorial'])}")
        has_funeral = True
    if not has_funeral:
        lines.append("- 없음 (최소 500만원 공제 적용)")
    lines.append("")

    # 채무
    lines.append("### 채무")
    has_any_debt = False

    # 부동산 관련 채무
    re_debt = data.get("real_estate_debt", {})
    if re_debt.get("deposit", 0) > 0:
        lines.append(f"- 임대보증금: {format_currency(re_debt['deposit'])}")
        has_any_debt = True
    if re_debt.get("loan", 0) > 0:
        lines.append(f"- 부동산 대출: {format_currency(re_debt['loan'])}")
        has_any_debt = True

    # 기타 채무
    if debts.get("public_charges", 0) > 0:
        lines.append(f"- 공과금: {format_currency(debts['public_charges'])}")
        has_any_debt = True
    if debts.get("debt", 0) > 0:
        lines.append(f"- 기타 채무: {format_currency(debts['debt'])}")
        has_any_debt = True

    if not has_any_debt:
        lines.append("- 없음")
    lines.append("")

    # 사전증여
    lines.append("### 사전증여")
    if data.get("prior_gift_amount", 0) > 0:
        lines.append(f"- 증여액: {format_currency(data['prior_gift_amount'])}")
        if data.get("prior_gift_tax", 0) > 0:
            lines.append(f"- 납부 증여세: {format_currency(data['prior_gift_tax'])}")
    else:
        lines.append("- 없음")
    lines.append("")

    # 공제
    lines.append("### 추가사항")
    if data.get("co_residence"):
        lines.append("- 동거주택공제: 적용")
    else:
        lines.append("- 동거주택공제: 미적용")
    lines.append("- 신고세액공제: 3% 적용 (기한 내 신고 기준)")

    return "\n".join(lines)


# ============================================
# 메시지 처리
# ============================================

def add_message(role: str, content: str, step: int = None):
    """대화 기록에 메시지 추가 (step 정보 포함)"""
    if step is None:
        step = st.session_state.step
    st.session_state.messages.append({"role": role, "content": content, "step": step})


def process_input(user_input: str):
    """사용자 입력 처리 (LLM 우선, 정규식 fallback)"""
    step = STEPS[st.session_state.step]
    data = st.session_state.data
    use_llm = GEMINI_API_KEY and GEMINI_AVAILABLE

    # 사용자 메시지 저장
    add_message("user", user_input)

    response = ""
    next_step = st.session_state.step + 1

    if step == "assets":
        # LLM 파싱 시도
        assets = None
        if use_llm:
            llm_result = parse_with_llm(user_input, "assets")
            if llm_result:
                assets = {
                    "real_estate": llm_result.get("real_estate", 0) or 0,
                    "financial": llm_result.get("financial", 0) or 0,
                    "securities": llm_result.get("securities", 0) or 0,
                    "cash": llm_result.get("cash", 0) or 0,
                    "insurance": llm_result.get("insurance", 0) or 0,
                    "retirement": llm_result.get("retirement", 0) or 0,
                    "trust": llm_result.get("trust", 0) or 0,
                    "other": llm_result.get("other", 0) or 0
                }

        # Fallback to regex parsing
        if not assets or sum(assets.values()) == 0:
            assets = parse_assets(user_input)

        total = sum(assets.values())

        if total > 0:
            data["assets"] = assets
            response = f"확인했습니다.\n\n"
            for key, value in assets.items():
                if value > 0:
                    name_map = {
                        "real_estate": "부동산",
                        "financial": "금융자산",
                        "securities": "유가증권",
                        "cash": "현금",
                        "insurance": "보험금",
                        "retirement": "퇴직금",
                        "trust": "신탁재산",
                        "other": "기타"
                    }
                    response += f"- {name_map.get(key, key)}: {format_currency(value)}\n"
            response += f"\n**총 상속재산: {format_currency(total)}**"

            # 부동산이 있으면 임대보증금/대출 질문, 없으면 배우자 질문으로
            if assets.get("real_estate", 0) > 0:
                next_step = STEPS.index("real_estate_debt")
            else:
                next_step = STEPS.index("spouse")
        else:
            response = "금액을 인식하지 못했습니다. 다시 입력해주세요.\n\n예: '부동산 10억, 현금 5천만원'"
            next_step = st.session_state.step  # 현재 단계 유지

    elif step == "real_estate_debt":
        # LLM 파싱 시도
        re_debt = None
        if use_llm:
            llm_result = parse_with_llm(user_input, "real_estate_debt")
            if llm_result:
                re_debt = {
                    "deposit": llm_result.get("deposit", 0) or 0,
                    "loan": llm_result.get("loan", 0) or 0
                }

        # Fallback (LLM 실패하거나 결과가 0인 경우)
        if not re_debt or sum(re_debt.values()) == 0:
            if any(neg in user_input for neg in ["없", "아니", "no"]):
                re_debt = {"deposit": 0, "loan": 0}
            else:
                # 간단한 정규식 파싱
                re_debt = {"deposit": 0, "loan": 0}

                # 보증금 (전세보증금, 임대보증금 등 모두 찾기)
                deposit_patterns = ["전세보증금", "임대보증금", "월세보증금", "보증금", "전세"]
                for kw in deposit_patterns:
                    pattern = rf"{kw}\s*(\d+\.?\d*\s*(?:억|천만|백만|만)?(?:원)?)"
                    for match in re.finditer(pattern, user_input):
                        re_debt["deposit"] += parse_korean_number(match.group(1))

                # 대출 (모두 찾기)
                loan_patterns = ["담보대출", "근저당", "주택담보", "대출", "대출금", "융자"]
                for kw in loan_patterns:
                    pattern = rf"{kw}\s*(\d+\.?\d*\s*(?:억|천만|백만|만)?(?:원)?)"
                    for match in re.finditer(pattern, user_input):
                        re_debt["loan"] += parse_korean_number(match.group(1))

                # 키워드 없이 금액만 입력한 경우 -> 대출로 처리
                if re_debt["deposit"] == 0 and re_debt["loan"] == 0:
                    amount_pattern = r"(\d+\.?\d*\s*(?:억|천만|백만|만))\s*(?:원|정도)?"
                    match = re.search(amount_pattern, user_input)
                    if match:
                        re_debt["loan"] = parse_korean_number(match.group(1))

        data["real_estate_debt"] = re_debt
        total_re_debt = re_debt["deposit"] + re_debt["loan"]

        if total_re_debt > 0:
            response = "부동산 관련 채무 확인:\n"
            if re_debt["deposit"] > 0:
                response += f"- 임대보증금: {format_currency(re_debt['deposit'])}\n"
            if re_debt["loan"] > 0:
                response += f"- 대출: {format_currency(re_debt['loan'])}\n"
            response += f"\n이 금액은 채무로 공제됩니다."
        else:
            response = "부동산 관련 채무가 없으시군요."

        next_step = STEPS.index("spouse")

    elif step == "spouse":
        # LLM 파싱 시도 - yes_no 프롬프트 사용
        has_spouse = None
        if use_llm:
            llm_result = parse_with_llm(user_input, "yes_no")
            if llm_result:
                has_spouse = llm_result.get("answer", False)

        # Fallback
        if has_spouse is None:
            has_spouse = parse_yes_no(user_input)

        data["has_spouse"] = has_spouse

        if has_spouse:
            response = "배우자가 계시는군요."
            next_step = STEPS.index("spouse_detail")
        else:
            response = "배우자가 없으시군요."
            next_step = STEPS.index("children")

    elif step == "spouse_detail":
        # LLM 파싱 시도
        if use_llm:
            llm_result = parse_with_llm(user_input, "spouse")
            if llm_result:
                age = llm_result.get("age", 60) or 60
                # 출생년도로 보이면 나이로 변환 (1900~2025 범위)
                if 1900 <= age <= 2025:
                    age = 2025 - age
                data["spouse_age"] = age
                data["spouse_disabled"] = llm_result.get("is_disabled", False)
                if data["spouse_disabled"]:
                    data["spouse_life_exp"] = llm_result.get("life_expectancy", 20) or 20
            else:
                # Fallback
                age = parse_age(user_input)
                if 1900 <= age <= 2025:
                    age = 2025 - age
                data["spouse_age"] = age if age > 0 else 60
                data["spouse_disabled"] = "장애" in user_input
        else:
            # Fallback
            age = parse_age(user_input)
            if 1900 <= age <= 2025:
                age = 2025 - age
            data["spouse_age"] = age if age > 0 else 60
            data["spouse_disabled"] = "장애" in user_input
            if data["spouse_disabled"]:
                life_exp_match = re.search(r"기대여명\s*(\d+)", user_input)
                data["spouse_life_exp"] = int(life_exp_match.group(1)) if life_exp_match else 20

        response = f"배우자 정보: {data['spouse_age']}세"
        if data.get("spouse_disabled"):
            response += f", 장애인 (기대여명 {data.get('spouse_life_exp', 20)}년)"

    elif step == "children":
        # LLM 파싱 시도
        num = None
        has_children = None
        ages = None

        if use_llm:
            llm_result = parse_with_llm(user_input, "children_count")
            if llm_result:
                has_children = llm_result.get("has_children")
                num = llm_result.get("num_children")  # None일 수 있음

        # Fallback - 자녀 없음 표현 확인
        if has_children is None:
            if any(neg in user_input for neg in ["없", "아니", "no"]):
                has_children = False
                num = 0
            else:
                has_children = True

        # 자녀가 있다고 했는데 수를 모르는 경우
        if has_children and num is None:
            # 정규식으로 숫자 추출 시도
            num = parse_children_count(user_input)
            if num == 0:
                # 숫자를 찾지 못함 - 재입력 요청
                response = "자녀가 몇 명인지 정확히 알려주세요.\n\n**예시**: \"2명\", \"아들 하나 딸 둘\""
                next_step = st.session_state.step  # 현재 단계 유지
                add_message("assistant", response)
                st.session_state.step_history.append(st.session_state.step)
                st.session_state.step = next_step
                return

        # 자녀 없음
        if not has_children or num == 0:
            data["num_children"] = 0
            response = "자녀가 없으시군요."
            next_step = STEPS.index("funeral_costs")
        else:
            data["num_children"] = num
            response = f"자녀 {num}명이시군요."
            next_step = STEPS.index("children_detail")

    elif step == "children_detail":
        # LLM 파싱 시도
        ages = None
        if use_llm:
            llm_result = parse_with_llm(user_input, "children")
            if llm_result:
                ages = llm_result.get("ages", [])
                data["has_disabled_child"] = llm_result.get("has_disabled", False)

        # Fallback
        if not ages:
            ages = parse_children_ages(user_input)
            data["has_disabled_child"] = "장애" in user_input

        # 출생년도로 보이면 나이로 변환
        ages = [2025 - a if 1900 <= a <= 2025 else a for a in ages]

        num_children = data.get("num_children", 0)

        # 나이 처리
        if len(ages) == 1 and num_children > 1:
            # 나이 하나만 입력하면 모든 자녀가 그 나이라고 가정
            ages = [ages[0]] * num_children
        elif len(ages) < num_children:
            # 나이가 부족하면 다시 입력 요청
            response = f"자녀가 {num_children}명인데 나이가 {len(ages)}개만 입력되었습니다.\n\n"
            response += f"**{num_children}명 모두의 나이를 입력해주세요.** (예: 45, 42, 40, 38)"
            next_step = st.session_state.step  # 현재 단계 유지
            add_message("assistant", response)
            st.session_state.step_history.append(st.session_state.step)
            st.session_state.step = next_step
            return

        data["children_ages"] = ages[:num_children]
        data["num_children"] = len(data["children_ages"])

        response = f"자녀 정보: {', '.join(str(a)+'세' for a in data['children_ages'])}"
        if data.get("has_disabled_child"):
            response += " (장애인 자녀 포함)"
        next_step = STEPS.index("grandchild")

    elif step == "grandchild":
        # 세대생략 상속 여부 - 버튼으로 처리하지만 fallback으로 LLM 해석도 유지
        has_grandchild = None

        if use_llm:
            llm_result = parse_with_llm(user_input, "grandchild")
            if llm_result:
                has_grandchild = llm_result.get("has_grandchild")

        # Fallback
        if has_grandchild is None:
            if any(pos in user_input for pos in ["네", "예", "응", "있", "할", "손자", "손녀", "손주"]):
                has_grandchild = True
            else:
                has_grandchild = False

        data["has_grandchild"] = has_grandchild

        if has_grandchild:
            response = "세대생략 상속을 계획하고 계시군요."
            next_step = STEPS.index("grandchild_detail")
        else:
            response = "세대생략 상속은 없으시군요."
            next_step = STEPS.index("funeral_costs")

    elif step == "grandchild_detail":
        # 손자녀 상세 정보 - LLM 파싱
        gc_age = None
        gc_amount = 0

        if use_llm:
            llm_result = parse_with_llm(user_input, "grandchild_detail")
            if llm_result:
                gc_age = llm_result.get("age")
                gc_amount = llm_result.get("amount", 0) or 0
                # 출생년도로 보이면 나이로 변환
                if gc_age and 1900 <= gc_age <= 2025:
                    gc_age = 2025 - gc_age

        # Fallback - 정규식으로 파싱
        if gc_age is None or gc_amount == 0:
            # 나이 추출
            age_match = re.search(r"(\d+)\s*(?:세|살)", user_input)
            if age_match:
                gc_age = int(age_match.group(1))
                if 1900 <= gc_age <= 2025:
                    gc_age = 2025 - gc_age

            # 금액 추출
            amount_pattern = r"(\d+\.?\d*\s*(?:억|천만|백만|만))\s*(?:원)?"
            amount_match = re.search(amount_pattern, user_input)
            if amount_match:
                gc_amount = parse_korean_number(amount_match.group(1))

        # 데이터 저장
        if gc_age and gc_age > 0:
            data["grandchild_age"] = gc_age
            data["grandchild_amount"] = gc_amount
            data["grandchild_is_minor"] = gc_age < 19

            response = f"손자녀 정보: {gc_age}세"
            if gc_age < 19:
                response += " (미성년자)"
            if gc_amount > 0:
                response += f", 상속 예정 금액: {format_currency(gc_amount)}"
                if gc_age < 19 and gc_amount > 2_000_000_000:
                    response += "\n⚠️ 미성년자 20억 초과 상속으로 **40% 할증** 적용"
                else:
                    response += "\n(30% 할증 적용)"
            next_step = STEPS.index("funeral_costs")
        else:
            response = "손자녀 나이를 인식하지 못했습니다. 다시 입력해주세요.\n\n예: '25세 손자에게 5억'"
            next_step = st.session_state.step  # 현재 단계 유지

    elif step == "funeral_costs":
        # LLM 파싱 시도
        funeral = {"funeral_expense": 0, "funeral_memorial": 0}
        has_costs = None

        if use_llm:
            llm_result = parse_with_llm(user_input, "funeral_costs")
            if llm_result:
                has_costs = llm_result.get("has_costs")
                funeral["funeral_expense"] = llm_result.get("funeral_expense", 0) or 0
                funeral["funeral_memorial"] = llm_result.get("funeral_memorial", 0) or 0

        # Fallback - 없음 표현 확인
        if has_costs is None:
            if any(neg in user_input for neg in ["없", "아니", "no", "모르"]):
                has_costs = False
            else:
                has_costs = True

        # LLM이 금액을 못 찾았으면 정규식 시도
        if has_costs and sum(funeral.values()) == 0:
            # 금액 패턴 (숫자 또는 한글 숫자로 시작)
            amount_pattern = r"(\d+\.?\d*\s*(?:억|천만|백만|만)?(?:원)?|(?:천만|백만|천|백)\s*(?:원)?)"

            # 장례비
            for kw in ["장례식장", "장례식", "장례비", "장례", "장의"]:
                pattern = rf"{kw}\s*(?:비용|비|용|액)?\s*{amount_pattern}"
                match = re.search(pattern, user_input)
                if match:
                    funeral["funeral_expense"] += parse_korean_number(match.group(1))
                    break

            # 봉안시설
            for kw in ["봉안시설", "봉안", "묘지", "납골당", "납골", "매장", "화장"]:
                pattern = rf"{kw}\s*(?:비용|비|용|액)?\s*{amount_pattern}"
                match = re.search(pattern, user_input)
                if match:
                    funeral["funeral_memorial"] += parse_korean_number(match.group(1))
                    break

            # 키워드 없이 금액만 입력한 경우 -> 장례비로 처리
            if sum(funeral.values()) == 0:
                simple_pattern = r"(\d+\.?\d*\s*(?:억|천만|백만|만)|(?:천만|백만))\s*(?:원|정도)?"
                match = re.search(simple_pattern, user_input)
                if match:
                    funeral["funeral_expense"] = parse_korean_number(match.group(1))

        # 기존 debts 데이터가 없으면 초기화
        if "debts" not in data:
            data["debts"] = {"public_charges": 0, "funeral_expense": 0, "funeral_memorial": 0, "debt": 0}

        data["debts"]["funeral_expense"] = funeral["funeral_expense"]
        data["debts"]["funeral_memorial"] = funeral["funeral_memorial"]

        total = sum(funeral.values())
        if total > 0:
            response = "장례비용 확인:\n"
            if funeral["funeral_expense"] > 0:
                response += f"- 장례비: {format_currency(funeral['funeral_expense'])}\n"
            if funeral["funeral_memorial"] > 0:
                response += f"- 봉안시설: {format_currency(funeral['funeral_memorial'])}\n"
        else:
            response = "장례비용이 없으시군요. (최소 500만원 공제 적용)"

        next_step = STEPS.index("other_debts")

    elif step == "other_debts":
        # 기타 채무 파싱
        other = {"public_charges": 0, "debt": 0}
        has_debts = None

        if use_llm:
            llm_result = parse_with_llm(user_input, "other_debts")
            if llm_result:
                has_debts = llm_result.get("has_debts")
                other["public_charges"] = llm_result.get("public_charges", 0) or 0
                other["debt"] = llm_result.get("debt", 0) or 0

        # Fallback - 없음 표현 확인
        if has_debts is None:
            if any(neg in user_input for neg in ["없", "아니", "no", "모르"]):
                has_debts = False
            else:
                has_debts = True

        # LLM이 금액을 못 찾았으면 정규식 시도
        if has_debts and sum(other.values()) == 0:
            # 공과금
            for kw in ["공과금", "공공요금", "관리비", "세금"]:
                pattern = rf"{kw}\s*(\d+\.?\d*\s*(?:억|천만|백만|만)?(?:원)?)"
                match = re.search(pattern, user_input)
                if match:
                    other["public_charges"] += parse_korean_number(match.group(1))
                    break

            # 채무
            for kw in ["채무", "대출", "빚", "부채", "카드"]:
                pattern = rf"{kw}\s*(\d+\.?\d*\s*(?:억|천만|백만|만)?(?:원)?)"
                match = re.search(pattern, user_input)
                if match:
                    other["debt"] += parse_korean_number(match.group(1))
                    break

            # 키워드 없이 금액만 입력한 경우 -> 채무로 처리
            if sum(other.values()) == 0:
                amount_pattern = r"(\d+\.?\d*\s*(?:억|천만|백만|만))\s*(?:원|정도)?"
                match = re.search(amount_pattern, user_input)
                if match:
                    other["debt"] = parse_korean_number(match.group(1))

        # 기존 debts 데이터가 없으면 초기화
        if "debts" not in data:
            data["debts"] = {"public_charges": 0, "funeral_expense": 0, "funeral_memorial": 0, "debt": 0}

        data["debts"]["public_charges"] = other["public_charges"]
        data["debts"]["debt"] = other["debt"]

        total = sum(other.values())
        if total > 0:
            response = "기타 채무 확인:\n"
            if other["public_charges"] > 0:
                response += f"- 공과금: {format_currency(other['public_charges'])}\n"
            if other["debt"] > 0:
                response += f"- 채무: {format_currency(other['debt'])}\n"
        else:
            response = "기타 채무가 없으시군요."

        next_step = STEPS.index("prior_gift")

    elif step == "prior_gift":
        # 사전증여 유무 확인 (예/아니오)
        has_gift = None
        if use_llm:
            llm_result = parse_with_llm(user_input, "yes_no")
            if llm_result:
                has_gift = llm_result.get("answer", False)

        # Fallback
        if has_gift is None:
            has_gift = parse_yes_no(user_input)

        data["has_prior_gift"] = has_gift

        if has_gift:
            response = "사전증여가 있으시군요."
            next_step = STEPS.index("prior_gift_detail")
        else:
            response = "사전증여가 없으시군요."
            data["prior_gift_amount"] = 0
            data["prior_gift_tax"] = 0
            next_step = STEPS.index("co_residence")

    elif step == "prior_gift_detail":
        # 사전증여 금액/세금 파싱
        gift = {"amount": 0, "tax": 0}
        has_gift = None

        if use_llm:
            llm_result = parse_with_llm(user_input, "prior_gift")
            if llm_result:
                has_gift = llm_result.get("has_gift")
                gift["amount"] = llm_result.get("amount", 0) or 0
                gift["tax"] = llm_result.get("tax", 0) or 0

        # Fallback - 없음 표현 확인 (사전 단계에서 있다고 했으므로 기본적으로 true)
        if has_gift is None:
            if any(neg in user_input for neg in ["없", "아니", "no", "모르"]):
                has_gift = False
            else:
                has_gift = True

        # LLM이 금액을 못 찾았으면 정규식 시도
        if has_gift and gift["amount"] == 0:
            parsed = parse_prior_gift(user_input)
            if parsed:
                gift["amount"] = parsed.get("amount", 0)
                gift["tax"] = parsed.get("tax", 0)

            # 키워드 없이 금액만 입력한 경우
            if gift["amount"] == 0:
                amount_pattern = r"(\d+\.?\d*\s*(?:억|천만|백만|만))\s*(?:원|정도)?"
                match = re.search(amount_pattern, user_input)
                if match:
                    gift["amount"] = parse_korean_number(match.group(1))

        data["prior_gift_amount"] = gift["amount"]
        data["prior_gift_tax"] = gift["tax"]

        if gift["amount"] > 0:
            response = f"사전증여: {format_currency(gift['amount'])}"
            if gift["tax"] > 0:
                response += f", 납부 증여세: {format_currency(gift['tax'])}"
            next_step = STEPS.index("co_residence")
        elif not has_gift:
            # 사용자가 없다고 명시한 경우 - 이전 단계로 돌아가거나 0으로 처리
            response = "사전증여가 없으시군요."
            data["prior_gift_amount"] = 0
            data["prior_gift_tax"] = 0
            next_step = STEPS.index("co_residence")
        else:
            response = "금액을 인식하지 못했습니다. 다시 입력해주세요.\n\n예: '3억, 증여세 2천만원'"
            next_step = st.session_state.step  # 현재 단계 유지

    elif step == "co_residence":
        # LLM 파싱 시도
        answer = None
        if use_llm:
            llm_result = parse_with_llm(user_input, "yes_no")
            if llm_result:
                answer = llm_result.get("answer", False)

        # Fallback
        if answer is None:
            answer = parse_yes_no(user_input)

        data["co_residence"] = answer
        if data["co_residence"]:
            response = "동거주택공제 요건을 충족하시는군요."
        else:
            response = "동거주택공제는 적용되지 않습니다."

    elif step == "confirm":
        if "수정" in user_input:
            response = "처음부터 다시 시작합니다."
            st.session_state.step = 0
            st.session_state.data = {}
            st.session_state.messages = []
            add_message("assistant", "안녕하세요, 상속세 계산을 도와드리겠습니다. 대화 형식으로 편하게 말씀해 주시면 됩니다.\n\n" + get_step_question("assets", {}))
            return
        else:
            response = "정보 확인이 완료되었습니다. 상속세를 계산합니다..."
            next_step = STEPS.index("result")

    # 응답 메시지 추가
    add_message("assistant", response)

    # 다음 단계로 이동
    st.session_state.step_history.append(st.session_state.step)
    st.session_state.step = next_step

    # 다음 질문 추가 (결과 단계가 아닌 경우)
    if next_step < len(STEPS) - 1:
        next_question = get_step_question(STEPS[next_step], data)
        if next_question:
            add_message("assistant", next_question)


def go_back():
    """이전 단계로 돌아가기"""
    if st.session_state.step_history:
        prev_step = st.session_state.step_history.pop()
        jump_to_step(prev_step, clear_data=False)


def jump_to_step(target_step: int, clear_data: bool = True):
    """특정 단계로 이동 (수정 기능용)"""
    # 해당 단계 이후의 메시지 모두 제거
    st.session_state.messages = [
        msg for msg in st.session_state.messages
        if msg.get("step", 0) < target_step
    ]

    # step_history에서 target_step 이후 기록 제거
    st.session_state.step_history = [
        s for s in st.session_state.step_history if s < target_step
    ]

    # 관련 데이터 초기화 (선택적)
    if clear_data:
        clear_step_data(target_step)

    # 단계 이동
    st.session_state.step = target_step

    # 해당 단계 질문 추가
    step_name = STEPS[target_step]
    question = get_step_question(step_name, st.session_state.data)
    if question:
        add_message("assistant", question, step=target_step)


def clear_step_data(from_step: int):
    """특정 단계부터의 데이터 초기화"""
    data = st.session_state.data
    step_name = STEPS[from_step]

    # 단계별 데이터 매핑
    step_data_keys = {
        "assets": ["assets"],
        "real_estate_debt": ["real_estate_debt"],
        "spouse": ["has_spouse"],
        "spouse_detail": ["spouse_age", "spouse_disabled", "spouse_life_exp"],
        "children": ["num_children", "has_disabled_child"],
        "children_detail": ["children_ages"],
        "grandchild": ["has_grandchild"],
        "grandchild_detail": ["grandchild_age", "grandchild_amount", "grandchild_is_minor"],
        "funeral_costs": [],  # debts 내부 키는 개별 처리
        "other_debts": [],
        "prior_gift": ["has_prior_gift"],
        "prior_gift_detail": ["prior_gift_amount", "prior_gift_tax"],
        "co_residence": ["co_residence"],
    }

    # 현재 단계의 데이터 삭제
    if step_name in step_data_keys:
        for key in step_data_keys[step_name]:
            if key in data:
                del data[key]

    # 장례비용/기타채무 특별 처리
    if step_name == "funeral_costs" and "debts" in data:
        data["debts"]["funeral_expense"] = 0
        data["debts"]["funeral_memorial"] = 0
    elif step_name == "other_debts" and "debts" in data:
        data["debts"]["public_charges"] = 0
        data["debts"]["debt"] = 0


def build_inheritance_info(data: dict) -> InheritanceInfo:
    """수집된 데이터로 InheritanceInfo 객체 생성"""
    assets = data.get("assets", {})

    # 자녀 정보 구성
    children = []
    children_ages = data.get("children_ages", [])
    for age in children_ages:
        children.append(ChildInfo(
            age=age,
            is_disabled=data.get("has_disabled_child", False),
            is_grandchild=data.get("has_grandchild", False)
        ))

    # 채무 정보
    debts = data.get("debts", {})
    re_debt = data.get("real_estate_debt", {})

    # 부동산 관련 채무 (임대보증금 + 대출)를 일반 채무에 합산
    total_debt = debts.get("debt", 0) + re_debt.get("deposit", 0) + re_debt.get("loan", 0)

    return InheritanceInfo(
        asset=Asset(
            real_estate=assets.get("real_estate", 0),
            financial=assets.get("financial", 0),
            securities=assets.get("securities", 0),
            cash=assets.get("cash", 0),
            insurance=assets.get("insurance", 0),
            retirement=assets.get("retirement", 0),
            trust=assets.get("trust", 0),
            other=assets.get("other", 0)
        ),
        heir=Heir(
            spouse=SpouseInfo(
                exists=data.get("has_spouse", False),
                age=data.get("spouse_age", 60),
                is_disabled=data.get("spouse_disabled", False),
                life_expectancy=data.get("spouse_life_exp", 0)
            ),
            children=children
        ),
        deductions=Deductions(
            public_charges=debts.get("public_charges", 0),
            funeral_expense=debts.get("funeral_expense", 0),
            funeral_memorial=debts.get("funeral_memorial", 0),
            debt=total_debt
        ),
        prior_gift=PriorGift(
            to_heir_10yr=data.get("prior_gift_amount", 0),
            to_heir_10yr_tax=data.get("prior_gift_tax", 0)
        ),
        co_residence=CoResidenceInfo(
            eligible=data.get("co_residence", False),
            house_value=assets.get("real_estate", 0) if data.get("co_residence") else 0,
            co_residence_years=10 if data.get("co_residence") else 0,
            heir_is_homeless=data.get("co_residence", False)
        ),
        file_on_time=True  # 기한 내 신고 기준 (3% 세액공제 항상 적용)
    )


def show_result():
    """결과 표시"""
    data = st.session_state.data

    # InheritanceInfo 생성
    info = build_inheritance_info(data)

    # 세대생략 정보
    grandchild_amount = data.get("grandchild_amount", 0)
    grandchild_is_minor = data.get("grandchild_is_minor", False)

    # 케이스 비교
    result = compare_cases(
        info,
        grandchild_amount=grandchild_amount,
        grandchild_is_minor=grandchild_is_minor
    )

    st.divider()
    st.header("계산 결과")

    # 요약
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("총 상속재산", format_currency(info.total_inheritance))
    with col2:
        st.metric("최적 케이스 세액", format_currency(result.optimal_case.final_tax))
    with col3:
        st.metric("최대 절세 효과", format_currency(result.max_savings))

    # ========================================
    # 법정 상속분 표시
    # ========================================
    st.divider()
    st.subheader("법정 상속분")

    has_spouse = data.get("has_spouse", False)
    num_children = data.get("num_children", 0)
    shares = get_legal_inheritance_shares(has_spouse, num_children)

    # 법정 상속분은 과세가액(net_inheritance) 기준으로 계산
    base_amount = info.net_inheritance

    if has_spouse and num_children > 0:
        total = 1.5 + num_children
        spouse_pct = (1.5 / total) * 100
        child_pct = (1.0 / total) * 100

        share_text = f"**배우자** : **자녀 {num_children}명** = **1.5** : **{num_children}** (총 {total})\n\n"
        share_text += f"과세가액 기준: {format_currency(base_amount)}\n\n"
        share_text += f"- 배우자: **{spouse_pct:.1f}%** ({format_currency(int(base_amount * 1.5 / total))})\n"
        for i in range(num_children):
            share_text += f"- 자녀 {i+1}: **{child_pct:.1f}%** ({format_currency(int(base_amount / total))})\n"
        st.markdown(share_text)
    elif has_spouse:
        st.markdown(f"과세가액 기준: {format_currency(base_amount)}\n\n- 배우자: **100%** (전액)")
    elif num_children > 0:
        child_pct = 100 / num_children
        share_text = f"자녀 {num_children}명 균등 분배\n\n"
        share_text += f"과세가액 기준: {format_currency(base_amount)}\n\n"
        for i in range(num_children):
            share_text += f"- 자녀 {i+1}: **{child_pct:.1f}%** ({format_currency(int(base_amount / num_children))})\n"
        st.markdown(share_text)

    st.divider()

    # 케이스별 비교
    st.subheader("케이스별 비교")

    sorted_cases = result.get_sorted_cases()
    num_cases = len(sorted_cases)

    # 세로 구분선 CSS 스타일 추가
    st.markdown("""
    <style>
    .case-column {
        border-right: 2px solid #e0e0e0;
        padding-right: 15px;
        margin-right: 5px;
    }
    .case-column-last {
        padding-right: 15px;
    }
    div[data-testid="column"]:not(:last-child) {
        border-right: 1px solid #ddd;
        padding-right: 20px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 케이스를 나란히 표시 (테이블 형식)
    if num_cases > 0:
        # 헤더 행
        header_cols = st.columns(num_cases)
        for i, case in enumerate(sorted_cases):
            is_optimal = case.case_name == result.optimal_case.case_name
            with header_cols[i]:
                if is_optimal:
                    st.success(f"**{case.case_name}** ⭐ 최적")
                else:
                    st.info(f"**{case.case_name}**")
                st.caption(case.description)

        # 구분선
        st.markdown("---")

        # 1단계: 과세가액 계산 (너비 제한)
        st.markdown("##### 1단계: 과세가액 = 총 상속재산 - 채무/비용 + 사전증여")

        # 너비를 줄이기 위해 좌우 여백 추가
        _, step1_content, _ = st.columns([1, 2, 1])
        with step1_content:
            calc_col1, calc_col2 = st.columns([2, 1])
            with calc_col1:
                st.markdown("**총 상속재산**")
                assets = data.get("assets", {})
                asset_names = {
                    "real_estate": "부동산", "financial": "금융자산", "securities": "유가증권",
                    "cash": "현금", "insurance": "보험금", "retirement": "퇴직금",
                    "trust": "신탁재산", "other": "기타"
                }
                asset_items = []
                for key, value in assets.items():
                    if value > 0:
                        asset_items.append(f"{asset_names.get(key, key)}: {format_currency(value)}")
                if asset_items:
                    st.caption("  " + ", ".join(asset_items))
            with calc_col2:
                st.markdown(f"**{format_currency(info.asset.total)}**")

            # 채무/비용 공제
            calc_col1, calc_col2 = st.columns([2, 1])
            with calc_col1:
                st.markdown("**(-) 채무 및 비용**")
                debts = data.get("debts", {})
                re_debt = data.get("real_estate_debt", {})
                debt_items = []

                if debts.get("funeral_expense", 0) > 0 or debts.get("funeral_memorial", 0) == 0:
                    funeral_display = max(5_000_000, min(debts.get("funeral_expense", 0), 10_000_000))
                    debt_items.append(f"장례비: {format_currency(funeral_display)}")
                if debts.get("funeral_memorial", 0) > 0:
                    memorial_display = min(debts.get("funeral_memorial", 0), 5_000_000)
                    debt_items.append(f"봉안시설: {format_currency(memorial_display)}")
                if re_debt.get("deposit", 0) > 0:
                    debt_items.append(f"임대보증금: {format_currency(re_debt['deposit'])}")
                if re_debt.get("loan", 0) > 0:
                    debt_items.append(f"대출: {format_currency(re_debt['loan'])}")
                if debts.get("public_charges", 0) > 0:
                    debt_items.append(f"공과금: {format_currency(debts['public_charges'])}")
                if debts.get("debt", 0) > 0:
                    debt_items.append(f"기타채무: {format_currency(debts['debt'])}")
                if debt_items:
                    st.caption("  " + ", ".join(debt_items))
            with calc_col2:
                st.markdown(f"**-{format_currency(info.total_debt_deduction)}**")

            # 사전증여
            if info.prior_gift.total > 0:
                calc_col1, calc_col2 = st.columns([2, 1])
                with calc_col1:
                    st.markdown("**(+) 사전증여 (10년 내)**")
                with calc_col2:
                    st.markdown(f"**+{format_currency(info.prior_gift.total)}**")

            # 과세가액 결과
            calc_col1, calc_col2 = st.columns([2, 1])
            with calc_col1:
                st.markdown("**= 과세가액**")
            with calc_col2:
                st.success(f"**{format_currency(info.net_inheritance)}**")

        st.markdown("---")

        # 2단계: 과세표준 계산
        st.markdown("##### 2단계: 과세표준 = 과세가액 - 공제")
        row_items_1 = [
            ("과세가액", lambda tr: format_currency(tr.taxable_inheritance)),
            ("(-) 총공제", lambda tr: f"-{format_currency(tr.total_deduction)}"),
            ("= 과세표준", lambda tr: format_currency(tr.taxable_amount)),
        ]

        for label, get_value in row_items_1:
            cols = st.columns(num_cases)
            for i, case in enumerate(sorted_cases):
                with cols[i]:
                    value = get_value(case.tax_result)
                    if label == "= 과세표준":
                        st.success(f"**{label}**: {value}")
                    else:
                        st.markdown(f"**{label}**: {value}")

        # 공제 상세 (expander)
        st.markdown("")
        detail_cols = st.columns(num_cases)
        for i, case in enumerate(sorted_cases):
            with detail_cols[i]:
                with st.expander("공제 상세 보기"):
                    for name, amount in case.tax_result.deduction_detail.items():
                        st.caption(f"• {name}: {format_currency(amount)}")

        # 3단계: 세액 계산
        st.markdown("---")
        st.markdown("##### 3단계: 세액 계산")

        # 적용 세율
        cols = st.columns(num_cases)
        for i, case in enumerate(sorted_cases):
            with cols[i]:
                st.markdown(f"**적용세율**: {get_tax_rate_info(case.tax_result.taxable_amount)}")

        # 산출세액
        cols = st.columns(num_cases)
        for i, case in enumerate(sorted_cases):
            with cols[i]:
                st.markdown(f"**산출세액**: {format_currency(case.tax_result.calculated_tax)}")
                st.caption(f"  (과세표준 × 세율 - 누진공제)")

        # 세대생략 할증 (있는 경우)
        has_surcharge = any(case.tax_result.generation_surcharge > 0 for case in sorted_cases)
        if has_surcharge:
            cols = st.columns(num_cases)
            for i, case in enumerate(sorted_cases):
                with cols[i]:
                    if case.tax_result.generation_surcharge > 0:
                        st.markdown(f"**(+) 세대생략 할증**: +{format_currency(case.tax_result.generation_surcharge)}")
                        st.caption("  (산출세액의 30%)")
                    else:
                        st.markdown("**(+) 세대생략 할증**: 없음")

        # 신고세액공제
        cols = st.columns(num_cases)
        for i, case in enumerate(sorted_cases):
            with cols[i]:
                st.markdown(f"**(-) 신고세액공제**: -{format_currency(case.tax_result.filing_credit)}")
                st.caption("  (기한 내 신고 시 3%)")

        # 기납부 증여세 (있는 경우)
        has_prior_tax = any(case.tax_result.prior_gift_tax_credit > 0 for case in sorted_cases)
        if has_prior_tax:
            cols = st.columns(num_cases)
            for i, case in enumerate(sorted_cases):
                with cols[i]:
                    if case.tax_result.prior_gift_tax_credit > 0:
                        st.markdown(f"**(-) 기납부 증여세**: -{format_currency(case.tax_result.prior_gift_tax_credit)}")
                    else:
                        st.markdown("**(-) 기납부 증여세**: 없음")

        # 최종 세액 강조
        st.markdown("---")
        final_cols = st.columns(num_cases)
        for i, case in enumerate(sorted_cases):
            is_optimal = case.case_name == result.optimal_case.case_name
            tr = case.tax_result
            with final_cols[i]:
                if is_optimal:
                    st.markdown(f"### 💰 최종 납부세액")
                else:
                    st.markdown(f"### 최종 납부세액")

                # 계산식 표시
                calc_parts = [f"{format_currency(tr.calculated_tax)}"]
                if tr.generation_surcharge > 0:
                    calc_parts.append(f"+ {format_currency(tr.generation_surcharge)}")
                calc_parts.append(f"- {format_currency(tr.filing_credit)}")
                if tr.prior_gift_tax_credit > 0:
                    calc_parts.append(f"- {format_currency(tr.prior_gift_tax_credit)}")

                st.caption(" ".join(calc_parts))

                if is_optimal:
                    st.markdown(f"## {format_currency(tr.final_tax)}")
                else:
                    st.markdown(f"## {format_currency(tr.final_tax)}")

    # 추천
    st.divider()
    st.success(f"""
**추천: {result.optimal_case.case_name}**

{result.optimal_case.description}

이 방법을 선택하면 **{format_currency(result.max_savings)}** 절세할 수 있습니다.
""")

    # 주의사항
    st.divider()
    st.caption("""
**주의사항**
- 이 계산기는 참고용이며, 실제 상속세는 세무사와 상담하시기 바랍니다.
- 가업상속공제, 영농상속공제 등 일부 특수 공제는 반영되지 않았습니다.
- 세법 개정에 따라 세율 및 공제 한도가 변경될 수 있습니다.
""")

    # 다시 시작 버튼
    if st.button("처음부터 다시 시작", type="primary"):
        st.session_state.step = 0
        st.session_state.data = {}
        st.session_state.messages = []
        st.session_state.step_history = []
        st.rerun()


# ============================================
# 메인 앱
# ============================================

def main():
    st.set_page_config(
        page_title="상속세 계산기",
        page_icon="",
        layout="wide"
    )

    st.title("상속세 계산기")

    # 세션 상태 초기화
    if "step" not in st.session_state:
        st.session_state.step = 0
    if "data" not in st.session_state:
        st.session_state.data = {}
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "step_history" not in st.session_state:
        st.session_state.step_history = []

    # 사이드바: 디자인 테스트 모드
    with st.sidebar:
        st.markdown("### 개발자 도구")
        if st.button("디자인 테스트 (결과 화면)", use_container_width=True):
            # 테스트 데이터 설정
            st.session_state.data = {
                "assets": {
                    "real_estate": 1_500_000_000,
                    "financial": 200_000_000,
                    "cash": 50_000_000,
                },
                "has_spouse": True,
                "spouse_age": 65,
                "spouse_disabled": False,
                "num_children": 2,
                "children": [
                    {"age": 35, "disabled": False},
                    {"age": 30, "disabled": False},
                ],
                "debts": {
                    "funeral_expense": 8_000_000,
                    "funeral_memorial": 5_000_000,
                },
                "real_estate_debt": {
                    "deposit": 300_000_000,
                    "loan": 200_000_000,
                },
                "has_prior_gift": True,
                "prior_gift": {
                    "to_heir_10yr": 100_000_000,
                    "to_heir_10yr_tax": 5_000_000,
                },
                "has_grandchild": False,
                "grandchild_amount": 0,
                "grandchild_age": 0,
                "co_residence_eligible": False,
                "file_on_time": True,
            }
            st.session_state.step = len(STEPS) - 1
            st.session_state.messages = [
                {"role": "assistant", "content": "[디자인 테스트 모드]"}
            ]
            st.rerun()

        if st.button("처음으로 리셋", use_container_width=True):
            st.session_state.step = 0
            st.session_state.data = {}
            st.session_state.messages = []
            st.session_state.step_history = []
            st.rerun()

        st.markdown("---")

    # 첫 메시지
    if not st.session_state.messages:
        welcome = "안녕하세요! 상속세 계산을 도와드리겠습니다.\n\n"
        welcome += get_step_question("assets", {})
        add_message("assistant", welcome)

    # 결과 단계인 경우 (전체 화면 사용)
    if st.session_state.step >= len(STEPS) - 1:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        show_result()
        return

    # 메인 레이아웃: 왼쪽 대화 / 오른쪽 서머리
    chat_col, summary_col = st.columns([3, 1])

    # 왼쪽: 대화 영역
    with chat_col:
        # 대화 기록 표시
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # 뒤로 가기 버튼 & 진행률
        btn_col, progress_col = st.columns([1, 4])
        with btn_col:
            if st.session_state.step > 0 and st.button("← 이전"):
                go_back()
                st.rerun()

        current_step = st.session_state.step
        total_steps = len(STEPS) - 1
        with progress_col:
            st.progress(current_step / total_steps, text=f"진행: {current_step}/{total_steps}")

        # confirm 단계인 경우
        if STEPS[st.session_state.step] == "confirm":
            st.divider()
            st.subheader("입력 정보 확인")
            st.markdown(get_data_summary(st.session_state.data))

            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                if st.button("확인 - 계산하기", type="primary", use_container_width=True):
                    add_message("user", "확인")
                    add_message("assistant", "정보 확인이 완료되었습니다. 상속세를 계산합니다...")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("result")
                    st.rerun()
            with col2:
                if st.button("수정 - 처음부터", use_container_width=True):
                    st.session_state.step = 0
                    st.session_state.data = {}
                    st.session_state.messages = []
                    st.session_state.step_history = []
                    st.rerun()
        # grandchild 단계: 버튼으로 선택
        elif STEPS[st.session_state.step] == "grandchild":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("예, 계획하고 있습니다", type="primary", use_container_width=True):
                    add_message("user", "예")
                    st.session_state.data["has_grandchild"] = True
                    add_message("assistant", "세대생략 상속을 계획하고 계시군요.")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("grandchild_detail")
                    next_question = get_step_question("grandchild_detail", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
            with col2:
                if st.button("아니오, 없습니다", use_container_width=True):
                    add_message("user", "아니오")
                    st.session_state.data["has_grandchild"] = False
                    add_message("assistant", "세대생략 상속은 없으시군요.")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("funeral_costs")
                    next_question = get_step_question("funeral_costs", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
        # spouse 단계: 버튼으로 선택
        elif STEPS[st.session_state.step] == "spouse":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("예, 생존해 계십니다", type="primary", use_container_width=True):
                    add_message("user", "예")
                    st.session_state.data["has_spouse"] = True
                    add_message("assistant", "배우자가 계시는군요.")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("spouse_detail")
                    next_question = get_step_question("spouse_detail", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
            with col2:
                if st.button("아니오, 없습니다", use_container_width=True):
                    add_message("user", "아니오")
                    st.session_state.data["has_spouse"] = False
                    add_message("assistant", "배우자가 없으시군요.")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("children")
                    next_question = get_step_question("children", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
        # prior_gift 단계: 버튼으로 선택
        elif STEPS[st.session_state.step] == "prior_gift":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("예, 있습니다", type="primary", use_container_width=True):
                    add_message("user", "예")
                    st.session_state.data["has_prior_gift"] = True
                    add_message("assistant", "사전증여가 있으시군요.")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("prior_gift_detail")
                    next_question = get_step_question("prior_gift_detail", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
            with col2:
                if st.button("아니오, 없습니다", use_container_width=True):
                    add_message("user", "아니오")
                    st.session_state.data["has_prior_gift"] = False
                    st.session_state.data["prior_gift_amount"] = 0
                    st.session_state.data["prior_gift_tax"] = 0
                    add_message("assistant", "사전증여가 없으시군요.")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("co_residence")
                    next_question = get_step_question("co_residence", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
        # co_residence 단계: 버튼으로 선택
        elif STEPS[st.session_state.step] == "co_residence":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("예, 충족합니다", type="primary", use_container_width=True):
                    add_message("user", "예")
                    st.session_state.data["co_residence"] = True
                    add_message("assistant", "동거주택공제 요건을 충족하시는군요. (최대 6억원 공제)")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("confirm")
                    next_question = get_step_question("confirm", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
            with col2:
                if st.button("아니오, 충족하지 않습니다", use_container_width=True):
                    add_message("user", "아니오")
                    st.session_state.data["co_residence"] = False
                    add_message("assistant", "동거주택공제는 적용되지 않습니다.")
                    st.session_state.step_history.append(st.session_state.step)
                    st.session_state.step = STEPS.index("confirm")
                    next_question = get_step_question("confirm", st.session_state.data)
                    add_message("assistant", next_question)
                    st.rerun()
        else:
            # 일반 단계: 사용자 입력
            if user_input := st.chat_input("답변을 입력하세요..."):
                process_input(user_input)
                st.rerun()

    # 오른쪽: 실시간 서머리
    with summary_col:
        st.markdown("### 📋 입력 현황")

        # 처음부터 다시 시작 버튼
        if st.button("🔄 처음부터", use_container_width=True):
            st.session_state.step = 0
            st.session_state.data = {}
            st.session_state.messages = []
            st.session_state.step_history = []
            st.rerun()

        st.divider()

        data = st.session_state.get("data", {})

        # 상속재산
        if data.get("assets"):
            assets = data["assets"]
            total = sum(assets.values())
            st.markdown("**📦 상속재산**")
            name_map = {
                "real_estate": "부동산",
                "financial": "금융자산",
                "securities": "유가증권",
                "cash": "현금",
                "insurance": "보험금",
                "retirement": "퇴직금",
                "trust": "신탁재산",
                "other": "기타"
            }
            for key, value in assets.items():
                if value > 0:
                    st.caption(f"{name_map.get(key, key)}: {format_currency(value)}")
            st.markdown(f"**합계: {format_currency(total)}**")
            st.divider()

        # 상속인
        if data.get("has_spouse") is not None or data.get("num_children", 0) > 0:
            st.markdown("**👨‍👩‍👧‍👦 상속인**")
            if data.get("has_spouse"):
                if "spouse_age" in data:
                    spouse_text = f"배우자: {data['spouse_age']}세"
                    if data.get("spouse_disabled"):
                        spouse_text += " (장애인)"
                else:
                    spouse_text = "배우자: 있음"
                st.caption(spouse_text)
            elif data.get("has_spouse") is False:
                st.caption("배우자: 없음")

            if data.get("num_children", 0) > 0:
                ages = data.get("children_ages", [])
                ages_str = ', '.join(f"{a}세" for a in ages) if ages else ""
                st.caption(f"자녀: {data['num_children']}명 ({ages_str})")
            elif "num_children" in data:
                st.caption("자녀: 없음")

            # 세대생략
            if "has_grandchild" in data:
                if data.get("has_grandchild"):
                    gc_age = data.get("grandchild_age")
                    gc_amount = data.get("grandchild_amount", 0)
                    if gc_age:
                        gc_text = f"⚠️ 세대생략: {gc_age}세"
                        if gc_age < 19:
                            gc_text += " (미성년)"
                        if gc_amount > 0:
                            gc_text += f", {format_currency(gc_amount)}"
                        if gc_age < 19 and gc_amount > 2_000_000_000:
                            gc_text += " (40% 할증)"
                        else:
                            gc_text += " (30% 할증)"
                        st.caption(gc_text)
                    else:
                        st.caption("⚠️ 세대생략 상속: 예정")
                else:
                    st.caption("세대생략 상속: 없음")
            st.divider()

        # 장례비용
        debts = data.get("debts", {})
        funeral_total = debts.get("funeral_expense", 0) + debts.get("funeral_memorial", 0)
        if funeral_total > 0 or st.session_state.step > STEPS.index("funeral_costs"):
            st.markdown("**⚱️ 장례비용**")
            if funeral_total > 0:
                if debts.get("funeral_expense", 0) > 0:
                    st.caption(f"장례비: {format_currency(debts['funeral_expense'])}")
                if debts.get("funeral_memorial", 0) > 0:
                    st.caption(f"봉안시설: {format_currency(debts['funeral_memorial'])}")
            else:
                st.caption("없음 (최소 500만원 공제)")
            st.divider()

        # 채무
        other_debts_total = debts.get("public_charges", 0) + debts.get("debt", 0)
        re_debt = data.get("real_estate_debt", {})
        re_debt_total = re_debt.get("deposit", 0) + re_debt.get("loan", 0)

        if other_debts_total > 0 or re_debt_total > 0 or st.session_state.step > STEPS.index("other_debts"):
            st.markdown("**💳 채무**")
            if re_debt.get("deposit", 0) > 0:
                st.caption(f"임대보증금: {format_currency(re_debt['deposit'])}")
            if re_debt.get("loan", 0) > 0:
                st.caption(f"부동산대출: {format_currency(re_debt['loan'])}")
            if debts.get("public_charges", 0) > 0:
                st.caption(f"공과금: {format_currency(debts['public_charges'])}")
            if debts.get("debt", 0) > 0:
                st.caption(f"기타채무: {format_currency(debts['debt'])}")
            if other_debts_total == 0 and re_debt_total == 0:
                st.caption("없음")
            st.divider()

        # 사전증여
        if data.get("prior_gift_amount", 0) > 0 or (data.get("has_prior_gift") is not None):
            st.markdown("**🎁 사전증여**")
            if data.get("prior_gift_amount", 0) > 0:
                st.caption(f"증여액: {format_currency(data['prior_gift_amount'])}")
                if data.get("prior_gift_tax", 0) > 0:
                    st.caption(f"납부세: {format_currency(data['prior_gift_tax'])}")
            else:
                st.caption("없음")
            st.divider()

        # 동거주택공제
        if "co_residence" in data:
            st.markdown("**🏡 추가공제**")
            if data.get("co_residence"):
                st.caption("동거주택공제: 적용")
            else:
                st.caption("동거주택공제: 미적용")
            st.divider()

        # 진행 상태 안내
        if not data:
            st.info("질문에 답변하시면\n여기에 정보가 표시됩니다.")


if __name__ == "__main__":
    main()
