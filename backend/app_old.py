import logging
import math
import os
import random
import sys
import time
from typing import Literal, Annotated, cast
from dotenv import load_dotenv

from livekit import agents
from livekit.agents.voice import room_io
import livekit.agents.cli.cli
from livekit.agents.cli import _run
from livekit.agents.cli.proto import CliArgs
from livekit.agents.plugin import Plugin
from livekit.plugins.turn_detector.english import EnglishModel as EnglishTurnDetector
from livekit.plugins import deepgram, elevenlabs, noise_cancellation, openai, silero, anthropic, google


# - [v] update libs
# - [ ] match Fluently patterns
# - [ ] launch as it is and refactor
# - [ ] tune multi-agent setup
# - [ ] propose a point -> voting -> discussion
# - [ ] change a poing -> voting -> discussion


load_dotenv(override=True)
logger = logging.getLogger("livekit.agents")
NOISE_CANCELLATION = True
TURN_DETECTION = True
VOICES = {
    "chatgpt": "AQQ8gvgCVKvmLaopJlOC",  # male
    "claude": "4NejU5DwQjevnR6mh3mb",  # female
    "gemini": "UgBBYS2sOqTuMpoF3BR0",  # male
    "grok": "uYXf8XasLslADfZ2MB4u",  # female
}

AGENT_INSTRUCTIONS = """
You are a {agent_type} participating in a discussion on the topic given by the user.

Besides you and the user, other agents are participating in the discussion: {all_agents}.

Respond briefly and concisely <= 10 words.
"""

REPLY_INSTRUCTIONS = """
Continue the conversation, responding to the previous response:
- Address who you are responding to at the very beginning of your answer in the following format: "speaker_name, ..." where speaker_name is the name of the speaker you are responding to.
- Try to come up with a fresh thought that hasn't been voiced by other speakers.
- Critique the previous response or give constructive feedback.
"""

CREATE_TURN_TRANSITION_TOOL_DESCRIPTION = """
Use this tool to transition to the next speaker. You can only transition to the next speaker in the list.

Decide whether to transition to the next speaker based on the conversation history. \
You can:
1) Continue bouncing ideas back and forth with the specific agent you are currently engaged with.
2) Give a chance for another agent to speak and contribute to the discussion.
3) Give the floor to the user so they can say something.
4) If last response was from the user, transition to the next speaker to whom he addressed.
"""


# TODO DELETE
# class DialecticaChatMessage(agents.ChatMessage):
#     agent_type: Literal["chatgpt", "claude", "gemini", "grok", "user"]
#     is_formated: bool
# from livekit.agents.llm import ChatContent
# DialecticaChatMessage.model_rebuild()


