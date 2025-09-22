# -*- coding: utf-8 -*-
"""
Streamlit-приложение для аналитики ставок диспетчеров.

Функции:
- Загрузка CSV/TSV/XLSX.
- Автодетект разделителя.
- Перевод времени из UTC в America/New_York (NYC), добавление дат по NY.
- Подсчёт по каждому диспетчеру и по каждому водителю:
    * количество ставок;
    * средний профит (Dispatcher Price - Driver Price);
    * средняя цена водителя за милю (Driver Price / Total Miles);
- Сводка по каждому диспетчеру (общее количество ставок и др.).
- Фильтры по дате (NY), диспетчерам и минимальному числу ставок.
- Графики: количество ставок по диспетчерам, средний профит по диспетчерам,
  scatter по парам диспетчер-водитель (avg profit vs avg $/mile),
  таймсерия среднего профита по дням.
- Выгрузка агрегированных таблиц в CSV.

Как запустить:
    streamlit run app.py

Требуется: streamlit, pandas, numpy, altair
"""

import io
import sys
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

st.set_page_config(page_title="Dispatcher Bids Analytics", layout="wide")
st.title("📊 Статистика ставок диспетчеров")
st.caption("Время в источнике считается UTC. В отчёте все даты/время конвертируются в таймзону New York (America/New_York).")

# ----------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ----------------------------

REQUIRED_COLS = [
    "Created At",
    "Event At",
    "Dispatcher ID",
    "Dispatcher Name",  # email диспетчера
    "Unit",
    "Driver Name",
    "Total Miles",
    "Broker",
    "Driver Price",
    "Dispatcher Price",
    "User Dispatch ID",
]

DISPLAY_COL_RENAME = {
    "Created At": "created_at_utc",
    "Event At": "event_at_utc",
    "Dispatcher ID": "dispatcher_id",
    "Dispatcher Name": "dispatcher_name",  # email
    "Unit": "unit",
    "Driver Name": "driver_name",
    "Total Miles": "total_miles",
    "Broker": "broker",
    "Driver Price": "driver_price",
    "Dispatcher Price": "dispatcher_price",
    "User Dispatch ID": "user_dispatch_id",
}

NY_TZ = "America/New_York"

