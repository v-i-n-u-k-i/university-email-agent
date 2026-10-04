const UNIVERSITY_ADDRESS = 'fake_uni@westbridge.edu';
const ACTIVITY_STEPS = [
  'Email received',
  'Reading email',
  'Checking student eligibility',
  'Searching withdrawal policy',
  'Creating support ticket',
  'Sending response',
  'Request completed',
];

const state = {
  folder: 'inbox',
  emails: [],
  selectedId: null,
  busy: false,
  activity: [],
};

const elements = {
  topbar: document.querySelector('.topbar'),
  mailShell: document.querySelector('.mail-shell'),
  agentOverlay: document.querySelector('#agent-overlay'),
  folderTitle: document.querySelector('#folder-title'),
  listEyebrow: document.querySelector('#list-eyebrow'),
  emailList: document.querySelector('#email-list'),
  emptyList: document.querySelector('#empty-list'),
  listError: document.querySelector('#list-error'),
  messageTotal: document.querySelector('#message-total'),
  inboxCount: document.querySelector('#inbox-count'),
  readerEmpty: document.querySelector('#reader-empty'),
  emailReader: document.querySelector('#email-reader'),
  composeView: document.querySelector('#compose-view'),
  composeButton: document.querySelector('#compose-button'),
  emptyCompose: document.querySelector('#empty-compose'),
  closeCompose: document.querySelector('#close-compose'),
  refreshButton: document.querySelector('#refresh-button'),
  form: document.querySelector('#compose-view'),
  subject: document.querySelector('#subject'),
  body: document.querySelector('#body'),
  sendButton: document.querySelector('#send-button'),
  status: document.querySelector('#agent-status'),
  statusTitle: document.querySelector('#status-title'),
  statusMessage: document.querySelector('#status-message'),
  statusDismiss: document.querySelector('#status-dismiss'),
  activitySteps: document.querySelector('#activity-steps'),
  activityCurrentTool: document.querySelector('#activity-current-tool'),
  activityProgressFill: document.querySelector('#activity-progress-fill'),
  securityModeToggle: document.querySelector('#security-mode-toggle'),
  securityModeLabel: document.querySelector('#security-mode-label'),
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character]);
}

function senderDetails(sender) {
  const match = sender.match(/^(.*?)\s*<([^>]+)>$/);
  return match
    ? { name: match[1].trim(), address: match[2].trim() }
    : { name: sender, address: '' };
}

