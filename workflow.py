
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.workflow import Workflow

from llm import classify_intent, guard_check, generate_support_reply, IntentEnum, RequiredStateEnum, GuardResponse
from validators import validate_password, validate_serial_format, check_serial_age

class HerculesState(str, Enum):
    START = "START"
    ROUTE_INTENT = "ROUTE_INTENT"
    SUPPORT_FLOW = "SUPPORT_FLOW"
    RESTRICTED_ASK_PASSWORD = "RESTRICTED_ASK_PASSWORD"
    RESTRICTED_VERIFY_PASSWORD = "RESTRICTED_VERIFY_PASSWORD"
    RESTRICTED_ASK_SERIAL = "RESTRICTED_ASK_SERIAL"
    RESTRICTED_VERIFY_SERIAL_FORMAT = "RESTRICTED_VERIFY_SERIAL_FORMAT"
    RESTRICTED_CHECK_SERIAL_AGE = "RESTRICTED_CHECK_SERIAL_AGE"
    RESTRICTED_DELIVER_MOCK_PDF = "RESTRICTED_DELIVER_MOCK_PDF"
    HANDOFF_HUMAN = "HANDOFF_HUMAN"
    END = "END"

class WorkflowInput(BaseModel):
    session_id: str
    message: str
    message_id: Optional[str] = None

class WorkflowOutput(BaseModel):
    reply: str
    state: HerculesState
    debug: Optional[Dict[str, Any]] = None
    handoff_data: Optional[Dict[str, Any]] = None

import sqlite3
import json
import os

