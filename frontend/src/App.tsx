import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Empty, Loading } from "./components/ui";
import Dashboard from "./pages/Dashboard";

// Chart-heavy pages are split out so the dashboard loads quickly.
const MatchAnalysis = lazy(() => import("./pages/MatchAnalysis"));
const Predictions = lazy(() => import("./pages/Predictions"));
const Teams = lazy(() => import("./pages/Teams"));
const Performance = lazy(() => import("./pages/Performance"));
const Settings = lazy(() => import("./pages/Settings"));
const Login = lazy(() => import("./pages/Login"));

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="match/:id" element={<MatchAnalysis />} />
            <Route path="predictions" element={<Predictions />} />
            <Route path="teams" element={<Teams />} />
            <Route path="performance" element={<Performance />} />
            <Route path="settings" element={<Settings />} />
            <Route path="login" element={<Login />} />
            <Route path="*" element={<Empty title="Page not found" />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
