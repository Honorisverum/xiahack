'use client';

import { useMemo } from 'react';
import { TokenSource } from 'livekit-client';
import {
  RoomAudioRenderer,
  SessionProvider,
  StartAudio,
  useSession,
} from '@livekit/components-react';
import type { AppConfig } from '@/app-config';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/livekit/toaster';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { getSandboxTokenSource } from '@/lib/utils';

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

function AppSetup() {
  useDebugMode({ enabled: IN_DEVELOPMENT });
  useAgentErrors();

  return null;
}

interface AppProps {
  appConfig: AppConfig;
}

export function App({ appConfig }: AppProps) {
  const tokenSource = useMemo(() => {
    return typeof process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT === 'string'
      ? getSandboxTokenSource(appConfig)
      : TokenSource.endpoint('/api/connection-details');
  }, [appConfig]);

  const session = useSession(
    tokenSource,
    appConfig.agentName ? { agentName: appConfig.agentName } : undefined
  );

  return (
    <SessionProvider session={session}>
      <AppSetup />
      <main className="relative min-h-svh overflow-hidden bg-[#05060f] text-white">
        <div className="pointer-events-none absolute inset-0 -z-10">
          <div className="absolute top-[-160px] -left-32 h-[360px] w-[360px] rounded-full bg-[#ff52d9]/15 blur-3xl" />
          <div className="absolute top-[35%] right-[-140px] h-[400px] w-[400px] rounded-full bg-[#79e8ff]/14 blur-3xl" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_20%,rgba(141,107,255,0.08),transparent_35%),radial-gradient(circle_at_80%_70%,rgba(121,232,255,0.08),transparent_32%)]" />
          <div className="absolute inset-0 [background-image:linear-gradient(rgba(255,255,255,0.14)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.14)_1px,transparent_1px)] [background-size:140px_140px] opacity-[0.07]" />
        </div>

        <div className="relative z-10 flex min-h-svh items-center justify-center px-3 py-10 md:px-8 lg:px-12">
          <ViewController appConfig={appConfig} />
        </div>
      </main>
      <StartAudio label="Start Audio" />
      <RoomAudioRenderer />
      <Toaster />
    </SessionProvider>
  );
}
