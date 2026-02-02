"""상속세 공제 항목 계산 (고도화 버전)"""
from typing import Dict
from dataclasses import dataclass
from enum import Enum

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.asset import InheritanceInfo


# ============================================
# 공제 한도 상수
# ============================================

# 기본 공제
BASIC_DEDUCTION = 200_000_000           # 기초공제: 2억원
LUMP_SUM_DEDUCTION = 500_000_000        # 일괄공제: 5억원

# 배우자 공제
SPOUSE_MIN_DEDUCTION = 500_000_000      # 배우자공제 최소: 5억원
SPOUSE_MAX_DEDUCTION = 3_000_000_000    # 배우자공제 최대: 30억원

# 인적 공제
CHILD_DEDUCTION = 50_000_000            # 자녀공제: 1인당 5천만원
MINOR_DEDUCTION_PER_YEAR = 10_000_000   # 미성년자공제: 연 1천만원
ELDERLY_DEDUCTION = 50_000_000          # 연로자공제: 1인당 5천만원 (65세 이상)
DISABLED_DEDUCTION_PER_YEAR = 10_000_000  # 장애인공제: 연 1천만원 × 기대여명

# 금융재산 공제
FINANCIAL_FULL_THRESHOLD = 20_000_000   # 전액 공제 기준: 2천만원 미만
FINANCIAL_FIXED_THRESHOLD = 100_000_000  # 고정 공제 기준: 1억
FINANCIAL_FIXED_DEDUCTION = 20_000_000   # 고정 공제액: 2천만원
FINANCIAL_RATE = 0.20                    # 비율 공제: 20%
FINANCIAL_MAX_DEDUCTION = 200_000_000    # 최대 공제: 2억원

# 동거주택 공제
CO_RESIDENCE_MAX_DEDUCTION = 600_000_000  # 동거주택공제 최대: 6억원
CO_RESIDENCE_MIN_YEARS = 10               # 최소 동거 기간: 10년


class DeductionType(Enum):
    """공제 유형"""
    LUMP_SUM = "일괄공제"           # 기초+인적공제 대신 5억 선택
    ITEMIZED = "항목별공제"         # 기초공제 + 인적공제 개별 적용


@dataclass
class DeductionResult:
    """공제 계산 결과"""
    details: Dict[str, int]         # 공제 항목별 금액
    total: int                      # 총 공제액
    deduction_type: DeductionType   # 적용된 공제 유형


# ============================================
# 인적 공제 계산
# ============================================

def calculate_child_deduction(info: InheritanceInfo) -> int:
    """자녀 공제 (1인당 5천만원)"""
    return info.heir.num_children * CHILD_DEDUCTION


def calculate_minor_deduction(info: InheritanceInfo) -> int:
    """
    미성년자 공제
    (19세 - 현재나이) × 1천만원
    자녀 공제와 중복 가능
    """
    total = 0
    for child in info.heir.children:
        if child.is_minor:
            total += child.years_to_adult * MINOR_DEDUCTION_PER_YEAR
    return total


def calculate_elderly_deduction(info: InheritanceInfo) -> int:
    """
    연로자 공제 (65세 이상)
    1인당 5천만원
    배우자는 중복 불가 (별도 배우자공제 적용)
    """
    # 65세 이상 자녀
    count = info.heir.num_elderly_children
    # 65세 이상 직계존속
    count += info.heir.num_elderly_parents
    return count * ELDERLY_DEDUCTION


def calculate_disabled_deduction(info: InheritanceInfo) -> int:
    """
    장애인 공제
    기대여명 × 1천만원
    모든 공제와 중복 가능
    """
    total = 0

    # 자녀 중 장애인
    for child in info.heir.children:
        if child.is_disabled:
            total += child.life_expectancy * DISABLED_DEDUCTION_PER_YEAR

    # 배우자 장애인
    if info.heir.spouse.exists and info.heir.spouse.is_disabled:
        total += info.heir.spouse.life_expectancy * DISABLED_DEDUCTION_PER_YEAR

    return total


def calculate_personal_deductions(info: InheritanceInfo) -> Dict[str, int]:
    """
    모든 인적 공제 계산

    중복 규칙:
    - 자녀 + 미성년자: 중복 O
    - 장애인: 모든 공제와 중복 O
    - 배우자: 자녀/미성년자/연로자 공제와 중복 X
    """
    deductions = {}

    child_ded = calculate_child_deduction(info)
    if child_ded > 0:
        deductions["자녀공제"] = child_ded

    minor_ded = calculate_minor_deduction(info)
    if minor_ded > 0:
        deductions["미성년자공제"] = minor_ded

    elderly_ded = calculate_elderly_deduction(info)
    if elderly_ded > 0:
        deductions["연로자공제"] = elderly_ded

    disabled_ded = calculate_disabled_deduction(info)
    if disabled_ded > 0:
        deductions["장애인공제"] = disabled_ded

    return deductions


# ============================================
# 배우자 공제
# ============================================

def calculate_spouse_legal_share(info: InheritanceInfo) -> float:
    """배우자 법정상속분 비율 계산"""
    if not info.heir.has_spouse:
        return 0.0

    # 법정상속분: 배우자 1.5 : 자녀 각 1
    num_children = info.heir.num_children
    if num_children == 0:
        return 1.0  # 배우자만 있는 경우

    total_weight = 1.5 + num_children
    return 1.5 / total_weight


