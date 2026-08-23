$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$inputStream = [Console]::OpenStandardInput()
$inputBuffer = [byte[]]::new(65536)
$payloadStream = [System.IO.MemoryStream]::new()
while (($read = $inputStream.Read($inputBuffer, 0, $inputBuffer.Length)) -gt 0) {
    if (($payloadStream.Length + $read) -gt 262144) {
        throw 'COMMAND_PAYLOAD_LIMIT_EXCEEDED'
    }
    $payloadStream.Write($inputBuffer, 0, $read)
}
$payloadBytes = $payloadStream.ToArray()
$payload = $utf8.GetString($payloadBytes)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput(
    $payload,
    [ref]$tokens,
    [ref]$parseErrors
)

trap {
    $stableCode = [string]$_.Exception.Message
    if (
        $stableCode -cne 'COMMAND_PAYLOAD_LIMIT_EXCEEDED' -and
        $stableCode -cne 'COMMAND_DECODER_LIMIT_EXCEEDED'
    ) {
        $stableCode = 'COMMAND_DECODER_PARSE_INVALID'
    }
    $stableErrorBytes = $utf8.GetBytes($stableCode)
    $stableErrorStream = [Console]::OpenStandardError()
    $stableErrorStream.Write(
        $stableErrorBytes,
        0,
        $stableErrorBytes.Length
    )
    $stableErrorStream.Flush()
    exit 1
}

$documentByteLimit = 4194304

function Get-Sha256Hex {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [byte[]] $Bytes
    )

    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($Bytes)
    ).ToLowerInvariant()
}

function Get-CompactJsonUtf8Length {
    param(
        [Parameter(Mandatory)]
        [AllowNull()]
        [object] $Value
    )

    $compactJson = ConvertTo-Json -InputObject $Value -Depth 64 -Compress
    return [long]$utf8.GetByteCount($compactJson)
}

function Assert-DocumentBudgetDelta {
    param(
        [Parameter(Mandatory)]
        [System.Collections.IDictionary] $Budget,
        [Parameter(Mandatory)]
        [long] $Delta
    )

    $currentBytes = [long]$Budget.bytes
    if ($currentBytes -lt 0 -or $Delta -lt 0) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    if ($currentBytes -gt $documentByteLimit) {
        throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
    }
    if ($Delta -gt ([long]$documentByteLimit - $currentBytes)) {
        throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
    }
}

function Get-DocumentArrayEntryDelta {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [System.Collections.ICollection] $Entries,
        [Parameter(Mandatory)]
        [object] $Entry
    )

    $separatorByteCount = 0
    if ($Entries.Count -gt 0) {
        $separatorByteCount = 1
    }
    return (
        (Get-CompactJsonUtf8Length $Entry) + $separatorByteCount
    )
}

function Add-BudgetedDocumentEntry {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[object]] $Entries,
        [Parameter(Mandatory)]
        [object] $Entry,
        [Parameter(Mandatory)]
        [System.Collections.IDictionary] $Budget
    )

    $entryDelta = Get-DocumentArrayEntryDelta $Entries $Entry
    Assert-DocumentBudgetDelta $Budget $entryDelta
    [void]$Entries.Add($Entry)
    $Budget.bytes = [long]$Budget.bytes + $entryDelta
}

function Get-NonnegativeDecimalByteLength {
    param(
        [Parameter(Mandatory)]
        [long] $Value
    )

    if ($Value -lt 0) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $decimalText = $Value.ToString(
        [Globalization.CultureInfo]::InvariantCulture
    )
    return [long]$utf8.GetByteCount($decimalText)
}

