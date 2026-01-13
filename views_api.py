from http import HTTPStatus
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from lnbits.core.models import WalletTypeInfo
from lnbits.decorators import check_admin, require_admin_key
from loguru import logger
from pynostr.key import PrivateKey

from .crud import (
    create_nwc,
    delete_nwc,
    get_all_config_nwc,
    get_budgets_nwc,
    get_config_nwc,
    get_nwc,
    get_wallet_nwcs,
    set_config_nwc,
)
from .models import (
    CreateNWCKey,
    DeleteNWC,
    GetBudgetsNWC,
    GetNWC,
    GetWalletNWC,
    NWCGetResponse,
    NWCRegistrationRequest,
)
from .paranoia import (
    assert_boolean,
    assert_sane_string,
    assert_valid_pubkey,
    assert_valid_wallet_id,
)
from .permission import nwc_permissions

nwcprovider_api_router = APIRouter()


# Get supported permissions
@nwcprovider_api_router.get("/api/v1/permissions")
async def api_get_permissions() -> dict:
    return nwc_permissions


## Get nwc keys associated with the wallet
@nwcprovider_api_router.get("/api/v1/nwc")
async def api_get_nwcs(
    include_expired: bool = False,
    calculate_spent_budget: bool = False,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[NWCGetResponse]:
    wallet_id = wallet.wallet.id

    # hardening #
    assert_valid_wallet_id(wallet_id)
    assert_boolean(include_expired)
    assert_boolean(calculate_spent_budget)
    # ## #

    wallet_nwcs = GetWalletNWC(wallet=wallet_id, include_expired=include_expired)
    nwcs = await get_wallet_nwcs(wallet_nwcs)
    out = []
    for nwc in nwcs:
        budgets_nwc = GetBudgetsNWC(
            pubkey=nwc.pubkey, calculate_spent=calculate_spent_budget
        )
        budgets = await get_budgets_nwc(budgets_nwc)
        res = NWCGetResponse(data=nwc, budgets=budgets)
        out.append(res)
    return out


# Get a nwc key
@nwcprovider_api_router.get("/api/v1/nwc/{pubkey}")
async def api_get_nwc(
    pubkey: str,
    include_expired: bool = False,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> NWCGetResponse:
    wallet_id = wallet.wallet.id

    # hardening #
    assert_valid_pubkey(pubkey)
    assert_boolean(include_expired)
    assert_valid_wallet_id(wallet_id)
    # ## #

    nwc = await get_nwc(
        GetNWC(pubkey=pubkey, wallet=wallet_id, include_expired=include_expired)
    )

    if not nwc:
        raise ValueError("Pubkey has no associated wallet")
    res = NWCGetResponse(
        data=nwc, budgets=await get_budgets_nwc(GetBudgetsNWC(pubkey=pubkey))
    )

    return res


# Get pairing url for given secret
@nwcprovider_api_router.get("/api/v1/pairing/{secret}")
async def api_get_pairing_url(
    req: Request, secret: str, lud16: str | None = None
) -> str:

    # hardening #
    assert_sane_string(secret)
    if lud16:
        assert_sane_string(lud16)
    # ## #

    pprivkey: str | None = await get_config_nwc("provider_key")
    if not pprivkey:
        raise Exception("Extension is not configured")
    relay = await get_config_nwc("relay")
    if not relay:
        raise Exception("Extension is not configured")
    relay_alias: str | None = await get_config_nwc("relay_alias")
    if relay_alias:
        relay = relay_alias
    else:
        if relay == "nostrclient":
            scheme = req.url.scheme  # http or https
            netloc = req.url.netloc  # hostname and port
            if scheme == "http":
                scheme = "ws"
            else:
                scheme = "wss"
            netloc += "/nostrclient/api/v1/relay"
            relay = f"{scheme}://{netloc}"
    psk = PrivateKey.from_hex(pprivkey)
    ppk = psk.public_key
    if not ppk:
        raise Exception("Error generating pubkey")
    ppubkey = ppk.hex()
    url = "nostr+walletconnect://"
    url += ppubkey
    url += "?relay=" + quote(relay, safe="")
    url += "&secret=" + secret
    if lud16:
        url += "&lud16=" + quote(lud16, safe="")
    return url


## Register a new nwc key
@nwcprovider_api_router.put(
    "/api/v1/nwc/{pubkey}",
    status_code=HTTPStatus.CREATED,
)
async def api_register_nwc(
    pubkey: str,
    data: NWCRegistrationRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> NWCGetResponse:
    wallet_id = wallet.wallet.id

    # hardening #
    assert_valid_pubkey(pubkey)
    assert_valid_wallet_id(wallet_id)
    # ## #

    nwc = await create_nwc(
        CreateNWCKey(
            pubkey=pubkey,
            wallet=wallet_id,
            description=data.description,
            expires_at=data.expires_at,
            permissions=data.permissions,
            budgets=data.budgets,
            lud16=data.lud16,
        )
    )
    budgets = await get_budgets_nwc(GetBudgetsNWC(pubkey=pubkey))
    res = NWCGetResponse(data=nwc, budgets=budgets)
    return res


# Delete a nwc key
@nwcprovider_api_router.delete("/api/v1/nwc/{pubkey}")
async def api_delete_nwc(
    pubkey: str, wallet: WalletTypeInfo = Depends(require_admin_key)
):
    wallet_id = wallet.wallet.id

    # hardening #
    assert_valid_pubkey(pubkey)
    assert_valid_wallet_id(wallet_id)
    # ## #

    await delete_nwc(DeleteNWC(pubkey=pubkey, wallet=wallet_id))
    return JSONResponse(content={"message": f"NWC key {pubkey} deleted successfully."})


# Get config
@nwcprovider_api_router.get("/api/v1/config", dependencies=[Depends(check_admin)])
async def api_get_all_config_nwc():
    config = await get_all_config_nwc()
    return config


# Get config
@nwcprovider_api_router.get(
    "/api/v1/config/{key}",
    dependencies=[Depends(check_admin)],
)
async def api_get_config_nwc(key: str):
    config = await get_config_nwc(key)
    out = {}
    out[key] = config
    return out


# Set config
@nwcprovider_api_router.post("/api/v1/config", dependencies=[Depends(check_admin)])
async def api_set_config_nwc(req: Request):
    data = await req.json()

    # hardening #
    for key, value in data.items():
        assert_sane_string(key)
        assert_sane_string(value)
    # ## #

    for key, value in data.items():
        await set_config_nwc(key, value)
    return await api_get_all_config_nwc()


# Get available lightning addresses from lnurlp extension
@nwcprovider_api_router.get("/api/v1/lnaddresses")
async def api_get_lightning_addresses(
    req: Request,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[dict]:
    """
    Fetch available lightning addresses from lnurlp extension for this wallet.
    Returns list of {address, username, description} for dropdown selection.
    """
    wallet_id = wallet.wallet.id

    # hardening #
    assert_valid_wallet_id(wallet_id)
    # ## #

    try:
        # Import lnurlp crud - may not be installed
        from lnbits.extensions.lnurlp.crud import get_pay_links

        pay_links = await get_pay_links([wallet_id])
        domain = req.url.netloc

        addresses = []
        for link in pay_links:
            if link.username:
                addresses.append({
                    "address": f"{link.username}@{domain}",
                    "username": link.username,
                    "description": link.description or "",
                })

        return addresses
    except ImportError:
        logger.warning("lnurlp extension not available for lightning address lookup")
        return []
    except Exception as e:
        logger.error(f"Error fetching lightning addresses: {e}")
        return []
