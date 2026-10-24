# REPORT (run_2206)

**No LIRIS-ACCEDE on the volume**: distillation and the stress readout were trained on TikHarm (Harmful vs Safe),
split by uploader. There is **no out-of-domain test**; the stress AUROC below is in-domain (held-out uploaders).

## Data counts (clips with teacher labels and student features)
dataset split  label  n
   demo  test      0  3
   demo  test      1  4
tikharm  test      0 34
tikharm  test      1 19
tikharm train      0 66
tikharm train      1 71
tikharm   val      0 13
tikharm   val      1 23

## Student vs teacher (test split)
{
 "parcel_r_mean": 0.5028637051582336,
 "parcel_r_median": 0.5359625220298767,
 "roi_r": {
  "L_anterior_insula": 0.33409827947616577,
  "R_anterior_insula": 0.335605651140213,
  "dACC": 0.2222604751586914,
  "mPFC": 0.4025329649448395,
  "early_auditory": 0.5022093653678894,
  "early_visual": 0.6306406259536743
 },
 "n_timepoints": 513
}

Lag: 0 s (val ridge scores {0: 0.5130805969238281, 1: 0.4945416748523712, 2: 0.476865291595459, 3: 0.46393394470214844, 4: 0.4387746751308441, 5: 0.4310345947742462}). Text pathway active for 65% of clips.

## Stress
AUROC student readout: 0.6191950464396284; teacher-ROI readout: 0.6780185758513931; n_test=53
Shortcut baseline (logistic regression on raw encoder features, no brain model): 0.9272445820433437

**Label caveats.** TikHarm "Harmful" is a per-video moderation label (broad: dangerous acts, scams, bullying...),
not a stress rating, and only one 10 s window per video is used. In this data, Safe clips skew toward Vietnamese
creators and Harmful toward English-language creators, so a readout can partly learn language/region instead of harm;
the raw-feature baseline above shows how much is separable from surface cues alone. TRIBE's transcription is
hard-coded to English, so Vietnamese speech yields noisy text-pathway input.

## Ablations
vision only: {"parcel_r_mean": 0.4591180384159088, "parcel_r_median": 0.49289369583129883, "roi_r": {"L_anterior_insula": 0.24851252138614655, "R_anterior_insula": 0.1926649957895279, "dACC": 0.06948112696409225, "mPFC": 0.34869059920310974, "early_auditory": 0.34393468499183655, "early_visual": 0.5884718894958496}, "n_timepoints": 513}
audio only: {"parcel_r_mean": 0.22080053389072418, "parcel_r_median": 0.22455723583698273, "roi_r": {"L_anterior_insula": 0.19517651200294495, "R_anterior_insula": 0.1527874618768692, "dACC": 0.09954269230365753, "mPFC": 0.1490895003080368, "early_auditory": 0.39073097705841064, "early_visual": 0.16665980219841003}, "n_timepoints": 513}

## Demo clips ROI r (student vs teacher)
{
 "th_589900795163_e79a20": {
  "L_anterior_insula": 0.04592015966773033,
  "R_anterior_insula": -0.035636838525533676,
  "dACC": -0.15641383826732635,
  "mPFC": 0.37609338760375977,
  "early_auditory": 0.3741227984428406,
  "early_visual": 0.05253942683339119
 },
 "th_328683789574_1290c8": {
  "L_anterior_insula": 0.16350002586841583,
  "R_anterior_insula": -0.020773043856024742,
  "dACC": -0.001264624879695475,
  "mPFC": 0.5198701620101929,
  "early_auditory": 0.9266897439956665,
  "early_visual": 0.9323241710662842
 },
 "th_470774095136_48bcf7": {
  "L_anterior_insula": -0.6821683049201965,
  "R_anterior_insula": -0.6944888830184937,
  "dACC": -0.6563959121704102,
  "mPFC": -0.7404406666755676,
  "early_auditory": 0.5697295665740967,
  "early_visual": 0.8193128108978271
 },
 "th_998841744666_362464": {
  "L_anterior_insula": -0.3743774890899658,
  "R_anterior_insula": -0.5752242207527161,
  "dACC": -0.4287107586860657,
  "mPFC": -0.471356600522995,
  "early_auditory": 0.6274009346961975,
  "early_visual": 0.22536592185497284
 },
 "th_015694036225_df7fbf": {
  "L_anterior_insula": 0.6532754898071289,
  "R_anterior_insula": 0.5609527230262756,
  "dACC": 0.30765753984451294,
  "mPFC": 0.8485478162765503,
  "early_auditory": 0.7851217985153198,
  "early_visual": 0.874319851398468
 },
 "th_270716566791_ce9e09": {
  "L_anterior_insula": 0.4395304322242737,
  "R_anterior_insula": 0.4881058931350708,
  "dACC": 0.4911055564880371,
  "mPFC": -0.21251986920833588,
  "early_auditory": 0.6880176663398743,
  "early_visual": 0.8773503303527832
 },
 "th_380503403802_1f171e": {
  "L_anterior_insula": 0.4859969913959503,
  "R_anterior_insula": 0.4097605347633362,
  "dACC": 0.37671366333961487,
  "mPFC": -0.17857956886291504,
  "early_auditory": 0.7923102974891663,
  "early_visual": 0.6006870269775391
 }
}

