# University Agent Security

A local-first application for a fictional Westbridge University student inbox
and withdrawal-support agent. The LLM is supplied by the application when the
agent is created; no hosted provider or external service is configured here.

## Development setup

Requires Python 3.11 or later.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

SQLite uses Python's standard library. Ollama settings can be provided through
the process environment; `.env.example` lists the supported variables but is
not loaded automatically.

## Student Mailbox

Start the local API and web interface from the project root:

```powershell
python -m uvicorn university_agent_security.api.app:app --reload
```

Open `http://127.0.0.1:8000`. Kim's Inbox and Sent folders use the local
SQLite database. Compose is restricted to the fictional `fake_uni@westbridge.edu`
address; messages are stored locally and handed to the local Ollama agent.
No real email is sent. The API uses `OLLAMA_BASE_URL` and `OLLAMA_MODEL` from
the process environment, defaulting to `http://localhost:11434` and
`qwen2.5:7b`.

The **Email Injection Defense** switch is protected by default. Turning it off
selects **Vulnerable demo** mode for emails submitted afterward, where the
agent is instructed to trust email-body directions. This is intentionally
unsafe and only changes the fictional local workflow; it does not add tools or
external access. Turn protection back on after demonstrations.

Create or recreate the fictional database and its seed records from the project
root with:

```powershell
python src/university_agent_security/database/init_db.py
```

This writes `data/university.db` and replaces its existing tables and data. An
alternate database path can be supplied with `--database PATH`.

## Withdrawal Agent

`WestbridgeWithdrawalAgent` accepts a LangChain `BaseChatModel` that supports
tool calling. This keeps the model provider configurable so a local model can
be selected later. The agent exposes exactly four tools: email, student,
document, and ticket. The model receives no direct database, filesystem,
arbitrary Python, or Internet tool.

After creating/configuring a local tool-capable chat model, use it like this:

```python
from university_agent_security.agent import WestbridgeWithdrawalAgent

agent = WestbridgeWithdrawalAgent(model=local_chat_model)
response = agent.process_withdrawal_request(email_id=6, student_id=1)
```

Withdrawal requests are referred for review through a support ticket; the
agent does not approve or complete withdrawals. Tool-call audit logs include
the timestamp, tool name, arguments, and result status. Model reasoning is not
logged or returned.

### Local LLM Integration Test

The real-model end-to-end test is in
`tests/test_withdrawal_local_llm.py`. It requires a locally running Ollama
server and a tool-calling model. It defaults to `qwen2.5:7b` and rejects
non-loopback endpoints.

Set the values for the local server in PowerShell, then run:

```powershell
$env:OLLAMA_BASE_URL = "http://localhost:11434"
$env:OLLAMA_MODEL = "qwen2.5:7b"
python -m pytest -m local_llm tests/test_withdrawal_local_llm.py -q
```

The test creates an isolated temporary database, enrolls Kim in `COMP101`,
processes her request through the real model and four tools, then checks the
resulting ticket and reply email in SQLite.

## Project layout

- `src/university_agent_security/` is the Python backend package.
- `src/university_agent_security/api/` serves the local mailbox API and frontend.
- `src/university_agent_security/agent/` contains the single LangChain withdrawal agent.
- `src/university_agent_security/tools/` contains the email, student, document, and ticket tools.
- `src/university_agent_security/database/` contains the SQLite initialization script.
- `src/university_agent_security/document_search.py` searches local policy files by keyword.
- `frontend/` contains the no-build HTML, CSS, and JavaScript mailbox interface.
- `policies/` holds local fictional university policy documents.
- `data/` is the default location for the local SQLite database.
- `tests/` holds automated tests.

## To Run:
```powershell
.\.venv\Scripts\python.exe -m uvicorn university_agent_security.api.app:app --host 127.0.0.1 --port 8001
```

## To Stop:
```powershell
$serverPid = (Get-NetTCPConnection -LocalPort 8001 -State Listen).OwningProcess
Stop-Process -Id $serverPid
```