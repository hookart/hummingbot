from decimal import Decimal

from pydantic import Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap, ClientFieldData
from hummingbot.core.data_type.trade_fee import TradeFeeSchema
from hummingbot.core.utils.tracking_nonce import NonceCreator

CENTRALIZED = True
EXAMPLE_PAIR = "MILADY-ETH"

DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.001"),  # 10 bps
    taker_percent_fee_decimal=Decimal("0.0025"),  # 25 bps
    buy_percent_fee_deducted_from_returns=True,
)

_nonce_provider = NonceCreator.for_microseconds()


class HookOdysseyPerpetualConfigMap(BaseConnectorConfigMap):
    connector: str = Field(default="hook_odyssey_perpetual", const=True, client_data=None)
    hook_odyssey_perpetual_signer_address: str = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the order signer address",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_perpetual_signer_pkey: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the order signer private key",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_api_key: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Hook Odyssey API key",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_pool_address: str = Field(
        default='',
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the pool address to trade on behalf of",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_pool_subaccount: str = Field(
        default='',
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the pool subaccount to trade on behalf of",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_pool_trading_pair: str = Field(
        default='',
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the trading pair configured for the pool",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )

    class Config:
        title = "hook_odyssey_perpetual"


KEYS = HookOdysseyPerpetualConfigMap.construct()

OTHER_DOMAINS = ["hook_odyssey_perpetual_testnet"]
OTHER_DOMAINS_PARAMETER = {"hook_odyssey_perpetual_testnet": "hook_odyssey_perpetual_testnet"}
OTHER_DOMAINS_EXAMPLE_PAIR = {"hook_odyssey_perpetual_testnet": EXAMPLE_PAIR}
OTHER_DOMAINS_DEFAULT_FEES = {"hook_odyssey_perpetual_testnet": DEFAULT_FEES}


class HookOdysseyPerpetualTestnetConfigMap(BaseConnectorConfigMap):
    connector: str = Field(default="hook_odyssey_perpetual_testnet", const=True, client_data=None)
    hook_odyssey_perpetual_signer_address: str = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ethereum address",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_perpetual_signer_pkey: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ethereum private key",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_api_key: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Hook Odyssey API key",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_pool_address: str = Field(
        default='',
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the pool address to trade on behalf of",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_pool_subaccount: str = Field(
        default='',
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the pool subaccount to trade on behalf of",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )
    hook_odyssey_pool_trading_pair: str = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter the trading pair configured for the pool",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        ),
    )

    class Config:
        title = "hook_odyssey_perpetual_testnet"


OTHER_DOMAINS_KEYS = {"hook_odyssey_perpetual_testnet": HookOdysseyPerpetualTestnetConfigMap.construct()}


def eth_to_wei(eth_amount: Decimal) -> int:
    return int(eth_amount * Decimal("1e18"))


def wei_to_eth(wei_amount: str | int | Decimal) -> Decimal:
    return Decimal(wei_amount) / Decimal("1e18")


def get_tracking_nonce() -> int:
    nonce = _nonce_provider.get_tracking_nonce()
    return nonce
