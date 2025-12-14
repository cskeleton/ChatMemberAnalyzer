import type { TimeSlice, SemanticAnalysisResult, UserProfile, SliceAnalysisResult } from './types';
import { formatActiveHours } from './analyzer';

/**
 * AI 配置接口
 * 与 Python GUI (wizard.py) 保持一致的设计：
 * - slicePromptTemplate: 切片分析提示词（可选）
 * - promptTemplate: 汇总分析提示词（对应 Python 的 prompt_template_path）
 * - reportTemplate: 报告输出模板（对应 Python 的 template_path，包含占位符）
 */
export interface AIConfig {
    apiKey: string;
    apiUrl: string;
    model: string;
    // 切片分析提示词（用于分段摘要）
    slicePromptTemplate?: string;
    // 汇总分析提示词（对应 Python GUI 的 "提示词模板"）
    promptTemplate?: string;
    // 报告输出模板（对应 Python GUI 的 "报告模板"，包含 {analysis_time} 等占位符）
    reportTemplate?: string;
}

export const DEFAULT_CONFIG: AIConfig = {
    apiKey: '',
    apiUrl: '/v1/chat/completions', // Use relative path by default to leverage proxy
    model: 'gpt-3.5-turbo',
    slicePromptTemplate: '',
    promptTemplate: '',
    reportTemplate: ''
};

