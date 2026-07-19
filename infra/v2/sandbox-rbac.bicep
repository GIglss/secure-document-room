// Role assignments for the Function listener MI on the sandboxes RG:
// it must hard-delete VMs (Virtual Machine Contributor) and their NIC/PIP
// (Network Contributor).
param functionPrincipalId string

var roleVmContributor = '9980e02c-c2be-4d73-94e8-173b1dc7cf3c'
var roleNetworkContributor = '4d97b98b-1d4f-4787-a291-c67834d212e7'

resource vmContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, functionPrincipalId, roleVmContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleVmContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource netContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, functionPrincipalId, roleNetworkContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleNetworkContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}
