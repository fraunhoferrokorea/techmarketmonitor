# Wait for Groq TPD window, reprocess priority June dates, regenerate monthly report.
$ErrorActionPreference = "Continue"
Set-Location "c:\Users\Admin\Documents\python-project"

$log = "output/regen_june_catchup_groq.log"
function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg"
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

function Test-GroqReady {
    $out = python -c @"
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv(Path('.') / '.env')
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'), base_url=os.getenv('OPENAI_BASE_URL'))
try:
    client.chat.completions.create(
        model=os.getenv('MODEL_NAME', 'llama-3.3-70b-versatile'),
        messages=[{'role':'user','content':'ping'}],
        max_tokens=16,
    )
    print('ready')
except Exception as e:
    print('blocked')
"@ 2>&1
    return ($out -match 'ready')
}

Log "Waiting for Groq TPD to clear..."
$maxWaitMin = 120
$waited = 0
while (-not (Test-GroqReady)) {
    if ($waited -ge $maxWaitMin) {
        Log "Gave up after ${maxWaitMin}m; Groq still blocked."
        exit 1
    }
    Start-Sleep -Seconds 300
    $waited += 5
    Log "Still waiting... (${waited}m)"
}

Log "Groq ready. Starting June catch-up."
$env:MAX_ARTICLES_PER_RUN = "10"

# Power/grid priority dates first, then remaining month
$dates = @(
    "2026-06-07", "2026-06-10", "2026-06-18", "2026-06-24",
    "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
    "2026-06-06", "2026-06-08", "2026-06-09", "2026-06-11", "2026-06-12",
    "2026-06-14", "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-19",
    "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-25", "2026-06-26",
    "2026-06-28", "2026-06-29"
)

foreach ($d in $dates) {
    if (-not (Test-GroqReady)) {
        Log "Groq blocked before $d — stopping batch."
        break
    }
    Log "Reprocessing $d ..."
    python -m src.main daily-reprocess --from $d --to $d --fresh 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) {
        Log "Warning: daily-reprocess $d exit code $LASTEXITCODE"
    }
}

Log "Regenerating monthly report..."
python -m src.main monthly --year 2026 --month 6 --no-cleanup 2>&1 | Tee-Object -FilePath $log -Append
python scripts/post_reprocess_status.py 2>&1 | Tee-Object -FilePath $log -Append
Log "Done."
