// Temple Crowd Monitoring & Prediction Dashboard
// Fetches data from the PHP API every 5 seconds and updates the UI.

const API_URL = 'api/stats.php';
const REFRESH_MS = 5000;

const $ = (id) => document.getElementById(id);

function formatNumber(n) {
  return Number(n || 0).toLocaleString('en-IN');
}

// Gate names come from devices, so escape them before using innerHTML.
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

function capitalize(text) {
  if (!text) return '';
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function setBadge(el, text, cssClass) {
  if (!el) return;
  el.textContent = text;
  el.className = 'badge ' + cssClass;
}

// Tracks whether we currently have a live connection
let _isLiveConnected = false;

function setLive(isOn) {
  _isLiveConnected = isOn;
  const dot = $('liveDot');
  if (dot) dot.className = 'dot ' + (isOn ? 'on' : 'off');
  if (!isOn) {
    const text = $('liveText');
    if (text) text.textContent = 'Connection lost';
  }
  // If reconnected, immediately refresh the clock display
  if (isOn) updateLiveClockDisplay();
}

function updateLiveClockDisplay() {
  const text = $('liveText');
  if (!text || !_isLiveConnected) return;
  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  text.textContent = 'Live · ' + timeStr;
}

function startLiveClock() {
  // Tick every second to keep the displayed time accurate
  setInterval(updateLiveClockDisplay, 1000);
}

function renderSummary(summary, deviceInfo) {
  if ($('entries')) $('entries').textContent = formatNumber(summary.entries);
  if ($('exits')) $('exits').textContent = formatNumber(summary.exits);
  if ($('occupancy')) $('occupancy').textContent = formatNumber(summary.occupancy);

  const pct = Math.min(summary.occupancy_percent, 100);
  if ($('occupancyBar')) $('occupancyBar').style.width = pct + '%';
  if ($('occupancyNote')) {
    $('occupancyNote').textContent =
      summary.occupancy_percent + '% of ' + formatNumber(summary.capacity) + ' capacity';
  }

  // Device status in header pill and panel
  if ($('deviceCount')) {
    $('deviceCount').textContent = deviceInfo.online + ' / ' + deviceInfo.total + ' Devices';
  }
  if ($('devicePillDot')) {
    let dotClass = 'off';
    if (deviceInfo.online > 0 && deviceInfo.online === deviceInfo.total) {
      dotClass = 'on';
    } else if (deviceInfo.online > 0) {
      dotClass = 'partial';
    }
    $('devicePillDot').className = 'pill-dot ' + dotClass;
  }
  if ($('deviceStatus')) {
    setBadge($('deviceStatus'), deviceInfo.label, deviceInfo.status);
  }
}

function renderPrediction(prediction) {
  if (!prediction) return;

  if ($('predCurrentCrowd')) {
    $('predCurrentCrowd').textContent = formatNumber(prediction.current_crowd);
  }

  if ($('predExpectedCrowd')) {
    $('predExpectedCrowd').textContent = '≈ ' + formatNumber(prediction.expected_crowd);
  }

  if ($('predStatusDot')) {
    $('predStatusDot').className = 'sphere-dot ' + (prediction.status_level || 'normal');
  }

  if ($('predStatusText')) {
    $('predStatusText').textContent = prediction.status_text || 'Normal Crowd Expected';
    $('predStatusText').className = 'status-highlight ' + (prediction.status_level || 'normal');
  }

  if ($('predChangeLabel')) {
    $('predChangeLabel').textContent = (prediction.approx_change < 0) ? 'APPROX. DECREASE' : 'APPROX. INCREASE';
  }

  if ($('predApproxChange')) {
    $('predApproxChange').textContent = prediction.approx_change_text || '+0 People';
  }

  if ($('predMessage')) {
    $('predMessage').textContent = prediction.message || 'Crowd is expected to remain steady within the next hour.';
  }

  if ($('predUpdatedText')) {
    $('predUpdatedText').textContent = 'Last updated ' + (prediction.updated_time || 'just now');
  }
}

function capitalizeWords(str) {
  if (!str) return '';
  return String(str).replace(/\b\w/g, (l) => l.toUpperCase());
}

function formatShortIp(ip) {
  if (!ip) return '';
  return String(ip).replace(/^https?:\/\//i, '').replace(/\/stream$/i, '').replace(/\/$/, '');
}

function renderGates(gates) {
  const body = $('gatesBody');
  if (!body) return;

  if (!gates || gates.length === 0) {
    body.innerHTML = '<tr><td colspan="6" class="empty">No devices registered yet</td></tr>';
    return;
  }

  body.innerHTML = gates.map((g) => {
    const isEntry = g.direction === 'entry';
    const isBoth = g.direction === 'both';
    const isOnline = Boolean(g.online);
    const gateLabel = capitalizeWords(g.gate_name || 'Main Gate');
    const hasStream = Boolean(g.stream_url || g.ip_address);
    const streamTarget = g.stream_url || (g.ip_address ? `http://${g.ip_address}` : '');
    const aiFeedUrl = g.ai_feed_url || '';
    const hasAiFeed = Boolean(aiFeedUrl);
    const aiOn = Boolean(g.ai_enabled) || hasAiFeed;
    const isAi = Boolean(g.is_ai || hasAiFeed);

    let dirBadgeHtml = '';
    if (isBoth) {
      dirBadgeHtml = `<span class="badge-direction both"><span class="dir-icon">↕</span> Both</span>`;
    } else if (isEntry) {
      dirBadgeHtml = `<span class="badge-direction entry"><span class="dir-icon">↓</span> Entry</span>`;
    } else {
      dirBadgeHtml = `<span class="badge-direction exit"><span class="dir-icon">↑</span> Exit</span>`;
    }

    const aiBadge = isAi
      ? `<span class="badge-ai" title="AI counting active${g.ai_model ? ' (' + escapeHtml(g.ai_model) + ')' : ''}">AI</span>`
      : '';

    const insideTag = isAi && Number(g.ai_inside) > 0
      ? `<span class="ai-inside-tag" title="People currently inside (reported by the AI tracker)">inside ${formatNumber(g.ai_inside)}</span>`
      : '';

    return `
      <tr>
        <td data-label="Gate">
          <div class="gate-cell">
            <span class="gate-name">${escapeHtml(gateLabel)}</span>
            ${aiBadge}
          </div>
        </td>
        <td data-label="Device / IP">
          <div class="device-cell">
            <span class="device-id-tag">${escapeHtml(g.device_id)}</span>
            ${g.ip_address 
              ? `<span class="ip-tag ip-copyable" onclick="copyIpAddress('${escapeHtml(g.ip_address)}')" title="Click to copy IP: ${escapeHtml(g.ip_address)}"><svg class="ip-mini-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>${escapeHtml(formatShortIp(g.ip_address))}</span>` 
              : '<span class="ip-tag-none">No IP</span>'}
            ${insideTag}
          </div>
        </td>
        <td data-label="Direction" class="text-center">
          ${dirBadgeHtml}
        </td>
        <td data-label="Status" class="text-center">
          <span class="badge-status ${isOnline ? 'online' : 'offline'}">
            <span class="status-indicator-dot"></span>
            ${isOnline ? 'Online' : 'Offline'}
          </span>
        </td>
        <td data-label="In / Out" class="text-center">
          <div class="count-pair">
            <span class="count-pill count-in" title="Entries today">↓ ${formatNumber(g.entry_count)}</span>
            <span class="count-pill count-out" title="Exits today">↑ ${formatNumber(g.exit_count)}</span>
          </div>
        </td>
        <td data-label="Action" class="text-center action-cell">
          ${hasStream ? `
            <button type="button" class="btn-action-stream" onclick="openStreamModal('${escapeHtml(streamTarget)}', '${escapeHtml(gateLabel)}', '${escapeHtml(aiFeedUrl)}')" title="View Live Camera Stream" aria-label="View stream">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
            </button>
          ` : ''}
          ${hasAiFeed ? `
            <button type="button" class="btn-action-ai" onclick="openStreamModal('${escapeHtml(aiFeedUrl)}', '${escapeHtml(gateLabel)}', '${escapeHtml(aiFeedUrl)}')" title="View AI annotated feed (boxes + counting line)" aria-label="View AI feed">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a2 2 0 0 0-2 2v1a6 6 0 0 0-6 6v3a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2v-3a6 6 0 0 0-6-6V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="2"/></svg>
            </button>
          ` : ''}
          ${hasStream ? `
            <button type="button" class="btn-action-ai-toggle ${aiOn ? 'active' : ''}" onclick="toggleAiCounting('${escapeHtml(g.device_id)}', ${aiOn ? 'false' : 'true'})" title="${aiOn ? 'AI counting is ON - click to stop the AI tracker for this camera' : 'Start AI counting for this camera'}" aria-label="Toggle AI counting">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a2 2 0 0 0-2 2v1a6 6 0 0 0-6 6v3a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2v-3a6 6 0 0 0-6-6V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="2"/></svg>
            </button>
          ` : ''}
          <button type="button" class="btn-action-delete" onclick="deleteCameraDevice('${escapeHtml(g.device_id)}')" title="Remove this camera" aria-label="Remove camera">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

// Enable / disable AI counting (YOLO tracker) for a camera
async function toggleAiCounting(deviceId, enable) {
  if (!deviceId) return;
  try {
    const res = await fetch('api/devices.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId, ai_enabled: enable }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Failed to update camera');

    await loadStats();
    showToast(enable
      ? `AI counting enabled for ${deviceId} - the tracker will start within seconds`
      : `AI counting disabled for ${deviceId}`);
  } catch (err) {
    alert('Error updating camera: ' + err.message);
  }
}

// Delete camera device
async function deleteCameraDevice(deviceId) {
  if (!deviceId) return;
  if (!confirm(`Are you sure you want to remove device "${deviceId}"?`)) return;

  try {
    const res = await fetch('api/devices.php', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Failed to delete device');

    await loadStats();
  } catch (err) {
    alert('Error removing camera: ' + err.message);
  }
}

// Setup Manual Add Camera Form
function initAddCameraUI() {
  const toggleBtn = $('toggleAddCameraBtn');
  const cancelBtn = $('btnCancelAddCamera');
  const container = $('addCameraContainer');
  const form      = $('addCameraForm');
  const feedback  = $('formFeedback');

  if (toggleBtn && container) {
    toggleBtn.addEventListener('click', () => {
      const isHidden = container.style.display === 'none';
      container.style.display = isHidden ? 'block' : 'none';
      if (isHidden) {
        $('inputIpAddress').focus();
        feedback.style.display = 'none';
      }
    });
  }

  if (cancelBtn && container) {
    cancelBtn.addEventListener('click', () => {
      container.style.display = 'none';
      feedback.style.display = 'none';
      form.reset();
      if (window.resetDirectionDropdown) window.resetDirectionDropdown();
    });
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const ip = $('inputIpAddress').value.trim();
      const gate = $('inputGateName').value.trim();
      const device = $('inputDeviceId').value.trim();
      const direction = $('inputDirection').value;
      const saveBtn = $('btnSaveCamera');

      if (!ip) {
        feedback.textContent = 'Please enter a camera IP address';
        feedback.className = 'form-feedback error';
        feedback.style.display = 'inline-block';
        return;
      }

      saveBtn.disabled = true;
      saveBtn.textContent = 'Connecting…';
      feedback.textContent = 'Pinging camera and saving…';
      feedback.className = 'form-feedback info';
      feedback.style.display = 'inline-block';

      try {
        const res = await fetch('api/devices.php', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ip_address: ip,
            gate_name: gate,
            device_id: device,
            direction: direction
          }),
        });

        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'Failed to save camera');

        feedback.textContent = data.message;
        feedback.className = 'form-feedback success';
        feedback.style.display = 'inline-block';
        form.reset();
        if (window.resetDirectionDropdown) window.resetDirectionDropdown();

        await loadStats();

        setTimeout(() => {
          container.style.display = 'none';
          feedback.style.display = 'none';
        }, 2000);
      } catch (err) {
        feedback.textContent = err.message;
        feedback.className = 'form-feedback error';
        feedback.style.display = 'inline-block';
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Connect & Save';
      }
    });
  }
}

