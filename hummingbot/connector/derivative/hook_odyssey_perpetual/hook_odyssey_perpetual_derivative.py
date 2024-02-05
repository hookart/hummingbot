import asyncio
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from _decimal import Decimal
from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.derivative.hook_odyssey_perpetual import hook_odyssey_perpetual_constants as CONSTANTS
from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_api_order_book_data_source import (
    HookOdysseyPerpetualAPIOrderBookDataSource,
)
from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_data_source import (
    HookOdysseyPerpetualDataSource,
)
from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_utils import (
    get_tracking_nonce,
    wei_to_eth,
)
from hummingbot.connector.perpetual_derivative_py_base import PerpetualDerivativePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.api_throttler.data_types import RateLimit
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionMode, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import AddedToCostTradeFee, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.event.event_forwarder import EventForwarder
from hummingbot.core.event.events import AccountEvent, BalanceUpdateEvent, MarketEvent
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.utils.async_utils import safe_ensure_future, safe_gather
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter


class HookOdysseyPerpetualDerivative(PerpetualDerivativePyBase):
    def __init__(
        self,
        client_config_map: "ClientConfigAdapter",
        hook_odyssey_perpetual_eth_address: str,
        hook_odyssey_perpetual_private_key: str,
        hook_odyssey_api_key: str,
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
        domain: str = CONSTANTS.DOMAIN,
    ):
        self.hook_odyssey_perpetual_eth_address = hook_odyssey_perpetual_eth_address
        self.hook_odyssey_perpetual_private_key = hook_odyssey_perpetual_private_key
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._domain = domain
        self._data_source = HookOdysseyPerpetualDataSource(
            hook_odyssey_perpetual_eth_address=hook_odyssey_perpetual_eth_address,
            hook_odyssey_perpetual_private_key=hook_odyssey_perpetual_private_key,
            hook_odyssey_api_key=hook_odyssey_api_key,
            connector=self,
            domain=self.domain,
            trading_required=self._trading_required,
        )
        super().__init__(client_config_map)
        self._forwarders = []
        self._configure_event_forwarders()

    @property
    def name(self) -> str:
        return self._domain

    @property
    def authenticator(self) -> AuthBase:
        return None

    @property
    def rate_limits_rules(self) -> List[RateLimit]:
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def client_order_id_max_length(self) -> int:
        return None

    @property
    def client_order_id_prefix(self) -> str:
        return CONSTANTS.BROKER_ID

    @property
    def trading_rules_request_path(self) -> str:
        raise NotImplementedError

    @property
    def trading_pairs_request_path(self) -> str:
        raise NotImplementedError

    @property
    def check_network_request_path(self) -> str:
        raise NotImplementedError

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return False

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    @property
    def funding_fee_poll_interval(self) -> int:
        return 60

    @property
    def status_dict(self) -> Dict[str, bool]:
        return {
            "symbols_mapping_initialized": self.trading_pair_symbol_map_ready(),
            "order_books_initialized": self.order_book_tracker.ready,
            "account_balance": not self.is_trading_required or len(self._account_balances) > 0,
            "trading_rule_initialized": len(self._trading_rules) > 0 if self.is_trading_required else True,
        }

    async def start_network(self):
        await super().start_network()
        await self._data_source.start(self._trading_pairs)
        await self._initialize_trading_pair_symbol_map()
        await self._update_trading_rules()
        # self._ready = True  # Mark connector as ready

    async def stop_network(self):
        """
        This function is executed when the connector is stopped. It performs a general cleanup and stops all background
        tasks that require the connection with the exchange to work.
        """
        await super().stop_network()
        await self._data_source.stop()

    async def check_network(self) -> NetworkStatus:
        """
        Checks connectivity with the exchange using the API
        """
        try:
            status = await self._data_source.exchange_status()
        except asyncio.CancelledError:
            raise
        except Exception:
            status = NetworkStatus.NOT_CONNECTED
        return status

    def supported_order_types(self) -> List[OrderType]:
        """
        :return a list of OrderType supported by this connector
        """
        return [OrderType.LIMIT, OrderType.MARKET]

    def supported_position_modes(self):
        """
        This method needs to be overridden to provide the accurate information depending on the exchange.
        """
        return [PositionMode.ONEWAY]

    def get_buy_collateral_token(self, trading_pair: str) -> str:
        trading_rule: TradingRule = self._trading_rules[trading_pair]
        return trading_rule.buy_order_collateral_token

    def get_sell_collateral_token(self, trading_pair: str) -> str:
        trading_rule: TradingRule = self._trading_rules[trading_pair]
        return trading_rule.sell_order_collateral_token

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        return False

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        return False

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        return False

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return WebAssistantsFactory(throttler=self._throttler)

    async def _initialize_trading_pair_symbol_map(self):
        markets = await self._data_source.get_supported_pairs()
        mapping = bidict()
        for market in markets:
            symbol = market["symbol"]
            baseCurrency = market["baseCurrency"]
            mapping[symbol] = combine_to_hb_trading_pair(symbol, baseCurrency)
        self._set_trading_pair_symbol_map(mapping)

    async def _update_trading_rules(self):
        self._trading_rules = dict()
        for trading_pair in self._trading_pairs:
            perpetual_pair = self._data_source.get_perpetual_pair_for_trading_pair(trading_pair)
            if perpetual_pair is None:
                continue
            self._trading_rules[trading_pair] = TradingRule(
                trading_pair=trading_pair,
                min_order_size=Decimal(wei_to_eth(perpetual_pair["minOrderSize"])),
                max_order_size=Decimal(wei_to_eth(perpetual_pair["maxOrderSize"])),
                min_base_amount_increment=Decimal(wei_to_eth(perpetual_pair["minOrderSizeIncrement"])),
                min_price_increment=Decimal(wei_to_eth(perpetual_pair["minPriceIncrement"])),
                buy_order_collateral_token=perpetual_pair["baseCurrency"],
                sell_order_collateral_token=perpetual_pair["baseCurrency"],
            )

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return HookOdysseyPerpetualAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            data_source=self._data_source,
            domain=self.domain,
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        # Not used in HookOdysseyPerpetual
        raise NotImplementedError

    def _is_user_stream_initialized(self):
        # HookOdysseyPerpetual does not have private websocket endpoints
        return self._data_source.is_started()

    def _create_user_stream_tracker(self):
        # HookOdysseyPerpetual does not use a tracker for the private streams
        return None

    def _create_user_stream_tracker_task(self):
        # HookOdysseyPerpetual does not use a tracker for the private streams
        return None

    def _get_fee(
        self,
        base_currency: str,
        quote_currency: str,
        order_type: OrderType,
        order_side: TradeType,
        amount: Decimal,
        price: Decimal = s_decimal_NaN,
        is_maker: Optional[bool] = None,
    ) -> TradeFeeBase:
        maker_fee, taker_fee = self._data_source._fees
        fee_rate = maker_fee if is_maker else taker_fee
        return AddedToCostTradeFee(percent=fee_rate)

    async def _update_trading_fees(self):
        """
        Update fees information from the exchange
        """
        self._fees = await self._data_source.fetch_fees()

    async def _status_polling_loop_fetch_updates(self):
        await safe_gather(
            self._update_balances(),
            self._update_positions(),
        )
        pass

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        hook_order_hash = tracked_order.exchange_order_id
        return await self._data_source.cancel_order(hook_order_hash)

    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        price: Decimal,
        position_action: PositionAction = PositionAction.NIL,
        **kwargs,
    ) -> Tuple[str, float]:
        # Get nonce from kwargs
        nonce = kwargs.get("nonce")
        market_hash = kwargs.get("market_hash")
        instrument_hash = kwargs.get("instrument_hash")
        subaccount = kwargs.get("subaccount")
        return await self._data_source.place_order(
            market_hash=market_hash,
            instrument_hash=instrument_hash,
            subaccount=subaccount,
            amount=amount,
            price=price,
            trade_type=trade_type,
            order_type=order_type,
            nonce=nonce,
        )

    def buy(
        self,
        trading_pair: str,
        amount: Decimal,
        order_type=OrderType.LIMIT,
        price: Decimal = s_decimal_NaN,
        **kwargs,
    ) -> str:
        """
        Creates a promise to create a buy order using the parameters

        :param trading_pair: the token pair to operate with
        :param amount: the order amount
        :param order_type: the type of order to create (MARKET, LIMIT, LIMIT_MAKER)
        :param price: the order price

        :return: the id assigned by the connector to the order (the client id)
        """
        perpetual_pair = self._data_source.get_perpetual_pair_for_trading_pair(trading_pair)
        market_hash = perpetual_pair["marketHash"]
        instrument_hash = perpetual_pair["instrumentHash"]
        subaccount = perpetual_pair["subaccount"]

        if order_type in [OrderType.LIMIT, OrderType.LIMIT_MAKER]:
            price = self.quantize_order_price(trading_pair, price)
        amount = self.quantize_order_amount(trading_pair=trading_pair, amount=amount)
        nonce = get_tracking_nonce()
        order_id = self._data_source.order_hash(
            market_hash=market_hash,
            instrument_hash=instrument_hash,
            subaccount=subaccount,
            amount=amount,
            price=price,
            order_type=order_type,
            trade_type=TradeType.BUY,
            nonce=nonce,
        )
        safe_ensure_future(
            self._create_order(
                trade_type=TradeType.BUY,
                order_id=order_id,
                trading_pair=trading_pair,
                amount=amount,
                order_type=order_type,
                price=price,
                nonce=nonce,
                market_hash=market_hash,
                instrument_hash=instrument_hash,
                subaccount=subaccount,
                **kwargs,
            )
        )
        return order_id

    def sell(
        self,
        trading_pair: str,
        amount: Decimal,
        order_type: OrderType = OrderType.LIMIT,
        price: Decimal = s_decimal_NaN,
        **kwargs,
    ) -> str:
        """
        Creates a promise to create a sell order using the parameters.
        :param trading_pair: the token pair to operate with
        :param amount: the order amount
        :param order_type: the type of order to create (MARKET, LIMIT, LIMIT_MAKER)
        :param price: the order price
        :return: the id assigned by the connector to the order (the client id)
        """
        perpetual_pair = self._data_source.get_perpetual_pair_for_trading_pair(trading_pair)
        market_hash = perpetual_pair["marketHash"]
        instrument_hash = perpetual_pair["instrumentHash"]
        subaccount = perpetual_pair["subaccount"]

        if order_type in [OrderType.LIMIT, OrderType.LIMIT_MAKER]:
            price = self.quantize_order_price(trading_pair, price)
        amount = self.quantize_order_amount(trading_pair=trading_pair, amount=amount)
        nonce = get_tracking_nonce()
        order_id = self._data_source.order_hash(
            market_hash=market_hash,
            instrument_hash=instrument_hash,
            subaccount=subaccount,
            amount=amount,
            price=price,
            order_type=order_type,
            trade_type=TradeType.SELL,
            nonce=nonce,
        )
        safe_ensure_future(
            self._create_order(
                trade_type=TradeType.SELL,
                order_id=order_id,
                trading_pair=trading_pair,
                amount=amount,
                order_type=order_type,
                price=price,
                nonce=nonce,
                market_hash=market_hash,
                instrument_hash=instrument_hash,
                subaccount=subaccount,
                **kwargs,
            )
        )
        return order_id

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: List):
        raise NotImplementedError

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        ltp = await self._data_source.get_index_price(trading_pair)
        return float(ltp)

    async def _update_balances(self):
        if not self._is_user_stream_initialized() or len(self._trading_pairs) == 0:
            # We are unable to get the balance snapshot without the user stream running
            # Additionally without trading pairs we cannot map the balances to the correct trading pairs
            for collateral in CONSTANTS.SUPPORTED_COLLATERAL:
                self._account_balances[collateral] = Decimal(0)
                self._account_available_balances[collateral] = Decimal(0)
            return

        balances = await self._data_source.get_balances()
        for trading_pair in self._trading_pairs:
            # Use the subaccount balance for the first found trading pair
            perpetual_pair = self._data_source.get_perpetual_pair_for_trading_pair(trading_pair)
            if perpetual_pair is not None:
                subaccount = perpetual_pair["subaccount"]
                self._account_balances[perpetual_pair["baseCurrency"]] = balances[subaccount]
                self._account_available_balances[perpetual_pair["baseCurrency"]] = balances[subaccount]
                break

    async def _update_positions(self):
        positions = await self._data_source.get_positions()
        for position in positions.values():
            if position.amount != 0:
                self._perpetual_trading.set_position(position.trading_pair, position)
            else:
                self._perpetual_trading.remove_position(position.trading_pair)

    async def _get_position_mode(self) -> Optional[PositionMode]:
        return PositionMode.ONEWAY

    async def _trading_pair_position_mode_set(self, mode: PositionMode, trading_pair: str) -> Tuple[bool, str]:
        msg = ""
        success = True
        initial_mode = await self._get_position_mode()
        if initial_mode != mode:
            msg = "hook odyssey only supports the ONEWAY position mode."
            success = False
        return success, msg

    async def _set_trading_pair_leverage(self, trading_pair: str, leverage: int) -> Tuple[bool, str]:
        """
        Leverage is set on a per order basis
        """
        return True, ""

    async def _fetch_last_fee_payment(self, trading_pair: str) -> Tuple[int, Decimal, Decimal]:
        return 0, Decimal(0), Decimal(0)

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        # Hook Odyssey Perpetual does not support fetching all trade updates for an order
        pass

    async def _format_trading_rules(self, exchange_info_dict: List) -> List[TradingRule]:
        return []

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        return None

    async def _user_stream_event_listener(self):
        # User stream events are managed through HookOdysseyPerpetualDataSource
        pass

    async def _update_time_synchronizer(self, pass_on_non_cancelled_error: bool = False):
        pass

    def _configure_event_forwarders(self):
        event_forwarder = EventForwarder(to_function=self._process_user_trade_update)
        self._forwarders.append(event_forwarder)
        self._data_source.add_listener(event_tag=MarketEvent.TradeUpdate, listener=event_forwarder)

        event_forwarder = EventForwarder(to_function=self._process_user_order_update)
        self._forwarders.append(event_forwarder)
        self._data_source.add_listener(event_tag=MarketEvent.OrderUpdate, listener=event_forwarder)

        event_forwarder = EventForwarder(to_function=self._process_balance_event)
        self._forwarders.append(event_forwarder)
        self._data_source.add_listener(event_tag=AccountEvent.BalanceEvent, listener=event_forwarder)

    def _process_balance_event(self, event: BalanceUpdateEvent):
        self._account_balances[event.asset_name] = event.total_balance
        self._account_available_balances[event.asset_name] = event.available_balance

    def _process_user_order_update(self, order_update: OrderUpdate):
        tracked_order = self._order_tracker.all_updatable_orders.get(order_update.client_order_id)

        if tracked_order is not None:
            self.logger().debug(f"Processing order update {order_update}\nUpdatable order {tracked_order.to_json()}")
            order_update_to_process = OrderUpdate(
                trading_pair=tracked_order.trading_pair,
                update_timestamp=order_update.update_timestamp,
                new_state=order_update.new_state,
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=order_update.exchange_order_id,
            )
            self._order_tracker.process_order_update(order_update=order_update_to_process)

    def _process_user_trade_update(self, trade_update: TradeUpdate):
        tracked_order = self._order_tracker.all_fillable_orders_by_exchange_order_id.get(trade_update.exchange_order_id)

        if tracked_order is not None:
            self.logger().debug(f"Processing trade update {trade_update}\nFillable order {tracked_order.to_json()}")

            # Fetch the current fee rates
            maker_fee, taker_fee = self._data_source.get_fees()
            fee_rate = maker_fee if tracked_order.is_maker else taker_fee
            fee = TradeFeeBase.new_perpetual_fee(trade_type=tracked_order.trade_type, percent=fee_rate)

            fill_amount = trade_update.fill_base_amount - tracked_order.executed_amount_base
            trade_update: TradeUpdate = TradeUpdate(
                trade_id=trade_update.trade_id,
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=trade_update.exchange_order_id,
                trading_pair=tracked_order.trading_pair,
                fill_timestamp=trade_update.fill_timestamp,
                fill_price=trade_update.fill_price,
                fill_base_amount=fill_amount,
                fill_quote_amount=fill_amount * trade_update.fill_price,
                fee=fee,
            )
            self._order_tracker.process_trade_update(trade_update)
