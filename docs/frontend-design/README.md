# Handoff: Smart Bookmarks — Unified Extension UI

## Overview
A single visual design language for the Smart Bookmarks browser extension, applied
consistently across its three surfaces:

1. **Toolbar Popup** — quick capture + search (360px wide)
2. **Full-page Library Manager** — browse / filter / edit all bookmarks
3. **Sidebar Chat** — ask questions across saved pages

Previously these three surfaces had diverged (a dark popup, a light manager, a light
chat). This design unifies them on one **mid-slate dark theme with a violet accent**.

## About the Design Files
The file in this bundle (`Smart Bookmarks — Unified Design.html`) is a **design
reference created in HTML** — a prototype showing the intended look, spacing, and
component styling. It is **not production code to ship directly.**

The task is to **recreate these designs inside the extension's actual codebase**,
using its established framework and patterns (the current extension appears to be a
WebExtension with separate popup / options / sidebar documents — implement each
surface in whatever HTML/CSS/JS or framework that codebase already uses). If no
front-end conventions exist yet, plain HTML + CSS variables (as used in the
reference) is a perfectly good target.

The reference page also includes a "Tweaks" panel (React) used during design
exploration — **that panel is not part of the product** and should not be ported.
It only existed to tune the tokens below. The final, locked token values are
recorded in this README.

## Fidelity
**High-fidelity (hifi).** Colors, typography, spacing, and component states are final.
Recreate the UI to match. Exact values are in **Design Tokens** below.

---

## Design Tokens

All values are exposed as CSS custom properties on `:root` in the reference file.
These are the **locked** defaults.

### Color — surfaces (mid-slate)
| Token | Value | Use |
|---|---|---|
| page canvas | `#14171c` | Outermost background (behind any framed surface) |
| `--bg` | `#1e2228` | Base background of a surface; chat stream fade target |
| `--surface` | `#2a2f37` | Primary panel / card background |
| `--surface-2` | `#323843` | Raised: inputs, list rows, recent items, header bars |
| `--surface-3` | `#3a414c` | Hover state of raised elements |
| `--border` | `rgba(255,255,255,0.07)` | Hairline dividers & card borders |
| `--border-strong` | `rgba(255,255,255,0.12)` | Stronger borders (ghost buttons, checkboxes) |

### Color — text
| Token | Value | Use |
|---|---|---|
| `--text` | `#e8eaef` | Primary text |
| `--text-2` | `#a3acba` | Secondary text, body copy in tables |
| `--text-3` | `#727b8a` | Muted: placeholders, meta, dates, eyebrows |

### Color — accent (violet) + danger
| Token | Value | Use |
|---|---|---|
| `--accent` | `#7c6ff0` | Primary accent (button base, active states) |
| `--accent-hover` | `#9489f3` | Lighter violet (gradient top, hover, links, brand text) |
| `--accent-soft` | `rgba(124,111,240,0.16)` | Tinted fills: tags, active nav, badges |
| `--accent-line` | `rgba(124,111,240,0.38)` | Borders on tinted elements |
| `--danger` | `#df6360` | Destructive (Delete button) |
| `--danger-soft` | `rgba(223,99,96,0.16)` | Reserved for danger tints |

### Shape & rhythm
| Token | Value | Notes |
|---|---|---|
| `--radius` | `10px` | Buttons, inputs, cards |
| `--radius-sm` | `7px` | Recent items, small chips, preview box |
| `--row-pad` | `8px 14px` | Table cells & recent items (tight density) |
| `--recent-gap` | `7px` | Gap between popup recent items |
| pill radius | `999px` | Tags & count badges |

### Typography
- **Font family:** `-apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, "Segoe UI", Arial, system-ui, sans-serif` (system neutral sans)
- **Monospace** (URLs/meta accents only): `"SF Mono", ui-monospace, "Roboto Mono", Menlo, Consolas, monospace`
- Body / list text: **14px**, line-height 1.45
- Antialiasing: `-webkit-font-smoothing: antialiased`

