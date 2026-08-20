import React, { useState } from "react";
import { useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useAuth } from "@clerk/clerk-react";
import { adminFetch } from "../../api/adminApi";

export const TelegramCommandView: React.FC = () => {
  const sessions = useQuery(api.adminQuery.listTelegramSessions);
  const { getToken } = useAuth();
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);

  const messages = useQuery(
    api.adminQuery.getTelegramChatHistory,
    selectedChatId ? { chatId: selectedChatId } : "skip"
  );

  const [inputMsg, setInputMsg] = useState("");
  const [sending, setSending] = useState(false);

  const activeSession = sessions?.find((s: any) => s.chatId === selectedChatId);

  const handleTakeover = async () => {
    if (!selectedChatId) return;

    try {
      await adminFetch(getToken, `/api/admin/telegram/${selectedChatId}/takeover`, {
        method: "POST",
        body: JSON.stringify({ pause_duration_minutes: 60 }),
      });
    } catch (e: any) {
      alert(`Takeover failed: ${e.message}`);
    }
  };

  const handleRelease = async () => {
    if (!selectedChatId) return;

    try {
      await adminFetch(getToken, `/api/admin/telegram/${selectedChatId}/release`, {
        method: "POST",
      });
    } catch (e: any) {
      alert(`Release failed: ${e.message}`);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedChatId || !inputMsg.trim()) return;

    setSending(true);

    try {
      await adminFetch(getToken, `/api/admin/telegram/${selectedChatId}/message`, {
        method: "POST",
        body: JSON.stringify({ message: inputMsg.trim() }),
      });
      setInputMsg("");
    } catch (e: any) {
      alert(`Send message failed: ${e.message}`);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">Telegram Command Center (The Inbox)</h1>
        <p className="text-xs text-ink-400">Live chat streaming, 1-hour TTL human agent takeover, and direct bot dispatch</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[650px]">
        {/* Left: Chat Sessions List */}
        <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 p-4 backdrop-blur-xl flex flex-col overflow-hidden">
          <h2 className="text-xs font-bold uppercase tracking-wider text-ink-400 font-mono mb-3">
            Active Chat Sessions
          </h2>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {(!sessions || sessions.length === 0) && (
              <div className="py-12 text-center text-xs text-ink-500 font-mono">
                Zero active Telegram sessions.
              </div>
            )}

            {sessions?.map((sess: any) => (
              <button
                key={sess._id}
                onClick={() => setSelectedChatId(sess.chatId)}
                className={`w-full text-left p-3 rounded-xl border transition-all font-mono text-xs ${
                  selectedChatId === sess.chatId
                    ? "bg-brand-500/15 border-brand-500/40 text-white shadow-sm"
                    : "bg-ink-950/40 border-white/[0.04] text-ink-300 hover:bg-white/[0.03]"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-white">Chat #{sess.chatId}</span>
                  {sess.isBotPaused && (
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-500/20 text-amber-300">
                      HUMAN TAKEOVER
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-ink-400 truncate mt-1">{sess.lastMessage || "No messages yet"}</div>
                <div className="text-[10px] text-ink-600 mt-1">
                  {new Date(sess.updatedAt || sess._creationTime).toLocaleTimeString()}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Right: Live Chat Box */}
        <div className="lg:col-span-2 rounded-2xl border border-white/[0.08] bg-ink-900/40 p-4 backdrop-blur-xl flex flex-col overflow-hidden">
          {selectedChatId ? (
            <>
              {/* Chat Header & Takeover Controls */}
              <div className="border-b border-white/[0.08] pb-3 flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-bold text-white font-mono">Chat #{selectedChatId}</h3>
                  <div className="text-[11px] text-ink-400 font-mono">
                    State: {activeSession?.isBotPaused ? "Human Takeover Active (AI Paused)" : "Autonomous Bot AI Active"}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {activeSession?.isBotPaused ? (
                    <button
                      onClick={handleRelease}
                      className="px-3 py-1.5 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 text-xs font-semibold font-mono"
                    >
                      🤖 Release to AI Bot
                    </button>
                  ) : (
                    <button
                      onClick={handleTakeover}
                      className="px-3 py-1.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 text-xs font-semibold font-mono"
                    >
                      ✋ Takeover (1h TTL)
                    </button>
                  )}
                </div>
              </div>

              {/* Messages Feed (Zero-Trust Plain-Text Rendering) */}
              <div className="flex-1 overflow-y-auto py-4 space-y-3 pr-2">
                {(!messages || messages.length === 0) && (
                  <div className="py-12 text-center text-xs text-ink-500 font-mono">
                    No message history recorded for this chat.
                  </div>
                )}

                {messages?.map((msg: any) => {
                  const isUser = msg.sender === "USER";
                  const isOperator = msg.sender === "OPERATOR";

                  return (
                    <div
                      key={msg._id}
                      className={`flex flex-col ${isUser ? "items-start" : "items-end"}`}
                    >
                      <div className="text-[10px] text-ink-500 font-mono mb-0.5">
                        {msg.sender} • {new Date(msg.createdAt || msg._creationTime).toLocaleTimeString()}
                      </div>
                      <div
                        className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-xs select-text whitespace-pre-wrap ${
                          isUser
                            ? "bg-ink-800 text-ink-100 border border-white/5"
                            : isOperator
                            ? "bg-purple-600/30 border border-purple-500/30 text-purple-200"
                            : "bg-brand-500/20 border border-brand-500/30 text-brand-200"
                        }`}
                      >
                        {/* Zero-Trust Plain Text — Never DangerouslySetInnerHTML */}
                        {String(msg.message)}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Chat Input */}
              <form onSubmit={handleSendMessage} className="border-t border-white/[0.08] pt-3 flex gap-2">
                <input
                  type="text"
                  value={inputMsg}
                  onChange={(e) => setInputMsg(e.target.value)}
                  placeholder={
                    activeSession?.isBotPaused
                      ? "Type human operator response..."
                      : "Takeover chat to reply as human..."
                  }
                  className="flex-1 bg-ink-950 border border-white/10 rounded-xl px-4 py-2.5 text-xs text-white placeholder:text-ink-600 focus:outline-none focus:border-brand-400"
                />
                <button
                  type="submit"
                  disabled={sending || !inputMsg.trim()}
                  className="px-5 py-2.5 rounded-xl bg-brand-500 hover:bg-brand-400 text-white font-bold text-xs uppercase tracking-wider disabled:opacity-50 transition-colors"
                >
                  {sending ? "Sending..." : "Send"}
                </button>
              </form>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-xs text-ink-500 font-mono">
              Select a chat session from the left to view messages and engage takeover mode.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default TelegramCommandView;
