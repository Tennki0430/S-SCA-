"""多角的評価器（MultiFactor Evaluator）。

MAPE に加えて以下の観点から予測を多角的に評価する。
各スコアは EvaluationResult.multi_factor_scores に格納され、
LLM Judge のプロンプトに渡されて根本原因の特定に使われる。

評価軸：
  direction_accuracy  - 価格の方向（上昇/下落）を正しく予測できたか（1=正解, 0=誤り）
  vix_adjusted_mape   - VIX水準で補正したMAPE（恐怖指数が高い時は許容誤差を広げる）
  external_shock_score - 外生変数の急変幅（大きいほど外部ショック由来の誤差）
  data_completeness   - 予測時の外生変数の欠損率（1=完全, 0=全欠損）
"""

import logging
from dataclasses import dataclass

from evaluators.base import EvaluationResult

logger = logging.getLogger(__name__)

# VIX補正: VIXがこの値を超えると許容MAPE閾値を緩和
VIX_HIGH_THRESHOLD = 25.0
VIX_VERY_HIGH_THRESHOLD = 35.0
REGRESSORS = ["BDI", "VIX", "Gold", "Oil", "DXY", "NatGas", "ChinaETF", "Brent"]


@dataclass
class MultiFactorScores:
    direction_accuracy: int        # 1=方向正解, 0=方向誤り
    vix_adjusted_mape: float       # VIX補正後のMAPE（閾値と比較用）
    external_shock_score: float    # 外生変数の最大変動幅(%)
    data_completeness: float       # 外生変数の欠損なし率（0〜1）
    shock_culprit: str             # 最も変動した外生変数名

    def to_dict(self) -> dict:
        return {
            "direction_accuracy": self.direction_accuracy,
            "vix_adjusted_mape": round(self.vix_adjusted_mape, 2),
            "external_shock_score": round(self.external_shock_score, 2),
            "data_completeness": round(self.data_completeness, 3),
            "shock_culprit": self.shock_culprit,
        }


def compute(result: EvaluationResult) -> MultiFactorScores:
    """EvaluationResult を受け取り、多角的スコアを計算して返す。"""

    # --- ① 方向精度 ---
    baseline = result.current_price_at_pred or result.actual
    pred_direction = result.predicted - baseline
    actual_direction = result.actual - baseline
    direction_ok = int((pred_direction >= 0) == (actual_direction >= 0))

    # --- ② VIX補正MAPE ---
    vix_at_pred = result.regressors_at_pred.get("VIX", 0.0)
    if vix_at_pred >= VIX_VERY_HIGH_THRESHOLD:
        tolerance_multiplier = 2.0   # VIX≥35: 許容誤差を2倍に
    elif vix_at_pred >= VIX_HIGH_THRESHOLD:
        tolerance_multiplier = 1.5   # VIX≥25: 許容誤差を1.5倍に
    else:
        tolerance_multiplier = 1.0   # 平常時: 補正なし
    vix_adjusted_mape = result.error_rate / tolerance_multiplier

    # --- ③ 外部ショックスコア（外生変数の変化幅）---
    max_drift = 0.0
    shock_culprit = "なし"
    available_count = 0
    total_count = len(REGRESSORS)

    for sym in REGRESSORS:
        v_pred = result.regressors_at_pred.get(sym)
        v_tgt = result.regressors_at_target.get(sym)

        if v_pred is not None:
            available_count += 1

        if v_pred and v_tgt and v_pred > 0:
            drift = abs(v_tgt - v_pred) / v_pred * 100
            if drift > max_drift:
                max_drift = drift
                shock_culprit = sym

    # --- ④ データ完全性 ---
    completeness = available_count / total_count if total_count > 0 else 0.0

    scores = MultiFactorScores(
        direction_accuracy=direction_ok,
        vix_adjusted_mape=vix_adjusted_mape,
        external_shock_score=round(max_drift, 2),
        data_completeness=completeness,
        shock_culprit=shock_culprit,
    )

    logger.info(
        "[%s] 多角評価: 方向=%s / VIX補正MAPE=%.1f%% / 外部ショック=%.1f%%(%s) / データ完全性=%.0f%%",
        result.symbol,
        "✅" if direction_ok else "❌",
        vix_adjusted_mape,
        max_drift,
        shock_culprit,
        completeness * 100,
    )
    return scores
