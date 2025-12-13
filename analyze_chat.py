#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信群聊用户画像分析系统
基于聊天记录JSON文件，通过分层分析生成用户画像报告
"""

import json
import os
import re
import time
import hashlib
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# ============================================================
# 常量配置（请填入你的配置）
# ============================================================

OPENAI_API = ""  # API地址，OpenAI 兼容 API，例如: "https://api.openai.com/v1/chat/completions" 或者 “https://api.openai.com/”
API_KEY = ""  # API密钥
MODEL_NAME = ""  # 模型名称，例如: "gpt-4" 或 "gpt-3.5-turbo"
CONTENT_DIR = ""     # 内容路径（单个JSON文件或包含多个JSON的目录）

# ============================================================
# 性能调优配置
# ============================================================

API_TIMEOUT = 180              # API请求超时时间（秒），默认180秒
SLICE_MAX_MESSAGES = 500       # 切片最大消息数（超过则按天细分）
SLICE_MIN_MESSAGES = 30        # 切片最小消息数（少于则合并）
PROMPT_MAX_MESSAGES = 200      # 发送给API的最大消息数
VERBOSE_LOG = True             # 是否打印详细日志

# ============================================================
# 多线程与缓存配置
# ============================================================

MAX_WORKERS = 10                # 并发线程数
CACHE_DIR = "temp"             # 缓存目录
ENABLE_CACHE = True            # 是否启用缓存

# ============================================================
# 用户过滤配置
# ============================================================

MIN_MESSAGE_COUNT = 1000       # 只分析消息数 >= 此值的用户，设为0则分析所有用户

# ============================================================
# 时间过滤与抽样配置
# ============================================================

# 时间过滤：只分析指定时间范围内的消息
TIME_FILTER_START = 1735689600  # 开始时间戳，2025-01-01 00:00:00，设为0则不限制
TIME_FILTER_END = 0             # 结束时间戳，设为0则不限制

# 抽样配置：限制每个用户的最大切片数
MAX_SLICES_PER_USER = 30        # 每用户最大切片数，超过时均匀抽样，设为0则不限制

# 线程锁（用于线程安全的输出和缓存写入）
print_lock = threading.Lock()
cache_lock = threading.Lock()

# ============================================================
# 缓存模块
# ============================================================

def get_safe_filename(name: str) -> str:
    """将名称转换为安全的文件名"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def get_slice_hash(slice_data: Dict) -> str:
    """
    计算切片的哈希值，用于缓存标识
    
    Args:
        slice_data: 切片数据
        
    Returns:
        哈希值字符串（前8位）
    """
    # 使用时间范围和消息数量生成哈希
    content = f"{slice_data['time_start']}_{slice_data['time_end']}_{slice_data['message_count']}"
    # 如果有消息，加入第一条和最后一条消息的内容
    if slice_data['messages']:
        first_msg = slice_data['messages'][0].get('content', '')[:50]
        last_msg = slice_data['messages'][-1].get('content', '')[:50]
        content += f"_{first_msg}_{last_msg}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()[:8]


def get_cache_dir(group_name: str, username: str) -> str:
    """
    获取缓存目录路径
    
    Args:
        group_name: 群名称
        username: 用户名
        
    Returns:
        缓存目录路径
    """
    safe_group = get_safe_filename(group_name)
    safe_user = get_safe_filename(username)
    return os.path.join(CACHE_DIR, safe_group, safe_user)


def get_cache_path(group_name: str, username: str, slice_index: int, slice_hash: str) -> str:
    """
    获取切片缓存文件路径
    
    Args:
        group_name: 群名称
        username: 用户名
        slice_index: 切片索引
        slice_hash: 切片哈希
        
    Returns:
        缓存文件路径
    """
    cache_dir = get_cache_dir(group_name, username)
    return os.path.join(cache_dir, f"slice_{slice_index:03d}_{slice_hash}.json")


def get_final_analysis_cache_path(group_name: str, username: str) -> str:
    """
    获取最终分析缓存文件路径
    
    Args:
        group_name: 群名称
        username: 用户名
        
    Returns:
        缓存文件路径
    """
    cache_dir = get_cache_dir(group_name, username)
    return os.path.join(cache_dir, "final_analysis.json")


def load_cache(cache_path: str) -> Optional[Dict]:
    """
    加载缓存文件
    
    Args:
        cache_path: 缓存文件路径
        
    Returns:
        缓存数据，如果不存在或加载失败则返回None
    """
    if not ENABLE_CACHE:
        return None
    
    try:
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        if VERBOSE_LOG:
            with print_lock:
                print(f"        [缓存] 加载失败: {e}")
    return None


def save_cache(cache_path: str, data: Dict) -> bool:
    """
    保存缓存文件
    
    Args:
        cache_path: 缓存文件路径
        data: 要缓存的数据
        
    Returns:
        是否保存成功
    """
    if not ENABLE_CACHE:
        return False
    
    try:
        with cache_lock:
            # 确保目录存在
            cache_dir = os.path.dirname(cache_path)
            os.makedirs(cache_dir, exist_ok=True)
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        if VERBOSE_LOG:
            with print_lock:
                print(f"        [缓存] 保存失败: {e}")
        return False


def thread_safe_print(message: str):
    """线程安全的打印函数"""
    with print_lock:
        print(message)


# ============================================================
# 数据预处理模块
# ============================================================

