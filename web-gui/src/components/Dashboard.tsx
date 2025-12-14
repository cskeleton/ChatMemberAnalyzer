import React, { useState } from 'react';
import type { UserProfile, ChatSession } from '../lib/types';
import { Users, MessageSquare, Calendar } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import './Dashboard.css';

interface DashboardProps {
    session: ChatSession['session'];
    timeRange: string;
    totalMessages: number;
    profiles: UserProfile[];
    onSelectMember: (member: UserProfile) => void;
    socialNetwork: any; // Simplified for now

    // New Props for Date Filter
    dateRange?: { start: string; end: string } | null;
    onDateChange?: (range: { start: string; end: string }) => void;
}

export const Dashboard: React.FC<DashboardProps> = ({
    session,
    timeRange,
    totalMessages,
    profiles,
    onSelectMember,
    dateRange,
    onDateChange
}) => {
    const [searchTerm, setSearchTerm] = useState('');

    const filteredProfiles = profiles.filter(p =>
        p.displayName.toLowerCase().includes(searchTerm.toLowerCase()) ||
        p.username.toLowerCase().includes(searchTerm.toLowerCase())
    );

    const handleDateChange = (type: 'start' | 'end', value: string) => {
        if (!dateRange || !onDateChange) return;
        onDateChange({
            ...dateRange,
            [type]: value
        });
    };

    return (
        <div className="dashboard-container">
            <div className="overview-card">
                <div className="overview-header">
                    <div>
                        <h2>{session.nickname || '未命名群组'}</h2>
                        <div className="meta-info">
                            <span>消息总数: {totalMessages}</span>
                            <span>成员数: {profiles.length}</span>
                        </div>
                    </div>
                    {dateRange && (
                        <div className="date-filter">
                            <label>
                                <span>开始:</span>
                                <input
                                    type="date"
                                    value={dateRange.start}
                                    onChange={(e) => handleDateChange('start', e.target.value)}
                                />
                            </label>
                            <label>
                                <span>结束:</span>
                                <input
                                    type="date"
                                    value={dateRange.end}
                                    onChange={(e) => handleDateChange('end', e.target.value)}
                                />
                            </label>
                        </div>
                    )}
                </div>
            </div>
            <div className="stats-grid">
                <div className="stat-card">
                    <div className="stat-icon"><MessageSquare /></div>
                    <div className="stat-info">
                        <h3>{totalMessages.toLocaleString()}</h3>
                        <p>总消息数</p>
                    </div>
                </div>
                <div className="stat-card">
                    <div className="stat-icon"><Users /></div>
                    <div className="stat-info">
                        <h3>{profiles.length}</h3>
                        <p>群成员</p>
                    </div>
                </div>
                <div className="stat-card">
                    <div className="stat-icon"><Calendar /></div>
                    <div className="stat-info">
                        <h3>{timeRange}</h3>
                        <p>时间跨度</p>
                    </div>
                </div>
            </div>

            <div className="content-grid">
                <div className="member-list-card">
                    <div className="card-header">
                        <h2>成员列表</h2>
                        <input
                            type="text"
                            placeholder="搜索成员..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="search-input"
                        />
                    </div>
                    <div className="member-list">
                        {filteredProfiles.map(p => (
                            <div key={p.username} className="member-item" onClick={() => onSelectMember(p)}>
                                <div className="member-info">
                                    <span className="member-name">{p.displayName}</span>
                                    <span className="member-stats">{p.basicStats.messageCount} 条发言</span>
                                </div>
                                <div className="member-tags">
                                    {p.groupStatus === '核心成员' && <span className="tag core">核心</span>}
                                    {p.groupStatus === '活跃成员' && <span className="tag active">活跃</span>}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="charts-card">
                    <h2>互动概览 (Top 10)</h2>
                    <div className="chart-container">
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={profiles.slice(0, 10).map(p => ({ name: p.displayName, count: p.basicStats.messageCount }))}>
                                <XAxis dataKey="name" />
                                <YAxis />
                                <Tooltip />
                                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </div>
    );
};
