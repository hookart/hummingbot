from typing import Tuple

import sha3
from coincurve import PrivateKey
from eip712_structs import Address, Boolean, Bytes, EIP712Struct, String, Uint, make_domain
from eth_utils import big_endian_to_int

import hummingbot.connector.derivative.hook_odyssey_perpetual.hook_odyssey_perpetual_constants as CONSTANTS


class EIP712Domain(EIP712Struct):
    name = String()
    version = String()
    chainId = Uint(256)
    verifyingContract = Address()


class Order(EIP712Struct):
    """
    Order typehash
    "Order(bytes32 market,uint8 instrumentType,bytes32 instrumentId,uint8 direction,uint256 maker,uint256 taker,uint256 amount,uint256 limitPrice,uint256 expiration,uint256 nonce,uint256 counter,bool postOnly,bool reduceOnly,bool allOrNothing)"
    """

    market = Bytes(32)
    instrumentType = Uint(8)  # 0 = Call, 1 = Put, 2 = Perpetual
    instrumentId = Bytes(32)
    direction = Uint(8)  # 0 = Buy, 1 = Sell
    maker = Uint(256)
    taker = Uint(256)
    amount = Uint(256)
    limitPrice = Uint(256)
    expiration = Uint(256)
    nonce = Uint(256)
    counter = Uint(256)
    postOnly = Boolean()
    reduceOnly = Boolean()
    allOrNothing = Boolean()


def keccak_hash(x):
    return sha3.keccak_256(x).digest()


class HookOdysseyPerpetualSigner:
    def __init__(self, private_key: str, domain: str = CONSTANTS.DOMAIN):
        self.private_key = private_key
        self.domain = domain
        self.contract_address = CONSTANTS.CONTRACT_ADDRESSES[self.domain]
        self.chain_id = CONSTANTS.CHAIN_IDS[self.domain]

    def compute_order_hash(self, order: Order) -> str:
        """
        Gets the eip 712 hash of an Order for use as a client order id

        :param order: the order to hash

        :return: a string hex of the keccak_256 of the signable_bytes of the order
        """
        domain = make_domain(
            name=CONSTANTS.EIP712_DOMAIN_NAME,
            version=CONSTANTS.EIP712_DOMAIN_VERSION,
            chainId=self.chain_id,
            verifyingContract=self.contract_address,
        )
        signable_bytes = order.signable_bytes(domain)
        return self.generate_digest(signable_bytes)

    def sign_order(self, order: Order) -> Tuple[str, str]:
        """
        Signs the order using the private key and returns the signature and order hash (digest)

        :param order: the order using EIP712 structure for signing

        :return: a tuple with both a string hex of the signature of the order payload and order hash (digest)
        """
        domain = make_domain(
            name=CONSTANTS.EIP712_DOMAIN_NAME,
            version=CONSTANTS.EIP712_DOMAIN_VERSION,
            chainId=self.chain_id,
            verifyingContract=self.contract_address,
        )
        signable_bytes = order.signable_bytes(domain)
        # Digest for order tracking in Hummingbot
        digest = self.generate_digest(signable_bytes)

        pk = PrivateKey.from_hex(self.private_key)
        signature = pk.sign_recoverable(signable_bytes, hasher=keccak_hash)

        v = signature[64] + 27
        r = big_endian_to_int(signature[0:32])
        s = big_endian_to_int(signature[32:64])

        final_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big") + v.to_bytes(1, "big")
        return f"0x{final_sig.hex()}", digest

    def generate_digest(self, signable_bytes: bytearray) -> str:
        """
        Generates the digest of the payload for use across Vetext lookups

        :param signable_bytes: the bytes of the payload

        :return: a string hex of the keccak_256 of the signable_bytes of the payload
        """
        return f"0x{keccak_hash(signable_bytes).hex()}"
