
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles # Optional if we use static dir
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import io
import datetime

# from collections import deque # This import is no longer needed if logs_store is imported

# Load environment variables (OPENAI_API_KEY)
load_dotenv()

from workflow import HerculesWorkflow, WorkflowInput
from llm import transcribe_audio
from logger import add_log, logs_store

app = FastAPI(title="Hercules Motores Bot API")
workflow = HerculesWorkflow()

import asyncio

# --- MESSAGE BUFFERING ---
# buffers[session_id] = [msg1, msg2, ...]
# timers[session_id] = asyncio.Task
message_buffers = {}
buffer_timers = {}
# Load delay from .env, default to 2.0 seconds
BUFFER_DELAY = float(os.getenv("BUFFER_DELAY_SECONDS", "2.0")) 


class LogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    metadata: dict = {}

# The local definition of add_log and logs_store are removed as they are now imported.
# logs_store = deque(maxlen=50)
# def add_log(level: str, message: str, metadata: dict = None):
#     entry = {
#         "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
#         "level": level,
#         "message": message,
#         "metadata": metadata or {}
#     }
#     logs_store.append(entry)
#     # Also print to console for development
#     print(f"[{entry['timestamp']}] [{level}] {message}")

@app.get("/api/logs")
async def get_logs():
    return list(logs_store)

@app.post("/api/logs/clear")
async def clear_logs():
    logs_store.clear()
    return {"status": "cleared"}

class ChatRequest(BaseModel):
    session_id: str
    message: str

