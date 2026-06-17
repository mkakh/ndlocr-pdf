# Build-after smoke test (§7.2). Runs the packaged exe headlessly on the
# committed sample.pdf and fails (non-zero exit) if the OCR output is missing.
#
# Usage: pwsh tools/smoke_test.ps1 -Exe dist/ndlocr-pdf/ndlocr-pdf.exe
param(
    [Parameter(Mandatory = $true)][string]$Exe
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$sample = Join-Path $repo "tests/fixtures/sample.pdf"
$out = Join-Path $repo "_smoke_ci_out"

if (-not (Test-Path $Exe)) { Write-Error "exe not found: $Exe"; exit 1 }
if (-not (Test-Path $sample)) { Write-Error "fixture not found: $sample"; exit 1 }
if (Test-Path $out) { Remove-Item -Recurse -Force $out }

Write-Host "Running: $Exe --cli $sample --pages 1 --output $out"
# The packaged exe is a windowed (GUI-subsystem) binary, so the call operator
# would not wait for it. Start-Process -Wait blocks until it exits and -PassThru
# gives us the real exit code from sys.exit() on the --cli path.
$p = Start-Process -FilePath $Exe `
    -ArgumentList @("--cli", $sample, "--pages", "1", "--output", $out) `
    -Wait -PassThru
$code = $p.ExitCode
Write-Host "exit code: $code"
if ($code -ne 0) { Write-Error "OCR exited with code $code"; exit 1 }

$txt = Join-Path $out "sample.txt"
$pdf = Join-Path $out "sample_text.pdf"

if (-not (Test-Path $txt)) { Write-Error "missing expected text output: $txt"; exit 1 }
if (-not (Test-Path $pdf)) { Write-Error "missing expected searchable PDF: $pdf"; exit 1 }
if ((Get-Item $txt).Length -le 0) { Write-Error "text output is empty: $txt"; exit 1 }

Write-Host "SMOKE TEST PASSED: $txt and $pdf produced."
Remove-Item -Recurse -Force $out
exit 0
