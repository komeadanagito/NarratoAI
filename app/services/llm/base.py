"""
大模型服务提供商基类定义

定义了统一的大模型服务接口，包括视觉模型和文本生成模型的抽象基类
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from pathlib import Path

from .exceptions import LLMServiceError, ConfigurationError


class BaseLLMProvider(ABC):
    """大模型服务提供商基类"""
    
    def __init__(self, 
                 api_key: str,
                 model_name: str,
                 base_url: Optional[str] = None,
                 **kwargs):
        """
        初始化大模型服务提供商
        
        Args:
            api_key: API密钥
            model_name: 模型名称
            base_url: API基础URL
            **kwargs: 其他配置参数
        """
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.config = kwargs
        
        # 验证必要配置
        self._validate_config()
        
        # 初始化提供商特定设置
        self._initialize()
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """供应商名称"""
        pass
    
    @property
    @abstractmethod
    def supported_models(self) -> List[str]:
        """支持的模型列表"""
        pass
    
    def _validate_config(self):
        """验证配置参数"""
        if not self.api_key:
            raise ConfigurationError("API密钥不能为空", "api_key")

        if not self.model_name:
            raise ConfigurationError("模型名称不能为空", "model_name")

        # 检查模型支持情况
        self._validate_model_support()
    
    def _validate_model_support(self):
        """验证模型支持情况（宽松模式，仅记录警告）"""
        from loguru import logger

        # OpenAI 兼容网关的模型数量较多，运行时由远端完成最终校验
        if self.model_name not in self.supported_models:
            logger.warning(
                f"模型 {self.model_name} 未在供应商 {self.provider_name} 的预定义支持列表中。"
                f"支持的模型列表: {self.supported_models}"
            )

    def _initialize(self):
        """初始化提供商特定设置，子类可重写"""
        pass
    
    @abstractmethod
    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行API调用，子类必须实现"""
        pass
    
    def _handle_api_error(self, status_code: int, response_text: str) -> LLMServiceError:
        """处理API错误，返回适当的异常"""
        from .exceptions import APICallError, RateLimitError, AuthenticationError

        if status_code == 401:
            return AuthenticationError()
        elif status_code == 429:
            return RateLimitError()
        elif status_code in [502, 503, 504]:
            return APICallError(f"服务器错误 HTTP {status_code}", status_code, response_text)
        elif status_code == 524:
            return APICallError(f"服务器处理超时 HTTP {status_code}", status_code, response_text)
        else:
            return APICallError(f"HTTP {status_code}", status_code, response_text)


class VisionModelProvider(BaseLLMProvider):
    """视觉模型提供商基类"""

    @abstractmethod
    async def analyze_video(
        self,
        video: Union[str, Path],
        prompt: str,
        system_prompt: Optional[str] = None,
        response_format: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        直接分析完整视频并返回结果。

        Args:
            video: 本地视频路径
            prompt: 视频分析提示词
            system_prompt: 可选系统提示词
            response_format: 响应格式（``json`` 或 ``None``）
            **kwargs: 其他参数

        Returns:
            模型返回的完整文本
        """
        pass


class TextModelProvider(BaseLLMProvider):
    """文本生成模型提供商基类"""
    
    @abstractmethod
    async def generate_text(self,
                          prompt: str,
                          system_prompt: Optional[str] = None,
                          temperature: float = 1.0,
                          max_tokens: Optional[int] = None,
                          response_format: Optional[str] = None,
                          **kwargs) -> str:
        """
        生成文本内容
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 生成温度
            max_tokens: 最大token数
            response_format: 响应格式 ('json' 或 None)
            **kwargs: 其他参数
            
        Returns:
            生成的文本内容
        """
        pass

    async def generate_text_stream(self,
                                 prompt: str,
                                 system_prompt: Optional[str] = None,
                                 temperature: float = 1.0,
                                 max_tokens: Optional[int] = None,
                                 response_format: Optional[str] = None,
                                 on_chunk=None,
                                 **kwargs) -> str:
        """生成文本内容并尽可能回调流式片段；默认退化为一次性输出。"""
        result = await self.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            **kwargs,
        )
        if on_chunk:
            on_chunk({"type": "content", "text": result})
        return result
    
    def _build_messages(self, prompt: str, system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        """构建消息列表"""
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        return messages