function formatDate(value, compact = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const options = compact
    ? { month: 'short', day: 'numeric' }
    : { weekday: 'short', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' };
  return new Intl.DateTimeFormat('en', options).format(date);
}

function showStatus(message, stateName = 'working', title = 'Agent activity') {
  elements.status.hidden = false;
  elements.agentOverlay.hidden = false;
  elements.agentOverlay.setAttribute('aria-hidden', 'false');
  elements.topbar.inert = true;
  elements.mailShell.inert = true;
  elements.status.classList.toggle('is-working', stateName === 'working');
  elements.status.classList.toggle('is-error', stateName === 'error');
  elements.statusTitle.textContent = title;
  elements.statusMessage.textContent = message;
}

function hideStatus() {
  elements.status.hidden = true;
  elements.agentOverlay.hidden = true;
  elements.agentOverlay.setAttribute('aria-hidden', 'true');
  elements.topbar.inert = false;
  elements.mailShell.inert = false;
  elements.status.classList.remove('is-working', 'is-error');
  state.activity = [];
  elements.activitySteps.replaceChildren();
  elements.activityCurrentTool.textContent = 'Waiting for agent';
  elements.activityProgressFill.style.width = '0%';
}

function resetActivity() {
  state.activity = [];
  elements.activitySteps.replaceChildren();
  elements.activityCurrentTool.textContent = 'Waiting for agent';
  elements.activityProgressFill.style.width = '0%';
  elements.status.classList.remove('is-error');
}

function renderActivity(event) {
  showStatus(event.message, event.status === 'error' ? 'error' : 'working');
  if (event.tool) {
    elements.activityCurrentTool.textContent = event.tool;
  } else if (event.done && event.status === 'completed') {
    elements.activityCurrentTool.textContent = 'All tools finished';
  }

  const stepIndex = ACTIVITY_STEPS.indexOf(event.message);
  if (stepIndex >= 0 && state.activity.at(-1) !== event.message) {
    state.activity.push(event.message);
  }
  if (event.message === 'Request could not be completed') {
    state.activity.push(event.message);
  }

  elements.activitySteps.innerHTML = state.activity.map((step, index) => {
    const isCurrent = index === state.activity.length - 1 && !event.done;
    const className = event.message === 'Request could not be completed' && index === state.activity.length - 1
      ? 'is-error'
      : isCurrent ? 'is-current' : 'is-complete';
    return `<li class="activity-step ${className}"><span class="activity-step-marker" aria-hidden="true"></span><span>${escapeHtml(step)}</span></li>`;
  }).join('');

  const progress = stepIndex >= 0
    ? (stepIndex / (ACTIVITY_STEPS.length - 1)) * 100
    : 0;
  elements.activityProgressFill.style.width = `${progress}%`;
}

function applySecurityMode(mode) {
  const vulnerable = mode === 'vulnerable';
  elements.securityModeToggle.checked = !vulnerable;
  elements.securityModeLabel.textContent = vulnerable ? 'Vulnerable Demo' : 'Protected Demo';
  document.body.classList.toggle('demo-vulnerable', vulnerable);
  elements.securityModeToggle.setAttribute(
    'aria-label',
    vulnerable ? 'Disable vulnerable prompt injection demo' : 'Enable vulnerable prompt injection demo'
  );
}

async function loadSecurityMode() {
  try {
    const response = await fetch('/api/security-mode');
    if (!response.ok) throw new Error('Could not load security mode');
    const data = await response.json();
    applySecurityMode(data.mode);
  } catch {
    applySecurityMode('protected');
  }
}

async function changeSecurityMode() {
  const requestedMode = elements.securityModeToggle.checked ? 'protected' : 'vulnerable';
  elements.securityModeToggle.disabled = true;
  try {
    const response = await fetch('/api/security-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: requestedMode }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Could not change security mode');
    applySecurityMode(data.mode);
  } catch (error) {
    elements.securityModeToggle.checked = !elements.securityModeToggle.checked;
    showStatus(error.message, 'error', 'Security mode unchanged');
  } finally {
    elements.securityModeToggle.disabled = false;
  }
}

function switchView(view) {
  elements.readerEmpty.hidden = view !== 'empty';
  elements.emailReader.hidden = view !== 'reader';
  elements.composeView.hidden = view !== 'compose';
}

function renderEmails() {
  const unreadCount = state.emails.filter((email) => email.read_status === 'unread').length;
  elements.inboxCount.textContent = String(unreadCount);
  elements.inboxCount.hidden = state.folder !== 'inbox' || unreadCount === 0;
  elements.emailList.replaceChildren();
  elements.emptyList.hidden = state.emails.length > 0;
  elements.messageTotal.textContent = `${state.emails.length} ${state.emails.length === 1 ? 'message' : 'messages'}`;
  elements.listError.hidden = true;

  for (const [index, email] of state.emails.entries()) {
    const sender = state.folder === 'sent' ? `To ${email.recipient}` : senderDetails(email.sender).name;
    const row = document.createElement('button');
    row.type = 'button';
    row.className = `email-item${email.read_status === 'unread' ? ' is-unread' : ''}${email.email_id === state.selectedId ? ' is-selected' : ''}`;
    row.style.animationDelay = `${Math.min(index * 25, 175)}ms`;
    row.setAttribute('aria-label', `${sender}, ${email.subject}`);
    row.innerHTML = `
      <span class="unread-dot" aria-hidden="true"></span>
      <span class="email-item-copy">
        <span class="email-row-top"><span class="email-sender">${escapeHtml(sender)}</span><time class="email-date">${escapeHtml(formatDate(email.timestamp, true))}</time></span>
        <span class="email-subject">${escapeHtml(email.subject)}</span>
        <span class="email-snippet">${escapeHtml(email.body.replace(/\s+/g, ' ').slice(0, 100))}</span>
      </span>`;
    row.addEventListener('click', () => openEmail(email.email_id));
    elements.emailList.append(row);
  }
}

async function loadFolder(folder = state.folder) {
  state.folder = folder;
  state.selectedId = null;
  document.querySelectorAll('.folder-link').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.folder === folder);
  });
  elements.folderTitle.textContent = folder === 'inbox' ? 'Inbox' : 'Sent';
  elements.listEyebrow.textContent = folder === 'inbox' ? 'YOUR MAILBOX' : 'OUTGOING MAIL';
  switchView('empty');
  elements.messageTotal.textContent = 'Loading messages';
  elements.listError.hidden = true;

  try {
    const response = await fetch(`/api/mailbox/${folder}`);
    if (!response.ok) throw new Error((await response.json()).detail || 'Mailbox could not be loaded.');
    const data = await response.json();
    state.emails = data.emails;
    renderEmails();
  } catch (error) {
    state.emails = [];
    renderEmails();
    elements.emptyList.hidden = true;
    elements.listError.textContent = `${error.message} Start the Westbridge local server and try again.`;
    elements.listError.hidden = false;
    elements.messageTotal.textContent = 'Mailbox unavailable';
  }
}

