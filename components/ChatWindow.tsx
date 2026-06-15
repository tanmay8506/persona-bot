import React, { useState, useEffect, useRef, useMemo } from "react"
import { Send, LogOut, Loader2, Settings, Copy, Check } from "lucide-react"

interface Message {
  role: "user" | "assistant"
  content: string
  id?: string
}

interface MessageBubbleProps {
  msg: Message
  index: number
}

const MessageBubble = ({ msg, index }: MessageBubbleProps) => {
  const [copied, setCopied] = useState(false)
  const isUser = msg.role === "user"

  const handleCopy = () => {
    navigator.clipboard.writeText(msg.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (isUser) {
    return (
      <div key={index} className="flex justify-end mb-4 animate-fade-in-up">
        <div className="group relative max-w-[75%]">
          <div className="px-4 py-2.5 rounded-2xl bg-purple-600 text-white text-[15px] font-normal leading-relaxed rounded-tr-sm shadow-md">
            {msg.content}
          </div>
          <button
            type="button"
            onClick={handleCopy}
            className="absolute -left-8 top-1/2 -translate-y-1/2 p-1.5 rounded bg-charcoal-800/90 text-gray-400 hover:text-white border border-white/5 opacity-0 group-hover:opacity-100 transition-opacity duration-200 cursor-pointer shadow-sm"
            title="Copy text"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>
    )
  }

  const lines = msg.content.split("\n").filter((l) => l.trim() !== "")
  
  if (lines.length <= 1) {
    return (
      <div key={index} className="flex justify-start mb-4 animate-fade-in-up">
        <div className="group relative max-w-[75%]">
          <div className="px-4 py-2.5 rounded-2xl bg-charcoal-700 text-gray-100 text-[15px] font-normal leading-relaxed rounded-tl-sm shadow-md border border-white/5">
            {msg.content}
          </div>
          <button
            type="button"
            onClick={handleCopy}
            className="absolute -right-8 top-1/2 -translate-y-1/2 p-1.5 rounded bg-charcoal-800/90 text-gray-400 hover:text-white border border-white/5 opacity-0 group-hover:opacity-100 transition-opacity duration-200 cursor-pointer shadow-sm"
            title="Copy text"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div key={index} className="flex flex-col items-start gap-1 mb-4 animate-fade-in-up">
      <div className="group relative max-w-[75%]">
        <div className="flex flex-col items-start gap-1">
          {lines.map((line, lineIdx) => {
            const isFirst = lineIdx === 0
            const isLast = lineIdx === lines.length - 1
            
            return (
              <div
                key={lineIdx}
                className={`px-4 py-2.5 bg-charcoal-700 text-gray-100 text-[15px] font-normal leading-relaxed shadow-md border border-white/5 transition-all duration-300
                  ${isFirst ? "rounded-t-2xl rounded-r-2xl rounded-bl-md rounded-tl-sm" : ""}
                  ${!isFirst && !isLast ? "rounded-r-2xl rounded-l-md" : ""}
                  ${isLast ? "rounded-b-2xl rounded-l-md rounded-tr-md" : ""}
                `}
              >
                {line}
              </div>
            )
          })}
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="absolute -right-8 top-1/2 -translate-y-1/2 p-1.5 rounded bg-charcoal-800/90 text-gray-400 hover:text-white border border-white/5 opacity-0 group-hover:opacity-100 transition-opacity duration-200 cursor-pointer shadow-sm"
          title="Copy text"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  )
}

interface ChatWindowProps {
  profileName: string
  passcode: string
  onBack: () => void
}

export default function ChatWindow({ profileName, passcode, onBack }: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState("")
  const [initializing, setInitializing] = useState(true)
  const [error, setError] = useState("")
  const [showSettings, setShowSettings] = useState(false)
  const [hinglishRatio, setHinglishRatio] = useState(0.45)
  const [elongationRate, setElongationRate] = useState(0.5)
  const [burstiness, setBurstiness] = useState(0.5)
  const [intimacy, setIntimacy] = useState(0.8) // Default to high intimacy to enforce tu/tere/tujhe
  const [currentVibe, setCurrentVibe] = useState("")

  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Memoize rendered messages to avoid re-evaluating on every typing keystroke (prevents typing lag / INP issues)
  const renderedMessages = useMemo(() => {
    return messages.map((msg, index) => <MessageBubble key={index} msg={msg} index={index} />)
  }, [messages])

  // Auto-scroll to bottom of conversation
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  // Focus input field on mount and whenever loading finishes to avoid manual click refocusing
  useEffect(() => {
    if (!loading && !initializing) {
      const timer = setTimeout(() => {
        inputRef.current?.focus()
      }, 50)
      return () => clearTimeout(timer)
    }
  }, [loading, initializing])

  // Initialize Conversation Session on mount
  useEffect(() => {
    const initSession = async () => {
      try {
        const res = await fetch("/api/conversations", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${passcode}`,
          },
          body: JSON.stringify({ profile_name: profileName }),
        })

        if (res.status === 200) {
          const data = await res.json()
          setConversationId(data.conversation_id)
        } else {
          setError("Failed to authorize or start conversation session.")
        }
      } catch (err) {
        setError("Network connection failed.")
      } finally {
        setInitializing(false)
      }
    }

    initSession()
  }, [profileName, passcode])

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    const msg = input.trim()
    if (!msg || loading || initializing) return

    // Clear input & set typing/loading state (Send Debouncing safeguard)
    setInput("")
    setLoading(true)
    setError("")

    // Add user message locally
    const userMsg: Message = { role: "user", content: msg }
    setMessages((prev) => [...prev, userMsg])

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${passcode}`,
        },
        body: JSON.stringify({
          conversation_id: conversationId,
          message: msg,
          config: {
            hinglish_ratio: hinglishRatio,
            elongation_rate: elongationRate,
            burstiness: burstiness,
            intimacy: intimacy,
          }
        }),
      })

      if (res.status === 200) {
        const data = await res.json()
        setMessages((prev) => [...prev, { role: data.role, content: data.content }])
        if (data.vibe) {
          setCurrentVibe(data.vibe)
        }
      } else {
        const errData = await res.json().catch(() => ({}))
        setError(errData.detail || "API returned an error. Try again.")
      }
    } catch (err) {
      setError("Failed to send message. Check server connection.")
    } finally {
      setLoading(false)
    }
  }



  if (initializing) {
    return (
      <div className="w-full max-w-lg h-[600px] rounded-2xl glass-panel shadow-2xl flex flex-col items-center justify-center">
        <Loader2 className="w-8 h-8 text-purple-500 animate-spin mb-4" />
        <p className="text-gray-400 text-sm">Initializing chat session with {profileName}...</p>
      </div>
    )
  }

  return (
    <div className="w-full max-w-lg h-[600px] rounded-2xl glass-panel shadow-2xl flex flex-col overflow-hidden relative border border-white/5">
      {/* Header Area */}
      <div className="px-6 py-4 border-b border-white/5 bg-charcoal-900/60 flex items-center justify-between z-10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-purple-600/35 border border-purple-500/20 flex items-center justify-center font-bold text-white text-lg select-none">
            {profileName[0]}
          </div>
          <div>
            <h3 className="font-semibold text-white leading-tight">{profileName}</h3>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-[10px] text-green-400 flex items-center gap-1 font-medium bg-green-950/30 border border-green-500/20 px-1.5 py-0.5 rounded-full">
                <span className="w-1 h-1 rounded-full bg-green-400 animate-pulse" /> active
              </span>
              {currentVibe && (
                <span className="text-[10px] bg-purple-950/40 border border-purple-500/20 text-purple-300 px-2 py-0.5 rounded-full font-medium tracking-wide">
                  {currentVibe === "emotional" && "❤️ emotional"}
                  {currentVibe === "excited" && "🥳 excited"}
                  {currentVibe === "humor" && "🤪 banter"}
                  {currentVibe === "question" && "🧐 answering"}
                  {currentVibe === "planning" && "📅 planning"}
                  {currentVibe === "casual" && "💬 casual"}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowSettings(!showSettings)}
            className={`p-2 rounded-lg hover:bg-white/5 active:bg-white/10 transition ${showSettings ? "text-purple-400" : "text-gray-400 hover:text-white"}`}
            title="Tweak Persona settings"
          >
            <Settings className="w-5 h-5" />
          </button>
          <button
            onClick={onBack}
            className="p-2 rounded-lg hover:bg-white/5 active:bg-white/10 text-gray-400 hover:text-white transition"
            title="Exit Session"
          >
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Settings Control Panel */}
      {showSettings && (
        <div className="absolute top-[73px] left-0 right-0 bg-[#121214]/95 border-b border-white/5 p-5 z-20 shadow-xl backdrop-blur-md transition-all duration-300">
          <h4 className="text-white text-xs font-bold uppercase tracking-widest mb-4 flex items-center gap-1.5">
            ⚙️ Tonal Tuning Controls
          </h4>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div className="flex flex-col gap-1">
              <label className="flex justify-between text-gray-400 mb-0.5">
                <span>Hinglish Mix</span>
                <span className="font-mono text-purple-400">{Math.round(hinglishRatio * 100)}%</span>
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={hinglishRatio}
                onChange={(e) => setHinglishRatio(parseFloat(e.target.value))}
                className="w-full h-1 bg-purple-950 rounded-lg appearance-none cursor-pointer accent-purple-500"
              />
              <span className="text-[9px] text-gray-500 leading-none">
                {hinglishRatio < 0.3 ? "Mostly English" : hinglishRatio < 0.7 ? "Natural Mix" : "Heavy Hinglish"}
              </span>
            </div>
            
            <div className="flex flex-col gap-1">
              <label className="flex justify-between text-gray-400 mb-0.5">
                <span>Intimacy (Tu-Tad)</span>
                <span className="font-mono text-purple-400">{Math.round(intimacy * 100)}%</span>
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={intimacy}
                onChange={(e) => setIntimacy(parseFloat(e.target.value))}
                className="w-full h-1 bg-purple-950 rounded-lg appearance-none cursor-pointer accent-purple-500"
              />
              <span className="text-[9px] text-gray-500 leading-none">
                {intimacy < 0.3 ? "Casual/Interchangeable" : intimacy < 0.75 ? "Strict 'Tu' & 'Tere'" : "High Closeness"}
              </span>
            </div>

            <div className="flex flex-col gap-1">
              <label className="flex justify-between text-gray-400 mb-0.5">
                <span>Word Elongation</span>
                <span className="font-mono text-purple-400">{Math.round(elongationRate * 100)}%</span>
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={elongationRate}
                onChange={(e) => setElongationRate(parseFloat(e.target.value))}
                className="w-full h-1 bg-purple-950 rounded-lg appearance-none cursor-pointer accent-purple-500"
              />
              <span className="text-[9px] text-gray-500 leading-none">
                {elongationRate < 0.3 ? "Standard Spelling" : elongationRate < 0.7 ? "Occasional Stretching" : "Heavy Stretching (yaaarr)"}
              </span>
            </div>

            <div className="flex flex-col gap-1">
              <label className="flex justify-between text-gray-400 mb-0.5">
                <span>Text Bursting</span>
                <span className="font-mono text-purple-400">{Math.round(burstiness * 100)}%</span>
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={burstiness}
                onChange={(e) => setBurstiness(parseFloat(e.target.value))}
                className="w-full h-1 bg-purple-950 rounded-lg appearance-none cursor-pointer accent-purple-500"
              />
              <span className="text-[9px] text-gray-500 leading-none">
                {burstiness < 0.3 ? "Single-line replies" : burstiness < 0.7 ? "Moderate splits" : "Heavy burst splits"}
              </span>
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <button
              onClick={() => setShowSettings(false)}
              className="px-3 py-1 rounded bg-purple-600 hover:bg-purple-700 active:bg-purple-800 text-white font-medium text-[11px] transition shadow"
            >
              Apply & Close
            </button>
          </div>
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 p-6 overflow-y-auto space-y-2 relative bg-charcoal-900/30">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center px-4">
            <span className="w-12 h-12 rounded-full bg-purple-500/10 text-purple-400 flex items-center justify-center font-bold mb-4 border border-purple-500/10">
              💬
            </span>
            <h4 className="text-white font-medium mb-1">Send a Message</h4>
            <p className="text-gray-500 text-xs max-w-xs">
              Start texting {profileName} in Hinglish or English. Few-shot retrieval will auto-align replies.
            </p>
          </div>
        )}

        {renderedMessages}

        {loading && (
          <div className="flex justify-start mb-4">
            <div className="max-w-[75%] px-4 py-3 rounded-2xl bg-charcoal-700 border border-white/5 shadow-md rounded-tl-sm flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-purple-500 animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="w-2 h-2 rounded-full bg-purple-500 animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="w-2 h-2 rounded-full bg-purple-500 animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
          </div>
        )}

        {error && (
          <div className="p-3 text-xs bg-red-950/40 border border-red-500/20 text-red-200 rounded-lg text-center">
            {error}
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      {/* Input area */}
      <form onSubmit={handleSend} className="p-4 bg-charcoal-900/60 border-t border-white/5 flex gap-2 items-center z-10">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
          placeholder={`Message ${profileName}...`}
          className="flex-1 px-4 py-2.5 text-sm rounded-lg glass-input text-white focus:ring-1 focus:ring-purple-500 placeholder:text-gray-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!input.trim() || loading}
          className="p-2.5 rounded-lg bg-purple-600 hover:bg-purple-700 active:bg-purple-800 disabled:bg-purple-600/30 text-white transition disabled:cursor-not-allowed flex items-center justify-center shrink-0 shadow-md"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  )
}
