$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskAudioDir = Join-Path $taskRoot 'runtime\demo\audio'
New-Item -ItemType Directory -Path $taskAudioDir -Force | Out-Null
Add-Type -AssemblyName System.Speech
$taskSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$taskSynth.SelectVoice('Microsoft Huihui Desktop')
$taskSynth.Rate = -1
$taskChapters = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'narration.json') -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($taskChapter in $taskChapters) {
    $taskWavePath = Join-Path $taskAudioDir ($taskChapter.id + '.wav')
    $taskSynth.SetOutputToWaveFile($taskWavePath)
    $taskSynth.Speak($taskChapter.text)
    $taskSynth.SetOutputToNull()
}
$taskSynth.Dispose()
Write-Output 'Chinese narration created locally.'
