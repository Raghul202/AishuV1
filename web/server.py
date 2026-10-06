"""
web/server.py — Ultra-lightweight Web Dashboard for Aishu.

Runs inside Aishu's existing asyncio event loop using aiohttp.web.
Zero extra background processes, zero heavy frameworks.

Features:
  - 🤖 AI Model Manager: Add/remove custom free models, toggle models, live probe & latency benchmarks.
  - 🎨 Visual & Profile Studio: Live Discord profile card, avatar/banner updater, status/activity controls, embed color picker.
  - ⚙️ Feature Toggles: Vision / image analysis, image generation result embed toggle, quiet mode, memory.
  - 📊 Live Status: Real-time mood, metrics, active providers, and memory health.
  - 🔒 Password-protected dashboard session.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
from typing import Optional

from aiohttp import web
import aiohttp
import discord

import config.settings as cfg
from brain.model_controller import model_controller
from core.memory.memory_manager import memory_manager
from core.personality.aishu_state import aishu_state
from utilities.logger import get_logger

log = get_logger("web.dashboard")

_HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aishu • Companion Control Dashboard</title>
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
.container { max-width: 1240px; margin: 0 auto; width: 100%; padding: 24px 20px 60px; }

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
  font-size: 13.5px; font-weight: 600; padding: 10px 18px; border-radius: 11px;
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
  background: var(--bg-input); border: 1px solid var(--border);
  border-radius: 14px; padding: 16px 18px;
  transition: all 0.2s; position: relative; overflow: hidden;
}
.stat-box::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--cyan), transparent);
  opacity: 0; transition: opacity 0.2s;
}
.stat-box:hover { border-color: rgba(0, 245, 212, 0.25); transform: translateY(-1px); }
.stat-box:hover::before { opacity: 1; }
.stat-label {
  font-size: 11px; color: var(--text-muted); font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.6px;
}
.stat-value {
  font-size: 22px; font-weight: 800; margin-top: 6px; color: #FFF;
  letter-spacing: -0.5px;
}
.stat-sub { font-size: 12px; color: var(--text-dim); margin-top: 3px; font-weight: 500; }

/* Discord Live Profile Card */
.profile-preview-card {
  background: var(--discord-dark);
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
  margin-bottom: 18px;
}
.profile-banner {
  height: 115px;
  background: linear-gradient(135deg, #1E1B4B 0%, #4C1D95 50%, #064E3B 100%);
  background-size: cover;
  background-position: center;
  position: relative;
  transition: background-image 0.3s ease;
}
.profile-banner::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 60%, rgba(30, 31, 34, 0.8) 100%);
}
.profile-avatar-wrap {
  position: relative;
  width: 84px; height: 84px;
  margin-top: -42px; margin-left: 20px;
  z-index: 2;
}
.profile-avatar-img {
  width: 84px; height: 84px;
  border-radius: 50%;
  border: 6px solid var(--discord-dark);
  background: #111214;
  object-fit: cover;
  display: block;
}
.profile-status-dot {
  position: absolute;
  bottom: 2px; right: 2px;
  width: 22px; height: 22px;
  border-radius: 50%;
  border: 4px solid var(--discord-dark);
  background: #23A55A;
}
.status-online { background: #23A55A; }
.status-idle { background: #F0B232; }
.status-dnd { background: #F23F43; }
.status-invisible, .status-offline { background: #80848E; }

.profile-body {
  padding: 14px 20px 22px;
  background: var(--discord-dark);
}
.profile-names {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.profile-display-name {
  font-size: 19px; font-weight: 800; color: #FFF; letter-spacing: -0.3px;
}
.profile-tag {
  background: var(--discord);
  color: #FFF; font-size: 10px; font-weight: 800;
  padding: 2px 6px; border-radius: 4px;
  text-transform: uppercase; letter-spacing: 0.3px;
}
.profile-activity-box {
  margin-top: 10px; padding: 10px 14px;
  background: var(--discord-sub);
  border-radius: 10px; font-size: 12.5px;
  color: #949BA4; display: flex; align-items: center; gap: 8px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}
.profile-activity-box strong { color: #DBDEE1; font-weight: 600; }
.profile-bio-box {
  margin-top: 12px; font-size: 13px; color: #DBDEE1;
  line-height: 1.45; background: var(--discord-sub);
  padding: 12px 14px; border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}

/* Model Row */
.model-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 16px; border-radius: 12px; background: var(--bg-input);
  border: 1px solid var(--border); margin-bottom: 10px; transition: all 0.2s;
}
.model-row:hover {
  background: var(--bg-card-hover);
  border-color: rgba(168, 85, 247, 0.35);
  transform: translateX(2px);
}
.model-info { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.model-name {
  font-family: var(--mono); font-size: 13px; font-weight: 600;
  color: var(--text-main); word-break: break-all;
}
.model-meta {
  font-size: 11.5px; color: var(--text-muted);
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
}

.badge {
  padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: 800;
  text-transform: uppercase; letter-spacing: 0.4px;
}
.badge-active { background: rgba(16, 185, 129, 0.15); color: #34D399; border: 1px solid rgba(16, 185, 129, 0.3); }
.badge-cooldown { background: rgba(245, 158, 11, 0.15); color: #FBBF24; border: 1px solid rgba(245, 158, 11, 0.3); }
.badge-disabled { background: rgba(239, 68, 68, 0.15); color: #F87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.badge-untested { background: rgba(148, 163, 184, 0.15); color: var(--text-muted); border: 1px solid rgba(148, 163, 184, 0.2); }
.badge-best {
  background: linear-gradient(135deg, rgba(0, 245, 212, 0.2), rgba(168, 85, 247, 0.2));
  color: var(--cyan); border: 1px solid rgba(0, 245, 212, 0.4);
}

/* Switch Toggle */
.switch { position: relative; display: inline-block; width: 46px; height: 26px; flex-shrink: 0; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute; cursor: pointer; inset: 0;
  background-color: rgba(255, 255, 255, 0.12); transition: .25s cubic-bezier(0.16, 1, 0.3, 1);
  border-radius: 26px; border: 1px solid var(--border);
}
.slider:before {
  position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px;
  background-color: #FFF; transition: .25s cubic-bezier(0.16, 1, 0.3, 1);
  border-radius: 50%; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.4);
}
input:checked + .slider {
  background: linear-gradient(135deg, var(--cyan), #00C4A7);
  border-color: var(--cyan);
}
input:checked + .slider:before { transform: translateX(20px); background-color: #080B11; }

/* Forms & Inputs */
.form-group { margin-bottom: 16px; }
.form-label {
  font-size: 12.5px; font-weight: 700; margin-bottom: 7px;
  display: block; color: var(--text-muted); letter-spacing: 0.2px;
}
.input-text, .select {
  width: 100%; padding: 11px 14px; background: var(--bg-input);
  border: 1px solid var(--border); border-radius: 12px; color: var(--text-main);
  font-family: var(--font); font-size: 13.5px; outline: none;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.input-text:focus, .select:focus {
  border-color: var(--cyan); box-shadow: 0 0 16px var(--cyan-glow);
  background: rgba(14, 18, 30, 0.9);
}
.input-text::placeholder { color: var(--text-dim); }

.color-picker-wrap { display: flex; align-items: center; gap: 12px; }
.color-picker {
  width: 44px; height: 44px; border: none; border-radius: 12px;
  cursor: pointer; background: none; flex-shrink: 0;
}

/* Toast notifications */
#toast {
  position: fixed; bottom: 24px; right: 24px;
  background: rgba(18, 22, 36, 0.95);
  border: 1px solid var(--cyan);
  padding: 14px 22px; border-radius: 14px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6), 0 0 20px var(--cyan-glow);
  font-size: 13.5px; font-weight: 700; color: #FFF;
  display: flex; align-items: center; gap: 10px; z-index: 999;
  transform: translateY(100px); opacity: 0;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  backdrop-filter: blur(16px);
}
#toast.show { transform: translateY(0); opacity: 1; }

/* Auth Modal */
#authModal {
  position: fixed; inset: 0; background: rgba(8, 11, 17, 0.88);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
  padding: 20px;
}
.auth-card {
  background: var(--bg-card); border: 1px solid rgba(168, 85, 247, 0.3);
  padding: 38px 32px; border-radius: 24px; max-width: 400px; width: 100%;
  text-align: center; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 30px var(--purple-glow);
}
</style>
</head>
<body>

<div id="authModal" style="display: none;">
  <div class="auth-card">
    <div class="avatar-badge" style="margin: 0 auto 16px; width: 64px; height: 64px; font-size: 32px; border-radius: 18px;">🌸</div>
    <h2 style="font-size: 21px; font-weight: 800; margin-bottom: 6px; letter-spacing: -0.4px;">Aishu Dashboard</h2>
    <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 22px;">Enter your access password to unlock settings</p>
    <div class="form-group">
      <input type="password" id="authPassInput" class="input-text" placeholder="Dashboard Password..." autofocus onkeydown="if(event.key==='Enter') login()">
    </div>
    <button class="btn btn-primary" style="width: 100%; justify-content: center; padding: 13px;" onclick="login()">Unlock Dashboard ✦</button>
    <p id="authError" style="color: var(--danger); font-size: 12.5px; margin-top: 12px; display: none; font-weight: 600;">Invalid password. Please try again.</p>
  </div>
</div>

<div class="container">
  <!-- Header -->
  <header>
    <div class="brand">
      <div class="avatar-badge" id="botAvatar">🌸</div>
      <div>
        <h1 id="botName">Aishu</h1>
        <p id="botTag">Discord AI Companion • v2.6</p>
      </div>
    </div>
    <div class="header-actions">
      <div class="status-pill" id="liveStatus">Online</div>
      <button class="btn btn-purple" onclick="triggerProbe()" id="probeBtn">⚡ Benchmark All Models</button>
    </div>
  </header>

  <!-- Navigation Tabs -->
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('models')">🤖 AI Models</button>
    <button class="tab-btn" onclick="showTab('visuals')">🎨 Profile & Embeds</button>
    <button class="tab-btn" onclick="showTab('features')">⚙️ Features & AI</button>
    <button class="tab-btn" onclick="showTab('overview')">📊 Metrics & Persona</button>
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
        <div class="stat-value" style="font-size: 14.5px; font-family: var(--mono); color: var(--purple);" id="statBestModel">Analyzing...</div>
        <div class="stat-sub">Lowest latency route</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Average Latency</div>
        <div class="stat-value" id="statAvgLatency" style="font-family: var(--mono);">- ms</div>
        <div class="stat-sub">Across all providers</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Total Providers</div>
        <div class="stat-value" style="color: #38BDF8;">5</div>
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
          <label class="form-label">Model Identifier (e.g. meta-llama/llama-3.3-70b-instruct:free)</label>
          <input type="text" id="newModelName" class="input-text" placeholder="e.g. google/gemma-3-27b-it:free">
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

          <div style="font-size: 12px; color: var(--text-dim); line-height: 1.5; padding: 6px 4px 0;">
            💡 <strong>Discord API Note:</strong> Discord rate limits avatar & username changes to 2 times per hour. Status and activity changes apply live instantly.
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FEATURES & AI CONTROLS -->
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

  <!-- TAB 4: METRICS & PERSONA -->
  <div id="tab-overview" style="display: none;">
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

function showToast(msg) {
  const t = document.getElementById('toast');
  t.innerText = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

function showTab(name) {
  ['models', 'visuals', 'features', 'overview'].forEach(t => {
    document.getElementById('tab-' + t).style.display = (t === name ? 'block' : 'none');
  });
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.innerText.toLowerCase().includes(name));
  });
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

function handleFileUpload(input, type) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    if (type === 'avatar') {
      avatarDataUri = e.target.result;
      document.getElementById('settingsAvatarUrl').value = '';
      updateProfilePreview();
      showToast('Avatar image loaded for upload ✦');
    } else if (type === 'banner') {
      bannerDataUri = e.target.result;
      document.getElementById('settingsBannerUrl').value = '';
      updateProfilePreview();
      showToast('Banner image loaded for upload ✦');
    }
  };
  reader.readAsDataURL(file);
}

function updateProfilePreview() {
  const name = document.getElementById('settingsName').value.trim() || 'Aishu';
  const statusType = document.getElementById('settingsPresenceStatus').value || 'online';
  const actType = document.getElementById('settingsActivityType').value || 'playing';
  const actText = document.getElementById('settingsStatus').value.trim() || 'chatting with you ♡';
  const bio = document.getElementById('settingsPersonality').value.trim() || 'sweet, sassy, teasing, genuine';
  
  const avatarUrl = avatarDataUri || document.getElementById('settingsAvatarUrl').value.trim() || botData.avatar_url || 'https://cdn.discordapp.com/embed/avatars/0.png';
  const bannerUrl = bannerDataUri || document.getElementById('settingsBannerUrl').value.trim() || botData.banner_url || '';

  document.getElementById('prevName').innerText = name;
  document.getElementById('prevAvatar').src = avatarUrl;
  
  const bannerEl = document.getElementById('prevBanner');
  if (bannerUrl) {
    bannerEl.style.backgroundImage = `url('${bannerUrl}')`;
  } else {
    bannerEl.style.backgroundImage = 'linear-gradient(135deg, #1E1B4B 0%, #4C1D95 50%, #064E3B 100%)';
  }

  const dot = document.getElementById('prevStatusDot');
  dot.className = 'profile-status-dot status-' + statusType;

  const verbMap = {
    playing: 'Playing',
    listening: 'Listening to',
    watching: 'Watching',
    competing: 'Competing in',
    custom: 'Status'
  };
  document.getElementById('prevActivityVerb').innerText = verbMap[actType] || 'Playing';
  document.getElementById('prevActivityText').innerText = actText;
  document.getElementById('prevBio').innerText = bio;
}

async function loadAll() {
  const status = await api('status');
  if (!status) return;
  botData = status;
  
  document.getElementById('botName').innerText = status.name || 'Aishu';
  document.getElementById('botTag').innerText = status.status_text || 'chatting with you ♡';
  
  if (status.avatar_url) {
    document.getElementById('botAvatar').innerHTML = `<img src="${status.avatar_url}" alt="Aishu" style="width:100%;height:100%;object-fit:cover;">`;
  }

  document.getElementById('settingsName').value = status.name || '';
  document.getElementById('settingsStatus').value = status.status_text || '';
  document.getElementById('settingsPersonality').value = status.personality || '';
  document.getElementById('settingsPresenceStatus').value = status.status || 'online';
  document.getElementById('settingsActivityType').value = status.activity_type || 'playing';
  
  document.getElementById('embedColorPicker').value = status.embed_color || '#FFB7C5';
  document.getElementById('embedColorHex').value = status.embed_color || '#FFB7C5';
  
  if (document.getElementById('toggleVision')) {
    document.getElementById('toggleVision').checked = status.vision_enabled !== false;
  }
  if (document.getElementById('toggleImageEmbed')) {
    document.getElementById('toggleImageEmbed').checked = status.image_embed_enabled !== false;
  }
  if (document.getElementById('toggleQuiet')) {
    document.getElementById('toggleQuiet').checked = Boolean(status.quiet_mode_default);
  }
  if (document.getElementById('toggleMemory')) {
    document.getElementById('toggleMemory').checked = status.memory_enabled !== false;
  }

  document.getElementById('moodEmoji').innerText = status.mood_emoji || '🌸';
  document.getElementById('moodLabel').innerText = status.mood || 'neutral';
  document.getElementById('moodScore').innerText = `Score: ${status.mood_score || 0} / 100`;
  document.getElementById('partnerName').innerText = status.partner || 'None set';
  document.getElementById('loverName').innerText = status.lover || 'None set';
  document.getElementById('userCount').innerText = status.user_count || 0;
  document.getElementById('statBestModel').innerText = status.best_model ? status.best_model.split('/').pop() : 'Dynamic ranked';

  updateProfilePreview();
  loadModels();
}

async function loadModels() {
  const models = await api('models');
  if (!models) return;
  currentModels = models;
  document.getElementById('modelCount').innerText = models.length;
  document.getElementById('statActiveModels').innerText = models.filter(m => m.enabled && m.status !== 'disabled').length;
  
  const latencies = models.filter(m => m.avg_latency_ms > 0).map(m => m.avg_latency_ms);
  const avg = latencies.length ? Math.round(latencies.reduce((a,b)=>a+b,0)/latencies.length) : 0;
  document.getElementById('statAvgLatency').innerText = avg ? `${avg} ms` : 'N/A';
  
  renderModels();
}

function renderModels() {
  const filter = (document.getElementById('modelSearch').value || '').toLowerCase();
  const list = document.getElementById('modelsList');
  const filtered = currentModels.filter(m => m.key.toLowerCase().includes(filter) || m.provider.toLowerCase().includes(filter));
  
  if (!filtered.length) {
    list.innerHTML = '<div style="text-align:center; padding: 28px; color: var(--text-muted); font-size: 13px;">No matching models found.</div>';
    return;
  }
  
  list.innerHTML = filtered.map(m => `
    <div class="model-row">
      <div class="model-info">
        <div style="display:flex; align-items:center; gap: 8px;">
          <span class="model-name">${m.key}</span>
          ${m.is_best ? '<span class="badge badge-best">★ FAST PATH</span>' : ''}
          ${m.is_custom ? '<span class="badge" style="background:rgba(0,245,212,0.15); color:var(--cyan); border: 1px solid rgba(0,245,212,0.3);">Custom</span>' : ''}
        </div>
        <div class="model-meta">
          <span>Provider: <strong style="color: #FFF;">${m.provider}</strong></span>
          <span>Latency: <strong style="font-family: var(--mono); color: ${m.avg_latency_ms > 1500 ? '#F87171' : (m.avg_latency_ms > 500 ? '#FBBF24' : '#34D399')}">${m.avg_latency_ms ? m.avg_latency_ms + 'ms' : 'untested'}</strong></span>
          <span>Success: <strong style="color: #FFF;">${m.success_rate}%</strong></span>
          ${m.last_error ? `<span style="color:var(--danger)">Error: ${m.last_error.slice(0,35)}</span>` : ''}
        </div>
      </div>
      <div style="display:flex; align-items:center; gap: 14px;">
        <span class="badge badge-${m.status}">${m.status}</span>
        <label class="switch">
          <input type="checkbox" ${m.enabled ? 'checked' : ''} onchange="toggleModel('${m.key}', this.checked)">
          <span class="slider"></span>
        </label>
        ${m.is_custom ? `<button class="btn btn-danger" style="padding: 4px 8px; font-size:11px;" onclick="removeModel('${m.key}')">✕</button>` : ''}
      </div>
    </div>
  `).join('');
}

async function toggleModel(key, enabled) {
  const res = await api('models/toggle', {method: 'POST', body: JSON.stringify({model: key, enabled})});
  if (res && res.ok) {
    showToast(`${key.split('/').pop()} ${enabled ? 'enabled' : 'disabled'}`);
    loadModels();
  }
}

async function addModel() {
  const prefix = document.getElementById('newModelProvider').value;
  const raw = document.getElementById('newModelName').value.trim();
  if (!raw) return alert('Please enter a model name');
  const fullKey = prefix + raw;
  const res = await api('models/add', {method: 'POST', body: JSON.stringify({model: fullKey})});
  if (res && res.ok) {
    document.getElementById('newModelName').value = '';
    showToast(`Added ${fullKey}`);
    loadModels();
  } else {
    alert(res ? res.error : 'Failed to add model');
  }
}

async function removeModel(key) {
  if (!confirm(`Remove custom model: ${key}?`)) return;
  const res = await api('models/remove', {method: 'POST', body: JSON.stringify({model: key})});
  if (res && res.ok) {
    showToast(`Removed ${key}`);
    loadModels();
  }
}

async function triggerProbe() {
  const btn = document.getElementById('probeBtn');
  btn.disabled = true;
  btn.innerText = '⏳ Benchmarking Models...';
  const res = await api('models/probe', {method: 'POST'});
  btn.disabled = false;
  btn.innerText = '⚡ Benchmark All Models';
  if (res && res.ok) {
    showToast(`Benchmark complete — ${res.active} active models`);
    loadModels();
  }
}

function updateEmbedColor(hex) {
  document.getElementById('embedColorPicker').value = hex;
  document.getElementById('embedColorHex').value = hex;
}

async function saveVisualSettings() {
  const color = document.getElementById('embedColorHex').value.trim();
  const res = await api('settings/embed_color', {method: 'POST', body: JSON.stringify({color})});
  if (res && res.ok) showToast('Embed theme color saved 🌸');
}

async function saveProfileSettings() {
  const btn = document.getElementById('saveProfileBtn');
  btn.disabled = true;
  btn.innerText = '⏳ Updating Discord...';

  const name = document.getElementById('settingsName').value.trim();
  const statusText = document.getElementById('settingsStatus').value.trim();
  const personality = document.getElementById('settingsPersonality').value.trim();
  const status = document.getElementById('settingsPresenceStatus').value;
  const activityType = document.getElementById('settingsActivityType').value;
  const avatar = avatarDataUri || document.getElementById('settingsAvatarUrl').value.trim();
  const banner = bannerDataUri || document.getElementById('settingsBannerUrl').value.trim();

  const payload = {
    name,
    status_text: statusText,
    personality,
    status,
    activity_type: activityType,
    avatar: avatar || undefined,
    banner: banner || undefined,
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

// Initial load
loadAll();
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
        self._setup_routes()

    def _check_auth(self, request: web.Request) -> bool:
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {cfg.DASHBOARD_PASSWORD}"
        return auth == expected

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/ping", self.handle_health)
        self.app.router.add_post("/api/auth", self.handle_auth)
        self.app.router.add_get("/api/status", self.handle_status)
        self.app.router.add_get("/api/models", self.handle_models)
        self.app.router.add_post("/api/models/toggle", self.handle_model_toggle)
        self.app.router.add_post("/api/models/add", self.handle_model_add)
        self.app.router.add_post("/api/models/remove", self.handle_model_remove)
        self.app.router.add_post("/api/models/probe", self.handle_model_probe)
        self.app.router.add_post("/api/settings/embed_color", self.handle_embed_color)
        self.app.router.add_post("/api/settings/profile", self.handle_profile_settings)
        self.app.router.add_post("/api/settings/feature", self.handle_feature_toggle)

    async def handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_HTML_PAGE, content_type="text/html")

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "healthy",
            "bot": aishu_state.name,
            "version": "2.6",
            "uptime": True
        })

    async def handle_auth(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            if data.get("password") == cfg.DASHBOARD_PASSWORD:
                return web.json_response({"ok": True, "token": cfg.DASHBOARD_PASSWORD})
        except Exception:
            pass
        return web.json_response({"error": "Invalid password"}, status=401)

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
                async with aiohttp.ClientSession() as session:
                    async with session.get(source, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            return await resp.read()
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

        # Discord presence & profile updates
        errors = []
        if self.bot and self.bot.user:
            # 1. Update presence (status & activity)
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

            # 2. Update bot user profile (avatar, banner, username)
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
