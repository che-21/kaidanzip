// props.json 계약. 모든 시간 필드는 Python(kaidanzip.timeutil.ms_to_frames)이 계산한 frame 정수다.
// 이 레이어는 시간을 변환하거나 추정하지 않는다.

export type Motion = 'zoomIn' | 'pan' | 'fadeOut';
export type Effect = 'shake' | 'glitch';

export type SceneProps = {
  index: number;
  image: string;
  fromFrame: number;
  durationInFrames: number;
  motion: Motion;
  effects: Effect[];
};

export type Span = {text: string; highlight: boolean};

export type CaptionProps = {
  fromFrame: number;
  durationInFrames: number;
  spans: Span[];
};

export type SfxProps = {file: string; fromFrame: number};

export type BgmProps = {
  file: string;
  volume: number;
  ducks: {fromFrame: number; durationInFrames: number}[];
};

export type ShortProps = {
  durationInFrames: number;
  narration: string;
  bgm: BgmProps | null;
  scenes: SceneProps[];
  captions: CaptionProps[];
  sfx: SfxProps[];
};
