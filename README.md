# Gauge

Film an experiment on your phone, tap what moves, and Gauge finds the physical law behind it, then tries to prove itself wrong on a second recording.

Built for the Meta Global AI Developer Hackathon, Push the Frontier theme. All code here was written during the hackathon.

## How it works

1. **Read:** Muse Spark watches the clip and Muse Voice Transcribe hears your narration, so saying "this ruler is 30 cm" sets the length for you.
2. **Measure:** you tap the object once. SAM 3.1 follows it through every frame with no training, and each sample is timed from the frame's real timestamp, since phones record at a variable frame rate.
3. **Find the law:** a Muse Spark agent checks the data, picks the window that isolates the physics, and compares candidate laws by AICc.
4. **Try to break it:** the agent proposes a second recording. Gauge freezes the law's constants from run 1 and scores how well they predict run 2.

## Why the numbers can be trusted

- Spark chooses what to fit, but it can only report a result by citing a fit ID computed in code, so it cannot invent a value.
- The pass or fail verdict comes from code, never from the model.
- The error bar includes uncertainty from your taps on the reference, which is usually larger than the fit error.
- Clipped boxes at the frame edge and single-frame jumps to another object are removed, and suspicious timing raises a visible warning.

## Results on real footage

### Gravity on the Moon

The sample is the Apollo 16 jump salute from 1972. Gauge measures the first jump, then uses the frozen law to predict the second.

| Test | Result |
| --- | --- |
| Jump 1, acceleration | 1.61 m/s² in two repeat runs, against the accepted 1.62 m/s² |
| Jump 2, free fit | 1.69 m/s², a 5% difference |
| Jump 1 law tested on jump 2 | Passed |

The scale is the weak point. It assumes the backpack stack is 0.914 m tall (a 26 inch PLSS plus a 10 inch OPS) and that the tracked box spans it. Fitting different windows by hand moved the result by about 5%, and the app's error bar covers only the fit and the taps, so read this as about 1.65 ± 0.15 m/s², clearly lunar and about a sixth of Earth's gravity. Nothing here was calibrated from a published jump height, because those figures assume lunar gravity.

### Earth

Tested on clips from the Tracker physics sample pack, which are not included in this repo.

| Test | Result |
| --- | --- |
| Ball drop, gravity | 9.69 ± 0.05 m/s², assuming the stick's stripes are 10 cm apart |
| Law from the drop tested on a ball thrown upward | Passed, 9.57 m/s² on run 2, a 1.3% difference |
| Pendulum period, 1 m length | 2.04 s against about 2.06 s predicted at this swing size |
| Law from the drop tested on the pendulum | Correctly failed |

## Footage credit

Sample clips are cut from the Apollo 16 jump salute by NASA, digitized by Ken Glover, from the [Apollo Lunar Surface Journal](https://apollojournals.org/alsj/a16/a16salute.mpg). Use here does not imply endorsement by NASA.

## Meta models used

| Model | Job |
| --- | --- |
| SAM 3.1 | Tracks the tapped object through the video |
| Muse Spark 1.3 | Reads the video and runs the analysis agent with tool calls |
| Muse Voice Transcribe | Turns narration into the reference length and timed notes |

## Run it

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and ffmpeg.

```bash
cp .env.example .env
```

Add your Meta Model API key to `.env`, then:

```bash
uv sync
```

```bash
uv run uvicorn gauge.app:app --port 8060
```

Run the tests with:

```bash
uv run pytest
```

## Spending limits

The Meta Model API has no hard spend cap, so Gauge keeps its own ledger and refuses paid calls past `GAUGE_BUDGET_USD`, which defaults to 100. Each visitor is limited to 12 runs per hour.
