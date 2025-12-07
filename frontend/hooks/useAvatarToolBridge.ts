import { useEffect, useRef } from 'react';
import type { ToolCall, ToolInvoker } from '@/lib/avatar-tools';
import { coerceToolCalls, logToolInvoker } from '@/lib/avatar-tools';
import { isBrowser } from '@/lib/utils';

type BridgeRuntime = {
  invoke: (call: ToolCall) => Promise<void>;
  process: (payload: unknown) => Promise<void>;
  lastCall?: ToolCall;
  calls: ToolCall[];
};

/**
 * Wires tool calls to an invoker and exposes a debug surface on `window.__avatarTools`.
 * You can trigger a tool call manually with:
 *   window.dispatchEvent(new CustomEvent('avatar-tool-call', { detail: { type: 'setPose', pose: 'listening' } }))
 * or directly:
 *   window.__avatarTools.invoke({ type: 'setExpression', preset: 'smile' })
 *
 * To feed LLM tool payloads (e.g., OpenAI tool_calls):
 *   window.__avatarTools.process({ tool_calls: [{ function: { arguments: '{"type":"setExpression","preset":"smile"}' } }] })
 */
export function useAvatarToolBridge(invoker: ToolInvoker = logToolInvoker) {
  const runtimeRef = useRef<BridgeRuntime>();

  useEffect(() => {
    const runtime: BridgeRuntime = {
      calls: [],
      invoke: async (call: ToolCall) => {
        console.info('[AvatarToolBridge] invoke', call);
        runtime.lastCall = call;
        runtime.calls.push(call);
        if (isBrowser()) {
          window.dispatchEvent(new CustomEvent('avatar-tool-apply', { detail: call }));
        }
        try {
          await invoker(call);
        } catch (err) {
          console.error('[AvatarToolBridge] invoke failed', err);
        }
      },
      process: async (payload: unknown) => {
        const calls = coerceToolCalls(payload);
        if (!calls.length) {
          console.warn('[AvatarToolBridge] process: no tool calls recognized', payload);
          return;
        }
        console.info('[AvatarToolBridge] process', calls);
        for (const call of calls) {
          await runtime.invoke(call);
        }
      },
    };
    runtimeRef.current = runtime;

    const onEvent = (ev: Event) => {
      const detail = (ev as CustomEvent<ToolCall>).detail;
      if (!detail || typeof detail !== 'object') return;
      runtime.invoke(detail);
    };
    const onProcessEvent = (ev: Event) => {
      const detail = (ev as CustomEvent<unknown>).detail;
      runtime.process(detail);
    };

    (window as any).__avatarTools = runtime;
    if (isBrowser()) {
      window.addEventListener('avatar-tool-call', onEvent as EventListener);
      window.addEventListener('avatar-tool-payload', onProcessEvent as EventListener);
      console.info('[AvatarToolBridge] ready; window.__avatarTools available');
    }

    return () => {
      delete (window as any).__avatarTools;
      if (isBrowser()) {
        window.removeEventListener('avatar-tool-call', onEvent as EventListener);
        window.removeEventListener('avatar-tool-payload', onProcessEvent as EventListener);
      }
    };
  }, [invoker]);
}
