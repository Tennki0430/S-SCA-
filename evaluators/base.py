"""評価器の基本クラス（インターフェース）。

全ての Evaluator はこのクラスを継承して evaluate() を実装する。
採点基準を変えたいときはここを見る。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EvaluationResult:
    symbol: str
    error_rate: float    # MAPE（%）
    predicted: float
    actual: float
    passed: bool         # True = 合格（誤差が閾値未満）
    notes: str = field(default="")


class BaseEvaluator(ABC):
    @abstractmethod
    def evaluate(self, symbol: str, predicted: float, actual: float) -> EvaluationResult:
        """予測値と実績値を受け取り、EvaluationResult を返す。"""
        ...
