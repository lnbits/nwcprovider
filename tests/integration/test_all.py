import pytest
import asyncio
from loguru import logger
import httpx
import asyncio
import bolt11
import secp256k1
import time
from typing import List, Dict
import websockets
import random
import json
from typing import List, Dict, Optional
from Cryptodome.Util.Padding import pad, unpad
import hashlib
from Cryptodome import Random
from Cryptodome.Cipher import AES
import base64
from typing import Union, Dict
wallets = {
    "wallet1": {
        "name": "wallet1",
        "id": "ca464af8b1a94f988d6d729586961d2a",
        "admin_key": "7d2541d0c4154a498e43e5e287c64640",
        "balance_msats": 1000000,
    },
    "wallet2": {
        "name": "wallet2",
        "id": "147adb7b35f14fcca146a5e9b570fc18",
        "admin_key": "4d67c02489f34cd78aec68af48c7c8b4",
        "balance_msats": 1000000,
    },
    "wallet3": {
        "name": "wallet3",
        "id": "343a5d4a96cc4cf793a49a2df9ca04e6",
        "admin_key": "ca4e7c921fdb4ec2b761cadb5fd1d30d",
        "balance_msats": 1000000,
    },
    "wallet4": {
        "name": "wallet4",
        "id": "2faa91184177414ab14712cadafbc78f",
        "admin_key": "0ffd65580a664e0aae85687f99dac7ad",
        "balance_msats": 1000000,
    }
}

async def check_services():
    # wait for http server in localhost:7777
    while True:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get('http://localhost:7777')
                assert resp.status_code == 200
                break
        except:
            logger.info("Waiting for nostr relay @ http://localhost:7777")
            logger.info("Please start the required services by running `bash start.sh` if you haven't already")
            await asyncio.sleep(1)
    
    # wait lnbits @ localhost:5000
    while True:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get('http://localhost:5002')
                assert resp.status_code == 200
                break
        except:
            logger.info("Waiting for lnbits @ http://localhost:5002")
            logger.info("Please start the required services by running `bash start.sh` if you haven't already")
            await asyncio.sleep(1)


