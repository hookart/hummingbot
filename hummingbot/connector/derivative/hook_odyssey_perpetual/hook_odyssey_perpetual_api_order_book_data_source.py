import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_data_source import (
    HookOdysseyPerpetualDataSource,
)
from hummingbot.core.data_type.funding_info import FundingInfo
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.perpetual_api_order_book_data_source import PerpetualAPIOrderBookDataSource
from hummingbot.core.event.event_forwarder import EventForwarder
from hummingbot.core.event.events import OrderBookEvent
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_derivative import (
        HookOdysseyPerpetualDerivative,
    )


class HookOdysseyPerpetualAPIOrderBookDataSource(PerpetualAPIOrderBookDataSource):
    _hpopobds_logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        trading_pairs: List[str],
        connector: "HookOdysseyPerpetualDerivative",
        data_source: HookOdysseyPerpetualDataSource,
        domain: str,
    ):
        super().__init__(trading_pairs)
        self._connector = connector
        self._domain = domain
        self._data_source = data_source
        self._forwarders = []
        self._configure_event_forwarders()

    async def get_last_traded_prices(
        self, trading_pairs: List[str], domain: Optional[str] = None
    ) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def listen_for_subscriptions(self):
        # The socket reconnection is managed by the data_source. This method should do nothing
        pass

    async def _parse_order_book_snapshot_message(
        self, raw_message: OrderBookMessage, message_queue: asyncio.Queue
    ):
        # In HookOdysseyPerpetual, 'raw_message' is the OrderBookMessage from the data source
        message_queue.put_nowait(raw_message)

    async def _connected_websocket_assistant(self) -> WSAssistant:
        # HookOdysseyPerpetual uses GraphQL websockets to consume stream events
        raise NotImplementedError

    async def _subscribe_channels(self, ws: WSAssistant):
        # HookOdysseyPerpetual uses GraphQL websockets to consume stream events
        raise NotImplementedError

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        return await self._data_source.get_order_book_snapshot(trading_pair)

    async def _parse_trade_message(
        self, raw_message: OrderBookMessage, message_queue: asyncio.Queue
    ):
        # In HookOdysseyPerpetual, 'raw_message' is the OrderBookMessage from the data source
        message_queue.put_nowait(raw_message)

    async def _parse_order_book_diff_message(
        self, raw_message: OrderBookMessage, message_queue: asyncio.Queue
    ):
        # In HookOdysseyPerpetual, 'raw_message' is the OrderBookMessage from the data source
        message_queue.put_nowait(raw_message)

    async def get_funding_info(self, trading_pair: str) -> FundingInfo:
        index_price = await self._data_source.get_last_traded_price(trading_pair)
        funding_info = await self._data_source.get_funding_info(trading_pair)
        funding_info.index_price = Decimal(index_price)
        return funding_info

    async def _parse_funding_info_message(
        self, raw_message: Dict[str, Any], message_queue: asyncio.Queue
    ):
        """
        Placeholder method for parsing funding info messages. Actual implementation needed.
        """
        pass

    def _configure_event_forwarders(self):
        # Forward order book diffs
        order_book_event_forwarder = EventForwarder(
            to_function=self._process_order_book_event
        )
        self._forwarders.append(order_book_event_forwarder)
        self._data_source.add_listener(
            event_tag=OrderBookEvent.OrderBookDataSourceUpdateEvent,
            listener=order_book_event_forwarder,
        )

        # Forward trade updates
        trade_event_forwarder = EventForwarder(
            to_function=self._process_public_trade_event
        )
        self._forwarders.append(trade_event_forwarder)
        self._data_source.add_listener(
            event_tag=OrderBookEvent.TradeEvent, listener=trade_event_forwarder
        )

    def _process_order_book_event(self, order_book_diff: OrderBookMessage):
        if order_book_diff.type == OrderBookMessageType.SNAPSHOT:
            self._message_queue[self._snapshot_messages_queue_key].put_nowait(
                order_book_diff
            )
        else:
            self._message_queue[self._diff_messages_queue_key].put_nowait(
                order_book_diff
            )

    def _process_public_trade_event(self, trade_update: OrderBookMessage):
        self._message_queue[self._trade_messages_queue_key].put_nowait(trade_update)
