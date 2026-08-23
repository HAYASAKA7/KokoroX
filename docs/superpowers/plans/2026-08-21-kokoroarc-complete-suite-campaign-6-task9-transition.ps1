[CmdletBinding(DefaultParameterSetName='Transition')]
param(
    [Parameter(Mandatory,ParameterSetName='Transition',Position=0)]
    [string]$HandoffPath,
    [Parameter(Mandatory,ParameterSetName='Transition',Position=1)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedHandoffSha256,
    [Parameter(Mandatory,ParameterSetName='Transition',Position=2)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedTask8Commit,
    [Parameter(Mandatory,ParameterSetName='Transition',Position=3)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedTask9Commit,
    [Parameter(Mandatory,ParameterSetName='Transition',Position=4)]
    [string]$CheckoutRoot,
    [Parameter(Mandatory,ParameterSetName='Transition',Position=5)]
    [string]$ArtifactOracleHandoffPath,
    [Parameter(Mandatory,ParameterSetName='Transition',Position=6)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedArtifactOracleHandoffSha256,
    [Parameter(Mandatory,ParameterSetName='Transition',Position=7)]
    [string]$ArtifactOracleCheckoutRoot,
    [Parameter(Mandatory,ParameterSetName='SuccessorVerifierSource')]
    [switch]$SuccessorVerifierSource
)
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
Set-StrictMode -Version Latest
if ($PSCmdlet.ParameterSetName -eq 'SuccessorVerifierSource') {
    if (-not $SuccessorVerifierSource.IsPresent) {
        throw 'SuccessorVerifierSource switch must be explicitly present'
    }
    $successorVerifierText=@'
function Read-C6AuthenticatedBytes {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{64}$')][string]$Sha256,
        [Parameter(Mandatory)]
        [ValidateSet(
            'receipt','trust','transition','oracle','zero-envelope','manifest',
            'control-plane','bootstrap','launcher','writer','host-review-result'
        )]
        [string]$Role
    )
    [long]$cap=switch ($Role) {
        'zero-envelope' { 16384L }
        'host-review-result' { 262144L }
        'manifest' { 8388608L }
        'control-plane' { 4194304L }
        'bootstrap' { 4194304L }
        'launcher' { 1048576L }
        'writer' { 1048576L }
        default { 65536L }
    }
    if (-not [IO.Path]::IsPathFullyQualified($Path)) {
        throw "authenticated path is not absolute: $Path"
    }
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw "authenticated path is not an observed plain file: $Path"
    }
    $stream=$null
    try {
        $stream=[IO.FileStream]::new(
            $item.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,
            [IO.FileShare]::Read,65536,[IO.FileOptions]::SequentialScan
        )
        if ($stream.Length -lt 1 -or $stream.Length -gt $cap -or
            $stream.Length -gt [int]::MaxValue -or
            $stream.Length -ne $item.Length) {
            throw "authenticated role/length mismatch: $Role"
        }
        [byte[]]$bytes=[byte[]]::new([int]$stream.Length)
        $offset=0
        while ($offset -lt $bytes.Length) {
            $count=$stream.Read($bytes,$offset,$bytes.Length-$offset)
            if ($count -le 0) { throw "authenticated short read: $Role" }
            $offset += $count
        }
        if ($stream.ReadByte() -ne -1 -or $stream.Length -ne $bytes.Length) {
            throw "authenticated retained-stream drift: $Role"
        }
        $actual=[Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData($bytes)
        ).ToLowerInvariant()
        if ($actual -cne $Sha256) {
            throw "authenticated byte hash mismatch: $Role"
        }
        return [pscustomobject]@{
            role=$Role; path=$item.FullName; sha256=$Sha256
            length=[long]$bytes.Length; bytes=$bytes; stream=$stream
        }
    } catch {
        if ($null -ne $stream) { $stream.Dispose() }
        throw
    }
}

function Confirm-C6AuthenticatedBytes {
    param([Parameter(Mandatory)]$Held)
    if ($Held.stream.Length -ne $Held.length) {
        throw "authenticated retained length drift: $($Held.role)"
    }
    $Held.stream.Position=0
    $hasher=[Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try {
        $buffer=[byte[]]::new(65536)
        [long]$total=0
        while (($count=$Held.stream.Read($buffer,0,$buffer.Length)) -gt 0) {
            $total += $count
            if ($total -gt $Held.length) {
                throw "authenticated retained stream grew: $($Held.role)"
            }
            $hasher.AppendData($buffer,0,$count)
        }
        $actual=[Convert]::ToHexString(
            $hasher.GetHashAndReset()
        ).ToLowerInvariant()
        if ($total -ne $Held.length -or $actual -cne $Held.sha256) {
            throw "authenticated retained rehash mismatch: $($Held.role)"
        }
    } finally { $hasher.Dispose() }
}

function ConvertFrom-C6AuthenticatedJson {
    param(
        [Parameter(Mandatory)]$Held,
        [Parameter(Mandatory)][string[]]$ExpectedKeys,
        [Parameter(Mandatory)][string[]]$IntegerKeys,
        [Parameter(Mandatory)][string[]]$BooleanKeys,
        [Parameter(Mandatory)][string[]]$ObjectKeys,
        [Parameter(Mandatory)][string[]]$ArrayKeys,
        [Parameter(Mandatory)][string]$Label
    )
    $encoding=[Text.UTF8Encoding]::new($false,$true)
    $text=$encoding.GetString($Held.bytes)
    if (-not $text.EndsWith("`n") -or $text.Contains("`r") -or
        $text.Contains([char]0)) { throw "$Label text envelope" }
    $options=[Text.Json.JsonDocumentOptions]::new()
    $options.AllowTrailingCommas=$false
    $options.CommentHandling=[Text.Json.JsonCommentHandling]::Disallow
    $options.MaxDepth=32
    $document=[Text.Json.JsonDocument]::Parse(
        [ReadOnlyMemory[byte]]::new($Held.bytes),$options
    )
    try {
        if ($document.RootElement.ValueKind -ne
                [Text.Json.JsonValueKind]::Object -or
            $document.RootElement.GetRawText() -cne
                $text.Substring(0,$text.Length-1)) {
            throw "$Label JSON root/framing"
        }
        $properties=[Collections.Generic.List[Text.Json.JsonProperty]]::new()
        $enumerator=$document.RootElement.EnumerateObject()
        while ($enumerator.MoveNext()) { [void]$properties.Add($enumerator.Current) }
        if ($properties.Count -ne $ExpectedKeys.Count) {
            throw "$Label JSON property count"
        }
        for ($index=0; $index -lt $ExpectedKeys.Count; $index++) {
            $property=$properties[$index]
            $name=$property.Name
            $expectedKind=if ($IntegerKeys -ccontains $name) {
                [Text.Json.JsonValueKind]::Number
            } elseif ($BooleanKeys -ccontains $name) {
                if ($property.Value.GetBoolean()) {
                    [Text.Json.JsonValueKind]::True
                } else { [Text.Json.JsonValueKind]::False }
            } elseif ($ObjectKeys -ccontains $name) {
                [Text.Json.JsonValueKind]::Object
            } elseif ($ArrayKeys -ccontains $name) {
                [Text.Json.JsonValueKind]::Array
            } else { [Text.Json.JsonValueKind]::String }
            if ($name -cne $ExpectedKeys[$index] -or
                $property.Value.ValueKind -ne $expectedKind) {
                throw "$Label JSON name/type: $index"
            }
            if ($IntegerKeys -ccontains $name) {
                [long]$number=0
                if (-not $property.Value.TryGetInt64([ref]$number)) {
                    throw "$Label JSON integer: $name"
                }
            } elseif ($expectedKind -eq [Text.Json.JsonValueKind]::String -and
                $null -eq $property.Value.GetString()) {
                throw "$Label JSON null string: $name"
            }
        }
    } finally { $document.Dispose() }
    $value=$text | ConvertFrom-Json -AsHashtable -NoEnumerate -ErrorAction Stop
    if ($value -isnot [Collections.IDictionary] -or
        (@($value.Keys) -join "`n") -cne ($ExpectedKeys -join "`n") -or
        (ConvertTo-Json -InputObject $value -Compress -Depth 30) + "`n" -cne
            $text) {
        throw "$Label PowerShell/canonical mismatch"
    }
    foreach ($key in $ExpectedKeys) {
        if ($IntegerKeys -ccontains $key) {
            if ($value[$key] -isnot [long]) { throw "$Label integer: $key" }
        } elseif ($BooleanKeys -ccontains $key) {
            if ($value[$key] -isnot [bool]) { throw "$Label boolean: $key" }
        } elseif ($ObjectKeys -ccontains $key) {
            if ($value[$key] -isnot [Collections.IDictionary]) {
                throw "$Label object: $key"
            }
        } elseif ($ArrayKeys -ccontains $key) {
            if ($value[$key] -isnot [object[]]) { throw "$Label array: $key" }
        } elseif ($value[$key] -isnot [string]) {
            throw "$Label string: $key"
        }
    }
    return $value
}

function Assert-C6AuthenticatedObject {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string[]]$ExpectedKeys,
        [Parameter(Mandatory)][string]$Label
    )
    if ($Value -isnot [Collections.IDictionary] -or
        (@($Value.Keys) -join "`n") -cne ($ExpectedKeys -join "`n")) {
        throw "$Label object/key order"
    }
}

function Assert-C6AuthenticatedScalarTypes {
    param(
        [Parameter(Mandatory)][Collections.IDictionary]$Value,
        [Parameter(Mandatory)][string[]]$StringKeys,
        [Parameter(Mandatory)][string[]]$IntegerKeys,
        [Parameter(Mandatory)][string[]]$BooleanKeys,
        [Parameter(Mandatory)][string]$Label
    )
    foreach ($key in $StringKeys) {
        if ($Value[$key] -isnot [string]) { throw "$Label string: $key" }
    }
    foreach ($key in $IntegerKeys) {
        if ($Value[$key] -isnot [long]) { throw "$Label integer: $key" }
    }
    foreach ($key in $BooleanKeys) {
        if ($Value[$key] -isnot [bool]) { throw "$Label boolean: $key" }
    }
}

function Get-C6AuthenticatedGitBlob {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    $hasher=[Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA1
    )
    try {
        $header=[Text.Encoding]::ASCII.GetBytes(
            'blob ' + $Bytes.LongLength + [char]0
        )
        $hasher.AppendData($header)
        $hasher.AppendData($Bytes)
        return [Convert]::ToHexString(
            $hasher.GetHashAndReset()
        ).ToLowerInvariant()
    } finally { $hasher.Dispose() }
}

$heldAuthenticatedFiles=[Collections.Generic.List[object]]::new()
$heldByRole=[Collections.Generic.Dictionary[string,object]]::new(
    [StringComparer]::Ordinal
)
$successorVerifierFailure=$null
try {
$receiptHeld=Read-C6AuthenticatedBytes -Path $script:C6Task9BootstrapReceipt `
    -Sha256 $script:C6Task9BootstrapReceiptSha256 -Role receipt
[void]$heldAuthenticatedFiles.Add($receiptHeld)
$receiptBytes=$receiptHeld.bytes
$utf8=[Text.UTF8Encoding]::new($false,$true)
$receiptText=$utf8.GetString($receiptBytes)
if (-not $receiptText.EndsWith("`n") -or
    $receiptText.Contains("`r") -or $receiptText.Contains([char]0)) {
    throw 'Task 9 receipt is not strict LF UTF-8'
}
$receiptKeys=@(
    'schema_version','plan_commit','plan_sha256','task9_commit','task9_tree',
    'post_trust_selection_registry_sha256',
    'host_constructor_implementation_sha256',
    'broker_constructor_implementation_sha256',
    'constructor_implementation_set_sha256',
    'constructor_attribute_set_sha256',
    'job_topology_sha256','artifact_tty_contract_sha256',
    'artifact_oracle_path','artifact_oracle_commit','artifact_oracle_tree',
    'artifact_oracle_blob','artifact_oracle_size','artifact_oracle_sha256',
    'artifact_oracle_review_result_sha256','artifact_oracle_digest_count',
    'checkout_root','trust_record_path','trust_record_sha256',
    'transition_record_path','transition_record_sha256',
    'checkout_manifest_path','checkout_manifest_sha256',
    'zero_codex_envelope_path','zero_codex_envelope_sha256',
    'control_plane_path','control_plane_sha256',
    'python_bootstrap_path','python_bootstrap_sha256',
    'artifact_launcher_path','artifact_launcher_size','artifact_launcher_sha256',
    'artifact_writer_path','artifact_writer_size','artifact_writer_sha256'
)
$receiptIntegerKeys=@(
    'artifact_oracle_size','artifact_oracle_digest_count',
    'artifact_launcher_size','artifact_writer_size'
)
$receiptStringKeys=@(
    'schema_version','plan_commit','plan_sha256','task9_commit','task9_tree',
    'post_trust_selection_registry_sha256',
    'host_constructor_implementation_sha256',
    'broker_constructor_implementation_sha256',
    'constructor_implementation_set_sha256',
    'constructor_attribute_set_sha256',
    'job_topology_sha256','artifact_tty_contract_sha256',
    'artifact_oracle_path','artifact_oracle_commit','artifact_oracle_tree',
    'artifact_oracle_blob','artifact_oracle_sha256',
    'artifact_oracle_review_result_sha256',
    'checkout_root','trust_record_path','trust_record_sha256',
    'transition_record_path','transition_record_sha256',
    'checkout_manifest_path','checkout_manifest_sha256',
    'zero_codex_envelope_path','zero_codex_envelope_sha256',
    'control_plane_path','control_plane_sha256',
    'python_bootstrap_path','python_bootstrap_sha256',
    'artifact_launcher_path','artifact_launcher_sha256',
    'artifact_writer_path','artifact_writer_sha256'
)
$jsonOptions=[Text.Json.JsonDocumentOptions]::new()
$jsonOptions.AllowTrailingCommas=$false
$jsonOptions.CommentHandling=[Text.Json.JsonCommentHandling]::Disallow
$jsonOptions.MaxDepth=16
$receiptDocument=[Text.Json.JsonDocument]::Parse(
    [ReadOnlyMemory[byte]]::new($receiptBytes),$jsonOptions
)
try {
    if ($receiptDocument.RootElement.ValueKind -ne
            [Text.Json.JsonValueKind]::Object) {
        throw 'Task 9 receipt root type mismatch'
    }
    $jsonProperties=[Collections.Generic.List[Text.Json.JsonProperty]]::new()
    $jsonEnumerator=$receiptDocument.RootElement.EnumerateObject()
    while ($jsonEnumerator.MoveNext()) {
        [void]$jsonProperties.Add($jsonEnumerator.Current)
    }
    if ($jsonProperties.Count -ne $receiptKeys.Count) {
        throw 'Task 9 receipt JSON property count mismatch'
    }
    for ($index=0; $index -lt $receiptKeys.Count; $index++) {
        $property=$jsonProperties[$index]
        $integerIndex=[Array]::IndexOf($receiptIntegerKeys,$property.Name)
        $expectedKind=if ($integerIndex -ge 0) {
            [Text.Json.JsonValueKind]::Number
        } else {
            [Text.Json.JsonValueKind]::String
        }
        if ($property.Name -cne $receiptKeys[$index] -or
            $property.Value.ValueKind -ne $expectedKind) {
            throw "Task 9 receipt JSON name/type mismatch: $index"
        }
        if ($expectedKind -eq [Text.Json.JsonValueKind]::Number) {
            [long]$integerValue=0
            if (-not $property.Value.TryGetInt64([ref]$integerValue)) {
                throw "Task 9 receipt JSON integer mismatch: $($property.Name)"
            }
        }
    }
} finally {
    $receiptDocument.Dispose()
}
$receipt=$receiptText | ConvertFrom-Json -AsHashtable -NoEnumerate -ErrorAction Stop
if ($receipt -isnot [Collections.IDictionary]) {
    throw 'Task 9 receipt PowerShell root type mismatch'
}
$derivedStringKeys=[Collections.Generic.List[string]]::new()
foreach ($key in $receiptKeys) {
    if ([Array]::IndexOf($receiptIntegerKeys,$key) -lt 0) {
        [void]$derivedStringKeys.Add($key)
    }
}
if ((@($receipt.Keys) -join "`n") -cne ($receiptKeys -join "`n") -or
    ($derivedStringKeys -join "`n") -cne ($receiptStringKeys -join "`n")) {
    throw 'Task 9 receipt key/type partition mismatch'
}
foreach ($key in $receiptStringKeys) {
    if ($receipt[$key] -isnot [string]) {
        throw "Task 9 receipt string type mismatch: $key"
    }
}
foreach ($key in $receiptIntegerKeys) {
    if ($receipt[$key] -isnot [long]) {
        throw "Task 9 receipt integer type mismatch: $key"
    }
}
if (
    $receipt.schema_version -cne 'complete-suite-task9-bootstrap-receipt-v2' -or
    $receipt.post_trust_selection_registry_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.host_constructor_implementation_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.broker_constructor_implementation_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.constructor_implementation_set_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.constructor_attribute_set_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.job_topology_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.artifact_tty_contract_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.artifact_oracle_path -cnotmatch
        '\AD:\\tmp\\kokoroarc-c6-task9-artifact-source-oracle-checkout-' +
        '[0-9a-f]{32}\\docs\\superpowers\\plans\\' +
        '2026-08-21-kokoroarc-complete-suite-campaign-6-' +
        'task9-artifact-source-oracle\.json\z' -or
    $receipt.artifact_oracle_commit -cnotmatch '^[0-9a-f]{40}$' -or
    $receipt.artifact_oracle_tree -cnotmatch '^[0-9a-f]{40}$' -or
    $receipt.artifact_oracle_blob -cnotmatch '^[0-9a-f]{40}$' -or
    $receipt.artifact_oracle_size -lt 2 -or
    $receipt.artifact_oracle_size -gt 65536 -or
    $receipt.artifact_oracle_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.artifact_oracle_review_result_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $receipt.artifact_oracle_digest_count -ne 8 -or
    $receipt.checkout_root -cne $script:C6Task9MaterializedRoot -or
    $receipt.zero_codex_envelope_path -cne $script:C6ZeroCodexEnvelopeRecord -or
    $receipt.zero_codex_envelope_sha256 -cne $script:C6ZeroCodexEnvelopeSha256 -or
    $receipt.control_plane_path -cne $script:C6Task9ControlPlanePath -or
    $receipt.control_plane_sha256 -cne $script:C6Task9ControlPlaneSha256 -or
    $receipt.python_bootstrap_path -cne $script:C6Task9PythonBootstrapPath -or
    $receipt.python_bootstrap_sha256 -cne $script:C6Task9PythonBootstrapSha256 -or
    $receipt.artifact_tty_contract_sha256 -cne
        $script:C6Task9ArtifactTtyContractSha256 -or
    $receipt.artifact_launcher_path -cne $script:C6Task9ArtifactLauncherPath -or
    $receipt.artifact_launcher_sha256 -cne
        $script:C6Task9ArtifactLauncherSha256 -or
    $receipt.artifact_launcher_size -lt 1 -or
    $receipt.artifact_launcher_size -gt 1048576 -or
    $receipt.artifact_writer_path -cne $script:C6Task9ArtifactWriterPath -or
    $receipt.artifact_writer_sha256 -cne $script:C6Task9ArtifactWriterSha256 -or
    $receipt.artifact_writer_size -lt 1 -or
    $receipt.artifact_writer_size -gt 1048576) {
    throw 'Task 9 receipt binding mismatch'
}
$script:C6Task9TrustRecord=$receipt.trust_record_path
$script:C6Task9TrustRecordSha256=$receipt.trust_record_sha256
$script:C6Task9TransitionRecord=$receipt.transition_record_path
$script:C6Task9TransitionRecordSha256=$receipt.transition_record_sha256
$script:C6PostTrustSelectionRegistrySha256=(
    $receipt.post_trust_selection_registry_sha256
)
$script:C6HostConstructorImplementationSha256=(
    $receipt.host_constructor_implementation_sha256
)
$script:C6BrokerConstructorImplementationSha256=(
    $receipt.broker_constructor_implementation_sha256
)
$script:C6ConstructorImplementationSetSha256=(
    $receipt.constructor_implementation_set_sha256
)
$script:C6ConstructorAttributeSetSha256=(
    $receipt.constructor_attribute_set_sha256
)
$script:C6JobTopologySha256=$receipt.job_topology_sha256
$script:C6Task9MaterializationRecord=$receipt.checkout_manifest_path
$script:C6Task9MaterializationRecordSha256=$receipt.checkout_manifest_sha256
$script:C6Task9ArtifactOraclePath=$receipt.artifact_oracle_path
$script:C6Task9ArtifactOracleCommit=$receipt.artifact_oracle_commit
$script:C6Task9ArtifactOracleTree=$receipt.artifact_oracle_tree
$script:C6Task9ArtifactOracleBlob=$receipt.artifact_oracle_blob
$script:C6Task9ArtifactOracleSize=[long]$receipt.artifact_oracle_size
$script:C6Task9ArtifactOracleSha256=$receipt.artifact_oracle_sha256
$script:C6Task9ArtifactOracleReviewResultSha256=(
    $receipt.artifact_oracle_review_result_sha256
)
$script:C6Task9ArtifactOracleDigestCount=[long]$receipt.artifact_oracle_digest_count
$script:C6Task9ArtifactLauncherSize=[long]$receipt.artifact_launcher_size
$script:C6Task9ArtifactWriterSize=[long]$receipt.artifact_writer_size
foreach ($pair in @(
    @('trust',$receipt.trust_record_path,$receipt.trust_record_sha256),
    @('transition',$receipt.transition_record_path,$receipt.transition_record_sha256),
    @('oracle',$receipt.artifact_oracle_path,$receipt.artifact_oracle_sha256),
    @('manifest',$receipt.checkout_manifest_path,$receipt.checkout_manifest_sha256),
    @('zero-envelope',$receipt.zero_codex_envelope_path,$receipt.zero_codex_envelope_sha256)
)) {
    $held=Read-C6AuthenticatedBytes -Role $pair[0] -Path $pair[1] -Sha256 $pair[2]
    [void]$heldAuthenticatedFiles.Add($held)
    $heldByRole.Add([string]$pair[0],$held)
}
$controlHeld=Read-C6AuthenticatedBytes -Role control-plane `
    -Path $script:C6Task9ControlPlanePath -Sha256 $script:C6Task9ControlPlaneSha256
[void]$heldAuthenticatedFiles.Add($controlHeld)
$heldByRole.Add([string]$controlHeld.role,$controlHeld)
$bootstrapHeld=Read-C6AuthenticatedBytes -Role bootstrap `
    -Path $script:C6Task9PythonBootstrapPath `
    -Sha256 $script:C6Task9PythonBootstrapSha256
[void]$heldAuthenticatedFiles.Add($bootstrapHeld)
$heldByRole.Add([string]$bootstrapHeld.role,$bootstrapHeld)
$launcherHeld=Read-C6AuthenticatedBytes -Role launcher `
    -Path $script:C6Task9ArtifactLauncherPath `
    -Sha256 $script:C6Task9ArtifactLauncherSha256
[void]$heldAuthenticatedFiles.Add($launcherHeld)
$heldByRole.Add([string]$launcherHeld.role,$launcherHeld)
$writerHeld=Read-C6AuthenticatedBytes -Role writer `
    -Path $script:C6Task9ArtifactWriterPath -Sha256 $script:C6Task9ArtifactWriterSha256
[void]$heldAuthenticatedFiles.Add($writerHeld)
$heldByRole.Add([string]$writerHeld.role,$writerHeld)
$trustKeys=@(
    'schema_version','authority','task8_commit','task9_commit','task9_tree',
    'checkout_root','checkout_manifest_path','checkout_manifest_sha256',
    'zero_codex_envelope_path','zero_codex_envelope_sha256',
    'python_runtime_inventory_sha256','powershell_runtime_inventory_sha256',
    'git_runtime_inventory_sha256','post_trust_selection_registry_sha256',
    'host_constructor_implementation_sha256',
    'broker_constructor_implementation_sha256',
    'constructor_implementation_set_sha256',
    'constructor_attribute_set_sha256','job_topology_sha256',
    'control_plane_path','control_plane_blob','control_plane_size',
    'control_plane_sha256','python_bootstrap_path','python_bootstrap_blob',
    'python_bootstrap_size','python_bootstrap_sha256',
    'artifact_tty_contract_sha256','artifact_oracle_path',
    'artifact_oracle_commit','artifact_oracle_tree','artifact_oracle_blob',
    'artifact_oracle_size','artifact_oracle_sha256',
    'artifact_oracle_review_result_sha256','artifact_oracle_digest_count',
    'artifact_launcher_path','artifact_launcher_blob','artifact_launcher_size',
    'artifact_launcher_sha256','artifact_writer_path','artifact_writer_blob',
    'artifact_writer_size','artifact_writer_sha256','codex_processes_requested',
    'provider_credentials_supplied','verdict'
)
$trustIntegerKeys=@(
    'control_plane_size','python_bootstrap_size','artifact_oracle_size',
    'artifact_oracle_digest_count','artifact_launcher_size',
    'artifact_writer_size','codex_processes_requested'
)
$trust=ConvertFrom-C6AuthenticatedJson -Held $heldByRole['trust'] `
    -ExpectedKeys $trustKeys -IntegerKeys $trustIntegerKeys `
    -BooleanKeys @('provider_credentials_supplied') -ObjectKeys @('authority') `
    -ArrayKeys @() -Label 'Task 9 trust record'
$authorityKeys=@(
    'plan_commit','plan_tree','plan_blob','plan_sha256','handoff_path','handoff_sha256'
)
Assert-C6AuthenticatedObject -Value $trust.authority `
    -ExpectedKeys $authorityKeys -Label 'Task 9 trust authority'
Assert-C6AuthenticatedScalarTypes -Value $trust.authority `
    -StringKeys $authorityKeys -IntegerKeys @() -BooleanKeys @() `
    -Label 'Task 9 trust authority'

$transitionKeys=@(
    'schema_version','transition_id','trust_record_path','trust_record_sha256',
    'checkout_manifest_path','checkout_manifest_sha256','task9_commit','task9_tree',
    'post_trust_selection_registry_sha256',
    'host_constructor_implementation_sha256',
    'broker_constructor_implementation_sha256',
    'constructor_implementation_set_sha256',
    'constructor_attribute_set_sha256','job_topology_sha256',
    'artifact_tty_contract_sha256','artifact_oracle_sha256',
    'artifact_oracle_review_result_sha256','artifact_oracle_digest_count',
    'predecessor_repository_code_loaded','codex_processes_requested',
    'provider_credentials_supplied','fresh_successor_required','verdict'
)
$transition=ConvertFrom-C6AuthenticatedJson -Held $heldByRole['transition'] `
    -ExpectedKeys $transitionKeys `
    -IntegerKeys @('artifact_oracle_digest_count','codex_processes_requested') `
    -BooleanKeys @(
        'predecessor_repository_code_loaded','provider_credentials_supplied',
        'fresh_successor_required'
    ) -ObjectKeys @() -ArrayKeys @() -Label 'Task 9 transition record'

$manifestKeys=@(
    'schema_version','commit','tree','root','entries','file_count','file_bytes',
    'aggregate_sha256'
)
$manifest=ConvertFrom-C6AuthenticatedJson -Held $heldByRole['manifest'] `
    -ExpectedKeys $manifestKeys -IntegerKeys @('file_count','file_bytes') `
    -BooleanKeys @() -ObjectKeys @() -ArrayKeys @('entries') `
    -Label 'Task 9 checkout manifest'

$oracleKeys=@(
    'schema_version','plan_commit','task9_commit','task9_tree',
    'algorithm_table_revision','algorithm_table_sha256','sources','semantics',
    'digest_count'
)
$oracle=ConvertFrom-C6AuthenticatedJson -Held $heldByRole['oracle'] `
    -ExpectedKeys $oracleKeys -IntegerKeys @('digest_count') `
    -BooleanKeys @() -ObjectKeys @() -ArrayKeys @('sources','semantics') `
    -Label 'Task 9 artifact source oracle'

$shaPattern='^[0-9a-f]{64}$'
$oidPattern='^[0-9a-f]{40}$'
if ($trust.schema_version -cne 'complete-suite-task9-trust-v3' -or
    $trust.authority.plan_commit -cne $receipt.plan_commit -or
    $trust.authority.plan_sha256 -cne $receipt.plan_sha256 -or
    $trust.task9_commit -cne $receipt.task9_commit -or
    $trust.task9_tree -cne $receipt.task9_tree -or
    $trust.checkout_root -cne $receipt.checkout_root -or
    $trust.checkout_manifest_path -cne $receipt.checkout_manifest_path -or
    $trust.checkout_manifest_sha256 -cne $receipt.checkout_manifest_sha256 -or
    $trust.zero_codex_envelope_path -cne $receipt.zero_codex_envelope_path -or
    $trust.zero_codex_envelope_sha256 -cne $receipt.zero_codex_envelope_sha256 -or
    $trust.post_trust_selection_registry_sha256 -cne
        $receipt.post_trust_selection_registry_sha256 -or
    $trust.host_constructor_implementation_sha256 -cne
        $receipt.host_constructor_implementation_sha256 -or
    $trust.broker_constructor_implementation_sha256 -cne
        $receipt.broker_constructor_implementation_sha256 -or
    $trust.constructor_implementation_set_sha256 -cne
        $receipt.constructor_implementation_set_sha256 -or
    $trust.constructor_attribute_set_sha256 -cne
        $receipt.constructor_attribute_set_sha256 -or
    $trust.job_topology_sha256 -cne $receipt.job_topology_sha256 -or
    $trust.artifact_tty_contract_sha256 -cne
        $receipt.artifact_tty_contract_sha256 -or
    $trust.artifact_oracle_path -cne $receipt.artifact_oracle_path -or
    $trust.artifact_oracle_commit -cne $receipt.artifact_oracle_commit -or
    $trust.artifact_oracle_tree -cne $receipt.artifact_oracle_tree -or
    $trust.artifact_oracle_blob -cne $receipt.artifact_oracle_blob -or
    $trust.artifact_oracle_size -ne $receipt.artifact_oracle_size -or
    $trust.artifact_oracle_sha256 -cne $receipt.artifact_oracle_sha256 -or
    $trust.artifact_oracle_review_result_sha256 -cne
        $receipt.artifact_oracle_review_result_sha256 -or
    $trust.artifact_oracle_digest_count -ne $receipt.artifact_oracle_digest_count -or
    $trust.artifact_launcher_path -cne $receipt.artifact_launcher_path -or
    $trust.artifact_launcher_size -ne $receipt.artifact_launcher_size -or
    $trust.artifact_launcher_sha256 -cne $receipt.artifact_launcher_sha256 -or
    $trust.artifact_writer_path -cne $receipt.artifact_writer_path -or
    $trust.artifact_writer_size -ne $receipt.artifact_writer_size -or
    $trust.artifact_writer_sha256 -cne $receipt.artifact_writer_sha256 -or
    $trust.codex_processes_requested -ne 0 -or
    $trust.provider_credentials_supplied -or $trust.verdict -cne 'pass') {
    throw 'Task 9 trust/receipt cross-binding mismatch'
}
foreach ($key in @(
    'python_runtime_inventory_sha256','powershell_runtime_inventory_sha256',
    'git_runtime_inventory_sha256','control_plane_sha256',
    'python_bootstrap_sha256','artifact_oracle_sha256',
    'artifact_oracle_review_result_sha256','artifact_launcher_sha256',
    'artifact_writer_sha256'
)) {
    if ($trust[$key] -cnotmatch $shaPattern) {
        throw "Task 9 trust digest grammar mismatch: $key"
    }
}
foreach ($key in @(
    'control_plane_blob','python_bootstrap_blob','artifact_oracle_commit',
    'artifact_oracle_tree','artifact_oracle_blob','artifact_launcher_blob',
    'artifact_writer_blob'
)) {
    if ($trust[$key] -cnotmatch $oidPattern) {
        throw "Task 9 trust object-id grammar mismatch: $key"
    }
}
if ($transition.schema_version -cne 'complete-suite-task9-transition-v3' -or
    $transition.trust_record_path -cne $receipt.trust_record_path -or
    $transition.trust_record_sha256 -cne $receipt.trust_record_sha256 -or
    $transition.checkout_manifest_path -cne $receipt.checkout_manifest_path -or
    $transition.checkout_manifest_sha256 -cne $receipt.checkout_manifest_sha256 -or
    $transition.task9_commit -cne $receipt.task9_commit -or
    $transition.task9_tree -cne $receipt.task9_tree -or
    $transition.post_trust_selection_registry_sha256 -cne
        $receipt.post_trust_selection_registry_sha256 -or
    $transition.host_constructor_implementation_sha256 -cne
        $receipt.host_constructor_implementation_sha256 -or
    $transition.broker_constructor_implementation_sha256 -cne
        $receipt.broker_constructor_implementation_sha256 -or
    $transition.constructor_implementation_set_sha256 -cne
        $receipt.constructor_implementation_set_sha256 -or
    $transition.constructor_attribute_set_sha256 -cne
        $receipt.constructor_attribute_set_sha256 -or
    $transition.job_topology_sha256 -cne $receipt.job_topology_sha256 -or
    $transition.artifact_tty_contract_sha256 -cne
        $receipt.artifact_tty_contract_sha256 -or
    $transition.artifact_oracle_sha256 -cne $receipt.artifact_oracle_sha256 -or
    $transition.artifact_oracle_review_result_sha256 -cne
        $receipt.artifact_oracle_review_result_sha256 -or
    $transition.artifact_oracle_digest_count -ne 8 -or
    $transition.predecessor_repository_code_loaded -or
    $transition.codex_processes_requested -ne 0 -or
    $transition.provider_credentials_supplied -or
    -not $transition.fresh_successor_required -or
    $transition.verdict -cne 'pass') {
    throw 'Task 9 transition/receipt cross-binding mismatch'
}
if ($manifest.schema_version -cne 'complete-suite-task9-checkout-manifest-v1' -or
    $manifest.commit -cne $receipt.task9_commit -or
    $manifest.tree -cne $receipt.task9_tree -or
    $manifest.root -cne $receipt.checkout_root -or
    $manifest.file_count -ne $manifest.entries.Count -or
    $manifest.file_count -lt 18 -or $manifest.file_bytes -lt 1 -or
    $manifest.aggregate_sha256 -cnotmatch $shaPattern) {
    throw 'Task 9 manifest/receipt cross-binding mismatch'
}
$manifestEntryKeys=@(
    'relative_path','mode','blob','size','sha256','lf_only','nul_free'
)
$manifestEntries=[Collections.Generic.Dictionary[string,object]]::new(
    [StringComparer]::Ordinal
)
$previousRelative=$null
foreach ($entry in $manifest.entries) {
    Assert-C6AuthenticatedObject -Value $entry -ExpectedKeys $manifestEntryKeys `
        -Label 'Task 9 manifest entry'
    Assert-C6AuthenticatedScalarTypes -Value $entry `
        -StringKeys @('relative_path','mode','blob','sha256') `
        -IntegerKeys @('size') -BooleanKeys @('lf_only','nul_free') `
        -Label 'Task 9 manifest entry'
    if ($entry.relative_path -cnotmatch
            '\A(?!/)(?!.*(?:\A|/)\.\.?(?:/|\z))(?!.*\\)[A-Za-z0-9._/-]+\z' -or
        $entry.mode -notin @('100644','100755') -or
        $entry.blob -cnotmatch $oidPattern -or $entry.size -lt 0 -or
        $entry.sha256 -cnotmatch $shaPattern -or
        ($null -ne $previousRelative -and
         [StringComparer]::Ordinal.Compare($previousRelative,$entry.relative_path) -ge 0)) {
        throw "Task 9 manifest entry binding mismatch: $($entry.relative_path)"
    }
    $manifestEntries.Add([string]$entry.relative_path,$entry)
    $previousRelative=[string]$entry.relative_path
}
$producerRelative='docs/superpowers/plans/' +
    '2026-08-21-kokoroarc-complete-suite-campaign-6-task9-transition.ps1'
if ($script:C6PlanOwnedProducerPath -isnot [string] -or
    -not [IO.Path]::IsPathFullyQualified($script:C6PlanOwnedProducerPath) -or
    $script:C6PlanOwnedProducerBlob -isnot [string] -or
    $script:C6PlanOwnedProducerBlob -cnotmatch $oidPattern -or
    $script:C6PlanOwnedProducerSize -isnot [long] -or
    $script:C6PlanOwnedProducerSize -lt 1 -or
    $script:C6PlanOwnedProducerSize -gt 1048576 -or
    $script:C6PlanOwnedProducerSha256 -isnot [string] -or
    $script:C6PlanOwnedProducerSha256 -cnotmatch $shaPattern -or
    -not $manifestEntries.ContainsKey($producerRelative)) {
    throw 'plan-owned producer literal/manifest binding mismatch'
}
$producerEntry=$manifestEntries[$producerRelative]
$producerExpectedPath=[IO.Path]::GetFullPath(
    [IO.Path]::Combine(
        $receipt.checkout_root,$producerRelative.Replace('/',[char]92)
    )
)
if ([IO.Path]::GetFullPath($script:C6PlanOwnedProducerPath) -cne
        $producerExpectedPath -or
    $producerEntry.blob -cne $script:C6PlanOwnedProducerBlob -or
    $producerEntry.size -ne $script:C6PlanOwnedProducerSize -or
    $producerEntry.sha256 -cne $script:C6PlanOwnedProducerSha256 -or
    $producerEntry.mode -cne '100644' -or
    -not $producerEntry.lf_only -or -not $producerEntry.nul_free) {
    throw 'plan-owned producer P-handoff/manifest cross-binding mismatch'
}
$leafBindings=@(
    @('control_plane','tests/skills/complete_suite_control_plane.ps1','control-plane'),
    @('python_bootstrap','tests/skills/complete_suite_release_python_bootstrap.py','bootstrap'),
    @('artifact_launcher','tests/skills/complete_suite_artifact_launcher.ps1','launcher'),
    @('artifact_writer','tests/skills/complete_suite_artifact_writer.py','writer')
)
foreach ($binding in $leafBindings) {
    $prefix=[string]$binding[0]
    $relative=[string]$binding[1]
    $heldRole=[string]$binding[2]
    if (-not $manifestEntries.ContainsKey($relative)) {
        throw "Task 9 manifest missing authenticated leaf: $relative"
    }
    $entry=$manifestEntries[$relative]
    $expectedPath=[IO.Path]::GetFullPath(
        [IO.Path]::Combine($receipt.checkout_root,$relative.Replace('/',[char]92))
    )
    if ($trust["${prefix}_path"] -cne $expectedPath -or
        $trust["${prefix}_blob"] -cne $entry.blob -or
        $trust["${prefix}_size"] -ne $entry.size -or
        $trust["${prefix}_sha256"] -cne $entry.sha256 -or
        $heldByRole[$heldRole].length -ne $entry.size -or
        $heldByRole[$heldRole].sha256 -cne $entry.sha256 -or
        $entry.mode -cne '100644' -or -not $entry.lf_only -or -not $entry.nul_free) {
        throw "Task 9 trust/manifest leaf mismatch: $relative"
    }
}
if ($oracle.schema_version -cne
        'complete-suite-task9-artifact-source-oracle-v1' -or
    $oracle.plan_commit -cne $receipt.plan_commit -or
    $oracle.task9_commit -cne $receipt.task9_commit -or
    $oracle.task9_tree -cne $receipt.task9_tree -or
    $oracle.algorithm_table_revision -cne
        'complete-suite-task9-artifact-source-oracle-algorithms-v1' -or
    $oracle.algorithm_table_sha256 -cne
        '048fa0d9fc0e66562dd35bb3d0bd1598e23cd7af9febaa6f499eb676d93bb445' -or
    $oracle.digest_count -ne 8 -or $oracle.sources.Count -ne 2 -or
    $oracle.semantics.Count -ne 6 -or
    $heldByRole['oracle'].length -ne $receipt.artifact_oracle_size -or
    (Get-C6AuthenticatedGitBlob $heldByRole['oracle'].bytes) -cne
        $receipt.artifact_oracle_blob) {
    throw 'Task 9 artifact oracle/receipt cross-binding mismatch'
}
$sourceKeys=@('id','relative_path','size','sha256')
$sourceIds=@('artifact-launcher','artifact-writer')
$sourcePaths=@(
    'tests/skills/complete_suite_artifact_launcher.ps1',
    'tests/skills/complete_suite_artifact_writer.py'
)
for ($index=0; $index -lt 2; $index++) {
    $source=$oracle.sources[$index]
    Assert-C6AuthenticatedObject -Value $source -ExpectedKeys $sourceKeys `
        -Label 'Task 9 artifact oracle source'
    Assert-C6AuthenticatedScalarTypes -Value $source `
        -StringKeys @('id','relative_path','sha256') -IntegerKeys @('size') `
        -BooleanKeys @() -Label 'Task 9 artifact oracle source'
    $entry=$manifestEntries[$sourcePaths[$index]]
    if ($source.id -cne $sourceIds[$index] -or
        $source.relative_path -cne $sourcePaths[$index] -or
        $source.size -ne $entry.size -or $source.sha256 -cne $entry.sha256) {
        throw "Task 9 artifact oracle source mismatch: $index"
    }
}
$semanticKeys=@('id','sha256')
$semanticIds=@(
    'launcher-ast','launcher-bootstrap-fixture','launcher-rawui-reader',
    'writer-ast','writer-closed-import-native-call-table',
    'writer-launcher-fixture'
)
for ($index=0; $index -lt 6; $index++) {
    $semantic=$oracle.semantics[$index]
    Assert-C6AuthenticatedObject -Value $semantic -ExpectedKeys $semanticKeys `
        -Label 'Task 9 artifact oracle semantic'
    Assert-C6AuthenticatedScalarTypes -Value $semantic `
        -StringKeys $semanticKeys -IntegerKeys @() -BooleanKeys @() `
        -Label 'Task 9 artifact oracle semantic'
    if ($semantic.id -cne $semanticIds[$index] -or
        $semantic.sha256 -cnotmatch $shaPattern) {
        throw "Task 9 artifact oracle semantic mismatch: $index"
    }
}
$controlPlaneBytes=$controlHeld.bytes
$artifactLauncherBytes=$launcherHeld.bytes
$artifactWriterBytes=$writerHeld.bytes
if ($artifactLauncherBytes.Length -ne $script:C6Task9ArtifactLauncherSize -or
    $artifactLauncherBytes[-1] -ne 10 -or 0 -in $artifactLauncherBytes -or
    13 -in $artifactLauncherBytes -or
    ($artifactLauncherBytes.Length -ge 3 -and
     $artifactLauncherBytes[0] -eq 239 -and
     $artifactLauncherBytes[1] -eq 187 -and
     $artifactLauncherBytes[2] -eq 191) -or
    $artifactWriterBytes.Length -ne $script:C6Task9ArtifactWriterSize -or
    $artifactWriterBytes[-1] -ne 10 -or 0 -in $artifactWriterBytes -or
    13 -in $artifactWriterBytes -or
    ($artifactWriterBytes.Length -ge 3 -and
     $artifactWriterBytes[0] -eq 239 -and
     $artifactWriterBytes[1] -eq 187 -and
     $artifactWriterBytes[2] -eq 191)) {
    throw 'Task 9 artifact launcher/writer byte envelope mismatch'
}
$null=$utf8.GetString($artifactLauncherBytes)
$null=$utf8.GetString($artifactWriterBytes)
$controlPlaneText=$utf8.GetString($controlPlaneBytes)
if (-not $controlPlaneText.EndsWith("`n") -or
    $controlPlaneText.Contains("`r") -or
    $controlPlaneText.Contains([char]0)) {
    throw 'Task 9 control plane is not strict LF UTF-8'
}
$controlPlaneBlock=[ScriptBlock]::Create($controlPlaneText)
. $controlPlaneBlock
$public=@('Invoke-C6RootPython','Invoke-C6Git')
foreach ($name in $public) {
    $command=Get-Command -Name $name -CommandType Function -ErrorAction Stop
    if ($command.Name -cne $name) { throw "missing control-plane function: $name" }
}
} catch {
    $successorVerifierFailure=$_
    throw
} finally {
    $retainedRehashFailure=$null
    for ($heldIndex=$heldAuthenticatedFiles.Count-1; $heldIndex -ge 0;
            $heldIndex--) {
        $held=$heldAuthenticatedFiles[$heldIndex]
        try {
            Confirm-C6AuthenticatedBytes $held
        } catch {
            if ($null -eq $retainedRehashFailure) {
                $retainedRehashFailure=$_
            }
        } finally {
            if ($null -ne $held.stream) {
                try {
                    $held.stream.Dispose()
                } catch {
                    if ($null -eq $retainedRehashFailure) {
                        $retainedRehashFailure=$_
                    }
                }
            }
        }
    }
    if ($null -ne $retainedRehashFailure) {
        if ($null -ne $successorVerifierFailure) {
            $successorVerifierFailure.Exception.Data[
                'C6RetainedRecordRehashFailure'
            ]=$retainedRehashFailure.Exception.Message
        } else {
            throw $retainedRehashFailure
        }
    }
}
'@
    return ($successorVerifierText + "`n")
}


