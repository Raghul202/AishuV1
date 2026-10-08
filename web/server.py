"""
web/server.py — Ultra-lightweight Feature-Rich Web Dashboard for Aishu.

Runs inside Aishu's existing asyncio event loop using aiohttp.web.
Zero extra background processes, zero heavy frameworks.

Features:
  - 🤖 AI Model Manager: Add/remove custom free models, toggle models, live probe & latency benchmarks.
  - 🎨 Visual & Profile Studio: Live Discord profile card, avatar/banner updater, status/activity controls, embed color picker.
  - 💬 Live Chat Playground: Test chat turns directly from browser with real-time token/latency stats.
  - 🧠 Memory Explorer: Search & browse remembered users, view facts & preferences, delete facts.
  - 💖 Persona & Mood Studio: Instant mood presets, score slider, likes/dislikes, lover & partner bonds.
  - ⚙️ Feature Toggles: Vision / image analysis, image generation result embed toggle, quiet mode, memory.
  - 📜 Live Logs Console: Real-time logs stream with search filtering and log level tags.
  - 📊 System & Discord Metrics: Live gateway ping, guild count, remembered users, SQLite engine health.
  - 🔒 Password-protected dashboard session.
"""

from __future__ import annotations

import asyncio
import base64
import html
import hmac
import io
import ipaddress
import json
import os
import secrets
import socket
import sys
import time
from typing import Optional
from urllib.parse import quote, urlparse

from aiohttp import web
import aiohttp
from aiohttp.abc import AbstractResolver
import discord

import config.settings as cfg
from brain.model_controller import model_controller
from core.memory.memory_manager import memory_manager
from core.personality.aishu_state import aishu_state
from utilities.logger import get_logger

log = get_logger("web.dashboard")


class _PublicAddressResolver(AbstractResolver):
    """Resolver that permits connections only to globally routable addresses."""

    def __init__(self):
        self._resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC) -> list[dict]:
        addresses = await self._resolver.resolve(host, port, family)
        if not addresses or any(not ipaddress.ip_address(item["host"]).is_global for item in addresses):
            raise OSError("Image host resolves to a non-public address")
        return addresses

    async def close(self) -> None:
        await self._resolver.close()


_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aishu Dashboard</title>
{FAVICON_LINK}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg-main: #0B0E17;
  --bg-surface: #121624;
  --bg-card: rgba(18, 22, 36, 0.85);
  --bg-card-hover: rgba(26, 32, 52, 0.95);
  --bg-glass: rgba(255, 255, 255, 0.035);
  --bg-input: rgba(10, 13, 22, 0.7);
  --border: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(168, 85, 247, 0.35);
  --border-focus: #00F5D4;
  
  --cyan: #00F5D4;
  --cyan-glow: rgba(0, 245, 212, 0.25);
  --purple: #A855F7;
  --purple-glow: rgba(168, 85, 247, 0.28);
  --pink: #FF7597;
  --pink-glow: rgba(255, 117, 151, 0.3);
  --discord: #5865F2;
  --discord-dark: #1E1F22;
  --discord-sub: #111214;
  
  --primary: #00F5D4;
  --primary-glow: var(--cyan-glow);
  --accent: #A855F7;
  --success: #10B981;
  --warning: #F59E0B;
  --danger: #EF4444;
  
  --text-main: #F8FAFC;
  --text-muted: #94A3B8;
  --text-dim: #64748B;
  --font: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
  --mono: 'JetBrains Mono', monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg-main);
  background-image: 
    radial-gradient(circle at 10% 10%, rgba(168, 85, 247, 0.12) 0px, transparent 45%),
    radial-gradient(circle at 90% 85%, rgba(0, 245, 212, 0.09) 0px, transparent 45%),
    radial-gradient(circle at 50% 50%, rgba(255, 117, 151, 0.05) 0px, transparent 60%);
  color: var(--text-main);
  font-family: var(--font);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  -webkit-font-smoothing: antialiased;
}

/* Layout */
.container { max-width: 1280px; margin: 0 auto; width: 100%; padding: 24px 20px 60px; }

/* Header */
header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 18px 24px; background: var(--bg-card);
  border: 1px solid var(--border); border-radius: 20px;
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  margin-bottom: 24px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
}

.brand { display: flex; align-items: center; gap: 14px; }
.avatar-badge {
  width: 48px; height: 48px; border-radius: 14px;
  background: linear-gradient(135deg, var(--cyan), var(--purple));
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; box-shadow: 0 0 20px var(--cyan-glow);
  overflow: hidden; border: 1.5px solid rgba(255, 255, 255, 0.25);
  flex-shrink: 0; position: relative;
}
.avatar-badge img { width: 100%; height: 100%; object-fit: cover; }
.brand h1 {
  font-size: 20px; font-weight: 800; letter-spacing: -0.4px;
  background: linear-gradient(135deg, #FFF 30%, var(--cyan) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.brand p { font-size: 13px; color: var(--text-muted); font-weight: 500; margin-top: 1px; }

.header-actions { display: flex; align-items: center; gap: 12px; }

.status-pill {
  padding: 6px 14px; border-radius: 99px; font-size: 12px; font-weight: 700;
  display: flex; align-items: center; gap: 8px;
  background: rgba(16, 185, 129, 0.12); color: #34D399;
  border: 1px solid rgba(16, 185, 129, 0.25);
}
.status-pill::before {
  content: ''; width: 7px; height: 7px; border-radius: 50%;
  background: #34D399; box-shadow: 0 0 10px #34D399;
  animation: pulse-dot 2s infinite ease-in-out;
}
@keyframes pulse-dot { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.85); } }

/* Buttons */
.btn {
  background: var(--bg-glass); color: var(--text-main);
  border: 1px solid var(--border);
  padding: 9px 18px; border-radius: 12px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  display: inline-flex; align-items: center; gap: 7px; font-family: var(--font);
}
.btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.25);
  transform: translateY(-1px);
}
.btn:active { transform: translateY(0); }

.btn-primary {
  background: linear-gradient(135deg, var(--cyan) 0%, #00C4A7 100%);
  color: #080B11; border: none; font-weight: 700;
  box-shadow: 0 4px 18px var(--cyan-glow);
}
.btn-primary:hover {
  box-shadow: 0 6px 24px rgba(0, 245, 212, 0.45);
  transform: translateY(-2px);
  filter: brightness(1.05);
}
.btn-purple {
  background: linear-gradient(135deg, var(--purple) 0%, #9333EA 100%);
  color: #FFF; border: none; font-weight: 700;
  box-shadow: 0 4px 18px var(--purple-glow);
}
.btn-purple:hover {
  box-shadow: 0 6px 24px rgba(168, 85, 247, 0.45);
  transform: translateY(-2px);
}
.btn-danger {
  background: rgba(239, 68, 68, 0.12); color: #FCA5A5;
  border: 1px solid rgba(239, 68, 68, 0.25);
}
.btn-danger:hover {
  background: #EF4444; color: #FFF; border-color: #EF4444;
}

/* Tabs Navigation */
.tabs {
  display: flex; gap: 8px; margin-bottom: 24px;
  background: var(--bg-card); padding: 6px;
  border-radius: 16px; border: 1px solid var(--border);
  backdrop-filter: blur(16px);
  overflow-x: auto;
}
.tab-btn {
  background: transparent; border: none; color: var(--text-muted);
  font-size: 13.5px; font-weight: 600; padding: 10px 16px; border-radius: 11px;
  cursor: pointer; transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex; align-items: center; gap: 8px; white-space: nowrap;
  font-family: var(--font);
}
.tab-btn:hover { color: var(--text-main); background: rgba(255, 255, 255, 0.04); }
.tab-btn.active {
  color: #080B11; font-weight: 700;
  background: linear-gradient(135deg, var(--cyan), #38BDF8);
  box-shadow: 0 4px 16px var(--cyan-glow);
}

/* Grid & Cards */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
@media (max-width: 960px) { .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; } }

.card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 18px; padding: 22px; backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  margin-bottom: 20px; transition: border-color 0.25s, transform 0.2s;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
  position: relative; overflow: hidden;
}
.card:hover { border-color: rgba(255, 255, 255, 0.16); }
.card-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 18px;
}
.card-title {
  font-size: 15px; font-weight: 700; letter-spacing: -0.2px;
  display: flex; align-items: center; gap: 9px; color: var(--text-main);
}

/* Stat Box */
.stat-box {
  background: var(--bg-glass); border: 1px solid var(--border);
  padding: 16px 20px; border-radius: 14px;
}
.stat-label { font-size: 12px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value { font-size: 22px; font-weight: 800; margin: 4px 0 2px; color: #FFF; }
.stat-sub { font-size: 11.5px; color: var(--text-dim); }

/* Form Controls */
.form-group { margin-bottom: 18px; }
.form-label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 7px; color: var(--text-muted); }
.input-text, .select {
  width: 100%; background: var(--bg-input); border: 1px solid var(--border);
  color: var(--text-main); padding: 11px 16px; border-radius: 12px; font-size: 13.5px;
  font-family: var(--font); transition: all 0.2s ease;
}
.input-text:focus, .select:focus {
  outline: none; border-color: var(--cyan);
  box-shadow: 0 0 0 3px rgba(0, 245, 212, 0.15);
}
.select { cursor: pointer; }

/* Switch Toggle */
.switch {
  position: relative; display: inline-block; width: 44px; height: 24px;
}
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
  background-color: rgba(255, 255, 255, 0.1); transition: .3s cubic-bezier(0.16, 1, 0.3, 1);
  border-radius: 34px; border: 1px solid var(--border);
}
.slider:before {
  position: absolute; content: ""; height: 16px; width: 16px; left: 3px; bottom: 3px;
  background-color: white; transition: .3s cubic-bezier(0.16, 1, 0.3, 1);
  border-radius: 50%;
}
input:checked + .slider {
  background-color: var(--cyan);
  box-shadow: 0 0 12px var(--cyan-glow);
}
input:checked + .slider:before {
  transform: translateX(20px);
  background-color: #0B0E17;
}

