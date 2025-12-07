'use client';

import React, { useEffect, useRef, useState } from 'react';
import { DataPacket_Kind, Participant, RoomEvent } from 'livekit-client';
import { motion } from 'motion/react';
import { useSessionContext, useSessionMessages } from '@livekit/components-react';
import type { AppConfig } from '@/app-config';
import { ChatTranscript } from '@/components/app/chat-transcript';
import { PreConnectMessage } from '@/components/app/preconnect-message';
import { TileLayout } from '@/components/app/tile-layout';
import {
  AgentControlBar,
  type ControlBarControls,
} from '@/components/livekit/agent-control-bar/agent-control-bar';
import { useAvatarToolBridge } from '@/hooks/useAvatarToolBridge';
import { cn } from '@/lib/utils';
import { ScrollArea } from '../livekit/scroll-area/scroll-area';

const MotionBottom = motion.create('div');

type AvatarToolPayload = {
  call?: Record<string, unknown>;
  [key: string]: unknown;
};

type ToolBridgePayload =
  | AvatarToolPayload
  | {
      tool_calls: Array<{ function: { arguments: string } }>;
    };

const BOTTOM_VIEW_MOTION_PROPS = {
  variants: {
    visible: {
      opacity: 1,
      translateY: '0%',
    },
    hidden: {
      opacity: 0,
      translateY: '100%',
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.3,
    delay: 0.5,
    ease: 'easeOut',
  },
};

interface FadeProps {
  top?: boolean;
  bottom?: boolean;
  className?: string;
}

export function Fade({ top = false, bottom = false, className }: FadeProps) {
  return (
    <div
      className={cn(
        'from-background pointer-events-none h-4 bg-linear-to-b to-transparent',
        top && 'bg-linear-to-b',
        bottom && 'bg-linear-to-t',
        className
      )}
    />
  );
}

interface SessionViewProps {
  appConfig: AppConfig;
}

export const SessionView = ({
  appConfig,
  ...props
}: React.ComponentProps<'section'> & SessionViewProps) => {
  const session = useSessionContext();
  const { messages } = useSessionMessages(session);
  const [chatOpen, setChatOpen] = useState(false);
  const [activeSpeaker, setActiveSpeaker] = useState<'assistant-1' | 'assistant-2'>('assistant-1');
  const lastRemoteMessageIdRef = useRef<string | number | undefined>(undefined);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  useAvatarToolBridge();

  useEffect(() => {
    const room = session?.room;
    if (!room) return;
    const onData = (
      payload: Uint8Array,
      _participant?: Participant,
      _kind?: DataPacket_Kind,
      topic?: string
    ) => {
      if (topic !== 'avatar-tool') return;
      try {
        const text = new TextDecoder().decode(payload);
        const parsedData = JSON.parse(text) as AvatarToolPayload;
        console.info('[AvatarToolBridge] received data packet', parsedData);

        const avatarTools = (
          window as typeof window & {
            __avatarTools?: { process?: (data: ToolBridgePayload) => void };
          }
        ).__avatarTools;

        const toolPayload: ToolBridgePayload =
          parsedData.call !== undefined
            ? { tool_calls: [{ function: { arguments: JSON.stringify(parsedData.call) } }] }
            : parsedData;

        avatarTools?.process?.(toolPayload);
      } catch (err) {
        console.error('[AvatarToolBridge] failed to parse data', err);
      }
    };
    room.on(RoomEvent.DataReceived, onData);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [session]);

  const controls: ControlBarControls = {
    leave: true,
    microphone: true,
    chat: appConfig.supportsChatInput,
    camera: appConfig.supportsVideoInput,
    screenShare: appConfig.supportsVideoInput,
  };

  useEffect(() => {
    const lastRemoteMessage = [...messages].reverse().find((msg) => !msg.from?.isLocal);
    const lastMessage = messages.at(-1);
    const lastMessageIsLocal = lastMessage?.from?.isLocal === true;

    if (lastRemoteMessage && typeof lastRemoteMessage.message === 'string') {
      if (lastRemoteMessage.id !== lastRemoteMessageIdRef.current) {
        lastRemoteMessageIdRef.current = lastRemoteMessage.id;
        const text = lastRemoteMessage.message.toLowerCase();

        setActiveSpeaker((prev) => {
          if (text.includes('raven')) return 'assistant-1';
          if (text.includes('lumi')) return 'assistant-2';
          // Fallback: alternate on each remote message when names aren’t present
          return prev === 'assistant-1' ? 'assistant-2' : 'assistant-1';
        });
      }
    }

    if (scrollAreaRef.current && lastMessageIsLocal) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <section className="relative z-10 h-full w-full overflow-hidden text-white" {...props}>
      {/* Chat Transcript */}
      <div
        className={cn(
          'fixed inset-0 grid grid-cols-1 grid-rows-1',
          !chatOpen && 'pointer-events-none'
        )}
      >
        <Fade top className="absolute inset-x-4 top-0 h-40" />
        <ScrollArea ref={scrollAreaRef} className="px-4 pt-40 pb-[150px] md:px-6 md:pb-[200px]">
          <ChatTranscript
            hidden={!chatOpen}
            messages={messages}
            className="mx-auto max-w-2xl space-y-3 transition-opacity duration-300 ease-out"
          />
        </ScrollArea>
      </div>

      {/* Tile Layout */}
      <TileLayout chatOpen={chatOpen} activeSpeaker={activeSpeaker} />

      {/* Bottom */}
      <MotionBottom
        {...BOTTOM_VIEW_MOTION_PROPS}
        className="fixed inset-x-3 bottom-0 z-50 md:inset-x-12"
      >
        {appConfig.isPreConnectBufferEnabled && (
          <PreConnectMessage messages={messages} className="pb-4" />
        )}
        <div className="relative mx-auto max-w-3xl rounded-[28px] border border-white/10 bg-white/[0.06] px-2 pt-2 pb-4 shadow-[0_20px_90px_-55px_rgba(0,0,0,0.9)] backdrop-blur-2xl md:pb-10">
          <Fade bottom className="absolute inset-x-4 top-0 h-6 -translate-y-full" />
          <AgentControlBar
            controls={controls}
            isConnected={session.isConnected}
            onDisconnect={session.end}
            onChatOpenChange={setChatOpen}
            className="border-white/10 bg-white/[0.03] text-white shadow-[0_20px_70px_-60px_rgba(0,0,0,1)]"
          />
        </div>
      </MotionBottom>
    </section>
  );
};
