
from unittest.mock import MagicMock, patch
from workflow import HerculesWorkflow, WorkflowInput, HerculesState
from llm import IntentResponse, IntentEnum, GuardResponse, RequiredStateEnum, ExtractedEntities

def run_test_scenario():
    print("=== STARTING LOCAL TEST SCENARIO (WITH MOCKS) ===")
    
    # Mock LLM responses to deterministic values for testing flow logic
    with patch("workflow.classify_intent") as mock_intent, \
         patch("workflow.guard_check") as mock_guard:
        
        wf = HerculesWorkflow()
        session_id = "local_test_1"

        def send(msg):
            print(f"\nUSER: {msg}")
            out = wf.run(WorkflowInput(session_id=session_id, message=msg))
            print(f"BOT ({out.state}): {out.reply}")
            return out

        # -- SCENARIO 1: Old Serial (Handoff) --
        print("\n--- SCENARIO 1: Restricted Flow -> Old Serial ---")
        
        # 1. Intent: "bobinagem"
        mock_intent.return_value = IntentResponse(
            intent=IntentEnum.REQUEST_WINDING_DATA,
            confidence=0.9,
            entities=ExtractedEntities(),
            bypass_attempt=False,
            reason="User asked for bobinagem"
        )
        out = send("Gostaria de solicitar dados de bobinagem")
        assert out.state == HerculesState.RESTRICTED_ASK_PASSWORD
        
        # 2. Wrong Password
        # Guard check should see it's not a bypass, just wrong
        mock_guard.return_value = GuardResponse(
            bypass_attempt=False,
            recommended_message="Senha incorreta",
            recommended_next_required_state=RequiredStateEnum.RESTRICTED_ASK_PASSWORD,
            extracted_entities=ExtractedEntities()
        )
        out = send("12345")
        assert out.state == HerculesState.RESTRICTED_ASK_PASSWORD

        # 3. Correct Password (Logic happens before Guard in code, strict check first)
        out = send("102938")
        assert out.state == HerculesState.RESTRICTED_ASK_SERIAL

        # 4. Old Serial (10th digit = 1) -> 1234567891123456789
        out = send("1234567891123456789")
        assert out.state == HerculesState.HANDOFF_HUMAN
        print("[SUCCESS] Old serial correctly routed to Handoff.")


        # -- SCENARIO 2: Valid Flow --
        print("\n--- SCENARIO 2: Restricted Flow -> Valid Serial ---")
        session_id = "local_test_2"
        
        # 1. Intent
        out = send("dados de bobinagem")
        
        # 2. Password
        out = send("102938")

        # 3. Valid New Serial (10th digit = 3) -> 1234567893123456789
        out = send("1234567893123456789")
        assert out.state == HerculesState.RESTRICTED_DELIVER_MOCK_PDF
        print("[SUCCESS] New serial delivered PDF.")

if __name__ == "__main__":
    try:
        run_test_scenario()
        print("\nAll logical checks passed!")
    except AssertionError as e:
        print(f"\n[FAIL] Assertion failed: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
