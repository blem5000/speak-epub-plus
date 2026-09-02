<#
Run-SpeakEPUB.ps1
Interactive launcher for speak.py.

How to use:
  1. Put this file in the same folder as speak.py.
  2. Double-click Run-SpeakEPUB.cmd, or run this script from PowerShell.
  3. Or drag an .epub file onto Run-SpeakEPUB.cmd (or pass its path as the
     first argument) to skip the "Enter EPUB path" prompt.

This launcher does not need manual venv activation. It uses .\venv\Scripts\python.exe directly.
If venv does not exist, it can create it and install requirements automatically
(finding Python via "python" or "py -3").
It remembers the last conversion in last-run.json so you can repeat it with one answer.
If FFmpeg is missing, it can install it for you with winget.
#>

param(
    # Optional path to an EPUB file (set automatically when you drag an EPUB onto Run-SpeakEPUB.cmd).
    [string]$EpubPath = ""
)

# Copy the argument: PowerShell variables are case-insensitive, so $EpubPath
# would collide with the $epubPath prompt variable below.
$EpubArg = $EpubPath

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

function Find-Python {
    # Returns the working Python command as a string array (e.g. @("python") or @("py", "-3")),
    # or $null when no Python 3.10+ is available.
    $candidates = @(
        @("python"),
        @("py", "-3")
    )

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
            continue
        }

        # Never use a splat-only invocation like `& @checkArgs`: Windows PowerShell 5.1
        # joins the splatted elements into a single command name ("python --version").
        # Also relax $ErrorActionPreference so a native-stderr probe (e.g. the Microsoft
        # Store "python" stub) cannot throw under "Stop".
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            if ($candidate.Count -gt 1) {
                $versionOutput = (& $exe $candidate[1] --version 2>&1 | Out-String).Trim()
            }
            else {
                $versionOutput = (& $exe --version 2>&1 | Out-String).Trim()
            }
        }
        catch {
            $versionOutput = ""
        }
        finally {
            $ErrorActionPreference = $prevEap
        }

        if ($versionOutput -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 4 -or ($major -eq 3 -and $minor -ge 10)) {
                return $candidate
            }

            Write-Warn "Found $versionOutput, but Python 3.10+ is required. Looking for another installation..."
        }
    }

    return $null
}

