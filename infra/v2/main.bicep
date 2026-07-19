// Confidant v2 — control plane, subscription-scope entrypoint.
// Creates both resource groups and deploys the core control plane.
// Sandboxes RG stays empty; sandbox.bicep deploys into it on demand.
targetScope = 'subscription'

@description('Azure region for everything.')
param location string = 'westeurope'

@description('Name of the persistent control-plane resource group.')
param coreRgName string = 'confidant-core-rg'

@description('Name of the ephemeral sandboxes resource group.')
param sandboxRgName string = 'confidant-sandboxes-rg'

@description('Deployer public IP allowed to SSH into sandboxes (debug only, removable). Empty string = no SSH rule.')
param deployerIp string = ''

resource coreRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: coreRgName
  location: location
  tags: { project: 'confidant', plane: 'control' }
}

resource sandboxRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: sandboxRgName
  location: location
  tags: { project: 'confidant', plane: 'sandbox' }
}

module core 'core.bicep' = {
  name: 'confidant-core'
  scope: coreRg
  params: {
    location: location
    deployerIp: deployerIp
    sandboxRgName: sandboxRgName
  }
}

// Function MI needs to hard-delete VM/NIC/PIP in the sandboxes RG.
module sandboxRbac 'sandbox-rbac.bicep' = {
  name: 'confidant-sandbox-rbac'
  scope: sandboxRg
  params: {
    functionPrincipalId: core.outputs.functionPrincipalId
  }
}

output coreStorageAccount string = core.outputs.storageAccountName
output tablesEndpoint string = core.outputs.tablesEndpoint
output diskEncryptionSetId string = core.outputs.diskEncryptionSetId
output galleryImageDefinitionId string = core.outputs.galleryImageDefinitionId
output functionAppName string = core.outputs.functionAppName
output sandboxSubnetId string = core.outputs.sandboxSubnetId