@app.get("/", response_class=HTMLResponse)
async def get_ui():
    with open("templates/index.html", "r") as f:
        return f.read()

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Main endpoint for the conversational bot.
    Maintains state via session_id.
    """
    try:
        # Wrap input for Agno Workflow
        wf_input = WorkflowInput(
            session_id=request.session_id,
            message=request.message
        )
        add_log("INFO", f"Web Chat Message: {request.message[:50]}...", {"session_id": request.session_id})
        
        # Run workflow step
        output = workflow.run(wf_input)
        
        return {
            "reply": output.reply,
            "state": output.state,
            "debug": output.debug
        }
    except Exception as e:
        # In production, log error properly
        print(f"Error processing request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/voice")
async def voice_endpoint(
    session_id: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Receives an audio file (blob), transcribes it, and runs the workflow.
    """
    try:
        add_log("INFO", "Voice message received", {"session_id": session_id})
        # Read the file
        audio_content = await file.read()
        audio_file = io.BytesIO(audio_content)
        audio_file.name = "voice.webm" # OpenAI needs a filename/extension hint
        
        # Transcribe
        transcribed_text = transcribe_audio(audio_file)
        
        if not transcribed_text:
             return {"reply": "Desculpe, não consegui ouvir nada.", "state": "ERROR", "transcription": ""}

        # Run workflow with transcribed text
        wf_input = WorkflowInput(
            session_id=session_id,
            message=transcribed_text
        )
        add_log("INFO", f"Voice Transcribed: {transcribed_text}", {"session_id": session_id})
        
        output = workflow.run(wf_input)
        
        return {
            "reply": output.reply,
            "state": output.state,
            "debug": output.debug,
            "transcription": transcribed_text
        }
    except Exception as e:
        print(f"Error processing voice: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- SUNSHINE CONVERSATIONS INTEGRATION ---

import requests
from fastapi import Request, BackgroundTasks

# Config (Loaded from .env)
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
SUNSHINE_APP_ID = os.getenv("SUNSHINE_APP_ID")
SUNSHINE_KEY_ID = os.getenv("SUNSHINE_KEY_ID")
SUNSHINE_SECRET = os.getenv("SUNSHINE_SECRET")

def send_sunshine_reply(app_id: str, conversation_id: str, message: str):
    """
    Sends a message back to Sunshine Conversations via Zendesk SC API.
    """
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/sc/v2/apps/{app_id}/conversations/{conversation_id}/messages"
    
    # Split message if using our delimiter '|||'
    messages_to_send = message.split("|||")
    
    for msg_part in messages_to_send:
        payload = {
            "author": {"type": "business"},
            "content": {"type": "text", "text": msg_part.strip()}
        }
        
        try:
            add_log("BOT", f"Sending to Sunshine: {msg_part[:50]}...", {"conversation_id": conversation_id})
            response = requests.post(
                url, 
                json=payload, 
                auth=(SUNSHINE_KEY_ID, SUNSHINE_SECRET),
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
        except Exception as e:
            print(f"Error sending Sunshine reply: {e}")

def pass_control_to_switchboard(app_id: str, conversation_id: str):
    """
    Passes control to the 'next' integration (usually Agent Workspace) via Switchboard.
    """
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/sc/v2/apps/{app_id}/conversations/{conversation_id}/passControl"
    
    payload = {
        "switchboardIntegration": "next"
    }
    
    try:
        add_log("WARN", f"Passing control to Switchboard (Next)", {"conversation_id": conversation_id})
        response = requests.post(
            url,
            json=payload,
            auth=(SUNSHINE_KEY_ID, SUNSHINE_SECRET),
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        print(f"Control passed for conversation {conversation_id}")
    except Exception as e:
        print(f"Error passing control: {e}")

@app.post("/sunshine/webhook")
@app.head("/sunshine/webhook")
async def sunshine_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives webhooks from Sunshine Conversations.
    Supports HEAD for verification.
    """
    if request.method == "HEAD":
        return {"status": "ok"}
        
    try:
        data = await request.json()
        
        events = data.get("events", [])
        for event in events:
            # Handle standard messages
            if event.get("type") == "conversation:message":
                payload = event.get("payload", {})
                conversation = payload.get("conversation", {})
                message = payload.get("message", {})
                author = message.get("author", {})
                
                # Ignore messages from ourselves (business)
                if author.get("type") == "business":
                    continue

                user_id = author.get("userId") # This is the Sunshine User ID
                conversation_id = conversation.get("id")
                
                content = message.get("content", {})
                msg_type = content.get("type")
                text = ""

                if msg_type == "text":
                    text = content.get("text", "")
                elif msg_type == "file" or msg_type == "image":
                    media_url = content.get("mediaUrl")
                    media_type = content.get("mediaType", "")
                    
                    add_log("ZENDESK", f"Recebendo arquivo de áudio/mídia: {media_type}", {"user_id": user_id})
                    
                    if media_url:
                        try:
                            import io
                            file_resp = requests.get(media_url)
                            if file_resp.status_code == 200:
                                file_bytes = io.BytesIO(file_resp.content)
                                file_bytes.name = "audio.ogg"
                                transcription = transcribe_audio(file_bytes)
                                if transcription:
                                    text = transcription
                                    add_log("BOT", f"Áudio transcrito: {text}", {"user_id": user_id})
                                else:
                                    add_log("WARN", "Falha na transcrição ou áudio vazio.")
                            else:
                                add_log("ERROR", f"Falha ao baixar mídia: {file_resp.status_code}")
                        except Exception as e:
                            add_log("ERROR", f"Erro processando mídia: {str(e)}")

                
                add_log("ZENDESK", f"Webhook Message: {text}", {"user_id": user_id, "conversation_id": conversation_id})
                
                if not user_id or not text:
                    continue
                
                # --- BUFFERING LOGIC ---
                session_id = f"sunshine_{user_id}"
                
                # Initialize buffer if needed
                if session_id not in message_buffers:
                    message_buffers[session_id] = []
                
                # Add message to buffer
                message_buffers[session_id].append(text)
                
                # Cancel existing timer
                if session_id in buffer_timers:
                    buffer_timers[session_id].cancel()
                
                # Define processing logic
                async def process_buffered_messages(sid, cid, appid):
                    try:
                        await asyncio.sleep(BUFFER_DELAY)
                        
                        # Get and clear messages
                        msgs = message_buffers.pop(sid, [])
                        if not msgs:
                             return
                        
                        # Combine messages
                        combined_text = " ".join(msgs)
                        add_log("BOT", f"Processing Buffered: {combined_text}", {"session_id": sid, "count": len(msgs)})
                        
                        # Run Workflow (Run in threadpool to avoid blocking loop)
                        from fastapi.concurrency import run_in_threadpool
                        wf_input = WorkflowInput(session_id=sid, message=combined_text)
                        output = await run_in_threadpool(workflow.run, wf_input)
                        
                        # Send Reply
                        await run_in_threadpool(send_sunshine_reply, appid, cid, output.reply)
                        
                        add_log("BOT", f"Replying: {output.reply[:40]}...", {"state": output.state, "conversation_id": cid})

                        # Handle Handoff
                        if output.state.lower() == "handoff_human" or output.state == "HANDOFF_HUMAN":
                             add_log("HANDOFF", "Triggering PassControl to Switchboard", {"conversation_id": cid})
                             await run_in_threadpool(pass_control_to_switchboard, appid, cid)

                    except asyncio.CancelledError:
                        pass # Valid cancellation
                    except Exception as e:
                        print(f"Error processing buffer: {e}")
                        add_log("ERROR", f"Buffer Error: {e}")
                    finally:
                        # cleanup timer ref
                        if sid in buffer_timers:
                            del buffer_timers[sid]

                # Start new timer
                buffer_timers[session_id] = asyncio.create_task(
                    process_buffered_messages(session_id, conversation_id, SUNSHINE_APP_ID)
                )

        return {"status": "ok"}
        
    except Exception as e:
        print(f"Error processing Sunshine webhook: {e}")
        return {"status": "error", "detail": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Allow running directly for testing
    uvicorn.run(app, host="0.0.0.0", port=8000)