// Custom Direction Dropdown Handler
function initCustomDropdown() {
  const dropdown = $('customDirectionDropdown');
  const trigger = $('customDropdownTrigger');
  const menu = $('customDropdownMenu');
  const hiddenInput = $('inputDirection');
  if (!dropdown || !trigger || !menu || !hiddenInput) return;

  const options = menu.querySelectorAll('.custom-dropdown-option');

  function setDropdownValue(value) {
    hiddenInput.value = value;
    options.forEach((opt) => {
      const isMatch = opt.dataset.value === value;
      opt.classList.toggle('selected', isMatch);
      opt.setAttribute('aria-selected', isMatch ? 'true' : 'false');
      if (isMatch) {
        const iconHtml = opt.querySelector('.dropdown-icon-pill').outerHTML;
        const titleText = opt.querySelector('.option-title').textContent;
        const selectedContainer = trigger.querySelector('.dropdown-selected-val');
        if (selectedContainer) {
          selectedContainer.innerHTML = `${iconHtml}<span class="dropdown-text">${titleText}</span>`;
        }
      }
    });
  }

  function toggleMenu(force) {
    const isOpen = typeof force === 'boolean' ? force : !dropdown.classList.contains('open');
    dropdown.classList.toggle('open', isOpen);
    trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  }

  trigger.addEventListener('click', (e) => {
    e.preventDefault();
    toggleMenu();
  });

  options.forEach((opt) => {
    opt.addEventListener('click', () => {
      setDropdownValue(opt.dataset.value);
      toggleMenu(false);
      trigger.focus();
    });

    opt.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setDropdownValue(opt.dataset.value);
        toggleMenu(false);
        trigger.focus();
      }
    });
  });

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (!dropdown.contains(e.target)) {
      toggleMenu(false);
    }
  });

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && dropdown.classList.contains('open')) {
      toggleMenu(false);
      trigger.focus();
    }
  });

  // Attach reset method to window for form reset hooks
  window.resetDirectionDropdown = () => {
    setDropdownValue('entry');
    toggleMenu(false);
  };
}