| Role | Size | Weight | Other |
|---|---|---|---|
| Popup brand title | 18px | 700 | color `--accent-hover`, letter-spacing −0.01em |
| Manager header `h2` | 18px | 700 | letter-spacing −0.01em |
| Manager "All Bookmarks" `h3` | 20px | 700 | |
| Section eyebrow / column title | 11px | 600 | uppercase, letter-spacing 0.14em, color `--text-3` |
| Body / row text | 14px | 400–600 | |
| URL link | 13px | 400 | color `--accent-hover` |
| Date / meta | 13px | 400 | color `--text-3`, `font-variant-numeric: tabular-nums` |
| Tag | 12px | 600 | |

---

## Shared Components

These are styled once and reused on every surface.

### Primary button (`.btn`)
- Background: `linear-gradient(180deg, var(--accent-hover), var(--accent))`
- Text: `#fff`, 14px, weight 650
- Radius `--radius`
- Shadow: `0 1px 0 rgba(255,255,255,0.18) inset, 0 6px 16px -8px var(--accent)`
- Hover: `filter: brightness(1.06)` · Active: `translateY(1px)`

### Ghost button (`.btn.ghost`)
- Background `--surface-2`, text `--text`, border `1px solid --border-strong`, no glow. Weight 600.

### Danger button (`.btn.danger`)
- Background `linear-gradient(180deg, #e8716e, var(--danger))`, white text, danger-colored glow.

### Input (`.field`)
- Background `--surface-2`, border `1px solid --border`, radius `--radius`, padding `11px 13px`, text `--text`, 14px
- Placeholder color `--text-3`
- Focus: border `--accent-line` + `box-shadow: 0 0 0 3px var(--accent-soft)`
- Readonly variant (`.field.readonly`): text color `--text-3`

### Tag pill (`.tag`)
- Height 22px, padding `0 9px`, radius 999px, 12px / weight 600
- Background `--accent-soft`, text `--accent-hover`, border `1px solid --accent-line`
- **One single tinted style for every tag** (no per-tag colors).

### Icon button (`.icon-btn`)
- 34×34, radius 9px, background `--surface-2`, border `1px solid --border`, icon color `--text-2`
- Hover: background `--surface-3`, icon `--text`

### Icons
All icons are inline SVG, 1.5–2px stroke, `stroke="currentColor"`, Feather/Lucide-style
line icons. Replace with the codebase's existing icon set if it has one. Icons used:
account (user + arc), logout (door + arrow), bookmark/save (ribbon), library (open book),
gear (settings, unused in final), send (paper-plane), chat (speech bubble), checkbox (rounded square).

---

## Screens / Views

### 1. Toolbar Popup
**Purpose:** Save the current page, search bookmarks, jump to recents, reach the library.

**Layout:** Fixed **360px** wide column. Vertical stack:
- **Header row** (`padding: 16px 16px 4px`, flex, gap 12px, align center):
  - **Left:** account/settings icon button (`.icon-btn`)
  - **Center:** brand title "Smart Bookmarks" (`flex:1`, 18px/700, `--accent-hover`)
  - **Right:** logout icon button (`.icon-btn`)
- **Body** (`padding: 14px 16px 18px`):
  - **Save row** (flex, gap 9px, margin-bottom 12px):
    - **"Save Current Page"** primary button (`flex:1`, padding 13px, 15px text, bookmark icon + label)
    - **Manage Library** icon button — `.btn.ghost`, 48px wide, square, open-book icon, `title="Manage Library"`. *(This was previously a full-width button at the bottom that got clipped with many bookmarks — it now lives in the fixed header area so it never scrolls away.)*
  - **Search input** — `.field`, placeholder "Ask your bookmarks…"
  - **"RECENT"** eyebrow label (11px uppercase, `--text-3`, margin `16px 2px 9px`)
  - **Recent list** — vertical flex, gap `--recent-gap`. Each item (`.recent-item`):
    - Background `--surface-2`, border `--border`, radius `--radius-sm`, padding `--row-pad`, 14px text
    - Single-line, ellipsis-truncated
    - Leading 7×7 accent square (`--accent-line`) as a faux favicon dot, gap 10px
    - Hover: background `--surface-3`, border `--border-strong`
    - The list is the scrolling region; header + save row stay fixed.

