import React from 'react';
import './AboutModal.css';

interface AboutModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export const AboutModal: React.FC<AboutModalProps> = ({ isOpen, onClose }) => {
    if (!isOpen) return null;

    return (
        <div className="about-overlay" onClick={onClose}>
            <div className="about-modal" onClick={e => e.stopPropagation()}>
                <div className="about-header">
                    <h2>关于 & 说明</h2>
                </div>

                <div className="about-section">
                    <p>
                        可以在 Windows 上使用 <a href="https://github.com/ycccccccy/echotrace" target="_blank" rel="noopener noreferrer">ycccccccy/echotrace</a> 导出 JSON 格式群聊消息用于分析。
                        <br />
                        <span className="warning-text">请自行判断第三方工具的项目风险。</span>
                    </p>
                </div>

                <div className="about-section">
                    <p>
                        <strong>隐私声明：</strong>
                        <br />
                        此网站 <strong>不存储</strong> 任何你的数据，所有统计分析均在本地浏览器完成。
                    </p>
                    <p>
                        如果要进行 <strong>AI 语义分析</strong>，你的聊天记录片段会发送给你在设置中设定的 AI 提供商（如 OpenAI）。
                        <br />
                        AI 提供商可能会根据 token 数量向你收取一定费用。
                    </p>
                </div>

                <div className="about-actions">
                    <button className="btn-primary" onClick={onClose}>知道了</button>
                </div>
            </div>
        </div>
    );
};
