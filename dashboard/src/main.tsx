import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App, type Api } from './App';
import { fetchHistory, fetchVerdicts } from './api';
import './styles.css';

// Set VITE_API_URL to the deployed API (the stack's ApiUrl output); the default is the local
// server from dev/local_api.py.
const apiUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8787';

const api: Api = {
  fetchVerdicts: (project, options) => fetchVerdicts(apiUrl, project, options),
  fetchHistory: (project, testId, options) => fetchHistory(apiUrl, project, testId, options),
};

// The project lives in the URL, so a link opens the dashboard on it.
const params = new URLSearchParams(window.location.search);

function rememberProject(project: string) {
  params.set('project', project);
  window.history.replaceState(null, '', `?${params}`);
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App
      api={api}
      initialProject={params.get('project') ?? undefined}
      onProjectChange={rememberProject}
    />
  </StrictMode>,
);
