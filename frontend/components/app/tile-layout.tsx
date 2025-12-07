import React, { useMemo } from 'react';
import { Track } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import {
  type TrackReference,
  VideoTrack,
  useLocalParticipant,
  useVoiceAssistant,
} from '@livekit/components-react';
import { VrmAvatar } from '@/components/avatar/vrm-avatar';
import { cn } from '@/lib/utils';

const MotionContainer = motion.create('div');

const ANIMATION_TRANSITION = {
  type: 'spring',
  stiffness: 675,
  damping: 75,
  mass: 1,
};

export function useLocalTrackRef(source: Track.Source) {
  const { localParticipant } = useLocalParticipant();
  const publication = localParticipant.getTrackPublication(source);
  const trackRef = useMemo<TrackReference | undefined>(
    () => (publication ? { source, participant: localParticipant, publication } : undefined),
    [source, publication, localParticipant]
  );
  return trackRef;
}

interface TileLayoutProps {
  chatOpen: boolean;
  activeSpeaker?: 'assistant-1' | 'assistant-2';
}

export function TileLayout({ chatOpen, activeSpeaker = 'assistant-1' }: TileLayoutProps) {
  const { audioTrack: agentAudioTrack, videoTrack: agentVideoTrack } = useVoiceAssistant();
  const animationDelay = chatOpen ? 0 : 0.15;
  const isAvatar = agentVideoTrack !== undefined;
  const videoWidth = agentVideoTrack?.publication.dimensions?.width ?? 0;
  const videoHeight = agentVideoTrack?.publication.dimensions?.height ?? 0;
  const assistantOneTrack = activeSpeaker === 'assistant-1' ? agentAudioTrack : undefined;
  const assistantTwoTrack = activeSpeaker === 'assistant-2' ? agentAudioTrack : undefined;
  const tallTileSize = chatOpen
    ? 'h-[340px] w-[260px] lg:h-[360px] lg:w-[300px] max-w-[360px]'
    : 'h-[440px] w-[320px] lg:h-[460px] lg:w-[340px] max-w-[380px]';
  const tileChrome =
    'overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-[#0d0f1a]/85 via-[#070912]/90 to-[#05060f]/90 shadow-[0_35px_120px_-70px_rgba(0,0,0,0.9)] backdrop-blur-[3px]';
  const labelClass =
    'text-[11px] font-semibold uppercase tracking-[0.26em] text-white/60 drop-shadow';

  return (
    <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center px-4 pt-20 pb-32 md:px-8">
      <div className="flex w-full max-w-6xl flex-wrap items-start justify-center gap-10 md:gap-16 lg:gap-20">
        {/* Agent */}
        <div className="flex flex-col items-center gap-2">
          <AnimatePresence mode="popLayout">
            {!isAvatar && (
              <MotionContainer
                key="agent"
                layoutId="agent"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: chatOpen ? 1 : 1.2 }}
                transition={{ ...ANIMATION_TRANSITION, delay: animationDelay }}
            className={cn(tileChrome, tallTileSize, 'backdrop-blur-[2px]')}
          >
            <VrmAvatar
              vrmSrc="/charlotte-1.0.vrm"
              audioTrack={assistantOneTrack}
              avatarId="assistant"
              className="h-full w-full"
            />
          </MotionContainer>
        )}

            {isAvatar && (
              <MotionContainer
                key="avatar"
                layoutId="avatar"
                initial={{
                  scale: 1,
                  opacity: 1,
                  maskImage:
                    'radial-gradient(circle, rgba(0, 0, 0, 1) 0, rgba(0, 0, 0, 1) 20px, transparent 20px)',
                  filter: 'blur(20px)',
                }}
                animate={{
                  maskImage:
                    'radial-gradient(circle, rgba(0, 0, 0, 1) 0, rgba(0, 0, 0, 1) 500px, transparent 500px)',
                  filter: 'blur(0px)',
                  borderRadius: chatOpen ? 6 : 12,
                }}
                transition={{
                  ...ANIMATION_TRANSITION,
                  delay: animationDelay,
                  maskImage: { duration: 1 },
                  filter: { duration: 1 },
                }}
                className={cn(
                  'overflow-hidden bg-black drop-shadow-xl/80',
                  chatOpen ? 'h-[90px]' : 'h-auto w-full'
                )}
              >
                <VideoTrack
                  width={videoWidth}
                  height={videoHeight}
                  trackRef={agentVideoTrack}
                  className={cn(chatOpen && 'size-[90px] object-cover')}
                />
              </MotionContainer>
            )}
          </AnimatePresence>
          <div className={labelClass}>Assistant 1</div>
        </div>

        {/* Local mic avatar or fallback camera */}
        <div className="flex flex-col items-center gap-2">
          <MotionContainer
            key="assistant-2"
            layoutId="assistant-2"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: chatOpen ? 1 : 1.2 }}
            transition={{ ...ANIMATION_TRANSITION, delay: animationDelay + 0.05 }}
            className={cn(tileChrome, tallTileSize, 'backdrop-blur-[2px]')}
          >
            <VrmAvatar
              vrmSrc="/Ruby.vrm"
              audioTrack={assistantTwoTrack}
              allowLocalAudio={false}
              rotateY={Math.PI}
              mirrorArms
              avatarId="assistant-2"
              scale={0.9}
              className="h-full w-full"
            />
          </MotionContainer>
          <div className={labelClass}>Assistant 2</div>
        </div>
      </div>
    </div>
  );
}
