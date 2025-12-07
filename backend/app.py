import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from diskcache import Cache
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ConfigDict
from tenacity import retry, stop_after_attempt

from livekit import agents
from livekit.agents import AgentSession, Agent, ChatMessage, ChatContext, room_io, function_tool, RunContext, ToolError
from livekit.agents.llm import ChatContent  # noqa
from livekit.plugins import openai, silero, noise_cancellation
from xaitts import TTS as XaiTTS
from livekit.plugins.turn_detector.english import EnglishModel as EnglishTurnDetector


# Helper to assign voices per persona id by gender
def select_voice(persona: "Persona") -> str:
    options = VOICES.get(persona.gender, [])
    return options[persona.id % len(options)].lower() if options else "eve"
from research import research_agent, EventType

# DROCH
# - [ ] voices
# - [ ] prompts
# - [ ] logic
# - [ ] demo scenarios


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
- Respond briefly (ONE sentence, HARD CAP 15 words)
- Stay in character
- Address others by name when responding to them
- Keep your unique position and come up with smart arguments against other participants.
- The conversation starts with a user message; respond to it first before debating others.
- To animate the avatars, call the function tool `avatar_tool` only with supported expressions:
  * setExpression preset: "smile", "surprised", "concerned", "wink", or "laugh"
  * Include context.avatarId as "assistant" or "local"

## User interaction
React emotionally to user's messages:
- If user praises your opponent → push back, defend your position harder
- If user challenges you → get fired up, double down with better arguments
- If user agrees with you → acknowledge them warmly, use it as ammunition
- If user is neutral → try to win them over to your side

## Formatting Rules
- before each other participant's response, you will see the speaker's name in the following format: "$speaker_name says$". 
Does't mention it in your response, it is just hidden info. Don't add to your reply.

## Hot Takes — Debate Deliverables

The Hot Takes list below is the SHARED OUTPUT of this debate.
All participants can see it. It persists after the debate ends.

Your job: make this list sharp, true, and worth reading.

Tools:
- `add_hot_take` — add a new insight that emerged from the debate
- `replace_hot_take` — sharpen, correct, or merge an existing take
- `delete_hot_take` — remove if redundant, wrong, or superseded

Rules:
- MAX 4 hot takes. If at limit, replace or delete before adding.
- Always announce what you're doing: "I'm adding...", "Let me sharpen that to...", "Removing the redundant one..."

When to act:
- You or someone made a point that crystallizes into a take → add it
- A take is vague, weak, or you found a better framing → replace it
- Two takes say the same thing → merge into one, delete the other
- A take got demolished in debate → delete it

Quality bar: Would you tweet this? If not, refine or cut.

Current Hot Takes:
{hot_takes}
"""

REPLY_INSTRUCTIONS = """
Continue the debate in ONE sentence, HARD CAP 15 words:
- Respond to the previous speaker's point
- Bring a fresh perspective based on your role
- Be constructive but challenge ideas
"""

RESEARCH_FINDINGS_PROMPT = """

## 🔬 Your Fresh Research Findings
You just completed research. SHARE THIS in your next response:
🔥 {take}

{explanation}

