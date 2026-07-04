$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "graph.json")) {
    Write-Host "ERROR: graph.json not found. Run build_graph.py first." -ForegroundColor Red
    exit 1
}

Write-Host "Starting Streamlit demo at http://localhost:8501"
python -m streamlit run app.py
