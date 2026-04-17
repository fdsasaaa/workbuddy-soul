"""
晓霞 AI 交易大脑 - 能量块 V11 规则引擎
========================================
从 Pine Script 完整翻译，不做任何改动
交易品种：XAUUSD | 周期：H1（主）+ M15/M5（辅助）
"""

import os
import json
import time
import math
import threading
from datetime import datetime
from typing import Optional

# ========================================
# 配置
# ========================================
MT4_FILES_PATH = r"C:\Users\fdsas\AppData\Roaming\MetaQuotes\Terminal\E022EDB7217C2E1A652AF8049A698882\MQL4\Files"
DATA_FILE    = os.path.join(MT4_FILES_PATH, "ai_brain_data.txt")
CMD_FILE     = os.path.join(MT4_FILES_PATH, "ai_brain_cmd.txt")
REPORT_FILE  = os.path.join(MT4_FILES_PATH, "ai_brain_report.txt")
LOG_FILE     = os.path.join(MT4_FILES_PATH, "ai_brain_log.txt")

# ========================================
# 能量块 V11 策略参数（XAUUSD H1 优化配置）
# ========================================
PARAMS = {
    # ATR 动态止损
    "ATR_Period":         17,
    "ATR_SL_Mult":        2.0,
    "EnableATRStopLoss":  True,

    # 智能入场过滤
    "UseSmartEntry":      True,
    "MinVolumeRatio":      1.2,      # 当前成交量 >= 均量的1.2倍
    "MaxBoxAgeBars":       25,       # 箱体最大年龄
    "MaxBoxATR":           2.0,
    "MaxBoxATRHard":       2.5,

    # 箱体过滤
    "EnableBoxHeightFilter": True,
    "BoxHeightMultLimit":   21.0,    # 箱体高度 <= 前15根K线平均高度的21倍
    "BoxHeightLookback":     15,

    # 移动止损
    "TrailStartRatio":    0.75,      # 盈利达到箱体高度75%时启动
    "TrailStepRatio":     0.56,      # 每次移动步长
    "TrailOffsetRatio":   0.48,      # 回撤止损位

    # 自动化核心
    "BaseQty":            1,
    "CooldownBars":       6,         # 马丁爆仓后冷却K线数
    "BreakoutInvalid":    0.42,      # 强突破失效阈值42%
    "MaxWaitBars":        100,       # 挂单超时

    # 评分
    "MinDisplayScore":    1.0,       # 合格评分阈值
    "TriggerMinBars":     1,        # 最小K线数限制

    # 时间限制
    "StratStartHour":     0,
    "StratEndHour":       21,        # 21:00后不再首次挂单

    # 马丁格尔（已禁用）
    "MartinMax":          1,
    "MartinMult":          1.0,

    # 评分权重
    "w_flatness":         0.25,
    "w_independence":     0.20,
    "w_smoothness":       0.12,
    "w_space":            0.13,
    "w_volume":           0.12,
    "w_time":             0.10,
    "w_micro":            0.08,

    # 内部固定参数
    "PivotStrength":      2,         # 前后各2根K线
    "MinBars":            5,
    "IdealBarsMin":       5,
    "IdealBarsMax":       120,
    "ReevalBars":         3,
    "MinAspect":          2.5,
    "AspectTarget":       4.5,
    "SpikeThreshold":     0.35,
    "MaxSpikeRatio":      0.25,
}


# ========================================
# 工具函数
# ========================================

def log(msg: str):
    """写入日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    print(line.strip())
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def safe_write(path: str, content: str):
    """安全写入文件"""
    for _ in range(3):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            log(f"[WARN] Write failed: {e}")
            time.sleep(0.1)
    return False


def safe_read(path: str) -> Optional[str]:
    """安全读取文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None


# ========================================
# 市场数据解析
# ========================================

def parse_market_data(raw: str) -> dict:
    """解析 MT4 EA 推送的数据"""
    lines = raw.strip().split("\n")
    result = {
        "symbol":   "",
        "time":     0,
        "bid":      0.0,
        "ask":      0.0,
        "atr":      0.0,
        "spread":   0,
        "tickvol":  0,
        "position": {
            "dir":    "NONE",
            "ticket": 0,
            "size":   0.0,
            "avg":    0.0,
            "profit": 0.0,
        },
        "H1":  {"count": 0, "open": [], "high": [], "low": [], "close": [], "vol": [], "time": []},
        "M15": {"count": 0, "open": [], "high": [], "low": [], "close": [], "vol": [], "time": []},
        "M5":  {"count": 0, "open": [], "high": [], "low": [], "close": [], "vol": [], "time": []},
    }

    for line in lines:
        if not line.strip():
            continue

        # 主行情行
        if "SYM=" in line and "BID=" in line:
            parts = line.split("|")
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    if k == "SYM":     result["symbol"] = v
                    elif k == "TIME":  result["time"] = int(v)
                    elif k == "BID":  result["bid"] = float(v)
                    elif k == "ASK":  result["ask"] = float(v)
                    elif k == "ATR":  result["atr"] = float(v)
                    elif k == "SPREAD": result["spread"] = int(v)
                    elif k == "TICKVOL": result["tickvol"] = int(v)

        # 持仓行
        elif "POS=" in line:
            parts = line.split("|")
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    if k == "POS":
                        result["position"]["dir"] = v
                    elif k == "TICKET":
                        result["position"]["ticket"] = int(v)
                    elif k == "SIZE":
                        result["position"]["size"] = float(v)
                    elif k == "AVG":
                        result["position"]["avg"] = float(v)
                    elif k == "PROFIT":
                        result["position"]["profit"] = float(v)

        # K线行（H1 / M15 / M5，支持两种格式）
        # 格式1（MT4数据）: H1:COUNT=120|OPEN=...
        # 格式2（其他来源）: H1|COUNT=120|OPEN=...
        elif any(line.startswith(p) for p in ("H1:", "M15:", "M5:", "H1|", "M15|", "M5|")):
            if line.startswith("H1:") or line.startswith("H1|"): period = "H1"
            elif line.startswith("M15:") or line.startswith("M15|"): period = "M15"
            elif line.startswith("M5:") or line.startswith("M5|"): period = "M5"
            else: continue

            bar_data = result[period]
            parts = line.split("|")
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    if k == "COUNT":
                        bar_data["count"] = int(v)
                    elif k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL", "TIME"):
                        bar_data[k.lower()] = [float(x) if k != "VOL" and k != "TIME" else
                                                (int(x) if k in ("VOL", "TIME") else float(x))
                                                for x in v.split(",")] if v else []
                    # 兼容 H1:COUNT=120 格式（冒号分隔）
                    elif ":" in k:
                        subk = k.split(":")[1]
                        if subk == "COUNT":
                            bar_data["count"] = int(v)
                        elif subk in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL", "TIME"):
                            bar_data[subk.lower()] = [float(x) if subk not in ("VOL", "TIME") else
                                                        (int(x) if subk in ("VOL", "TIME") else float(x))
                                                        for x in v.split(",")] if v else []

    return result


