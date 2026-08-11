"""Free A-share market data adapter.

The professional analysis tools consume this normalized interface instead of
calling AKShare or a paid provider directly. Successful remote responses are
cached in MongoDB so a temporary upstream disconnect does not empty a report.
"""

from __future__ import annotations

import asyncio
from io import StringIO
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


INDEX_SYMBOLS = {
    "000001.SH": "sh000001",
    "399001.SZ": "sz399001",
    "399006.SZ": "sz399006",
    "000300.SH": "sh000300",
    "000905.SH": "sh000905",
    "000688.SH": "sh000688",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        text = str(value).replace("%", "").replace(",", "").strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def _first_column(df: pd.DataFrame, *names: str) -> Optional[str]:
    return next((name for name in names if name in df.columns), None)


class FreeChinaMarketData:
    """Normalized free-data interface for index and sector analysis."""

    cache_collection = "free_market_data_cache"

    def __init__(self, retries: int = 3, retry_delay: float = 0.6):
        self.retries = retries
        self.retry_delay = retry_delay
        self._memory: Dict[str, tuple[float, pd.DataFrame]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _ak():
        import akshare as ak

        return ak

    @staticmethod
    def _mongo_collection():
        try:
            from app.core.database import get_mongo_db_sync

            return get_mongo_db_sync()[FreeChinaMarketData.cache_collection]
        except Exception as exc:
            logger.debug("Free market MongoDB cache unavailable: %s", exc)
            return None

    def _read_persistent(self, key: str, max_age: Optional[int]) -> pd.DataFrame:
        collection = self._mongo_collection()
        if collection is None:
            return pd.DataFrame()
        try:
            doc = collection.find_one({"key": key})
            if not doc or not doc.get("payload"):
                return pd.DataFrame()
            updated_at = doc.get("updated_at")
            if max_age is not None and isinstance(updated_at, datetime):
                now = datetime.now(timezone.utc)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                if (now - updated_at).total_seconds() > max_age:
                    return pd.DataFrame()
            return pd.read_json(
                StringIO(doc["payload"]), orient="split", dtype=False, convert_dates=False
            )
        except Exception as exc:
            logger.debug("Read free market cache failed for %s: %s", key, exc)
            return pd.DataFrame()

    def _write_persistent(self, key: str, frame: pd.DataFrame, source: str) -> None:
        collection = self._mongo_collection()
        if collection is None or frame.empty:
            return
        try:
            collection.update_one(
                {"key": key},
                {
                    "$set": {
                        "payload": frame.to_json(
                            orient="split", date_format="iso", force_ascii=False
                        ),
                        "source": source,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
        except Exception as exc:
            logger.debug("Write free market cache failed for %s: %s", key, exc)

    def _fetch_frame(
        self,
        key: str,
        fetcher: Callable[[], pd.DataFrame],
        *,
        ttl: int,
        stale_ttl: int,
        source: str,
    ) -> pd.DataFrame:
        now = time.time()
        with self._lock:
            cached = self._memory.get(key)
            if cached and now - cached[0] <= ttl:
                return cached[1].copy()

        persisted = self._read_persistent(key, ttl)
        if not persisted.empty:
            with self._lock:
                self._memory[key] = (now, persisted.copy())
            return persisted

        last_error: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                frame = fetcher()
                if frame is not None and not frame.empty:
                    frame = frame.copy()
                    frame.attrs["data_source"] = source
                    with self._lock:
                        self._memory[key] = (time.time(), frame.copy())
                    self._write_persistent(key, frame, source)
                    return frame
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Free market source failed (%s, attempt %s/%s): %s",
                    key,
                    attempt + 1,
                    self.retries,
                    exc,
                )
            if attempt + 1 < self.retries:
                time.sleep(self.retry_delay * (attempt + 1))

        stale = self._read_persistent(key, stale_ttl)
        if not stale.empty:
            stale.attrs["stale"] = True
            logger.warning("Using stale free market cache for %s", key)
            return stale
        if last_error:
            logger.error("No free market data available for %s: %s", key, last_error)
        return pd.DataFrame()

    async def get_index_daily(
        self, ts_code: str, start_date: str, end_date: str, **_: Any
    ) -> pd.DataFrame:
        symbol = INDEX_SYMBOLS.get(ts_code, ts_code)
        key = f"index:{symbol}:{start_date}:{end_date}"

        def fetch() -> pd.DataFrame:
            ak = self._ak()
            try:
                raw = ak.stock_zh_index_daily_em(
                    symbol=symbol, start_date=start_date, end_date=end_date
                )
                if raw is None or raw.empty:
                    raise ValueError(f"empty index response for {symbol}")
                mapping = {
                    "date": "trade_date",
                    "open": "open",
                    "close": "close",
                    "high": "high",
                    "low": "low",
                    "volume": "vol",
                    "amount": "amount",
                }
            except Exception:
                try:
                    raw = ak.index_zh_a_hist(
                        symbol=ts_code.split(".")[0],
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if raw is None or raw.empty:
                        raise ValueError(f"empty fallback index response for {ts_code}")
                    mapping = {
                        "日期": "trade_date",
                        "开盘": "open",
                        "收盘": "close",
                        "最高": "high",
                        "最低": "low",
                        "成交量": "vol",
                        "成交额": "amount",
                        "涨跌幅": "pct_chg",
                    }
                except Exception:
                    return self._index_from_baostock(ts_code, start_date, end_date)
            frame = raw.rename(columns=mapping)
            keep = [column for column in mapping.values() if column in frame.columns]
            frame = frame[keep]
            frame["trade_date"] = (
                pd.to_datetime(frame["trade_date"]).dt.strftime("%Y%m%d")
            )
            for column in ("open", "close", "high", "low", "vol", "amount"):
                if column in frame:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if "pct_chg" not in frame and "close" in frame:
                frame["pct_chg"] = frame["close"].pct_change() * 100
            return frame.sort_values("trade_date")

        return await asyncio.to_thread(
            self._fetch_frame,
            key,
            fetch,
            ttl=900,
            stale_ttl=7 * 86400,
            source="akshare-index",
        )

    async def get_market_activity(self) -> Dict[str, Any]:
        frame = await asyncio.to_thread(
            self._fetch_frame,
            "market:activity",
            lambda: self._ak().stock_market_activity_legu(),
            ttl=300,
            stale_ttl=86400,
            source="akshare-legu",
        )
        if frame.empty:
            return {}
        values = {str(row["item"]): row["value"] for _, row in frame.iterrows()}
        return {
            "up_count": int(_number(values.get("上涨"))),
            "down_count": int(_number(values.get("下跌"))),
            "flat_count": int(_number(values.get("平盘"))),
            "limit_up_count": int(_number(values.get("真实涨停", values.get("涨停")))),
            "limit_down_count": int(_number(values.get("真实跌停", values.get("跌停")))),
            "suspended_count": int(_number(values.get("停牌"))),
            "activity_rate": _number(values.get("活跃度")),
            "data_time": str(values.get("统计日期", "")),
        }

    async def get_market_valuation(self) -> pd.DataFrame:
        def fetch() -> pd.DataFrame:
            raw = self._ak().stock_a_ttm_lyr().copy()
            raw["date"] = pd.to_datetime(raw["date"]).dt.strftime("%Y%m%d")
            return raw.rename(
                columns={
                    "date": "trade_date",
                    "middlePETTM": "pe_ttm_median",
                    "averagePETTM": "pe_ttm_mean",
                    "middlePELYR": "pe_lyr_median",
                    "averagePELYR": "pe_lyr_mean",
                }
            )

        return await asyncio.to_thread(
            self._fetch_frame,
            "market:valuation:a-share",
            fetch,
            ttl=6 * 3600,
            stale_ttl=14 * 86400,
            source="akshare-legu",
        )

    async def get_northbound_summary(self) -> pd.DataFrame:
        def fetch() -> pd.DataFrame:
            raw = self._ak().stock_hsgt_fund_flow_summary_em()
            if raw.empty:
                return raw
            north = raw[raw["资金方向"].astype(str) == "北向"].copy()
            return north.rename(
                columns={
                    "交易日": "trade_date",
                    "板块": "channel",
                    "交易状态": "status",
                    "相关指数": "related_index",
                    "指数涨跌幅": "index_pct_chg",
                }
            )

        return await asyncio.to_thread(
            self._fetch_frame,
            "market:northbound:summary",
            fetch,
            ttl=900,
            stale_ttl=3 * 86400,
            source="akshare-eastmoney",
        )

    async def get_margin_summary(self, trade_date: str, lookback_days: int) -> pd.DataFrame:
        end = datetime.strptime(trade_date.replace("-", ""), "%Y%m%d")
        start = end - timedelta(days=lookback_days + 8)
        start_text, end_text = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

        def fetch() -> pd.DataFrame:
            ak = self._ak()
            sh = ak.stock_margin_sse(start_date=start_text, end_date=end_text).copy()
            sh = sh.rename(
                columns={
                    "信用交易日期": "trade_date",
                    "融资余额": "financing_balance",
                    "融券余量金额": "securities_balance",
                    "融资融券余额": "margin_balance",
                }
            )
            rows = []
            for day in pd.date_range(start, end):
                try:
                    sz = ak.stock_margin_szse(date=day.strftime("%Y%m%d"))
                    if not sz.empty:
                        row = sz.iloc[0]
                        rows.append(
                            {
                                "trade_date": day.strftime("%Y%m%d"),
                                "financing_balance": _number(row.get("融资余额")) * 1e8,
                                "securities_balance": _number(row.get("融券余额")) * 1e8,
                                "margin_balance": _number(row.get("融资融券余额")) * 1e8,
                            }
                        )
                except Exception:
                    continue
            sz_frame = pd.DataFrame(rows)
            frames = [frame for frame in (sh, sz_frame) if not frame.empty]
            if not frames:
                return pd.DataFrame()
            combined = pd.concat(frames, ignore_index=True)
            for column in ("financing_balance", "securities_balance", "margin_balance"):
                combined[column] = pd.to_numeric(combined[column], errors="coerce")
            return (
                combined.groupby("trade_date", as_index=False)[
                    ["financing_balance", "securities_balance", "margin_balance"]
                ]
                .sum()
                .sort_values("trade_date")
            )

        return await asyncio.to_thread(
            self._fetch_frame,
            f"market:margin:{start_text}:{end_text}",
            fetch,
            ttl=6 * 3600,
            stale_ttl=14 * 86400,
            source="akshare-exchange",
        )

    async def get_limit_pools(self, trade_date: str) -> Dict[str, pd.DataFrame]:
        date_text = trade_date.replace("-", "")

        async def load(name: str, fetcher: Callable[[], pd.DataFrame]) -> pd.DataFrame:
            return await asyncio.to_thread(
                self._fetch_frame,
                f"market:limit:{name}:{date_text}",
                fetcher,
                ttl=1800,
                stale_ttl=7 * 86400,
                source="akshare-eastmoney",
            )

        up, down = await asyncio.gather(
            load("up", lambda: self._ak().stock_zt_pool_em(date=date_text)),
            load("down", lambda: self._ak().stock_zt_pool_dtgc_em(date=date_text)),
        )
        return {"limit_up": up, "limit_down": down}

    def _industry_from_database(self, ticker: str) -> Optional[str]:
        try:
            from app.core.database import get_mongo_db_sync

            doc = get_mongo_db_sync().stock_basic_info.find_one(
                {"$or": [{"code": ticker}, {"symbol": ticker}]},
                {"industry": 1},
            )
            industry = str((doc or {}).get("industry") or "").strip()
            return industry or None
        except Exception:
            return None

    @staticmethod
    def _industry_from_baostock(ticker: str) -> Optional[str]:
        try:
            import baostock as bs

            prefix = "sh" if ticker.startswith(("5", "6", "9")) else "sz"
            login = bs.login()
            if login.error_code != "0":
                return None
            try:
                result = bs.query_stock_industry(code=f"{prefix}.{ticker}")
                if result.error_code == "0" and result.next():
                    row = dict(zip(result.fields, result.get_row_data()))
                    return str(row.get("industry") or "").strip() or None
            finally:
                bs.logout()
        except Exception as exc:
            logger.warning("BaoStock industry fallback failed for %s: %s", ticker, exc)
        return None

    @staticmethod
    def _index_from_baostock(
        ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        import baostock as bs

        code, market = ts_code.split(".")
        bs_code = f"{'sh' if market == 'SH' else 'sz'}.{code}"
        login = bs.login()
        if login.error_code != "0":
            raise ConnectionError(f"BaoStock login failed: {login.error_msg}")
        try:
            result = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,preclose,volume,amount,pctChg",
                start_date=f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}",
                end_date=f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}",
                frequency="d",
                adjustflag="3",
            )
            if result.error_code != "0":
                raise RuntimeError(result.error_msg)
            rows = []
            while result.next():
                rows.append(result.get_row_data())
            frame = pd.DataFrame(rows, columns=result.fields)
            if frame.empty:
                return frame
            frame = frame.rename(
                columns={
                    "date": "trade_date",
                    "preclose": "pre_close",
                    "volume": "vol",
                    "pctChg": "pct_chg",
                }
            )
            frame["trade_date"] = frame["trade_date"].str.replace("-", "", regex=False)
            for column in ("open", "high", "low", "close", "pre_close", "vol", "amount", "pct_chg"):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            return frame
        finally:
            bs.logout()

    async def get_stock_industry(self, ticker: str) -> Optional[str]:
        code = ticker.split(".")[0].zfill(6)
        cached = await asyncio.to_thread(self._industry_from_database, code)
        if cached and not re.match(r"^[A-Z]\d+", cached):
            return cached

        def fetch() -> pd.DataFrame:
            ak = self._ak()
            industry = ""
            try:
                history = ak.stock_industry_change_cninfo(
                    symbol=code,
                    start_date="19900101",
                    end_date=datetime.now().strftime("%Y%m%d"),
                )
                if history is not None and not history.empty:
                    sw = history[
                        history["分类标准"].astype(str).str.contains("申银万国", na=False)
                    ]
                    candidates = sw if not sw.empty else history
                    if "变更日期" in candidates:
                        candidates = candidates.sort_values("变更日期")
                    latest = candidates.iloc[-1]
                    for field in ("行业次类", "行业大类", "行业中类", "行业门类"):
                        value = str(latest.get(field) or "").strip()
                        if value and value.lower() != "nan":
                            industry = value
                            break
            except Exception as exc:
                logger.warning("CNInfo industry lookup failed for %s: %s", code, exc)

            if not industry:
                raw = ak.stock_individual_info_em(symbol=code, timeout=15)
                values = {str(row["item"]): row["value"] for _, row in raw.iterrows()}
                industry = str(values.get("行业") or "").strip()
            return pd.DataFrame([{"ticker": code, "industry": industry}]) if industry else pd.DataFrame()

        frame = await asyncio.to_thread(
            self._fetch_frame,
            f"stock:industry:{code}",
            fetch,
            ttl=30 * 86400,
            stale_ttl=365 * 86400,
            source="akshare-eastmoney",
        )
        if not frame.empty:
            return str(frame.iloc[0].get("industry") or "").strip() or None
        return await asyncio.to_thread(self._industry_from_baostock, code)

    async def get_sector_daily(
        self, industry: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        def fetch() -> pd.DataFrame:
            ak = self._ak()
            try:
                raw = ak.stock_board_industry_hist_em(
                    symbol=industry,
                    start_date=start_date,
                    end_date=end_date,
                    period="日k",
                    adjust="",
                )
                if raw is None or raw.empty:
                    raise ValueError(f"empty Eastmoney sector response for {industry}")
            except Exception:
                raw = ak.stock_board_industry_index_ths(
                    symbol=industry, start_date=start_date, end_date=end_date
                )
            frame = raw.rename(
                columns={
                    "日期": "trade_date",
                    "开盘": "open",
                    "开盘价": "open",
                    "收盘": "close",
                    "收盘价": "close",
                    "最高": "high",
                    "最高价": "high",
                    "最低": "low",
                    "最低价": "low",
                    "成交量": "vol",
                    "成交额": "amount",
                    "涨跌幅": "pct_change",
                    "换手率": "turnover_rate",
                }
            )
            frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.strftime("%Y%m%d")
            if "pct_change" not in frame and "close" in frame:
                frame["pct_change"] = pd.to_numeric(frame["close"], errors="coerce").pct_change() * 100
            return frame

        return await asyncio.to_thread(
            self._fetch_frame,
            f"sector:daily:{industry}:{start_date}:{end_date}",
            fetch,
            ttl=1800,
            stale_ttl=14 * 86400,
            source="akshare-eastmoney",
        )

    async def get_sector_fund_flow(self, indicator: str = "今日") -> pd.DataFrame:
        def fetch() -> pd.DataFrame:
            ak = self._ak()
            try:
                summary = ak.stock_board_industry_summary_ths()
                if summary is not None and not summary.empty:
                    result = pd.DataFrame(
                        {
                            "name": summary["板块"].astype(str),
                            "net_amount": pd.to_numeric(summary["净流入"], errors="coerce") * 1e8,
                            "pct_change": pd.to_numeric(summary["涨跌幅"], errors="coerce"),
                            "data_date": datetime.now().strftime("%Y%m%d"),
                        }
                    )
                    turnover = pd.to_numeric(summary["总成交额"], errors="coerce")
                    result["net_amount_rate"] = (
                        pd.to_numeric(summary["净流入"], errors="coerce") / turnover * 100
                    )
                    return result
            except Exception as exc:
                logger.warning("THS sector summary failed, trying Eastmoney: %s", exc)

            raw = ak.stock_sector_fund_flow_rank(
                indicator=indicator, sector_type="行业资金流"
            )
            name_col = _first_column(raw, "名称", "行业", "板块名称")
            amount_col = _first_column(
                raw, "今日主力净流入-净额", "主力净流入-净额", "净额"
            )
            rate_col = _first_column(
                raw, "今日主力净流入-净占比", "主力净流入-净占比", "净占比"
            )
            change_col = _first_column(raw, "今日涨跌幅", "涨跌幅")
            result = pd.DataFrame()
            if name_col:
                result["name"] = raw[name_col].astype(str)
            if amount_col:
                result["net_amount"] = pd.to_numeric(raw[amount_col], errors="coerce")
            if rate_col:
                result["net_amount_rate"] = pd.to_numeric(raw[rate_col], errors="coerce")
            if change_col:
                result["pct_change"] = pd.to_numeric(raw[change_col], errors="coerce")
            return result

        return await asyncio.to_thread(
            self._fetch_frame,
            f"sector:flow:{indicator}",
            fetch,
            ttl=900,
            stale_ttl=3 * 86400,
            source="akshare-eastmoney",
        )

    async def get_sector_constituents(self, industry: str) -> pd.DataFrame:
        def fetch() -> pd.DataFrame:
            ak = self._ak()
            raw = ak.stock_board_industry_cons_em(symbol=industry)
            mapping = {
                "代码": "ts_code",
                "名称": "name",
                "最新价": "close",
                "涨跌幅": "pct_chg",
                "换手率": "turnover_rate",
                "市盈率-动态": "pe_ttm",
                "市净率": "pb",
                "总市值": "total_mv",
            }
            frame = raw.rename(columns=mapping)
            keep = [column for column in mapping.values() if column in frame.columns]
            frame = frame[keep].copy()
            if "ts_code" in frame:
                frame["ts_code"] = frame["ts_code"].astype(str).str.zfill(6)
            for column in ("close", "pct_chg", "turnover_rate", "pe_ttm", "pb", "total_mv"):
                if column in frame:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if "total_mv" not in frame:
                try:
                    snapshot = ak.stock_zh_a_spot_em()
                    if {"代码", "总市值"}.issubset(snapshot.columns):
                        market_caps = snapshot[["代码", "总市值"]].copy()
                        market_caps["ts_code"] = market_caps["代码"].astype(str).str.zfill(6)
                        market_caps["total_mv"] = pd.to_numeric(
                            market_caps["总市值"], errors="coerce"
                        )
                        frame = frame.merge(
                            market_caps[["ts_code", "total_mv"]],
                            on="ts_code",
                            how="left",
                        )
                except Exception as exc:
                    logger.warning("A-share market-cap enrichment failed: %s", exc)
            frame["data_date"] = datetime.now().strftime("%Y%m%d")
            return frame

        return await asyncio.to_thread(
            self._fetch_frame,
            f"sector:constituents:{industry}",
            fetch,
            ttl=1800,
            stale_ttl=14 * 86400,
            source="akshare-eastmoney",
        )


_instance: Optional[FreeChinaMarketData] = None


def get_free_china_market_data() -> FreeChinaMarketData:
    global _instance
    if _instance is None:
        _instance = FreeChinaMarketData()
    return _instance
