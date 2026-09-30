# -*- coding: utf-8 -*-
"""启动音效（v3.6.2）：代码合成提示音，无需素材文件

- 双音「叮—咚」：G5(784Hz) → D5(587Hz)，指数衰减包络 + 轻二次谐波
- 通过 winsound 以内存 WAV 异步播放（不阻塞主线程、不落地临时文件）
- 按音量缓存合成结果
"""
import math
import struct

SAMPLE_RATE = 44100
NOTES = ((784.00, 0.00, 0.42), (587.33, 0.16, 0.60))   # (频率, 起始秒, 时长)
TOTAL_SECONDS = 0.90
DEFAULT_VOLUME = 0.6

_cache = {}


def _wrap_wav(pcm, sample_rate=SAMPLE_RATE, channels=1, bits=16):
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                                byte_rate, block_align, bits)
    data = b"data" + struct.pack("<I", len(pcm)) + pcm
    return header + fmt + data


def make_wav(volume=DEFAULT_VOLUME):
    """合成「叮—咚」提示音（WAV 字节；按音量缓存）"""
    key = round(max(0.0, min(1.0, float(volume))), 2)
    if key in _cache:
        return _cache[key]
    total = int(SAMPLE_RATE * TOTAL_SECONDS)
    frames = bytearray()
    gain = 0.42 * key
    for i in range(total):
        t = i / SAMPLE_RATE
        v = 0.0
        for freq, start, dur in NOTES:
            if start <= t < start + dur:
                tt = t - start
                env = math.exp(-tt * 6.2) * min(1.0, tt / 0.006)
                v += env * (math.sin(2 * math.pi * freq * tt) * 0.85
                            + math.sin(4 * math.pi * freq * tt) * 0.15)
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v * gain)) * 32767))
    data = _wrap_wav(bytes(frames))
    _cache[key] = data
    return data


def play(volume=DEFAULT_VOLUME):
    """异步播放提示音；任何异常都静默返回 False（不影响启动）"""
    try:
        import winsound
        winsound.PlaySound(make_wav(volume), winsound.SND_MEMORY | winsound.SND_ASYNC)
        return True
    except Exception:  # noqa: BLE001
        return False
