window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  data: function () {
    return {
      selectedWallet: 'all',
      dialogWallet: null,
      nodePermissions: [],
      nwcEntries: [],
      nwcsTable: {
        columns: [
          {
            name: 'wallet_name',
            align: 'left',
            label: 'Wallet',
            field: 'wallet_name'
          },
          {
            name: 'description',
            align: 'left',
            label: 'Description',
            field: 'description'
          },
          {
            name: 'lud16',
            align: 'left',
            label: 'Lightning Address',
            field: 'lud16'
          },
          {name: 'status', align: 'left', label: 'Status', field: 'status'},
          {
            name: 'last_used',
            align: 'left',
            label: 'Last used',
            field: 'last_used'
          },
          {
            name: 'created_at',
            align: 'left',
            label: 'Created',
            field: 'created_at'
          },
          {
            name: 'expires_at',
            align: 'left',
            label: 'Expires',
            field: 'expires_at'
          }
        ],
        pagination: {
          rowsPerPage: 0
        }
      },
      connectDialog: {
        show: false,
        data: {}
      },
      pairingDialog: {
        show: false,
        data: {
          pairingUrl: ''
        }
      },
      pairingQrDialog: {
        show: false,
        data: {
          pairingUrl: ''
        }
      },
      connectionInfoDialog: {
        show: false,
        data: {}
      },
      lud16OptionsAll: [],
      lud16Loading: false
    }
  },

  computed: {
    walletOptions() {
      // Count connections per wallet
      const counts = {}
      for (const entry of this.nwcEntries) {
        if (entry.wallet_id) {
          counts[entry.wallet_id] = (counts[entry.wallet_id] || 0) + 1
        }
      }

      const options = [
        {label: 'All Wallets', value: 'all', count: null}
      ]
      for (const wallet of this.g.user.wallets) {
        options.push({
          label: wallet.name,
          value: wallet.id,
          count: counts[wallet.id] || 0
        })
      }
      return options
    },
    visibleColumns() {
      if (this.selectedWallet === 'all') {
        return this.nwcsTable.columns.map(c => c.name)
      }
      return this.nwcsTable.columns.filter(c => c.name !== 'wallet_name').map(c => c.name)
    }
  },
  methods: {
    showConnectDialog() {
      // When "All Wallets" is selected, default dialog wallet to first wallet
      if (this.selectedWallet === 'all') {
        if (this.g.user.wallets && this.g.user.wallets.length > 0) {
          this.dialogWallet = this.g.user.wallets[0].id
        } else {
          Quasar.Notify.create({
            type: 'negative',
            message: 'No wallets found'
          })
          return
        }
      } else {
        this.dialogWallet = this.selectedWallet
      }
      this.connectDialog.show = true
    },
    openConnectionInfoDialog(data) {
      this.connectionInfoDialog.data = data
      this.connectionInfoDialog.show = true
    },
    closeConnectionInfoDialog() {
      this.connectionInfoDialog.show = false
    },
    openPairingUrl() {
      const url = this.pairingDialog.data.pairingUrl
      if (url) window.open(url, '_blank')
    },
    go(url) {
      window.open(url, '_blank')
    },
    switchToWallet(walletId) {
      // Switch to the selected wallet in the dropdown
      this.selectedWallet = walletId
    },
    async copyPairingUrl() {
      const url = this.pairingDialog.data.pairingUrl
      if (url) {
        try {
          await navigator.clipboard.writeText(url)
          Quasar.Notify.create({
            type: 'positive',
            message: 'URL copied to clipboard'
          })
        } catch (err) {
          Quasar.Notify.create({
            type: 'negative',
            message: 'Failed to copy URL.'
          })
        }
      }
    },
    showPairingQR() {
      this.pairingQrDialog.data.pairingUrl = this.pairingDialog.data.pairingUrl
      this.pairingQrDialog.show = true
    },
    closePairingQrDialog() {
      this.pairingQrDialog.show = false
    },
    loadConnectDialogData() {
      this.connectDialog.data = {
        description: '',
        expires_at: Date.now() + 1000 * 60 * 60 * 24 * 7,
        neverExpires: true,
        permissions: [],
        budgets: [],
        lud16: ''
      }
      for (const permission of this.nodePermissions) {
        this.connectDialog.data.permissions.push({
          key: permission.key,
          name: permission.name,
          value: permission.value
        })
      }
      this.lud16OptionsAll = []
      this.loadLightningAddresses()
    },
    getDialogWallet() {
      for (let i = 0; i < this.g.user.wallets.length; i++) {
        if (this.g.user.wallets[i].id === this.dialogWallet) {
          return this.g.user.wallets[i]
        }
      }
      return null
    },
    async loadLightningAddresses() {
      const wallet = this.getDialogWallet()
      if (!wallet) {
        this.lud16OptionsAll = []
        return
      }
      this.lud16Loading = true
      try {
        const response = await LNbits.api.request(
          'GET',
          '/nwcprovider/api/v1/lnaddresses',
          wallet.adminkey
        )
        if (response.data && response.data.length > 0) {
          this.lud16OptionsAll = response.data.map(addr => ({
            label: addr.description || addr.username,
            value: addr.address
          }))
        } else {
          this.lud16OptionsAll = []
        }
      } catch (error) {
        console.warn('Could not load lightning addresses:', error)
        this.lud16OptionsAll = []
      } finally {
        this.lud16Loading = false
      }
    },
    deleteBudget(index) {
      this.connectDialog.data.budgets.splice(index, 1)
    },
    addBudget() {
      this.connectDialog.data.budgets.push({
        budget_sats: 1000,
        used_budget_sats: 0,
        created_at: new Date(new Date().setHours(0, 0, 0, 0)).getTime() / 1000,
        expiration: 'never'
      })
    },
    closeConnectDialog() {
      this.connectDialog.show = false
      this.loadConnectDialogData()
    },
    getWallet: function () {
      let wallet = undefined
      for (let i = 0; i < this.g.user.wallets.length; i++) {
        if (this.g.user.wallets[i].id == this.selectedWallet) {
          wallet = this.g.user.wallets[i]
          break
        }
      }
      return wallet
    },
    async generateKeyPair() {
      while (!window.NobleSecp256k1) {
        await new Promise(resolve => setTimeout(resolve, 1))
      }
      const privKeyBytes = window.NobleSecp256k1.utils.randomPrivateKey()
      const pubKeyBytes = window.NobleSecp256k1.getPublicKey(privKeyBytes)
      const out = {
        privKeyBytes: privKeyBytes,
        pubKeyBytes: pubKeyBytes,
        privKey: window.NobleSecp256k1.etc.bytesToHex(privKeyBytes),
        pubKey: window.NobleSecp256k1.etc.bytesToHex(pubKeyBytes.slice(1))
      }
      return out
    },
    deleteNWC: async function (row) {
      Quasar.Dialog.create({
        title: 'Confirm Deletion',
        message: 'This will disconnect the app. Are you sure?',
        cancel: true,
        persistent: true
      })
        .onOk(async () => {
          try {
            // When in "All Wallets" view, use the wallet_id from the row
            let adminkey
            if (this.selectedWallet === 'all') {
              const wallet = this.g.user.wallets.find(w => w.id === row.wallet_id)
              if (!wallet) {
                Quasar.Notify.create({
                  type: 'negative',
                  message: 'Could not find wallet for this connection'
                })
                return
              }
              adminkey = wallet.adminkey
            } else {
              const wallet = this.getWallet()
              adminkey = wallet.adminkey
            }
            const response = await LNbits.api.request(
              'DELETE',
              `/nwcprovider/api/v1/nwc/${row.pubkey}`,
              adminkey
            )
            this.loadNwcs()
            Quasar.Notify.create({
              type: 'positive',
              message: 'Connection removed'
            })
          } catch (error) {
            LNbits.utils.notifyApiError(error)
          }
        })
        .onCancel(() => {
          // User canceled the operation
        })
    },
    loadNwcs: async function () {
      // Get any wallet's adminkey for API calls (needed for "all" view)
      let adminkey
      if (this.selectedWallet === 'all') {
        if (this.g.user.wallets && this.g.user.wallets.length > 0) {
          adminkey = this.g.user.wallets[0].adminkey
        } else {
          this.nwcs = []
          this.nwcEntries = []
          return
        }
      } else {
        const wallet = this.getWallet()
        if (!wallet) {
          this.nwcs = []
          this.nwcEntries = []
          return
        }
        adminkey = wallet.adminkey
      }

      try {
        const endpoint = this.selectedWallet === 'all'
          ? '/nwcprovider/api/v1/nwc/all?include_expired=true&calculate_spent_budget=true'
          : '/nwcprovider/api/v1/nwc?include_expired=true&calculate_spent_budget=true'
        const response = await LNbits.api.request(
          'GET',
          endpoint,
          adminkey
        )
        this.nwcs = response.data
      } catch (error) {
        this.nwcs = []
      }
      try {
        const response = await LNbits.api.request(
          'GET',
          '/nwcprovider/api/v1/permissions',
          adminkey
        )
        const permissions = []
        for (const [key, value] of Object.entries(response.data)) {
          permissions.push({
            key: key,
            name: value.name,
            value: value.default
          })
        }
        this.nodePermissions = permissions
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
      this.loadConnectDialogData()
      const newTableEntries = []
      for (const nwc of this.nwcs) {
        const t = Quasar.date.formatDate(
          new Date(nwc.data.created_at * 1000),
          'YYYY-MM-DD HH:mm'
        )
        const e =
          nwc.data.expires_at > 0
            ? Quasar.date.formatDate(
                new Date(nwc.data.expires_at * 1000),
                'YYYY-MM-DD HH:mm'
              )
            : 'Never'
        const l = Quasar.date.formatDate(
          new Date(nwc.data.last_used * 1000),
          'YYYY-MM-DD HH:mm'
        )
        const nwcTableEntry = {
          description: nwc.data.description,
          lud16: nwc.data.lud16 || '-',
          created_at: t,
          expires_at: e,
          last_used: l,
          pubkey: nwc.data.pubkey,
          permissions: nwc.data.permissions,
          budgets: [],
          status: 'Active',
          wallet_id: nwc.wallet_id || null,
          wallet_name: nwc.wallet_name || ''
        }
        if (
          nwc.data.expires_at > 0 &&
          nwc.data.expires_at < new Date().getTime() / 1000
        ) {
          nwcTableEntry.status = 'Expired'
        }
        for (const budget of nwc.budgets) {
          const createdAt = Quasar.date.formatDate(
            new Date(budget.created_at * 1000),
            'YYYY-MM-DD HH:mm'
          )
          let refreshWindow = budget.refresh_window
          if (refreshWindow <= 0) {
            refreshWindow = 'Never'
          } else if (refreshWindow == 60 * 60 * 24) {
            refreshWindow = 'Daily'
          } else if (refreshWindow == 60 * 60 * 24 * 7) {
            refreshWindow = 'Weekly'
          } else if (refreshWindow == 60 * 60 * 24 * 30) {
            refreshWindow = 'Monthly'
          } else if (refreshWindow == 60 * 60 * 24 * 365) {
            refreshWindow = 'Yearly'
          }
          nwcTableEntry.budgets.push({
            budget_sats: budget.budget_msats / 1000,
            used_budget_sats: budget.used_budget_msats / 1000,
            created_at: createdAt,
            refresh_window: refreshWindow
          })
        }
        newTableEntries.push(nwcTableEntry)
      }
      // Sort by wallet name when showing all wallets
      if (this.selectedWallet === 'all') {
        newTableEntries.sort((a, b) => a.wallet_name.localeCompare(b.wallet_name))
      }
      this.nwcEntries = newTableEntries
    },
    closePairingDialog() {
      this.pairingDialog.show = false
    },
    getLud16Value() {
      const lud16 = this.connectDialog.data.lud16
      return lud16 && lud16.trim() ? lud16.trim() : null
    },
    async showPairingDialog(secret, lud16) {
      let url = `/nwcprovider/api/v1/pairing/${secret}`
      if (lud16) {
        url += `?lud16=${encodeURIComponent(lud16)}`
      }
      let response = await LNbits.api.request('GET', url)
      this.pairingDialog.data.pairingUrl = response.data
      this.pairingDialog.show = true
    },
    async confirmConnectDialog() {
      const keyPair = await this.generateKeyPair()
      // Save lud16 before dialog closes (closeConnectDialog resets it)
      const lud16 = this.getLud16Value()
      // timestamp
      let expires_at = 0
      if (!this.connectDialog.data.neverExpires) {
        expires_at =
          new Date(this.connectDialog.data.expires_at).getTime() / 1000
      }
      const data = {
        permissions: [],
        description: this.connectDialog.data.description,
        expires_at: expires_at,
        budgets: [],
        lud16: lud16
      }
      for (const permission of this.connectDialog.data.permissions) {
        if (permission.value) data.permissions.push(permission.key)
      }
      for (const budget of this.connectDialog.data.budgets) {
        const budget_msats = budget.budget_sats * 1000
        let refresh_window = 0
        switch (budget.expiry) {
          case 'Daily':
            refresh_window = 60 * 60 * 24
            break
          case 'Weekly':
            refresh_window = 60 * 60 * 24 * 7
            break
          case 'Monthly':
            refresh_window = 60 * 60 * 24 * 30
            break
          case 'Yearly':
            refresh_window = 60 * 60 * 24 * 365
            break
          case 'Never':
            refresh_window = 0
            break
        }
        data.budgets.push({
          budget_msats: budget_msats,
          refresh_window: refresh_window,
          created_at: new Date(new Date().setHours(0, 0, 0, 0)).getTime() / 1000
        })
      }
      // Use dialogWallet for creating connections (handles "All Wallets" case)
      const wallet = this.getDialogWallet()
      if (!wallet) {
        Quasar.Notify.create({
          type: 'negative',
          message: 'Select a wallet first'
        })
        return
      }

      try {
        const response = await LNbits.api.request(
          'PUT',
          '/nwcprovider/api/v1/nwc/' + keyPair.pubKey,
          wallet.adminkey,
          data
        )
        this.closeConnectDialog()
        if (
          !response.data ||
          !response.data.data ||
          !response.data.data.pubkey
        ) {
          LNbits.utils.notifyApiError('Error creating nwc pairing')
          return
        }
        this.showPairingDialog(keyPair.privKey, lud16)
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
      this.loadNwcs()
    }
  },

  created: function () {
    // Default to "All Wallets" to show all connections
    this.selectedWallet = 'all'
    // Load connections on initial page load
    this.loadNwcs()
  },
  watch: {
    selectedWallet(newValue, oldValue) {
      this.loadNwcs()
    },
    dialogWallet(newValue, oldValue) {
      // Reload lightning addresses when dialog wallet changes
      if (newValue && this.connectDialog.show) {
        this.loadLightningAddresses()
      }
    }
  }
})
