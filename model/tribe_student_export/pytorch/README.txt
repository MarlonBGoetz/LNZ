student_head.pt = PyTorch state_dict of the `Head` class in train_export.py (F=2496 inputs, hidden 512,
causal conv over W=3 windows, outputs 148 parcels + 6 ROIs; input/output normalization stored as buffers).
encoders.py = the frozen MobileCLIP-S1 / EfficientAT mn10_as encoders and the exact preprocessing.
For the browser, use the ONNX files one folder up (see ../README.md).
