"""
Research Agent using xai_sdk.

Flow: problem → thinking → done (1 take + 1 image)
"""
import asyncio
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Optional

from dotenv import load_dotenv

from xai_sdk import AsyncClient
from xai_sdk.chat import user, system
from xai_sdk.tools import web_search

load_dotenv()


class EventType(Enum):
    SEARCHING = "searching"
    PROCESSING_DATA = "processing_data"
    DONE = "done"
    ERROR = "error"


@dataclass
class AgentEvent:
    type: EventType
    data: dict


RESEARCH_SYSTEM = """You are a research agent. Use web_search to find info. Max 1 search.

Find the SINGLE most surprising, counterintuitive, or impactful insight.

Output JSON:
{
  "take": "One powerful sentence - the juiciest finding",
  "explanation": "2-3 sentences why this matters",
  "image_prompt": "MUST include: specific numbers/data from the take, comparison (before/after, old/new, X vs Y), visual metaphor. Format: 'Infographic: [specific data point] shown as [visual element]. Include [chart type] comparing [A] to [B]. Style: clean white background, bold accent color, large typography for key number, minimal text labels.'"
}"""


def extract_json(text: str) -> Optional[dict]:
    """Extract JSON from text."""
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


async def research_agent(problem: str) -> AsyncGenerator[AgentEvent, None]:
    """
    Research agent: problem → thinking → done (1 take + 1 image)
    """
    client = AsyncClient()
    
    try:
        # ═══════════════════════════════════════════════════════════════
        # STEP 1: searching (1 web_search call)
        # ═══════════════════════════════════════════════════════════════
        yield AgentEvent(EventType.SEARCHING, {})
        
        async def do_search():
            chat = client.chat.create(
                model="grok-4-1-fast-non-reasoning",
                messages=[system(RESEARCH_SYSTEM), user(problem)],
                tools=[web_search(enable_image_understanding=False)],
                include=["web_search_call_output"],
                temperature=0.7,
            )
            return await chat.sample()
        
        # Run 3 in parallel, take fastest
        tasks = [asyncio.create_task(do_search()) for _ in range(3)]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        
        # Cancel the rest
        for task in pending:
            task.cancel()
        
        response = done.pop().result()
        
        yield AgentEvent(EventType.PROCESSING_DATA, {})
        
        result = extract_json(response.content) or {}

        # ═══════════════════════════════════════════════════════════════
        # STEP 2: done (generate image + return)
        # ═══════════════════════════════════════════════════════════════
        image_url = None
        image_prompt = result.get("image_prompt", f"Infographic: {problem}")
        try:
            img = await client.image.sample(prompt=image_prompt, model="grok-2-image-1212")
            image_url = img.url
        except Exception:
            pass
        
        yield AgentEvent(EventType.DONE, {
            "take": result.get("take", ""),
            "explanation": result.get("explanation", ""),
            "image_url": image_url,
        })
        
    except Exception as e:
        yield AgentEvent(EventType.ERROR, {"error": str(e)})
        raise
    finally:
        await client.close()


async def main():
    import sys
    
    problem = sys.argv[1] if len(sys.argv) > 1 else "What are the latest breakthroughs in nuclear fusion energy?"
    
    print(f"\nProblem: {problem}\n")
    
    async for event in research_agent(problem):
        match event.type:
            case EventType.SEARCHING:
                print("✓ SEARCHING")
            
            case EventType.PROCESSING_DATA:
                print("✓ PROCESSING_DATA")
            
            case EventType.DONE:
                print("✓ DONE\n")
                print(f"🔥 {event.data.get('take')}\n")
                print(f"{event.data.get('explanation')}\n")
                if event.data.get("image_url"):
                    print(f"🖼  {event.data['image_url']}")
            
            case EventType.ERROR:
                print(f"❌ {event.data.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
