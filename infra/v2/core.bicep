// Confidant v2 — persistent control plane (deployed into confidant-core-rg).
// VNet + NSG, analytics storage (tables + private endpoint), Key Vault + CMK + DES,
// Compute Gallery + image definition, Function app shell (code deployed separately).

param location string
param sandboxRgName string

@description('Deployer public IP allowed to SSH into sandboxes (debug only, removable). Empty = no SSH rule.')
param deployerIp string = ''

var suffix = uniqueString(subscription().subscriptionId, resourceGroup().id)
var storageName = 'stconfcore${take(suffix, 12)}'
var funcStorageName = 'stconffunc${take(suffix, 12)}'
var keyVaultName = 'kv-conf-${take(suffix, 12)}'
var functionAppName = 'func-confidant-${take(suffix, 8)}'

// Built-in role definition IDs
var roleKvCryptoServiceEncryptionUser = 'e147488a-f6f5-4113-8e2d-b22465e65bf6'
var roleStorageTableDataContributor = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var roleReader = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

// ---------------------------------------------------------------- networking

resource nsgSandbox 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-sandbox'
  location: location
  properties: {
    securityRules: concat(
      [
        {
          name: 'AllowHttpsInFromInternet'
          properties: {
            priority: 100
            direction: 'Inbound'
            access: 'Allow'
            protocol: 'Tcp'
            sourceAddressPrefix: 'Internet'
            sourcePortRange: '*'
            destinationAddressPrefix: '*'
            destinationPortRange: '443'
          }
        }
      ],
      empty(deployerIp) ? [] : [
        {
          // REMOVABLE: debug-only SSH from the deployer's public IP.
          // Delete this rule once the image is stable:
          //   az network nsg rule delete -g confidant-core-rg --nsg-name nsg-sandbox -n AllowSshFromDeployerDebugOnly
          name: 'AllowSshFromDeployerDebugOnly'
          properties: {
            priority: 110
            direction: 'Inbound'
            access: 'Allow'
            protocol: 'Tcp'
            sourceAddressPrefix: '${deployerIp}/32'
            sourcePortRange: '*'
            destinationAddressPrefix: '*'
            destinationPortRange: '22'
          }
        }
      ],
      [
        {
          name: 'DenyAllOtherInbound'
          properties: {
            priority: 4000
            direction: 'Inbound'
            access: 'Deny'
            protocol: '*'
            sourceAddressPrefix: '*'
            sourcePortRange: '*'
            destinationAddressPrefix: '*'
            destinationPortRange: '*'
          }
        }
        // ------------------------------------------------------- outbound
        {
          name: 'AllowVnetOut'
          properties: {
            // Private endpoint traffic (storage tables) and nothing else in-VNet
            // can actually answer (inbound deny-all keeps VM<->VM closed).
            priority: 100
            direction: 'Outbound'
            access: 'Allow'
            protocol: '*'
            sourceAddressPrefix: 'VirtualNetwork'
            sourcePortRange: '*'
            destinationAddressPrefix: 'VirtualNetwork'
            destinationPortRange: '*'
          }
        }
        {
          name: 'AllowAzureDnsOut'
          properties: {
            // Azure-provided recursive resolver (link-local, required for
            // privatelink zone resolution).
            priority: 110
            direction: 'Outbound'
            access: 'Allow'
            protocol: '*'
            sourceAddressPrefix: '*'
            sourcePortRange: '*'
            destinationAddressPrefix: '168.63.129.16/32'
            destinationPortRange: '53'
          }
        }
        {
          name: 'AllowHttpHttpsOutAcmeCarveout'
          properties: {
            // CARVE-OUT: ACME/Let's Encrypt certificate issuance at first boot
            // (HTTP-01/directory over 80+443). See OPERATIONS.md for how to
            // close this after boot if desired.
            priority: 120
            direction: 'Outbound'
            access: 'Allow'
            protocol: 'Tcp'
            sourceAddressPrefix: '*'
            sourcePortRange: '*'
            destinationAddressPrefix: 'Internet'
            destinationPortRanges: [ '80', '443' ]
          }
        }
        {
          name: 'DenyAllOtherOutbound'
          properties: {
            priority: 4000
            direction: 'Outbound'
            access: 'Deny'
            protocol: '*'
            sourceAddressPrefix: '*'
            sourcePortRange: '*'
            destinationAddressPrefix: '*'
            destinationPortRange: '*'
          }
        }
      ]
    )
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-confidant-core'
  location: location
  properties: {
    addressSpace: { addressPrefixes: [ '10.20.0.0/16' ] }
    subnets: [
      {
        name: 'snet-sandbox'
        properties: {
          addressPrefix: '10.20.1.0/24'
          networkSecurityGroup: { id: nsgSandbox.id }
        }
      }
      {
        name: 'snet-endpoints'
        properties: {
          addressPrefix: '10.20.2.0/24'
        }
      }
    ]
  }
}