async function openEmail(emailId) {
  try {
    const response = await fetch(`/api/emails/${emailId}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Message could not be opened.');
    const email = data.email;
    email.read_status = 'read';
    state.selectedId = email.email_id;
    const sender = senderDetails(email.sender);
    const destination = state.folder === 'sent' ? email.recipient : 'Kim Park';
    elements.emailReader.innerHTML = `
      <div class="reader-topline"><span class="reader-label">${state.folder === 'sent' ? 'Sent message' : 'Student correspondence'}</span><time class="reader-date">${escapeHtml(formatDate(email.timestamp))}</time></div>
      <h2 class="reader-subject">${escapeHtml(email.subject)}</h2>
      <div class="sender-line"><span class="sender-avatar">${escapeHtml((sender.name || 'WB').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase())}</span><span class="sender-meta"><span class="sender-name">${escapeHtml(sender.name)}</span><span class="sender-address">${escapeHtml(sender.address || email.sender)}</span></span><span class="reader-to">To ${escapeHtml(destination)}</span></div>
      <div class="reader-body">${escapeHtml(email.body)}</div>
      <div class="reader-footer">WESTBRIDGE UNIVERSITY · FICTIONAL STUDENT MAIL</div>`;
    switchView('reader');
    renderEmails();
  } catch (error) {
    showStatus(error.message, 'error', 'Message unavailable');
  }
}

function showCompose() {
  switchView('compose');
  elements.subject.focus();
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.busy) return;
  state.busy = true;
  elements.sendButton.disabled = true;
  resetActivity();
  showStatus('Email received', 'working');

  try {
    const response = await fetch('/api/emails', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        recipient: UNIVERSITY_ADDRESS,
        subject: elements.subject.value,
        body: elements.body.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Message could not be sent.');
    elements.form.reset();
    document.querySelector('#recipient').value = UNIVERSITY_ADDRESS;
    const activity = new EventSource(`/api/activity/${encodeURIComponent(data.job_id)}`);
    let finished = false;

    activity.onmessage = async (messageEvent) => {
      const update = JSON.parse(messageEvent.data);
      renderActivity(update);
      if (!update.done || finished) return;
      finished = true;
      activity.close();
      state.busy = false;
      elements.sendButton.disabled = false;

      window.setTimeout(async () => {
        hideStatus();
        await loadFolder('inbox');
        if (update.status === 'completed') {
          const reply = state.emails.find((email) =>
            email.email_id > data.sent_email.email_id &&
            email.sender.includes('security-agent@westbridge.example')
          );
          if (reply) await openEmail(reply.email_id);
        }
      }, update.status === 'completed' ? 1100 : 1700);
    };

    activity.onerror = () => {
      if (finished) return;
      finished = true;
      activity.close();
      state.busy = false;
      elements.sendButton.disabled = false;
      renderActivity({
        message: 'Activity connection interrupted',
        status: 'error',
        tool: null,
        done: true,
      });
      window.setTimeout(async () => {
        hideStatus();
        await loadFolder('inbox');
      }, 1700);
    };
  } catch (error) {
    await loadFolder('sent');
    showStatus(error.message, 'error', 'Message not processed');
    state.busy = false;
    elements.sendButton.disabled = false;
  }
}

document.querySelectorAll('.folder-link').forEach((button) => {
  button.addEventListener('click', () => loadFolder(button.dataset.folder));
});
elements.composeButton.addEventListener('click', showCompose);
elements.emptyCompose.addEventListener('click', showCompose);
elements.closeCompose.addEventListener('click', () => switchView('empty'));
elements.refreshButton.addEventListener('click', () => loadFolder());
elements.form.addEventListener('submit', sendMessage);
elements.statusDismiss.addEventListener('click', hideStatus);
elements.securityModeToggle.addEventListener('change', changeSecurityMode);

loadSecurityMode();
loadFolder('inbox');