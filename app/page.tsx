"use client"

import React, { useState } from "react"
import SetupForm from "../components/SetupForm"
import ChatWindow from "../components/ChatWindow"

export default function Home() {
  const [session, setSession] = useState<{
    profileName: string
    passcode: string
  } | null>(null)

  const handleSetupSuccess = (profileName: string, passcode: string) => {
    setSession({ profileName, passcode })
  }

  const handleBack = () => {
    setSession(null)
  }

  return (
    <main className="min-h-screen w-screen flex flex-col items-center justify-center p-4 bg-charcoal-900 overflow-x-hidden relative select-none">
      {/* Dynamic Background Accents */}
      <div className="absolute top-1/4 left-1/4 w-[350px] h-[350px] bg-purple-600/5 rounded-full blur-3xl -z-10" />
      <div className="absolute bottom-1/4 right-1/4 w-[350px] h-[350px] bg-indigo-600/5 rounded-full blur-3xl -z-10" />
      
      {!session ? (
        <SetupForm onSuccess={handleSetupSuccess} />
      ) : (
        <ChatWindow
          profileName={session.profileName}
          passcode={session.passcode}
          onBack={handleBack}
        />
      )}
    </main>
  )
}
