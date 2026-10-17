# Third-party OCR notices

Pokato 0.6.0 bundles local OCR dependencies and pretrained weights in its single
executable. Their upstream license files are retained through package data and
distribution metadata during the Windows build.

| Component | Version / models | License and source |
| --- | --- | --- |
| RapidOCR | 3.10.0 | Apache-2.0 · [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) |
| PaddleOCR weights distributed with RapidOCR | PP-OCRv6 detection/recognition small ONNX models; bundled classifier is unused | Apache-2.0 · [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) · see RapidOCR distribution's `MODEL_LICENSES.md` for Baidu attribution |
| ONNX Runtime | 1.24.4, CPU | MIT · [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime) |

The installed RapidOCR distribution includes `licenses/LICENSE` and
`licenses/MODEL_LICENSES.md`; ONNX Runtime includes its license and third-party
notices. The models are inference assets, not newly trained Pokato models.
