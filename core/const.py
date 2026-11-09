"""全局常量：图片扩展名、打分分档、硬伤标记位、算法阈值。"""

from __future__ import annotations

# ---------- 支持的照片格式 ----------
# 普通位图
COMMON_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
# 相机 RAW：本身打不开，但里面都嵌着全尺寸 JPEG 预览（见 core/raw.py）
RAW_EXTS = {
    ".cr2", ".cr3", ".crw",            # Canon
    ".nef", ".nrw",                    # Nikon
    ".arw", ".srf", ".sr2",            # Sony
    ".raf",                            # Fujifilm
    ".rw2", ".raw",                    # Panasonic
    ".orf",                            # Olympus
    ".pef", ".dng",                    # Pentax / Adobe DNG
    ".srw",                            # Samsung
    ".3fr", ".fff",                    # Hasselblad
    ".erf", ".kdc", ".mef", ".mos",    # 其它少见机型
    ".iiq", ".x3f", ".rwl", ".dcr",
}
IMAGE_EXTS = COMMON_EXTS | RAW_EXTS

# ---------- 打水分档（与产品文档 §4.4 一致） ----------
# 5 星 → 精选；3-4 星 → 待定；1-2 星 → 淘汰；0 星 → 未评分（不参与归档）
BUCKET_PICK = "pick"
BUCKET_MAYBE = "maybe"
BUCKET_REJECT = "reject"
BUCKET_NONE = "none"

BUCKETS = (BUCKET_PICK, BUCKET_MAYBE, BUCKET_REJECT, BUCKET_NONE)

BUCKET_LABEL = {
    BUCKET_PICK: "精选",
    BUCKET_MAYBE: "待定",
    BUCKET_REJECT: "淘汰",
    BUCKET_NONE: "未评分",
}

# 归档时落地到根目录下的子文件夹名
BUCKET_DIRNAME = {
    BUCKET_PICK: "精选",
    BUCKET_MAYBE: "待定",
    BUCKET_REJECT: "淘汰",
}


def bucket_of(score: int) -> str:
    """星级 → 分档。"""
    if score >= 5:
        return BUCKET_PICK
    if score >= 3:
        return BUCKET_MAYBE
    if score >= 1:
        return BUCKET_REJECT
    return BUCKET_NONE


# ---------- 硬伤标记位（photo.flags 位掩码） ----------
FLAG_BLUR = 1 << 0        # 失焦
FLAG_OVEREXPOSED = 1 << 1  # 过曝
FLAG_UNDEREXPOSED = 1 << 2  # 暗部丢失
FLAG_LOWRES = 1 << 3      # 分辨率过低
FLAG_CLOSED_EYES = 1 << 4  # 闭眼（P2，接云 API 后再启用）

FLAG_LABELS = (
    (FLAG_BLUR, "失焦"),
    (FLAG_OVEREXPOSED, "过曝"),
    (FLAG_UNDEREXPOSED, "欠曝"),
    (FLAG_LOWRES, "分辨率低"),
    (FLAG_CLOSED_EYES, "闭眼"),
)


def flag_text(flags: int) -> str:
    """把位掩码翻成中文短语，用「·」连接；无标记时返回空串。"""
    return "·".join(text for bit, text in FLAG_LABELS if flags & bit)


def flag_short(flags: int) -> str:
    """取第一个标记，用于缩略图角标（短文案）。"""
    for bit, text in FLAG_LABELS:
        if flags & bit:
            return text
    return ""


# ---------- 硬伤判定阈值（产品文档 §4.9） ----------
SHARP_BLUR_MAX = 60.0        # Laplacian 方差低于此视为失焦
EXPOSURE_HIGHLIGHT = 250     # 直方图高光起始灰度
EXPOSURE_SHADOW = 5          # 直方图暗部截止灰度
OVEREXPOSED_RATIO = 0.08     # 高光像素占比超过 8% 视为过曝
UNDEREXPOSED_RATIO = 0.12    # 暗部像素占比超过 12% 视为欠曝
MIN_MEGAPIXEL = 1.0          # 低于 100 万像素视为分辨率过低

# ---------- 连拍分组参数 ----------
BURST_TIME_GAP = 2.0         # 相邻两张拍摄时间差（秒）以内视为同一串
BURST_HAMMING_MAX = 10       # dHash 汉明距离上限，超过则判定为不同画面

# ---------- 缩略图 ----------
THUMB_SIZES = (200, 320, 480, 720, 1080)  # 按格子尺寸就近取档
THUMB_QUALITY = 86
