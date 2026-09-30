# Generate public English sample speech using Windows SAPI.
$demoOutput = Join-Path $PSScriptRoot '..\examples\demo.en.wav'
if (Test-Path -LiteralPath $demoOutput) { throw 'Sample already exists; refusing to overwrite it.' }
$demoSpeaker = New-Object -ComObject SAPI.SpVoice
$demoStream = New-Object -ComObject SAPI.SpFileStream
foreach ($demoVoice in $demoSpeaker.GetVoices()) {
    if ($demoVoice.GetDescription() -match 'English|Zira|David') {
        $demoSpeaker.Voice = $demoVoice
        break
    }
}
try {
    $demoStream.Open($demoOutput, 3, $false)
    $demoSpeaker.AudioOutputStream = $demoStream
    [void]$demoSpeaker.Speak('Hello. This is a subtitle translation test. You can choose the source and target languages.')
} finally {
    $demoStream.Close()
}
Write-Output 'Created public synthetic speech sample: examples/demo.en.wav'