## Log
clips with teacher+features: 233
   dataset  split  label   n
0     demo   test      0   3
1     demo   test      1   4
2  tikharm   test      0  34
3  tikharm   test      1  19
4  tikharm  train      0  66
5  tikharm  train      1  71
6  tikharm    val      0  13
7  tikharm    val      1  23
train 137 val 36 test 53 demo 7
lag scores (val mean parcel r): {0: 0.5130805969238281, 1: 0.4945416748523712, 2: 0.476865291595459, 3: 0.46393394470214844, 4: 0.4387746751308441, 5: 0.4310345947742462} -> lag 0
[both] best val parcel r = 0.554
test: {"parcel_r_mean": 0.5028637051582336, "parcel_r_median": 0.5359625220298767, "roi_r": {"L_anterior_insula": 0.33409827947616577, "R_anterior_insula": 0.335605651140213, "dACC": 0.2222604751586914, "mPFC": 0.4025329649448395, "early_auditory": 0.5022093653678894, "early_visual": 0.6306406259536743}, "n_timepoints": 513}
stress AUROC student 0.6191950464396284 teacher 0.6780185758513931
shortcut baseline AUROC (raw features, no brain model): 0.9272445820433437
demo traces: 60 clips, 24 with English speech
exported student_head {"fp32": {"file": "student_head.fp32.onnx", "mb": 9.67, "max_rel_err_vs_torch": 0.0}, "fp16": {"file": "student_head.fp16.onnx", "mb": 4.84, "max_rel_err_vs_torch": 0.00047}, "int8": {"file": "student_head.int8.onnx", "mb": 2.46, "max_rel_err_vs_torch": 0.13427}, "inputs": {"feats": [1, 3, 2496]}, "outputs": ["parcels", "roi"]}
exported vision_encoder {"fp32": {"file": "vision_encoder.fp32.onnx", "mb": 86.1, "max_rel_err_vs_torch": 0.0}, "fp16": {"file": "vision_encoder.fp16.onnx", "error": "[ONNXRuntimeError] : 1 : FAIL : Load model from /workspace/export/vision_encoder.fp16.onnx failed:Type Error: Type (tensor(float16)) of output arg (/visual/trunk/stages.3/blocks/blocks.0/token_mixer/Cast_output_0) of node (/visual/trunk/stages.3/blocks/blocks.0/token_mixer/Cast) does not match expec"}, "int8": {"file": "vision_encoder.int8.onnx", "mb": 22.46, "max_rel_err_vs_torch": 1.03691}, "inputs": {"image": [1, 3, 224, 224]}, "outputs": ["embedding"]}
exported audio_encoder {"fp32": {"file": "audio_encoder.fp32.onnx", "mb": 11.93, "max_rel_err_vs_torch": 0.0}, "fp16": {"file": "audio_encoder.fp16.onnx", "mb": 6.04, "max_rel_err_vs_torch": 0.00322}, "int8": {"file": "audio_encoder.int8.onnx", "mb": 3.25, "max_rel_err_vs_torch": 0.08791}, "inputs": {"logmel": [1, 1, 128, 101]}, "outputs": ["embedding"]}
[vision_only] best val parcel r = 0.442
[audio_only] best val parcel r = 0.279