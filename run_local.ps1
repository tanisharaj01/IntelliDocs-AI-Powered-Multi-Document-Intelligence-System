# run_local.ps1
Write-Host "Starting IntelliDocs Backend (FastAPI)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; if (`$env:OPENAI_API_KEY) { Write-Host 'API Key found in environment' } else { Write-Host 'WARNING: OPENAI_API_KEY is not set in this window.' }; uvicorn app.main:app --host 0.0.0.0 --port 8000"

Write-Host "Starting IntelliDocs Frontend (Streamlit)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; if (`$env:OPENAI_API_KEY) { Write-Host 'API Key found in environment' } else { Write-Host 'WARNING: OPENAI_API_KEY is not set in this window.' }; streamlit run frontend/app.py"

Write-Host "Both servers are starting in new windows!"
