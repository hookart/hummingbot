from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "hook_odyssey_perpetual"
DOMAIN = EXCHANGE_NAME
TESTNET_DOMAIN = "hook_odyssey_perpetual_testnet"
SUPPORTED_COLLATERAL = ["ETH", "USDC"]

BASE_URLS = {
    DOMAIN: "https://api-prod.hook.xyz/query",
    TESTNET_DOMAIN: "https://goerli-api.hook.xyz/query",
}

WS_URLS = {
    DOMAIN: "wss://api-prod.hook.xyz/query",
    TESTNET_DOMAIN: "wss://goerli-api.hook.xyz/query",
}

# Order Statuses
# Note: "Partially Matched" and "Matched" are ignored because they are not final states
ORDER_STATE = {
    "OPEN": OrderState.OPEN,
    "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
    "FILLED": OrderState.FILLED,
    "CANCELED": OrderState.CANCELED,
    "EXPIRED": OrderState.CANCELED,
    "REJECTED": OrderState.FAILED,
    "UNFILLABLE": OrderState.FAILED,
    "FAILED": OrderState.FAILED,
}

RATE_LIMITS = []

# EIP 712
EIP712_DOMAIN_NAME = "Hook"
EIP712_DOMAIN_VERSION = "1.0.0"

CONTRACT_ADDRESSES = {
    DOMAIN: "0xF9Bd1BaB25442A3b6888f2086736C6aC76A4Cf4B",
    TESTNET_DOMAIN: "0x64247BeF0C0990aF63FCbdd21dc07aC2b251f500",
}

CHAIN_IDS = {
    DOMAIN: 4665,
    TESTNET_DOMAIN: 46658378,
}

DEFAULT_TIMEOUT = 3