def calculate_spouse_deduction(
    info: InheritanceInfo,
    spouse_inheritance_amount: int
) -> int:
    """
    배우자 상속공제 계산

    규칙:
    - 실제 상속액 없거나 5억 미만: 5억 공제
    - 5억 이상: min(30억, 법정지분 - 사전증여)
    """
    if not info.heir.has_spouse:
        return 0

    taxable_value = info.net_inheritance
    if taxable_value <= 0:
        return 0

    # 법정상속분 계산
    legal_share_ratio = calculate_spouse_legal_share(info)
    legal_share_amount = int(taxable_value * legal_share_ratio)

    # 배우자 사전증여 과세표준 차감
    spouse_prior_gift = info.heir.spouse.prior_gift
    legal_share_after_gift = legal_share_amount - spouse_prior_gift

    # 실제 상속액이 없거나 5억 미만이면 최소 5억
    if spouse_inheritance_amount < SPOUSE_MIN_DEDUCTION:
        deduction = SPOUSE_MIN_DEDUCTION
    else:
        # min(30억, 법정지분 - 사전증여)
        deduction = min(SPOUSE_MAX_DEDUCTION, max(0, legal_share_after_gift))
        # 실제 상속액을 초과할 수 없음
        deduction = min(deduction, spouse_inheritance_amount)

    # 과세가액을 초과할 수 없음
    deduction = min(deduction, taxable_value)

    return deduction


# ============================================
# 금융재산 공제
# ============================================

def calculate_financial_deduction(info: InheritanceInfo) -> int:
    """
    금융재산 공제

    규칙:
    - 2천만원 미만: 전액
    - 2천만원 ~ 1억: 2천만원
    - 1억 초과: 20% (최대 2억)

    Note: 부동산 관련 채무(보증금, 대출)는 금융부채가 아니므로 차감하지 않음
    """
    net_financial = info.asset.net_financial

    if net_financial < FINANCIAL_FULL_THRESHOLD:
        # 2천만원 미만: 전액 공제
        return net_financial
    elif net_financial <= FINANCIAL_FIXED_THRESHOLD:
        # 2천만원 ~ 1억: 2천만원 고정
        return FINANCIAL_FIXED_DEDUCTION
    else:
        # 1억 초과: 20%, 최대 2억
        deduction = int(net_financial * FINANCIAL_RATE)
        return min(deduction, FINANCIAL_MAX_DEDUCTION)


# ============================================
# 동거주택 공제
# ============================================

def calculate_co_residence_deduction(info: InheritanceInfo) -> int:
    """
    동거주택 상속공제

    요건:
    1. 피상속인이 거주자
    2. 10년 이상 동거
    3. 10년 이상 1세대 1주택
    4. 상속인 무주택자

    최대 6억원
    """
    co_res = info.co_residence

    if not co_res.eligible:
        return 0

    if co_res.co_residence_years < CO_RESIDENCE_MIN_YEARS:
        return 0

    if not co_res.heir_is_homeless:
        return 0

    # 주택 가액과 6억 중 작은 값
    return min(co_res.house_value, CO_RESIDENCE_MAX_DEDUCTION)


# ============================================
# 일괄공제 vs 항목별공제
# ============================================

def calculate_itemized_deductions(info: InheritanceInfo) -> Dict[str, int]:
    """
    항목별 공제 계산 (기초공제 + 인적공제)
    """
    deductions = {}

    # 기초공제: 2억원
    deductions["기초공제"] = BASIC_DEDUCTION

    # 인적공제
    personal = calculate_personal_deductions(info)
    deductions.update(personal)

    return deductions


def get_optimal_base_deduction_type(info: InheritanceInfo) -> DeductionType:
    """
    일괄공제 vs 항목별공제 중 유리한 것 선택
    """
    itemized = calculate_itemized_deductions(info)
    itemized_total = sum(itemized.values())

    if itemized_total > LUMP_SUM_DEDUCTION:
        return DeductionType.ITEMIZED
    else:
        return DeductionType.LUMP_SUM


# ============================================
# 전체 공제 계산
# ============================================

def calculate_deductions(
    info: InheritanceInfo,
    deduction_type: DeductionType = DeductionType.LUMP_SUM,
    spouse_inheritance_amount: int = 0
) -> Dict[str, int]:
    """
    전체 공제액 계산

    Args:
        info: 상속 정보
        deduction_type: 공제 유형 (일괄공제 vs 항목별공제)
        spouse_inheritance_amount: 배우자 실제 상속액

    Returns:
        공제 항목별 금액 딕셔너리
    """
    deductions = {}

    # 1. 기초공제 + 인적공제 vs 일괄공제
    if deduction_type == DeductionType.LUMP_SUM:
        deductions["일괄공제"] = LUMP_SUM_DEDUCTION
    else:
        itemized = calculate_itemized_deductions(info)
        deductions.update(itemized)

    # 2. 배우자공제 (일괄공제와 별도)
    if info.heir.has_spouse and spouse_inheritance_amount > 0:
        spouse_ded = calculate_spouse_deduction(info, spouse_inheritance_amount)
        if spouse_ded > 0:
            deductions["배우자공제"] = spouse_ded

    # 3. 금융재산공제
    financial_ded = calculate_financial_deduction(info)
    if financial_ded > 0:
        deductions["금융재산공제"] = financial_ded

    # 4. 동거주택공제
    co_res_ded = calculate_co_residence_deduction(info)
    if co_res_ded > 0:
        deductions["동거주택공제"] = co_res_ded

    return deductions


def calculate_all_deductions_with_comparison(
    info: InheritanceInfo,
    spouse_inheritance_amount: int = 0
) -> DeductionResult:
    """
    최적의 공제 유형을 자동 선택하여 계산
    """
    optimal_type = get_optimal_base_deduction_type(info)
    details = calculate_deductions(info, optimal_type, spouse_inheritance_amount)
    total = sum(details.values())

    return DeductionResult(
        details=details,
        total=total,
        deduction_type=optimal_type
    )
