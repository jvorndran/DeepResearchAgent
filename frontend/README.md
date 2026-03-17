# Frontend - Deep Financial Research Agent

Next.js frontend with shadcn/ui and Recharts for interactive financial research visualizations.

## Setup

### 1. Install Dependencies

```bash
npm install
```

### 2. Environment Configuration

Copy `.env.local.example` to `.env.local` and fill in your keys:

```bash
cp .env.local.example .env.local
```

Required environment variables:
- `NEXT_PUBLIC_API_URL` - Backend API URL (http://localhost:8000)
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` - Clerk public key
- `CLERK_SECRET_KEY` - Clerk secret key

### 3. Run Development Server

```bash
npm run dev
```

Open http://localhost:3000 in your browser.

## Project Structure

```
frontend/
├── src/
│   ├── app/                # Next.js App Router
│   │   ├── (auth)/         # Clerk sign-in/sign-up pages
│   │   ├── dashboard/      # User's reports & history
│   │   ├── api/            # Next.js API routes (optional)
│   │   ├── layout.tsx      # Root layout
│   │   └── page.tsx        # Homepage
│   │
│   ├── components/         # UI Components
│   │   ├── ui/             # shadcn/ui base components
│   │   ├── charts/         # Recharts wrappers
│   │   │   └── InteractiveChart.tsx
│   │   └── chat/           # Chat interface
│   │       └── ChatInterface.tsx
│   │
│   ├── lib/                # Utilities
│   │   └── api.ts          # Backend API client
│   │
│   └── types/              # TypeScript definitions
│       └── index.ts        # Shared types
│
├── public/                 # Static assets
├── package.json
└── tsconfig.json
```

## Features

### Chat Interface
- Multi-turn clarification flow
- Real-time message updates
- Loading states

### Interactive Charts
- Line, bar, and area charts using Recharts
- Hover tooltips with data points
- Responsive design

### Authentication
- Clerk integration for secure login
- Protected routes
- User session management

## Adding shadcn/ui Components

```bash
npx shadcn@latest add button
npx shadcn@latest add card
npx shadcn@latest add input
# etc.
```

Components will be added to `src/components/ui/`

## Building for Production

```bash
npm run build
npm start
```

## Implementation Status

### ✅ Completed
- [x] Project structure with src/ directory
- [x] TypeScript types matching backend
- [x] API client stubs
- [x] Basic chat interface component
- [x] Interactive chart component

### 🚧 In Progress
- [ ] shadcn/ui installation & theming
- [ ] Clerk authentication setup
- [ ] Dashboard page with job history
- [ ] Report viewer with Markdown rendering
- [ ] Job status polling UI

### ⏳ Planned
- [ ] Real-time job status updates
- [ ] Chart customization options
- [ ] Export functionality
- [ ] Mobile responsive design