# ========================================
# 核心指标计算
# ========================================

def calc_atr(high: list, low: list, close: list, period: int) -> list:
    """计算 ATR（Average True Range）"""
    n = len(high)
    tr = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            h_l = high[i] - low[i]
            h_c = abs(high[i] - close[i - 1])
            c_l = abs(low[i] - close[i - 1])
            tr[i] = max(h_l, h_c, c_l)

    # 简单移动平均
    atr = [0.0] * n
    for i in range(period - 1, n):
        if i < period - 1:
            continue
        atr[i] = sum(tr[i - period + 1:i + 1]) / period
    return atr


def calc_pivots(prices: list, strength: int) -> list:
    """
    计算 pivot 点
    strength=2 表示前后各2根K线（共5根窗口）
    返回与 prices 等长的列表，非 pivot 处为 0
    """
    n = len(prices)
    length = strength + 2  # 5
    pivots = [0.0] * n
    for i in range(length - 1, n):
        center = prices[i - strength]
        is_pivot = True
        for j in range(length):
            if j == strength:
                continue
            if prices[i - j] >= center:
                is_pivot = False
                break
        if is_pivot:
            pivots[i] = center
    return pivots


def calc_r2(prices: list, start_idx: int, count: int) -> float:
    """计算 R² 拟合度"""
    if count <= 1:
        return 0.5
    vals = prices[start_idx:start_idx + count]
    n = len(vals)
    if n <= 2:
        return 0.5

    sum_x = sum_y = sum_xy = sum_x2 = sum_y2 = 0.0
    for i, y in enumerate(vals):
        x = float(i)
        sum_x  += x
        sum_y  += y
        sum_xy += x * y
        sum_x2 += x * x
        sum_y2 += y * y

    var_x = n * sum_x2 - sum_x * sum_x
    var_y = n * sum_y2 - sum_y * sum_y
    denom = math.sqrt(var_x * var_y)
    if denom == 0 or var_x <= 0 or var_y <= 0:
        return 0.5
    r = (n * sum_xy - sum_x * sum_y) / denom
    return r * r


def calc_sma(values: list, period: int) -> list:
    """简单移动平均"""
    n = len(values)
    result = [0.0] * n
    for i in range(period - 1, n):
        result[i] = sum(values[i - period + 1:i + 1]) / period
    return result


# ========================================
# 箱体评分系统（100分制）
# ========================================

def score_flatness(width_height_ratio: float, height_atr_ratio: float, p: dict) -> float:
    """平整度评分（25%）"""
    score = 0.0
    # 宽高比
    if width_height_ratio >= p["AspectTarget"]:
        score += 60
    elif width_height_ratio >= p["MinAspect"]:
        ratio1 = (width_height_ratio - p["MinAspect"]) / (p["AspectTarget"] - p["MinAspect"])
        score += 35 + ratio1 * 25
    elif width_height_ratio >= p["MinAspect"] * 0.7:
        ratio2 = width_height_ratio / p["MinAspect"]
        score += ratio2 * 25
    else:
        score += 10

    # ATR 高度比
    tight_target = 1.2
    if height_atr_ratio <= 0:
        score += 10
    elif height_atr_ratio <= tight_target:
        score += 40
    elif height_atr_ratio <= p["MaxBoxATR"]:
        h_ratio1 = 1.0 - (height_atr_ratio - tight_target) / (p["MaxBoxATR"] - tight_target)
        score += 20 + h_ratio1 * 20
    elif height_atr_ratio <= p["MaxBoxATRHard"]:
        h_ratio2 = 1.0 - (height_atr_ratio - p["MaxBoxATR"]) / (p["MaxBoxATRHard"] - p["MaxBoxATR"])
        score += h_ratio2 * 20

    if height_atr_ratio > 2.0:
        score *= 0.75

    return min(100.0, score)


def score_independence(box_top: float, box_bottom: float, box_height: float,
                        high: list, low: list, start_bar: int,
                        touches_top: int, touches_bottom: int,
                        p: dict) -> float:
    """独立性评分（20%）"""
    score = 100.0
    if touches_top < 2 or touches_top > 8:
        score -= 15
    if touches_bottom < 2 or touches_bottom > 8:
        score -= 15

    lookback = 10
    overlap_count = 0
    buffer = box_height * 0.3
    for k in range(lookback):
        idx = start_bar + 1 + k
        if 0 <= idx < len(high):
            mid = (high[idx] + low[idx]) / 2.0
            bar_range = high[idx] - low[idx]
            price_overlap = mid < (box_top + buffer) and mid > (box_bottom - buffer)
            is_flat = bar_range < box_height * 1.2
            if price_overlap and is_flat:
                overlap_count += 1

    if overlap_count > 6:
        score -= 40
    elif overlap_count > 4:
        score -= 25
    elif overlap_count > 2:
        score -= 10
    else:
        score += 15

    return max(0.0, min(100.0, score))


