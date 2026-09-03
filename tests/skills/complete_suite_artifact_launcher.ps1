$ErrorActionPreference='Stop'
$script:C6ArtifactLauncherRevision='complete-suite-artifact-launcher-v1'
$script:C6ArtifactPythonPath='C:\Python314\python.exe'
$script:C6ArtifactPythonArguments=[string[]]@('-I','-S','-B','-X','utf8')
$script:C6ArtifactChildEnvironment=[ordered]@{
    SYSTEMROOT='C:\Windows'
    WINDIR='C:\Windows'
}
$script:C6ArtifactRequestCapBytes=524288
$script:C6ArtifactOutputCapBytes=65536
$script:C6ArtifactDeadlineMilliseconds=120000
$script:C6ArtifactTerminationGraceMilliseconds=5000
$script:C6ArtifactFrameHeaderCharacters=94
$script:C6ArtifactFramePayloadCapCharacters=699052
$script:C6ArtifactFrameTotalCapCharacters=699146
$script:C6ArtifactNativeVectorCapUtf16Units=30000

# C6_ARTIFACT_FRAME_HEADER_VALIDATION_BEGIN
if ($null -eq $script:C6ArtifactFrameHeaderText -or
    $script:C6ArtifactFrameHeaderText.Length -ne
        $script:C6ArtifactFrameHeaderCharacters) {
    throw 'artifact frame invalid'
}
$c6ArtifactFrameHeader=$script:C6ArtifactFrameHeaderText
for ($c6ArtifactIndex=0;
     $c6ArtifactIndex -lt $c6ArtifactFrameHeader.Length;
     $c6ArtifactIndex++) {
    $c6ArtifactCode=[int][char]$c6ArtifactFrameHeader[$c6ArtifactIndex]
    if ($c6ArtifactCode -lt 33 -or $c6ArtifactCode -gt 126) {
        throw 'artifact frame invalid'
    }
}
if (-not $c6ArtifactFrameHeader.StartsWith(
        'C6ARF1:',[StringComparison]::Ordinal) -or
    $c6ArtifactFrameHeader[14] -ne ':' -or
    $c6ArtifactFrameHeader[21] -ne ':' -or
    $c6ArtifactFrameHeader[28] -ne ':' -or
    $c6ArtifactFrameHeader[93] -ne ':') {
    throw 'artifact frame invalid'
}
[int]$c6ArtifactFrameTotalCharacters=0
for ($c6ArtifactIndex=7; $c6ArtifactIndex -lt 14; $c6ArtifactIndex++) {
    $c6ArtifactDigit=[int][char]$c6ArtifactFrameHeader[$c6ArtifactIndex]-48
    if ($c6ArtifactDigit -lt 0 -or $c6ArtifactDigit -gt 9) {
        throw 'artifact frame invalid'
    }
    $c6ArtifactFrameTotalCharacters=
        (10*$c6ArtifactFrameTotalCharacters)+$c6ArtifactDigit
}
[int]$c6ArtifactFrameRequestBytes=0
for ($c6ArtifactIndex=15; $c6ArtifactIndex -lt 21; $c6ArtifactIndex++) {
    $c6ArtifactDigit=[int][char]$c6ArtifactFrameHeader[$c6ArtifactIndex]-48
    if ($c6ArtifactDigit -lt 0 -or $c6ArtifactDigit -gt 9) {
        throw 'artifact frame invalid'
    }
    $c6ArtifactFrameRequestBytes=
        (10*$c6ArtifactFrameRequestBytes)+$c6ArtifactDigit
}
[int]$c6ArtifactFramePayloadCharacters=0
for ($c6ArtifactIndex=22; $c6ArtifactIndex -lt 28; $c6ArtifactIndex++) {
    $c6ArtifactDigit=[int][char]$c6ArtifactFrameHeader[$c6ArtifactIndex]-48
    if ($c6ArtifactDigit -lt 0 -or $c6ArtifactDigit -gt 9) {
        throw 'artifact frame invalid'
    }
    $c6ArtifactFramePayloadCharacters=
        (10*$c6ArtifactFramePayloadCharacters)+$c6ArtifactDigit
}
$c6ArtifactFrameRequestSha256=$c6ArtifactFrameHeader.Substring(29,64)
for ($c6ArtifactIndex=0;
     $c6ArtifactIndex -lt $c6ArtifactFrameRequestSha256.Length;
     $c6ArtifactIndex++) {
    $c6ArtifactCode=[int][char]$c6ArtifactFrameRequestSha256[$c6ArtifactIndex]
    if (-not (($c6ArtifactCode -ge 48 -and $c6ArtifactCode -le 57) -or
              ($c6ArtifactCode -ge 97 -and $c6ArtifactCode -le 102))) {
        throw 'artifact frame invalid'
    }
}
$c6ArtifactExpectedPayloadCharacters=
    4*[int][Math]::Ceiling($c6ArtifactFrameRequestBytes/3.0)
