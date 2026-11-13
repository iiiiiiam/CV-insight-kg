"""Bounded one-level CV directions from title and corroborated source signals.

These are rule-normalized source classifications, not literal abstract evidence
or a new graph entity type. Unknown tasks are deliberately left unmapped.
"""

import re
from dataclasses import asdict

from .extraction import fingerprint

VERSION = "cv-combined-directions/2"

# Stable keys survive display-name changes. Keep this small and explicit rather
# than guessing a direction from arbitrary substrings or unrelated ML tasks.
DIRECTIONS = {
    "object-detection": ("目标检测", (
        "Object Detection", "3D object detection", "Open-Vocabulary Object Detection",
        "Oriented Object Detection", "Few-Shot Object Detection", "Camouflaged object detection")),
    "image-segmentation": ("图像分割", (
        "Image segmentation", "Instance Segmentation", "Semantic Segmentation",
        "3D semantic segmentation", "Medical Image Segmentation", "Few-Shot Segmentation",
        "Zero-shot segmentation", "Video segmentation")),
    "image-classification": ("图像分类", (
        "Image Classification", "Semi-Supervised Image Classification")),
    "visual-generation": ("图像与视频生成", (
        "Image generation", "Text-to-Image Generation", "Video generation")),
    "visual-editing": ("图像与视频编辑", ("Image editing", "Video Editing", "Image Inpainting")),
    "visual-restoration": ("图像与视频恢复", (
        "Image Restoration", "Video Restoration", "Image super-resolution", "Image Fusion")),
    "3d-vision": ("三维视觉", (
        "3D understanding", "3D Reconstruction", "Novel View Synthesis", "Inverse Rendering",
        "3D generation", "3D Occupancy Prediction")),
    "depth-and-geometry": ("深度与几何估计", (
        "Depth estimation", "Depth Completion", "Stereo Matching", "Surface Normal Estimation",
        "Optical Flow", "Visual SLAM", "Image Matching")),
    "pose-estimation": ("姿态估计", (
        "Pose Estimation", "3D Pose Estimation", "6D Pose Estimation", "Camera Pose Estimation")),
    "object-tracking": ("目标跟踪", ("Object Tracking", "3D Tracking")),
    "video-understanding": ("视频理解与动作识别", (
        "Video Understanding", "Video classification", "Action Recognition", "Temporal Action Localization")),
    "visual-retrieval": ("视觉检索", (
        "Image-Text Retrieval", "Person Re-Identification", "Visual Place Recognition",
        "Visual Place Recognition with Re-ranking")),
    "image-quality": ("图像质量评价", ("No-Reference Image Quality Assessment", "Image Quality Assessment")),
    "visual-anomaly": ("视觉异常检测", ("Image Anomaly Detection", "Deepfake Detection")),
}


DIRECTIONS.update({
    "vision-language": ("视觉语言理解", ()),
    "visual-efficiency": ("视觉模型效率优化", ()),
    "visual-security": ("视觉安全与水印", ()),
})

# Explicit task expressions, not model names such as Transformer or Diffusion.
EXTRA = {
    "object-detection": r"(?:species|camouflaged object|pedestrian|human) detection|object discovery",
    "image-segmentation": r"(?:panoptic|point cloud|open.vocabulary semantic) segmentation|lidar segmentation",
    "image-classification": r"(?:zero.shot|few.shot|incremental|face) (?:classification|recognition)|point cloud classification",
    "visual-generation": r"text.to.\s*(?:image|video|texture)|(?:face|image|video|caricature|texture) (?:generation|synthesis|prediction)|video generators",
    "visual-editing": r"image.to.image translation|face (?:swapping|reenactment|editing|retouching)",
    "visual-restoration": r"(?:image|video) (?:denoising|deblurring|enhancement)|image super.resolution|hdr deghosting",
    "3d-vision": r"multi.view reconstruction|radiance fields?|gaussian splatting|3d gaussians?|3d (?:shape|vision|scene|gan)|avatar|garment recovery",
    "depth-and-geometry": r"monocular depth estimation|multi.view stereo|absolute pose|structure.from|\bslam\b|visual.inertial odometry|homography estimation",
    "pose-estimation": r"human pose|human motion (?:prediction|generation)|gesture generation",
    "object-tracking": r"(?:visual|camera|multi.camera|multiple object) tracking",
    "video-understanding": r"human action recognition|human.object interaction|video recognition",
    "visual-retrieval": r"(?:image|video|point cloud) retrieval|place recognition|geo.localization",
    "image-quality": r"image quality assessment",
    "visual-anomaly": r"(?:industrial|surface|image) anomaly detection|deepfake detection",
    "vision-language": r"vision(?:.and)?.language|visual question answering|(?:image|video) (?:captioning|paragraph grounding)|visual reasoning|language grounding|multimodal large language models",
    "visual-efficiency": r"(?:vision transformer.{0,45}(?:quantization|efficient|size and speed)|(?:quantization|efficient).{0,55}vision transformer)",
    "visual-security": r"image watermarking|watermarks? in .*diffusion|visual adversarial|adversarial (?:attack|distillation|transferability|robustness)",
}


