#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信群聊用户画像分析系统 (API Refactored Version)
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
from typing import Dict, List, Optional, Tuple, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# ============================================================
# 默认配置
# ============================================================

DEFAULT_API_TIMEOUT = 180
DEFAULT_SLICE_MAX_MESSAGES = 500
DEFAULT_SLICE_MIN_MESSAGES = 30
DEFAULT_PROMPT_MAX_MESSAGES = 200
DEFAULT_MAX_WORKERS = 10
DEFAULT_CACHE_DIR = "ChenfenTemp"

# 线程锁
print_lock = threading.Lock()
cache_lock = threading.Lock()

# ============================================================
# 辅助函数 (Stateless)
# ============================================================

def get_safe_filename(name: str) -> str:
    """将名称转换为安全的文件名"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def get_slice_hash(slice_data: Dict) -> str:
    """计算切片的哈希值"""
    content = f"{slice_data['time_start']}_{slice_data['time_end']}_{slice_data['message_count']}"
    if slice_data['messages']:
        first_msg = slice_data['messages'][0].get('content', '')[:50]
        last_msg = slice_data['messages'][-1].get('content', '')[:50]
        content += f"_{first_msg}_{last_msg}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()[:8]

def thread_safe_print(message: str):
    """线程安全的打印函数"""
    with print_lock:
        print(message)

def load_json_file(file_path: str) -> Tuple[Optional[Dict], Optional[str]]:
    """加载并验证JSON文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'session' not in data:
            return None, "JSON结构错误: 缺少'session'字段"
        if 'messages' not in data:
            return None, "JSON结构错误: 缺少'messages'字段"
        
        return data, None
    except Exception as e:
        return None, f"读取文件错误: {str(e)}"

def format_active_hours(active_hours: Dict[int, int]) -> str:
    """格式化活跃时段"""
    if not active_hours:
        return "无数据"
    sorted_hours = sorted(active_hours.items(), key=lambda x: x[1], reverse=True)
    top_hours = sorted_hours[:3]
    result = []
    for hour, count in top_hours:
        result.append(f"{hour}:00-{hour+1}:00 ({count}条)")
    return ", ".join(result)

def extract_messages(data: Dict, time_start: int = 0, time_end: int = 0) -> Tuple[List[Dict], Dict]:
    messages = data.get('messages', [])
    extracted = []
    stats = {'total': len(messages), 'system': 0, 'time_filtered': 0, 'valid': 0}
    
    for msg in messages:
        if msg.get('type') == '系统消息':
            stats['system'] += 1
            continue
        
        create_time = msg.get('createTime', 0)
        if time_start > 0 and create_time < time_start:
            stats['time_filtered'] += 1
            continue
        if time_end > 0 and create_time > time_end:
            stats['time_filtered'] += 1
            continue
        
        extracted_msg = {
            'senderUsername': msg.get('senderUsername', ''),
            'senderDisplayName': msg.get('senderDisplayName', ''),
            'createTime': create_time,
            'formattedTime': msg.get('formattedTime', ''),
            'type': msg.get('type', ''),
            'content': msg.get('content', ''),
            'isSend': msg.get('isSend', 0)
        }
        
        if extracted_msg['type'] == '文本消息' and extracted_msg['content']:
            content = extracted_msg['content']
            pattern = r'^[a-zA-Z0-9_]+:\n?'
            extracted_msg['content'] = re.sub(pattern, '', content).strip()
        
        extracted.append(extracted_msg)
        stats['valid'] += 1
    
    return extracted, stats

def group_by_user(messages: List[Dict]) -> Dict[str, List[Dict]]:
    user_messages = defaultdict(list)
    for msg in messages:
        username = msg.get('senderUsername', '')
        if username:
            user_messages[username].append(msg)
    return dict(user_messages)

def get_user_display_names(messages: List[Dict]) -> Dict[str, str]:
    display_names = {}
    for msg in messages:
        username = msg.get('senderUsername', '')
        display_name = msg.get('senderDisplayName', '')
        if username and display_name:
            display_names[username] = display_name
    return display_names