let currentRecentEvents = [];

function renderActivity(events) {
  const list = $('activityList');
  if (!list) return;

  currentRecentEvents = events || [];

  if (!events || events.length === 0) {
    list.innerHTML = `
      <li class="empty">
        <svg class="activity-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        <span class="activity-empty-title">No recent activity yet today</span>
        <span class="activity-empty-sub">Live visitor entries and exits from connected cameras will appear here automatically.</span>
      </li>
    `;
    return;
  }

  list.innerHTML = events.map((e) => {
    const isEntry = e.direction === 'entry';
    const gateLabel = capitalizeWords(e.gate_name || 'Gate');
    const deviceTag = e.device_id || '';

    return `
      <li class="activity-row">
        <div class="activity-row-left">
          <div class="activity-icon-badge ${isEntry ? 'entry' : 'exit'}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              ${isEntry ? '<polyline points="7 10 12 15 17 10"/>' : '<polyline points="7 14 12 9 17 14"/>'}
            </svg>
          </div>
          <div class="activity-meta-block">
            <div class="activity-title-line">
              <span class="activity-gate-name">${escapeHtml(gateLabel)}</span>
              ${deviceTag ? `<span class="activity-device-chip">${escapeHtml(deviceTag)}</span>` : ''}
            </div>
            <div class="activity-sub-line">
              <svg class="activity-clock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              <span class="activity-timestamp">${escapeHtml(e.time)}</span>
            </div>
          </div>
        </div>

        <div class="activity-row-right">
          <span class="activity-badge-pill ${isEntry ? 'entry' : 'exit'}">
            <span class="dir-arrow">${isEntry ? '↓' : '↑'}</span> ${isEntry ? 'Entry' : 'Exit'} · +${formatNumber(e.count)}
          </span>
          <button type="button" class="btn-copy-item" onclick="copySingleEvent('${escapeHtml(e.time)}', '${escapeHtml(gateLabel)}', '${escapeHtml(deviceTag)}', '${isEntry ? 'Entry' : 'Exit'}', ${e.count})" title="Copy this event" aria-label="Copy event">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
          </button>
        </div>
      </li>
    `;
  }).join('');
}