**Copy:** Recent items shown: "Ideas — Noah Zender", "Getting started with uv",
"How do I run two isolated instances of fi…", "Installation - Claude-Mem",
"abis330/bge-small-en-v1.5: bge-small-e…", etc. (real titles, ellipsis on overflow).

### 2. Full-page Library Manager
**Purpose:** Browse, filter by tag, search, and edit/delete bookmarks.

**Layout:** Full-width surface. Vertical:
- **Header bar** (`padding: 18px 24px`, `linear-gradient(100deg, var(--surface-2), var(--surface))`, bottom border):
  - 30×30 logo tile (radius 8px, `--accent-soft` bg, `--accent-line` border, open-book icon, `--accent-hover`)
  - Title "Smart Bookmark Manager" (18px/700)
  - A 2px accent underline gradient bleeds along the bottom edge (`linear-gradient(90deg, var(--accent), transparent 55%)`).
- **Body grid:** `grid-template-columns: 228px 1fr 300px`, min-height 560px.
  - **Left column — Tags** (`padding 18px`, right border):
    - "TAGS" column title
    - Nav list (`.tag-nav a`): padding `8px 10px`, radius 8px, 14px, `--text-2`. Each row = 8×8 dot + label + right-aligned count badge (pill, `--surface-2` bg).
    - Hover: `--surface-2` bg. **Active** (e.g. "All Bookmarks"): `--accent-soft` bg, `--accent-hover` text+dot, weight 600, count badge tinted.
    - Items: All Bookmarks (active), Untagged, AI (3), Claude (2), Cloud (1), Deployment (1), Firefox (1), ML (1), Tools (1).
  - **Center column — Table** (`padding 18px 18px 0`, right border):
    - Top row: `h3` "All Bookmarks" + search `.field` (max-width 280px, placeholder "Search title or URL…")
    - Table (`.table`, 14px): columns **[checkbox] · Title · URL · Tags · Date**
      - `th`: 11px uppercase, `--text-3`, bottom border `--border`
      - `td`: padding `--row-pad`, bottom border `--border`, `--text-2`
      - Title cell: `--text`, weight 600, truncated (≈34% width)
      - URL cell: `<a>` `--accent-hover`, 13px, truncated max 220px, underline on hover
      - Date cell: `--text-3`, 13px, tabular-nums
      - Row hover: `--surface-2`. **Selected row** (`.sel`): `--accent-soft` bg + `inset 2px 0 0 var(--accent-hover)` left rail.
      - Checkbox (`.cb`): 16×16, radius 5px, 1.5px `--border-strong` border, `--surface-2` fill.
  - **Right column — Details** (`padding 18px`):
    - "DETAILS" column title
    - Field groups, each with an 11px uppercase label (`--text-3`) above a `.field`:
      - **Title** — editable input ("Installation - Claude-Mem")
      - **URL** — readonly input + "Open ↗" link (`--accent-hover`) below
      - **Tags (comma separated)** — input ("AI, Claude")
      - **Content Preview** — `.preview` box (`--surface-2`, italic `--text-3`): "No content available."
    - **Actions row** (flex, gap 10px, margin-top 22px): "Save Changes" primary button (`flex:1`) + "Delete" danger button (auto width).

### 3. Sidebar Chat
**Purpose:** Conversational Q&A over saved bookmarks.

