import Image from 'next/image';
import { Button } from '@/components/livekit/button';

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
  companyName: string;
  pageTitle: string;
  pageDescription: string;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  companyName,
  pageTitle,
  pageDescription,
  ref,
  ...props
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  const displayName = companyName || pageTitle || 'Waifu Think Tank';

  return (
    <div ref={ref} className="relative isolate w-full" {...props}>
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute top-0 -left-24 h-72 w-72 rounded-full bg-[#ff52d9]/30 blur-3xl" />
        <div className="absolute top-10 right-0 h-80 w-80 rounded-full bg-[#79e8ff]/25 blur-3xl" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(255,82,217,0.08),transparent_35%),radial-gradient(circle_at_80%_0%,rgba(121,232,255,0.08),transparent_30%),radial-gradient(circle_at_50%_70%,rgba(141,107,255,0.12),transparent_35%)]" />
        <div className="absolute inset-6 rounded-[32px] border border-white/10 bg-gradient-to-b from-white/5 via-white/0 to-white/0 shadow-[0_30px_120px_-60px_rgba(0,0,0,0.9)] backdrop-blur-xl" />
        <div className="absolute inset-0 [background-image:radial-gradient(circle_at_1px_1px,rgba(255,255,255,0.35),transparent_0)] [background-size:36px_36px] [opacity:.15]" />
      </div>

      <section className="relative mx-auto flex min-h-[78svh] max-w-6xl flex-col gap-10 px-4 py-10 md:px-10 md:py-14 lg:px-16">
        <header className="flex flex-col gap-6 border-b border-white/10 pb-8">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#ff52d9] via-[#8d6bff] to-[#79e8ff] shadow-lg shadow-fuchsia-500/30">
              <Image
                src="/waifu-think-tank.svg"
                alt="Waifu Think Tank logo"
                width={40}
                height={40}
                className="h-8 w-8"
                priority
              />
            </div>
            <div className="leading-tight">
              <p className="text-[10px] font-semibold tracking-[0.45em] text-white/60 uppercase">
                {displayName}
              </p>
              <p className="text-lg font-semibold text-white">Grok-flavored research lab</p>
            </div>
          </div>
        </header>

        <div className="space-y-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-[11px] font-semibold tracking-[0.28em] text-white/80 uppercase shadow-[0_15px_70px_-40px_rgba(121,232,255,0.8)]">
            <span className="h-1.5 w-1.5 rounded-full bg-gradient-to-r from-[#ff52d9] to-[#79e8ff]" />
            Grok attitude, anime brain
          </div>

          <div className="space-y-4">
            <h1 className="text-4xl leading-[1.05] font-semibold text-balance text-white md:text-5xl lg:text-6xl">
              {displayName}
            </h1>
            <p className="text-lg text-pretty text-white/75 md:text-xl">
              AI-powered brainstorm with heated debates on various topics — and ready-to-use action points at the end.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              size="lg"
              onClick={onStartCall}
              className="h-12 rounded-full bg-gradient-to-r from-[#ff52d9] via-[#8d6bff] to-[#79e8ff] px-8 text-sm font-bold tracking-[0.25em] text-[#0b0c11] uppercase shadow-[0_25px_70px_-35px_rgba(255,82,217,0.9)] transition hover:scale-[1.02] hover:shadow-[0_30px_90px_-40px_rgba(121,232,255,1)]"
            >
              {startButtonText}
            </Button>
            <Button
              variant="secondary"
              size="lg"
              asChild
              className="h-12 rounded-full border border-white/20 bg-white/5 px-6 text-xs font-semibold tracking-[0.18em] text-white/80 hover:bg-white/10"
            >
              <a
                href="https://docs.livekit.io/agents/start/voice-ai/"
                target="_blank"
                rel="noreferrer"
              >
                Voice AI quickstart
              </a>
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
};