def load_json_file(file_path: str) -> Tuple[Optional[Dict], Optional[str]]:
    """
    加载并验证JSON文件
    
    Args:
        file_path: JSON文件路径
        
    Returns:
        (data, error): 成功返回(数据, None)，失败返回(None, 错误信息)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 验证必要的结构
        if 'session' not in data:
            return None, f"JSON结构错误: 缺少'session'字段"
        if 'messages' not in data:
            return None, f"JSON结构错误: 缺少'messages'字段"
        if not isinstance(data['messages'], list):
            return None, f"JSON结构错误: 'messages'应为数组"
        
        # 验证session字段
        required_session_fields = ['wxid', 'nickname', 'type']
        for field in required_session_fields:
            if field not in data['session']:
                return None, f"JSON结构错误: session缺少'{field}'字段"
        
        return data, None
        
    except json.JSONDecodeError as e:
        return None, f"JSON解析错误: {str(e)}"
    except FileNotFoundError:
        return None, f"文件不存在: {file_path}"
    except Exception as e:
        return None, f"读取文件错误: {str(e)}"


def extract_messages(data: Dict) -> Tuple[List[Dict], Dict]:
    """
    提取并过滤消息，保留必要字段，支持时间过滤
    
    Args:
        data: 原始JSON数据
        
    Returns:
        (过滤后的消息列表, 统计信息)
    """
    messages = data.get('messages', [])
    extracted = []
    
    stats = {
        'total': len(messages),
        'system': 0,
        'time_filtered': 0,
        'valid': 0
    }
    
    for msg in messages:
        # 过滤系统消息
        if msg.get('type') == '系统消息':
            stats['system'] += 1
            continue
        
        # 时间过滤
        create_time = msg.get('createTime', 0)
        if TIME_FILTER_START > 0 and create_time < TIME_FILTER_START:
            stats['time_filtered'] += 1
            continue
        if TIME_FILTER_END > 0 and create_time > TIME_FILTER_END:
            stats['time_filtered'] += 1
            continue
        
        # 提取必要字段
        extracted_msg = {
            'senderUsername': msg.get('senderUsername', ''),
            'senderDisplayName': msg.get('senderDisplayName', ''),
            'createTime': create_time,
            'formattedTime': msg.get('formattedTime', ''),
            'type': msg.get('type', ''),
            'content': msg.get('content', ''),
            'isSend': msg.get('isSend', 0),
            'localType': msg.get('localType', 0)
        }
        
        # 清理文本内容中的用户名前缀（如 "username:\n内容"）
        if extracted_msg['type'] == '文本消息' and extracted_msg['content']:
            content = extracted_msg['content']
            # 匹配 "username:\n" 或 "username:" 开头的模式
            pattern = r'^[a-zA-Z0-9_]+:\n?'
            extracted_msg['content'] = re.sub(pattern, '', content).strip()
        
        extracted.append(extracted_msg)
        stats['valid'] += 1
    
    return extracted, stats


def group_by_user(messages: List[Dict]) -> Dict[str, List[Dict]]:
    """
    按用户分组消息
    
    Args:
        messages: 消息列表
        
    Returns:
        按用户名分组的消息字典
    """
    user_messages = defaultdict(list)
    
    for msg in messages:
        username = msg.get('senderUsername', '')
        if username:
            user_messages[username].append(msg)
    
    return dict(user_messages)


def get_user_display_names(messages: List[Dict]) -> Dict[str, str]:
    """
    获取用户名到显示名的映射
    
    Args:
        messages: 消息列表
        
    Returns:
        用户名 -> 显示名 的映射字典
    """
    display_names = {}
    for msg in messages:
        username = msg.get('senderUsername', '')
        display_name = msg.get('senderDisplayName', '')
        if username and display_name:
            display_names[username] = display_name
    return display_names


# ============================================================
# 切片策略模块
# ============================================================

def get_week_key(timestamp: int) -> str:
    """获取时间戳对应的周标识（年-周号）"""
    dt = datetime.fromtimestamp(timestamp)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def get_day_key(timestamp: int) -> str:
    """获取时间戳对应的日期标识"""
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime('%Y-%m-%d')


def slice_messages_by_time(messages: List[Dict]) -> List[Dict]:
    """
    按时间窗口对消息进行切片（混合策略）
    - 基础切片：按周
    - 超过1000条：按天细分
    - 少于50条：合并相邻周
    
    Args:
        messages: 消息列表（已按时间排序）
        
    Returns:
        切片列表，每个切片包含时间范围和消息列表
    """
    if not messages:
        return []
    
    # 第一步：按周分组
    weekly_groups = defaultdict(list)
    for msg in messages:
        week_key = get_week_key(msg['createTime'])
        weekly_groups[week_key].append(msg)
    
    # 按周排序
    sorted_weeks = sorted(weekly_groups.keys())
    
    # 第二步：根据消息量调整
    slices = []
    pending_merge = []  # 待合并的小切片
    
    for week_key in sorted_weeks:
        week_msgs = weekly_groups[week_key]
        
        if len(week_msgs) > SLICE_MAX_MESSAGES:
            # 消息过多，按天细分
            if pending_merge:
                # 先处理待合并的切片
                slices.append(create_slice_from_messages(
                    [m for msgs in pending_merge for m in msgs]
                ))
                pending_merge = []
            
            daily_groups = defaultdict(list)
            for msg in week_msgs:
                day_key = get_day_key(msg['createTime'])
                daily_groups[day_key].append(msg)
            
            for day_key in sorted(daily_groups.keys()):
                slices.append(create_slice_from_messages(daily_groups[day_key]))
        
        elif len(week_msgs) < SLICE_MIN_MESSAGES:
            # 消息过少，加入待合并队列
            pending_merge.append(week_msgs)
            
            # 累积超过最小阈值时合并
            total_pending = sum(len(msgs) for msgs in pending_merge)
            if total_pending >= SLICE_MIN_MESSAGES:
                slices.append(create_slice_from_messages(
                    [m for msgs in pending_merge for m in msgs]
                ))
                pending_merge = []
        else:
            # 正常范围，先处理待合并的
            if pending_merge:
                # 将待合并的与当前合并
                pending_merge.append(week_msgs)
                slices.append(create_slice_from_messages(
                    [m for msgs in pending_merge for m in msgs]
                ))
                pending_merge = []
            else:
                slices.append(create_slice_from_messages(week_msgs))
    
    # 处理剩余的待合并切片
    if pending_merge:
        slices.append(create_slice_from_messages(
            [m for msgs in pending_merge for m in msgs]
        ))
    
    return slices


def create_slice_from_messages(messages: List[Dict]) -> Dict:
    """从消息列表创建切片对象"""
    if not messages:
        return {
            'time_start': '',
            'time_end': '',
            'message_count': 0,
            'messages': []
        }
    
    # 按时间排序
    sorted_msgs = sorted(messages, key=lambda x: x['createTime'])
    
    return {
        'time_start': sorted_msgs[0]['formattedTime'],
        'time_end': sorted_msgs[-1]['formattedTime'],
        'message_count': len(sorted_msgs),
        'messages': sorted_msgs
    }


def sample_slices(slices: List[Dict], max_slices: int) -> Tuple[List[Dict], bool]:
    """
    对切片进行均匀抽样，确保时间跨度覆盖
    
    Args:
        slices: 原始切片列表
        max_slices: 最大切片数
        
    Returns:
        (抽样后的切片列表, 是否进行了抽样)
    """
    if max_slices <= 0 or len(slices) <= max_slices:
        return slices, False
    
    # 均匀抽样，确保首尾被包含
    n = len(slices)
    
    # 计算抽样间隔
    # 需要选择 max_slices 个切片，首尾固定，中间均匀分布
    if max_slices == 1:
        # 只取最后一个（最新的）
        return [slices[-1]], True
    elif max_slices == 2:
        # 取首尾
        return [slices[0], slices[-1]], True
    
    # 首尾固定，中间均匀选择 max_slices - 2 个
    middle_count = max_slices - 2
    step = (n - 2) / (middle_count + 1)
    
    sampled = [slices[0]]  # 首
    for i in range(1, middle_count + 1):
        idx = int(i * step)
        if idx < n - 1:  # 确保不重复选择最后一个
            sampled.append(slices[idx])
    sampled.append(slices[-1])  # 尾
    
    return sampled, True


# ============================================================
# 第一层分析：本地量化统计
# ============================================================

def calculate_basic_stats(messages: List[Dict], username: str) -> Dict:
    """
    计算用户的基础统计数据
    
    Args:
        messages: 该用户的消息列表
        username: 用户名
        
    Returns:
        基础统计数据字典
    """
    if not messages:
        return {
            'message_count': 0,
            'avg_length': 0,
            'active_hours': {},
            'message_types': {},
            'most_active_date': '',
            'interaction_count': {'mentions': 0, 'quotes': 0}
        }
    
    # 发言数量
    message_count = len(messages)
    
    # 平均消息长度（仅文本消息）
    text_messages = [m for m in messages if m['type'] == '文本消息']
    if text_messages:
        total_length = sum(len(m['content']) for m in text_messages)
        avg_length = round(total_length / len(text_messages), 1)
    else:
        avg_length = 0
    
    # 活跃时段分布（按小时统计）
    active_hours = defaultdict(int)
    for msg in messages:
        if msg['formattedTime']:
            try:
                hour = int(msg['formattedTime'].split(' ')[1].split(':')[0])
                active_hours[hour] += 1
            except (IndexError, ValueError):
                pass
    
    # 消息类型分布
    message_types = defaultdict(int)
    for msg in messages:
        msg_type = msg.get('type', '其他')
        message_types[msg_type] += 1
    
    # 最活跃日期
    daily_count = defaultdict(int)
    for msg in messages:
        if msg['formattedTime']:
            date = msg['formattedTime'].split(' ')[0]
            daily_count[date] += 1
    
    most_active_date = max(daily_count.keys(), key=lambda x: daily_count[x]) if daily_count else ''
    
    # 互动统计（@提及和引用）
    mentions = 0
    quotes = 0
    for msg in messages:
        content = msg.get('content', '')
        # 统计@提及
        mentions += len(re.findall(r'@\w+', content))
        # 统计引用消息
        if msg.get('type') == '引用消息':
            quotes += 1
    
    return {
        'message_count': message_count,
        'avg_length': avg_length,
        'active_hours': dict(active_hours),
        'message_types': dict(message_types),
        'most_active_date': most_active_date,
        'most_active_count': daily_count.get(most_active_date, 0),
        'interaction_count': {
            'mentions': mentions,
            'quotes': quotes
        }
    }


def format_active_hours(active_hours: Dict[int, int]) -> str:
    """格式化活跃时段为可读字符串"""
    if not active_hours:
        return "无数据"
    
    # 找出最活跃的时段
    sorted_hours = sorted(active_hours.items(), key=lambda x: x[1], reverse=True)
    top_hours = sorted_hours[:3]
    
    result = []
    for hour, count in top_hours:
        result.append(f"{hour}:00-{hour+1}:00 ({count}条)")
    
    return ", ".join(result)


# ============================================================
# API调用模块
# ============================================================

def build_summary_prompt(slice_data: Dict, user_info: Dict) -> Tuple[str, str]:
    """
    构建切片摘要的提示词（第一阶段：摘要）
    
    Args:
        slice_data: 切片数据
        user_info: 用户信息
        
    Returns:
        (system_prompt, user_message)
    """
    system_prompt = """你是一位专业的社交行为分析师。请对这段微信群聊记录进行摘要总结，提取关键特征。