class DialecticaAgent(agents.Agent):
    def __init__(
        self,
        agent_type: Literal["chatgpt", "claude", "gemini", "grok"],
        all_agents: list[Literal["chatgpt", "claude", "gemini", "grok"]],
        initial_user_query: str = None,
        chat_ctx: agents.ChatContext = None,
    ):
        self.agent_type = agent_type
        self.all_agents = all_agents
        self.initial_user_query = initial_user_query

        # if chat_ctx is not None:
        #     logger.info(f"{self.agent_type} `chat_ctx` {chat_ctx.items}")

        super().__init__(
            instructions=AGENT_INSTRUCTIONS.format(
                agent_type=agent_type,
                all_agents=[a for a in all_agents if a != agent_type],   # + user
            ),
            chat_ctx=chat_ctx,
            tts=elevenlabs.TTS(
                voice_id=VOICES[agent_type],
                model="eleven_turbo_v2_5",
                voice_settings=elevenlabs.VoiceSettings(
                    speed=1.0,
                    stability=0.65,
                    similarity_boost=0.55,
                ),
                encoding="mp3_44100_96",
                api_key=os.getenv("ELEVENLABS_API_KEY"),
            ),
            llm={
                "chatgpt": openai.LLM(
                    model="gpt-4.1",
                    api_key=os.getenv("OPENAI_API_KEY"),
                ),
                "claude": anthropic.LLM(
                    model="claude-sonnet-4-20250514",
                    api_key=os.getenv("ANTHROPIC_API_KEY"),
                ),
                "gemini": google.LLM(
                    model="gemini-2.0-flash-001",
                    api_key=os.getenv("GOOGLE_API_KEY"),
                ),
                "grok": openai.LLM.with_x_ai(
                    model="grok-2-public",
                    api_key=os.getenv("OPENAI_API_KEY"),
                ),
            }[agent_type],
            stt=deepgram.STT(
                model="nova-3-general",
                language="en-US",
                filler_words=True,
                api_key=os.getenv("DEEPGRAM_API_KEY"),
            ),
            tools=[self._create_turn_transition_function()]
        )
    
    async def on_enter(self):
        logger.info(f"{self.agent_type} on_enter")

        await self.update_chat_ctx(chat_ctx=self._format_chat_ctx(self.session._chat_ctx))
        logger.info(f"{self.agent_type} chat_ctx: {self.session._chat_ctx.items}")
        if self.initial_user_query is not None:
            logger.info(f"{self.agent_type} `initial_user_query` reply")
            await self.session.generate_reply(tool_choice="none", user_input=self.initial_user_query)
        else:
            logger.info(f"{self.agent_type} standard reply")
            await self.session.generate_reply(
                tool_choice="none",
                instructions=REPLY_INSTRUCTIONS.strip(),
            )
        
        await self.session.generate_reply(tool_choice="required")
    
    def _format_chat_ctx(self, chat_ctx: agents.ChatContext):
        for i, item in enumerate(chat_ctx.items):
            if isinstance(item, DialecticaChatMessage):
                if (item.role == "user"):
                    content = f"*user says* {item.content[0]}" if not item.is_formated else item.content[0]
                    chat_ctx.items[i] = DialecticaChatMessage(
                        **{
                            **item.model_dump(),
                            "content": [content],
                            "agent_type": "user",
                            "is_formated": True,
                        },
                    )
                elif (item.role == "assistant") and (item.agent_type == self.agent_type):
                    content = f"*{item.agent_type} says* {item.content[0]}" if item.is_formated else item.content[0]
                    chat_ctx.items[i] = DialecticaChatMessage(
                        **{
                            **item.model_dump(),
                            "content": [content],
                            "role": "assistant",
                            "agent_type": item.agent_type,
                            "is_formated": False,
                        },
                    )
                elif (item.role == "assistant") and (item.agent_type != self.agent_type):
                    content = f"*{item.agent_type} says* {item.content[0]}" if not item.is_formated else item.content[0]
                    chat_ctx.items[i] = DialecticaChatMessage(
                        **{
                            **item.model_dump(),
                            "content": [content],
                            "role": "user",
                            "agent_type": item.agent_type,
                            "is_formated": True,
                        },
                    )
        return chat_ctx
        
    
    def _create_turn_transition_function(self):
        next_speakers = [a for a in self.all_agents if a != self.agent_type] + ["user"]
        @agents.function_tool(
            name="turn_transition_to_next_speaker",
            description=CREATE_TURN_TRANSITION_TOOL_DESCRIPTION.strip(),
        )
        async def _turn_transition_function(
            context: agents.RunContext,
            next_speaker: Annotated[str, f"The next speaker to transition turn to. Choose one of {next_speakers}"],
        ):
            logger.info(f"{self.agent_type} `turn_transition_to_next_speaker` -> {next_speaker}")
            if next_speaker == "user":
                self.session.say(text="user, what do you think?")
                return None
            elif next_speaker not in self.all_agents:
                logger.error(f"{self.agent_type} `turn_transition_to_next_speaker` error -> {next_speaker}")
                return DialecticaAgent(
                    agent_type=self.agent_type,
                    all_agents=self.all_agents,
                    chat_ctx=self.session._chat_ctx,
                )
            return DialecticaAgent(
                agent_type=next_speaker,
                all_agents=self.all_agents,
                chat_ctx=self.session._chat_ctx,
            )
        return _turn_transition_function

    async def on_user_turn_completed(self, turn_ctx: agents.ChatContext, new_message: agents.ChatMessage):

        logger.info(f"`on_user_turn_completed` {turn_ctx.items}")
        # await self.session.interrupt()
        await self.session.generate_reply(tool_choice="required")
        # self.session.update_agent(DialecticaAgent(
        #     agent_type=self.agent_type,
        #     all_agents=self.all_agents,
        #     chat_ctx=self.session._chat_ctx,
        # ))


async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Starting entrypoint with room_name={ctx.room.name} and mode={os.environ["LIVEKIT_MODE"]}")

    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    agent_session_kwargs = {
        "vad": silero.VAD.load(),
        "allow_interruptions": True,
        "min_interruption_duration": 0.5,
        "min_endpointing_delay": 0.5,
        "max_endpointing_delay": 6.0,
    }
    if TURN_DETECTION:
        agent_session_kwargs["turn_detection"] = EnglishTurnDetector()
    session = agents.AgentSession(**agent_session_kwargs)

    # all_agents = ["chatgpt", "claude", "gemini", "grok"]
    all_agents = ["chatgpt", "claude", "gemini"]
    initial_user_query = "What is better for the world: AI or human?"
    start_agent = random.choice(all_agents)

    logger.info(f"Starting session with {start_agent} as the first agent")

    session_start_kwargs = {
        "room": ctx.room,
        "agent": DialecticaAgent(
            agent_type=start_agent,
            all_agents=all_agents,
            initial_user_query=initial_user_query,
        ),
        "room_output_options": room_io.RoomOutputOptions(audio_sample_rate=44100),
    }
    if NOISE_CANCELLATION:
        session_start_kwargs["room_input_options"] = room_io.RoomInputOptions(noise_cancellation=noise_cancellation.BVC())
    

    @session.on("conversation_item_added")
    def _on_conversation_item_added(event: agents.ConversationItemAddedEvent):
        # Remove empty or interrupted messages
        if (event.item.content and event.item.content[0] == "") or event.item.interrupted:
            # Find and remove the specific item by ID instead of using pop()
            session.history.items = [item for item in session.history.items if item.id != event.item.id]
            return

        if event.item.role == "assistant":
            session.history.items[-1] = DialecticaChatMessage(
                **event.item.model_dump(),
                agent_type=session.current_agent.agent_type,
                is_formated=False,
            )
        elif event.item.role == "user":
            session.history.items[-1] = DialecticaChatMessage(
                **event.item.model_dump(),
                agent_type="user",
                is_formated=False,
            )

    await session.start(**session_start_kwargs)


