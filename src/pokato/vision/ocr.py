"""Local pretrained OCR. Packaged models are required; no runtime downloads."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np


@dataclass(frozen=True)
class Text:
    text: str
    score: float
    box: tuple


class LocalOCR:
    def __init__(self):
        import rapidocr
        from rapidocr import RapidOCR
        models = Path(rapidocr.__file__).parent/'models'
        paths = {name: models/file for name, file in (
            ('Det', 'PP-OCRv6_det_small.onnx'), ('Rec', 'PP-OCRv6_rec_small.onnx'))}
        if any(not path.is_file() for path in paths.values()):
            raise RuntimeError('OCR models are missing. Reinstall or rebuild Pokato.')
        self.engine = RapidOCR(params={
            'Global.log_level': 'error', 'Global.use_cls': False,
            'Global.max_side_len': 2400, 'Det.limit_side_len': 1200, 'Det.limit_type': 'max',
            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
            **{name+'.model_path': str(path) for name, path in paths.items()}})

    def text(self, image):
        array = np.asarray(image.convert('RGB'))[:, :, ::-1].copy()
        result = self.engine(array)
        if result.boxes is None or result.txts is None:
            return ()
        return tuple(Text(text, float(score), (float(box[:, 0].min()), float(box[:, 1].min()),
                     float(box[:, 0].max()), float(box[:, 1].max())))
                     for box, text, score in zip(result.boxes, result.txts, result.scores))

    def ranks(self, images):
        if not images:
            return ()
        result = self.engine.recognize_txt([np.asarray(im.convert('RGB'))[:, :, ::-1].copy() for im in images])
        return tuple((text.strip().upper(), float(score)) for text, score in zip(result.txts, result.scores))
