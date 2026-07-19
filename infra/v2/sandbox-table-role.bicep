// Grants a sandbox VM's system MI a data role on the core storage account.
// Deployed as a module scoped to confidant-core-rg from sandbox.bicep.
param storageAccountName string
param principalId string
param roleDefinitionId string

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource role 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, principalId, roleDefinitionId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
