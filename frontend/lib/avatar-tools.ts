// Lightweight tool-call contracts for animating avatars.
// Wire these to your animation system and let the LLM emit them by name.

export type AvatarTarget = { avatarId?: string };

export type PoseName = 'idle' | 'listening' | 'speaking' | 'thinking' | 'excited';
export type GazeTarget =
  | 'user'
  | 'screen'
  | 'offscreen-left'
  | 'offscreen-right'
  | { x: number; y: number; z: number };
export type ExpressionPreset = 'smile' | 'surprised' | 'concerned' | 'wink' | 'laugh' | 'blink';
export type BlinkRate = 'calm' | 'fast' | number;
export type BreathLevel = 'low' | 'med' | 'high';
export type IdleStyle = 'calm' | 'bouncy' | 'focused' | 'fidgety';
export type Hand = 'left' | 'right' | 'both';
export type HandGesture = 'wave' | 'point' | 'thumbs-up' | 'open' | 'closed';
export type EmoteName = 'nod' | 'shrug' | 'head-tilt' | 'head-shake' | 'bow' | 'fist-pump';
export type LipSyncMode = 'live' | 'muted' | 'exaggerated';
export type LightingMood = 'warm' | 'cool' | 'dramatic';
export type PostureStyle = 'upright' | 'relaxed' | 'hero' | 'shy';

export type ToolCall =
  | { type: 'setPose'; pose: PoseName; context?: AvatarTarget }
  | { type: 'setGaze'; target: GazeTarget; context?: AvatarTarget }
  | { type: 'setExpression'; preset: ExpressionPreset; context?: AvatarTarget }
  | { type: 'setBlinkRate'; rate: BlinkRate; context?: AvatarTarget }
  | { type: 'setBreath'; level: BreathLevel; context?: AvatarTarget }
  | { type: 'setIdleStyle'; style: IdleStyle; context?: AvatarTarget }
  | { type: 'setHandGesture'; gesture: HandGesture; hand: Hand; context?: AvatarTarget }
  | { type: 'playEmote'; emote: EmoteName; intensity?: number; context?: AvatarTarget }
  | { type: 'setLipSyncMode'; mode: LipSyncMode; context?: AvatarTarget }
  | { type: 'setVoiceReactiveness'; level: number; context?: AvatarTarget }
  | { type: 'setLean'; amount: number; axis: 'forward' | 'back' | 'left' | 'right'; context?: AvatarTarget }
  | { type: 'setHairReactiveness'; level: number; context?: AvatarTarget }
  | { type: 'setEyeDart'; enabled: boolean; rate?: number; context?: AvatarTarget }
  | { type: 'setHeadBob'; amount: number; tempo?: number; context?: AvatarTarget }
  | { type: 'playLookAround'; durationMs: number; arc?: number; context?: AvatarTarget }
  | { type: 'setProximityReact'; distance: number; context?: AvatarTarget }
  | { type: 'setLightingMood'; mood: LightingMood; context?: AvatarTarget }
  | { type: 'setAvatarFocus'; target: 'self' | 'peer'; context?: AvatarTarget }
  | { type: 'setPosture'; style: PostureStyle; context?: AvatarTarget }
  | { type: 'playBeatReaction'; context?: AvatarTarget };

export type ToolInvoker = (call: ToolCall) => Promise<void>;

// Default stub invoker; replace with real animation bus.
export const logToolInvoker: ToolInvoker = async (call) => {
  console.info('[AvatarTool]', call);
};

export function isToolCall(input: unknown): input is ToolCall {
  return Boolean(input && typeof input === 'object' && 'type' in (input as any));
}

export function coerceToolCalls(input: unknown): ToolCall[] {
  if (!input) return [];
  if (Array.isArray(input)) {
    return input.filter(isToolCall) as ToolCall[];
  }
  if (isToolCall(input)) return [input];
  // Shape for OpenAI-style tool calls: { tool_calls: [{ function: { name, arguments } }] }
  if (
    typeof input === 'object' &&
    'tool_calls' in (input as any) &&
    Array.isArray((input as any).tool_calls)
  ) {
    return (input as any).tool_calls
      .map((tc: any) => tc?.function?.arguments)
      .map((args: any) => {
        try {
          return typeof args === 'string' ? JSON.parse(args) : args;
        } catch (e) {
          console.warn('[AvatarTool] failed to parse tool args', e, args);
          return undefined;
        }
      })
      .filter(isToolCall) as ToolCall[];
  }
  return [];
}
