"""Prompt for generating a narration script directly from a complete video."""

from ..base import ModelType, OutputFormat, PromptMetadata, VisionPrompt


class VideoNarrationPrompt(VisionPrompt):
    """Ask a multimodal video model for the final structured narration."""

    def __init__(self) -> None:
        metadata = PromptMetadata(
            name="video_narration",
            category="documentary",
            version="v1.0",
            description="直接理解完整视频并生成带时间轴的最终解说脚本",
            model_type=ModelType.MULTIMODAL,
            output_format=OutputFormat.JSON,
            tags=["视频理解", "解说文案", "时间轴", "结构化输出"],
            parameters=["language", "video_theme", "custom_instructions"],
        )
        super().__init__(metadata)
        self._system_prompt = (
            "你是一名资深短视频解说导演。你必须直接理解用户提供的完整视频，"
            "只返回最终可执行的 JSON，不展示思考过程、草稿、修改记录或解释。"
        )

    def get_template(self) -> str:
        return """请直接分析所附完整视频的画面、时序、字幕及可理解的声音信息，一次生成最终解说脚本。

创作设置：
- 解说语言：${language}
- 视频主题：${video_theme}
- 补充要求：${custom_instructions}

创作要求：
1. 开头 3 秒内给出准确、有吸引力的钩子，但不得虚构视频中不存在的人物、关系、事件或结果。
2. 按真实视频时间轴切分片段；时间戳必须来自完整视频，升序排列、互不重叠，结束时间晚于开始时间。
3. `picture` 客观描述该时间段的真实画面，`narration` 是可直接交给 TTS 的最终口播。
4. 解说以短句为主，口语自然、情节连贯，并与对应画面严格同步；避免重复和空泛套话。
5. 单个 `narration` 保持精炼且不得超过 3000 字符，不能包含草稿、反思、自我纠错、JSON 注释或提示词复述。
6. 合理覆盖视频主要情节；原声对白或关键现场声音更重要的片段可以不安排解说，不要用解说遮盖所有声音。
7. `_id` 从 1 连续递增。时间戳格式必须严格为 `HH:MM:SS,mmm-HH:MM:SS,mmm`。

只返回以下 JSON 对象，不要使用 Markdown 代码块，也不要添加 JSON 之外的任何字符：
{
  "items": [
    {
      "_id": 1,
      "timestamp": "00:00:00,000-00:00:03,000",
      "picture": "该时间段的客观画面描述",
      "narration": "可直接合成语音的最终解说"
    }
  ]
}"""


__all__ = ["VideoNarrationPrompt"]