async def get_wallet_balance(w:str):
    api_key = wallets[w]["admin_key"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(f'http://localhost:5002/api/v1/wallet?api-key={api_key}')
        assert resp.status_code == 200
        v = resp.json()
        balance = v["balance"]
        return balance
    
async def refresh_wallet_balances():
    for w in wallets:
        wallets[w]["balance_msats"] = await get_wallet_balance(w)
        logger.info(f"{w} balance: {wallets[w]['balance_msats']}")
    

def gen_keypair():
    private_key_hex = bytes.hex(secp256k1._gen_private_key())    
    private_key = secp256k1.PrivateKey(bytes.fromhex(private_key_hex))
    public_key = private_key.pubkey
    public_key_hex = public_key.serialize().hex()[2:]
    return {
        "priv": private_key_hex,
        "pub": public_key_hex
    }

async def create_nwc(w:str, desc:str, permissions:List[str], budgets:List[Dict[str, int]], expiration: 0):
    keypair = gen_keypair()
    api_key = wallets[w]["admin_key"]
    async with httpx.AsyncClient() as client:
        resp = await client.put(f'http://localhost:5002/nwcprovider/api/v1/nwc/{keypair["pub"]}?api-key={api_key}', json={
            "permissions": permissions,
            "description": desc,
            "expires_at": time.time()+expiration if expiration > 0 else 0,
            "budgets": budgets
        })
        assert resp.status_code == 201
        nwc = resp.json()

        async with httpx.AsyncClient() as client:
            resp = await client.get(f'http://localhost:5002/nwcprovider/api/v1/pairing/{keypair["priv"]}')
            assert resp.status_code == 200
            pairing = resp.json()
            return {
                "pubkey": keypair["pub"],
                "privkey": keypair["priv"],
                "pairing": pairing,
                "nwc": nwc
            }
    
    

async def delete_nwc(w:str, pubkey:str):

    api_key = wallets[w]["admin_key"]
    async with httpx.AsyncClient() as client:
        resp = await client.delete(f'http://localhost:5002/nwcprovider/api/v1/nwc/{pubkey}?api-key={api_key}')
        assert resp.status_code == 200
        return resp.json()
    

class NWCWallet :
    def __init__(self, pairing_url):
        # Extract from Pairing url nostr+walletconnect://provider_pub?relay=relay&secret=secret
        self.pairing_url = pairing_url
        self.provider_pub_hex = pairing_url.split("://")[1].split("?")[0]
        self.relay = pairing_url.split("relay=")[1].split("&")[0]
        self.secret = pairing_url.split("secret=")[1]
        self.ws = None
        self.connected = False
        self.shutdown = False
        self.event_queue = []
        self.subscriptions_count = 0
        self.sub_id=""
        self.private_key = secp256k1.PrivateKey(bytes.fromhex(self.secret))
        self.private_key_hex = self.secret
        self.public_key = self.private_key.pubkey
        self.public_key_hex = self.public_key.serialize().hex()[2:]

        
    async def close(self):
        self.shutdown = True
        await self.ws.close()
        self.connected = False

    async def _wait_for_connection(self):
        while not self.connected:
            await asyncio.sleep(0.2)

    async def start(self):
        asyncio.create_task(self._run())
        await self._wait_for_connection()
       


    def _is_shutting_down(self):
        return self.shutdown

    def _get_new_subid(self) -> str:        
        subid = "lnbitsnwcstest"+str(self.subscriptions_count)
        self.subscriptions_count += 1
        maxLength = 64
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        n = maxLength - len(subid)
        if n > 0:
            for i in range(n):
                subid += chars[random.randint(0, len(chars) - 1)]
        return subid
    
    async def _run(self):
        while True:
            try:
                async with websockets.connect(self.relay) as ws:
                    self.ws = ws
                    self.connected = True
                    self.sub_id = self._get_new_subid()
                    res_filter = {
                        "kinds": [23195],
                        "authors": [self.provider_pub_hex],
                        "since": int(time.time()) 
                    }
                    await self.ws.send(self._json_dumps(["REQ", self.sub_id, res_filter]))
                    while not self._is_shutting_down() and not ws.closed:
                        try:
                            reply = await ws.recv()
                            try:
                                await self._on_message(ws, reply)
                            except Exception as e:
                                pass
                        except Exception as e:
                            logger.debug("Error receiving message: " + str(e))
                            break
            except Exception as e:
                logger.debug("Error connecting to relay: " + str(e))
                pass
            self.connected = False
            if not self._is_shutting_down():
                await asyncio.sleep(0.2)
            else:
                break
     
    def _encrypt_content(self, content: str, pubkey_hex: str, iv_seed: Optional[int] = None) -> str:
        pubkey = secp256k1.PublicKey(
            bytes.fromhex("02" + pubkey_hex), True)
        shared = pubkey.tweak_mul(bytes.fromhex(
            self.private_key_hex)).serialize()[1:]
        if not iv_seed:
            iv = Random.new().read(AES.block_size)
        else:
            iv = hashlib.sha256(iv_seed.to_bytes(32, byteorder='big')).digest()
            iv = iv[:AES.block_size]
        aes = AES.new(shared, AES.MODE_CBC, iv)
        content_bytes = content.encode("utf-8")
        content_bytes = pad(content_bytes, AES.block_size)
        encrypted_b64 = base64.b64encode(
            aes.encrypt(content_bytes)).decode("ascii")
        ivB64 = base64.b64encode(iv).decode("ascii")
        encrypted_content = encrypted_b64 + "?iv=" + ivB64
        return encrypted_content

    def _decrypt_content(self, content: str, pubkey_hex: str) -> str:
        pubkey = secp256k1.PublicKey(
            bytes.fromhex("02" + pubkey_hex), True)
        shared = pubkey.tweak_mul(bytes.fromhex(
            self.private_key_hex)).serialize()[1:]
        (encrypted_content_b64, iv_b64) = content.split("?iv=")
        encrypted_content = base64.b64decode(
            encrypted_content_b64.encode("ascii"))
        iv = base64.b64decode(iv_b64.encode("ascii"))
        aes = AES.new(shared, AES.MODE_CBC, iv)
        decrypted_bytes = aes.decrypt(encrypted_content)
        decrypted_bytes = unpad(decrypted_bytes, AES.block_size)
        decrypted = decrypted_bytes.decode("utf-8")
        return decrypted
    
    async def _on_message(self, ws, message: str):
        logger.debug("Received message: " + message)
        msg = json.loads(message)
        if msg[0] == "EVENT":  # Event message
            sub_id = msg[1]
            event = msg[2]
            nwc_pubkey = event["pubkey"]        
            content = self._decrypt_content(event["content"], nwc_pubkey)
            content = json.loads(content)
            self.event_queue.append({
                "created_at": event["created_at"],
                "content": content,
                "result": content["result"] if "result" in content else None,
                "error": content["error"] if "error" in content else None,
                "method": content["result_type"],
                "tags": event["tags"]
            })

    def _json_dumps(self, data: Union[Dict, list]) -> str:        
        if isinstance(data, Dict):
            data = {k: v for k, v in data.items() if v is not None}
        return json.dumps(data, separators=(',', ':'), ensure_ascii=False)

    def _sign_event(self, event: Dict) -> Dict:
        signature_data = self._json_dumps([
            0,
            self.public_key_hex,
            event["created_at"],
            event["kind"],
            event["tags"],
            event["content"]
        ])

        event_id = hashlib.sha256(signature_data.encode()).hexdigest()
        event["id"] = event_id
        event["pubkey"] = self.public_key_hex
        signature = (self.private_key.schnorr_sign(
            bytes.fromhex(event_id), None, raw=True)).hex()
        event["sig"] = signature
        return event
    

    async def sendEvent(self, method,params):
        await self._wait_for_connection()
        event = {
            "created_at": int(time.time()),
            "kind": 23194,
            "tags":[
                ["p", self.provider_pub_hex],
            ],
            "content": json.dumps({
                "method": method,
                "params": params
            
            })
        }
        logger.debug("Sending event: " + str(event))
        event["content"] = self._encrypt_content(event["content"], self.provider_pub_hex)
        self._sign_event(event)
        logger.debug("Sending event (encrypted): " + str(event))
        await self.ws.send(self._json_dumps(["EVENT", event]))

    async def waitFor(self, result_type, callback=None, on_error_callback=None, timeout=10):
        now = time.time()
        while True:
            for i in range(len(self.event_queue)):
                e = self.event_queue[i]
                event_time = e["created_at"]
                if e["method"] == result_type:
                    if event_time > now - timeout:
                        if not callback or callback(e["result"], e["tags"]):
                            self.event_queue.pop(i)
                            if e["error"]:
                                if on_error_callback:
                                    on_error_callback(e["error"], e["tags"])
                                
                                return e["result"], e["tags"], e["error"]
                            else:
                                return e["result"], e["tags"], None
            await asyncio.sleep(1)
            if timeout > 0 and time.time() > now + timeout:
                raise Exception("Timeout")
            
                    

@pytest.mark.asyncio
async def test_create():
    await check_services()
    nwc = await create_nwc("wallet1", "test_create", ["pay"], [], 0)
    logger.info(nwc)
    assert nwc["nwc"]["data"]["expires_at"] == 0
    assert nwc["nwc"]["data"]["permissions"] == "pay"
    assert nwc["nwc"]["data"]["description"] == "test_create"
    assert nwc["nwc"]["data"]["last_used"] > time.time() - 10
    assert nwc["nwc"]["data"]["last_used"] < time.time() + 10
    assert nwc["nwc"]["data"]["created_at"] > time.time() - 10
    assert nwc["nwc"]["data"]["created_at"] < time.time() + 10
    assert len(nwc["nwc"]["budgets"]) == 0
        

@pytest.mark.asyncio
async def test_make_invoice():
    await check_services()
    nwc = await create_nwc("wallet1", "test_make_invoice", ["invoice"], [], 0)
    wallet1 = NWCWallet(nwc["pairing"])
    await wallet1.start()
    await wallet1.sendEvent("make_invoice", {"amount": 1, "description": "test 123", "expiry": 1000})
    result, tags, error = await wallet1.waitFor("make_invoice")
    logger.info(error)
    assert error , "Expected internal error, because amount is too low"

    await wallet1.sendEvent("make_invoice", {"amount": 123000, "description":"test 123", "expiry": 1000})
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error
    assert result["type"] == "incoming"
    assert result["description"] == "test 123"
    assert result["amount"] == 123000
    assert result["preimage"]
    assert result["created_at"] < time.time() + 10
    assert result["created_at"] > time.time() - 10
    assert result["expires_at"] < time.time() + 1000  + 10
    assert result["expires_at"] > time.time() 
    assert result["invoice"]

    invoice = result["invoice"]
    decoded_invoice = bolt11.decode(invoice)
    assert decoded_invoice.amount_msat == 123000
    
    await wallet1.close()
    

@pytest.mark.asyncio
async def test_lookup_invoice():
    await check_services()
    nwc = await create_nwc("wallet1", "test_lookup_invoice_make", ["invoice"], [], 0)
    nwc2 = await create_nwc("wallet1", "test_lookup_invoice_lookup", ["lookup"], [], 0)

    wallet1 = NWCWallet(nwc["pairing"])
    await wallet1.start()
 

    await wallet1.sendEvent("make_invoice", {"amount": 123000, "description": "test 123", "expiry": 1000})
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error
    assert result["type"] == "incoming"
    assert result["description"] == "test 123"
    assert result["amount"] == 123000
    assert result["preimage"]
    assert result["created_at"] < time.time() + 10
    assert result["created_at"] > time.time() - 10
    assert result["expires_at"] < time.time() + 1000 + 10
    assert result["expires_at"] > time.time()
    assert result["invoice"]

    wallet2 = NWCWallet(nwc2["pairing"])
    await wallet2.start()

    await wallet2.sendEvent("lookup_invoice", {"invoice": result["invoice"]})
    result, tags, error = await wallet2.waitFor("lookup_invoice")
    assert not error
    assert result["type"] == "incoming"
    assert result["description"] == "test 123"
    assert result["amount"] == 123000
    assert result["preimage"]
    assert result["created_at"] < time.time() + 10
    assert result["created_at"] > time.time() - 10
    assert result["expires_at"] < time.time() + 1000 + 10
    assert result["expires_at"] > time.time()
    assert result["invoice"]

    await wallet1.close()
    await wallet2.close()


@pytest.mark.asyncio
async def test_get_info():
    await check_services()
    nwc = await create_nwc("wallet1", "test_get_info", ["info"], [], 0)
    

    wallet1 = NWCWallet(nwc["pairing"])
    await wallet1.start()


    await wallet1.sendEvent("get_info", {})
    result, tags, error = await wallet1.waitFor("get_info")
    assert not error
    assert result["alias"] == "LNBits_NWC_SP"
    assert result["color"] == ""
    assert result["network"] == "mainnet"
    assert result["block_height"] == 0
    assert result["block_hash"] == ""
    assert result["methods"]  == ["get_info"]

    await wallet1.close()


@pytest.mark.asyncio
async def test_permisions():
    await check_services()
    nwc = await create_nwc("wallet1", "test_permisions1", ["info"], [], 0)
    nwc2 = await create_nwc("wallet1", "test_permisions2", [ "pay", "invoice"], [], 0)
    nwc3 = await create_nwc("wallet1", "test_permisions3", ["info" , "pay", "invoice"], [], 0)


    wallet1 = NWCWallet(nwc["pairing"])
    wallet2 = NWCWallet(nwc2["pairing"])
    wallet3 = NWCWallet(nwc3["pairing"])
    await wallet1.start()


    await wallet1.sendEvent("get_info", {})
    result, tags, error = await wallet1.waitFor("get_info")
    assert not error

    await wallet1.sendEvent("make_invoice", {
        "amount": 123000,
        "description": "test 123",
        "expiry": 1000
    })
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert error

    await wallet1.close()
    await wallet2.start()

    await wallet2.sendEvent("get_info", {})
    result, tags, error = await wallet2.waitFor("get_info")
    assert error

  
    await wallet2.sendEvent("make_invoice", {
        "amount": 123000,
        "description": "test 123",
        "expiry": 1000
    })
    result, tags, error = await wallet2.waitFor("make_invoice")
    assert not error

    await wallet2.close()
    await wallet3.start()

    await wallet3.sendEvent("get_info", {})
    result, tags, error = await wallet3.waitFor("get_info")
    assert not error
    assert "make_invoice" in result["methods"]
    assert "pay_invoice" in result["methods"]
    assert "get_info" in result["methods"]

    await wallet3.close()


@pytest.mark.asyncio
async def test_pay_invoice_and_balance():
    await check_services()
    nwc = await create_nwc("wallet1", "test_pay_invoice_and_balance", ["invoice", "balance"], [], 0)
    nwc2 = await create_nwc("wallet2", "test_pay_invoice_and_balance", ["pay", "balance"], [], 0)


    wallet1 = NWCWallet(nwc["pairing"])
    await wallet1.start()

    
    await refresh_wallet_balances()
    wallet1_balance = wallets["wallet1"]["balance_msats"]
    wallet2_balance = wallets["wallet2"]["balance_msats"]


    await wallet1.sendEvent("make_invoice", {
        "amount": 123000,
        "description": "test 123"
    })

    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error
    assert result["invoice"]

    invoice = result["invoice"]
    wallet2 = NWCWallet(nwc2["pairing"])
    await wallet2.start()

    await wallet2.sendEvent("pay_invoice", {
        "invoice": invoice
    })
    result, tags, error = await wallet2.waitFor("pay_invoice")
    assert not error
    assert result["preimage"]

    await refresh_wallet_balances()
    wallet1_balance_new = wallets["wallet1"]["balance_msats"]
    wallet2_balance_new = wallets["wallet2"]["balance_msats"]

    assert wallet1_balance_new == wallet1_balance + 123000
    assert wallet2_balance_new == wallet2_balance - 123000

    await wallet1.sendEvent("get_balance", {})
    result, tags, error = await wallet1.waitFor("get_balance")
    assert not error
    assert result["balance"] == wallet1_balance_new

    await wallet2.sendEvent("get_balance", {})
    result, tags, error = await wallet2.waitFor("get_balance")
    assert not error
    assert result["balance"] == wallet2_balance_new

    await wallet1.close()
    await wallet2.close()


@pytest.mark.asyncio
async def test_multi_pay_invoices():
    nwc1 = await create_nwc("wallet1", "test_multi_pay_invoices", ["invoice", "pay", "balance"], [], 0)
    nwc2 = await create_nwc("wallet2", "test_multi_pay_invoices", ["invoice", "pay", "balance"], [], 0)
    nwc3 = await create_nwc("wallet3", "test_multi_pay_invoices", ["invoice", "pay", "balance"], [], 0)
    
    wallet1 = NWCWallet(nwc1["pairing"])
    wallet2 = NWCWallet(nwc2["pairing"])
    wallet3 = NWCWallet(nwc3["pairing"])

    await wallet1.start()
    await wallet2.start()
    await wallet3.start()

    await refresh_wallet_balances()
    wallet1_balance = wallets["wallet1"]["balance_msats"]
    wallet2_balance = wallets["wallet2"]["balance_msats"]
    wallet3_balance = wallets["wallet3"]["balance_msats"]

    await wallet1.sendEvent("make_invoice", {
        "amount": 123000,
        "description": "test 123"
    })

    result, tags, error = await wallet1.waitFor("make_invoice") 
    assert not error
    assert result["invoice"]
    invoice1 = result["invoice"]

    await wallet1.sendEvent("make_invoice", {
        "amount": 123000,
        "description": "test 123"
    })
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error
    assert result["invoice"]
    invoice2 = result["invoice"]

    await wallet2.sendEvent("make_invoice", {
        "amount": 123000,
        "description": "test 123"
    })
    result, tags, error = await wallet2.waitFor("make_invoice")
    assert not error
    assert result["invoice"]
    invoice3 = result["invoice"]

    await wallet3.sendEvent("multi_pay_invoice", {
        "invoices":[
            {"id":"invoice1", "invoice": invoice1, "amount": 123000},
            {"id":"invoice2", "invoice": invoice2, "amount": 123000},
            { "invoice": invoice3}
        ]
    })
    result, tags, error = await wallet3.waitFor("multi_pay_invoice")
    assert not error
    d_tag = [t[1] for t in tags if t[0] == "d"][0]
    if d_tag=="invoice1":
        assert result["preimage"]
    elif d_tag=="invoice2":
        assert result["preimage"]
    elif d_tag==invoice3:
        assert result["preimage"]
    else:
        assert False
    

    await refresh_wallet_balances()
    wallet1_balance_new = wallets["wallet1"]["balance_msats"]
    wallet2_balance_new = wallets["wallet2"]["balance_msats"]
    wallet3_balance_new = wallets["wallet3"]["balance_msats"]

    assert wallet1_balance_new == wallet1_balance + 123000 + 123000
    assert wallet2_balance_new == wallet2_balance + 123000
    assert wallet3_balance_new == wallet3_balance - 123000 - 123000  - 123000



    await wallet1.sendEvent("get_balance", {})
    result, tags, error = await wallet1.waitFor("get_balance")
    assert not error
    assert result["balance"] == wallet1_balance_new

    await wallet2.sendEvent("get_balance", {})
    result, tags, error = await wallet2.waitFor("get_balance")
    assert not error
    assert result["balance"] == wallet2_balance_new

    await wallet3.sendEvent("get_balance", {})
    result, tags, error = await wallet3.waitFor("get_balance")
    assert not error
    assert result["balance"] == wallet3_balance_new

    await wallet1.close()
    await wallet2.close()
    await wallet3.close()
        

                            



@pytest.mark.asyncio
async def test_insufficient_balance():
    nwc1 = await create_nwc("wallet1", "test_insufficient_balance", ["invoice", "pay", "balance"], [], 0)
    nwc2 = await create_nwc("wallet2", "test_insufficient_balance", ["invoice", "pay", "balance"], [], 0)
    await refresh_wallet_balances()
    wallet1_balance = wallets["wallet1"]["balance_msats"]
    amount_to_spend = wallet1_balance + 1000
    wallet1 = NWCWallet(nwc1["pairing"])
    wallet2 = NWCWallet(nwc2["pairing"])
    await wallet1.start()
    await wallet2.start()

    await wallet2.sendEvent("make_invoice", {
        "amount": amount_to_spend,
        "description": "test 123"
    })
    result, tags, error = await wallet2.waitFor("make_invoice")
    assert not error
    assert result["invoice"]
    invoice = result["invoice"]

    await wallet1.sendEvent("pay_invoice", {
        "invoice": invoice
    })
    result, tags, error = await wallet1.waitFor("pay_invoice")
    logger.info(error)
    logger.info(result)
    logger.info(amount_to_spend)

    assert error
    # The proper error code should be INSUFFICIENT_BALANCE
    # but we use the more generic PAYMENT_FAILED in our implementation for simplicity
    #assert error["code"] == "INSUFFICIENT_BALANCE" 
    assert error["code"] == "PAYMENT_FAILED"
    
    await wallet1.close()
    await wallet2.close()



@pytest.mark.asyncio
async def test_expiry():
    nwc = await create_nwc("wallet3", "test_expiry", ["invoice", "pay", "balance"], [], 1)
    await asyncio.sleep(2)
    wallet3 = NWCWallet(nwc["pairing"])
    await wallet3.start()
    await wallet3.sendEvent("make_invoice", {
        "amount": 123000,
        "description": "test 123"
    })
    result, tags, error = await wallet3.waitFor("make_invoice")
    assert error
    assert error["code"] == "UNAUTHORIZED" , "Expected UNAUTHORIZED error, because the NWC expired"
    await wallet3.close()




@pytest.mark.asyncio
async def test_budget():
    nwc1 = await create_nwc("wallet1", "test_expiry", ["invoice", "pay", "balance"], [], 0)
    nwc3 = await create_nwc("wallet3", "test_expiry", ["invoice", "pay", "balance"], [
        {
            "budget_msats": 100000,
            "refresh_window": 3600,
            "created_at": time.time()
        }
    ], 0)
    wallet1 = NWCWallet(nwc1["pairing"])
    wallet3 = NWCWallet(nwc3["pairing"])
    await wallet3.start()
    await wallet1.start()
    await wallet1.sendEvent("make_invoice", {
        "amount": 101000,
        "description": "Invalid"
    })
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error

    await wallet3.sendEvent("pay_invoice", {
        "invoice": result["invoice"]
    })
    result, tags, error = await wallet3.waitFor("pay_invoice")
    assert error
    assert error["code"] == "QUOTA_EXCEEDED" , "Expected QUOTA_EXCEEDED error, because the budget was exceeded"

    await wallet1.sendEvent("make_invoice", {
        "amount": 99000,
        "description": "Valid"
    })
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error

    await wallet3.sendEvent("pay_invoice", {
        "invoice": result["invoice"]
    })
    result, tags, error = await wallet3.waitFor("pay_invoice")
    assert not error, "Expected successful payment, because the budget was not exceeded"
    assert result["preimage"]

    await wallet1.sendEvent("make_invoice", {
        "amount": 100000-99000+1000,
        "description": "Invalid"
    })

    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error

    await wallet3.sendEvent("pay_invoice", {
        "invoice": result["invoice"]
    })
    result, tags, error = await wallet3.waitFor("pay_invoice")
    assert error
    assert error["code"] == "QUOTA_EXCEEDED" , "Expected QUOTA_EXCEEDED error, because the budget was exceeded"

    await wallet3.close()
    await wallet1.close()


@pytest.mark.asyncio
async def test_budget_refresh():
    nwc1 = await create_nwc("wallet1", "test_expiry", ["invoice", "pay", "balance"], [], 0)
    nwc3 = await create_nwc("wallet3", "test_expiry", ["invoice", "pay", "balance"], [   {
            "budget_msats": 100000,
            "refresh_window": 5,
            "created_at": time.time()
        }], 0)
    wallet1 = NWCWallet(nwc1["pairing"])
    wallet3 = NWCWallet(nwc3["pairing"])
    await wallet3.start()
    await wallet1.start()
    await wallet1.sendEvent("make_invoice", {
        "amount": 100000,
        "description": "Invalid"
    })
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error

    await wallet1.sendEvent("make_invoice", {
        "amount": 100000,
        "description": "Invalid"
    })
    result2, tags, error = await wallet1.waitFor("make_invoice")
    assert not error

    await wallet3.sendEvent("pay_invoice", {
        "invoice": result["invoice"]
    })
    result, tags, error = await wallet3.waitFor("pay_invoice")
    assert not error, "Expected successful payment, because the budget was not exceeded"


    await wallet3.sendEvent("pay_invoice", {
        "invoice": result2["invoice"]
    })
    result, tags, error = await wallet3.waitFor("pay_invoice")
    assert error
    assert error["code"] == "QUOTA_EXCEEDED", "Expected QUOTA_EXCEEDED error, because the budget was exceeded"

    await asyncio.sleep(5)
    await wallet1.sendEvent("make_invoice", {
        "amount": 100000,
        "description": "Valid"
    })
    result, tags, error = await wallet1.waitFor("make_invoice")
    assert not error


    await wallet3.sendEvent("pay_invoice", {
        "invoice": result["invoice"]
    })
    result, tags, error = await wallet3.waitFor("pay_invoice")
    assert not error, "Expected successful payment, because the budget was refreshed"

    await wallet3.close()
    await wallet1.close()



    
