"""
统一的大模型服务接口

提供简化的API接口，方便现有代码迁移到新的架构
"""

from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from loguru import logger

from .manager import LLMServiceManager
from .exceptions import LLMServiceError

# 提供商由 LLMServiceManager 在首次使用时延迟注册。
# 这样更可靠，错误也更容易调试


class UnifiedLLMService:
    """统一的大模型服务接口"""
    
    @staticmethod
    async def analyze_video(
        video: Union[str, Path],
        prompt: str,
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        response_format: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        直接分析完整视频内容。
        
        Args:
            video: 本地视频路径
            prompt: 分析提示词
            provider: 视觉模型提供商名称，如果不指定则使用配置中的默认值
            system_prompt: 可选系统提示词
            response_format: 响应格式
            **kwargs: 其他参数
            
        Returns:
            模型返回文本
            
        Raises:
            LLMServiceError: 服务调用失败时抛出
        """
        try:
            # 获取视觉模型提供商
            vision_provider = LLMServiceManager.get_vision_provider(provider)
            
            result = await vision_provider.analyze_video(
                video=video,
                prompt=prompt,
                system_prompt=system_prompt,
                response_format=response_format,
                **kwargs,
            )

            logger.info("视频分析完成")
            return result
            
        except Exception as e:
            logger.error(f"视频分析失败: {str(e)}")
            raise LLMServiceError(f"视频分析失败: {str(e)}")
    
    @staticmethod
    async def generate_text(prompt: str,
                          system_prompt: Optional[str] = None,
                          provider: Optional[str] = None,
                          temperature: float = 1.0,
                          max_tokens: Optional[int] = None,
                          response_format: Optional[str] = None,
                          **kwargs) -> str:
        """
        生成文本内容
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            provider: 文本模型提供商名称，如果不指定则使用配置中的默认值
            temperature: 生成温度
            max_tokens: 最大token数
            response_format: 响应格式 ('json' 或 None)
            **kwargs: 其他参数
            
        Returns:
            生成的文本内容
            
        Raises:
            LLMServiceError: 服务调用失败时抛出
        """
        try:
            # 获取文本模型提供商
            text_provider = LLMServiceManager.get_text_provider(provider)
            
            # 执行文本生成
            result = await text_provider.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                **kwargs
            )
            
            logger.info(f"文本生成完成，生成内容长度: {len(result)} 字符")
            return result
            
        except Exception as e:
            logger.error(f"文本生成失败: {str(e)}")
            raise LLMServiceError(f"文本生成失败: {str(e)}")

    @staticmethod
    async def generate_text_stream(prompt: str,
                                 system_prompt: Optional[str] = None,
                                 provider: Optional[str] = None,
                                 temperature: float = 1.0,
                                 max_tokens: Optional[int] = None,
                                 response_format: Optional[str] = None,
                                 on_chunk=None,
                                 **kwargs) -> str:
        """
        流式生成文本内容；不支持流式的 provider 会退化为一次性返回。
        """
        try:
            text_provider = LLMServiceManager.get_text_provider(provider)
            result = await text_provider.generate_text_stream(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                on_chunk=on_chunk,
                **kwargs
            )

            logger.info(f"流式文本生成完成，生成内容长度: {len(result)} 字符")
            return result

        except Exception as e:
            logger.error(f"流式文本生成失败: {str(e)}")
            raise LLMServiceError(f"流式文本生成失败: {str(e)}")
    
    @staticmethod
    def get_provider_info() -> Dict[str, Any]:
        """
        获取所有提供商信息
        
        Returns:
            提供商信息字典
        """
        return LLMServiceManager.get_provider_info()
    
    @staticmethod
    def list_vision_providers() -> List[str]:
        """
        列出所有视觉模型提供商
        
        Returns:
            提供商名称列表
        """
        return LLMServiceManager.list_vision_providers()
    
    @staticmethod
    def list_text_providers() -> List[str]:
        """
        列出所有文本模型提供商
        
        Returns:
            提供商名称列表
        """
        return LLMServiceManager.list_text_providers()
    
    @staticmethod
    def clear_cache():
        """清空提供商实例缓存"""
        LLMServiceManager.clear_cache()
        logger.info("已清空大模型服务缓存")


async def analyze_video_unified(
    video: Union[str, Path],
    prompt: str,
    provider: Optional[str] = None,
    **kwargs,
) -> str:
    """便捷的视频分析函数。"""
    return await UnifiedLLMService.analyze_video(
        video=video,
        prompt=prompt,
        provider=provider,
        **kwargs,
    )


async def generate_text_unified(prompt: str,
                              system_prompt: Optional[str] = None,
                              provider: Optional[str] = None,
                              temperature: float = 1.0,
                              response_format: Optional[str] = None) -> str:
    """便捷的文本生成函数"""
    return await UnifiedLLMService.generate_text(
        prompt, system_prompt, provider, temperature, response_format=response_format
    )
