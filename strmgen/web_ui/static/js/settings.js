const API_BASE = document.getElementById('settingsForm')?.dataset.apiBase;
const settingsForm = document.getElementById('settingsForm');
const submitButton = settingsForm?.querySelector('button[type="submit"]');

const boolFields = [
  'skip_stream_check', 'only_updated_streams', 'update_stream_link',
  'clean_output_dir', 'process_movies_groups', 'process_tv_series_groups',
  'process_groups_24_7', 'tmdb_download_images', 'tmdb_create_not_found',
  'check_tmdb_thresholds', 'write_nfo', 'write_nfo_only_if_not_exists',
  'update_tv_series_nfo', 'opensubtitles_download', 'enable_scheduled_task'
];

const numberFields = [
  'last_modified_days', 'batch_size', 'batch_delay_seconds',
  'concurrent_requests', 'tmdb_rate_limit', 'minimum_year',
  'minimum_tmdb_rating', 'minimum_tmdb_votes',
  'minimum_tmdb_popularity', 'scheduled_hour', 'scheduled_minute'
];

const arrayFields = [
  'movies_groups_raw', 'tv_series_groups_raw',
  'groups_24_7_raw', 'remove_strings_raw'
];

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function showMessage(msg, success = true) {
  const box = document.createElement('div');
  box.textContent = msg;
  box.className = success ? 'msg-success' : 'msg-error';
  box.style.cssText = `
    position: fixed; top: 0; left: 0; right: 0; padding: 10px;
    background: ${success ? '#4CAF50' : '#f44336'}; color: white;
    text-align: center; z-index: 1000; font-weight: bold;
  `;
  document.body.prepend(box);
  setTimeout(() => box.remove(), 4000);
}

async function loadSettings() {
  try {
    if (!API_BASE) throw new Error('API base not found');
    const res = await fetch(API_BASE);
    if (!res.ok) throw new Error(await res.text());
    const cfg = await res.json();

    // Plain values
    [
      'api_base', 'token_url', 'access', 'refresh', 'username', 'password',
      'stream_base_url', 'output_root', 'movie_year_regex', 'tv_series_episode_regex',
      'tmdb_api_key', 'tmdb_language', 'tmdb_image_size',
      'opensubtitles_app_name', 'opensubtitles_api_key',
      'opensubtitles_username', 'opensubtitles_password',
      'emby_api_url', 'emby_api_key', 'emby_movie_library_id'
    ].forEach(id => setVal(id, cfg[id] ?? ''));

    numberFields.forEach(id => setVal(id, cfg[id]));

    arrayFields.forEach(id => {
      const val = (cfg[id.replace('_raw', '')] || []).join(',');
      setVal(id, val);
    });

    boolFields.forEach(name => {
      const cb = document.querySelector(`input[type="checkbox"][name="${name}"]`);
      if (cb) cb.checked = !!cfg[name];
    });

  } catch (err) {
    console.error('Failed to load settings:', err);
    showMessage('Could not load settings', false);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadSettings();

  document.querySelectorAll('.collapsible-header').forEach(header => {
    header.addEventListener('click', () => {
      const group = header.closest('.settings-group');
      group?.classList.toggle('collapsed');
    });
  });

  document.querySelectorAll('.toggle-password').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.target);
      if (input) {
        const isHidden = input.type === 'password';
        input.type = isHidden ? 'text' : 'password';
        btn.textContent = isHidden ? 'Hide' : 'Show';
      }
    });
  });

  settingsForm?.addEventListener('submit', async e => {
    e.preventDefault();
    if (!API_BASE) return;

    const payload = {};

    // Load boolean checkboxes
    boolFields.forEach(name => {
      const cb = settingsForm.querySelector(`input[type="checkbox"][name="${name}"]`);
      payload[name] = cb ? cb.checked : false;
    });

    const data = new FormData(settingsForm);
    for (let [key, value] of data.entries()) {
      if (boolFields.includes(key)) continue;

      if (arrayFields.includes(key)) {
        const realKey = key.replace('_raw', '');
        payload[realKey] = value.split(',').map(s => s.trim()).filter(Boolean);
      } else if (numberFields.includes(key)) {
        const number = Number(value);
        if (isNaN(number)) {
          showMessage(`Invalid number for ${key}`, false);
          return;
        }
        payload[key] = number;
      } else {
        payload[key] = value;
      }
    }

    try {
      if (submitButton) submitButton.disabled = true;

      const res = await fetch(API_BASE, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(await res.text());

      showMessage('Settings saved successfully');
    } catch (err) {
      console.error('Save failed:', err);
      showMessage('Failed to save settings', false);
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  });
});