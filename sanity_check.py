import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure UTF-8 stdout encoding on Windows
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

QUESTION = "How do I add a YouTube video?"

SYSTEM_PROMPT = (
    "You are OptiBot, the customer-support bot for OptiSigns.com.\n"
    "\u2022 Tone: helpful, factual, concise.\n"
    "\u2022 Only answer using the uploaded docs.\n"
    "\u2022 Max 5 bullet points; else link to the doc.\n"
    "\u2022 Cite up to 3 \"Article URL:\" lines per reply."
)


def run_sanity_check() -> int:
    gemini_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not gemini_key and not openai_key:
        print("Error: GEMINI_API_KEY or OPENAI_API_KEY is not set.")
        return 1

    print("==================================================")
    print(f"QUERY: {QUESTION}")
    print("==================================================")

    if gemini_key and not str(gemini_key).startswith("sk-"):
        from ai.gemini_sync import GeminiSync

        sync = GeminiSync(api_key=gemini_key)
        store_name = sync.get_or_create_vector_store()
        answer = sync.ask(QUESTION, store_name=store_name)
        print(answer)
        print("==================================================")

    elif openai_key or (gemini_key and str(gemini_key).startswith("sk-")):
        key = openai_key or gemini_key
        from openai import OpenAI

        client = OpenAI(api_key=key)
        stores = client.beta.vector_stores.list()
        store_id = stores.data[0].id if stores.data else None

        if store_id:
            assistant = client.beta.assistants.create(
                name="OptiBot-Verification",
                instructions=SYSTEM_PROMPT,
                model="gpt-4o-mini",
                tools=[{"type": "file_search"}],
                tool_resources={"file_search": {"vector_store_ids": [store_id]}},
            )
            thread = client.beta.threads.create(
                messages=[{"role": "user", "content": QUESTION}]
            )
            run = client.beta.threads.runs.create_and_poll(
                thread_id=thread.id, assistant_id=assistant.id
            )
            messages = client.beta.threads.messages.list(thread_id=thread.id)
            print(messages.data[0].content[0].text.value)
            print("==================================================")

    return 0


if __name__ == "__main__":
    sys.exit(run_sanity_check())