def _matches(text):
    for key, (_, aliases) in DIRECTIONS.items():
        patterns = [re.escape(a).replace(r"\ ", r"[\s-]+") for a in aliases]
        patterns.append(EXTRA[key])
        match = re.search(r"(?<!\w)(?:" + "|".join(patterns) + r")(?!\w)", text, re.I)
        if match:
            yield key, match


def classify_directions(paper, records):
    """Select one direction normally; extra directions require distinct title support.

    Input source records have already passed paper identity and digest validation.
    Scores are deterministic ranking weights, never probabilities.
    """
    signals = {}
    input_digest = fingerprint(asdict(paper))

    def collect(text, channel, url, digest, path):
        if not isinstance(text, str):
            return
        for key, match in _matches(text):
            signals.setdefault(key, []).append(dict(channel=channel, name=text,
                quote=match.group(), start=match.start(), end=match.end(),
                source_url=url, source_digest=digest, source_path=path))

    collect(paper.title, "title", paper.source_url, input_digest, ["title"])
    # Abstract mentions alone are insufficient. They can corroborate a source
    # task/keyword, but are not assumed to describe the paper's contribution.
    collect(paper.abstract or "", "abstract", paper.source_url, input_digest, ["abstract"])
    for record in records:
        payload = record["payload"]
        if record["source"] == "openalex":
            for i, keyword in enumerate(payload.get("keywords") or []):
                if isinstance(keyword, dict):
                    collect(keyword.get("display_name"), "keyword", record["url"], record["digest"], ["keywords", i])
            topic = payload.get("primary_topic")
            if isinstance(topic, dict):
                collect(topic.get("display_name"), "primary_topic", record["url"], record["digest"], ["primary_topic"])
        elif record["source"] == "paperswithcode":
            for i, task in enumerate(payload.get("tasks") or []):
                if isinstance(task, dict):
                    collect(task.get("name"), "task", record["url"], record["digest"], ["tasks", i])

    candidates = []
    for key, evidence in signals.items():
        channels = {s["channel"] for s in evidence}
        eligible = ("title" in channels or ("keyword" in channels and bool(channels & {"task", "primary_topic", "abstract"}))
                    or {"task", "abstract"} <= channels or {"primary_topic", "abstract"} <= channels)
        if not eligible:
            continue
        score = sum(weight for channel, weight in
                    (("title", 5), ("keyword", 2), ("task", 2), ("primary_topic", 1), ("abstract", 1))
                    if channel in channels)
        title_end = max((s["end"] for s in evidence if s["channel"] == "title"), default=0)
        candidates.append((key, score, title_end, channels, evidence))
    candidates.sort(key=lambda c: (-c[1], -c[2], c[0]))
    selected = candidates[:1]
    if selected:
        for item in candidates[1:]:
            # A second/third direction is exceptional: both it and the primary
            # need explicit title evidence, plus corroboration for the extra.
            if (len(selected) < 3 and "title" in selected[0][3] and "title" in item[3]
                    and item[1] >= selected[0][1] - 2 and len(item[3] - {"title"}) >= 1):
                selected.append(item)
    output = []
    for rank, (key, score, _, channels, evidence) in enumerate(selected):
        # Stable order independent of source-record arrival order.
        evidence.sort(key=lambda s: (s["channel"], s["source_url"], str(s["source_path"]), s["name"]))
        first = next((s for s in evidence if s["channel"] == "title"), evidence[0])
        output.append(dict(kind="research_direction", name=DIRECTIONS[key][0], source_id="cv-direction:" + key,
            parent_name="计算机视觉", basis="source_classification", classification_method="combined_rules",
            mapping_version=VERSION, selection="primary" if rank == 0 else "additional",
            source="b_rules", source_url=first["source_url"], source_digest=first["source_digest"],
            source_path=first["source_path"], mapped_from=evidence))
    if not output:
        output.append(dict(kind="research_direction", name="其他", source_id="cv-direction:other",
            parent_name="计算机视觉", basis="source_classification", classification_method="unclassified_fallback",
            mapping_version=VERSION, selection="fallback", source="b_rules", source_url=paper.source_url,
            source_digest=input_digest, source_path=[], mapped_from=[], reason="insufficient_supported_direction"))
    return output
