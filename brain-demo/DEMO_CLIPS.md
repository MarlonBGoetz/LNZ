# Demo clips breakdown

These are the hand-picked demo clips from the TikHarm test split, held out of training. 8 were picked; 7 made the final run (TRIBE didn't finish the 8th before training started).

**Stress** is the end-of-clip stress score from 0 to 1. **r** is the per-clip correlation between the student's and TRIBE's second-by-second curves for each brain region; 1 is a perfect match.

Per-second curves: `demo/<clip_id>.json`. Watch them play: `live_demo.html`.

| Clip | Label | English speech | Length (s) | Student stress | Teacher stress | Insula L/R r | dACC r | mPFC r | Auditory r | Visual r |
|---|---|---|---|---|---|---|---|---|---|---|
| [th_589900795163_e79a20](demo/th_589900795163_e79a20.mp4) | Harmful | yes | 10 | 0.78 | 0.58 | 0.05 / -0.04 | -0.16 | 0.38 | 0.37 | 0.05 |
| [th_328683789574_1290c8](demo/th_328683789574_1290c8.mp4) | Harmful | no | 5 | 0.71 | 0.59 | 0.16 / -0.02 | -0.00 | 0.52 | 0.93 | 0.93 |
| [th_470774095136_48bcf7](demo/th_470774095136_48bcf7.mp4) | Harmful | yes | 10 | 0.79 | 0.50 | -0.68 / -0.69 | -0.66 | -0.74 | 0.57 | 0.82 |
| [th_998841744666_362464](demo/th_998841744666_362464.mp4) | Harmful | yes | 10 | 0.85 | 0.69 | -0.37 / -0.58 | -0.43 | -0.47 | 0.63 | 0.23 |
| [th_015694036225_df7fbf](demo/th_015694036225_df7fbf.mp4) | Safe | yes | 10 | 0.67 | 0.15 | 0.65 / 0.56 | 0.31 | 0.85 | 0.79 | 0.87 |
| [th_270716566791_ce9e09](demo/th_270716566791_ce9e09.mp4) | Safe | no | 10 | 0.47 | 0.60 | 0.44 / 0.49 | 0.49 | -0.21 | 0.69 | 0.88 |
| [th_380503403802_1f171e](demo/th_380503403802_1f171e.mp4) | Safe | no | 6 | 0.55 | 0.25 | 0.49 / 0.41 | 0.38 | -0.18 | 0.79 | 0.60 |