async function loadStats() {
  try {
    const response = await fetch(API_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error('HTTP ' + response.status);

    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'API error');

    renderSummary(data.summary, data.devices);
    renderPrediction(data.prediction);
    renderGates(data.gates);
    renderActivity(data.recent);
    setLive(true);
  } catch (error) {
    console.error('Could not load stats:', error);
    setLive(false);
  }
}

// Live Camera Stream Modal
let streamSources = { camera: '', ai: '' };
let streamRealUrls = { camera: '', ai: '' };  // display-only

/**
 * Normalise and optionally proxy a stream URL.
 * - AI preview URLs (127.0.0.1:8090) are served from the same LAN so
 *   we just ensure they are absolute and rely on the CORS headers the
 *   tracker now sends.
 * - Camera/ESP32-CAM URLs that differ in host from window.location are
 *   proxied through api/proxy_stream.php so the browser never makes a
 *   cross-origin request.
 */
function normaliseStreamUrl(url, isAi) {
  let fullUrl = (url || '').trim();
  if (!fullUrl) return '';
  if (!fullUrl.startsWith('http://') && !fullUrl.startsWith('https://')) {
    fullUrl = 'http://' + fullUrl;
  }
  if (isAi) {
    // AI preview comes from the Python server which now sends CORS headers.
    return fullUrl;
  }
  // For raw camera streams from a different host, proxy through PHP to avoid
  // browser CORS / mixed-content blocks.
  try {
    const u = new URL(fullUrl);
    if (u.hostname !== window.location.hostname) {
      return 'api/proxy_stream.php?url=' + encodeURIComponent(fullUrl);
    }
  } catch (_) {}
  return fullUrl;
}