$closedTokenKinds = [string[]]@(
    'Unknown', 'Variable', 'SplattedVariable', 'Parameter', 'Number',
    'Label', 'Identifier', 'Generic', 'NewLine', 'LineContinuation',
    'Comment', 'EndOfInput', 'StringLiteral', 'StringExpandable',
    'HereStringLiteral', 'HereStringExpandable', 'LParen', 'RParen',
    'LCurly', 'RCurly', 'LBracket', 'RBracket', 'AtParen', 'AtCurly',
    'DollarParen', 'Semi', 'AndAnd', 'OrOr', 'Ampersand', 'Pipe',
    'Comma', 'MinusMinus', 'PlusPlus', 'DotDot', 'ColonColon', 'Dot',
    'Exclaim', 'Multiply', 'Divide', 'Rem', 'Plus', 'Minus', 'Equals',
    'PlusEquals', 'MinusEquals', 'MultiplyEquals', 'DivideEquals',
    'RemainderEquals', 'Redirection', 'RedirectInStd', 'Format', 'Not',
    'Bnot', 'And', 'Or', 'Xor', 'Band', 'Bor', 'Bxor', 'Join', 'Ieq',
    'Ine', 'Ige', 'Igt', 'Ilt', 'Ile', 'Ilike', 'Inotlike', 'Imatch',
    'Inotmatch', 'Ireplace', 'Icontains', 'Inotcontains', 'Iin', 'Inotin',
    'Isplit', 'Ceq', 'Cne', 'Cge', 'Cgt', 'Clt', 'Cle', 'Clike',
    'Cnotlike', 'Cmatch', 'Cnotmatch', 'Creplace', 'Ccontains',
    'Cnotcontains', 'Cin', 'Cnotin', 'Csplit', 'Is', 'IsNot', 'As',
    'PostfixPlusPlus', 'PostfixMinusMinus', 'Shl', 'Shr', 'Colon',
    'QuestionMark', 'QuestionQuestionEquals', 'QuestionQuestion',
    'QuestionDot', 'QuestionLBracket', 'Begin', 'Break', 'Catch', 'Class',
    'Continue', 'Data', 'Define', 'Do', 'Dynamicparam', 'Else', 'ElseIf',
    'End', 'Exit', 'Filter', 'Finally', 'For', 'Foreach', 'From',
    'Function', 'If', 'In', 'Param', 'Process', 'Return', 'Switch',
    'Throw', 'Trap', 'Try', 'Until', 'Using', 'Var', 'While', 'Workflow',
    'Parallel', 'Sequence', 'InlineScript', 'Configuration',
    'DynamicKeyword', 'Public', 'Private', 'Static', 'Interface', 'Enum',
    'Namespace', 'Module', 'Type', 'Assembly', 'Command', 'Hidden', 'Base',
    'Default', 'Clean'
)
$closedTokenFlags = [string[]]@(
    'None', 'BinaryPrecedenceLogical', 'BinaryPrecedenceBitwise',
    'BinaryPrecedenceComparison', 'BinaryPrecedenceCoalesce',
    'BinaryPrecedenceAdd', 'BinaryPrecedenceMultiply',
    'BinaryPrecedenceFormat', 'BinaryPrecedenceRange',
    'BinaryPrecedenceMask', 'Keyword', 'ScriptBlockBlockName',
    'BinaryOperator', 'UnaryOperator', 'CaseSensitiveOperator',
    'TernaryOperator', 'SpecialOperator', 'AssignmentOperator',
    'ParseModeInvariant', 'TokenInError', 'DisallowedInRestrictedMode',
    'PrefixOrPostfixOperator', 'CommandName', 'MemberName', 'TypeName',
    'AttributeName', 'CanConstantFold', 'StatementDoesntSupportAttributes'
)
$closedTokenKindSet = [System.Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($closedTokenKind in $closedTokenKinds) {
    [void]$closedTokenKindSet.Add($closedTokenKind)
}
$closedTokenFlagSet = [System.Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($closedTokenFlag in $closedTokenFlags) {
    [void]$closedTokenFlagSet.Add($closedTokenFlag)
}

$closedAstTypes = [string[]]@(
    'ArrayExpressionAst', 'ArrayLiteralAst', 'AssignmentStatementAst',
    'AttributeAst', 'AttributeBaseAst', 'AttributedExpressionAst',
    'BaseCtorInvokeMemberExpressionAst', 'BinaryExpressionAst',
    'BlockStatementAst', 'BreakStatementAst', 'CatchClauseAst',
    'ChainableAst', 'CommandAst', 'CommandBaseAst', 'CommandElementAst',
    'CommandExpressionAst', 'CommandParameterAst',
    'CompilerGeneratedMemberFunctionAst', 'ConfigurationDefinitionAst',
    'ConstantExpressionAst', 'ContinueStatementAst', 'ConvertExpressionAst',
    'DataStatementAst', 'DoUntilStatementAst', 'DoWhileStatementAst',
    'DynamicKeywordStatementAst', 'ErrorExpressionAst', 'ErrorStatementAst',
    'ExitStatementAst', 'ExpandableStringExpressionAst', 'ExpressionAst',
    'FileRedirectionAst', 'ForEachStatementAst', 'ForStatementAst',
    'FunctionDefinitionAst', 'FunctionMemberAst', 'HashtableAst',
    'IfStatementAst', 'IndexExpressionAst', 'InvokeMemberExpressionAst',
    'LabeledStatementAst', 'LoopStatementAst', 'MemberAst',
    'MemberExpressionAst', 'MergingRedirectionAst',
    'NamedAttributeArgumentAst', 'NamedBlockAst', 'ParamBlockAst',
    'ParameterAst', 'ParenExpressionAst', 'PipelineAst', 'PipelineBaseAst',
    'PipelineChainAst', 'PropertyMemberAst', 'RedirectionAst',
    'ReturnStatementAst', 'ScriptBlockAst', 'ScriptBlockExpressionAst',
    'SequencePointAst', 'StatementAst', 'StatementBlockAst',
    'StringConstantExpressionAst', 'SubExpressionAst', 'SwitchStatementAst',
    'TernaryExpressionAst', 'ThrowStatementAst', 'TrapStatementAst',
    'TryStatementAst', 'TypeConstraintAst', 'TypeDefinitionAst',
    'TypeExpressionAst', 'UnaryExpressionAst', 'UsingExpressionAst',
    'UsingStatementAst', 'AssignmentTarget', 'VariableExpressionAst',
    'WhileStatementAst'
)
$scriptBlockAstTypes = [string[]]@(
    'ScriptBlockAst'
)
$statementRoleAstTypes = [string[]]@(
    'AssignmentStatementAst', 'AttributeAst', 'AttributeBaseAst',
    'ChainableAst', 'CommandBaseAst', 'CompilerGeneratedMemberFunctionAst',
    'ConfigurationDefinitionAst', 'DataStatementAst',
    'DynamicKeywordStatementAst', 'ErrorStatementAst',
    'FunctionDefinitionAst', 'FunctionMemberAst', 'MemberAst',
    'NamedAttributeArgumentAst', 'NamedBlockAst', 'ParamBlockAst',
    'ParameterAst', 'PipelineBaseAst', 'PropertyMemberAst',
    'SequencePointAst', 'StatementAst', 'StatementBlockAst',
    'TypeConstraintAst', 'TypeDefinitionAst', 'UsingStatementAst'
)
$pipelineAstTypes = [string[]]@(
    'PipelineAst', 'PipelineChainAst'
)
$commandAstTypes = [string[]]@(
    'CommandAst', 'CommandExpressionAst'
)
$commandElementAstTypes = [string[]]@(
    'CommandElementAst', 'CommandParameterAst'
)
$redirectionAstTypes = [string[]]@(
    'FileRedirectionAst', 'MergingRedirectionAst', 'RedirectionAst'
)
$controlFlowAstTypes = [string[]]@(
    'BlockStatementAst', 'BreakStatementAst', 'CatchClauseAst',
    'ContinueStatementAst', 'DoUntilStatementAst', 'DoWhileStatementAst',
    'ExitStatementAst', 'ForEachStatementAst', 'ForStatementAst',
    'IfStatementAst', 'LabeledStatementAst', 'LoopStatementAst',
    'ReturnStatementAst', 'SwitchStatementAst', 'ThrowStatementAst',
    'TrapStatementAst', 'TryStatementAst', 'WhileStatementAst'
)
$expressionAstTypes = [string[]]@(
    'ArrayExpressionAst', 'ArrayLiteralAst', 'AssignmentTarget',
    'AttributedExpressionAst', 'BaseCtorInvokeMemberExpressionAst',
    'BinaryExpressionAst', 'ConstantExpressionAst', 'ConvertExpressionAst',
    'ErrorExpressionAst', 'ExpandableStringExpressionAst', 'ExpressionAst',
    'HashtableAst', 'IndexExpressionAst', 'InvokeMemberExpressionAst',
    'MemberExpressionAst', 'ParenExpressionAst',
    'ScriptBlockExpressionAst', 'StringConstantExpressionAst',
    'SubExpressionAst', 'TernaryExpressionAst', 'TypeExpressionAst',
    'UnaryExpressionAst', 'UsingExpressionAst', 'VariableExpressionAst'
)
$concreteStatementAstTypes = [string[]]@(
    'AssignmentStatementAst', 'BlockStatementAst', 'BreakStatementAst',
    'CommandAst', 'CommandExpressionAst', 'ConfigurationDefinitionAst',
    'ContinueStatementAst', 'DataStatementAst', 'DoUntilStatementAst',
    'DoWhileStatementAst', 'DynamicKeywordStatementAst', 'ErrorStatementAst',
    'ExitStatementAst', 'ForEachStatementAst', 'ForStatementAst',
    'FunctionDefinitionAst', 'IfStatementAst', 'PipelineAst',
    'PipelineChainAst', 'ReturnStatementAst', 'SwitchStatementAst',
    'ThrowStatementAst', 'TrapStatementAst', 'TryStatementAst',
    'TypeDefinitionAst', 'UsingStatementAst', 'WhileStatementAst'
)
$operationAstTypes = [string[]]@(
    'CommandAst'
)
$pipelineStageAstTypes = [string[]]@(
    'CommandAst', 'CommandExpressionAst'
)
$closedAstPropertyValueKinds = [string[]]@(
    'ast', 'ast_sequence', 'tuple_sequence', 'flag_map'
)

$closedAstTypeOrdinal = [System.Collections.Generic.Dictionary[string, int]]::new(
    [StringComparer]::Ordinal
)
for ($index = 0; $index -lt $closedAstTypes.Count; $index++) {
    if (-not $closedAstTypeOrdinal.TryAdd($closedAstTypes[$index], $index)) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
}
$astRoleByType = [System.Collections.Generic.Dictionary[string, string]]::new(
    [StringComparer]::Ordinal
)
$astRolePartitions = [ordered]@{
    script_block = $scriptBlockAstTypes
    statement = $statementRoleAstTypes
    pipeline = $pipelineAstTypes
    command = $commandAstTypes
    command_element = $commandElementAstTypes
    redirection = $redirectionAstTypes
    control_flow = $controlFlowAstTypes
    expression = $expressionAstTypes
}
foreach ($astRole in $astRolePartitions.Keys) {
    foreach ($astType in $astRolePartitions[$astRole]) {
        if (
            -not $closedAstTypeOrdinal.ContainsKey($astType) -or
            -not $astRoleByType.TryAdd($astType, $astRole)
        ) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
    }
}
if ($astRoleByType.Count -ne $closedAstTypes.Count) {
    throw 'COMMAND_DECODER_PARSE_INVALID'
}

$concreteStatementAstTypeSet = [System.Collections.Generic.HashSet[string]]::new(
    $concreteStatementAstTypes,
    [StringComparer]::Ordinal
)
$operationAstTypeSet = [System.Collections.Generic.HashSet[string]]::new(
    $operationAstTypes,
    [StringComparer]::Ordinal
)
$pipelineStageAstTypeSet = [System.Collections.Generic.HashSet[string]]::new(
    $pipelineStageAstTypes,
    [StringComparer]::Ordinal
)

function Get-Utf8BoundaryTable {
    param([string] $Value)

    $boundaries = [int[]]::new($Value.Length + 1)
    [Array]::Fill($boundaries, -1)
    $boundaries[0] = 0
    $utf16Offset = 0
    $utf8Offset = 0
    while ($utf16Offset -lt $Value.Length) {
        $first = [int][char]$Value[$utf16Offset]
        if ($first -ge 0xD800 -and $first -le 0xDBFF) {
            if (($utf16Offset + 1) -ge $Value.Length) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            $second = [int][char]$Value[$utf16Offset + 1]
            if ($second -lt 0xDC00 -or $second -gt 0xDFFF) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            $utf16Offset += 2
            $utf8Offset += 4
        }
        elseif ($first -ge 0xDC00 -and $first -le 0xDFFF) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
        else {
            $utf16Offset++
            if ($first -le 0x7F) {
                $utf8Offset++
            }
            elseif ($first -le 0x7FF) {
                $utf8Offset += 2
            }
            else {
                $utf8Offset += 3
            }
        }
        $boundaries[$utf16Offset] = $utf8Offset
    }
    return ,$boundaries
}

function Convert-Extent {
    param(
        [System.Management.Automation.Language.IScriptExtent] $Extent,
        [int[]] $BoundaryTable,
        [int] $Utf8Length
    )

    $startOffset = [int]$Extent.StartOffset
    $endOffset = [int]$Extent.EndOffset
    if (
        $startOffset -lt 0 -or
        $endOffset -lt $startOffset -or
        $endOffset -ge $BoundaryTable.Length -or
        $BoundaryTable[$startOffset] -lt 0 -or
        $BoundaryTable[$endOffset] -lt 0 -or
        $BoundaryTable[$endOffset] -gt $Utf8Length
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    return [ordered]@{
        start_utf16 = $startOffset
        end_utf16 = $endOffset
        start_utf8 = $BoundaryTable[$startOffset]
        end_utf8 = $BoundaryTable[$endOffset]
    }
}

function Convert-EndOfInputExtent {
    param(
        [int] $StartOffset,
        [int] $EndOffset,
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [int[]] $BoundaryTable,
        [int] $Utf8Length
    )

    if (
        $BoundaryTable.Length -eq 0 -or
        $Utf8Length -lt 0 -or
        $BoundaryTable[-1] -ne $Utf8Length
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $payloadEndUtf16 = $BoundaryTable.Length - 1
    $firstSyntheticOffset = $payloadEndUtf16 + 1
    $lastSyntheticOffset = $payloadEndUtf16 + 2
    if (
        $StartOffset -ne $EndOffset -or
        $StartOffset -lt $firstSyntheticOffset -or
        $StartOffset -gt $lastSyntheticOffset
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    return [ordered]@{
        start_utf16 = $payloadEndUtf16
        end_utf16 = $payloadEndUtf16
        start_utf8 = $Utf8Length
        end_utf8 = $Utf8Length
    }
}

function Assert-EndOfInputExtentContract {
    $probeBoundaries = [int[]]@(0, 1)
    $acceptedSpans = @(
        (Convert-EndOfInputExtent 2 2 $probeBoundaries 1),
        (Convert-EndOfInputExtent 3 3 $probeBoundaries 1)
    )
    foreach ($acceptedSpan in $acceptedSpans) {
        if (
            $acceptedSpan.start_utf16 -ne 1 -or
            $acceptedSpan.end_utf16 -ne 1 -or
            $acceptedSpan.start_utf8 -ne 1 -or
            $acceptedSpan.end_utf8 -ne 1
        ) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
    }

    $rejectedProbes = @(
        [ordered]@{
            start = 1
            end = 1
            boundaries = $probeBoundaries
            utf8_length = 1
        },
        [ordered]@{
            start = 4
            end = 4
            boundaries = $probeBoundaries
            utf8_length = 1
        },
        [ordered]@{
            start = 2
            end = 3
            boundaries = $probeBoundaries
            utf8_length = 1
        },
        [ordered]@{
            start = 2
            end = 2
            boundaries = [int[]]@(0, 2)
            utf8_length = 1
        }
    )
    foreach ($rejectedProbe in $rejectedProbes) {
        $wasRejected = $false
        try {
            [void](Convert-EndOfInputExtent (
                $rejectedProbe.start
            ) $rejectedProbe.end $rejectedProbe.boundaries (
                $rejectedProbe.utf8_length
            ))
        }
        catch {
            if ($_.Exception.Message -cne 'COMMAND_DECODER_PARSE_INVALID') {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            $wasRejected = $true
        }
        if (-not $wasRejected) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
    }
}

function Convert-Token {
    param(
        [System.Management.Automation.Language.Token] $Token,
        [int] $Index,
        [int[]] $BoundaryTable,
        [byte[]] $PayloadBytes,
        [System.Collections.Generic.HashSet[string]] $AllowedKinds,
        [System.Collections.Generic.HashSet[string]] $AllowedFlags
    )

    $kind = $Token.Kind.ToString()
    if (-not $AllowedKinds.Contains($kind)) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }

    $flags = [System.Collections.Generic.List[string]]::new()
    $seenFlags = [System.Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($rawFlag in $Token.TokenFlags.ToString().Split(',')) {
        $flag = $rawFlag.Trim()
        if (
            $flag.Length -eq 0 -or
            -not $AllowedFlags.Contains($flag) -or
            -not $seenFlags.Add($flag)
        ) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
        [void]$flags.Add($flag)
    }
    $flags.Sort([StringComparer]::Ordinal)

    if ($kind -ceq 'EndOfInput') {
        $span = Convert-EndOfInputExtent (
            $Token.Extent.StartOffset
        ) $Token.Extent.EndOffset $BoundaryTable $PayloadBytes.Length
    }
    else {
        $span = Convert-Extent (
            $Token.Extent
        ) $BoundaryTable $PayloadBytes.Length
    }
    $tokenLength = $span.end_utf8 - $span.start_utf8
    $tokenBytes = [byte[]]::new($tokenLength)
    if ($tokenLength -gt 0) {
        [Array]::Copy(
            $PayloadBytes,
            $span.start_utf8,
            $tokenBytes,
            0,
            $tokenLength
        )
    }
    $literal = $null
    if ($kind -ceq 'Identifier' -or $kind -ceq 'Number') {
        $literalValue = $utf8.GetString($tokenBytes)
        $literalBytes = $utf8.GetBytes($literalValue)
        $literal = [ordered]@{
            kind = 'bare'
            value = $literalValue
            utf8_bytes = $literalBytes.Length
            sha256 = Get-Sha256Hex $literalBytes
        }
    }
    elseif ($kind -ceq 'StringLiteral') {
        $literalValue = [string]$Token.Value
        $literalBytes = $utf8.GetBytes($literalValue)
        $literal = [ordered]@{
            kind = 'single_quoted'
            value = $literalValue
            utf8_bytes = $literalBytes.Length
            sha256 = Get-Sha256Hex $literalBytes
        }
    }
    $tokenSha256 = Get-Sha256Hex $tokenBytes

    return [ordered]@{
        index = $Index
        kind = $kind
        flags = $flags
        start_utf16 = $span.start_utf16
        end_utf16 = $span.end_utf16
        start_utf8 = $span.start_utf8
        end_utf8 = $span.end_utf8
        text_sha256 = $tokenSha256
        literal = $literal
    }
}

function Get-SafeAstPropertyValue {
    param(
        [System.Management.Automation.Language.Ast] $Node,
        [System.Reflection.PropertyInfo] $Property,
        [string] $ValueKind,
        [ref] $Result
    )

    if (
        $Property.Name -ceq 'Parent' -or
        -not $Property.CanRead -or
        $Property.GetIndexParameters().Count -ne 0
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $getter = $Property.GetGetMethod()
    if ($null -eq $getter -or $getter.IsStatic) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }

    $astBaseType = [System.Management.Automation.Language.Ast]
    $readOnlyCollectionDefinition = (
        [System.Collections.ObjectModel.ReadOnlyCollection``1]
    )
    $dictionaryDefinition = [System.Collections.Generic.Dictionary``2]
    $tupleDefinition = [System.Tuple``2]
    $tokenBaseType = [System.Management.Automation.Language.Token]
    $propertyType = $Property.PropertyType
    $verifiedKind = $null
    if ($astBaseType.IsAssignableFrom($propertyType)) {
        $verifiedKind = 'ast'
    }
    elseif (
        $propertyType.IsGenericType -and
        $propertyType.GetGenericTypeDefinition() -eq $readOnlyCollectionDefinition
    ) {
        $elementType = $propertyType.GetGenericArguments()[0]
        if ($astBaseType.IsAssignableFrom($elementType)) {
            $verifiedKind = 'ast_sequence'
        }
        elseif (
            $elementType.IsGenericType -and
            $elementType.GetGenericTypeDefinition() -eq $tupleDefinition
        ) {
            $tupleArguments = $elementType.GetGenericArguments()
            if (
                $tupleArguments.Count -eq 2 -and
                $astBaseType.IsAssignableFrom($tupleArguments[0]) -and
                $astBaseType.IsAssignableFrom($tupleArguments[1])
            ) {
                $verifiedKind = 'tuple_sequence'
            }
        }
    }
    elseif (
        $propertyType.IsGenericType -and
        $propertyType.GetGenericTypeDefinition() -eq $dictionaryDefinition
    ) {
        $dictionaryArguments = $propertyType.GetGenericArguments()
        if (
            $dictionaryArguments.Count -eq 2 -and
            $dictionaryArguments[0] -eq [string] -and
            $dictionaryArguments[1].IsGenericType -and
            $dictionaryArguments[1].GetGenericTypeDefinition() -eq $tupleDefinition
        ) {
            $tupleArguments = $dictionaryArguments[1].GetGenericArguments()
            if (
                $tupleArguments.Count -eq 2 -and
                $tupleArguments[0] -eq $tokenBaseType -and
                $tupleArguments[1] -eq $astBaseType
            ) {
                $verifiedKind = 'flag_map'
            }
        }
    }
    if ($null -eq $verifiedKind -or $ValueKind -cne $verifiedKind) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }

    try {
        $Result.Value = $Property.GetValue($Node)
    }
    catch {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
}

function Add-DirectAstCandidate {
    param(
        [System.Management.Automation.Language.Ast] $ParentNode,
        [AllowNull()]
        [object] $CandidateNode,
        [int] $PropertyOrdinal,
        [ref] $DiscoveryOrdinal,
        [System.Collections.Generic.Dictionary[string, int]] $TypeOrdinals,
        [System.Collections.Generic.HashSet[object]] $DirectIdentitySet,
        [System.Collections.Generic.HashSet[object]] $GlobalIdentitySet,
        [ref] $DiscoveredCount,
        [System.Collections.Generic.List[object]] $Candidates
    )

    if ($null -eq $CandidateNode) {
        return
    }
    if ($CandidateNode -isnot [System.Management.Automation.Language.Ast]) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $candidateAst = [System.Management.Automation.Language.Ast]$CandidateNode
    if (-not [object]::ReferenceEquals($candidateAst.Parent, $ParentNode)) {
        return
    }

    $currentDiscoveryOrdinal = [int]$DiscoveryOrdinal.Value
    $DiscoveryOrdinal.Value = $currentDiscoveryOrdinal + 1
    if ($DirectIdentitySet.Contains($candidateAst)) {
        return
    }
    if ($GlobalIdentitySet.Contains($candidateAst)) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }

    $astType = $candidateAst.GetType().Name
    [int]$typeOrdinal = 0
    if (-not $TypeOrdinals.TryGetValue($astType, [ref]$typeOrdinal)) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $extent = $candidateAst.Extent
    $startOffset = [int]$extent.StartOffset
    $endOffset = [int]$extent.EndOffset
    if ($startOffset -lt 0 -or $endOffset -lt $startOffset) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }

    $nextCount = [int]$DiscoveredCount.Value + 1
    if ($nextCount -gt 8192) {
        throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
    }
    $DiscoveredCount.Value = $nextCount
    if (
        -not $DirectIdentitySet.Add($candidateAst) -or
        -not $GlobalIdentitySet.Add($candidateAst)
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    [void]$Candidates.Add([ordered]@{
        node = $candidateAst
        start_offset = $startOffset
        end_offset = $endOffset
        closed_type_ordinal = $typeOrdinal
        property_ordinal = $PropertyOrdinal
        discovery_ordinal = $currentDiscoveryOrdinal
    })
}

function Get-DirectAstChildren {
    param(
        [System.Management.Automation.Language.Ast] $Node,
        [System.Collections.Generic.Dictionary[string, int]] $TypeOrdinals,
        [System.Collections.Generic.HashSet[object]] $GlobalIdentitySet,
        [ref] $DiscoveredCount
    )

    $directChildIdentitySet = [System.Collections.Generic.HashSet[object]]::new(
        [System.Collections.Generic.ReferenceEqualityComparer]::Instance
    )
    $candidates = [System.Collections.Generic.List[object]]::new()
    $properties = [System.Collections.Generic.List[System.Reflection.PropertyInfo]]::new()
    foreach (
        $property in $Node.GetType().GetProperties(
            [System.Reflection.BindingFlags]::Instance -bor
            [System.Reflection.BindingFlags]::Public
        )
    ) {
        [void]$properties.Add($property)
    }
    $properties.Sort([System.Comparison[System.Reflection.PropertyInfo]]{
        param($left, $right)
        $comparison = [StringComparer]::Ordinal.Compare($left.Name, $right.Name)
        if ($comparison -ne 0) {
            return $comparison
        }
        $comparison = [StringComparer]::Ordinal.Compare(
            $left.DeclaringType.FullName,
            $right.DeclaringType.FullName
        )
        if ($comparison -ne 0) {
            return $comparison
        }
        $comparison = [StringComparer]::Ordinal.Compare(
            $left.PropertyType.AssemblyQualifiedName,
            $right.PropertyType.AssemblyQualifiedName
        )
        if ($comparison -ne 0) {
            return $comparison
        }
        return $left.MetadataToken.CompareTo($right.MetadataToken)
    })

    $astBaseType = [System.Management.Automation.Language.Ast]
    $readOnlyCollectionDefinition = (
        [System.Collections.ObjectModel.ReadOnlyCollection``1]
    )
    $dictionaryDefinition = [System.Collections.Generic.Dictionary``2]
    $tupleDefinition = [System.Tuple``2]
    $tokenBaseType = [System.Management.Automation.Language.Token]
    $discoveryOrdinal = 0
    for ($propertyOrdinal = 0; $propertyOrdinal -lt $properties.Count; $propertyOrdinal++) {
        $property = $properties[$propertyOrdinal]
        if (
            $property.Name -ceq 'Parent' -or
            -not $property.CanRead -or
            $property.GetIndexParameters().Count -ne 0
        ) {
            continue
        }
        $getter = $property.GetGetMethod()
        if ($null -eq $getter -or $getter.IsStatic) {
            continue
        }

        $propertyType = $property.PropertyType
        $valueKind = $null
        $tupleElementType = $null
        $flagTupleType = $null
        if ($astBaseType.IsAssignableFrom($propertyType)) {
            $valueKind = 'ast'
        }
        elseif (
            $propertyType.IsGenericType -and
            $propertyType.GetGenericTypeDefinition() -eq $readOnlyCollectionDefinition
        ) {
            $elementType = $propertyType.GetGenericArguments()[0]
            if ($astBaseType.IsAssignableFrom($elementType)) {
                $valueKind = 'ast_sequence'
            }
            elseif (
                $elementType.IsGenericType -and
                $elementType.GetGenericTypeDefinition() -eq $tupleDefinition
            ) {
                $tupleArguments = $elementType.GetGenericArguments()
                if (
                    $tupleArguments.Count -eq 2 -and
                    $astBaseType.IsAssignableFrom($tupleArguments[0]) -and
                    $astBaseType.IsAssignableFrom($tupleArguments[1])
                ) {
                    $valueKind = 'tuple_sequence'
                    $tupleElementType = $elementType
                }
            }
        }
        elseif (
            $propertyType.IsGenericType -and
            $propertyType.GetGenericTypeDefinition() -eq $dictionaryDefinition
        ) {
            $dictionaryArguments = $propertyType.GetGenericArguments()
            if (
                $dictionaryArguments.Count -eq 2 -and
                $dictionaryArguments[0] -eq [string] -and
                $dictionaryArguments[1].IsGenericType -and
                $dictionaryArguments[1].GetGenericTypeDefinition() -eq $tupleDefinition
            ) {
                $tupleArguments = $dictionaryArguments[1].GetGenericArguments()
                if (
                    $tupleArguments.Count -eq 2 -and
                    $tupleArguments[0] -eq $tokenBaseType -and
                    $tupleArguments[1] -eq $astBaseType
                ) {
                    $valueKind = 'flag_map'
                    $flagTupleType = $dictionaryArguments[1]
                }
            }
        }
        if ($null -eq $valueKind) {
            continue
        }

        $propertyValue = $null
        Get-SafeAstPropertyValue $Node $property $valueKind ([ref]$propertyValue)
        if ($null -eq $propertyValue) {
            continue
        }
        if ($valueKind -ceq 'ast') {
            Add-DirectAstCandidate $Node $propertyValue $propertyOrdinal (
                [ref]$discoveryOrdinal
            ) $TypeOrdinals $directChildIdentitySet $GlobalIdentitySet (
                $DiscoveredCount
            ) $candidates
            continue
        }
        if ($propertyValue.GetType() -ne $propertyType) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
        if ($valueKind -ceq 'flag_map') {
            if (
                $null -eq $flagTupleType -or
                $propertyValue -isnot [System.Collections.IDictionary]
            ) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            $flagDictionary = [System.Collections.IDictionary]$propertyValue
            $flagKeys = [System.Collections.Generic.List[string]]::new()
            foreach ($flagKeyObject in $flagDictionary.Keys) {
                if (
                    $null -eq $flagKeyObject -or
                    $flagKeyObject.GetType() -ne [string]
                ) {
                    throw 'COMMAND_DECODER_PARSE_INVALID'
                }
                [void]$flagKeys.Add([string]$flagKeyObject)
            }
            if ($flagKeys.Count -ne $flagDictionary.Count) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            $flagKeys.Sort([StringComparer]::Ordinal)
            foreach ($flagKey in $flagKeys) {
                try {
                    $tupleObject = $flagDictionary[$flagKey]
                }
                catch {
                    throw 'COMMAND_DECODER_PARSE_INVALID'
                }
                if (
                    $null -eq $tupleObject -or
                    $tupleObject.GetType() -ne $flagTupleType -or
                    $tupleObject -isnot [System.Runtime.CompilerServices.ITuple]
                ) {
                    throw 'COMMAND_DECODER_PARSE_INVALID'
                }
                $tupleValue = [System.Runtime.CompilerServices.ITuple]$tupleObject
                if (
                    $tupleValue.Length -ne 2 -or
                    (
                        $null -ne $tupleValue[0] -and
                        $tupleValue[0] -isnot [System.Management.Automation.Language.Token]
                    )
                ) {
                    throw 'COMMAND_DECODER_PARSE_INVALID'
                }
                Add-DirectAstCandidate $Node $tupleValue[1] (
                    $propertyOrdinal
                ) ([ref]$discoveryOrdinal) $TypeOrdinals (
                    $directChildIdentitySet
                ) $GlobalIdentitySet $DiscoveredCount $candidates
            }
            continue
        }
        $sequence = [System.Collections.IList]$propertyValue
        if ($valueKind -ceq 'ast_sequence') {
            for ($sequenceIndex = 0; $sequenceIndex -lt $sequence.Count; $sequenceIndex++) {
                Add-DirectAstCandidate $Node $sequence[$sequenceIndex] (
                    $propertyOrdinal
                ) ([ref]$discoveryOrdinal) $TypeOrdinals (
                    $directChildIdentitySet
                ) $GlobalIdentitySet $DiscoveredCount $candidates
            }
            continue
        }
        if ($valueKind -cne 'tuple_sequence') {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
        for ($sequenceIndex = 0; $sequenceIndex -lt $sequence.Count; $sequenceIndex++) {
            $tupleObject = $sequence[$sequenceIndex]
            if (
                $null -eq $tupleObject -or
                $tupleObject.GetType() -ne $tupleElementType -or
                $tupleObject -isnot [System.Runtime.CompilerServices.ITuple]
            ) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            $tupleValue = [System.Runtime.CompilerServices.ITuple]$tupleObject
            if ($tupleValue.Length -ne 2) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            for ($tupleIndex = 0; $tupleIndex -lt 2; $tupleIndex++) {
                Add-DirectAstCandidate $Node $tupleValue[$tupleIndex] (
                    $propertyOrdinal
                ) ([ref]$discoveryOrdinal) $TypeOrdinals (
                    $directChildIdentitySet
                ) $GlobalIdentitySet $DiscoveredCount $candidates
            }
        }
    }

    $candidates.Sort([System.Comparison[object]]{
        param($left, $right)
        $comparison = $left.start_offset.CompareTo($right.start_offset)
        if ($comparison -ne 0) {
            return $comparison
        }
        $comparison = $left.end_offset.CompareTo($right.end_offset)
        if ($comparison -ne 0) {
            return $comparison
        }
        $comparison = $left.closed_type_ordinal.CompareTo(
            $right.closed_type_ordinal
        )
        if ($comparison -ne 0) {
            return $comparison
        }
        $comparison = $left.property_ordinal.CompareTo($right.property_ordinal)
        if ($comparison -ne 0) {
            return $comparison
        }
        return $left.discovery_ordinal.CompareTo($right.discovery_ordinal)
    })
    return ,$candidates
}

function Convert-SafeAstLiteral {
    param(
        [System.Management.Automation.Language.Ast] $Node,
        [int[]] $BoundaryTable,
        [byte[]] $PayloadBytes
    )

    if ($Node.GetType().Name -cne 'StringConstantExpressionAst') {
        return $null
    }
    $constantNode = (
        [System.Management.Automation.Language.StringConstantExpressionAst]$Node
    )
    $span = Convert-Extent $Node.Extent $BoundaryTable $PayloadBytes.Length
    $sourceLength = $span.end_utf8 - $span.start_utf8
    $sourceBytes = [byte[]]::new($sourceLength)
    if ($sourceLength -gt 0) {
        [Array]::Copy(
            $PayloadBytes,
            $span.start_utf8,
            $sourceBytes,
            0,
            $sourceLength
        )
    }
    $sourceText = $utf8.GetString($sourceBytes)

    if (
        $sourceBytes.Length -ge 2 -and
        $sourceBytes[0] -eq 0x40 -and
        ($sourceBytes[1] -eq 0x27 -or $sourceBytes[1] -eq 0x22)
    ) {
        return $null
    }

    $literalKind = $null
    $expectedConstantType = $null
    $reconstructedValue = $null
    if ($sourceBytes.Length -gt 0 -and $sourceBytes[0] -eq 0x27) {
        if (
            $sourceText.Length -lt 2 -or
            $sourceText[0] -ne [char]0x27 -or
            $sourceText[-1] -ne [char]0x27
        ) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
        $valueBuilder = [System.Text.StringBuilder]::new()
        $cursor = 1
        while ($cursor -lt ($sourceText.Length - 1)) {
            $character = $sourceText[$cursor]
            if ($character -ne [char]0x27) {
                [void]$valueBuilder.Append($character)
                $cursor++
                continue
            }
            if (
                ($cursor + 1) -ge ($sourceText.Length - 1) -or
                $sourceText[$cursor + 1] -ne [char]0x27
            ) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            [void]$valueBuilder.Append([char]0x27)
            $cursor += 2
        }
        $literalKind = 'single_quoted'
        $expectedConstantType = 'SingleQuoted'
        $reconstructedValue = $valueBuilder.ToString()
    }
    elseif ($sourceBytes.Length -gt 0 -and $sourceBytes[0] -eq 0x22) {
        if (
            $sourceText.Length -lt 2 -or
            $sourceText[0] -ne [char]0x22 -or
            $sourceText[-1] -ne [char]0x22
        ) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
        $valueBuilder = [System.Text.StringBuilder]::new()
        $cursor = 1
        while ($cursor -lt ($sourceText.Length - 1)) {
            $character = $sourceText[$cursor]
            if (
                $character -eq [char]0x24 -or
                $character -eq [char]0x0D -or
                $character -eq [char]0x0A
            ) {
                return $null
            }
            if ($character -eq [char]0x22) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            if ($character -ne [char]0x60) {
                [void]$valueBuilder.Append($character)
                $cursor++
                continue
            }
            $cursor++
            if ($cursor -ge ($sourceText.Length - 1)) {
                return $null
            }
            $escaped = $sourceText[$cursor]
            switch ([int]$escaped) {
                0x30 { $replacement = [char]0x00 }
                0x61 { $replacement = [char]0x07 }
                0x62 { $replacement = [char]0x08 }
                0x65 { $replacement = [char]0x1B }
                0x66 { $replacement = [char]0x0C }
                0x6E { $replacement = [char]0x0A }
                0x72 { $replacement = [char]0x0D }
                0x74 { $replacement = [char]0x09 }
                0x76 { $replacement = [char]0x0B }
                0x22 { $replacement = [char]0x22 }
                0x60 { $replacement = [char]0x60 }
                0x24 { $replacement = [char]0x24 }
                default { return $null }
            }
            [void]$valueBuilder.Append($replacement)
            $cursor++
        }
        $literalKind = 'double_quoted'
        $expectedConstantType = 'DoubleQuoted'
        $reconstructedValue = $valueBuilder.ToString()
    }
    else {
        if (
            $sourceText.Length -eq 0 -or
            $sourceText[0] -eq [char]0x40 -or
            $sourceText[0] -eq [char]0x23
        ) {
            return $null
        }
        for ($cursor = 0; $cursor -lt $sourceText.Length; $cursor++) {
            $character = $sourceText[$cursor]
            $characterCode = [int]$character
            if (
                [char]::IsWhiteSpace($character) -or
                $characterCode -lt 0x20
            ) {
                return $null
            }
            switch ($characterCode) {
                0x60 { return $null }
                0x24 { return $null }
                0x27 { return $null }
                0x22 { return $null }
                0x3B { return $null }
                0x2C { return $null }
                0x7C { return $null }
                0x26 { return $null }
                0x28 { return $null }
                0x29 { return $null }
                0x7B { return $null }
                0x7D { return $null }
                0x5B { return $null }
                0x5D { return $null }
                0x3C { return $null }
                0x3E { return $null }
            }
        }
        $literalKind = 'bare'
        $expectedConstantType = 'BareWord'
        $reconstructedValue = $sourceText
    }

    if (
        $constantNode.StringConstantType.ToString() -cne $expectedConstantType -or
        -not [StringComparer]::Ordinal.Equals(
            $reconstructedValue,
            [string]$constantNode.Value
        )
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $literalByteCount = $utf8.GetByteCount($reconstructedValue)
    if ($literalByteCount -gt 262144) {
        throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
    }
    $literalBytes = $utf8.GetBytes($reconstructedValue)
    return [ordered]@{
        kind = $literalKind
        value = $reconstructedValue
        utf8_bytes = $literalByteCount
        sha256 = Get-Sha256Hex $literalBytes
    }
}

function Convert-AstTree {
    param(
        [System.Management.Automation.Language.Ast] $Root,
        [int[]] $BoundaryTable,
        [byte[]] $PayloadBytes,
        [System.Collections.Generic.Dictionary[string, int]] $TypeOrdinals,
        [System.Collections.Generic.Dictionary[string, string]] $RoleByType,
        [System.Collections.Generic.HashSet[string]] $StatementTypes,
        [System.Collections.Generic.HashSet[string]] $OperationTypes,
        [System.Collections.Generic.HashSet[string]] $PipelineStageTypes,
        [System.Collections.Generic.List[object]] $NodeEntries,
        [System.Collections.IDictionary] $Metrics,
        [System.Collections.IDictionary] $DocumentBudget
    )

    if ($null -eq $Root -or $null -ne $Root.Parent) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    if (
        $NodeEntries.Count -ne 0 -or
        [long]$Metrics.ast_nodes -ne 0 -or
        [long]$Metrics.ast_depth -ne 0 -or
        [long]$Metrics.statements -ne 0 -or
        [long]$Metrics.operations -ne 0 -or
        [long]$Metrics.pipeline_stages -ne 0
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $globalAstIdentitySet = [System.Collections.Generic.HashSet[object]]::new(
        [System.Collections.Generic.ReferenceEqualityComparer]::Instance
    )
    $astStack = [System.Collections.Generic.Stack[object]]::new()
    $discoveredAstCount = 0
    if (($discoveredAstCount + 1) -gt 8192) {
        throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
    }
    $discoveredAstCount++
    if (-not $globalAstIdentitySet.Add($Root)) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $astStack.Push([ordered]@{
        node = $Root
        parent_index = $null
        depth = 1
    })

    while ($astStack.Count -gt 0) {
        $frame = $astStack.Pop()
        $node = [System.Management.Automation.Language.Ast]$frame.node
        $nodeIndex = $nodeEntries.Count
        if (($nodeEntries.Count + 1) -gt 8192) {
            throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
        }

        $astType = $node.GetType().Name
        [int]$ignoredTypeOrdinal = 0
        [string]$role = $null
        if (
            -not $TypeOrdinals.TryGetValue($astType, [ref]$ignoredTypeOrdinal) -or
            -not $RoleByType.TryGetValue($astType, [ref]$role)
        ) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }

        $depth = [int]$frame.depth
        if ($depth -lt 1) {
            throw 'COMMAND_DECODER_PARSE_INVALID'
        }
        if ($depth -gt 64) {
            throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
        }
        $nextStatementCount = [long]$Metrics.statements
        if ($StatementTypes.Contains($astType)) {
            $nextStatementCount++
        }
        if ($nextStatementCount -gt 256) {
            throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
        }
        $nextOperationCount = [long]$Metrics.operations
        if ($OperationTypes.Contains($astType)) {
            $nextOperationCount++
        }
        if ($nextOperationCount -gt 256) {
            throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
        }
        $nextPipelineStageCount = [long]$Metrics.pipeline_stages
        if ($PipelineStageTypes.Contains($astType)) {
            $nextPipelineStageCount++
        }
        if ($nextPipelineStageCount -gt 256) {
            throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
        }
        $nextAstDepth = [long]$Metrics.ast_depth
        if ($depth -gt $nextAstDepth) {
            $nextAstDepth = $depth
        }

        $span = Convert-Extent $node.Extent $BoundaryTable $PayloadBytes.Length
        $invocationOperator = $null
        if ($astType -ceq 'CommandAst') {
            $commandNode = [System.Management.Automation.Language.CommandAst]$node
            switch -CaseSensitive ($commandNode.InvocationOperator.ToString()) {
                'Unknown' {
                    $invocationOperator = 'none'
                }
                'Ampersand' {
                    $invocationOperator = 'call'
                }
                'Dot' {
                    $invocationOperator = 'dot'
                }
                default {
                    throw 'COMMAND_DECODER_PARSE_INVALID'
                }
            }
        }
        $literal = Convert-SafeAstLiteral $node $BoundaryTable $PayloadBytes
        $childIndices = [System.Collections.Generic.List[int]]::new()
        $nodeEntry = [ordered]@{
            index = $nodeIndex
            ast_type = $astType
            role = $role
            parent_index = $frame.parent_index
            child_indices = $childIndices
            start_utf16 = $span.start_utf16
            end_utf16 = $span.end_utf16
            start_utf8 = $span.start_utf8
            end_utf8 = $span.end_utf8
            invocation_operator = $invocationOperator
            literal = $literal
        }

        $parentIndex = $null
        $parentChildDelta = [long]0
        if ($null -eq $frame.parent_index) {
            if ($nodeIndex -ne 0) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
        }
        else {
            $parentIndex = [int]$frame.parent_index
            if ($parentIndex -lt 0 -or $parentIndex -ge $nodeIndex) {
                throw 'COMMAND_DECODER_PARSE_INVALID'
            }
            $parentChildDelta = Get-NonnegativeDecimalByteLength $nodeIndex
            if ($NodeEntries[$parentIndex].child_indices.Count -gt 0) {
                $parentChildDelta++
            }
        }

        $nodeEntryDelta = Get-DocumentArrayEntryDelta $NodeEntries $nodeEntry
        $nextAstNodeCount = [long]$nodeIndex + 1
        $metricDelta = (
            (Get-NonnegativeDecimalByteLength $nextAstNodeCount) -
            (Get-NonnegativeDecimalByteLength ([long]$Metrics.ast_nodes)) +
            (Get-NonnegativeDecimalByteLength $nextAstDepth) -
            (Get-NonnegativeDecimalByteLength ([long]$Metrics.ast_depth)) +
            (Get-NonnegativeDecimalByteLength $nextStatementCount) -
            (Get-NonnegativeDecimalByteLength ([long]$Metrics.statements)) +
            (Get-NonnegativeDecimalByteLength $nextOperationCount) -
            (Get-NonnegativeDecimalByteLength ([long]$Metrics.operations)) +
            (Get-NonnegativeDecimalByteLength $nextPipelineStageCount) -
            (Get-NonnegativeDecimalByteLength ([long]$Metrics.pipeline_stages))
        )
        $nodeDocumentDelta = (
            [long]$nodeEntryDelta + $parentChildDelta + $metricDelta
        )
        Assert-DocumentBudgetDelta $DocumentBudget $nodeDocumentDelta

        if ($null -ne $parentIndex) {
            [void]$NodeEntries[$parentIndex].child_indices.Add($nodeIndex)
        }
        $Metrics.ast_nodes = $nodeIndex + 1
        $Metrics.ast_depth = $nextAstDepth
        $Metrics.statements = $nextStatementCount
        $Metrics.operations = $nextOperationCount
        $Metrics.pipeline_stages = $nextPipelineStageCount
        [void]$NodeEntries.Add($nodeEntry)
        $DocumentBudget.bytes = (
            [long]$DocumentBudget.bytes + $nodeDocumentDelta
        )

        $children = Get-DirectAstChildren $node $TypeOrdinals (
            $globalAstIdentitySet
        ) ([ref]$discoveredAstCount)
        for ($childOffset = $children.Count - 1; $childOffset -ge 0; $childOffset--) {
            $astStack.Push([ordered]@{
                node = $children[$childOffset].node
                parent_index = $nodeIndex
                depth = $depth + 1
            })
        }
    }
    if (
        $nodeEntries.Count -ne $discoveredAstCount -or
        $globalAstIdentitySet.Count -ne $discoveredAstCount
    ) {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }

    return [ordered]@{
        nodes = $NodeEntries
        metrics = $Metrics
    }
}

Assert-EndOfInputExtentContract

$utf8Boundaries = Get-Utf8BoundaryTable $payload
if ($utf8Boundaries[-1] -ne $payloadBytes.Length) {
    throw 'COMMAND_DECODER_PARSE_INVALID'
}

if ($tokens.Count -gt 8192) {
    throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
}
if ($parseErrors.Count -gt 256) {
    throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
}

$shellPath = [Environment]::ProcessPath
if ([string]::IsNullOrWhiteSpace($shellPath)) {
    throw 'COMMAND_DECODER_IDENTITY_MISMATCH'
}
$shellBytes = [IO.File]::ReadAllBytes($shellPath)
$shellVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo($shellPath)
$fileVersion = [string]$shellVersion.FileVersion
$productVersion = [string]$shellVersion.ProductVersion
$parserVersion = [string]$PSVersionTable.PSVersion.ToString()
if (
    [string]::IsNullOrWhiteSpace($fileVersion) -or
    [string]::IsNullOrWhiteSpace($productVersion) -or
    [string]::IsNullOrWhiteSpace($parserVersion) -or
    $PSEdition -cne 'Core'
) {
    throw 'COMMAND_DECODER_IDENTITY_MISMATCH'
}

$decoderBytes = [IO.File]::ReadAllBytes($PSCommandPath)
$tokenEntries = [System.Collections.Generic.List[object]]::new()
$parseErrorEntries = [System.Collections.Generic.List[object]]::new()
$nodeEntries = [System.Collections.Generic.List[object]]::new()
$metrics = [ordered]@{
    ast_nodes = [long]0
    ast_depth = [long]0
    statements = [long]0
    operations = [long]0
    pipeline_stages = [long]0
}
$document = [ordered]@{
    schema_version = 'complete-suite-command-plan-decoder-v1'
    payload = [ordered]@{
        utf8_bytes = $payloadBytes.Length
        sha256 = Get-Sha256Hex $payloadBytes
    }
    powershell = [ordered]@{
        path = $shellPath
        sha256 = Get-Sha256Hex $shellBytes
        file_version = $fileVersion
        product_version = $productVersion
        edition = 'Core'
        parser_version = $parserVersion
    }
    decoder = [ordered]@{
        path = 'tests/skills/complete_suite_command_plan_decoder.ps1'
        sha256 = Get-Sha256Hex $decoderBytes
    }
    parse_errors = $parseErrorEntries
    tokens = $tokenEntries
    nodes = $nodeEntries
    metrics = $metrics
}
$documentBudget = [ordered]@{
    bytes = Get-CompactJsonUtf8Length $document
}
if ([long]$documentBudget.bytes -gt $documentByteLimit) {
    throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
}

for ($index = 0; $index -lt $tokens.Count; $index++) {
    $tokenEntry = Convert-Token (
        $tokens[$index]
    ) $index $utf8Boundaries $payloadBytes (
        $closedTokenKindSet
    ) $closedTokenFlagSet
    Add-BudgetedDocumentEntry $tokenEntries $tokenEntry $documentBudget
}

for ($index = 0; $index -lt $parseErrors.Count; $index++) {
    $parseError = $parseErrors[$index]
    $errorId = [string]$parseError.ErrorId
    if ($errorId -cnotmatch '^[A-Za-z0-9_.:-]{1,256}$') {
        throw 'COMMAND_DECODER_PARSE_INVALID'
    }
    $span = Convert-Extent $parseError.Extent $utf8Boundaries $payloadBytes.Length
    $messageBytes = $utf8.GetBytes([string]$parseError.Message)
    $parseErrorEntry = [ordered]@{
        index = $index
        error_id = $errorId
        incomplete_input = [bool]$parseError.IncompleteInput
        start_utf16 = $span.start_utf16
        end_utf16 = $span.end_utf16
        start_utf8 = $span.start_utf8
        end_utf8 = $span.end_utf8
        message_sha256 = Get-Sha256Hex $messageBytes
    }
    Add-BudgetedDocumentEntry (
        $parseErrorEntries
    ) $parseErrorEntry $documentBudget
}

$astTree = Convert-AstTree $ast $utf8Boundaries $payloadBytes (
    $closedAstTypeOrdinal
) $astRoleByType $concreteStatementAstTypeSet $operationAstTypeSet (
    $pipelineStageAstTypeSet
) $nodeEntries $metrics $documentBudget

$json = ConvertTo-Json -InputObject $document -Depth 64 -Compress
$outputBytes = $utf8.GetBytes($json)
if ($outputBytes.Length -gt $documentByteLimit) {
    throw 'COMMAND_DECODER_LIMIT_EXCEEDED'
}
if ([long]$outputBytes.Length -ne [long]$documentBudget.bytes) {
    throw 'COMMAND_DECODER_PARSE_INVALID'
}
$outputStream = [Console]::OpenStandardOutput()
$outputStream.Write($outputBytes, 0, $outputBytes.Length)
$outputStream.Flush()
