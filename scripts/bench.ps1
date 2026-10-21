# Runs parakeet-cli transcribe with wall-time and peak-memory measurement.
# Usage: powershell -File scripts/bench.ps1 -Wav samples\arenes1_4min.wav [-Threads 4] [-Vad] [-Json]
param(
  [Parameter(Mandatory = $true)][string]$Wav,
  [int]$Threads = 4,
  [switch]$Vad,
  [switch]$Json,
  [string]$Model = "",
  [string]$VadModel = "",
  [string]$Cli = ""
)

$ErrorActionPreference = "Stop"
if (-not $Model) { $Model = "$PSScriptRoot\..\artifacts\fluid-speech-mini-q2k-q4k.gguf" }
if (-not $VadModel) { $VadModel = "$PSScriptRoot\..\artifacts\silero-vad-f16.gguf" }
if (-not $Cli) { $Cli = "$PSScriptRoot\..\artifacts\parakeet-cli\parakeet-v0.6.1-bin-win-cpu-x64\parakeet-cli.exe" }
$wavPath = (Resolve-Path $Wav).Path
$cliPath = (Resolve-Path $Cli).Path
$modelPath = (Resolve-Path $Model).Path

$cliArgs = @("transcribe", "--model", $modelPath, "--input", $wavPath, "--threads", $Threads)
if ($Vad) { $cliArgs += @("--vad", "--vad-model", (Resolve-Path $VadModel).Path) }
if ($Json) { $cliArgs += "--json" }

$base = [IO.Path]::Combine([IO.Path]::GetDirectoryName($wavPath), [IO.Path]::GetFileNameWithoutExtension($wavPath))
$outFile = "${base}.out.txt"
$errFile = "${base}.err.txt"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $cliPath -ArgumentList $cliArgs -NoNewWindow -PassThru `
      -RedirectStandardOutput $outFile -RedirectStandardError $errFile
$peakWS = 0L
while (-not $p.HasExited) {
  try {
    $ws = (Get-Process -Id $p.Id -ErrorAction Stop).WorkingSet64
    if ($ws -gt $peakWS) { $peakWS = $ws }
  } catch {}
  Start-Sleep -Milliseconds 100
}
$p.WaitForExit() | Out-Null
$sw.Stop()

$peakMB = [math]::Round($peakWS / 1MB)
$dur = [double](& ffprobe -v error -show_entries format=duration -of csv=p=0 $wavPath 2>$null)
if ($dur -le 0) { $dur = 0 }
$rtfx = if ($sw.Elapsed.TotalSeconds -gt 0) { [math]::Round($dur / $sw.Elapsed.TotalSeconds, 2) } else { 0 }

Write-Output ("RESULT exit={0} wall={1:n1}s audio={2:n0}s rtfx={3} peakWorkingSet={4}MB out={5} err={6}" -f `
  $p.ExitCode, $sw.Elapsed.TotalSeconds, $dur, $rtfx, $peakMB, $outFile, $errFile)
