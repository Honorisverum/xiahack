import json
import logging
import os
from dataclasses import dataclass
from typing import Annotated, Any

from dotenv import load_dotenv
from langchain_xai import ChatXAI
from pydantic import BaseModel, Field

from livekit import agents
from livekit.agents import AgentSession, Agent, ChatMessage, ChatContext, room_io, function_tool, RunContext
from livekit.agents.llm import ChatContent  # noqa
from livekit.plugins import openai, silero
from livekit.plugins.turn_detector.english import EnglishModel as EnglishTurnDetector


class DebateChatMessage(ChatMessage):
    """ChatMessage with speaker attribution for multi-agent debate."""
    speaker: str = "user"  # persona name or "user"

DebateChatMessage.model_rebuild()

load_dotenv(".env")

VOICES = ["Ara", "Rex", "Sal", "Eve", "Una", "Leo"]

AGENT_INSTRUCTIONS = """
You are {persona_name} participating in a debate on: "{topic}"

Your role
```
{persona_prompt}
```

Other participants: {other_personas}

Rules:
- Respond briefly (max 1 sentences)
- Stay in character
- Address others by name when responding to them
- Keep your unique position and come up with smart arguments against other participants.

## Formatting Rules
- before each other participant's response, you will see the speaker's name in the following format: "$speaker_name says$". 
Does't mention it in your response, it is just hidden info. Don't add to your reply.
"""

REPLY_INSTRUCTIONS = """
Continue the debate:
- Respond to the previous speaker's point
- Bring a fresh perspective based on your role
- Be constructive but challenge ideas
"""

TURN_TOOL_DESCRIPTION = """
Transition to the next speaker. Choose based on:
1. Who hasn't spoken recently
2. Who might have opposing view
3. Give user a chance to participate
"""


@dataclass
class Persona:
    """A debate persona with a unique perspective."""
    name: str
    prompt: str


class PersonaSchema(BaseModel):
    name: str = Field(description="Short unique name for the persona (1-2 words)")
    prompt: str = Field(description="Brief description of persona's worldview and debate style (1-2 sentences)")


class DebatePersonasSchema(BaseModel):
    personas: list[PersonaSchema] = Field(description="List of debate personas")


def generate_debating_personas(topic: str, n_agents: int) -> list[Persona]:
    """Generate debate personas using LLM with structured output."""
    result: DebatePersonasSchema = ChatXAI(
        model="grok-4-1-fast-reasoning-latest",
        xai_api_key=os.environ.get("XAI_API_KEY"),
    ).with_structured_output(DebatePersonasSchema).with_retry(stop_after_attempt=3).invoke(
        f"Generate {n_agents} diverse debate personas for the topic: '{topic}'. "
        f"Each persona should have a distinct perspective that creates interesting debate dynamics. "
        f"Make them varied: some optimistic, some critical, some pragmatic, etc."
    )
    return [Persona(name=p.name, prompt=p.prompt) for p in result.personas]


### ============================================================ ###


class DebateAgent(Agent):
    def __init__(
        self,
        topic: str,
        persona: Persona,
        all_personas: list[Persona],
        session: AgentSession,
        first: bool = False,
    ):
        self.topic = topic
        self.persona = persona
        self.all_personas = all_personas
        self._session = session
        self.first = first

        super().__init__(
            instructions=AGENT_INSTRUCTIONS.format(
                persona_name=persona.name,
                topic=topic,
                persona_prompt=persona.prompt,
                other_personas=", ".join([p.name for p in all_personas if p.name != persona.name]) + ", and User",
            ),
            tts=openai.TTS(
                base_url="https://api.x.ai/v1",
                api_key=os.environ.get("XAI_API_KEY"),
                voice=VOICES[all_personas.index(persona) % len(VOICES)],
                model="tts-1",
            ),
        )

    def _reformat_history(self, chat_ctx: ChatContext) -> ChatContext:
        """Reformat history so current agent sees others as 'user' role. Returns a copy."""
        formatted = chat_ctx.copy()
        for i, item in enumerate(formatted.items):
            if not isinstance(item, DebateChatMessage):
                continue
            is_self = item.speaker == self.persona.name
            content = item.content[0] if item.content else ""
            if not is_self:
                content = f"*{item.speaker} says* {content}"
            formatted.items[i] = DebateChatMessage(
                **{**item.model_dump(), "role": "assistant" if is_self else "user", "content": [content]}
            )
        return formatted

    async def on_enter(self):
        await self.update_chat_ctx(self._reformat_history(self._session.history))
        print(self.chat_ctx.items)
        if self.first:
            await self._session.generate_reply(
                instructions=f"Introduce yourself briefly and share your opening position on: {self.topic}"
            )
        else:
            await self._session.generate_reply(instructions=REPLY_INSTRUCTIONS)

        await self._session.generate_reply(
            tool_choice={"type": "function", "function": {"name": "give_turn_to_next_speaker"}},
            instructions="Now decide who should speak next.",
        )

    async def on_user_turn_completed(self, turn_ctx, new_message):
        await self._session.generate_reply(
            tool_choice={"type": "function", "function": {"name": "give_turn_to_next_speaker"}},
            instructions="User just spoke. Decide who should respond.",
        )

    @function_tool(name="give_turn_to_next_speaker", description=TURN_TOOL_DESCRIPTION)
    async def next_speaker(
        self,
        context: RunContext,
        speaker: Annotated[str, "Name of next speaker: one of the other participants or 'user'"],
    ):
        if speaker.lower() == "user":
            self._session.say("What do you think?")
            return None

        for p in self.all_personas:
            if p.name.lower() == speaker.lower():
                return DebateAgent(
                    topic=self.topic,
                    persona=p,
                    all_personas=self.all_personas,
                    session=self._session,
                )

        # fallback: stay as current
        return None


server = agents.AgentServer()


@server.rtc_session()
async def entrypoint(ctx: agents.JobContext):
    metadata: dict[str, Any] = json.loads(ctx.job.metadata or '{}')
    topic = metadata.get("topic", "What is the best way to solve global warming?")
    n_agents = metadata.get("n_agents", 2)

    logging.info(f"Starting session with {topic=} and {n_agents=}")
    personas = generate_debating_personas(topic, n_agents)
    for i, p in enumerate(personas, 1):
        logging.info(f"  Persona {i}: {p.name} — {p.prompt[:80]}...")

    session = AgentSession(
        llm=openai.LLM.with_x_ai(model="grok-4-1-fast-non-reasoning"),
        stt=openai.STT(
            base_url="https://api.x.ai/v1",
            api_key=os.environ.get("XAI_API_KEY"),
            model="whisper-1",
        ),
        vad=silero.VAD.load(),
        turn_detection=EnglishTurnDetector(),
    )

    @session.on("conversation_item_added")
    def conversation_item_added(ev: agents.ConversationItemAddedEvent):
        agent: DebateAgent = session.current_agent
        speaker = agent.persona.name if ev.item.role == "assistant" else "user"
        session.history.items[-1] = DebateChatMessage(**ev.item.model_dump(), speaker=speaker)

    await session.start(
        room=ctx.room,
        agent=DebateAgent(
            topic=topic,
            persona=next(iter(personas)),
            all_personas=personas,
            session=session,
            first=True,
        ),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(noise_cancellation=True),
        ),
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