function setStreamSource(source) {
  const img = $('streamVideoImg');
  const urlTag = $('streamModalUrl');
  const container = $('streamVideoContainer');
  const target = streamSources[source] || streamSources.camera || streamSources.ai || '';

  if (img) img.src = target;
  if (container) container.classList.remove('stream-error');
  // Show the real (un-proxied) URL in the footer for clarity
  if (urlTag) urlTag.textContent = streamRealUrls[source] || target || 'Stream endpoint';

  const cameraBtn = $('streamSourceCamera');
  const aiBtn = $('streamSourceAi');
  if (cameraBtn) cameraBtn.classList.toggle('active', source === 'camera');
  if (aiBtn) aiBtn.classList.toggle('active', source === 'ai');
}

function openStreamModal(streamUrl, gateName, aiFeedUrl) {
  const modal = $('streamModal');
  const img = $('streamVideoImg');
  const title = $('streamModalTitle');
  const container = $('streamVideoContainer');
  if (!modal || !img) return;

  const rawCamera = streamUrl  ? (streamUrl.startsWith('http') ? streamUrl : 'http://' + streamUrl) : '';
  const rawAi     = aiFeedUrl ? (aiFeedUrl.startsWith('http') ? aiFeedUrl : 'http://' + aiFeedUrl) : '';

  streamRealUrls = { camera: rawCamera, ai: rawAi };
  streamSources = {
    camera: rawCamera ? normaliseStreamUrl(rawCamera, false) : '',
    ai:     rawAi    ? normaliseStreamUrl(rawAi, true)        : '',
  };

  if (container) container.classList.remove('stream-error');
  if (title) title.textContent = `${gateName || 'Gate Camera'} - Live Feed`;

  const aiBtn = $('streamSourceAi');
  const cameraBtn = $('streamSourceCamera');
  if (aiBtn) {
    aiBtn.style.display = streamSources.ai ? 'inline-flex' : 'none';
    aiBtn.disabled = !streamSources.ai;
  }
  if (cameraBtn) {
    cameraBtn.style.display = streamSources.camera ? 'inline-flex' : 'none';
    cameraBtn.disabled = !streamSources.camera;
  }

  // Prefer the AI overlay when the gate only has an AI feed available
  const preferred = streamSources.camera ? 'camera' : (streamSources.ai ? 'ai' : 'camera');
  setStreamSource(preferred);

  modal.style.display = 'flex';
}

function closeStreamModal() {
  const modal = $('streamModal');
  const img = $('streamVideoImg');
  if (modal) modal.style.display = 'none';
  if (img) img.src = '';
}

function initStreamModal() {
  const modal = $('streamModal');
  const closeBtn1 = $('closeStreamModalBtn');
  const closeBtn2 = $('closeStreamModalBtn2');
  const cameraBtn = $('streamSourceCamera');
  const aiBtn = $('streamSourceAi');

  if (closeBtn1) closeBtn1.addEventListener('click', closeStreamModal);
  if (closeBtn2) closeBtn2.addEventListener('click', closeStreamModal);

  if (cameraBtn) cameraBtn.addEventListener('click', () => setStreamSource('camera'));
  if (aiBtn) aiBtn.addEventListener('click', () => setStreamSource('ai'));

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeStreamModal();
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal && modal.style.display !== 'none') {
      closeStreamModal();
    }
  });
}