请以JSON格式返回摘要结果：
{
  "time_range": "时间范围",
  "message_count": 消息数量,
  "emotion_summary": {
    "overall_tone": "整体情绪基调（积极/消极/中性/混合）",
    "emotion_keywords": ["情绪关键词1", "情绪关键词2"]
  },
  "topics": ["讨论的主要话题1", "话题2", "话题3"],
  "keywords": ["高频关键词1", "关键词2", "关键词3"],
  "style_notes": "沟通风格要点（简短描述）",
  "notable_behaviors": ["值得注意的行为1", "行为2"],
  "brief_summary": "50字以内的摘要"
}

要求：
- 提取最关键的信息，不要冗余
- 关键词和话题不超过5个
- 只返回JSON，不要添加其他内容"""

    # 构建用户消息
    messages_text = []
    for msg in slice_data['messages'][:PROMPT_MAX_MESSAGES]:
        time_str = msg.get('formattedTime', '')
        content = msg.get('content', '')
        msg_type = msg.get('type', '')
        
        if msg_type == '文本消息':
            messages_text.append(f"[{time_str}] {content}")
        else:
            messages_text.append(f"[{time_str}] [{msg_type}]")
    
    user_message = f"""请为以下用户的聊天记录生成摘要：

用户: {user_info['display_name']} ({user_info['username']})
时间范围: {slice_data['time_start']} 至 {slice_data['time_end']}
消息数: {slice_data['message_count']}

聊天记录:
{chr(10).join(messages_text)}

请返回JSON格式的摘要。"""

    return system_prompt, user_message


def build_final_analysis_prompt(user_info: Dict, summaries: List[Dict], basic_stats: Dict) -> Tuple[str, str]:
    """
    构建最终分析的提示词（第二阶段：综合分析）
    
    Args:
        user_info: 用户信息
        summaries: 所有切片的摘要列表
        basic_stats: 基础统计数据
        
    Returns:
        (system_prompt, user_message)
    """
    system_prompt = """你是一位专业的社交行为分析师。请基于用户在不同时间段的聊天摘要，生成综合用户画像。

请以JSON格式返回分析结果：
{
  "emotion_analysis": {
    "positive_ratio": 数字(0-100),
    "negative_ratio": 数字(0-100),
    "volatility": "低/中/高",
    "dominant_tone": "主要语气特征描述"
  },
  "communication_style": {
    "style_tags": ["标签1", "标签2", "标签3"],
    "language_pattern": "语言风格描述",
    "emoji_usage": "表情使用偏好描述"
  },
  "topic_interests": {
    "main_topics": ["话题1", "话题2", "话题3"],
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "interest_description": "兴趣描述"
  },
  "role_analysis": {
    "group_role": "群内角色（如：活跃分子/信息提供者/倾听者/氛围担当等）",
    "initiative_level": "主动/被动/均衡",
    "social_behavior": "社交行为描述"
  },
  "professional_inference": {
    "possible_fields": ["可能领域1", "可能领域2"],
    "expertise_indicators": "专业能力指标描述",
    "confidence": "低/中/高"
  },
  "summary": "100字以内的综合评价",
  "tags": ["用户标签1", "标签2", "标签3", "标签4", "标签5"]
}

要求：
- 综合所有摘要信息，形成全面画像
- 标签不超过5个，要精准概括用户特征
- 若信息不足，标注"信息不足"
- 只返回JSON，不要添加其他内容"""

    # 构建摘要文本
    summaries_text = []
    for i, summary in enumerate(summaries):
        if summary.get('data'):
            data = summary['data']
            summaries_text.append(f"""
--- 时间段 {i+1}: {summary.get('time_range', 'N/A')} ---
情绪基调: {data.get('emotion_summary', {}).get('overall_tone', 'N/A')}
话题: {', '.join(data.get('topics', []))}
关键词: {', '.join(data.get('keywords', []))}
风格: {data.get('style_notes', 'N/A')}
摘要: {data.get('brief_summary', 'N/A')}""")
    
    user_message = f"""请为以下用户生成综合画像：

用户: {user_info['display_name']} ({user_info['username']})

基础统计:
- 总发言数: {basic_stats.get('message_count', 0)} 条
- 平均消息长度: {basic_stats.get('avg_length', 0)} 字
- 活跃时段: {format_active_hours(basic_stats.get('active_hours', {}))}
- @他人次数: {basic_stats.get('interaction_count', {}).get('mentions', 0)} 次
- 引用消息次数: {basic_stats.get('interaction_count', {}).get('quotes', 0)} 次

各时间段摘要（共{len(summaries)}个时间段）:
{''.join(summaries_text) if summaries_text else '无有效摘要数据'}

