"""상속세 계산 핵심 로직 (고도화 버전)"""
from typing import Dict
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.asset import InheritanceInfo


# ============================================
# 상속세율 구간
# ============================================

# (과세표준 상한, 세율, 누진공제액)
TAX_BRACKETS = [
    (100_000_000, 0.10, 0),              # 1억 이하: 10%
    (500_000_000, 0.20, 10_000_000),     # 5억 이하: 20%, 누진공제 1천만원
    (1_000_000_000, 0.30, 60_000_000),   # 10억 이하: 30%, 누진공제 6천만원
    (3_000_000_000, 0.40, 160_000_000),  # 30억 이하: 40%, 누진공제 1억6천만원
    (float('inf'), 0.50, 460_000_000),   # 30억 초과: 50%, 누진공제 4억6천만원
]

# 세대생략 할증률
GENERATION_SKIP_SURCHARGE_RATE = 0.30          # 기본 30%
GENERATION_SKIP_SURCHARGE_RATE_MINOR = 0.40    # 미성년자 20억 초과 시 40%
GENERATION_SKIP_MINOR_THRESHOLD = 2_000_000_000  # 20억원

# 신고세액공제율
FILING_TAX_CREDIT_RATE = 0.03  # 3%


# ============================================
# 세액 계산 함수
# ============================================

def calculate_tax_amount(taxable_amount: int) -> int:
    """
    과세표준에 따른 상속세 산출세액 계산

    Args:
        taxable_amount: 과세표준

    Returns:
        산출세액
    """
    if taxable_amount <= 0:
        return 0

    for bracket, rate, deduction in TAX_BRACKETS:
        if taxable_amount <= bracket:
            return int(taxable_amount * rate - deduction)

    # 최고 구간
    _, rate, deduction = TAX_BRACKETS[-1]
    return int(taxable_amount * rate - deduction)


def calculate_generation_skip_surcharge(
    base_tax: int,
    info: InheritanceInfo,
    taxable_inheritance: int = 0,
    grandchild_amount: int = 0,
    grandchild_is_minor: bool = False
) -> int:
    """
    세대생략 할증 계산

    공식: 산출세액 × (세대생략 상속가액 / 총 과세가액) × 할증률

    규칙:
    - 상속인이 피상속인의 자녀가 아닌 직계비속(손자녀 등): 30% 할증
    - 미성년자가 20억 초과 상속: 40% 할증
    - 예외: 직계비속(자녀) 사망으로 최근친인 경우 할증 없음

    Args:
        base_tax: 기본 산출세액
        info: 상속 정보
        taxable_inheritance: 총 과세가액
        grandchild_amount: 세대생략 상속가액 (손자녀에게 상속할 금액)
        grandchild_is_minor: 손자녀가 미성년자인지 여부

    Returns:
        할증 세액
    """
    # 세대생략 상속이 없으면 0
    if not info.heir.has_generation_skip and grandchild_amount == 0:
        return 0

    # 과세가액이 0이면 할증 없음
    if taxable_inheritance <= 0:
        return 0

    # 세대생략 상속가액 결정
    # 1. 명시적으로 전달된 grandchild_amount 사용
    # 2. 없으면 children에서 손자녀 찾기
    skip_amount = grandchild_amount

    if skip_amount == 0:
        # children에서 손자녀 정보로 계산 (기존 방식 fallback)
        for child in info.heir.children:
            if child.is_grandchild and child.parent_alive:
                # 손자녀 1인당 균등 배분 가정
                num_heirs = info.heir.total_heirs
                if num_heirs > 0:
                    skip_amount = taxable_inheritance // num_heirs

    if skip_amount == 0:
        return 0

    # 할증률 결정
    # 미성년자 + 20억 초과 -> 40%, 그 외 -> 30%
    is_minor = grandchild_is_minor
    if not is_minor:
        # children에서 확인
        for child in info.heir.children:
            if child.is_grandchild and child.is_minor:
                is_minor = True
                break

    if is_minor and skip_amount > GENERATION_SKIP_MINOR_THRESHOLD:
        surcharge_rate = GENERATION_SKIP_SURCHARGE_RATE_MINOR  # 40%
    else:
        surcharge_rate = GENERATION_SKIP_SURCHARGE_RATE  # 30%

    # 세대생략 할증 = 산출세액 × (세대생략 상속가액 / 총 과세가액) × 할증률
    ratio = skip_amount / taxable_inheritance
    surcharge = int(base_tax * ratio * surcharge_rate)

    return surcharge


