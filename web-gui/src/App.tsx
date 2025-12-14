import { useState, useEffect } from 'react';
import type { ChatSession, UserProfile, ExtractedMessage } from './lib/types';
import {
  extractMessages,
  groupByUser,
  getUserDisplayNames,
  calculateBasicStats,
  calculateSocialNetwork
} from './lib/analyzer';
import { DEFAULT_CONFIG } from './lib/ai-client';
import type { AIConfig } from './lib/ai-client';
import { FileUpload } from './components/FileUpload';
import { Dashboard } from './components/Dashboard';
import { MemberDetail } from './components/MemberDetail';
import { Settings } from './components/Settings';
import { AboutModal } from './components/AboutModal';
import { Settings as SettingsIcon, MessageSquare, CircleHelp } from 'lucide-react';
import './App.css';

function App() {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [rawMessages, setRawMessages] = useState<ExtractedMessage[]>([]);
  const [profiles, setProfiles] = useState<UserProfile[]>([]);
  const [socialNetwork, setSocialNetwork] = useState<any>(null);
  const [selectedMember, setSelectedMember] = useState<UserProfile | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showAbout, setShowAbout] = useState(true); // Auto-show on startup
  const [config, setConfig] = useState<AIConfig>(() => {
    const saved = localStorage.getItem('chat_analyzer_config');
    return saved ? JSON.parse(saved) : DEFAULT_CONFIG;
  });

  const [dateRange, setDateRange] = useState<{ start: string; end: string } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    localStorage.setItem('chat_analyzer_config', JSON.stringify(config));
  }, [config]);

  // Initial Data Processing
  const processData = async (data: any) => {
    try {
      setLoading(true);
      setTimeout(() => {
        const { messages } = extractMessages(data);
        // Find min and max date
        if (messages.length > 0) {
          const dates = messages.map(m => new Date(m.createTime * 1000).toISOString().split('T')[0]).sort();
          setDateRange({
            start: dates[0],
            end: dates[dates.length - 1]
          });
        }
        setRawMessages(messages);
        setSession(data);
        setLoading(false);
      }, 100);
    } catch (e) {
      alert("处理数据时出错: " + e);
      setLoading(false);
    }
  };

  // Dynamic Analysis when messages or dateRange changes
  useEffect(() => {
    if (rawMessages.length === 0 || !dateRange) return;

    setLoading(true); // Short loading state for recalculation
    const timer = setTimeout(() => {
      const startTs = new Date(dateRange.start).getTime() / 1000;
      const endTs = new Date(dateRange.end).getTime() / 1000 + 86400; // Include the end date fully

      const filteredMessages = rawMessages.filter(m =>
        m.createTime >= startTs && m.createTime < endTs
      );

      const userMap = groupByUser(filteredMessages);
      const displayNames = getUserDisplayNames(filteredMessages);
      const allProfiles: UserProfile[] = [];
      const social = calculateSocialNetwork(filteredMessages, userMap);

      for (const [username, msgs] of Object.entries(userMap)) {
        const basicStats = calculateBasicStats(msgs);
        const userScore = social.userScores[username] || {};

        let groupStatus = '成员';
        if (social.coreMembers.includes(username)) groupStatus = '核心成员';
        else if (social.peripheralMembers.includes(username)) groupStatus = '边缘成员';
        else if (basicStats.messageCount > 100) groupStatus = '活跃成员';

        allProfiles.push({
          username,
          displayName: displayNames[username] || username,
          basicStats,
          messageRatio: filteredMessages.length > 0 ? parseFloat((msgs.length / filteredMessages.length * 100).toFixed(2)) : 0,
          groupStatus,
          tags: [],
          mentionsGiven: userScore.mentionsGiven || 0,
          mentionsReceived: userScore.mentionsReceived || 0,
          semanticResults: undefined
        });
      }

      allProfiles.sort((a, b) => b.basicStats.messageCount - a.basicStats.messageCount);
      setProfiles(allProfiles);
      setSocialNetwork(social);
      setLoading(false);
    }, 50);

    return () => clearTimeout(timer);
  }, [rawMessages, dateRange]);


  const handleMemberSelect = (member: UserProfile) => {
    setSelectedMember(member);
  };

  const handleBack = () => {
    setSelectedMember(null);
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-content">
          <div className="logo">
            <MessageSquare className="logo-icon" />
            <h1>Chat Analyzer</h1>
          </div>
          <div className="header-actions">
            <button className="icon-btn" onClick={() => setShowAbout(true)} title="关于与说明">
              <CircleHelp />
            </button>
            <button className="icon-btn" onClick={() => setShowSettings(true)} title="设置">
              <SettingsIcon />
            </button>
          </div>
        </div>
      </header>

      <main className="app-main">
        {loading && rawMessages.length === 0 && (
          <div className="loading-overlay">
            <div className="spinner"></div>
            <p>正如火如荼地分析中...</p>
          </div>
        )}

        {!session && !loading && (
          <div className="upload-view">
            <FileUpload onFileLoaded={processData} />
            <div className="demo-hint">
              <p>支持 .json 格式的微信聊天记录</p>
            </div>
          </div>
        )}

        {session && !selectedMember && (
          <Dashboard
            session={session.session}
            timeRange={profiles.length > 0 ? `${dateRange?.start} 至 ${dateRange?.end}` : "N/A"}
            totalMessages={profiles.reduce((acc, p) => acc + p.basicStats.messageCount, 0)}
            profiles={profiles}
            socialNetwork={socialNetwork}
            onSelectMember={handleMemberSelect}
            // Date Filter Props
            dateRange={dateRange}
            onDateChange={setDateRange}
          />
        )}

        {selectedMember && (
          <MemberDetail
            member={selectedMember}
            config={config}
            groupName={session?.session.nickname || "Unknown"}
            onBack={handleBack}
            // Filter user messages by date range as well
            messages={rawMessages.filter(m =>
              m.senderUsername === selectedMember.username &&
              (!dateRange || (
                m.createTime >= new Date(dateRange.start).getTime() / 1000 &&
                m.createTime < new Date(dateRange.end).getTime() / 1000 + 86400
              ))
            )}
          />
        )}
      </main>

      <Settings
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        config={config}
        onConfigChange={setConfig}
      />

      <AboutModal
        isOpen={showAbout}
        onClose={() => setShowAbout(false)}
      />
    </div>
  );
}

export default App;
