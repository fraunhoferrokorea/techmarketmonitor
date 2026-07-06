# Reprocess the 5 most recent daily reports with current filter rules (Groq-aware).
$ErrorActionPreference = "Continue"
Set-Location "c:\Users\Admin\Documents\python-project"

$log = "output/regen_recent5_filter_rule.log"
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

function Get-DbCount($d) {
    return [int](python -c "from datetime import date; from src.storage import DailyLogStore; from src.config import load_settings; s=load_settings(); print(DailyLogStore(s.database_path).count_for_date(date.fromisoformat('$d')))")
}

Log "Applying no-LLM refilter to all existing daily dates (2026-06-21..2026-07-03)..."
python -m src.main daily-refilter --from 2026-06-21 --to 2026-07-03 2>&1 | Tee-Object -FilePath $log -Append

$dates = @(
    "2026-07-03",
    "2026-07-02",
    "2026-06-29",
    "2026-06-28",
    "2026-06-27"
)

foreach ($d in $dates) {
    while (-not (Test-GroqReady)) {
        Log "Groq blocked before $d — waiting 5m..."
        Start-Sleep -Seconds 300
    }

    $count = Get-DbCount $d
    if ($count -ge 30) {
        Log "Skip LLM reprocess for $d — already has $count stored rows."
        continue
    }

    if ($count -gt 0) {
        Log "Resume reprocess $d ($count rows in DB)..."
        python -m src.main daily-reprocess --from $d --to $d 2>&1 | Tee-Object -FilePath $log -Append
    } else {
        Log "Fresh reprocess $d ..."
        python -m src.main daily-reprocess --from $d --to $d --fresh 2>&1 | Tee-Object -FilePath $log -Append
    }

    if ($LASTEXITCODE -ne 0) {
        Log "Warning: daily-reprocess $d exit code $LASTEXITCODE"
    }
}

python scripts/post_reprocess_status.py 2>&1 | Tee-Object -FilePath $log -Append
Log "Recent-5 batch done."