def download_eou_files_w_token(hf_token: str | None):
    from livekit.plugins.turn_detector.base import _download_from_hf_hub
    from livekit.plugins.turn_detector.models import HG_MODEL, MODEL_REVISIONS, ONNX_FILENAME
    from transformers import AutoTokenizer

    if not hf_token:
        raise ValueError("`HF_TOKEN` is not set")

    for revision in MODEL_REVISIONS.values():
        AutoTokenizer.from_pretrained(HG_MODEL, revision=revision, token=hf_token)
        _download_from_hf_hub(
            HG_MODEL, ONNX_FILENAME, subfolder="onnx", revision=revision, token=hf_token
        )
        _download_from_hf_hub(HG_MODEL, "languages.json", revision=revision, token=hf_token)


def PREWARM(proc: agents.JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=0.6,
        prefix_padding_duration=0.5,
        max_buffered_speech=60.0,
        activation_threshold=0.5,
    )


def run_livekit_worker(mode: Literal["dev", "start", "console"]) -> None:
    from livekit.plugins.turn_detector import EOUPlugin

    assert mode in ["dev", "start", "console"]
    logger.info(f"Running livekit worker with mode={mode}")

    # mimic cli-run -> download_files
    for plugin in Plugin.registered_plugins:
        try:
            plugin.download_files()
            logger.info(f"✅ DONE download files for {plugin}")
        except Exception as e:
            logger.info(f"error while downloading files: {e}")
            if isinstance(plugin, EOUPlugin):
                logger.warning(f"🟡 trying to download files for {plugin} with token")
                download_eou_files_w_token(hf_token=os.getenv("HF_TOKEN"))
                logger.info(f"✅ DONE download files for {plugin}")
            else:
                logger.error(f"❌ FAILED to download files for {plugin}")
                raise e

    # mimic cli-run -> dev/start/console
    try:
        if mode == "console":
            opts = agents.WorkerOptions(
                job_executor_type=agents.JobExecutorType.THREAD,
                entrypoint_fnc=entrypoint,
                ws_url=os.environ["LIVEKIT_URL"],
                api_key=os.environ["LIVEKIT_API_KEY"],
                api_secret=os.environ["LIVEKIT_API_SECRET"],
                prewarm_fnc=PREWARM,
                port=0,  # livekit will choose free port for health-check
            )
            args = CliArgs(
                opts=opts,
                log_level="DEBUG",
                devmode=True,
                asyncio_debug=False,
                console=True,
                register=False,
                watch=False,
                simulate_job=agents.SimulateJobInfo(room="mock-console"),
            )
            livekit.agents.cli.cli.CLI_ARGUMENTS = args
            _run.run_worker(args)
        elif mode in ["dev", "start"]:
            opts = agents.WorkerOptions(
                entrypoint_fnc=entrypoint,
                ws_url=os.environ["LIVEKIT_URL"],
                api_key=os.environ["LIVEKIT_API_KEY"],
                api_secret=os.environ["LIVEKIT_API_SECRET"],
                prewarm_fnc=PREWARM,
                agent_name="fluently-agents",
                port=0,  # livekit will choose free port for health-check
                load_threshold=0.8 if mode == "start" else math.inf,
                shutdown_process_timeout=120.0,
            )
            args = CliArgs(
                opts=opts,
                log_level="DEBUG" if mode == "dev" else "INFO",
                devmode=mode == "dev",
                asyncio_debug=False,
                register=True,
                watch=False,
            )
            livekit.agents.cli.cli.CLI_ARGUMENTS = args
            _run.run_worker(args)
    except Exception as e:
        logger.error(f"Error while running livekit worker: {e}")
        raise e 


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise ValueError("mode is not provided")
    raw_mode = sys.argv[1].lower().strip()
    if raw_mode not in ["dev", "start", "console"]:
        raise ValueError(f"invalid mode: {raw_mode}")
    mode = cast(Literal["dev", "start", "console"], raw_mode)

    print(f"mode: {mode}")
    os.environ['LIVEKIT_MODE'] = mode

    while True:
        try:
            run_livekit_worker(mode)
        except Exception as e:
            logger.error(f"Livekit worker crashed: {e}")
            logger.info("Restarting in 10 seconds...")
            time.sleep(10)
