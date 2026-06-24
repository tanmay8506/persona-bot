import React, { useState, useEffect } from "react"
import { Key, Users, ArrowRight, CheckCircle2, AlertCircle, Upload, Plus, Sparkles, X } from "lucide-react"


interface SetupFormProps {
  onSuccess: (profileName: string, passcode: string) => void
}

export default function SetupForm({ onSuccess }: SetupFormProps) {
  const [passcode, setPasscode] = useState("")
  const [profiles, setProfiles] = useState<Array<{ name: string }>>([])
  const [selectedProfile, setSelectedProfile] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [authSuccess, setAuthSuccess] = useState(false)

  // Upload States
  const [showUpload, setShowUpload] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [newName, setNewName] = useState("")
  const [newAliases, setNewAliases] = useState("")
  const [uploading, setUploading] = useState(false)
  const [uploadSuccess, setUploadSuccess] = useState("")

  // Load passcode from localStorage if previously stored
  useEffect(() => {
    const savedPasscode = localStorage.getItem("persona_bot_passcode")
    if (savedPasscode) {
      setPasscode(savedPasscode)
      validateAndFetch(savedPasscode)
    }
  }, [])

  const validateAndFetch = async (codeToCheck: string) => {
    setLoading(true)
    setError("")
    try {
      const res = await fetch("/api/profiles", {
        headers: {
          "Authorization": `Bearer ${codeToCheck}`,
        },
      })

      if (res.status === 200) {
        const data = await res.json()
        setProfiles(data)
        setAuthSuccess(true)
        localStorage.setItem("persona_bot_passcode", codeToCheck)
        
        // Auto-select first profile if available
        if (data.length > 0) {
          setSelectedProfile(data[0].name)
        }
      } else {
        const errData = await res.json().catch(() => ({}))
        setError(errData.detail || "Invalid passcode. Access denied.")
        setAuthSuccess(false)
      }
    } catch (err) {
      setError("Server connection failed. Make sure dev server is running.")
      setAuthSuccess(false)
    } finally {
      setLoading(false)
    }
  }

  const handlePasscodeSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!passcode.trim()) {
      setError("Passcode cannot be empty.")
      return
    }
    validateAndFetch(passcode.trim())
  }

  const handleStartChat = () => {
    if (!selectedProfile) {
      setError("Please select a target persona profile.")
      return
    }
    onSuccess(selectedProfile, passcode.trim())
  }

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadFile) {
      setError("Please select a chat file to upload.")
      return
    }
    if (!newName.trim()) {
      setError("Please enter the target persona's name.")
      return
    }
    setUploading(true)
    setError("")
    setUploadSuccess("")

    const formData = new FormData()
    formData.append("file", uploadFile)
    formData.append("name", newName.trim())
    formData.append("aliases", newAliases.trim())

    try {
      const res = await fetch("/api/upload_chat", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${passcode.trim()}`,
        },
        body: formData,
      })

      if (res.ok) {
        const result = await res.json()
        setUploadSuccess(result.message || "Persona uploaded successfully!")
        setNewName("")
        setNewAliases("")
        setUploadFile(null)
        await validateAndFetch(passcode.trim())
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || "Failed to upload and parse the chat file.")
      }
    } catch (err) {
      setError("Connection error. Could not upload file.")
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="w-full max-w-md p-8 rounded-2xl glass-panel shadow-2xl relative overflow-hidden">
      {/* Decorative gradients */}
      <div className="absolute -top-20 -left-20 w-40 h-40 bg-purple-500/10 rounded-full blur-3xl" />
      <div className="absolute -bottom-20 -right-20 w-40 h-40 bg-indigo-500/10 rounded-full blur-3xl" />

      <div className="text-center mb-8 relative">
        <h2 className="text-3xl font-extrabold text-white tracking-tight">🎭 Persona Bot</h2>
        <p className="text-gray-400 mt-2 text-sm">Clone personality logs and talk to them</p>
      </div>

      {error && (
        <div className="mb-6 p-4 rounded-lg bg-red-950/40 border border-red-500/20 flex items-start gap-3 text-red-200 text-sm">
          <AlertCircle className="w-5 h-5 shrink-0 text-red-400" />
          <span>{error}</span>
        </div>
      )}

      {!authSuccess ? (
        <form onSubmit={handlePasscodeSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
              Enter Access Passcode
            </label>
            <div className="relative">
              <Key className="absolute left-3 top-3 w-5 h-5 text-gray-500" />
              <input
                type="password"
                placeholder="••••••••••••"
                value={passcode}
                onChange={(e) => setPasscode(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 text-sm rounded-lg glass-input text-white font-mono placeholder:text-gray-600 focus:ring-1 focus:ring-purple-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg bg-purple-600 hover:bg-purple-700 active:bg-purple-800 text-white font-medium text-sm transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading ? "Verifying..." : "Verify Passcode"}
          </button>
        </form>
      ) : (
        <div className="space-y-6">
          <div className="p-4 rounded-lg bg-green-950/30 border border-green-500/20 flex items-center gap-3 text-green-200 text-sm">
            <CheckCircle2 className="w-5 h-5 shrink-0 text-green-400" />
            <span>Passcode authorized successfully.</span>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
              Select Target Clone Persona
            </label>
            <div className="relative">
              <Users className="absolute left-3 top-3 w-5 h-5 text-gray-500" />
              {profiles.length > 0 ? (
                <select
                  value={selectedProfile}
                  onChange={(e) => setSelectedProfile(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 text-sm rounded-lg glass-input text-white appearance-none cursor-pointer focus:ring-1 focus:ring-purple-500"
                >
                  {profiles.map((p) => (
                    <option key={p.name} value={p.name} className="bg-charcoal-800 text-white">
                      {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <div className="w-full pl-10 pr-4 py-2.5 text-sm rounded-lg glass-input text-gray-500">
                  No synced profiles in DB. Run build_embeddings.py first!
                </div>
              )}
            </div>
          </div>

          <button
            onClick={handleStartChat}
            disabled={profiles.length === 0}
            className="w-full py-2.5 rounded-lg bg-purple-600 hover:bg-purple-700 active:bg-purple-800 text-white font-medium text-sm transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            Start Chatting <ArrowRight className="w-4 h-4" />
          </button>
          
          {/* Toggle Upload Mode */}
          <div className="pt-4 border-t border-white/10">
            {!showUpload ? (
              <button
                onClick={() => setShowUpload(true)}
                className="w-full py-2 rounded-lg border border-purple-500/30 hover:border-purple-500 bg-purple-500/5 hover:bg-purple-500/10 text-purple-300 font-medium text-xs transition flex items-center justify-center gap-1.5"
              >
                <Plus className="w-3.5 h-3.5" /> Clone New Persona (.txt, .json, .html)
              </button>
            ) : (
              <form onSubmit={handleUploadSubmit} className="space-y-4 pt-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-1.5">
                    <Sparkles className="w-4 h-4 text-purple-400" /> Create Custom Persona
                  </h3>
                  <button
                    type="button"
                    onClick={() => {
                      setShowUpload(false)
                      setError("")
                      setUploadSuccess("")
                    }}
                    className="text-gray-400 hover:text-white"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {uploadSuccess && (
                  <div className="p-3 rounded-lg bg-green-950/40 border border-green-500/20 text-green-200 text-xs">
                    {uploadSuccess}
                  </div>
                )}

                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
                    Chat File
                  </label>
                  <div className="relative">
                    <input
                      type="file"
                      accept=".txt,.json,.html,.htm"
                      onChange={(e) => {
                        if (e.target.files && e.target.files.length > 0) {
                          setUploadFile(e.target.files[0])
                        }
                      }}
                      className="hidden"
                      id="chat-file-upload"
                    />
                    <label
                      htmlFor="chat-file-upload"
                      className="w-full px-4 py-2 rounded-lg glass-input text-gray-300 hover:text-white text-xs border border-dashed border-white/20 hover:border-purple-500/50 cursor-pointer flex items-center justify-center gap-2 transition bg-white/5"
                    >
                      <Upload className="w-4 h-4 text-purple-400" />
                      {uploadFile ? uploadFile.name : "Select WhatsApp / Instagram file"}
                    </label>
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
                    Target Persona Name
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Rahul"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-lg glass-input text-white focus:ring-1 focus:ring-purple-500"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
                    Aliases in chat file (comma separated)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Rahul Sharma, rahul_sharma"
                    value={newAliases}
                    onChange={(e) => setNewAliases(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-lg glass-input text-white focus:ring-1 focus:ring-purple-500"
                    title="Aliases used by the person in the export file (to filter their replies)"
                  />
                  <p className="text-[10px] text-gray-500 mt-1">
                    Helps filter who is who. Exclude your own name.
                  </p>
                </div>

                <button
                  type="submit"
                  disabled={uploading}
                  className="w-full py-2 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-semibold text-xs transition disabled:opacity-50 flex items-center justify-center gap-1.5 shadow-lg shadow-purple-900/20"
                >
                  {uploading ? "Analyzing & Vectorizing..." : "Create Persona"}
                </button>
              </form>
            )}
          </div>
          
          <div className="text-center">
            <button
              onClick={() => {
                setAuthSuccess(false)
                localStorage.removeItem("persona_bot_passcode")
                setPasscode("")
                setShowUpload(false)
                setError("")
                setUploadSuccess("")
              }}
              className="text-xs text-purple-400 hover:text-purple-300 underline"
            >
              Reset Passcode
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
