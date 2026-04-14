'use strict';
/**
 * Voice command system — STT + TTS via Web Speech API (zero server latency)
 * Command parsing via /api/voice-command (AI, ~5-15s)
 *
 * Public API:
 *   Voice.start()          — open overlay, start listening for a food command
 *   Voice.close()          — close overlay
 *   Voice.toggleChat()     — toggle voice mode in the chat page
 *   Voice.speakIfActive(t) — speak text aloud (only when chat voice mode is on)
 */
const Voice = (() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;

  let rec        = null;
  let listening  = false;
  let chatMode   = false;   // true while voice mode is on in chat page

  // ── Speech Recognition ──────────────────────────────────────────
  function buildRec(onFinal, onInterim) {
    if (!SR) return null;
    const r = new SR();
    r.continuous      = false;
    r.interimResults  = true;
    r.lang            = 'en-US';
    r.maxAlternatives = 1;

    r.onstart = () => { listening = true; setFabState(true); };
    r.onend   = () => { listening = false; setFabState(false); };
    r.onerror = (e) => {
      listening = false; setFabState(false);
      if (e.error === 'not-allowed') {
        showOverlayMsg('error', 'Microphone access denied. Please allow mic permission and try again.');
      } else if (e.error !== 'no-speech') {
        showOverlayMsg('error', 'Microphone error: ' + e.error + '. Try again.');
      }
    };
    r.onresult = (e) => {
      const results = Array.from(e.results);
      const text    = results.map(r => r[0].transcript).join('');
      const final   = results[results.length - 1].isFinal;
      if (onInterim) onInterim(text);
      if (final && onFinal) { r.stop(); onFinal(text); }
    };
    return r;
  }

  function stopListening() {
    if (rec && listening) { try { rec.stop(); } catch (_) {} }
    listening = false;
    setFabState(false);
  }

  // ── TTS ─────────────────────────────────────────────────────────
  function speak(text, onEnd) {
    if (!synth || !text) { if (onEnd) onEnd(); return; }
    cancelSpeech();
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate   = 1.05;
    utt.pitch  = 1.0;
    utt.volume = 1.0;
    utt.lang   = 'en-US';
    // Pick best available voice
    const voices = synth.getVoices();
    const v = voices.find(v => v.name === 'Samantha')
           || voices.find(v => v.name.includes('Google') && v.lang === 'en-US')
           || voices.find(v => v.lang === 'en-US' && !v.name.toLowerCase().includes('compact'))
           || voices.find(v => v.lang.startsWith('en'));
    if (v) utt.voice = v;
    utt.onend   = () => { if (onEnd) onEnd(); };
    utt.onerror = () => { if (onEnd) onEnd(); };
    synth.speak(utt);
  }

  // Voices can load async on Chrome — retry after load if needed
  if (synth && synth.onvoiceschanged !== undefined) {
    synth.onvoiceschanged = () => {};
  }

  function cancelSpeech() {
    if (synth && synth.speaking) synth.cancel();
  }

  // Strip markdown for speech
  function plainText(md) {
    return md.replace(/[*_#`\[\]>]/g, '')
             .replace(/\n{2,}/g, '. ')
             .replace(/\n/g, ' ')
             .replace(/\s{2,}/g, ' ')
             .trim();
  }

  // ── Overlay helpers ─────────────────────────────────────────────
  function getOverlay()   { return document.getElementById('voice-overlay'); }
  function getOrb()       { return document.getElementById('voice-orb'); }
  function getStatus()    { return document.getElementById('voice-status'); }
  function getTranscript(){ return document.getElementById('voice-transcript'); }
  function getResponse()  { return document.getElementById('voice-response'); }

  const ORB_STATES = {
    ready:      'Ready — tap the orb to speak',
    listening:  'Listening…',
    processing: 'Processing…',
    speaking:   'Speaking…',
    error:      'Tap to try again',
  };

  function setOverlayState(state) {
    const orb = getOrb(); const st = getStatus();
    if (orb) orb.className = 'voice-orb voice-orb-' + state;
    if (st)  st.textContent = ORB_STATES[state] || state;
  }

  function showOverlayMsg(state, msg) {
    setOverlayState(state);
    const r = getResponse();
    if (r) r.textContent = msg;
  }

  function setFabState(on) {
    const fab = document.getElementById('voice-fab');
    if (fab) fab.classList.toggle('listening', on);
  }

  // ── Command mode (overlay) ──────────────────────────────────────
  function start() {
    if (!SR) {
      alert('Voice commands require Chrome, Edge, or Safari.\nPlease switch browsers.');
      return;
    }
    chatMode = false;
    cancelSpeech();

    const ov = getOverlay();
    if (ov) {
      ov.classList.add('active');
      setOverlayState('ready');
      const t = getTranscript(); if (t) t.textContent = '';
      const r = getResponse();   if (r) r.textContent = '';
    }

    _startCommandRec();
  }

  function _startCommandRec() {
    rec = buildRec(
      (text) => {
        // Final transcript — process as command
        setOverlayState('processing');
        processCommand(text);
      },
      (text) => {
        // Interim — show live transcript
        const t = getTranscript();
        if (t) { t.textContent = text; t.style.opacity = '0.65'; }
      }
    );
    if (rec) {
      rec.start();
      setOverlayState('listening');
    }
  }

  function close() {
    const ov = getOverlay();
    if (ov) ov.classList.remove('active');
    stopListening();
    cancelSpeech();
  }

  // Tap orb to re-listen after error / response
  function orbTap() {
    const st = getStatus();
    if (!st) return;
    const t = getTranscript(); if (t) t.textContent = '';
    const r = getResponse();   if (r) r.textContent = '';
    cancelSpeech();
    _startCommandRec();
  }

  // ── Process voice command via server ────────────────────────────
  async function processCommand(transcript) {
    if (!transcript.trim()) { setOverlayState('ready'); return; }

    // Show final transcript
    const t = getTranscript();
    if (t) { t.textContent = '"' + transcript + '"'; t.style.opacity = '1'; }

    try {
      const res = await fetch('/api/voice-command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: transcript, page: window.location.pathname })
      });
      const data = await res.json();
      const spokenText = data.speak || 'Done.';

      const r = getResponse();
      if (r) r.textContent = spokenText;
      setOverlayState('speaking');

      speak(spokenText, () => {
        // After speaking: apply action, then close overlay
        applyAction(data);
        setTimeout(close, 600);
      });
    } catch (e) {
      showOverlayMsg('error', 'Connection error. Please try again.');
      speak('Connection error. Please try again.');
    }
  }

  // ── Apply server action to current page DOM ─────────────────────
  function applyAction(data) {
    const action = data.action;
    const isLogPage = window.location.pathname === '/log';
    const isDash    = window.location.pathname === '/dashboard';

    if (action === 'add_food' && data.log) {
      if (isLogPage && typeof addRowToTable === 'function') {
        addRowToTable(data.log);
        if (typeof voiceUpdateCalories === 'function') voiceUpdateCalories(data.log.calories);
      } else {
        // Other pages: do a soft reload to reflect the new entry
        setTimeout(() => location.reload(), 800);
        return;
      }
      if (data.achievements && data.achievements.length) handleAchievements(data.achievements);
    }

    if (action === 'edit_food' && data.log_id && data.log) {
      const row = document.getElementById('row-' + data.log_id);
      if (row) {
        const oldCal = parseInt(row.querySelector('.log-kcal').textContent) || 0;
        if (typeof voiceUpdateCalories === 'function') voiceUpdateCalories(data.log.calories - oldCal);
        row.querySelector('.log-food-name').textContent = data.log.food_name;
        const mealTag = row.querySelector('.meal-tag');
        if (mealTag) {
          mealTag.textContent = data.log.meal_type.charAt(0).toUpperCase() + data.log.meal_type.slice(1);
          mealTag.className = 'meal-tag meal-tag-' + data.log.meal_type;
        }
        const macros = row.querySelectorAll('.log-macro');
        if (macros[0]) macros[0].textContent = data.log.protein_g + 'g';
        if (macros[1]) macros[1].textContent = data.log.carbs_g + 'g';
        if (macros[2]) macros[2].textContent = data.log.fat_g + 'g';
        row.querySelector('.log-kcal').textContent = data.log.calories + ' kcal';
      } else {
        setTimeout(() => location.reload(), 800);
      }
    }

    if (action === 'delete_food' && data.log_id) {
      const row = document.getElementById('row-' + data.log_id);
      if (row) {
        const kcalEl = row.querySelector('.log-kcal');
        if (kcalEl && typeof voiceUpdateCalories === 'function')
          voiceUpdateCalories(-(parseInt(kcalEl.textContent) || 0));
        row.style.opacity = '0';
        setTimeout(() => row.remove(), 200);
      } else {
        setTimeout(() => location.reload(), 800);
      }
    }

    // Refresh dashboard ring stats silently
    if ((isDash || isLogPage) && (action === 'add_food' || action === 'edit_food' || action === 'delete_food')) {
      if (isDash && typeof loadStats === 'function') loadStats();
    }
  }

  // ── Chat voice mode ─────────────────────────────────────────────
  function toggleChat() {
    if (!SR) {
      alert('Voice input requires Chrome, Edge, or Safari.');
      return;
    }
    chatMode = !chatMode;
    const btn = document.getElementById('voice-chat-btn');
    if (btn) btn.classList.toggle('active', chatMode);

    if (chatMode) {
      cancelSpeech();
      startChatListening();
    } else {
      stopListening();
    }
  }

  function startChatListening() {
    rec = buildRec(
      (text) => {
        // Fill the chat input and submit
        const input = document.getElementById('chat-input');
        if (input) {
          input.value = text;
          if (typeof autoResize === 'function') autoResize(input);
        }
        if (typeof sendMessage === 'function') sendMessage();
        // Don't auto-restart — wait for AI + TTS to finish (speakIfActive handles it)
      },
      (text) => {
        const input = document.getElementById('chat-input');
        if (input) input.value = text;
      }
    );
    if (rec) rec.start();
  }

  // Called from chat.html after AI responds
  function speakIfActive(text, onEnd) {
    if (!chatMode) { if (onEnd) onEnd(); return; }
    const plain = plainText(text);
    speak(plain, () => {
      if (onEnd) onEnd();
      // Auto-restart listening for next turn
      if (chatMode) {
        setTimeout(() => startChatListening(), 400);
      }
    });
  }

  // Expose for pages to update calorie counter bridge
  return { start, close, orbTap, toggleChat, speakIfActive };
})();