def score_smoothness(top_r2: float, bottom_r2: float, spike_ratio: float, p: dict) -> float:
    """平滑度评分（12%）"""
    avg_r2 = (top_r2 + bottom_r2) / 2.0
    if avg_r2 >= 0.5:
        score = 80 + (avg_r2 - 0.5) * 40
    elif avg_r2 >= 0.2:
        score = 40 + (avg_r2 - 0.2) * (100.0 / 0.3)
    else:
        score = avg_r2 * 200

    score -= spike_ratio * 30
    return max(0.0, min(100.0, score))


def score_space(box_height: float, atr: float, p: dict) -> float:
    """空间比评分（13%）"""
    safe_height = box_height if box_height > 0 else atr
    expected_move = 3 * atr
    ratio = expected_move / safe_height if safe_height > 0 else 0

    if ratio >= 3:
        return 100.0
    elif ratio >= 2:
        return 70 + (ratio - 2) * 30
    elif ratio >= 1:
        return 30 + (ratio - 1) * 40
    else:
        return ratio * 30


def score_volume(current_vol: float, box_vol_list: list, p: dict) -> float:
    """成交量评分（12%）"""
    if not box_vol_list:
        return 50.0
    avg_vol = sum(box_vol_list) / len(box_vol_list)
    if avg_vol == 0:
        return 50.0
    ratio = current_vol / avg_vol
    if ratio >= 1.5:
        return 100.0
    elif ratio >= 1.0:
        return 50 + (ratio - 1.0) / 0.5 * 50
    else:
        return ratio * 50


def score_time(box_bars: int, p: dict) -> float:
    """时间评分（10%）"""
    if p["IdealBarsMin"] <= box_bars <= p["IdealBarsMax"]:
        return 100.0
    elif box_bars < p["IdealBarsMin"]:
        return float(box_bars) / float(p["IdealBarsMin"]) * 70.0
    else:
        return max(30.0, 100.0 - (box_bars - p["IdealBarsMax"]) / 2.0)


def score_micro(box_top: float, box_bottom: float, box_height: float,
                 touches_top: int, touches_bottom: int,
                 spike_ratio: float, top_r2: float, bottom_r2: float,
                 box_bars: int, p: dict) -> float:
    """微观评分（8%）"""
    score = 70.0
    effective_spike = spike_ratio
    if box_bars < 8:
        effective_spike = spike_ratio * 0.5
    if effective_spike > p["MaxSpikeRatio"]:
        score -= (effective_spike - p["MaxSpikeRatio"]) * 100

    touch_diff = abs(touches_top - touches_bottom)
    score -= touch_diff * 5

    if box_bars <= 6 and (top_r2 > 0.8 or bottom_r2 > 0.8):
        score += 15

    return max(0.0, min(100.0, score))


# ========================================
# 主策略引擎
# ========================================

