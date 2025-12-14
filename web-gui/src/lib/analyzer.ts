import type {
    ChatSession,
    ExtractedMessage,
    MessageStats,
    BasicStats,
    SocialNetwork,
    TimeSlice
} from './types';

// ============================================================
// Helper Functions
// ============================================================

export function getWeekKey(timestamp: number): string {
    const date = new Date(timestamp * 1000);
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const dayNum = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    const weekNo = Math.ceil((((d.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
    return `${d.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`;
}

export function getDayKey(timestamp: number): string {
    const date = new Date(timestamp * 1000);
    return date.toISOString().split('T')[0];
}

export function formatActiveHours(activeHours: Record<string, number>): string {
    if (Object.keys(activeHours).length === 0) return "无数据";

    const sorted = Object.entries(activeHours)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3);

    return sorted.map(([h, count]) => {
        const hour = parseInt(h);
        return `${hour}:00-${hour + 1}:00 (${count}条)`;
    }).join(", ");
}

// ============================================================
// Core Logic
// ============================================================

export function extractMessages(data: ChatSession, timeStart = 0, timeEnd = 0): { messages: ExtractedMessage[], stats: MessageStats } {
    const rawMessages = data.messages || [];
    const extracted: ExtractedMessage[] = [];
    const stats: MessageStats = { total: rawMessages.length, system: 0, timeFiltered: 0, valid: 0 };

    for (const msg of rawMessages) {
        if (msg.type === '系统消息') {
            stats.system++;
            continue;
        }

        const createTime = msg.createTime || 0;
        if (timeStart > 0 && createTime < timeStart) {
            stats.timeFiltered++;
            continue;
        }
        if (timeEnd > 0 && createTime > timeEnd) {
            stats.timeFiltered++;
            continue;
        }

        let content = msg.content || '';
        if (msg.type === '文本消息' && content) {
            // Remove "username:\n" prefix if present (common in some exports)
            const pattern = /^[a-zA-Z0-9_]+:\n?/;
            content = content.replace(pattern, '').trim();
        }

        extracted.push({
            senderUsername: msg.senderUsername || '',
            senderDisplayName: msg.senderDisplayName || '',
            createTime: createTime,
            formattedTime: msg.formattedTime || '',
            type: msg.type || 'Unknown',
            content: content,
            isSend: msg.isSend || 0
        });
        stats.valid++;
    }

    return { messages: extracted, stats };
}

export function groupByUser(messages: ExtractedMessage[]): Record<string, ExtractedMessage[]> {
    const groups: Record<string, ExtractedMessage[]> = {};
    for (const msg of messages) {
        const username = msg.senderUsername;
        if (username) {
            if (!groups[username]) groups[username] = [];
            groups[username].push(msg);
        }
    }
    return groups;
}

export function getUserDisplayNames(messages: ExtractedMessage[]): Record<string, string> {
    const names: Record<string, string> = {};
    for (const msg of messages) {
        if (msg.senderUsername && msg.senderDisplayName) {
            names[msg.senderUsername] = msg.senderDisplayName;
        }
    }
    return names;
}

export function calculateBasicStats(messages: ExtractedMessage[]): BasicStats {
    if (!messages || messages.length === 0) {
        return {
            messageCount: 0,
            avgLength: 0,
            activeHours: {},
            messageTypes: {},
            mostActiveDate: '',
            mostActiveCount: 0,
            interactionCount: { mentions: 0, quotes: 0 }
        };
    }

    const messageCount = messages.length;
    const textMessages = messages.filter(m => m.type === '文本消息');
    const avgLength = textMessages.length > 0
        ? parseFloat((textMessages.reduce((sum, m) => sum + m.content.length, 0) / textMessages.length).toFixed(1))
        : 0;

    const activeHours: Record<string, number> = {};
    const dailyCount: Record<string, number> = {};
    const messageTypes: Record<string, number> = {};
    let mentions = 0;
    let quotes = 0;

    for (const msg of messages) {
        // Hour extraction
        try {
            // Assuming formattedTime is "YYYY-MM-DD HH:MM:SS"
            const hourStr = msg.formattedTime.split(' ')[1]?.split(':')[0];
            if (hourStr) {
                const hour = parseInt(hourStr);
                activeHours[hour] = (activeHours[hour] || 0) + 1;
            }
        } catch (e) { /* ignore */ }

        // Date extraction
        const date = msg.formattedTime.split(' ')[0];
        if (date) dailyCount[date] = (dailyCount[date] || 0) + 1;

        // Type
        const type = msg.type || '其他';
        messageTypes[type] = (messageTypes[type] || 0) + 1;

        // Interactions
        const mentionMatch = msg.content.match(/@\w+/g);
        if (mentionMatch) mentions += mentionMatch.length;

        if (msg.type === '引用消息') quotes++;
    }

    // Most active date
    let mostActiveDate = '';
    let mostActiveCount = 0;
    for (const [date, count] of Object.entries(dailyCount)) {
        if (count > mostActiveCount) {
            mostActiveCount = count;
            mostActiveDate = date;
        }
    }

    return {
        messageCount,
        avgLength,
        activeHours,
        messageTypes,
        mostActiveDate,
        mostActiveCount,
        interactionCount: { mentions, quotes }
    };
}

export function calculateSocialNetwork(allMessages: ExtractedMessage[], userMessages: Record<string, ExtractedMessage[]>): SocialNetwork {
    const interactionMatrix: Record<string, Record<string, number>> = {};
    const mentionReceived: Record<string, number> = {};

    // Initialize matrix
    for (const u of Object.keys(userMessages)) {
        interactionMatrix[u] = {};
    }

    for (const msg of allMessages) {
        const sender = msg.senderUsername;
        if (!sender) continue;

        const mentions = msg.content.match(/@(\w+)/g);

        if (mentions) {
            for (let m of mentions) {
                const mentionedName = m.substring(1); // remove @
                if (mentionedName !== sender) {
                    if (!interactionMatrix[sender]) interactionMatrix[sender] = {};
                    interactionMatrix[sender][mentionedName] = (interactionMatrix[sender][mentionedName] || 0) + 1;
                    mentionReceived[mentionedName] = (mentionReceived[mentionedName] || 0) + 1;
                }
            }
        }
    }

    const userScores: Record<string, { messageCount: number; mentionsGiven: number; mentionsReceived: number; interactionScore: number }> = {};

    for (const username of Object.keys(userMessages)) {
        const msgCount = userMessages[username].length;
        // Sum mentions given
        const givenMap = interactionMatrix[username] || {};
        const mentionsGiven = Object.values(givenMap).reduce((a, b) => a + b, 0);
        const mentionsGot = mentionReceived[username] || 0;

        userScores[username] = {
            messageCount: msgCount,
            mentionsGiven: mentionsGiven,
            mentionsReceived: mentionsGot,
            interactionScore: msgCount + mentionsGiven * 2 + mentionsGot * 2
        };
    }

    const sortedUsers = Object.keys(userScores).sort((a, b) => userScores[b].interactionScore - userScores[a].interactionScore);

    const coreCount = Math.max(1, Math.floor(sortedUsers.length / 3));
    const peripheralCount = Math.max(1, Math.floor(sortedUsers.length / 3));

    return {
        interactionMatrix,
        userScores,
        coreMembers: sortedUsers.slice(0, coreCount),
        peripheralMembers: sortedUsers.length > 1 ? sortedUsers.slice(-peripheralCount) : []
    };
}

export function sliceMessagesByTime(messages: ExtractedMessage[], maxMsgs = 500, minMsgs = 30): TimeSlice[] {
    if (!messages.length) return [];

    const weeklyGroups: Record<string, ExtractedMessage[]> = {};
    for (const msg of messages) {
        const key = getWeekKey(msg.createTime);
        if (!weeklyGroups[key]) weeklyGroups[key] = [];
        weeklyGroups[key].push(msg);
    }

    const sortedWeeks = Object.keys(weeklyGroups).sort();
    const slices: TimeSlice[] = [];
    let pendingMerge: ExtractedMessage[][] = [];

    const createSlice = (msgs: ExtractedMessage[]): TimeSlice => {
        msgs.sort((a, b) => a.createTime - b.createTime);
        return {
            timeStart: msgs[0].formattedTime,
            timeEnd: msgs[msgs.length - 1].formattedTime,
            messageCount: msgs.length,
            messages: msgs
        };
    };

    for (const weekKey of sortedWeeks) {
        const weekMsgs = weeklyGroups[weekKey];
        if (weekMsgs.length > maxMsgs) {
            if (pendingMerge.length > 0) {
                slices.push(createSlice(pendingMerge.flat()));
                pendingMerge = [];
            }

            // Sub-slice by day
            const dailyGroups: Record<string, ExtractedMessage[]> = {};
            for (const msg of weekMsgs) {
                const dayKey = getDayKey(msg.createTime);
                if (!dailyGroups[dayKey]) dailyGroups[dayKey] = [];
                dailyGroups[dayKey].push(msg);
            }

            Object.keys(dailyGroups).sort().forEach(dayKey => {
                slices.push(createSlice(dailyGroups[dayKey]));
            });

        } else if (weekMsgs.length < minMsgs) {
            pendingMerge.push(weekMsgs);
            const currentTotal = pendingMerge.reduce((sum, m) => sum + m.length, 0);
            if (currentTotal >= minMsgs) {
                slices.push(createSlice(pendingMerge.flat()));
                pendingMerge = [];
            }
        } else {
            if (pendingMerge.length > 0) {
                pendingMerge.push(weekMsgs);
                slices.push(createSlice(pendingMerge.flat()));
                pendingMerge = [];
            } else {
                slices.push(createSlice(weekMsgs));
            }
        }
    }

    if (pendingMerge.length > 0) {
        slices.push(createSlice(pendingMerge.flat()));
    }

    return slices;
}

export function sampleSlices(slices: TimeSlice[], maxSlices: number): TimeSlice[] {
    if (maxSlices <= 0 || slices.length <= maxSlices) return slices;
    if (maxSlices === 1) return [slices[slices.length - 1]];
    if (maxSlices === 2) return [slices[0], slices[slices.length - 1]];

    const n = slices.length;
    const middleCount = maxSlices - 2;
    const step = (n - 2) / (middleCount + 1);

    // Always include first
    const sampled = [slices[0]];

    // Sample middle
    for (let i = 1; i <= middleCount; i++) {
        const idx = Math.floor(i * step);
        if (idx < n - 1 && idx > 0) {
            sampled.push(slices[idx]);
        }
    }

    // Always include last if distinct
    if (sampled[sampled.length - 1] !== slices[n - 1]) {
        sampled.push(slices[n - 1]);
    }

    // Deduplicate just in case
    return Array.from(new Set(sampled));
}