$script:C6Task9ProducerTerminationGraceMs=5000
$script:C6Task9ProducerNativeVectorBindings=[Collections.Generic.List[object]]::new()

function Assert-C6WindowsNativeVectorString {
    param([Parameter(Mandatory)][AllowNull()][object]$Value)
    if ($null -eq $Value) { throw 'native vector contains null string' }
    if ($Value -isnot [string]) { throw 'native vector value is not a string' }
    [string]$text=$Value
    for ($index=0; $index -lt $text.Length; $index++) {
        $character=$text[$index]
        if ($character -eq [char]0) { throw 'native vector contains NUL' }
        if ([char]::IsHighSurrogate($character)) {
            if ($index + 1 -ge $text.Length -or
                -not [char]::IsLowSurrogate($text[$index + 1])) {
                throw 'native vector contains unpaired high surrogate'
            }
            $index++
        } elseif ([char]::IsLowSurrogate($character)) {
            throw 'native vector contains unpaired low surrogate'
        }
    }
}

function ConvertTo-C6WindowsNativeArgument {
    param([Parameter(Mandatory)][AllowNull()][object]$Value)
    Assert-C6WindowsNativeVectorString -Value $Value
    [string]$text=$Value
    $requiresQuotes=($text.Length -eq 0)
    if (-not $requiresQuotes) {
        foreach ($character in $text.ToCharArray()) {
            if ($character -eq '"' -or $character -eq ' ' -or
                $character -eq [char]9) {
                $requiresQuotes=$true
                break
            }
        }
    }
    if (-not $requiresQuotes) { return $text }
    $builder=[Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashes=0
    foreach ($character in $text.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            if ($backslashes -gt 0) {
                [void]$builder.Append(('\' * (2 * $backslashes)))
            }
            [void]$builder.Append('\')
            [void]$builder.Append('"')
            $backslashes=0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes=0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * (2 * $backslashes)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Get-C6WindowsNativeVectorBinding {
    param(
        [Parameter(Mandatory)][AllowNull()][object]$Executable,
        [Parameter(Mandatory)][AllowNull()][object]$ArgumentList
    )
    Assert-C6WindowsNativeVectorString -Value $Executable
    [string]$executableText=$Executable
    if ($executableText.Length -eq 0 -or
        -not [IO.Path]::IsPathFullyQualified($executableText)) {
        throw 'native vector executable is not absolute'
    }
    if ($null -eq $ArgumentList -or $ArgumentList -isnot [object[]]) {
        throw 'native vector argument list is not an array'
    }
    $serialized=[Collections.Generic.List[string]]::new()
    [void]$serialized.Add((ConvertTo-C6WindowsNativeArgument -Value $executableText))
    foreach ($argument in [object[]]$ArgumentList) {
        [void]$serialized.Add((ConvertTo-C6WindowsNativeArgument -Value $argument))
    }
    $commandLine=[string]::Join(' ',$serialized)
    [int]$unitCount=$commandLine.Length + 1
    if ($unitCount -gt 30000) { throw 'native vector exceeds 30000 UTF-16 units' }
    $serializedBytes=[Text.Encoding]::Unicode.GetBytes($commandLine + [char]0)
    return [pscustomobject]@{
        contract='complete-suite-windows-native-vector-v1'
        utf16_units=$unitCount
        utf16le_sha256=[Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData($serializedBytes)
        ).ToLowerInvariant()
    }
}

function Stop-C6Task9ProducerChild {
    param([Parameter(Mandatory)][Diagnostics.Process]$Process)
    if (-not $Process.HasExited) {
        try { $Process.Kill($true) } catch {
            if (-not $Process.HasExited) {
                throw 'Task 9 producer child-tree termination request failed'
            }
        }
    }
    if (-not $Process.WaitForExit($script:C6Task9ProducerTerminationGraceMs)) {
        throw 'Task 9 producer child did not exit within termination grace'
    }
}

function New-C6Task9ProducerGitEnvironment {
    param([Parameter(Mandatory)][string]$PrivateRoot)
    if ($PrivateRoot -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-pretrust-git-[0-9a-f]{32}\z' -or
        [IO.Path]::GetDirectoryName($PrivateRoot) -cne 'D:\tmp' -or
        [IO.Directory]::Exists($PrivateRoot) -or
        [IO.File]::Exists($PrivateRoot)) {
        throw 'invalid or pre-existing Task 9 producer Git root'
    }
    [void][IO.Directory]::CreateDirectory($PrivateRoot)
    $profile=[IO.Directory]::CreateDirectory((Join-Path $PrivateRoot 'profile')).FullName
    $temp=[IO.Directory]::CreateDirectory((Join-Path $PrivateRoot 'tmp')).FullName
    $xdg=[IO.Directory]::CreateDirectory((Join-Path $PrivateRoot 'xdg')).FullName
    $appDataRoot=[IO.Directory]::CreateDirectory((Join-Path $profile 'AppData')).FullName
    $appData=[IO.Directory]::CreateDirectory((Join-Path $appDataRoot 'Roaming')).FullName
    $localAppData=[IO.Directory]::CreateDirectory((Join-Path $appDataRoot 'Local')).FullName
    return [ordered]@{
        APPDATA=$appData; COMSPEC='C:\Windows\System32\cmd.exe'; HOME=$profile
        LOCALAPPDATA=$localAppData; NO_COLOR='1'; PATHEXT='.COM;.EXE;.BAT;.CMD'
        PATH='C:\Program Files\Git\mingw64\bin;C:\Program Files\Git\cmd;C:\Windows\System32;C:\Windows'
        SYSTEMROOT='C:\Windows'; TEMP=$temp; TMP=$temp; USERPROFILE=$profile
        WINDIR='C:\Windows'; GCM_INTERACTIVE='never'; GIT_ASKPASS=''
        GIT_ATTR_NOSYSTEM='1'; GIT_CONFIG_GLOBAL='NUL'; GIT_CONFIG_NOSYSTEM='1'
        GIT_NO_LAZY_FETCH='1'; GIT_OPTIONAL_LOCKS='0'; GIT_TERMINAL_PROMPT='0'
        LANG='C'; LC_ALL='C'; SSH_ASKPASS=''; XDG_CONFIG_HOME=$xdg
    }
}

function Get-C6PlanOwnedSha256 {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($Bytes)
    ).ToLowerInvariant()
}

function Assert-C6PlanOwnedKeys {
    param(
        [Parameter(Mandatory)][Collections.IDictionary]$Value,
        [Parameter(Mandatory)][string[]]$Expected,
        [Parameter(Mandatory)][string]$Label
    )
    $actual=@($Value.Keys | ForEach-Object { [string]$_ })
    if (($actual -join "`n") -cne ($Expected -join "`n")) {
        throw "$Label keys are not exact or ordered"
    }
}

function Assert-C6PlanOwnedScalarTypes {
    param(
        [Parameter(Mandatory)][Collections.IDictionary]$Value,
        [Parameter(Mandatory)][string[]]$StringKeys,
        [Parameter(Mandatory)][string[]]$IntegerKeys,
        [Parameter(Mandatory)][string]$Label
    )
    foreach ($key in $StringKeys) {
        if (-not $Value.Contains($key) -or $Value[$key] -isnot [string]) {
            throw "$Label exact string type mismatch: $key"
        }
    }
    foreach ($key in $IntegerKeys) {
        if (-not $Value.Contains($key) -or $Value[$key] -isnot [long]) {
            throw "$Label exact integer type mismatch: $key"
        }
    }
}

function Read-C6PlanOwnedJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
        [Parameter(Mandatory)][ValidateRange(1,8388608)][int]$MaxBytes
    )
    if (-not [IO.Path]::IsPathFullyQualified($Path)) {
        throw "record path is not absolute: $Path"
    }
    Initialize-C6PlanOwnedNativeFileApi
    $full=[IO.Path]::GetFullPath($Path)
    $opened=[C6PlanOwnedNativeFile]::OpenRegular($full)
    try {
        if ($opened.Length -lt 2 -or $opened.Length -gt $MaxBytes -or
            $opened.Length -gt [int]::MaxValue) {
            throw "record path/type/size rejected: $Path"
        }
        [byte[]]$bytes=[byte[]]::new([int]$opened.Length)
        $offset=0
        while ($offset -lt $bytes.Length) {
            $count=$opened.Stream.Read($bytes,$offset,$bytes.Length-$offset)
            if ($count -le 0) { throw "record short read: $Path" }
            $offset += $count
        }
        if ($opened.Stream.ReadByte() -ne -1 -or
            $opened.Stream.Length -ne $bytes.Length -or
            $bytes[-1] -ne 10 -or 0 -in $bytes -or 13 -in $bytes -or
            (Get-C6PlanOwnedSha256 $bytes) -cne $ExpectedSha256) {
            throw "record bytes rejected: $Path"
        }
    } finally {
        $opened.Dispose()
    }
    $strictUtf8=[Text.UTF8Encoding]::new($false,$true)
    $text=$strictUtf8.GetString($bytes)
    $parsed=$text | ConvertFrom-Json -AsHashtable -NoEnumerate -ErrorAction Stop
    $roundTrip=(
        ConvertTo-Json -InputObject $parsed -Compress -Depth 30
    ) + "`n"
    if ($roundTrip -cne $text) {
        throw "record is not canonical compact JSON: $Path"
    }
    return [pscustomobject]@{
        bytes=$bytes
        parsed=$parsed
        sha256=$ExpectedSha256
    }
}

function Read-C6PlanOwnedHeldJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
        [Parameter(Mandatory)][ValidateRange(2,8388608)][int]$MaxBytes,
        [Parameter(Mandatory)][string]$Role
    )
    if (-not [IO.Path]::IsPathFullyQualified($Path)) {
        throw "$Role record path is not absolute"
    }
    Initialize-C6PlanOwnedNativeFileApi
    $opened=[C6PlanOwnedNativeFile]::OpenRegular([IO.Path]::GetFullPath($Path))
    try {
        if ($opened.Length -lt 2 -or $opened.Length -gt $MaxBytes -or
            $opened.Length -gt [int]::MaxValue) {
            throw "$Role record exceeds its preallocation cap"
        }
        [byte[]]$bytes=[byte[]]::new([int]$opened.Length)
        $offset=0
        while ($offset -lt $bytes.Length) {
            $count=$opened.Stream.Read($bytes,$offset,$bytes.Length-$offset)
            if ($count -le 0) { throw "$Role record short read" }
            $offset += $count
        }
        if ($opened.Stream.ReadByte() -ne -1 -or
            $opened.Stream.Length -ne $bytes.Length -or
            $bytes[-1] -ne 10 -or 0 -in $bytes -or 13 -in $bytes -or
            (Get-C6PlanOwnedSha256 $bytes) -cne $ExpectedSha256) {
            throw "$Role record byte envelope mismatch"
        }
        $strictUtf8=[Text.UTF8Encoding]::new($false,$true)
        $text=$strictUtf8.GetString($bytes)
        $parsed=$text | ConvertFrom-Json -AsHashtable -NoEnumerate `
            -ErrorAction Stop
        if ((ConvertTo-Json -InputObject $parsed -Compress -Depth 30) + "`n" -cne
                $text) {
            throw "$Role record is not canonical compact JSON"
        }
        $opened.Stream.Position=0
        return [pscustomobject]@{
            role=$Role
            path=[IO.Path]::GetFullPath($Path)
            sha256=$ExpectedSha256
            bytes=$bytes
            parsed=$parsed
            opened=$opened
        }
    } catch {
        $opened.Dispose()
        throw
    }
}

