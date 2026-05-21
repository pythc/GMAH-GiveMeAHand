import { App as AntApp } from 'antd';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import AppLayout from './layouts/AppLayout';
import Approvals from './pages/Approvals';
import Chat from './pages/Chat';
import Dashboard from './pages/Dashboard';
import Evaluation from './pages/Evaluation';
import Login from './pages/Login';
import Logs from './pages/Logs';
import Mcp from './pages/Mcp';
import Qq from './pages/Qq';
import Rag from './pages/Rag';
import Sessions from './pages/Sessions';
import Settings from './pages/Settings';

export default function App() {
  return (
    <AntApp>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="settings" element={<Settings />} />
            <Route path="chat" element={<Chat />} />
            <Route path="review" element={<Evaluation />} />
            <Route path="logs" element={<Logs />} />
            <Route path="sessions" element={<Sessions />} />
            <Route path="approvals" element={<Approvals />} />
            <Route path="rag" element={<Rag />} />
            <Route path="qq" element={<Qq />} />
            <Route path="mcp" element={<Mcp />} />
            <Route path="login" element={<Login />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AntApp>
  );
}
