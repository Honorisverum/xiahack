'use client';

import React, { useEffect, useRef, useState } from 'react';
import type { TrackReference } from '@livekit/components-react';
import { Track } from 'livekit-client';
import { cn } from '@/lib/utils';
import { useSessionContext, useVoiceAssistant } from '@livekit/components-react';
import { VRMHumanBoneName } from '@pixiv/three-vrm';

type VrmAvatarProps = {
  vrmSrc: string;
  audioTrack?: TrackReference;
  className?: string;
  allowLocalAudio?: boolean;
  rotateY?: number;
  scale?: number;
  mirrorArms?: boolean;
};

/**
 * Lightweight VRM viewer with lip sync driven by a LiveKit audio track.
 * Uses dynamic imports to avoid SSR issues with three.js.
 */
export function VrmAvatar({
  vrmSrc,
  audioTrack,
  className,
  allowLocalAudio = false,
  rotateY = 0,
  scale = 1,
  mirrorArms = false,
}: VrmAvatarProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const setMouthOpenRef = useRef<(v: number) => void>(() => {});
  const [debugLevel, setDebugLevel] = useState<number>(0);
  const [debugStatus, setDebugStatus] = useState<string>('idle');
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const session = useSessionContext();
  const { state: assistantState } = useVoiceAssistant();
  const vowelPresetRef = useRef<'Aa' | 'Ih' | 'Ou'>('Aa');
  const vowelUntilRef = useRef<number>(0);

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
    let blinkTimer = 2.5 + Math.random() * 3.0;
    let blinkPhase = 0;
    let blinkValue = 0;
    let gazeTimer = 1.5 + Math.random() * 1.5;
    const gazeOffset = { x: 0, y: 0 };
    let breatheAmp = 0.014;
    let swayAmp = 0.05;
    let nodAmp = 0.025;
    let armAmp = 0.03;
    const armTargets: Array<{ node: any; base: any; quat: any }> = [];
    const armPoseBase = [
      // Shoulders: downward tilt with a bit more outward roll
      { name: 'J_Bip_L_Shoulder', degX: -10, degZ: -15 },
      { name: 'J_Bip_R_Shoulder', degX: -10, degZ: 15 },
      // Upper arms: hang down with a wider flare to clear hips/skirt
      { name: 'J_Bip_L_UpperArm', degX: -10, degZ: -65 },
      { name: 'J_Bip_R_UpperArm', degX: -10, degZ: 65 },
      // Lower arms: mild bend and slight outward
      { name: 'J_Bip_L_LowerArm', degX: -18, degZ: -8 },
      { name: 'J_Bip_R_LowerArm', degX: -18, degZ: 8 },
    ];
    let spinePause = 0;
    let spinePhase = 0;
    let spineNoise = 0;
    let spineNoiseSpeed = 0.35 + Math.random() * 0.2;
    let breatheAmpTarget = breatheAmp;
    let swayAmpTarget = swayAmp;
    let nodAmpTarget = nodAmp;
    let armAmpTarget = armAmp;
    let breatheFreq = 1.0;
    let swayFreq = 0.85;
    let nodFreq = 1.2;
    let armFreq = 0.95;
    let breatheFreqTarget = breatheFreq;
    let swayFreqTarget = swayFreq;
    let nodFreqTarget = nodFreq;
    let armFreqTarget = armFreq;
    let ampTimer = 8 + Math.random() * 6;
    let tiltTimer = 6 + Math.random() * 6;
    let tiltPhase = 0;
    let tiltValue = 0;
    let tiltTarget = 0;

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
        const names = [
          'spine',
          'chest',
          'neck',
          'head',
          'leftShoulder',
          'rightShoulder',
          'leftUpperArm',
          'rightUpperArm',
          'leftLowerArm',
          'rightLowerArm',
        ];
        const axisZ = new THREE.Vector3(0, 0, 1);
        const baseOffsets: Record<string, number> = {
          leftShoulder: -15,
          rightShoulder: 15,
          leftUpperArm: -80,
          rightUpperArm: 80,
          leftLowerArm: -25,
          rightLowerArm: 25,
        };
        names.forEach((name) => {
          const bone = humanoid.getNormalizedBoneNode(name);
          if (bone) {
            const base = bone.quaternion.clone();
            const offset = baseOffsets[name];
            if (offset !== undefined) {
              base.premultiply(new THREE.Quaternion().setFromAxisAngle(axisZ, THREE.MathUtils.degToRad(offset)));
            }
            idleBones.push({ bone, base, name });
          }
        });
      };

      const applyProceduralIdle = (delta: number) => {
        if (!idleBones.length) return;
        idleTime += delta;
        const t = idleTime;
        const motionScale = 0.2;
        const breathe = Math.sin(t * breatheFreq) * breatheAmp * motionScale;
        const sway = Math.sin(t * swayFreq) * swayAmp * motionScale + spineNoise;
        const nod = Math.sin(t * nodFreq) * nodAmp * motionScale;
        const armWave = Math.sin(t * armFreq) * armAmp * motionScale;

        idleBones.forEach(({ bone, base, name }) => {
          tmpEuler.set(0, 0, 0, 'XYZ');
          if (name === 'spine' || name === 'chest') {
            tmpEuler.x += breathe;
            tmpEuler.y += sway * 0.25;
          } else if (name === 'neck' || name === 'head') {
            tmpEuler.x += nod * 0.6;
            tmpEuler.y += sway * 0.6;
            tmpEuler.z += tiltValue;
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
      const lookTarget = new THREE.Object3D();
      scene.add(lookTarget);

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
      console.info('[VRM] clips', gltf.animations?.map((a: any) => a.name || 'unnamed') ?? []);
      if ((gltf as any).parser?.json?.nodes) {
        const nodes = (gltf as any).parser.json.nodes;
        console.info(
          '[VRM] nodes sample',
          nodes
            .map((n: any, idx: number) => ({ idx, name: n.name }))
            .filter((n: any) => n.name && /arm|hand|shoulder/i.test(n.name))
            .slice(0, 20)
        );
      }

      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);

      currentVrm = gltf.userData.vrm;
      currentVrm.scene.rotation.y = rotateY;
      if (scale !== 1) {
        currentVrm.scene.scale.setScalar(scale);
      }
      scene.add(currentVrm.scene);
      // Relax arms from T-pose using actual humanoid names
      if (currentVrm.humanoid) {
        const human = currentVrm.humanoid;
        const humanNames = Object.entries((human as any).humanBones ?? {}).reduce(
          (acc: Record<string, string>, [k, v]: [string, any]) => {
            acc[k] = v?.node?.name;
            return acc;
          },
          {}
        );
        console.info('[VRM] humanoid bones', humanNames);
      }
      // Prepare arm targets to keep arms relaxed out of T-pose
      armTargets.length = 0;
      const armPose = armPoseBase.map((pose) => {
        const sign = mirrorArms ? -1 : 1;
        return { ...pose, degZ: (pose.degZ ?? 0) * sign };
      });

      armPose.forEach(({ name, degX = 0, degZ = 0 }) => {
        const node = gltf.scene.getObjectByName(name);
        if (node) {
          const base = node.quaternion.clone();
          const offset = new THREE.Quaternion().setFromEuler(
            new THREE.Euler(THREE.MathUtils.degToRad(degX), 0, THREE.MathUtils.degToRad(degZ))
          );
          const quat = base.clone().multiply(offset);
          armTargets.push({ node, base, quat });
        } else {
          console.warn('[VRM] relaxNode missing', name);
        }
      });
      cacheIdleBones();
      if (currentVrm.lookAt) {
        currentVrm.lookAt.target = lookTarget;
      }

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

        // Blink
        blinkTimer -= delta;
        if (blinkTimer <= 0) {
          blinkPhase = 1;
          blinkTimer = 2.5 + Math.random() * 3.0;
        }
        if (blinkPhase === 1) {
          blinkValue += delta / 0.08;
          if (blinkValue >= 1) {
            blinkValue = 1;
            blinkPhase = 2;
          }
        } else if (blinkPhase === 2) {
          blinkValue -= delta / 0.12;
          if (blinkValue <= 0) {
            blinkValue = 0;
            blinkPhase = 0;
          }
        }

        // Gaze micro-darts
        gazeTimer -= delta;
        if (gazeTimer <= 0) {
          gazeOffset.x = (Math.random() * 2 - 1) * 0.12;
          gazeOffset.y = (Math.random() * 2 - 1) * 0.1;
          gazeTimer = 1.5 + Math.random() * 1.5;
        }
        gazeOffset.x *= 0.92;
        gazeOffset.y *= 0.92;

        // Amplitude randomization
        ampTimer -= delta;
        if (ampTimer <= 0) {
          breatheAmpTarget = 0.012 + Math.random() * 0.01;
          swayAmpTarget = 0.045 + Math.random() * 0.03;
          nodAmpTarget = 0.02 + Math.random() * 0.02;
          armAmpTarget = 0.025 + Math.random() * 0.02;
          breatheFreqTarget = 0.85 + Math.random() * 0.35;
          swayFreqTarget = 0.7 + Math.random() * 0.4;
          nodFreqTarget = 1.0 + Math.random() * 0.4;
          armFreqTarget = 0.8 + Math.random() * 0.35;
          ampTimer = 8 + Math.random() * 6;
        }
        spinePause -= delta;
        if (spinePause <= 0) {
          spinePhase = Math.random() * Math.PI * 2;
          spinePause = 2.5 + Math.random() * 3.5;
          spineNoiseSpeed = 0.25 + Math.random() * 0.3;
        }
        spineNoise = Math.sin(clock.elapsedTime * spineNoiseSpeed + spinePhase) * 0.015;
        const damp = (cur: number, target: number, lambda: number) =>
          cur + (target - cur) * Math.min(1, lambda * delta);
        breatheAmp = damp(breatheAmp, breatheAmpTarget, 1.5);
        swayAmp = damp(swayAmp, swayAmpTarget, 1.5);
        nodAmp = damp(nodAmp, nodAmpTarget, 1.5);
        armAmp = damp(armAmp, armAmpTarget, 1.5);
        breatheFreq = damp(breatheFreq, breatheFreqTarget, 1.2);
        swayFreq = damp(swayFreq, swayFreqTarget, 1.2);
        nodFreq = damp(nodFreq, nodFreqTarget, 1.2);
        armFreq = damp(armFreq, armFreqTarget, 1.2);

        // Occasional head tilt bursts
        tiltTimer -= delta;
        if (tiltTimer <= 0) {
          tiltPhase = 1;
          tiltTarget = (Math.random() * 2 - 1) * 0.05; // ~3 deg
          tiltTimer = 7 + Math.random() * 6;
        }
        if (tiltPhase === 1) {
          tiltValue = THREE.MathUtils.damp(tiltValue, tiltTarget, 8, delta);
          if (Math.abs(tiltValue - tiltTarget) < 0.003) {
            tiltPhase = 2;
          }
        } else if (tiltPhase === 2) {
          tiltValue = THREE.MathUtils.damp(tiltValue, 0, 6, delta);
          if (Math.abs(tiltValue) < 0.001) {
            tiltPhase = 0;
            tiltValue = 0;
          }
        }

        if (currentVrm?.expressionManager) {
          const manager = currentVrm.expressionManager;
          const currentMouth = manager.getValue(VRMExpressionPresetName.Aa) ?? 0;
          const nextMouth = THREE.MathUtils.damp(currentMouth, mouthTarget.value, 18, delta);
          const now = performance.now();
          const activePreset =
            now < vowelUntilRef.current ? vowelPresetRef.current : VRMExpressionPresetName.Aa;
          // Always drive base open (Aa) so lips move even without vowel inference
          manager.setValue(VRMExpressionPresetName.Aa, nextMouth);
          manager.setValue(
            VRMExpressionPresetName.Ih,
            activePreset === 'Ih' ? nextMouth * 0.9 : 0
          );
          manager.setValue(
            VRMExpressionPresetName.Ou,
            activePreset === 'Ou' ? nextMouth * 0.9 : 0
          );
          manager.setValue(VRMExpressionPresetName.Blink, Math.min(Math.max(blinkValue, 0), 1));
        }

        applyProceduralIdle(delta);
        if (currentVrm?.lookAt) {
          lookTarget.position.set(gazeOffset.x * 0.5, 1.35 + gazeOffset.y * 0.35, 0.6);
        }
        currentVrm?.update(delta);
        // Force relaxed arms each frame
        armTargets.forEach(({ node, base, quat }) => {
          node.quaternion.copy(quat ?? base);
          node.updateMatrixWorld(true);
        });
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
    // Only lip-sync to remote audio unless allowLocalAudio is true
    if (!allowLocalAudio && track.participant?.isLocal) {
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

  // Capture assistant transcript vowels to shape mouth briefly
  useEffect(() => {
    const text = assistantState?.lastTranscription?.text;
    if (!text) return;
    const vowels = text.toLowerCase().match(/[aeiou]/g);
    if (!vowels?.length) return;
    const last = vowels.at(-1) ?? 'a';
    const preset: 'Aa' | 'Ih' | 'Ou' =
      last === 'u' ? 'Ou' : last === 'i' || last === 'e' ? 'Ih' : 'Aa';
    vowelPresetRef.current = preset;
    vowelUntilRef.current = performance.now() + 180;
  }, [assistantState?.lastTranscription?.text]);

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
