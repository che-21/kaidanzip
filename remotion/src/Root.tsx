import React from 'react';
import {Composition} from 'remotion';
import {HorrorShort} from './HorrorShort';
import type {ShortProps} from './types';

const defaultProps: ShortProps = {
  durationInFrames: 1,
  narration: 'narration.mp3',
  bgm: null,
  scenes: [],
  captions: [],
  sfx: [],
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="HorrorShort"
    component={HorrorShort}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={1}
    defaultProps={defaultProps}
    // 길이는 Python이 계산한 값을 그대로 쓴다.
    calculateMetadata={({props}) => ({durationInFrames: props.durationInFrames})}
  />
);
