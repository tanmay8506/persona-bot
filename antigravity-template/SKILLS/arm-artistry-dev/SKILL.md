---
name: arm-artistry-dev
description: Core development guidelines, brand tokens, database schemas, and step-by-step roadmap for the ARM Artistry Next.js + Supabase migration. Use this skill whenever building or editing pages, layouts, styles, database configurations, API routes, or emails.
---

# ARM Artistry Development Guide

This skill acts as the unified project manual for rebuilding the ARM Artistry makeup atelier website using the Free Stack (Next.js 14, Supabase, Resend, Cloudinary, Vercel).

---

## 1. Brand Identity & Design System

### Colors (Tailwind Custom Config)
- **Primary/Heading**: `--gold` (`#D4AF37`) — Luxury accents, headers, active states.
- **Secondary/Hover**: `--terracotta` (`#C97B4A`) — Secondary elements, hover changes.
- **Background**: `--stone` (`#1A1A1A`) — Solid deep charcoal background.
- **Surface**: `--bone` (`#F5F5DC`) — Light section backgrounds (if used).
- **Cards**: `--bone-dark` (`#E8E4D0`) — Surface cards on bone sections.

### Typography
- **Headings**: `Playfair Display` (Bold 700 / ExtraBold 800)
- **Body & UI**: `Inter` (Regular 400 / Medium 500 / Semibold 600)

### CSS Utility Layouts
- **Dynamic Viewports**: Use `.h-screen-safe` (resolves to `100dvh` for iOS Safari toolbar stability).
- **Gold Gradient Text**: Use `.text-gold-gradient` utility class.

---

## 2. Core Technical Architecture

### Tech Stack
- **Framework**: Next.js 14 (App Router)
- **Styling**: Tailwind CSS
- **Animations**: GSAP 3 (Free plugins only) + Lenis 1 (for smooth scroll)
- **Database & Auth**: Supabase JS (Magic Links for clients, Email/Password for admin)
- **Asset CDN**: Cloudinary (for portfolio assets and WebP optimization)
- **Mailing**: Resend SDK (for transactional client emails)
- **Cron Jobs**: Vercel Cron

### Timezone Safety
- **Target timezone**: Indian Standard Time (`Asia/Kolkata` / IST).
- **Rule**: All availability calculations, date formatting, and slot bookings must use `date-fns-tz` (`fromZonedTime` and `toZonedTime`) to prevent drift when executed on UTC serverless environments.

---

## 3. Database Schema

All tables and schemas must align with these details:
- **`settings`**: Configuration table containing working hours (e.g. 09:00 to 18:00 IST).
- **`service_tiers`**: Services pricing and durations.
- **`bookings`**: Client bookings with status values: `held`, `pending`, `confirmed`, `completed`, `cancelled`. Contains `held_until` for reservations.
- **`portfolio_assets`**: Path, title, category, display order, and dimensions (width/height) to avoid layout shifts.

### Atomic Concurrency Control (`hold_slot` RPC)
To prevent double bookings, the database uses a PostgreSQL transaction function that deletes expired holds, checks for overlapping ranges, and inserts a 15-minute held row in a single locked transaction:
```sql
CREATE OR REPLACE FUNCTION hold_slot(
  p_client_id UUID,
  p_service_tier_id UUID,
  p_start_time TIMESTAMPTZ,
  p_end_time TIMESTAMPTZ,
  p_hold_duration INTERVAL DEFAULT INTERVAL '15 minutes'
) RETURNS UUID AS $$
...
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

---

## 4. 5-Stage Roadmap & Execution Prompts

Follow this sequence exactly, applying the Master Execution Prompts at each stage:

### Stage 1: Foundation & Physics (Zero UI)
1. **Next.js Init**: Setup TypeScript, Tailwind, and ESLint.
2. **GSAP & Lenis Setup**: Wire smooth scrolling into `gsap.ticker` to avoid double-RAF issues.
3. **Cursor**: Build a custom `CustomCursor` using `gsap.quickTo` and raw DOM refs (no state).

### Stage 2: Static Visual Scaffolding (No Backend)
1. **Components**: Build `Navbar`, `Footer`.
2. **Home/Service/Portfolio UI**: Implement beautiful mock layouts. Force image dimensions (`aspect-*`) for zero CLS.

### Stage 3: The Supabase Brain (Backend Only)
1. **Database Schema**: Execute SQL schemas & RLS.
2. **API Routes**: Write `/api/availability`, `/api/bookings/hold`, `/api/bookings/confirm`.

### Stage 4: Connecting the Nerves (Frontend ↔ Backend)
1. **Wiring**: Connect frontend cards to database queries.
2. **Booking Flow**: Implement the `IDLE -> HOLDING -> CONFIRMED` state machine.
3. **Authentication**: Wire up Magic Link logins and middleware route guards.

### Stage 5: Admin & Automation (The Final Polish)
1. **Admin Control**: Build dashboard to approve/decline appointments and upload images.
2. **Emails**: Integrate Resend SDK templates (Request Receipt, Confirmation, Reminder, Decline).
3. **Cron Jobs**: Secure and configure `/api/cron/reminders` for daily runs.
