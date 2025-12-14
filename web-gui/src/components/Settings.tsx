import React, { useState } from 'react';
import type { AIConfig } from '../lib/ai-client';
import { X, Save, Upload } from 'lucide-react';
import './Settings.css';

interface SettingsProps {
    isOpen: boolean;
    onClose: () => void;
    config: AIConfig;
    onConfigChange: (config: AIConfig) => void;
}

export const Settings: React.FC<SettingsProps> = ({ isOpen, onClose, config, onConfigChange }) => {
    const [activeTab, setActiveTab] = useState<'model' | 'prompts'>('model');
    const [localConfig, setLocalConfig] = useState<AIConfig>(config);

    if (!isOpen) return null;

    const handleSave = () => {
        onConfigChange(localConfig);
        onClose();
    };

    const handleChange = (field: keyof AIConfig, value: string) => {
        setLocalConfig(prev => ({ ...prev, [field]: value }));
    };

    const handleFileUpload = (field: keyof AIConfig, e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const validExtensions = ['.md', '.txt'];
        const hasValidExt = validExtensions.some(ext => file.name.toLowerCase().endsWith(ext));
        
        if (!hasValidExt) {
            alert('请上传 .md 或 .txt 格式的文件');
            return;
        }

        const reader = new FileReader();
        reader.onload = (event) => {
            const content = event.target?.result as string;
            if (content) {
                handleChange(field, content);
                // 显示加载成功提示
                console.log(`已加载模板文件: ${file.name} (${content.length} 字符)`);
            }
        };
        reader.readAsText(file);
    };

    return (
        <div className="settings-overlay">
            <div className="settings-modal">
                <div className="settings-header">
                    <h2>设置</h2>
                    <button className="close-btn" onClick={onClose}><X size={20} /></button>
                </div>

                <div className="settings-tabs">
                    <button
                        className={`tab-btn ${activeTab === 'model' ? 'active' : ''}`}
                        onClick={() => setActiveTab('model')}
                    >
                        模型配置
                    </button>
                    <button
                        className={`tab-btn ${activeTab === 'prompts' ? 'active' : ''}`}
                        onClick={() => setActiveTab('prompts')}
                    >
                        提示词与模板
                    </button>
                </div>

                <div className="settings-content">
                    {activeTab === 'model' && (
                        <>
                            <div className="form-group">
                                <label>API Endpoint Base URL</label>
                                <input
                                    type="text"
                                    value={localConfig.apiUrl}
                                    onChange={e => handleChange('apiUrl', e.target.value)}
                                    placeholder="https://api.openai.com/v1/chat/completions"
                                />
                                <small>兼容 OpenAI 格式的接口地址</small>
                            </div>

                            <div className="form-group">
                                <label>API Key</label>
                                <input
                                    type="password"
                                    value={localConfig.apiKey}
                                    onChange={e => handleChange('apiKey', e.target.value)}
                                    placeholder="sk-..."
                                />
                                <small>密钥仅存储在本地浏览器中</small>
                            </div>

                            <div className="form-group">
                                <label>模型名称 (Model Name)</label>
                                <input
                                    type="text"
                                    value={localConfig.model}
                                    onChange={e => handleChange('model', e.target.value)}
                                    placeholder="gpt-3.5-turbo"
                                />
                            </div>
                        </>
                    )}

                    {activeTab === 'prompts' && (
                        <>
                            <p className="settings-hint">
                                与桌面版 GUI 对齐的模板配置。支持上传 .md 文件或直接粘贴内容。
                            </p>

                            <div className="form-group">
                                <div className="label-row">
                                    <label>切片分析提示词</label>
                                    <label className="upload-label" title="上传 Markdown 文件">
                                        <Upload size={14} />
                                        <span>上传 .md</span>
                                        <input
                                            type="file"
                                            accept=".md,.txt"
                                            onChange={(e) => handleFileUpload('slicePromptTemplate', e)}
                                            hidden
                                        />
                                    </label>
                                </div>
                                <textarea
                                    rows={5}
                                    value={localConfig.slicePromptTemplate || ''}
                                    onChange={e => handleChange('slicePromptTemplate', e.target.value)}
                                    placeholder="（可选）用于分段摘要分析的 AI 提示词，留空使用默认..."
                                />
                                <small>
                                    用于分析单个聊天切片的 AI 系统提示词。应告诉 AI 返回 JSON 格式的摘要结果。
                                </small>
                            </div>

                            <div className="form-group">
                                <div className="label-row">
                                    <label>提示词模板 (对应桌面版 test_prompt.md)</label>
                                    <label className="upload-label" title="上传 Markdown 文件">
                                        <Upload size={14} />
                                        <span>上传 .md</span>
                                        <input
                                            type="file"
                                            accept=".md,.txt"
                                            onChange={(e) => handleFileUpload('promptTemplate', e)}
                                            hidden
                                        />
                                    </label>
                                </div>
                                <textarea
                                    rows={6}
                                    value={localConfig.promptTemplate || ''}
                                    onChange={e => handleChange('promptTemplate', e.target.value)}
                                    placeholder="（可选）用于汇总分析的 AI 提示词，留空使用默认..."
                                />
                                <small>
                                    用于生成最终用户画像的 AI 系统提示词（优先级最高）。
                                    应告诉 AI 返回指定格式的 JSON 结果。
                                </small>
                            </div>

                            <div className="form-group">
                                <div className="label-row">
                                    <label>报告模板 (对应桌面版 test_template.md)</label>
                                    <label className="upload-label" title="上传 Markdown 文件">
                                        <Upload size={14} />
                                        <span>上传 .md</span>
                                        <input
                                            type="file"
                                            accept=".md,.txt"
                                            onChange={(e) => handleFileUpload('reportTemplate', e)}
                                            hidden
                                        />
                                    </label>
                                </div>
                                <textarea
                                    rows={6}
                                    value={localConfig.reportTemplate || ''}
                                    onChange={e => handleChange('reportTemplate', e.target.value)}
                                    placeholder="（可选）报告输出格式模板，可包含 {'{display_name}'} 等占位符..."
                                />
                                <small>
                                    报告输出格式模板，可包含 {'{analysis_time}'} 等占位符用于生成报告。
                                    如果同时包含提示词和 "## 报告输出模板" 标记，会自动分离。
                                </small>
                            </div>
                        </>
                    )}
                </div>

                <div className="settings-footer">
                    <button className="btn-save" onClick={handleSave}><Save size={16} /> 保存配置</button>
                </div>
            </div>
        </div>
    );
};