function Confirm-C6PlanOwnedHeldJson {
    param([Parameter(Mandatory)]$Held)
    $Held.opened.Stream.Position=0
    [byte[]]$recheck=[byte[]]::new($Held.bytes.Length)
    $offset=0
    while ($offset -lt $recheck.Length) {
        $count=$Held.opened.Stream.Read($recheck,$offset,$recheck.Length-$offset)
        if ($count -le 0) { throw "$($Held.role) held record short re-read" }
        $offset += $count
    }
    if ($Held.opened.Stream.ReadByte() -ne -1 -or
        $Held.opened.Stream.Length -ne $recheck.Length -or
        (Get-C6PlanOwnedSha256 $recheck) -cne $Held.sha256 -or
        [Convert]::ToBase64String($recheck) -cne
            [Convert]::ToBase64String($Held.bytes)) {
        throw "$($Held.role) held record drifted"
    }
    $Held.opened.Stream.Position=0
}

function Get-C6PlanOwnedOracleProjection {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string[]]$ExpectedKeys,
        [Parameter(Mandatory)][string]$Label
    )
    $lines=@($Text.Split("`n"))
    $begin=@(); $payload=@(); $end=@()
    for ($index=0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -ceq '# C6-ARTIFACT-SOURCE-ORACLE-BEGIN') {
            $begin += $index
        } elseif ($lines[$index].StartsWith(
                '# C6-ARTIFACT-SOURCE-ORACLE ',
                [StringComparison]::Ordinal
            )) {
            $payload += $index
        } elseif ($lines[$index] -ceq '# C6-ARTIFACT-SOURCE-ORACLE-END') {
            $end += $index
        }
    }
    if ($begin.Count -ne 1 -or $payload.Count -ne 1 -or $end.Count -ne 1 -or
        $payload[0] -ne $begin[0]+1 -or $end[0] -ne $payload[0]+1) {
        throw "$Label source-oracle delimiters are not unique and adjacent"
    }
    $json=$lines[$payload[0]].Substring(
        '# C6-ARTIFACT-SOURCE-ORACLE '.Length
    )
    [byte[]]$ascii=[Text.Encoding]::ASCII.GetBytes($json)
    if ([Text.Encoding]::ASCII.GetString($ascii) -cne $json) {
        throw "$Label source-oracle payload is not ASCII"
    }
    $parsed=$json | ConvertFrom-Json -AsHashtable -NoEnumerate `
        -ErrorAction Stop
    if ($parsed -isnot [Collections.IDictionary]) {
        throw "$Label source-oracle payload is not an object"
    }
    Assert-C6PlanOwnedKeys -Value $parsed -Expected $ExpectedKeys `
        -Label "$Label source-oracle payload"
    Assert-C6PlanOwnedScalarTypes -Value $parsed -StringKeys $ExpectedKeys `
        -IntegerKeys @() -Label "$Label source-oracle payload"
    foreach ($key in $ExpectedKeys) {
        if ($parsed[$key] -cnotmatch '^[0-9a-f]{64}$') {
            throw "$Label source-oracle digest mismatch: $key"
        }
    }
    if ((ConvertTo-Json -InputObject $parsed -Compress -Depth 5) -cne $json) {
        throw "$Label source-oracle payload is not canonical"
    }
    return $parsed
}

function Get-C6PlanOwnedArtifactBundleSha256 {
    param(
        [Parameter(Mandatory)][byte[]]$LauncherBytes,
        [Parameter(Mandatory)][byte[]]$WriterBytes
    )
    $hash=[Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try {
        foreach ($entry in @(
            @('artifact-launcher',[object]$LauncherBytes),
            @('artifact-writer',[object]$WriterBytes)
        )) {
            [byte[]]$bytes=[byte[]]$entry[1]
            [byte[]]$header=[Text.Encoding]::ASCII.GetBytes(
                [string]$entry[0] + ':' + $bytes.Length + "`n"
            )
            $hash.AppendData($header)
            $hash.AppendData($bytes)
        }
        return [Convert]::ToHexString(
            $hash.GetHashAndReset()
        ).ToLowerInvariant()
    } finally {
        $hash.Dispose()
    }
}

