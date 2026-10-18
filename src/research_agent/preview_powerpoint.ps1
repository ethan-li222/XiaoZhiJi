param(
    [Parameter(Mandatory=$true)][string]$PptxPath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$presentation = $null
$application = $null
try {
    $resolvedPptx = (Resolve-Path -LiteralPath $PptxPath).Path
    $resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
    New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
    $application = New-Object -ComObject PowerPoint.Application
    # WithWindow=false opens only the requested presentation without an interactive window.
    $presentation = $application.Presentations.Open($resolvedPptx, $true, $false, $false)
    $pdfPath = Join-Path $resolvedOutput ([System.IO.Path]::GetFileNameWithoutExtension($resolvedPptx) + '.pdf')
    $presentation.SaveAs($pdfPath, 32)
    $slideDirectory = Join-Path $resolvedOutput 'slides'
    New-Item -ItemType Directory -Path $slideDirectory -Force | Out-Null
    $slideNames = @()
    for ($index = 1; $index -le $presentation.Slides.Count; $index++) {
        $slidePath = Join-Path $slideDirectory ('Slide{0}.PNG' -f $index)
        $presentation.Slides.Item($index).Export($slidePath, 'PNG', 1600, 900)
        $slideNames += ('Slide{0}.PNG' -f $index)
    }
    ConvertTo-Json -InputObject @($slideNames) | Set-Content -LiteralPath (Join-Path $resolvedOutput 'slides.json') -Encoding UTF8
} finally {
    if ($null -ne $presentation) {
        $presentation.Close()
        [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation) | Out-Null
    }
    if ($null -ne $application) {
        # Preserve any presentations the user already has open.
        if ($application.Presentations.Count -eq 0) { $application.Quit() }
        [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($application) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
