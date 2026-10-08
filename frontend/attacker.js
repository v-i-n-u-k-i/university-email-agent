const attackerAccount = document.querySelector('#attacker-account');
const attackerAccountMenu = document.querySelector('#attacker-account-menu');
const switchToKim = document.querySelector('#switch-to-kim');

const state = {
  emails: [],
};

const elements = {
  emailList: document.querySelector('#attacker-email-list'),
  emptyList: document.querySelector('#attacker-empty-list'),
  readerEmpty: document.querySelector('#attacker-reader-empty'),
  emailReader: document.querySelector('#attacker-email-reader'),
};

attackerAccount.addEventListener('click', (event) => {
  event.stopPropagation();

  const isOpen = !attackerAccountMenu.hidden;

  attackerAccountMenu.hidden = isOpen;
});

switchToKim.addEventListener('click', () => {
  window.location.href = '/';
});

document.addEventListener('click', (event) => {
  if (
    !attackerAccountMenu.hidden &&
    !attackerAccountMenu.contains(event.target) &&
    !attackerAccount.contains(event.target)
  ) {
    attackerAccountMenu.hidden = true;
  }
});

function openAttackerEmail(emailId) {
    console.log('Opening email:', emailId);
  const email = state.emails.find(
    (item) => item.email_id === emailId
  );

  if (!email) {
    console.error('Email not found:', emailId);
    return;
  }

  elements.readerEmpty.hidden = true;
  elements.emailReader.hidden = false;

  elements.emailReader.innerHTML = `
    <div class="attacker-reader-header">
      <p class="attacker-eyebrow">MESSAGE</p>

      <h2>${escapeHtml(email.subject)}</h2>

      <div class="attacker-reader-meta">
        <div>
          <strong>From:</strong>
          ${escapeHtml(email.sender)}
        </div>

        <div>
          <strong>To:</strong>
          ${escapeHtml(email.recipient)}
        </div>

        <div>
          <strong>Date:</strong>
          ${escapeHtml(email.timestamp)}
        </div>
      </div>
    </div>

    <div class="attacker-reader-body">
      ${escapeHtml(email.body).replace(/\n/g, '<br>')}
    </div>
  `;
}

async function loadAttackerMailbox() {
  try {
    const response = await fetch('/api/mailbox/attacker');

    if (!response.ok) {
      throw new Error('Attacker mailbox could not be loaded.');
    }

    const data = await response.json();

    state.emails = data.emails;

    renderAttackerEmails();
  } catch (error) {
    console.error('Could not load attacker mailbox:', error);
  }
}

function renderAttackerEmails() {
  elements.emailList.replaceChildren();

  elements.emptyList.hidden = state.emails.length > 0;

  for (const email of state.emails) {
    const row = document.createElement('button');

    row.type = 'button';

    row.className = `attacker-email-item${
      email.read_status === 'unread' ? ' is-unread' : ''
    }`;

    row.innerHTML = `
      <div class="attacker-email-copy">
        <div class="attacker-email-top">
          <span>${escapeHtml(email.sender)}</span>
          <time>${escapeHtml(email.timestamp)}</time>
        </div>

        <strong>${escapeHtml(email.subject)}</strong>

        <span class="attacker-email-preview">
          ${escapeHtml(email.body.replace(/\\n/g, ' ').replace(/\s+/g, ' ').slice(0, 120))}
        </span>
      </div>
    `;
    row.addEventListener('click', () => {
    console.log('CLICKED EMAIL:', email.email_id);
    openAttackerEmail(email.email_id);
    });

    elements.emailList.append(row);
  }
}

function escapeHtml(value) {
  const element = document.createElement('div');
  element.textContent = value;
  return element.innerHTML;
}

loadAttackerMailbox();