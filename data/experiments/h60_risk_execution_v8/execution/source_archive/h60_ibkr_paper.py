"""Opt-in IBKR PAPER adapter for H60Executor. No live mode and no login automation.

OrderRef namespace + nonzero clientId + exact configured DU account isolate
ownership. reqExecutions/completed orders have limited history; absent uncertain
orders remain blocked. This module has not been validated against a real paper
session merely because its offline contract tests pass.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import math
import re

from h60_execution import ExecutionBlocked, intent_prefix, number, utc
from ibkr_readonly import quiet_client_logs


class IBKRPaperAdapter:
    mode='paper'

    def __init__(self,config,expected_account,*,client=None):
        if (config.get('mode')!='paper' or not config.get('enable_paper_orders')
                or not config.get('paper_budget_isolated') or not re.fullmatch(r'DU\d+',expected_account or '')
                or not 0<number(config.get('budget',0))<=1000 or config.get('client_id',0)<=0
                or config.get('host') not in ('127.0.0.1','localhost')
                or config.get('currency')!='USD'):
            raise ExecutionBlocked('Explicit isolated PAPER-only configuration and exact DU identity required')
        self.config, self.account = config, expected_account
        self.prefix=intent_prefix(config['strategy_id'])
        self.contracts={}; self.details={}; self.quote_cache={}; self.references={}
        self.confirmed=False
        if client is None:
            try:
                asyncio.get_event_loop()
            except RuntimeError:
                asyncio.set_event_loop(asyncio.new_event_loop())
            from ib_async import IB
            client=IB()
        self.ib=client
        self.ib.RequestTimeout=6

    def connect(self):
        with quiet_client_logs():
            self.ib.connect(self.config['host'],self.config['port'],clientId=self.config['client_id'],
                            timeout=6,readonly=False,raiseSyncErrors=True)
        self._identity()
        return True

    def _identity(self):
        if (not self.ib.isConnected() or not self.ib.client.isReady()
                or self.ib.managedAccounts()!=[self.account] or not self.account.startswith('DU')):
            self.confirmed=False
            raise ExecutionBlocked('PAPER identity handshake missing/changed/mixed; no order calls allowed')
        self.confirmed=True

    def _contract(self,symbol):
        if symbol not in self.config['symbols']:
            raise ExecutionBlocked('Unknown strategy instrument')
        if symbol not in self.contracts:
            from ib_async import Stock
            qualified=self.ib.qualifyContracts(Stock(symbol,'SMART','USD'))
            if len(qualified)!=1 or not qualified[0].conId:
                raise ExecutionBlocked('Ambiguous stock contract')
            details=self.ib.reqContractDetails(qualified[0])
            if len(details)!=1:
                raise ExecutionBlocked('Contract/quantity precision not confirmed')
            d=details[0]
            increment=number(d.sizeIncrement)
            if not 0<number(d.minSize)<=1 or increment<=0 or Decimal(1)%increment!=0 or not 0<number(d.minTick):
                raise ExecutionBlocked('Whole-share lot/price increment not supported or unavailable')
            self.contracts[symbol],self.details[symbol]=qualified[0],d
        return self.contracts[symbol]

    def quotes(self,symbols,now):
        self._identity()
        if self.config.get('corporate_actions_checked_through') != utc(now).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat():
            raise ExecutionBlocked('Corporate action boundary not checked for this session')
        contracts=[self._contract(s) for s in symbols]
        tickers=self.ib.reqTickers(*contracts)
        output={}
        for s,ticker in zip(symbols,tickers):
            detail=self.details[s]
            regular=any(session.start<=utc(now)<=session.end for session in detail.liquidSessions())
            if (ticker.marketDataType!=1 or ticker.time is None or not regular
                    or not all(math.isfinite(v) and v>0 for v in (ticker.bid,ticker.ask)) or ticker.bid>ticker.ask):
                raise ExecutionBlocked('Realtime bid/ask permissions or regular-session quote unavailable')
            if not 0<=(utc(now)-utc(ticker.time)).total_seconds()<=30:
                raise ExecutionBlocked('Received quote is stale')
            output[s]=dict(bid=str(ticker.bid),ask=str(ticker.ask),asof=utc(ticker.time).isoformat(),
                basis='broker_unadjusted_quote',regular_session=regular,quantity_step_confirmed=True,
                corporate_action_pending=False,con_id=ticker.contract.conId,
                timestamp_basis='API quote receipt; not an exchange execution timestamp')
        self.quote_cache.update(output)
        return output

    def snapshot(self,now):
        self._identity()
        with quiet_client_logs():
            opened=self.ib.reqAllOpenOrders()
            completed=self.ib.reqCompletedOrders(apiOnly=False)
            from ib_async import ExecutionFilter
            fills=self.ib.reqExecutions(ExecutionFilter(acctCode=self.account,clientId=self.config['client_id']))
            positions=self.ib.reqPositions()
            self.ib._run(self.ib.reqAccountSummaryAsync())  # Explicit fresh response, not cached-only access.
            summary=self.ib.accountSummary(self.account)
        self._identity()
        cash_tags={v.tag:v.value for v in summary if v.account==self.account and v.currency=='USD'}
        if not {'TotalCashValue','SettledCash','AvailableFunds'}.issubset(cash_tags):
            raise ExecutionBlocked('Explicit USD cash/settled cash/available funds snapshot missing')
        rows={}; refs={}
        for trade in [*completed,*opened]:
            order=trade.order
            if order.account!=self.account or not order.orderRef.startswith(self.prefix):
                continue
            if order.clientId!=self.config['client_id'] or order.action not in ('BUY','SELL') or not order.permId:
                raise ExecutionBlocked('Owned order identity not fully acknowledged')
            key=order.orderRef
            if key in rows and refs[key].order.permId!=order.permId:
                raise ExecutionBlocked('Multiple broker orders for one intent')
            if key in rows and rows[key]['status'] in ('Filled','Cancelled','ApiCancelled') and trade in opened:
                raise ExecutionBlocked('Open/terminal broker snapshot conflict')
            rows[key]=dict(strategy_id=self.config['strategy_id'],symbol=trade.contract.symbol,side=order.action,
                quantity=str(order.totalQuantity),reference='ibkr-perm:'+str(order.permId),status=trade.orderStatus.status,
                filled=str(trade.orderStatus.filled),fills=[])
            refs[key]=trade
        commissions={}
        for fill in fills:
            execution=fill.execution
            if execution.acctNumber!=self.account or execution.clientId!=self.config['client_id'] or not execution.orderRef.startswith(self.prefix):
                continue
            if execution.orderRef not in rows:
                raise ExecutionBlocked('Owned execution lacks available order identity/history')
            row=rows[execution.orderRef]
            if ('ibkr-perm:'+str(execution.permId)!=row['reference'] or fill.contract.symbol!=row['symbol']
                    or execution.side!=('BOT' if row['side']=='BUY' else 'SLD')):
                raise ExecutionBlocked('Execution identity disagrees with order')
            row['fills'].append(dict(id=execution.execId,quantity=str(execution.shares),price=str(execution.price)))
            report=fill.commissionReport
            if report.execId==execution.execId and math.isfinite(report.commission) and report.commission>=0 and report.currency=='USD':
                commissions[execution.execId]=dict(fee=str(report.commission),currency='USD')
        self.references=refs
        current_date=utc(now).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()
        return dict(asof=utc(now).isoformat(),snapshot_completed_at=datetime.now(timezone.utc).isoformat(),identity_confirmed=True,complete=True,
            corporate_actions_pending=self.config.get('corporate_actions_checked_through')!=current_date,
            cash=str(cash_tags['TotalCashValue']),available_cash=str(min(number(cash_tags[k]) for k in ('TotalCashValue','SettledCash','AvailableFunds'))),
            positions={p.contract.symbol:str(p.position) for p in positions if p.account==self.account},
            orders=rows,commissions=commissions,
            history_boundary='Only API-accessible execution/completed-order history; missing uncertain intents remain blocked')

    def submit(self,payload,now):
        self._identity()
        if (not payload['key'].startswith(self.prefix) or payload['strategy_id']!=self.config['strategy_id']
                or payload['side'] not in ('BUY','SELL') or payload['kind'] not in ('LMT','STP')
                or number(payload['quantity'])<=0 or number(payload['quantity'])%1!=0):
            raise ExecutionBlocked('Paper order identity/type/quantity invalid')
        contract=self._contract(payload['symbol'])
        q=self.quote_cache.get(payload['symbol'])
        if not q or not 0<=(utc(now)-utc(q['asof'])).total_seconds()<=30:
            raise ExecutionBlocked('Paper submit requires fresh unadjusted quote')
        if payload['side']=='BUY' and number(payload['quantity'])*number(q['ask'])>number(self.config.get('max_order_notional','250')):
            raise ExecutionBlocked('Small paper order notional cap exceeded')
        from ib_async import LimitOrder, StopOrder
        tick=number(self.details[payload['symbol']].minTick)
        if payload['kind']=='STP':
            if payload['side']!='SELL':
                raise ExecutionBlocked('Only long protective sell stops supported')
            price=(number(payload['stop_price'])/tick).to_integral_value(rounding=ROUND_DOWN)*tick
            order=StopOrder('SELL',float(payload['quantity']),float(price),tif='GTC')
        else:
            rounding=ROUND_DOWN if payload['side']=='BUY' else ROUND_UP
            price=(number(payload['limit_price'])/tick).to_integral_value(rounding=rounding)*tick
            order=LimitOrder(payload['side'],float(payload['quantity']),float(price),tif='DAY')
        order.account=self.account; order.orderRef=payload['key']; order.outsideRth=False
        with quiet_client_logs():
            trade=self.ib.placeOrder(contract,order)
            self.ib.sleep(.2)
        self.references[payload['key']]=trade
        if not trade.order.permId:
            raise TimeoutError('Order sent; durable intent requires reconciliation before any further action')
        return 'ibkr-perm:'+str(trade.order.permId)

    def cancel(self,key,now):
        self._identity()
        if key not in self.references or not key.startswith(self.prefix):
            raise ExecutionBlocked('Cancellation requires an owned order from broker reconciliation')
        trade=self.references[key]
        if trade.order.account!=self.account or trade.order.clientId!=self.config['client_id']:
            raise ExecutionBlocked('Refusing to touch another account/client order')
        with quiet_client_logs():
            self.ib.cancelOrder(trade.order)

    def close(self):
        self.ib.disconnect()
