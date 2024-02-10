import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.websockets import WebsocketsTransport

from hummingbot.connector.derivative.hook_odyssey_perpetual import hook_odyssey_perpetual_constants as CONSTANTS
from hummingbot.logger import HummingbotLogger


class BaseGraphQLExecutor(ABC):
    @abstractmethod
    async def perpetual_pairs(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def account_details(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def subscribe_ticker(self, handler: Callable, symbol: str) -> None:
        raise NotImplementedError

    async def subscribe_statistics(self, handler: Callable, symbol: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe_bbo(self, handler: Callable, symbol: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe_orderbook(self, handler: Callable, instrument_hash: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe_subaccount_orders(self, handler: Callable, subaccount: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe_subaccount_balances(self, handler: Callable, address: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe_subaccount_positions(self, handler: Callable, address: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def place_order(
        self,
        order_input: Dict[str, Any],
        signature: Dict[str, Any],
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, order_hash: str) -> bool:
        raise NotImplementedError


class HookOdysseyPerpetualGrapQLExecutor(BaseGraphQLExecutor):
    _logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(HummingbotLogger.logger_name_for_class(cls))
        return cls._logger

    def __init__(self, hook_odyssey_api_key: str, domain: Optional[str] = CONSTANTS.DOMAIN):
        super().__init__()
        self._hook_odyssey_api_key = hook_odyssey_api_key
        self._domain = domain
        self._client = None

    async def _execute(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ):
        headers = {"X-HOOK-API-KEY": self._hook_odyssey_api_key}
        url = CONSTANTS.BASE_URLS[self._domain]
        transport = AIOHTTPTransport(url=url, headers=headers)
        async with Client(
            transport=transport,
            fetch_schema_from_transport=False,
            execute_timeout=CONSTANTS.DEFAULT_TIMEOUT,
        ) as session:
            result = await session.execute(gql(query), variable_values=variables)

        return result

    async def _execute_subscription(self, subscription_query: str, variables: dict[str, Any] | None = None):
        headers = {"X-HOOK-API-KEY": self._hook_odyssey_api_key}
        url = CONSTANTS.WS_URLS[self._domain]
        transport = WebsocketsTransport(url=url, headers=headers)
        async with Client(transport=transport, execute_timeout=CONSTANTS.DEFAULT_TIMEOUT) as session:
            subscription = gql(subscription_query)
            async for result in session.subscribe(subscription, variable_values=variables):
                yield result

    async def perpetual_pairs(self) -> Dict[str, Any]:
        query = """
            query PerpetualPairs {
                perpetualPairs {
                    marketHash
                    instrumentHash
                    symbol
                    baseCurrency
                    minOrderSize
                    maxOrderSize
                    minOrderSizeIncrement
                    minPriceIncrement
                    initialMarginBips
                    subaccount
                }
            }
        """
        result = await self._execute(query=query, variables={})
        return result

    async def account_details(self) -> Dict[str, Any]:
        query = """
            query AccountDetails {
                accountDetails {
                    makerFeeBips
                    takerFeeBips
                }
            }
        """
        result = await self._execute(query=query, variables={})
        return result

    async def subscribe_ticker(self, handler: Callable, symbol: str):
        query = """
            subscription onTickerEvent($symbol: String!) {
                ticker(symbol: $symbol) {
                    price
                    timestamp
                }
            }
        """
        variables = {"symbol": symbol}
        async for event in self._execute_subscription(subscription_query=query, variables=variables):
            await handler(event=event, symbol=symbol)

    async def subscribe_statistics(self, handler: Callable, symbol: str):
        query = """
            subscription onStatisticsEvent($symbol: String!) {
                statistics(symbol: $symbol) {
                    eventType
                    timestamp
                    fundingRateBips
                    nextFundingEpoch
                }
            }
        """
        variables = {"symbol": symbol}
        async for event in self._execute_subscription(subscription_query=query, variables=variables):
            await handler(event=event, symbol=symbol)

    async def subscribe_bbo(self, handler: Callable, symbol: str) -> None:
        query = """
            subscription onBboEvent($symbol: String!, $instrumentType: InstrumentType!) {
                bbo(symbol: $symbol, instrumentType: $instrumentType) {
                    eventType
                    timestamp
                    instruments {
                        id
                        markPrice
                    }
                }
            }
        """
        variables = {"symbol": symbol, "instrumentType": "PERPETUAL"}
        async for event in self._execute_subscription(subscription_query=query, variables=variables):
            await handler(event=event, symbol=symbol)

    async def subscribe_orderbook(self, handler: Callable, instrument_hash: str):
        query = """
            subscription onOrderbookEvent($instrumentHash: ID!) {
                orderbook(instrumentHash: $instrumentHash) {
                    eventType
                    timestamp
                    bidLevels {
                        direction
                        size
                        price
                    }
                    askLevels {
                        direction
                        size
                        price
                    }
                }
            }
        """
        variables = {"instrumentHash": instrument_hash}
        async for event in self._execute_subscription(subscription_query=query, variables=variables):
            await handler(event=event, instrument_hash=instrument_hash)

    async def subscribe_subaccount_orders(self, handler: Callable, subaccount: str):
        query = """
            subscription onSubaccountOrderEvent($subaccount: BigInt!) {
                subaccountOrders(subaccount: $subaccount) {
                    eventType
                    orders {
                        instrument {
                            id
                        }
                        direction
                        size
                        remainingSize
                        orderHash
                        status
                    }
                }
            }
        """
        variables = {"subaccount": subaccount}
        async for event in self._execute_subscription(subscription_query=query, variables=variables):
            await handler(event=event, subaccount=subaccount)

    async def subscribe_subaccount_balances(self, handler: Callable, address: str):
        query = """
            subscription onSubaccountBalanceEvent($address: Address!) {
                subaccountBalances(address: $address) {
                    eventType
                    balances {
                        subaccount
                        subaccountID
                        balance
                    }
                }
            }
        """
        variables = {"address": address}
        async for event in self._execute_subscription(subscription_query=query, variables=variables):
            await handler(event=event, address=address)

    async def subscribe_subaccount_positions(self, handler: Callable, address: str):
        query = """
            subscription onSubaccountPositionEvent($address: Address!) {
                subaccountPositions(address: $address) {
                    eventType
                    positions {
                        instrument {
                            id
                        }
                        subaccount
                        marketHash
                        sizeHeld
                        isLong
                        averageCost
                    }
                }
            }
        """
        variables = {"address": address}
        async for event in self._execute_subscription(subscription_query=query, variables=variables):
            await handler(event=event, address=address)

    async def place_order(
        self,
        order_input: Dict[str, Any],
        signature: Dict[str, Any],
    ) -> bool:
        mutation = """
            mutation PlaceOrder(
                $orderInput: PlaceOrderInput!
                $signature: SignatureInput!
            ) {
                placeOrderV2(
                    orderInput: $orderInput
                    signature: $signature
                )
            }
        """
        variables = {"orderInput": order_input, "signature": signature}
        result = await self._execute(query=mutation, variables=variables)
        return result.get("placeOrderV2", False)

    async def cancel_order(self, order_hash: str) -> bool:
        mutation = """
            mutation CancelOrder($orderHash: String!) {
                cancelOrderV2(orderHash: $orderHash)
            }
        """
        variables = {"orderHash": order_hash}
        result = await self._execute(query=mutation, variables=variables)
        return result.get("cancelOrderV2", False)