def calculate_filing_credit(calculated_tax: int, file_on_time: bool) -> int:
    """
    신고세액공제 계산

    기한 내 신고 시 산출세액의 3% 공제

    Args:
        calculated_tax: 산출세액
        file_on_time: 기한 내 신고 여부

    Returns:
        신고세액공제
    """
    if file_on_time:
        return int(calculated_tax * FILING_TAX_CREDIT_RATE)
    return 0


# ============================================
# 결과 데이터 클래스
# ============================================

@dataclass
class TaxResult:
    """상속세 계산 결과"""
    total_inheritance: int       # 총 상속재산
    taxable_inheritance: int     # 과세가액 (채무/장례비 차감 후)
    total_deduction: int         # 총 공제액
    taxable_amount: int          # 과세표준
    calculated_tax: int          # 산출세액
    generation_surcharge: int    # 세대생략 할증
    filing_credit: int           # 신고세액공제
    prior_gift_tax_credit: int   # 기납부 증여세 공제
    final_tax: int               # 최종 납부세액
    deduction_detail: Dict       # 공제 상세 내역

    def to_dict(self) -> Dict:
        return {
            "총상속재산": self.total_inheritance,
            "과세가액": self.taxable_inheritance,
            "총공제액": self.total_deduction,
            "과세표준": self.taxable_amount,
            "산출세액": self.calculated_tax,
            "세대생략할증": self.generation_surcharge,
            "신고세액공제": self.filing_credit,
            "기납부증여세공제": self.prior_gift_tax_credit,
            "최종납부세액": self.final_tax,
            "공제상세": self.deduction_detail,
        }


# ============================================
# 메인 계산 함수
# ============================================

def calculate_inheritance_tax(
    info: InheritanceInfo,
    deduction_detail: Dict[str, int],
    spouse_inheritance_ratio: float = 0.0,
    grandchild_amount: int = 0,
    grandchild_is_minor: bool = False
) -> TaxResult:
    """
    상속세 계산

    Args:
        info: 상속 정보
        deduction_detail: 공제 상세 내역 (deductions.py에서 계산)
        spouse_inheritance_ratio: 배우자 상속 비율 (0.0 ~ 1.0)
        grandchild_amount: 세대생략 상속가액 (손자녀에게 상속할 금액)
        grandchild_is_minor: 손자녀가 미성년자인지 여부

    Returns:
        TaxResult: 상속세 계산 결과
    """
    # 1. 총 상속재산 (사전증여 포함)
    total_inheritance = info.total_inheritance

    # 2. 과세가액 (채무, 장례비용 등 차감)
    taxable_inheritance = info.net_inheritance

    # 3. 총 공제액
    total_deduction = sum(deduction_detail.values())

    # 4. 과세표준
    taxable_amount = taxable_inheritance - total_deduction
    if taxable_amount < 0:
        taxable_amount = 0

    # 5. 산출세액
    calculated_tax = calculate_tax_amount(taxable_amount)

    # 6. 세대생략 할증
    # 공식: 산출세액 × (세대생략 상속가액 / 총 과세가액) × 할증률
    generation_surcharge = calculate_generation_skip_surcharge(
        calculated_tax,
        info,
        taxable_inheritance=taxable_inheritance,
        grandchild_amount=grandchild_amount,
        grandchild_is_minor=grandchild_is_minor
    )

    # 7. 할증 적용 후 세액
    tax_after_surcharge = calculated_tax + generation_surcharge

    # 8. 신고세액공제 (3%)
    filing_credit = calculate_filing_credit(tax_after_surcharge, info.file_on_time)

    # 9. 기납부 증여세액 공제
    prior_gift_tax_credit = info.prior_gift.total_tax_paid

    # 10. 최종 납부세액
    final_tax = tax_after_surcharge - filing_credit - prior_gift_tax_credit
    if final_tax < 0:
        final_tax = 0

    return TaxResult(
        total_inheritance=total_inheritance,
        taxable_inheritance=taxable_inheritance,
        total_deduction=total_deduction,
        taxable_amount=taxable_amount,
        calculated_tax=calculated_tax,
        generation_surcharge=generation_surcharge,
        filing_credit=filing_credit,
        prior_gift_tax_credit=prior_gift_tax_credit,
        final_tax=final_tax,
        deduction_detail=deduction_detail,
    )