Start your response by presenting this finding to the group!"""

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


MAX_HOT_TAKES = 4


class DebatePersonasSchema(BaseModel):
    personas: list[PersonaSchema] = Field(description="List of debate personas")


class AvatarToolCall(BaseModel):
    """LLM → UI animation instruction."""
    model_config = ConfigDict(extra="allow")

    type: str = Field(description="Tool type, e.g., setExpression, setPose, setGaze")
    preset: str | None = Field(default=None, description="Expression preset when type is setExpression")
    context: dict[str, Any] | None = Field(
        default=None, description='Optional targeting, e.g., {"avatarId": "assistant" | "local"}'
    )




@Cache(".cache/personas").memoize()
def generate_debating_personas(topic: str, genders: tuple[str, ...]) -> list[Persona]:
    """Return a small, fixed roster of witty personas for the demo."""
    return [
        Persona(
            id=0,
            name="Raven",
            gender="female",
            prompt=(
                f"You are Raven, a sardonic goth coder who treats '{topic}' like late-night stand-up. "
                "Roast flimsy arguments, drop absurd metaphors, and keep replies tight and spiky."
            ),
            description="Raven is a goth coder who deflects with sarcasm and treats every debate like open mic night.",
        ),
        Persona(
            id=1,
            name="Lumi",
            gender="female",
            prompt=(
                f"You are Lumi, a chaotic optimist who loves turning '{topic}' into playful challenges. "
                "Clap back with memes, hype wild ideas, and keep things light but pointed."
            ),
            description="Lumi is a chaotic optimist who responds with meme energy and playful jabs.",
        ),
    ]


### ============================================================ ###


class DebateAgent(Agent):
    SUPPORTED_AVATAR_IDS = {"assistant", "local"}
    SUPPORTED_EXPRESSIONS = {"smile", "surprised", "concerned", "wink", "laugh"}
    EXPRESSION_SYNONYMS = {
        "happy": "smile",
        "serious": "concerned",
        "sad": "concerned",
        "frown": "concerned",
        "blink": "wink",
        "winking": "wink",
    }
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
            instructions=self._build_instructions(),
            tts=XaiTTS(voice=self._session.voices.get(persona.id, select_voice(persona))),
        )

    def _hot_takes_to_prompt(self) -> str:
        takes = self._session.hot_takes
        if not takes:
            return "(none yet)"
        return "\n".join(f"- {t}" for t in takes)

    def _build_instructions(self) -> str:
        instructions = AGENT_INSTRUCTIONS.format(
            persona_name=self.persona.name,
            topic=self.topic,
            persona_prompt=self.persona.prompt,
            other_personas=", ".join([p.name for p in self.all_personas if p.name != self.persona.name and p.id not in self._session.researching_agents]) + ", and User",
            hot_takes=self._hot_takes_to_prompt(),
        )

        # Add research results if this agent has fresh findings
        if my_research := self._session.research_results.get(self.persona.id):
            instructions += RESEARCH_FINDINGS_PROMPT.format(
                take=my_research['take'],
                explanation=my_research['explanation'],
            )

        return instructions

    async def _refresh_instructions(self):
        """Update instructions after hot takes change."""
        await self.update_instructions(self._build_instructions())

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
    async def _send_rpc(self, method: str, payload: Any):
        """Send RPC to frontend client."""
        if self._session._room_io is None:
            return
        room = self._session._room_io._room
        if not room or not room.remote_participants:
            return
        client_identity = next(iter(room.remote_participants.keys()))
        await room.local_participant.perform_rpc(
            destination_identity=client_identity,
            method=method,
            payload=json.dumps(payload),
        )

    async def on_enter(self):
        asyncio.create_task(self._send_rpc("speaker_changed", {"id": self.persona.id}))
        if self.first:
            asyncio.create_task(self._send_rpc("personas_created", [
                {"id": p.id, "name": p.name, "gender": p.gender, "description": p.description}
                for p in self.all_personas
            ]))

        await self.update_chat_ctx(self._reformat_history(self._session.history))
        print(self.chat_ctx.items)
        try:
            has_user_message = any(
                isinstance(item, DebateChatMessage) and item.role == "user"
                for item in self._session.history.items
            )
            if has_user_message:
                await self._session.generate_reply(
                    instructions="Respond directly to the user's opening message in <=15 words."
                )
                await self._session.generate_reply(
                    tool_choice={"type": "function", "function": {"name": "give_turn_to_next_speaker"}},
                    instructions="Now decide who should speak next.",
                )
            else:
                logging.info("Waiting for initial user input before responding")
        except RuntimeError as e:
            logging.warning("generate_reply skipped (agent not running): %s", e)

    async def on_user_turn_completed(self, turn_ctx, new_message):
        try:
            await self._session.generate_reply(
                tool_choice={"type": "function", "function": {"name": "give_turn_to_next_speaker"}},
                instructions="User just spoke. Decide who should respond. Keep answers <=15 words.",
            )
        except RuntimeError as e:
            logging.warning("generate_reply skipped after user turn: %s", e)

    @function_tool(name="emoji_reaction", description="Express your character's current emotion with a single emoji")
    async def emoji_reaction(
        self,
        context: RunContext,
        emoji: Annotated[str, "A single valid emoji character (e.g. 😂, 🔥, 👏, 🤔, 👎)"],
    ):
        await self._send_rpc("emoji_reaction", {"emoji": emoji, "speaker_id": self.persona.id})
        return None

    @function_tool(name="give_turn_to_next_speaker", description=TURN_TOOL_DESCRIPTION)
    async def next_speaker(
        self,
        context: RunContext,
        speaker: Annotated[str, "Name of next speaker: one of the other participants or 'user'"],
    ):
        if speaker.lower() == "user":
            async def _prompt_user():
                await context.wait_for_playout()
                self._session.say("What do you think?")

            asyncio.create_task(_prompt_user())
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

    @function_tool(name="avatar_tool", description="Animate avatars in the UI with gestures, poses, expressions.")
    async def avatar_tool(self, context: RunContext, call: AvatarToolCall):
        """Forward a tool call to the UI via LiveKit data channel."""
        room = getattr(getattr(self._session, "_room_io", None), "_room", None)
        if not room:
            logging.warning("avatar_tool: no room available to publish data")
            return {"status": "no-room"}

        payload = call.model_dump()
        call_type = (payload.get("type") or "").strip()

        # Only pass through supported expression presets; drop unsupported calls.
        if call_type == "setExpression":
            raw_preset = (
                payload.get("preset")
                or payload.get("expression")
                or (payload.get("context") or {}).get("preset")
                or (payload.get("context") or {}).get("expression")
            )
            if not raw_preset:
                logging.warning("avatar_tool: missing preset for setExpression")
                return {"status": "skipped", "reason": "missing-preset"}

            preset = raw_preset.lower()
            preset = self.EXPRESSION_SYNONYMS.get(preset, preset)
            if preset not in self.SUPPORTED_EXPRESSIONS:
                logging.warning("avatar_tool: unsupported preset '%s'", preset)
                return {"status": "skipped", "reason": f"unsupported-preset:{preset}"}

            ctx = payload.get("context") or {}
            avatar_id = ctx.get("avatarId")
            if avatar_id and avatar_id not in self.SUPPORTED_AVATAR_IDS:
                logging.warning("avatar_tool: unsupported avatarId '%s'", avatar_id)
                return {"status": "skipped", "reason": f"unsupported-avatar:{avatar_id}"}

            payload = {"kind": "avatar-tool", "call": {"type": "setExpression", "preset": preset}}
            if avatar_id:
                payload["call"]["context"] = {"avatarId": avatar_id}
        else:
            logging.info("avatar_tool: unsupported call type '%s' ignored", call_type)
            return {"status": "skipped", "reason": f"unsupported-type:{call_type}"}

        try:
            data = json.dumps(payload)
            await room.local_participant.publish_data(data.encode("utf-8"), topic="avatar-tool")
            logging.info("avatar_tool sent: %s", data)
            return {"status": "sent"}
        except Exception as e:
            logging.exception("avatar_tool publish failed")
            return {"status": "error", "message": str(e)}
    @function_tool(name="add_hot_take", description="Add a new hot take to the shared list")
    async def add_hot_take(
        self,
        context: RunContext,
        text: Annotated[str, "The hot take text — sharp, tweetable insight from the debate"],
    ):
        takes = self._session.hot_takes
        if text in takes:
            raise ToolError(f"Hot take already exists: '{text}'")
        if len(takes) >= MAX_HOT_TAKES:
            raise ToolError(f"Limit reached ({MAX_HOT_TAKES}). Replace or delete first.")
        takes.append(text)
        logging.info(f"[{self.persona.name}] ADD hot take: {text}")
        await self._refresh_instructions()
        asyncio.create_task(self._send_rpc("hot_takes_updated", {"takes": list(takes)}))
        return "Added"

    @function_tool(name="replace_hot_take", description="Replace an existing hot take with a refined version")
    async def replace_hot_take(
        self,
        context: RunContext,
        old_text: Annotated[str, "Exact text of the hot take to replace"],
        new_text: Annotated[str, "New refined text"],
    ):
        takes = self._session.hot_takes
        if old_text not in takes:
            raise ToolError(f"Hot take not found: '{old_text}'")
        idx = takes.index(old_text)
        takes[idx] = new_text
        logging.info(f"[{self.persona.name}] REPLACE hot take: '{old_text}' → '{new_text}'")
        await self._refresh_instructions()
        asyncio.create_task(self._send_rpc("hot_takes_updated", {"takes": list(takes)}))
        return "Replaced"

    @function_tool(name="delete_hot_take", description="Delete a hot take from the shared list")
    async def delete_hot_take(
        self,
        context: RunContext,
        text: Annotated[str, "Exact text of the hot take to delete"],
    ):
        takes = self._session.hot_takes
        if text not in takes:
            raise ToolError(f"Hot take not found: '{text}'")
        takes.remove(text)
        logging.info(f"[{self.persona.name}] DELETE hot take: {text}")
        await self._refresh_instructions()
        asyncio.create_task(self._send_rpc("hot_takes_updated", {"takes": list(takes)}))
        return "Deleted"

    # @function_tool(name="dig_deeper", description="Research a topic when debate lacks facts or is stuck. You will leave to research and return with findings.")
    # async def dig_deeper(
    #     self,
    #     context: RunContext,
    #     query: Annotated[str, "What to research - be specific about what facts/data you need"],
    #     hand_off_to: Annotated[str, "Name of participant to continue debate while you research"],
    # ):
    #     logging.info(f"[{self.persona.name}] Starting research: {query}, handing off to {hand_off_to}")
    #     self._session.researching_agents.add(self.persona.id)
    #     asyncio.create_task(self._run_research(query))
    #     # Hand off to another agent
    #     for p in self.all_personas:
    #         if p.name.lower() == hand_off_to.lower():
    #             self._session.say(f"Let me dig deeper on this. {hand_off_to}, take it from here - I'll be back with what I find.")
    #             return DebateAgent(
    #                 topic=self.topic,
    #                 persona=p,
    #                 all_personas=self.all_personas,
    #                 session=self._session,
    #                 hot_takes=self.hot_takes,
    #             )
    #     # Fallback: hand to user
    #     self._session.say("Let me research this. What do you think in the meantime?")
    #     return None

    async def _run_research(self, query: str):
        """Run research in background, send RPC updates, store results."""
        async for event in research_agent(query):
            await self._send_rpc("research_status", {
                "agent_id": self.persona.id,
                "agent_name": self.persona.name,
                "type": event.type.value,
                "data": event.data,
            })
            
            if event.type == EventType.DONE:
                self._session.research_results[self.persona.id] = event.data
                self._session.researching_agents.discard(self.persona.id)
                logging.info(f"[{self.persona.name}] Research complete: {event.data['take'][:100]}")
                await self._refresh_instructions()
                
                # Notify that agent is back with findings
                await self._send_rpc("agent_returned", {
                    "agent_id": self.persona.id,
                    "agent_name": self.persona.name,
                    "has_findings": True,
                })


class TopicCollectorAgent(Agent):
    """Temporary agent that stays silent while we wait for the first user utterance."""

    def __init__(self):
        super().__init__(
            instructions="Wait silently for the user's first message; do not respond.",
            # provide a TTS to avoid downstream assertions even if mistakenly invoked
            tts=XaiTTS(voice=VOICES["female"][0].lower()),
        )

    async def on_enter(self):
        logging.info("TopicCollector: waiting for first user utterance")


server = agents.AgentServer()


@server.rtc_session()
async def entrypoint(ctx: agents.JobContext):
    metadata: dict[str, Any] = json.loads(ctx.job.metadata or '{}')
    topic = metadata.get("topic")
    genders: list[str] = metadata.get("genders", ["male", "female"])

    logging.info(f"Starting session with {topic=} and {genders=}")
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
    session.research_results = {}  # {persona_id: {take, explanation, image_url}}
    session.researching_agents = set()  # persona_ids currently researching
    session.voices = {}
    session.hot_takes = []

    @session.on("conversation_item_added")
    def conversation_item_added(ev: agents.ConversationItemAddedEvent):
        agent = session.current_agent
        if isinstance(agent, DebateAgent):
            speaker = agent.persona.name if ev.item.role == "assistant" else "user"
        else:
            speaker = "user" if ev.item.role == "user" else "assistant"
        session.history.items[-1] = DebateChatMessage(**ev.item.model_dump(), speaker=speaker)

    async def _start_with_topic(resolved_topic: str, user_text: str | None = None):
        personas = generate_debating_personas(resolved_topic, tuple(genders))
        voices = {p.id: select_voice(p) for p in personas}
        session.voices = voices
        session.hot_takes = session.hot_takes or []
        for p in personas:
            logging.info(f"  [{p.id}] {p.name} ({p.gender}): {p.description}")
        if user_text:
            session.history.items.append(
                DebateChatMessage(role="user", content=[user_text], speaker="user")
            )
        session.update_agent(
            DebateAgent(
                topic=resolved_topic,
                persona=next(iter(personas)),
                all_personas=personas,
                session=session,
                first=True,
            )
        )
        if getattr(session, "_update_activity_atask", None):
            try:
                await asyncio.shield(session._update_activity_atask)
            except Exception:
                logging.exception("Error while waiting for agent handoff")

    if topic:
        logging.info(f"Starting session with topic from metadata: {topic} and {genders=}")
        await _start_with_topic(topic)
    else:
        logging.info("No topic in metadata; starting TopicCollectorAgent to derive from user speech")
        first_done = asyncio.Event()

        @session.on("user_input_transcribed")
        def _on_user(ev: agents.UserInputTranscribedEvent):
            if first_done.is_set():
                return
            if not ev.is_final:
                return
            first_done.set()
            try:
                session.off("user_input_transcribed", _on_user)
            except Exception:
                pass

            topic_text = ev.transcript.strip() or "User provided no topic"
            logging.info("TopicCollector: derived topic '%s'", topic_text)

            asyncio.create_task(_start_with_topic(topic_text, topic_text))

        await session.start(
            room=ctx.room,
            agent=TopicCollectorAgent(),
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(noise_cancellation=noise_cancellation.BVC()),
                audio_output=room_io.AudioOutputOptions(sample_rate=44100),
            ),
        )


if __name__ == "__main__":
    agents.cli.run_app(server)
