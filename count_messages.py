#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户消息数量统计脚本
分析JSON文件中各用户的有效发言数量，按数量从大到小排序输出
"""

import json
import sys
from collections import defaultdict

def analyze_user_messages(json_path: str):
    """
    分析用户消息数量
    
    Args:
        json_path: JSON文件路径
    """
    print(f"加载文件: {json_path}")
    
    # 加载JSON
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 获取群信息
    session = data.get('session', {})
    group_name = session.get('nickname', '未知群')
    total_count = session.get('messageCount', 0)
    
    print(f"群名: {group_name}")
    print(f"记录总消息数: {total_count}")
    
    # 统计用户消息
    messages = data.get('messages', [])
    user_messages = defaultdict(lambda: {'count': 0, 'text_count': 0, 'display_name': ''})
    system_count = 0
    
    for msg in messages:
        # 过滤系统消息
        if msg.get('type') == '系统消息':
            system_count += 1
            continue
        
        username = msg.get('senderUsername', '')
        display_name = msg.get('senderDisplayName', '')
        msg_type = msg.get('type', '')
        
        if username:
            user_messages[username]['count'] += 1
            user_messages[username]['display_name'] = display_name
            
            # 单独统计文本消息
            if msg_type == '文本消息':
                user_messages[username]['text_count'] += 1
    
    # 按消息数量排序
    sorted_users = sorted(
        user_messages.items(), 
        key=lambda x: x[1]['count'], 
        reverse=True
    )
    
    # 输出统计结果
    valid_count = sum(u[1]['count'] for u in sorted_users)
    
    print(f"\n{'='*70}")
    print(f"有效消息数: {valid_count} (系统消息: {system_count})")
    print(f"活跃用户数: {len(sorted_users)}")
    print(f"{'='*70}\n")
    
    print(f"{'排名':<6}{'显示名':<20}{'用户名':<25}{'消息数':<10}{'文本数':<10}{'占比'}")
    print("-" * 80)
    
    for i, (username, stats) in enumerate(sorted_users, 1):
        display_name = stats['display_name'] or username
        count = stats['count']
        text_count = stats['text_count']
        ratio = count / valid_count * 100 if valid_count > 0 else 0
        
        # 截断过长的名字
        if len(display_name) > 18:
            display_name = display_name[:16] + '..'
        if len(username) > 23:
            username = username[:21] + '..'
        
        print(f"{i:<6}{display_name:<20}{username:<25}{count:<10}{text_count:<10}{ratio:.2f}%")
    
    # 输出消息数分布
    print(f"\n{'='*70}")
    print("消息数分布:")
    print("-" * 40)
    
    brackets = [
        (1000, "1000+"),
        (500, "500-999"),
        (200, "200-499"),
        (100, "100-199"),
        (50, "50-99"),
        (20, "20-49"),
        (10, "10-19"),
        (1, "1-9"),
        (0, "0")
    ]
    
    for threshold, label in brackets:
        users_in_bracket = [u for u in sorted_users if u[1]['count'] >= threshold]
        if threshold > 0:
            users_in_bracket = [u for u in sorted_users if u[1]['count'] >= threshold and u[1]['count'] < brackets[brackets.index((threshold, label)) - 1][0]] if brackets.index((threshold, label)) > 0 else [u for u in sorted_users if u[1]['count'] >= threshold]
        
        # 重新计算
        if threshold == 1000:
            users_in_bracket = [u for u in sorted_users if u[1]['count'] >= 1000]
        elif threshold == 500:
            users_in_bracket = [u for u in sorted_users if 500 <= u[1]['count'] < 1000]
        elif threshold == 200:
            users_in_bracket = [u for u in sorted_users if 200 <= u[1]['count'] < 500]
        elif threshold == 100:
            users_in_bracket = [u for u in sorted_users if 100 <= u[1]['count'] < 200]
        elif threshold == 50:
            users_in_bracket = [u for u in sorted_users if 50 <= u[1]['count'] < 100]
        elif threshold == 20:
            users_in_bracket = [u for u in sorted_users if 20 <= u[1]['count'] < 50]
        elif threshold == 10:
            users_in_bracket = [u for u in sorted_users if 10 <= u[1]['count'] < 20]
        elif threshold == 1:
            users_in_bracket = [u for u in sorted_users if 1 <= u[1]['count'] < 10]
        else:
            users_in_bracket = [u for u in sorted_users if u[1]['count'] == 0]
        
        if users_in_bracket:
            print(f"  {label:>10} 条: {len(users_in_bracket)} 人")
    
    # 建议分析的用户
    print(f"\n{'='*70}")
    print("建议分析的用户（消息数 >= 50）:")
    print("-" * 40)
    
    recommended = [u for u in sorted_users if u[1]['count'] >= 50]
    print(f"共 {len(recommended)} 人，占总人数的 {len(recommended)/len(sorted_users)*100:.1f}%")
    print(f"这些用户的消息占比: {sum(u[1]['count'] for u in recommended)/valid_count*100:.1f}%")
    
    if recommended:
        print("\n用户名列表（可复制用于配置）:")
        usernames = [u[0] for u in recommended]
        print(json.dumps(usernames, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # 默认分析的文件
    default_file = "FEND毕业生.json"
    
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    else:
        json_path = default_file
    
    analyze_user_messages(json_path)

