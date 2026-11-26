import React from 'react';
import {AbsoluteFill} from 'remotion';
import {AudioLayer} from './AudioLayer';
import {Captions} from './Captions';
import {SceneLayer} from './SceneLayer';
import type {ShortProps} from './types';

export const HorrorShort: React.FC<ShortProps> = (props) => (
  <AbsoluteFill style={{backgroundColor: '#000'}}>
    <SceneLayer scenes={props.scenes} />
    <Captions captions={props.captions} />
    <AudioLayer narration={props.narration} bgm={props.bgm} sfx={props.sfx} />
  </AbsoluteFill>
);
