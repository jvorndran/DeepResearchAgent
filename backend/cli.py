"""
Simple CLI for testing the Deep Research Agent orchestrator.

Run with: python backend/cli.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
from agents.orchestrator import run_research

# Load environment variables
load_dotenv()


def check_api_keys():
    """Check if required API keys are set."""
    missing = []

    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")

    if not os.getenv("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")

    if missing:
        print("❌ Missing required API keys:")
        for key in missing:
            print(f"   - {key}")
        print("\nSet them in your .env file or export them:")
        print("   export GOOGLE_API_KEY=your_key")
        print("   export OPENAI_API_KEY=your_key")
        return False

    return True


async def run_query(query: str, job_id: str):
    """Run a query through the orchestrator."""
    print("\n🤖 Orchestrator is working...\n")

    result = await run_research(query=query, job_id=job_id)

    print("="*60)
    if result['status'] == 'completed':
        print("✅ COMPLETED")
        print("="*60)
        print(result.get('response', 'No response'))
    else:
        print("❌ FAILED")
        print("="*60)
        print(f"Error: {result.get('error')}")
    print("="*60 + "\n")


async def main():
    """Main CLI loop."""
    print("\n" + "="*60)
    print("  Deep Research Agent - Interactive CLI")
    print("="*60 + "\n")

    # Check API keys
    if not check_api_keys():
        sys.exit(1)

    print("✅ API keys loaded")
    print("\nType your research query and press Enter.")
    print("Type 'exit' or 'quit' to stop.\n")

    job_counter = 1

    while True:
        try:
            # Get user input
            query = input("\n💬 Query: ").strip()

            # Check for exit
            if query.lower() in ['exit', 'quit', 'q']:
                print("\n👋 Goodbye!\n")
                break

            # Skip empty queries
            if not query:
                continue

            # Generate job ID
            job_id = f"cli-{job_counter:03d}"
            job_counter += 1

            # Run the query
            await run_query(query, job_id)

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!\n")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
