export interface RawMessage {
    id?: string;
    type: string;
    content: string;
    createTime: number;
    formattedTime: string;
    senderUsername: string;
    senderDisplayName: string;
    isSend: number;
}

export interface ChatSession {
    session: {
        nickname: string;
        username?: string;
    };
    messages: RawMessage[];
}

export interface ExtractedMessage {
    senderUsername: string;
    senderDisplayName: string;
    createTime: number;
    formattedTime: string;
    type: string;
    content: string;
    isSend: number;
}

export interface MessageStats {
    total: number;
    system: number;
    timeFiltered: number;
    valid: number;
}

export interface BasicStats {
    messageCount: number;
    avgLength: number;
    activeHours: Record<string, number>; // "H" -> count
    messageTypes: Record<string, number>;
    mostActiveDate: string;
    mostActiveCount: number;
    interactionCount: {
        mentions: number;
        quotes: number;
    };
}

export interface SocialNetwork {
    interactionMatrix: Record<string, Record<string, number>>; // user -> target -> count
    userScores: Record<string, {
        messageCount: number;
        mentionsGiven: number;
        mentionsReceived: number;
        interactionScore: number;
    }>;
    coreMembers: string[];
    peripheralMembers: string[];
}

export interface TimeSlice {
    timeStart: string;
    timeEnd: string;
    messageCount: number;
    messages: ExtractedMessage[];
}

// 分段分析结果（用于汇总）
export interface SliceAnalysisResult {
    time_range?: string;
    message_count?: number;
    emotion_summary?: {
        overall_tone?: string;
        emotion_keywords?: string[];
    };
    topics?: string[];
    brief_summary?: string;
}

// 最终汇总分析结果
export interface SemanticAnalysisResult {
    emotion_analysis?: {
        positive_ratio?: number;
        negative_ratio?: number;
        volatility?: string;
        dominant_tone?: string;
    };
    communication_style?: {
        style_tags?: string[];
        language_pattern?: string;
        emoji_usage?: string;
    };
    topic_interests?: {
        main_topics?: string[];
        keywords?: string[];
        interest_description?: string;
    };
    role_analysis?: {
        group_role?: string;
        initiative_level?: string;
        social_behavior?: string;
    };
    professional_inference?: {
        possible_fields?: string[];
        expertise_indicators?: string;
        confidence?: string;
    };
    summary?: string;
    tags?: string[];
}


export interface UserProfile {
    username: string;
    displayName: string;
    basicStats: BasicStats;
    semanticResults?: SemanticAnalysisResult;
    messageRatio: number;
    groupStatus: string;
    tags: string[];
    mentionsGiven: number;
    mentionsReceived: number;
}
