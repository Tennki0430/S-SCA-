"""評価器の基本クラス（インターフェース）。

全ての Evaluator はこのクラスを継承して evaluate() を実装する。
採点基準を変えたいときはここを見る。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class EvaluationResult:
    symbol: str
    error_rate: float    # MAPE（%）
    predicted: float
    actual: float
    passed: bool         # True = 合格（誤差が閾値未満）
    notes: str = field(default="")
    # PDCA深掘り用コンテキスト（reporter.py が設定する）
    predicted_date: date | None = field(default=None)
    target_date: date | None = field(default=None)
    current_price_at_pred: float | None = field(default=None)
    reasoning_text: str = field(default="")
    regressors_at_pred: dict[str, float] = field(default_factory=dict)
    regressors_at_target: dict[str, float] = field(default_factory=dict)
    prev_feedbacks: list[dict] = field(default_factory=list)
    # 多角的評価スコア（multi_factor.py が設定する）
    multi_factor_scores: dict[str, object] = field(default_factory=dict)
    # 修正が必要かどうか（MAPE以外の要因でも要改善と判断した場合 True）
    needs_improvement: bool = field(default=False)


class BaseEvaluator(ABC):
    @abstractmethod
    def evaluate(self, symbol: str, predicted: float, actual: float) -> EvaluationResult:
        """予測値と実績値を受け取り、EvaluationResult を返す。"""
        ...