class EnergyBlockEngine:
    """
    能量块 V11 规则引擎
    从 Pine Script 完整翻译，不做任何策略改动
    """

    def __init__(self):
        self.p = PARAMS
        self.state = "IDLE"           # IDLE / PENDING / POSITION
        self.lock_box_top = 0.0
        self.lock_box_bottom = 0.0
        self.lock_box_h = 0.0
        self.lock_box_start_bar = 0
        self.lock_box_end_bar = 0
        self.lock_box_time = 0

        self.martin_count = 0
        self.is_recovery = False
        self.martin_dir = 0
        self.trail_high_price = 0.0
        self.dynamic_sl = 0.0
        self.wait_bar_count = 0
        log(f"[WAIT_CNT] init wait_bar_count=0")
        self.box_bar_count = 0     # 独立箱体年龄计数器（不受 wait_bar_count 影响）
        log(f"[BOX_CNT] init box_bar_count=0")
        self.trade_qty = 1.0
        self.atr_stop_loss = 0.0
        self.next_trade_bar = 0

        self.pending_orders = []       # 当前挂出的订单
        self.last_bar_index = -1
        self.score_history = [50.0, 50.0, 50.0]

        self.darvas_state = 0          # 0=初始, 1=有top, -1=有bottom
        self.darvas_confirmed = 0      # 0=未确认, 1=已确认
        self.darvas_box_top = None
        self.darvas_box_bottom = None
        self.darvas_box_start_time = 0

        self.pending_cmd = None         # 待发送指令
        self.last_mtime = 0.0           # 文件修改时间戳（用于Tick触发）
        self.last_bar_count = 0        # 已处理的K线编号

        # 高亮日志去重状态追踪
        self._last_high_boundary_bar = -1
        self._last_high_boundary_ratio = 0.0
        self._high_vol_ok_fired = False
        self._high_vol_no_cmd_fired = False
        self._high_vol_no_cmd_bar = -1

    def is_in_trade_time(self) -> bool:
        """检查是否在交易时间内（00:00-21:00）"""
        now = datetime.now()
        if self.p["StratStartHour"] == 0 and self.p["StratEndHour"] == 0:
            return True
        hour = now.hour
        start = self.p["StratStartHour"]
        end = self.p["StratEndHour"]
        if start <= end:
            return start <= hour < end
        else:
            return hour >= start or hour < end

    def is_smart_entry_valid(self, box_top: float, box_bottom: float,
                              current_vol: float, avg_vol: float,
                              atr: float, avg_price: float,
                              box_bars: int) -> bool:
        """智能入场过滤"""
        if not self.p["UseSmartEntry"]:
            return True
        volume_ok = current_vol >= avg_vol * self.p["MinVolumeRatio"]
        age_ok = box_bars <= self.p["MaxBoxAgeBars"]
        volatility_ok = (avg_price > 0) and (atr <= avg_price * 0.02)
        return volume_ok and age_ok and volatility_ok

    def is_box_height_valid(self, box_height: float, recent_high: list,
                             recent_low: list, box_end_idx: int) -> bool:
        """箱体高度过滤"""
        if not self.p["EnableBoxHeightFilter"]:
            return True
        lookback = self.p["BoxHeightLookback"]
        total = 0.0
        valid = 0
        start_offset = box_end_idx + 1
        for i in range(lookback):
            idx = start_offset + i
            if 0 <= idx < len(recent_high):
                kline_h = recent_high[idx] - recent_low[idx]
                total += kline_h
                valid += 1
        if valid == 0:
            return True
        avg_h = total / valid
        max_allowed = avg_h * self.p["BoxHeightMultLimit"]
        return box_height < max_allowed

    def calculate_sl(self, entry_price: float, box_top: float,
                      box_bottom: float, is_long: bool, atr: float) -> float:
        """计算止损价格（ATR 动态止损）"""
        box_h = abs(box_top - box_bottom)
        atr_sl = atr * self.p["ATR_SL_Mult"]
        sl_dist = max(box_h, atr_sl)
        if is_long:
            return entry_price - sl_dist
        else:
            return entry_price + sl_dist

    def calc_stop_pips(self, entry_price: float, sl_price: float) -> int:
        """计算止损点数（XAUUSD 精度）"""
        if sl_price <= 0 or entry_price <= 0:
            return 50
        dist = abs(entry_price - sl_price)
        # XAUUSD 的 1 pip = 0.01（两位小数），1 point = 0.01, 1 pip = 10 points
        pips = int(dist / 0.01)
        return max(1, pips)

    def calc_trail_stop(self, pos_avg: float, trail_high: float,
                         direction: int, is_long: bool) -> float:
        """计算移动止损"""
        if self.lock_box_h <= 0:
            return 0.0  # 无箱体数据，跳过移动止损

        if is_long:
            profit = trail_high - pos_avg
        else:
            profit = pos_avg - trail_high

        trigger_dist = self.lock_box_h * self.p["TrailStartRatio"]
        if profit < trigger_dist:
            return 0.0  # 未触发

        step_dist = self.lock_box_h * self.p["TrailStepRatio"]
        if step_dist <= 0:
            return 0.0  # 防除零
        jumps = int((profit - trigger_dist) / step_dist)
        offset = self.p["TrailOffsetRatio"] * self.lock_box_h + jumps * step_dist

        if is_long:
            return pos_avg + offset
        else:
            return pos_avg - offset

    def detect_darvas_box(self, h1: dict) -> dict:
        """
        检测当前 Darvas 箱体
        返回 box 信息或 None
        """
        closes = h1["close"]
        highs  = h1["high"]
        lows   = h1["low"]
        times  = h1["time"]
        n = len(closes)
        if n < self.p["MinBars"] + 5:
            return None

        # MT4 数据排列为 [最新, ..., 最旧]，反转后 index 0 = 最旧，与 pivot 算法一致
        closes = closes[::-1]
        highs  = highs[::-1]
        lows   = lows[::-1]
        times  = times[::-1]

        # 计算 pivot high / low
        strength = self.p["PivotStrength"]
        length = strength + 2  # 5

        # 高点 pivot
        pivot_high = [0.0] * n
        for i in range(length - 1, n):
            center_val = highs[i - strength]
            is_max = True
            for j in range(length):
                if j == strength:
                    continue
                if highs[i - j] >= center_val:
                    is_max = False
                    break
            if is_max:
                pivot_high[i] = center_val

        # 低点 pivot
        pivot_low = [0.0] * n
        for i in range(length - 1, n):
            center_val = lows[i - strength]
            is_min = True
            for j in range(length):
                if j == strength:
                    continue
                if lows[i - j] <= center_val:
                    is_min = False
                    break
            if is_min:
                pivot_low[i] = center_val

        # 状态机找箱体（从后往前遍历，找到最近的 pivot 组合）
        self.darvas_state = 0
        self.darvas_confirmed = 0
        box_top = None
        box_bottom = None
        box_start_time = 0

        for i in range(n - 1, length - 2, -1):
            if self.darvas_state == 0:
                # 初始状态，找第一个 pivot
                if pivot_high[i] > 0:
                    box_top = pivot_high[i]
                    self.darvas_state = 1
                    box_start_time = times[i - strength] if (i - strength) >= 0 else 0
                elif pivot_low[i] > 0:
                    box_bottom = pivot_low[i]
                    self.darvas_state = -1
                    box_start_time = times[i - strength] if (i - strength) >= 0 else 0
            elif self.darvas_state == 1:
                # 已有 top（更近），等待更早的 bottom
                if pivot_low[i] > 0 and times[i - strength] < box_start_time:
                    box_bottom = pivot_low[i]
                    self.darvas_confirmed = 1
                    break
            elif self.darvas_state == -1:
                # 已有 bottom（更近），等待更早的 top
                if pivot_high[i] > 0 and times[i - strength] < box_start_time:
                    box_top = pivot_high[i]
                    self.darvas_confirmed = 1
                    break

        if self.darvas_confirmed != 1:
            log(f"[BOX_DEBUG] 检测失败: darvas_confirmed={self.darvas_confirmed} darvas_state={self.darvas_state} n={n}")
            return None

        # 计算箱体
        if box_top is None or box_bottom is None:
            return None

        box_top = max(box_top, box_bottom)
        box_bottom = min(box_top, box_bottom)
        box_height = box_top - box_bottom

        if box_top <= box_bottom or box_height <= 0:
            return None

        return {
            "top":   box_top,
            "bottom": box_bottom,
            "height": box_height,
        }

    def rate_box(self, box: dict, h1: dict, current_bar_idx: int) -> float:
        """
        对箱体进行7维度评分
        返回 0-100 的总分
        """
        p = self.p
        top = box["top"]
        bottom = box["bottom"]
        height = box["height"]

        # 统计箱体内K线
        box_bars = 0
        touches_top = 0
        touches_bottom = 0
        spikes = 0
        box_vol_list = []

        closes = h1["close"]
        highs  = h1["high"]
        lows   = h1["low"]
        vols   = h1["vol"]
        n = len(closes)

        # 从当前往前找箱体范围（最多 IdealBarsMax 根）
        for k in range(p["IdealBarsMax"]):
            idx = current_bar_idx - k
            if idx < 0 or idx >= n:
                break
            is_current = (k == 0)
            is_inside = (highs[idx] <= top + height * 0.05 and
                          lows[idx] >= bottom - height * 0.05)
            if is_current or is_inside:
                box_bars += 1
            else:
                break

        box_bars = max(p["MinBars"], box_bars)
        box_start_idx = current_bar_idx - box_bars + 1
        box_end_idx = current_bar_idx

        # 触碰统计
        for idx in range(box_end_idx, box_start_idx - 1, -1):
            if 0 <= idx < n:
                if abs(highs[idx] - top) < height * 0.05:
                    touches_top += 1
                if abs(lows[idx] - bottom) < height * 0.05:
                    touches_bottom += 1
                if highs[idx] > top + height * p["SpikeThreshold"] or \
                   lows[idx] < bottom - height * p["SpikeThreshold"]:
                    spikes += 1
                box_vol_list.append(vols[idx] if idx < len(vols) else 0)

        spike_ratio = spikes / max(1, box_bars)

        # ATR
        atr_vals = calc_atr(highs, lows, closes, p["ATR_Period"])
        atr = atr_vals[current_bar_idx] if current_bar_idx < len(atr_vals) else height * 0.5
        if atr <= 0:
            atr = height * 0.5

        # R²
        top_r2 = calc_r2(highs, box_start_idx, box_bars)
        bottom_r2 = calc_r2(lows, box_start_idx, box_bars)

        # 7维度评分
        s_flatness     = score_flatness(box_bars / height if height > 0 else 0, height / atr if atr > 0 else 0, p)
        s_independence = score_independence(top, bottom, height, highs, lows, box_start_idx,
                                             touches_top, touches_bottom, p)
        s_smoothness   = score_smoothness(top_r2, bottom_r2, spike_ratio, p)
        s_space        = score_space(height, atr, p)
        s_volume       = score_volume(vols[current_bar_idx] if current_bar_idx < len(vols) else 0,
                                      box_vol_list, p)
        s_time         = score_time(box_bars, p)
        s_micro        = score_micro(top, bottom, height, touches_top, touches_bottom,
                                      spike_ratio, top_r2, bottom_r2, box_bars, p)

        total = (s_flatness * p["w_flatness"] +
                 s_independence * p["w_independence"] +
                 s_smoothness * p["w_smoothness"] +
                 s_space * p["w_space"] +
                 s_volume * p["w_volume"] +
                 s_time * p["w_time"] +
                 s_micro * p["w_micro"])

        return min(100.0, total)

    def on_bar(self, data: dict) -> Optional[dict]:
        """
        每根K线调用一次，返回交易指令或 None
        """
        h1 = data["H1"]
        closes = h1["close"]
        m15 = data["M15"]
        highs  = h1["high"]
        lows   = h1["low"]
        vols   = h1["vol"]

        n = len(closes)
        if n < 10:
            return None

        current_bar = n - 1
        bar_changed = (current_bar != self.last_bar_index)
        if bar_changed:
            self.last_bar_index = current_bar
            log(f"[WAIT_CNT] bar_changed_plus | old={self.wait_bar_count} new={self.wait_bar_count+1} loc=on_bar:814")
            self.wait_bar_count += 1
            # box_bar_count: 独立箱体年龄计数，仅在 bar 变化时递增，不受其他逻辑重置
            if not hasattr(self, 'box_bar_count'):
                self.box_bar_count = 0
                log(f"[BOX_CNT] init box_bar_count=0 loc=on_bar:817")
            log(f"[BOX_CNT] bar_changed_plus | old={self.box_bar_count} new={self.box_bar_count+1} loc=on_bar:818")
            self.box_bar_count += 1

        pos_dir  = data["position"]["dir"]
        pos_size = data["position"]["size"]
        pos_avg  = data["position"]["avg"]
        pos_profit = data["position"]["profit"]
        bid = data["bid"]
        ask = data["ask"]
        current_time = data["time"]

        # ----- ATR -----
        atr_vals = calc_atr(highs, lows, closes, self.p["ATR_Period"])
        atr = atr_vals[current_bar] if current_bar < len(atr_vals) else 0.0
        avg_price = (bid + ask) / 2.0

        # ----- 冷却检查（提前到此处，使 box 块内的高亮日志可引用） -----
        in_cooldown = current_bar <= self.next_trade_bar

        # ----- 检测箱体 -----
        box = self.detect_darvas_box(h1)
        box_score = 0.0
        box_height_ok = True
        smart_entry_ok = True
        is_qualified = False
        volume_ok = False
        age_ok = False
        volatility_ok = False

        if box:
            box_score = self.rate_box(box, h1, current_bar)
            box_height_ok = self.is_box_height_valid(
                box["height"], highs, lows, current_bar)
            is_qualified = (box_score >= self.p["MinDisplayScore"] and
                            self.wait_bar_count >= self.p["TriggerMinBars"] and
                            box_height_ok)

            avg_vol_vals = calc_sma(vols, 20)
            avg_vol = avg_vol_vals[current_bar] if current_bar < len(avg_vol_vals) else vols[current_bar]
            smart_entry_ok = self.is_smart_entry_valid(
                box["top"], box["bottom"],
                vols[current_bar] if current_bar < len(vols) else 0,
                avg_vol, atr, avg_price,
                self.wait_bar_count)

            # [DEBUG] 智能入场过滤 - 10个真实值
            current_vol = vols[current_bar] if current_bar < len(vols) else 0
            MinVolumeRatio = self.p["MinVolumeRatio"]
            avg_vol = avg_vol_vals[current_bar] if current_bar < len(avg_vol_vals) else vols[current_bar]
            volume_ok = current_vol >= avg_vol * MinVolumeRatio
            ratio = current_vol / avg_vol if avg_vol > 0 else 0
            box_bars = self.box_bar_count
            MaxBoxAgeBars = self.p["MaxBoxAgeBars"]
            age_ok = box_bars <= MaxBoxAgeBars
            volatility_ok = (avg_price > 0) and (atr <= avg_price * 0.02)

            # [HIGH_BOUNDARY] 边界状态事件：只在新 bar 首次进入边界，或 ratio 跨越阈值边界时打印
            in_boundary = (1.05 <= ratio < 1.20)
            ratio_crossed = (self._last_high_boundary_ratio > 0 and
                             ((self._last_high_boundary_ratio < 1.05 and ratio >= 1.05) or
                              (self._last_high_boundary_ratio < 1.20 and ratio >= 1.20)))
            new_bar_entry = bar_changed and in_boundary
            if is_qualified and in_boundary and (new_bar_entry or ratio_crossed):
                self._last_high_boundary_bar = current_bar
                self._last_high_boundary_ratio = ratio
                log(f"[HIGH_BOUNDARY] BAR={current_bar} TS={data['time']} cur_vol={current_vol:.0f} "
                    f"avg_vol={avg_vol:.2f} ratio={ratio:.4f} vol_ok={'T' if volume_ok else 'F'} "
                    f"age_ok={'T' if age_ok else 'F'} volatility_ok={'T' if volatility_ok else 'F'} "
                    f"smart_ok={'T' if smart_entry_ok else 'F'} qualified=T "
                    f"trigger={'NEW_BAR' if new_bar_entry else 'RATIO_CROSS'}")

            # [HIGH_VOL_OK] 首次放行：只在该状态首次满足时打印，重置条件：状态从 F 变 T 或新 bar 首次满足
            if is_qualified and volume_ok and not self._high_vol_ok_fired:
                self._high_vol_ok_fired = True
                log(f"[HIGH_VOL_OK] BAR={current_bar} TS={data['time']} cur_vol={current_vol:.0f} "
                    f"avg_vol={avg_vol:.2f} ratio={ratio:.4f} vol_ok=T "
                    f"age_ok={'T' if age_ok else 'F'} volatility_ok={'T' if volatility_ok else 'F'} "
                    f"smart_ok={'T' if smart_entry_ok else 'F'} qualified=T")

            # [HIGH_VOL_OK_NO_CMD] 首次命中：只打印首次，重置条件：持多仓 或 新 bar 首次命中
            if pos_size <= 0 and is_qualified and volume_ok:
                if not self._high_vol_no_cmd_fired or self._high_vol_no_cmd_bar != current_bar:
                    self._high_vol_no_cmd_fired = True
                    self._high_vol_no_cmd_bar = current_bar
                    blockers = []
                    if not age_ok: blockers.append("age")
                    if not volatility_ok: blockers.append("volatility")
                    if not smart_entry_ok: blockers.append("smart")
                    block_str = ",".join(blockers) if blockers else "none"
                    log(f"[HIGH_VOL_OK_NO_CMD] BAR={current_bar} TS={data['time']} cur_vol={current_vol:.0f} "
                        f"avg_vol={avg_vol:.2f} ratio={ratio:.4f} blocker={block_str} "
                        f"cooldown={'T' if in_cooldown else 'F'} pos_size={pos_size:.1f}")

            # 重置 HIGH_VOL_OK 标志：持多仓时允许下次重新触发
            if pos_size > 0:
                self._high_vol_ok_fired = False

        # ----- [DEBUG] 打印当前 Tick 关键状态 -----
        score_ok = box_score >= self.p["MinDisplayScore"]
        wait_ok  = self.wait_bar_count >= self.p["TriggerMinBars"]
        box_height_val = box["height"] if box else 0.0
        min_pts = self.p.get("MinBoxPoints", 0)
        max_pts = self.p.get("MaxBoxPoints", 99999)
        # box_bars 使用独立变量，不受 wait_bar_count 重置影响
        box_bars = self.box_bar_count if hasattr(self, 'box_bar_count') else 0
        # 防御性取值：box 为 None 时这些变量未定义，不能直接出现在 f-string 中
        cv_val   = current_vol if box else 0.0
        vo_val   = volume_ok   if box else False
        ao_val   = age_ok      if box else False
        vol_val  = volatility_ok if box else False
        sm_val   = smart_entry_ok if box else False
        log(f"[DEBUG] box={'存在' if box else 'None'} score={box_score:.1f} MinDS={self.p['MinDisplayScore']} "
            f"score_ok={'T' if score_ok else 'F'} wait_cnt={self.wait_bar_count} box_bars={box_bars} TrigMB={self.p['TriggerMinBars']} "
            f"wait_ok={'T' if wait_ok else 'F'} box_h={box_height_val:.1f} MinBP={min_pts} MaxBP={max_pts} "
            f"bh_ok={'T' if box_height_ok else 'F'} qualified={'T' if is_qualified else 'F'} "
            f"vol_ok={'T' if vo_val else 'F'} age_ok={'T' if ao_val else 'F'} "
            f"volatility_ok={'T' if vol_val else 'F'} smart_ok={'T' if sm_val else 'F'} "
            f"cooldown={'T' if in_cooldown else 'F'} state={self.state} pos_size={pos_size:.1f}")

        # ----- 状态机 -----
        cmd = None

        # ====== 持仓中 ======
        if pos_size > 0:
            self.state = "POSITION"
            log(f"[WAIT_CNT] pos_size_gt_zero | old={self.wait_bar_count} new=0 loc=on_bar:945 reason=pos_size>0")
            self.wait_bar_count = 0
            log(f"[BOX_CNT] pos_size_gt_zero | old={self.box_bar_count} new=0 loc=on_bar:947 reason=pos_size>0")
            self.box_bar_count = 0   # 同步重置箱体年龄

            # 更新 trail high
            if pos_dir == "LONG":
                self.trail_high_price = max(self.trail_high_price, highs[current_bar])
            else:
                if self.trail_high_price == 0:
                    self.trail_high_price = lows[current_bar]
                else:
                    self.trail_high_price = min(self.trail_high_price, lows[current_bar])

            # 计算止损
            sl_price = self.calculate_sl(pos_avg, self.lock_box_top,
                                          self.lock_box_bottom,
                                          pos_dir == "LONG", atr)

            # 移动止损
            is_long_pos = pos_dir == "LONG"
            trail_sl = self.calc_trail_stop(pos_avg, self.trail_high_price,
                                              self.martin_dir, is_long_pos)

            final_sl = sl_price
            if trail_sl > 0:
                if is_long_pos:
                    final_sl = max(sl_price, trail_sl)
                else:
                    final_sl = min(sl_price, trail_sl)

            self.dynamic_sl = final_sl

            # 触发移动止盈？（必须 lock_box_h > 0 才有意义）
            if self.lock_box_h > 0:
                trail_trigger = self.lock_box_h * self.p["TrailStartRatio"]
                if is_long_pos:
                    profit = self.trail_high_price - pos_avg
                    if profit >= trail_trigger:
                        cmd = {"action": "CLOSE", "reason": "移动止盈"}
                else:
                    profit = pos_avg - self.trail_high_price
                    if profit >= trail_trigger:
                        cmd = {"action": "CLOSE", "reason": "移动止盈"}

        # ====== 空闲状态 ======
        elif pos_size == 0 and self.state != "PENDING":
            if self.state == "POSITION":
                # 刚平仓，判断结果
                if pos_profit >= 0:
                    # 盈利，重置
                    self.state = "IDLE"
                    self.martin_count = 0
                    self.is_recovery = False
                    self.pending_orders = []
                    self.darvas_state = 0
                    self.darvas_confirmed = 0
                    self.lock_box_top = 0.0
                    self.lock_box_bottom = 0.0
                    cmd = None
                else:
                    # 止损亏损
                    self.state = "PENDING"
                    log(f"[WAIT_CNT] stop_loss_pending | old={self.wait_bar_count} new=0 loc=on_bar:1008 reason=stop_loss")
                    self.wait_bar_count = 0
                    log(f"[BOX_CNT] stop_loss_pending | old={self.box_bar_count} new=0 loc=on_bar:1010 reason=stop_loss")
                    self.box_bar_count = 0   # 同步重置箱体年龄
                    # 马丁逻辑（但当前禁用）
                    if self.martin_count >= self.p["MartinMax"]:
                        # 马丁用尽，冷却
                        self.state = "IDLE"
                        self.martin_count = 0
                        self.next_trade_bar = current_bar + self.p["CooldownBars"]
                        self.pending_orders = []
                        self.darvas_state = 0
                        self.darvas_confirmed = 0
                        log(f"[马丁用尽] 冷却 {self.p['CooldownBars']} 根K线")
                    else:
                        # 马丁未用尽（当前实际不会走到这里，因为MartinMax=1）
                        self.martin_count += 1
            else:
                # 仅在 POSITION → IDLE 状态转换时重置
                if self.state == "POSITION":
                    log(f"[BOX_CNT] position_closed_reset | old={self.box_bar_count} new=0 loc=on_bar:1026 reason=position_to_idle")
                    self.box_bar_count = 0
                self.state = "IDLE"

        # ====== 挂单中 ======
        if self.state == "PENDING" and pos_size == 0:
            # 超时撤单
            if self.wait_bar_count > self.p["MaxWaitBars"]:
                self.state = "IDLE"
                self.pending_orders = []
                log("[超时] 撤单，空闲")
                cmd = {"action": "CANCEL"}

            # 强突破检测
            if box and len(self.pending_orders) > 0:
                hard_limit_up = self.lock_box_top + self.lock_box_h * self.p["BreakoutInvalid"]
                hard_limit_down = self.lock_box_bottom - self.lock_box_h * self.p["BreakoutInvalid"]
                if highs[current_bar] > hard_limit_up or lows[current_bar] < hard_limit_down:
                    self.state = "IDLE"
                    self.pending_orders = []
                    self.martin_count = 0
                    log("[强突破] 撤单，空闲")
                    cmd = {"action": "CANCEL"}

        # ====== 空闲 + 新箱体满足条件 ======
        if self.state == "IDLE" and not in_cooldown and box and is_qualified \
           and self.is_in_trade_time() and smart_entry_ok:
            # 锁定箱体，发送挂单指令
            self.lock_box_top = box["top"]
            self.lock_box_bottom = box["bottom"]
            self.lock_box_h = box["height"]

            self.state = "PENDING"
            log(f"[WAIT_CNT] enter_pending | old={self.wait_bar_count} new=0 loc=on_bar:1061 reason=enter_pending")
            self.wait_bar_count = 0
            log(f"[BOX_CNT] enter_pending | old={self.box_bar_count} new=0 loc=on_bar:1063 reason=enter_pending")
            self.box_bar_count = 0   # 同步重置箱体年龄
            self.martin_count = 0
            self.is_recovery = False
            self.pending_orders = ["BUY", "SELL"]

            # ATR 止损价格
            if self.p["EnableATRStopLoss"]:
                self.atr_stop_loss = self.calculate_sl(ask, box["top"], box["bottom"], True, atr)

            log(f"[新箱体] TOP={box['top']:.2f} BOT={box['bottom']:.2f} "
                f"H={box['height']:.2f} SCORE={box_score:.1f}")

            # 同时挂多空两个 stop 单
            cmd = {
                "action": "PENDING",
                "buy_stop":  box["top"],
                "sell_stop": box["bottom"],
                "sl_pips":   self.calc_stop_pips(box["top"], self.calculate_sl(box["top"], box["top"], box["bottom"], True, atr)),
                "comment":   f"能量块V11 | 评分{box_score:.1f}",
            }

            # [HIGH_VOL_OK_NO_CMD] box存在 + qualified + volume_ok=True + 但 cmd=None（下一层阻塞点）
            if is_qualified and volume_ok and not cmd:
                block_reason = []
                if not self.is_in_trade_time(): block_reason.append("time")
                if in_cooldown: block_reason.append("cooldown")
                if not smart_entry_ok: block_reason.append("smart")
                if not self.is_in_trade_time(): block_reason.append("time")
                log(f"[HIGH_VOL_OK_NO_CMD] TS={data['time']} cur_vol={current_vol:.0f} "
                    f"avg_vol={avg_vol:.2f} ratio={ratio:.4f} vol_ok=T "
                    f"age_ok={'T' if age_ok else 'F'} volatility_ok={'T' if volatility_ok else 'F'} "
                    f"smart_ok={'T' if smart_entry_ok else 'F'} qualified={'T' if is_qualified else 'F'} "
                    f"state={self.state} cooldown={'T' if in_cooldown else 'F'} "
                    f"block={';'.join(block_reason) if block_reason else 'unknown'}")

        log(f"[DEBUG] 最终 cmd={'有指令' if cmd else 'None'}")
        return cmd