export async function callAI(
    config: AIConfig,
    systemPrompt: string,
    userMessage: string
): Promise<any> {
    if (!config.apiKey) throw new Error("API Key is missing");

    // Auto-rewrite URL to use local proxy if it points to the problematic domain
    let endpoint = config.apiUrl;
    if (endpoint.includes('juya.owl.ci') && !endpoint.startsWith('/')) {
        endpoint = '/v1/chat/completions';
        console.log("Using local proxy for:", config.apiUrl);
    }

    console.log("AI Request Endpoint:", endpoint);
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${config.apiKey}`
    };

    const body = {
        model: config.model,
        messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: userMessage }
        ],
        temperature: 0.3,
        max_tokens: 2000
    };

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers,
            body: JSON.stringify(body)
        });

        console.log(`AI Response Status: ${response.status} ${response.statusText}`);

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`API Error ${response.status}: ${errText}`);
        }

        const text = await response.text();
        console.log("Raw AI Response preview:", text.substring(0, 100));

        let responseData;
        try {
            responseData = JSON.parse(text);
        } catch (e) {
            console.error("API returned non-JSON response. Full text:", text);
            throw new Error(`API returned invalid JSON (Status ${response.status}): ${text.substring(0, 100)}...`);
        }

        const content = responseData.choices?.[0]?.message?.content;
        if (!content) {
            console.error("Unexpected API response structure:", responseData);
            throw new Error("API response missing choices/message/content");
        }

        const textToParse = content; // use content field not raw response text for final parse
        console.log("AI Content:", textToParse.substring(0, 100));

        // Regex to extract JSON block including markdown fences or just the object
        const jsonMatch = textToParse.match(/```json\n?([\s\S]*?)\n?```/) ||
            textToParse.match(/```\n?([\s\S]*?)\n?```/) ||
            textToParse.match(/(\{[\s\S]*\})/); // Greedy match for first { to last }

        let jsonStr = "";
        if (jsonMatch) {
            jsonStr = jsonMatch[1] || jsonMatch[0];
        } else {
            // Fallback
            jsonStr = textToParse;
        }

        jsonStr = jsonStr.trim();

        // Extra cleanup: remove any leading text before the first {
        const firstOpenBrace = jsonStr.indexOf('{');
        const lastCloseBrace = jsonStr.lastIndexOf('}');
        if (firstOpenBrace !== -1 && lastCloseBrace !== -1 && lastCloseBrace > firstOpenBrace) {
            jsonStr = jsonStr.substring(firstOpenBrace, lastCloseBrace + 1);
        }

        let finalData;
        try {
            finalData = JSON.parse(jsonStr);
            // 验证解析后的数据结构是否合理（至少应该是一个对象）
            if (typeof finalData !== 'object' || finalData === null) {
                throw new Error("Parsed JSON is not an object");
            }
            return finalData;
        } catch (e) {
            // Attempt to auto-repair common Chinese model JSON errors
            try {
                let repaired = jsonStr.replace(/[""]/g, '"'); // Replace Chinese quotes
                repaired = repaired.replace(/"\s*、\s*"/g, '","'); // Replace Chinese comma separators between strings
                // 修复常见的JSON错误：缺少逗号、多余的逗号等
                repaired = repaired.replace(/,\s*}/g, '}'); // Remove trailing commas before }
                repaired = repaired.replace(/,\s*]/g, ']'); // Remove trailing commas before ]

                console.warn("JSON Parse failed, attempting repair. Repaired preview:", repaired.substring(0, 100));
                finalData = JSON.parse(repaired);
                
                // 再次验证修复后的数据
                if (typeof finalData !== 'object' || finalData === null) {
                    throw new Error("Repaired JSON is still not an object");
                }
                
                return finalData;
            } catch (repairErr) {
                console.error("Failed to parse AI response after repair attempts.");
                console.error("JSON string length:", jsonStr.length);
                console.error("JSON string preview (first 200 chars):", jsonStr.substring(0, 200));
                console.error("JSON string preview (last 200 chars):", jsonStr.substring(Math.max(0, jsonStr.length - 200)));
                console.error("Original API response text length:", text.length);
                console.error("Original API response preview:", text.substring(0, 200));
                console.error("System Prompt preview:", systemPrompt.substring(0, 200));
                console.error("Parse error:", e);
                console.error("Repair error:", repairErr);
                
                // 提供更详细的错误信息
                const errorMsg = `无法解析AI返回的JSON格式。这可能是因为：
1. AI返回的格式不符合预期的JSON结构
2. 系统提示模板或报告模板中包含了无效的JSON结构
3. AI模型输出包含了额外的文本或格式问题

原始输出预览: ${jsonStr.substring(0, 100)}...
如果这是汇总分析阶段，请检查分段分析的结果是否正确。`;
                
                throw new Error(errorMsg);
            }
        }
    } catch (e: any) {
        console.error("AI Request Error details:", e);
        throw new Error(`AI Request Failed: ${e.message}`);
    }
}

export async function analyzeSlice(
    config: AIConfig,
    slice: TimeSlice,
    userDisplayName: string,
    username: string
): Promise<SliceAnalysisResult> {
    const defaultSysPrompt = `你是一位专业的社交行为分析师。请对微信群聊记录进行摘要总结。
    请以JSON格式返回摘要结果：
    {
      "time_range": "时间范围",
      "message_count": 消息数量,
      "emotion_summary": {
        "overall_tone": "整体情绪基调",
        "emotion_keywords": ["关键词"]
      },
      "topics": ["话题"],
      "brief_summary": "50字摘要"
    }`;

    // 使用切片分析专用提示词
    let sysPrompt = defaultSysPrompt;
    
    if (config.slicePromptTemplate) {
        // 直接使用切片分析提示词
        sysPrompt = config.slicePromptTemplate;
        console.log("使用自定义切片分析提示词");
    }

    const messagesText = slice.messages.slice(0, 200).map(m => {
        const t = m.formattedTime;
        const c = m.content;
        return m.type === '文本消息' ? `[${t}] ${c}` : `[${t}] [${m.type}]`;
    }).join('\n');

    const userMsg = `请为以下用户生成摘要：
    用户: ${userDisplayName} (${username})
    时间范围: ${slice.timeStart} 至 ${slice.timeEnd}
    消息数: ${slice.messageCount}
    聊天记录:
    ${messagesText}`;

    return callAI(config, sysPrompt, userMsg);
}

/**
 * 从报告模板内容中提取 AI 系统提示词（隐式提示词）
 * 与 analyze_chat.py 的逻辑保持一致：使用 "## 报告输出模板" 标记分离
 * 标记之前的部分是 AI 系统提示词，标记之后的部分是输出报告格式模板
 */
function extractPromptFromReportTemplate(templateContent: string): string | null {
    const marker = "## 报告输出模板";
    
    if (templateContent.includes(marker)) {
        // 分离提示词和报告模板
        const parts = templateContent.split(marker);
        const promptPart = parts[0].trim();
        
        if (promptPart) {
            console.log(`从报告模板分离出隐式提示词: ${promptPart.length} 字符`);
            return promptPart;
        }
    }
    
    return null;
}

/**
 * 检测内容是否为输出模板（包含占位符）
 */
function isOutputTemplate(content: string): boolean {
    const outputTemplatePlaceholders = [
        '{analysis_time}', '{display_name}', '{username}', '{group_name}',
        '{time_range}', '{total_messages}', '{member_count}', '{message_count}',
        '{avg_length}', '{message_ratio}', '{active_hours}', '{text_count}',
        '{image_count}', '{video_count}', '{voice_count}', '{other_count}'
    ];
    
    return outputTemplatePlaceholders.some(p => content.includes(p));
}

export async function analyzeUserFinal(
    config: AIConfig,
    userProfile: UserProfile,
    sliceSummaries: SliceAnalysisResult[]
): Promise<SemanticAnalysisResult> {
    const defaultSysPrompt = `你是一位专业的社交行为分析师。请基于用户在不同时间段的聊天摘要，生成综合用户画像。
    请以JSON格式返回结果：
    {
      "emotion_analysis": {
        "positive_ratio": 50,
        "negative_ratio": 50,
        "volatility": "中",
        "dominant_tone": "描述"
      },
      "communication_style": {
        "style_tags": ["标签"],
        "language_pattern": "描述",
        "emoji_usage": "描述"
      },
      "topic_interests": {
        "main_topics": ["话题"],
        "keywords": ["关键词"],
        "interest_description": "描述"
      },
      "role_analysis": {
        "group_role": "角色",
        "initiative_level": "主动/被动",
        "social_behavior": "描述"
      },
      "professional_inference": {
        "possible_fields": ["领域"],
        "expertise_indicators": "描述",
        "confidence": "中"
      },
      "summary": "100字综合评价",
      "tags": ["标签"]
    }`;

    /**
     * 提示词优先级（与 analyze_chat.py 的 run_analysis 保持一致）：
     * 1. promptTemplate（显式提示词模板，对应 Python 的 prompt_template_path）- 最高优先级
     * 2. 从 reportTemplate 提取的隐式提示词（如果包含 "## 报告输出模板" 标记）
     * 3. 默认提示词
     */
    let sysPrompt = defaultSysPrompt;
    let promptSource = "默认";
    
    // 优先级 2：从报告模板提取隐式提示词
    if (config.reportTemplate) {
        const implicitPrompt = extractPromptFromReportTemplate(config.reportTemplate);
        if (implicitPrompt) {
            sysPrompt = implicitPrompt;
            promptSource = "报告模板(隐式)";
            console.log("使用从报告模板提取的隐式提示词");
        } else if (isOutputTemplate(config.reportTemplate)) {
            // 纯输出模板（如 test_template.md），不包含提示词部分
            console.log("报告模板为纯输出格式模板，不包含 AI 提示词");
        }
    }
    
    // 优先级 1：显式提示词模板（最高优先级，会覆盖隐式提示词）
    if (config.promptTemplate) {
        // 检查是否为有效的提示词（不应包含输出模板占位符）
        if (isOutputTemplate(config.promptTemplate)) {
            console.warn("警告: 提示词模板中包含输出格式占位符，这可能是配置错误");
            console.warn("提示: 请将输出格式模板配置到'报告模板'字段，将 AI 提示词配置到'提示词模板'字段");
        } else {
            sysPrompt = config.promptTemplate;
            promptSource = "提示词模板(显式)";
            console.log("使用显式提示词模板进行汇总分析");
        }
    }
    
    console.log(`汇总分析使用的提示词来源: ${promptSource}`);

    // 容错处理：检查每个摘要是否有brief_summary字段，如果没有则使用备用方案
    const summaryText = sliceSummaries.map((s, i) => {
        let summaryContent = '';
        if (s.brief_summary) {
            summaryContent = s.brief_summary;
        } else if (s.emotion_summary?.overall_tone) {
            // 备用方案1：使用情绪摘要
            summaryContent = `情绪基调: ${s.emotion_summary.overall_tone}`;
            if (s.topics && s.topics.length > 0) {
                summaryContent += `, 话题: ${s.topics.join(', ')}`;
            }
        } else if (s.topics && s.topics.length > 0) {
            // 备用方案2：使用话题列表
            summaryContent = `主要话题: ${s.topics.join(', ')}`;
        } else {
            // 备用方案3：使用时间范围和消息数
            summaryContent = `时间段: ${s.time_range || '未知'}, 消息数: ${s.message_count || 0}`;
        }
        return `--- Segment ${i + 1} ---\nSummary: ${summaryContent}`;
    }).join('\n');

    // 验证是否有有效的摘要数据
    if (sliceSummaries.length === 0) {
        console.warn("警告: 没有有效的分段摘要数据，汇总分析可能不准确");
    }

    const userMsg = `用户: ${userProfile.displayName}
    统计:
    - 发言: ${userProfile.basicStats.messageCount}
    - 平均长度: ${userProfile.basicStats.avgLength}
    
    各时段摘要:
    ${summaryText}`;

    console.log("汇总分析请求 - 分段摘要数量:", sliceSummaries.length);
    console.log("汇总分析请求 - 摘要内容预览:", summaryText.substring(0, 200));

    try {
        const result = await callAI(config, sysPrompt, userMsg);
        console.log("汇总分析完成 - 返回结果结构:", Object.keys(result || {}));
        return result;
    } catch (e: any) {
        console.error("汇总分析失败 - 错误详情:", e);
        console.error("汇总分析失败 - 使用的系统提示:", sysPrompt.substring(0, 200));
        console.error("汇总分析失败 - 分段摘要数据:", sliceSummaries);
        throw new Error(`汇总分析失败: ${e.message}`);
    }
}

// ============================================================
// 报告生成函数（与 analyze_chat.py 的 _generate_report_content 对齐）
// ============================================================

interface ReportContext {
    member: UserProfile;
    semanticResult: SemanticAnalysisResult;
    groupName: string;
    timeRange?: string;
    totalMessages?: number;
    memberCount?: number;
}

/**
 * 将分析结果展平为键值对，用于模板变量替换
 * 与 analyze_chat.py 的 _flatten_profile_for_template 对齐
 */
function flattenDataForTemplate(context: ReportContext): Record<string, string | number> {
    const { member, semanticResult, groupName, timeRange, totalMessages, memberCount } = context;
    const stats = member.basicStats;
    const flat: Record<string, string | number> = {};
    
    // 1. 群组信息
    flat['group_name'] = groupName || '';
    flat['time_range'] = timeRange || 'N/A';
    flat['total_messages'] = totalMessages || 0;
    flat['member_count'] = memberCount || 0;
    flat['analysis_time'] = new Date().toLocaleString();
    
    // 2. 用户基本信息
    flat['display_name'] = member.displayName || '';
    flat['username'] = member.username || '';
    flat['message_ratio'] = member.messageRatio || 0;
    flat['group_status'] = member.groupStatus || '';
    
    // 3. 基础统计
    flat['message_count'] = stats.messageCount || 0;
    flat['avg_length'] = stats.avgLength || 0;
    flat['most_active_date'] = stats.mostActiveDate || 'N/A';
    flat['active_hours'] = formatActiveHours(stats.activeHours);
    
    // 4. 消息类型统计
    const msgTypes = stats.messageTypes || {};
    const total = stats.messageCount || 1;
    
    const typeMapping: [string, string][] = [
        ['text', '文本消息'],
        ['image', '图片消息'],
        ['video', '视频消息'],
        ['voice', '语音消息']
    ];
    
    for (const [key, typeName] of typeMapping) {
        const count = msgTypes[typeName] || 0;
        flat[`${key}_count`] = count;
        flat[`${key}_ratio`] = Math.round(count / total * 1000) / 10;
    }
    
    // 其他类型
    const knownTypes = typeMapping.map(t => t[1]);
    const otherCount = Object.entries(msgTypes)
        .filter(([k]) => !knownTypes.includes(k))
        .reduce((sum, [, v]) => sum + v, 0);
    flat['other_count'] = otherCount;
    flat['other_ratio'] = Math.round(otherCount / total * 1000) / 10;
    
    // 5. 语义分析结果（递归展平）
    function flattenRecursive(data: Record<string, any>, prefix = ''): void {
        for (const [k, v] of Object.entries(data)) {
            if (v === null || v === undefined) {
                flat[k] = '无';
            } else if (typeof v === 'object' && !Array.isArray(v)) {
                flattenRecursive(v, prefix);
            } else if (Array.isArray(v)) {
                flat[k] = v.length > 0 ? v.join(', ') : '无';
            } else {
                flat[k] = String(v);
            }
        }
    }
    
    if (semanticResult) {
        flattenRecursive(semanticResult);
    }
    
    // 6. 用户标签格式化（覆盖递归展平的结果）
    // 智能生成标签：如果 AI 未返回标签，从其他字段提取
    let userTags: string[] = [];
    
    if (semanticResult?.tags && semanticResult.tags.length > 0) {
        userTags = semanticResult.tags;
    } else {
        // 从其他分析字段自动生成标签
        const generatedTags: string[] = [];
        
        // 从沟通风格提取标签
        if (semanticResult?.communication_style?.style_tags && Array.isArray(semanticResult.communication_style.style_tags)) {
            generatedTags.push(...semanticResult.communication_style.style_tags.slice(0, 2));
        }
        
        // 从群组角色提取标签
        if (semanticResult?.role_analysis?.group_role && semanticResult.role_analysis.group_role !== '无') {
            generatedTags.push(semanticResult.role_analysis.group_role);
        }
        
        // 从情感基调提取标签
        if (semanticResult?.emotion_analysis?.dominant_tone && semanticResult.emotion_analysis.dominant_tone !== '无') {
            const tone = semanticResult.emotion_analysis.dominant_tone;
            // 提取简短的情感关键词（取前10个字符）
            generatedTags.push(tone.slice(0, 10));
        }
        
        // 从主要话题提取标签（最多2个）
        if (semanticResult?.topic_interests?.main_topics && Array.isArray(semanticResult.topic_interests.main_topics)) {
            generatedTags.push(...semanticResult.topic_interests.main_topics.slice(0, 2));
        }
        
        // 如果还是没有标签，使用基于群组状态的默认标签
        if (generatedTags.length === 0) {
            const groupStatus = member.groupStatus || '成员';
            generatedTags.push(groupStatus);
        }
        
        // 去重并限制数量（最多5个标签）
        userTags = [...new Set(generatedTags)].filter(tag => tag && tag.trim()).slice(0, 5);
    }
    
    // 格式化标签
    if (userTags.length > 0) {
        flat['user_tags'] = userTags.map(t => `\`${t}\``).join(' ');
    } else {
        flat['user_tags'] = '无';
    }
    
    // 7. 确保所有值都是字符串或数字（用于模板替换）
    const result: Record<string, string | number> = {};
    for (const [key, value] of Object.entries(flat)) {
        if (typeof value === 'number') {
            result[key] = value;
        } else if (value === null || value === undefined) {
            result[key] = '无';
        } else {
            result[key] = String(value);
        }
    }
    
    // 调试：输出所有可用的模板变量（按字母顺序）
    const sortedKeys = Object.keys(result).sort();
    console.log("可用的模板变量总数:", sortedKeys.length);
    console.log("模板变量列表:", sortedKeys);
    
    // 输出一些关键变量的值用于调试
    const debugVars = [
        'analysis_time', 'display_name', 'username', 'group_name',
        'summary', 'positive_ratio', 'negative_ratio', 'main_topics',
        'financial_indicators', 'fconfidence', 'user_tags'
    ];
    const debugValues: Record<string, any> = {};
    for (const key of debugVars) {
        if (key in result) {
            debugValues[key] = result[key];
        }
    }
    console.log("关键模板变量值:", debugValues);
    
    return result;
}

