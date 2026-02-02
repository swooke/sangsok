"""상속세 계산 로직 테스트"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.asset import InheritanceInfo, Asset, Heir
from calculator.inheritance_tax import calculate_tax_amount, calculate_inheritance_tax
from calculator.deductions import calculate_deductions, DeductionType
from calculator.cases import compare_cases


class TestTaxCalculation:
    """세액 계산 테스트"""

    def test_tax_bracket_1억이하(self):
        """1억 이하: 10%"""
        assert calculate_tax_amount(100_000_000) == 10_000_000

    def test_tax_bracket_5억(self):
        """5억: 20% - 누진공제 1천만원 = 9천만원"""
        assert calculate_tax_amount(500_000_000) == 90_000_000

    def test_tax_bracket_10억(self):
        """10억: 30% - 누진공제 6천만원 = 2.4억"""
        assert calculate_tax_amount(1_000_000_000) == 240_000_000

    def test_tax_bracket_30억(self):
        """30억: 40% - 누진공제 1.6억 = 10.4억"""
        assert calculate_tax_amount(3_000_000_000) == 1_040_000_000

    def test_tax_bracket_50억(self):
        """50억: 50% - 누진공제 4.6억 = 20.4억"""
        assert calculate_tax_amount(5_000_000_000) == 2_040_000_000

    def test_zero_taxable(self):
        """과세표준 0원"""
        assert calculate_tax_amount(0) == 0

    def test_negative_taxable(self):
        """음수 과세표준"""
        assert calculate_tax_amount(-100_000_000) == 0


class TestDeductions:
    """공제 계산 테스트"""

    def test_lump_sum_deduction(self):
        """일괄공제 5억"""
        info = InheritanceInfo(
            asset=Asset(real_estate=1_000_000_000),
            heir=Heir(has_spouse=False, num_children=2)
        )
        deductions = calculate_deductions(info, DeductionType.LUMP_SUM, 0)
        assert deductions["일괄공제"] == 500_000_000

    def test_spouse_deduction_min(self):
        """배우자 공제 최소 5억"""
        info = InheritanceInfo(
            asset=Asset(real_estate=1_000_000_000),
            heir=Heir(has_spouse=True, num_children=2)
        )
        # 법정상속분보다 적은 금액을 상속해도 최소 5억 공제
        deductions = calculate_deductions(info, DeductionType.LUMP_SUM, 100_000_000)
        assert deductions["배우자공제"] == 500_000_000


class TestCaseComparison:
    """케이스 비교 테스트"""

    def test_compare_with_spouse(self):
        """배우자 있는 경우 케이스 비교"""
        info = InheritanceInfo(
            asset=Asset(real_estate=1_500_000_000),
            heir=Heir(has_spouse=True, num_children=2)
        )
        result = compare_cases(info)

        # 여러 케이스가 생성되어야 함
        assert len(result.cases) >= 2
        # 최적 케이스가 있어야 함
        assert result.optimal_case is not None
        # 최적 케이스의 세액이 가장 낮아야 함
        assert result.optimal_case.final_tax == min(c.final_tax for c in result.cases)

    def test_compare_without_spouse(self):
        """배우자 없는 경우"""
        info = InheritanceInfo(
            asset=Asset(real_estate=1_000_000_000),
            heir=Heir(has_spouse=False, num_children=2)
        )
        result = compare_cases(info)

        assert len(result.cases) >= 1
        assert result.optimal_case is not None


class TestEndToEnd:
    """통합 테스트"""

    def test_full_calculation_15억_배우자있음(self):
        """15억 상속, 배우자 있음, 자녀 2명"""
        info = InheritanceInfo(
            asset=Asset(
                real_estate=1_000_000_000,
                financial=500_000_000
            ),
            heir=Heir(has_spouse=True, num_children=2),
            debt=0,
            funeral_expense=10_000_000
        )

        result = compare_cases(info)

        # 기본 검증
        assert result.optimal_case.final_tax >= 0
        assert result.max_savings >= 0

        # 총 상속재산 확인
        assert result.optimal_case.tax_result.total_inheritance == 1_500_000_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
