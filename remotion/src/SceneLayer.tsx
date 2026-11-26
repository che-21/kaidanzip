import React from 'react';
import {AbsoluteFill, Img, Sequence, interpolate, random, staticFile, useCurrentFrame} from 'remotion';
import type {SceneProps} from './types';

const VIGNETTE =
  'radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 75%, rgba(0,0,0,0.92) 100%)';

const SceneImage: React.FC<{scene: SceneProps}> = ({scene}) => {
  const frame = useCurrentFrame(); // Sequence 기준 상대 frame
  const last = Math.max(1, scene.durationInFrames - 1);
  const progress = Math.min(1, frame / last); // 0..1 진행률 (시간 단위 변환 아님)

  let scale = interpolate(progress, [0, 1], [1.0, 1.12]);
  let translateX = 0;
  let opacity = 1;
  if (scene.motion === 'pan') {
    scale = 1.12;
    translateX = interpolate(progress, [0, 1], [-3, 3]);
  }
  if (scene.motion === 'fadeOut') {
    scale = interpolate(progress, [0, 1], [1.0, 1.06]);
    opacity = interpolate(progress, [0.7, 1], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  }

  let shakeX = 0;
  let shakeY = 0;
  if (scene.effects.includes('shake')) {
    shakeX = (random(`sx-${scene.index}-${frame}`) - 0.5) * 18;
    shakeY = (random(`sy-${scene.index}-${frame}`) - 0.5) * 18;
  }
  const glitchOn = scene.effects.includes('glitch') && random(`g-${scene.index}-${frame}`) < 0.35;
  const glitchShift = glitchOn ? (random(`gs-${scene.index}-${frame}`) - 0.5) * 60 : 0;

  const src = staticFile(scene.image);
  const imgStyle: React.CSSProperties = {width: '100%', height: '100%', objectFit: 'cover'};
  const transform = `translate(${translateX}%, 0) translate(${shakeX}px, ${shakeY}px) scale(${scale})`;

  return (
    <AbsoluteFill style={{opacity, overflow: 'hidden'}}>
      <AbsoluteFill style={{transform}}>
        <Img src={src} style={imgStyle} />
        {glitchOn ? (
          <>
            <AbsoluteFill style={{transform: `translateX(${glitchShift}px)`, mixBlendMode: 'screen', opacity: 0.6}}>
              <Img src={src} style={{...imgStyle, filter: 'sepia(1) saturate(6) hue-rotate(-50deg)'}} />
            </AbsoluteFill>
            <AbsoluteFill style={{transform: `translateX(${-glitchShift}px)`, mixBlendMode: 'screen', opacity: 0.5}}>
              <Img src={src} style={{...imgStyle, filter: 'sepia(1) saturate(6) hue-rotate(150deg)'}} />
            </AbsoluteFill>
          </>
        ) : null}
      </AbsoluteFill>
      {glitchOn
        ? [0, 1, 2, 3].map((i) => (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                top: `${random(`gb-${scene.index}-${frame}-${i}`) * 100}%`,
                height: 6 + random(`gh-${scene.index}-${frame}-${i}`) * 30,
                backgroundColor: 'rgba(255,255,255,0.18)',
              }}
            />
          ))
        : null}
      <AbsoluteFill style={{background: VIGNETTE}} />
    </AbsoluteFill>
  );
};

export const SceneLayer: React.FC<{scenes: SceneProps[]}> = ({scenes}) => (
  <AbsoluteFill>
    {scenes.map((s) => (
      <Sequence key={s.index} from={s.fromFrame} durationInFrames={s.durationInFrames} layout="none">
        <SceneImage scene={s} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
