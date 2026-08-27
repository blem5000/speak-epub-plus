<#
Run-SpeakEPUB.ps1
Interactive launcher for speak.py.

How to use:
  1. Put this file in the same folder as speak.py.
  2. Double-click Run-SpeakEPUB.cmd, or run this script from PowerShell.

This launcher does not need manual venv activation. It uses .\venv\Scripts\python.exe directly.
If venv does not exist, it can create it and install requirements automatically.
#>

$ErrorActionPreference = "Stop"

function Write-Info($Message) {
    Write-Host $Message -ForegroundColor Cyan
}

function Write-Warn($Message) {
    Write-Host $Message -ForegroundColor Yellow
}

function Write-Err($Message) {
    Write-Host $Message -ForegroundColor Red
}

function Read-Default($Prompt, $Default) {
    if ([string]::IsNullOrWhiteSpace($Default)) {
        $value = Read-Host "$Prompt"
    }
    else {
        $value = Read-Host "$Prompt ($Default)"
    }

    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }

    return $value.Trim()
}

function Read-YesNo($Prompt, $Default = "N") {
    $defaultUpper = $Default.ToUpperInvariant()
    while ($true) {
        $answer = Read-Host "$Prompt (Y/N, default $defaultUpper)"
        if ([string]::IsNullOrWhiteSpace($answer)) {
            return ($defaultUpper -eq "Y")
        }
        switch ($answer.Trim().ToUpperInvariant()) {
            "Y" { return $true }
            "YES" { return $true }
            "N" { return $false }
            "NO" { return $false }
            default { Write-Warn "Please answer Y or N." }
        }
    }
}

function Clean-PathInput($Value) {
    if ($null -eq $Value) { return "" }
    return $Value.Trim().Trim('"').Trim("'")
}

function Ensure-Venv($ScriptDir) {
    $venvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"
    $requirements = Join-Path $ScriptDir "requirements.txt"

    if (Test-Path $venvPython) {
        return $venvPython
    }

    Write-Warn "Virtual environment was not found: .\venv"
    $create = Read-YesNo "Create venv and install requirements now?" "Y"
    if (-not $create) {
        throw "Cannot continue without venv. Create venv manually or answer Y next time."
    }

    Write-Info "Creating virtual environment..."
    python -m venv (Join-Path $ScriptDir "venv")

    if (-not (Test-Path $venvPython)) {
        throw "venv python was not created. Check your Python installation."
    }

    Write-Info "Upgrading pip..."
    & $venvPython -m pip install --upgrade pip

    if (Test-Path $requirements) {
        Write-Info "Installing requirements from requirements.txt..."
        & $venvPython -m pip install -r $requirements
    }
    else {
        Write-Warn "requirements.txt not found. Installing common dependencies..."
        & $venvPython -m pip install ebooklib beautifulsoup4 edge-tts lxml
    }

    return $venvPython
}