/**
 * 从报告模板中提取输出格式部分
 * 如果模板包含 "## 报告输出模板" 标记，返回标记之后的部分
 */
function extractOutputTemplateFromReport(templateContent: string): string {
    const marker = "## 报告输出模板";
    
    if (templateContent.includes(marker)) {
        const parts = templateContent.split(marker);
        if (parts.length > 1) {
            return parts[1].trim();
        }
    }
    
    // 如果没有标记，检查是否为纯输出模板（包含占位符）
    if (isOutputTemplate(templateContent)) {
        return templateContent;
    }
    
    return '';
}

/**
 * 使用模板生成报告
 * 与 analyze_chat.py 的 _generate_report_content 对齐
 */
export function generateReportFromTemplate(
    context: ReportContext,
    reportTemplate?: string
): string {
    const flatData = flattenDataForTemplate(context);
    
    // 如果有报告模板，尝试使用它
    if (reportTemplate) {
        const outputTemplate = extractOutputTemplateFromReport(reportTemplate);
        
        if (outputTemplate) {
            try {
                // 改进的模板替换逻辑：
                // 1. 先转义所有大括号（避免替换时误替换）
                let escaped = outputTemplate.replace(/\{/g, '{{').replace(/\}/g, '}}');
                
                // 2. 只还原已知的占位符（从 flatData 中获取）
                for (const key of Object.keys(flatData)) {
                    const placeholder = `{{${key}}}`;
                    const replacement = `{${key}}`;
                    // 使用全局替换，确保所有出现的地方都被替换
                    escaped = escaped.replace(new RegExp(placeholder.replace(/[{}]/g, '\\$&'), 'g'), replacement);
                }
                
                // 3. 执行变量替换
                let result = escaped;
                for (const [key, value] of Object.entries(flatData)) {
                    const placeholder = `{${key}}`;
                    const valueStr = String(value);
                    // 使用全局替换
                    result = result.replace(new RegExp(placeholder.replace(/[{}]/g, '\\$&'), 'g'), valueStr);
                }
                
                // 4. 清理未替换的双大括号（恢复为单大括号，用于代码块等）
                result = result.replace(/\{\{/g, '{').replace(/\}\}/g, '}');
                
                // 5. 检查是否有未替换的占位符
                const unmatchedPlaceholders = result.match(/\{[a-z_][a-z0-9_]*\}/gi);
                if (unmatchedPlaceholders && unmatchedPlaceholders.length > 0) {
                    const uniqueUnmatched = [...new Set(unmatchedPlaceholders)];
                    console.warn("未匹配的模板变量:", uniqueUnmatched);
                    console.warn("提示: 这些变量可能不在数据中，或者变量名拼写错误");
                }
                
                // 6. 清理表格中的空值（将 "无" 或空字符串替换为合适的占位符）
                // 确保表格格式正确（移除可能导致表格格式错误的空行）
                result = result.replace(/\|\s*无\s*\|/g, '| - |');
                
                // 7. 验证表格格式（确保表格行之间没有多余空行）
                const lines = result.split('\n');
                const cleanedLines: string[] = [];
                let inTable = false;
                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i];
                    const isTableRow = line.trim().startsWith('|') && line.trim().endsWith('|');
                    
                    if (isTableRow) {
                        if (inTable && cleanedLines[cleanedLines.length - 1] === '') {
                            // 移除表格前的空行
                            cleanedLines.pop();
                        }
                        inTable = true;
                        cleanedLines.push(line);
                    } else {
                        if (inTable && line.trim() === '') {
                            // 表格后的第一个空行保留，后续空行移除
                            if (cleanedLines[cleanedLines.length - 1] !== '') {
                                cleanedLines.push(line);
                            }
                            inTable = false;
                        } else {
                            cleanedLines.push(line);
                            inTable = false;
                        }
                    }
                }
                result = cleanedLines.join('\n');
                
                console.log("使用自定义报告模板生成报告");
                console.log("生成的报告长度:", result.length, "字符");
                return result;
            } catch (e) {
                console.error("模板填充失败:", e);
                console.error("错误详情:", e);
                console.log("回退到默认报告格式");
            }
        }
    }
    
    // 默认报告格式
    return generateDefaultReport(context);
}

