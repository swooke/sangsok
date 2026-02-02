"""상속 관련 데이터 모델"""
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class HeirType(Enum):
    """상속인 유형"""
    SPOUSE = "배우자"
    CHILD = "자녀"
    GRANDCHILD = "손자녀"  # 세대생략
    PARENT = "부모"
    SIBLING = "형제자매"


@dataclass
class Asset:
    """자산 정보"""
    real_estate: int = 0          # 부동산
    financial: int = 0            # 금융자산 (예금, 주식 등)
    securities: int = 0           # 유가증권
    cash: int = 0                 # 현금
    insurance: int = 0            # 보험금 (계약자/피보험자가 피상속인)
    retirement: int = 0           # 퇴직금
    trust: int = 0                # 신탁재산
    other: int = 0                # 기타 자산

    @property
    def total(self) -> int:
        """총 자산"""
        return (self.real_estate + self.financial + self.securities +
                self.cash + self.insurance + self.retirement +
                self.trust + self.other)

    @property
    def net_financial(self) -> int:
        """순 금융재산 (금융재산공제 계산용) - 현금 제외, 보험금 포함"""
        return self.financial + self.securities + self.insurance


@dataclass
class ChildInfo:
    """자녀 정보 (개별)"""
    age: int = 30                 # 나이
    is_disabled: bool = False     # 장애인 여부
    life_expectancy: int = 0      # 기대여명 (장애인인 경우)
    is_grandchild: bool = False   # 손자녀 여부 (세대생략)
    parent_alive: bool = True     # 부모(피상속인 자녀) 생존 여부

    @property
    def is_minor(self) -> bool:
        """미성년자 여부"""
        return self.age < 19

    @property
    def years_to_adult(self) -> int:
        """성년까지 남은 연수"""
        if self.is_minor:
            return 19 - self.age
        return 0


@dataclass
class SpouseInfo:
    """배우자 정보"""
    exists: bool = False          # 배우자 생존 여부
    age: int = 60                 # 나이
    is_disabled: bool = False     # 장애인 여부
    life_expectancy: int = 0      # 기대여명 (장애인인 경우)
    prior_gift: int = 0           # 배우자에게 사전증여한 금액
    prior_gift_tax: int = 0       # 사전증여 시 납부한 증여세

    @property
    def is_elderly(self) -> bool:
        """연로자 여부 (65세 이상)"""
        return self.age >= 65


@dataclass
class Heir:
    """상속인 정보"""
    spouse: SpouseInfo = field(default_factory=SpouseInfo)
    children: List[ChildInfo] = field(default_factory=list)
    num_elderly_parents: int = 0  # 65세 이상 직계존속 수

    @property
    def has_spouse(self) -> bool:
        return self.spouse.exists

    @property
    def num_children(self) -> int:
        """자녀 수"""
        return len(self.children)

    @property
    def num_minor_children(self) -> int:
        """미성년 자녀 수"""
        return sum(1 for c in self.children if c.is_minor)

    @property
    def num_disabled(self) -> int:
        """장애인 수 (배우자 포함)"""
        count = sum(1 for c in self.children if c.is_disabled)
        if self.spouse.exists and self.spouse.is_disabled:
            count += 1
        return count

    @property
    def num_elderly_children(self) -> int:
        """65세 이상 자녀 수"""
        return sum(1 for c in self.children if c.age >= 65)

    @property
    def total_heirs(self) -> int:
        """총 상속인 수"""
        count = self.num_children + self.num_elderly_parents
        if self.has_spouse:
            count += 1
        return count

    @property
    def has_generation_skip(self) -> bool:
        """세대생략 상속 여부"""
        return any(c.is_grandchild for c in self.children)


@dataclass
class Deductions:
    """공제 관련 정보"""
    public_charges: int = 0       # 공과금 (승계된 조세/공공요금)
    funeral_expense: int = 0      # 장례비용
    funeral_memorial: int = 0     # 봉안시설 비용 (별도 500만원 한도)
    debt: int = 0                 # 채무


@dataclass
class PriorGift:
    """사전증여 정보"""
    to_heir_10yr: int = 0         # 상속인에게 10년 내 증여
    to_heir_10yr_tax: int = 0     # 납부한 증여세
    to_others_5yr: int = 0        # 상속인 외 5년 내 증여
    to_others_5yr_tax: int = 0    # 납부한 증여세
    business_succession: int = 0  # 창업자금/가업승계 (기간 무관)
    business_succession_tax: int = 0

    @property
    def total(self) -> int:
        """총 사전증여액"""
        return self.to_heir_10yr + self.to_others_5yr + self.business_succession

    @property
    def total_tax_paid(self) -> int:
        """총 납부 증여세"""
        return self.to_heir_10yr_tax + self.to_others_5yr_tax + self.business_succession_tax


@dataclass
class CoResidenceInfo:
    """동거주택 정보"""
    eligible: bool = False        # 동거주택공제 요건 충족 여부
    house_value: int = 0          # 주택 가액
    co_residence_years: int = 0   # 동거 기간 (년)
    heir_is_homeless: bool = False  # 상속인 무주택 여부


@dataclass
class InheritanceInfo:
    """상속 정보 전체"""
    asset: Asset = field(default_factory=Asset)
    heir: Heir = field(default_factory=Heir)
    deductions: Deductions = field(default_factory=Deductions)
    prior_gift: PriorGift = field(default_factory=PriorGift)
    co_residence: CoResidenceInfo = field(default_factory=CoResidenceInfo)

    # 신고 관련
    file_on_time: bool = True     # 기한 내 신고 여부 (신고세액공제 3%)

    @property
    def total_inheritance(self) -> int:
        """총 상속재산 (사전증여 포함)"""
        return self.asset.total + self.prior_gift.total

    @property
    def total_debt_deduction(self) -> int:
        """채무/비용 공제 합계"""
        # 장례비용: 500만원 ~ 1000만원
        funeral = max(5_000_000, min(self.deductions.funeral_expense, 10_000_000))
        # 봉안시설: 별도 500만원 한도
        memorial = min(self.deductions.funeral_memorial, 5_000_000)
        # 채무: 상속재산 초과분은 0
        debt = min(self.deductions.debt, self.asset.total)

        return self.deductions.public_charges + funeral + memorial + debt

    @property
    def net_inheritance(self) -> int:
        """과세가액 (채무/장례비 차감 후, 사전증여 포함)"""
        value = self.asset.total + self.prior_gift.total - self.total_debt_deduction
        return max(0, value)


# 하위 호환성을 위한 간단한 생성 함수
def create_simple_inheritance_info(
    real_estate: int = 0,
    financial: int = 0,
    other: int = 0,
    has_spouse: bool = False,
    num_children: int = 0,
    debt: int = 0,
    funeral_expense: int = 0,
    prior_gift: int = 0,
    prior_gift_tax: int = 0
) -> InheritanceInfo:
    """간단한 입력으로 InheritanceInfo 생성 (하위 호환)"""
    children = [ChildInfo(age=30) for _ in range(num_children)]

    return InheritanceInfo(
        asset=Asset(
            real_estate=real_estate,
            financial=financial,
            other=other
        ),
        heir=Heir(
            spouse=SpouseInfo(exists=has_spouse),
            children=children
        ),
        deductions=Deductions(
            debt=debt,
            funeral_expense=funeral_expense
        ),
        prior_gift=PriorGift(
            to_heir_10yr=prior_gift,
            to_heir_10yr_tax=prior_gift_tax
        )
    )
