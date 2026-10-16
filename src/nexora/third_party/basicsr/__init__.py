"""From BasicSR (https://github.com/XPixelGroup/BasicSR, Apache-2.0), commit 8d56e3a045f9fb3e1d8872f92ee4a4f07f886b0a.

Taken for the Visual Quality engine (design 2026-10-16, section 9): NIQE (a picture's naturalness without a reference),
PSNR and SSIM (faithfulness to a reference), and synthetic degradations (known defects made on clean frames, to measure
whether a defect is found and how well a filter undoes it). BasicSR's own versions lean on PyTorch and OpenCV; here they
run on numpy, scipy and Pillow. The numerical cores are BasicSR's, line for line where marked.
"""
