#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import aiohttp
from typing import Dict, Any, Optional

from loguru import logger

from src.plugin_base import PluginBase


class NaoImageSearchPlugin(PluginBase):
    description = "使用 SauceNAO 搜索图片来源，支持识别二次元图片、动漫截图等"

    def __init__(self, context):
        super().__init__(context)
        self.api_key = self.config.get("api_key")
        self.trigger_tag = self.config.get("trigger_tag", "#nao") # 默认触发标签
        self.session = None
        self.saucenao_api_url = "https://saucenao.com/search.php"

    async def initialize(self) -> bool:
        """初始化插件"""
        if not self.api_key:
            logger.warning("NaoImageSearchPlugin: 未设置 SauceNAO API 密钥，将使用免费额度")

        self.session = aiohttp.ClientSession()
        self._register_resource(self.session, "close")

        self._log_plugin_action("初始化完成", f"SauceNAO 账户 API 密钥: {'已设置' if self.api_key else '未设置'}")
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        await super().cleanup()

    async def on_mention(self, mention_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 @mention 事件"""
        return await self._handle_image_search_event(mention_data, action_desc="处理 Nao 图片识别请求")

    async def on_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理聊天消息事件"""
        return await self._handle_image_search_event(message_data, action_desc="处理 Nao 图片识别消息")

    async def _handle_image_search_event(self, data: Dict[str, Any], action_desc: str) -> Optional[Dict[str, Any]]:
        """统一处理图片识别事件"""
        try:
            images = self._extract_images_from_note(data)
            if not images:
                return None
            if not self._has_trigger_tag(data):
                return None
            image_url = images[0]
            username = self._extract_username(data)
            self._log_plugin_action(action_desc, f"来自 @{username}")
            search_result = await self._search_image_by_url(image_url)
            return self._create_response(search_result or "没有找到相似的图片哦～")
        except Exception as e:
            logger.error(f"NaoPlugin 处理图片事件出错: {e}")
            return None

    def _extract_images_from_note(self, note_data: Dict[str, Any]) -> list:
        """从 note 数据中提取图片 URL"""
        images = []
        
        # 尝试多种可能的数据结构
        note = note_data.get("note", note_data)
        
        # 检查 Misskey files 字段（图片附件信息通常在这里）
        files = note.get("files", [])
        for file_info in files:
            if isinstance(file_info, dict):
                # 检查是否是图片类型
                file_type = file_info.get("type", "")
                if file_type.startswith("image/"):
                    # 获取图片 URL
                    url = file_info.get("url") or file_info.get("thumbnailUrl")
                    if url:
                        images.append(url)
        
        return images

    def _has_trigger_tag(self, note_data: Dict[str, Any]) -> bool:
        """检查文本是否包含触发标签"""
        note = note_data.get("note", note_data)
        text = note.get("text", "") or ""
        return self.trigger_tag in text

    async def _search_image_by_url(self, image_url: str) -> Optional[str]:
        """通过图片 URL 在 SauceNAO 中搜索"""
        try:
            # SauceNAO API 参数
            params = {
                "output_type": "2",  # JSON 输出
                "api_key": self.api_key,
                "url": image_url,
                "numres": "3",  # 返回前3个结果
                "db": "999",  # 搜索所有数据库
            }
            
            # 如果没有 API key，移除该参数
            if not self.api_key:
                params.pop("api_key")
            
            async with self.session.get(self.saucenao_api_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_saucenao_response(data)
                else:
                    logger.error(f"SauceNAO API 请求失败: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"SauceNAO 图片搜索失败: {e}")
            return None

    def _parse_saucenao_response(self, data: Dict[str, Any]) -> Optional[str]:
        """解析 SauceNAO API 响应"""
        try:
            results = data.get("results", [])
            if not results:
                return None
            
            # 获取第一个结果
            first_result = results[0]
            header = first_result.get("header", {})
            result_data = first_result.get("data", {})
            
            # 提取信息
            similarity = header.get("similarity", "0")
            
            # 尝试获取标题
            title = (result_data.get("title") or 
                    result_data.get("jp_name") or 
                    result_data.get("eng_name") or 
                    result_data.get("source") or 
                    "未知")
            
            # 尝试获取作者
            author = (result_data.get("author") or 
                     result_data.get("member_name") or 
                     result_data.get("creator") or 
                     "未知")
            
            # 尝试获取来源链接
            source_url = (result_data.get("ext_urls", [{}])[0] if result_data.get("ext_urls") else None) or ""
            
            # 格式化结果
            result_text = f"🔍 相似度: {similarity}%\n\n"
            result_text += f"📝 标题: {title}\n"
            result_text += f"👤 作者: {author}\n"
            
            if source_url:
                result_text += f"🔗 来源: {source_url}\n"
            
            # 添加数据库信息
            index_name = header.get("index_name", "")
            if index_name:
                result_text += f"📚 数据库: {index_name}"
            
            return result_text
            
        except Exception as e:
            logger.error(f"解析 SauceNAO 响应失败: {e}")
            return None

    def _create_response(self, response_text: str, content_key: str = "response") -> Dict[str, Any]:
        """创建插件响应"""
        try:
            response = {
                "handled": True,
                "plugin_name": self.name,
                content_key: response_text,
            }
            return response if self._validate_plugin_response(response) else {}
        except Exception as e:
            logger.error(f"创建响应时出错: {e}")
            return {}