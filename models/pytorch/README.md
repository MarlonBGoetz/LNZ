`student_head.pt` is the PyTorch `state_dict` of the `Head` class in [`pipeline/train_export.py`](../../pipeline/train_export.py).
- Input: F=2496 window features.
- Architecture: hidden 512, causal conv over the last W=3 windows.
- Output: 148 Destrieux parcels + 6 ROIs.
- Input/output normalization is stored as buffers.

The frozen encoders and their exact preprocessing are in [`pipeline/encoders.py`](../../pipeline/encoders.py). For the browser, use the ONNX files one folder up (see [`../README.md`](../README.md)).
