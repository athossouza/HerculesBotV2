# Hercules Motores Bot

A production-ready conversational system using **Agno** (Phidata) and **OpenAI** to manage technical support flows with strict "hard dialog" gating.

## Project Structure

- `main.py`: FastAPI application entry point.
- `workflow.py`: Core Agno Workflow and State Machine logic.
- `llm.py`: OpenAI Structured Outputs integration for Intent and Guardrails.
- `validators.py`: Logic for validation (password, serial number).
- `architecture.mermaid`: State machine diagram.

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment**:
   Set your OpenAI API Key:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

## Running the API

Start the server using `uvicorn`:

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.

## Testing with CURL

**1. General Support:**
```bash
curl -X POST "http://localhost:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{"session_id": "test1", "message": "preciso de ajuda tecnica geral"}'
```

**2. Restricted Flow (Winding Data):**
```bash
curl -X POST "http://localhost:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{"session_id": "test2", "message": "preciso de dados de bobinagem"}'
```

**3. Provide Password (102938):**
```bash
curl -X POST "http://localhost:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{"session_id": "test2", "message": "102938"}'
```

**4. Provide Serial (19 digits):**
```bash
curl -X POST "http://localhost:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{"session_id": "test2", "message": "1234567893123456789"}'
```

## Local Testing (No Server)

Run the included test script to verify logic directly in the terminal:

```bash
python test_local.py
```
