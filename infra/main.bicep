// Confidant sandbox room — one VM per client engagement + durable side services.
// Deploy at resource-group scope (see provision.sh).
//
// Lifecycle model:
//   - VM deallocated  -> engagement in standby, ~zero compute cost
//   - VM deleted      -> engagement data destroyed (docs, vectors, SQLite, chat)
//   - Storage account -> anonymized insights OUTLIVE the VM (table "insights")
//   - ACS email       -> verification-code sender, shared across engagements

@description('Region for all regional resources.')
param location string = resourceGroup().location

@description('VM size. Default chosen from actual subscription quota (D8s_v6 is NVMe-only; if you switch to an older/GPU SKU set diskControllerType=SCSI).')
param vmSize string = 'Standard_D8s_v6'

@description('SCSI for most older/GPU SKUs (e.g. Standard_NC8as_T4_v3), NVMe for v6+ SKUs.')
@allowed(['NVMe', 'SCSI'])
param diskControllerType string = 'NVMe'

@description('True on GPU VMs: cloud-init additionally installs the NVIDIA driver + nvidia-container-toolkit.')
param gpu bool = false

param adminUsername string = 'azureuser'

@description('SSH public key for the admin user (provision.sh passes ~/.ssh/confidant_vm.pub).')
param sshPublicKey string

@description('CIDR allowed to SSH (deployer\'s current public IP /32).')
param allowedSshSourcePrefix string

@description('Daily auto-shutdown time (HHmm, UTC) — cost safety net.')
param autoShutdownTime string = '2000'

var suffix = uniqueString(resourceGroup().id)
var vmName = 'vm-confidant'
var dnsLabel = 'confidant-${suffix}'
var storageAccountName = 'stconfidant${suffix}' // 11 + 13 = 24 chars, at the limit
var insightsTableName = 'insights'
var cloudInit = gpu ? loadTextContent('cloud-init-gpu.yaml') : loadTextContent('cloud-init.yaml')

// ---------------------------------------------------------------- storage ---
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource insightsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: insightsTableName
}

// -------------------------------------------------------------- ACS email ---
resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: 'email-confidant-${suffix}'
  location: 'global'
  properties: {
    dataLocation: 'Europe'
  }
}

resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: 'acs-confidant-${suffix}'
  location: 'global'
  properties: {
    dataLocation: 'Europe'
    linkedDomains: [emailDomain.id]
  }
}

// ---------------------------------------------------------------- network ---
resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-confidant'
  location: location
  properties: {
    securityRules: [
      {
        name: 'allow-https'
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
      {
        name: 'allow-http'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '80'
        }
      }
      {
        name: 'allow-ssh-deployer'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: allowedSshSourcePrefix
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-confidant'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.20.0.0/24'] }
    subnets: [
      {
        name: 'default'
        properties: {
          addressPrefix: '10.20.0.0/26'
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource pip 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: 'pip-confidant'
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: { domainNameLabel: dnsLabel }
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: 'nic-confidant'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: vnet.properties.subnets[0].id }
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: { id: pip.id }
        }
      }
    ]
  }
}

// --------------------------------------------------------------------- VM ---
resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: vmName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 128
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
        deleteOption: 'Delete'
      }
      diskControllerType: diskControllerType
    }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [{ id: nic.id, properties: { deleteOption: 'Delete' } }]
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: { secureBootEnabled: true, vTpmEnabled: true }
    }
    diagnosticsProfile: { bootDiagnostics: { enabled: true } }
  }
}

// VM managed identity may write anonymized insights to Table Storage.
var tableDataContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3' // Storage Table Data Contributor
)

resource insightsRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, vm.id, tableDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: tableDataContributorRoleId
    principalId: vm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Cost safety net: stop the VM every evening even if someone forgets down.sh.
resource autoShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${vmName}'
  location: location
  properties: {
    status: 'Enabled'
    taskType: 'ComputeVmShutdownTask'
    dailyRecurrence: { time: autoShutdownTime }
    timeZoneId: 'UTC'
    targetResourceId: vm.id
    notificationSettings: { status: 'Disabled' }
  }
}

// ---------------------------------------------------------------- outputs ---
output vmName string = vmName
output vmFqdn string = pip.properties.dnsSettings.fqdn
output publicIpAddress string = pip.properties.ipAddress
output storageAccountName string = storage.name
output tableEndpoint string = storage.properties.primaryEndpoints.table
output insightsTable string = insightsTableName
output acsName string = acs.name
output acsSenderAddress string = 'DoNotReply@${emailDomain.properties.fromSenderDomain}'
output adminUsername string = adminUsername