# ========================================
# Python AI 大脑（主程序）
# ========================================

class XiaoXiaBrain:
    """晓霞 AI 交易大脑"""

    def __init__(self):
        self.engine = EnergyBlockEngine()
        self.last_data_hash = ""
        self.last_bar_count = 0
        self.last_mtime = 0.0   # 文件修改时间戳（Tick感知）
        self.running = True
        self.data_interval = 1.0   # 秒
        self.lock = threading.Lock()

    def send_command(self, cmd: dict):
        """发送指令到 MT4 EA"""
        if cmd["action"] == "PENDING":
            content = (
                f"ACTION=BUY|LOTS=0.01|PRICE={cmd['buy_stop']:.2f}"
                f"|SL={cmd['sl_pips']}|COMMENT={cmd['comment']}\n"
                f"ACTION=SELL|LOTS=0.01|PRICE={cmd['sell_stop']:.2f}"
                f"|SL={cmd['sl_pips']}|COMMENT={cmd['comment']}"
            )
        elif cmd["action"] == "CLOSE":
            content = "ACTION=CLOSE|COMMENT=AI_Close"
        elif cmd["action"] == "CANCEL":
            content = "ACTION=CANCEL|COMMENT=AI_Cancel"
        else:
            return

        safe_write(CMD_FILE, content)
        log(f"[发送指令] {cmd['action']}")

    def read_reports(self):
        """读取成交回报"""
        content = safe_read(REPORT_FILE)
        if not content:
            return []
        reports = []
        for line in content.strip().split("\n"):
            if "|" in line:
                parts = line.split("|")
                r = {}
                for p in parts:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        r[k] = v
                reports.append(r)
        # 清空回报文件
        safe_write(REPORT_FILE, "")
        return reports

    def tick(self):
        """主循环tick"""
        # 读取数据
        raw = safe_read(DATA_FILE)
        if not raw:
            return

        # 获取文件修改时间（Tick感知核心）
        try:
            current_mtime = os.path.getmtime(DATA_FILE)
        except OSError:
            return

        # 文件无变化，跳过（配合1秒轮询做节流）
        if current_mtime == self.last_mtime:
            return
        self.last_mtime = current_mtime

        # 解析
        data = parse_market_data(raw)
        if not data["symbol"]:
            return

        # 检查K线变化（新K线形成时触发策略层）
        h1_count = data["H1"]["count"]
        bar_changed = (h1_count != self.last_bar_count)
        self.last_bar_count = h1_count

        log(f"[Tick] BAR={h1_count} BID={data['bid']:.2f} ATR={data['atr']:.4f} "
            f"POS={data['position']['dir']} PROFIT={data['position']['profit']:.2f} NEW_BAR={'T' if bar_changed else 'F'}")

        # 策略引擎处理（每轮Tick都执行，不等新K线）
        cmd = self.engine.on_bar(data)

        if cmd:
            self.send_command(cmd)

        # 读取回报
        reports = self.read_reports()
        for r in reports:
            log(f"[回报] TICKET={r.get('TICKET','?')} {r.get('ACTION','?')} "
                f"{r.get('STATUS','?')} ERR={r.get('COMMENT','?')}")

    def run(self):
        """主程序入口"""
        log("=" * 50)
        log("晓霞 AI 交易大脑启动")
        log(f"数据文件: {DATA_FILE}")
        log(f"指令文件: {CMD_FILE}")
        log(f"策略: 能量块 V11")
        log("=" * 50)

        while self.running:
            try:
                self.tick()
            except Exception as e:
                log(f"[ERROR] {e}")
            time.sleep(self.data_interval)


if __name__ == "__main__":
    brain = XiaoXiaBrain()
    try:
        brain.run()
    except KeyboardInterrupt:
        brain.running = False
        log("晓霞 AI 交易大脑已停止")
