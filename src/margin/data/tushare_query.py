"""Bounded Tushare query plans for the quant-required endpoint closure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

QueryMode = Literal[
    "snapshot",
    "calendar_range",
    "date_slice",
    "period_slice",
    "symbol_range",
    "symbol_batch",
    "industry_members",
    "index_range",
]


@dataclass(frozen=True)
class TushareQuerySpec:
    """One field-bounded API plan and its scalable All-A query mode.."""

    api_name: str
    query_mode: QueryMode
    fields: tuple[str, ...]

    @property
    def fields_csv(self) -> str:
        """Return SDK-compatible field selection.

        Returns:
            str: .
        """
        return ",".join(self.fields)


class TushareQueryCatalog:
    """Registry of Tushare calls admitted by active quant requirements.."""

    def __init__(self, specs: tuple[TushareQuerySpec, ...]) -> None:
        """Initialize a unique API-name registry.

        Args:
            specs: tuple[TushareQuerySpec, ...]: .

        Returns:
            None: .
        """
        self._specs = {spec.api_name: spec for spec in specs}
        if len(self._specs) != len(specs):
            raise ValueError("duplicate Tushare query spec")

    def get(self, api_name: str) -> TushareQuerySpec:
        """Return one query specification.

        Args:
            api_name: str: .

        Returns:
            TushareQuerySpec: .
        """
        return self._specs[api_name.strip().lower()]

    def api_names(self) -> tuple[str, ...]:
        """Return stable API names.

        Returns:
            tuple[str, ...]: .
        """
        return tuple(sorted(self._specs))

    def probe_params(
        self,
        api_name: str,
        *,
        as_of: datetime,
        sample_symbol: str,
        industry_code: str = "801010.SI",
    ) -> dict[str, Any]:
        """Build a minimal real-seat probe request.

        Args:
            api_name: str: .
            as_of: datetime: .
            sample_symbol: str: .
            industry_code: str: .

        Returns:
            dict[str, Any]: .
        """
        spec = self.get(api_name)
        end = as_of.strftime("%Y%m%d")
        start = (as_of - timedelta(days=45)).strftime("%Y%m%d")
        params: dict[str, Any] = {"fields": spec.fields_csv, "limit": 20}
        if api_name == "stock_basic":
            params.update(exchange="", list_status="L")
        elif api_name == "namechange":
            params.update(ts_code=sample_symbol)
        elif api_name == "trade_cal":
            params.update(exchange="SSE", start_date=start, end_date=end)
        elif api_name in {
            "daily",
            "adj_factor",
            "daily_basic",
            "index_daily",
            "moneyflow",
            "margin_detail",
            "limit_list_d",
        }:
            params.update(
                ts_code="000300.SH" if api_name == "index_daily" else sample_symbol,
                start_date=start,
                end_date=end,
            )
        elif api_name == "suspend_d":
            params.update(start_date=start, end_date=end)
        elif api_name in {
            "income",
            "balancesheet",
            "cashflow",
            "fina_indicator",
            "fina_audit",
            "pledge_stat",
            "forecast",
            "express",
        }:
            params.update(ts_code=sample_symbol)
        elif api_name == "index_classify":
            params.update(level="L1", src="SW2021")
        elif api_name == "index_member":
            params.update(index_code=industry_code)
        elif api_name == "index_weight":
            params.update(
                index_code="000300.SH",
                start_date=(as_of - timedelta(days=400)).strftime("%Y%m%d"),
                end_date=end,
            )
        return params

    @classmethod
    def default(cls) -> TushareQueryCatalog:
        """Build the v0.3 quant-only Tushare field and query catalog.

        Returns:
            TushareQueryCatalog: .
        """
        return cls(
            (
                _spec(
                    "stock_basic",
                    "snapshot",
                    "ts_code,symbol,name,industry,market,exchange,list_status,"
                    "list_date,delist_date",
                ),
                _spec(
                    "namechange",
                    "symbol_range",
                    "ts_code,name,start_date,end_date,ann_date,change_reason",
                ),
                _spec(
                    "trade_cal",
                    "calendar_range",
                    "exchange,cal_date,is_open,pretrade_date",
                ),
                _spec(
                    "daily",
                    "date_slice",
                    "ts_code,trade_date,close,amount",
                ),
                _spec("adj_factor", "date_slice", "ts_code,trade_date,adj_factor"),
                _spec(
                    "suspend_d",
                    "date_slice",
                    "ts_code,trade_date,suspend_timing,suspend_type",
                ),
                _spec(
                    "daily_basic",
                    "date_slice",
                    "ts_code,trade_date,turnover_rate,volume_ratio,pe_ttm,pb,"
                    "ps_ttm,dv_ttm,total_mv,circ_mv,float_share,free_share",
                ),
                _spec(
                    "moneyflow",
                    "date_slice",
                    "ts_code,trade_date,buy_lg_amount,sell_lg_amount,"
                    "buy_elg_amount,sell_elg_amount,net_mf_amount",
                ),
                _spec(
                    "margin_detail",
                    "date_slice",
                    "trade_date,ts_code,rzye,rqye,rzmre,rqyl,rzche,rqmcl,rzrqye",
                ),
                _spec(
                    "income",
                    "symbol_batch",
                    "ts_code,ann_date,f_ann_date,end_date,report_type,basic_eps,"
                    "diluted_eps,total_revenue,revenue,operate_profit,total_profit,"
                    "n_income,n_income_attr_p,ebit,ebitda,update_flag",
                ),
                _spec(
                    "balancesheet",
                    "symbol_batch",
                    "ts_code,ann_date,f_ann_date,end_date,report_type,total_assets,"
                    "total_liab,total_hldr_eqy_exc_min_int,total_cur_assets,"
                    "total_cur_liab,accounts_receiv,inventories,goodwill,money_cap,"
                    "update_flag",
                ),
                _spec(
                    "cashflow",
                    "symbol_batch",
                    "ts_code,ann_date,f_ann_date,end_date,report_type,n_cashflow_act,"
                    "n_cashflow_inv_act,n_cash_flows_fnc_act,c_pay_acq_const_fiolta,"
                    "free_cashflow,update_flag",
                ),
                _spec(
                    "fina_indicator",
                    "symbol_batch",
                    "ts_code,ann_date,end_date,eps,dt_eps,roe,roe_waa,roic,"
                    "grossprofit_margin,netprofit_margin,debt_to_assets,"
                    "current_ratio,quick_ratio,assets_turn,inv_turn,ar_turn,"
                    "ocf_to_or,ocf_to_opincome,ebit_to_interest,tr_yoy,or_yoy,"
                    "netprofit_yoy,dt_netprofit_yoy,update_flag",
                ),
                _spec(
                    "fina_audit",
                    "symbol_batch",
                    "ts_code,ann_date,end_date,audit_result,audit_fees,audit_agency,audit_sign",
                ),
                _spec(
                    "forecast",
                    "symbol_batch",
                    "ts_code,ann_date,end_date,type,p_change_min,p_change_max,"
                    "net_profit_min,net_profit_max,last_parent_net_profit,"
                    "first_ann_date,summary,change_reason",
                ),
                _spec(
                    "express",
                    "symbol_batch",
                    "ts_code,ann_date,end_date,revenue,operate_profit,total_profit,"
                    "n_income,total_assets,total_hldr_eqy_exc_min_int,diluted_eps,"
                    "diluted_roe,yoy_net_profit,bps,yoy_sales,yoy_op,yoy_tp,"
                    "yoy_dedu_np,yoy_eps,yoy_roe",
                ),
                _spec(
                    "index_classify",
                    "snapshot",
                    "index_code,industry_name,level,industry_code,is_pub,parent_code,src",
                ),
                _spec(
                    "index_member",
                    "industry_members",
                    "index_code,index_name,con_code,con_name,in_date,out_date,is_new",
                ),
                _spec(
                    "pledge_stat",
                    "symbol_batch",
                    "ts_code,end_date,pledge_count,unrest_pledge,rest_pledge,"
                    "total_share,pledge_ratio",
                ),
                _spec(
                    "index_daily",
                    "index_range",
                    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
                ),
                _spec(
                    "index_weight",
                    "index_range",
                    "index_code,con_code,trade_date,weight",
                ),
                _spec(
                    "limit_list_d",
                    "date_slice",
                    "trade_date,ts_code,name,close,pct_chg,amp,fc_ratio,fl_ratio,"
                    "fd_amount,first_time,last_time,open_times,strth,limit",
                ),
            )
        )


def _spec(api_name: str, query_mode: QueryMode, fields: str) -> TushareQuerySpec:
    """Build a query spec from a comma-separated field list.

    Args:
        api_name: str: .
        query_mode: QueryMode: .
        fields: str: .

    Returns:
        TushareQuerySpec: .
    """
    return TushareQuerySpec(
        api_name=api_name,
        query_mode=query_mode,
        fields=tuple(field.strip() for field in fields.split(",") if field.strip()),
    )
