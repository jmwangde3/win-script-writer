@{
    # Only failures block a release. Warnings are reviewed, not enforced.
    Severity     = @('Error', 'Warning')

    ExcludeRules = @(
        # This repository deliberately exposes positional parameters on the
        # command line tools so they can be called from scripts and CI.
        'PSAvoidUsingPositionalParameters'

        # New-EncodedScript.ps1 implements ShouldProcess on the script level;
        # the rule only inspects functions.
        'PSUseShouldProcessForStateChangingFunctions'

        # Switches such as -FailOnWarning are consumed through $PSBoundParameters
        # patterns that the analyzer cannot follow.
        'PSReviewUnusedParameter'

        # The tools emit ASCII-only structured output on purpose; Write-Output is
        # used instead of Write-Host everywhere.
        'PSAvoidUsingWriteHost'

        # "Bytes" and "CodePoints" are mass nouns. Renaming Get-FileBytes to
        # Get-FileByte or Test-StartsWithBytes to Test-StartsWithByte would
        # satisfy the rule and make the name wrong.
        'PSUseSingularNouns'
    )
}
