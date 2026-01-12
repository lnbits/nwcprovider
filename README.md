# NWC Service Provider Extension for [LNbits](https://github.com/lnbits/lnbits)

Easily connect your LNbits wallets via [NWC](https://nwc.dev/).

## Installation

Install the extension via the .env file or through the admin UI on your LNbits server. More details can be found [here](https://github.com/lnbits/lnbits/wiki/LNbits-Extensions).

# Configuration

The **LNbits NWC Service Provider** requires a one-time setup before it can be used.  
It relies on a Nostr relay, which can be either:

- The **LNbits Nostrclient** browser extension
- A **third-party Nostr relay** of your choice

## Relay Configuration

Before you can start using the extension, you need to configure a Nostr relay.

### Option 1: Use a third-party Nostr relay (recommended)

This is the easiest option for most users. It allows you to run LNbits on a private network while connecting to NWC apps through a public Nostr relay.

1. Choose a Nostr relay that supports NWC connections.
2. Open the **NWC Service Provider settings** (gear icon in the top-right corner).
   1. Enter your chosen relay URL in the **Nostr Relay URL** field (e.g. `wss://relay.nostrconnect.com`).
   2. Click **Save**.

### Option 2: Use the LNbits Nostrclient extension

> **Note:** This option only works if your LNbits instance is publicly accessible on the internet. Refer to the [nostrclient documentation](https://github.com/lnbits/nostrclient) for more information.

1. Install the **Nostrclient** extension in your browser.
2. Open the extension.
   1. Add at least one relay (e.g. `wss://relay.nostrconnect.com` is a good choice for NWC connections).
   2. Open **Settings** and enable **Expose Public WebSocket**.

---

## Connecting a NWC App

1. In the **NWC Service Provider** extension, select the wallet you want to connect.
2. Click the **+** button to add a new connection.
3. Enter a description, expiry date (optional), permissions, and limits.
4. Click **Connect** to create the connection.
5. Use the generated **pairing URL** or **QR code** to connect your chosen app.

---

# Extension Configuration

The "Configuration" page of the NWC Service Provider extension can be accessed by clicking the gear icon in the top-right corner of the extension page.

### Configuration Options:

| Key                  | Description                                                                                                                                                                                                 | Default                         |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| relay                | URL of the nostr relay for dispatching and receiving NWC events. Use public relays or a custom one. Specify `nostrclient` to connect to the [nostrclient extension](https://github.com/lnbits/nostrclient). | nostrclient                     |
| provider_key         | Nostr secret key of the NWC Service Provider.                                                                                                                                                               | Random key generated on install |
| relay_alias          | Relay URL to display in pairing URLs. Set if different from `relay`.                                                                                                                                        | Empty (uses the `relay` value)  |
| handle_missed_events | Number of seconds to look back for processing events missed while offline. Setting it to 0 disables this functionality.                                                                                     | 0                               |

> [!WARNING]
>
> Do not change `handle_missed_events` from its default value of `0` unless you fully understand its implications.
> While a non-zero value may improve service quality under unstable conditions (e.g., poor connectivity or unreliable power), it can also lead to unexpected behavior.
> For example, in shared or community lnbits instances, where users are unaware of this functionality, they might assume a payment has failed and attempt to pay a new invoice with a different wallet, only for the instance to come back online and process the original payment request, potentially leading to duplicate payments.
>
> For this reason, unless you are trying to tackle this specific issue, it is recommended to leave this setting at `0`.
