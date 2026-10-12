"""대시보드용 추가 통계 - 주문·회원 표(DataFrame)만으로 계산해서 더미/서버 어느 쪽이든 똑같이 동작한다."""
from datetime import timedelta

import pandas as pd

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
GRADE_ORDER = ["신규", "재방문", "단골", "휴면"]
WINDOW_DAYS = 30


def recent_orders(orders: pd.DataFrame, days: int = WINDOW_DAYS) -> pd.DataFrame:
    """가장 최근 주문일 기준 최근 N일 주문 (오늘 주문이 없어도 화면이 비지 않게 최신 주문일을 기준으로 한다)."""
    if orders.empty:
        return orders
    last = orders["주문 시각"].max().normalize()
    return orders[orders["주문 시각"] >= last - timedelta(days=days - 1)]


def summarize(orders: pd.DataFrame, members: pd.DataFrame, tables: int | None = None) -> dict:
    df = recent_orders(orders)
    if df.empty:
        return {"empty": True}
    days = df["주문 시각"].dt.normalize().nunique()
    revenue = int(df["금액"].sum())
    hourly = df.groupby(df["주문 시각"].dt.hour)["금액"].sum()
    by_hour = {f"{h:02d}시": int(hourly.get(h, 0)) for h in range(int(hourly.index.min()), int(hourly.index.max()) + 1)}
    weekday = df.groupby(df["주문 시각"].dt.dayofweek)["금액"].sum()
    by_weekday = {WEEKDAYS[i]: int(weekday.get(i, 0)) for i in range(7)}
    per_table = df.groupby("테이블").size()
    used_tables = tables or int(per_table.size)
    last_day = df["주문 시각"].max().normalize()
    today_df = df[df["주문 시각"] >= last_day]
    grade = members.set_index("customer_id")["등급"] if not members.empty else pd.Series(dtype=str)
    buyers = df["customer_id"].dropna().unique()
    grades = pd.Series([grade.get(int(c)) for c in buyers if int(c) in grade.index]).value_counts()
    ai = df[df["AI 추천 사용"]]
    plain = df[~df["AI 추천 사용"]]
    return {
        "empty": False,
        "days": days,
        "revenue": revenue,
        "daily_revenue": revenue // days,
        "avg_ticket": revenue // len(df),
        "orders": len(df),
        "by_hour": by_hour,
        "peak_hour": max(by_hour, key=by_hour.get),
        "by_weekday": by_weekday,
        "peak_weekday": max(by_weekday, key=by_weekday.get),
        "turnover_today": round(len(today_df) / used_tables, 1),
        "turnover_avg": round(len(df) / days / used_tables, 1),
        "tables": used_tables,
        "top_tables": {f"{int(t)}번": int(n) for t, n in per_table.sort_values(ascending=False).head(5).items()},
        "customer_grades": {g: int(grades.get(g, 0)) for g in GRADE_ORDER},
        "returning_share": (sum(int(grades.get(g, 0)) for g in ("재방문", "단골")) / grades.sum()) if grades.sum() else None,
        "ai_avg_ticket": int(ai["금액"].mean()) if len(ai) else None,
        "plain_avg_ticket": int(plain["금액"].mean()) if len(plain) else None,
        "ai_share": len(ai) / len(df),
    }