/* Models List */
.model-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border); border-radius: 12px; margin-bottom: 10px;
  transition: all 0.2s;
}
.model-row:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.15);
}
.model-info { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
.model-tag {
  font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
  text-transform: uppercase; font-family: var(--mono);
}
.tag-groq { background: rgba(249, 115, 22, 0.15); color: #FB923C; border: 1px solid rgba(249, 115, 22, 0.3); }
.tag-cf { background: rgba(234, 88, 12, 0.15); color: #F97316; border: 1px solid rgba(234, 88, 12, 0.3); }
.tag-gemini { background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(59, 130, 246, 0.3); }
.tag-nim { background: rgba(34, 197, 94, 0.15); color: #4ADE80; border: 1px solid rgba(34, 197, 94, 0.3); }
.tag-openrouter { background: rgba(168, 85, 247, 0.15); color: #C084FC; border: 1px solid rgba(168, 85, 247, 0.3); }

.model-name {
  font-family: var(--mono); font-size: 13px; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.model-meta { font-size: 11.5px; color: var(--text-dim); display: flex; gap: 12px; align-items: center; }

/* Discord Card Preview */
.profile-preview-card {
  width: 100%; max-width: 360px; margin: 0 auto;
  background: var(--discord-dark); border-radius: 16px;
  overflow: hidden; box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  font-family: 'gg sans', 'Noto Sans', var(--font);
}
.profile-banner {
  height: 105px; width: 100%;
  background: linear-gradient(135deg, #FF7597, #A855F7, #00F5D4);
  background-size: cover; background-position: center; position: relative;
}
.profile-avatar-wrap {
  position: relative; margin-top: -42px; margin-left: 20px;
  width: 80px; height: 80px;
}
.profile-avatar-img {
  width: 80px; height: 80px; border-radius: 50%;
  border: 6px solid var(--discord-dark); background: #2B2D31;
  object-fit: cover;
}
.profile-status-dot {
  position: absolute; bottom: 2px; right: 2px; width: 22px; height: 22px;
  border-radius: 50%; border: 4px solid var(--discord-dark);
}
.status-online { background: #23A55A; }
.status-idle { background: #F0B232; }
.status-dnd { background: #F23F43; }
.status-invisible { background: #80848E; }

.profile-body {
  padding: 12px 18px 20px; background: var(--discord-dark);
}
.profile-names { display: flex; align-items: baseline; gap: 6px; }
.profile-display-name { font-size: 18px; font-weight: 700; color: #F2F3F5; }
.profile-tag {
  background: var(--discord); color: #FFF; font-size: 9.5px; font-weight: 700;
  padding: 1px 4px; border-radius: 3px; letter-spacing: 0.2px; vertical-align: middle;
}
.profile-activity-box {
  margin-top: 14px; background: var(--discord-sub); padding: 10px 14px;
  border-radius: 8px; font-size: 12.5px; color: #DBDEE1;
}
.profile-bio-box {
  margin-top: 12px; font-size: 12.5px; color: #B5BAC1; line-height: 1.4;
  white-space: pre-wrap; word-break: break-word;
}

/* Chat Playground */
.chat-container {
  display: flex; flex-direction: column; height: 500px;
  background: var(--bg-surface); border-radius: 14px; border: 1px solid var(--border);
  overflow: hidden;
}
.chat-messages {
  flex: 1; overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 14px;
}
.chat-msg {
  display: flex; flex-direction: column; max-width: 80%;
}
.chat-msg.user { align-self: flex-end; align-items: flex-end; }
.chat-msg.assistant { align-self: flex-start; align-items: flex-start; }
.chat-bubble {
  padding: 12px 16px; border-radius: 14px; font-size: 13.5px; line-height: 1.45; word-break: break-word;
}
.chat-msg.user .chat-bubble {
  background: linear-gradient(135deg, var(--cyan) 0%, #00C4A7 100%);
  color: #080B11; font-weight: 600; border-bottom-right-radius: 2px;
}
.chat-msg.assistant .chat-bubble {
  background: var(--bg-card); color: var(--text-main);
  border: 1px solid var(--border); border-bottom-left-radius: 2px;
}
.chat-meta {
  font-size: 10.5px; color: var(--text-dim); margin-top: 4px; font-family: var(--mono);
}
.chat-input-bar {
  display: flex; gap: 10px; padding: 12px 16px; background: var(--bg-card);
  border-top: 1px solid var(--border);
}

/* Log Box */
.log-console {
  background: #05070D; border: 1px solid var(--border); border-radius: 12px;
  padding: 16px; font-family: var(--mono); font-size: 12px; line-height: 1.6;
  height: 480px; overflow-y: auto; color: #CBD5E1; white-space: pre-wrap; word-break: break-all;
}

/* User Memory Table */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
th { padding: 12px 14px; background: rgba(255,255,255,0.03); color: var(--text-muted); font-size: 11.5px; text-transform: uppercase; border-bottom: 1px solid var(--border); }
td { padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--text-main); }
tr:hover td { background: rgba(255,255,255,0.02); }

/* Color Picker */
.color-picker-wrap { display: flex; align-items: center; gap: 12px; }
.color-picker {
  -webkit-appearance: none; border: none; width: 44px; height: 44px;
  border-radius: 12px; cursor: pointer; background: transparent;
}
.color-picker::-webkit-color-swatch-wrapper { padding: 0; }
.color-picker::-webkit-color-swatch { border: 2px solid rgba(255, 255, 255, 0.2); border-radius: 12px; }

/* Toast */
#toast {
  position: fixed; bottom: 24px; right: 24px;
  background: var(--bg-surface); border: 1px solid var(--cyan);
  color: var(--cyan); padding: 12px 20px; border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5); font-size: 13px; font-weight: 600;
  display: none; align-items: center; gap: 8px; z-index: 999;
}
#toast.show { display: flex; animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
@keyframes slideUp { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

/* Auth Modal */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(5, 7, 13, 0.85);
  backdrop-filter: blur(12px); display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-card {
  background: var(--bg-card); border: 1px solid var(--border);
  padding: 32px; border-radius: 20px; width: 100%; max-width: 400px;
  text-align: center; box-shadow: 0 20px 50px rgba(0,0,0,0.6);
}
</style>
</head>
<body>

<div class="modal-overlay" id="authModal" style="display: none;">
  <div class="modal-card">
    <div style="font-size: 44px; margin-bottom: 10px;">🌸</div>
    <h2 style="font-size: 20px; font-weight: 800; margin-bottom: 6px;">Aishu Dashboard</h2>
    <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">Sign in with your verified Discord owner account or backup password</p>
    
    <a href="/auth/discord/login" class="btn" style="width: 100%; justify-content: center; background: #5865F2; color: #FFF; font-weight: 700; margin-bottom: 14px; text-decoration: none; padding: 12px 16px; border-radius: 12px; box-shadow: 0 4px 18px rgba(88,101,242,0.35);">
      <svg width="20" height="15" viewBox="0 0 71 55" fill="none" xmlns="http://www.w3.org/2000/svg" style="margin-right: 6px;"><path d="M60.1 4.9A58.6 58.6 0 0045.6.5a.2.2 0 00-.2.1 40.8 40.8 0 00-1.8 3.7 54.1 54.1 0 00-16.2 0A37.5 37.5 0 0025.6.6a.2.2 0 00-.2-.1A58.4 58.4 0 0010.9 5a.2.2 0 00-.1.1C1.6 18.9-.9 32.3.3 45.6a.2.2 0 00.1.2 58.8 58.8 0 0017.7 9 .2.2 0 00.2-.1c1.4-1.9 2.6-3.8 3.6-6a.2.2 0 00-.1-.3 38.6 38.6 0 01-5.5-2.6.2.2 0 010-.4c.4-.3.7-.6 1.1-.9a.2.2 0 01.2 0 42 42 0 0036 0 .2.2 0 01.2 0c.4.3.8.6 1.1.9a.2.2 0 010 .4 39.3 39.3 0 01-5.5 2.6.2.2 0 00-.1.3c1.1 2.1 2.3 4.1 3.6 6a.2.2 0 00.2.1 58.6 58.6 0 0017.8-9 .2.2 0 00.1-.2c1.4-15.3-2.3-28.7-10.8-40.5a.2.2 0 00-.1-.1zM23.7 37.3c-3.5 0-6.4-3.2-6.4-7.2s2.8-7.2 6.4-7.2c3.6 0 6.5 3.3 6.4 7.2 0 4-2.8 7.2-6.4 7.2zm23.6 0c-3.5 0-6.4-3.2-6.4-7.2s2.8-7.2 6.4-7.2c3.6 0 6.5 3.3 6.4 7.2 0 4-2.8 7.2-6.4 7.2z" fill="white"/></svg>
      Login with Discord ✦
    </a>

    <div style="display: flex; align-items: center; gap: 10px; margin: 16px 0; color: var(--text-dim); font-size: 11px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">
      <span style="flex: 1; height: 1px; background: var(--border);"></span>
      <span>or backup password</span>
      <span style="flex: 1; height: 1px; background: var(--border);"></span>
    </div>

    <input type="password" id="authPassInput" class="input-text" placeholder="Dashboard Password" style="margin-bottom: 12px; text-align: center;" onkeydown="if(event.key==='Enter')login()">
    <button class="btn btn-primary" style="width: 100%; justify-content: center; padding: 11px;" onclick="login()">Password Login ✦</button>
    <p id="authError" style="color: var(--danger); font-size: 12px; margin-top: 12px; display: none;">Invalid credentials or unauthorized account.</p>
  </div>
</div>

<div class="container">
  <!-- Header -->
  <header>
    <div class="brand">
      <div class="avatar-badge" id="headerAvatar">🌸</div>
      <div>
        <h1 id="headerName">Aishu</h1>
        <p id="headerStatusText">AI Companion & Character</p>
      </div>
    </div>
    <div class="header-actions">
      <div class="status-pill" id="headerLiveStatus">System Online</div>
      <button class="btn btn-purple" onclick="probeModels()" id="btnProbe">⚡ Probe Models</button>
      <button class="btn" onclick="logout()">🔒 Logout</button>
    </div>
  </header>

  <!-- Navigation Tabs -->
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('models')">🤖 AI Models</button>
    <button class="tab-btn" onclick="showTab('visuals')">🎨 Visuals & Profile</button>
    <button class="tab-btn" onclick="showTab('chat')">💬 Live Chat</button>
    <button class="tab-btn" onclick="showTab('memory')">🧠 Memory Explorer</button>
    <button class="tab-btn" onclick="showTab('persona')">💖 Persona & Mood</button>
    <button class="tab-btn" onclick="showTab('features')">⚙️ Features</button>
    <button class="tab-btn" onclick="showTab('logs')">📜 Live Logs</button>
    <button class="tab-btn" onclick="showTab('overview')">📊 Metrics</button>
  </div>

  <!-- TAB 1: AI MODELS -->
  <div id="tab-models">
    <div class="grid-4" style="margin-bottom: 20px;">
      <div class="stat-box">
        <div class="stat-label">Active Models</div>
        <div class="stat-value" id="statActiveModels" style="color: var(--cyan);">-</div>
        <div class="stat-sub">Ready for chat fallback</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Primary Fast-Path</div>
        <div class="stat-value" style="font-size: 13.5px; font-family: var(--mono); color: var(--purple);" id="statBestModel">Analyzing...</div>
        <div class="stat-sub">Lowest latency route</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Average Latency</div>
        <div class="stat-value" id="statAvgLatency" style="font-family: var(--mono);">- ms</div>
        <div class="stat-sub">Across active providers</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Total Providers</div>
        <div class="stat-value" style="color: #38BDF8;" id="statTotalProviders">5</div>
        <div class="stat-sub">Groq, CF, Gem, NIM, OR</div>
      </div>
    </div>

    <!-- Add Custom Model Card -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">➕ Add Free AI Model</div>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 2fr auto; gap: 14px; align-items: end;">
        <div>
          <label class="form-label">Provider Prefix</label>
          <select id="newModelProvider" class="select">
            <option value="">OpenRouter (default)</option>
            <option value="groq/">Groq (groq/)</option>
            <option value="cf/">Cloudflare (cf/)</option>
            <option value="gemini/">Gemini (gemini/)</option>
            <option value="nim/">NVIDIA NIM (nim/)</option>
          </select>
        </div>
        <div>
          <label class="form-label">Model Identifier</label>
          <input type="text" id="newModelName" class="input-text" placeholder="e.g. meta-llama/llama-3.3-70b-instruct:free">
        </div>
        <button class="btn btn-primary" onclick="addModel()" style="height: 44px; padding: 0 20px;">Add Model ✦</button>
      </div>
    </div>

    <!-- Configured Models List -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">📋 Configured Model Routes (<span id="modelCount" style="color: var(--cyan);">0</span>)</div>
        <input type="text" id="modelSearch" class="input-text" placeholder="Filter models..." style="max-width: 220px;" oninput="renderModels()">
      </div>
      <div id="modelsList">Loading models...</div>
    </div>
  </div>

  <!-- TAB 2: VISUALS & PROFILE -->
  <div id="tab-visuals" style="display: none;">
    <div class="grid-2">
      <!-- Left Column: Controls -->
      <div>
        <div class="card">
          <div class="card-header">
            <div class="card-title">✨ Aishu Identity & Discord Profile</div>
          </div>
          
          <div class="form-group">
            <label class="form-label">Aishu Display Name</label>
            <input type="text" id="settingsName" class="input-text" placeholder="Aishu" oninput="updateProfilePreview()">
          </div>

          <div class="form-group">
            <label class="form-label">Profile Avatar / Picture</label>
            <div style="display: flex; gap: 10px; align-items: center;">
              <input type="text" id="settingsAvatarUrl" class="input-text" placeholder="https://example.com/avatar.png" oninput="updateProfilePreview()">
              <label class="btn btn-purple" style="cursor: pointer; white-space: nowrap; padding: 10px 14px;">
                📁 Upload
                <input type="file" id="settingsAvatarFile" accept="image/*" style="display: none;" onchange="handleFileUpload(this, 'avatar')">
              </label>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Profile Banner Image</label>
            <div style="display: flex; gap: 10px; align-items: center;">
              <input type="text" id="settingsBannerUrl" class="input-text" placeholder="https://example.com/banner.png" oninput="updateProfilePreview()">
              <label class="btn btn-purple" style="cursor: pointer; white-space: nowrap; padding: 10px 14px;">
                📁 Upload
                <input type="file" id="settingsBannerFile" accept="image/*" style="display: none;" onchange="handleFileUpload(this, 'banner')">
              </label>
            </div>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;" class="form-group">
            <div>
              <label class="form-label">Discord Status</label>
              <select id="settingsPresenceStatus" class="select" onchange="updateProfilePreview()">
                <option value="online">🟢 Online</option>
                <option value="idle">🟡 Idle / Away</option>
                <option value="dnd">🔴 Do Not Disturb</option>
                <option value="invisible">⚪ Invisible</option>
              </select>
            </div>
            <div>
              <label class="form-label">Activity Type</label>
              <select id="settingsActivityType" class="select" onchange="updateProfilePreview()">
                <option value="playing">Playing</option>
                <option value="listening">Listening to</option>
                <option value="watching">Watching</option>
                <option value="competing">Competing in</option>
                <option value="custom">Custom Status</option>
              </select>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Activity / Status Text</label>
            <input type="text" id="settingsStatus" class="input-text" placeholder="chatting with you ♡" oninput="updateProfilePreview()">
          </div>

          <div class="form-group">
            <label class="form-label">Personality Summary / Bio</label>
            <input type="text" id="settingsPersonality" class="input-text" placeholder="sweet, sassy, teasing, genuine" oninput="updateProfilePreview()">
          </div>

          <button class="btn btn-primary" onclick="saveProfileSettings()" id="saveProfileBtn" style="width: 100%; justify-content: center; padding: 12px; margin-top: 6px;">Update Discord Profile ✦</button>
        </div>

        <div class="card">
          <div class="card-header">
            <div class="card-title">🎨 Embed & Theme Studio</div>
          </div>
          <div class="form-group">
            <label class="form-label">Discord Embed Accent Color</label>
            <div class="color-picker-wrap">
              <input type="color" id="embedColorPicker" class="color-picker" value="#FFB7C5" onchange="updateEmbedColor(this.value)">
              <input type="text" id="embedColorHex" class="input-text" value="#FFB7C5" style="max-width: 130px; font-family: var(--mono);" oninput="updateEmbedColor(this.value)">
              <span style="font-size: 12px; color: var(--text-muted);">Used across /memories, /profile, /bond</span>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Quick Swatches</label>
            <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
              <button class="btn" style="background: #FFB7C5; color: #111; font-weight: 700;" onclick="updateEmbedColor('#FFB7C5')">🌸 Sakura</button>
              <button class="btn" style="background: #C084FC; color: #111; font-weight: 700;" onclick="updateEmbedColor('#C084FC')">💜 Lavender</button>
              <button class="btn" style="background: #00F5D4; color: #111; font-weight: 700;" onclick="updateEmbedColor('#00F5D4')">💎 Neon Cyan</button>
              <button class="btn" style="background: #5865F2; color: #FFF; font-weight: 700;" onclick="updateEmbedColor('#5865F2')">💙 Blurple</button>
              <button class="btn" style="background: #34D399; color: #111; font-weight: 700;" onclick="updateEmbedColor('#34D399')">💚 Mint</button>
            </div>
          </div>
          <button class="btn btn-primary" onclick="saveVisualSettings()">Save Theme Color</button>
        </div>
      </div>

      <!-- Right Column: Live Profile Card -->
      <div>
        <div class="card" style="position: sticky; top: 24px;">
          <div class="card-header">
            <div class="card-title">👁️ Live Discord Profile Card</div>
            <span style="font-size: 11.5px; color: var(--cyan); font-weight: 600;">✦ Real-time preview</span>
          </div>
          
          <div class="profile-preview-card" id="cardPreviewWrap">
            <div class="profile-banner" id="prevBanner"></div>
            <div class="profile-avatar-wrap">
              <img src="" alt="Avatar" class="profile-avatar-img" id="prevAvatar" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
              <div class="profile-status-dot status-online" id="prevStatusDot"></div>
            </div>
            <div class="profile-body">
              <div class="profile-names">
                <span class="profile-display-name" id="prevName">Aishu</span>
                <span class="profile-tag">BOT</span>
              </div>
              <div class="profile-activity-box" id="prevActivityBox">
                <span id="prevActivityVerb" style="color: var(--text-dim);">Playing</span>
                <strong id="prevActivityText">chatting with you ♡</strong>
              </div>
              <div class="profile-bio-box" id="prevBio">
                sweet, sassy, teasing, genuine
              </div>
            </div>
          </div>

          <div style="font-size: 12px; color: var(--text-dim); line-height: 1.5; padding: 12px 4px 0;">
            💡 <strong>Discord API Note:</strong> Discord rate limits avatar & username changes to 2 times per hour. Status and activity changes apply live instantly.
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 3: LIVE CHAT PLAYGROUND -->
  <div id="tab-chat" style="display: none;">
    <div class="card">
      <div class="card-header">
        <div class="card-title">💬 Interactive AI Chat Playground</div>
        <span style="font-size: 12px; color: var(--text-muted);">Simulate turns & test active AI routing in real-time</span>
      </div>
      <div class="chat-container">
        <div class="chat-messages" id="chatHistory">
          <div class="chat-msg assistant">
            <div class="chat-bubble">hey! I'm Aishu. How's your day going? ✨</div>
            <div class="chat-meta">Aishu • Ready</div>
          </div>
        </div>
        <div class="chat-input-bar">
          <input type="text" id="chatInputText" class="input-text" placeholder="Type a message to test Aishu's response..." onkeydown="if(event.key==='Enter')sendTestChat()">
          <button class="btn btn-primary" onclick="sendTestChat()" id="btnSendChat">Send ✦</button>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 4: MEMORY EXPLORER -->
  <div id="tab-memory" style="display: none;">
    <div class="grid-2">
      <!-- Left: Users List -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">👥 Remembered Users (<span id="memUserCount" style="color: var(--cyan);">0</span>)</div>
          <input type="text" id="memUserSearch" class="input-text" placeholder="Search user..." style="max-width: 180px;" oninput="loadMemoryUsers()">
        </div>
        <div class="table-wrap" style="max-height: 520px; overflow-y: auto;">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Msgs</th>
                <th>Streak</th>
                <th>Facts</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="memUsersTableBody">
              <tr><td colspan="5" style="text-align: center; color: var(--text-dim);">Loading users...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Right: User Details & LTM Facts -->
      <div class="card">
        <div class="card-header">
          <div class="card-title" id="selectedUserHeader">🔍 User Details & Facts</div>
          <span id="selectedUserTier" class="status-pill" style="display: none;">Tier: -</span>
        </div>
        <div id="selectedUserDetails" style="color: var(--text-muted); font-size: 13px;">
          Select a user from the list to view their long-term memory facts, preferences, and relationship status.
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 5: PERSONA & MOOD STUDIO -->
  <div id="tab-persona" style="display: none;">
    <div class="grid-2">
      <div class="card">
        <div class="card-header">
          <div class="card-title">💖 Dynamic Mood Engine</div>
        </div>
        <div style="text-align: center; padding: 12px 0 18px;">
          <div id="personaMoodEmoji" style="font-size: 54px; filter: drop-shadow(0 0 16px var(--pink-glow));">🌸</div>
          <h2 id="personaMoodName" style="font-size: 20px; font-weight: 800; text-transform: capitalize; margin-top: 4px;">Soft</h2>
          <p id="personaMoodScoreText" style="color: var(--cyan); font-size: 13px; font-family: var(--mono); font-weight: 600;">Score: 8 / 100</p>
        </div>

        <div class="form-group">
          <label class="form-label">Set Mood Preset</label>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button class="btn" onclick="setMoodPreset('soft')">🌸 Soft</button>
            <button class="btn" onclick="setMoodPreset('happy')">😊 Happy</button>
            <button class="btn" onclick="setMoodPreset('playful')">😏 Playful</button>
            <button class="btn" onclick="setMoodPreset('flirty')">😘 Flirty</button>
            <button class="btn" onclick="setMoodPreset('excited')">🤩 Excited</button>
            <button class="btn" onclick="setMoodPreset('shy')">🥺 Shy</button>
            <button class="btn" onclick="setMoodPreset('neutral')">😐 Neutral</button>
            <button class="btn" onclick="setMoodPreset('bored')">🥱 Bored</button>
            <button class="btn" onclick="setMoodPreset('annoyed')">😒 Annoyed</button>
            <button class="btn" onclick="setMoodPreset('sad')">😢 Sad</button>
          </div>
        </div>

        <div class="form-group" style="margin-top: 14px;">
          <label class="form-label">Mood Score Slider (<span id="moodSliderVal">8</span> / 100)</label>
          <input type="range" id="moodScoreSlider" min="1" max="100" value="8" style="width: 100%; accent-color: var(--cyan);" oninput="document.getElementById('moodSliderVal').innerText = this.value">
          <button class="btn btn-primary" onclick="applyMoodScore()" style="margin-top: 10px; width: 100%; justify-content: center;">Apply Mood Score ✦</button>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">🎭 Core Traits & Bonds</div>
        </div>
        <div class="form-group">
          <label class="form-label">Likes</label>
          <input type="text" id="personaLikes" class="input-text" placeholder="music, chatting, stargazing, sweets, anime">
        </div>
        <div class="form-group">
          <label class="form-label">Dislikes</label>
          <input type="text" id="personaDislikes" class="input-text" placeholder="rude people, being ignored, spicy food">
        </div>
        <div class="form-group">
          <label class="form-label">Custom Note / Quirk</label>
          <input type="text" id="personaCustomNote" class="input-text" placeholder="e.g. loves late night conversations">
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;" class="form-group">
          <div>
            <label class="form-label">Special Person (Lover)</label>
            <input type="text" id="personaLover" class="input-text" placeholder="None / Username">
          </div>
          <div>
            <label class="form-label">Life Partner</label>
            <input type="text" id="personaPartner" class="input-text" placeholder="None / Username">
          </div>
        </div>
        <button class="btn btn-primary" onclick="savePersonaTraits()" style="width: 100%; justify-content: center; padding: 12px;">Save Persona Traits ✦</button>
      </div>
    </div>
  </div>

  <!-- TAB 6: FEATURES & AI CONTROLS -->
  <div id="tab-features" style="display: none;">
    <div class="card">
      <div class="card-header">
        <div class="card-title">⚙️ Feature Toggles</div>
      </div>
      <div class="model-row" style="padding: 18px;">
        <div>
          <div style="font-weight: 700; font-size: 14.5px;">🖼️ Vision & Image Analysis</div>
          <div style="font-size: 12.5px; color: var(--text-muted); margin-top: 2px;">Enable Aishu to analyze uploaded photos and attachments via Gemini Vision</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="toggleVision" checked onchange="toggleFeature('vision_enabled', this.checked)">
          <span class="slider"></span>
        </label>
      </div>
      <div class="model-row" style="padding: 18px;">
        <div>
          <div style="font-weight: 700; font-size: 14.5px;">🎨 Image Generation Result Embed</div>
          <div style="font-size: 12.5px; color: var(--text-muted); margin-top: 2px;">ON: Send styled embed with prompt, model, and duration. OFF: Send clean generated image file only.</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="toggleImageEmbed" checked onchange="toggleFeature('image_embed_enabled', this.checked)">
          <span class="slider"></span>
        </label>
      </div>
      <div class="model-row" style="padding: 18px;">
        <div>
          <div style="font-weight: 700; font-size: 14.5px;">🌙 Quiet Mode Global Default</div>
          <div style="font-size: 12.5px; color: var(--text-muted); margin-top: 2px;">When enabled, Aishu only speaks when directly mentioned</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="toggleQuiet" onchange="toggleFeature('quiet_mode_default', this.checked)">
          <span class="slider"></span>
        </label>
      </div>
      <div class="model-row" style="padding: 18px;">
        <div>
          <div style="font-weight: 700; font-size: 14.5px;">🧠 Memory Auto-Extraction</div>
          <div style="font-size: 12.5px; color: var(--text-muted); margin-top: 2px;">Automatically save facts, preferences, and moments to SQLite long-term memory</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="toggleMemory" checked onchange="toggleFeature('memory_enabled', this.checked)">
          <span class="slider"></span>
        </label>
      </div>
    </div>
  </div>

  <!-- TAB 7: LIVE LOGS -->
  <div id="tab-logs" style="display: none;">
    <div class="card">
      <div class="card-header">
        <div class="card-title">📜 Real-time System Logs</div>
        <div style="display: flex; gap: 10px; align-items: center;">
          <input type="text" id="logSearchInput" class="input-text" placeholder="Filter logs..." style="max-width: 200px;" oninput="filterLogs()">
          <button class="btn btn-primary" onclick="fetchLogs()">🔄 Refresh</button>
        </div>
      </div>
      <div class="log-console" id="logConsole">Loading logs...</div>
    </div>
  </div>

  <!-- TAB 8: METRICS & OVERVIEW -->
  <div id="tab-overview" style="display: none;">
    <div class="grid-4" style="margin-bottom: 20px;">
      <div class="stat-box">
        <div class="stat-label">Discord Ping</div>
        <div class="stat-value" id="metricPing" style="color: var(--cyan);">- ms</div>
        <div class="stat-sub">Gateway WebSocket latency</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Connected Guilds</div>
        <div class="stat-value" id="metricGuilds" style="color: var(--purple);">-</div>
        <div class="stat-sub">Active Discord servers</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Total Users</div>
        <div class="stat-value" id="metricUsers" style="color: var(--pink);">-</div>
        <div class="stat-sub">Stored in SQLite DB</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Python Version</div>
        <div class="stat-value" id="metricPython" style="font-size: 16px; font-family: var(--mono); color: #38BDF8;">-</div>
        <div class="stat-sub">Runtime Environment</div>
      </div>
    </div>

    <div class="grid-3">
      <div class="card">
        <div class="card-header"><div class="card-title">💖 Emotional State</div></div>
        <div style="text-align: center; padding: 22px 0;">
          <div id="moodEmoji" style="font-size: 58px; margin-bottom: 10px; filter: drop-shadow(0 0 16px var(--pink-glow));">🌸</div>
          <h2 id="moodLabel" style="font-size: 22px; font-weight: 800; text-transform: capitalize; color: #FFF;">Soft</h2>
          <p id="moodScore" style="color: var(--cyan); font-size: 13.5px; margin-top: 4px; font-family: var(--mono); font-weight: 600;">Score: 8 / 100</p>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div class="card-title">👥 Companionship</div></div>
        <div style="display: flex; flex-direction: column; gap: 12px; padding: 10px 0;">
          <div class="stat-box">
            <div class="stat-label">Life Partner</div>
            <div class="stat-value" style="font-size: 16px; color: var(--pink);" id="partnerName">None set</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Special Person</div>
            <div class="stat-value" style="font-size: 16px; color: var(--purple);" id="loverName">None set</div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div class="card-title">💾 Memory & Database</div></div>
        <div style="display: flex; flex-direction: column; gap: 12px; padding: 10px 0;">
          <div class="stat-box">
            <div class="stat-label">Remembered Users</div>
            <div class="stat-value" id="userCount" style="color: var(--cyan);">0</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Storage Engine</div>
            <div class="stat-value" style="font-size: 15px; color: #34D399;">SQLite WAL Mode</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="toast">✅ Action completed</div>

<script>
let authToken = localStorage.getItem('aishu_auth') || '';
let currentModels = [];
let botData = {};
let avatarDataUri = '';
let bannerDataUri = '';
let allRawLogs = [];

function showToast(msg) {
  const t = document.getElementById('toast');
  t.innerText = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

function showTab(name) {
  const tabs = ['models', 'visuals', 'chat', 'memory', 'persona', 'features', 'logs', 'overview'];
  tabs.forEach(t => {
    const el = document.getElementById('tab-' + t);
    if (el) el.style.display = (t === name ? 'block' : 'none');
  });
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.innerText.toLowerCase().includes(name));
  });
  if (name === 'logs') fetchLogs();
  if (name === 'memory') loadMemoryUsers();
  if (name === 'overview') loadSystemMetrics();
}

async function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  if (authToken) opts.headers['Authorization'] = 'Bearer ' + authToken;
  opts.headers['Content-Type'] = 'application/json';
  try {
    const res = await fetch('/api/' + path, opts);
    if (res.status === 401) {
      document.getElementById('authModal').style.display = 'flex';
      return null;
    }
    return await res.json();
  } catch(e) {
    console.error(e);
    return null;
  }
}

async function login() {
  const pass = document.getElementById('authPassInput').value;
  const res = await fetch('/api/auth', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password: pass})
  });
  if (res.ok) {
    const data = await res.json();
    authToken = data.token;
    localStorage.setItem('aishu_auth', authToken);
    document.getElementById('authModal').style.display = 'none';
    document.getElementById('authError').style.display = 'none';
    loadAll();
  } else {
    document.getElementById('authError').style.display = 'block';
  }
}

async function logout() {
  await api('auth/logout', {method: 'POST'});
  localStorage.removeItem('aishu_auth');
  authToken = '';
  document.getElementById('authModal').style.display = 'flex';
}

function handleFileUpload(input, type) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    if (type === 'avatar') {
      avatarDataUri = e.target.result;
      document.getElementById('settingsAvatarUrl').value = '';
      document.getElementById('prevAvatar').src = avatarDataUri;
    } else {
      bannerDataUri = e.target.result;
      document.getElementById('settingsBannerUrl').value = '';
      document.getElementById('prevBanner').style.backgroundImage = `url(${bannerDataUri})`;
    }
    showToast(`${type} image uploaded ready to save ✨`);
  };
  reader.readAsDataURL(file);
}

function updateProfilePreview() {
  const name = document.getElementById('settingsName').value || 'Aishu';
  const statusText = document.getElementById('settingsStatus').value || 'chatting with you ♡';
  const personality = document.getElementById('settingsPersonality').value || 'sweet, sassy, teasing, genuine';
  const status = document.getElementById('settingsPresenceStatus').value;
  const activityType = document.getElementById('settingsActivityType').value;
  const avatarUrl = avatarDataUri || document.getElementById('settingsAvatarUrl').value;
  const bannerUrl = bannerDataUri || document.getElementById('settingsBannerUrl').value;

  document.getElementById('prevName').innerText = name;
  document.getElementById('prevBio').innerText = personality;
  
  const verbMap = { playing: 'Playing', listening: 'Listening to', watching: 'Watching', competing: 'Competing in', custom: '' };
  document.getElementById('prevActivityVerb').innerText = verbMap[activityType] || 'Playing';
  document.getElementById('prevActivityText').innerText = statusText;

  if (avatarUrl) document.getElementById('prevAvatar').src = avatarUrl;
  if (bannerUrl) {
    document.getElementById('prevBanner').style.backgroundImage = `url(${bannerUrl})`;
  } else {
    document.getElementById('prevBanner').style.backgroundImage = 'linear-gradient(135deg, #FF7597, #A855F7, #00F5D4)';
  }

  const dot = document.getElementById('prevStatusDot');
  dot.className = 'profile-status-dot status-' + status;
}

function updateEmbedColor(hex) {
  document.getElementById('embedColorPicker').value = hex;
  document.getElementById('embedColorHex').value = hex;
}

async function saveVisualSettings() {
  const color = document.getElementById('embedColorPicker').value;
  const res = await api('settings/embed_color', {method: 'POST', body: JSON.stringify({color})});
  if (res && res.ok) showToast('Embed theme color saved 🌸');
}

async function loadAll() {
  const status = await api('status');
  if (!status) return;

  botData = status;
  document.getElementById('headerName').innerText = status.name || 'Aishu';
  document.getElementById('headerStatusText').innerText = status.status_text || 'AI Companion';
  if (status.avatar_url) {
    document.getElementById('headerAvatar').innerHTML = `<img src="${status.avatar_url}">`;
    document.getElementById('prevAvatar').src = status.avatar_url;
  }
  if (status.banner_url) {
    document.getElementById('prevBanner').style.backgroundImage = `url(${status.banner_url})`;
  }

  // Populate form fields
  document.getElementById('settingsName').value = status.name || '';
  document.getElementById('settingsStatus').value = status.status_text || '';
  document.getElementById('settingsPersonality').value = status.personality || '';
  document.getElementById('settingsPresenceStatus').value = status.status || 'online';
  document.getElementById('settingsActivityType').value = status.activity_type || 'playing';
  
  // Persona Tab fields
  document.getElementById('personaLikes').value = status.likes || '';
  document.getElementById('personaDislikes').value = status.dislikes || '';
  document.getElementById('personaCustomNote').value = status.custom_note || '';
  document.getElementById('personaLover').value = status.lover || '';
  document.getElementById('personaPartner').value = status.partner || '';
  
  if (status.embed_color) updateEmbedColor(status.embed_color);

  // Features
  document.getElementById('toggleVision').checked = !!status.vision_enabled;
  document.getElementById('toggleImageEmbed').checked = !!status.image_embed_enabled;
  document.getElementById('toggleQuiet').checked = !!status.quiet_mode_default;
  document.getElementById('toggleMemory').checked = !!status.memory_enabled;

  // Overview & Mood
  document.getElementById('moodEmoji').innerText = status.mood_emoji || '🌸';
  document.getElementById('moodLabel').innerText = status.mood || 'Soft';
  document.getElementById('moodScore').innerText = `Score: ${status.mood_score || 0} / 100`;
  document.getElementById('personaMoodEmoji').innerText = status.mood_emoji || '🌸';
  document.getElementById('personaMoodName').innerText = status.mood || 'Soft';
  document.getElementById('personaMoodScoreText').innerText = `Score: ${status.mood_score || 0} / 100`;
  document.getElementById('moodScoreSlider').value = status.mood_score || 8;
  document.getElementById('moodSliderVal').innerText = status.mood_score || 8;

  document.getElementById('loverName').innerText = status.lover || 'None set';
  document.getElementById('partnerName').innerText = status.partner || 'None set';
  document.getElementById('userCount').innerText = status.user_count || 0;
  document.getElementById('statBestModel').innerText = status.best_model || 'None active';

  updateProfilePreview();
  await loadModels();
}

async function loadModels() {
  const models = await api('models');
  if (!models) return;
  currentModels = models;
  renderModels();
}

function renderModels() {
  const list = document.getElementById('modelsList');
  const search = (document.getElementById('modelSearch').value || '').toLowerCase();
  const filtered = currentModels.filter(m => m.name.toLowerCase().includes(search));

  document.getElementById('modelCount').innerText = currentModels.length;
  const activeCount = currentModels.filter(m => m.enabled).length;
  document.getElementById('statActiveModels').innerText = `${activeCount} / ${currentModels.length}`;

  const latencies = currentModels.filter(m => m.latency_ms > 0).map(m => m.latency_ms);
  const avgLat = latencies.length ? Math.round(latencies.reduce((a,b)=>a+b,0) / latencies.length) : 0;
  document.getElementById('statAvgLatency').innerText = avgLat > 0 ? `${avgLat} ms` : '- ms';

  if (!filtered.length) {
    list.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--text-dim);">No matching models found.</div>`;
    return;
  }

  list.innerHTML = filtered.map(m => {
    let tagClass = 'tag-openrouter';
    let prov = 'OpenRouter';
    if (m.name.startsWith('groq/')) { tagClass = 'tag-groq'; prov = 'Groq'; }
    else if (m.name.startsWith('cf/')) { tagClass = 'tag-cf'; prov = 'Cloudflare'; }
    else if (m.name.startsWith('gemini/')) { tagClass = 'tag-gemini'; prov = 'Gemini'; }
    else if (m.name.startsWith('nim/')) { tagClass = 'tag-nim'; prov = 'NVIDIA'; }

    const cleanName = m.name.replace(/^(groq\/|cf\/|gemini\/|nim\/)/, '');
    const lat = m.latency_ms > 0 ? `<span style="color: var(--cyan);">${m.latency_ms}ms</span>` : 'untested';
    const fail = m.fails > 0 ? `<span style="color: var(--danger); font-weight: 700;">⚠️ ${m.fails} fails</span>` : '';
    const customBadge = m.is_custom ? `<button class="btn btn-danger" style="padding: 4px 10px; font-size: 11px;" onclick="removeModel('${m.name}')">Remove</button>` : '';

    return `
      <div class="model-row">
        <div class="model-info">
          <span class="model-tag ${tagClass}">${prov}</span>
          <div style="min-width: 0;">
            <div class="model-name" title="${m.name}">${cleanName}</div>
            <div class="model-meta">
              <span>⚡ Latency: ${lat}</span>
              ${fail}
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 14px;">
          ${customBadge}
          <label class="switch">
            <input type="checkbox" ${m.enabled ? 'checked' : ''} onchange="toggleModel('${m.name}', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
      </div>
    `;
  }).join('');
}

async function toggleModel(model, enabled) {
  await api('models/toggle', {method: 'POST', body: JSON.stringify({model, enabled})});
  showToast(`Model ${enabled ? 'enabled' : 'disabled'} ✦`);
  await loadModels();
}

async function addModel() {
  const prefix = document.getElementById('newModelProvider').value;
  const name = document.getElementById('newModelName').value.trim();
  if (!name) return alert('Enter model name');
  const full = prefix + name;
  const res = await api('models/add', {method: 'POST', body: JSON.stringify({model: full})});
  if (res && res.ok) {
    document.getElementById('newModelName').value = '';
    showToast(`Added ${full} ✨`);
    await loadModels();
  } else {
    alert(res && res.error ? res.error : 'Failed to add model');
  }
}

async function removeModel(model) {
  if (!confirm(`Remove model ${model}?`)) return;
  const res = await api('models/remove', {method: 'POST', body: JSON.stringify({model})});
  if (res && res.ok) {
    showToast(`Model removed`);
    await loadModels();
  }
}

async function probeModels() {
  const btn = document.getElementById('btnProbe');
  btn.disabled = true;
  btn.innerText = '⏳ Probing...';
  const res = await api('models/probe', {method: 'POST'});
  btn.disabled = false;
  btn.innerText = '⚡ Probe Models';
  if (res && res.ok) {
    showToast(`Probe complete: ${res.active} models responsive ✅`);
    await loadModels();
  }
}

async function saveProfileSettings() {
  const btn = document.getElementById('saveProfileBtn');
  btn.disabled = true;
  btn.innerText = '⏳ Updating Discord...';

  const payload = {
    name: document.getElementById('settingsName').value.trim(),
    status_text: document.getElementById('settingsStatus').value.trim(),
    personality: document.getElementById('settingsPersonality').value.trim(),
    status: document.getElementById('settingsPresenceStatus').value,
    activity_type: document.getElementById('settingsActivityType').value,
    avatar: avatarDataUri || document.getElementById('settingsAvatarUrl').value.trim() || undefined,
    banner: bannerDataUri || document.getElementById('settingsBannerUrl').value.trim() || undefined,
  };

  const res = await api('settings/profile', {method: 'POST', body: JSON.stringify(payload)});
  btn.disabled = false;
  btn.innerText = 'Update Discord Profile ✦';

  if (res && res.ok) {
    avatarDataUri = '';
    bannerDataUri = '';
    showToast('Aishu profile & Discord presence updated ✨');
    loadAll();
  } else {
    alert(res && res.error ? res.error : 'Failed to update profile');
  }
}

async function toggleFeature(feature, val) {
  const res = await api('settings/feature', {method: 'POST', body: JSON.stringify({feature, value: val})});
  if (res && res.ok) showToast(`Setting updated ✦`);
}

/* Chat Playground */
async function sendTestChat() {
  const inp = document.getElementById('chatInputText');
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';

  const history = document.getElementById('chatHistory');
  history.innerHTML += `
    <div class="chat-msg user">
      <div class="chat-bubble">${htmlEscape(msg)}</div>
      <div class="chat-meta">You</div>
    </div>
  `;
  history.scrollTop = history.scrollHeight;

  const btn = document.getElementById('btnSendChat');
  btn.disabled = true;
  btn.innerText = '...';

  const res = await api('chat/test', {method: 'POST', body: JSON.stringify({message: msg})});
  btn.disabled = false;
  btn.innerText = 'Send ✦';

  if (res && res.ok) {
    history.innerHTML += `
      <div class="chat-msg assistant">
        <div class="chat-bubble">${htmlEscape(res.reply)}</div>
        <div class="chat-meta">⚡ ${res.model} • ${res.latency_ms}ms • ~${res.estimated_tokens}tk</div>
      </div>
    `;
  } else {
    history.innerHTML += `
      <div class="chat-msg assistant">
        <div class="chat-bubble" style="color: var(--danger);">Error: ${res && res.error ? res.error : 'Request failed'}</div>
      </div>
    `;
  }
  history.scrollTop = history.scrollHeight;
}

/* Memory Explorer */
async function loadMemoryUsers() {
  const q = document.getElementById('memUserSearch').value.trim();
  const res = await api('memory/users?q=' + encodeURIComponent(q));
  if (!res) return;
  const tbody = document.getElementById('memUsersTableBody');
  document.getElementById('memUserCount').innerText = res.users.length;

  if (!res.users.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-dim);">No users stored.</td></tr>';
    return;
  }

  tbody.innerHTML = res.users.map(u => `
    <tr>
      <td><strong>${htmlEscape(u.display_name || u.username)}</strong><br><span style="font-size: 11px; color: var(--text-dim);">${u.user_id}</span></td>
      <td>${u.message_count}</td>
      <td>🔥 ${u.current_streak}</td>
      <td><span style="color: var(--cyan); font-weight: 700;">${u.memory_count}</span></td>
      <td><button class="btn" style="padding: 4px 10px; font-size: 11.5px;" onclick="loadUserDetail(${u.user_id})">Inspect 🔍</button></td>
    </tr>
  `).join('');
}

async function loadUserDetail(userId) {
  const res = await api('memory/user?user_id=' + userId);
  if (!res) return;
  const box = document.getElementById('selectedUserDetails');
  const hdr = document.getElementById('selectedUserHeader');
  const tier = document.getElementById('selectedUserTier');

  hdr.innerText = `👤 ${res.display_name} (@${res.username})`;
  tier.style.display = 'inline-flex';
  tier.innerText = `Tier: ${res.relationship ? res.relationship.tier : 'stranger'}`;

  const factsHtml = res.facts && res.facts.length ? res.facts.map(f => {
    const text = typeof f === 'object' ? f.content : f;
    const itemId = typeof f === 'object' ? (f.item_id || '') : '';
    return `
      <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.03); padding: 8px 12px; border-radius: 8px; margin-bottom: 6px;">
        <span>• ${htmlEscape(text)}</span>
        <button class="btn btn-danger" style="padding: 2px 8px; font-size: 10.5px;" onclick="deleteFact(${userId}, '${htmlEscape(itemId)}', '${htmlEscape(text)}')">Delete</button>
      </div>
    `;
  }).join('') : '<div style="color: var(--text-dim);">No LTM facts stored yet.</div>';

  box.innerHTML = `
    <div style="margin-bottom: 14px;">
      <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;"><strong>First seen:</strong> ${res.first_seen} | <strong>Last seen:</strong> ${res.last_seen}</p>
      <p style="font-size: 12px; color: var(--text-muted);"><strong>Relationship Dynamics:</strong> ${res.relationship ? res.relationship.description : 'Standard familiarity'}</p>
    </div>
    <h4 style="font-size: 13px; font-weight: 700; margin-bottom: 8px; color: var(--cyan);">📌 Long-term Memory Facts (${res.facts ? res.facts.length : 0})</h4>
    <div style="max-height: 240px; overflow-y: auto; margin-bottom: 16px;">
      ${factsHtml}
    </div>
  `;
}

async function deleteFact(userId, itemId, content) {
  if (!confirm(`Delete this memory fact?`)) return;
  const res = await api('memory/delete_fact', {method: 'POST', body: JSON.stringify({user_id: userId, item_id: itemId, content})});
  if (res && res.ok) {
    showToast('Fact deleted from memory 🗑️');
    loadUserDetail(userId);
    loadMemoryUsers();
  }
}

/* Persona & Mood */
async function setMoodPreset(mood) {
  const res = await api('personality/mood', {method: 'POST', body: JSON.stringify({mood})});
  if (res && res.ok) {
    showToast(`Mood set to ${mood} 🌸`);
    loadAll();
  }
}

async function applyMoodScore() {
  const score = parseInt(document.getElementById('moodScoreSlider').value);
  const mood = document.getElementById('personaMoodName').innerText.toLowerCase();
  const res = await api('personality/mood', {method: 'POST', body: JSON.stringify({mood, score})});
  if (res && res.ok) {
    showToast(`Mood score updated to ${score} ✦`);
    loadAll();
  }
}

async function savePersonaTraits() {
  const likes = document.getElementById('personaLikes').value;
  const dislikes = document.getElementById('personaDislikes').value;
  const custom_note = document.getElementById('personaCustomNote').value;
  const lover = document.getElementById('personaLover').value;
  const partner = document.getElementById('personaPartner').value;

  const res = await api('personality/traits', {method: 'POST', body: JSON.stringify({likes, dislikes, custom_note, lover, partner})});
  if (res && res.ok) {
    showToast('Persona traits & bonds saved 🌸');
    loadAll();
  }
}

/* Logs */
async function fetchLogs() {
  const res = await api('logs');
  if (!res) return;
  allRawLogs = res.lines || [];
  filterLogs();
}

function filterLogs() {
  const q = (document.getElementById('logSearchInput').value || '').toLowerCase();
  const consoleEl = document.getElementById('logConsole');
  const filtered = allRawLogs.filter(l => l.toLowerCase().includes(q));
  consoleEl.innerText = filtered.join('\\n') || 'No log entries found.';
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

/* Metrics */
async function loadSystemMetrics() {
  const res = await api('system/stats');
  if (!res) return;
  document.getElementById('metricPing').innerText = `${res.gateway_ping_ms} ms`;
  document.getElementById('metricGuilds').innerText = res.guild_count;
  document.getElementById('metricUsers').innerText = res.total_users;
  document.getElementById('metricPython').innerText = `Python ${res.python_version}`;
}

function htmlEscape(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Initial load & OAuth token/error handling
const urlParams = new URLSearchParams(window.location.search);
const tokenParam = urlParams.get('token');
const errorParam = urlParams.get('error');

if (tokenParam) {
  authToken = tokenParam;
  localStorage.setItem('aishu_auth', authToken);
  window.history.replaceState({}, document.title, window.location.pathname);
  document.getElementById('authModal').style.display = 'none';
  showToast('Logged in via Discord ✦');
  loadAll();
} else if (errorParam) {
  window.history.replaceState({}, document.title, window.location.pathname);
  const errEl = document.getElementById('authError');
  if (errorParam === 'unauthorized') {
    errEl.innerText = 'Access denied: Discord account is not the authorized bot owner.';
  } else if (errorParam === 'oauth_unconfigured') {
    errEl.innerText = 'Discord OAuth2 is not configured. Please use password login.';
  } else {
    errEl.innerText = 'Discord authentication failed. Please try again or use password.';
  }
  errEl.style.display = 'block';
  document.getElementById('authModal').style.display = 'flex';
} else {
  loadAll();
}
</script>
</body>
</html>
"""


class DashboardServer:
    def __init__(self, bot: Optional[discord.Client] = None):
        self.bot = bot
        self.app = web.Application(client_max_size=16 * 1024 * 1024)
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._sessions: dict[str, dict] = {}       # token -> {user_id, auth_type, created_at, expires_at}
        self._oauth_states: dict[str, float] = {}   # state -> expires_at
        self._setup_routes()

    def _create_session(self, user_id: int, auth_type: str) -> str:
        """Create a cryptographically secure dashboard session token."""
        now = time.time()
        # Clean expired sessions
        self._sessions = {k: v for k, v in self._sessions.items() if v.get("expires_at", 0) > now}
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "user_id": user_id,
            "auth_type": auth_type,
            "created_at": now,
            "expires_at": now + (7 * 86400), # 7-day expiration
        }
        return token

    def _check_auth(self, request: web.Request) -> bool:
        """Verify session token from Authorization header or secure cookie, with password fallback."""
        auth = request.headers.get("Authorization", "")
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
        if not token:
            token = request.cookies.get("aishu_session", "").strip()

        if not token:
            return False

        now = time.time()
        session = self._sessions.get(token)
        if session and session.get("expires_at", 0) > now:
            return True

        # Fallback comparison for direct password authentication
        if cfg.DASHBOARD_PASSWORD and hmac.compare_digest(token, cfg.DASHBOARD_PASSWORD):
            return True

        return False

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/ping", self.handle_health)
        self.app.router.add_get("/auth/discord/login", self.handle_discord_login)
        self.app.router.add_get("/auth/discord/callback", self.handle_discord_callback)
        self.app.router.add_post("/api/auth", self.handle_auth)
        self.app.router.add_post("/api/auth/logout", self.handle_logout)
        self.app.router.add_get("/api/status", self.handle_status)
        self.app.router.add_get("/api/models", self.handle_models)
        self.app.router.add_post("/api/models/toggle", self.handle_model_toggle)
        self.app.router.add_post("/api/models/add", self.handle_model_add)
        self.app.router.add_post("/api/models/remove", self.handle_model_remove)
        self.app.router.add_post("/api/models/probe", self.handle_model_probe)
        self.app.router.add_post("/api/settings/embed_color", self.handle_embed_color)
        self.app.router.add_post("/api/settings/profile", self.handle_profile_settings)
        self.app.router.add_post("/api/settings/feature", self.handle_feature_toggle)
        self.app.router.add_post("/api/chat/test", self.handle_chat_test)
        self.app.router.add_get("/api/memory/users", self.handle_memory_users)
        self.app.router.add_get("/api/memory/user", self.handle_memory_user_detail)
        self.app.router.add_post("/api/memory/delete_fact", self.handle_memory_delete_fact)
        self.app.router.add_post("/api/personality/mood", self.handle_personality_mood)
        self.app.router.add_post("/api/personality/traits", self.handle_personality_traits)
        self.app.router.add_get("/api/logs", self.handle_logs)
        self.app.router.add_get("/api/system/stats", self.handle_system_stats)

    async def handle_index(self, request: web.Request) -> web.Response:
        favicon_link = ""
        if self.bot and self.bot.user:
            try:
                avatar_url = html.escape(str(self.bot.user.display_avatar.url), quote=True)
                favicon_link = f'<link rel="icon" href="{avatar_url}">'
            except Exception:
                pass
        return web.Response(
            text=_HTML_PAGE.replace("{FAVICON_LINK}", favicon_link),
            content_type="text/html",
        )

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "healthy",
            "bot": aishu_state.name,
            "version": "2.6",
            "uptime": True
        })

    async def handle_discord_login(self, request: web.Request) -> web.Response:
        client_id = cfg.DISCORD_CLIENT_ID
        redirect_uri = cfg.DISCORD_REDIRECT_URI
        if not client_id or not cfg.DISCORD_CLIENT_SECRET:
            log.warning("Discord OAuth login attempted but DISCORD_CLIENT_ID/DISCORD_CLIENT_SECRET is not configured")
            return web.HTTPFound("/?error=oauth_unconfigured")

        now = time.time()
        self._oauth_states = {k: v for k, v in self._oauth_states.items() if v > now}
        state = secrets.token_urlsafe(16)
        self._oauth_states[state] = now + 600  # 10 minute TTL

        auth_url = (
            f"https://discord.com/oauth2/authorize"
            f"?client_id={quote(str(client_id))}"
            f"&response_type=code"
            f"&redirect_uri={quote(redirect_uri)}"
            f"&scope=identify"
            f"&state={quote(state)}"
        )
        return web.HTTPFound(auth_url)

    async def handle_discord_callback(self, request: web.Request) -> web.Response:
        code = request.query.get("code", "")
        state = request.query.get("state", "")
        error = request.query.get("error", "")

        if error or not code or not state:
            return web.HTTPFound("/?error=oauth_cancelled")

        now = time.time()
        valid_until = self._oauth_states.pop(state, None)
        if not valid_until or valid_until < now:
            return web.HTTPFound("/?error=invalid_state")

        token_url = "https://discord.com/api/v10/oauth2/token"
        token_payload = {
            "client_id": str(cfg.DISCORD_CLIENT_ID),
            "client_secret": str(cfg.DISCORD_CLIENT_SECRET),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.DISCORD_REDIRECT_URI,
        }
        token_headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(token_url, data=token_payload, headers=token_headers) as token_resp:
                    if token_resp.status != 200:
                        log.warning(f"Discord token exchange failed: {await token_resp.text()}")
                        return web.HTTPFound("/?error=token_exchange_failed")
                    token_data = await token_resp.json()
                    access_token = token_data.get("access_token")

                if not access_token:
                    return web.HTTPFound("/?error=no_access_token")

                user_headers = {"Authorization": f"Bearer {access_token}"}
                async with session.get("https://discord.com/api/v10/users/@me", headers=user_headers) as user_resp:
                    if user_resp.status != 200:
                        return web.HTTPFound("/?error=user_fetch_failed")
                    user_data = await user_resp.json()
                    discord_user_id = int(user_data.get("id", 0))
        except Exception as e:
            log.error(f"Discord OAuth2 error: {e}")
            return web.HTTPFound("/?error=oauth_error")

        if not cfg.BOT_OWNER_ID or discord_user_id != int(cfg.BOT_OWNER_ID):
            log.warning(f"Unauthorized Discord login attempt: user_id={discord_user_id} (owner={cfg.BOT_OWNER_ID})")
            return web.HTTPFound("/?error=unauthorized")

        session_token = self._create_session(user_id=discord_user_id, auth_type="discord")
        log.info(f"Dashboard login via Discord OAuth successful for owner {discord_user_id}")

        resp = web.HTTPFound(f"/?token={session_token}")
        is_secure = request.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
        resp.set_cookie(
            "aishu_session",
            session_token,
            max_age=7 * 86400,
            httponly=True,
            secure=is_secure,
            samesite="Lax",
            path="/",
        )
        return resp

    async def handle_auth(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            provided_pass = str(data.get("password", ""))
            if cfg.DASHBOARD_PASSWORD and hmac.compare_digest(provided_pass, cfg.DASHBOARD_PASSWORD):
                session_token = self._create_session(user_id=cfg.BOT_OWNER_ID or 1, auth_type="password")
                resp = web.json_response({"ok": True, "token": session_token})
                is_secure = request.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
                resp.set_cookie(
                    "aishu_session",
                    session_token,
                    max_age=7 * 86400,
                    httponly=True,
                    secure=is_secure,
                    samesite="Lax",
                    path="/",
                )
                return resp
        except Exception:
            pass
        return web.json_response({"error": "Invalid password"}, status=401)

    async def handle_logout(self, request: web.Request) -> web.Response:
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = request.cookies.get("aishu_session", "").strip()

        if token in self._sessions:
            self._sessions.pop(token, None)

        resp = web.json_response({"ok": True})
        resp.del_cookie("aishu_session", path="/")
        return resp

    async def _fetch_image_bytes(self, source: str) -> Optional[bytes]:
        """Fetch bytes from either base64 data URI or HTTP URL."""
        if not source:
            return None
        source = source.strip()
        if source.startswith("data:image"):
            try:
                _, b64data = source.split(",", 1)
                return base64.b64decode(b64data)
            except Exception as e:
                log.warning(f"Failed to decode base64 image: {e}")
                return None
        elif source.startswith("http://") or source.startswith("https://"):
            try:
                parsed = urlparse(source)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    return None
                try:
                    if not ipaddress.ip_address(parsed.hostname).is_global:
                        return None
                except ValueError:
                    pass

                timeout = aiohttp.ClientTimeout(total=10)
                connector = aiohttp.TCPConnector(
                    resolver=_PublicAddressResolver(), use_dns_cache=False,
                )
                async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                    async with session.get(source, allow_redirects=False) as resp:
                        if resp.status != 200 or not resp.content_type.startswith("image/"):
                            return None
                        content_length = resp.content_length
                        max_size = 8 * 1024 * 1024
                        if content_length is not None and content_length > max_size:
                            return None
                        image = bytearray()
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            image.extend(chunk)
                            if len(image) > max_size:
                                return None
                        return bytes(image)
            except Exception as e:
                log.warning(f"Failed to fetch image from URL {source}: {e}")
                return None
        return None

    async def handle_status(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        db = memory_manager.db
        embed_color = db.get_state("embed_color", "#FFB7C5") if db else "#FFB7C5"
        image_embed_enabled = db.get_state("image_embed_enabled", True) if db else True
        vision_enabled = db.get_state("feature_vision_enabled", True) if db else True
        quiet_mode_default = db.get_state("feature_quiet_mode_default", False) if db else False
        memory_enabled = db.get_state("feature_memory_enabled", True) if db else True

        avatar_url = ""
        banner_url = ""
        current_status = "online"
        activity_type = "playing"

        if self.bot and self.bot.user:
            try:
                avatar_url = self.bot.user.display_avatar.url
            except Exception:
                pass
            try:
                if self.bot.user.banner:
                    banner_url = self.bot.user.banner.url
            except Exception:
                pass
            try:
                if hasattr(self.bot, "status") and self.bot.status:
                    current_status = self.bot.status.name
            except Exception:
                pass

        return web.json_response({
            "name": aishu_state.name,
            "status_text": aishu_state.status_text,
            "personality": aishu_state.personality,
            "likes": aishu_state.likes,
            "dislikes": aishu_state.dislikes,
            "custom_note": aishu_state.custom_note,
            "mood": aishu_state.mood.mood,
            "mood_emoji": aishu_state.mood.emoji,
            "mood_score": aishu_state.mood.score,
            "lover": aishu_state.lover_name,
            "partner": aishu_state.partner_name,
            "user_count": memory_manager.user_count(),
            "best_model": model_controller.best_model(),
            "embed_color": embed_color,
            "avatar_url": avatar_url,
            "banner_url": banner_url,
            "status": current_status,
            "activity_type": activity_type,
            "image_embed_enabled": image_embed_enabled,
            "vision_enabled": vision_enabled,
            "quiet_mode_default": quiet_mode_default,
            "memory_enabled": memory_enabled,
        })

    async def handle_models(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        return web.json_response(model_controller.get_all_models_status())

    async def handle_model_toggle(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        model = data.get("model")
        enabled = bool(data.get("enabled", True))
        if enabled:
            model_controller.enable_model(model)
        else:
            model_controller.disable_model(model)
        return web.json_response({"ok": True})

    async def handle_model_add(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        model = data.get("model", "").strip()
        if not model:
            return web.json_response({"error": "Model name required"}, status=400)
        success = model_controller.add_custom_model(model)
        if success:
            return web.json_response({"ok": True})
        return web.json_response({"error": "Model already exists or invalid"}, status=400)

    async def handle_model_remove(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        model = data.get("model", "").strip()
        success = model_controller.remove_custom_model(model)
        return web.json_response({"ok": success})

    async def handle_model_probe(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        results = await asyncio.to_thread(model_controller.probe_all_models)
        active = sum(1 for r in results if "✅" in r.get("status", ""))
        return web.json_response({"ok": True, "active": active, "results": results})

    async def handle_embed_color(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        color = data.get("color", "#FFB7C5").strip()
        if memory_manager.db:
            memory_manager.db.set_state("embed_color", color)
        return web.json_response({"ok": True, "color": color})

    async def handle_profile_settings(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()

        new_name = data.get("name", "").strip()
        status_text = data.get("status_text", "").strip()
        personality = data.get("personality", "").strip()
        status_mode = data.get("status", "online").strip().lower()
        activity_type_str = data.get("activity_type", "playing").strip().lower()
        avatar_src = data.get("avatar")
        banner_src = data.get("banner")

        if new_name:
            aishu_state.set("name", new_name)
        if status_text:
            aishu_state.set("status_text", status_text)
        if personality:
            aishu_state.set("personality", personality)
        aishu_state.save(force=True)

        errors = []
        if self.bot and self.bot.user:
            status_map = {
                "online": discord.Status.online,
                "idle": discord.Status.idle,
                "dnd": discord.Status.dnd,
                "invisible": discord.Status.invisible,
            }
            status_enum = status_map.get(status_mode, discord.Status.online)

            activity_map = {
                "playing": discord.ActivityType.playing,
                "listening": discord.ActivityType.listening,
                "watching": discord.ActivityType.watching,
                "competing": discord.ActivityType.competing,
                "custom": discord.ActivityType.custom,
            }
            act_type = activity_map.get(activity_type_str, discord.ActivityType.playing)
            act_name = status_text or aishu_state.status_text

            if act_type == discord.ActivityType.custom:
                activity = discord.CustomActivity(name=act_name)
            else:
                activity = discord.Activity(type=act_type, name=act_name)

            try:
                await self.bot.change_presence(status=status_enum, activity=activity)
            except Exception as e:
                log.warning(f"Failed to change presence: {e}")

            edit_kwargs = {}
            if new_name and self.bot.user.name != new_name:
                edit_kwargs["username"] = new_name

            if avatar_src:
                avatar_bytes = await self._fetch_image_bytes(avatar_src)
                if avatar_bytes:
                    edit_kwargs["avatar"] = avatar_bytes

            if banner_src:
                banner_bytes = await self._fetch_image_bytes(banner_src)
                if banner_bytes:
                    edit_kwargs["banner"] = banner_bytes

            if edit_kwargs:
                try:
                    await self.bot.user.edit(**edit_kwargs)
                except discord.HTTPException as exc:
                    log.warning(f"Discord API rejected profile edit: {exc}")
                    errors.append(f"Discord API limit/error: {exc.text if hasattr(exc, 'text') else str(exc)}")
                except Exception as exc:
                    log.warning(f"Profile edit failed: {exc}")
                    errors.append(f"Profile edit error: {exc}")

        if errors:
            return web.json_response({"ok": True, "warning": "; ".join(errors)})
        return web.json_response({"ok": True})

    async def handle_feature_toggle(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        feature = data.get("feature")
        val = data.get("value")
        if memory_manager.db and feature:
            if feature == "image_embed_enabled":
                memory_manager.db.set_state("image_embed_enabled", bool(val))
            else:
                memory_manager.db.set_state(f"feature_{feature}", val)
        return web.json_response({"ok": True})

    async def handle_chat_test(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            return web.json_response({"error": "Message is empty"}, status=400)

        owner_id = cfg.BOT_OWNER_ID or 1
        um = memory_manager.load(owner_id, "Creator", "Creator")

        from brain.prompt_engine import prompt_engine
        prompt, ctx = prompt_engine.build_system_prompt(
            aishu=aishu_state, um=um, guild_id=0, server_topics=[], current_msg=message
        )
        messages = prompt_engine.build_messages(prompt, um.get_stm_list()[-6:], message)

        t0 = time.perf_counter()
        resp = await asyncio.to_thread(model_controller.chat, messages, 350, 0.85)
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)

        return web.json_response({
            "ok": True,
            "reply": resp.text if resp else "no response",
            "model": resp.model if resp else "unknown",
            "provider": resp.provider if resp else "unknown",
            "latency_ms": duration_ms,
            "estimated_tokens": ctx.estimated_tokens,
        })

    async def handle_memory_users(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        q = request.query.get("q", "").strip()
        users = memory_manager.list_users(limit=60, search=q)
        return web.json_response({"users": users})

    async def handle_memory_user_detail(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        user_id_str = request.query.get("user_id", "").strip()
        if not user_id_str.isdigit():
            return web.json_response({"error": "Invalid user_id"}, status=400)
        user_id = int(user_id_str)
        um = memory_manager.load(user_id)
        if not um:
            return web.json_response({"error": "User not found"}, status=404)

        rel_state = aishu_state.relationships.get_state(0, user_id)
        rel_tier = aishu_state.relationships.get_tier(0, user_id)
        rel_desc = aishu_state.relationships.describe_relationship(0, user_id)

        return web.json_response({
            "user_id": um.user_id,
            "username": um.username,
            "display_name": um.display_name,
            "first_seen": um.first_seen,
            "last_seen": um.last_seen,
            "message_count": um.message_count,
            "current_streak": um.current_streak,
            "longest_streak": um.longest_streak,
            "facts": um.ltm_facts,
            "prefs": um.ltm_prefs,
            "topics": um.ltm_topics,
            "relationship": {
                "tier": rel_tier,
                "score": rel_state.score if rel_state else 0,
                "streak": rel_state.streak if rel_state else 0,
                "trust": round(rel_state.trust, 2) if rel_state else 0,
                "comfort": round(rel_state.comfort, 2) if rel_state else 0,
                "attachment": round(rel_state.attachment, 2) if rel_state else 0,
                "description": rel_desc,
            }
        })

    async def handle_memory_delete_fact(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        user_id = data.get("user_id")
        item_id = data.get("item_id", "")
        content = data.get("content", "")
        if not user_id:
            return web.json_response({"error": "user_id required"}, status=400)
        ok = memory_manager.delete_memory_fact(int(user_id), item_id=item_id, content=content)
        return web.json_response({"ok": ok})

    async def handle_personality_mood(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        mood = data.get("mood", "").strip().lower()
        score = data.get("score")
        if mood:
            aishu_state.set_mood(mood, int(score) if score is not None else None)
        return web.json_response({
            "ok": True,
            "mood": aishu_state.mood.mood,
            "mood_emoji": aishu_state.mood.emoji,
            "mood_score": aishu_state.mood.score,
        })

    async def handle_personality_traits(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        data = await request.json()
        likes = data.get("likes")
        dislikes = data.get("dislikes")
        custom_note = data.get("custom_note")
        lover = data.get("lover")
        partner = data.get("partner")

        if likes is not None: aishu_state.set("likes", likes.strip())
        if dislikes is not None: aishu_state.set("dislikes", dislikes.strip())
        if custom_note is not None: aishu_state.set("custom_note", custom_note.strip())
        if lover is not None: aishu_state.set_lover(lover.strip() or None)
        if partner is not None: aishu_state.set_partner(partner.strip() or None)
        aishu_state.save(force=True)
        return web.json_response({"ok": True})

    async def handle_logs(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        log_path = cfg.LOG_FILE
        lines = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    all_lines = f.readlines()
                    lines = [l.rstrip("\r\n") for l in all_lines[-150:]]
            except Exception as e:
                lines = [f"Error reading log file: {e}"]
        else:
            lines = ["Log file does not exist yet."]
        return web.json_response({"lines": lines})

    async def handle_system_stats(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        guild_count = len(self.bot.guilds) if self.bot else 0
        ping_ms = round(self.bot.latency * 1000, 1) if (self.bot and hasattr(self.bot, "latency")) else 0

        return web.json_response({
            "guild_count": guild_count,
            "gateway_ping_ms": ping_ms,
            "python_version": sys.version.split()[0],
            "total_users": memory_manager.user_count(),
            "uptime_status": "Active",
            "models_count": len(model_controller.get_all_models_status()),
        })

    async def start(self):
        """Start the background dashboard server."""
        if not cfg.DASHBOARD_ENABLED:
            log.info("Web dashboard is disabled (DASHBOARD_ENABLED=false)")
            return

        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, host=cfg.DASHBOARD_HOST, port=cfg.DASHBOARD_PORT)
            await self.site.start()
            log.info(f"🌸 Web Dashboard active at http://{cfg.DASHBOARD_HOST}:{cfg.DASHBOARD_PORT}")
        except Exception as e:
            log.error(f"Failed to start web dashboard on port {cfg.DASHBOARD_PORT}: {e}")

    async def stop(self):
        """Stop the dashboard server cleanly on bot shutdown."""
        if self.runner:
            await self.runner.cleanup()
            log.info("Web Dashboard stopped.")
