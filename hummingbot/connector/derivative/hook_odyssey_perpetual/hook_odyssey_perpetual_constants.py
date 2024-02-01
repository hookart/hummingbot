from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "hook_odyssey_perpetual"
DOMAIN = EXCHANGE_NAME
TESTNET_DOMAIN = "hook_odyssey_perpetual_testnet"
SUPPORTED_COLLATERAL = ["ETH", "USDC"]

BASE_URLS = {
    DOMAIN: "https://goerli-api.hook.xyz/query",  # TODO: Set to mainnet
    TESTNET_DOMAIN: "https://api.hookdev.xyz/query",  # TODO: Set to testnet
}

WS_URLS = {
    DOMAIN: "wss://goerli-api.hook.xyz/query",  # TODO: Set to mainnet
    TESTNET_DOMAIN: "wss://api.hookdev.xyz/query",  # TODO: Set to testnet
}

# Order Statuses
ORDER_STATE = {
    "OPEN": OrderState.OPEN,
    "PARTIALLY_MATCHED": OrderState.PARTIALLY_FILLED,
    "MATCHED": OrderState.FILLED,
    "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
    "FILLED": OrderState.FILLED,
    "CANCELED": OrderState.CANCELED,
    "EXPIRED": OrderState.CANCELED,
    "REJECTED": OrderState.FAILED,
    "UNFILLABLE": OrderState.FAILED,
}

RATE_LIMITS = []

# EIP 712
EIP712_DOMAIN_NAME = "Hook"
EIP712_DOMAIN_VERSION = "1.0.0"

CONTRACT_ADDRESSES = {
    DOMAIN: "0x64247BeF0C0990aF63FCbdd21dc07aC2b251f500",  # TODO: Set to mainnet
    TESTNET_DOMAIN: "0xc6e7DF5E7b4f2A278906862b61205850344D4e7d",  # TODO: Set to testnet
}

CHAIN_IDS = {
    DOMAIN: 46658378,  # TODO: Set to mainnet
    TESTNET_DOMAIN: 9999,  # TODO: Set to testnet
}

DEFAULT_TIMEOUT = 3