请返回JSON格式的综合分析。"""

    return system_prompt, user_message


def get_api_url() -> str:
    """
    获取完整的API URL，自动补全路径
    """
    api_url = OPENAI_API.rstrip('/')
    if not api_url.endswith('/chat/completions'):
        if not api_url.endswith('/v1'):
            api_url += '/v1'
        api_url += '/chat/completions'
    return api_url


def call_api(system_prompt: str, user_message: str, max_retries: int = 3, log_prefix: str = "") -> Tuple[Optional[Dict], Optional[str]]:
    """
    通用API调用函数
    
    Args:
        system_prompt: 系统提示词
        user_message: 用户消息
        max_retries: 最大重试次数
        log_prefix: 日志前缀（用于区分不同调用）
        
    Returns:
        (result, error): 成功返回(分析结果, None)，失败返回(None, 错误信息)
    """
    if not OPENAI_API or not API_KEY or not MODEL_NAME:
        return None, "API配置不完整，请填写OPENAI_API、API_KEY和MODEL_NAME"
    
    # 获取完整的API URL
    api_url = get_api_url()
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.3,
        "max_tokens": 2000
    }
    
    # 估算请求大小
    prompt_size = len(system_prompt) + len(user_message)
    if VERBOSE_LOG:
        thread_safe_print(f"{log_prefix}[API] 请求大小: ~{prompt_size} 字符, 超时: {API_TIMEOUT}秒")
    
    for attempt in range(max_retries):
        try:
            if VERBOSE_LOG and attempt > 0:
                thread_safe_print(f"{log_prefix}[API] 第 {attempt + 1} 次重试...")
            
            start_time = time.time()
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=API_TIMEOUT
            )
            elapsed = time.time() - start_time
            
            if VERBOSE_LOG:
                thread_safe_print(f"{log_prefix}[API] 响应时间: {elapsed:.1f}秒, 状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                
                # 显示token使用情况
                if VERBOSE_LOG and 'usage' in result:
                    usage = result['usage']
                    thread_safe_print(f"{log_prefix}[API] Token: 输入={usage.get('prompt_tokens', 'N/A')}, 输出={usage.get('completion_tokens', 'N/A')}")
                
                # 尝试解析JSON
                content = content.strip()
                if content.startswith('```json'):
                    content = content[7:]
                if content.startswith('```'):
                    content = content[3:]
                if content.endswith('```'):
                    content = content[:-3]
                content = content.strip()
                
                try:
                    parsed = json.loads(content)
                    return parsed, None
                except json.JSONDecodeError as e:
                    if VERBOSE_LOG:
                        thread_safe_print(f"{log_prefix}[API] JSON解析失败，原始响应前200字符: {content[:200]}...")
                    return None, f"API返回的JSON解析失败: {str(e)}"
            else:
                error_msg = f"API请求失败 (状态码: {response.status_code}): {response.text[:200]}"
                if VERBOSE_LOG:
                    thread_safe_print(f"{log_prefix}[API] 请求失败: {error_msg}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    if VERBOSE_LOG:
                        thread_safe_print(f"{log_prefix}[API] 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                return None, error_msg
                
        except requests.exceptions.Timeout:
            if VERBOSE_LOG:
                thread_safe_print(f"{log_prefix}[API] 请求超时 ({API_TIMEOUT}秒)")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                if VERBOSE_LOG:
                    thread_safe_print(f"{log_prefix}[API] 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                continue
            return None, f"API请求超时 ({API_TIMEOUT}秒)"
        except requests.exceptions.RequestException as e:
            if VERBOSE_LOG:
                thread_safe_print(f"{log_prefix}[API] 请求异常: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                if VERBOSE_LOG:
                    thread_safe_print(f"{log_prefix}[API] 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                continue
            return None, f"API请求异常: {str(e)}"
    
    return None, "API调用失败，已达到最大重试次数"


def call_summary_api(slice_data: Dict, user_info: Dict, log_prefix: str = "") -> Tuple[Optional[Dict], Optional[str]]:
    """
    调用API生成切片摘要（第一阶段）
    
    Args:
        slice_data: 切片数据
        user_info: 用户信息
        log_prefix: 日志前缀
        
    Returns:
        (result, error)
    """
    system_prompt, user_message = build_summary_prompt(slice_data, user_info)
    return call_api(system_prompt, user_message, max_retries=3, log_prefix=log_prefix)


def call_final_analysis_api(user_info: Dict, summaries: List[Dict], basic_stats: Dict, log_prefix: str = "") -> Tuple[Optional[Dict], Optional[str]]:
    """
    调用API生成最终综合分析（第二阶段）
    
    Args:
        user_info: 用户信息
        summaries: 所有切片的摘要列表
        basic_stats: 基础统计数据
        log_prefix: 日志前缀
        
    Returns:
        (result, error)
    """
    system_prompt, user_message = build_final_analysis_prompt(user_info, summaries, basic_stats)
    return call_api(system_prompt, user_message, max_retries=3, log_prefix=log_prefix)


# ============================================================
# 第二层分析：语义分析（多线程+缓存）
# ============================================================

def process_single_slice(args: Tuple) -> Dict:
    """
    处理单个切片（用于多线程调用）
    
    Args:
        args: (slice_index, slice_data, user_info, group_name) 元组
        
    Returns:
        切片处理结果
    """
    slice_index, slice_data, user_info, group_name = args
    
    username = user_info['username']
    slice_hash = get_slice_hash(slice_data)
    time_range = f"{slice_data['time_start']} - {slice_data['time_end']}"
    log_prefix = f"        [切片{slice_index+1}] "
    
    # 检查缓存
    cache_path = get_cache_path(group_name, username, slice_index, slice_hash)
    cached = load_cache(cache_path)
    
    if cached is not None:
        thread_safe_print(f"{log_prefix}命中缓存 ✓")
        return {
            'slice_index': slice_index,
            'time_range': time_range,
            'error': None,
            'data': cached,
            'from_cache': True
        }
    
    # 调用API生成摘要
    thread_safe_print(f"{log_prefix}开始处理 ({slice_data['message_count']}条消息)...")
    result, error = call_summary_api(slice_data, user_info, log_prefix)
    
    if error:
        thread_safe_print(f"{log_prefix}失败: {error}")
        return {
            'slice_index': slice_index,
            'time_range': time_range,
            'error': error,
            'data': None,
            'from_cache': False
        }
    
    # 保存到缓存
    if save_cache(cache_path, result):
        thread_safe_print(f"{log_prefix}已缓存 ✓")
    
    return {
        'slice_index': slice_index,
        'time_range': time_range,
        'error': None,
        'data': result,
        'from_cache': False
    }


def analyze_user_semantics_parallel(
    username: str, 
    display_name: str, 
    slices: List[Dict],
    group_name: str
) -> List[Dict]:
    """
    使用多线程对用户的所有切片进行语义分析（第一阶段：生成摘要）
    
    Args:
        username: 用户名
        display_name: 显示名
        slices: 切片列表
        group_name: 群名称（用于缓存路径）
        
    Returns:
        每个切片的摘要结果列表
    """
    user_info = {
        'username': username,
        'display_name': display_name
    }
    
    # 准备参数列表
    args_list = [
        (i, slice_data, user_info, group_name)
        for i, slice_data in enumerate(slices)
    ]
    
    print(f"    开始多线程处理 {len(slices)} 个切片 (并发数: {MAX_WORKERS})...")
    
    results = []
    
    # 使用线程池并行处理
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务
        future_to_index = {
            executor.submit(process_single_slice, args): args[0]
            for args in args_list
        }
        
        # 收集结果
        for future in as_completed(future_to_index):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                slice_index = future_to_index[future]
                thread_safe_print(f"        [切片{slice_index+1}] 异常: {str(e)}")
                results.append({
                    'slice_index': slice_index,
                    'time_range': 'N/A',
                    'error': str(e),
                    'data': None,
                    'from_cache': False
                })
    
    # 按切片索引排序
    results.sort(key=lambda x: x['slice_index'])
    
    # 统计结果
    cached_count = sum(1 for r in results if r.get('from_cache', False))
    success_count = sum(1 for r in results if r['data'] is not None)
    fail_count = len(results) - success_count
    
    print(f"    摘要完成: 成功 {success_count} 个 (缓存 {cached_count} 个), 失败 {fail_count} 个")
    
    return results


def generate_final_analysis(
    username: str,
    display_name: str,
    summaries: List[Dict],
    basic_stats: Dict,
    group_name: str
) -> Tuple[Optional[Dict], Optional[str]]:
    """
    基于摘要生成最终综合分析（第二阶段）
    
    Args:
        username: 用户名
        display_name: 显示名
        summaries: 所有切片的摘要列表
        basic_stats: 基础统计数据
        group_name: 群名称
        
    Returns:
        (分析结果, 错误信息)
    """
    user_info = {
        'username': username,
        'display_name': display_name
    }
    
    # 检查最终分析缓存
    cache_path = get_final_analysis_cache_path(group_name, username)
    cached = load_cache(cache_path)
    
    if cached is not None:
        print(f"    综合分析命中缓存 ✓")
        return cached, None
    
    # 过滤有效摘要
    valid_summaries = [s for s in summaries if s.get('data') is not None]
    
    if not valid_summaries:
        return None, "没有有效的摘要数据"
    
    print(f"    开始综合分析 (基于 {len(valid_summaries)} 个有效摘要)...")
    
    # 调用API生成最终分析
    result, error = call_final_analysis_api(user_info, valid_summaries, basic_stats, "    ")
    
    if error:
        return None, error
    
    # 保存到缓存
    if save_cache(cache_path, result):
        print(f"    综合分析已缓存 ✓")
    
    return result, None


# ============================================================
# 第三层分析：汇总生成
# ============================================================

def merge_slice_results(slice_results: List[Dict]) -> Dict:
    """
    合并所有切片的分析结果
    
    Args:
        slice_results: 切片分析结果列表
        
    Returns:
        合并后的分析结果
    """
    # 过滤有效结果
    valid_results = [r for r in slice_results if r['data'] is not None]
    
    if not valid_results:
        return {
            'emotion_analysis': {
                'positive_ratio': 50,
                'negative_ratio': 50,
                'volatility': '信息不足',
                'dominant_tone': '信息不足'
            },
            'communication_style': {
                'style_tags': ['信息不足'],
                'language_pattern': '信息不足',
                'emoji_usage': '信息不足'
            },
            'topic_interests': {
                'main_topics': ['信息不足'],
                'keywords': [],
                'interest_description': '信息不足'
            },
            'role_analysis': {
                'group_role': '信息不足',
                'initiative_level': '信息不足',
                'social_behavior': '信息不足'
            },
            'professional_inference': {
                'possible_fields': ['信息不足'],
                'expertise_indicators': '信息不足',
                'confidence': '低'
            },
            'summary': '数据不足，无法生成有效分析'
        }
    
    # 合并情绪分析
    positive_ratios = []
    negative_ratios = []
    volatilities = []
    tones = []
    
    for r in valid_results:
        data = r['data']
        if 'emotion_analysis' in data:
            ea = data['emotion_analysis']
            if isinstance(ea.get('positive_ratio'), (int, float)):
                positive_ratios.append(ea['positive_ratio'])
            if isinstance(ea.get('negative_ratio'), (int, float)):
                negative_ratios.append(ea['negative_ratio'])
            if ea.get('volatility'):
                volatilities.append(ea['volatility'])
            if ea.get('dominant_tone'):
                tones.append(ea['dominant_tone'])
    
    # 合并话题和关键词
    all_topics = []
    all_keywords = []
    interest_descs = []
    
    for r in valid_results:
        data = r['data']
        if 'topic_interests' in data:
            ti = data['topic_interests']
            if isinstance(ti.get('main_topics'), list):
                all_topics.extend(ti['main_topics'])
            if isinstance(ti.get('keywords'), list):
                all_keywords.extend(ti['keywords'])
            if ti.get('interest_description'):
                interest_descs.append(ti['interest_description'])
    
    # 统计最常见的话题和关键词
    topic_counts = defaultdict(int)
    for t in all_topics:
        topic_counts[t] += 1
    top_topics = sorted(topic_counts.keys(), key=lambda x: topic_counts[x], reverse=True)[:5]
    
    keyword_counts = defaultdict(int)
    for k in all_keywords:
        keyword_counts[k] += 1
    top_keywords = sorted(keyword_counts.keys(), key=lambda x: keyword_counts[x], reverse=True)[:10]
    
    # 合并角色分析
    roles = []
    initiatives = []
    behaviors = []
    
    for r in valid_results:
        data = r['data']
        if 'role_analysis' in data:
            ra = data['role_analysis']
            if ra.get('group_role'):
                roles.append(ra['group_role'])
            if ra.get('initiative_level'):
                initiatives.append(ra['initiative_level'])
            if ra.get('social_behavior'):
                behaviors.append(ra['social_behavior'])
    
    # 合并沟通风格
    all_style_tags = []
    patterns = []
    emoji_usages = []
    
    for r in valid_results:
        data = r['data']
        if 'communication_style' in data:
            cs = data['communication_style']
            if isinstance(cs.get('style_tags'), list):
                all_style_tags.extend(cs['style_tags'])
            if cs.get('language_pattern'):
                patterns.append(cs['language_pattern'])
            if cs.get('emoji_usage'):
                emoji_usages.append(cs['emoji_usage'])
    
    style_tag_counts = defaultdict(int)
    for t in all_style_tags:
        style_tag_counts[t] += 1
    top_style_tags = sorted(style_tag_counts.keys(), key=lambda x: style_tag_counts[x], reverse=True)[:5]
    
    # 合并专业领域
    all_fields = []
    expertise_indicators = []
    confidences = []
    
    for r in valid_results:
        data = r['data']
        if 'professional_inference' in data:
            pi = data['professional_inference']
            if isinstance(pi.get('possible_fields'), list):
                all_fields.extend(pi['possible_fields'])
            if pi.get('expertise_indicators'):
                expertise_indicators.append(pi['expertise_indicators'])
            if pi.get('confidence'):
                confidences.append(pi['confidence'])
    
    field_counts = defaultdict(int)
    for f in all_fields:
        field_counts[f] += 1
    top_fields = sorted(field_counts.keys(), key=lambda x: field_counts[x], reverse=True)[:3]
    
    # 合并摘要
    summaries = []
    for r in valid_results:
        data = r['data']
        if data.get('summary'):
            summaries.append(data['summary'])
    
    # 计算综合情绪波动
    def get_volatility_score(v):
        return {'低': 1, '中': 2, '高': 3}.get(v, 2)
    
    avg_volatility = sum(get_volatility_score(v) for v in volatilities) / len(volatilities) if volatilities else 2
    volatility_result = '低' if avg_volatility < 1.5 else ('高' if avg_volatility > 2.5 else '中')
    
    # 计算主动程度
    def get_initiative_score(i):
        return {'被动': 1, '均衡': 2, '主动': 3}.get(i, 2)
    
    avg_initiative = sum(get_initiative_score(i) for i in initiatives) / len(initiatives) if initiatives else 2
    initiative_result = '被动' if avg_initiative < 1.5 else ('主动' if avg_initiative > 2.5 else '均衡')
    
    return {
        'emotion_analysis': {
            'positive_ratio': round(sum(positive_ratios) / len(positive_ratios)) if positive_ratios else 50,
            'negative_ratio': round(sum(negative_ratios) / len(negative_ratios)) if negative_ratios else 50,
            'volatility': volatility_result,
            'dominant_tone': tones[0] if tones else '信息不足'
        },
        'communication_style': {
            'style_tags': top_style_tags if top_style_tags else ['信息不足'],
            'language_pattern': patterns[0] if patterns else '信息不足',
            'emoji_usage': emoji_usages[0] if emoji_usages else '信息不足'
        },
        'topic_interests': {
            'main_topics': top_topics if top_topics else ['信息不足'],
            'keywords': top_keywords,
            'interest_description': interest_descs[0] if interest_descs else '信息不足'
        },
        'role_analysis': {
            'group_role': roles[0] if roles else '信息不足',
            'initiative_level': initiative_result,
            'social_behavior': behaviors[0] if behaviors else '信息不足'
        },
        'professional_inference': {
            'possible_fields': top_fields if top_fields else ['信息不足'],
            'expertise_indicators': expertise_indicators[0] if expertise_indicators else '信息不足',
            'confidence': confidences[0] if confidences else '低'
        },
        'summary': summaries[0] if summaries else '数据不足，无法生成有效分析'
    }


def calculate_social_network(all_messages: List[Dict], user_messages: Dict[str, List[Dict]]) -> Dict:
    """
    计算社交关系网络
    
    Args:
        all_messages: 所有消息列表
        user_messages: 按用户分组的消息
        
    Returns:
        社交网络分析结果
    """
    # 计算互动矩阵（基于@提及和引用）
    interaction_matrix = defaultdict(lambda: defaultdict(int))
    
    # 统计每个用户被@的次数
    mention_received = defaultdict(int)
    
    for msg in all_messages:
        sender = msg.get('senderUsername', '')
        content = msg.get('content', '')
        
        # 统计@提及
        mentions = re.findall(r'@(\w+)', content)
        for mentioned in mentions:
            if mentioned != sender:
                interaction_matrix[sender][mentioned] += 1
                mention_received[mentioned] += 1
    
    # 计算每个用户的互动得分
    user_scores = {}
    for username in user_messages.keys():
        msg_count = len(user_messages[username])
        mentions_given = sum(interaction_matrix[username].values())
        mentions_got = mention_received.get(username, 0)
        user_scores[username] = {
            'message_count': msg_count,
            'mentions_given': mentions_given,
            'mentions_received': mentions_got,
            'interaction_score': msg_count + mentions_given * 2 + mentions_got * 2
        }
    
    # 按互动得分排序
    sorted_users = sorted(user_scores.keys(), key=lambda x: user_scores[x]['interaction_score'], reverse=True)
    
    # 核心成员（前30%或至少1人）
    core_count = max(1, len(sorted_users) // 3)
    core_members = sorted_users[:core_count]
    
    # 边缘成员（后30%）
    peripheral_count = max(1, len(sorted_users) // 3)
    peripheral_members = sorted_users[-peripheral_count:] if len(sorted_users) > 1 else []
    
    return {
        'interaction_matrix': dict(interaction_matrix),
        'user_scores': user_scores,
        'core_members': core_members,
        'peripheral_members': peripheral_members
    }


def generate_user_profile(
    username: str,
    display_name: str,
    basic_stats: Dict,
    semantic_results: Dict,
    social_data: Dict,
    total_messages: int
) -> Dict:
    """
    生成用户综合画像
    
    Args:
        username: 用户名
        display_name: 显示名
        basic_stats: 基础统计数据
        semantic_results: 语义分析结果
        social_data: 社交网络数据
        total_messages: 群总消息数
        
    Returns:
        用户画像字典
    """
    # 计算消息占比
    message_ratio = round(basic_stats['message_count'] / total_messages * 100, 2) if total_messages > 0 else 0
    
    # 确定群内地位
    user_score = social_data['user_scores'].get(username, {})
    if username in social_data['core_members']:
        group_status = '核心成员'
    elif username in social_data['peripheral_members']:
        group_status = '边缘成员'
    else:
        group_status = '活跃成员'
    
    # 生成用户标签
    tags = []
    
    # 基于角色的标签
    role = semantic_results.get('role_analysis', {}).get('group_role', '')
    if role and role != '信息不足':
        tags.append(role)
    
    # 基于情绪的标签
    emotion = semantic_results.get('emotion_analysis', {})
    if emotion.get('positive_ratio', 50) > 70:
        tags.append('正能量')
    elif emotion.get('negative_ratio', 50) > 70:
        tags.append('情绪化')
    
    # 基于活跃度的标签
    if message_ratio > 30:
        tags.append('话痨')
    elif message_ratio < 5:
        tags.append('低调')
    
    # 基于专业领域的标签
    fields = semantic_results.get('professional_inference', {}).get('possible_fields', [])
    if fields and fields[0] != '信息不足':
        tags.append(fields[0])
    
    # 基于沟通风格的标签
    style_tags = semantic_results.get('communication_style', {}).get('style_tags', [])
    for tag in style_tags[:2]:
        if tag not in tags and tag != '信息不足':
            tags.append(tag)
    
    # 限制标签数量
    tags = tags[:5]
    
    return {
        'username': username,
        'display_name': display_name,
        'basic_stats': basic_stats,
        'semantic_results': semantic_results,
        'message_ratio': message_ratio,
        'group_status': group_status,
        'tags': tags,
        'mentions_given': user_score.get('mentions_given', 0),
        'mentions_received': user_score.get('mentions_received', 0)
    }


# ============================================================
# 报告生成模块
# ============================================================

def generate_markdown_report(profiles: List[Dict], group_info: Dict, social_data: Dict) -> str:
    """
    生成Markdown格式的分析报告
    
    Args:
        profiles: 用户画像列表
        group_info: 群信息
        social_data: 社交网络数据
        
    Returns:
        Markdown格式的报告字符串
    """
    report = []
    
    # 标题
    report.append(f"# {group_info['group_name']} 用户画像分析报告\n")
    
    # 群整体信息
    report.append("## 📊 群整体信息\n")
    report.append(f"- **群名称**: {group_info['group_name']}")
    report.append(f"- **分析时间范围**: {group_info['time_range']}")
    report.append(f"- **总消息数**: {group_info['total_messages']} 条")
    report.append(f"- **成员数**: {group_info['member_count']} 人")
    report.append(f"- **分析生成时间**: {group_info['analysis_time']}\n")
    
    # 社交关系网络
    report.append("## 🔗 社交关系网络\n")
    
    report.append("### 核心成员")
    for username in social_data['core_members']:
        score = social_data['user_scores'].get(username, {})
        profile = next((p for p in profiles if p['username'] == username), None)
        display_name = profile['display_name'] if profile else username
        report.append(f"- **{display_name}** ({username}): {score.get('message_count', 0)}条消息, 互动得分 {score.get('interaction_score', 0)}")
    report.append("")
    
    if social_data['peripheral_members']:
        report.append("### 边缘成员")
        for username in social_data['peripheral_members']:
            score = social_data['user_scores'].get(username, {})
            profile = next((p for p in profiles if p['username'] == username), None)
            display_name = profile['display_name'] if profile else username
            report.append(f"- **{display_name}** ({username}): {score.get('message_count', 0)}条消息")
        report.append("")
    
    # 成员画像
    report.append("---\n")
    report.append("## 👤 成员画像\n")
    
    # 按消息数量排序
    sorted_profiles = sorted(profiles, key=lambda x: x['basic_stats']['message_count'], reverse=True)
    
    for profile in sorted_profiles:
        report.append(f"### {profile['display_name']}（{profile['username']}）\n")
        
        # 用户标签
        if profile['tags']:
            tags_str = " ".join([f"`{tag}`" for tag in profile['tags']])
            report.append(f"**标签**: {tags_str}\n")
        
        # 基础统计
        report.append("#### 📊 基础统计\n")
        stats = profile['basic_stats']
        report.append("| 指标 | 数值 |")
        report.append("|------|------|")
        report.append(f"| 发言总数 | {stats['message_count']} 条 |")
        report.append(f"| 平均消息长度 | {stats['avg_length']} 字 |")
        report.append(f"| 消息占比 | {profile['message_ratio']}% |")
        report.append(f"| 活跃时段 | {format_active_hours(stats['active_hours'])} |")
        report.append(f"| 最活跃日期 | {stats['most_active_date']} ({stats.get('most_active_count', 0)}条) |")
        report.append(f"| @他人次数 | {profile['mentions_given']} 次 |")
        report.append(f"| 被@次数 | {profile['mentions_received']} 次 |")
        report.append(f"| 群内地位 | {profile['group_status']} |")
        report.append("")
        
        # 消息类型分布
        report.append("#### 📱 消息类型分布\n")
        report.append("| 类型 | 数量 | 占比 |")
        report.append("|------|------|------|")
        
        msg_types = stats.get('message_types', {})
        total_msgs = sum(msg_types.values()) if msg_types else 1
        for msg_type, count in sorted(msg_types.items(), key=lambda x: x[1], reverse=True):
            ratio = round(count / total_msgs * 100, 1)
            report.append(f"| {msg_type} | {count} | {ratio}% |")
        report.append("")
        
        # 语义分析结果
        sem = profile.get('semantic_results', {})
        
        # 情绪与沟通风格
        report.append("#### 🎭 情绪与沟通风格\n")
        emotion = sem.get('emotion_analysis', {})
        style = sem.get('communication_style', {})
        
        report.append(f"- **情绪倾向**: 正向 {emotion.get('positive_ratio', 50)}% / 负向 {emotion.get('negative_ratio', 50)}%")
        report.append(f"- **情绪波动**: {emotion.get('volatility', '信息不足')}")
        report.append(f"- **语气特征**: {emotion.get('dominant_tone', '信息不足')}")
        report.append(f"- **语言风格**: {style.get('language_pattern', '信息不足')}")
        report.append(f"- **表情偏好**: {style.get('emoji_usage', '信息不足')}")
        report.append("")
        
        # 兴趣与话题
        report.append("#### 💡 兴趣与话题\n")
        topics = sem.get('topic_interests', {})
        main_topics = topics.get('main_topics', [])
        keywords = topics.get('keywords', [])
        
        report.append(f"- **主要话题**: {', '.join(main_topics) if main_topics else '信息不足'}")
        report.append(f"- **典型关键词**: {', '.join(keywords[:5]) if keywords else '信息不足'}")
        report.append(f"- **兴趣描述**: {topics.get('interest_description', '信息不足')}")
        report.append("")
        
        # 角色定位
        report.append("#### 🎯 角色定位\n")
        role = sem.get('role_analysis', {})
        
        report.append(f"- **群内角色**: {role.get('group_role', '信息不足')}")
        report.append(f"- **主动程度**: {role.get('initiative_level', '信息不足')}")
        report.append(f"- **社交行为**: {role.get('social_behavior', '信息不足')}")
        report.append("")
        
        # 专业领域
        report.append("#### 🔧 专业领域\n")
        prof = sem.get('professional_inference', {})
        possible_fields = prof.get('possible_fields', [])
        
        report.append(f"- **可能领域**: {', '.join(possible_fields) if possible_fields else '信息不足'}")
        report.append(f"- **专业指标**: {prof.get('expertise_indicators', '信息不足')}")
        report.append(f"- **推断置信度**: {prof.get('confidence', '低')}")
        report.append("")
        
        # 综合评价
        report.append("#### 📝 综合评价\n")
        report.append(f"> {sem.get('summary', '数据不足，无法生成有效分析')}")
        report.append("")
        report.append("---\n")
    
    # 分析说明
    report.append("## 📋 分析说明\n")
    report.append("- 本报告基于导出的微信聊天记录自动生成")
    report.append("- 语义分析部分由AI模型完成，结果仅供参考")
    report.append("- 量化指标为本地统计结果，数据准确")
    report.append("- 若某项分析显示\"信息不足\"，表示该维度的数据不足以支撑有效推断")
    
    return "\n".join(report)


# ============================================================
# 单用户报告生成
# ============================================================

def generate_single_user_report(profile: Dict, group_info: Dict) -> str:
    """
    生成单个用户的分析报告
    
    Args:
        profile: 用户画像数据
        group_info: 群信息
        
    Returns:
        Markdown格式的单用户报告
    """
    report = []
    
    # 标题
    report.append(f"# {profile['display_name']} 用户画像分析\n")
    report.append(f"**群名称**: {group_info['group_name']}")
    report.append(f"**分析时间**: {group_info['analysis_time']}\n")
    report.append("---\n")
    
    # 用户标签
    if profile.get('tags'):
        tags_str = " ".join([f"`{tag}`" for tag in profile['tags']])
        report.append(f"**标签**: {tags_str}\n")
    
    # 基础统计
    report.append("## 📊 基础统计\n")
    stats = profile['basic_stats']
    report.append("| 指标 | 数值 |")
    report.append("|------|------|")
    report.append(f"| 发言总数 | {stats['message_count']} 条 |")
    report.append(f"| 平均消息长度 | {stats['avg_length']} 字 |")
    report.append(f"| 消息占比 | {profile['message_ratio']}% |")
    report.append(f"| 活跃时段 | {format_active_hours(stats['active_hours'])} |")
    report.append(f"| 最活跃日期 | {stats['most_active_date']} ({stats.get('most_active_count', 0)}条) |")
    report.append(f"| @他人次数 | {profile['mentions_given']} 次 |")
    report.append(f"| 被@次数 | {profile['mentions_received']} 次 |")
    report.append(f"| 群内地位 | {profile['group_status']} |")
    report.append("")
    
    # 语义分析结果
    sem = profile.get('semantic_results', {})
    
    # 情绪与沟通风格
    report.append("## 🎭 情绪与沟通风格\n")
    emotion = sem.get('emotion_analysis', {})
    style = sem.get('communication_style', {})
    
    report.append(f"- **情绪倾向**: 正向 {emotion.get('positive_ratio', 50)}% / 负向 {emotion.get('negative_ratio', 50)}%")
    report.append(f"- **情绪波动**: {emotion.get('volatility', '信息不足')}")
    report.append(f"- **语气特征**: {emotion.get('dominant_tone', '信息不足')}")
    report.append(f"- **语言风格**: {style.get('language_pattern', '信息不足')}")
    report.append(f"- **表情偏好**: {style.get('emoji_usage', '信息不足')}")
    report.append("")
    
    # 兴趣与话题
    report.append("## 💡 兴趣与话题\n")
    topics = sem.get('topic_interests', {})
    main_topics = topics.get('main_topics', [])
    keywords = topics.get('keywords', [])
    
    report.append(f"- **主要话题**: {', '.join(main_topics) if main_topics else '信息不足'}")
    report.append(f"- **典型关键词**: {', '.join(keywords[:5]) if keywords else '信息不足'}")
    report.append(f"- **兴趣描述**: {topics.get('interest_description', '信息不足')}")
    report.append("")
    
    # 角色定位
    report.append("## 🎯 角色定位\n")
    role = sem.get('role_analysis', {})
    
    report.append(f"- **群内角色**: {role.get('group_role', '信息不足')}")
    report.append(f"- **主动程度**: {role.get('initiative_level', '信息不足')}")
    report.append(f"- **社交行为**: {role.get('social_behavior', '信息不足')}")
    report.append("")
    
    # 专业领域
    report.append("## 🔧 专业领域\n")
    prof = sem.get('professional_inference', {})
    possible_fields = prof.get('possible_fields', [])
    
    report.append(f"- **可能领域**: {', '.join(possible_fields) if possible_fields else '信息不足'}")
    report.append(f"- **专业指标**: {prof.get('expertise_indicators', '信息不足')}")
    report.append(f"- **推断置信度**: {prof.get('confidence', '低')}")
    report.append("")
    
    # 综合评价
    report.append("## 📝 综合评价\n")
    report.append(f"> {sem.get('summary', '数据不足，无法生成有效分析')}")
    
    return "\n".join(report)


def save_user_report(profile: Dict, group_info: Dict, output_dir: str) -> str:
    """
    保存单用户报告
    
    Args:
        profile: 用户画像数据
        group_info: 群信息
        output_dir: 输出目录
        
    Returns:
        保存的文件路径
    """
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成报告
    report = generate_single_user_report(profile, group_info)
    
    # 生成文件名
    safe_group = get_safe_filename(group_info['group_name'])
    safe_user = get_safe_filename(profile['display_name'])
    filename = f"{safe_group}_{safe_user}_画像.md"
    
    file_path = os.path.join(output_dir, filename)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    return file_path


# ============================================================
# 主流程
# ============================================================

def process_single_file(json_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    处理单个JSON文件（支持两阶段分析、多线程、逐用户报告）
    
    Args:
        json_path: JSON文件路径
        
    Returns:
        (报告内容, 错误信息): 成功返回(报告, None)，失败返回(None, 错误信息)
    """
    print(f"\n{'='*60}")
    print(f"处理文件: {json_path}")
    print('='*60)
    
    # 1. 加载和验证JSON
    print("\n[1/6] 加载JSON文件...")
    data, error = load_json_file(json_path)
    if error:
        return None, error
    
    group_name = data['session']['nickname']
    print(f"  ✓ 成功加载，群名: {group_name}")
    
    # 2. 提取消息（含时间过滤）
    print("\n[2/6] 提取和预处理消息...")
    messages, extract_stats = extract_messages(data)
    print(f"  ✓ 原始消息: {extract_stats['total']} 条")
    print(f"  ✓ 系统消息: {extract_stats['system']} 条（已过滤）")
    if TIME_FILTER_START > 0 or TIME_FILTER_END > 0:
        from datetime import datetime
        time_desc = ""
        if TIME_FILTER_START > 0:
            time_desc += f"从 {datetime.fromtimestamp(TIME_FILTER_START).strftime('%Y-%m-%d')}"
        if TIME_FILTER_END > 0:
            time_desc += f" 到 {datetime.fromtimestamp(TIME_FILTER_END).strftime('%Y-%m-%d')}"
        print(f"  ✓ 时间过滤 ({time_desc}): 过滤掉 {extract_stats['time_filtered']} 条")
    print(f"  ✓ 有效消息: {extract_stats['valid']} 条")
    
    # 3. 按用户分组
    print("\n[3/6] 按用户分组消息...")
    user_messages_all = group_by_user(messages)
    display_names = get_user_display_names(messages)
    print(f"  ✓ 共 {len(user_messages_all)} 个用户")
    
    # 根据消息数过滤用户
    if MIN_MESSAGE_COUNT > 0:
        user_messages = {
            username: msgs 
            for username, msgs in user_messages_all.items() 
            if len(msgs) >= MIN_MESSAGE_COUNT
        }
        print(f"  ✓ 过滤后（消息数 >= {MIN_MESSAGE_COUNT}）: {len(user_messages)} 个用户待分析")
    else:
        user_messages = user_messages_all
    
    for username, msgs in sorted(user_messages_all.items(), key=lambda x: len(x[1]), reverse=True):
        display_name = display_names.get(username, username)
        marker = "✓" if username in user_messages else " "
        print(f"    [{marker}] {display_name} ({username}): {len(msgs)} 条")
    
    # 4. 第一层分析：本地统计
    print("\n[4/6] 计算基础统计数据...")
    basic_stats_all = {}
    for username, msgs in user_messages.items():
        basic_stats_all[username] = calculate_basic_stats(msgs, username)
    print(f"  ✓ 完成基础统计")
    
    # 5. 计算社交网络（使用所有用户数据计算，确保关系完整）
    print("\n[5/6] 计算社交关系网络...")
    social_data = calculate_social_network(messages, user_messages_all)
    print(f"  ✓ 核心成员: {len(social_data['core_members'])} 人")
    print(f"  ✓ 边缘成员: {len(social_data['peripheral_members'])} 人")
    
    # 6. 两阶段语义分析 + 逐用户报告
    print("\n[6/6] 进行语义分析（两阶段：摘要 → 综合分析）...")
    
    profiles = []
    total_messages = len(messages)
    
    # 检查API配置
    api_configured = bool(OPENAI_API and API_KEY and MODEL_NAME)
    if not api_configured:
        print("  ⚠ API未配置，将跳过语义分析，仅生成基础统计报告")
    
    # 获取输出目录
    if os.path.isfile(json_path):
        output_dir = os.path.join(os.path.dirname(json_path), 'results')
    else:
        output_dir = os.path.join(json_path, 'results')
    
    # 获取时间范围
    if messages:
        sorted_msgs = sorted(messages, key=lambda x: x['createTime'])
        time_range = f"{sorted_msgs[0]['formattedTime']} 至 {sorted_msgs[-1]['formattedTime']}"
    else:
        time_range = "无数据"
    
    group_info = {
        'group_name': group_name,
        'time_range': time_range,
        'total_messages': total_messages,
        'member_count': len(user_messages_all),  # 总成员数
        'analyzed_count': len(user_messages),     # 实际分析的用户数
        'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # 逐用户处理
    user_count = len(user_messages)
    for idx, (username, msgs) in enumerate(user_messages.items()):
        display_name = display_names.get(username, username)
        print(f"\n  [{idx+1}/{user_count}] 处理用户: {display_name} ({username})")
        
        # 切片
        slices = slice_messages_by_time(msgs)
        original_slice_count = len(slices)
        
        # 抽样（如果切片过多）
        slices, was_sampled = sample_slices(slices, MAX_SLICES_PER_USER)
        if was_sampled:
            print(f"    生成 {original_slice_count} 个切片 → 抽样后 {len(slices)} 个")
        else:
            print(f"    生成 {len(slices)} 个切片")
        
        # 语义分析
        if api_configured:
            # 第一阶段：多线程生成摘要
            summaries = analyze_user_semantics_parallel(username, display_name, slices, group_name)
            
            # 第二阶段：综合分析
            final_analysis, error = generate_final_analysis(
                username, display_name, summaries, 
                basic_stats_all[username], group_name
            )
            
            if error:
                print(f"    ⚠ 综合分析失败: {error}")
                final_analysis = {
                    'emotion_analysis': {'positive_ratio': 50, 'negative_ratio': 50, 'volatility': '分析失败', 'dominant_tone': '分析失败'},
                    'communication_style': {'style_tags': ['分析失败'], 'language_pattern': '分析失败', 'emoji_usage': '分析失败'},
                    'topic_interests': {'main_topics': ['分析失败'], 'keywords': [], 'interest_description': '分析失败'},
                    'role_analysis': {'group_role': '分析失败', 'initiative_level': '分析失败', 'social_behavior': '分析失败'},
                    'professional_inference': {'possible_fields': ['分析失败'], 'expertise_indicators': '分析失败', 'confidence': '低'},
                    'summary': f'综合分析失败: {error}',
                    'tags': []
                }
        else:
            final_analysis = {
                'emotion_analysis': {'positive_ratio': 50, 'negative_ratio': 50, 'volatility': '未分析', 'dominant_tone': '未分析'},
                'communication_style': {'style_tags': ['未分析'], 'language_pattern': '未分析', 'emoji_usage': '未分析'},
                'topic_interests': {'main_topics': ['未分析'], 'keywords': [], 'interest_description': '未分析'},
                'role_analysis': {'group_role': '未分析', 'initiative_level': '未分析', 'social_behavior': '未分析'},
                'professional_inference': {'possible_fields': ['未分析'], 'expertise_indicators': '未分析', 'confidence': '未分析'},
                'summary': 'API未配置，语义分析未执行',
                'tags': []
            }
        
        # 生成用户画像
        profile = generate_user_profile(
            username,
            display_name,
            basic_stats_all[username],
            final_analysis,
            social_data,
            total_messages
        )
        profiles.append(profile)
        
        # 保存单用户报告
        user_report_path = save_user_report(profile, group_info, output_dir)
        print(f"    ✓ 用户报告已保存: {user_report_path}")
    
    # 生成群整体报告
    print("\n生成群整体分析报告...")
    report = generate_markdown_report(profiles, group_info, social_data)
    print("  ✓ 群整体报告生成完成")
    
    return report, None


def process_directory(dir_path: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """
    处理目录中的所有JSON文件
    
    Args:
        dir_path: 目录路径
        
    Returns:
        [(文件名, 报告内容, 错误信息), ...] 的列表
    """
    results = []
    
    # 查找所有JSON文件
    json_files = [f for f in os.listdir(dir_path) if f.endswith('.json')]
    
    if not json_files:
        print(f"目录 {dir_path} 中没有找到JSON文件")
        return results
    
    print(f"找到 {len(json_files)} 个JSON文件")
    
    for json_file in json_files:
        file_path = os.path.join(dir_path, json_file)
        report, error = process_single_file(file_path)
        results.append((json_file, report, error))
    
    return results


def save_report(report: str, group_name: str, output_dir: str) -> str:
    """
    保存分析报告
    
    Args:
        report: 报告内容
        group_name: 群名称
        output_dir: 输出目录
        
    Returns:
        保存的文件路径
    """
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成文件名（清理非法字符）
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', group_name)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{safe_name}_分析结果_{timestamp}.md"
    
    file_path = os.path.join(output_dir, filename)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    return file_path


def main():
    """主函数"""
    print("="*60)
    print("微信群聊用户画像分析系统")
    print("="*60)
    
    # 检查配置
    if not CONTENT_DIR:
        print("\n错误: 请设置 CONTENT_DIR 常量（JSON文件路径或目录路径）")
        return
    
    if not os.path.exists(CONTENT_DIR):
        print(f"\n错误: 路径不存在: {CONTENT_DIR}")
        return
    
    # 确定输出目录
    if os.path.isfile(CONTENT_DIR):
        output_dir = os.path.join(os.path.dirname(CONTENT_DIR), 'results')
    else:
        output_dir = os.path.join(CONTENT_DIR, 'results')
    
    # 处理文件
    if os.path.isfile(CONTENT_DIR):
        # 处理单个文件
        report, error = process_single_file(CONTENT_DIR)
        
        if error:
            print(f"\n处理失败: {error}")
        else:
            # 从文件中提取群名
            data, _ = load_json_file(CONTENT_DIR)
            group_name = data['session']['nickname'] if data else 'unknown'
            
            saved_path = save_report(report, group_name, output_dir)
            print(f"\n✓ 报告已保存: {saved_path}")
    else:
        # 处理目录
        results = process_directory(CONTENT_DIR)
        
        success_count = 0
        fail_count = 0
        
        for json_file, report, error in results:
            if error:
                print(f"\n✗ {json_file}: {error}")
                fail_count += 1
            else:
                # 从文件名提取群名（去掉时间戳部分）
                group_name = json_file.rsplit('_', 1)[0] if '_' in json_file else json_file.replace('.json', '')
                saved_path = save_report(report, group_name, output_dir)
                print(f"\n✓ {json_file} -> {saved_path}")
                success_count += 1
        
        print(f"\n{'='*60}")
        print(f"处理完成: 成功 {success_count} 个，失败 {fail_count} 个")
        print(f"输出目录: {output_dir}")


if __name__ == "__main__":
    main()