if ($c6ArtifactFrameRequestBytes -lt 2 -or
    $c6ArtifactFrameRequestBytes -gt $script:C6ArtifactRequestCapBytes -or
    $c6ArtifactFramePayloadCharacters -ne
        $c6ArtifactExpectedPayloadCharacters -or
    $c6ArtifactFramePayloadCharacters -gt
        $script:C6ArtifactFramePayloadCapCharacters -or
    $c6ArtifactFrameTotalCharacters -ne
        ($script:C6ArtifactFrameHeaderCharacters+
         $c6ArtifactFramePayloadCharacters) -or
    $c6ArtifactFrameTotalCharacters -gt
        $script:C6ArtifactFrameTotalCapCharacters) {
    throw 'artifact frame invalid'
}
$script:C6ArtifactFrameTotalCharacters=$c6ArtifactFrameTotalCharacters
$script:C6ArtifactFrameRequestBytes=$c6ArtifactFrameRequestBytes
$script:C6ArtifactFramePayloadCharacters=$c6ArtifactFramePayloadCharacters
$script:C6ArtifactFrameRequestSha256=$c6ArtifactFrameRequestSha256
$script:C6ArtifactFrameHeaderValidated=$true
# C6_ARTIFACT_FRAME_HEADER_VALIDATION_END

# C6_ARTIFACT_FRAME_PAYLOAD_ALLOCATION_BEGIN
$script:C6ArtifactPayloadCharacters=[char[]]::new($script:C6ArtifactFramePayloadCharacters)
# C6_ARTIFACT_FRAME_PAYLOAD_ALLOCATION_END

