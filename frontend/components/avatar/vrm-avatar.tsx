'use client';

import React, { useEffect, useRef, useState } from 'react';
import type { TrackReference } from '@livekit/components-react';
import { Track } from 'livekit-client';
import { cn } from '@/lib/utils';

type VrmAvatarProps = {
  vrmSrc: string;
  audioTrack?: TrackReference;
  className?: string;
};

/**
 * Lightweight VRM viewer with lip sync driven by a LiveKit audio track.
 * Uses dynamic imports to avoid SSR issues with three.js.
 */
export function VrmAvatar({ vrmSrc, audioTrack, className }: VrmAvatarProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const setMouthOpenRef = useRef<(v: number) => void>(() => {});
  const [debugLevel, setDebugLevel] = useState<number>(0);
  const [debugStatus, setDebugStatus] = useState<string>('idle');
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    if (!mountRef.current) return;
    let disposed = false;
    let renderer: any;
    let scene: any;
    let camera: any;
    let currentVrm: any;
    let mixer: any;
    let idleAction: any;
    let animationFrame: number;
    let idleTime = 0;
    const idleBones: Array<{ bone: any; base: any; name: string }> = [];

    const start = async () => {
      console.info('[VRM] initializing loader for', vrmSrc);
      const THREE = await import('three');
      const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js');
      const { VRMLoaderPlugin, VRMUtils, VRMExpressionPresetName } = await import('@pixiv/three-vrm');
      const tmpQuat = new THREE.Quaternion();
      const tmpEuler = new THREE.Euler();

      const cacheIdleBones = () => {
        const humanoid = currentVrm?.humanoid;
        if (!humanoid) return;
        idleBones.length = 0;
        const names = ['spine', 'chest', 'neck', 'head', 'leftUpperArm', 'rightUpperArm'];
        names.forEach((name) => {
          const bone = humanoid.getNormalizedBoneNode(name);
          if (bone) {
            idleBones.push({ bone, base: bone.quaternion.clone(), name });
          }
        });
      };

      const applyProceduralIdle = (delta: number) => {
        if (!idleBones.length) return;
        idleTime += delta;
        const t = idleTime;
        const motionScale = 0.25;
        const breathe = Math.sin(t * 1.2) * 0.015 * motionScale;
        const sway = Math.sin(t * 0.8) * 0.06 * motionScale;
        const nod = Math.sin(t * 1.6) * 0.03 * motionScale;
        const armWave = Math.sin(t * 0.9) * 0.04 * motionScale;

        idleBones.forEach(({ bone, base, name }) => {
          tmpEuler.set(0, 0, 0, 'XYZ');
          if (name === 'spine' || name === 'chest') {
            tmpEuler.x += breathe;
            tmpEuler.y += sway * 0.4;
          } else if (name === 'neck' || name === 'head') {
            tmpEuler.x += nod * 0.6;
            tmpEuler.y += sway;
          } else if (name === 'leftUpperArm') {
            tmpEuler.z += armWave * 0.5;
            tmpEuler.x += breathe * 0.5;
          } else if (name === 'rightUpperArm') {
            tmpEuler.z -= armWave * 0.5;
            tmpEuler.x += breathe * 0.5;
          }
          tmpQuat.copy(base).multiply(tmpQuat.setFromEuler(tmpEuler));
          bone.quaternion.copy(tmpQuat);
        });
      };

      if (disposed) return;

      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
      });
      renderer.setClearColor(0x000000, 0);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(mountRef.current!.clientWidth, mountRef.current!.clientHeight);
      mountRef.current!.appendChild(renderer.domElement);

      scene = new THREE.Scene();

      camera = new THREE.PerspectiveCamera(
        25,
        mountRef.current!.clientWidth / mountRef.current!.clientHeight,
        0.1,
        50
      );
      camera.position.set(0, 1.35, 2.5);

      const directionalLight = new THREE.DirectionalLight(0xffffff, 1.1);
      directionalLight.position.set(1, 1, 1.5);
      scene.add(directionalLight);
      scene.add(new THREE.AmbientLight(0xffffff, 0.55));

      const loader = new GLTFLoader();
      loader.register((parser: any) => new VRMLoaderPlugin(parser));
      const gltf = await loader.loadAsync(vrmSrc);
      console.info('[VRM] gltf loaded', gltf);

      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);

      currentVrm = gltf.userData.vrm;
      currentVrm.scene.rotation.y = 0;
      scene.add(currentVrm.scene);
      cacheIdleBones();

      const box = new THREE.Box3().setFromObject(currentVrm.scene);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const portraitHeight = Math.max(size.y * 0.6, 1.0);
      const portraitDepth = Math.max(size.z * 2.2, 1.4);

      const headNode = currentVrm.humanoid?.getNormalizedBoneNode('head');
      const headPos = headNode
        ? headNode.getWorldPosition(new THREE.Vector3())
        : center.clone().add(new THREE.Vector3(0, portraitHeight * 0.4, 0));

      camera.position.set(
        headPos.x,
        headPos.y + portraitHeight * 0.15,
        headPos.z + Math.max(portraitDepth, 2.2)
      );
      camera.lookAt(headPos.x, headPos.y, headPos.z);

      console.info('[VRM] bounds', { size: size.toArray(), center: center.toArray(), head: headPos.toArray() });

      if (gltf.animations && gltf.animations.length > 0) {
        mixer = new THREE.AnimationMixer(currentVrm.scene);
        idleAction = mixer.clipAction(gltf.animations[0]);
        idleAction.reset().setLoop(THREE.LoopRepeat, Infinity).play();
      }

      const clock = new THREE.Clock();
      const mouthTarget = { value: 0 };
      setMouthOpenRef.current = (v: number) => {
        mouthTarget.value = THREE.MathUtils.clamp(v, 0, 1);
      };

      const resize = () => {
        if (!mountRef.current) return;
        const { clientWidth, clientHeight } = mountRef.current;
        camera.aspect = clientWidth / clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(clientWidth, clientHeight);
      };
      window.addEventListener('resize', resize);

      const animate = () => {
        if (disposed) return;
        animationFrame = requestAnimationFrame(animate);
        const delta = clock.getDelta();

        if (currentVrm?.expressionManager) {
          const manager = currentVrm.expressionManager;
          const currentMouth = manager.getValue(VRMExpressionPresetName.Aa) ?? 0;
          const nextMouth = THREE.MathUtils.damp(currentMouth, mouthTarget.value, 18, delta);
          manager.setValue(VRMExpressionPresetName.Aa, nextMouth);
        }

        applyProceduralIdle(delta);
        currentVrm?.update(delta);
        if (mixer) mixer.update(delta);
        renderer.render(scene, camera);
      };

      setStatus('ready');
      console.info('[VRM] ready');
      animate();

      return () => {
        window.removeEventListener('resize', resize);
      };
    };

    start()
      .catch((err) => {
        console.error('Failed to load VRM avatar', err);
        setStatus('error');
      })
      .then(() => {
        if (disposed) return;
      });

    return () => {
      disposed = true;
      cancelAnimationFrame(animationFrame);
      if (mixer) mixer.stopAllAction();
      renderer?.dispose();
      currentVrm?.dispose?.();
      if (mountRef.current?.firstChild) {
        mountRef.current.removeChild(mountRef.current.firstChild as Node);
      }
    };
  }, [vrmSrc]);

  useEffect(() => {
    if (!audioTrack) {
      setDebugStatus('no-ref');
      return;
    }
    if (!audioTrack.publication) {
      setDebugStatus('no-publication');
      return;
    }
    const track = audioTrack.publication.track;
    if (!track) {
      setDebugStatus('no-track');
      return;
    }
    // Only lip-sync to remote assistant audio, not local mic
    if (track.participant?.isLocal) {
      setDebugStatus('local-track');
      return;
    }
    const isAudioKind =
      (track as any).kind === 'audio' ||
      (track.mediaStreamTrack && track.mediaStreamTrack.kind === 'audio') ||
      track.source === Track.Source.Audio ||
      track.source === Track.Source.Microphone;
    if (!isAudioKind) {
      setDebugStatus(`non-audio:${track.source}`);
      return;
    }

    let rafId: number | undefined;
    let ctx: AudioContext | undefined;
    let analyser: AnalyserNode | undefined;
    let data: Float32Array | undefined;
    let frameCount = 0;

    let audioEl: HTMLAudioElement | null = null;
    const mediaFromTrack = (track as any).mediaStream;
    const mediaFromTrackAudio = track.mediaStreamTrack ? new MediaStream([track.mediaStreamTrack]) : null;
    if ((track as any).attach) {
      try {
        audioEl = (track as any).attach();
        if (audioEl) {
          audioEl.muted = true;
          audioEl.volume = 0;
          audioEl.play().catch(() => {});
        }
      } catch (err) {
        console.warn('[VRM] attach failed', err);
      }
    }
    const media =
      mediaFromTrack ||
      mediaFromTrackAudio ||
      ((audioEl as any)?.srcObject instanceof MediaStream ? (audioEl as any).srcObject : null);
    if (!media) {
      console.warn('[VRM] lip sync: no media stream on track', {
        trackSid: (track as any).sid,
        participant: track.participant?.identity,
      });
      setDebugStatus('no-media');
      return;
    }

    const setup = async () => {
      console.info('[VRM] starting lip sync analyser', {
        trackSid: (track as any).sid,
        participant: track.participant?.identity,
        isMuted: (track as any).isMuted,
      });
      setDebugStatus('starting');
      ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const source = ctx.createMediaStreamSource(media);
      analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.25;
      data = new Float32Array(analyser.fftSize);
      source.connect(analyser);

      let envelope = 0;
      const lipConfig = {
        gate: 0.03,
        attack: 40 / 1000,
        release: 220 / 1000,
        gain: 2.0,
        rmsTau: 80 / 1000,
      };
      let rmsSmooth = 0;
      const tick = () => {
        if (!analyser || !data) return;
        analyser.getFloatTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          sum += data[i] * data[i];
        }
        const rms = Math.sqrt(sum / data.length);
        const delta = 1 / 60;
        const rmsDecay = Math.exp(-delta / lipConfig.rmsTau);
        rmsSmooth = rms * (1 - rmsDecay) + rmsSmooth * rmsDecay;
        const gated = Math.max(0, rmsSmooth - lipConfig.gate) * lipConfig.gain;
        const target = Math.min(Math.max(gated * 3.2, 0), 1);
        const coefAttack = Math.exp(-delta / lipConfig.attack);
        const coefRelease = Math.exp(-delta / lipConfig.release);
        envelope = target > envelope
          ? target + (envelope - target) * coefAttack
          : target + (envelope - target) * coefRelease;
        setMouthOpenRef.current(Math.min(Math.max(envelope, 0), 1));
        if (frameCount++ % 10 === 0) {
          setDebugLevel(Math.min(Math.max(envelope, 0), 1));
          setDebugStatus(
            `sid:${(track as any).sid ?? 'n/a'} muted:${(track as any).isMuted ?? 'n/a'} pubMuted:${
              audioTrack.publication.isMuted ?? 'n/a'
            } src:${track.source}`
          );
        }
        rafId = requestAnimationFrame(tick);
      };
      tick();
    };

    setup();

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      analyser?.disconnect();
      if (ctx?.state !== 'closed') ctx?.close();
      if (audioEl && (track as any).detach) {
        try {
          (track as any).detach(audioEl);
        } catch {
          // ignore
        }
      }
    };
  }, [audioTrack?.publication?.track]);

  return (
    <div
      ref={mountRef}
      data-testid="vrm-avatar"
      className={cn('relative h-full w-full min-h-[280px] bg-black/70', className)}
    >
      {status !== 'ready' && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-white/80">
          {status === 'loading' ? 'Loading avatar…' : 'Avatar failed to load'}
        </div>
      )}
      <div className="pointer-events-none absolute left-2 top-2 rounded bg-black/60 px-2 py-1 text-[10px] text-white/70 space-y-0.5">
        <div>lvl {debugLevel.toFixed(2)}</div>
        <div>{debugStatus}</div>
      </div>
    </div>
  );
}
