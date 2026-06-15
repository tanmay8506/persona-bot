import React, { useState, useEffect, useRef } from "react"
import { Send, LogOut, Loader2 } from "lucide-react"

interface Message {
  role: "user" | "assistant"
  content: string
  id?: string
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

  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom of conversation
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

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
        }),
      })

      if (res.status === 200) {
        const data = await res.json()
        setMessages((prev) => [...prev, data])
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

  // Helper to render message content with burst bubbles
  const renderMessageContent = (msg: Message, index: number) => {
    const isUser = msg.role === "user"
    
    // User messages do not burst (they are sent as single messages)
    if (isUser) {
      return (
        <div key={index} className="flex justify-end mb-4">
          <div className="max-w-[75%] px-4 py-2.5 rounded-2xl bg-purple-600 text-white text-[15px] font-normal leading-relaxed rounded-tr-sm shadow-md">
            {msg.content}
          </div>
        </div>
      )
    }

    // Assistant/Clone responses can burst split by newlines (\n)
    const lines = msg.content.split("\n").filter((l) => l.trim() !== "")
    
    // If it's a single line, render normally
    if (lines.length <= 1) {
      return (
        <div key={index} className="flex justify-start mb-4">
          <div className="max-w-[75%] px-4 py-2.5 rounded-2xl bg-charcoal-700 text-gray-100 text-[15px] font-normal leading-relaxed rounded-tl-sm shadow-md border border-white/5">
            {msg.content}
          </div>
        </div>
      )
    }

    // For multi-line responses, render burst bubbles
    return (
      <div key={index} className="flex flex-col items-start gap-1 mb-4">
        {lines.map((line, lineIdx) => {
          const isFirst = lineIdx === 0
          const isLast = lineIdx === lines.length - 1
          
          return (
            <div
              key={lineIdx}
              className={`max-w-[75%] px-4 py-2.5 bg-charcoal-700 text-gray-100 text-[15px] font-normal leading-relaxed shadow-md border border-white/5 transition-all duration-300
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
    )
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
            <span className="text-xs text-green-400 flex items-center gap-1.5 font-medium mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" /> Active Clone
            </span>
          </div>
        </div>
        <button
          onClick={onBack}
          className="p-2 rounded-lg hover:bg-white/5 active:bg-white/10 text-gray-400 hover:text-white transition"
          title="Exit Session"
        >
          <LogOut className="w-5 h-5" />
        </button>
      </div>

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

        {messages.map((msg, index) => renderMessageContent(msg, index))}

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