/**
 * 生成默认格式的报告
 */
function generateDefaultReport(context: ReportContext): string {
    const { member, semanticResult, groupName } = context;
    
    return `# ${member.displayName} (${member.username}) - 社交行为分析报告

## 群组信息
- **群名称**: ${groupName}
- **分析时间**: ${new Date().toLocaleString()}

## 综合评价
${semanticResult?.summary ?? '无'}

## 详细分析

### 1. 性格与沟通风格
- **情感基调**: ${semanticResult?.emotion_analysis?.dominant_tone ?? '无'} (正面: ${semanticResult?.emotion_analysis?.positive_ratio ?? 0}%, 负面: ${semanticResult?.emotion_analysis?.negative_ratio ?? 0}%)
- **风格**: ${(semanticResult?.communication_style?.style_tags ?? []).join(', ') || '无'}
- **语言模式**: ${semanticResult?.communication_style?.language_pattern ?? '无'}

### 2. 话题兴趣
- **主要话题**: ${(semanticResult?.topic_interests?.main_topics ?? []).join(', ') || '无'}
- **兴趣描述**: ${semanticResult?.topic_interests?.interest_description ?? '无'}

### 3. 角色定位
- **群组角色**: ${semanticResult?.role_analysis?.group_role ?? '无'} (${semanticResult?.role_analysis?.initiative_level ?? '未知'})
- **行为特征**: ${semanticResult?.role_analysis?.social_behavior ?? '无'}

### 4. 职业推断
- **可能领域**: ${(semanticResult?.professional_inference?.possible_fields ?? []).join(', ') || '无'}
- **置信度**: ${semanticResult?.professional_inference?.confidence ?? '未知'}
- **依据**: ${semanticResult?.professional_inference?.expertise_indicators ?? '无'}

### 用户标签
${semanticResult?.tags?.map(t => `\`${t}\``).join(' ') || '无'}

---
*生成时间: ${new Date().toLocaleString()}*
*Powered by Chat Analyzer*
`;
}
