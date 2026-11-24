"""Lightweight 5-target Meal Calorie visual regression models (``timm`` MobileNetV3).

Input contract for exported ONNX wrapper ``WithNormCalorieWrapper``:
  - Input ``image``: float32 NCHW ``(N, 3, 224, 224)`` RGB in ``[0.0, 255.0]``
  - Output ``pred``: float32 ``(N, 5)`` non-negative ``[kcal, mass_g, fat_g, carb_g, protein_g]``
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from tastoria_ml.calorie import PHYSICAL_UPPER_BOUNDS, TARGET_COLS

SUPPORTED_BACKBONES = ("mobilenetv3_small_100", "mobilenetv3_large_100")


class MealCalorieNet(nn.Module):
    """Lightweight CNN backbone + 5-target regression head over standardized targets."""

    def __init__(self, backbone_name: str = "mobilenetv3_small_100", pretrained: bool = True, dropout: float = 0.2) -> None:
        super().__init__()
        if backbone_name not in SUPPORTED_BACKBONES:
            raise ValueError(f"Unsupported backbone {backbone_name!r}; expected {SUPPORTED_BACKBONES}")
        import timm

        self.backbone_name = backbone_name
        self.backbone = timm.create_model(
            backbone_name,
            pretrained=pretrained,
            num_classes=len(TARGET_COLS),
            drop_rate=dropout,
        )

    def forward(self, x_norm: torch.Tensor) -> torch.Tensor:
        return self.backbone(x_norm)


class WithNormCalorieWrapper(nn.Module):
    """Bakes ImageNet uint8->normalized input scaling and target unstandardization + physical bounds clamp for ONNX export."""

    def __init__(self, net: MealCalorieNet, target_mean: np.ndarray, target_std: np.ndarray) -> None:
        super().__init__()
        self.net = net
        self.register_buffer("in_mean", torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("in_std", torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(1, 3, 1, 1) * 255.0)
        self.register_buffer("y_mean", torch.tensor(target_mean, dtype=torch.float32).view(1, -1))
        self.register_buffer("y_std", torch.tensor(target_std, dtype=torch.float32).view(1, -1))
        self.register_buffer("y_max", torch.tensor(PHYSICAL_UPPER_BOUNDS, dtype=torch.float32).view(1, -1))

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        x_norm = (image - self.in_mean) / self.in_std
        z = self.net(x_norm)
        pred = z * self.y_std + self.y_mean
        return torch.minimum(torch.clamp(pred, min=0.0), self.y_max)
