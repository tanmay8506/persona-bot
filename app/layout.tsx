import "./globals.css"
import React from "react"

export const metadata = {
  title: "Persona Bot — Talk to a Clone",
  description: "A high-fidelity persona cloning chatbot running on Next.js, FastAPI, and Supabase pgvector.",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0" />
      </head>
      <body>
        {children}
      </body>
    </html>
  )
}
