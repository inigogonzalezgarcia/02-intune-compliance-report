<#
.SYNOPSIS
    Exports Intune managed devices to JSON for compliance_report.py.

.DESCRIPTION
    Connects to Microsoft Graph with read-only permissions and exports the device
    fields the report needs, using the same names as the Graph managedDevices
    resource (deviceName, complianceState, lastSyncDateTime, ...).

    Requires the Microsoft Graph PowerShell SDK:
        Install-Module Microsoft.Graph.DeviceManagement -Scope CurrentUser

    Permission used (delegated, read-only): DeviceManagementManagedDevices.Read.All

.PARAMETER OutputPath
    Where to write the JSON file. Default: .\intune_devices.json

.PARAMETER TenantId
    Optional tenant ID or domain, if your account has access to more than one tenant.

.EXAMPLE
    .\Export-IntuneDevices.ps1 -OutputPath .\intune_devices.json
    python compliance_report.py .\intune_devices.json
#>
[CmdletBinding()]
param(
    [string]$OutputPath = ".\intune_devices.json",
    [string]$TenantId
)

$ErrorActionPreference = "Stop"

if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.DeviceManagement)) {
    throw "Microsoft.Graph.DeviceManagement is not installed. Run: Install-Module Microsoft.Graph.DeviceManagement -Scope CurrentUser"
}
Import-Module Microsoft.Graph.DeviceManagement

$connectParams = @{ Scopes = "DeviceManagementManagedDevices.Read.All"; NoWelcome = $true }
if ($TenantId) { $connectParams.TenantId = $TenantId }
Connect-MgGraph @connectParams

$properties = @(
    "id", "deviceName", "userPrincipalName", "operatingSystem", "osVersion",
    "complianceState", "isEncrypted", "manufacturer", "model",
    "managedDeviceOwnerType", "enrolledDateTime", "lastSyncDateTime"
)

Write-Host "Reading managed devices from Intune..."
$devices = Get-MgDeviceManagementManagedDevice -All -Property $properties

# Dates are written as ISO 8601 (UTC) so the output is the same on
# Windows PowerShell 5.1 and PowerShell 7.
function Format-Date($value) {
    if ($null -eq $value) { return $null }
    return ([datetime]$value).ToUniversalTime().ToString("o")
}

$export = foreach ($d in $devices) {
    [ordered]@{
        id                     = $d.Id
        deviceName             = $d.DeviceName
        userPrincipalName      = $d.UserPrincipalName
        operatingSystem        = $d.OperatingSystem
        osVersion              = $d.OsVersion
        complianceState        = "$($d.ComplianceState)"
        isEncrypted            = $d.IsEncrypted
        manufacturer           = $d.Manufacturer
        model                  = $d.Model
        managedDeviceOwnerType = "$($d.ManagedDeviceOwnerType)"
        enrolledDateTime       = Format-Date $d.EnrolledDateTime
        lastSyncDateTime       = Format-Date $d.LastSyncDateTime
    }
}

# Always write a JSON array, even for a single device.
ConvertTo-Json -InputObject @($export) -Depth 3 | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host "Exported $(@($export).Count) devices to $OutputPath"

Disconnect-MgGraph | Out-Null
