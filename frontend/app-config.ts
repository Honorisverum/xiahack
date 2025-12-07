export interface AppConfig {
  pageTitle: string;
  pageDescription: string;
  companyName: string;

  supportsChatInput: boolean;
  supportsVideoInput: boolean;
  supportsScreenShare: boolean;
  isPreConnectBufferEnabled: boolean;

  logo: string;
  startButtonText: string;
  accent?: string;
  logoDark?: string;
  accentDark?: string;

  // for LiveKit Cloud Sandbox
  sandboxId?: string;
  agentName?: string;
}

export const APP_CONFIG_DEFAULTS: AppConfig = {
  companyName: 'Waifu Think Tank',
  pageTitle: 'Waifu Think Tank',
  pageDescription: 'Waifu Think Tank is your neon-lit command center for curious, sassy voice agents.',

  supportsChatInput: true,
  supportsVideoInput: true,
  supportsScreenShare: true,
  isPreConnectBufferEnabled: true,

  logo: '/waifu-think-tank.svg',
  accent: '#ff52d9',
  logoDark: '/waifu-think-tank.svg',
  accentDark: '#79e8ff',
  startButtonText: 'Launch the lab',

  // for LiveKit Cloud Sandbox
  sandboxId: undefined,
  agentName: undefined,
};
