
import asyncio
import os
from smp.client import SMPClient
from smp.agent import CodingAgent, _GeminiBackend

# Mock the Gemini backend to avoid real API calls
class MockGeminiBackend:
    def __init__(self, api_key="mock", model="mock-model"):
        self._model = model
    def generate(self, system_prompt, user_prompt):
        # Simply return a dummy modification
        return "# Mocked edit\ndef mocked_function():\n    pass\n"

async def test_agent_workflow():
    async with SMPClient("http://localhost:8420") as client:
        agent = CodingAgent(client)
        # Manually inject mock LLM
        agent._llm = MockGeminiBackend()
        
        test_file = "smp/demo/agent_test_file.py"
        os.makedirs("smp/demo", exist_ok=True)
        with open(test_file, "w") as f:
            f.write("def original():\n    pass\n")
            
        print(f"--- Running agent on {test_file} ---")
        result = await agent.run(
            file_path=test_file,
            instruction="Add a mocked function",
        )
        
        print("\n=== Agent Result ===")
        print(f"Summary: {result.summary}")
        print(f"Edited Content:\n{result.edited_content}")
        print(f"Nodes synced: {result.nodes_synced}")
        
        # Cleanup
        if os.path.exists(test_file):
            os.remove(test_file)

if __name__ == "__main__":
    asyncio.run(test_agent_workflow())