# C6_ARTIFACT_FRAME_PAYLOAD_VALIDATION_BEGIN
if ($script:C6ArtifactFrameHeaderValidated -ne $true -or
    $null -eq $script:C6ArtifactFramePayloadText -or
    $script:C6ArtifactPayloadCharacters.Length -ne
        $script:C6ArtifactFramePayloadCharacters -or
    $script:C6ArtifactFramePayloadText.Length -ne
        $script:C6ArtifactFramePayloadCharacters) {
    throw 'artifact frame invalid'
}
$c6ArtifactFramePayloadText=$script:C6ArtifactFramePayloadText
try {
    [byte[]]$c6ArtifactRequestBytes=
        [Convert]::FromBase64String($c6ArtifactFramePayloadText)
} catch {
    throw 'artifact frame invalid'
}
if ([Convert]::ToBase64String($c6ArtifactRequestBytes) -cne
        $c6ArtifactFramePayloadText -or
    $c6ArtifactRequestBytes.Length -ne $script:C6ArtifactFrameRequestBytes) {
    throw 'artifact frame invalid'
}
$c6ArtifactRequestSha256=[Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($c6ArtifactRequestBytes)
).ToLowerInvariant()
if ($c6ArtifactRequestSha256 -cne $script:C6ArtifactFrameRequestSha256) {
    throw 'artifact frame invalid'
}
for ($c6ArtifactIndex=0;
     $c6ArtifactIndex -lt $c6ArtifactRequestBytes.Length;
     $c6ArtifactIndex++) {
    $c6ArtifactByte=[int]$c6ArtifactRequestBytes[$c6ArtifactIndex]
    if ($c6ArtifactByte -gt 127 -or
        $c6ArtifactByte -eq 0 -or
        $c6ArtifactByte -eq 13 -or
        ($c6ArtifactByte -eq 10 -and
         $c6ArtifactIndex -ne ($c6ArtifactRequestBytes.Length-1))) {
        throw 'artifact frame invalid'
    }
}
if ($c6ArtifactRequestBytes[$c6ArtifactRequestBytes.Length-1] -ne 10) {
    throw 'artifact frame invalid'
}
$c6ArtifactStrictUtf8=[Text.UTF8Encoding]::new($false,$true)
try {
    $c6ArtifactRequestText=$c6ArtifactStrictUtf8.GetString(
        $c6ArtifactRequestBytes
    )
    [byte[]]$c6ArtifactRoundTripBytes=
        $c6ArtifactStrictUtf8.GetBytes($c6ArtifactRequestText)
} catch {
    throw 'artifact frame invalid'
}
if ($c6ArtifactRoundTripBytes.Length -ne $c6ArtifactRequestBytes.Length) {
    throw 'artifact frame invalid'
}
for ($c6ArtifactIndex=0;
     $c6ArtifactIndex -lt $c6ArtifactRequestBytes.Length;
     $c6ArtifactIndex++) {
    if ($c6ArtifactRoundTripBytes[$c6ArtifactIndex] -ne
            $c6ArtifactRequestBytes[$c6ArtifactIndex]) {
        throw 'artifact frame invalid'
    }
}
$c6ArtifactJsonText=$c6ArtifactRequestText.Substring(
    0,$c6ArtifactRequestText.Length-1
)
$c6ArtifactJsonOptions=[Text.Json.JsonDocumentOptions]::new()
$c6ArtifactJsonOptions.AllowTrailingCommas=$false
$c6ArtifactJsonOptions.CommentHandling=[Text.Json.JsonCommentHandling]::Disallow
$c6ArtifactJsonOptions.MaxDepth=32
$c6ArtifactJsonDocument=$null
try {
    $c6ArtifactJsonDocument=[Text.Json.JsonDocument]::Parse(
        $c6ArtifactJsonText,$c6ArtifactJsonOptions
    )
} catch {
    throw 'artifact frame invalid'
}
try {
    if ($c6ArtifactJsonDocument.RootElement.ValueKind -ne
            [Text.Json.JsonValueKind]::Object -or
        $c6ArtifactJsonDocument.RootElement.GetRawText() -cne
            $c6ArtifactJsonText) {
        throw 'artifact frame invalid'
    }
    $c6ArtifactPropertyNames=
        [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $c6ArtifactPropertyEnumerator=
        $c6ArtifactJsonDocument.RootElement.EnumerateObject()
    while ($c6ArtifactPropertyEnumerator.MoveNext()) {
        if (-not $c6ArtifactPropertyNames.Add(
                $c6ArtifactPropertyEnumerator.Current.Name)) {
            throw 'artifact frame invalid'
        }
    }
} finally {
    $c6ArtifactJsonDocument.Dispose()
}
$script:C6ArtifactValidatedRequestBytes=$c6ArtifactRequestBytes
$script:C6ArtifactValidatedRequestSha256=$c6ArtifactRequestSha256
$script:C6ArtifactFrameValidated=$true
# C6_ARTIFACT_FRAME_PAYLOAD_VALIDATION_END

if ($script:C6ArtifactFrameValidated -ne $true -or
    $null -eq $script:C6ArtifactAuthenticatedWriterPath -or
    $script:C6ArtifactAuthenticatedWriterPath -isnot [string] -or
    $null -eq $script:C6ArtifactAuthenticatedCheckoutPath -or
    $script:C6ArtifactAuthenticatedCheckoutPath -isnot [string] -or
    $null -eq $script:C6ArtifactValidatedExpectedOutputPath -or
    $script:C6ArtifactValidatedExpectedOutputPath -isnot [string] -or
    -not [IO.Path]::IsPathFullyQualified(
        $script:C6ArtifactAuthenticatedWriterPath
    ) -or
    -not [IO.Path]::IsPathFullyQualified(
        $script:C6ArtifactAuthenticatedCheckoutPath
    ) -or
    -not [IO.Path]::IsPathFullyQualified(
        $script:C6ArtifactValidatedExpectedOutputPath
    )) {
    throw 'artifact child authority invalid'
}
$script:C6ArtifactNativeExecutable=$script:C6ArtifactPythonPath
$script:C6ArtifactNativeArguments=[object[]]@(
    '-I'
    '-S'
    '-B'
    '-X'
    'utf8'
    $script:C6ArtifactAuthenticatedWriterPath
    '--expected-request-sha256'
    $script:C6ArtifactValidatedRequestSha256
)
# C6_ARTIFACT_NATIVE_VECTOR_VALIDATION_BEGIN
$script:C6ArtifactNativeVectorValidated=$false
try {
    if ($null -eq $script:C6ArtifactNativeExecutable -or
        $script:C6ArtifactNativeExecutable -isnot [string] -or
        $null -eq $script:C6ArtifactNativeArguments -or
        $script:C6ArtifactNativeArguments -isnot [object[]]) {
        throw 'artifact native vector invalid'
    }
    $c6ArtifactNativeEvidence=[Collections.Generic.List[object]]::new()
    [void]$c6ArtifactNativeEvidence.Add(
        $script:C6ArtifactNativeExecutable
    )
    foreach ($c6ArtifactNativeArgumentEvidence in
             [object[]]$script:C6ArtifactNativeArguments) {
        [void]$c6ArtifactNativeEvidence.Add(
            $c6ArtifactNativeArgumentEvidence
        )
    }
    $c6ArtifactValidatedNativeValues=
        [Collections.Generic.List[string]]::new()
    foreach ($c6ArtifactNativeValueEvidence in $c6ArtifactNativeEvidence) {
        if ($null -eq $c6ArtifactNativeValueEvidence -or
            $c6ArtifactNativeValueEvidence -isnot [string]) {
            throw 'artifact native vector invalid'
        }
        [string]$c6ArtifactNativeText=$c6ArtifactNativeValueEvidence
        for ($c6ArtifactNativeIndex=0;
             $c6ArtifactNativeIndex -lt $c6ArtifactNativeText.Length;
             $c6ArtifactNativeIndex++) {
            $c6ArtifactNativeCharacter=
                $c6ArtifactNativeText[$c6ArtifactNativeIndex]
            if ($c6ArtifactNativeCharacter -eq [char]0) {
                throw 'artifact native vector invalid'
            }
            if ([char]::IsHighSurrogate($c6ArtifactNativeCharacter)) {
                if ($c6ArtifactNativeIndex+1 -ge
                        $c6ArtifactNativeText.Length -or
                    -not [char]::IsLowSurrogate(
                        $c6ArtifactNativeText[$c6ArtifactNativeIndex+1]
                    )) {
                    throw 'artifact native vector invalid'
                }
                $c6ArtifactNativeIndex++
            } elseif ([char]::IsLowSurrogate($c6ArtifactNativeCharacter)) {
                throw 'artifact native vector invalid'
            }
        }
        [void]$c6ArtifactValidatedNativeValues.Add($c6ArtifactNativeText)
    }
    $c6ArtifactValidatedNativeExecutable=
        $c6ArtifactValidatedNativeValues[0]
    if ($c6ArtifactValidatedNativeExecutable.Length -eq 0 -or
        -not [IO.Path]::IsPathFullyQualified(
            $c6ArtifactValidatedNativeExecutable
        )) {
        throw 'artifact native vector invalid'
    }
    $c6ArtifactValidatedNativeArguments=[string[]]::new(
        $c6ArtifactValidatedNativeValues.Count-1
    )
    for ($c6ArtifactNativeIndex=1;
         $c6ArtifactNativeIndex -lt $c6ArtifactValidatedNativeValues.Count;
         $c6ArtifactNativeIndex++) {
        $c6ArtifactValidatedNativeArguments[$c6ArtifactNativeIndex-1]=
            $c6ArtifactValidatedNativeValues[$c6ArtifactNativeIndex]
    }
    $c6ArtifactSerializedNativeValues=
        [Collections.Generic.List[string]]::new()
    foreach ($c6ArtifactNativeText in $c6ArtifactValidatedNativeValues) {
        $c6ArtifactNativeRequiresQuotes=($c6ArtifactNativeText.Length -eq 0)
        if (-not $c6ArtifactNativeRequiresQuotes) {
            for ($c6ArtifactNativeIndex=0;
                 $c6ArtifactNativeIndex -lt $c6ArtifactNativeText.Length;
                 $c6ArtifactNativeIndex++) {
                $c6ArtifactNativeCharacter=
                    $c6ArtifactNativeText[$c6ArtifactNativeIndex]
                if ($c6ArtifactNativeCharacter -eq '"' -or
                    $c6ArtifactNativeCharacter -eq ' ' -or
                    $c6ArtifactNativeCharacter -eq [char]9) {
                    $c6ArtifactNativeRequiresQuotes=$true
                    break
                }
            }
        }
        if (-not $c6ArtifactNativeRequiresQuotes) {
            [void]$c6ArtifactSerializedNativeValues.Add(
                $c6ArtifactNativeText
            )
            continue
        }
        $c6ArtifactNativeBuilder=[Text.StringBuilder]::new()
        [void]$c6ArtifactNativeBuilder.Append('"')
        $c6ArtifactNativeBackslashes=0
        for ($c6ArtifactNativeIndex=0;
             $c6ArtifactNativeIndex -lt $c6ArtifactNativeText.Length;
             $c6ArtifactNativeIndex++) {
            $c6ArtifactNativeCharacter=
                $c6ArtifactNativeText[$c6ArtifactNativeIndex]
            if ($c6ArtifactNativeCharacter -eq '\') {
                $c6ArtifactNativeBackslashes++
                continue
            }
            if ($c6ArtifactNativeCharacter -eq '"') {
                if ($c6ArtifactNativeBackslashes -gt 0) {
                    [void]$c6ArtifactNativeBuilder.Append(
                        ('\'*(2*$c6ArtifactNativeBackslashes))
                    )
                }
                [void]$c6ArtifactNativeBuilder.Append('\')
                [void]$c6ArtifactNativeBuilder.Append('"')
                $c6ArtifactNativeBackslashes=0
                continue
            }
            if ($c6ArtifactNativeBackslashes -gt 0) {
                [void]$c6ArtifactNativeBuilder.Append(
                    ('\'*$c6ArtifactNativeBackslashes)
                )
                $c6ArtifactNativeBackslashes=0
            }
            [void]$c6ArtifactNativeBuilder.Append(
                $c6ArtifactNativeCharacter
            )
        }
        if ($c6ArtifactNativeBackslashes -gt 0) {
            [void]$c6ArtifactNativeBuilder.Append(
                ('\'*(2*$c6ArtifactNativeBackslashes))
            )
        }
        [void]$c6ArtifactNativeBuilder.Append('"')
        [void]$c6ArtifactSerializedNativeValues.Add(
            $c6ArtifactNativeBuilder.ToString()
        )
    }
    $c6ArtifactNativeCommandLine=[string]::Join(
        ' ',$c6ArtifactSerializedNativeValues
    )
    [long]$c6ArtifactNativeUtf16Units=
        $c6ArtifactNativeCommandLine.Length+1
    if ($c6ArtifactNativeUtf16Units -gt
            $script:C6ArtifactNativeVectorCapUtf16Units) {
        throw 'artifact native vector invalid'
    }
    [byte[]]$c6ArtifactNativeUtf16LeBytes=
        [Text.Encoding]::Unicode.GetBytes(
            $c6ArtifactNativeCommandLine+[char]0
        )
    if ($c6ArtifactNativeUtf16LeBytes.Length -ne
            2*$c6ArtifactNativeUtf16Units) {
        throw 'artifact native vector invalid'
    }
    $c6ArtifactNativeUtf16LeSha256=[Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData(
            $c6ArtifactNativeUtf16LeBytes
        )
    ).ToLowerInvariant()
    $script:C6ArtifactValidatedNativeExecutable=
        $c6ArtifactValidatedNativeExecutable
    $script:C6ArtifactValidatedNativeArguments=
        $c6ArtifactValidatedNativeArguments
    $script:C6ArtifactNativeVectorContract=
        'complete-suite-windows-native-vector-v1'
    $script:C6ArtifactNativeVectorUtf16Units=
        $c6ArtifactNativeUtf16Units
    $script:C6ArtifactNativeVectorUtf16LeSha256=
        $c6ArtifactNativeUtf16LeSha256
    $script:C6ArtifactNativeVectorValidated=$true
} catch {
    throw 'artifact native vector invalid'
}
# C6_ARTIFACT_NATIVE_VECTOR_VALIDATION_END

# C6_ARTIFACT_CHILD_LIFECYCLE_BEGIN
$c6ArtifactChildFailed=$true
$c6ArtifactChildTerminationFailed=$false
$c6ArtifactProcess=$null
$c6ArtifactStdoutMemory=$null
$c6ArtifactStderrMemory=$null
try {
    if ($script:C6ArtifactFrameValidated -ne $true -or
        $script:C6ArtifactNativeVectorValidated -ne $true -or
        $script:C6ArtifactValidatedNativeExecutable -isnot [string] -or
        $script:C6ArtifactValidatedNativeExecutable -cne
            $script:C6ArtifactPythonPath -or
        $script:C6ArtifactValidatedNativeArguments -isnot [string[]] -or
        $script:C6ArtifactValidatedNativeArguments.Length -ne 8 -or
        $script:C6ArtifactValidatedRequestBytes -isnot [byte[]] -or
        $script:C6ArtifactValidatedRequestSha256 -isnot [string] -or
        $script:C6ArtifactAuthenticatedWriterPath -isnot [string] -or
        $script:C6ArtifactAuthenticatedCheckoutPath -isnot [string] -or
        $script:C6ArtifactValidatedExpectedOutputPath -isnot [string] -or
        $script:C6ArtifactDeadlineStopwatch -isnot
            [System.Diagnostics.Stopwatch] -or
        -not $script:C6ArtifactDeadlineStopwatch.IsRunning -or
        $script:C6ArtifactDeadlineMilliseconds -lt 1 -or
        $script:C6ArtifactDeadlineMilliseconds -gt 120000 -or
        $script:C6ArtifactOutputCapBytes -ne 65536 -or
        $script:C6ArtifactTerminationGraceMilliseconds -ne 5000 -or
        -not [IO.Path]::IsPathFullyQualified(
            $script:C6ArtifactAuthenticatedWriterPath
        ) -or
        -not [IO.Path]::IsPathFullyQualified(
            $script:C6ArtifactAuthenticatedCheckoutPath
        ) -or
        -not [IO.Path]::IsPathFullyQualified(
            $script:C6ArtifactValidatedExpectedOutputPath
        )) {
        throw 'artifact child failed'
    }
    if ($script:C6ArtifactValidatedNativeArguments[0] -cne '-I' -or
        $script:C6ArtifactValidatedNativeArguments[1] -cne '-S' -or
        $script:C6ArtifactValidatedNativeArguments[2] -cne '-B' -or
        $script:C6ArtifactValidatedNativeArguments[3] -cne '-X' -or
        $script:C6ArtifactValidatedNativeArguments[4] -cne 'utf8' -or
        $script:C6ArtifactValidatedNativeArguments[5] -cne
            $script:C6ArtifactAuthenticatedWriterPath -or
        $script:C6ArtifactValidatedNativeArguments[6] -cne
            '--expected-request-sha256' -or
        $script:C6ArtifactValidatedNativeArguments[7] -cne
            $script:C6ArtifactValidatedRequestSha256) {
        throw 'artifact child failed'
    }
    $c6ArtifactChildRequestSha256=[Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData(
            $script:C6ArtifactValidatedRequestBytes
        )
    ).ToLowerInvariant()
    if ($c6ArtifactChildRequestSha256 -cne
            $script:C6ArtifactValidatedRequestSha256 -or
        $script:C6ArtifactDeadlineStopwatch.ElapsedMilliseconds -ge
            $script:C6ArtifactDeadlineMilliseconds) {
        throw 'artifact child failed'
    }
    for ($c6ArtifactChildIndex=0;
         $c6ArtifactChildIndex -lt
            $script:C6ArtifactValidatedExpectedOutputPath.Length;
         $c6ArtifactChildIndex++) {
        $c6ArtifactChildCharacter=
            $script:C6ArtifactValidatedExpectedOutputPath[
                $c6ArtifactChildIndex
            ]
        if ($c6ArtifactChildCharacter -eq [char]0 -or
            $c6ArtifactChildCharacter -eq [char]10 -or
            $c6ArtifactChildCharacter -eq [char]13) {
            throw 'artifact child failed'
        }
        if ([char]::IsHighSurrogate($c6ArtifactChildCharacter)) {
            if ($c6ArtifactChildIndex+1 -ge
                    $script:C6ArtifactValidatedExpectedOutputPath.Length -or
                -not [char]::IsLowSurrogate(
                    $script:C6ArtifactValidatedExpectedOutputPath[
                        $c6ArtifactChildIndex+1
                    ]
                )) {
                throw 'artifact child failed'
            }
            $c6ArtifactChildIndex++
        } elseif ([char]::IsLowSurrogate($c6ArtifactChildCharacter)) {
            throw 'artifact child failed'
        }
    }
    # C6_ARTIFACT_PROCESS_START_INFO_ALLOCATION_BEGIN
    $c6ArtifactStartInfo=
        [System.Diagnostics.ProcessStartInfo]::new()
    # C6_ARTIFACT_PROCESS_START_INFO_ALLOCATION_END
    $c6ArtifactStartInfo.FileName=$script:C6ArtifactValidatedNativeExecutable
    $c6ArtifactStartInfo.WorkingDirectory=
        $script:C6ArtifactAuthenticatedCheckoutPath
    $c6ArtifactStartInfo.UseShellExecute=$false
    $c6ArtifactStartInfo.RedirectStandardInput=$true
    $c6ArtifactStartInfo.RedirectStandardOutput=$true
    $c6ArtifactStartInfo.RedirectStandardError=$true
    $c6ArtifactStartInfo.Environment.Clear()
    $c6ArtifactStartInfo.Environment.Add('SYSTEMROOT','C:\Windows')
    $c6ArtifactStartInfo.Environment.Add('WINDIR','C:\Windows')
    foreach ($c6ArtifactValidatedNativeArgument in
             $script:C6ArtifactValidatedNativeArguments) {
        [void]$c6ArtifactStartInfo.ArgumentList.Add(
            $c6ArtifactValidatedNativeArgument
        )
    }
    if ($c6ArtifactStartInfo.Environment.Count -ne 2 -or
        -not $c6ArtifactStartInfo.Environment.ContainsKey('SYSTEMROOT') -or
        -not $c6ArtifactStartInfo.Environment.ContainsKey('WINDIR') -or
        $c6ArtifactStartInfo.Environment['SYSTEMROOT'] -cne 'C:\Windows' -or
        $c6ArtifactStartInfo.Environment['WINDIR'] -cne 'C:\Windows' -or
        $c6ArtifactStartInfo.ArgumentList.Count -ne
            $script:C6ArtifactValidatedNativeArguments.Length) {
        throw 'artifact child failed'
    }
    for ($c6ArtifactChildIndex=0;
         $c6ArtifactChildIndex -lt $c6ArtifactStartInfo.ArgumentList.Count;
         $c6ArtifactChildIndex++) {
        if ($c6ArtifactStartInfo.ArgumentList[$c6ArtifactChildIndex] -cne
                $script:C6ArtifactValidatedNativeArguments[
                    $c6ArtifactChildIndex
                ]) {
            throw 'artifact child failed'
        }
    }
    $c6ArtifactProcess=[System.Diagnostics.Process]::Start(
        $c6ArtifactStartInfo
    )
    if ($null -eq $c6ArtifactProcess) {
        throw 'artifact child failed'
    }
    $c6ArtifactStdoutMemory=[IO.MemoryStream]::new()
    $c6ArtifactStderrMemory=[IO.MemoryStream]::new()
    $c6ArtifactStdoutBuffer=[byte[]]::new(8192)
    $c6ArtifactStderrBuffer=[byte[]]::new(8192)
    $c6ArtifactStdoutStream=
        $c6ArtifactProcess.StandardOutput.BaseStream
    $c6ArtifactStderrStream=
        $c6ArtifactProcess.StandardError.BaseStream
    $c6ArtifactStdinStream=
        $c6ArtifactProcess.StandardInput.BaseStream
    $c6ArtifactStdoutEof=$false
    $c6ArtifactStderrEof=$false
    $c6ArtifactStdoutTask=
        $c6ArtifactProcess.StandardOutput.BaseStream.ReadAsync(
        $c6ArtifactStdoutBuffer,0,$c6ArtifactStdoutBuffer.Length
    )
    $c6ArtifactStderrTask=
        $c6ArtifactProcess.StandardError.BaseStream.ReadAsync(
        $c6ArtifactStderrBuffer,0,$c6ArtifactStderrBuffer.Length
    )
    $c6ArtifactStdinTask=
        $c6ArtifactProcess.StandardInput.BaseStream.WriteAsync(
            $script:C6ArtifactValidatedRequestBytes,
            0,
            $script:C6ArtifactValidatedRequestBytes.Length
        )
    while ($null -ne $c6ArtifactStdinTask -or
           -not $c6ArtifactStdoutEof -or
           -not $c6ArtifactStderrEof) {
        $c6ArtifactOutstandingTasks=
            [Collections.Generic.List[Threading.Tasks.Task]]::new()
        if ($null -ne $c6ArtifactStdinTask) {
            [void]$c6ArtifactOutstandingTasks.Add($c6ArtifactStdinTask)
        }
        if (-not $c6ArtifactStdoutEof) {
            [void]$c6ArtifactOutstandingTasks.Add($c6ArtifactStdoutTask)
        }
        if (-not $c6ArtifactStderrEof) {
            [void]$c6ArtifactOutstandingTasks.Add($c6ArtifactStderrTask)
        }
        $c6ArtifactRemainingMilliseconds=
            $script:C6ArtifactDeadlineMilliseconds-
            $script:C6ArtifactDeadlineStopwatch.ElapsedMilliseconds
        if ($c6ArtifactRemainingMilliseconds -le 0 -or
            [Threading.Tasks.Task]::WaitAny(
                $c6ArtifactOutstandingTasks.ToArray(),
                [int]$c6ArtifactRemainingMilliseconds
            ) -lt 0) {
            throw 'artifact child failed'
        }
        if ($null -ne $c6ArtifactStdinTask -and
            $c6ArtifactStdinTask.IsCompleted) {
            [void]$c6ArtifactStdinTask.GetAwaiter().GetResult()
            $c6ArtifactProcess.StandardInput.Close()
            $c6ArtifactStdinTask=$null
        }
        if (-not $c6ArtifactStdoutEof -and
            $c6ArtifactStdoutTask.IsCompleted) {
            $c6ArtifactStdoutRead=
                $c6ArtifactStdoutTask.GetAwaiter().GetResult()
            if ($c6ArtifactStdoutRead -eq 0) {
                $c6ArtifactStdoutEof=$true
                $c6ArtifactStdoutTask=$null
            } else {
                if ($c6ArtifactStdoutMemory.Length+$c6ArtifactStdoutRead -gt
                        $script:C6ArtifactOutputCapBytes) {
                    throw 'artifact child failed'
                }
                $c6ArtifactStdoutMemory.Write(
                    $c6ArtifactStdoutBuffer,0,$c6ArtifactStdoutRead
                )
                $c6ArtifactStdoutTask=$c6ArtifactStdoutStream.ReadAsync(
                    $c6ArtifactStdoutBuffer,
                    0,
                    $c6ArtifactStdoutBuffer.Length
                )
            }
        }
        if (-not $c6ArtifactStderrEof -and
            $c6ArtifactStderrTask.IsCompleted) {
            $c6ArtifactStderrRead=
                $c6ArtifactStderrTask.GetAwaiter().GetResult()
            if ($c6ArtifactStderrRead -eq 0) {
                $c6ArtifactStderrEof=$true
                $c6ArtifactStderrTask=$null
            } else {
                if ($c6ArtifactStderrMemory.Length+$c6ArtifactStderrRead -gt
                        $script:C6ArtifactOutputCapBytes) {
                    throw 'artifact child failed'
                }
                $c6ArtifactStderrMemory.Write(
                    $c6ArtifactStderrBuffer,0,$c6ArtifactStderrRead
                )
                $c6ArtifactStderrTask=$c6ArtifactStderrStream.ReadAsync(
                    $c6ArtifactStderrBuffer,
                    0,
                    $c6ArtifactStderrBuffer.Length
                )
            }
        }
    }
    $c6ArtifactRemainingMilliseconds=
        $script:C6ArtifactDeadlineMilliseconds-
        $script:C6ArtifactDeadlineStopwatch.ElapsedMilliseconds
    if ($c6ArtifactRemainingMilliseconds -le 0 -or
        -not $c6ArtifactProcess.WaitForExit(
            [int]$c6ArtifactRemainingMilliseconds
        ) -or
        -not $c6ArtifactProcess.HasExited -or
        $c6ArtifactProcess.ExitCode -ne 0 -or
        -not $c6ArtifactStdoutEof -or
        -not $c6ArtifactStderrEof) {
        throw 'artifact child failed'
    }
    [byte[]]$c6ArtifactStdoutBytes=$c6ArtifactStdoutMemory.ToArray()
    [byte[]]$c6ArtifactStderrBytes=$c6ArtifactStderrMemory.ToArray()
    $c6ArtifactStrictChildUtf8=[Text.UTF8Encoding]::new($false,$true)
    $c6ArtifactStdoutText=
        $c6ArtifactStrictChildUtf8.GetString($c6ArtifactStdoutBytes)
    $c6ArtifactStderrText=
        $c6ArtifactStrictChildUtf8.GetString($c6ArtifactStderrBytes)
    [byte[]]$c6ArtifactStdoutRoundTrip=
        $c6ArtifactStrictChildUtf8.GetBytes($c6ArtifactStdoutText)
    [byte[]]$c6ArtifactStderrRoundTrip=
        $c6ArtifactStrictChildUtf8.GetBytes($c6ArtifactStderrText)
    if ($c6ArtifactStdoutRoundTrip.Length -ne
            $c6ArtifactStdoutBytes.Length -or
        $c6ArtifactStderrRoundTrip.Length -ne
            $c6ArtifactStderrBytes.Length -or
        $c6ArtifactStderrBytes.Length -ne 0) {
        throw 'artifact child failed'
    }
    for ($c6ArtifactChildIndex=0;
         $c6ArtifactChildIndex -lt $c6ArtifactStdoutBytes.Length;
         $c6ArtifactChildIndex++) {
        if ($c6ArtifactStdoutRoundTrip[$c6ArtifactChildIndex] -ne
                $c6ArtifactStdoutBytes[$c6ArtifactChildIndex]) {
            throw 'artifact child failed'
        }
    }
    for ($c6ArtifactChildIndex=0;
         $c6ArtifactChildIndex -lt $c6ArtifactStderrBytes.Length;
         $c6ArtifactChildIndex++) {
        if ($c6ArtifactStderrRoundTrip[$c6ArtifactChildIndex] -ne
                $c6ArtifactStderrBytes[$c6ArtifactChildIndex]) {
            throw 'artifact child failed'
        }
    }
    [byte[]]$c6ArtifactExpectedStdoutBytes=
        $c6ArtifactStrictChildUtf8.GetBytes(
            $script:C6ArtifactValidatedExpectedOutputPath+"`n"
        )
    if ($c6ArtifactStdoutBytes.Length -ne
            $c6ArtifactExpectedStdoutBytes.Length) {
        throw 'artifact child failed'
    }
    for ($c6ArtifactChildIndex=0;
         $c6ArtifactChildIndex -lt $c6ArtifactStdoutBytes.Length;
         $c6ArtifactChildIndex++) {
        if ($c6ArtifactStdoutBytes[$c6ArtifactChildIndex] -ne
                $c6ArtifactExpectedStdoutBytes[$c6ArtifactChildIndex]) {
            throw 'artifact child failed'
        }
    }
    if ($script:C6ArtifactDeadlineStopwatch.ElapsedMilliseconds -gt
            $script:C6ArtifactDeadlineMilliseconds) {
        throw 'artifact child failed'
    }
    $script:C6ArtifactChildExitCode=$c6ArtifactProcess.ExitCode
    $script:C6ArtifactChildStdoutBytes=$c6ArtifactStdoutBytes
    $script:C6ArtifactChildStdoutSha256=[Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData(
            $c6ArtifactStdoutBytes
        )
    ).ToLowerInvariant()
    $script:C6ArtifactChildStderrBytes=$c6ArtifactStderrBytes
    $script:C6ArtifactChildStdoutEof=$c6ArtifactStdoutEof
    $script:C6ArtifactChildStderrEof=$c6ArtifactStderrEof
    $script:C6ArtifactChildLifecycleValidated=$true
    $c6ArtifactChildFailed=$false
} catch {
    $c6ArtifactChildFailed=$true
} finally {
    if ($null -ne $c6ArtifactProcess -and $c6ArtifactChildFailed) {
        try {
            $c6ArtifactProcess.StandardInput.Close()
        } catch {
        }
        try {
            if (-not $c6ArtifactProcess.HasExited) {
                $c6ArtifactProcess.Kill($true)
            }
        } catch {
            $c6ArtifactChildTerminationFailed=$true
        }
        try {
            if (-not $c6ArtifactProcess.WaitForExit($script:C6ArtifactTerminationGraceMilliseconds)) {
                $c6ArtifactChildTerminationFailed=$true
            }
        } catch {
            $c6ArtifactChildTerminationFailed=$true
        }
    }
    if ($null -ne $c6ArtifactStdoutMemory) {
        $c6ArtifactStdoutMemory.Dispose()
    }
    if ($null -ne $c6ArtifactStderrMemory) {
        $c6ArtifactStderrMemory.Dispose()
    }
    if ($null -ne $c6ArtifactProcess) {
        $c6ArtifactProcess.Dispose()
    }
}
if ($c6ArtifactChildFailed -or $c6ArtifactChildTerminationFailed) {
    throw 'artifact child failed'
}
# C6_ARTIFACT_CHILD_LIFECYCLE_END