function Write-C6PlanOwnedJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][Collections.IDictionary]$Value,
        [Parameter(Mandatory)][string[]]$ExpectedKeys,
        [Parameter(Mandatory)][ValidateRange(2,8388608)][int]$MaxBytes
    )
    Assert-C6PlanOwnedKeys -Value $Value -Expected $ExpectedKeys -Label $Path
    if (Test-Path -LiteralPath $Path) {
        throw "terminal record already exists: $Path"
    }
    $parent=Get-Item -LiteralPath ([IO.Path]::GetDirectoryName($Path)) `
        -Force -ErrorAction Stop
    if (-not $parent.PSIsContainer -or
        (($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw "terminal record parent is not an observed plain directory: $Path"
    }
    $strictUtf8=[Text.UTF8Encoding]::new($false,$true)
    $text=(
        ConvertTo-Json -InputObject $Value -Compress -Depth 30
    ) + "`n"
    [byte[]]$bytes=$strictUtf8.GetBytes($text)
    if ($bytes.Length -lt 2 -or $bytes.Length -gt $MaxBytes -or
        $bytes[-1] -ne 10 -or 0 -in $bytes -or 13 -in $bytes) {
        throw "terminal record violates its UTF-8/LF/size envelope: $Path"
    }
    $sha256=Get-C6PlanOwnedSha256 $bytes
    $stream=[IO.FileStream]::new(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None,
        65536,
        [IO.FileOptions]::WriteThrough
    )
    try {
        $stream.Write($bytes,0,$bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
    $reopened=Read-C6PlanOwnedJson -Path $Path `
        -ExpectedSha256 $sha256 -MaxBytes $MaxBytes
    Assert-C6PlanOwnedKeys -Value $reopened.parsed `
        -Expected $ExpectedKeys -Label $Path
    if ($reopened.bytes.Length -ne $bytes.Length -or
        [Convert]::ToBase64String($reopened.bytes) -cne
            [Convert]::ToBase64String($bytes)) {
        throw "terminal record reopen is not byte-identical: $Path"
    }
    return [pscustomobject]@{
        path=$Path
        sha256=$sha256
        size=[long]$bytes.Length
        parsed=$reopened.parsed
    }
}

function New-C6PlanOwnedRoot {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Pattern
    )
    if ($Root -cnotmatch $Pattern -or
        [IO.Path]::GetDirectoryName($Root) -cne 'D:\tmp' -or
        (Test-Path -LiteralPath $Root)) {
        throw "writer root is outside its grammar or already exists: $Root"
    }
    $tmpItem=Get-Item -LiteralPath 'D:\tmp' -Force -ErrorAction Stop
    if (-not $tmpItem.PSIsContainer -or
        (($tmpItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'D:\tmp is not an observed plain directory'
    }
    New-Item -ItemType Directory -Path $Root -ErrorAction Stop | Out-Null
    $created=Get-Item -LiteralPath $Root -Force -ErrorAction Stop
    if (-not $created.PSIsContainer -or
        (($created.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw "created writer root is not an observed plain directory: $Root"
    }
}

function Assert-C6PlanOwnedMembership {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string[]]$ExpectedNames
    )
    $members=@(Get-ChildItem -LiteralPath $Root -Force -ErrorAction Stop)
    $actual=@($members.Name | Sort-Object)
    $expected=@($ExpectedNames | Sort-Object)
    if ($members.Count -ne $ExpectedNames.Count -or
        ($actual -join "`n") -cne ($expected -join "`n")) {
        throw "writer root membership mismatch: $Root"
    }
    foreach ($member in $members) {
        if ($member.PSIsContainer -or
            (($member.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "writer root has a non-plain member: $($member.FullName)"
        }
    }
}

function Initialize-C6PlanOwnedNativeFileApi {
    if ($null -ne ('C6PlanOwnedNativeFile' -as [type])) { return }
    Add-Type -Language CSharp -ErrorAction Stop -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public sealed class C6PlanOwnedOpenedFile : IDisposable
{
    public FileStream Stream { get; private set; }
    public string Identity { get; private set; }
    public long Length { get; private set; }

    internal C6PlanOwnedOpenedFile(
        SafeFileHandle handle, string identity, long length)
    {
        Stream = new FileStream(handle, FileAccess.Read, 65536, false);
        Identity = identity;
        Length = length;
    }

    public void Dispose()
    {
        if (Stream != null) {
            Stream.Dispose();
            Stream = null;
        }
    }
}

public static class C6PlanOwnedNativeFile
{
    private const uint GENERIC_READ = 0x80000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint FILE_SHARE_DELETE = 0x00000004;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_ATTRIBUTE_DIRECTORY = 0x00000010;
    private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400;
    private const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
    private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
    private const uint FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000;

    [StructLayout(LayoutKind.Sequential)]
    private struct BY_HANDLE_FILE_INFORMATION
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode,
        SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string name, uint access, uint share, IntPtr security,
        uint creation, uint flags, IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle handle, out BY_HANDLE_FILE_INFORMATION info);

    private static BY_HANDLE_FILE_INFORMATION GetInfo(SafeFileHandle handle)
    {
        BY_HANDLE_FILE_INFORMATION info;
        if (!GetFileInformationByHandle(handle, out info)) {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return info;
    }

    private static string Identity(BY_HANDLE_FILE_INFORMATION info)
    {
        return info.VolumeSerialNumber.ToString("x8") + ":" +
            info.FileIndexHigh.ToString("x8") + ":" +
            info.FileIndexLow.ToString("x8");
    }

    public static void AssertPlainDirectory(string path)
    {
        using (SafeFileHandle handle = CreateFileW(
            path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            IntPtr.Zero, OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
            IntPtr.Zero)) {
            if (handle.IsInvalid) {
                throw new Win32Exception(Marshal.GetLastWin32Error(), path);
            }
            BY_HANDLE_FILE_INFORMATION info = GetInfo(handle);
            if ((info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0 ||
                (info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
                throw new IOException("not a plain directory: " + path);
            }
        }
    }

    public static C6PlanOwnedOpenedFile OpenRegular(string path)
    {
        SafeFileHandle handle = CreateFileW(
            path, GENERIC_READ, FILE_SHARE_READ, IntPtr.Zero, OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN,
            IntPtr.Zero);
        if (handle.IsInvalid) {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, path);
        }
        try {
            BY_HANDLE_FILE_INFORMATION info = GetInfo(handle);
            if ((info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0 ||
                (info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
                info.NumberOfLinks != 1) {
                throw new IOException("not a single-link plain regular file: " + path);
            }
            long length = ((long)info.FileSizeHigh << 32) | info.FileSizeLow;
            return new C6PlanOwnedOpenedFile(handle, Identity(info), length);
        } catch {
            handle.Dispose();
            throw;
        }
    }
}
'@
}

function Resolve-C6PlanOwnedPlainFile {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath
    )
    Initialize-C6PlanOwnedNativeFileApi
    if (-not [IO.Path]::IsPathFullyQualified($Root) -or
        $RelativePath -notmatch '\A[^\\/:\x00-\x1f]+(?:/[^\\/:\x00-\x1f]+)*\z' -or
        @($RelativePath.Split('/')).Where({ $_ -in @('.','..') }).Count -ne 0) {
        throw "invalid plan-owned relative path: $RelativePath"
    }
    $rootFull=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    $candidate=[IO.Path]::GetFullPath(
        [IO.Path]::Combine($rootFull,$RelativePath.Replace('/','\'))
    )
    $prefix=$rootFull + '\'
    if (-not $candidate.StartsWith(
            $prefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw "plan-owned path escaped its root: $RelativePath"
    }
    [C6PlanOwnedNativeFile]::AssertPlainDirectory($rootFull)
    $current=$rootFull
    $parts=@($RelativePath.Split('/'))
    for ($index=0; $index -lt $parts.Count-1; $index++) {
        $current=[IO.Path]::Combine($current,$parts[$index])
        [C6PlanOwnedNativeFile]::AssertPlainDirectory($current)
    }
    return $candidate
}

function Assert-C6PlanOwnedSingleLinkFile {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$Label
    )
    $full=Resolve-C6PlanOwnedPlainFile -Root $Root -RelativePath $RelativePath
    $opened=$null
    $primaryFailure=$null
    try {
        $opened=[C6PlanOwnedNativeFile]::OpenRegular($full)
    } catch {
        $primaryFailure=$_
        throw
    } finally {
        if ($null -ne $opened) {
            try {
                $opened.Dispose()
            } catch {
                if ($null -ne $primaryFailure) {
                    $primaryFailure.Exception.Data[
                        'C6SingleLinkCensusDisposeFailure'
                    ]=$_.Exception.Message
                } else {
                    throw
                }
            }
        }
    }
    [void](Resolve-C6PlanOwnedPlainFile -Root $Root -RelativePath $RelativePath)
}

function Assert-C6PlanOwnedSingleLinkCensus {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][ValidateRange(1,50000)][int]$MaxFiles,
        [Parameter(Mandatory)][ValidateRange(1,50000)][int]$MaxDirectories
    )
    Initialize-C6PlanOwnedNativeFileApi
    $rootFull=[IO.Path]::GetFullPath($Root).TrimEnd([char]92)
    [C6PlanOwnedNativeFile]::AssertPlainDirectory($rootFull)
    $rootPrefix=$rootFull + [char]92
    $pending=[Collections.Generic.Stack[string]]::new()
    $pending.Push('')
    $fileCount=0
    $directoryCount=0
    while ($pending.Count -gt 0) {
        $relativeDirectory=$pending.Pop()
        $directoryPath=if ($relativeDirectory.Length -eq 0) {
            $rootFull
        } else {
            Resolve-C6PlanOwnedPlainFile -Root $rootFull `
                -RelativePath $relativeDirectory
        }
        [C6PlanOwnedNativeFile]::AssertPlainDirectory($directoryPath)
        $enumerator=$null
        $enumerationFailure=$null
        try {
            $enumerator=[IO.Directory]::EnumerateFileSystemEntries(
                $directoryPath
            ).GetEnumerator()
            while ($enumerator.MoveNext()) {
                $absolute=[IO.Path]::GetFullPath([string]$enumerator.Current)
                if (-not $absolute.StartsWith(
                        $rootPrefix,[StringComparison]::OrdinalIgnoreCase)) {
                    throw 'single-link census member escaped its root'
                }
                $relative=[IO.Path]::GetRelativePath(
                    $rootFull,$absolute
                ).Replace([char]92,[char]47)
                $attributes=[IO.File]::GetAttributes($absolute)
                if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw "single-link census rejects reparse member: $relative"
                }
                if (($attributes -band [IO.FileAttributes]::Directory) -ne 0) {
                    $directoryCount++
                    if ($directoryCount -gt $MaxDirectories) {
                        throw 'single-link census directory cap exceeded'
                    }
                    $resolved=Resolve-C6PlanOwnedPlainFile `
                        -Root $rootFull -RelativePath $relative
                    if (-not $resolved.Equals(
                            $absolute,[StringComparison]::OrdinalIgnoreCase)) {
                        throw "single-link census directory aliases root: $relative"
                    }
                    [C6PlanOwnedNativeFile]::AssertPlainDirectory($resolved)
                    $pending.Push($relative)
                } else {
                    $fileCount++
                    if ($fileCount -gt $MaxFiles) {
                        throw 'single-link census file cap exceeded'
                    }
                    Assert-C6PlanOwnedSingleLinkFile -Root $rootFull `
                        -RelativePath $relative -Label checkout-census
                }
            }
        } catch {
            $enumerationFailure=$_
            throw
        } finally {
            if ($null -ne $enumerator) {
                try {
                    $enumerator.Dispose()
                } catch {
                    if ($null -ne $enumerationFailure) {
                        $enumerationFailure.Exception.Data[
                            'C6SingleLinkCensusEnumerationDisposeFailure'
                        ]=$_.Exception.Message
                    } else {
                        throw
                    }
                }
            }
        }
    }
    if ($fileCount -lt 1) {
        throw 'single-link census found no files'
    }
}

function Read-C6PlanOwnedPlainFile {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][ValidateRange(1,8388608)][int]$MaxBytes,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256
    )
    $full=Resolve-C6PlanOwnedPlainFile -Root $Root -RelativePath $RelativePath
    $opened=[C6PlanOwnedNativeFile]::OpenRegular($full)
    try {
        if ($opened.Length -lt 1 -or $opened.Length -gt $MaxBytes) {
            throw "plan-owned file is outside its byte cap: $RelativePath"
        }
        [byte[]]$bytes=[byte[]]::new([int]$opened.Length)
        $offset=0
        while ($offset -lt $bytes.Length) {
            $count=$opened.Stream.Read($bytes,$offset,$bytes.Length-$offset)
            if ($count -le 0) { throw "short file read: $RelativePath" }
            $offset += $count
        }
        $identity=$opened.Identity
        $length=$opened.Length
    } finally {
        $opened.Dispose()
    }
    $post=[C6PlanOwnedNativeFile]::OpenRegular($full)
    try {
        if ($post.Identity -cne $identity -or $post.Length -ne $length) {
            throw "file identity drift: $RelativePath"
        }
    } finally {
        $post.Dispose()
    }
    [void](Resolve-C6PlanOwnedPlainFile -Root $Root -RelativePath $RelativePath)
    if ((Get-C6PlanOwnedSha256 $bytes) -cne $ExpectedSha256) {
        throw "file hash drift: $RelativePath"
    }
    return ,$bytes
}

function Invoke-C6Task9PostcheckGit {
    param(
        [Parameter(Mandatory)]
        [ValidateSet(
            'source-root','source-head','source-tree','source-parent',
            'source-parent-line','source-subject','source-branch','source-status',
            'plan-tree','plan-parent','plan-message','plan-entries','plan-delta',
            'plan-ancestor',
            'checkout-head','checkout-tree','checkout-status',
            'checkout-detached','checkout-ls-tree',
            'oracle-head','oracle-tree','oracle-parent','oracle-parent-line',
            'oracle-subject','oracle-status','oracle-detached','oracle-entries',
            'oracle-delta'
        )]
        [string]$Role,
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$CheckoutRoot,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')]
        [string]$Task9Commit,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')]
        [string]$PlanCommit,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')]
        [string]$PlanParent,
        [Parameter(Mandatory)][string]$OracleRoot,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')]
        [string]$OracleCommit,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')]
        [string]$OracleParent
    )
    $git='C:\Program Files\Git\mingw64\bin\git.exe'
    $gitItem=Get-Item -LiteralPath $git -Force -ErrorAction Stop
    if ($gitItem.Length -ne 4285328 -or
        (Get-FileHash -LiteralPath $git -Algorithm SHA256).Hash.ToLowerInvariant() -cne
            'de6c9879b7502cf2f3de9cf311aee18f61df0b8351a0b636069415aaf14bdf22') {
        throw 'Task 9 postcheck Git identity drift'
    }
    $prefix=@(
        '--no-pager','--no-optional-locks','--no-replace-objects',
        '--literal-pathspecs',
        '-c','core.longpaths=true','-c','core.autocrlf=false',
        '-c','core.eol=lf','-c','core.safecrlf=true',
        '-c','core.symlinks=false','-c','core.protectNTFS=true',
        '-c','core.protectHFS=true','-c','core.hooksPath=NUL',
        '-c','core.fsmonitor=false','-c','core.useReplaceRefs=false',
        '-c','core.attributesFile=NUL','-c','core.excludesFile=/dev/null',
        '-c','commit.gpgSign=false','-c','tag.gpgSign=false',
        '-c','credential.helper=','-c','credential.interactive=never',
        '-c','maintenance.auto=false','-c','gc.auto=0',
        '-c','submodule.recurse=false','-c','fetch.recurseSubmodules=false',
        '-c','protocol.allow=never','-c','protocol.file.allow=never',
        '-c','diff.external=','-c','core.pager=cat'
    )
    $rootForRole = if ($Role.StartsWith('checkout-')) {
        $CheckoutRoot
    } elseif ($Role.StartsWith('oracle-')) {
        $OracleRoot
    } else {
        $SourceRoot
    }
    $tail = switch ($Role) {
        'source-root' { @('rev-parse','--show-toplevel') }
        'source-head' { @('rev-parse','--verify','HEAD^{commit}') }
        'source-tree' { @('rev-parse','--verify','HEAD^{tree}') }
        'source-parent' { @('rev-parse','--verify','HEAD^1') }
        'source-parent-line' { @('rev-list','--parents','-n','1','HEAD') }
        'source-subject' { @('show','-s','--format=%s','HEAD') }
        'source-branch' { @('symbolic-ref','--short','HEAD') }
        'source-status' { @('status','--porcelain=v2','--untracked-files=all') }
        'plan-tree' { @('rev-parse','--verify',"$PlanCommit`^{tree}") }
        'plan-parent' { @('rev-parse','--verify',"$PlanCommit`^1") }
        'plan-message' { @('show','-s','--format=%B',$PlanCommit) }
        'plan-entries' {
            @(
                'ls-tree','-z',$PlanCommit,'--',
                ('docs/superpowers/plans/' +
                 '2026-08-21-kokoroarc-complete-suite-campaign-6-task9-transition.ps1'),
                ('docs/superpowers/plans/' +
                 '2026-08-21-kokoroarc-complete-suite-campaign-6.md')
            )
        }
        'plan-delta' {
            @(
                'diff-tree','--no-commit-id','--name-status','-z','-r',
                $PlanParent,$PlanCommit,'--'
            )
        }
        'plan-ancestor' { @('merge-base','--is-ancestor',$PlanCommit,$Task9Commit) }
        'checkout-head' { @('rev-parse','--verify','HEAD^{commit}') }
        'checkout-tree' { @('rev-parse','--verify','HEAD^{tree}') }
        'checkout-status' { @('status','--porcelain=v2','--untracked-files=all') }
        'checkout-detached' { @('symbolic-ref','-q','HEAD') }
        'checkout-ls-tree' { @('ls-tree','-r','-z','-l','--full-tree',$Task9Commit) }
        'oracle-head' { @('rev-parse','--verify','HEAD^{commit}') }
        'oracle-tree' { @('rev-parse','--verify','HEAD^{tree}') }
        'oracle-parent' { @('rev-parse','--verify','HEAD^1') }
        'oracle-parent-line' { @('rev-list','--parents','-n','1','HEAD') }
        'oracle-subject' { @('show','-s','--format=%s','HEAD') }
        'oracle-status' { @('status','--porcelain=v2','--untracked-files=all') }
        'oracle-detached' { @('symbolic-ref','-q','HEAD') }
        'oracle-entries' {
            @(
                'ls-tree','-z',$OracleCommit,'--',
                ('docs/superpowers/plans/' +
                 '2026-08-21-kokoroarc-complete-suite-campaign-6-' +
                 'task9-artifact-source-oracle.json')
            )
        }
        'oracle-delta' {
            @(
                'diff-tree','--no-commit-id','--name-status','-z','-r',
                $OracleParent,$OracleCommit,'--'
            )
        }
    }
    $arguments=@($prefix + @('-C',$rootForRole) + $tail)
    $expectedExit = if ($Role -in @('checkout-detached','oracle-detached')) {
        1
    } else { 0 }
    $nativeVector=Get-C6WindowsNativeVectorBinding `
        -Executable $git -ArgumentList $arguments
    [void]$script:C6Task9ProducerNativeVectorBindings.Add([ordered]@{
        role=$Role
        contract=[string]$nativeVector.contract
        utf16_units=[int]$nativeVector.utf16_units
        utf16le_sha256=[string]$nativeVector.utf16le_sha256
    })
    $privateRoot='D:\tmp\kokoroarc-c6-pretrust-git-' +
        [Guid]::NewGuid().ToString('N')
    $environment=New-C6Task9ProducerGitEnvironment -PrivateRoot $privateRoot
    $psi=[Diagnostics.ProcessStartInfo]::new()
    $psi.FileName=$git
    $psi.WorkingDirectory=$SourceRoot
    $psi.UseShellExecute=$false
    $psi.CreateNoWindow=$true
    $psi.RedirectStandardInput=$true
    $psi.RedirectStandardOutput=$true
    $psi.RedirectStandardError=$true
    $psi.Environment.Clear()
    foreach ($name in @($environment.Keys | Sort-Object)) {
        $psi.Environment[$name]=[string]$environment[$name]
    }
    foreach ($argument in $arguments) { [void]$psi.ArgumentList.Add($argument) }
    $process=[Diagnostics.Process]::new()
    $process.StartInfo=$psi
    $started=$false
    $stdout=$null
    $stderr=$null
    $clock=$null
    try {
        if (-not $process.Start()) { throw 'Task 9 Git postcheck did not start' }
        $started=$true
        $process.StandardInput.Close()
        $stdout=[IO.MemoryStream]::new()
        $stderr=[IO.MemoryStream]::new()
        $outBuffer=[byte[]]::new(65536)
        $errBuffer=[byte[]]::new(65536)
        $outTask=$process.StandardOutput.BaseStream.ReadAsync(
            $outBuffer,0,$outBuffer.Length
        )
        $errTask=$process.StandardError.BaseStream.ReadAsync(
            $errBuffer,0,$errBuffer.Length
        )
        $outDone=$false
        $errDone=$false
        $clock=[Diagnostics.Stopwatch]::StartNew()
        while (-not ($outDone -and $errDone -and $process.HasExited)) {
            if ($clock.ElapsedMilliseconds -ge 120000) {
                Stop-C6Task9ProducerChild -Process $process
                throw 'Task 9 Git postcheck deadline exceeded'
            }
            $progress=$false
            if (-not $outDone -and $outTask.IsCompleted) {
                $count=$outTask.GetAwaiter().GetResult()
                if ($count -eq 0) { $outDone=$true } else {
                    if ($stdout.Length+$count -gt 8388608) {
                        Stop-C6Task9ProducerChild -Process $process
                        throw 'Task 9 Git stdout exceeded 8 MiB'
                    }
                    $stdout.Write($outBuffer,0,$count)
                    $outTask=$process.StandardOutput.BaseStream.ReadAsync(
                        $outBuffer,0,$outBuffer.Length
                    )
                }
                $progress=$true
            }
            if (-not $errDone -and $errTask.IsCompleted) {
                $count=$errTask.GetAwaiter().GetResult()
                if ($count -eq 0) { $errDone=$true } else {
                    if ($stderr.Length+$count -gt 4194304) {
                        Stop-C6Task9ProducerChild -Process $process
                        throw 'Task 9 Git stderr exceeded 4 MiB'
                    }
                    $stderr.Write($errBuffer,0,$count)
                    $errTask=$process.StandardError.BaseStream.ReadAsync(
                        $errBuffer,0,$errBuffer.Length
                    )
                }
                $progress=$true
            }
            if (-not $progress) { Start-Sleep -Milliseconds 10 }
        }
        if ($process.ExitCode -ne $expectedExit -or $stderr.Length -ne 0) {
            throw "Task 9 Git role failed: $Role"
        }
        [byte[]]$result=$stdout.ToArray()
    } finally {
        if ($null -ne $clock) { $clock.Stop() }
        if ($started -and -not $process.HasExited) {
            Stop-C6Task9ProducerChild -Process $process
        }
        if ($null -ne $stdout) { $stdout.Dispose() }
        if ($null -ne $stderr) { $stderr.Dispose() }
        $process.Dispose()
    }
    if ((Get-FileHash -LiteralPath $git -Algorithm SHA256).Hash.ToLowerInvariant() -cne
            'de6c9879b7502cf2f3de9cf311aee18f61df0b8351a0b636069415aaf14bdf22') {
        throw 'Task 9 postcheck Git changed during invocation'
    }
    return ,$result
}

function ConvertFrom-C6Task9SingleLine {
    param(
        [Parameter(Mandatory)][byte[]]$Bytes,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$Pattern
    )
    if ($Bytes.Length -lt 2 -or $Bytes[-1] -ne 10 -or
        0 -in $Bytes -or 13 -in $Bytes) {
        throw "invalid Task 9 Git scalar bytes: $Label"
    }
    $text=[Text.UTF8Encoding]::new($false,$true).GetString($Bytes)
    $value=$text.Substring(0,$text.Length-1)
    if ($value.Contains("`n") -or $value -cnotmatch $Pattern) {
        throw "invalid Task 9 Git scalar value: $Label"
    }
    return $value
}

function Get-C6PlanOwnedGitBlobOid {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    $hash=[Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA1
    )
    try {
        $header=[Text.Encoding]::ASCII.GetBytes(
            'blob ' + $Bytes.Length + [char]0
        )
        $hash.AppendData($header)
        $hash.AppendData($Bytes)
        return [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
    } finally {
        $hash.Dispose()
    }
}

function Get-C6PlanOwnedRegistryLiteral {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$BeginLine,
        [Parameter(Mandatory)][string]$EndLine,
        [Parameter(Mandatory)][string]$VariableName
    )
    $lines=@($Text.Split("`n"))
    $begin=@()
    $end=@()
    for ($index=0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -ceq $BeginLine) { $begin += $index }
        if ($lines[$index] -ceq $EndLine) { $end += $index }
    }
    if ($begin.Count -ne 1 -or $end.Count -ne 1 -or
        $end[0] -ne $begin[0]+4) {
        throw "registry delimiters are not unique/exact: $VariableName"
    }
    $assignment=[string]::Concat('$script:',$VariableName,'=@',[char]39)
    if ($lines[$begin[0]+1] -cne $assignment -or
        $lines[$begin[0]+3] -cne "'@") {
        throw "registry assignment grammar mismatch: $VariableName"
    }
    $payload=$lines[$begin[0]+2]
    if ([string]::IsNullOrEmpty($payload)) {
        throw "empty registry payload: $VariableName"
    }
    [byte[]]$payloadBytes=[Text.Encoding]::ASCII.GetBytes($payload)
    if ([Text.Encoding]::ASCII.GetString($payloadBytes) -cne $payload) {
        throw "non-ASCII registry payload: $VariableName"
    }
    $parsed=$payload | ConvertFrom-Json -AsHashtable -NoEnumerate `
        -ErrorAction Stop
    if ((ConvertTo-Json -InputObject $parsed -Compress -Depth 30) -cne $payload) {
        throw "noncanonical registry payload: $VariableName"
    }
    return [pscustomobject]@{
        parsed=$parsed
        sha256=Get-C6PlanOwnedSha256 $payloadBytes
    }
}

function Get-C6PlanOwnedImplementationBodySha256 {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$BeginLine,
        [Parameter(Mandatory)][string]$EndLine
    )
    $pattern='(?ms)^' + [regex]::Escape($BeginLine) +
        "`n(?<body>.*?)^" + [regex]::Escape($EndLine) + '$'
    $matches=[regex]::Matches($Text,$pattern)
    if ($matches.Count -ne 1 -or $matches[0].Groups['body'].Length -lt 1) {
        throw "implementation delimiters/body are not unique: $BeginLine"
    }
    [byte[]]$body=[Text.UTF8Encoding]::new($false,$true).GetBytes(
        $matches[0].Groups['body'].Value
    )
    if ($body[-1] -ne 10 -or 0 -in $body -or 13 -in $body) {
        throw "implementation body byte grammar mismatch: $BeginLine"
    }
    return Get-C6PlanOwnedSha256 $body
}

function Assert-C6PlanOwnedRegistryIds {
    param(
        [Parameter(Mandatory)]$Parsed,
        [Parameter(Mandatory)][string]$IdKey,
        [Parameter(Mandatory)][string[]]$ExpectedIds,
        [Parameter(Mandatory)][string]$Label
    )
    $records=@($Parsed)
    if ($records.Count -ne $ExpectedIds.Count) {
        throw "$Label record count mismatch"
    }
    for ($index=0; $index -lt $records.Count; $index++) {
        if ($records[$index] -isnot [Collections.IDictionary]) {
            throw "$Label record is not an ordered object at $index"
        }
        $firstKey=[string](@($records[$index].Keys)[0])
        if ([string]$records[$index][$IdKey] -cne $ExpectedIds[$index] -or
            $firstKey -cne $IdKey) {
            throw "$Label ordered ID mismatch at $index"
        }
    }
}

function Get-C6Task9TransitionInputs {
    param(
        [Parameter(Mandatory)][string]$HandoffPath,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedHandoffSha256,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedTask8Commit,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedTask9Commit,
        [Parameter(Mandatory)][string]$CheckoutRoot,
        [Parameter(Mandatory)][string]$ArtifactOracleHandoffPath,
        [Parameter(Mandatory)]
        [ValidatePattern('^[0-9a-f]{64}$')]
        [string]$ExpectedArtifactOracleHandoffSha256,
        [Parameter(Mandatory)][string]$ArtifactOracleCheckoutRoot
    )
    $handoffName=[IO.Path]::GetFileName($HandoffPath)
    $handoffMatch=[regex]::Match(
        $handoffName,
        '\Akokoroarc-c6-plan-handoff-(?<guid>[0-9a-f]{32})\.json\z'
    )
    if ([IO.Path]::GetDirectoryName($HandoffPath) -cne 'D:\tmp' -or
        -not $handoffMatch.Success -or
        $CheckoutRoot -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-task09-checkout-[0-9a-f]{32}\z' -or
        [IO.Path]::GetDirectoryName($ArtifactOracleHandoffPath) -cne 'D:\tmp' -or
        [IO.Path]::GetFileName($ArtifactOracleHandoffPath) -cnotmatch
            '\Akokoroarc-c6-task9-artifact-source-oracle-handoff-[0-9a-f]{32}\.json\z' -or
        $ArtifactOracleCheckoutRoot -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-task9-artifact-source-oracle-checkout-[0-9a-f]{32}\z') {
        throw 'Task 9 producer path grammar mismatch'
    }
    Initialize-C6PlanOwnedNativeFileApi
    [C6PlanOwnedNativeFile]::AssertPlainDirectory($CheckoutRoot)
    [C6PlanOwnedNativeFile]::AssertPlainDirectory($ArtifactOracleCheckoutRoot)
    Assert-C6PlanOwnedSingleLinkCensus -Root $CheckoutRoot `
        -MaxFiles 50000 -MaxDirectories 50000
    $artifactOracleRelative=(
        'docs/superpowers/plans/' +
        '2026-08-21-kokoroarc-complete-suite-campaign-6-' +
        'task9-artifact-source-oracle.json'
    )
    Assert-C6PlanOwnedSingleLinkFile -Root $ArtifactOracleCheckoutRoot `
        -RelativePath $artifactOracleRelative -Label artifact-oracle-census
    $handoffGuid=$handoffMatch.Groups['guid'].Value
    [byte[]]$handoffPlain=Read-C6PlanOwnedPlainFile -Root 'D:\tmp' `
        -RelativePath $handoffName `
        -MaxBytes 65536 -ExpectedSha256 $ExpectedHandoffSha256
    $handoffRecord=Read-C6PlanOwnedJson -Path $HandoffPath `
        -ExpectedSha256 $ExpectedHandoffSha256 -MaxBytes 65536
    if ([Convert]::ToBase64String($handoffPlain) -cne
            [Convert]::ToBase64String($handoffRecord.bytes)) {
        throw 'Task 9 handoff no-follow/canonical reads differ'
    }
    $handoff=$handoffRecord.parsed
    if ($handoff -isnot [Collections.IDictionary]) {
        throw 'Task 9 handoff root is not an exact JSON object'
    }
    Assert-C6PlanOwnedKeys -Value $handoff -Expected @(
        'schema_version','plan','task9_transition_producer','design',
        'executables','runtime_inventories',
        'implementation','historical_tree_path_counts',
        'planning_inaccessible_manifest_sha256','audits',
        'execution_boundary_revision','runtime_inventory_algorithm'
    ) -Label 'Task 9 handoff'
    Assert-C6PlanOwnedScalarTypes -Value $handoff -StringKeys @(
        'schema_version','planning_inaccessible_manifest_sha256',
        'execution_boundary_revision','runtime_inventory_algorithm'
    ) -IntegerKeys @() -Label 'Task 9 handoff'
    if ($handoff.schema_version -isnot [string] -or
        $handoff.schema_version -cne
            'complete-suite-campaign6-plan-handoff-v1') {
        throw 'Task 9 handoff schema mismatch'
    }
    if ($handoff.plan -isnot [Collections.IDictionary] -or
        $handoff.task9_transition_producer -isnot [Collections.IDictionary] -or
        $handoff.design -isnot [Collections.IDictionary] -or
        $handoff.implementation -isnot [Collections.IDictionary] -or
        $handoff.executables -isnot [object[]] -or
        $handoff.runtime_inventories -isnot [object[]] -or
        $handoff.historical_tree_path_counts -isnot [object[]] -or
        $handoff.audits -isnot [object[]]) {
        throw 'Task 9 handoff nested object/array type mismatch'
    }
    Assert-C6PlanOwnedKeys -Value $handoff.plan -Expected @(
        'commit','tree','parent','blob','sha256','message'
    ) -Label 'Task 9 handoff plan'
    Assert-C6PlanOwnedScalarTypes -Value $handoff.plan -StringKeys @(
        'commit','tree','parent','blob','sha256','message'
    ) -IntegerKeys @() -Label 'Task 9 handoff plan'
    Assert-C6PlanOwnedKeys -Value $handoff.task9_transition_producer -Expected @(
        'path','relative_path','blob','size','sha256'
    ) -Label 'Task 9 handoff transition producer'
    Assert-C6PlanOwnedScalarTypes -Value $handoff.task9_transition_producer `
        -StringKeys @('path','relative_path','blob','sha256') `
        -IntegerKeys @('size') -Label 'Task 9 handoff transition producer'
    Assert-C6PlanOwnedKeys -Value $handoff.design -Expected @(
        'commit','tree','blob','sha256'
    ) -Label 'Task 9 handoff design'
    Assert-C6PlanOwnedScalarTypes -Value $handoff.design `
        -StringKeys @('commit','tree','blob','sha256') -IntegerKeys @() `
        -Label 'Task 9 handoff design'
    Assert-C6PlanOwnedKeys -Value $handoff.implementation -Expected @(
        'branch','root'
    ) -Label 'Task 9 handoff implementation'
    Assert-C6PlanOwnedScalarTypes -Value $handoff.implementation `
        -StringKeys @('branch','root') -IntegerKeys @() `
        -Label 'Task 9 handoff implementation'
    $executableKeys=@(
        'id','path','length','sha256','product_version','file_version'
    )
    $runtimeKeys=@(
        'id','runtime_root','runtime_entry_count','runtime_file_count',
        'runtime_directory_count','runtime_file_bytes','runtime_inventory_sha256'
    )
    $historicalKeys=@('campaign','path_count')
    $auditKeys=@('audit_id','plan_sha256','verdict')
    $executables=@($handoff.executables)
    $runtimeInventories=@($handoff.runtime_inventories)
    $historicalCounts=@($handoff.historical_tree_path_counts)
    $audits=@($handoff.audits)
    if ($executables.Count -ne 3 -or $runtimeInventories.Count -ne 3 -or
        $historicalCounts.Count -ne 5 -or $audits.Count -ne 3) {
        throw 'Task 9 handoff collection count mismatch'
    }
    foreach ($record in $executables) {
        if ($record -isnot [Collections.IDictionary]) {
            throw 'Task 9 handoff executable is not an exact JSON object'
        }
        Assert-C6PlanOwnedKeys -Value $record -Expected $executableKeys `
            -Label 'Task 9 handoff executable'
        Assert-C6PlanOwnedScalarTypes -Value $record -StringKeys @(
            'id','path','sha256','product_version','file_version'
        ) -IntegerKeys @('length') -Label 'Task 9 handoff executable'
    }
    foreach ($record in $runtimeInventories) {
        if ($record -isnot [Collections.IDictionary]) {
            throw 'Task 9 handoff runtime inventory is not an exact JSON object'
        }
        Assert-C6PlanOwnedKeys -Value $record -Expected $runtimeKeys `
            -Label 'Task 9 handoff runtime inventory'
        Assert-C6PlanOwnedScalarTypes -Value $record `
            -StringKeys @('id','runtime_root','runtime_inventory_sha256') `
            -IntegerKeys @(
                'runtime_entry_count','runtime_file_count',
                'runtime_directory_count','runtime_file_bytes'
            ) -Label 'Task 9 handoff runtime inventory'
    }
    foreach ($record in $historicalCounts) {
        if ($record -isnot [Collections.IDictionary]) {
            throw 'Task 9 handoff historical count is not an exact JSON object'
        }
        Assert-C6PlanOwnedKeys -Value $record -Expected $historicalKeys `
            -Label 'Task 9 handoff historical count'
        Assert-C6PlanOwnedScalarTypes -Value $record -StringKeys @('campaign') `
            -IntegerKeys @('path_count') -Label 'Task 9 handoff historical count'
    }
    foreach ($record in $audits) {
        if ($record -isnot [Collections.IDictionary]) {
            throw 'Task 9 handoff audit is not an exact JSON object'
        }
        Assert-C6PlanOwnedKeys -Value $record -Expected $auditKeys `
            -Label 'Task 9 handoff audit'
        Assert-C6PlanOwnedScalarTypes -Value $record `
            -StringKeys @('audit_id','plan_sha256','verdict') -IntegerKeys @() `
            -Label 'Task 9 handoff audit'
    }
    $expectedExecutables=[object[]]@(
        [ordered]@{
            id='python'
            path='C:\Python314\python.exe'
            length=[long]106328
            sha256='467014615a5255aca450ae88100dd2caf887da87657f00e3c2171ec44a685aec'
            product_version='3.14.0'
            file_version='3.14.0'
        },
        [ordered]@{
            id='powershell'
            path='C:\Program Files\PowerShell\7\pwsh.exe'
            length=[long]301368
            sha256='db6dd81183fe57d22e03b911ec9a30a2fd7c40542e97743615355a6fb44f458f'
            product_version=(
                '7.6.4 SHA: ' +
                '929d27f4e66dcfba8f5f74ff03105705e483a27d+' +
                '929d27f4e66dcfba8f5f74ff03105705e483a27d'
            )
            file_version='7.6.4.500'
        },
        [ordered]@{
            id='git'
            path='C:\Program Files\Git\mingw64\bin\git.exe'
            length=[long]4285328
            sha256='de6c9879b7502cf2f3de9cf311aee18f61df0b8351a0b636069415aaf14bdf22'
            product_version='2.51.1.windows.1'
            file_version='2.51.1.windows.1'
        }
    )
    $expectedRuntimeInventories=[object[]]@(
        [ordered]@{
            id='python'
            runtime_root='C:\Python314'
            runtime_entry_count=[long]5938
            runtime_file_count=[long]5389
            runtime_directory_count=[long]549
            runtime_file_bytes=[long]160053976
            runtime_inventory_sha256=(
                '34413fbc3fc1404957999a286c20723a24eea7f3c862bdfff289cefc5a275ec9'
            )
        },
        [ordered]@{
            id='powershell'
            runtime_root='C:\Program Files\PowerShell\7'
            runtime_entry_count=[long]1041
            runtime_file_count=[long]987
            runtime_directory_count=[long]54
            runtime_file_bytes=[long]296411947
            runtime_inventory_sha256=(
                '267a116743b5fb75c4d1530d164afd8406989587b4def95ec10a804dffd07ee0'
            )
        },
        [ordered]@{
            id='git'
            runtime_root='C:\Program Files\Git'
            runtime_entry_count=[long]10101
            runtime_file_count=[long]9280
            runtime_directory_count=[long]821
            runtime_file_bytes=[long]428672755
            runtime_inventory_sha256=(
                '202e5fd8bebf7901edcd35a993a66af3ca12a60836c083b0a0d877c7a2d64c87'
            )
        }
    )
    $expectedHistoricalCounts=[object[]]@(
        [ordered]@{ campaign='approved1'; path_count=[long]515 },
        [ordered]@{ campaign='approved2'; path_count=[long]515 },
        [ordered]@{ campaign='approved3'; path_count=[long]542 },
        [ordered]@{ campaign='approved4'; path_count=[long]6 },
        [ordered]@{ campaign='approved5'; path_count=[long]641 }
    )
    $expectedAudits=[object[]]@(
        [ordered]@{
            audit_id='Campaign6-Spec-Audit'
            plan_sha256=[string]$handoff.plan.sha256
            verdict='PASS'
        },
        [ordered]@{
            audit_id='Campaign6-Security-Audit'
            plan_sha256=[string]$handoff.plan.sha256
            verdict='PASS'
        },
        [ordered]@{
            audit_id='Campaign6-Executable-Audit'
            plan_sha256=[string]$handoff.plan.sha256
            verdict='PASS'
        }
    )
    if ((ConvertTo-Json $executables -Compress -Depth 10) -cne
            (ConvertTo-Json $expectedExecutables -Compress -Depth 10) -or
        (ConvertTo-Json $runtimeInventories -Compress -Depth 10) -cne
            (ConvertTo-Json $expectedRuntimeInventories -Compress -Depth 10) -or
        (ConvertTo-Json $historicalCounts -Compress -Depth 10) -cne
            (ConvertTo-Json $expectedHistoricalCounts -Compress -Depth 10) -or
        (ConvertTo-Json $audits -Compress -Depth 10) -cne
            (ConvertTo-Json $expectedAudits -Compress -Depth 10)) {
        throw 'Task 9 handoff collection semantics mismatch'
    }
    if ($handoff.planning_inaccessible_manifest_sha256 -isnot [string] -or
        $handoff.planning_inaccessible_manifest_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        $handoff.execution_boundary_revision -isnot [string] -or
        $handoff.execution_boundary_revision -cne
            'complete-suite-campaign6-pre-trust-execution-boundary-v1' -or
        $handoff.runtime_inventory_algorithm -isnot [string] -or
        $handoff.runtime_inventory_algorithm -cne
            'complete-suite-runtime-inventory-binary-v1') {
        throw 'Task 9 handoff scalar authority mismatch'
    }
    foreach ($name in @('commit','tree','parent','blob')) {
        if ($handoff.plan[$name] -isnot [string] -or
            [string]$handoff.plan[$name] -cnotmatch '^[0-9a-f]{40}$') {
            throw "Task 9 handoff plan OID mismatch: $name"
        }
    }
    $producer=$handoff.task9_transition_producer
    $producerRelative='docs/superpowers/plans/' +
        '2026-08-21-kokoroarc-complete-suite-campaign-6-task9-transition.ps1'
    if ($producer.path -isnot [string] -or
        $producer.relative_path -isnot [string] -or
        $producer.relative_path -cne $producerRelative -or
        $producer.blob -isnot [string] -or
        $producer.blob -cnotmatch '^[0-9a-f]{40}$' -or
        $producer.size -isnot [long] -or $producer.size -lt 1 -or
        $producer.size -gt 1048576 -or
        $producer.sha256 -isnot [string] -or
        $producer.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $handoff.plan.sha256 -isnot [string] -or
        [string]$handoff.plan.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $handoff.plan.message -isnot [string] -or
        [string]::IsNullOrEmpty([string]$handoff.plan.message)) {
        throw 'Task 9 handoff plan hash/message mismatch'
    }
    $designCommit='1fa1540d536c6f192f9486f74cc215011d93582b'
    $designTree='9fd745cfff3b99e5c61c7bb89f52ea5ab90a3ccc'
    $designBlob='3dd2218b6be217a795158e5000d02a4e6e2d48ce'
    $designSha256=(
        '0ee991cc719632dc72d8b2a8ce08d68704071c63b3a2c8fc925015e82295dd2f'
    )
    if ($handoff.design.commit -isnot [string] -or
        $handoff.design.tree -isnot [string] -or
        $handoff.design.blob -isnot [string] -or
        $handoff.design.sha256 -isnot [string] -or
        $handoff.plan.parent -cne $designCommit -or
        $handoff.design.commit -cne $designCommit -or
        $handoff.design.tree -cne $designTree -or
        $handoff.design.blob -cne $designBlob -or
        $handoff.design.sha256 -cne $designSha256) {
        throw 'Task 9 handoff design authority mismatch'
    }
    $expectedPlanMessage=@(
        'docs: plan complete-suite campaign 6',
        '',
        ('Campaign6-Plan-SHA256: ' + [string]$handoff.plan.sha256),
        ('Campaign6-Plan-Blob: ' + [string]$handoff.plan.blob),
        ('Campaign6-Plan-Tree: ' + [string]$handoff.plan.tree),
        ('Campaign6-Task9-Producer-Blob: ' + [string]$producer.blob),
        ('Campaign6-Task9-Producer-Size: ' + [string]$producer.size),
        ('Campaign6-Task9-Producer-SHA256: ' + [string]$producer.sha256),
        ('Campaign6-Design-Commit: ' + $designCommit),
        ('Campaign6-Design-Tree: ' + $designTree),
        ('Campaign6-Design-SHA256: ' + $designSha256),
        'Campaign6-Spec-Audit: PASS',
        'Campaign6-Security-Audit: PASS',
        'Campaign6-Executable-Audit: PASS'
    ) -join "`n"
    if ([string]$handoff.plan.message -cne $expectedPlanMessage) {
        throw 'Task 9 handoff plan message/trailer mismatch'
    }
    $expectedImplementationBranch="feat/complete-suite-campaign-6-$handoffGuid"
    $expectedImplementationRoot=(
        'D:\Projects\AI\KokoroArc\.worktrees\' +
        "complete-suite-campaign-6-$handoffGuid"
    )
    if ($handoff.implementation.branch -isnot [string] -or
        $handoff.implementation.root -isnot [string] -or
        [string]$handoff.implementation.branch -cne
            $expectedImplementationBranch -or
        [string]$handoff.implementation.root -cne $expectedImplementationRoot) {
        throw 'Task 9 handoff filename/branch/root GUID mismatch'
    }
    $sourceRoot=[IO.Path]::GetFullPath((Get-Location).ProviderPath).TrimEnd('\')
    if ($sourceRoot -cne
            [IO.Path]::GetFullPath([string]$handoff.implementation.root).TrimEnd('\')) {
        throw 'Task 9 source root differs from authenticated handoff'
    }
    if ([IO.Path]::GetFullPath([string]$producer.path) -cne
            [IO.Path]::GetFullPath((Join-Path $sourceRoot $producerRelative))) {
        throw 'Task 9 transition-producer path authority mismatch'
    }
    [C6PlanOwnedNativeFile]::AssertPlainDirectory($sourceRoot)
    [C6PlanOwnedNativeFile]::AssertPlainDirectory($CheckoutRoot)
    [C6PlanOwnedNativeFile]::AssertPlainDirectory($ArtifactOracleCheckoutRoot)

    $oracleHeldRecords=[Collections.Generic.List[object]]::new()
    try {
    $artifactOracleHandoffHeld=Read-C6PlanOwnedHeldJson `
        -Path $ArtifactOracleHandoffPath `
        -ExpectedSha256 $ExpectedArtifactOracleHandoffSha256 `
        -MaxBytes 65536 -Role artifact-oracle-handoff
    $oracleHeldRecords.Add($artifactOracleHandoffHeld)
    $artifactOracleHandoff=$artifactOracleHandoffHeld.parsed
    if ($artifactOracleHandoff -isnot [Collections.IDictionary]) {
        throw 'artifact-oracle handoff root is not an exact object'
    }
    $artifactOracleHandoffKeys=@(
        'schema_version','plan_commit','task9_commit','task9_tree',
        'review_result_path','review_result_sha256','review_envelope_sha256',
        'artifact_oracle_checkout_root','artifact_oracle_path',
        'artifact_oracle_commit','artifact_oracle_tree','artifact_oracle_parent',
        'artifact_oracle_blob','artifact_oracle_size','artifact_oracle_sha256',
        'artifact_oracle_digest_count','cybersecurity_checks_may_be_bypassed'
    )
    Assert-C6PlanOwnedKeys -Value $artifactOracleHandoff `
        -Expected $artifactOracleHandoffKeys -Label 'artifact-oracle handoff'
    Assert-C6PlanOwnedScalarTypes -Value $artifactOracleHandoff -StringKeys @(
        'schema_version','plan_commit','task9_commit','task9_tree',
        'review_result_path','review_result_sha256','review_envelope_sha256',
        'artifact_oracle_checkout_root','artifact_oracle_path',
        'artifact_oracle_commit','artifact_oracle_tree','artifact_oracle_parent',
        'artifact_oracle_blob','artifact_oracle_sha256'
    ) -IntegerKeys @(
        'artifact_oracle_size','artifact_oracle_digest_count'
    ) -Label 'artifact-oracle handoff'
    $oracleRelative='docs/superpowers/plans/' +
        '2026-08-21-kokoroarc-complete-suite-campaign-6-' +
        'task9-artifact-source-oracle.json'
    $expectedOraclePath=[IO.Path]::GetFullPath(
        [IO.Path]::Combine(
            $ArtifactOracleCheckoutRoot,
            $oracleRelative.Replace('/',[char]92)
        )
    )
    if ($artifactOracleHandoff.schema_version -cne
            'complete-suite-task9-artifact-source-oracle-handoff-v1' -or
        $artifactOracleHandoff.plan_commit -cne [string]$handoff.plan.commit -or
        $artifactOracleHandoff.task9_commit -cne $ExpectedTask9Commit -or
        $artifactOracleHandoff.task9_tree -cnotmatch '^[0-9a-f]{40}$' -or
        $artifactOracleHandoff.review_result_path -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-task9-artifact-source-oracle-review-[0-9a-f]{32}\.json\z' -or
        $artifactOracleHandoff.review_result_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $artifactOracleHandoff.review_envelope_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $artifactOracleHandoff.artifact_oracle_checkout_root -cne
            $ArtifactOracleCheckoutRoot -or
        [IO.Path]::GetFullPath($artifactOracleHandoff.artifact_oracle_path) -cne
            $expectedOraclePath -or
        $artifactOracleHandoff.artifact_oracle_commit -cnotmatch
            '^[0-9a-f]{40}$' -or
        $artifactOracleHandoff.artifact_oracle_tree -cnotmatch
            '^[0-9a-f]{40}$' -or
        $artifactOracleHandoff.artifact_oracle_parent -cne
            [string]$handoff.plan.commit -or
        $artifactOracleHandoff.artifact_oracle_blob -cnotmatch
            '^[0-9a-f]{40}$' -or
        $artifactOracleHandoff.artifact_oracle_size -lt 2 -or
        $artifactOracleHandoff.artifact_oracle_size -gt 65536 -or
        $artifactOracleHandoff.artifact_oracle_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        $artifactOracleHandoff.artifact_oracle_digest_count -ne 8 -or
        $artifactOracleHandoff.cybersecurity_checks_may_be_bypassed -isnot
            [bool] -or
        $artifactOracleHandoff.cybersecurity_checks_may_be_bypassed) {
        throw 'artifact-oracle handoff authority mismatch'
    }

    $reviewHeld=Read-C6PlanOwnedHeldJson `
        -Path ([string]$artifactOracleHandoff.review_result_path) `
        -ExpectedSha256 ([string]$artifactOracleHandoff.review_result_sha256) `
        -MaxBytes 262144 -Role artifact-oracle-review-result
    $oracleHeldRecords.Add($reviewHeld)
    $review=$reviewHeld.parsed
    if ($review -isnot [Collections.IDictionary]) {
        throw 'artifact-oracle review result root is not an exact object'
    }
    $reviewKeys=@(
        'schema_version','review_role','review_revision',
        'plan_commit','plan_tree','plan_blob','plan_sha256',
        'task9_commit','task9_tree','oracle_parent','oracle_relative_path',
        'oracle_blob','oracle_size','oracle_sha256','oracle_tree','oracle_commit',
        'oracle_message','reviewed_bundle_sha256','algorithm_table_revision',
        'algorithm_table_sha256','launcher_source_relative_path',
        'launcher_source_size','launcher_source_sha256',
        'writer_source_relative_path','writer_source_size','writer_source_sha256',
        'launcher_ast_sha256','launcher_bootstrap_fixture_sha256',
        'launcher_rawui_reader_sha256','writer_ast_sha256',
        'writer_closed_import_native_call_table_sha256',
        'writer_launcher_fixture_sha256','source_binding_count',
        'semantic_binding_count','digest_count','critical_findings',
        'important_findings','verdict','cybersecurity_checks_may_be_bypassed',
        'review_envelope_sha256','reviewer_transport_tcb',
        'local_processes_requested','provider_calls_requested',
        'network_requested','filesystem_writes_requested','subagent_spawn_allowed'
    )
    Assert-C6PlanOwnedKeys -Value $review -Expected $reviewKeys `
        -Label 'artifact-oracle review result'
    Assert-C6PlanOwnedScalarTypes -Value $review -StringKeys @(
        'schema_version','review_role','review_revision',
        'plan_commit','plan_tree','plan_blob','plan_sha256',
        'task9_commit','task9_tree','oracle_parent','oracle_relative_path',
        'oracle_blob','oracle_sha256','oracle_tree','oracle_commit',
        'oracle_message','reviewed_bundle_sha256','algorithm_table_revision',
        'algorithm_table_sha256','launcher_source_relative_path',
        'launcher_source_sha256','writer_source_relative_path',
        'writer_source_sha256',
        'launcher_ast_sha256','launcher_bootstrap_fixture_sha256',
        'launcher_rawui_reader_sha256','writer_ast_sha256',
        'writer_closed_import_native_call_table_sha256',
        'writer_launcher_fixture_sha256','verdict','review_envelope_sha256',
        'reviewer_transport_tcb'
    ) -IntegerKeys @(
        'oracle_size','launcher_source_size','writer_source_size',
        'source_binding_count','semantic_binding_count',
        'digest_count','critical_findings','important_findings',
        'local_processes_requested','provider_calls_requested'
    ) -Label 'artifact-oracle review result'
    $algorithmRevision=(
        'complete-suite-task9-artifact-source-oracle-algorithms-v1'
    )
    $algorithmSha256=(
        '048fa0d9fc0e66562dd35bb3d0bd1598e23cd7af9febaa6f499eb676d93bb445'
    )
    $reviewDigestKeys=@(
        'plan_sha256','reviewed_bundle_sha256','algorithm_table_sha256',
        'launcher_source_sha256','writer_source_sha256','launcher_ast_sha256',
        'launcher_bootstrap_fixture_sha256','launcher_rawui_reader_sha256',
        'writer_ast_sha256','writer_closed_import_native_call_table_sha256',
        'writer_launcher_fixture_sha256','review_envelope_sha256'
    )
    foreach ($key in $reviewDigestKeys) {
        if ($review[$key] -cnotmatch '^[0-9a-f]{64}$') {
            throw "artifact-oracle review digest mismatch: $key"
        }
    }
    if ($review.schema_version -cne
            'complete-suite-task9-artifact-source-oracle-review-v1' -or
        $review.review_role -cne 'c6_task9_artifact_oracle_review' -or
        $review.review_revision -cne
            'complete-suite-task9-artifact-source-oracle-review-v1' -or
        $review.plan_commit -cne [string]$handoff.plan.commit -or
        $review.plan_tree -cne [string]$handoff.plan.tree -or
        $review.plan_blob -cne [string]$handoff.plan.blob -or
        $review.plan_sha256 -cne [string]$handoff.plan.sha256 -or
        $review.task9_commit -cne $ExpectedTask9Commit -or
        $review.task9_tree -cne $artifactOracleHandoff.task9_tree -or
        $review.oracle_parent -cne [string]$handoff.plan.commit -or
        $review.oracle_relative_path -cne $oracleRelative -or
        $review.oracle_blob -cne $artifactOracleHandoff.artifact_oracle_blob -or
        $review.oracle_size -ne $artifactOracleHandoff.artifact_oracle_size -or
        $review.oracle_sha256 -cne $artifactOracleHandoff.artifact_oracle_sha256 -or
        $review.oracle_tree -cne $artifactOracleHandoff.artifact_oracle_tree -or
        $review.oracle_commit -cne $artifactOracleHandoff.artifact_oracle_commit -or
        $review.oracle_message -cne
            'docs: seal campaign 6 Task 9 artifact source oracle' -or
        $review.algorithm_table_revision -cne $algorithmRevision -or
        $review.algorithm_table_sha256 -cne $algorithmSha256 -or
        $review.launcher_source_relative_path -cne
            'tests/skills/complete_suite_artifact_launcher.ps1' -or
        $review.launcher_source_size -lt 1 -or
        $review.launcher_source_size -gt 1048576 -or
        $review.writer_source_relative_path -cne
            'tests/skills/complete_suite_artifact_writer.py' -or
        $review.writer_source_size -lt 1 -or
        $review.writer_source_size -gt 1048576 -or
        $review.source_binding_count -ne 2 -or
        $review.semantic_binding_count -ne 6 -or $review.digest_count -ne 8 -or
        $review.critical_findings -ne 0 -or $review.important_findings -ne 0 -or
        $review.verdict -cne 'PASS' -or
        $review.cybersecurity_checks_may_be_bypassed -isnot [bool] -or
        $review.cybersecurity_checks_may_be_bypassed -or
        $review.review_envelope_sha256 -cne
            $artifactOracleHandoff.review_envelope_sha256 -or
        $review.reviewer_transport_tcb -cne
            'platform-primary-plus-collaboration' -or
        $review.local_processes_requested -ne 0 -or
        $review.provider_calls_requested -ne 0 -or
        $review.network_requested -isnot [bool] -or $review.network_requested -or
        $review.filesystem_writes_requested -isnot [bool] -or
            $review.filesystem_writes_requested -or
        $review.subagent_spawn_allowed -isnot [bool] -or
            $review.subagent_spawn_allowed) {
        throw 'artifact-oracle review authority mismatch'
    }

    $oracleHeld=Read-C6PlanOwnedHeldJson `
        -Path ([string]$artifactOracleHandoff.artifact_oracle_path) `
        -ExpectedSha256 ([string]$artifactOracleHandoff.artifact_oracle_sha256) `
        -MaxBytes 65536 -Role artifact-oracle
    $oracleHeldRecords.Add($oracleHeld)
    if ($oracleHeld.bytes.Length -ne $artifactOracleHandoff.artifact_oracle_size) {
        throw 'artifact-oracle size differs from authenticated handoff'
    }
    $oracle=$oracleHeld.parsed
    if ($oracle -isnot [Collections.IDictionary]) {
        throw 'artifact-oracle root is not an exact object'
    }
    $oracleKeys=@(
        'schema_version','plan_commit','task9_commit','task9_tree',
        'algorithm_table_revision','algorithm_table_sha256','sources',
        'semantics','digest_count'
    )
    Assert-C6PlanOwnedKeys -Value $oracle -Expected $oracleKeys `
        -Label 'artifact-oracle'
    Assert-C6PlanOwnedScalarTypes -Value $oracle -StringKeys @(
        'schema_version','plan_commit','task9_commit','task9_tree',
        'algorithm_table_revision','algorithm_table_sha256'
    ) -IntegerKeys @('digest_count') -Label 'artifact-oracle'
    if ($oracle.sources -isnot [object[]] -or
        $oracle.semantics -isnot [object[]]) {
        throw 'artifact-oracle binding collections have wrong JSON types'
    }
    $oracleSources=@($oracle.sources)
    $oracleSemantics=@($oracle.semantics)
    if ($oracleSources.Count -ne 2 -or $oracleSemantics.Count -ne 6 -or
        $oracle.schema_version -cne
            'complete-suite-task9-artifact-source-oracle-v1' -or
        $oracle.plan_commit -cne [string]$handoff.plan.commit -or
        $oracle.task9_commit -cne $ExpectedTask9Commit -or
        $oracle.task9_tree -cne $artifactOracleHandoff.task9_tree -or
        $oracle.algorithm_table_revision -cne $algorithmRevision -or
        $oracle.algorithm_table_sha256 -cne $algorithmSha256 -or
        $oracle.digest_count -ne 8) {
        throw 'artifact-oracle scalar/count authority mismatch'
    }
    $sourceKeys=@('id','relative_path','size','sha256')
    $expectedSourceIds=@('artifact-launcher','artifact-writer')
    $expectedSourcePaths=@(
        'tests/skills/complete_suite_artifact_launcher.ps1',
        'tests/skills/complete_suite_artifact_writer.py'
    )
    for ($index=0; $index -lt 2; $index++) {
        $source=$oracleSources[$index]
        if ($source -isnot [Collections.IDictionary]) {
            throw 'artifact-oracle source binding is not an object'
        }
        Assert-C6PlanOwnedKeys -Value $source -Expected $sourceKeys `
            -Label 'artifact-oracle source binding'
        Assert-C6PlanOwnedScalarTypes -Value $source `
            -StringKeys @('id','relative_path','sha256') `
            -IntegerKeys @('size') -Label 'artifact-oracle source binding'
        if ($source.id -cne $expectedSourceIds[$index] -or
            $source.relative_path -cne $expectedSourcePaths[$index] -or
            $source.size -lt 1 -or $source.size -gt 1048576 -or
            $source.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "artifact-oracle source binding mismatch at $index"
        }
    }
    $semanticKeys=@('id','sha256')
    $expectedSemanticIds=@(
        'launcher-ast','launcher-bootstrap-fixture','launcher-rawui-reader',
        'writer-ast','writer-closed-import-native-call-table',
        'writer-launcher-fixture'
    )
    for ($index=0; $index -lt 6; $index++) {
        $semantic=$oracleSemantics[$index]
        if ($semantic -isnot [Collections.IDictionary]) {
            throw 'artifact-oracle semantic binding is not an object'
        }
        Assert-C6PlanOwnedKeys -Value $semantic -Expected $semanticKeys `
            -Label 'artifact-oracle semantic binding'
        Assert-C6PlanOwnedScalarTypes -Value $semantic `
            -StringKeys $semanticKeys -IntegerKeys @() `
            -Label 'artifact-oracle semantic binding'
        if ($semantic.id -cne $expectedSemanticIds[$index] -or
            $semantic.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "artifact-oracle semantic binding mismatch at $index"
        }
    }
    if ((Get-C6PlanOwnedGitBlobOid $oracleHeld.bytes) -cne
            $artifactOracleHandoff.artifact_oracle_blob) {
        throw 'artifact-oracle Git blob differs from authenticated handoff'
    }

    $gitArgs=@{
        SourceRoot=$sourceRoot
        CheckoutRoot=$CheckoutRoot
        Task9Commit=$ExpectedTask9Commit
        PlanCommit=[string]$handoff.plan.commit
        PlanParent=[string]$handoff.plan.parent
        OracleRoot=$ArtifactOracleCheckoutRoot
        OracleCommit=[string]$artifactOracleHandoff.artifact_oracle_commit
        OracleParent=[string]$artifactOracleHandoff.artifact_oracle_parent
    }
    $sourceRootBytes=Invoke-C6Task9PostcheckGit -Role source-root @gitArgs
    $gitSourceRoot=ConvertFrom-C6Task9SingleLine -Bytes $sourceRootBytes `
        -Label source-root -Pattern '^.+$'
    if ([IO.Path]::GetFullPath($gitSourceRoot.Replace('/','\')).TrimEnd('\') -cne
            $sourceRoot) {
        throw 'Task 9 Git source-root mismatch'
    }
    $sourceHead=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-head @gitArgs) `
        -Label source-head -Pattern '^[0-9a-f]{40}$'
    $sourceTree=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-tree @gitArgs) `
        -Label source-tree -Pattern '^[0-9a-f]{40}$'
    $sourceParent=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-parent @gitArgs) `
        -Label source-parent -Pattern '^[0-9a-f]{40}$'
    $parentLine=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-parent-line @gitArgs) `
        -Label source-parent-line -Pattern '^[0-9a-f]{40} [0-9a-f]{40}$'
    $subject=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-subject @gitArgs) `
        -Label source-subject -Pattern '^feat: freeze complete-suite shell preflight$'
    $branch=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-branch @gitArgs) `
        -Label source-branch -Pattern '^feat/complete-suite-campaign-6-[0-9a-f]{32}$'
    if ($sourceHead -cne $ExpectedTask9Commit -or
        $sourceParent -cne $ExpectedTask8Commit -or
        $sourceTree -cne $artifactOracleHandoff.task9_tree -or
        $parentLine -cne "$ExpectedTask9Commit $ExpectedTask8Commit" -or
        $subject -cne 'feat: freeze complete-suite shell preflight' -or
        $branch -cne [string]$handoff.implementation.branch -or
        (Invoke-C6Task9PostcheckGit -Role source-status @gitArgs).Length -ne 0 -or
        (Invoke-C6Task9PostcheckGit -Role plan-ancestor @gitArgs).Length -ne 0) {
        throw 'Task 9 source commit/branch/status closure mismatch'
    }

    $planTree=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role plan-tree @gitArgs) `
        -Label plan-tree -Pattern '^[0-9a-f]{40}$'
    $planParent=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role plan-parent @gitArgs) `
        -Label plan-parent -Pattern '^[0-9a-f]{40}$'
    [byte[]]$planMessage=Invoke-C6Task9PostcheckGit -Role plan-message @gitArgs
    [byte[]]$expectedPlanMessage=[Text.UTF8Encoding]::new($false,$true).GetBytes(
        [string]$handoff.plan.message + "`n`n"
    )
    if ($planTree -cne [string]$handoff.plan.tree -or
        $planParent -cne [string]$handoff.plan.parent -or
        [Convert]::ToBase64String($planMessage) -cne
            [Convert]::ToBase64String($expectedPlanMessage)) {
        throw 'Task 9 plan commit identity mismatch'
    }
    $planRelative='docs/superpowers/plans/' +
        '2026-08-21-kokoroarc-complete-suite-campaign-6.md'
    [byte[]]$planBytes=Read-C6PlanOwnedPlainFile -Root $sourceRoot `
        -RelativePath $planRelative -MaxBytes 8388608 `
        -ExpectedSha256 ([string]$handoff.plan.sha256)
    if ((Get-C6PlanOwnedGitBlobOid $planBytes) -cne [string]$handoff.plan.blob) {
        throw 'Task 9 plan working bytes/blob mismatch'
    }
    [byte[]]$planEntryBytes=Invoke-C6Task9PostcheckGit -Role plan-entries @gitArgs
    $strictUtf8=[Text.UTF8Encoding]::new($false,$true)
    $planEntry=$strictUtf8.GetString($planEntryBytes)
    $expectedPlanEntry='100644 blob ' + [string]$producer.blob +
        "`t" + $producerRelative + [char]0 +
        '100644 blob ' + [string]$handoff.plan.blob +
        "`t" + $planRelative + [char]0
    if ($planEntry -cne $expectedPlanEntry) {
        throw 'Task 9 plan tree entry mismatch'
    }
    [byte[]]$planDelta=Invoke-C6Task9PostcheckGit -Role plan-delta @gitArgs
    [byte[]]$expectedPlanDelta=$strictUtf8.GetBytes(
        'A' + [char]0 + $producerRelative + [char]0 +
        'A' + [char]0 + $planRelative + [char]0
    )
    if ([Convert]::ToBase64String($planDelta) -cne
            [Convert]::ToBase64String($expectedPlanDelta)) {
        throw 'Task 9 plan commit delta mismatch'
    }

    $oracleHead=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role oracle-head @gitArgs) `
        -Label oracle-head -Pattern '^[0-9a-f]{40}$'
    $oracleTree=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role oracle-tree @gitArgs) `
        -Label oracle-tree -Pattern '^[0-9a-f]{40}$'
    $oracleParent=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role oracle-parent @gitArgs) `
        -Label oracle-parent -Pattern '^[0-9a-f]{40}$'
    $oracleParentLine=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role oracle-parent-line @gitArgs) `
        -Label oracle-parent-line -Pattern '^[0-9a-f]{40} [0-9a-f]{40}$'
    $oracleSubject=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role oracle-subject @gitArgs) `
        -Label oracle-subject `
        -Pattern '^docs: seal campaign 6 Task 9 artifact source oracle$'
    if ($oracleHead -cne $artifactOracleHandoff.artifact_oracle_commit -or
        $oracleTree -cne $artifactOracleHandoff.artifact_oracle_tree -or
        $oracleParent -cne [string]$handoff.plan.commit -or
        $oracleParentLine -cne "$oracleHead $oracleParent" -or
        $oracleSubject -cne
            'docs: seal campaign 6 Task 9 artifact source oracle' -or
        (Invoke-C6Task9PostcheckGit -Role oracle-status @gitArgs).Length -ne 0 -or
        (Invoke-C6Task9PostcheckGit -Role oracle-detached @gitArgs).Length -ne 0) {
        throw 'artifact-oracle checkout topology/status mismatch'
    }
    [byte[]]$oracleEntryBytes=Invoke-C6Task9PostcheckGit `
        -Role oracle-entries @gitArgs
    $oracleEntry=$strictUtf8.GetString($oracleEntryBytes)
    $expectedOracleEntry='100644 blob ' +
        [string]$artifactOracleHandoff.artifact_oracle_blob + "`t" +
        $oracleRelative + [char]0
    if ($oracleEntry -cne $expectedOracleEntry) {
        throw 'artifact-oracle tree entry mismatch'
    }
    [byte[]]$oracleDelta=Invoke-C6Task9PostcheckGit `
        -Role oracle-delta @gitArgs
    [byte[]]$expectedOracleDelta=$strictUtf8.GetBytes(
        'A' + [char]0 + $oracleRelative + [char]0
    )
    if ([Convert]::ToBase64String($oracleDelta) -cne
            [Convert]::ToBase64String($expectedOracleDelta)) {
        throw 'artifact-oracle commit is not the exact one-file child of P'
    }

    $checkoutHead=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role checkout-head @gitArgs) `
        -Label checkout-head -Pattern '^[0-9a-f]{40}$'
    $checkoutTree=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role checkout-tree @gitArgs) `
        -Label checkout-tree -Pattern '^[0-9a-f]{40}$'
    if ($checkoutHead -cne $ExpectedTask9Commit -or
        $checkoutTree -cne $sourceTree -or
        (Invoke-C6Task9PostcheckGit -Role checkout-status @gitArgs).Length -ne 0 -or
        (Invoke-C6Task9PostcheckGit -Role checkout-detached @gitArgs).Length -ne 0) {
        throw 'Task 9 detached checkout identity/status mismatch'
    }

    [byte[]]$treeBytes=Invoke-C6Task9PostcheckGit -Role checkout-ls-tree @gitArgs
    if ($treeBytes.Length -lt 1 -or $treeBytes[-1] -ne 0) {
        throw 'Task 9 ls-tree framing mismatch'
    }
    $records=[Collections.Generic.List[string]]::new()
    $segmentStart=0
    for ($index=0; $index -lt $treeBytes.Length; $index++) {
        if ($treeBytes[$index] -eq 0) {
            if ($index -eq $segmentStart) { throw 'empty Task 9 ls-tree record' }
            [byte[]]$segment=$treeBytes[$segmentStart..($index-1)]
            $records.Add($strictUtf8.GetString($segment))
            $segmentStart=$index+1
        }
    }
    if ($segmentStart -ne $treeBytes.Length -or
        $records.Count -lt 1 -or $records.Count -gt 50000) {
        throw 'Task 9 ls-tree record count/framing mismatch'
    }

    $entries=[Collections.Generic.List[object]]::new()
    $entryMap=[Collections.Generic.Dictionary[string,object]]::new(
        [StringComparer]::Ordinal
    )
    $caseMap=[Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    [long]$totalBytes=0
    [long]$projectionBytes=2
    $previous=''
    foreach ($record in $records) {
        if ($record -cnotmatch
                '\A(?<mode>100644|100755) blob (?<blob>[0-9a-f]{40}) +(?<size>0|[1-9][0-9]*)\t(?<path>.+)\z') {
            throw "unsupported Task 9 tree entry: $record"
        }
        $relative=[string]$Matches.path
        $mode=[string]$Matches.mode
        $blob=[string]$Matches.blob
        if (($entries.Count -gt 0 -and
                [StringComparer]::Ordinal.Compare($previous,$relative) -ge 0) -or
            -not $caseMap.Add($relative)) {
            throw "Task 9 tree order/case collision: $relative"
        }
        $previous=$relative
        [long]$declaredSize=[long]::Parse(
            [string]$Matches.size,[Globalization.CultureInfo]::InvariantCulture
        )
        $full=Resolve-C6PlanOwnedPlainFile -Root $CheckoutRoot `
            -RelativePath $relative
        $opened=[C6PlanOwnedNativeFile]::OpenRegular($full)
        $sha256=[Security.Cryptography.IncrementalHash]::CreateHash(
            [Security.Cryptography.HashAlgorithmName]::SHA256
        )
        $gitSha1=[Security.Cryptography.IncrementalHash]::CreateHash(
            [Security.Cryptography.HashAlgorithmName]::SHA1
        )
        try {
            if ($opened.Length -ne $declaredSize) {
                throw "Task 9 checkout size mismatch: $relative"
            }
            $header=[Text.Encoding]::ASCII.GetBytes(
                'blob ' + $declaredSize + [char]0
            )
            $gitSha1.AppendData($header)
            $buffer=[byte[]]::new(65536)
            [long]$readTotal=0
            $hasNul=$false
            $hasCr=$false
            while (($count=$opened.Stream.Read($buffer,0,$buffer.Length)) -gt 0) {
                $readTotal += $count
                if ($readTotal -gt $declaredSize) {
                    throw "Task 9 checkout grew during read: $relative"
                }
                $sha256.AppendData($buffer,0,$count)
                $gitSha1.AppendData($buffer,0,$count)
                for ($offset=0; $offset -lt $count; $offset++) {
                    if ($buffer[$offset] -eq 0) { $hasNul=$true }
                    if ($buffer[$offset] -eq 13) { $hasCr=$true }
                }
            }
            if ($readTotal -ne $declaredSize) {
                throw "Task 9 checkout short read: $relative"
            }
            $identity=$opened.Identity
            $fileSha=[Convert]::ToHexString(
                $sha256.GetHashAndReset()
            ).ToLowerInvariant()
            $blobSha=[Convert]::ToHexString(
                $gitSha1.GetHashAndReset()
            ).ToLowerInvariant()
        } finally {
            $sha256.Dispose()
            $gitSha1.Dispose()
            $opened.Dispose()
        }
        $post=[C6PlanOwnedNativeFile]::OpenRegular($full)
        try {
            if ($post.Identity -cne $identity -or $post.Length -ne $declaredSize) {
                throw "Task 9 checkout identity drift: $relative"
            }
        } finally {
            $post.Dispose()
        }
        [void](Resolve-C6PlanOwnedPlainFile -Root $CheckoutRoot `
            -RelativePath $relative)
        if ($blobSha -cne $blob) {
            throw "Task 9 checkout Git blob mismatch: $relative"
        }
        $governedText=($relative -match
            '(?i)\.(py|ps1|md|json|toml|yaml|yml|txt|gitattributes|gitignore)$')
        if ($governedText -and ($hasNul -or $hasCr)) {
            throw "Task 9 governed text violates LF/no-NUL: $relative"
        }
        $entry=[ordered]@{
            relative_path=$relative
            mode=$mode
            blob=$blob
            size=[long]$declaredSize
            sha256=$fileSha
            lf_only=[bool](-not $hasCr)
            nul_free=[bool](-not $hasNul)
        }
        [byte[]]$entryBytes=$strictUtf8.GetBytes(
            (ConvertTo-Json -InputObject $entry -Compress -Depth 5)
        )
        $projectionBytes += $entryBytes.Length
        if ($entries.Count -gt 0) { $projectionBytes++ }
        $totalBytes += $declaredSize
        if ($projectionBytes -gt 7340032 -or $totalBytes -gt 1073741824) {
            throw 'Task 9 checkout projection/aggregate cap exceeded'
        }
        $entries.Add($entry)
        $entryMap.Add($relative,$entry)
    }

    $controlRelative='tests/skills/complete_suite_control_plane.ps1'
    $bootstrapRelative='tests/skills/complete_suite_release_python_bootstrap.py'
    $launcherRelative='tests/skills/complete_suite_artifact_launcher.ps1'
    $writerRelative='tests/skills/complete_suite_artifact_writer.py'
    if ($entryMap.ContainsKey($oracleRelative)) {
        throw 'Task 9 tree illegally contains the sibling artifact-oracle record'
    }
    if (-not $entryMap.ContainsKey($controlRelative) -or
        -not $entryMap.ContainsKey($bootstrapRelative) -or
        -not $entryMap.ContainsKey($launcherRelative) -or
        -not $entryMap.ContainsKey($writerRelative)) {
        throw 'Task 9 control/bootstrap/artifact-launcher/writer member is missing'
    }
    [byte[]]$controlBytes=Read-C6PlanOwnedPlainFile -Root $CheckoutRoot `
        -RelativePath $controlRelative -MaxBytes 4194304 `
        -ExpectedSha256 ([string]$entryMap[$controlRelative].sha256)
    [byte[]]$bootstrapBytes=Read-C6PlanOwnedPlainFile -Root $CheckoutRoot `
        -RelativePath $bootstrapRelative -MaxBytes 4194304 `
        -ExpectedSha256 ([string]$entryMap[$bootstrapRelative].sha256)
    [byte[]]$launcherBytes=Read-C6PlanOwnedPlainFile -Root $CheckoutRoot `
        -RelativePath $launcherRelative -MaxBytes 1048576 `
        -ExpectedSha256 ([string]$entryMap[$launcherRelative].sha256)
    [byte[]]$writerBytes=Read-C6PlanOwnedPlainFile -Root $CheckoutRoot `
        -RelativePath $writerRelative -MaxBytes 1048576 `
        -ExpectedSha256 ([string]$entryMap[$writerRelative].sha256)
    foreach ($bytes in @($controlBytes,$bootstrapBytes,$launcherBytes,$writerBytes)) {
        if ($bytes[-1] -ne 10 -or 0 -in $bytes -or 13 -in $bytes -or
            ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and
             $bytes[1] -eq 187 -and $bytes[2] -eq 191)) {
            throw 'Task 9 control/bootstrap/artifact-launcher/writer UTF-8/LF grammar mismatch'
        }
    }
    $controlText=$strictUtf8.GetString($controlBytes)
    $bootstrapText=$strictUtf8.GetString($bootstrapBytes)
    $launcherText=$strictUtf8.GetString($launcherBytes)
    $writerText=$strictUtf8.GetString($writerBytes)
    $launcherProjection=Get-C6PlanOwnedOracleProjection -Text $launcherText `
        -ExpectedKeys @(
            'launcher_ast_sha256','launcher_bootstrap_fixture_sha256',
            'launcher_rawui_reader_sha256'
        ) -Label artifact-launcher
    $writerProjection=Get-C6PlanOwnedOracleProjection -Text $writerText `
        -ExpectedKeys @(
            'writer_ast_sha256','writer_closed_import_native_call_table_sha256',
            'writer_launcher_fixture_sha256'
        ) -Label artifact-writer
    $actualBundleSha256=Get-C6PlanOwnedArtifactBundleSha256 `
        -LauncherBytes $launcherBytes -WriterBytes $writerBytes
    $actualSourceValues=@(
        [string]$entryMap[$launcherRelative].sha256,
        [string]$entryMap[$writerRelative].sha256
    )
    $actualSourceSizes=@(
        [long]$entryMap[$launcherRelative].size,
        [long]$entryMap[$writerRelative].size
    )
    $actualSemanticValues=@(
        [string]$launcherProjection.launcher_ast_sha256,
        [string]$launcherProjection.launcher_bootstrap_fixture_sha256,
        [string]$launcherProjection.launcher_rawui_reader_sha256,
        [string]$writerProjection.writer_ast_sha256,
        [string]$writerProjection.writer_closed_import_native_call_table_sha256,
        [string]$writerProjection.writer_launcher_fixture_sha256
    )
    $reviewSourceFields=@('launcher_source_sha256','writer_source_sha256')
    $reviewSourceSizeFields=@('launcher_source_size','writer_source_size')
    $reviewSourcePathFields=@(
        'launcher_source_relative_path','writer_source_relative_path'
    )
    $reviewSemanticFields=@(
        'launcher_ast_sha256','launcher_bootstrap_fixture_sha256',
        'launcher_rawui_reader_sha256','writer_ast_sha256',
        'writer_closed_import_native_call_table_sha256',
        'writer_launcher_fixture_sha256'
    )
    for ($index=0; $index -lt 2; $index++) {
        if ($oracleSources[$index].sha256 -cne $actualSourceValues[$index] -or
            $oracleSources[$index].size -ne $actualSourceSizes[$index] -or
            $review[$reviewSourcePathFields[$index]] -cne
                $expectedSourcePaths[$index] -or
            $review[$reviewSourceSizeFields[$index]] -ne
                $actualSourceSizes[$index] -or
            $review[$reviewSourceFields[$index]] -cne
                $actualSourceValues[$index]) {
            throw "artifact source differs from independent oracle at $index"
        }
    }
    for ($index=0; $index -lt 6; $index++) {
        if ($oracleSemantics[$index].sha256 -cne
                $actualSemanticValues[$index] -or
            $review[$reviewSemanticFields[$index]] -cne
                $actualSemanticValues[$index]) {
            throw "artifact semantic projection differs from oracle at $index"
        }
    }
    if ($review.reviewed_bundle_sha256 -cne $actualBundleSha256) {
        throw 'reviewed artifact bundle aggregate differs from exact source bytes'
    }
    $postRegistry=Get-C6PlanOwnedRegistryLiteral -Text $controlText `
        -BeginLine '# C6-POST-TRUST-SELECTION-REGISTRY-BEGIN' `
        -EndLine '# C6-POST-TRUST-SELECTION-REGISTRY-END' `
        -VariableName 'C6PostTrustSelectionRegistryJson'
    $implementationRegistry=Get-C6PlanOwnedRegistryLiteral -Text $controlText `
        -BeginLine '# C6-CONSTRUCTOR-IMPLEMENTATION-SET-BEGIN' `
        -EndLine '# C6-CONSTRUCTOR-IMPLEMENTATION-SET-END' `
        -VariableName 'C6ConstructorImplementationSetJson'
    $attributeRegistry=Get-C6PlanOwnedRegistryLiteral -Text $controlText `
        -BeginLine '# C6-CONSTRUCTOR-ATTRIBUTE-SET-BEGIN' `
        -EndLine '# C6-CONSTRUCTOR-ATTRIBUTE-SET-END' `
        -VariableName 'C6ConstructorAttributeSetJson'
    $topologyRegistry=Get-C6PlanOwnedRegistryLiteral -Text $controlText `
        -BeginLine '# C6-JOB-TOPOLOGY-BEGIN' `
        -EndLine '# C6-JOB-TOPOLOGY-END' `
        -VariableName 'C6JobTopologyJson'
    $artifactTtyContract=Get-C6PlanOwnedRegistryLiteral -Text $launcherText `
        -BeginLine '# C6-ARTIFACT-TTY-CONTRACT-BEGIN' `
        -EndLine '# C6-ARTIFACT-TTY-CONTRACT-END' `
        -VariableName 'C6ArtifactTtyContractJson'
    Assert-C6PlanOwnedRegistryIds -Parsed $postRegistry.parsed `
        -IdKey selection -ExpectedIds @(
            'task09-client-record-replay','task09-integrated',
            'task10-red','task10-integrated'
        ) -Label 'post-trust selection registry'
    Assert-C6PlanOwnedRegistryIds -Parsed $implementationRegistry.parsed `
        -IdKey constructor_implementation_id -ExpectedIds @(
            'host-native-core-v1','broker-native-core-v1'
        ) -Label 'constructor implementation registry'
    Assert-C6PlanOwnedRegistryIds -Parsed $attributeRegistry.parsed `
        -IdKey constructor_class -ExpectedIds @(
            'root-broker','guarded-target-or-native-leaf','codex-client-root'
        ) -Label 'constructor attribute registry'
    Assert-C6PlanOwnedRegistryIds -Parsed $topologyRegistry.parsed `
        -IdKey topology_id -ExpectedIds @(
            'root-broker','standalone-native-leaf','initial-guarded-target',
            'nested-guarded-target','broker-native-leaf','codex-client-root',
            'codex-client-descendant'
        ) -Label 'Job topology registry'
    $selectionKeys=@(
        'selection','adapter','pytest_argv','binding_keys','expected_exit',
        'expected_terminal_contract'
    )
    foreach ($record in @($postRegistry.parsed)) {
        Assert-C6PlanOwnedKeys -Value $record -Expected $selectionKeys `
            -Label 'post-trust selection registry record'
    }
    $commonSuffix=[object[]]@(
        '-q','-p','no:cacheprovider','--basetemp','BROKER_BASETEMP'
    )
    $securityNodes=[object[]]@(
        ('tests/security/test_authoring_security.py::' +
         'test_fsync_entry_real_junction_mutation_fails_closed_when_supported'),
        ('tests/security/test_persistence_security.py::' +
         'test_storage_rejects_real_windows_junction_when_supported'),
        ('tests/security/test_research_security.py::' +
         'test_rejects_real_windows_junction_or_skips_with_exact_reason')
    )
    $task10Families=[object[]]@(
        'campaign6_structure','provider_attempt','execute_boundary',
        'guarded_pytest_audit','zero_codex_guard','release_broker',
        'release_gate_audit','closure_manifest_audit'
    )
    $forbiddenTerminal=[object[]]@(
        'skipped','xfailed','xpassed','rerun','missing','error'
    )
    $task10Argv=[object[]](@(
        'tests/skills/test_complete_suite_campaign_structure.py',
        'tests/skills/test_complete_suite_preparation.py',
        'tests/skills/test_complete_suite_evidence.py',
        $securityNodes[0],$securityNodes[1],$securityNodes[2],
        '-k',
        ('campaign6_structure or provider_attempt or execute_boundary or ' +
         'guarded_pytest_audit or zero_codex_guard or release_broker or ' +
         'release_gate_audit or closure_manifest_audit or ' +
         'fsync_entry_real_junction_mutation_fails_closed_when_supported or ' +
         'storage_rejects_real_windows_junction_when_supported or ' +
         'rejects_real_windows_junction_or_skips_with_exact_reason')
    ) + $commonSuffix)
    $expectedSelections=[object[]]@(
        [ordered]@{
            selection='task09-client-record-replay'
            adapter='development-pytest'
            pytest_argv=[object[]](@(
                'tests/skills/test_complete_suite_shell_preflight.py',
                'tests/skills/test_complete_suite_evidence.py',
                'tests/skills/test_complete_suite_release_evidence.py',
                '-k',
                ('client_preflight_record_replay or ' +
                 'client_evaluation_envelope_replay or ' +
                 'approved_client_launch_replay')
            ) + $commonSuffix)
            binding_keys=[object[]]@(
                'selection','preflight_record',
                'expected_preflight_record_sha256','preflight_audit_record',
                'expected_preflight_audit_record_sha256',
                'producer_evaluation_envelope_record',
                'expected_producer_evaluation_envelope_sha256',
                'client_evaluation_envelope_manifest',
                'expected_client_evaluation_envelope_manifest_sha256',
                'client_evaluation_envelopes','phase_root',
                'evaluation_envelope_record','evaluation_envelope_sha256'
            )
            expected_exit=[long]0
            expected_terminal_contract=[ordered]@{
                schema_version='complete-suite-selection-terminal-contract-v1'
                classification='families'
                ordered_families=[object[]]@(
                    'client_preflight_record_replay',
                    'client_evaluation_envelope_replay',
                    'approved_client_launch_replay'
                )
                ordered_exact_nodes=[object[]]@()
                family_terminal='passed'
                exact_node_terminal=$null
                minimum_nodes_per_family=[long]1
                reject_unclassified_nodes=$true
                forbidden_terminal_states=$forbiddenTerminal
            }
        },
        [ordered]@{
            selection='task09-integrated'
            adapter='development-pytest'
            pytest_argv=[object[]](@(
                ('tests/skills/test_complete_suite_shell_preflight.py::' +
                 'test_task9_committed_control_plane_integrated'),
                ('tests/skills/test_complete_suite_artifact_writer.py::' +
                 'test_task9_committed_artifact_writer_integrated'),
                ('tests/skills/test_complete_suite_evidence.py::' +
                 'test_task9_client_record_replay'),
                ('tests/skills/test_complete_suite_release_evidence.py::' +
                 'test_task9_launch_evidence_release_replay'),
                ('tests/skills/test_complete_suite_preparation.py::' +
                 'test_task9_zero_launch_proof')
            ) + $commonSuffix)
            binding_keys=[object[]]@(
                'selection','transition_record',
                'expected_transition_record_sha256','trust_record',
                'expected_trust_record_sha256','preflight_record',
                'expected_preflight_record_sha256','preflight_audit_record',
                'expected_preflight_audit_record_sha256',
                'producer_evaluation_envelope_record',
                'expected_producer_evaluation_envelope_sha256',
                'client_evaluation_envelope_manifest',
                'expected_client_evaluation_envelope_manifest_sha256',
                'client_evaluation_envelopes','phase_root',
                'evaluation_envelope_record','evaluation_envelope_sha256'
            )
            expected_exit=[long]0
            expected_terminal_contract=[ordered]@{
                schema_version='complete-suite-selection-terminal-contract-v1'
                classification='exact-nodes'
                ordered_families=[object[]]@()
                ordered_exact_nodes=[object[]]@(
                    ('tests/skills/test_complete_suite_shell_preflight.py::' +
                     'test_task9_committed_control_plane_integrated'),
                    ('tests/skills/test_complete_suite_artifact_writer.py::' +
                     'test_task9_committed_artifact_writer_integrated'),
                    ('tests/skills/test_complete_suite_evidence.py::' +
                     'test_task9_client_record_replay'),
                    ('tests/skills/test_complete_suite_release_evidence.py::' +
                     'test_task9_launch_evidence_release_replay'),
                    ('tests/skills/test_complete_suite_preparation.py::' +
                     'test_task9_zero_launch_proof')
                )
                family_terminal=$null
                exact_node_terminal='passed'
                minimum_nodes_per_family=[long]0
                reject_unclassified_nodes=$true
                forbidden_terminal_states=$forbiddenTerminal
            }
        },
        [ordered]@{
            selection='task10-red'
            adapter='development-pytest'
            pytest_argv=$task10Argv
            binding_keys=[object[]]@(
                'selection','source_mode','phase_root','trust_record',
                'expected_trust_record_sha256','evaluation_envelope_record',
                'evaluation_envelope_sha256'
            )
            expected_exit=[long]1
            expected_terminal_contract=[ordered]@{
                schema_version='complete-suite-selection-terminal-contract-v1'
                classification='families-plus-exact-nodes'
                ordered_families=$task10Families
                ordered_exact_nodes=$securityNodes
                family_terminal='failed'
                exact_node_terminal='passed'
                minimum_nodes_per_family=[long]1
                reject_unclassified_nodes=$true
                forbidden_terminal_states=$forbiddenTerminal
            }
        },
        [ordered]@{
            selection='task10-integrated'
            adapter='guarded-pytest-audit'
            pytest_argv=$task10Argv
            binding_keys=[ordered]@{
                'authenticated-provisional'=[object[]]@(
                    'source_root','source_identity_mode','selection',
                    'guard_source','guard_record',
                    'expected_guard_record_sha256','phase_root',
                    'expected_parent','expected_tree','provisional_record',
                    'expected_provisional_record_sha256','output',
                    'evaluation_envelope_record','evaluation_envelope_sha256'
                )
                commit=[object[]]@(
                    'source_root','source_identity_mode','selection',
                    'guard_source','guard_record',
                    'expected_guard_record_sha256','phase_root','expected_head',
                    'expected_parent','expected_tree','prior_audit_record',
                    'expected_prior_audit_record_sha256','output',
                    'evaluation_envelope_record','evaluation_envelope_sha256'
                )
            }
            expected_exit=[long]0
            expected_terminal_contract=[ordered]@{
                schema_version='complete-suite-selection-terminal-contract-v1'
                classification='families-plus-exact-nodes'
                ordered_families=$task10Families
                ordered_exact_nodes=$securityNodes
                family_terminal='passed'
                exact_node_terminal='passed'
                minimum_nodes_per_family=[long]1
                reject_unclassified_nodes=$true
                forbidden_terminal_states=$forbiddenTerminal
            }
        }
    )
    if ((ConvertTo-Json -InputObject $postRegistry.parsed `
            -Compress -Depth 30) -cne
        (ConvertTo-Json -InputObject $expectedSelections `
            -Compress -Depth 30)) {
        throw 'post-trust selection registry semantics mismatch'
    }
    $attributeKeys=@(
        'constructor_class','subject_kinds',
        'permitted_implementation_contexts','proc_thread_attribute_tokens',
        'direct_child_authority'
    )
    foreach ($record in @($attributeRegistry.parsed)) {
        Assert-C6PlanOwnedKeys -Value $record -Expected $attributeKeys `
            -Label 'constructor attribute registry record'
    }
    $topologyKeys=@(
        'topology_id','implicit_campaign_job_kinds',
        'explicit_job_list_kinds','effective_campaign_job_kinds',
        'immediate_scope','completion_owner','termination_owner'
    )
    foreach ($record in @($topologyRegistry.parsed)) {
        Assert-C6PlanOwnedKeys -Value $record -Expected $topologyKeys `
            -Label 'Job topology registry record'
    }
    $rootImplementationContext=[object[]]@(
        'host-native-core-v1','root-broker'
    )
    $standaloneImplementationContext=[object[]]@(
        'host-native-core-v1','standalone-native-leaf'
    )
    $brokerImplementationContext=[object[]]@(
        'broker-native-core-v1','guarded-target-or-native-leaf'
    )
    $clientImplementationContext=[object[]]@(
        'broker-native-core-v1','codex-client-root'
    )
    $expectedAttributes=[object[]]@(
        [ordered]@{
            constructor_class='root-broker'
            subject_kinds=[object[]]@('root-broker')
            permitted_implementation_contexts=(,$rootImplementationContext)
            proc_thread_attribute_tokens=[object[]]@(
                'HANDLE_LIST','JOB_LIST'
            )
            direct_child_authority='closed-broker-api-only'
        },
        [ordered]@{
            constructor_class='guarded-target-or-native-leaf'
            subject_kinds=[object[]]@(
                'guarded-python-target','native-leaf'
            )
            permitted_implementation_contexts=[object[]]@(
                $standaloneImplementationContext,
                $brokerImplementationContext
            )
            proc_thread_attribute_tokens=[object[]]@(
                'HANDLE_LIST','JOB_LIST',
                'CHILD_PROCESS_POLICY=PROCESS_CREATION_CHILD_PROCESS_RESTRICTED'
            )
            direct_child_authority='none'
        },
        [ordered]@{
            constructor_class='codex-client-root'
            subject_kinds=[object[]]@(
                'loopback-codex-client-root','approved-codex-client-root'
            )
            permitted_implementation_contexts=(,$clientImplementationContext)
            proc_thread_attribute_tokens=[object[]]@(
                'HANDLE_LIST','JOB_LIST'
            )
            direct_child_authority=(
                'unchanged-client-declared-descendants-only'
            )
        }
    )
    $expectedTopologies=[object[]]@(
        [ordered]@{
            topology_id='root-broker'
            implicit_campaign_job_kinds=[object[]]@()
            explicit_job_list_kinds=[object[]]@('J0')
            effective_campaign_job_kinds=[object[]]@('J0')
            immediate_scope='J0'
            completion_owner='host:P0:J0'
            termination_owner='host:J0'
        },
        [ordered]@{
            topology_id='standalone-native-leaf'
            implicit_campaign_job_kinds=[object[]]@()
            explicit_job_list_kinds=[object[]]@('L0')
            effective_campaign_job_kinds=[object[]]@('L0')
            immediate_scope='L0'
            completion_owner='host:P0:L0'
            termination_owner='host:L0'
        },
        [ordered]@{
            topology_id='initial-guarded-target'
            implicit_campaign_job_kinds=[object[]]@('J0')
            explicit_job_list_kinds=[object[]]@('J1','T0')
            effective_campaign_job_kinds=[object[]]@('J0','J1','T0')
            immediate_scope='T0'
            completion_owner='root:P1:J1'
            termination_owner='root:T0'
        },
        [ordered]@{
            topology_id='nested-guarded-target'
            implicit_campaign_job_kinds=[object[]]@('J0')
            explicit_job_list_kinds=[object[]]@('J1','T0..Tk','Tnew')
            effective_campaign_job_kinds=[object[]]@(
                'J0','J1','T0..Tk','Tnew'
            )
            immediate_scope='Tnew'
            completion_owner='root:P1:J1'
            termination_owner='root:Tnew'
        },
        [ordered]@{
            topology_id='broker-native-leaf'
            implicit_campaign_job_kinds=[object[]]@('J0')
            explicit_job_list_kinds=[object[]]@('J1','T0..Tk','Ln')
            effective_campaign_job_kinds=[object[]]@(
                'J0','J1','T0..Tk','Ln'
            )
            immediate_scope='Ln'
            completion_owner='root:P1:J1'
            termination_owner='root:Ln'
        },
        [ordered]@{
            topology_id='codex-client-root'
            implicit_campaign_job_kinds=[object[]]@('J0')
            explicit_job_list_kinds=[object[]]@('J1','T0..Tk','Cn')
            effective_campaign_job_kinds=[object[]]@(
                'J0','J1','T0..Tk','Cn'
            )
            immediate_scope='Cn'
            completion_owner='root:P1:J1'
            termination_owner='root:Cn'
        },
        [ordered]@{
            topology_id='codex-client-descendant'
            implicit_campaign_job_kinds=[object[]]@(
                'parent-effective-chain'
            )
            explicit_job_list_kinds=[object[]]@()
            effective_campaign_job_kinds=[object[]]@(
                'parent-effective-chain'
            )
            immediate_scope='inherited-Cn'
            completion_owner='root:P1:J1'
            termination_owner='root:Cn'
        }
    )
    if ((ConvertTo-Json -InputObject $attributeRegistry.parsed `
            -Compress -Depth 30) -cne
            (ConvertTo-Json -InputObject $expectedAttributes `
                -Compress -Depth 30) -or
        (ConvertTo-Json -InputObject $topologyRegistry.parsed `
            -Compress -Depth 30) -cne
            (ConvertTo-Json -InputObject $expectedTopologies `
                -Compress -Depth 30)) {
        throw 'constructor attribute or Job topology semantics mismatch'
    }
    $hostBodySha=Get-C6PlanOwnedImplementationBodySha256 -Text $controlText `
        -BeginLine '# C6-HOST-NATIVE-CONSTRUCTOR-IMPLEMENTATION-BEGIN' `
        -EndLine '# C6-HOST-NATIVE-CONSTRUCTOR-IMPLEMENTATION-END'
    $brokerBodySha=Get-C6PlanOwnedImplementationBodySha256 -Text $bootstrapText `
        -BeginLine '# C6-BROKER-NATIVE-CONSTRUCTOR-IMPLEMENTATION-BEGIN' `
        -EndLine '# C6-BROKER-NATIVE-CONSTRUCTOR-IMPLEMENTATION-END'
    $implementationRecords=@($implementationRegistry.parsed)
    $implementationKeys=@(
        'constructor_implementation_id','source_relative_path',
        'implementation_sha256','permitted_contexts'
    )
    Assert-C6PlanOwnedKeys -Value $implementationRecords[0] `
        -Expected $implementationKeys -Label 'host constructor registry record'
    Assert-C6PlanOwnedKeys -Value $implementationRecords[1] `
        -Expected $implementationKeys -Label 'broker constructor registry record'
    if ($implementationRecords[0].source_relative_path -cne $controlRelative -or
        $implementationRecords[0].implementation_sha256 -cne $hostBodySha -or
        (@($implementationRecords[0].permitted_contexts) -join "`n") -cne
            "root-broker`nstandalone-native-leaf" -or
        $implementationRecords[1].source_relative_path -cne $bootstrapRelative -or
        $implementationRecords[1].implementation_sha256 -cne $brokerBodySha -or
        (@($implementationRecords[1].permitted_contexts) -join "`n") -cne
            "guarded-target-or-native-leaf`ncodex-client-root") {
        throw 'constructor implementation registry/body mismatch'
    }

    $finalSourceHead=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-head @gitArgs) `
        -Label final-source-head -Pattern '^[0-9a-f]{40}$'
    $finalSourceTree=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role source-tree @gitArgs) `
        -Label final-source-tree -Pattern '^[0-9a-f]{40}$'
    $finalCheckoutHead=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role checkout-head @gitArgs) `
        -Label final-checkout-head -Pattern '^[0-9a-f]{40}$'
    $finalCheckoutTree=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role checkout-tree @gitArgs) `
        -Label final-checkout-tree -Pattern '^[0-9a-f]{40}$'
    $finalOracleHead=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role oracle-head @gitArgs) `
        -Label final-oracle-head -Pattern '^[0-9a-f]{40}$'
    $finalOracleTree=ConvertFrom-C6Task9SingleLine `
        -Bytes (Invoke-C6Task9PostcheckGit -Role oracle-tree @gitArgs) `
        -Label final-oracle-tree -Pattern '^[0-9a-f]{40}$'
    if ($finalSourceHead -cne $ExpectedTask9Commit -or
        $finalSourceTree -cne $sourceTree -or
        $finalCheckoutHead -cne $ExpectedTask9Commit -or
        $finalCheckoutTree -cne $sourceTree -or
        $finalOracleHead -cne $artifactOracleHandoff.artifact_oracle_commit -or
        $finalOracleTree -cne $artifactOracleHandoff.artifact_oracle_tree -or
        (Invoke-C6Task9PostcheckGit -Role source-status @gitArgs).Length -ne 0 -or
        (Invoke-C6Task9PostcheckGit -Role checkout-status @gitArgs).Length -ne 0 -or
        (Invoke-C6Task9PostcheckGit -Role checkout-detached @gitArgs).Length -ne 0 -or
        (Invoke-C6Task9PostcheckGit -Role oracle-status @gitArgs).Length -ne 0 -or
        (Invoke-C6Task9PostcheckGit -Role oracle-detached @gitArgs).Length -ne 0) {
        throw 'Task 9 source/checkout/oracle changed during the closed postcheck'
    }

    $zeroRoot='D:\tmp\kokoroarc-c6-zero-codex-envelope-' +
        [Guid]::NewGuid().ToString('N')
    $transitionRoot='D:\tmp\kokoroarc-c6-task09-transition-' +
        [Guid]::NewGuid().ToString('N')
    if ((Test-Path -LiteralPath $zeroRoot) -or
        (Test-Path -LiteralPath $transitionRoot)) {
        throw 'Task 9 generated output root unexpectedly exists'
    }
    return [ordered]@{
        plan_commit=[string]$handoff.plan.commit
        plan_tree=[string]$handoff.plan.tree
        plan_blob=[string]$handoff.plan.blob
        plan_sha256=[string]$handoff.plan.sha256
        handoff_path=$HandoffPath
        handoff_sha256=$ExpectedHandoffSha256
        task8_commit=$ExpectedTask8Commit
        task9_commit=$ExpectedTask9Commit
        task9_tree=$sourceTree
        post_trust_selection_registry_sha256=$postRegistry.sha256
        host_constructor_implementation_sha256=$hostBodySha
        broker_constructor_implementation_sha256=$brokerBodySha
        constructor_implementation_set_sha256=$implementationRegistry.sha256
        constructor_attribute_set_sha256=$attributeRegistry.sha256
        job_topology_sha256=$topologyRegistry.sha256
        artifact_tty_contract_sha256=$artifactTtyContract.sha256
        artifact_oracle_path=$expectedOraclePath
        artifact_oracle_commit=[string]$artifactOracleHandoff.artifact_oracle_commit
        artifact_oracle_tree=[string]$artifactOracleHandoff.artifact_oracle_tree
        artifact_oracle_blob=[string]$artifactOracleHandoff.artifact_oracle_blob
        artifact_oracle_size=[long]$artifactOracleHandoff.artifact_oracle_size
        artifact_oracle_sha256=[string]$artifactOracleHandoff.artifact_oracle_sha256
        artifact_oracle_review_result_sha256=(
            [string]$artifactOracleHandoff.review_result_sha256
        )
        artifact_oracle_digest_count=[long]8
        checkout_root=$CheckoutRoot
        checkout_entries=[object[]]$entries.ToArray()
        zero_envelope_root=$zeroRoot
        transition_root=$transitionRoot
    }
    } finally {
        foreach ($heldRecord in $oracleHeldRecords) {
            try { Confirm-C6PlanOwnedHeldJson -Held $heldRecord } finally {
                $heldRecord.opened.Dispose()
            }
        }
    }
}

function Write-C6Task9TransitionArtifacts {
    param(
        [Parameter(Mandatory)]
        [Collections.IDictionary]$Task9TransitionInputs
    )
    $inputKeys=@(
        'plan_commit','plan_tree','plan_blob','plan_sha256',
        'handoff_path','handoff_sha256','task8_commit','task9_commit',
        'task9_tree','post_trust_selection_registry_sha256',
        'host_constructor_implementation_sha256',
        'broker_constructor_implementation_sha256',
        'constructor_implementation_set_sha256',
        'constructor_attribute_set_sha256','job_topology_sha256',
        'artifact_tty_contract_sha256',
        'artifact_oracle_path','artifact_oracle_commit','artifact_oracle_tree',
        'artifact_oracle_blob','artifact_oracle_size','artifact_oracle_sha256',
        'artifact_oracle_review_result_sha256','artifact_oracle_digest_count',
        'checkout_root','checkout_entries',
        'zero_envelope_root','transition_root'
    )
    Assert-C6PlanOwnedKeys -Value $Task9TransitionInputs `
        -Expected $inputKeys -Label 'Task9TransitionInputs'
    foreach ($name in @(
        'plan_commit','plan_tree','plan_blob','task8_commit','task9_commit',
        'task9_tree','artifact_oracle_commit','artifact_oracle_tree',
        'artifact_oracle_blob'
    )) {
        if ($Task9TransitionInputs[$name] -isnot [string] -or
            $Task9TransitionInputs[$name] -cnotmatch '^[0-9a-f]{40}$') {
            throw "invalid 40-hex Task 9 input: $name"
        }
    }
    foreach ($name in @(
        'plan_sha256','handoff_sha256',
        'post_trust_selection_registry_sha256',
        'host_constructor_implementation_sha256',
        'broker_constructor_implementation_sha256',
        'constructor_implementation_set_sha256',
        'constructor_attribute_set_sha256','job_topology_sha256',
        'artifact_tty_contract_sha256','artifact_oracle_sha256',
        'artifact_oracle_review_result_sha256'
    )) {
        if ($Task9TransitionInputs[$name] -isnot [string] -or
            $Task9TransitionInputs[$name] -cnotmatch '^[0-9a-f]{64}$') {
            throw "invalid 64-hex Task 9 input: $name"
        }
    }
    if ($Task9TransitionInputs.artifact_oracle_path -isnot [string] -or
        $Task9TransitionInputs.artifact_oracle_size -isnot [long] -or
        $Task9TransitionInputs.artifact_oracle_size -lt 2 -or
        $Task9TransitionInputs.artifact_oracle_size -gt 65536 -or
        $Task9TransitionInputs.artifact_oracle_digest_count -isnot [long] -or
        $Task9TransitionInputs.artifact_oracle_digest_count -ne 8) {
        throw 'invalid artifact-oracle Task 9 input'
    }
    $checkoutRoot=[string]$Task9TransitionInputs.checkout_root
    $zeroRoot=[string]$Task9TransitionInputs.zero_envelope_root
    $transitionRoot=[string]$Task9TransitionInputs.transition_root
    if ($checkoutRoot -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-task09-checkout-[0-9a-f]{32}\z' -or
        $zeroRoot -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-zero-codex-envelope-[0-9a-f]{32}\z' -or
        $transitionRoot -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-task09-transition-[0-9a-f]{32}\z' -or
        (Test-Path -LiteralPath $zeroRoot) -or
        (Test-Path -LiteralPath $transitionRoot)) {
        throw 'Task 9 roots violate their closed fresh-root grammar'
    }
    $checkoutItem=Get-Item -LiteralPath $checkoutRoot -Force -ErrorAction Stop
    if (-not $checkoutItem.PSIsContainer -or
        (($checkoutItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'Task 9 checkout root is not an observed plain directory'
    }
    [void](Read-C6PlanOwnedJson `
        -Path ([string]$Task9TransitionInputs.handoff_path) `
        -ExpectedSha256 ([string]$Task9TransitionInputs.handoff_sha256) `
        -MaxBytes 65536)
    if ([string]$Task9TransitionInputs.artifact_oracle_path -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-task9-artifact-source-oracle-checkout-' +
            '[0-9a-f]{32}\\docs\\superpowers\\plans\\' +
            '2026-08-21-kokoroarc-complete-suite-campaign-6-' +
            'task9-artifact-source-oracle\.json\z') {
        throw 'artifact-oracle path is outside its authenticated checkout grammar'
    }
    $oracleHeldForWrite=Read-C6PlanOwnedHeldJson `
        -Path ([string]$Task9TransitionInputs.artifact_oracle_path) `
        -ExpectedSha256 ([string]$Task9TransitionInputs.artifact_oracle_sha256) `
        -MaxBytes 65536 -Role artifact-oracle-write-stage
    try {
    if ($oracleHeldForWrite.bytes.Length -ne
            $Task9TransitionInputs.artifact_oracle_size -or
        (Get-C6PlanOwnedGitBlobOid $oracleHeldForWrite.bytes) -cne
            $Task9TransitionInputs.artifact_oracle_blob) {
        throw 'artifact-oracle write-stage tuple mismatch'
    }

    $entryKeys=@(
        'relative_path','mode','blob','size','sha256','lf_only','nul_free'
    )
    $entries=@($Task9TransitionInputs.checkout_entries)
    if ($entries.Count -lt 1 -or $entries.Count -gt 50000) {
        throw 'Task 9 checkout entry count is outside 1..50000'
    }
    [long]$maxCheckoutBytes=1073741824L
    [long]$maxEntryProjectionBytes=7340032L
    [long]$maxManifestBytes=8388608L
    $strictUtf8=[Text.UTF8Encoding]::new($false,$true)
    $entryProjectionStream=[IO.MemoryStream]::new()
    $entryProjectionStream.WriteByte(91)
    $normalized=[Collections.Generic.List[object]]::new()
    $entryMap=[Collections.Generic.Dictionary[string,object]]::new(
        [StringComparer]::Ordinal
    )
    $caseFolded=[Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $previous=''
    [long]$totalBytes=0
    foreach ($entry in $entries) {
        if ($entry -isnot [Collections.IDictionary]) {
            throw 'Task 9 checkout entry is not an ordered object'
        }
        Assert-C6PlanOwnedKeys -Value $entry -Expected $entryKeys `
            -Label 'Task 9 checkout entry'
        $relative=[string]$entry.relative_path
        $segments=$relative.Split('/')
        if ([string]::IsNullOrEmpty($relative) -or
            [IO.Path]::IsPathFullyQualified($relative) -or
            $relative.Contains('\') -or $relative.Contains(':') -or
            $relative.Contains([char]0) -or $relative.Contains('//') -or
            $segments -contains '.' -or $segments -contains '..' -or
            ($previous.Length -gt 0 -and
                [StringComparer]::Ordinal.Compare($previous,$relative) -ge 0) -or
            -not $caseFolded.Add($relative)) {
            throw "invalid, duplicate, or unsorted checkout path: $relative"
        }
        if ($entry.mode -isnot [string] -or
            @('100644','100755') -cnotcontains $entry.mode -or
            $entry.blob -isnot [string] -or
            $entry.blob -cnotmatch '^[0-9a-f]{40}$' -or
            $entry.sha256 -isnot [string] -or
            $entry.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $entry.size -isnot [long] -or $entry.size -lt 0 -or
            $entry.lf_only -isnot [bool] -or
            $entry.nul_free -isnot [bool]) {
            throw "invalid checkout entry scalar: $relative"
        }
        $absolute=Resolve-C6PlanOwnedPlainFile -Root $checkoutRoot `
            -RelativePath $relative
        if ([IO.Path]::GetRelativePath($checkoutRoot,$absolute).Replace(
                [char]92,[char]47
            ) -cne $relative) {
            throw "checkout entry escapes or aliases its root: $relative"
        }
        if ($totalBytes -gt $maxCheckoutBytes - $entry.size) {
            throw 'Task 9 checkout aggregate exceeds 1 GiB'
        }
        $totalBytes += $entry.size
        $shaHasher=[Security.Cryptography.IncrementalHash]::CreateHash(
            [Security.Cryptography.HashAlgorithmName]::SHA256
        )
        $blobHasher=[Security.Cryptography.IncrementalHash]::CreateHash(
            [Security.Cryptography.HashAlgorithmName]::SHA1
        )
        $opened=$null
        $memberFailure=$null
        try {
            $opened=[C6PlanOwnedNativeFile]::OpenRegular($absolute)
            if ($opened.Length -gt 268435456 -or
                $opened.Length -ne $entry.size) {
                throw "checkout member type/size mismatch: $relative"
            }
            $memberIdentity=$opened.Identity
            $memberLength=$opened.Length
            $header=[Text.Encoding]::ASCII.GetBytes(
                'blob ' + $entry.size + [char]0
            )
            $blobHasher.AppendData($header)
            [byte[]]$buffer=[byte[]]::new(65536)
            [long]$fileBytesRead=0
            $hasCr=$false
            $hasNul=$false
            while (($count=$opened.Stream.Read(
                        $buffer,0,$buffer.Length
                    )) -gt 0) {
                if ($fileBytesRead + $count -gt $entry.size) {
                    throw "checkout member grew while hashing: $relative"
                }
                $shaHasher.AppendData($buffer,0,$count)
                $blobHasher.AppendData($buffer,0,$count)
                for ($byteIndex=0; $byteIndex -lt $count; $byteIndex++) {
                    if ($buffer[$byteIndex] -eq 13) { $hasCr=$true }
                    if ($buffer[$byteIndex] -eq 0) { $hasNul=$true }
                }
                $fileBytesRead += $count
            }
            $actualSha256=[Convert]::ToHexString(
                $shaHasher.GetHashAndReset()
            ).ToLowerInvariant()
            $actualBlob=[Convert]::ToHexString(
                $blobHasher.GetHashAndReset()
            ).ToLowerInvariant()
        } catch {
            $memberFailure=$_
            throw
        } finally {
            $cleanupFailure=$null
            foreach ($cleanup in @(
                [pscustomobject]@{
                    value=$opened
                    key='C6FinalCheckoutNativeHandleDisposeFailure'
                },
                [pscustomobject]@{
                    value=$shaHasher
                    key='C6FinalCheckoutSha256DisposeFailure'
                },
                [pscustomobject]@{
                    value=$blobHasher
                    key='C6FinalCheckoutBlobDisposeFailure'
                }
            )) {
                if ($null -ne $cleanup.value) {
                    try {
                        $cleanup.value.Dispose()
                    } catch {
                        if ($null -ne $memberFailure) {
                            $memberFailure.Exception.Data[$cleanup.key]=(
                                $_.Exception.Message
                            )
                        } elseif ($null -eq $cleanupFailure) {
                            $cleanupFailure=$_
                        } else {
                            $cleanupFailure.Exception.Data[$cleanup.key]=(
                                $_.Exception.Message
                            )
                        }
                    }
                }
            }
            if ($null -eq $memberFailure -and $null -ne $cleanupFailure) {
                throw $cleanupFailure
            }
        }
        $post=$null
        $postFailure=$null
        try {
            $post=[C6PlanOwnedNativeFile]::OpenRegular($absolute)
            if ($post.Identity -cne $memberIdentity -or
                $post.Length -ne $memberLength -or
                $post.Length -ne $entry.size) {
                throw "checkout member identity drift: $relative"
            }
        } catch {
            $postFailure=$_
            throw
        } finally {
            if ($null -ne $post) {
                try {
                    $post.Dispose()
                } catch {
                    if ($null -ne $postFailure) {
                        $postFailure.Exception.Data[
                            'C6FinalCheckoutPostHandleDisposeFailure'
                        ]=$_.Exception.Message
                    } else {
                        throw
                    }
                }
            }
        }
        [void](Resolve-C6PlanOwnedPlainFile -Root $checkoutRoot `
            -RelativePath $relative)
        if ($fileBytesRead -ne $entry.size -or
            $actualSha256 -cne $entry.sha256 -or
            $entry.lf_only -ne (-not $hasCr) -or
            $entry.nul_free -ne (-not $hasNul)) {
            throw "checkout member byte projection mismatch: $relative"
        }
        if ($actualBlob -cne $entry.blob) {
            throw "checkout member Git blob mismatch: $relative"
        }
        $normalizedEntry=[ordered]@{
            relative_path=$relative
            mode=[string]$entry.mode
            blob=[string]$entry.blob
            size=[long]$entry.size
            sha256=[string]$entry.sha256
            lf_only=[bool]$entry.lf_only
            nul_free=[bool]$entry.nul_free
        }
        $entryJson=$strictUtf8.GetBytes((
            ConvertTo-Json -InputObject $normalizedEntry -Compress -Depth 10
        ))
        [long]$separatorBytes=if ($normalized.Count -eq 0) { 0 } else { 1 }
        if ($entryProjectionStream.Length + $separatorBytes +
                $entryJson.Length + 1 -gt $maxEntryProjectionBytes) {
            throw 'Task 9 checkout entry projection exceeds 7 MiB'
        }
        if ($separatorBytes -eq 1) { $entryProjectionStream.WriteByte(44) }
        $entryProjectionStream.Write($entryJson,0,$entryJson.Length)
        $normalized.Add($normalizedEntry)
        $entryMap.Add($relative,$normalizedEntry)
        $previous=$relative
    }
    $controlRelative='tests/skills/complete_suite_control_plane.ps1'
    $bootstrapRelative=(
        'tests/skills/complete_suite_release_python_bootstrap.py'
    )
    $launcherRelative='tests/skills/complete_suite_artifact_launcher.ps1'
    $writerRelative='tests/skills/complete_suite_artifact_writer.py'
    if (-not $entryMap.ContainsKey($controlRelative) -or
        -not $entryMap.ContainsKey($bootstrapRelative) -or
        -not $entryMap.ContainsKey($launcherRelative) -or
        -not $entryMap.ContainsKey($writerRelative)) {
        throw 'Task 9 checkout omits a control-plane/bootstrap/artifact-launcher/writer leaf'
    }
    $controlEntry=$entryMap[$controlRelative]
    $bootstrapEntry=$entryMap[$bootstrapRelative]
    $launcherEntry=$entryMap[$launcherRelative]
    $writerEntry=$entryMap[$writerRelative]
    $entryProjectionStream.WriteByte(93)
    $entryProjection=$entryProjectionStream.ToArray()
    $entryProjectionStream.Dispose()
    [object[]]$normalizedEntries=$normalized.ToArray()
    $entryAggregate=Get-C6PlanOwnedSha256 $entryProjection
    $manifestValue=[ordered]@{
        schema_version='complete-suite-task9-checkout-manifest-v1'
        commit=[string]$Task9TransitionInputs.task9_commit
        tree=[string]$Task9TransitionInputs.task9_tree
        root=$checkoutRoot
        entries=$normalizedEntries
        file_count=[long]$normalizedEntries.Count
        file_bytes=$totalBytes
        aggregate_sha256=$entryAggregate
    }
    $manifestKeys=@(
        'schema_version','commit','tree','root','entries','file_count',
        'file_bytes','aggregate_sha256'
    )
    $manifestPreview=$strictUtf8.GetBytes((
        ConvertTo-Json -InputObject $manifestValue -Compress -Depth 30
    ))
    if ($manifestPreview.Length + 1 -gt $maxManifestBytes) {
        throw 'Task 9 checkout manifest exceeds 8 MiB before E creation'
    }

    $allowedRoles=[object[]]@(
        'development-pytest',
        'client-preflight-audit',
        'guarded-pytest-audit',
        'candidate-input-audit',
        'pre-freeze-gate-audit',
        'release-gate-audit',
        'envelope-audit',
        'host-review-audit',
        'authorize-provider',
        'close-provider-authorization-failure',
        'sealed-campaign-audit',
        'import-campaign',
        'adjudicate-campaign',
        'closure-manifest-audit'
    )
    $zeroPrefix='kokoroarc-c6-zero-codex-envelope-'
    $zeroId=[IO.Path]::GetFileName($zeroRoot).Substring($zeroPrefix.Length)
    $zeroValue=[ordered]@{
        schema_version='complete-suite-zero-codex-evaluation-envelope-v1'
        envelope_id=$zeroId
        purpose='campaign-6-committed-control-plane-non-client-operations'
        plan_commit=[string]$Task9TransitionInputs.plan_commit
        plan_sha256=[string]$Task9TransitionInputs.plan_sha256
        task9_commit=[string]$Task9TransitionInputs.task9_commit
        task9_tree=[string]$Task9TransitionInputs.task9_tree
        root_constructor_class='root-broker'
        root_constructor_implementation_id='host-native-core-v1'
        root_constructor_implementation_sha256=(
            [string]$Task9TransitionInputs.host_constructor_implementation_sha256
        )
        constructor_implementation_set_sha256=(
            [string]$Task9TransitionInputs.constructor_implementation_set_sha256
        )
        constructor_attribute_set_sha256=(
            [string]$Task9TransitionInputs.constructor_attribute_set_sha256
        )
        job_topology_sha256=(
            [string]$Task9TransitionInputs.job_topology_sha256
        )
        allowed_roles=$allowedRoles
        codex_processes_allowed=0
        provider_processes_allowed=0
        network_allowed=$false
        provider_credentials_allowed=$false
        cybersecurity_checks_may_be_bypassed=$false
        filesystem_scope='authenticated-role-defined-local-roots-only'
    }
    $zeroKeys=@(
        'schema_version','envelope_id','purpose','plan_commit','plan_sha256',
        'task9_commit','task9_tree','root_constructor_class',
        'root_constructor_implementation_id',
        'root_constructor_implementation_sha256',
        'constructor_implementation_set_sha256',
        'constructor_attribute_set_sha256','job_topology_sha256',
        'allowed_roles','codex_processes_allowed',
        'provider_processes_allowed','network_allowed',
        'provider_credentials_allowed','cybersecurity_checks_may_be_bypassed',
        'filesystem_scope'
    )
    $publicationOracleRelative=(
        'docs/superpowers/plans/' +
        '2026-08-21-kokoroarc-complete-suite-campaign-6-' +
        'task9-artifact-source-oracle.json'
    )
    $publicationOraclePath=[IO.Path]::GetFullPath(
        [string]$Task9TransitionInputs.artifact_oracle_path
    )
    $publicationOracleSuffix=[char]92 +
        $publicationOracleRelative.Replace('/',[char]92)
    if (-not $publicationOraclePath.EndsWith(
            $publicationOracleSuffix,[StringComparison]::Ordinal)) {
        throw 'publication oracle path/role suffix mismatch'
    }
    $publicationOracleRoot=$publicationOraclePath.Substring(
        0,$publicationOraclePath.Length-$publicationOracleSuffix.Length
    )
    if ($publicationOracleRoot -cnotmatch
            '\AD:\\tmp\\kokoroarc-c6-task9-artifact-source-oracle-checkout-' +
            '[0-9a-f]{32}\z') {
        throw 'publication oracle root grammar mismatch'
    }
    Assert-C6PlanOwnedSingleLinkCensus -Root $checkoutRoot `
        -MaxFiles 50000 -MaxDirectories 50000
    Assert-C6PlanOwnedSingleLinkFile -Root $publicationOracleRoot `
        -RelativePath $publicationOracleRelative `
        -Label artifact-oracle-prepublication
    New-C6PlanOwnedRoot -Root $zeroRoot `
        -Pattern '\AD:\\tmp\\kokoroarc-c6-zero-codex-envelope-[0-9a-f]{32}\z'
    $zeroPath=Join-Path $zeroRoot 'zero-codex-evaluation-envelope.json'
    $zeroRecord=Write-C6PlanOwnedJson -Path $zeroPath -Value $zeroValue `
        -ExpectedKeys $zeroKeys -MaxBytes 16384
    Assert-C6PlanOwnedMembership -Root $zeroRoot `
        -ExpectedNames @('zero-codex-evaluation-envelope.json')

    New-C6PlanOwnedRoot -Root $transitionRoot `
        -Pattern '\AD:\\tmp\\kokoroarc-c6-task09-transition-[0-9a-f]{32}\z'
    $manifestPath=Join-Path $transitionRoot 'checkout-manifest.json'
    $manifestRecord=Write-C6PlanOwnedJson -Path $manifestPath `
        -Value $manifestValue -ExpectedKeys $manifestKeys -MaxBytes 8388608
    Assert-C6PlanOwnedMembership -Root $transitionRoot `
        -ExpectedNames @('checkout-manifest.json')

    $authority=[ordered]@{
        plan_commit=[string]$Task9TransitionInputs.plan_commit
        plan_tree=[string]$Task9TransitionInputs.plan_tree
        plan_blob=[string]$Task9TransitionInputs.plan_blob
        plan_sha256=[string]$Task9TransitionInputs.plan_sha256
        handoff_path=[string]$Task9TransitionInputs.handoff_path
        handoff_sha256=[string]$Task9TransitionInputs.handoff_sha256
    }
    $controlPath=[IO.Path]::Combine(
        $checkoutRoot,$controlRelative.Replace('/',[char]92)
    )
    $bootstrapPath=[IO.Path]::Combine(
        $checkoutRoot,$bootstrapRelative.Replace('/',[char]92)
    )
    $launcherPath=[IO.Path]::Combine(
        $checkoutRoot,$launcherRelative.Replace('/',[char]92)
    )
    $writerPath=[IO.Path]::Combine(
        $checkoutRoot,$writerRelative.Replace('/',[char]92)
    )
    $trustValue=[ordered]@{
        schema_version='complete-suite-task9-trust-v3'
        authority=$authority
        task8_commit=[string]$Task9TransitionInputs.task8_commit
        task9_commit=[string]$Task9TransitionInputs.task9_commit
        task9_tree=[string]$Task9TransitionInputs.task9_tree
        checkout_root=$checkoutRoot
        checkout_manifest_path=$manifestPath
        checkout_manifest_sha256=$manifestRecord.sha256
        zero_codex_envelope_path=$zeroPath
        zero_codex_envelope_sha256=$zeroRecord.sha256
        python_runtime_inventory_sha256=(
            '34413fbc3fc1404957999a286c20723a24eea7f3c862bdfff289cefc5a275ec9'
        )
        powershell_runtime_inventory_sha256=(
            '267a116743b5fb75c4d1530d164afd8406989587b4def95ec10a804dffd07ee0'
        )
        git_runtime_inventory_sha256=(
            '202e5fd8bebf7901edcd35a993a66af3ca12a60836c083b0a0d877c7a2d64c87'
        )
        post_trust_selection_registry_sha256=(
            [string]$Task9TransitionInputs.post_trust_selection_registry_sha256
        )
        host_constructor_implementation_sha256=(
            [string]$Task9TransitionInputs.host_constructor_implementation_sha256
        )
        broker_constructor_implementation_sha256=(
            [string]$Task9TransitionInputs.broker_constructor_implementation_sha256
        )
        constructor_implementation_set_sha256=(
            [string]$Task9TransitionInputs.constructor_implementation_set_sha256
        )
        constructor_attribute_set_sha256=(
            [string]$Task9TransitionInputs.constructor_attribute_set_sha256
        )
        job_topology_sha256=(
            [string]$Task9TransitionInputs.job_topology_sha256
        )
        control_plane_path=$controlPath
        control_plane_blob=$controlEntry.blob
        control_plane_size=[long]$controlEntry.size
        control_plane_sha256=$controlEntry.sha256
        python_bootstrap_path=$bootstrapPath
        python_bootstrap_blob=$bootstrapEntry.blob
        python_bootstrap_size=[long]$bootstrapEntry.size
        python_bootstrap_sha256=$bootstrapEntry.sha256
        artifact_tty_contract_sha256=(
            [string]$Task9TransitionInputs.artifact_tty_contract_sha256
        )
        artifact_oracle_path=[string]$Task9TransitionInputs.artifact_oracle_path
        artifact_oracle_commit=[string]$Task9TransitionInputs.artifact_oracle_commit
        artifact_oracle_tree=[string]$Task9TransitionInputs.artifact_oracle_tree
        artifact_oracle_blob=[string]$Task9TransitionInputs.artifact_oracle_blob
        artifact_oracle_size=[long]$Task9TransitionInputs.artifact_oracle_size
        artifact_oracle_sha256=[string]$Task9TransitionInputs.artifact_oracle_sha256
        artifact_oracle_review_result_sha256=(
            [string]$Task9TransitionInputs.artifact_oracle_review_result_sha256
        )
        artifact_oracle_digest_count=(
            [long]$Task9TransitionInputs.artifact_oracle_digest_count
        )
        artifact_launcher_path=$launcherPath
        artifact_launcher_blob=$launcherEntry.blob
        artifact_launcher_size=[long]$launcherEntry.size
        artifact_launcher_sha256=$launcherEntry.sha256
        artifact_writer_path=$writerPath
        artifact_writer_blob=$writerEntry.blob
        artifact_writer_size=[long]$writerEntry.size
        artifact_writer_sha256=$writerEntry.sha256
        codex_processes_requested=0
        provider_credentials_supplied=$false
        verdict='pass'
    }
    $trustKeys=@(
        'schema_version','authority','task8_commit','task9_commit','task9_tree',
        'checkout_root','checkout_manifest_path','checkout_manifest_sha256',
        'zero_codex_envelope_path','zero_codex_envelope_sha256',
        'python_runtime_inventory_sha256',
        'powershell_runtime_inventory_sha256','git_runtime_inventory_sha256',
        'post_trust_selection_registry_sha256',
        'host_constructor_implementation_sha256',
        'broker_constructor_implementation_sha256',
        'constructor_implementation_set_sha256',
        'constructor_attribute_set_sha256',
        'job_topology_sha256',
        'control_plane_path','control_plane_blob','control_plane_size',
        'control_plane_sha256','python_bootstrap_path','python_bootstrap_blob',
        'python_bootstrap_size','python_bootstrap_sha256',
        'artifact_tty_contract_sha256','artifact_oracle_path',
        'artifact_oracle_commit','artifact_oracle_tree','artifact_oracle_blob',
        'artifact_oracle_size','artifact_oracle_sha256',
        'artifact_oracle_review_result_sha256','artifact_oracle_digest_count',
        'artifact_launcher_path',
        'artifact_launcher_blob','artifact_launcher_size','artifact_launcher_sha256',
        'artifact_writer_path','artifact_writer_blob','artifact_writer_size',
        'artifact_writer_sha256',
        'codex_processes_requested','provider_credentials_supplied','verdict'
    )
    $trustPath=Join-Path $transitionRoot 'trust-record.json'
    $trustRecord=Write-C6PlanOwnedJson -Path $trustPath -Value $trustValue `
        -ExpectedKeys $trustKeys -MaxBytes 65536
    Assert-C6PlanOwnedMembership -Root $transitionRoot -ExpectedNames @(
        'checkout-manifest.json','trust-record.json'
    )

    $transitionPrefix='kokoroarc-c6-task09-transition-'
    $transitionId=(
        [IO.Path]::GetFileName($transitionRoot).Substring(
            $transitionPrefix.Length
        )
    )
    $transitionValue=[ordered]@{
        schema_version='complete-suite-task9-transition-v3'
        transition_id=$transitionId
        trust_record_path=$trustPath
        trust_record_sha256=$trustRecord.sha256
        checkout_manifest_path=$manifestPath
        checkout_manifest_sha256=$manifestRecord.sha256
        task9_commit=[string]$Task9TransitionInputs.task9_commit
        task9_tree=[string]$Task9TransitionInputs.task9_tree
        post_trust_selection_registry_sha256=(
            [string]$Task9TransitionInputs.post_trust_selection_registry_sha256
        )
        host_constructor_implementation_sha256=(
            [string]$Task9TransitionInputs.host_constructor_implementation_sha256
        )
        broker_constructor_implementation_sha256=(
            [string]$Task9TransitionInputs.broker_constructor_implementation_sha256
        )
        constructor_implementation_set_sha256=(
            [string]$Task9TransitionInputs.constructor_implementation_set_sha256
        )
        constructor_attribute_set_sha256=(
            [string]$Task9TransitionInputs.constructor_attribute_set_sha256
        )
        job_topology_sha256=(
            [string]$Task9TransitionInputs.job_topology_sha256
        )
        artifact_tty_contract_sha256=(
            [string]$Task9TransitionInputs.artifact_tty_contract_sha256
        )
        artifact_oracle_sha256=[string]$Task9TransitionInputs.artifact_oracle_sha256
        artifact_oracle_review_result_sha256=(
            [string]$Task9TransitionInputs.artifact_oracle_review_result_sha256
        )
        artifact_oracle_digest_count=(
            [long]$Task9TransitionInputs.artifact_oracle_digest_count
        )
        predecessor_repository_code_loaded=$false
        codex_processes_requested=0
        provider_credentials_supplied=$false
        fresh_successor_required=$true
        verdict='pass'
    }
    $transitionKeys=@(
        'schema_version','transition_id','trust_record_path',
        'trust_record_sha256','checkout_manifest_path',
        'checkout_manifest_sha256','task9_commit','task9_tree',
        'post_trust_selection_registry_sha256',
        'host_constructor_implementation_sha256',
        'broker_constructor_implementation_sha256',
        'constructor_implementation_set_sha256',
        'constructor_attribute_set_sha256',
        'job_topology_sha256','artifact_tty_contract_sha256',
        'artifact_oracle_sha256','artifact_oracle_review_result_sha256',
        'artifact_oracle_digest_count',
        'predecessor_repository_code_loaded','codex_processes_requested',
        'provider_credentials_supplied','fresh_successor_required','verdict'
    )
    $transitionPath=Join-Path $transitionRoot 'transition-record.json'
    $transitionRecord=Write-C6PlanOwnedJson -Path $transitionPath `
        -Value $transitionValue -ExpectedKeys $transitionKeys -MaxBytes 65536
    Assert-C6PlanOwnedMembership -Root $transitionRoot -ExpectedNames @(
        'checkout-manifest.json','trust-record.json','transition-record.json'
    )

    $receiptValue=[ordered]@{
        schema_version='complete-suite-task9-bootstrap-receipt-v2'
        plan_commit=[string]$Task9TransitionInputs.plan_commit
        plan_sha256=[string]$Task9TransitionInputs.plan_sha256
        task9_commit=[string]$Task9TransitionInputs.task9_commit
        task9_tree=[string]$Task9TransitionInputs.task9_tree
        post_trust_selection_registry_sha256=(
            [string]$Task9TransitionInputs.post_trust_selection_registry_sha256
        )
        host_constructor_implementation_sha256=(
            [string]$Task9TransitionInputs.host_constructor_implementation_sha256
        )
        broker_constructor_implementation_sha256=(
            [string]$Task9TransitionInputs.broker_constructor_implementation_sha256
        )
        constructor_implementation_set_sha256=(
            [string]$Task9TransitionInputs.constructor_implementation_set_sha256
        )
        constructor_attribute_set_sha256=(
            [string]$Task9TransitionInputs.constructor_attribute_set_sha256
        )
        job_topology_sha256=(
            [string]$Task9TransitionInputs.job_topology_sha256
        )
        artifact_tty_contract_sha256=(
            [string]$Task9TransitionInputs.artifact_tty_contract_sha256
        )
        artifact_oracle_path=[string]$Task9TransitionInputs.artifact_oracle_path
        artifact_oracle_commit=[string]$Task9TransitionInputs.artifact_oracle_commit
        artifact_oracle_tree=[string]$Task9TransitionInputs.artifact_oracle_tree
        artifact_oracle_blob=[string]$Task9TransitionInputs.artifact_oracle_blob
        artifact_oracle_size=[long]$Task9TransitionInputs.artifact_oracle_size
        artifact_oracle_sha256=[string]$Task9TransitionInputs.artifact_oracle_sha256
        artifact_oracle_review_result_sha256=(
            [string]$Task9TransitionInputs.artifact_oracle_review_result_sha256
        )
        artifact_oracle_digest_count=(
            [long]$Task9TransitionInputs.artifact_oracle_digest_count
        )
        checkout_root=$checkoutRoot
        trust_record_path=$trustPath
        trust_record_sha256=$trustRecord.sha256
        transition_record_path=$transitionPath
        transition_record_sha256=$transitionRecord.sha256
        checkout_manifest_path=$manifestPath
        checkout_manifest_sha256=$manifestRecord.sha256
        zero_codex_envelope_path=$zeroPath
        zero_codex_envelope_sha256=$zeroRecord.sha256
        control_plane_path=$controlPath
        control_plane_sha256=$controlEntry.sha256
        python_bootstrap_path=$bootstrapPath
        python_bootstrap_sha256=$bootstrapEntry.sha256
        artifact_launcher_path=$launcherPath
        artifact_launcher_size=[long]$launcherEntry.size
        artifact_launcher_sha256=$launcherEntry.sha256
        artifact_writer_path=$writerPath
        artifact_writer_size=[long]$writerEntry.size
        artifact_writer_sha256=$writerEntry.sha256
    }
    $receiptKeys=@(
        'schema_version','plan_commit','plan_sha256','task9_commit','task9_tree',
        'post_trust_selection_registry_sha256',
        'host_constructor_implementation_sha256',
        'broker_constructor_implementation_sha256',
        'constructor_implementation_set_sha256',
        'constructor_attribute_set_sha256',
        'job_topology_sha256','artifact_tty_contract_sha256',
        'artifact_oracle_path','artifact_oracle_commit','artifact_oracle_tree',
        'artifact_oracle_blob','artifact_oracle_size','artifact_oracle_sha256',
        'artifact_oracle_review_result_sha256','artifact_oracle_digest_count',
        'checkout_root','trust_record_path','trust_record_sha256',
        'transition_record_path','transition_record_sha256',
        'checkout_manifest_path','checkout_manifest_sha256',
        'zero_codex_envelope_path','zero_codex_envelope_sha256',
        'control_plane_path','control_plane_sha256','python_bootstrap_path',
        'python_bootstrap_sha256','artifact_launcher_path',
        'artifact_launcher_size','artifact_launcher_sha256','artifact_writer_path',
        'artifact_writer_size','artifact_writer_sha256'
    )
    $receiptPath=Join-Path $transitionRoot 'bootstrap-receipt.json'
    $receiptRecord=Write-C6PlanOwnedJson -Path $receiptPath `
        -Value $receiptValue -ExpectedKeys $receiptKeys -MaxBytes 65536
    Assert-C6PlanOwnedMembership -Root $transitionRoot -ExpectedNames @(
        'bootstrap-receipt.json','checkout-manifest.json',
        'transition-record.json','trust-record.json'
    )
    return [ordered]@{
        zero_codex_envelope_path=$zeroRecord.path
        zero_codex_envelope_sha256=$zeroRecord.sha256
        checkout_manifest_path=$manifestRecord.path
        checkout_manifest_sha256=$manifestRecord.sha256
        trust_record_path=$trustRecord.path
        trust_record_sha256=$trustRecord.sha256
        transition_record_path=$transitionRecord.path
        transition_record_sha256=$transitionRecord.sha256
        bootstrap_receipt_path=$receiptRecord.path
        bootstrap_receipt_sha256=$receiptRecord.sha256
        native_vector_bindings=[object[]](
            $script:C6Task9ProducerNativeVectorBindings.ToArray()
        )
    }
    } finally {
        try { Confirm-C6PlanOwnedHeldJson -Held $oracleHeldForWrite } finally {
            $oracleHeldForWrite.opened.Dispose()
        }
    }
}

$Task9TransitionInputs=Get-C6Task9TransitionInputs `
    -HandoffPath $HandoffPath `
    -ExpectedHandoffSha256 $ExpectedHandoffSha256 `
    -ExpectedTask8Commit $ExpectedTask8Commit `
    -ExpectedTask9Commit $ExpectedTask9Commit `
    -CheckoutRoot $CheckoutRoot `
    -ArtifactOracleHandoffPath $ArtifactOracleHandoffPath `
    -ExpectedArtifactOracleHandoffSha256 `
        $ExpectedArtifactOracleHandoffSha256 `
    -ArtifactOracleCheckoutRoot $ArtifactOracleCheckoutRoot
$task9TransitionArtifacts=Write-C6Task9TransitionArtifacts `
    -Task9TransitionInputs $Task9TransitionInputs
ConvertTo-Json -InputObject $task9TransitionArtifacts -Compress -Depth 5
