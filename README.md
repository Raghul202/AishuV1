# 🌸 Aishu (AI Companion Bot)

> An intelligent, personality-rich, memory-enabled Discord companion bot powered by multi-provider AI model routing and persistent SQLite memory.

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-v2.4%2B-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Database](https://img.shields.io/badge/SQLite-WAL%20Mode-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/Author-Raghul%20M-FF69B4)](COPYRIGHT.md)

**Aishu** is designed to feel like a real friend with her own emotions, memories, and conversational nuance. She supports normal server conversations, private 1-on-1 direct messages, multi-user Group DMs, dynamic partner roleplay, AI image generation/analysis, and includes a built-in real-time Web Dashboard.

---

## ✨ Key Features

- **🧠 Multi-Layered Memory Architecture**:
  - **STM (Short-Term Memory)**: Rolling conversational context (up to 12 turns) to keep discussions coherent across restarts.
  - **UTM (User Topic Memory)**: Topic frequency tracker for promotion candidate memories.
  - **LTM (Long-Term Memory)**: Persistent personal facts, preferences, and topic associations stored in a local SQLite database (`data/aishu.db`).
  - **Partner Private Memory & Roleplay**: Separate private memory bucket for life-partner interactions and dynamic roleplay sessions.
- **⚡ Smart Multi-Provider AI Routing**:
  - Dynamic benchmarking and ranked sequential fallback across **OpenRouter**, **Groq**, **NVIDIA NIM**, **Google Gemini**, **Cloudflare Workers AI**, and **HuggingFace**.
  - Sub-second response times with automatic rate-limit (HTTP 429) cooldown tracking.
- **🎭 Dynamic Mood & Relationship System**:
  - 11 distinct emotional moods (`happy`, `soft`, `flirty`, `excited`, `playful`, `neutral`, `shy`, `bored`, `annoyed`, `sad`, `angry`) with dynamic intensity, energy, and stability.
  - Relationship tier progression (`Stranger` → `Friend` → `Close Friend` → `High Trust` → `Special Person` → `Life Partner`) based on trust, comfort, warmth, attachment scores, and daily streaks.
- **🎨 Creative Vision & Image Generation**:
  - High-speed AI image generation (powered by Pollinations.ai) with toggleable detail embeds.
  - SSRF-hardened image inspection (`/analyzeimage` / `!analyzeimage`) for analyzing attachments and web images.
- **🖥️ Lightweight Web Dashboard**:
  - Real-time web studio running on `aiohttp.web` within the bot's event loop (zero heavy frameworks, optimized for 256MB RAM).
  - Manage bot avatar, banner, username, status, embed theme colors, custom free models, feature toggles, and live system metrics.
- **🔒 Strong Privacy & Data Isolation**:
  - Group DMs and public server channels are strictly isolated from private partner memories and roleplay contexts.
  - Self-viewing privacy protections on emotional bond stats and personal moments.
  - Full GDPR-style user controls: `/export`, `/forget`, `/clear`.

---

## 📋 Commands Reference

Aishu supports both modern **Slash Commands (`/command`)** and **Prefix Commands (`!command`)**.

### 💬 Chat & Creative
| Slash Command | Prefix Command | Description |
| :--- | :--- | :--- |
| `/chat <message>` | `!aishu <msg>` / `!ai` / `!chat` | Chat directly with Aishu. |
| `/continue [prompt]` | `!continue` / `!cont` | Continue the conversation or active roleplay story naturally. |
| `/image <prompt>` | `!image <prompt>` / `!draw` | Generate AI artwork based on your prompt. |
| `/analyzeimage <image>` | `!analyzeimage` / `!analyze` | Let Aishu inspect an image and share her detailed thoughts. |

### 🧠 Memory & Notes
| Slash Command | Prefix Command | Description |
| :--- | :--- | :--- |
| `/memories` | `!memories` / `!mem` | View everything Aishu remembers about you (ephemeral/private). |
| `/remember <text>` | `!remember <fact>` / `!rem` | Teach Aishu a specific fact or preference to remember. |
| `/memorysearch <query>` | `!memorysearch <query>` | Search your stored memories with Aishu. |
| `/forget <keyword>` | `!forget <keyword>` / `!remove` | Release and delete memories related to a specific topic. |
| `/clear` | `!clear` | Reset and wipe both short-term context and long-term memories. |
| `/export` | `!export` | Download an exact JSON export of all your stored data. |

### 💕 Social, Bond & Personality
| Slash Command | Prefix Command | Description |
| :--- | :--- | :--- |
| `/profile [@user]` | `!profile [@user]` / `!p` | View user profile card, message counts, and bond tier. |
| `/bond [@user]` | `!bond [@user]` | View detailed emotional metrics (trust, warmth, attachment) privately. |
| `/relationship` | `!relationship` / `!rel` | Check relationship score and points needed for next tier. |
| `/streak [@user]` | `!streak [@user]` / `!s` | View your daily conversation streak with Aishu. |
| `/leaderboard` | `!leaderboard` / `!lb` / `!top` | Server favorites leaderboard based on relationship score. |
| `/mood` | `!mood` / `!vibe` | Check Aishu's current mood, energy, and score. |
| `/diary` | `!diary` | Read a personal journal entry from Aishu's diary. |
| `/moments [@user]` | `!moments [@user]` | View cherished moments and milestones between you and Aishu. |
| `/persona` | `!persona` | View Aishu's identity, age, personality, and family card. |
| `/afk [reason]` | `!afk [reason]` | Set yourself as AFK across restarts. |
| `/quietmode [on/off]` | `!quietmode` / `!quiet` | Toggle quiet mode (Aishu replies only when directly mentioned). |

### 🎭 Roleplay System (Partner 1-on-1 DM Only)
| Slash Command | Prefix Command | Description |
| :--- | :--- | :--- |
| `/rp_status` | `!rp_status` | View current roleplay scene, tone, character roles, and story summary. |
| `/rp_history` | `!rp_history` | View past archived roleplay sessions. |
| `/rp_end` | `!rp_end` | End and archive the active roleplay session. |
| *Natural Trigger* | — | Say *"let's roleplay, you're my wife"* in DMs to start naturally. |

### 🛡️ Server Administration
| Slash Command | Prefix Command | Description |
| :--- | :--- | :--- |
| `/setchannel [channel]` | `!setchannel [channel]` | Set a dedicated channel where Aishu auto-replies without mentions. |
| `/removechannel` | `!removechannel` | Disable auto-reply channel (mentions only). |
| `/announce <message>` | `!announce <msg>` | Send an announcement embed from Aishu. |
| `/guildconfig` | `!guildconfig` | View server settings (cooldowns, memory toggles, auto-channel). |
| `/purge <count>` | `!purge <count>` | Bulk delete 1-100 messages (requires *Manage Messages*). |

### 👑 Owner & Diagnostics
| Slash Command | Prefix Command | Description |
| :--- | :--- | :--- |
| `/aishu_panel` | — | Interactive personality, identity, and behavior studio. |
| `/setprofile` | `!setprofile` | Update bot avatar, banner, and display name. |
| `/setmood <mood>` | `!setmood <mood>` | Force Aishu into a specific emotional mood. |
| `/setstatus <text>` | `!setstatus <text>` | Update bot presence / status text. |
| `/setpartner <@user>` | `!setpartner <@user>` | Designate Aishu's life partner. |
| `/clearpartner` | `!clearpartner` | Clear Aishu's life partner. |
| `/setlover <@user>` | `!setlover <@user>` | Set Aishu's special person. |
| `/stats` | `!stats` | Global runtime metrics, latency averages, and active users. |
| `/inspect [@user]` | `!inspect [@user]` | Debug prompt assembly, token estimates, and memory context for a user. |
| `/refreshmodel` | `!refreshmodel` / `!probe` | Live benchmark and rank all configured AI models. |
| `/adminreset` | — | Global wipe of all user memory data (owner-only with confirmation). |

---

## 🛠️ Project Structure

```text
Aishu/
├── brain/                         # AI routing, prompt engine, and memory context
│   ├── memory_optimizer.py        # Token-budget context selection
│   ├── model_controller.py        # Multi-provider sequential fallback & rankings
│   ├── prompt_engine.py           # Persona and roleplay prompt assembly
│   ├── reasoning_engine.py        # Intent and sentiment classification
│   └── router.py                  # User concurrency locks and turn serialization
├── commands/                      # Discord command cogs
│   ├── admin_cog.py               # Owner, server admin, and diagnostics
│   ├── application_command_config.py # Global slash command context configuration
│   ├── chat_cog.py                # Main conversation, memories, social commands
│   └── refresh_model_cog.py       # Live model testing and ranking command
├── config/                        # Bot and provider configuration
│   └── settings.py                # API keys, model lists, and limits
├── core/                          # State, persistence, and psychology
│   ├── memory/
│   │   ├── database.py            # SQLite thread-safe persistence (WAL mode)
│   │   ├── memory_manager.py      # User & guild memory cache and eviction
│   │   └── user_memory.py         # STM, UTM, LTM, and serialization logic
│   ├── mood/                      # Mood transitions, intensity, and decay
│   ├── personality/               # AishuState persona and presence state
│   ├── relationship/              # Relationship tier and score tracking
│   ├── roleplay_manager.py        # Partner roleplay session engine
│   └── schemas.py                 # Data models and structures
├── data/                          # Persistent storage (auto-created)
│   └── aishu.db                   # SQLite authoritative database
├── utilities/                     # Shared helpers, rate-limiters, and logger
│   ├── helpers.py
│   ├── image_gen.py               # Image generation and vision analysis
│   ├── logger.py
│   └── ratelimit.py
├── web/                           # Built-in Web Dashboard
│   ├── auth.py                    # Session password authentication
│   └── server.py                  # aiohttp web routes and UI template
├── main.py                        # Bot entry point and lifecycle manager
├── requirements.txt               # Python runtime dependencies
├── .env.example                   # Environment template
├── PRIVACY_POLICY.md              # Privacy Policy and data disclosures
├── TERMS_OF_SERVICE.md            # Terms of Service
└── COPYRIGHT.md                   # Ownership and copyright documentation
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10, 3.11, 3.12, or 3.14.
- A Discord Bot Token with **Message Content Intent**, **Server Members Intent**, and **Presence Intent** enabled in the [Discord Developer Portal](https://discord.com/developers/applications).

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/Raghul202/AishuV1.git
cd AishuV1
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```
Key configuration values in `.env`:
```env
DISCORD_TOKEN=your_discord_bot_token_here
BOT_OWNER_ID=your_discord_numeric_user_id

# AI Providers (add whatever keys you have; Aishu automatically routes to available ones)
OPENROUTER_KEY=your_openrouter_api_key
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_google_gemini_api_key
NVIDIA_API_KEY=your_nvidia_nim_api_key
HF_API_KEY=your_huggingface_api_key

# Web Dashboard
DASHBOARD_ENABLED=true
DASHBOARD_PORT=8080
DASHBOARD_PASSWORD=your_secure_password
```

### 4. Running Aishu
```bash
python main.py
```

---

## 🌐 Web Dashboard

When `DASHBOARD_ENABLED=true`, Aishu starts an ultra-lightweight dashboard on `http://0.0.0.0:8080` (or your configured `PORT`).

- **Authentication**: Protected by `DASHBOARD_PASSWORD`.
- **Live Model Control**: Toggle specific free AI models on/off, add custom OpenRouter models, and view live latency benchmarks.
- **Visual Studio**: Update Aishu's Discord avatar, banner, and display name directly via official Discord APIs.
- **Live Metrics**: Monitor active users, memory count, mood score, and provider health.

---

## 📄 Policies & Legal

- [Privacy Policy](PRIVACY_POLICY.md) — Comprehensive explanation of data processing, storage, and user controls.
- [Terms of Service](TERMS_OF_SERVICE.md) — Terms governing use of Aishu.
- [Copyright & Ownership](COPYRIGHT.md) — Author attribution, ownership rights, and third-party acknowledgments.

---

## 👤 Author & Maintainer

- **Creator & Owner**: **Raghul M** ([@Raghul202](https://github.com/Raghul202))
- **Repository**: [Raghul202/AishuV1](https://github.com/Raghul202/AishuV1)
