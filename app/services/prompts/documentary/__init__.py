#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
@Project: NarratoAI
@File   : __init__.py
@Author : viccy同学
@Date   : 2025/1/7
@Description: 纪录片解说提示词模块
"""

from .video_narration import VideoNarrationPrompt
from ..manager import PromptManager


def register_prompts():
    """注册纪录片解说相关的提示词"""
    
    narration_prompt = VideoNarrationPrompt()
    PromptManager.register_prompt(narration_prompt, is_default=True)


__all__ = [
    "VideoNarrationPrompt",
    "register_prompts"
]
