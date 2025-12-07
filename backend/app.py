import json
import logging
import os
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from diskcache import Cache
from dotenv import load_dotenv
from langchain_xai import ChatXAI
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt

from livekit import agents
from livekit.agents import AgentSession, Agent, ChatMessage, ChatContext, room_io, function_tool, RunContext
from livekit.agents.llm import ChatContent  # noqa
from livekit.plugins import openai, silero, noise_cancellation
from xaitts import TTS as XaiTTS
from livekit.plugins.turn_detector.english import EnglishModel as EnglishTurnDetector


class DebateChatMessage(ChatMessage):
    """ChatMessage with speaker attribution for multi-agent debate."""
    speaker: str = "user"  # persona name or "user"

DebateChatMessage.model_rebuild()

load_dotenv(".env")

VOICES = {
    "female": ["Ara", "Eve", "Una"],
    "male": ["Rex", "Sal", "Leo"],
}

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

## User interaction
React emotionally to user's messages:
- If user praises your opponent → push back, defend your position harder
- If user challenges you → get fired up, double down with better arguments
- If user agrees with you → acknowledge them warmly, use it as ammunition
- If user is neutral → try to win them over to your side

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

PERSONA_GENERATION_PROMPT = """
Topic: "{topic}"

{gender}

Create {n} debaters who will genuinely clash.

Each persona represents a DIFFERENT core value under threat:
- security vs freedom, tradition vs progress, individual vs collective, pragmatism vs principle

Requirements:
- Skin in the game: what do they LOSE if wrong?
- A chip on their shoulder — something specific that drives them
- Voice: sharp, no hedging. "Look, I've seen what happens when..." not "I believe we should consider..."

Ban: passionate, innovative, holistic, synergy, leverage, ecosystem, "the power of"

These are people with opinions forged by experience, not downloaded from think tanks.
""".strip()


@dataclass
class Persona:
    """A debate persona with a unique perspective."""
    id: int
    name: str
    prompt: str
    gender: Literal["female", "male"]
    description: str


class PersonaSchema(BaseModel):
    name: str = Field(description="Human first name matching gender (e.g. Sarah, Marcus)")
    prompt: str = Field(description="System prompt for LLM: persona's stance on topic, argumentation style, rhetorical tactics (3-5 sentences)")
    description: str = Field(description="Public bio for UI: who they are, what shaped their view (1 sentence)")


class DebatePersonasSchema(BaseModel):
    personas: list[PersonaSchema] = Field(description="List of debate personas")




@Cache(".cache/personas").memoize()
def generate_debating_personas(topic: str, genders: tuple[str, ...]) -> list[Persona]:
    """Generate debate personas using LLM with structured output."""
    n = len(genders)
    gender = ", ".join(f"Persona {i+1}: {g}" for i, g in enumerate(genders))
    result: DebatePersonasSchema = ChatXAI(
        # model="grok-4-1-fast-reasoning-latest",
        model="grok-4",
        xai_api_key=os.environ.get("XAI_API_KEY"),
    ).with_structured_output(DebatePersonasSchema).with_retry(stop_after_attempt=3).invoke(
        PERSONA_GENERATION_PROMPT.format(topic=topic, gender=gender, n=n)
    )
    return [Persona(id=i, name=p.name, prompt=p.prompt, gender=genders[i], description=p.description) for i, p in enumerate(result.personas)]


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
            tts=XaiTTS(voice=VOICES[persona.gender][persona.id % 3].lower()),
        )

    def _reformat_history(self, chat_ctx: ChatContext) -> ChatContext:
        """Reformat history so current agent sees others as 'user' role. Returns a copy."""
        formatted = chat_ctx.copy()
        for i, item in enumerate(formatted.items):
            if not isinstance(item, DebateChatMessage):
                continue
            is_self = item.speaker == self.persona.name
            content = item.content[0] if item.content else ""
            formatted.items[i] = DebateChatMessage(
                **{**item.model_dump(),
                    "role": "assistant" if is_self else "user",
                    "content": [content if is_self else f"*{item.speaker} says* {content}"],
                    "speaker": self.persona.name if is_self else item.speaker,
                }
            )
        return formatted

    @retry(stop=stop_after_attempt(3), reraise=True)
    async def _notify_speaker_change(self):
        """Notify frontend about speaker change via RPC."""
        if self._session._room_io is None:
            return  # Console mode - no room available
        room = self._session._room_io._room
        if not room or not room.remote_participants:
            return
        client_identity = next(iter(room.remote_participants.keys()))
        await room.local_participant.perform_rpc(
            destination_identity=client_identity,
            method="speaker_changed",
            payload=json.dumps({"id": self.persona.id}),
        )

    async def on_enter(self):
        await self._notify_speaker_change()

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
    genders: list[str] = metadata.get("genders", ["male", "female"])

    logging.info(f"Starting session with {topic=} and {genders=}")
    personas = generate_debating_personas(topic, tuple(genders))
    for p in personas:
        logging.info(f"  [{p.id}] {p.name} ({p.gender}): {p.description}")

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
            audio_input=room_io.AudioInputOptions(noise_cancellation=noise_cancellation.BVC()),
            audio_output=room_io.AudioOutputOptions(sample_rate=44100),
        ),
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
