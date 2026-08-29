"""
宝妈指数计算引擎
四个板块独立计算，各自有完整的历史曲线
"""
from datetime import datetime, date
from typing import Dict, List
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

SECTOR_NAMES = {
    "nasdaq": "纳斯达克",
    "gold": "黄金",
    "cpo": "CPO通信",
    "semiconductor": "半导体",
}


def compute_sector_index(analysis_results: List) -> Dict:
    """
    计算单个板块的宝妈指数 (0-100)
    
    四个维度:
    1. 小白占比 (40%) — 该板块中小白帖的比例
    2. 小白强度 (25%) — 小白帖的平均得分
    3. 情绪极端度 (20%) — 贪婪/恐慌的情绪极端程度
    4. 热度信号 (15%) — 该板块的讨论活跃度
    """
    if not analysis_results:
        return {
            "index": 0, 
            "interpretation": "无数据",
            "details": {}
        }
    
    total = len(analysis_results)
    
    # 过滤掉垃圾帖
    valid_posts = [r for r in analysis_results if r.level != "垃圾帖"]
    spam_count = total - len(valid_posts)
    
    # 小白帖（分数 >= 20）
    newbie_posts = [r for r in analysis_results if r.newbie_score >= 20]
    pure_newbie = [r for r in analysis_results if r.newbie_score >= 50]
    newbie_count = len(newbie_posts)
    
    # 维度1: 小白占比 (0-100) — 基于有效帖子
    newbie_ratio = (newbie_count / len(valid_posts)) * 100 if valid_posts else 0
    
    # 维度2: 小白强度 (0-100)
    avg_newbie_score = sum(r.newbie_score for r in newbie_posts) / max(newbie_count, 1)
    
    # 维度3: 情绪极端度 (0-100)
    sentiments = [abs(r.sentiment_score) for r in newbie_posts]
    avg_sentiment = sum(sentiments) / max(len(sentiments), 1) * 100
    
    # 维度4: 热度信号 (0-100) — 小白帖占比越高 + 纯小白越多 = 信号越强
    purity_signal = (len(pure_newbie) / max(newbie_count, 1)) * 100 if newbie_count > 0 else 0
    activity_signal = min(100, len(valid_posts) / 80 * 100)  # 80条为满热度
    
    # 综合指数
    index = (
        newbie_ratio * 0.40 +
        avg_newbie_score * 0.25 +
        avg_sentiment * 0.20 +
        purity_signal * 0.15
    )
    
    index = round(min(100, index), 1)
    
    # ---- 买入/卖出子指数 ----
    newbie_buy = [r for r in newbie_posts if r.intent == "buy"]
    newbie_sell = [r for r in newbie_posts if r.intent == "sell"]
    
    buy_ratio = len(newbie_buy) / max(newbie_count, 1)
    sell_ratio = len(newbie_sell) / max(newbie_count, 1)
    buy_intensity = sum(r.intent_strength for r in newbie_buy) / max(len(newbie_buy), 1)
    sell_intensity = sum(r.intent_strength for r in newbie_sell) / max(len(newbie_sell), 1)
    
    # 买入指数: 小白买入占比(50%) + 小白热度(30%) + 买入强度(20%)
    mom_buy_index = round(min(100, (
        buy_ratio * 100 * 0.50 +
        (avg_newbie_score / 100) * buy_ratio * 30 * 0.30 +
        buy_intensity * 100 * 0.20
    )), 1)
    
    # 卖出指数: 小白卖出占比(50%) + 小白热度(30%) + 卖出强度(20%)
    mom_sell_index = round(min(100, (
        sell_ratio * 100 * 0.50 +
        (avg_newbie_score / 100) * sell_ratio * 30 * 0.30 +
        sell_intensity * 100 * 0.20
    )), 1)
    
    # 买卖比: >1 表示买入情绪占优, <1 表示恐慌卖出占优
    buy_sell_ratio = round(len(newbie_buy) / max(len(newbie_sell), 1), 1)
    
    return {
        "index": index,
        "interpretation": interpret_index(index),
        "details": {
            "total_posts": total,
            "valid_posts": len(valid_posts),
            "spam_posts": spam_count,
            "newbie_posts": newbie_count,
            "pure_newbie": len(pure_newbie),
            "newbie_ratio": round(newbie_ratio, 1),
            "avg_newbie_score": round(avg_newbie_score, 1),
            "avg_sentiment": round(avg_sentiment, 1),
            "purity_signal": round(purity_signal, 1),
            "activity": round(activity_signal, 1),
            # 买入/卖出子指数
            "mom_buy_index": mom_buy_index,
            "mom_sell_index": mom_sell_index,
            "buy_sell_ratio": buy_sell_ratio,
            "buy_count": len(newbie_buy),
            "sell_count": len(newbie_sell),
        },
        "top_newbie_posts": [
            {
                "title": r.title[:60],
                "score": r.newbie_score,
                "level": r.level,
                "reasoning": r.reasoning[:150],
                "sentiment": r.sentiment_score,
                "intent": r.intent,
                "intent_label": {"buy": "🟢 买入", "sell": "🔴 卖出", "neutral": "⚪ 观望"}.get(r.intent, ""),
                "key_signals": r.key_signals[:2],
            }
            for r in sorted(newbie_posts, key=lambda x: x.newbie_score, reverse=True)[:5]
        ],
    }


def interpret_index(index: float) -> str:
    if index >= 75:
        return "🔴 极度狂热 — 擦鞋童时刻！小白情绪爆表，历史级别的危险信号"
    elif index >= 60:
        return "🟠 高度警惕 — 小白大量涌入，市场情绪过热，建议大幅减仓"
    elif index >= 40:
        return "🟡 开始升温 — 小白活跃度明显上升，需保持关注"
    elif index >= 20:
        return "🟢 正常区间 — 小白参与度适中，无需特别操作"
    else:
        return "🔵 极度冷清 — 小白沉默不语，可能是市场底部信号"


def load_history() -> Dict:
    """加载历史数据"""
    history_file = os.path.join(DATA_DIR, "history.json")
    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"records": []}


def save_history(history: Dict):
    """保存历史数据"""
    history_file = os.path.join(DATA_DIR, "history.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_record(sector_indices: Dict[str, Dict], analysis_results: Dict):
    """添加一条历史记录"""
    history = load_history()
    
    record = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "sectors": sector_indices,
    }
    
    # 如果今天已有记录，更新而非新增
    today = record["date"]
    existing = [r for r in history["records"] if r["date"] == today]
    if existing:
        history["records"] = [r for r in history["records"] if r["date"] != today]
    
    history["records"].append(record)
    history["records"].sort(key=lambda r: r["date"])
    save_history(history)


def get_dashboard_data() -> Dict:
    """获取前端所需的完整数据"""
    history = load_history()
    records = history.get("records", [])
    
    # 最新一条
    latest = records[-1] if records else None
    
    # 为每个板块准备历史曲线数据
    sector_history = {
        "nasdaq": [],
        "gold": [],
        "cpo": [],
        "semiconductor": [],
    }
    
    for r in records:
        for sector, data in r.get("sectors", {}).items():
            if sector in sector_history:
                sector_history[sector].append({
                    "date": r["date"],
                    "index": data["index"],
                })
    
    return {
        "latest": latest,
        "sector_history": sector_history,
        "record_count": len(records),
        "data_notice": "脱敏合成演示数据，不对应真实用户、账户或生产策略。",
    }