// ------------------------------------------------------------------ storage

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    // Shared keys and SAS disabled: data plane is Entra RBAC only.
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    // Pragmatic networking choice (documented in OPERATIONS.md):
    // public access stays ENABLED with defaultAction Allow because the
    // consumption Function app (outside the VNet, no fixed egress) must reach
    // the tables and is NOT covered by the "trusted Azure services" bypass.
    // Data is protected by Entra RBAC (keys/SAS disabled above). In-VNet VMs
    // use the private endpoint below, so sandbox traffic never leaves the VNet.
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource tableInsights 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'insights'
}

resource tableSessions 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'sessions'
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.table.core.windows.net'
  location: 'global'
}

resource dnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: privateDnsZone
  name: 'link-vnet-confidant-core'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource peTable 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${storageName}-table'
  location: location
  properties: {
    subnet: { id: vnet.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: 'plsc-table'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: [ 'table' ]
        }
      }
    ]
  }
}

resource peDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peTable
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'table'
        properties: { privateDnsZoneId: privateDnsZone.id }
      }
    ]
  }
}

// -------------------------------------------------------------- CMK (KV+DES)

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: tenant().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    // NOTE: purge protection locks this vault NAME for 90 days after delete.
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
  }
}

resource cmkKey 'Microsoft.KeyVault/vaults/keys@2023-07-01' = {
  parent: keyVault
  name: 'cmk-gallery'
  properties: {
    kty: 'RSA'
    keySize: 3072
    keyOps: [ 'wrapKey', 'unwrapKey' ]
  }
}

resource des 'Microsoft.Compute/diskEncryptionSets@2023-10-02' = {
  name: 'des-confidant-gallery'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    encryptionType: 'EncryptionAtRestWithCustomerKey'
    activeKey: {
      sourceVault: { id: keyVault.id }
      keyUrl: cmkKey.properties.keyUriWithVersion
    }
  }
}

resource desKvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, des.id, roleKvCryptoServiceEncryptionUser)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleKvCryptoServiceEncryptionUser)
    principalId: des.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ------------------------------------------------------------ compute gallery

resource gallery 'Microsoft.Compute/galleries@2023-07-03' = {
  name: 'confidant_gallery'
  location: location
  properties: {
    description: 'Confidant sandbox gold images (versions encrypted with des-confidant-gallery).'
  }
}

resource imageDef 'Microsoft.Compute/galleries/images@2023-07-03' = {
  parent: gallery
  name: 'confidant-sandbox'
  location: location
  properties: {
    osType: 'Linux'
    osState: 'Generalized'
    hyperVGeneration: 'V2'
    architecture: 'x64'
    identifier: {
      publisher: 'confidant'
      offer: 'sandbox'
      sku: 'e4s-cpu'
    }
    features: [
      // Required so v6 sizes (NVMe-only disk controller, e.g. E4s_v6) can boot it.
      { name: 'DiskControllerTypes', value: 'SCSI, NVMe' }
      { name: 'IsAcceleratedNetworkSupported', value: 'true' }
    ]
    recommended: {
      vCPUs: { min: 2, max: 8 }
      memory: { min: 8, max: 64 }
    }
  }
}

// ---------------------------------------------------------- function app shell

resource funcStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: funcStorageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource funcPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-confidant-func'
  location: location
  kind: 'linux'
  sku: { name: 'Y1', tier: 'Dynamic' }
  properties: { reserved: true }
}

resource funcApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: funcPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${funcStorage.name};AccountKey=${funcStorage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'INACTIVITY_MINUTES', value: '15' }
        { name: 'SANDBOX_RG', value: sandboxRgName }
        { name: 'TABLES_ENDPOINT', value: storage.properties.primaryEndpoints.table }
      ]
    }
  }
}

// Function MI: read/write analytics tables on the core storage account.
resource funcTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, funcApp.id, roleStorageTableDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageTableDataContributor)
    principalId: funcApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Function MI: read the control plane (gallery image versions, subnet ids...).
resource funcReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, funcApp.id, roleReader)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleReader)
    principalId: funcApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ------------------------------------------------------------------- outputs

output storageAccountName string = storage.name
output tablesEndpoint string = storage.properties.primaryEndpoints.table
output diskEncryptionSetId string = des.id
output galleryImageDefinitionId string = imageDef.id
output functionAppName string = funcApp.name
output functionPrincipalId string = funcApp.identity.principalId
output sandboxSubnetId string = vnet.properties.subnets[0].id
output keyVaultName string = keyVault.name
