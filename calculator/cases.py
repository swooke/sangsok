"""케이스별 시나리오 비교 로직 (고도화 버전)"""
from typing import List, Dict
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.asset import InheritanceInfo
from calculator.inheritance_tax import calculate_inheritance_tax, TaxResult
from calculator.deductions import (
    calculate_deductions,
    DeductionType,
    SPOUSE_MIN_DEDUCTION,
    SPOUSE_MAX_DEDUCTION,
    calculate_spouse_legal_share,
)


@dataclass
class CaseResult:
    """케이스별 계산 결과"""
    case_name: str               # 케이스 이름
    description: str             # 케이스 설명
    tax_result: TaxResult        # 상속세 계산 결과
    spouse_inheritance: int      # 배우자 상속액
    deduction_type: DeductionType  # 공제 유형

    @property
    def final_tax(self) -> int:
        return self.tax_result.final_tax


@dataclass
class ComparisonResult:
    """케이스 비교 결과"""
    cases: List[CaseResult]      # 모든 케이스 결과
    optimal_case: CaseResult     # 최적 케이스
    max_savings: int             # 최대 절세액 (최악 케이스 대비)

    def get_sorted_cases(self) -> List[CaseResult]:
        """세액 낮은 순으로 정렬"""
        return sorted(self.cases, key=lambda x: x.final_tax)


def calculate_spouse_legal_share_amount(info: InheritanceInfo) -> int:
    """배우자 법정상속분 금액 계산"""
    if not info.heir.has_spouse:
        return 0

    ratio = calculate_spouse_legal_share(info)
    return int(info.net_inheritance * ratio)


def generate_cases(info: InheritanceInfo) -> List[tuple]:
    """
    비교할 케이스 목록 생성

    Returns:
        List of (케이스명, 설명, 배우자상속액, 공제유형)
    """
    cases = []
    net_value = max(0, info.net_inheritance)

    if info.heir.has_spouse:
        # 배우자 법정상속분
        legal_share = calculate_spouse_legal_share_amount(info)

        # 케이스 A: 배우자 법정상속분 + 일괄공제
        cases.append((
            "A: 법정상속분",
            f"배우자 법정상속분 + 일괄공제 5억",
            legal_share,
            DeductionType.LUMP_SUM
        ))

        # 케이스 B: 배우자 공제 최대화 (30억 한도, 또는 과세가액 전체)
        max_spouse = min(net_value, SPOUSE_MAX_DEDUCTION)
        # 법정상속분과 다르거나 비교를 위해 항상 표시
        cases.append((
            "B: 배우자 최대",
            f"배우자 상속 최대화 (30억 한도)",
            max_spouse,
            DeductionType.LUMP_SUM
        ))

        # 케이스 C: 배우자 공제 최소화 (5억)
        min_spouse = min(SPOUSE_MIN_DEDUCTION, net_value)
        cases.append((
            "C: 배우자 최소",
            f"배우자 상속 최소화 (5억)",
            min_spouse,
            DeductionType.LUMP_SUM
        ))

        # 중복 케이스 제거 (배우자 상속액이 같은 경우)
        seen_amounts = set()
        unique_cases = []
        for case in cases:
            amount = case[2]  # 배우자상속액
            if amount not in seen_amounts:
                seen_amounts.add(amount)
                unique_cases.append(case)
        cases = unique_cases

        # 케이스 재정렬 (이름 다시 부여)
        for i, case in enumerate(cases):
            case_letter = chr(ord('A') + i)
            cases[i] = (f"{case_letter}: {case[0].split(': ')[1]}", case[1], case[2], case[3])

    else:
        # 배우자 없는 경우
        cases.append((
            "A: 일괄공제",
            "일괄공제 5억원 적용",
            0,
            DeductionType.LUMP_SUM
        ))

        # 항목별 공제 (비교용으로 항상 추가)
        cases.append((
            "B: 항목별공제",
            "기초공제 2억 + 인적공제",
            0,
            DeductionType.ITEMIZED
        ))

    return cases


def compare_cases(
    info: InheritanceInfo,
    grandchild_amount: int = 0,
    grandchild_is_minor: bool = False
) -> ComparisonResult:
    """
    여러 케이스를 비교하여 최적의 절세 방법 찾기

    Args:
        info: 상속 정보
        grandchild_amount: 세대생략 상속가액 (손자녀에게 상속할 금액)
        grandchild_is_minor: 손자녀가 미성년자인지 여부

    Returns:
        ComparisonResult: 비교 결과
    """
    cases = generate_cases(info)
    results = []

    for case_name, description, spouse_amount, deduction_type in cases:
        # 공제액 계산
        deductions = calculate_deductions(
            info,
            deduction_type=deduction_type,
            spouse_inheritance_amount=spouse_amount
        )

        # 상속세 계산
        tax_result = calculate_inheritance_tax(
            info,
            deduction_detail=deductions,
            spouse_inheritance_ratio=spouse_amount / info.net_inheritance if info.net_inheritance > 0 else 0,
            grandchild_amount=grandchild_amount,
            grandchild_is_minor=grandchild_is_minor
        )

        results.append(CaseResult(
            case_name=case_name,
            description=description,
            tax_result=tax_result,
            spouse_inheritance=spouse_amount,
            deduction_type=deduction_type
        ))

    # 최적 케이스 찾기 (세액이 가장 낮은 것)
    optimal = min(results, key=lambda x: x.final_tax)

    # 최대 절세액 (최악 케이스 대비)
    max_tax = max(r.final_tax for r in results)
    min_tax = min(r.final_tax for r in results)
    max_savings = max_tax - min_tax

    return ComparisonResult(
        cases=results,
        optimal_case=optimal,
        max_savings=max_savings
    )
