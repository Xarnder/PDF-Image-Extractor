from pathlib import Path
import os
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get('PDF_EXTRACTOR_DATA', ROOT / 'data')).resolve()
MODELS = ROOT / 'models'
for directory in (DATA, DATA / 'documents', DATA / 'cache', DATA / 'exports', ROOT / 'logs', MODELS):
    directory.mkdir(parents=True, exist_ok=True)


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['native', 'fast', 'balanced', 'maximum'] = 'balanced'
    format: Literal['original', 'png', 'jpg'] = 'png'
    preference: Literal['auto', 'source', 'displayed'] = 'auto'
    resolution: Literal['source', 'dpi'] = 'source'
    dpi: int = Field(300, ge=72, le=1200)
    jpeg_quality: int = Field(98, ge=1, le=100)
    jpeg_background: str = Field('#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')
    preserve_metadata: bool = False
    min_dimension: int = Field(80, ge=16, le=2000)
    min_area: float = Field(0.004, ge=0.0001, le=0.5)
    padding: float = Field(0, ge=0, le=36)
    sensitivity: float = Field(0.5, ge=0, le=1)
    gutter_sensitivity: float = Field(0.5, ge=0, le=1)
    refinement: float = Field(0.5, ge=0, le=1)
    ai_threshold: float = Field(0.5, ge=0.1, le=0.95)
    ai_enabled: bool = False
    content_analysis: bool = True
    face_priority: bool = True
    ai_resolution: int = Field(1024, ge=512, le=2048)
    device: Literal['auto', 'cpu', 'mps', 'cuda'] = 'auto'
    duplicate_distance: int = Field(6, ge=0, le=20)
    skip_exact_duplicates: bool = False
    workers: int = Field(1, ge=1, le=4)
    memory_mb: int = Field(2048, ge=512, le=16384)
    page_timeout: int = Field(120, ge=10, le=600)
    max_pixels: int = Field(60000000, ge=1000000, le=150000000)
    output_directory: str = ''
    automatic_export: bool = False
    theme: Literal['dark', 'light', 'system'] = 'dark'


def safe_name(name: str, fallback: str = 'document') -> str:
    import re
    result = re.sub(r'[^\w .-]', '_', Path(name.replace('\\', '/')).name).strip(' .')[:100]
    return result or fallback


def check_disk(path: Path, required: int = 256 * 1024 * 1024):
    import shutil
    if shutil.disk_usage(path).free < required:
        raise ValueError('Insufficient disk space. Free some space and retry.')
