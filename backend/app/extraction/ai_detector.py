"""Optional Heron adapter. No downloads occur during inference or startup."""
import importlib.util
from pathlib import Path
from app.core.config import MODELS
from app.extraction.geometry import Detection

MODEL_PATH = MODELS / 'heron'
_engines = {}


def model_status():
    deps = all(importlib.util.find_spec(name) for name in ('torch','transformers'))
    installed = (MODEL_PATH / 'config.json').is_file() and (MODEL_PATH / 'model.safetensors').is_file()
    return {'id':'heron','name':'Docling Heron','installed':installed,'dependencies':deps,
            'available':bool(deps and installed),'path':str(MODEL_PATH),
            'size':'~173 MB weights; PyTorch runtime installed separately', 'license':'Apache-2.0',
            'backend':'Transformers · CPU / MPS / CUDA', 'version': (MODEL_PATH / 'REVISION').read_text().strip() if (MODEL_PATH / 'REVISION').exists() else None,
            'error':None if deps else 'Optional runtime is not installed. Run ./scripts/install-ai.sh first.'}


def choose_device(torch, requested):
    if requested in ('auto','mps') and torch.backends.mps.is_available():
        return 'mps'
    if requested in ('auto','cuda') and torch.cuda.is_available():
        return 'cuda'
    return 'cpu'


class HeronDetector:
    name = 'Heron'

    def __init__(self, device='auto'):
        import torch
        from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection
        self.torch = torch
        self.device = choose_device(torch, device)
        self.warning = None
        self.processor = RTDetrImageProcessor.from_pretrained(MODEL_PATH, local_files_only=True)
        self.model = RTDetrV2ForObjectDetection.from_pretrained(MODEL_PATH, local_files_only=True).eval()
        try:
            self.model.to(self.device)
        except Exception as exc:
            self.warning = f'{self.device} unavailable; using CPU: {exc}'
            self.device = 'cpu'
            self.model.to('cpu')

    def detect(self, image, settings):
        inputs = self.processor(images=image, return_tensors='pt', size={'height':settings.ai_resolution,'width':settings.ai_resolution})
        def infer():
            with self.torch.inference_mode():
                return self.model(**{k:v.to(self.device) for k,v in inputs.items()})
        try:
            output = infer()
        except Exception as exc:
            if self.device == 'cpu':
                raise
            self.warning = f'{self.device} inference failed; using CPU: {exc}'
            self.device = 'cpu'
            self.model.to('cpu')
            output = infer()
        predictions = self.processor.post_process_object_detection(output, threshold=settings.ai_threshold, target_sizes=[image.size[::-1]])[0]
        result = []
        for score,label,box in zip(predictions['scores'],predictions['labels'],predictions['boxes']):
            label_name = self.model.config.id2label.get(int(label),str(int(label)))
            if 'picture' in label_name.lower() or 'figure' in label_name.lower() or int(label)==6:
                result.append(Detection(box.detach().cpu().tolist(), float(score), 'Heron', reasons=['Layout figure; photographic content needs verification']))
        return result


def detect_optional(image, settings):
    if not settings.ai_enabled or settings.mode not in ('balanced','maximum'):
        return [], 'CPU', []
    if not model_status()['available']:
        return [], 'CPU', ['Heron unavailable; native PDF and OpenCV remain active.']
    try:
        if settings.device not in _engines:
            _engines.clear()  # Only keep one model resident in each worker.
            _engines[settings.device] = HeronDetector(settings.device)
        engine = _engines[settings.device]
        result = engine.detect(image, settings)
        if settings.mode == 'maximum' and max(image.size)>1600:
            # Overlapping tiles allow small figures to be proposed independently.
            w,h = image.size
            for x,y in ((0,0),(w//3,0),(0,h//3),(w//3,h//3)):
                crop = image.crop((x,y,min(w,x+2*w//3),min(h,y+2*h//3)))
                for det in engine.detect(crop, settings):
                    det.bbox = [det.bbox[0]+x,det.bbox[1]+y,det.bbox[2]+x,det.bbox[3]+y]
                    result.append(det)
        return result, engine.device.upper(), [engine.warning] if engine.warning else []
    except Exception as exc:
        return [], 'CPU', [f'Heron failed; core detection continued: {type(exc).__name__}: {exc}']
