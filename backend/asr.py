"""
ASR (Automatic Speech Recognition) module using GLM-ASR.

GLM-ASR-Nano-2512 is a robust open-source speech recognition model from Zhipu AI.
Repository: https://github.com/zai-org/GLM-ASR

Requirements:
- transformers (latest from source recommended)
- torch with CUDA support
- ffmpeg (system package)
"""

import os
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

# Check if GLM-ASR dependencies are available
GLM_ASR_AVAILABLE = False
GLM_ASR_ERROR = None
TORCH_DEVICE = "cpu"

try:
    import torch
    TORCH_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    
    from transformers import AutoModelForSeq2SeqLM, AutoProcessor
    GLM_ASR_AVAILABLE = True
        
except ImportError as e:
    GLM_ASR_ERROR = f"GLM-ASR 依赖未安装: {e}. 请运行: pip install git+https://github.com/huggingface/transformers.git"

# Model configuration
GLM_ASR_MODEL_ID = os.environ.get("GLM_ASR_MODEL", "zai-org/GLM-ASR-Nano-2512")

# Global model and processor (lazy loading)
_model = None
_processor = None


def _convert_audio_to_wav(input_path: str, output_path: str) -> bool:
    """Convert audio file to WAV format using ffmpeg."""
    try:
        subprocess.run([
            'ffmpeg', '-y', '-i', input_path,
            '-ar', '16000',  # 16kHz sample rate
            '-ac', '1',      # mono
            '-f', 'wav',
            output_path
        ], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[ASR] ffmpeg conversion failed: {e}")
        return False


def _load_model():
    """Lazy load the GLM-ASR model."""
    global _model, _processor, TORCH_DEVICE
    
    if not GLM_ASR_AVAILABLE:
        raise RuntimeError(GLM_ASR_ERROR)
    
    if _model is None or _processor is None:
        import torch
        
        # Re-check CUDA availability
        TORCH_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        
        print(f"[ASR] Loading GLM-ASR model: {GLM_ASR_MODEL_ID}")
        print(f"[ASR] Device: {TORCH_DEVICE}")
        
        # Load processor (official way from zhipu docs)
        _processor = AutoProcessor.from_pretrained(GLM_ASR_MODEL_ID)
        
        # Load model (official way from zhipu docs)
        _model = AutoModelForSeq2SeqLM.from_pretrained(
            GLM_ASR_MODEL_ID,
            dtype="auto",
            device_map="auto"
        )
        
        print(f"[ASR] Model loaded successfully")
    
    return _model, _processor


async def transcribe_audio(audio_path: str) -> str:
    """
    Transcribe audio file to text using GLM-ASR.
    
    Args:
        audio_path: Path to the audio file (WAV format preferred)
        
    Returns:
        Transcribed text
    """
    import torch
    
    if not GLM_ASR_AVAILABLE:
        raise RuntimeError(GLM_ASR_ERROR)
    
    # Convert to WAV if needed
    audio_path = str(Path(audio_path).resolve())
    wav_path = audio_path
    
    if not audio_path.lower().endswith('.wav'):
        wav_path = audio_path + '.wav'
        if not _convert_audio_to_wav(audio_path, wav_path):
            raise RuntimeError("音频格式转换失败，请确保已安装 ffmpeg")
    
    try:
        model, processor = _load_model()
        
        # Official API from zhipu docs
        inputs = processor.apply_transcription_request(wav_path)
        
        # Move inputs to model device and dtype
        inputs = inputs.to(model.device, dtype=model.dtype)
        
        # Generate transcription
        with torch.no_grad():
            outputs = model.generate(**inputs, do_sample=False, max_new_tokens=500)
        
        # Decode output (skip input tokens)
        transcription = processor.batch_decode(
            outputs[:, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )[0]
        
        return transcription.strip()
        
    finally:
        # Clean up temporary WAV file
        if wav_path != audio_path and os.path.exists(wav_path):
            os.remove(wav_path)


def get_asr_status() -> dict:
    """Get ASR module status."""
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    return {
        "available": GLM_ASR_AVAILABLE,
        "error": GLM_ASR_ERROR,
        "model": GLM_ASR_MODEL_ID if GLM_ASR_AVAILABLE else None,
        "device": device,
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "model_loaded": _model is not None,
        "trust_remote_code": True
    }