function Ensure-Venv($ScriptDir) {
    # Accept either "venv" or ".venv" as the environment folder name.
    $venvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    $dotVenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
    if (Test-Path $dotVenvPython) {
        return $dotVenvPython
    }

    $requirements = Join-Path $ScriptDir "requirements.txt"

    Write-Warn "Virtual environment was not found: .\venv"

    $pythonCmd = Find-Python
    if (-not $pythonCmd) {
        throw "Python 3.10+ was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') or run: winget install Python.Python.3.12"
    }

    $create = Read-YesNo "Create venv and install requirements now?" "Y"
    if (-not $create) {
        throw "Cannot continue without venv. Create venv manually or answer Y next time."
    }

    Write-Info "Creating virtual environment..."
    $venvArgs = @($pythonCmd) + @("-m", "venv", (Join-Path $ScriptDir "venv"))
    & @venvArgs

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

function Read-LastRun($ScriptDir) {
    $path = Join-Path $ScriptDir "last-run.json"
    if (-not (Test-Path $path)) {
        return $null
    }

    try {
        return Get-Content $path -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Save-LastRun($ScriptDir, $Settings) {
    $path = Join-Path $ScriptDir "last-run.json"
    try {
        $Settings | ConvertTo-Json | Set-Content -Path $path -Encoding UTF8
    }
    catch {
        # Saving the last-run settings is best effort only.
    }
}

function Test-FFmpegAvailable {
    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    return ($ffmpeg -and $ffprobe)
}

function Ensure-FFmpegIfNeeded($NeedFFmpeg) {
    if (-not $NeedFFmpeg) { return }
    if (Test-FFmpegAvailable) { return }

    Write-Warn "FFmpeg/ffprobe not found on PATH. M4B/M4A creation and chapter-part merging need FFmpeg."

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $install = Read-YesNo "Install FFmpeg now with winget (free, one-time)?" "Y"
        if ($install) {
            Write-Info "Installing FFmpeg with winget. This can take a few minutes..."
            & winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements

            # Make winget-installed tools visible in this session without a new terminal.
            $wingetLinks = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
            if (Test-Path $wingetLinks) {
                $env:Path = "$env:Path;$wingetLinks"
            }

            if (Test-FFmpegAvailable) {
                Write-Info "FFmpeg installed successfully."
                return
            }

            Write-Warn "FFmpeg was installed but is not visible in this session yet. Next time, start this launcher from a NEW terminal so it is found on PATH. For this run, chapter parts may stay unmerged."
            $continue = Read-YesNo "Continue anyway?" "Y"
            if (-not $continue) {
                throw "Stopped because FFmpeg is not on PATH yet. Open a new terminal and run this launcher again."
            }
            return
        }
    }
    else {
        Write-Warn "winget was not found. Install FFmpeg from https://www.gyan.dev/ffmpeg/builds/ or with: winget install ffmpeg"
    }

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
    $lastRun = Read-LastRun $scriptDir

    do {
        $repeatedLastRun = $false
        $epubPath = ""
        $format = ""
        $voice = ""
        $startChapter = ""
        $endChapter = ""
        $parallel = ""
        $retries = ""
        $chunkSize = ""
        $outputFolder = ""
        $keepParts = $false

        # EPUB source: argument (drag & drop), last run, or manual input
        if (-not [string]::IsNullOrWhiteSpace($EpubArg)) {
            $candidate = Clean-PathInput $EpubArg
            $EpubArg = ""   # only force it on the first pass
            if (-not (Test-Path $candidate)) {
                Write-Warn "EPUB passed to the launcher was not found: $candidate"
            }
            elseif ([System.IO.Path]::GetExtension($candidate) -ne ".epub") {
                Write-Warn "This does not look like an EPUB file: $candidate"
            }
            else {
                $epubPath = $candidate
            }
        }

        if ((-not $epubPath) -and $lastRun -and $lastRun.epub -and (Test-Path $lastRun.epub)) {
            Write-Host ""
            Write-Info "Last run: $($lastRun.epub) (format: $($lastRun.format))"
            if (Read-YesNo "Repeat this conversion with the same settings?" "N") {
                $epubPath = $lastRun.epub
                $format = [string]$lastRun.format
                $voice = [string]$lastRun.voice
                $startChapter = [string]$lastRun.startChapter
                $endChapter = [string]$lastRun.endChapter
                $parallel = [string]$lastRun.parallel
                $retries = [string]$lastRun.retries
                $chunkSize = [string]$lastRun.chunkSize
                $outputFolder = [string]$lastRun.outputFolder
                $keepParts = [bool]$lastRun.keepParts
                $repeatedLastRun = $true
            }
        }

        if (-not $epubPath) {
            do {
                $epubInput = Read-Host "Enter EPUB path (or drag the file here)"
                $epubPath = Clean-PathInput $epubInput
                if (-not (Test-Path $epubPath)) {
                    Write-Err "File not found: $epubPath"
                }
            } until (Test-Path $epubPath)
        }

        if (-not $format) {
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
        }

        $argsList = New-Object System.Collections.Generic.List[string]
        $argsList.Add($speakPy)
        $argsList.Add($epubPath)

        if ($format -eq "m4b") { $argsList.Add("--m4b") }
        if ($format -eq "m4a") { $argsList.Add("--m4a") }

        if (-not $repeatedLastRun) {
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

            $outputFolder = Clean-PathInput (Read-Default "Output folder, empty means default" "")
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

        Save-LastRun $scriptDir ([pscustomobject]@{
            epub = $epubPath
            format = $format
            voice = $voice
            startChapter = $startChapter
            endChapter = $endChapter
            parallel = $parallel
            retries = $retries
            chunkSize = $chunkSize
            outputFolder = $outputFolder
            keepParts = $keepParts
        })
    }

    Ensure-FFmpegIfNeeded (($format -eq "m4b") -or ($format -eq "m4a"))

    Write-Host ""
    Write-Info "Running command:"
    Write-Host "`"$venvPython`" $($argsList | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })"
    Write-Host ""

    & $venvPython @argsList

    Write-Host ""
    Write-Info "Finished."
    } while (Read-YesNo "Convert another EPUB?" "N")
}
catch {
    Write-Host ""
    Write-Err "ERROR: $($_.Exception.Message)"
}
finally {
    Write-Host ""
    Read-Host "Press ENTER to close"
}
