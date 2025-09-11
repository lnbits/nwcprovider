window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  delimiters: ['${', '}'],
  data: function () {
    return {
      config: {},
      columns: [
        {
          name: 'key',
          required: true,
          label: 'Key',
          align: 'left',
          field: row => row.key,
          sortable: true
        },
        {
          name: 'value',
          required: true,
          label: 'Value',
          align: 'left',
          field: row => row.value,
          sortable: true
        }
      ]
    }
  },

  methods: {
    fetchConfig() {
      this.config = {}
      LNbits.api
        .request(
          'GET',
          '/nwcprovider/api/v1/config',
          this.g.user.wallets[0].adminkey
        )
        .then(response => {
          this.config = response.data
          console.log('Config fetched:', this.config)
        })
        .catch(function (error) {
          console.error('Error fetching config:', error)
        })
    },
    async saveConfig() {
      const data = {}
      for (const [key, value] of Object.entries(this.config)) {
        data[key] = value
      }
      console.log('Saving config:', data)
      try {
        const response = await LNbits.api.request(
          'POST',
          '/nwcprovider/api/v1/config',
          this.g.user.wallets[0].adminkey,
          data
        )
        Quasar.Notify.create({
          type: 'positive',
          message: 'Config saved!'
        })
        Quasar.Notify.create({
          type: 'warning',
          message:
            'You need to restart the server for the changes to take effect!'
        })
      } catch (error) {
        Quasar.Notify.create({
          type: 'negative',
          message: 'Error saving config: ' + String(error)
        })
        console.error('Error saving config:', error)
      }
    }
  },

  created: function () {
    this.fetchConfig()
  }
})
