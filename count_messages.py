#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户消息数量统计脚本
分析JSON文件中各用户的有效发言数量，按数量从大到小排序输出
"""

import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Any

def parse_date(date_str: str) -> Optional[float]:
    """解析日期字符串为时间戳"""
    if not date_str:
        return None
    try:
        # 支持多种格式
        for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"]:
            try:
                return datetime.strptime(date_str, fmt).timestamp()
            except ValueError:
                continue
        return None
    except Exception:
        return None

def get_user_statistics(json_path: str, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    """
    获取用户统计信息 API
    
    Args:
        json_path: JSON文件路径
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        
    Returns:
        Dict: 包含群信息和用户统计列表
    """
    start_ts = parse_date(start_date)
    end_ts = parse_date(end_date)
    # 如果是日期（不含时间），结束日期通常指当天的结束，所以加一天减1秒，或者不做处理视具体需求
    # 这里简单处理：如果只给了日期，end_ts 默认为该日 00:00:00，如果想要包含当天，建议外部传入次日或包含时间
    # 为了GUI方便，假设传入的是覆盖全天的范围
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return {'error': '文件未找到', 'success': False}
    except Exception as e:
        return {'error': str(e), 'success': False}

    session = data.get('session', {})
    group_name = session.get('nickname', '未知群')
    
    messages = data.get('messages', [])
    user_messages = defaultdict(lambda: {'count': 0, 'text_count': 0, 'display_name': '', 'username': ''})
    system_count = 0
    valid_count = 0
    
    for msg in messages:
        # 时间过滤
        msg_time = msg.get('createTime', 0)
        if start_ts and msg_time < start_ts:
            continue
        if end_ts and msg_time > end_ts:
            continue
            
        # 过滤系统消息
        if msg.get('type') == '系统消息':
            system_count += 1
            continue
        
        username = msg.get('senderUsername', '')
        display_name = msg.get('senderDisplayName', '')
        msg_type = msg.get('type', '')
        
        if username:
            user_messages[username]['username'] = username
            user_messages[username]['count'] += 1
            # 优先使用非空的 display_name
            if display_name:
                user_messages[username]['display_name'] = display_name
            elif not user_messages[username]['display_name']:
                user_messages[username]['display_name'] = username
                
            # 单独统计文本消息
            if msg_type == '文本消息':
                user_messages[username]['text_count'] += 1
            valid_count += 1

    # 排序
    sorted_users = sorted(
        user_messages.values(), 
        key=lambda x: x['count'], 
        reverse=True
    )
    
    return {
        'success': True,
        'group_name': group_name,
        'total_count': session.get('messageCount', 0), # 原始记录总数
        'filtered_count': valid_count,                 # 筛选后的有效消息数
        'system_count': system_count,
        'user_stats': sorted_users
    }

def analyze_user_messages(json_path: str):
    """
    CLI 入口
    """
    print(f"Loading file: {json_path}")
    result = get_user_statistics(json_path)
    
    if not result.get('success'):
        print(f"Error: {result.get('error')}")
        return

    users = result['user_stats']
    valid_count = result['filtered_count']
    
    print(f"群名: {result['group_name']}")
    print(f"有效消息数: {valid_count} (系统消息: {result['system_count']})")
    print(f"活跃用户数: {len(users)}")
    print(f"{'='*70}\n")
    
    print(f"{'排名':<6}{'显示名':<20}{'用户名':<25}{'消息数':<10}{'文本数':<10}{'占比'}")
    print("-" * 80)
    
    for i, stats in enumerate(users, 1):
        display_name = stats['display_name']
        username = stats['username']
        count = stats['count']
        text_count = stats['text_count']
        ratio = count / valid_count * 100 if valid_count > 0 else 0
        
        # 截断过长的名字
        d_name_print = display_name[:16] + '..' if len(display_name) > 18 else display_name
        u_name_print = username[:21] + '..' if len(username) > 23 else username
        
        print(f"{i:<6}{d_name_print:<20}{u_name_print:<25}{count:<10}{text_count:<10}{ratio:.2f}%")

    # 输出建议
    print(f"\n{'='*70}")
    print("建议分析的用户（消息数 >= 50）:")
    recommended = [u['username'] for u in users if u['count'] >= 50]
    print(json.dumps(recommended, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    default_file = "FEND毕业生.json"
    target = sys.argv[1] if len(sys.argv) > 1 else default_file
    analyze_user_messages(target)

