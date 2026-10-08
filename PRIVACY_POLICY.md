# 🔒 Privacy Policy for Aishu

**Last Updated:** October 7, 2026  
**Project:** Aishu Discord Bot  
**Owner & Maintainer:** Raghul M ([GitHub: Raghul202](https://github.com/Raghul202))  
**Repository:** [Raghul202/AishuV1](https://github.com/Raghul202/AishuV1)

---

## 1. Introduction

This Privacy Policy explains how **Aishu** ("the Bot", "we", "our") collects, processes, stores, and manages data when you interact with the Bot in Discord direct messages (DMs), Group DMs, and Discord servers (guilds).

We believe in transparency and user data sovereignty. Aishu only processes and stores data that is strictly required to deliver her core features, conversational memory, emotional continuity, relationship progression, and server administration functionality.

> [!IMPORTANT]
> **AI / Model Training Disclosure:**  
> **Aishu may process and store Discord conversation and message data to provide its core functionality, conversational memory, personalization, and multi-turn context. However, Aishu does NOT use Discord message content to train, fine-tune, or create AI/ML training datasets.**

---

## 2. What Data Aishu Collects and Stores

Aishu stores its data locally in an authoritative SQLite database file (`data/aishu.db`) hosted directly on the Bot's deployment environment.

### A. User Identity & Interaction Data
When you talk with Aishu or execute commands, the following metadata is stored:
- **Discord User ID** (`user_id`): Your unique numeric Discord snowflake identifier (used as the primary key for memory association).
- **Username & Display Name**: Your current Discord username and server display name, used so Aishu addresses you naturally.
- **Timestamps & Counters**: `first_seen`, `last_seen`, total message count with Aishu.
- **Streak Records**: `current_streak`, `longest_streak`, and `last_streak_date` to calculate daily conversational streaks.

### B. Conversation Context (Short-Term Memory / STM)
- A rolling snapshot of your most recent conversation turns (up to **12 messages** per scope).
- Used solely to maintain conversational continuity within multi-turn dialogues so Aishu remembers what was said a few moments ago.
- When you execute `/clear` or `!clear`, this conversation history is immediately wiped from the database.

### C. Personal Facts, Preferences & Topics (Long-Term Memory / LTM)
- **User-Stated Facts & Preferences**: Specific information you share in conversation (e.g. your favorite game, pets, hobbies, timezone) or teach via `/remember <fact>`.
- **Topic Keywords**: Keywords related to conversations you have had with Aishu to facilitate context retrieval.
- **Importance & Mention Counters**: Internal numeric weights (1–10) and mention frequencies used by the memory optimizer to select relevant memories within model token limits.

### D. Emotional Bond & Relationship Metrics
- Numeric scores tracking relationship progression (trust, comfort, warmth, attachment) and relationship tier (`Stranger`, `Friend`, `Close Friend`, `High Trust`, `Special Person`, `Life Partner`).
- Relationship metrics are computed locally and are never shared across unrelated servers.

### E. Server / Guild Configuration Data
- **Guild ID & Guild Name**: Unique Discord server identifier.
- **Server Preferences**: Configured auto-reply channel ID, quiet mode toggles, guild cooldown duration, relationship tracking mode, and guild memory enable/disable toggles.
- **Server Topics**: A rolling buffer of recent server discussion topics (up to 20 topics) to help Aishu engage naturally in designated server channels.

### F. Partner-Private & Roleplay Data (1-on-1 DM Only)
- For the designated life partner in private 1-on-1 direct messages:
  - Separate private STM and private LTM buckets.
  - Active roleplay session data: character roles, scene description, tone, episode memories, and story summary.
  - **Data Boundary Guarantee:** Partner roleplay data, intimate dialogue, and private partner memories are strictly quarantined to 1-on-1 DMs and are never accessible or exposed in public servers, Group DMs, or general user lookups.

---

## 3. What Data Aishu Does NOT Collect

- **No Perpetual Message Logging:** Aishu does not record or store your entire Discord message history across servers.
- **No Private Personal Credentials:** Aishu never asks for, records, or stores passwords, payment credentials, financial details, or government IDs.
- **No IP Address Logging:** Aishu does not log user IP addresses. Web dashboard access logs only record authenticated administration requests.
- **No Cross-Platform Tracking:** Aishu does not track your activity outside of Discord channels where she is present and mentioned/active.

---

## 4. How Data Is Processed and Shared

### A. Third-Party AI Inference Providers
To generate intelligent natural language replies and AI art, Aishu sends an assembled text prompt (containing Aishu's persona instructions, relevant memory snippets from your profile, and recent short-term messages) via secure HTTPS to external AI model providers:
- **OpenRouter** (OpenRouter API)
- **Groq Cloud** (Groq API)
- **NVIDIA NIM** (NVIDIA API)
- **Google AI Studio / Gemini** (Google GenAI API)
- **Cloudflare Workers AI** (Cloudflare API)
- **HuggingFace Inference API** (Partner route only)
- **Pollinations.ai** (Image generation only)

These third-party providers process the prompt strictly in real time to generate text or image completions in accordance with their respective developer privacy policies. Data is not sold or commercialized.

### B. Third-Party Data Sharing
- Aishu does **NOT** sell, rent, monetize, or share your data with advertisers, data brokers, or marketing platforms.
- Data is only transmitted to Discord (via the official Discord Gateway & REST API) and the AI inference providers necessary to generate responses.

---

## 5. Data Privacy Boundaries (Server Channels vs. DMs vs. Group DMs)

Aishu enforces strict data boundaries:
1. **Public Server Channels:** Only public relationship tiers, server configs, and user-associated public memories are accessed. Partner-private relationship details and roleplay story moments are strictly blocked.
2. **Multi-User Group DMs:** Treated as multi-user public spaces. Aishu requires direct mentions or name addressals, and private partner roleplay/intimate memories remain inaccessible.
3. **1-on-1 Direct Messages:** Private conversational memory and partner roleplay are active exclusively in authenticated 1-on-1 DMs.
4. **Command Privacy:** Personal commands such as `/memories`, `/export`, `/bond`, and `/moments` are returned as ephemeral responses or restricted to self-viewing to prevent unauthorized inspection by other guild members.

---

## 6. User Rights & Data Controls

In accordance with Discord Developer Policies and standard privacy practices, you have full control over your stored data:

- **View Your Stored Data:**  
  Run `/memories` (slash command) or `!memories` (prefix command) to see what Aishu remembers about you.
- **Export Your Stored Data:**  
  Run `/export` or `!export` to receive a complete, structured JSON export of all your stored data (`aishu_memory_<your_id>.json`).
- **Delete Specific Memories:**  
  Run `/forget <keyword>` or `!forget <keyword>` (e.g. `/forget gaming`) to delete all memories matching that topic.
- **Completely Wipe All Your Data:**  
  Run `/clear` or `!clear` to delete all your short-term conversation context, topic candidates, and long-term memory records from the database.
- **Global Owner Reset:**  
  Server/bot owners can invoke `/adminreset` to globally purge all user memory across the instance.

---

## 7. Data Retention and Security

- **Storage Location:** All data is stored in the local SQLite database file (`data/aishu.db`) on the host running the bot instance.
- **Security Measures:** The database uses WAL (Write-Ahead Logging), parameter-bound SQL queries (preventing SQL injection), thread locks to avoid race conditions, and strict SSRF address filtering to protect image analysis endpoints.
- **Retention Period:** User memories remain stored until you delete them via `/forget`, wipe them via `/clear`, or until the bot database is reset by the bot administrator.

---

## 8. Compliance with Discord Policies

Aishu operates in strict compliance with the **[Discord Developer Terms of Service](https://discord.com/developers/docs/policies-and-agreements/developer-terms-of-service)** and **[Discord Developer Policy](https://discord.com/developers/docs/policies-and-agreements/developer-policy)**:
- We respect user privacy and provide easy data deletion controls.
- Message data is processed strictly for real-time bot interaction and conversational context.
- We do not use Discord message content to train machine learning models.

---

## 9. Contact & Inquiries

If you have questions regarding this Privacy Policy, your stored data, or wish to request manual data removal, please contact:

- **Maintainer:** Raghul M
- **GitHub:** [@Raghul202](https://github.com/Raghul202)
- **Repository:** [Raghul202/AishuV1](https://github.com/Raghul202/AishuV1)
