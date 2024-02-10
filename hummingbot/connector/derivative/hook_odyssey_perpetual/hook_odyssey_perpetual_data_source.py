import asyncio
import logging
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from hummingbot.connector.derivative.hook_odyssey_perpetual import hook_odyssey_perpetual_constants as CONSTANTS
from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_graphql_executor import (
    HookOdysseyPerpetualGrapQLExecutor,
)
from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_signing import (
    HookOdysseyPerpetualSigner,
    Order,
)
from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_utils import (
    DEFAULT_FEES,
    eth_to_wei,
    wei_to_eth,
)
from hummingbot.connector.derivative.position import Position, PositionSide
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.funding_info import FundingInfo
from hummingbot.core.data_type.in_flight_order import OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.trade_fee import TradeFeeBase
from hummingbot.core.event.event_listener import EventListener
from hummingbot.core.event.events import MarketEvent, OrderBookEvent
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.pubsub import PubSub
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange_py_base import ExchangePyBase


class HookOdysseyPerpetualDataSource:
    _logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(HummingbotLogger.logger_name_for_class(cls))
        return cls._logger

    def __init__(
        self,
        hook_odyssey_perpetual_eth_address: str,
        hook_odyssey_perpetual_private_key: str,
        hook_odyssey_api_key: str,
        connector: "ExchangePyBase",
        domain: Optional[str] = CONSTANTS.DOMAIN,
        trading_required: bool = True,
    ):
        self._connector = connector
        self._domain = domain
        self._trading_required = trading_required
        self._hook_odyssey_perpetual_eth_address = hook_odyssey_perpetual_eth_address
        self._graphql_executor = HookOdysseyPerpetualGrapQLExecutor(
            hook_odyssey_api_key=hook_odyssey_api_key, domain=self._domain
        )
        self._signer = HookOdysseyPerpetualSigner(private_key=hook_odyssey_perpetual_private_key, domain=self._domain)
        self._publisher = PubSub()
        self._events_listening_tasks = []
        self._assets_map: Dict[str, str] = {}

        # Data source state - used to provide subscription data at any time
        self._perpetual_pairs: Dict[str, Dict[str, Any]] = {}  # Mapping of trading pair to perpetual pair
        self._symbols: Dict[str, str] = {}  # Mapping of symbol to trading pair
        self._instrument_hashes: Dict[str, str] = {}  # Mapping of instrument hash to trading pair
        self._subaccounts: Dict[str, str] = {}  # Mapping of subaccount to trading pair
        self._index_prices: Dict[str, Decimal] = {}  # Mapping of trading pair to index price
        self._mark_prices: Dict[str, Decimal] = {}  # Mapping of trading pair to mark price
        self._subaccount_balances: Dict[str, Decimal] = {}  # Mapping of subaccount to balance
        self._subaccount_positions: Dict[str, Position] = {}  # Mapping of subaccount to position
        self._funding_info: Dict[str, FundingInfo] = {}  # Mapping of trading pair to funding info
        self._orderbook_snapshots: Dict[str, OrderBookMessage] = {}  # Mapping of trading pair to orderbook snapshot
        self._fees: Tuple[Decimal, Decimal] = (
            DEFAULT_FEES.maker_percent_fee_decimal,
            DEFAULT_FEES.taker_percent_fee_decimal,
        )

        self._initial_ticker_event = asyncio.Event()
        self._initial_statistics_event = asyncio.Event()
        self._initial_bbo_event = asyncio.Event()
        self._initial_orderbook_event = asyncio.Event()
        self._initial_subaccount_orders_event = asyncio.Event()
        self._initial_subaccount_balances_event = asyncio.Event()
        self._initial_subaccount_positions_event = asyncio.Event()

    async def start(self, trading_pairs: List[str]):
        if len(self._events_listening_tasks) > 0:
            raise AssertionError("Data source is already started and can't be started again")
        await self.get_supported_pairs()

        for trading_pair in trading_pairs:
            perpetual_pair = self.get_perpetual_pair_for_trading_pair(trading_pair)
            instrument_hash = perpetual_pair.get("instrumentHash", "")
            symbol = perpetual_pair.get("symbol", "")
            subaccount = perpetual_pair.get("subaccount", "")

            # Index price
            self._events_listening_tasks.append(
                asyncio.create_task(
                    self._graphql_executor.subscribe_ticker(
                        self._process_ticker_update,
                        symbol,
                    )
                )
            )
            # Statistics / Funding Info
            self._events_listening_tasks.append(
                asyncio.create_task(
                    self._graphql_executor.subscribe_statistics(
                        self._process_statistics_update,
                        symbol,
                    )
                )
            )
            # BBO - Top of book
            self._events_listening_tasks.append(
                asyncio.create_task(
                    self._graphql_executor.subscribe_bbo(
                        self._process_bbo_update,
                        symbol,
                    )
                )
            )
            # Orderbook
            self._events_listening_tasks.append(
                asyncio.create_task(
                    self._graphql_executor.subscribe_orderbook(
                        self._process_orderbook_update,
                        instrument_hash,
                    )
                )
            )

            if self._trading_required:
                # Private order updates
                self._events_listening_tasks.append(
                    asyncio.create_task(
                        self._graphql_executor.subscribe_subaccount_orders(
                            self._process_subaccount_orders_update,
                            subaccount,
                        )
                    )
                )

        if self._trading_required:
            # Private balances
            self._events_listening_tasks.append(
                asyncio.create_task(
                    self._graphql_executor.subscribe_subaccount_balances(
                        self._process_subaccount_balances,
                        self._hook_odyssey_perpetual_eth_address,
                    )
                )
            )
            # Private positions
            self._events_listening_tasks.append(
                asyncio.create_task(
                    self._graphql_executor.subscribe_subaccount_positions(
                        self._process_subaccount_positions,
                        self._hook_odyssey_perpetual_eth_address,
                    )
                )
            )

    async def stop(self):
        for task in self._events_listening_tasks:
            task.cancel()
        self._events_listening_tasks = []

    def is_started(self) -> bool:
        return len(self._events_listening_tasks) > 0

    def add_listener(self, event_tag, listener: EventListener):
        self._publisher.add_listener(event_tag=event_tag, listener=listener)

    def remove_listener(self, event_tag, listener: EventListener):
        self._publisher.remove_listener(event_tag=event_tag, listener=listener)

    async def exchange_status(self):
        resp = await self._graphql_executor.account_details()
        if "accountDetails" not in resp:
            return NetworkStatus.NOT_CONNECTED
        if "makerFeeBips" not in resp["accountDetails"]:
            return NetworkStatus.NOT_CONNECTED
        return NetworkStatus.CONNECTED

    def get_fees(self) -> Tuple[Decimal, Decimal]:
        return self._fees

    async def fetch_fees(self):
        resp = await self._graphql_executor.account_details()
        account_details = resp["accountDetails"]
        maker_fee = Decimal(account_details["makerFeeBips"]) / Decimal(10000)
        taker_fee = Decimal(account_details["takerFeeBips"]) / Decimal(10000)
        self._fees = (maker_fee, taker_fee)

    async def get_supported_pairs(self) -> List[Dict[str, Any]]:
        """Fetches and processes supported perpetual_pairs, updating the internal mapping."""
        resp = await self._graphql_executor.perpetual_pairs()
        perpetual_pairs = resp["perpetualPairs"]
        for perpetual_pair in perpetual_pairs:
            trading_pair = combine_to_hb_trading_pair(
                base=perpetual_pair["symbol"], quote=perpetual_pair["baseCurrency"]
            )
            self._perpetual_pairs[trading_pair] = perpetual_pair
            self._symbols[perpetual_pair["symbol"]] = trading_pair
            self._instrument_hashes[perpetual_pair["instrumentHash"]] = trading_pair
            self._subaccounts[perpetual_pair["subaccount"]] = trading_pair
        return perpetual_pairs

    def get_perpetual_pair_for_trading_pair(self, trading_pair: str) -> Optional[Dict[str, Any]]:
        """Retrieves perpetual pair details for a specific trading pair."""
        return self._perpetual_pairs.get(trading_pair, None)

    async def get_index_price(self, trading_pair: str) -> Decimal:
        # Wait for the trade subscription snapshot to come in
        await self._initial_ticker_event.wait()
        return self._index_prices.get(trading_pair, 0.0)

    async def get_mark_price(self, trading_pair: str) -> Decimal:
        # Wait for the bbo subscription snapshot to come in
        await self._initial_bbo_event.wait()
        return self._mark_prices.get(trading_pair, 0.0)

    async def get_funding_info(self, trading_pair: str) -> FundingInfo:
        # Wait for the funding info subscription snapshot to come in
        await self._initial_statistics_event.wait()
        if trading_pair in self._funding_info:
            return self._funding_info[trading_pair]
        else:
            return FundingInfo(
                trading_pair=trading_pair,
                index_price=Decimal(0),
                mark_price=Decimal(0),
                next_funding_utc_timestamp=int(time.time()),
                rate=Decimal(0),
            )

    async def get_order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        # Wait for the orderbook subscription snapshot to come in
        await self._initial_orderbook_event.wait()
        if trading_pair in self._orderbook_snapshots:
            return self._orderbook_snapshots[trading_pair]
        else:
            content = {
                "bids": [],
                "asks": [],
                "update_id": 0,
            }
            return OrderBookMessage(
                message_type=OrderBookMessageType.SNAPSHOT,
                content=content,
                timestamp=int(time.time()),
            )

    async def get_balances(self) -> Dict[str, Decimal]:
        # Wait for the subaccount balances subscription snapshot to come in
        await self._initial_subaccount_balances_event.wait()
        return self._subaccount_balances

    async def get_positions(self) -> Dict[str, Position]:
        # Wait for the subaccount positions subscription snapshot to come in
        await self._initial_subaccount_positions_event.wait()
        return self._subaccount_positions

    async def _process_ticker_update(self, event: Dict[str, Any], symbol: str):
        ticker_event = event["ticker"]

        if not self._initial_ticker_event.is_set():
            self._initial_ticker_event.set()

        if symbol not in self._symbols:
            return
        trading_pair = self._symbols[symbol]
        self._index_prices[trading_pair] = wei_to_eth(ticker_event["price"])
        return self._index_prices[trading_pair]

    async def _process_statistics_update(self, event: Dict[str, Any], symbol: str):
        statistics_event = event["statistics"]

        if statistics_event["eventType"] == "SNAPSHOT" and not self._initial_statistics_event.is_set():
            self._initial_statistics_event.set()

        if symbol not in self._symbols:
            return
        trading_pair = self._symbols[symbol]

        # Get index price
        index_price = await self.get_index_price(trading_pair)
        mark_price = await self.get_mark_price(trading_pair)
        self._funding_info[trading_pair] = FundingInfo(
            trading_pair=trading_pair,
            index_price=index_price,
            mark_price=mark_price,
            next_funding_utc_timestamp=int(statistics_event["nextFundingEpoch"]),
            rate=Decimal(statistics_event["fundingRateBips"]) / Decimal(10000),
        )

    async def _process_bbo_update(self, event: Dict[str, Any], symbol: str):
        bbo_event = event["bbo"]

        if bbo_event["eventType"] == "SNAPSHOT" and not self._initial_bbo_event.is_set():
            self._initial_bbo_event.set()

        if symbol not in self._symbols:
            return

        for instrument in bbo_event["instruments"]:
            instrument_hash = instrument["id"]
            trading_pair = self._instrument_hashes[instrument_hash]
            self._mark_prices[trading_pair] = wei_to_eth(instrument["markPrice"])

    async def _process_orderbook_update(self, event: Dict[str, Any], instrument_hash: str):
        if instrument_hash not in self._instrument_hashes:
            return
        trading_pair = self._instrument_hashes[instrument_hash]

        orderbook_event = event["orderbook"]
        message_type = OrderBookMessageType.DIFF
        if orderbook_event["eventType"] == "SNAPSHOT":
            message_type = OrderBookMessageType.SNAPSHOT

            if not self._initial_orderbook_event.is_set():
                self._initial_orderbook_event.set()

        bids = [
            [
                wei_to_eth(bl["price"]),
                wei_to_eth(bl["size"]),
            ]
            for bl in orderbook_event["bidLevels"]
        ]
        asks = [
            [
                wei_to_eth(al["price"]),
                wei_to_eth(al["size"]),
            ]
            for al in orderbook_event["askLevels"]
        ]

        order_book_message: OrderBookMessage = OrderBookMessage(
            message_type=message_type,
            content={
                "trading_pair": trading_pair,
                "update_id": orderbook_event["timestamp"],
                "bids": bids,
                "asks": asks,
            },
            timestamp=float(orderbook_event["timestamp"]),
        )

        self._apply_local_orderbook_update(order_book_message)

        self._publisher.trigger_event(
            event_tag=OrderBookEvent.OrderBookDataSourceUpdateEvent,
            message=order_book_message,
        )

    async def _process_subaccount_orders_update(self, event: Dict[str, Any], subaccount: str):
        orders_event = event["subaccountOrders"]

        if orders_event["eventType"] == "SNAPSHOT":
            if not self._initial_subaccount_orders_event.is_set():
                self._initial_subaccount_orders_event.set()
            return  # Ignore snapshots
        orders = orders_event["orders"]

        if subaccount not in self._subaccounts:
            return
        trading_pair = self._subaccounts[subaccount]

        for order in orders:
            trading_pair = trading_pair
            # Update order state
            order_state = CONSTANTS.ORDER_STATE[order["status"]]
            order_update = OrderUpdate(
                trading_pair=trading_pair,
                update_timestamp=int(time.time()),
                new_state=order_state,
                client_order_id=order["orderHash"],
                exchange_order_id=order["orderHash"],
            )
            self._publisher.trigger_event(event_tag=MarketEvent.OrderUpdate, message=order_update)

            # Update trade
            if order_state == "FILLED" or order_state == "PARTIALLY_FILLED":
                size = wei_to_eth(order["size"])
                remaining_size = wei_to_eth(order["remainingSize"])
                fill_amount = size - remaining_size
                fill_price = wei_to_eth(order["limitPrice"])
                trade_type = TradeType.BUY if order["direction"] == "BUY" else TradeType.SELL

                maker_fee, taker_fee = self.get_fees()
                fee_rate = maker_fee if order["orderType"] == "MARKET" else taker_fee
                fee = TradeFeeBase.new_perpetual_fee(trade_type=trade_type, percent=fee_rate)

                trade_update = TradeUpdate(
                    trade_id=f"{order['orderHash']}-{order['timestamp']}",
                    client_order_id=order["orderHash"],
                    exchange_order_id=order["orderHash"],
                    trading_pair=trading_pair,
                    fill_timestamp=self._time(),
                    fill_price=fill_price,
                    fill_base_amount=fill_amount,
                    fill_quote_amount=fill_price * fill_amount,
                    fee=fee,
                )
                self._publisher.trigger_event(event_tag=MarketEvent.TradeUpdate, message=trade_update)

    async def _process_subaccount_balances(self, event: Dict[str, Any], address: str):
        balances_event = event["subaccountBalances"]

        if balances_event["eventType"] == "SNAPSHOT" and not self._initial_subaccount_balances_event.is_set():
            self._initial_subaccount_balances_event.set()

        for balance in balances_event["balances"]:
            # Ignore primary account balances
            if balance["subaccountID"] != 0:
                self._subaccount_balances[balance["subaccount"]] = wei_to_eth(balance["balance"])

    async def _process_subaccount_positions(self, event: Dict[str, Any], address: str):
        positions_event = event["subaccountPositions"]

        if positions_event["eventType"] == "SNAPSHOT" and not self._initial_subaccount_positions_event.is_set():
            self._initial_subaccount_positions_event.set()

        for position in positions_event["positions"]:
            size = wei_to_eth(position["sizeHeld"])
            if position["isLong"]:
                side = PositionSide.LONG
            else:
                side = PositionSide.SHORT
                size = Decimal(-1) * size
            instrument_hash = position["instrument"]["id"]
            entry_price = wei_to_eth(position["averageCost"])

            if instrument_hash not in self._instrument_hashes:
                continue
            trading_pair = self._instrument_hashes[instrument_hash]
            mark_price = await self.get_mark_price(trading_pair)

            if side == PositionSide.LONG:
                unrealized_pnl = (mark_price - entry_price) * abs(size)
            else:
                unrealized_pnl = (entry_price - mark_price) * abs(size)

            if size == 0:
                self._subaccount_positions.pop(instrument_hash)
            else:
                self._subaccount_positions[instrument_hash] = Position(
                    trading_pair=trading_pair,
                    position_side=side,
                    unrealized_pnl=unrealized_pnl.normalize(),
                    entry_price=entry_price.normalize(),
                    amount=size.normalize(),
                    leverage=Decimal(1),
                )

    def order_hash(
        self,
        market_hash: str,
        instrument_hash: str,
        subaccount: str,
        amount: Decimal,
        price: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        nonce: int,
    ) -> str:
        amount = eth_to_wei(amount)
        price = eth_to_wei(price)
        trade_type = "BUY" if trade_type == TradeType.BUY else "SELL"
        order_type = "MARKET" if order_type == OrderType.MARKET else "LIMIT"
        order_input = {
            "marketHash": market_hash,
            "instrumentHash": instrument_hash,
            "subaccount": subaccount,
            "orderType": order_type,
            "direction": trade_type,
            "size": str(amount),
            "limitPrice": str(price),
            "timeInForce": "GTC",  # Good till cancelled
            "nonce": str(nonce),
        }

        order = Order(
            market=order_input["marketHash"],
            instrumentType=2,
            instrumentId=order_input["instrumentHash"],
            direction=0 if order_input["direction"] == "BUY" else 1,
            maker=int(order_input["subaccount"]),
            taker=0,  # Taker is not specified
            amount=int(order_input["size"]),
            limitPrice=int(order_input["limitPrice"]),
            expiration=0,  # Time in force is GTC
            nonce=nonce,
            counter=0,
            postOnly=False,
            reduceOnly=False,
            allOrNothing=False,
        )
        return self._signer.compute_order_hash(order)

    async def place_order(
        self,
        market_hash: str,
        instrument_hash: str,
        subaccount: str,
        amount: Decimal,
        price: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        nonce: int,
    ) -> Tuple[str, float]:
        amount = eth_to_wei(amount)
        price = eth_to_wei(price)
        trade_type = "BUY" if trade_type == TradeType.BUY else "SELL"
        order_type = "MARKET" if order_type == OrderType.MARKET else "LIMIT"
        order_input = {
            "marketHash": market_hash,
            "instrumentHash": instrument_hash,
            "subaccount": subaccount,
            "orderType": order_type,
            "direction": trade_type,
            "size": str(amount),
            "limitPrice": str(price),
            "timeInForce": "GTC",  # Good till cancelled
            "nonce": str(nonce),
        }

        order = Order(
            market=order_input["marketHash"],
            instrumentType=2,
            instrumentId=order_input["instrumentHash"],
            direction=0 if order_input["direction"] == "BUY" else 1,
            maker=int(order_input["subaccount"]),
            taker=0,  # Taker is not specified
            amount=int(order_input["size"]),
            limitPrice=int(order_input["limitPrice"]),
            expiration=0,  # Time in force is GTC
            nonce=nonce,
            counter=0,
            postOnly=False,
            reduceOnly=False,
            allOrNothing=False,
        )
        signature, order_hash = self._signer.sign_order(order)

        signature_input = {
            "signatureType": "DIRECT",
            "signature": signature,
        }
        success = await self._graphql_executor.place_order(order_input, signature_input)
        if not success:
            raise AssertionError("Failed to place order")
        return order_hash, int(time.time())

    async def cancel_order(self, order_id: str) -> bool:
        return await self._graphql_executor.cancel_order(order_id)

    def _apply_local_orderbook_update(self, order_book_message: OrderBookMessage):
        trading_pair = order_book_message.trading_pair
        if order_book_message.type == OrderBookMessageType.SNAPSHOT:
            self._orderbook_snapshots[trading_pair] = order_book_message
        else:
            # Apply diff to snapshot
            curr_snapshot = self._orderbook_snapshots.get(trading_pair)
            if "bids" in order_book_message.content:
                curr_snapshot.content["bids"] = order_book_message.content["bids"]
            if "asks" in order_book_message.content:
                curr_snapshot.content["asks"] = order_book_message.content["asks"]