def get_week_key(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"

def get_day_key(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime('%Y-%m-%d')

def create_slice_from_messages(messages: List[Dict]) -> Dict:
    if not messages:
        return {'time_start': '', 'time_end': '', 'message_count': 0, 'messages': []}
    sorted_msgs = sorted(messages, key=lambda x: x['createTime'])
    return {
        'time_start': sorted_msgs[0]['formattedTime'],
        'time_end': sorted_msgs[-1]['formattedTime'],
        'message_count': len(sorted_msgs),
        'messages': sorted_msgs
    }

def slice_messages_by_time(messages: List[Dict], max_msgs=DEFAULT_SLICE_MAX_MESSAGES, min_msgs=DEFAULT_SLICE_MIN_MESSAGES) -> List[Dict]:
    if not messages: return []
    
    weekly_groups = defaultdict(list)
    for msg in messages:
        weekly_groups[get_week_key(msg['createTime'])].append(msg)
    
    sorted_weeks = sorted(weekly_groups.keys())
    slices = []
    pending_merge = []
    
    for week_key in sorted_weeks:
        week_msgs = weekly_groups[week_key]
        if len(week_msgs) > max_msgs:
            if pending_merge:
                slices.append(create_slice_from_messages([m for msgs in pending_merge for m in msgs]))
                pending_merge = []
            
            daily_groups = defaultdict(list)
            for msg in week_msgs:
                daily_groups[get_day_key(msg['createTime'])].append(msg)
            for day_key in sorted(daily_groups.keys()):
                slices.append(create_slice_from_messages(daily_groups[day_key]))
        elif len(week_msgs) < min_msgs:
            pending_merge.append(week_msgs)
            if sum(len(msgs) for msgs in pending_merge) >= min_msgs:
                slices.append(create_slice_from_messages([m for msgs in pending_merge for m in msgs]))
                pending_merge = []
        else:
            if pending_merge:
                pending_merge.append(week_msgs)
                slices.append(create_slice_from_messages([m for msgs in pending_merge for m in msgs]))
                pending_merge = []
            else:
                slices.append(create_slice_from_messages(week_msgs))
    
    if pending_merge:
        slices.append(create_slice_from_messages([m for msgs in pending_merge for m in msgs]))
    return slices

def sample_slices(slices: List[Dict], max_slices: int) -> Tuple[List[Dict], bool]:
    if max_slices <= 0 or len(slices) <= max_slices:
        return slices, False
    if max_slices == 1: return [slices[-1]], True
    if max_slices == 2: return [slices[0], slices[-1]], True
    
    n = len(slices)
    middle_count = max_slices - 2
    step = (n - 2) / (middle_count + 1)
    sampled = [slices[0]]
    for i in range(1, middle_count + 1):
        idx = int(i * step)
        if idx < n - 1: sampled.append(slices[idx])
    sampled.append(slices[-1])
    return sampled, True

def calculate_basic_stats(messages: List[Dict], username: str) -> Dict:
    if not messages:
        return {'message_count': 0, 'avg_length': 0, 'active_hours': {}, 'message_types': {}, 'most_active_date': '', 'interaction_count': {'mentions': 0, 'quotes': 0}}
    
    message_count = len(messages)
    text_messages = [m for m in messages if m['type'] == '文本消息']
    avg_length = round(sum(len(m['content']) for m in text_messages) / len(text_messages), 1) if text_messages else 0
    
    active_hours = defaultdict(int)
    daily_count = defaultdict(int)
    message_types = defaultdict(int)
    mentions = 0
    quotes = 0
    
    for msg in messages:
        try:
            hour = int(msg['formattedTime'].split(' ')[1].split(':')[0])
            active_hours[hour] += 1
        except: pass
        
        date = msg['formattedTime'].split(' ')[0]
        daily_count[date] += 1
        message_types[msg.get('type', '其他')] += 1
        
        content = msg.get('content', '')
        # Only count if user is mentioned
        mentions += len(re.findall(r'@\w+', content))
        if msg.get('type') == '引用消息': quotes += 1

    most_active_date = max(daily_count.keys(), key=lambda x: daily_count[x]) if daily_count else ''
    
    return {
        'message_count': message_count,
        'avg_length': avg_length,
        'active_hours': dict(active_hours),
        'message_types': dict(message_types),
        'most_active_date': most_active_date,
        'most_active_count': daily_count.get(most_active_date, 0),
        'interaction_count': {'mentions': mentions, 'quotes': quotes}
    }

def calculate_social_network(all_messages: List[Dict], user_messages: Dict[str, List[Dict]]) -> Dict:
    interaction_matrix = defaultdict(lambda: defaultdict(int))
    mention_received = defaultdict(int)
    
    for msg in all_messages:
        sender = msg.get('senderUsername', '')
        content = msg.get('content', '')
        mentions = re.findall(r'@(\w+)', content)
        for mentioned in mentions:
            if mentioned != sender:
                interaction_matrix[sender][mentioned] += 1
                mention_received[mentioned] += 1
                
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
        
    sorted_users = sorted(user_scores.keys(), key=lambda x: user_scores[x]['interaction_score'], reverse=True)
    core_count = max(1, len(sorted_users) // 3)
    peripheral_count = max(1, len(sorted_users) // 3)
    
    return {
        'interaction_matrix': dict(interaction_matrix),
        'user_scores': user_scores,
        'core_members': sorted_users[:core_count],
        'peripheral_members': sorted_users[-peripheral_count:] if len(sorted_users) > 1 else []
    }

# ============================================================
# ChatAnalyzer 类
# ============================================================

class ChatAnalyzer:
    def __init__(self, 
                 api_url: str, 
                 api_key: str, 
                 model_name: str,
                 cache_dir: str = DEFAULT_CACHE_DIR,
                 max_workers: int = DEFAULT_MAX_WORKERS,
                 api_timeout: int = DEFAULT_API_TIMEOUT,
                 verbose: bool = True,
                 progress_callback: Optional[Callable[[str], None]] = None):
        """
        初始化分析器
        :param progress_callback: 回调函数，接受字符串参数，用于报告详细进度
        """
        # Fix: Initialize logging configuration first
        self.verbose = verbose
        self.progress_callback = progress_callback
        
        self.api_url = api_url.rstrip('/')
        if not self.api_url.endswith('/chat/completions') and not self.api_url.endswith('/v1'):
             self.api_url += '/v1/chat/completions'
        elif not self.api_url.endswith('/chat/completions'):
             self.api_url += '/chat/completions'
             
        self.api_key = api_key.strip() if api_key else ""
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.max_workers = max_workers
        self.api_timeout = api_timeout
        
        # 确保缓存目录存在
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

    def log(self, msg: str):
        # Console output
        if self.verbose:
            thread_safe_print(msg)
        # GUI callback
        if self.progress_callback:
            self.progress_callback(msg)

    def get_cache_path(self, group_name: str, username: str, suffix: str) -> str:
        safe_group = get_safe_filename(group_name)
        safe_user = get_safe_filename(username)
        user_dir = os.path.join(self.cache_dir, safe_group, safe_user)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, suffix)

    def load_cache_item(self, path: str) -> Optional[Dict]:
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def save_cache_item(self, path: str, data: Dict):
        try:
            with cache_lock:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"Cache save failed: {e}")

    def call_api(self, system_prompt: str, user_message: str, max_retries: int = 3, log_prefix: str = "") -> Tuple[Optional[Dict], Optional[str]]:
        if not self.api_key:
            return None, "API Key not configured"
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.3,
            "max_tokens": 2000
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.post(self.api_url, headers=headers, json=payload, timeout=self.api_timeout)
                if response.status_code == 200:
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    # Clean markdown
                    if content.startswith('```json'): content = content[7:]
                    if content.startswith('```'): content = content[3:]
                    if content.endswith('```'): content = content[:-3]
                    content = content.strip()
                    try:
                        return json.loads(content), None
                    except json.JSONDecodeError as e:
                        return None, f"JSON decode failed: {e}"
                else:
                    self.log(f"{log_prefix}API Error: {response.status_code}")
                    if attempt < max_retries - 1: time.sleep(2**attempt)
            except Exception as e:
                self.log(f"{log_prefix}Request Exception: {e}")
                if attempt < max_retries - 1: time.sleep(2**attempt)
        return None, "Max retries exceeded"

    def process_slice_task(self, slice_index: int, total_slices: int, slice_data: Dict, user_info: Dict, group_name: str) -> Dict:
        username = user_info['username']
        display_name = user_info['display_name']
        slice_hash = get_slice_hash(slice_data)
        cache_path = self.get_cache_path(group_name, username, f"slice_{slice_index:03d}_{slice_hash}.json")
        
        log_prefix = f"[{display_name} {slice_index+1}/{total_slices}] "
        
        cached = self.load_cache_item(cache_path)
        if cached:
            self.log(f"{log_prefix}命中缓存 ✓")
            return {'slice_index': slice_index, 'data': cached, 'error': None, 'from_cache': True}
            
        # Build prompt
        messages_text = []
        for msg in slice_data['messages'][:DEFAULT_PROMPT_MAX_MESSAGES]:
            c = msg.get('content', '')
            t = msg.get('formattedTime', '')
            messages_text.append(f"[{t}] {c}" if msg.get('type') == '文本消息' else f"[{t}] [{msg.get('type')}]")
        
        full_sys_prompt = """你是一位专业的社交行为分析师。请对这段微信群聊记录进行摘要总结，提取关键特征。
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
}"""
        full_user_msg = f"""请为以下用户生成摘要：
用户: {user_info['display_name']} ({user_info['username']})
时间范围: {slice_data['time_start']} 至 {slice_data['time_end']}
消息数: {slice_data['message_count']}
聊天记录:
{chr(10).join(messages_text)}
请返回JSON格式的摘要。"""

        self.log(f"{log_prefix}开始分析...")
        result, error = self.call_api(full_sys_prompt, full_user_msg, log_prefix=log_prefix)
        
        if result:
            self.save_cache_item(cache_path, result)
            self.log(f"{log_prefix}分析完成 ✓")
        elif error:
            self.log(f"{log_prefix}分析失败: {error}")
            
        return {'slice_index': slice_index, 'data': result, 'error': error, 'from_cache': False}

    def analyze_user_final(self, user_info: Dict, summaries: List[Dict], basic_stats: Dict, group_name: str, custom_sys_prompt: str = None) -> Tuple[Optional[Dict], Optional[str]]:
        # Define prompt first to calculate hash for cache key
        sys_prompt = custom_sys_prompt if custom_sys_prompt else """你是一位专业的社交行为分析师。请基于用户在不同时间段的聊天摘要，生成综合用户画像。
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
}"""
        
        # Calculate prompt hash for cache invalidation
        prompt_hash = hashlib.md5(sys_prompt.encode('utf-8')).hexdigest()[:8]
        cache_filename = f"final_analysis_{prompt_hash}.json"
        
        cache_path = self.get_cache_path(group_name, user_info['username'], cache_filename)
        cached = self.load_cache_item(cache_path)
        if cached: 
            self.log(f"[{user_info['display_name']}] 综合分析命中缓存 ({prompt_hash}) ✓")
            return cached, None
        
        valid_summaries = [s['data'] for s in summaries if s['data']]
        if not valid_summaries: return None, "No valid summaries"
        
        summaries_text = []
        for i, data in enumerate(valid_summaries):
            summaries_text.append(f"--- Segment {i+1} ---\nTone: {data.get('emotion_summary',{}).get('overall_tone')}\nSummary: {data.get('brief_summary')}")
        user_msg = f"""请为以下用户生成综合画像：
用户: {user_info['display_name']} ({user_info['username']})
基础统计:
- 总发言数: {basic_stats.get('message_count', 0)} 条
- 平均消息长度: {basic_stats.get('avg_length', 0)} 字
- 活跃时段: {format_active_hours(basic_stats.get('active_hours', {}))}
- @他人次数: {basic_stats.get('interaction_count', {}).get('mentions', 0)} 次
- 引用消息次数: {basic_stats.get('interaction_count', {}).get('quotes', 0)} 次

各时间段摘要:
{''.join(summaries_text)}"""
        
        self.log(f"[{user_info['display_name']}] 开始综合分析...")
        result, error = self.call_api(sys_prompt, user_msg, log_prefix="[Final]")
        if result:
            self.save_cache_item(cache_path, result)
            self.log(f"[{user_info['display_name']}] 综合分析完成 ✓")
        elif error:
            self.log(f"[{user_info['display_name']}] 综合分析失败: {error}")

        return result, error

    def run_analysis(self, 
                     json_path: str, 
                     output_dir: str, 
                     users_to_analyze: List[str] = [],
                     time_start: int = 0,
                     time_end: int = 0,
                     max_slices: int = 30) -> Dict[str, Any]:
        
        # 路径规范化，修复 FileNotFoundError 问题
        output_dir = os.path.normpath(output_dir)
        self.log(f"开始分析 - 输出目录: {output_dir}")
        
        data, err = load_json_file(json_path)
        if err: return {'success': False, 'error': err}
        
        group_name = data['session']['nickname']
        messages, _ = extract_messages(data, time_start, time_end)
        user_messages_map = group_by_user(messages)
        display_names = get_user_display_names(messages)
        
        # Social Network
        social_data = calculate_social_network(messages, user_messages_map)
        
        # Filter users
        if users_to_analyze:
            target_users = {u: user_messages_map[u] for u in users_to_analyze if u in user_messages_map}
        else:
            target_users = user_messages_map
            
        profiles = []
        total_users = len(target_users)
        
        self.log(f"共 {total_users} 位用户待分析...")
        
        # 为了更好地控制进度日志，我们可以在这里更细力度地输出
        # 虽然 ThreadPoolExecutor 可以并行，但为了日志清晰，我们可以选择
        # 每位用户内部切片并行，或者多位用户并行。
        # 这里维持原有的并行逻辑，但给 process_slice_task 增加了日志
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            tasks = []
            
            for username, msgs in target_users.items():
                display_name = display_names.get(username, username)
                basic_stats = calculate_basic_stats(msgs, username)
                
                 # Slicing
                slices = slice_messages_by_time(msgs)
                slices, _ = sample_slices(slices, max_slices)
                
                tasks.append({
                    'username': username,
                    'display_name': display_name,
                    'msgs': msgs,
                    'basic_stats': basic_stats,
                    'slices': slices
                })

            for i, task in enumerate(tasks):
                username = task['username']
                display_name = task['display_name']
                basic_stats = task['basic_stats']
                slices = task['slices']
                total_slices = len(slices)
                
                self.log(f"[{i+1}/{total_users}] 正在处理用户: {display_name} ({total_slices} 切片)")
                
                # Parallel Summary
    # ... (existing methods remain) ...

    def _flatten_profile_for_template(self, profile: Dict, group_info: Dict, social_context: Dict) -> Dict[str, Any]:
        """Flatten profile and group info into a dictionary for template formatting (Dynamic)"""
        flat = {}
        
        # 1. Group Info
        flat['group_name'] = group_info.get('group_name', '')
        flat['time_range'] = group_info.get('time_range', 'N/A')
        flat['total_messages'] = group_info.get('total_messages', 0)
        flat['member_count'] = group_info.get('member_count', 0)
        flat['analysis_time'] = group_info.get('analysis_time', '')
        
        # 2. Social Network (Global)
        flat['interaction_matrix'] = social_context.get('interaction_matrix_str', 'N/A')
        flat['core_members'] = social_context.get('core_members_str', 'N/A')
        flat['peripheral_members'] = social_context.get('peripheral_members_str', 'N/A')

        # 3. User Info
        flat['display_name'] = profile.get('display_name', '')
        flat['username'] = profile.get('username', '')
        flat['message_ratio'] = profile.get('message_ratio', 0)
        flat['group_status'] = profile.get('group_status', '')
        
        # 4. Basic Stats & Types
        stats = profile.get('basic_stats', {})
        flat['message_count'] = stats.get('message_count', 0)
        flat['avg_length'] = stats.get('avg_length', 0)
        flat['most_active_date'] = stats.get('most_active_date', 'N/A')
        flat['active_hours'] = format_active_hours(stats.get('active_hours', {}))
        
        msg_types = stats.get('message_types', {})
        total = flat['message_count'] or 1
        
        # Dynamic Message Types (if they change, we handle them; though hardcoded list is usually fine)
        for type_key, type_name in [('text', '文本消息'), ('image', '图片消息'), ('video', '视频消息'), ('voice', '语音消息')]:
            count = msg_types.get(type_name, 0)
            flat[f'{type_key}_count'] = count
            flat[f'{type_key}_ratio'] = round(count / total * 100, 1)
        
        other_count = sum(v for k, v in msg_types.items() if k not in ['文本消息', '图片消息', '视频消息', '语音消息'])
        flat['other_count'] = other_count
        flat['other_ratio'] = round(other_count / total * 100, 1)

        # 5. Semantic Results (Dynamic Flattening)
        # Helper function to recursively flatten dict
        def flatten_recursive(data):
            items = {}
            for k, v in data.items():
                if isinstance(v, dict):
                    # Recursive call
                    items.update(flatten_recursive(v))
                elif isinstance(v, list):
                    # Lists become strings
                    items[k] = ", ".join(map(str, v)) if v else "无"
                else:
                    items[k] = v
            return items

        sem_results = profile.get('semantic_results', {})
        flat.update(flatten_recursive(sem_results))
        
        # Explicit handling for Tags if not caught by recursion (usually it is a list at root of semantic_results)
        if 'tags' in profile:
             flat['user_tags'] = " ".join([f"`{t}`" for t in profile['tags']])
        elif 'tags' in flat:
             # If recursion caught it as comma string, we might want boolean tags style??
             # But for now, recursion's "a, b" is fine. Or let's override for pretty formatting.
             # Re-formatting tags if they exist in flat
             pass 

        return flat

    def run_analysis(self, 
                     json_path: str, 
                     output_dir: str, 
                     users_to_analyze: List[str] = [],
                     time_start: int = 0,
                     time_end: int = 0,
                     max_slices: int = 30,
                     template_path: str = None,
                     prompt_template_path: str = None) -> Dict[str, Any]:
        
        # 路径规范化
        output_dir = os.path.normpath(output_dir)
        self.log(f"开始分析 - 输出目录: {output_dir}")
        
        # 加载输出模板和隐式提示词
        report_template_content = None
        implicit_prompt_content = None
        
        if template_path and os.path.exists(template_path):
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 检查是否存在分割标记
                marker = "## 报告输出模板"
                if marker in content:
                    parts = content.split(marker, 1)
                    implicit_prompt_content = parts[0].strip()
                    report_template_content = parts[1].strip()
                    self.log(f"已加载符合模板: 分离出提示词 ({len(implicit_prompt_content)} chars) 和 报告模板")
                else:
                    report_template_content = content
                    self.log(f"已加载报告模板 (无提示词部分)")
            except Exception as e:
                self.log(f"加载报告模板失败: {e}")

        # 加载显式提示词模板（优先级更高）
        final_system_prompt = None
        if prompt_template_path and os.path.exists(prompt_template_path):
            try:
                with open(prompt_template_path, 'r', encoding='utf-8') as f:
                    final_system_prompt = f.read()
                self.log(f"已加载自定义提示词模板: {prompt_template_path}")
            except Exception as e:
                self.log(f"加载提示词模板失败: {e}")
        
        # 如果没有显式指定，使用隐式提取的
        if not final_system_prompt and implicit_prompt_content:
            final_system_prompt = implicit_prompt_content
            self.log("使用报告模板文件中提取的提示词")
        
        data, err = load_json_file(json_path)
        if err: return {'success': False, 'error': err}
        
        group_name = data['session']['nickname']
        messages, _ = extract_messages(data, time_start, time_end)
        
        # 时间范围计算
        if messages:
             time_range = f"{messages[0]['formattedTime']} 至 {messages[-1]['formattedTime']}"
        else:
             time_range = "无数据"
             
        user_messages_map = group_by_user(messages)
        display_names = get_user_display_names(messages)
        
        # Social Network
        social_data = calculate_social_network(messages, user_messages_map)
        
        # Prepare Social Context Strings for Template
        # 简化版矩阵展示
        matrix_lines = []
        top_interactions = []
        for u1, targets in social_data['interaction_matrix'].items():
            for u2, count in targets.items():
                if count > 5: # 只显示高频互动
                     n1 = display_names.get(u1, u1)
                     n2 = display_names.get(u2, u2)
                     top_interactions.append(f"{n1} -> {n2}: {count}次")
        
        social_context = {
            'interaction_matrix_str': "\n- " + "\n- ".join(top_interactions[:20]) if top_interactions else "无明显高频互动",
            'core_members_str': ", ".join([display_names.get(u, u) for u in social_data['core_members']]),
            'peripheral_members_str': ", ".join([display_names.get(u, u) for u in social_data['peripheral_members']])
        }
        
        # Filter users
        if users_to_analyze:
            target_users = {u: user_messages_map[u] for u in users_to_analyze if u in user_messages_map}
        else:
            target_users = user_messages_map
            
        profiles = []
        total_users = len(target_users)
        
        self.log(f"共 {total_users} 位用户待分析...")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            tasks = []
            
            for username, msgs in target_users.items():
                display_name = display_names.get(username, username)
                basic_stats = calculate_basic_stats(msgs, username)
                
                 # Slicing
                slices = slice_messages_by_time(msgs)
                slices, _ = sample_slices(slices, max_slices)
                
                tasks.append({
                    'username': username,
                    'display_name': display_name,
                    'msgs': msgs,
                    'basic_stats': basic_stats,
                    'slices': slices
                })

            for i, task in enumerate(tasks):
                username = task['username']
                display_name = task['display_name']
                basic_stats = task['basic_stats']
                slices = task['slices']
                total_slices = len(slices)
                
                self.log(f"[{i+1}/{total_users}] 正在处理用户: {display_name} ({total_slices} 切片)")
                
                # Parallel Summary
                user_info = {'username': username, 'display_name': display_name}
                futures = [executor.submit(self.process_slice_task, idx, total_slices, s, user_info, group_name) for idx, s in enumerate(slices)]
                summaries = [f.result() for f in as_completed(futures)]
                summaries.sort(key=lambda x: x['slice_index'])
                
                # Final Analysis (Call API)
                final_res, err = self.analyze_user_final(user_info, summaries, basic_stats, group_name, custom_sys_prompt=final_system_prompt)
                if not final_res:
                    final_res = {'summary': f'Analysis failed: {err}', 'tags': []}
                
                # Build Profile
                user_score = social_data['user_scores'].get(username, {})
                group_status = '活跃成员'
                if username in social_data['core_members']: group_status = '核心成员'
                elif username in social_data['peripheral_members']: group_status = '边缘成员'
                
                profile = {
                    'username': username,
                    'display_name': display_name,
                    'basic_stats': basic_stats,
                    'semantic_results': final_res,
                    'message_ratio': round(len(task['msgs'])/len(messages)*100, 2) if messages else 0,
                    'group_status': group_status,
                    'tags': final_res.get('tags', []),
                    'mentions_given': user_score.get('mentions_given', 0),
                    'mentions_received': user_score.get('mentions_received', 0)
                }
                profiles.append(profile)
                
                # Save Individual Report
                group_info = {
                    'group_name': group_name,
                    'time_range': time_range,
                    'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'total_messages': len(messages),
                    'member_count': len(user_messages_map)
                }
                
                try:
                    self.save_single_report(profile, group_info, output_dir, report_template_content, social_context)
                    self.log(f"[{i+1}/{total_users}] 用户报告保存完毕: {display_name}")
                except Exception as e:
                    self.log(f"[{i+1}/{total_users}] 保存报告失败: {e}")
                
        return {'success': True, 'profiles': profiles, 'group_name': group_name}

    def generate_single_user_report(self, profile: Dict, group_info: Dict) -> str:
        # Backward compatibility / fallback method
        return self._generate_report_content(profile, group_info, None, {})

    def _generate_report_content(self, profile: Dict, group_info: Dict, template_content: Optional[str], social_context: Dict) -> str:
        if template_content:
            try:
                flat_data = self._flatten_profile_for_template(profile, group_info, social_context)
                
                # Smart Escaping Algorithm:
                # The template might contain literal JSON (braces) which confuse str.format.
                # 1. Escape ALL braces: { -> {{, } -> }}
                # 2. Unescape only the known valid placeholders: {{key}} -> {key}
                
                escaped_content = template_content.replace('{', '{{').replace('}', '}}')
                
                for key in flat_data.keys():
                    # We look for {{key}} and revert it to {key}
                    # This assumes no complex format specs like {key:.2f} are used in the user template.
                    # If they are, this simple replacement won't catch them, but it fixes the "Invalid format specifier" crash.
                    escaped_content = escaped_content.replace(f'{{{{{key}}}}}', f'{{{key}}}')
                
                return escaped_content.format_map(flat_data)
            except Exception as e:
                self.log(f"[Template Error] {e}")
                return f"Template Rendering Error: {e}\n\n" + self.generate_single_user_report(profile, group_info)
        
        # Default Template Logic (Original)
        """生成详细的Markdown报告，符合analysis_template.md"""
        report = []
        p = profile
        s = p['semantic_results']
        stats = p['basic_stats']
        
        # 补全可能缺失的字段
        emo = s.get('emotion_analysis', {})
        style = s.get('communication_style', {})
        topics = s.get('topic_interests', {})
        role = s.get('role_analysis', {})
        prof = s.get('professional_inference', {})
        
        report.append(f"### 群整体信息")
        report.append(f"- **群名称**: {group_info['group_name']}")
        report.append(f"- **总消息数**: {group_info['total_messages']}")
        report.append(f"- **成员数**: {group_info['member_count']}")
        report.append(f"- **分析生成时间**: {group_info['analysis_time']}")
        report.append("---\n")
        
        report.append(f"### 成员画像")
        report.append(f"#### 👤 {p['display_name']}（{p['username']}）")
        
        report.append(f"##### 📊 基础统计")
        report.append("| 指标 | 数值 |")
        report.append("|------|------|")
        report.append(f"| 发言总数 | {stats['message_count']} 条 |")
        report.append(f"| 平均消息长度 | {stats['avg_length']} 字 |")
        report.append(f"| 消息占比 | {p['message_ratio']}% |")
        report.append(f"| 活跃时段 | {format_active_hours(stats['active_hours'])} |")
        report.append(f"| 最活跃日期 | {stats['most_active_date']} |")
        report.append(f"| 群内地位 | {p['group_status']} |")
        
        report.append(f"\n##### 📱 消息类型分布")
        report.append("| 类型 | 数量 |")
        report.append("|------|------|")
        for k, v in stats.get('message_types', {}).items():
            report.append(f"| {k} | {v} |")

        report.append(f"\n##### 🎭 情绪与沟通风格")
        report.append(f"- **情绪倾向**: 正向 {emo.get('positive_ratio', 50)}% / 负向 {emo.get('negative_ratio', 50)}%")
        report.append(f"- **情绪波动**: {emo.get('volatility', 'N/A')}")
        report.append(f"- **语气特征**: {emo.get('dominant_tone', 'N/A')}")
        report.append(f"- **语言风格**: {style.get('language_pattern', 'N/A')}")
        report.append(f"- **表情偏好**: {style.get('emoji_usage', 'N/A')}")
        
        report.append(f"\n##### 💡 兴趣与话题")
        m_topics = topics.get('main_topics', [])
        keywords = topics.get('keywords', [])
        report.append(f"- **主要话题**: {', '.join(m_topics) if m_topics else 'N/A'}")
        report.append(f"- **典型关键词**: {', '.join(keywords) if keywords else 'N/A'}")
        report.append(f"- **兴趣描述**: {topics.get('interest_description', 'N/A')}")
        
        report.append(f"\n##### 🎯 角色定位")
        report.append(f"- **群内角色**: {role.get('group_role', 'N/A')}")
        report.append(f"- **主动程度**: {role.get('initiative_level', 'N/A')}")
        report.append(f"- **社交行为**: {role.get('social_behavior', 'N/A')}")
        
        report.append(f"\n##### 🔧 专业领域")
        fields = prof.get('possible_fields', [])
        report.append(f"- **可能领域**: {', '.join(fields) if fields else 'N/A'}")
        report.append(f"- **专业指标**: {prof.get('expertise_indicators', 'N/A')}")
        report.append(f"- **推断置信度**: {prof.get('confidence', 'N/A')}")
        
        report.append(f"\n##### 🏷️ 用户标签")
        tags = p.get('tags', [])
        report.append(" ".join([f"`{t}`" for t in tags]) if tags else "无")
        
        report.append(f"\n##### 📝 综合评价")
        report.append(f"{s.get('summary', '无')}")
        
        return "\n".join(report)

    def save_single_report(self, profile, group_info, output_dir, template_content=None, social_context={}):
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        filename = f"{get_safe_filename(group_info['group_name'])}_{get_safe_filename(profile['display_name'])}.md"
        path = os.path.join(output_dir, filename)
        
        content = self._generate_report_content(profile, group_info, template_content, social_context)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

if __name__ == "__main__":
    print("This is a library module. Please use gui_app.py")
