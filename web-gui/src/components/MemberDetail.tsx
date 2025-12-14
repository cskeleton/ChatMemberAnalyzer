import React, { useState, useMemo } from 'react';
import type { UserProfile, SemanticAnalysisResult, ExtractedMessage, SliceAnalysisResult } from '../lib/types';
import { analyzeSlice, analyzeUserFinal, generateReportFromTemplate } from '../lib/ai-client';
import type { AIConfig } from '../lib/ai-client';
import { sliceMessagesByTime, sampleSlices } from '../lib/analyzer';
import { ArrowLeft, Play, Loader2, Download } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './MemberDetail.css';

interface MemberDetailProps {
    member: UserProfile;
    groupName: string;
    config: AIConfig;
    onBack: () => void;
    messages: ExtractedMessage[];
}

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];

export const MemberDetail: React.FC<MemberDetailProps> = ({ member, groupName, config, onBack, messages }) => {
    const [analyzing, setAnalyzing] = useState(false);
    const [progress, setProgress] = useState(0);
    const [log, setLog] = useState<string[]>([]);
    const [semanticResult, setSemanticResult] = useState<SemanticAnalysisResult | null>(member.semanticResults || null);

    const activeHoursData = Object.entries(member.basicStats.activeHours)
        .sort((a, b) => parseInt(a[0]) - parseInt(b[0]))
        .map(([h, c]) => ({ name: `${h}时`, count: c }));

    const msgTypeData = Object.entries(member.basicStats.messageTypes)
        .map(([name, value]) => ({ name, value }));

    const addLog = (msg: string) => setLog(prev => [...prev, msg]);

    // 使用模板生成报告内容（与下载保持一致）
    const reportMarkdown = useMemo(() => {
        if (!semanticResult) return '';
        
        // 计算用户消息的实际时间范围
        let timeRange = 'N/A';
        if (messages.length > 0) {
            const sortedMessages = [...messages].sort((a, b) => a.createTime - b.createTime);
            const startDate = sortedMessages[0].formattedTime.split(' ')[0];
            const endDate = sortedMessages[sortedMessages.length - 1].formattedTime.split(' ')[0];
            timeRange = `${startDate} 至 ${endDate}`;
        }
        
        return generateReportFromTemplate(
            {
                member,
                semanticResult,
                groupName,
                timeRange,
                totalMessages: messages.length,
                memberCount: undefined
            },
            config.reportTemplate
        );
    }, [semanticResult, member, groupName, messages, config.reportTemplate]);

    const handleStartAnalysis = async () => {
        if (!config.apiKey) {
            alert("请先在设置中配置 API Key");
            return;
        }

        setAnalyzing(true); // Ensure analyzing is set to true immediately
        setProgress(0);
        setLog(["开始分析..."]);

        try {
            // 1. Slice
            addLog("正在对消息进行切片...");
            // 1. Slice
            // Actually analyzer handles raw messages.
            // But we passed ExtractedMessages (which match RawMessage shape mostly but field names differ? extractMessages returns ExtractedMessage)
            // analyzer.ts expects ExtractedMessage. Correct.

            const slices = sliceMessagesByTime(messages);
            const sampledSlices = sampleSlices(slices, 5); // Max 5 slices for web to save tokens/time

            addLog(`生成了 ${slices.length} 个切片，采样 ${sampledSlices.length} 个进行分析`);



            addLog(`正在并发分析 ${sampledSlices.length} 个切片...`);

            // Parallel processing with progress tracking requires a bit of care
            let completed = 0;
            const updateProgress = () => {
                completed++;
                setProgress((completed / sampledSlices.length) * 80);
            };

            const slicePromises = sampledSlices.map(async (slice, i) => {
                addLog(`启动切片任务 ${i + 1}...`);
                try {
                    const summary = await analyzeSlice(config, slice, member.displayName, member.username);
                    updateProgress();
                    addLog(`切片 ${i + 1} 分析完成`);
                    return summary;
                } catch (err: any) {
                    addLog(`切片 ${i + 1} 失败: ${err.message}`);
                    return null; // Handle individual slice failure
                }
            });

            const results = await Promise.all(slicePromises);
            const summaries: SliceAnalysisResult[] = results.filter((s): s is SliceAnalysisResult => s !== null); // Filter out failed slices

            addLog("正在生成最终画像...");
            const finalResult = await analyzeUserFinal(config, member, summaries);

            setSemanticResult(finalResult);
            addLog("分析完成！");
            setAnalyzing(false);
            setProgress(100);

        } catch (e: any) {
            addLog(`Error: ${e.message}`);
            setAnalyzing(false);
        }
    };

    const handleDownloadReport = () => {
        if (!reportMarkdown) return;

        const blob = new Blob([reportMarkdown], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${member.displayName}_analysis.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    return (
        <div className="member-detail">
            <div className="detail-header">
                <button className="back-btn" onClick={onBack}><ArrowLeft size={20} /> 返回列表</button>
                <h1>{member.displayName} <span className="sub-header">({member.username})</span></h1>
            </div>

            <div className="detail-grid">
                <div className="detail-col">
                    <div className="card">
                        <h3>活跃时段</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <BarChart data={activeHoursData}>
                                <XAxis dataKey="name" fontSize={10} />
                                <YAxis fontSize={10} />
                                <Tooltip />
                                <Bar dataKey="count" fill="#3b82f6" />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="card">
                        <h3>消息类型</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <PieChart>
                                <Pie
                                    data={msgTypeData}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={40}
                                    outerRadius={70}
                                    paddingAngle={5}
                                    dataKey="value"
                                >
                                    {msgTypeData.map((_entry, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip />
                            </PieChart>
                        </ResponsiveContainer>
                        <div className="legend">
                            {msgTypeData.map((d, i) => (
                                <span key={d.name} style={{ color: COLORS[i % COLORS.length] }}>{d.name}: {d.value}</span>
                            ))}
                        </div>
                    </div>

                    <div className="card stats-summary">
                        <div className="stat-row">
                            <span>发言总数</span>
                            <strong>{member.basicStats.messageCount}</strong>
                        </div>
                        <div className="stat-row">
                            <span>平均长度</span>
                            <strong>{member.basicStats.avgLength} 字</strong>
                        </div>
                        <div className="stat-row">
                            <span>提及他人</span>
                            <strong>{member.mentionsGiven} 次</strong>
                        </div>
                        <div className="stat-row">
                            <span>被提及</span>
                            <strong>{member.mentionsReceived} 次</strong>
                        </div>
                    </div>
                </div>

                <div className="detail-col main-col">
                    <div className="card ai-card">
                        <div className="ai-header">
                            <h2>AI 深度分析</h2>
                            {!analyzing && !semanticResult && (
                                <button className="analyze-btn" onClick={handleStartAnalysis}>
                                    <Play size={16} /> 开始分析
                                </button>
                            )}
                            {analyzing && <span className="status"><Loader2 className="spin" size={16} /> 分析中 {Math.round(progress)}%</span>}
                            {semanticResult && (
                                <button className="download-btn" onClick={handleDownloadReport} title="下载 Markdown 报告">
                                    <Download size={16} /> 下载报告
                                </button>
                            )}
                        </div>

                        {log.length > 0 && !semanticResult && (
                            <div className="console-log">
                                {log.map((l, i) => <div key={i}>{l}</div>)}
                            </div>
                        )}

                        {semanticResult && reportMarkdown && (
                            <div className="report-content markdown-body">
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={{
                                        // 确保表格正确渲染
                                        table: ({ children }) => (
                                            <div style={{ overflowX: 'auto' }}>
                                                <table>{children}</table>
                                            </div>
                                        ),
                                    }}
                                >
                                    {reportMarkdown}
                                </ReactMarkdown>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
