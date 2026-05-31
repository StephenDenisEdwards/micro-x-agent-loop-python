import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { installMockWsForE2E } from './test/e2e-mock-bootstrap';
import './styles/global.css';

if (import.meta.env.VITE_E2E_MOCK_WS === '1') {
  installMockWsForE2E();
}

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('Missing #root element');

createRoot(rootEl).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
