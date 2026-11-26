import React from 'react';
import {AbsoluteFill, Sequence} from 'remotion';
import type {CaptionProps} from './types';

const HIGHLIGHT = '#E5141B';

const boxStyle: React.CSSProperties = {
  position: 'absolute',
  bottom: '22%',
  left: '8%',
  right: '15%', // 쇼츠 오른쪽 액션 버튼 열 회피
  textAlign: 'center',
  fontFamily: "'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif",
  fontWeight: 900,
  fontSize: 74,
  lineHeight: 1.25,
  color: '#FFFFFF',
  WebkitTextStroke: '4px #000000',
  paintOrder: 'stroke fill',
  textShadow: '0 0 12px rgba(0,0,0,0.9), 0 4px 6px rgba(0,0,0,0.9)',
  wordBreak: 'keep-all',
};

export const Captions: React.FC<{captions: CaptionProps[]}> = ({captions}) => (
  <AbsoluteFill>
    {captions.map((c, i) => (
      <Sequence key={i} from={c.fromFrame} durationInFrames={c.durationInFrames} layout="none">
        <div style={boxStyle}>
          {c.spans.map((s, j) => (
            <span key={j} style={s.highlight ? {color: HIGHLIGHT} : undefined}>
              {s.text}
            </span>
          ))}
        </div>
      </Sequence>
    ))}
  </AbsoluteFill>
);
