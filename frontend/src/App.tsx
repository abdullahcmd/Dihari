import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Skeleton, TabBar } from "./components/ui";
import { useI18n } from "./i18n";
import { FirstRun, Login, ProfileForm } from "./pages/Onboarding";
import PostJob from "./pages/PostJob";
import { JobDetail, MyJobs } from "./pages/Hirer";
import { Counter, Jobs, Me, MyWork } from "./pages/Worker";
import { useSession } from "./session";
import { useEffect, useState } from "react";

function OfflineBanner() {
  const { t } = useI18n();
  const [off, setOff] = useState(!navigator.onLine);
  useEffect(() => { const a = () => setOff(true), b = () => setOff(false); window.addEventListener("offline", a); window.addEventListener("online", b); return () => { window.removeEventListener("offline", a); window.removeEventListener("online", b); }; }, []);
  return off ? <p role="status" className="bg-yellow-300 text-black text-center font-bold p-2">{t("ui.offline")}</p> : null;
}

export default function App() {
  const { ready, t } = useI18n();
  const { me, loading, role } = useSession();
  const nav = useNavigate();
  if (!ready || loading) return <Skeleton />;
  if (!me) return role ? <Login /> : <FirstRun />;
  const p = me.profile;
  const needsSetup = me.role === "worker" ? !p || !p.trades?.length || !p.area_name : !p;
  if (needsSetup) return <ProfileForm onSaved={() => nav("/")} />;
  return (
    <>
      <OfflineBanner />
      {me.role === "hirer" ? (
        <>
          <Routes>
            <Route path="/" element={<PostJob />} />
            <Route path="/jobs-mine" element={<MyJobs />} />
            <Route path="/jobs-mine/:id" element={<JobDetail />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
          <TabBar tabs={[{ to: "/", icon: "🎤", label: t("ui.tab.post") }, { to: "/jobs-mine", icon: "📋", label: t("ui.tab.myjobs") }]} />
        </>
      ) : (
        <>
          <Routes>
            <Route path="/" element={<Jobs />} />
            <Route path="/counter/:id" element={<Counter />} />
            <Route path="/work" element={<MyWork />} />
            <Route path="/me" element={<Me />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
          <TabBar tabs={[{ to: "/", icon: "🔍", label: t("ui.tab.jobs") }, { to: "/work", icon: "🛠️", label: t("ui.tab.mywork") }, { to: "/me", icon: "👤", label: t("ui.tab.me") }]} />
        </>
      )}
    </>
  );
}
