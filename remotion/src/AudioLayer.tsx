import React from 'react';
import {Audio, Sequence, staticFile} from 'remotion';
import type {BgmProps, SfxProps} from './types';

const bgmVolume = (bgm: BgmProps) => (f: number) =>
  bgm.ducks.some((d) => f >= d.fromFrame && f < d.fromFrame + d.durationInFrames) ? 0 : bgm.volume;

export const AudioLayer: React.FC<{narration: string; bgm: BgmProps | null; sfx: SfxProps[]}> = ({
  narration,
  bgm,
  sfx,
}) => (
  <>
    <Audio src={staticFile(narration)} />
    {bgm ? <Audio src={staticFile(bgm.file)} loop volume={bgmVolume(bgm)} /> : null}
    {sfx.map((s, i) => (
      <Sequence key={i} from={s.fromFrame} layout="none">
        <Audio src={staticFile(s.file)} volume={0.9} />
      </Sequence>
    ))}
  </>
);