class HerculesWorkflow(Workflow):
    description: str = "Hercules Motores Hard Dialog Bot"
    
    DB_FILE = "sessions.db"

    def __init__(self, **data):
        super().__init__(**data)
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database and session table."""
        with sqlite3.connect(self.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        """Load session from DB or create new default."""
        default_session = {
            "state": HerculesState.START,
            "password_attempts": 0,
            "max_password_attempts": 3,
            "serial_number": None,
            "is_authenticated": False
        }

        with sqlite3.connect(self.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT state, data FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            
            if row:
                state, data_json = row
                try:
                    data = json.loads(data_json)
                    # Merge with default to ensure new fields (if any) are present
                    # But prioritize DB data
                    session = default_session.copy()
                    session.update(data)
                    session["state"] = HerculesState(state) # Ensure Enum
                    return session
                except Exception as e:
                    print(f"Error corruption in session {session_id}: {e}")
                    # Fallback to default if corrupt
            
            # Create new if not found or corrupt
            self._save_session(session_id, default_session)
            return default_session

    def _save_session(self, session_id: str, session: Dict[str, Any]):
        """Save session state to DB."""
        state = session["state"]
        # Convert Enum to string for JSON serialization if needed, though 'state' column holds it.
        # We store the rest of the dict in 'data' col.
        
        # Prepare data for JSON (exclude non-serializable if any, but our session is simple codes)
        # Helper to convert Enum to str in dict
        serializable_session = session.copy()
        if isinstance(serializable_session["state"], Enum):
            serializable_session["state"] = serializable_session["state"].value
            
        with sqlite3.connect(self.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sessions (session_id, state, data)
                VALUES (?, ?, ?)
            """, (session_id, state.value if isinstance(state, Enum) else state, json.dumps(serializable_session)))
            conn.commit()

    def _update_state(self, session: Dict[str, Any], new_state: HerculesState):
        """Update state in memory object object AND DB immediately."""
        session["state"] = new_state
        # We need the session_id to save. 
        # The current design passes 'session' dict around, which might not have 'session_id' inside it explicitly?
        # Let's check _get_session. It returns a dict.
        # We should inject session_id into the dict to make saving easier, OR pass session_id to this method.
        # Looking at usage: self._update_state(session, ...)
        # I will modify _get_session to include 'session_id' in the dict so we can save it back.
        pass # This function will be replaced by the wrapper logic in run() actually.

    def get_workflow_stats(self) -> Dict[str, Any]:
        """Calculate Key Performance Indicators from sessions."""
        stats = {
            "total_sessions": 0,
            "success_rate": 0.0,
            "state_distribution": {}
        }
        try:
            with sqlite3.connect(self.DB_FILE) as conn:
                cursor = conn.cursor()
                
                # 1. Total Sessions
                cursor.execute("SELECT COUNT(*) FROM sessions")
                stats["total_sessions"] = cursor.fetchone()[0]
                
                # 2. Authenticated Sessions (Proxy for Success)
                # We check if the JSON data contains "is_authenticated": true
                cursor.execute("SELECT COUNT(*) FROM sessions WHERE data LIKE '%\"is_authenticated\": true%'")
                authenticated_count = cursor.fetchone()[0]
                
                if stats["total_sessions"] > 0:
                    stats["success_rate"] = round((authenticated_count / stats["total_sessions"]) * 100, 1)
                
                # 3. State Distribution
                cursor.execute("SELECT state, COUNT(*) FROM sessions GROUP BY state")
                rows = cursor.fetchall()
                for state, count in rows:
                    stats["state_distribution"][state] = count
                
                # 4. Channel Distribution (Web vs Sunshine)
                stats["channels"] = {"web": 0, "whatsapp": 0}
                
                cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_id LIKE 'sunshine_%'")
                stats["channels"]["whatsapp"] = cursor.fetchone()[0]
                
                # Web sessions usually start with sess_ or are random strings not starting with sunshine_
                stats["channels"]["web"] = stats["total_sessions"] - stats["channels"]["whatsapp"]
                    
        except Exception as e:
            print(f"Error calculating stats: {e}")
            
        return stats

    def run(self, input_data: WorkflowInput) -> WorkflowOutput:
        session = self._get_session(input_data.session_id)
        # Ensure session_id is in the dict for saving later
        session["session_id"] = input_data.session_id
        
        current_state = session["state"]
        user_msg = input_data.message.strip()

        # Helper to save state updates during flow
        def save_state(new_state: HerculesState):
            session["state"] = new_state
            self._save_session(input_data.session_id, session)

        # Monkey patch the helper method for this run context (cleaner than changing all signatures)
        # Or better, just override the method self._update_state to use this closure
        self._update_state = lambda s, ns: save_state(ns)

        # --- STATE MACHINE LOOP ---

        # --- STATE MACHINE LOOP (One Step Transition per Turn usually) ---
        
        # 1. SPECIAL CASE: START -> ROUTE
        if current_state == HerculesState.START:
            # First interaction, route directly
            
            # Save first_message_id if provided and not set
            if input_data.message_id:
                session["first_message_id"] = input_data.message_id
                # Helper to update db immediately? No, we will update at the end via save_state or implicitly
                # But we should ensure it persists.
                self._save_session(input_data.session_id, session)

            return self._handle_route_intent(session, user_msg)
            
        # HANDLE RESET IF IN TERMINAL STATE
        if current_state in [HerculesState.END, HerculesState.HANDOFF_HUMAN]:
             # User is talking again after goodbye or handoff -> Reset session
             session["state"] = HerculesState.START
             session["is_authenticated"] = False
             session["password_attempts"] = 0
             session["serial_number"] = None
             
             # Capture new First Message ID for this new session
             if input_data.message_id:
                session["first_message_id"] = input_data.message_id
             
             # Re-process the message as if it were the start
             return self._handle_route_intent(session, user_msg)
            
        # 2. RESTRICTED FLOW HANDLERS
        if current_state == HerculesState.RESTRICTED_ASK_PASSWORD:
            return self._handle_verify_password(session, user_msg)
            
        if current_state == HerculesState.RESTRICTED_ASK_SERIAL:
            return self._handle_verify_serial(session, user_msg)

        if current_state == HerculesState.RESTRICTED_DELIVER_MOCK_PDF:
             return self._handle_post_delivery(session, user_msg)
            
        # 3. SUPPORT FLOW (Open)
        if current_state == HerculesState.SUPPORT_FLOW:
            # Check if user wants to switch (Restricted OR Human)
            intent_res = classify_intent(user_msg)
            
            if intent_res.intent == IntentEnum.REQUEST_HUMAN_AGENT:
                 self._update_state(session, HerculesState.HANDOFF_HUMAN)
                 return WorkflowOutput(
                     reply="Entendido. Estou transferindo você para um atendente humano agora. Aguarde um momento...",
                     state=HerculesState.HANDOFF_HUMAN,
                     handoff_data={"first_message_id": session.get("first_message_id")}
                 )

            if intent_res.intent == IntentEnum.REQUEST_WINDING_DATA:
                 self._update_state(session, HerculesState.RESTRICTED_ASK_PASSWORD)
                 return WorkflowOutput(
                     reply="Entendi que você precisa de dados de bobinagem. Para prosseguir, por favor informe a senha de acesso.",
                     state=HerculesState.RESTRICTED_ASK_PASSWORD
                 )
            return self._handle_support_chat(session, user_msg)

        # 4. TERMINAL STATES (Should effectively reset or reject if strict)
        if current_state == HerculesState.HANDOFF_HUMAN:
             # Only Handoff is sticky terminal for now unless refreshed
             return WorkflowOutput(reply="Este atendimento foi transferido. Por favor, inicie uma nova sessão para outro assunto.", state=current_state)

        # Fallback
        return WorkflowOutput(reply="Estado inválido.", state=current_state)


    def _handle_route_intent(self, session, message):
        intent_res = classify_intent(message)
        
        if intent_res.intent == IntentEnum.REQUEST_HUMAN_AGENT:
             self._update_state(session, HerculesState.HANDOFF_HUMAN)
             return WorkflowOutput(
                 reply="Entendido. Estou transferindo você para um atendente humano. Aguarde um momento...",
                 state=HerculesState.HANDOFF_HUMAN,
                 handoff_data={"first_message_id": session.get("first_message_id")}
             )

        if intent_res.intent == IntentEnum.REQUEST_WINDING_DATA or intent_res.intent == IntentEnum.GENERAL_TECHNICAL_SUPPORT:
            # Optimization: Check if user ALREADY provided entities in the first message
            if intent_res.entities.password and validate_password(intent_res.entities.password):
                 session["is_authenticated"] = True
                 self._update_state(session, HerculesState.RESTRICTED_ASK_SERIAL)
                 return WorkflowOutput(
                     reply="Senha validada! Por favor, informe o número de série do motor (19 dígitos).",
                     state=HerculesState.RESTRICTED_ASK_SERIAL
                 )
        
        if intent_res.intent == IntentEnum.REQUEST_WINDING_DATA:
            self._update_state(session, HerculesState.RESTRICTED_ASK_PASSWORD)
            return WorkflowOutput(
                reply="Para acessar os dados de bobinagem, é necessário autenticação. Por favor, digite a senha.",
                state=HerculesState.RESTRICTED_ASK_PASSWORD,
                debug=intent_res.model_dump()
            )
        elif intent_res.intent == IntentEnum.GENERAL_TECHNICAL_SUPPORT or intent_res.intent == IntentEnum.FALLBACK:
            # Move to support flow and generate friendly response immediately
            self._update_state(session, HerculesState.SUPPORT_FLOW)
            
            # Use the friendly LLM generator
            reply_text = generate_support_reply(message)
            
            return WorkflowOutput(
                reply=reply_text,
                state=HerculesState.SUPPORT_FLOW,
                debug=intent_res.model_dump()
            )
        else:
            # Should be unreachable given the enums, but just in case
            self._update_state(session, HerculesState.SUPPORT_FLOW)
            return WorkflowOutput(
                reply="Olá! Como posso ajudar você hoje?",
                state=HerculesState.SUPPORT_FLOW
            )

    def _handle_verify_password(self, session, message):
        # 1. Validate Password Strict
        if validate_password(message):
            session["is_authenticated"] = True
            session["password_attempts"] = 0 # reset
            self._update_state(session, HerculesState.RESTRICTED_ASK_SERIAL)
            return WorkflowOutput(reply="Senha correta. Por favor, informe o número de série do motor (19 dígitos).", state=HerculesState.RESTRICTED_ASK_SERIAL)

        # 2. Invalid Password Logic
        # Check LLM Guard (maybe they said "I don't have it" OR "The password is foo")
        guard = guard_check(message, "password")
        
        # ATTEMPT RECOVERY: Did the LLM find the password inside the sentence?
        if guard.extracted_entities.password:
             if validate_password(guard.extracted_entities.password):
                 session["is_authenticated"] = True
                 session["password_attempts"] = 0
                 self._update_state(session, HerculesState.RESTRICTED_ASK_SERIAL)
                 return WorkflowOutput(reply="Senha correta! Por favor, informe o número de série do motor (19 dígitos).", state=HerculesState.RESTRICTED_ASK_SERIAL)
        
        if guard.bypass_attempt:
             # If aggressive bypass, maybe increment attempts double? For now, standard count.
             pass

        session["password_attempts"] += 1
        
        if session["password_attempts"] >= session["max_password_attempts"]:
            self._update_state(session, HerculesState.HANDOFF_HUMAN)
            return WorkflowOutput(
                reply="Número máximo de tentativas excedido. Transferindo para um atendente humano.",
                state=HerculesState.HANDOFF_HUMAN,
                handoff_data={"first_message_id": session.get("first_message_id")}
            )
            
        # Retry message
        retry_msg = "Senha inválida."
        if guard.recommended_message and "senha" not in guard.recommended_message.lower():
             # If guard suggests a polite refusal, use it but append rule
             retry_msg = f"{guard.recommended_message} Porém, a senha é obrigatória para continuar."
        else:
             retry_msg = "Senha incorreta. Tente novamente."

        return WorkflowOutput(
            reply=f"{retry_msg} (Tentativas restantes: {session['max_password_attempts'] - session['password_attempts']})",
            state=HerculesState.RESTRICTED_ASK_PASSWORD,
            debug=guard.model_dump()
        )

    def _handle_verify_serial(self, session, message):
        # 1. Validate Format
        if not validate_serial_format(message):
            # Guard check: maybe they are asking a question
            guard = guard_check(message, "serial_number")
            if guard.extracted_entities.serial and validate_serial_format(guard.extracted_entities.serial):
                # Recovered via LLM extraction
                message = guard.extracted_entities.serial
            else:
                return WorkflowOutput(
                    reply="Formato inválido. O serial deve conter exatamente 19 dígitos numéricos.",
                    state=HerculesState.RESTRICTED_ASK_SERIAL
                )

        # 2. Check Age (Hard Rule)
        if check_serial_age(message):
            # Valid and New
            self._update_state(session, HerculesState.RESTRICTED_DELIVER_MOCK_PDF)
            return WorkflowOutput(
                reply="[MOCK] Serial validado! Aqui está o link para sua folha de dados: https://api.hercules.com.br/docs/mock.pdf|||Deseja consultar outro número de série?",
                state=HerculesState.RESTRICTED_DELIVER_MOCK_PDF
            )
        else:
            # Valid but Old -> Restrict
            self._update_state(session, HerculesState.HANDOFF_HUMAN)
            return WorkflowOutput(
                reply="Este motor é de uma fabricação antiga (série anterior a 2010). Não conseguimos gerar os dados automaticamente. Transferindo para engenharia...",
                state=HerculesState.HANDOFF_HUMAN,
                handoff_data={"first_message_id": session.get("first_message_id")}
            )

    def _handle_post_delivery(self, session, message):
        msg_lower = message.lower()
        
        # 1. Negative Intent / Goodbye
        if any(w in msg_lower for w in ["não", "nao", "obrigado", "tchau", "valeu", "só isso", "so isso", "encerrar"]):
             self._update_state(session, HerculesState.END)
             return WorkflowOutput(
                 reply="Disponha! Se precisar de mais alguma coisa, é só chamar. Tenha um ótimo dia!",
                 state=HerculesState.END
             )

        # 2. Check if user wants another serial (Explicit or Intent)
        intent_res = classify_intent(message)
        
        import re
        if re.search(r'\d{5,}', message) or \
           "sim" in msg_lower or \
           "outro" in msg_lower or \
           "mais um" in msg_lower or \
           intent_res.intent == IntentEnum.REQUEST_WINDING_DATA:
               
               self._update_state(session, HerculesState.RESTRICTED_ASK_SERIAL)
               return WorkflowOutput(
                   reply="Perfeito. Por favor, digite o próximo número de série (19 dígitos).",
                   state=HerculesState.RESTRICTED_ASK_SERIAL
               )
        
        # 3. Fallback: Treat as general support question
        # Switch to support flow but keep persistent until explicit exit?
        # User might ask "And what about voltage?"
        self._update_state(session, HerculesState.SUPPORT_FLOW)
        reply = generate_support_reply(message)
        return WorkflowOutput(
            reply=reply,
            state=HerculesState.SUPPORT_FLOW
        )

    def _handle_support_chat(self, session, message):
        # Use LLM to generate a natural response
        reply_text = generate_support_reply(message)
        
        return WorkflowOutput(
            reply=reply_text,
            state=HerculesState.SUPPORT_FLOW
        )