function Ensure-FFmpegIfNeeded($NeedFFmpeg) {
    if (-not $NeedFFmpeg) { return }

    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue

    if ($ffmpeg -and $ffprobe) { return }

    Write-Warn "FFmpeg/ffprobe not found on PATH. M4B/M4A creation and chapter-part merging need FFmpeg."
    Write-Warn "Install with: winget install ffmpeg"
    $continue = Read-YesNo "Continue anyway? The final audiobook merge may be skipped." "N"
    if (-not $continue) {
        throw "Stopped because FFmpeg is missing. Install FFmpeg and run again."
    }
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    Set-Location $scriptDir

    $speakPy = Join-Path $scriptDir "speak.py"
    if (-not (Test-Path $speakPy)) {
        throw "speak.py not found in this folder: $scriptDir`nPut this launcher in the same folder as speak.py."
    }

    Write-Host ""
    Write-Info "Speak EPUB interactive launcher"
    Write-Info "Folder: $scriptDir"
    Write-Host ""

    $venvPython = Ensure-Venv $scriptDir

    do {
        $epubInput = Read-Host "Enter EPUB path"
        $epubPath = Clean-PathInput $epubInput
        if (-not (Test-Path $epubPath)) {
            Write-Err "File not found: $epubPath"
        }
    } until (Test-Path $epubPath)

    Write-Host ""
    Write-Host "Choose output format:"
    Write-Host "  1. MP3 chapter files only"
    Write-Host "  2. M4B audiobook file + MP3 chapter files"
    Write-Host "  3. M4A audiobook file + MP3 chapter files"
    Write-Host ""

    $formatChoice = Read-Default "Output format" "2"
    switch ($formatChoice.Trim().ToUpperInvariant()) {
        "1" { $format = "mp3" }
        "MP3" { $format = "mp3" }
        "2" { $format = "m4b" }
        "M4B" { $format = "m4b" }
        "3" { $format = "m4a" }
        "M4A" { $format = "m4a" }
        "M4P" {
            Write-Warn "M4P is not used here. M4B is the audiobook format, so I will use M4B."
            $format = "m4b"
        }
        default {
            Write-Warn "Unknown choice. Using M4B."
            $format = "m4b"
        }
    }

    $argsList = New-Object System.Collections.Generic.List[string]
    $argsList.Add($speakPy)
    $argsList.Add($epubPath)

    if ($format -eq "m4b") { $argsList.Add("--m4b") }
    if ($format -eq "m4a") { $argsList.Add("--m4a") }

    $addParams = Read-YesNo "Do you want to change additional parameters?" "N"

    if ($addParams) {
        Write-Host ""
        Write-Info "Press ENTER to use the default value shown in parentheses."

        $voice = Read-Default "Voice" "en-US-AndrewNeural"
        if (-not [string]::IsNullOrWhiteSpace($voice)) {
            $argsList.Add("--voice")
            $argsList.Add($voice)
        }

        $startChapter = Read-Default "Start chapter" "1"
        if (-not [string]::IsNullOrWhiteSpace($startChapter)) {
            $argsList.Add("--start-chapter")
            $argsList.Add($startChapter)
        }

        $endChapter = Read-Default "End chapter, empty means to end" ""
        if (-not [string]::IsNullOrWhiteSpace($endChapter)) {
            $argsList.Add("--end-chapter")
            $argsList.Add($endChapter)
        }

        $parallel = Read-Default "Parallel TTS part jobs" "3"
        if (-not [string]::IsNullOrWhiteSpace($parallel)) {
            $argsList.Add("--parallel")
            $argsList.Add($parallel)
        }

        $retries = Read-Default "Retries per TTS part" "5"
        if (-not [string]::IsNullOrWhiteSpace($retries)) {
            $argsList.Add("--retries")
            $argsList.Add($retries)
        }

        $chunkSize = Read-Default "Chunk size" "3500"
        if (-not [string]::IsNullOrWhiteSpace($chunkSize)) {
            $argsList.Add("--chunk-size")
            $argsList.Add($chunkSize)
        }

        $outputFolder = Read-Default "Output folder, empty means default" ""
        $outputFolder = Clean-PathInput $outputFolder
        if (-not [string]::IsNullOrWhiteSpace($outputFolder)) {
            $argsList.Add("--output")
            $argsList.Add($outputFolder)
        }

        $keepParts = Read-YesNo "Keep temporary part MP3 files after merging?" "N"
        if ($keepParts) {
            $argsList.Add("--keep-parts")
        }
    }
    else {
        # Defaults already exist inside speak.py. Keep command short.
        Write-Info "Using speak.py defaults: voice en-US-AndrewNeural, parallel 3, retries 5, chunk-size 3500, start chapter 1."
    }

    Ensure-FFmpegIfNeeded (($format -eq "m4b") -or ($format -eq "m4a"))

    Write-Host ""
    Write-Info "Running command:"
    Write-Host "`"$venvPython`" $($argsList | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })"
    Write-Host ""

    & $venvPython @argsList

    Write-Host ""
    Write-Info "Finished."
}
catch {
    Write-Host ""
    Write-Err "ERROR: $($_.Exception.Message)"
}
finally {
    Write-Host ""
    Read-Host "Press ENTER to close"
}