// Clipboard & Export Utilities
function fallbackCopy(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    ta.setAttribute('readonly', '');
    document.body.appendChild(ta);
    ta.select();
    const success = document.execCommand('copy');
    document.body.removeChild(ta);
    return success;
  } catch (err) {
    return false;
  }
}

function copyToClipboard(text) {
  return new Promise((resolve) => {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(resolve).catch(() => {
        fallbackCopy(text);
        resolve();
      });
    } else {
      fallbackCopy(text);
      resolve();
    }
  });
}

let toastTimer = null;
function showToast(message) {
  const toast = $('toastNotification');
  if (!toast) return;

  toast.textContent = message;
  toast.classList.add('visible');

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove('visible');
  }, 2400);
}

function copyIpAddress(ip) {
  if (!ip) return;
  copyToClipboard(ip).then(() => {
    showToast(`Copied IP: ${ip}`);
  }).catch(() => {
    showToast('Failed to copy IP');
  });
}

function copySingleEvent(time, gate, device, direction, count) {
  const line = `[${time}] ${gate}${device ? ' (' + device + ')' : ''}: ${direction} +${count}`;
  copyToClipboard(line).then(() => {
    showToast(`Copied: ${gate} (${direction})`);
  }).catch(() => {
    showToast('Failed to copy event');
  });
}

function copyRecentActivity() {
  const copyBtn = $('btnCopyActivity');
  const copyText = $('copyActivityText');

  if (!currentRecentEvents || currentRecentEvents.length === 0) {
    showToast('No recent activity to copy');
    return;
  }

  const now = new Date().toLocaleString();
  let text = `Temple Crowd Monitoring - Recent Activity Log\nExported: ${now}\n\n`;
  text += `Time | Gate | Device | Direction | Count\n`;
  text += `-----------------------------------------------------------\n`;

  currentRecentEvents.forEach((e) => {
    const isEntry = e.direction === 'entry';
    const dirStr = isEntry ? 'Entry' : 'Exit';
    const gateStr = capitalizeWords(e.gate_name || 'Gate');
    const devStr = e.device_id || '-';
    text += `${e.time} | ${gateStr} | ${devStr} | ${dirStr} | +${e.count}\n`;
  });

  copyToClipboard(text).then(() => {
    if (copyText) copyText.textContent = 'Copied!';
    if (copyBtn) copyBtn.classList.add('copied');
    showToast('Recent activity log copied to clipboard!');

    setTimeout(() => {
      if (copyText) copyText.textContent = 'Copy';
      if (copyBtn) copyBtn.classList.remove('copied');
    }, 2000);
  }).catch(() => {
    showToast('Failed to copy activity log');
  });
}

function exportRecentActivityCsv() {
  if (!currentRecentEvents || currentRecentEvents.length === 0) {
    showToast('No recent activity to export');
    return;
  }

  // Prepend UTF-8 BOM so Microsoft Excel and other spreadsheet apps render characters perfectly
  let csv = '\uFEFF"Timestamp","Gate Name","Device ID","Direction","Count"\r\n';

  currentRecentEvents.forEach((e) => {
    const isEntry = e.direction === 'entry';
    const timeVal = (e.created_at || e.time || '').replace(/"/g, '""');
    const gateVal = (capitalizeWords(e.gate_name || 'Gate')).replace(/"/g, '""');
    const devVal = (e.device_id || '').replace(/"/g, '""');
    const dirVal = isEntry ? 'Entry' : 'Exit';
    const cntVal = e.count || 1;

    csv += `"${timeVal}","${gateVal}","${devVal}","${dirVal}",${cntVal}\r\n`;
  });

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `temple_activity_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  showToast('Activity log exported as CSV!');
}

function initActivityExportCopy() {
  const copyBtn = $('btnCopyActivity');
  const exportBtn = $('btnExportActivity');

  if (copyBtn) {
    copyBtn.addEventListener('click', copyRecentActivity);
  }
  if (exportBtn) {
    exportBtn.addEventListener('click', exportRecentActivityCsv);
  }
}

// Initial fetch + periodic polling
loadStats();
initAddCameraUI();
initCustomDropdown();
initStreamModal();
initActivityExportCopy();
startLiveClock();
setInterval(loadStats, REFRESH_MS);