@st.cache_data(show_spinner=False)
def load_table(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        # Автодетект разделителя (кома/таб/точка с запятой)
        df = pd.read_csv(io.BytesIO(file_bytes), sep=None, engine="python")
    return df

@st.cache_data(show_spinner=False)
def preprocess(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()

    # Переименуем, приведём к базовым именам
    # Попробуем сделать case-insensitive сопоставление колонок
    cols_map = {}
    lower_map = {c.lower().strip(): c for c in df.columns}
    for k in REQUIRED_COLS:
        lk = k.lower()
        if lk in lower_map:
            cols_map[lower_map[lk]] = DISPLAY_COL_RENAME[k]
    df = df.rename(columns=cols_map)

    # Проверим обязательные
    missing = [DISPLAY_COL_RENAME[c] for c in REQUIRED_COLS if DISPLAY_COL_RENAME[c] not in df.columns]
    if missing:
        raise ValueError(f"В файле отсутствуют обязательные колонки: {missing}")

    # Числа
    for c in ["total_miles", "driver_price", "dispatcher_price"]:
        df[c] = (
            df[c]
            .astype(str)
            .str.replace("$", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip()
        )
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Время: считаем, что в исходнике UTC (как указал пользователь)
    # pandas to_datetime(..., utc=True) трактует naive как UTC и добавляет tzinfo
    for tcol_src, tcol_dst in [("created_at_utc", "created_at_ny"), ("event_at_utc", "event_at_ny")]:
        ts = pd.to_datetime(df[tcol_src], errors="coerce", utc=True)
        df[tcol_dst] = ts.dt.tz_convert(NY_TZ)

    # Дата по Нью-Йорку (для группировок/фильтров)
    df["date_ny"] = df["created_at_ny"].dt.date

    # Текстовые поля
    for c in ["dispatcher_name", "driver_name", "unit", "broker"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    # Метрики
    df["profit"] = df["dispatcher_price"] - df["driver_price"]
    df["driver_price_per_mile"] = np.where(
        (df["total_miles"].fillna(0) > 0), df["driver_price"] / df["total_miles"], np.nan
    )

    return df

@st.cache_data(show_spinner=False)
def aggregate_tables(df: pd.DataFrame, min_bids_pair: int = 1):
    # Сводка по паре диспетчер-водитель
    grp_cols = ["dispatcher_name", "driver_name"]
    agg_pair = (
        df.groupby(grp_cols)
        .agg(
            bids=("user_dispatch_id", "count"),
            avg_profit=("profit", "mean"),
            median_profit=("profit", "median"),
            total_profit=("profit", "sum"),
            avg_driver_ppm=("driver_price_per_mile", "mean"),
            avg_miles=("total_miles", "mean"),
            total_miles=("total_miles", "sum"),
            first_bid_ny=("created_at_ny", "min"),
            last_bid_ny=("created_at_ny", "max"),
        )
        .reset_index()
    )
    if min_bids_pair > 1:
        agg_pair = agg_pair.loc[agg_pair["bids"] >= min_bids_pair].copy()

    # Сводка по диспетчеру
    agg_disp = (
        df.groupby("dispatcher_name")
        .agg(
            total_bids=("user_dispatch_id", "count"),
            unique_drivers=("driver_name", "nunique"),
            avg_profit=("profit", "mean"),
            median_profit=("profit", "median"),
            total_profit=("profit", "sum"),
            avg_driver_ppm=("driver_price_per_mile", "mean"),
        )
        .reset_index()
        .sort_values(["total_bids", "total_profit"], ascending=[False, False])
    )

    # По дням (NY) — средний профит
    daily = (
        df.groupby(["date_ny", "dispatcher_name"])  # по датам и диспетчерам
        .agg(avg_profit=("profit", "mean"), bids=("user_dispatch_id", "count"))
        .reset_index()
    )

    return agg_pair, agg_disp, daily


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

# ----------------------------
# Сайдбар: загрузка и настройки
# ----------------------------
with st.sidebar:
    st.header("⚙️ Настройки и данные")
    up = st.file_uploader("Загрузите CSV/TSV/XLSX с логами", type=["csv", "tsv", "txt", "xlsx", "xls"])

    st.divider()
    st.subheader("Фильтры")
    min_bids_pair = st.number_input("Минимум ставок для пары диспетчер-водитель", min_value=1, max_value=100, value=1, step=1)

# ----------------------------
# Загрузка данных
# ----------------------------

if up is not None:
    df_raw = load_table(up.getvalue(), up.name)
else:
    st.info("Загрузите файл с данными для анализа.")
    df_raw = None

if df_raw is not None:
    with st.expander("Первые строки исходных данных"):
        st.dataframe(df_raw.head(50), use_container_width=True)

    # Предобработка
    try:
        df = preprocess(df_raw)
    except Exception as e:
        st.error(f"Ошибка предобработки: {e}")
        st.stop()

    # Фильтры по дате NY и диспетчерам
    min_date, max_date = df["date_ny"].min(), df["date_ny"].max()
    colf1, colf2 = st.columns(2)
    with colf1:
        date_range = st.date_input(
            "Диапазон дат (по Нью-Йорку)",
            value=(min_date, max_date) if pd.notna(min_date) and pd.notna(max_date) else None,
        )
    with colf2:
        dispatchers = sorted(df["dispatcher_name"].dropna().unique().tolist())
        selected_dispatchers = st.multiselect("Выберите диспетчеров", dispatchers, default=dispatchers)

    # Применим фильтры
    if date_range:
        start_d, end_d = date_range if isinstance(date_range, tuple) else (date_range, date_range)
        m = (df["date_ny"] >= start_d) & (df["date_ny"] <= end_d)
        df = df.loc[m].copy()
    if selected_dispatchers:
        df = df[df["dispatcher_name"].isin(selected_dispatchers)].copy()

    if df.empty:
        st.warning("После применения фильтров данных не осталось.")
        st.stop()

    # Агрегации
    agg_pair, agg_disp, daily = aggregate_tables(df, min_bids_pair=min_bids_pair)

    # ----------------------------
    # КЛЮЧЕВЫЕ СВОДКИ
    # ----------------------------
    st.subheader("Итоги по диспетчерам")
    st.dataframe(agg_disp, use_container_width=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Всего ставок (видимых)", int(df["user_dispatch_id"].count()))
    with c2:
        st.metric("Уникальных диспетчеров", int(df["dispatcher_name"].nunique()))
    with c3:
        st.metric("Уникальных водителей", int(df["driver_name"].nunique()))
    with c4:
        st.metric("Средний профит по всем", round(float(df["profit"].mean()), 2) if df["profit"].notna().any() else 0.0)

    # Выгрузка CSV
    st.download_button("⬇️ Скачать сводку по диспетчерам (CSV)", data=df_to_csv_bytes(agg_disp), file_name="dispatchers_summary.csv", mime="text/csv")

    st.subheader("Пары диспетчер-водитель")
    st.caption("Для каждого диспетчера показаны водители, число ставок, средний профит и средняя цена водителя за милю.")
    st.dataframe(agg_pair, use_container_width=True)
    st.download_button("⬇️ Скачать сводку по парам (CSV)", data=df_to_csv_bytes(agg_pair), file_name="dispatcher_driver_pairs.csv", mime="text/csv")

    with st.expander("Детализированный журнал с конвертированным временем (NY)"):
        cols_show = [
            "created_at_utc",
            "created_at_ny",
            "dispatcher_name",
            "unit",
            "driver_name",
            "total_miles",
            "driver_price",
            "dispatcher_price",
            "profit",
            "driver_price_per_mile",
            "user_dispatch_id",
            "broker",
        ]
        st.dataframe(df[cols_show], use_container_width=True)
        st.download_button(
            "⬇️ Скачать детализированный журнал (CSV)",
            data=df_to_csv_bytes(df[cols_show]),
            file_name="bids_detail_ny.csv",
            mime="text/csv",
        )

    # ----------------------------
    # ВИЗУАЛИЗАЦИИ
    # ----------------------------
    st.subheader("Визуализации")

    # 1) Кол-во ставок по диспетчерам
    chart_bids = (
        alt.Chart(agg_disp)
        .mark_bar()
        .encode(
            x=alt.X("dispatcher_name:N", sort="-y", title="Диспетчер"),
            y=alt.Y("total_bids:Q", title="Количество ставок"),
            tooltip=["dispatcher_name", "total_bids", "unique_drivers", "avg_profit", "total_profit"],
        )
        .properties(height=320)
    )
    st.altair_chart(chart_bids, use_container_width=True)

    # 2) Средний профит по диспетчерам
    chart_profit = (
        alt.Chart(agg_disp)
        .mark_bar()
        .encode(
            x=alt.X("dispatcher_name:N", sort="-y", title="Диспетчер"),
            y=alt.Y("avg_profit:Q", title="Средний профит"),
            tooltip=["dispatcher_name", "avg_profit", "median_profit", "total_profit", "total_bids"],
        )
        .properties(height=320)
    )
    st.altair_chart(chart_profit, use_container_width=True)

    # 3) Scatter по парам: avg $/mile vs avg profit, размер = кол-во ставок
    if not agg_pair.empty:
        chart_scatter = (
            alt.Chart(agg_pair)
            .mark_circle()
            .encode(
                x=alt.X("avg_driver_ppm:Q", title="Средняя цена водителя за милю ($/mile)"),
                y=alt.Y("avg_profit:Q", title="Средний профит"),
                size=alt.Size("bids:Q", title="Ставок"),
                color=alt.Color("dispatcher_name:N", title="Диспетчер"),
                tooltip=[
                    "dispatcher_name",
                    "driver_name",
                    "bids",
                    alt.Tooltip("avg_driver_ppm:Q", title="$ водителя/миля", format=".2f"),
                    alt.Tooltip("avg_profit:Q", title="Avg профит", format=".2f"),
                    alt.Tooltip("total_miles:Q", title="Всего миль", format=".0f"),
                ],
            )
            .properties(height=380)
        )
        st.altair_chart(chart_scatter, use_container_width=True)

    # 4) Таймсерия: средний профит по дням (NY), раскраска по диспетчерам
    if not daily.empty:
        daily_chart = (
            alt.Chart(daily)
            .mark_line(point=True)
            .encode(
                x=alt.X("date_ny:T", title="Дата (NY)"),
                y=alt.Y("avg_profit:Q", title="Средний профит"),
                color=alt.Color("dispatcher_name:N", title="Диспетчер"),
                tooltip=["date_ny:T", "dispatcher_name:N", alt.Tooltip("avg_profit:Q", format=".2f"), "bids:Q"],
            )
            .properties(height=340)
        )
        st.altair_chart(daily_chart, use_container_width=True)

    # ----------------------------
    # Доп. идеи метрик
    # ----------------------------
    with st.expander("Идеи и заметки"):
        st.markdown(
            """
            **Что ещё можно посчитать:**
            - *Профит на милю* (profit / total_miles) по парам и диспетчерам.
            - *Топ водителей* по устойчивому профиту (фильтр по минимуму ставок).
            - *Когортный анализ* по месяцам или брокерам (если потребуется).
            - *Аномалии* — выбросы по цене за милю или профиту.
            """
        )

else:
    st.stop()