**Layout:** **360px** wide, **flex column, ~620px tall** (full sidebar height in production):
- **Title bar** (`.bar`, `--surface-2`, bottom border, padding `14px 16px`, space-between): "Smart Bookmarks" (15px/700) + close ✕ (`--text-3`).
- **Subheader** (`.sub`, padding `13px 16px`, bottom border): "Chat" (15px/650) + speech-bubble icon in `--accent-hover`.
- **Message stream** (`.stream`, flex:1, scrolls, padding 16px, gap 12px, background `linear-gradient(180deg, var(--surface), var(--bg))`):
  - **Assistant bubble** (`.bubble.bot`): left-aligned, max 80%, `--surface-2` bg, `--border`, radius 14px with 5px bottom-left corner, `--text`.
  - **User bubble** (`.bubble.me`): right-aligned, accent gradient (`--accent-hover`→`--accent`), white text, radius 14px with 5px bottom-right corner, accent glow.
  - **Source citations** (optional, inside an assistant bubble): a `.cite` flex-wrap row of `.tag` pills referencing matched bookmarks (e.g. "Installation - Claude-Mem", "AI"). Use when the answer is grounded in saved pages.
- **Composer** (`.compose`, `--surface-2`, top border, padding 12px, flex gap 9px): `.field` input ("Ask a question…") + **send button** (`.send`, 40×40, radius 10px, accent gradient, paper-plane icon, white).

**Copy in mock:** Bot "Hello! Ask me anything about your saved bookmarks." → User "Hi!" →
Bot "I couldn't find any relevant bookmarks to answer your question." → (example grounded answer with citation chips).

---

## Interactions & Behavior
- **Popup → Save Current Page:** captures the active tab (title + URL), prepends it to Recent.
- **Popup → Manage Library icon:** opens the full-page manager (new tab / options page).
- **Popup → account icon (left):** settings/account. **logout icon (right):** signs out.
- **Popup → search field:** "Ask your bookmarks…" filters/searches saved items.
- **Manager → tag nav:** filtering the table by tag; active item gets `--accent-soft` treatment; counts reflect filtered totals.
- **Manager → row click:** selects the row (`.sel`) and loads it into the Details panel.
- **Manager → Save Changes / Delete:** persist edits / remove the bookmark (confirm before delete recommended).
- **Manager → search:** filters by title or URL.
- **Chat → send:** appends a user bubble, then an assistant bubble; ground answers in matched bookmarks and render citation chips when available; show a "no relevant bookmarks" bot message otherwise.
- **Hover/focus states:** as specified per component above. Inputs use the accent focus ring (`0 0 0 3px var(--accent-soft)`).
- **Transitions:** subtle — background/border color 0.12–0.15s; button `brightness` 0.15s + 0.05s active translate. Nothing elaborate.

## State Management
- **Bookmarks collection:** `{ id, title, url, tags[], date, contentPreview }`.
- **Popup:** recent list (most-recent N), search query, current-tab capture state.
- **Manager:** active tag filter, search query, selected bookmark id, editable Details form (title/tags), checkbox multi-select set.
- **Chat:** message list `[{ role: 'user'|'assistant', text, citations?: bookmarkRef[] }]`, input value, pending/loading flag.
- **Tags:** derived from the bookmark set with counts; "Untagged" = bookmarks with empty tags.

## Responsive Behavior
- **Popup** and **Sidebar** are fixed-width (360px) by extension convention; only the
  recent list / message stream scroll. Headers and composer/save row stay pinned.
- **Manager** is the only fluid surface: the center column (`1fr`) flexes; side columns
  are fixed (228px / 300px). Consider collapsing the Details column to a drawer below a
  narrow breakpoint.

## Assets
- **Icons:** inline line-style SVGs (Feather/Lucide equivalents) — account, logout,
  bookmark, open-book/library, paper-plane (send), speech-bubble, checkbox. Swap for the
  codebase's existing icon library where possible.
- **No raster images or logos** are required by this design. The "favicon" dots in the
  popup are CSS squares; replace with real favicons if available.
- **Fonts:** system font stack — no web-font files to bundle.

## Files
- `Smart Bookmarks — Unified Design.html` — the hi-fi reference for all three surfaces
  (this is the source of truth; all tokens live in its `:root`).
- `screenshots/01-popup-and-chat.png` — rendered Toolbar Popup + Sidebar Chat.
- `screenshots/02-manager.png` — rendered Full-page Library Manager (with Details panel).
- *(Not for production — excluded intentionally:)* the `tweaks-panel.jsx` / `tweaks-app.jsx`
  design-exploration controls. Do not port them.
